from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from typing import List, Dict, Any
import os
import shutil
import json
from app.services.crew.crew import InterviewPrepCrew
from app.schemas.interview import InterviewQuestion
from app.api.deps import get_crew_instance # Import the dependency

interview_router = APIRouter()

@interview_router.post("/generate-questions/", response_model=List[InterviewQuestion])
async def generate_interview_questions(
    resume_file: UploadFile = File(...),
    crew: InterviewPrepCrew = Depends(get_crew_instance)
):
    if not resume_file.filename:
        raise HTTPException(status_code=400, detail="No resume file provided.")

    # Save the uploaded file temporarily
    file_location = f"temp_{resume_file.filename}"
    # The crew instance is now provided by dependency injection
    try:
        with open(file_location, "wb") as buffer:
            shutil.copyfileobj(resume_file.file, buffer)
        
        # Set the file_path on the injected crew instance
        crew.file_path = file_location
        
        # Run the crew with CrewAI async processing (async execution enabled at agent and crew level)
        result = await crew.run_async()

        # The result from crew.run() is expected to be a list of dictionaries
        # like [{"skill": "Python", "questions": ["Q1", "Q2"]}]
        
        formatted_results: List[InterviewQuestion] = []
        for item in result:
            if isinstance(item, dict) and "skill" in item and "questions" in item:
                formatted_results.append(
                    InterviewQuestion(
                        skill=item["skill"],
                        questions=item["questions"],
                        isLoading=False # Processing is complete
                    )
                )
            else:
                # Handle cases where the crew output might not be as expected
                print(f"Unexpected item in crew result: {item}")
                formatted_results.append(
                    InterviewQuestion(
                        skill="Unknown",
                        error="Failed to parse questions from AI crew.",
                        isLoading=False
                    )
                )
        
        return formatted_results

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing resume: {e}")
    finally:
        # Clean up the temporary file
        if os.path.exists(file_location):
            os.remove(file_location)
        # The cleanup for the crew instance is handled by the dependency `get_crew_instance`
