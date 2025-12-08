"""
This module defines a collection of CrewAI tools for the interview preparation agent.
These tools are responsible for file processing, discovering interview sources, and generating questions.
"""

# Standard Library Imports
import logging
from pathlib import Path
from typing import List, Dict

# Third-Party Imports
from langchain_community.document_loaders import PyPDFLoader


# Application-Specific Imports
from app.services.tools.source_discovery import discover_sources


logger = logging.getLogger(__name__)


# --- CrewAI Tools ---


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





