from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path

from app.api.v1.interview import interview_router
from app.core.config import settings
from app.core.logger import setup_logger

# Setup logger
logger = setup_logger()

app = FastAPI(
    title="AI Interview Prep",
    description="AI-powered interview preparation system.",
    version="1.0.0"
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for simplicity in development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
static_dir = Path("app/static")
static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Include routers
app.include_router(interview_router, prefix="/api/v1", tags=["interview"])

@app.get("/")
async def read_root():
    return FileResponse('app/templates/index.html')

@app.on_event("startup")
async def startup_event():
    logger.info("Application startup: AI Interview Prep System")

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Application shutdown")
