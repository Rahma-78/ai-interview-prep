import asyncio
import json
import logging
import os
from typing import List, Optional
from requests.exceptions import RequestException
import httpx
import PyPDF2
from bs4 import BeautifulSoup
from crewai.tools import tool
from dotenv import load_dotenv

from app.schemas.interview import (
    AllSkillSources,
    InterviewQuestions,
    AllInterviewQuestions,
    SkillSources,
)
from app.services.tools.helpers import (
    generate_fallback_results,
    optimize_search_query,
)
from app.services.tools.llm import llm_gemini_flash, llm_openrouter
from app.services.tools.search_tool import get_serper_tool
from app.services.tools.utils import  async_rate_limiter

# Configure logging and load environment variables first
from pathlib import Path
load_dotenv(Path(__file__).resolve().parent.parent.parent / 'core' / '.env')
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger(__name__)

# Initialize SerperDevTool after environment variables are loaded
_serper_tool = get_serper_tool()

@tool
def file_text_extractor(file_path: str) -> str:
    """
    Extracts all text content from a PDF file.

    Args:
        file_path: The path to the PDF file.

    Returns:
        The extracted text content from the PDF, or an error message.
    """
    try:
        _, file_extension = os.path.splitext(file_path)
        file_extension = file_extension.lower()

        if file_extension != ".pdf":
            logger.warning(f"Unsupported file type: {file_extension}. Only PDF files are supported.")
            return f"Unsupported file type: {file_extension}. Only PDF files are supported."

        with open(file_path, "rb") as file:
            reader = PyPDF2.PdfReader(file)
            text = "".join(page.extract_text() for page in reader.pages)
            logger.info(f"Extracted text length: {len(text)}")
            return (
                text
                if text
                else "Error: No text could be extracted from the PDF."
            )
    except FileNotFoundError:
        logger.error(f"File not found: {file_path}")
        return f"Error: The file at {file_path} was not found."
    except PermissionError:
        logger.error(f"Permission denied when accessing file: {file_path}")
        return f"Error: Permission denied when accessing file: {file_path}"
    except Exception as e:
        logger.error(f"Unexpected error in file_text_extractor for {file_path}: {e}", exc_info=True)
        return f"An error occurred while reading the PDF: {str(e)}"
    
@tool
async def google_search_tool(
    search_query: str,
    max_retries: int = 3,
    initial_delay: float = 2.0
) -> str:
    """
    Performs an ASYNCHRONOUS Google search with optimized caching, retries,
    and error handling.
    """
    try:
        optimized_query = optimize_search_query(search_query)
    except Exception as e:
        logger.error(f"Query optimization failed for '{search_query}': {e}. Using original.")
        optimized_query = search_query

    retry_delay = initial_delay
    
    for attempt in range(max_retries):
        try:
            # 4. Await the rate limiter
            await async_rate_limiter.wait_if_needed() 
            logger.info(
                f" Searching: '{optimized_query}' (Attempt {attempt + 1}/{max_retries})"
            )

            # 5. Await the async tool method
            # CORRECT: Awaiting the asynchronous function
            # This runs the blocking .run() function in a separate thread,
# awaits the thread's completion, and returns the result—all
# without blocking the main asyncio loop.
            raw_result = await asyncio.to_thread(
                _serper_tool.run, 
                search_query=optimized_query
            )
                                    
            # 6. FIXED: Await the async record_request method
            await async_rate_limiter.record_request()

            parsed_result = (
                json.loads(raw_result)
                if isinstance(raw_result, str)
                else raw_result
            )

            result_uris = []
            for item in parsed_result.get("organic", []):
                link = item.get("link")
                if link and link.strip():
                    result_uris.append(link.strip())

            formatted_result = AllSkillSources(
                all_sources=[
                SkillSources(skill=optimized_query, sources=result_uris)
                ]
            ).json()

        
            return formatted_result

        except (RequestException, json.JSONDecodeError, KeyError, TypeError) as e:
            logger.error(f"Search attempt {attempt + 1} failed for '{optimized_query}': {type(e).__name__}: {e}")
            if attempt < max_retries - 1:
                logger.info(f"Retrying in {retry_delay}s...")
                await asyncio.sleep(retry_delay) 
                retry_delay *= 2
            
    else:
        logger.warning(f"All search retries failed for '{optimized_query}'. Using fallback.")
        
        # 7. Check if your fallback is also async
        # If _generate_fallback_results is async, it needs 'await'
        # If it's a normal sync function, this is fine.
        return generate_fallback_results(optimized_query)
@tool
def smart_web_content_extractor(
    search_query: str, urls: Optional[List[str]] = None
) -> str:
    """
    Extracts relevant content from a list of URLs based on a query.
    """
    if not urls:
        return "No URLs provided for content extraction."

    try:
        # Create a dummy SkillSources object to conform to AllSkillSources schema
        skill_sources_obj = SkillSources(skill=search_query, sources=urls)
        all_skill_sources = AllSkillSources(all_sources=[skill_sources_obj])#
    except Exception as e:
        logger.error(f"Error processing URLs for '{search_query}': {e}", exc_info=True)
        return f"Error: Could not process URLs for '{search_query}': {str(e)}"

    urls_to_extract = [
        uri
        for item in all_skill_sources.all_sources
        for uri in item.sources
    ][:8]

    async def fetch_and_process(url: str) -> Optional[str]:
        if not url.startswith("http"):
            return None
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, timeout=15)
                response.raise_for_status()

            soup = BeautifulSoup(response.text, "html.parser")
            text_content = " ".join(soup.stripped_strings)
            if not text_content or len(text_content) < 100:
                return None

            prompt = f"""From the following content about "{search_query}", extract the most relevant information.
            Focus on key concepts and practical insights. Max 200 words.
            Content: \"\"\"{text_content[:6000]}\"\"\"
            """
            llm_response = llm_gemini_flash.call(
                messages=[{"role": "user", "content": prompt}]
            )
            return f"Source: {url}\n{llm_response}\n" if llm_response else None
        except Exception as e:
            logger.warning(f"Error processing {url}: {e}")
            return None

    # Run async function in sync context
    try:
        loop = asyncio.get_event_loop()
        tasks = [fetch_and_process(url) for url in urls_to_extract]
        results = loop.run_until_complete(asyncio.gather(*tasks))
        combined_content = [res for res in results if res]

        if not combined_content:
            return f"Could not extract relevant content for '{search_query}'."

        return f"Extracted content from {len(combined_content)} sources:\n\n" + "\n".join(
            combined_content
        )
    except RuntimeError as e:
        if " asyncio.get_event_loop() " in str(e):
            # Event loop not running, create a new one
            return f"Could not extract content due to async event loop issue for '{search_query}'."
        else:
            raise


@tool
def question_generator(skill: str, sources_content: str) -> str:
    """
    Generates interview questions based on provided skill and content.
    """
    try:
        prompt = f"""As an expert interviewer, generate insightful, non-coding questions for a candidate skilled in "{skill}",
        based ONLY on the provided Context.
        Context: {sources_content}
        Respond with a single, valid JSON object with a "questions" key, which is an array of unique strings.
        """
        llm_response = llm_openrouter.call(
            messages=[{"role": "user", "content": prompt}]
        )
        # Assuming llm_response is a string containing valid JSON
        questions_data = json.loads(llm_response)
        questions_list = questions_data.get("questions", [])

        interview_questions = InterviewQuestions(
            skill=skill, questions=questions_list
        )
        return AllInterviewQuestions(
            all_questions=[interview_questions]
        ).json()
    except json.JSONDecodeError as e:
        logger.error(f"JSON parsing error while generating questions for '{skill}': {e}", exc_info=True)
        return json.dumps({
            "skill": skill,
            "questions": [],
            "error": f"Failed to parse LLM response as JSON: {str(e)}"
        })
    except Exception as e:
        logger.error(f"Error generating questions for '{skill}': {e}", exc_info=True)
        return json.dumps({
            "skill": skill,
            "questions": [],
            "error": f"Question generation failed: {str(e)}"
        })
