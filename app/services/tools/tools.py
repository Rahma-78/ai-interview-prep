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




@tool
async def question_generator(skill: str) -> str:
    """
    Generates interview questions for a specific skill.
    The context for the skill is automatically loaded from 'app/data/context.json'.
    
    Args:
        skill: The technical skill to generate questions for.
        
    Returns:
        A JSON string conforming to the InterviewQuestions schema.
    """
    import logging
    import json
    from pathlib import Path
    logger = logging.getLogger(__name__)
    
    try:
        # Load context from file
        context_file = Path("app/data/context.json")
        context = ""
        
        if context_file.exists():
            try:
                with open(context_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    
                # Find the skill in the data
                # The data structure matches AllSkillSources: {"all_sources": [{"skill": "...", "extracted_content": [...]}]}
                all_sources = data.get("all_sources", [])
                for source in all_sources:
                    if source.get("skill", "").lower() == skill.lower():
                        content_list = source.get("extracted_content", [])
                        context = "\n".join(content_list)
                        break
                
                if not context:
                    logger.warning(f"No context found for skill '{skill}' in {context_file}. Using empty context.")
                    context = f"No specific context found for {skill}."
                    
            except Exception as e:
                logger.error(f"Error reading context file: {e}")
                context = f"Error reading context file: {e}"
        else:
            logger.warning(f"Context file not found at {context_file}. Using empty context.")
            context = "No context file found."

        # Get the schema for strict enforcement
        schema_json = json.dumps(InterviewQuestions.model_json_schema(), indent=2)

        prompt = "\n".join([f"As an expert technical interviewer, your goal is to assess a candidate's deep understanding of {skill}.",    
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
        
        
        try:
            # Use safe_api_call for rate limiting and retries
            # Wrap synchronous llm_openrouter.call in asyncio.to_thread
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
                raise # Re-raise to be caught by outer except

            questions_list = questions_data.get("questions", [])
            return InterviewQuestions(skill=skill, questions=questions_list).model_dump_json()
            
        except Exception as e:
            logger.error(f"Error generating questions for '{skill}': {e}", exc_info=True)
            # Include a snippet of the response in the error for debugging
            debug_info = f"Error: {str(e)}. Response snippet: {llm_response[:200] if 'llm_response' in locals() else 'No response'}"
            return InterviewQuestions(skill=skill, questions=[debug_info]).model_dump_json()

    except Exception as e:
        logger.error(f"Unexpected error in question_generator: {e}", exc_info=True)
        return json.dumps({"error": f"Unexpected error: {e}"})
