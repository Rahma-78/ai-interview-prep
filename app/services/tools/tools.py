"""
This module defines a collection of CrewAI tools for the interview preparation agent.
These tools are responsible for file processing, discovering interview sources, and generating questions.
"""

# Standard Library Imports
import json
import logging
from pathlib import Path

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
async def grounded_source_discoverer(search_query: str) -> AllSkillSources:
    """
    Asynchronously retrieves Gemini's native search response for a given skill.
    This function returns the raw Gemini response text along with the skill,
    providing context for question generation by the third agent.
    """
    return await discover_sources(search_query)


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
