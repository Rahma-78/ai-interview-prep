import logging
import sys
import time
from functools import wraps
from pathlib import Path
from typing import Callable, Any

from logging.handlers import RotatingFileHandler
import os

# Create logs directory if it doesn't exist
# Use absolute path to ensure logs are always written to the project root
BASE_DIR = Path(__file__).resolve().parent.parent.parent
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)

class ColorFormatter(logging.Formatter):
    """Custom formatter to add colors to console output."""
    
    grey = "\x1b[38;20m"
    yellow = "\x1b[33;20m"
    red = "\x1b[31;20m"
    bold_red = "\x1b[31;1m"
    reset = "\x1b[0m"
    format_str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

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

def setup_logger(name: str = "app", log_level: int = logging.INFO, clear_log: bool = False) -> logging.Logger:
    """
    Sets up a logger with console (colored) and file (rotating) handlers.
    
    Args:
        name: Logger name
        log_level: Logging level
        clear_log: If True, clears the log file at startup (useful for fresh runs)
    """
    logger = logging.getLogger(name)
    logger.setLevel(log_level)

    # Prevent adding handlers multiple times
    if logger.hasHandlers():
        # If clear_log requested and handlers already exist, clear the log file
        if clear_log:
            log_file = LOGS_DIR / "app.log"
            if log_file.exists():
                log_file.write_text("")  # Clear file
        return logger

    # Clear log file if requested (fresh start)
    if clear_log:
        log_file = LOGS_DIR / "app.log"
        if log_file.exists():
            log_file.write_text("")  # Truncate log file

    # Console Handler with Colors
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(ColorFormatter())
    logger.addHandler(console_handler)

    # File Handler with Rotation
    # Rotate after 5MB, keep 5 backup files
    file_handler = RotatingFileHandler(
        LOGS_DIR / "app.log", 
        maxBytes=5*1024*1024, 
        backupCount=5, 
        encoding="utf-8"
    )
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    ))
    logger.addHandler(file_handler)

    return logger

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
