"""
Interview Preparation Crew Package

Architecture:
- crew.py: Main orchestration
- history_manager.py: Data persistence
- file_validator.py: Input validation
- run_metadata.py: Run statistics tracking

All modules follow SOLID principles for maintainability and testability.
"""

from .interview_crew import InterviewPrepCrew
from .file_validator import FileValidator

__all__ = [
    'InterviewPrepCrew',
    'FileValidator',
]
