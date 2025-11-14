from fastapi import FastAPI
from typing import List, Dict, Any
import os
from dotenv import load_dotenv
import subprocess
import asyncio
from fastapi.responses import FileResponse

from app.api.v1.interview import interview_router # Import the new router

# Load environment variables
load_dotenv()

app = FastAPI()

app.include_router(interview_router, prefix="/v1", tags=["interview"])

@app.get("/")
async def read_root():
    return FileResponse('app/templates/index.html')

@app.get("/run-tests/")
async def run_tests():
    result = subprocess.run(['python', '-m', 'unittest', 'app/tests/'], capture_output=True, text=True)
    return {"output": result.stdout + result.stderr}
