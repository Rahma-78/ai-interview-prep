import asyncio
import logging
import os
import shutil
import traceback
from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect, Form
from app.api.deps import get_crew_instance
from app.core.websocket import manager
from app.schemas.interview import InterviewQuestionState
from app.services.crew.crew import InterviewPrepCrew

from app.core.logger import setup_logger

# Configure logging
logger = setup_logger()

interview_router = APIRouter()

@interview_router.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    await manager.connect(websocket, client_id)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(client_id)

@interview_router.post("/generate-questions/", response_model=List[InterviewQuestionState])
async def generate_interview_questions(
    resume_file: UploadFile = File(...),
    client_id: str = Form(...),
    crew: InterviewPrepCrew = Depends(get_crew_instance)
):
    """
    Generates interview questions based on an uploaded resume file.

    Args:
        resume_file (UploadFile): The resume file to process.
        crew (InterviewPrepCrew): The CrewAI instance for generating questions.

    Returns:
        List[InterviewQuestionState]: A list of generated interview questions.

    Raises:
        HTTPException: If no resume file is provided or an error occurs during processing.
    """
    if not resume_file.filename:
        logger.error("No resume file provided.")
        raise HTTPException(status_code=400, detail="No resume file provided.")

    file_location = f"temp_{resume_file.filename}"
    try:
        # Use asyncio.to_thread for blocking I/O operations
        await asyncio.to_thread(shutil.copyfileobj, resume_file.file, open(file_location, "wb"))
        
        crew.file_path = file_location
        
        async def progress_callback(message: str):
            # Message can be a step update ("step_1") or data ("data:{...}")
            await manager.send_message(message, client_id)

        result = await crew.run_async(progress_callback=progress_callback)
        
        formatted_results: List[InterviewQuestionState] = []
        for item in result:
            if isinstance(item, dict) and "skill" in item and "questions" in item:
                formatted_results.append(
                    InterviewQuestionState(
                        skill=item["skill"],
                        questions=item["questions"],
                        isLoading=False
                    )
                )
            else:
                logger.warning(f"Unexpected item in crew result: {item}")
                formatted_results.append(
                    InterviewQuestionState(
                        skill="Unknown",
                        error="Failed to parse questions from AI crew.",
                        isLoading=False
                    )
                )
        
        return formatted_results

    except Exception as e:
        logger.error(f"Error processing resume: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error processing resume: {e}")
    finally:
        if os.path.exists(file_location):
            os.remove(file_location)
            logger.info(f"Cleaned up temporary file: {file_location}")
