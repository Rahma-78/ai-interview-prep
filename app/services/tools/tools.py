"""
This module defines a collection of CrewAI tools for the interview preparation agent.
These tools are responsible for file processing, discovering interview sources, and generating questions.
"""

# Standard Library Imports
import asyncio
import json
import logging
import re
from pathlib import Path
from typing import List, Dict, Any
from json import JSONDecodeError

# Third-Party Imports
import PyPDF2
from crewai.tools import tool

# Application-Specific Imports
from app.schemas.interview import (
    InterviewQuestions,
    AllInterviewQuestions,
    AllSkillSources,
    SkillSources,
)
from pydantic import BaseModel
from app.services.tools.llm_config import llm_openrouter, llm_gemini_flash
from app.services.tools.utils import async_rate_limiter, call_llm_with_retry
from app.core.config import settings

logger = logging.getLogger(__name__)


def _extract_grounding_sources(response_text: str) -> List[Dict[str, str]]:
    """
    Extracts grounding metadata with URI, title, confidence scores, and snippets
    from Gemini's native search results for enhanced RAG context.

    Args:
        response_text: The LLM response text that may contain grounding metadata.

    Returns:
        A list of dictionaries, each containing 'url', 'title', and 'snippet'.
    """
    grounding_sources = []
    try:
        if 'groundingMetadata' in response_text:
            grounding_pattern = r'"groundingMetadata":\s*{[^}]*"web":\s*\[[^\]]*\]'
            grounding_match = re.search(grounding_pattern, response_text, re.DOTALL)

            if grounding_match:
                # Enhanced pattern to capture snippets
                web_pattern = r'"uri":\s*"([^"]+)"[^}]*"title":\s*"([^"]+)"[^}]*"snippet":\s*"([^"]*)"'
                web_matches = re.findall(web_pattern, grounding_match.group(0), re.DOTALL)

                for uri, title, snippet in web_matches:
                    if uri and title:
                        grounding_sources.append({
                            "url": uri,
                            "title": title,
                            "snippet": snippet.replace('\n', ' ').strip(),
                            "content": ""  # Keep for backward compatibility
                        })
                
                # Fallback for simpler grounding metadata
                if not web_matches:
                    simple_pattern = r'"uri":\s*"([^"]+)"[^}]*"title":\s*"([^"]+)"'
                    simple_matches = re.findall(simple_pattern, grounding_match.group(0))
                    
                    for uri, title in simple_matches:
                        if uri and title:
                            grounding_sources.append({
                                "url": uri,
                                "title": title,
                                "snippet": "",
                                "content": ""
                            })
    except Exception as e:
        logger.warning(f"Could not extract grounding metadata: {e}")
    return grounding_sources


def _create_fallback_sources(search_query: str) -> AllSkillSources:
    """Create fallback sources when primary search fails."""
    fallback_uris = [
        f"https://en.wikipedia.org/wiki/{search_query.replace(' ', '_')}",
        f"https://www.google.com/search?q={search_query.replace(' ', '+')}",
    ]
    
    skill_sources = SkillSources(
        skill=search_query,
        sources=[{"url": uri, "title": f"Fallback source for {search_query}", "content": ""}
                for uri in fallback_uris],
        extracted_content=f"Fallback sources for {search_query}. Consider manual search for better results."
    )
    
    return AllSkillSources(all_sources=[skill_sources])


def _extract_urls_from_text(text: str) -> List[Dict[str, str]]:
    """
    Extract URLs from text content when grounding metadata is not available.
    
    Args:
        text: The text content to search for URLs.
        
    Returns:
        A list of dictionaries containing URL and content information.
    """
    sources = []
    try:
        import re
        # Pattern to match URLs
        url_pattern = r'https?://[^\s<>"\'()]+'
        urls = re.findall(url_pattern, text)
        
        # Create source entries for each unique URL
        for url in urls:
            if url:  # Ensure URL is not empty
                sources.append({
                    "url": url,
                    "title": "",  # No title available from text extraction
                    "snippet": "",  # No snippet available from text extraction
                    "content": ""  # No content extracted from URL
                })
                
        logger.info(f"Extracted {len(sources)} URLs from text")
    except Exception as e:
        logger.warning(f"Could not extract URLs from text: {e}")
    
    return sources


def _clean_and_parse_json(json_string: str) -> Dict[str, Any]:
    """
    Cleans and parses a JSON string, removing markdown and fixing common formatting issues.

    Args:
        json_string: The raw string to be parsed.

    Returns:
        A dictionary parsed from the JSON string.
    """
    # Remove markdown code block fences
    if json_string.startswith('```json'):
        json_string = json_string[7:]
    if json_string.endswith('```'):
        json_string = json_string[:-3]

    # Fix common JSON formatting issues like trailing commas
    json_string = json_string.strip()
    json_string = json_string.replace(',]', ']').replace(',}', '}')

    return json.loads(json_string)

# --- CrewAI Tools ---
from app.services.tools.prompts import (
    SEARCH_PROMPT_TEMPLATE,
    QUESTION_GENERATOR_PROMPT_TEMPLATE,
)


# --- CrewAI Tools ---

@tool
def file_text_extractor(file_path: str) -> str:
    """
    Extracts all text content from a PDF file.

    Args:
        file_path: The path to the PDF file.

    Returns:
        The extracted text content from the PDF, or an error message if an issue occurs.
    """
    try:
        path_obj = Path(file_path)
        if path_obj.suffix.lower() != ".pdf":
            logger.warning(f"Unsupported file type: {path_obj.suffix}. Only PDF files are supported.")
            return f"Unsupported file type: {path_obj.suffix}. Only PDF files are supported."

        with path_obj.open("rb") as file:
            reader = PyPDF2.PdfReader(file)
            text = "".join(page.extract_text() for page in reader.pages)
            logger.info(f"Successfully extracted {len(text)} characters from {file_path}")
            return text if text else "Error: No text could be extracted from the PDF."

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
async def grounded_source_discoverer(search_query: str) -> AllSkillSources:
    """
    Discovers authoritative web sources using Gemini's native search grounding for technical skills.
    This tool focuses on finding high-quality text-based technical resources with proper grounding.
    
    Args:
        search_query: The technical skill or topic to search for.
        
    Returns:
        AllSkillSources: Pydantic model containing discovered sources with content
        for use as context by the question generation agent.
    """
    try:
        await async_rate_limiter.wait_if_needed()
        
        logger.info(f"Discovering sources for '{search_query}' using Gemini native search")

        # Use Gemini's native search grounding directly
        search_response = await call_llm_with_retry(
            llm_gemini_flash,
            search_query,  # Direct query - Gemini handles search natively
            settings.SEARCH_TIMEOUT
        )
        await async_rate_limiter.record_request()
        
        logger.info(f"Search response for '{search_query}': {str(search_response)[:500]}...")

        # Extract grounding sources directly from Gemini's response
        sources = _extract_grounding_sources(str(search_response))
        
        # Extract content from response
        extracted_content = str(search_response)
        
        # If no grounding metadata found, extract URLs from the response text
        if not sources:
            logger.info(f"No grounding metadata found for '{search_query}', extracting URLs from response text")
            sources = _extract_urls_from_text(str(search_response))
        
        # Build sources list with URL and content
        sources_list = []
        for source in sources:
            sources_list.append({
                "url": source.get("url", ""),
                "content": source.get("content", ""),
                "title": source.get("title", "")
            })

        skill_sources = SkillSources(
            skill=search_query,
            sources=sources_list,
            extracted_content=extracted_content
        )
        
        logger.info(f"Successfully discovered {len(sources)} sources for '{search_query}'")
        return AllSkillSources(all_sources=[skill_sources])

    except asyncio.TimeoutError:
        logger.error(f"Search call timed out for '{search_query}'")
        return _create_fallback_sources(search_query)
    except Exception as e:
        logger.error(f"Search call failed for '{search_query}': {e}", exc_info=True)
        if "quota" in str(e).lower() or "rate" in str(e).lower():
            logger.info(f"Rate limiting detected for '{search_query}', marking quota exhausted.")
            await async_rate_limiter.mark_quota_exhausted(retry_after_seconds=60)
        return _create_fallback_sources(search_query)




@tool
async def question_generator(skill: str, sources_content: str) -> str:
    """
    Generates interview questions based on a provided skill and contextual content.

    Args:
        skill: The technical skill to generate questions for.
        sources_content: The context to use for generating questions.

    Returns:
        A JSON string containing the generated questions or an error message.
    """
    prompt = QUESTION_GENERATOR_PROMPT_TEMPLATE.format(
        skill=skill, sources=sources_content
    )
    try:
        llm_response = await call_llm_with_retry(
            llm_openrouter,
            prompt,
            timeout=settings.QUESTION_GENERATION_TIMEOUT
        )
        questions_data = _clean_and_parse_json(llm_response)
        questions_list = questions_data.get("questions", [])

        interview_questions = InterviewQuestions(skill=skill, questions=questions_list)
        return AllInterviewQuestions(all_questions=[interview_questions]).json()

    except (JSONDecodeError, Exception) as e:
        logger.error(f"Error generating questions for '{skill}': {e}", exc_info=True)
        return json.dumps({"skill": skill, "questions": [], "error": f"Question generation failed: {e}"})
