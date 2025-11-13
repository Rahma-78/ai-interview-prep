from fastapi import FastAPI, UploadFile, File, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any
import os
from dotenv import load_dotenv
import shutil
import json
import subprocess
import asyncio
from fastapi.responses import FileResponse

from backend.crew import InterviewPrepCrew

# Load environment variables
load_dotenv()

app = FastAPI()

class InterviewQuestion(BaseModel):
    skill: str
    query: str | None = None
    sources: List[Dict] | None = None
    questions: List[str] | None = None
    isLoading: bool = False # Changed to False as processing will be done by backend
    error: str | None = None

@app.get("/")
async def read_root():
    return FileResponse('backend/templates/index.html')

@app.get("/run-tests/")
async def run_tests():
    result = subprocess.run(['python', '-m', 'unittest', 'backend/tests/'], capture_output=True, text=True)
    return {"output": result.stdout + result.stderr}

@app.post("/generate-questions/", response_model=List[InterviewQuestion])
async def generate_interview_questions(resume_file: UploadFile = File(...)):
    if not resume_file.filename:
        raise HTTPException(status_code=400, detail="No resume file provided.")

    # Save the uploaded file temporarily
    file_location = f"temp_{resume_file.filename}"
    crew = None  # Initialize crew to None
    try:
        with open(file_location, "wb") as buffer:
            shutil.copyfileobj(resume_file.file, buffer)
        
        # Create the crew with full CrewAI approach (all agents use CrewAI with async execution)
        crew = InterviewPrepCrew(file_path=file_location)
        
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
                    InterviewQuestion(#
                        skill="Unknown",
                        error="Failed to parse questions from AI crew.",
                        isLoading=False
                    )
                )
        
        return formatted_results

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing resume: {e}")
    finally:
        # Clean up the temporary file and crew resources
        if os.path.exists(file_location):
            os.remove(file_location)
        try:
            if crew is not None:
                crew.cleanup()
        except Exception as e:
            print(f"Error during cleanup: {e}")
