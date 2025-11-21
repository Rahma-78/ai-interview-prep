"""
This module defines a collection of CrewAI tools for the interview preparation agent.
These tools are responsible for file processing, discovering interview sources, and generating questions.
"""

# Standard Library Imports
import asyncio
import json
import logging
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
from app.services.tools.helpers import (
    _create_fallback_sources,
    optimize_search_query,
)
from app.services.tools.llm_config import llm_openrouter, llm_gemini_flash
from app.services.tools.utils import async_rate_limiter
from app.services.tools.parsers import (
    extract_grounding_sources,
    clean_and_parse_json,
)
from app.core.config import settings

logger = logging.getLogger(__name__)


# --- Helper Functions ---

async def retry_with_backoff(func, *args, max_retries=None, **kwargs):
    """
    Retry a function with exponential backoff.
    
    Args:
        func: The function to retry
        max_retries: Maximum number of retries (defaults to settings.MAX_RETRIES)
        *args: Positional arguments to pass to func
        **kwargs: Keyword arguments to pass to func
        
    Returns:
        The result of func(*args, **kwargs)
        
    Raises:
        The last exception if all retries fail
    """
    if max_retries is None:
        max_retries = settings.MAX_RETRIES
        
    for attempt in range(max_retries + 1):  # +1 to include the initial attempt
        try:
            return await func(*args, **kwargs)
        except asyncio.TimeoutError as e:
            if attempt == max_retries:
                logger.error(f"Operation failed after {max_retries + 1} attempts: {e}")
                raise
            
            # Calculate backoff time (exponential with jitter)
            backoff = min(2 ** attempt, 10) + (0.1 * (attempt + 1))
            logger.warning(f"Timeout on attempt {attempt + 1}, retrying in {backoff:.1f}s...")
            await asyncio.sleep(backoff)
        except Exception as e:
            # For non-timeout errors, don't retry
            raise


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
    Asynchronously discovers authoritative web sources using Gemini's native search grounding.
    This function acts as a RAG system, extracting real-world web content to provide
    context for question generation by the third agent.
    
    Args:
        search_query: The technical skill or topic to search for.
        
    Returns:
        AllSkillSources: Pydantic model containing discovered sources with content
        for use as context by the question generation agent.
    """
    try:
        await async_rate_limiter.wait_if_needed()
        
        # Optimize the search query for better results
        optimized_query = optimize_search_query(search_query)
        logger.info(f"Discovering sources for '{optimized_query}' using Gemini native search")

        # Use Gemini's native search grounding to find authoritative sources
        search_prompt = f"""
        Find high-quality technical learning resources and authoritative sources for '{optimized_query}'.
        Search for authoritative sources like tutorials, educational websites, documentation,
        technical articles, and expert blogs. Focus on text-based content with substantial information.
        
        CRITICAL: You MUST provide a COMPLETE and VALID JSON response. Do not truncate, cut off, or end mid-sentence.
        Ensure your JSON response is properly formatted and contains all required fields.
        
        Return a JSON object with the following structure:
        {{
            "sources": [
                {{
                    "url": "https://example.com",
                    "title": "Source Title",
                    "content": "Detailed content excerpt from the source"
                }}
            ]
        }}
        
        Include 5-10 high-quality sources with substantial content excerpts (200-500 words per source).
        Use Google Search grounding to find relevant information.
        
        IMPORTANT: Your entire response must be valid JSON. Do not add any explanatory text before or after the JSON.
        Ensure the JSON is complete and properly formatted with no missing brackets or braces.
        """
        
        # Call Gemini with search tool enabled using retry logic
        async def make_search_call():
            return await asyncio.wait_for(
                asyncio.to_thread(
                    llm_gemini_flash.call,
                    messages=[{"role": "user", "content": search_prompt}]
                ),
                timeout=settings.SEARCH_TIMEOUT
            )
            
        search_response = await retry_with_backoff(make_search_call)
        await async_rate_limiter.record_request()
        
        logger.info(f"Raw search response for '{search_query}': {str(search_response)[:500]}...")

        # --- Refactored Source Extraction Logic ---
        
        # Ensure search_response is a string
        if search_response is None:
            search_response = ""
            
        # 1. Prioritize structured grounding metadata for URLs and titles
        sources = extract_grounding_sources(str(search_response))
        source_map = {s['url']: s for s in sources}

        # 2. Try to parse JSON to get content and supplement sources
        try:
            response_data = clean_and_parse_json(str(search_response))
            if 'sources' in response_data and response_data['sources']:
                for source in response_data['sources']:
                    url = source.get('url')
                    if url in source_map:
                        # If source from grounding exists, update its content
                        source_map[url]['content'] = source.get('content', '')[:2000]
                    else:
                        # Otherwise, add it as a new source
                        new_source = {
                            "url": url,
                            "title": source.get('title', ''),
                            "content": source.get('content', '')[:2000]
                        }
                        sources.append(new_source)
                        source_map[url] = new_source
        except (JSONDecodeError, TypeError, Exception) as e:
            logger.warning(f"Could not parse JSON from response for '{search_query}': {e}. Relying solely on grounding.")

        # 3. Generate a summary of the extracted content for the RAG context
        extracted_content = ""
        if sources:
            content_summary_prompt = f"""
            Based on the following sources about '{search_query}', provide a comprehensive summary
            of the key themes, concepts, and patterns that would be most relevant for generating
            technical interview questions.
            Sources: {json.dumps(sources, indent=2)}
            Return a detailed summary (300-500 words) focusing on:
            - Core technical concepts and terminology
            - Common problem patterns and approaches
            - Key learning objectives and takeaways
            - Industry best practices and standards
            """
            try:
                async def make_summary_call():
                    return await asyncio.wait_for(
                        asyncio.to_thread(
                            llm_gemini_flash.call,
                            messages=[{"role": "user", "content": content_summary_prompt}]
                        ),
                        timeout=settings.SUMMARY_TIMEOUT
                    )
                    
                summary_response = await retry_with_backoff(make_summary_call)
                extracted_content = str(summary_response)[:2000]
            except Exception as e:
                logger.warning(f"Could not generate content summary: {e}")
                # Fallback: combine content from the first few sources
                extracted_content = "\n\n".join(s.get('content', '') for s in sources[:5] if s.get('content'))
                extracted_content = extracted_content[:2000]

        # 4. Validate that the extracted content is substantial enough
        if len(extracted_content) < 100:
            logger.warning(f"Extracted content for '{search_query}' is too short. Returning fallback.")
            return _create_fallback_sources(search_query)
        
        # Additional validation: check if we have enough high-quality sources
        high_quality_sources = [s for s in sources if len(s.get('content', '')) > 200]
        if len(high_quality_sources) < 3:
            logger.warning(f"Not enough high-quality sources for '{search_query}'. Found {len(high_quality_sources)} with substantial content.")
            # Try to enhance content from existing sources
            for source in sources[:5]:  # Try to enhance first 5 sources
                if len(source.get('content', '')) < 200 and source.get('url'):
                    try:
                        # Try to get more content from the source URL
                        content_enhancement_prompt = f"""
                        Extract the most relevant technical content from this URL about '{search_query}' that would be useful for generating interview questions:
                        URL: {source['url']}
                        Title: {source['title']}
                        Return only the most important technical concepts, problem-solving approaches, and key terminology (300-500 words).
                        """
                        async def make_enhancement_call():
                            return await asyncio.wait_for(
                                asyncio.to_thread(
                                    llm_gemini_flash.call,
                                    messages=[{"role": "user", "content": content_enhancement_prompt}]
                                ),
                                timeout=settings.CONTENT_ENHANCEMENT_TIMEOUT
                            )
                            
                        enhanced_content = await retry_with_backoff(make_enhancement_call)
                        source['content'] = str(enhanced_content)[:2000]
                    except Exception as e:
                        logger.warning(f"Could not enhance content for {source['url']}: {e}")

        logger.info(f"Successfully discovered {len(sources)} sources for '{search_query}'")
        
        # Create SkillSources object with the final, structured data
        skill_sources = SkillSources(
            skill=search_query,
            sources=sources,
            questions=[],  # Questions to be generated by the third agent
            extracted_content=extracted_content
        )
        
        return AllSkillSources(all_sources=[skill_sources])

    except asyncio.TimeoutError:
        logger.error(f"Search call timed out for '{search_query}' after {settings.SEARCH_TIMEOUT}s and {settings.MAX_RETRIES} retries")
        logger.info(f"Falling back to default sources for '{search_query}'")
        return _create_fallback_sources(search_query)
    except Exception as e:
        logger.error(f"Search call failed for '{search_query}': {e}", exc_info=True)
        if "quota" in str(e).lower() or "rate" in str(e).lower():
            logger.info(f"Rate limiting detected for '{search_query}', marking quota exhausted.")
            await async_rate_limiter.mark_quota_exhausted(retry_after_seconds=60)
        return _create_fallback_sources(search_query)




@tool
def question_generator(skill: str, sources_content: str) -> str:
    """
    Generates interview questions based on a provided skill and contextual content.

    Args:
        skill: The technical skill to generate questions for.
        sources_content: The context to use for generating questions.

    Returns:
        A JSON string containing the generated questions or an error message.
    """
    prompt = f"""As an expert interviewer, generate insightful, non-coding questions for a candidate skilled in "{skill}",
    based ONLY on the provided Context.
    Context: {sources_content}
    Respond with a single, valid JSON object with a "questions" key, which is an array of unique strings.
    """
    try:
        llm_response = llm_openrouter.call(
            messages=[{"role": "user", "content": prompt}]
        )
        questions_data = json.loads(llm_response)
        questions_list = questions_data.get("questions", [])

        interview_questions = InterviewQuestions(skill=skill, questions=questions_list)
        return AllInterviewQuestions(all_questions=[interview_questions]).json()

    except json.JSONDecodeError as e:
        logger.error(f"JSON parsing error for '{skill}': {e}", exc_info=True)
        return json.dumps({"skill": skill, "questions": [], "error": f"Failed to parse LLM response: {e}"})
    except Exception as e:
        logger.error(f"Error generating questions for '{skill}': {e}", exc_info=True)
        return json.dumps({"skill": skill, "questions": [], "error": f"Question generation failed: {e}"})
