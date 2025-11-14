from typing import Generator
from app.services.crew.crew import InterviewPrepCrew
from app.core.config import settings

def get_crew_instance() -> Generator[InterviewPrepCrew, None, None]:
    """
    Dependency for providing an InterviewPrepCrew instance.
    In a real application, this might handle database sessions,
    external API clients, etc.
    """
    # For now, we'll just yield a new instance.
    # In a more complex setup, you might manage a pool or
    # inject specific configurations.
    crew = None # Initialize crew to None
    try:
        crew = InterviewPrepCrew(file_path="temp_resume.pdf") # Placeholder file_path
        yield crew
    finally:
        # No specific cleanup needed for InterviewPrepCrew at this time.
        # If resources (e.g., temporary files) were managed by the crew itself,
        # their cleanup would be handled internally by the crew's methods.
        pass

# Example of another dependency (if needed)
# def get_current_user():
#     # Logic to get current authenticated user
#     pass
