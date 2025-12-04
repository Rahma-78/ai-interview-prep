from typing import Generator
from app.services.crew.interview_crew import InterviewPrepCrew
from app.core.config import settings

from typing import Callable

def get_crew_factory() -> Callable[[str], InterviewPrepCrew]:
    """
    Dependency for providing a factory to create InterviewPrepCrew instances.
    This allows deferring creation until the file path is known.
    """
    def factory(file_path: str) -> InterviewPrepCrew:
        return InterviewPrepCrew(file_path=file_path, validate=False)
    return factory

# Example of another dependency (if needed)
# def get_current_user():
#     # Logic to get current authenticated user
#     pass
