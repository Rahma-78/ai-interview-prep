"""
Interview Preparation Crew Package

Architecture:
- interview_crew.py: Pipeline orchestration
- batch_processor.py: Batch source discovery + question generation
- result_persister.py: Result file saving
- llm_service.py: LLM API calls
- prompts.py: Prompt generation
- parser.py: Response parsing
- file_validator.py: Input validation

All modules follow SOLID principles for maintainability and testability.
"""

from .interview_pipeline import InterviewPipeline
from .file_validator import FileValidator
from .batch_processor import BatchProcessor
from .llm_parser import parse_llm_response

__all__ = [
    'InterviewPipeline',
    'FileValidator',
    'BatchProcessor',
    'parse_llm_response',
]

