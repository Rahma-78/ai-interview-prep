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
from app.services.tools.helpers import (
    generate_fallback_results,
    optimize_search_query,
)
from app.services.tools.llm_config import llm_openrouter, llm_gemini_flash
from app.services.tools.utils import async_rate_limiter
from app.services.tools.parsers import (
    extract_grounding_sources,
    clean_and_parse_json,
    format_discovery_result,
)

logger = logging.getLogger(__name__)


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
        logger.info(f"Discovering sources for '{search_query}' using Gemini native search")

        # Use Gemini's native search grounding to find authoritative sources
        search_prompt = f"""
        Find high-quality technical learning resources and authoritative sources for '{search_query}'.
        
        Search for authoritative sources like tutorials, educational websites, documentation,
        technical articles, and expert blogs. Focus on text-based content with substantial information.
        
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
        
        Include 5-10 high-quality sources with substantial content excerpts.
        Use Google Search grounding to find relevant information.
        """
        
        # Call Gemini with search tool enabled
        search_response = await asyncio.wait_for(
            asyncio.to_thread(
                llm_gemini_flash.call,
                messages=[{"role": "user", "content": search_prompt}]
            ),
            timeout=30.0
        )
        await async_rate_limiter.record_request()
        
        logger.info(f"Raw search response for '{search_query}': {str(search_response)[:500]}...")

        # Extract sources from Gemini's response
        sources = []
        
        try:
            # First, try to parse the response as JSON directly
            response_data = clean_and_parse_json(search_response)
            
            if 'sources' in response_data:
                for source in response_data['sources'][:10]:  # Top 10 results
                    sources.append({
                        "url": source.get('url', ''),
                        "title": source.get('title', ''),
                        "content": source.get('content', '')[:2000]  # Limit content size
                    })
            
            # If no sources found in JSON, try to extract from grounding metadata
            if not sources:
                grounding_sources = extract_grounding_sources(search_response)
                sources.extend(grounding_sources)
                
                # If we have grounding sources but no content, try to extract content
                if grounding_sources:
                    content_extraction_prompt = f"""
                    Extract detailed content from the following URLs about '{search_query}':
                    {json.dumps([s['url'] for s in grounding_sources[:3]], indent=2)}
                    
                    For each URL, provide a substantial content excerpt (200-500 words)
                    that would be useful for generating technical interview questions.
                    
                    Return a JSON object with the same structure as the sources above.
                    """
                    
                    content_response = await asyncio.wait_for(
                        asyncio.to_thread(
                            llm_gemini_flash.call,
                            messages=[{"role": "user", "content": content_extraction_prompt}]
                        ),
                        timeout=30.0
                    )
                    
                    content_data = clean_and_parse_json(content_response)
                    if 'sources' in content_data:
                        sources.extend(content_data['sources'][:7])  # Add more sources

        except JSONDecodeError:
            # If JSON parsing fails, try to extract from grounding metadata
            logger.warning(f"JSON parsing failed for '{search_query}', extracting from grounding metadata")
            grounding_sources = extract_grounding_sources(search_response)
            sources.extend(grounding_sources)

        # Generate extracted_content summary for RAG context
        extracted_content = ""
        if sources:
            # Create a summary of the key themes and patterns across sources
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
                summary_response = await asyncio.wait_for(
                    asyncio.to_thread(
                        llm_gemini_flash.call,
                        messages=[{"role": "user", "content": content_summary_prompt}]
                    ),
                    timeout=30.0
                )
                
                extracted_content = clean_and_parse_json(summary_response).get("summary", "")
                if not extracted_content:
                    extracted_content = str(summary_response)[:2000]  # Fallback to raw content
                    
            except Exception as e:
                logger.warning(f"Could not generate content summary: {e}")
                # Combine source content as fallback
                extracted_content = "\n\n".join([s.get('content', '') for s in sources[:5]])
                extracted_content = extracted_content[:2000] if extracted_content else ""

        logger.info(f"Successfully discovered {len(sources)} sources for '{search_query}'")
        
        # Create SkillSources object with proper structure
        skill_sources = SkillSources(
            skill=search_query,
            sources=sources,
            questions=[],  # Empty - questions will be generated by third agent
            extracted_content=extracted_content
        )
        
        return AllSkillSources(all_sources=[skill_sources])

    except asyncio.TimeoutError:
        logger.error(f"Search call timed out for '{search_query}'")
        return _create_fallback_sources(search_query)
    except Exception as e:
        logger.error(f"Search call failed for '{search_query}': {e}")
        if "quota" in str(e).lower() or "rate" in str(e).lower():
            logger.info(f"Rate limiting detected for '{search_query}', marking quota exhausted.")
            await async_rate_limiter.mark_quota_exhausted(retry_after_seconds=60)
        return _create_fallback_sources(search_query)


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
        questions=[],
        extracted_content=f"Fallback sources for {search_query}. Consider manual search for better results."
    )
    
    return AllSkillSources(all_sources=[skill_sources])


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
