import logging
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Global exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal Server Error", "error": str(exc)},
    )

async def http_exception_handler(request: Request, exc: HTTPException):
    logger.warning(f"HTTP exception: {exc.detail}")
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )
