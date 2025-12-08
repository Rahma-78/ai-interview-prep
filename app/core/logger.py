import logging
import sys
import time
import json
import re
from functools import wraps
from pathlib import Path
from typing import Callable, Any, Optional
from contextvars import ContextVar

from logging.handlers import RotatingFileHandler
import os

# Context variable for correlation ID
correlation_id_var: ContextVar[Optional[str]] = ContextVar('correlation_id', default=None)

# Patterns for secrets that should be masked in logs
SECRET_PATTERNS = [
    (re.compile(r'(api[_-]?key\s*[=:]\s*)["\']?[\w-]{20,}["\']?', re.IGNORECASE), r'\1***MASKED***'),
    (re.compile(r'(key\s*[=:]\s*)["\']?sk-[\w-]+["\']?', re.IGNORECASE), r'\1***MASKED***'),
    (re.compile(r'(bearer\s+)[\w-]{20,}', re.IGNORECASE), r'\1***MASKED***'),
    (re.compile(r'(authorization\s*[=:]\s*)["\']?[\w-]{20,}["\']?', re.IGNORECASE), r'\1***MASKED***'),
]


def mask_secrets(text: str) -> str:
    """Mask sensitive values in text."""
    for pattern, replacement in SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class SecretMaskingFilter(logging.Filter):
    """Filter to mask secrets in log messages."""
    
    def filter(self, record):
        if isinstance(record.msg, str):
            record.msg = mask_secrets(record.msg)
        if record.args:
            record.args = tuple(
                mask_secrets(str(arg)) if isinstance(arg, str) else arg 
                for arg in record.args
            )
        return True

# Create logs directory if it doesn't exist
# Use absolute path to ensure logs are always written to the project root
BASE_DIR = Path(__file__).resolve().parent.parent.parent
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)

class CorrelationIdFilter(logging.Filter):
    """Filter to inject correlation ID into log records."""
    
    def filter(self, record):
        correlation_id = correlation_id_var.get()
        record.correlation_id = correlation_id if correlation_id else "N/A"
        return True


class JsonFormatter(logging.Formatter):
    """Formatter for structured JSON logging."""
    
    def format(self, record):
        log_data = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": getattr(record, 'correlation_id', 'N/A'),
        }
        
        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        
        # Add extra fields
        if hasattr(record, 'extra_data'):
            log_data.update(record.extra_data)
        
        return json.dumps(log_data)


class ColorFormatter(logging.Formatter):
    """Custom formatter to add colors to console output."""
    
    grey = "\x1b[38;20m"
    yellow = "\x1b[33;20m"
    red = "\x1b[31;20m"
    bold_red = "\x1b[31;1m"
    reset = "\x1b[0m"
    format_str = "%(asctime)s - [%(correlation_id)s] - %(name)s - %(levelname)s - %(message)s"

    FORMATS = {
        logging.DEBUG: grey + format_str + reset,
        logging.INFO: grey + format_str + reset,
        logging.WARNING: yellow + format_str + reset,
        logging.ERROR: red + format_str + reset,
        logging.CRITICAL: bold_red + format_str + reset
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt, datefmt="%Y-%m-%d %H:%M:%S")
        return formatter.format(record)

def setup_log_file(clear_log: bool = False):
    """
    Handles log file creation and clearing.
    """
    # Create logs directory if it doesn't exist
    LOGS_DIR.mkdir(exist_ok=True)
    
    log_file = LOGS_DIR / "app.log"
    
    if clear_log and log_file.exists():
         log_file.write_text("")  # Clear file

def configure_logger(name: str = "app", log_level: int = logging.INFO, use_json: bool = False, mask_secrets: bool = True) -> logging.Logger:
    """
    Configures the logger handlers and filters.
    """
    logger = logging.getLogger(name)
    logger.setLevel(log_level)
    
    # Add correlation ID filter
    correlation_filter = CorrelationIdFilter()
    
    # Add secret masking filter if enabled
    secret_filter = SecretMaskingFilter() if mask_secrets else None

    # Prevent adding handlers multiple times
    if logger.hasHandlers():
        return logger

    # Console Handler with Colors
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(ColorFormatter())
    console_handler.addFilter(correlation_filter)
    if secret_filter:
        console_handler.addFilter(secret_filter)
    logger.addHandler(console_handler)

    # File Handler with Rotation
    # Rotate after 5MB, keep 5 backup files
    file_handler = RotatingFileHandler(
        LOGS_DIR / "app.log", 
        maxBytes=5*1024*1024, 
        backupCount=5, 
        encoding="utf-8"
    )
    
    if use_json:
        file_handler.setFormatter(JsonFormatter(datefmt="%Y-%m-%d %H:%M:%S"))
    else:
        file_handler.setFormatter(logging.Formatter(
            "%(asctime)s - [%(correlation_id)s] - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        ))
    
    
    file_handler.addFilter(correlation_filter)
    if secret_filter:
        file_handler.addFilter(secret_filter)
    logger.addHandler(file_handler)

    return logger

def setup_logger(name: str = "app", log_level: int = logging.INFO, clear_log: bool = False, use_json: bool = False, mask_secrets: bool = True) -> logging.Logger:
    """
    Sets up a logger with console (colored) and file (rotating) handlers.
    
    Args:
        name: Logger name
        log_level: Logging level
        clear_log: If True, clears the log file at startup (useful for fresh runs)
        use_json: If True, uses JSON formatter for file output
        mask_secrets: If True, masks sensitive values like API keys in logs
    """
    setup_log_file(clear_log)
    return configure_logger(name, log_level, use_json, mask_secrets)


def set_correlation_id(correlation_id: str):
    """Set the correlation ID for the current context."""
    correlation_id_var.set(correlation_id)


def get_correlation_id() -> Optional[str]:
    """Get the correlation ID for the current context."""
    return correlation_id_var.get()

# Initialize logger for decorators
logger = logging.getLogger(__name__)



def log_execution_time(func: Callable[..., Any]) -> Callable[..., Any]:
    """
    Decorator to log the execution time of a function.
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        logger.info(f"Starting execution of: {func.__name__}")
        try:
            result = func(*args, **kwargs)
            end_time = time.time()
            duration = end_time - start_time
            logger.info(f"Finished execution of: {func.__name__} in {duration:.4f} seconds")
            return result
        except Exception as e:
            end_time = time.time()
            duration = end_time - start_time
            logger.error(f"Error in {func.__name__} after {duration:.4f} seconds: {str(e)}")
            raise e
    return wrapper

import inspect

def log_async_execution_time(func: Callable[..., Any]) -> Callable[..., Any]:
    """
    Decorator to log the execution time of an async function or async generator.
    """
    if inspect.isasyncgenfunction(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            start_time = time.time()
            logger.info(f"Starting async generator: {func.__name__}")
            try:
                async for item in func(*args, **kwargs):
                    yield item
                end_time = time.time()
                duration = end_time - start_time
                logger.info(f"Finished async generator: {func.__name__} in {duration:.4f} seconds")
            except Exception as e:
                end_time = time.time()
                duration = end_time - start_time
                logger.error(f"Error in async generator {func.__name__} after {duration:.4f} seconds: {str(e)}")
                raise e
        return wrapper
    else:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            start_time = time.time()
            logger.info(f"Starting async execution of: {func.__name__}")
            try:
                result = await func(*args, **kwargs)
                end_time = time.time()
                duration = end_time - start_time
                logger.info(f"Finished async execution of: {func.__name__} in {duration:.4f} seconds")
                return result
            except Exception as e:
                end_time = time.time()
                duration = end_time - start_time
                logger.error(f"Error in async {func.__name__} after {duration:.4f} seconds: {str(e)}")
                raise e
        return wrapper
