from fastapi import FastAPI
from fastapi.responses import FileResponse

from app.api.v1.interview import interview_router # Import the new router
from app.core.config import settings # Import settings

app = FastAPI()

app.include_router(interview_router, prefix="/v1", tags=["interview"])

@app.get("/")
async def read_root():
    return FileResponse('app/templates/index.html')
