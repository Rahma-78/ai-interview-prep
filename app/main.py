import os
# Disable CrewAI Telemetry to prevent 20s delay in "Trace Batch Finalization"
os.environ["OTEL_SDK_DISABLED"] = "true"

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Response, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
from app.api.v1.interview import interview_router
from app.core.logger import setup_logger
from app.core.exceptions import global_exception_handler, http_exception_handler

# Setup logger with fresh log file on startup
setup_logger(clear_log=True)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Application startup: AI Interview Prep System")
    yield
    logger.info("Application shutdown")

app = FastAPI(
    title="AI Interview Prep",
    description="AI-powered interview preparation system.",
    version="1.0.0",
    lifespan=lifespan
)

app.add_exception_handler(Exception, global_exception_handler)
app.add_exception_handler(HTTPException, http_exception_handler)

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
    import time
    with open('app/templates/index.html', 'r', encoding='utf-8') as f:
        content = f.read()
    # Dynamic cache busting: replace the static version with current timestamp
    content = content.replace('app.js?v=2', f'app.js?v={int(time.time())}')
    return HTMLResponse(content)

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse('app/static/favicon.ico') if (static_dir / "favicon.ico").exists() else Response(status_code=204)
