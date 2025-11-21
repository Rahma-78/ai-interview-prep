"""
This module defines a collection of CrewAI tools for the interview preparation agent.
These tools are responsible for file processing, discovering interview sources, and generating questions.
"""

# Standard Library Imports
import asyncio
import functools
import json
import logging
import re
from pathlib import Path
from typing import List, Dict, Any, Optional
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
from app.services.tools.utils import async_rate_limiter
from app.services.tools.parsers import extract_grounding_sources , clean_and_parse_json
from app.services.tools.helpers import optimize_search_query
from app.core.config import settings

logger = logging.getLogger(__name__)




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


# --- Decorators & Helpers ---

def with_retry(max_retries: Optional[int] = None):
    """Decorator to apply exponential backoff retry logic to async functions."""
    
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            retries = max_retries if max_retries is not None else settings.MAX_RETRIES
            
            for attempt in range(retries + 1):
                try:
                    return await func(*args, **kwargs)
                except asyncio.TimeoutError as e:
                    if attempt == retries:
                        logger.error(f"Operation {func.__name__} failed after {retries + 1} attempts: {e}")
                        raise
                    
                    backoff = min(2 ** attempt, 10) + (0.1 * (attempt + 1))
                    logger.warning(f"Timeout in {func.__name__} (attempt {attempt + 1}), retrying in {backoff:.1f}s...")
                    await asyncio.sleep(backoff)
                except Exception as e:
                    raise e
        return wrapper
    return decorator

@with_retry()
async def safe_llm_call(llm_instance, messages: List[Dict], timeout: int) -> str:
    """Wraps a blocking LLM call in a thread with timeout and retry logic."""
    return await asyncio.wait_for(
        asyncio.to_thread(llm_instance.call, messages=messages),
        timeout=timeout
    )

async def enhance_source_content(source: Dict, search_query: str) -> None:
    """
    Enhances a single source's content if it is too short.
    Mutates the source dictionary in place.
    """
    if len(source.get('content', '')) >= 200 or not source.get('url'):
        return

    try:
        content_enhancement_prompt = f"""
        Extract the most relevant technical content from this URL about '{search_query}' useful for interview prep.
        URL: {source['url']}
        Title: {source.get('title', 'Unknown')}
        Return only key technical concepts, problem-solving approaches, and terminology (300 words).
        """
        
        enhanced_content = await safe_llm_call(
            llm_gemini_flash,
            [{"role": "user", "content": content_enhancement_prompt}],
            timeout=settings.CONTENT_ENHANCEMENT_TIMEOUT
        )
        source['content'] = str(enhanced_content)[:2000]
    except Exception as e:
        logger.warning(f"Could not enhance content for {source.get('url')}: {e}")


# --- Main Tool ---

@tool
async def grounded_source_discoverer(search_query: str) -> AllSkillSources:
    """
    Asynchronously discovers authoritative web sources using Gemini's native search grounding.
    This function acts as a RAG system, extracting real-world web content to provide
    context for question generation by the third agent.
    """
    try:
        await async_rate_limiter.wait_if_needed()
        
        optimized_query = optimize_search_query(search_query)
        logger.info(f"Discovering sources for '{optimized_query}' using Gemini native search")

        # 1. Search Execution
        search_prompt = f"""
        Find high-quality technical learning resources for '{optimized_query}' (tutorials, docs, expert blogs).
        
        Return a valid JSON object with this structure:
        {{
            "sources": [
                {{ "url": "...", "title": "...", "content": "Excerpt (200-500 words)..." }}
            ]
        }}
        
        Include 2-3 sources. Use Google Search grounding.
        IMPORTANT: Return ONLY valid JSON. No markdown formatting.
        """

        search_response = await safe_llm_call(
            llm_gemini_flash,
            [{"role": "user", "content": search_prompt}],
            timeout=settings.SEARCH_TIMEOUT
        )
        await async_rate_limiter.record_request()

        # 2. Response Parsing & Merging
        search_response_str = str(search_response or "")
        
        # A. Get metadata from grounding (reliable URLs)
        sources = extract_grounding_sources(search_response_str)
        source_map = {s['url']: s for s in sources}

        # B. Parse JSON content (richer text)
        try:
            response_data = clean_and_parse_json(search_response_str)
            if 'sources' in response_data:
                for json_source in response_data['sources']:
                    url = json_source.get('url')
                    content = json_source.get('content', '')[:2000]
                    title = json_source.get('title', '')
                    
                    if url in source_map:
                        source_map[url]['content'] = content
                    else:
                        new_source = {"url": url, "title": title, "content": content}
                        sources.append(new_source)
                        source_map[url] = new_source
        except (JSONDecodeError, TypeError, Exception) as e:
            logger.warning(f"JSON parse failed for '{search_query}', relying on grounding metadata: {e}")

        # 3. Validation & Parallel Enhancement
        # Check if we need to enhance sources (parallelized)
        high_quality_sources = [s for s in sources if len(s.get('content', '')) > 200]
        
        if len(high_quality_sources) < 3:
            logger.info(f"Insufficent content depth for '{search_query}'. Enhancing sources in parallel...")
            # Create tasks for the top 5 sources to run concurrently
            enhancement_tasks = [
                enhance_source_content(source, search_query) 
                for source in sources[:5]
            ]
            # Run all enhancement calls at the same time
            await asyncio.gather(*enhancement_tasks, return_exceptions=True)

        # 4. Summary Generation
        extracted_content = ""
        if sources:
            summary_prompt = f"""
            Summarize key themes for technical interview questions based on these sources:
            {json.dumps([{k: v for k, v in s.items() if k != 'content'} for s in sources], indent=2)}
            
            Focus on: Core concepts, problem patterns, and best practices (300-500 words).
            """
            try:
                summary_response = await safe_llm_call(
                    llm_gemini_flash,
                    [{"role": "user", "content": summary_prompt}],
                    timeout=settings.SUMMARY_TIMEOUT
                )
                extracted_content = str(summary_response)[:2000]
            except Exception as e:
                logger.warning(f"Summary generation failed: {e}")
                # Fallback: Concatenate existing content
                extracted_content = "\n\n".join(s.get('content', '') for s in sources[:5])[:2000]

        # 5. Final Content Validation
        if len(extracted_content) < 100:
            logger.warning(f"Content too short for '{search_query}'. Returning fallback.")
            return _create_fallback_sources(search_query)

        logger.info(f"Successfully discovered {len(sources)} sources for '{search_query}'")
        
        return AllSkillSources(all_sources=[
            SkillSources(
                skill=search_query,
                sources=sources,
                extracted_content=extracted_content
            )
        ])

    except asyncio.TimeoutError:
        logger.error(f"Search timed out for '{search_query}'")
        return _create_fallback_sources(search_query)
    except Exception as e:
        logger.error(f"Search failed for '{search_query}': {e}", exc_info=True)
        if "quota" in str(e).lower() or "rate" in str(e).lower():
            await async_rate_limiter.mark_quota_exhausted(retry_after_seconds=60)
        return _create_fallback_sources(search_query)