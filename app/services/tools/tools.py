from crewai_tools import SerperDevTool
from crewai.tools import tool
from dotenv import load_dotenv
import os
import json
import requests
from bs4 import BeautifulSoup
from typing import Generator, List, Dict, Tuple, Optional
import asyncio
import time
from datetime import datetime, timedelta
import PyPDF2
import traceback
from app.schemas.interview import AllSkillSources, AllInterviewQuestions, Source, InterviewQuestions, SkillSources

load_dotenv()

# Import LLM locally to avoid circular imports
def get_llm(model: str, temperature: float = 0.1, api_key: str | None = None):
    """Get LLM instance locally to avoid circular imports"""
    from crewai import LLM
    return LLM(model=model, temperature=temperature, api_key=api_key)


# ============================================================================
# RATE LIMITING & QUOTA MANAGEMENT
# ============================================================================

class RateLimiter:
    """Manages API rate limiting and quota tracking"""
    def __init__(self, requests_per_minute: int = 10):
        self.requests_per_minute = requests_per_minute
        self.request_times: List[datetime] = []
        self.quota_exhausted_until: Optional[datetime] = None
        
    def wait_if_needed(self):
        """Wait if we've hit rate limits"""
        now = datetime.now()
        
        # If quota is exhausted, wait until it resets
        if self.quota_exhausted_until and now < self.quota_exhausted_until:
            wait_seconds = (self.quota_exhausted_until - now).total_seconds()
            print(f"⏳ Quota exhausted. Waiting {wait_seconds:.0f}s before retry...")
            time.sleep(wait_seconds + 1)
            self.quota_exhausted_until = None
            self.request_times = []
            return
        
        # Remove requests older than 1 minute
        cutoff_time = now - timedelta(minutes=1)
        self.request_times = [t for t in self.request_times if t > cutoff_time]
        
        # If we've made too many requests, wait
        if len(self.request_times) >= self.requests_per_minute:
            oldest_request = self.request_times[0]
            wait_time = (oldest_request + timedelta(minutes=1) - now).total_seconds()
            if wait_time > 0:
                print(f" Rate limit approaching. Waiting {wait_time:.1f}s...")
                time.sleep(wait_time)
                self.request_times = []
    
    def mark_quota_exhausted(self, retry_after_seconds: int = 60):
        """Mark that quota is exhausted; will retry after specified seconds"""
        self.quota_exhausted_until = datetime.now() + timedelta(seconds=retry_after_seconds)
        self.request_times = []
    
    def record_request(self):
        """Record that a request was made"""
        self.request_times.append(datetime.now())


# Global rate limiter for search requests (conservative: 10 per minute)
search_rate_limiter = RateLimiter(requests_per_minute=10)

# ============================================================================
# SESSION CACHE FOR OPTIMIZATION
# ============================================================================

# Global cache for URL searches - stores search results as strings
SEARCH_CACHE: Dict[str, str] = {}

# Initialize LLMs using CrewAI's unified LLM class
# 1. Gemini Flash - FREE tier (content extraction)
llm_gemini_flash = get_llm("gemini/gemini-2.5-flash", 
                           temperature=0.1,
                           api_key=os.environ.get("GOOGLE_API_KEY") or None)

# 2. Groq Llama - COMPLETELY FREE (skill extraction)
llm_groq = get_llm(
    "groq/openai/gpt-oss-120b",
    temperature=0.0,
    api_key=os.environ.get("GROQ_API_KEY") or None
)

# 3. DeepSeek via OpenRouter - VERY CHEAP/FREE tier (question generation)
llm_openrouter = get_llm(
    "openrouter/deepseek/deepseek-chat",
    temperature=0.7,
    api_key=os.environ.get("OPENROUTER_API_KEY") or None
)


@tool
def file_text_extractor(file_path: str) -> str:
    """Extracts all text content from a PDF file. Returns the extracted text."""
    print(f"DEBUG: file_text_extractor received file_path: {file_path}")
    try:
        # Check if it's a PDF file
        _, file_extension = os.path.splitext(file_path)
        file_extension = file_extension.lower()
        
        if file_extension != ".pdf":
            print(f"DEBUG: Unsupported file type: {file_extension}")
            return f"Unsupported file type: {file_extension}. Only PDF files are supported."
        
        # Extract PDF content
        with open(file_path, 'rb') as file:
            reader = PyPDF2.PdfReader(file)
            text = "".join(page.extract_text() for page in reader.pages)
            print(f"DEBUG: Extracted text length: {len(text)}")
            return text if text else "Error: No text could be extracted from the PDF."
    except FileNotFoundError:
        print(f"DEBUG: FileNotFoundError in file_text_extractor for path: {file_path}")
        return f"Error: The file at {file_path} was not found."
    except Exception as e:
        print(f"DEBUG: An unexpected error occurred in file_text_extractor: {e}")
        traceback.print_exc()
        return f"An error occurred while reading the PDF: {e}"



# SerperDevTool internally expects 'search_query' but agents may pass 'query'
_serper_tool = SerperDevTool()  # type: ignore

@tool
def google_search_tool(search_query: str) -> str:
    """Performs a Google search for a given query and returns relevant snippets and URLs. 
    Includes retry logic and rate limiting to handle quota exhaustion.
    Optimizes queries for high-quality results.
    Pass the search query as the search_query parameter."""
    
    max_retries = 3
    retry_delay = 2
    
    # Optimize search query for better quality results
    optimized_query = _optimize_search_query(search_query)
    
    # Check cache first to avoid unnecessary API calls
    cache_key = f"search:{optimized_query.lower()}"
    if cache_key in SEARCH_CACHE:
        print(f"✓ Cache hit for '{search_query}'")
        return SEARCH_CACHE[cache_key]
    
    for attempt in range(max_retries):
        try:
            # Apply rate limiting before making request
            search_rate_limiter.wait_if_needed()
            
            print(f" Searching: '{optimized_query}' (Attempt {attempt + 1}/{max_retries})")
            
            # Call the underlying SerperDevTool with the correct parameter name
            result = _serper_tool.run(search_query=optimized_query)  # type: ignore
            result_str = str(result) if result else "No results found"
            
            # Debug output to understand the response format
            print(f"DEBUG: Search result type: {type(result)}")
            print(f"DEBUG: Search result (first 500 chars): {str(result)[:500] if result else 'None'}")
            
            # Parse and reformat the result to match AllSkillSources schema
            parsed_serper_result = json.loads(result_str)
            
            skill_sources = []
            if "organic" in parsed_serper_result:
                for item in parsed_serper_result["organic"]:
                    if "link" in item and "title" in item:
                        skill_sources.append(Source(uri=item["link"], title=item["title"]))
            
            formatted_result = AllSkillSources(all_sources=[SkillSources(skill=search_query, sources=skill_sources)]).json()
            
            # Cache successful results
            SEARCH_CACHE[cache_key] = formatted_result
            search_rate_limiter.record_request()
            
            return formatted_result
            
        except Exception as e:
            error_msg = str(e)
            
            # Handle 429 (quota exhausted) with exponential backoff
            if "429" in error_msg or "quota" in error_msg.lower() or "exhausted" in error_msg.lower():
                retry_after = min(60 * (2 ** attempt), 300)  # Max 5 minutes
                search_rate_limiter.mark_quota_exhausted(retry_after_seconds=retry_after)
                
                if attempt < max_retries - 1:
                    print(f" Rate limit hit. Retrying in {retry_after}s...")
                    time.sleep(retry_after)
                    continue
                else:
                    print(f" Quota exhausted after {max_retries} attempts. Using fallback.")
                    return _generate_fallback_results(search_query)
            
            # Handle other errors with regular retry
            elif attempt < max_retries - 1:
                print(f" Error on attempt {attempt + 1}: {e}")
                print(f"   Retrying in {retry_delay}s...")
                time.sleep(retry_delay)
                retry_delay *= 2
                continue
            else:
                print(f" Failed after {max_retries} attempts: {e}")
                return _generate_fallback_results(search_query)
    
    return "No results available"


def _optimize_search_query(skill: str) -> str:
    """
    Generate a single, effective Google-style search query focused on
    technical interview questions for the given skill, excluding video sites.
    Returns a query that balances specificity with broad enough results.
    """

    skill = skill.strip().lower()

    # Core phrase - simple and direct
    base = f'{skill} interview questions'


    # Exclude video sites - simplified to avoid over-constraining the search
    exclude = "-youtube -vimeo"

    # Build a balanced query - make it less restrictive
    query = f'{base}  {exclude}'

    return query





def _generate_fallback_results(search_query: str) -> str:
    """Generate fallback results when API is exhausted"""
    print(f" Generating fallback results for '{search_query}'...")
    
    # Fallback should also conform to AllSkillSources schema
    fallback_sources = [
        Source(uri=f"https://en.wikipedia.org/wiki/{search_query.replace(' ', '_')}", title=f"Wikipedia: {search_query}").dict(),
        Source(uri=f"https://www.tutorialspoint.com/tutoriallist.htm?keyword={search_query.replace(' ', '_')}", title=f"TutorialsPoint: {search_query}").dict()
    ]
    
    fallback_data = AllSkillSources(all_sources=[SkillSources(skill=search_query, sources=fallback_sources)]).json()
    
    return fallback_data


@tool
def smart_web_content_extractor(search_query: str, urls: Optional[List[str]] = None) -> str:
    """Extracts relevant, contextual content from a list of URLs based on a specific query. 
    Returns a combined string of the most useful information.
    Efficiently handles 5-8 URLs without overwhelming the LLM.
    
    Args:
        search_query: The query/skill to search for in the content
        urls: Optional list of URLs to extract from. If not provided, will return empty.
    
    Returns:
        Combined string of extracted content from all URLs.
    """
    if urls is None or not urls:
        return "No URLs provided for content extraction."
    
    # Parse the AllSkillSources JSON string
    all_skill_sources: AllSkillSources
    try:
        parsed_data = json.loads(str(urls))
        all_skill_sources = AllSkillSources(**parsed_data)
    except (json.JSONDecodeError, ValueError) as e:
        print(f"Error parsing AllSkillSources in smart_web_content_extractor: {e}")
        return f"Error: Invalid URL list format provided for content extraction: {e}"

    urls_to_extract: List[str] = []
    for skill_source_item in all_skill_sources.all_sources:
        for source in skill_source_item.sources:
            urls_to_extract.append(source.uri)
            
    # Limit to 8 URLs max to avoid overwhelming the LLM
    urls_to_extract = urls_to_extract[:8]
    
    combined_content = []
    successful_extractions = 0
    
    print(f" Extracting content from {len(urls_to_extract)} URLs...")
    
    for idx, url in enumerate(urls_to_extract, 1):
        try:
            url = str(url).strip()
            if not url.startswith('http'):
                continue
            
            print(f"   [{idx}/{len(urls_to_extract)}] Processing: {url[:60]}...")
            
            response = requests.get(url, timeout=15)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # A more robust way to get text
            text_content = ' '.join(soup.stripped_strings)

            if not text_content or len(text_content) < 100:
                print(f" Minimal content found")
                continue

            # Use LLM to extract relevant info - be concise to save tokens
            prompt = f"""From the following web page content, extract ONLY the most relevant information about "{search_query}".
            Be concise and focus on key concepts, definitions, and practical insights.
            Limit your response to 200 words maximum.

            Web Page Content (first 6000 chars):
            \"\"\"{text_content[:6000]}\"\"\"

            Return only the extracted information, no introductions or explanations.
            """
            
            llm_response = llm_gemini_flash.call(messages=[{"role": "user", "content": prompt}])
            
            if llm_response and len(str(llm_response)) > 20:
                combined_content.append(f" Source: {url}\n{llm_response}\n")
                successful_extractions += 1
                print(f"      ✓ Content extracted ({len(str(llm_response))} chars)")
            else:
                print(f"      ✗ No relevant content extracted")

        except requests.exceptions.Timeout:
            print(f" ✗ Timeout (>15s)")
        except requests.exceptions.RequestException as e:
            print(f" ✗ Request error: {str(e)[:50]}")
        except Exception as e:
            print(f"✗ Error: {str(e)[:50]}")
    
    if not combined_content:
        return f" Could not extract content from {len(urls_to_extract)} URLs. They may not contain relevant information about '{search_query}'."
    
    result = f"Successfully extracted content from {successful_extractions} sources:\n\n" + "\n".join(combined_content)
    print(f" Extraction complete: {successful_extractions}/{len(urls_to_extract)} sources processed")
    
    return result

@tool
def question_generator(skill: str, sources_content: str) -> str:
    """Generates insightful, non-coding interview questions based on provided skill and source content using OpenRouter. Returns a JSON string of AllInterviewQuestions."""
    try:
        prompt = f"""Your task is to act as an expert technical interviewer.
        Based ONLY on the combined information from the Context provided below,
        generate a list of insightful, non-coding interview questions for a candidate skilled in "{skill}".

        Context:
        {sources_content}

        VERY IMPORTANT: Your entire response must be a single, valid JSON object.
        Do not include any text, explanation, or markdown formatting before or after the JSON object.
        The JSON object must have a single key "questions" which is an array of unique question strings.
        """
        llm_response = llm_openrouter.call(messages=[{"role": "user", "content": prompt}])
        
        # Parse the LLM response to extract questions
        questions_data = json.loads(str(llm_response))
        questions_list = questions_data.get("questions", [])
        
        # Format the output to match AllInterviewQuestions schema
        interview_questions_obj = InterviewQuestions(skill=skill, questions=questions_list)
        all_interview_questions = AllInterviewQuestions(all_questions=[interview_questions_obj])
        
        return all_interview_questions.json()
    except Exception as e:
        return f"Error generating questions: {e}"
