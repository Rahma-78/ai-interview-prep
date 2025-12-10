from __future__ import annotations
import asyncio
import logging
import re
from collections import deque, defaultdict
from datetime import datetime, timezone, timedelta
from typing import Callable, Any, Dict
from email.utils import parsedate_to_datetime

from google.api_core.exceptions import (
    ResourceExhausted, ServiceUnavailable, TooManyRequests, InternalServerError
)
try:
    from google.genai.errors import ClientError as GeminiClientError
except ImportError:
    GeminiClientError = None

from app.core.config import settings

logger = logging.getLogger(__name__)


class ServiceRateLimiter:
    """
    Simple rate limiter handling RPM and daily quotas.
    """
    def __init__(self):
        # RPM tracking (sliding window - last 1 minute)
        self._services: Dict[str, deque] = defaultdict(deque)
        self._rpm_limits = {
            'gemini': settings.GEMINI_RPM,
            'groq': settings.GROQ_RPM,
            'openrouter': settings.OPENROUTER_RPM,
            'default': settings.GEMINI_RPM
        }
        
        # Daily quota tracking (sliding window - last 24 hours)
        self._daily_usage: Dict[str, deque] = defaultdict(deque)
        self._daily_limits = {
            'gemini': settings.GEMINI_DAILY_LIMIT,
            'groq': settings.GROQ_DAILY_LIMIT,
        }
        
        # Concurrency semaphores for controlled parallelism (DRY: single initialization point)
        self._semaphores: Dict[str, asyncio.Semaphore] = {
            'openrouter': asyncio.Semaphore(settings.MAX_CONCURRENT_QUESTION_GEN),
        }
        
        self._lock = asyncio.Lock()

    async def acquire_slot(self, service: str):
        """Blocks until a slot is available for the given service."""
        while True:
            async with self._lock:
                now = datetime.now(timezone.utc)
                
                # Check daily quota first
                wait_time = self._check_daily_quota(service, now)
                if wait_time == 0:
                    # Check RPM and acquire
                    wait_time = self._check_rpm_and_acquire(service, now)
                    if wait_time == 0:
                        return  # Successfully acquired

            # Sleep outside the lock
            if wait_time > 0:
                await asyncio.sleep(wait_time)

    def _check_daily_quota(self, service: str, now: datetime) -> float:
        """Check daily quota limits. Raises error if exhausted."""
        if service not in self._daily_limits:
            return 0.0

        daily_history = self._daily_usage[service]
        daily_limit = self._daily_limits[service]
        
        # Remove requests older than 24 hours
        while daily_history and daily_history[0] < now - timedelta(hours=24):
            daily_history.popleft()
        
        # Check if quota exhausted
        if len(daily_history) >= daily_limit:
            oldest_request_expires_at = daily_history[0] + timedelta(hours=24)
            wait_seconds = (oldest_request_expires_at - now).total_seconds()
            
            if wait_seconds > 0:
                logger.error(
                    f"Daily quota EXHAUSTED for {service}! "
                    f"({len(daily_history)}/{daily_limit} used). "
                    f"Next slot available in {wait_seconds/3600:.1f} hours."
                )
                raise RuntimeError(
                    f"Daily quota exhausted for {service}. "
                    f"Used {len(daily_history)}/{daily_limit} requests in last 24h. "
                    f"Quota resets in {wait_seconds/3600:.1f} hours."
                )
        return 0.0

    def _check_rpm_and_acquire(self, service: str, now: datetime) -> float:
        """Check RPM limits and acquire slot if available."""
        history = self._services[service]
        limit = self._rpm_limits.get(service, self._rpm_limits['default'])

        # Remove requests older than 1 minute
        while history and history[0] < now - timedelta(minutes=1):
            history.popleft()

        # If full, wait for the oldest request to expire
        if len(history) >= limit:
            wait_time = (history[0] + timedelta(minutes=1) - now).total_seconds()
            if wait_time > 0:
                logger.info(f"RPM limit for {service}. Waiting {wait_time:.2f}s")
                return wait_time
        
        # Record the request
        self._services[service].append(now)
        if service in self._daily_limits:
            self._daily_usage[service].append(now)
        return 0.0

    def get_daily_usage(self, service: str) -> tuple[int, int]:
        """Returns (current_usage, daily_limit) for a service."""
        if service not in self._daily_limits:
            return (0, 0)
        
        now = datetime.now(timezone.utc)
        daily_history = self._daily_usage[service]
        
        # Clean up old entries
        while daily_history and daily_history[0] < now - timedelta(hours=24):
            daily_history.popleft()
        
        return (len(daily_history), self._daily_limits[service])


# Global Instance
rate_limiter = ServiceRateLimiter()


def parse_retry_after(exception: Exception) -> float:
    """
    Extracts wait time from API error responses.
    """
    try:
        # 1. Check Retry-After header
        if hasattr(exception, 'response') and exception.response:
            headers = getattr(exception.response, 'headers', {})
            val = headers.get('Retry-After') or headers.get('retry-after')
            if val:
                if val.isdigit(): 
                    return float(val)
                return (parsedate_to_datetime(val) - datetime.now(timezone.utc)).total_seconds()
        
        # 2. Check Google API metadata
        if hasattr(exception, 'metadata') and isinstance(exception.metadata, dict):
            if ms := exception.metadata.get('retry-after-ms'):
                return float(ms) / 1000.0
        
        # 3. Parse Gemini error message
        error_str = str(exception)
        retry_match = re.search(r'retry in ([\d.]+)s', error_str, re.IGNORECASE)
        if retry_match:
            return float(retry_match.group(1))
        
        # 4. Parse retryDelay from JSON
        delay_match = re.search(r"'retryDelay':\s*'([\d.]+)s'", error_str)
        if delay_match:
            return float(delay_match.group(1))
            
    except Exception:
        pass
    return 0.0


async def safe_api_call(
    func: Callable[..., Any],
    *args,
    service: str = 'default',
    **kwargs
) -> Any:
    """
    Unified API call wrapper with rate limiting, concurrency control, and retry logic.
    
    Follows SOLID: Single responsibility for all API calls, open for extension via semaphores.
    """
    max_retries = settings.RETRY_MAX_ATTEMPTS
    base_delay = settings.RETRY_BASE_DELAY
    max_delay = settings.RETRY_MAX_DELAY
    
    retryable_exceptions = (ResourceExhausted, TooManyRequests, ServiceUnavailable, InternalServerError)
    if GeminiClientError is not None:
        retryable_exceptions = retryable_exceptions + (GeminiClientError,)
    
    # Acquire concurrency semaphore if service has one (SOLID: open/closed principle)
    semaphore = rate_limiter._semaphores.get(service)
    
    async def _execute_with_rate_limit():
        for attempt in range(max_retries):
            try:
                # Acquire rate limit slot
                await rate_limiter.acquire_slot(service)
                
                # Execute the function
                return await func(*args, **kwargs)
                
            except RuntimeError as e:
                # Quota exhausted - fail immediately
                if "quota exhausted" in str(e).lower():
                    logger.error(f"Quota exhausted for {service}: {e}")
                    raise
                raise
                
            except retryable_exceptions as e:
                # Check if this is a hard quota error
                error_message = str(e).lower()
                hard_quota_keywords = ['billing', 'upgrade', 'daily limit']
                is_hard_quota = any(keyword in error_message for keyword in hard_quota_keywords)
                
                if is_hard_quota:
                    logger.error(f"API quota exhausted for {service}: {str(e)[:200]}")
                    raise RuntimeError(
                        f"API quota exhausted for {service}. Check your billing/plan."
                    ) from e
                
                # Last attempt - just raise
                if attempt == max_retries - 1:
                    logger.error(f"Max retries reached for {service}")
                    raise
                
                # Calculate retry delay
                retry_delay = parse_retry_after(e)
                if retry_delay > 0:
                    wait_time = min(retry_delay, max_delay)
                    logger.warning(f"Rate limit for {service}. Retrying in {wait_time:.1f}s (attempt {attempt + 1}/{max_retries})")
                else:
                    # Exponential backoff
                    wait_time = min(base_delay * (2 ** attempt), max_delay)
                    logger.warning(f"Retrying {service} in {wait_time:.1f}s (attempt {attempt + 1}/{max_retries})")
                
                await asyncio.sleep(wait_time)
                
            except Exception as e:
                # Non-retryable error
                logger.error(f"Non-retryable error for {service}: {e}")
                raise
        
        # Should never reach here
        raise RuntimeError(f"Failed after {max_retries} attempts")
    
    # Execute with or without semaphore (DRY: single code path)
    if semaphore:
        async with semaphore:
            return await _execute_with_rate_limit()
    else:
        return await _execute_with_rate_limit()