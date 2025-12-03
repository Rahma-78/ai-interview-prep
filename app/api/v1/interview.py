import asyncio
import logging
import json
import os
import shutil
import traceback
from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect, Form
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask
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

@interview_router.post("/generate-questions/")
async def generate_interview_questions(
    resume_file: UploadFile = File(...),
    client_id: str = Form(...)
):
    """
    Generates interview questions based on an uploaded resume file.
    Streams results as NDJSON (Newline Delimited JSON).
    
    Flow:
    1. Validate filename
    2. Save uploaded file
    3. Validate file (fail fast before processing)
    4. Create crew and process (inside generator)
    5. Stream results
    6. Cleanup file (after streaming completes)
    """
    if not resume_file.filename:
        logger.error("No resume file provided.")
        raise HTTPException(status_code=400, detail="No resume file provided.")

    file_location = f"temp_{resume_file.filename}"
    file_saved = False
    
    try:
        # Step 1: Save uploaded file
        with open(file_location, "wb") as buffer:
            await asyncio.to_thread(shutil.copyfileobj, resume_file.file, buffer)
        file_saved = True
        
        # Step 2: Validate file immediately (fail fast)
        from app.services.crew.file_validator import FileValidator
        validator = FileValidator(logger=logger)
        validator.validate(file_location)  # Raises if invalid
        
        async def response_generator():
            """Generator that creates crew, processes, and ensures cleanup."""
            try:
                # Step 3: Create crew (without re-validation)
                crew = InterviewPrepCrew(file_path=file_location, validate=False)
                
                # Progress callback for WebSocket updates
                async def progress_callback(message: str):
                    if not message.startswith("data:"):
                        await manager.send_message(f"STATUS: {message}", client_id)
                
                # Step 4: Process and get results
                results = await crew.run_async(progress_callback=progress_callback)
                
                # Step 5: Stream results as NDJSON
                for result_data in results:
                    if "error" in result_data:
                        error_data = InterviewQuestionState(
                            skill=result_data["skill"],
                            error=result_data.get("error", "Unknown error"),
                            isLoading=False
                        ).model_dump()
                        yield json.dumps(error_data) + "\n"
                    elif "skill" in result_data and "questions" in result_data:
                        data = InterviewQuestionState(
                            skill=result_data["skill"],
                            questions=result_data["questions"],
                            isLoading=False
                        ).model_dump()
                        yield json.dumps(data) + "\n"
                
            except Exception as e:
                logger.error(f"Error in response generator: {e}", exc_info=True)
                error_data = InterviewQuestionState(
                    skill="Error",
                    error=str(e),
                    isLoading=False
                ).model_dump()
                yield json.dumps(error_data) + "\n"
            finally:
                # Step 6: Cleanup file after streaming completes
                cleanup_file(file_location)

        # Return streaming response (cleanup handled in generator's finally block)
        return StreamingResponse(
            response_generator(), 
            media_type="application/x-ndjson"
        )

    except Exception as e:
        logger.error(f"Error processing resume: {e}", exc_info=True)
        # Cleanup if we fail before returning response
        if file_saved and os.path.exists(file_location):
            os.remove(file_location)
        raise HTTPException(status_code=500, detail=f"Error processing resume: {e}")

def cleanup_file(path: str):
    if os.path.exists(path):
        os.remove(path)
        logger.info(f"Cleaned up temporary file: {path}")
