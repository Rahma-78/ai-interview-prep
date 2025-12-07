from typing import Generator
from app.services.pipeline.interview_pipeline import InterviewPipeline
from app.core.config import settings

from typing import Callable

def get_crew_factory() -> Callable[[str], InterviewPipeline]:
    """
    Dependency for providing a factory to create InterviewPipeline instances.
    This allows deferring creation until the file path is known.
    """
    def factory(file_path: str, correlation_id: str = None) -> InterviewPipeline:
        return InterviewPipeline(file_path=file_path, validate=False, correlation_id=correlation_id)
    return factory

# Example of another dependency (if needed)
# def get_current_user():
#     # Logic to get current authenticated user
#     pass
