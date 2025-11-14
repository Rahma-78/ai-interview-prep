from __future__ import annotations # Added for postponed evaluation of type annotations
import asyncio
import json
import logging
import os
import time
import traceback
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional

import httpx # Import httpx for async requests
import PyPDF2
from bs4 import BeautifulSoup
from crewai.tools import tool
from crewai_tools import SerperDevTool
from dotenv import load_dotenv

load_dotenv() # Load environment variables from .env file

from app.schemas.interview import (
    AllInterviewQuestions,
    AllSkillSources,
    InterviewQuestions,
    SkillSources,
    Source,
)
from app.core.config import settings

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Import LLM locally to avoid circular imports
def get_llm(model: str, temperature: float = 0.1, api_key: str | None = None):
    """
    Retrieves an LLM instance from CrewAI, avoiding circular imports.

    Args:
        model (str): The name of the LLM model to use.
        temperature (float): The temperature setting for the LLM (default: 0.1).
        api_key (str | None): The API key for the LLM service (default: None).

    Returns:
        LLM: An instance of the CrewAI LLM.
    """
    from crewai import LLM
    return LLM(model=model, temperature=temperature, api_key=api_key)


# ============================================================================
# RATE LIMITING & QUOTA MANAGEMENT
# ============================================================================

class RateLimiter:
    """
    Manages API rate limiting and quota tracking for external services.
    Ensures that API calls do not exceed the specified requests per minute.
    """
    def __init__(self, requests_per_minute: int = 10):
        """
        Initializes the RateLimiter with a specified rate limit.

        Args:
            requests_per_minute (int): The maximum number of requests allowed per minute.
        """
        self.requests_per_minute = requests_per_minute
        self.request_times: List[datetime] = []
        self.quota_exhausted_until: Optional[datetime] = None
        
    def wait_if_needed(self):
        """
        Pauses execution if the rate limit has been hit or the quota is exhausted.
        """
        now = datetime.now()
        
        if self.quota_exhausted_until and now < self.quota_exhausted_until:
            wait_seconds = (self.quota_exhausted_until - now).total_seconds()
            logging.info(f"⏳ Quota exhausted. Waiting {wait_seconds:.0f}s before retry...")
            time.sleep(wait_seconds + 1)
            self.quota_exhausted_until = None
            self.request_times = []
            return
        
        cutoff_time = now - timedelta(minutes=1)
        self.request_times = [t for t in self.request_times if t > cutoff_time]
        
        if len(self.request_times) >= self.requests_per_minute:
            oldest_request = self.request_times[0]
            wait_time = (oldest_request + timedelta(minutes=1) - now).total_seconds()
            if wait_time > 0:
                logging.info(f" Rate limit approaching. Waiting {wait_time:.1f}s...")
                time.sleep(wait_time)
                self.request_times = []
    
    def mark_quota_exhausted(self, retry_after_seconds: int = 60):
        """
        Marks the API quota as exhausted, setting a time until which no new requests should be made.

        Args:
            retry_after_seconds (int): The number of seconds to wait before retrying.
        """
        self.quota_exhausted_until = datetime.now() + timedelta(seconds=retry_after_seconds)
        self.request_times = []
    
    def record_request(self):
        """
        Records the time a request was made to track rate limits.
        """
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
                           api_key=settings.GEMINI_API_KEY)

# 2. Groq Llama - COMPLETELY FREE (skill extraction)
llm_groq = get_llm(
    "groq/openai/gpt-oss-120b",
    temperature=0.0,
    api_key=settings.GROQ_API_KEY
)

# 3. DeepSeek via OpenRouter - VERY CHEAP/FREE tier (question generation)
llm_openrouter = get_llm(
    "openrouter/deepseek/deepseek-chat",
    temperature=0.7,
    api_key=settings.OPENROUTER_API_KEY
)


@tool
def file_text_extractor(file_path: str) -> str:
    """
    Extracts all text content from a PDF file.

    Args:
        file_path (str): The path to the PDF file.

    Returns:
        str: The extracted text content from the PDF, or an error message if extraction fails.
    """
    logging.debug(f"file_text_extractor received file_path: {file_path}")
    try:
        _, file_extension = os.path.splitext(file_path)
        file_extension = file_extension.lower()
        
        if file_extension != ".pdf":
            logging.debug(f"Unsupported file type: {file_extension}")
            return f"Unsupported file type: {file_extension}. Only PDF files are supported."
        
        with open(file_path, 'rb') as file:
            reader = PyPDF2.PdfReader(file)
            text = "".join(page.extract_text() for page in reader.pages)
            logging.debug(f"Extracted text length: {len(text)}")
            return text if text else "Error: No text could be extracted from the PDF."
    except FileNotFoundError:
        logging.error(f"FileNotFoundError in file_text_extractor for path: {file_path}")
        return f"Error: The file at {file_path} was not found."
    except Exception as e:
        logging.error(f"An unexpected error occurred in file_text_extractor: {e}", exc_info=True)
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
        logging.info(f"✓ Cache hit for '{search_query}'")
        return SEARCH_CACHE[cache_key]
    
    for attempt in range(max_retries):
        try:
            # Apply rate limiting before making request
            search_rate_limiter.wait_if_needed()
            
            logging.info(f" Searching: '{optimized_query}' (Attempt {attempt + 1}/{max_retries})")
            
            # Call the underlying SerperDevTool with the correct parameter name
            result = _serper_tool.run(search_query=optimized_query)  # type: ignore
            result_str = str(result) if result else "No results found"
            
            logging.debug(f"Search result type: {type(result)}")
            logging.debug(f"Search result (first 500 chars): {str(result)[:500] if result else 'None'}")
            
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
            
            if "429" in error_msg or "quota" in error_msg.lower() or "exhausted" in error_msg.lower():
                retry_after = min(60 * (2 ** attempt), 300)
                search_rate_limiter.mark_quota_exhausted(retry_after_seconds=retry_after)
                
                if attempt < max_retries - 1:
                    logging.warning(f" Rate limit hit. Retrying in {retry_after}s...")
                    time.sleep(retry_after)
                    continue
                else:
                    logging.error(f" Quota exhausted after {max_retries} attempts. Using fallback.")
                    return _generate_fallback_results(search_query)
            
            elif attempt < max_retries - 1:
                logging.warning(f" Error on attempt {attempt + 1}: {e}")
                logging.info(f"   Retrying in {retry_delay}s...")
                time.sleep(retry_delay)
                retry_delay *= 2
                continue
            else:
                logging.error(f" Failed after {max_retries} attempts: {e}", exc_info=True)
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
    """
    Generates fallback results when the search API quota is exhausted.

    Args:
        search_query (str): The original search query.

    Returns:
        str: A JSON string conforming to the AllSkillSources schema with fallback URLs.
    """
    logging.info(f" Generating fallback results for '{search_query}'...")
    
    fallback_sources = [
        Source(uri=f"https://en.wikipedia.org/wiki/{search_query.replace(' ', '_')}", title=f"Wikipedia: {search_query}"),
        Source(uri=f"https://www.tutorialspoint.com/tutoriallist.htm?keyword={search_query.replace(' ', '_')}", title=f"TutorialsPoint: {search_query}")
    ]
    
    fallback_data = AllSkillSources(all_sources=[SkillSources(skill=search_query, sources=fallback_sources)]).json()
    
    return fallback_data


@tool
async def smart_web_content_extractor(search_query: str, urls: Optional[List[str]] = None) -> str:
    """
    Extracts relevant, contextual content from a list of URLs based on a specific query.
    Returns a combined string of the most useful information.
    Efficiently handles multiple URLs concurrently using asynchronous requests.
    
    Args:
        search_query: The query/skill to search for in the content.
        urls: Optional list of URLs to extract from. If not provided, will return empty.
    
    Returns:
        Combined string of extracted content from all URLs.
    """
    if urls is None or not urls:
        return "No URLs provided for content extraction."
    
    all_skill_sources: AllSkillSources
    try:
        parsed_data = json.loads(str(urls))
        all_skill_sources = AllSkillSources(**parsed_data)
    except (json.JSONDecodeError, ValueError) as e:
        logging.error(f"Error parsing AllSkillSources in smart_web_content_extractor: {e}", exc_info=True)
        return f"Error: Invalid URL list format provided for content extraction: {e}"

    urls_to_extract: List[str] = []
    for skill_source_item in all_skill_sources.all_sources:
        for source in skill_source_item.sources:
            urls_to_extract.append(source.uri)
            
    urls_to_extract = urls_to_extract[:8] # Limit to 8 URLs max
    
    combined_content = []
    successful_extractions = 0
    
    logging.info(f" Extracting content from {len(urls_to_extract)} URLs concurrently...")

    async def fetch_and_process_url(url: str, idx: int) -> Optional[str]:
        if not url.startswith('http'):
            return None
        
        logging.info(f"   [{idx}/{len(urls_to_extract)}] Processing: {url[:60]}...")
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, timeout=15)
                response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            text_content = ' '.join(soup.stripped_strings)

            if not text_content or len(text_content) < 100:
                logging.info(f" Minimal content found for {url}")
                return None

            prompt = f"""From the following web page content, extract ONLY the most relevant information about "{search_query}".
            Be concise and focus on key concepts, definitions, and practical insights.
            Limit your response to 200 words maximum.

            Web Page Content (first 6000 chars):
            \"\"\"{text_content[:6000]}\"\"\"

            Return only the extracted information, no introductions or explanations.
            """
            
            llm_response = llm_gemini_flash.call(messages=[{"role": "user", "content": prompt}])
            
            if llm_response and len(str(llm_response)) > 20:
                logging.info(f"      ✓ Content extracted ({len(str(llm_response))} chars) from {url}")
                return f" Source: {url}\n{llm_response}\n"
            else:
                logging.info(f"      ✗ No relevant content extracted from {url}")
                return None

        except httpx.TimeoutException:
            logging.warning(f" ✗ Timeout (>15s) for {url}")
            return None
        except httpx.RequestError as e:
            logging.warning(f" ✗ Request error for {url}: {str(e)[:50]}")
            return None
        except Exception as e:
            logging.error(f"✗ Error processing {url}: {str(e)[:50]}", exc_info=True)
            return None

    tasks = [fetch_and_process_url(url, idx + 1) for idx, url in enumerate(urls_to_extract)]
    results = await asyncio.gather(*tasks)
    
    for content in results:
        if content:
            combined_content.append(content)
            successful_extractions += 1
    
    if not combined_content:
        return f" Could not extract content from {len(urls_to_extract)} URLs. They may not contain relevant information about '{search_query}'."
    
    result = f"Successfully extracted content from {successful_extractions} sources:\n\n" + "\n".join(combined_content)
    logging.info(f" Extraction complete: {successful_extractions}/{len(urls_to_extract)} sources processed")
    
    return result

@tool
def question_generator(skill: str, sources_content: str) -> str:
    """
    Generates insightful, non-coding interview questions based on provided skill and source content.

    Args:
        skill (str): The technical skill for which to generate questions.
        sources_content (str): Combined textual content from various sources related to the skill.

    Returns:
        str: A JSON string conforming to the AllInterviewQuestions schema,
             containing a list of generated interview questions.
    """
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
        
        questions_data = json.loads(str(llm_response))
        questions_list = questions_data.get("questions", [])
        
        interview_questions_obj = InterviewQuestions(skill=skill, questions=questions_list)
        all_interview_questions = AllInterviewQuestions(all_questions=[interview_questions_obj])
        
        return all_interview_questions.json()
    except json.JSONDecodeError as e:
        logging.error(f"Error parsing LLM response as JSON in question_generator: {e}", exc_info=True)
        return json.dumps({"skill": skill, "questions": [], "error": f"Failed to parse LLM response as JSON: {e}"})
    except Exception as e:
        logging.error(f"Error generating questions for skill '{skill}': {e}", exc_info=True)
        return json.dumps({"skill": skill, "questions": [], "error": f"Error generating questions: {e}"})
