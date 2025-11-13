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

load_dotenv()

# CrewAI requires OPENAI_API_KEY even if we don't use OpenAI
# This is a known limitation, so we set a placeholder if not configured
if not os.environ.get("OPENAI_API_KEY"):
    os.environ["OPENAI_API_KEY"] = "sk-placeholder-crewai-requirement"

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
                print(f"⏳ Rate limit approaching. Waiting {wait_time:.1f}s...")
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
llm_gemini_flash = get_llm("gemini/gemini-2.5-flash", temperature=0.1)

# 2. Groq Llama - COMPLETELY FREE (skill extraction)
llm_groq = get_llm(
    "groq/openai/gpt-oss-120b",
    temperature=0.2,
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
    try:
        # Check if it's a PDF file
        _, file_extension = os.path.splitext(file_path)
        file_extension = file_extension.lower()
        
        if file_extension != ".pdf":
            return f"Unsupported file type: {file_extension}. Only PDF files are supported."
        
        # Extract PDF content
        with open(file_path, "rb") as file:
            reader = PyPDF2.PdfReader(file)  # type: ignore
            text_content = ""
            
            for page_num in range(len(reader.pages)):
                page_text = reader.pages[page_num].extract_text()
                if page_text:
                    text_content += page_text + "\n"
            
            if not text_content.strip():
                return "Could not extract any text from the provided PDF file."
            
            return text_content
            
    except Exception as e:
        return f"Error extracting text from PDF file: {e}"


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
            
            print(f"🔍 Searching: '{optimized_query}' (Attempt {attempt + 1}/{max_retries})")
            
            # Call the underlying SerperDevTool with the correct parameter name
            result = _serper_tool.run(search_query=optimized_query)  # type: ignore
            result_str = str(result) if result else "No results found"
            
            # Debug output to understand the response format
            print(f"DEBUG: Search result type: {type(result)}")
            print(f"DEBUG: Search result (first 500 chars): {str(result)[:500] if result else 'None'}")
            
            # Cache successful results
            SEARCH_CACHE[cache_key] = result_str
            search_rate_limiter.record_request()
            
            return result_str
            
        except Exception as e:
            error_msg = str(e)
            
            # Handle 429 (quota exhausted) with exponential backoff
            if "429" in error_msg or "quota" in error_msg.lower() or "exhausted" in error_msg.lower():
                retry_after = min(60 * (2 ** attempt), 300)  # Max 5 minutes
                search_rate_limiter.mark_quota_exhausted(retry_after_seconds=retry_after)
                
                if attempt < max_retries - 1:
                    print(f"⚠️  Rate limit hit. Retrying in {retry_after}s...")
                    time.sleep(retry_after)
                    continue
                else:
                    print(f"❌ Quota exhausted after {max_retries} attempts. Using fallback.")
                    return _generate_fallback_results(search_query)
            
            # Handle other errors with regular retry
            elif attempt < max_retries - 1:
                print(f"⚠️  Error on attempt {attempt + 1}: {e}")
                print(f"   Retrying in {retry_delay}s...")
                time.sleep(retry_delay)
                retry_delay *= 2
                continue
            else:
                print(f"❌ Failed after {max_retries} attempts: {e}")
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
    print(f"📌 Generating fallback results for '{search_query}'...")
    
    fallback_data = {
        "searchResults": [
            {
                "title": f"Information about {search_query}",
                "link": f"https://en.wikipedia.org/wiki/{search_query.replace(' ', '_')}",
                "snippet": f"Wikipedia article about {search_query}. This is a fallback when search quota is exhausted."
            },
            {
                "title": f"Learn {search_query}",
                "link": f"https://www.tutorialspoint.com/tutoriallist.htm?keyword={search_query.replace(' ', '_')}",
                "snippet": f"TutorialsPoint tutorials on {search_query}. Available when search is unavailable."
            }
        ]
    }
    
    return json.dumps(fallback_data)


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
    
    # Ensure urls is always a list
    urls_list: List[str] = []
    if not isinstance(urls, list):
        # Try to parse if it's a JSON string
        try:
            parsed_urls = json.loads(str(urls))
            if isinstance(parsed_urls, dict) and 'links' in parsed_urls:
                urls_list = parsed_urls['links']
            elif isinstance(parsed_urls, dict) and 'link' in parsed_urls:
                urls_list = [parsed_urls['link']]
            elif isinstance(parsed_urls, list):
                urls_list = parsed_urls
            else:
                urls_list = [str(parsed_urls)]
        except json.JSONDecodeError:
            urls_list = [str(urls)]
    else:
        urls_list = urls
    
    # Limit to 8 URLs max to avoid overwhelming the LLM
    urls_list = urls_list[:8]
    
    combined_content = []
    successful_extractions = 0
    
    print(f"📄 Extracting content from {len(urls_list)} URLs...")
    
    for idx, url in enumerate(urls_list, 1):
        try:
            # Handle dict entries
            if isinstance(url, dict):
                url = url.get('link') or url.get('url') or url.get('href')
                if not url:
                    continue
            
            url = str(url).strip()
            if not url.startswith('http'):
                continue
            
            print(f"   [{idx}/{len(urls_list)}] Processing: {url[:60]}...")
            
            response = requests.get(url, timeout=15)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # A more robust way to get text
            text_content = ' '.join(soup.stripped_strings)

            if not text_content or len(text_content) < 100:
                print(f"      ⚠️  Minimal content found")
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
                combined_content.append(f"📌 Source: {url}\n{llm_response}\n")
                successful_extractions += 1
                print(f"      ✓ Content extracted ({len(str(llm_response))} chars)")
            else:
                print(f"      ✗ No relevant content extracted")

        except requests.exceptions.Timeout:
            print(f"      ✗ Timeout (>15s)")
        except requests.exceptions.RequestException as e:
            print(f"      ✗ Request error: {str(e)[:50]}")
        except Exception as e:
            print(f"      ✗ Error: {str(e)[:50]}")
    
    if not combined_content:
        return f"⚠️  Could not extract content from {len(urls_list)} URLs. They may not contain relevant information about '{search_query}'."
    
    result = f"✓ Successfully extracted content from {successful_extractions} sources:\n\n" + "\n".join(combined_content)
    print(f"\n✓ Extraction complete: {successful_extractions}/{len(urls_list)} sources processed")
    
    return result

@tool
def question_generator(skill: str, sources_content: str) -> str:
    """Generates insightful, non-coding interview questions based on provided skill and source content using OpenRouter. Returns a JSON string of questions."""
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
        response = llm_openrouter.call(messages=[{"role": "user", "content": prompt}])
        return str(response) if response else ""
    except Exception as e:
        return f"Error generating questions: {e}"

