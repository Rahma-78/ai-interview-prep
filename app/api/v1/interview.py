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
from app.api.deps import get_crew_factory
from app.core.websocket import manager
from app.schemas.interview import InterviewQuestionState
from app.services.crew.interview_crew import InterviewPrepCrew

# Configure logging
logger = logging.getLogger(__name__)

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
    client_id: str = Form(...),
    crew_factory = Depends(get_crew_factory)
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
                crew = crew_factory(file_location)
                
                # Step 4: Process and get results via async generator
                async for event in crew.run_async_generator():
                    if event["type"] == "status":
                        # Send status updates via WebSocket
                        await manager.send_message(event["content"], client_id)
                    
                    elif event["type"] == "data":
                        # Stream data results as NDJSON immediately
                        result_data = event["content"]
                        skill_name = result_data["skill"]
                        question_count = len(result_data.get("questions", []))
                        logger.info(f"📤 Streaming result for '{skill_name}' ({question_count} questions)")
                        
                        data = InterviewQuestionState(
                            skill=skill_name,
                            questions=result_data["questions"],
                            isLoading=False
                        ).model_dump()
                        yield json.dumps(data) + "\n"
                    
                    elif event["type"] == "error":
                        # Stream error results as NDJSON
                        error_data = event["content"]
                        data = InterviewQuestionState(
                            skill=error_data.get("skill", "Error"),
                            error=error_data.get("error", "Unknown error"),
                            isLoading=False
                        ).model_dump()
                        data_str = json.dumps(data)
                        logger.debug(f"Yielding data: {data_str[:100]}...")
                        yield data_str + "\n"
                
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

        # Return streaming response with headers to disable buffering
        # Cache-Control: no-cache prevents browser caching
        # X-Accel-Buffering: no disables nginx/proxy buffering for immediate delivery
        return StreamingResponse(
            response_generator(), 
            media_type="application/x-ndjson",
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive"
            }
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
