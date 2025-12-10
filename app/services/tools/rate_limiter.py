from __future__ import annotations
import asyncio
import logging
import re
from collections import deque, defaultdict
from datetime import datetime, timezone, timedelta
from typing import Callable, Any, Dict, Optional, Tuple

from google.api_core.exceptions import (
    ResourceExhausted, ServiceUnavailable, TooManyRequests, InternalServerError
)
try:
    from google.genai.errors import ClientError as GeminiClientError, ServerError
    GEMINI_ERRORS_AVAILABLE = True
except ImportError:
    GEMINI_ERRORS_AVAILABLE = False
    GeminiClientError = None
    ServerError = None

from app.core.config import settings

logger = logging.getLogger(__name__)

# Error message constants
ERR_QUOTA_EXHAUSTED = "quota exhausted"
ERR_MODEL_OVERLOADED = "model overloaded"
ERR_BILLING_REQUIRED = "billing/plan upgrade required"

class ServiceRateLimiter:
    """
    Simple rate limiter handling RPM limits.
    """
    def __init__(self):
        # RPM tracking (sliding window - last 1 minute)
        self._services: Dict[str, deque] = defaultdict(deque)
        self._rpm_limits = {
            'gemini': settings.GEMINI_RPM,
            'groq': settings.GROQ_RPM,
            'default': settings.GEMINI_RPM
        }
        self._lock = asyncio.Lock()

    async def acquire_slot(self, service: str) -> None:
        """Blocks until a slot is available for the given service (RPM only)."""
        while True:
            async with self._lock:
                wait_time = self._check_rpm(service, datetime.now(timezone.utc))
                if wait_time == 0:
                    return

            if wait_time > 0:
                await asyncio.sleep(wait_time)

    def _check_rpm(self, service: str, now: datetime) -> float:
        """Check RPM limits and return wait time if needed."""
        history = self._services[service]
        limit = self._rpm_limits.get(service, self._rpm_limits['default'])

        # Cleanup old requests
        while history and history[0] < now - timedelta(minutes=1):
            history.popleft()

        # Check limit
        if len(history) >= limit:
            wait_time = (history[0] + timedelta(minutes=1) - now).total_seconds()
            if wait_time > 0:
                logger.debug(f"RPM limit for {service}. Waiting {wait_time:.2f}s")
                return wait_time
        
        history.append(now)
        return 0.0

# Global Instance
rate_limiter = ServiceRateLimiter()

def parse_retry_after(exception: Exception) -> float:
    """Extracts wait time from API error responses."""
    try:
        # 1. Standard Retry-After header
        if hasattr(exception, 'response') and exception.response:
            headers = getattr(exception.response, 'headers', {})
            val = headers.get('Retry-After') or headers.get('retry-after')
            if val:
                if val.isdigit(): return float(val)
                return (parsedate_to_datetime(val) - datetime.now(timezone.utc)).total_seconds()
        
        # 2. Extract from error string/message (covers most Gemini/Groq cases)
        # Matches: "retry in 5s", "retryDelay: '5s'"
        error_str = str(exception)
        if match := re.search(r'(?:retry in|retryDelay\D+)([\d.]+)s?', error_str, re.IGNORECASE):
            return float(match.group(1))

    except Exception:
        pass
    return 0.0

def _is_hard_quota_error(error_msg: str) -> bool:
    """Check if error indicates a hard billing quota that requires manual intervention."""
    return any(k in error_msg for k in ['upgrade your plan', 'enable billing', 'billing must be enabled'])

async def safe_api_call(
    func: Callable[..., Any],
    *args,
    service: str = 'default',
    **kwargs
) -> Any:
    """
    Unified API call wrapper with rate limiting and retry logic.
    """
    max_retries = settings.RETRY_MAX_ATTEMPTS
    
    # Define retryable exceptions
    retryable = (ResourceExhausted, TooManyRequests, ServiceUnavailable, InternalServerError)
    if GEMINI_ERRORS_AVAILABLE:
        retryable += (GeminiClientError,)

    for attempt in range(max_retries + 1):
        try:
            await rate_limiter.acquire_slot(service)
            return await func(*args, **kwargs)
            
        except retryable as e:
            error_msg = str(e).lower()
            
            # Fail fast on hard quotas
            if _is_hard_quota_error(error_msg):
                logger.error(f"Hard quota exhausted for {service}: {str(e)[:200]}")
                raise RuntimeError(ERR_BILLING_REQUIRED) from e
                
            # Fail fast on quota exhausted (runtime) - enhanced detection
            # Check for Gemini's actual error patterns:
            # - "RESOURCE_EXHAUSTED" status
            # - "exceeded your current quota" message
            # - 429 status code
            if any(pattern in error_msg for pattern in [
                "resource_exhausted", 
                "exceeded your current quota",
                "quota exceeded",
                "429"
            ]):
                logger.error(f"Quota exhausted for {service} - failing fast")
                raise
            
            # Stop if max retries reached
            if attempt == max_retries:
                logger.error(f"Max retries reached for {service}: {e}")
                raise

            # Calculate delay
            delay = parse_retry_after(e)
            if delay == 0:
                delay = min(settings.RETRY_BASE_DELAY * (2 ** attempt), settings.RETRY_MAX_DELAY)
            
            logger.warning(f"Retrying {service} in {delay:.1f}s (Attempt {attempt+1}) due to: {type(e).__name__}")
            await asyncio.sleep(delay)
            
        except Exception as e:
            # Handle Gemini 503 specifically (SDK often raises it wrapped)
            if GEMINI_ERRORS_AVAILABLE and isinstance(e, ServerError):
                 if "503" in str(e) and "overloaded" in str(e).lower():
                     raise RuntimeError(ERR_MODEL_OVERLOADED) from e
            
            logger.error(f"Non-retryable error for {service}: {e}")
            raise

