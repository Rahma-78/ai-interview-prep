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
async def question_generator(all_skill_sources_json: str) -> str:
    """
    Generates interview questions for a batch of skills in parallel.
    
    Args:
        all_skill_sources_json: A JSON string conforming to the AllSkillSources schema.
        
    Returns:
        A JSON string conforming to the AllInterviewQuestions schema.
    """
    try:
        # Parse input
        sources_data = json.loads(all_skill_sources_json)
        all_sources = AllSkillSources(**sources_data)
        
        # Define the single question generation function (internal helper)
        async def generate_single_skill_questions(skill_source) -> InterviewQuestions:
            skill = skill_source.skill
            # Extract content from the structured object
            # Note: extracted_content is now a List[str]
            if skill_source.extracted_content:
                context = "\n".join(skill_source.extracted_content)
            else:
                context = f"No specific context found for {skill}."
            
            prompt = f"""As an expert technical interviewer, your goal is to assess a candidate's deep understanding of "{skill}".
            
            Use the provided Context below as a knowledge base (RAG) to ground your questions in relevant topics and terminology.
            Combine this context with your own expert knowledge to generate insightful, non-coding interview questions that test conceptual depth, problem-solving, and architectural understanding.
            
            Context:
            {context}
            
            Respond with a single, valid JSON object with a "questions" key, which is an array of unique strings.
            """
            
            try:
                # Use safe_api_call for rate limiting and retries
                llm_response = await safe_api_call(
                    llm_openrouter.call,
                    messages=[{"role": "user", "content": prompt}],
                    service='openrouter'
                )
                
                questions_data = json.loads(llm_response)
                questions_list = questions_data.get("questions", [])
                return InterviewQuestions(skill=skill, questions=questions_list)
                
            except Exception as e:
                logger.error(f"Error generating questions for '{skill}': {e}", exc_info=True)
                return InterviewQuestions(skill=skill, questions=[f"Error generating questions: {str(e)}"])

        # Execute in parallel
        tasks = [generate_single_skill_questions(source) for source in all_sources.all_sources]
        results = await asyncio.gather(*tasks)
        
        return AllInterviewQuestions(all_questions=list(results)).json()

    except json.JSONDecodeError as e:
        logger.error(f"JSON parsing error in batch_question_generator: {e}", exc_info=True)
        return json.dumps({"error": f"Failed to parse input JSON: {e}"})
    except Exception as e:
        logger.error(f"Unexpected error in batch_question_generator: {e}", exc_info=True)
        return json.dumps({"error": f"Unexpected error: {e}"})
