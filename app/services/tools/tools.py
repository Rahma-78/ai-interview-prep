"""
This module defines a collection of CrewAI tools for the interview preparation agent.
These tools are responsible for file processing, discovering interview sources, and generating questions.
"""

# Standard Library Imports
import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import List, Dict, Any

# Third-Party Imports
import PyPDF2
from crewai.tools import tool
from dotenv import load_dotenv

# Application-Specific Imports
from app.schemas.interview import (
    InterviewQuestions,
    AllInterviewQuestions,
)
from app.services.tools.helpers import (
    generate_fallback_results,
    optimize_search_query,
)
from app.services.tools.llm_config import llm_openrouter, llm_gemini_flash
from app.services.tools.utils import async_rate_limiter

# --- Configuration ---

# Load environment variables from the specified .env file
load_dotenv(Path(__file__).resolve().parent.parent.parent / 'core' / '.env')

# Configure logging for the module
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# --- Helper Functions ---

def _extract_grounding_sources(response_text: str) -> List[Dict[str, str]]:
    """
    Extracts grounding metadata with URI and title from Gemini's native search results.

    Args:
        response_text: The LLM response text that may contain grounding metadata.

    Returns:
        A list of dictionaries, each containing the 'url', 'title', and empty 'content'.
    """
    grounding_sources = []
    try:
        if 'groundingMetadata' in response_text:
            grounding_pattern = r'"groundingMetadata":\s*{[^}]*"web":\s*\[[^\]]*\]'
            grounding_match = re.search(grounding_pattern, response_text, re.DOTALL)

            if grounding_match:
                web_pattern = r'"uri":\s*"([^"]+)"[^}]*"title":\s*"([^"]+)"'
                web_matches = re.findall(web_pattern, grounding_match.group(0))

                for uri, title in web_matches:
                    if uri and title:
                        grounding_sources.append({
                            "url": uri,
                            "title": title,
                            "content": ""
                        })
    except Exception as e:
        logger.warning(f"Could not extract grounding metadata: {e}")
    return grounding_sources


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


def _format_discovery_result(skill: str, sources: List[Dict], questions: List[str], content: str) -> str:
    """
    Formats the discovered sources, questions, and content into the final JSON structure.
    """
    result_data = {
        "all_sources": [{
            "skill": skill,
            "sources": sources,
            "questions": questions,
            "extracted_content": content[:2000] if content else ""
        }]
    }
    return json.dumps(result_data)


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
        _, file_extension = os.path.splitext(file_path)
        if file_extension.lower() != ".pdf":
            logger.warning(f"Unsupported file type: {file_extension}. Only PDF files are supported.")
            return f"Unsupported file type: {file_extension}. Only PDF files are supported."

        with open(file_path, "rb") as file:
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
async def grounded_source_discoverer(search_query: str, max_retries: int = 3, initial_delay: float = 2.0) -> str:
    """
    Asynchronously discovers technical interview questions and sources using Gemini's native search grounding.
    It handles retries, rate limiting, and formats the output.
    """
    retry_delay = initial_delay
    optimized_query = optimize_search_query(search_query)
    
    for attempt in range(max_retries):
        try:
            await async_rate_limiter.wait_if_needed()
            logger.info(f"Discovering sources for '{search_query}' using Gemini native search (Attempt {attempt + 1}/{max_retries})")

            # Use Gemini's native search grounding
            search_prompt = f"""
            Find high-quality technical interview questions and learning resources for '{optimized_query}'.
            
            Search for authoritative sources like tutorials, educational websites, documentation, and interview question websites.
            Focus on text-based content (articles, documentation, Q&A sites, blogs, guides).
            
            Return a JSON object with the following structure:
            {{
                "sources": [
                    {{
                        "url": "https://example.com",
                        "title": "Source Title",
                        "content": "Brief content snippet"
                    }}
                ],
                "questions": [
                    "Question 1 about {optimized_query}",
                    "Question 2 about {optimized_query}"
                ]
            }}
            
            Include 5-10 high-quality sources and 10 technical interview questions.
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

            # Extract grounding metadata from Gemini's response
            sources = []
            questions = []
            
            try:
                # First, try to parse the response as JSON directly
                response_data = _clean_and_parse_json(search_response)
                
                # Extract sources
                if 'sources' in response_data:
                    for source in response_data['sources'][:10]:  # Top 10 results
                        sources.append({
                            "url": source.get('url', ''),
                            "title": source.get('title', ''),
                            "content": source.get('content', '')[:500]
                        })
                
                # Extract questions
                if 'questions' in response_data:
                    questions = response_data['questions'][:10]  # Top 10 questions
                
                # If no questions found, try to extract from grounding metadata
                if not questions:
                    grounding_sources = _extract_grounding_sources(search_response)
                    sources.extend(grounding_sources)
                    
                    # Generate questions if we have sources but no questions
                    if sources and not questions:
                        questions_prompt = f"""Based on the following sources about {optimized_query},
                        generate 10 technical interview questions. Return only valid JSON with "questions" array.
                        
                        Sources: {json.dumps(sources[:5], indent=2)}
                        
                        Return format: {{"questions": ["question1", "question2", ...]}}"""
                        
                        questions_response = await asyncio.wait_for(
                            asyncio.to_thread(
                                llm_gemini_flash.call,
                                messages=[{"role": "user", "content": questions_prompt}]
                            ),
                            timeout=30.0
                        )
                        
                        questions_data = _clean_and_parse_json(questions_response)
                        questions = questions_data.get("questions", [])
                
            except json.JSONDecodeError:
                # If JSON parsing fails, try to extract from grounding metadata
                logger.warning(f"JSON parsing failed for '{search_query}', extracting from grounding metadata")
                grounding_sources = _extract_grounding_sources(search_response)
                sources.extend(grounding_sources)
                
                # Generate questions if we have sources
                if sources:
                    questions_prompt = f"""Based on the following sources about {optimized_query},
                    generate 10 technical interview questions. Return only valid JSON with "questions" array.
                    
                    Sources: {json.dumps(sources[:5], indent=2)}
                    
                    Return format: {{"questions": ["question1", "question2", ...]}}"""
                    
                    questions_response = await asyncio.wait_for(
                        asyncio.to_thread(
                            llm_gemini_flash.call,
                            messages=[{"role": "user", "content": questions_prompt}]
                        ),
                        timeout=30.0
                    )
                    
                    questions_data = _clean_and_parse_json(questions_response)
                    questions = questions_data.get("questions", [])

            logger.info(f"Successfully discovered {len(questions)} questions and {len(sources)} sources for '{search_query}'")
            
            return _format_discovery_result(search_query, sources, questions, "")

        except asyncio.TimeoutError:
            logger.warning(f"Search call timed out for '{search_query}' on attempt {attempt + 1}")
        except Exception as e:
            logger.error(f"Search call failed for '{search_query}': {e}")
            if "quota" in str(e).lower() or "rate" in str(e).lower():
                logger.info(f"Rate limiting detected for '{search_query}', marking quota exhausted.")
                await async_rate_limiter.mark_quota_exhausted(retry_after_seconds=60)

        # Exponential backoff before retrying
        if attempt < max_retries - 1:
            await asyncio.sleep(retry_delay)
            retry_delay *= 2

    logger.error(f"All search retries failed for '{search_query}'.")
    return generate_fallback_results(search_query)


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
