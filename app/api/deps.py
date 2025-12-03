from typing import Generator
from app.services.crew.crew import InterviewPrepCrew
from app.core.config import settings

def get_crew_instance() -> Generator[InterviewPrepCrew, None, None]:
    """
    Dependency for providing an InterviewPrepCrew instance.
    Creates crew without validation since file_path will be set later in the endpoint.
    """
    crew = None
    try:
        # Create crew without validation since file_path will be set later
        crew = InterviewPrepCrew(file_path="", validate=False)
        yield crew
    finally:
        # No specific cleanup needed for InterviewPrepCrew at this time.
        pass

# Example of another dependency (if needed)
# def get_current_user():
#     # Logic to get current authenticated user
#     pass
