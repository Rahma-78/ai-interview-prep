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
    Handles both RPM (Requests Per Minute) and daily quota limits.
    Prevents hitting hard API quota limits like Gemini's 20 requests/day.
    """
    def __init__(self):
        # RPM tracking (sliding window - last 1 minute)
        self._services: Dict[str, deque] = defaultdict(deque)
        self._rpm_limits = {
            'gemini': settings.GEMINI_RPM,
            'openrouter': settings.OPENROUTER_RPM,
            'groq': settings.GROQ_RPM
        }
        
        # Daily quota tracking (sliding window - last 24 hours)
        self._daily_usage: Dict[str, deque] = defaultdict(deque)
        self._daily_limits = {
            'gemini': settings.GEMINI_DAILY_LIMIT,
            'openrouter': settings.OPENROUTER_DAILY_LIMIT,
            'groq': settings.GROQ_DAILY_LIMIT,
        }
        
        self._lock = asyncio.Lock()
        # "Penalty Box" - stores end_time if a service is blocked
        self._blocked_until: Dict[str, datetime] = {}

    async def acquire_slot(self, service: str):
        """Blocks until a slot is available for the given service."""
        while True:
            wait_time = 0.0
            
            async with self._lock:
                now = datetime.now(timezone.utc)
                
                # 1. Check Penalty Box (Global Hold)
                if service in self._blocked_until:
                    if now < self._blocked_until[service]:
                        wait_time = (self._blocked_until[service] - now).total_seconds()
                        logger.warning(f"Service {service} is blocked. Waiting {wait_time:.1f}s...")
                    else:
                        del self._blocked_until[service]  # Release block

                # 2. Check Daily Quota (if service has a daily limit)
                if wait_time == 0 and service in self._daily_limits:
                    daily_history = self._daily_usage[service]
                    daily_limit = self._daily_limits[service]
                    
                    # Remove requests older than 24 hours
                    while daily_history and daily_history[0] < now - timedelta(hours=24):
                        daily_history.popleft()
                    
                    # Check if we've hit the daily quota
                    if len(daily_history) >= daily_limit:
                        # Calculate when the oldest request will expire
                        oldest_request_expires_at = daily_history[0] + timedelta(hours=24)
                        wait_seconds = (oldest_request_expires_at - now).total_seconds()
                        
                        if wait_seconds > 0:
                            logger.error(
                                f"❌ Daily quota EXHAUSTED for {service}! "
                                f"({len(daily_history)}/{daily_limit} used). "
                                f"Next slot available in {wait_seconds/3600:.1f} hours."
                            )
                            # Don't wait here - raise an exception instead
                            raise RuntimeError(
                                f"Daily quota exhausted for {service}. "
                                f"Used {len(daily_history)}/{daily_limit} requests in last 24h. "
                                f"Quota resets in {wait_seconds/3600:.1f} hours."
                            )

                # 3. Check RPM (Sliding Window)
                if wait_time == 0:
                    history = self._services[service]
                    limit = self._rpm_limits.get(service, self._rpm_limits['default'])

                    # Remove requests older than 1 minute
                    while history and history[0] < now - timedelta(minutes=1):
                        history.popleft()

                    # If full, wait for the oldest request to expire
                    if len(history) >= limit:
                        wait_time = (history[0] + timedelta(minutes=1) - now).total_seconds()
                        if wait_time > 0:
                            logger.info(f"Local RPM limit for {service}. Sleeping {wait_time:.2f}s")
                    else:
                        # Success! Record and return
                        self._services[service].append(now)
                        # Also track for daily quota
                        if service in self._daily_limits:
                            self._daily_usage[service].append(now)
                        return

            # If we need to wait, sleep OUTSIDE the lock
            if wait_time > 0:
                await asyncio.sleep(wait_time)
                # Loop back and try again

    async def block_service(self, service: str, seconds: float):
        """Manually blocks a service (used when we hit a 429/Quota error)."""
        async with self._lock:
            logger.error(f"Blocking {service} for {seconds}s due to API rejection.")
            self._blocked_until[service] = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    
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
    Fails fast on quota exhaustion (don't retry quota errors).
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
            # STEP A: Check Permissions (Local Rate Limit + Daily Quota)
            # We do this BEFORE every attempt.
            try:
                await rate_limiter.acquire_slot(service)
            except RuntimeError as quota_error:
                # Daily quota exhausted - fail immediately without retrying
                logger.error(f"🚫 Quota exhaustion detected: {quota_error}")
                raise quota_error

            try:
                # STEP B: Execute
                return await func(*args, **kwargs)
            
            except (ResourceExhausted, TooManyRequests) as e:
                # STEP C: Detect if this is a quota error or a transient rate limit
                error_message = str(e).lower()
                
                # Quota error keywords that indicate hard quota limits (not transient)
                quota_keywords = ['quota', 'daily', 'limit exceeded', 'billing', 'plan']
                is_quota_error = any(keyword in error_message for keyword in quota_keywords)
                
                if is_quota_error:
                    # Hard quota limit - fail immediately
                    logger.error(
                        f"🚫 API quota exhausted for {service}. "
                        f"Error: {str(e)[:200]}... "
                        f"This is a hard limit that won't resolve with retries."
                    )
                    # Re-raise as a RuntimeError to skip retry logic
                    raise RuntimeError(
                        f"API quota exhausted for {service}. Check your billing/plan. "
                        f"Original error: {str(e)[:300]}"
                    ) from e
                else:
                    # Transient rate limit - update global state and retry
                    wait_time = parse_retry_after(e) or settings.RETRY_MIN_QUOTA_DELAY
                    await rate_limiter.block_service(service, wait_time)
                    logger.warning(
                        f"⚠️ Transient rate limit for {service}. "
                        f"Will retry after {wait_time}s..."
                    )
                    # Re-raise to trigger retry
                    raise e