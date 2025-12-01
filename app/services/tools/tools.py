"""
This module defines a collection of CrewAI tools for the interview preparation agent.
These tools are responsible for file processing, discovering interview sources, and generating questions.
"""

# Standard Library Imports
import json
import logging
from pathlib import Path
from typing import List, Dict

# Third-Party Imports
from langchain_community.document_loaders import PyPDFLoader
from crewai.tools import tool

# Application-Specific Imports
from app.schemas.interview import (
    InterviewQuestions,
    AllInterviewQuestions,
    AllSkillSources,
)
from app.services.tools.llm_config import llm_openrouter
from app.services.tools.source_discovery import discover_sources
from app.services.tools.utils import safe_api_call
from app.services.tools.helpers import optimize_search_query, parse_batch_response, create_fallback_sources, clean_llm_json_output
import asyncio


logger = logging.getLogger(__name__)

# --- CONFIGURATION ---
# Limits parallel question generation to avoid rate limits and control concurrency
MAX_CONCURRENT_QUESTION_GENERATION = 3

# --- CrewAI Tools ---


@tool
def file_text_extractor(file_path: str) -> str:
    """
    Extracts all text content from a PDF file using LangChain's PyPDFLoader.

    Args:
        file_path: The path to the PDF file.

    Returns:
        The extracted text content from the PDF, or an error message if an issue occurs.
    """
    try:
        # Ensure path is absolute and exists
        path_obj = Path(file_path).resolve()
        
        if not path_obj.exists():
            logger.error(f"File not found: {file_path}")
            return f"Error: The file at {file_path} was not found."
        
        if path_obj.suffix.lower() != ".pdf":
            logger.warning(f"Unsupported file type: {path_obj.suffix}. Only PDF files are supported.")
            return f"Unsupported file type: {path_obj.suffix}. Only PDF files are supported."

        # Use LangChain's PyPDFLoader for robust PDF extraction
        # Use native Windows path format (PyPDFLoader handles it correctly)
        loader = PyPDFLoader(str(path_obj))
        documents = loader.load()
        
        # Combine all pages' content
        text = "\n".join(doc.page_content for doc in documents)
        
        logger.info(f"Successfully extracted {len(text)} characters from {len(documents)} pages in {file_path}")
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
async def grounded_source_discoverer(skills: List[str]) -> Dict:
    """
    Asynchronously retrieves Gemini's native search response for a list of skills.
    This function returns the raw Gemini response text for each skill,
    providing context for question generation by the third agent.
    """
    results = await discover_sources(skills)
    return {"all_sources": results}






# --- Helper Function for Single Skill Processing ---

async def _generate_single_skill_questions(skill: str, context: str) -> InterviewQuestions:
    """
    Internal helper function to generate questions for a single skill.
    Used by batch_question_generator.
    
    Args:
        skill: The technical skill to generate questions for.
        context: The context string for the skill.
        
    Returns:
        InterviewQuestions object with skill and questions list.
    """
    try:
        if not context:
            logger.warning(f"No context provided for skill '{skill}'. Using empty context.")
            context = f"No specific context found for {skill}."

        # Get the schema for strict enforcement
        schema_json = json.dumps(InterviewQuestions.model_json_schema(), indent=2)

        prompt = "\n".join([
            f"As an expert technical interviewer, your goal is to assess a candidate's deep understanding of {skill}.",    
            "Use the provided Context below as a knowledge base (RAG) to ground your questions in relevant topics and terminology.",
            "Combine this context with your own expert knowledge to generate insightful, non-coding interview questions that test conceptual depth, problem-solving, and architectural understanding.",
            f"""Context: 
            {context}""",
            "STRICT OUTPUT FORMAT:",
            f"""You must respond with a valid JSON object that strictly adheres to the following JSON Schema: 
            {schema_json}""",
            f"""Example Output: {{
                "skill": "{skill}",
                "questions": [
                    "Question 1...",
                    "Question 2..."
                ]
            }}""",
            "IMPORTANT: Return ONLY the raw JSON string. Do NOT use markdown code blocks (no backticks). Do NOT add any introductory text."
        ])
        
        # Use safe_api_call for rate limiting and retries
        llm_response = await safe_api_call(
            asyncio.to_thread,
            llm_openrouter.call,
            messages=[{"role": "user", "content": prompt}],
            service='openrouter'
        )
        
        # Robust parsing using helper
        cleaned_response = clean_llm_json_output(llm_response)
        
        if not cleaned_response:
            raise ValueError("LLM returned empty response")

        try:
            questions_data = json.loads(cleaned_response)
        except json.JSONDecodeError:
            logger.error(f"JSON Parsing Failed for '{skill}'.")
            logger.error(f"Raw LLM Response: {llm_response}")
            logger.error(f"Cleaned Response: {cleaned_response}")
            raise

        questions_list = questions_data.get("questions", [])
        return InterviewQuestions(skill=skill, questions=questions_list)
        
    except Exception as e:
        logger.error(f"Error generating questions for '{skill}': {e}", exc_info=True)
        # Return error as InterviewQuestions object
        debug_info = f"Error: {str(e)}. Response snippet: {llm_response[:200] if 'llm_response' in locals() else 'No response'}"
        return InterviewQuestions(skill=skill, questions=[debug_info])


@tool
async def batch_question_generator(skills: List[str]) -> Dict:
    """
    Generates interview questions for multiple skills concurrently with controlled concurrency.
    Uses asyncio.gather() with a semaphore to limit concurrent API calls.
    
    Args:
        skills: List of technical skills to generate questions for.
        
    Returns:
        A dictionary conforming to AllInterviewQuestions schema with all_questions list.
    """
    logger.info(f"Starting batch question generation for {len(skills)} skills with max concurrency: {MAX_CONCURRENT_QUESTION_GENERATION}")
    
    # Create semaphore to limit concurrent requests
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_QUESTION_GENERATION)
    
    # Load context once
    context_map = {}
    try:
        context_file = Path("app/data/context.json")
        if context_file.exists():
            with open(context_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            # Build context map
            all_sources = data.get("all_sources", [])
            for source in all_sources:
                skill_name = source.get("skill", "").lower()
                content_list = source.get("extracted_content", [])
                context_map[skill_name] = "\n".join(content_list)
        else:
             logger.warning(f"Context file not found at {context_file}.")
    except Exception as e:
        logger.error(f"Error reading context file: {e}")

    async def process_single_skill(skill: str) -> InterviewQuestions:
        """Process a single skill with semaphore control."""
        async with semaphore:
            logger.info(f"[Semaphore] Processing skill: {skill}")
            # Get context for this skill
            skill_context = context_map.get(skill.lower(), "")
            result = await _generate_single_skill_questions(skill, skill_context)
            logger.info(f"[Semaphore] Completed skill: {skill}")
            return result
    
    try:
        # Process all skills concurrently with semaphore control
        results = await asyncio.gather(*[process_single_skill(skill) for skill in skills])
        
        # Create final output
        final_output = AllInterviewQuestions(all_questions=list(results))
        
        logger.info(f"Successfully generated questions for {len(results)} skills")
        
        # Return as dictionary for CrewAI
        return final_output.model_dump()
        
    except Exception as e:
        logger.error(f"Error in batch question generation: {e}", exc_info=True)
        # Return partial results or error
        return {
            "all_questions": [
                InterviewQuestions(skill=skill, questions=[f"Error in batch processing: {str(e)}"]).model_dump()
                for skill in skills
            ]
        }
