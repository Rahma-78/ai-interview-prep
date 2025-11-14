import asyncio
import logging
import os
import shutil
import traceback
from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.api.deps import get_crew_instance  # Import the dependency
from app.schemas.interview import InterviewQuestion
from app.services.crew.crew import InterviewPrepCrew

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

interview_router = APIRouter()

@interview_router.post("/generate-questions/", response_model=List[InterviewQuestion])
async def generate_interview_questions(
    resume_file: UploadFile = File(...),
    crew: InterviewPrepCrew = Depends(get_crew_instance)
):
    """
    Generates interview questions based on an uploaded resume file.

    Args:
        resume_file (UploadFile): The resume file to process.
        crew (InterviewPrepCrew): The CrewAI instance for generating questions.

    Returns:
        List[InterviewQuestion]: A list of generated interview questions.

    Raises:
        HTTPException: If no resume file is provided or an error occurs during processing.
    """
    if not resume_file.filename:
        logging.error("No resume file provided.")
        raise HTTPException(status_code=400, detail="No resume file provided.")

    file_location = f"temp_{resume_file.filename}"
    try:
        # Use asyncio.to_thread for blocking I/O operations
        await asyncio.to_thread(shutil.copyfileobj, resume_file.file, open(file_location, "wb"))
        
        crew.file_path = file_location
        
        result = await crew.run_async()
        
        formatted_results: List[InterviewQuestion] = []
        for item in result:
            if isinstance(item, dict) and "skill" in item and "questions" in item:
                formatted_results.append(
                    InterviewQuestion(
                        skill=item["skill"],
                        questions=item["questions"],
                        isLoading=False
                    )
                )
            else:
                logging.warning(f"Unexpected item in crew result: {item}")
                formatted_results.append(
                    InterviewQuestion(
                        skill="Unknown",
                        error="Failed to parse questions from AI crew.",
                        isLoading=False
                    )
                )
        
        return formatted_results

    except Exception as e:
        logging.error(f"Error processing resume: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error processing resume: {e}")
    finally:
        if os.path.exists(file_location):
            os.remove(file_location)
            logging.info(f"Cleaned up temporary file: {file_location}")
