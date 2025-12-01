import logging
import sys
import time
from functools import wraps
from pathlib import Path
from typing import Callable, Any

# Create logs directory if it doesn't exist
LOGS_DIR = Path("logs")
LOGS_DIR.mkdir(exist_ok=True)

def setup_logger(name: str = "ai_interview_prep", log_level: int = logging.INFO) -> logging.Logger:
    """
    Sets up a logger with console and file handlers.
    """
    logger = logging.getLogger(name)
    logger.setLevel(log_level)

    # Prevent adding handlers multiple times
    if logger.hasHandlers():
        return logger

    # Formatter
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Console Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File Handler
    file_handler = logging.FileHandler(LOGS_DIR / "app.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger

logger = setup_logger()

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

def log_async_execution_time(func: Callable[..., Any]) -> Callable[..., Any]:
    """
    Decorator to log the execution time of an async function.
    """
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
