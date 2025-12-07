"""
Custom exceptions for the AI Interview Prep application.

This module defines a hierarchy of exceptions to provide specific error handling
and better error messages throughout the application.
"""
import logging
from typing import Optional
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


# ============================================================================
# Custom Exception Classes
# ============================================================================

class AppError(Exception):
    """Base exception for all application errors."""
    def __init__(self, message: str, details: Optional[dict] = None):
        self.message = message
        self.details = details or {}
        super().__init__(self.message)


class SourceDiscoveryError(AppError):
    """Exception raised when source discovery fails."""
    pass


class TokenValidationError(AppError):
    """Exception raised when token limits are exceeded or validation fails."""
    pass


class PipelineTimeoutError(AppError):
    """Exception raised when the pipeline execution exceeds the timeout."""
    pass


class ConfigurationError(AppError):
    """Exception raised when configuration is invalid or missing."""
    pass


# ============================================================================
# FastAPI Exception Handlers
# ============================================================================

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
