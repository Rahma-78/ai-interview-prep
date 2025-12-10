"""
This module defines a collection of CrewAI tools for the interview preparation agent.
These tools are responsible for file processing, discovering interview sources, and generating questions.
"""

# Standard Library Imports
import logging
from pathlib import Path
from typing import List, Dict

# Third-Party Imports - using pypdf instead of PyPDFLoader for better performance
import pypdf

logger = logging.getLogger(__name__)


# --- CrewAI Tools ---


def file_text_extractor(file_path: str) -> str:
    """
    Extracts all text content from a PDF file using pypdf (fast and lightweight).

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

        # Use pypdf for fast PDF extraction (much faster than PyPDFLoader)
        with open(path_obj, 'rb') as file:
            reader = pypdf.PdfReader(file)
            
            # Extract text from all pages (list comprehension for better performance)
            text_parts = [page.extract_text() for page in reader.pages]
            text = "\n".join(text_parts)
        
        logger.info(f"Successfully extracted {len(text)} characters from {len(reader.pages)} pages in {file_path}")
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
