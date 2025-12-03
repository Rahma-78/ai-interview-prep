"""
Interview Preparation Crew Package

Architecture:
- crew.py: Main orchestration
- history_manager.py: Data persistence
- file_validator.py: Input validation
- run_metadata.py: Run statistics tracking

All modules follow SOLID principles for maintainability and testability.
"""

from .crew import InterviewPrepCrew
from .history_manager import HistoryManager
from .file_validator import FileValidator
from .run_metadata import RunMetadata

__all__ = [
    'InterviewPrepCrew',
    'HistoryManager', 
    'FileValidator',
    'RunMetadata'
]
