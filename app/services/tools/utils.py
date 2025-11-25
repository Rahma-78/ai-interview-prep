from __future__ import annotations
import asyncio
import logging
from collections import deque, defaultdict
from datetime import datetime, timezone, timedelta
from typing import Optional, Callable, Any, Dict
from email.utils import parsedate_to_datetime

from google.api_core.exceptions import (
    ResourceExhausted, ServiceUnavailable, TooManyRequests, InternalServerError
)
from tenacity import (
    AsyncRetrying,
    RetryCallState,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log
)

from app.core.config import settings

logger = logging.getLogger(__name__)

# --- 1. The Clean Rate Limiter (Prevention) ---
class ServiceRateLimiter:
    """
    Strictly handles Local RPM (Requests Per Minute).
    Does NOT handle retries or errors. just counts.
    """
    def __init__(self):
        self._services: Dict[str, deque] = defaultdict(deque)
        self._limits = {
            'gemini': settings.GEMINI_RPM,
            'openrouter': settings.OPENROUTER_RPM,
            'default': settings.REQUESTS_PER_MINUTE
        }
        self._lock = asyncio.Lock()
        # "Penalty Box" - stores end_time if a service is blocked
        self._blocked_until: Dict[str, datetime] = {}

    async def acquire_slot(self, service: str):
        """Blocks until a slot is available for the given service."""
        async with self._lock:
            now = datetime.now(timezone.utc)
            
            # 1. Check Penalty Box (Global Hold)
            if service in self._blocked_until:
                if now < self._blocked_until[service]:
                    wait_time = (self._blocked_until[service] - now).total_seconds()
                    logger.warning(f"Service {service} is blocked. Waiting {wait_time:.1f}s...")
                    await asyncio.sleep(wait_time)
                else:
                    del self._blocked_until[service] # Release block

            # 2. Check RPM (Sliding Window)
            history = self._services[service]
            limit = self._limits.get(service, self._limits['default'])

            # Remove requests older than 1 minute
            while history and history[0] < now - timedelta(minutes=1):
                history.popleft()

            # If full, wait for the oldest request to expire
            if len(history) >= limit:
                wait_time = (history[0] + timedelta(minutes=1) - now).total_seconds()
                if wait_time > 0:
                    logger.info(f"Local RPM limit for {service}. Sleeping {wait_time:.2f}s")
                    await asyncio.sleep(wait_time)
            
            # Record this new request
            self._services[service].append(datetime.now(timezone.utc))

    async def block_service(self, service: str, seconds: float):
        """Manually blocks a service (used when we hit a 429/Quota error)."""
        async with self._lock:
            logger.error(f"Blocking {service} for {seconds}s due to API rejection.")
            self._blocked_until[service] = datetime.now(timezone.utc) + timedelta(seconds=seconds)

# Global Instance
rate_limiter = ServiceRateLimiter()


# --- 2. The Smart Wait Logic (The Cure) ---
def parse_retry_after(exception: Exception) -> float:
    """Extracts wait time from API headers, defaulting to 0 if not found."""
    try:
        # Check standard Retry-After header
        if hasattr(exception, 'response') and exception.response:
            headers = getattr(exception.response, 'headers', {})
            val = headers.get('Retry-After') or headers.get('retry-after')
            if val:
                if val.isdigit(): return float(val)
                return (parsedate_to_datetime(val) - datetime.now(timezone.utc)).total_seconds()
        
        # Check Google Metadata
        if hasattr(exception, 'metadata') and isinstance(exception.metadata, dict):
             if ms := exception.metadata.get('retry-after-ms'):
                 return float(ms) / 1000.0
    except Exception:
        pass
    return 0.0

def custom_wait_generator(retry_state: RetryCallState) -> float:
    """
    Calculates how long to wait. 
    Prioritizes server headers -> then exponential backoff.
    """
    exc = retry_state.outcome.exception()
    
    # 1. Ask the server: "How long should I wait?"
    server_wait = parse_retry_after(exc)
    if server_wait > 0:
        return min(server_wait, settings.RETRY_MAX_DELAY)
    
    # 2. If server didn't say, use Exponential Backoff
    exp_wait = wait_exponential(
        multiplier=settings.RETRY_BASE_DELAY, 
        max=settings.RETRY_MAX_DELAY
    )(retry_state)
    
    return exp_wait


# --- 3. The Unified Wrapper ---
async def safe_api_call(
    func: Callable[..., Any],
    *args,
    service: str = 'default',
    **kwargs
) -> Any:
    """
    The only function you call. Handles locking -> executing -> catching -> retrying.
    """
    
    # Define retry logic
    retryer = AsyncRetrying(
        stop=stop_after_attempt(settings.RETRY_MAX_ATTEMPTS),
        wait=custom_wait_generator, # Uses our clean wait logic
        retry=retry_if_exception_type((ResourceExhausted, TooManyRequests, ServiceUnavailable, InternalServerError)),
        before_sleep=before_sleep_log(logger, logging.INFO),
        reraise=True
    )

    async for attempt in retryer:
        with attempt:
            # STEP A: Check Permissions (Local Rate Limit)
            # We do this BEFORE every attempt.
            await rate_limiter.acquire_slot(service)

            try:
                # STEP B: Execute
                return await func(*args, **kwargs)
            
            except (ResourceExhausted, TooManyRequests) as e:
                # STEP C: Handle Rejection (Update Global State)
                # If we crashed, we must tell the limiter to stop EVERYONE else.
                wait_time = parse_retry_after(e) or settings.RETRY_MIN_QUOTA_DELAY
                await rate_limiter.block_service(service, wait_time)
                
                # Now raise the error so Tenacity handles the actual retry sleep
                raise e