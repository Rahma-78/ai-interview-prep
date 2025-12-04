from fastapi import FastAPI, Response
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
    import time
    from fastapi.responses import HTMLResponse
    with open('app/templates/index.html', 'r', encoding='utf-8') as f:
        content = f.read()
    # Dynamic cache busting: replace the static version with current timestamp
    # This ensures the browser always loads the latest JS in development
    content = content.replace('app.js?v=2', f'app.js?v={int(time.time())}')
    return HTMLResponse(content)

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse('app/static/favicon.ico') if (static_dir / "favicon.ico").exists() else Response(status_code=204)

@app.on_event("startup")
async def startup_event():
    logger.info("Application startup: AI Interview Prep System")

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Application shutdown")
