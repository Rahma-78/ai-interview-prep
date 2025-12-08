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
# Import Gemini SDK's own error types (different from google.api_core)
try:
    from google.genai.errors import ClientError as GeminiClientError
except ImportError:
    GeminiClientError = None  # Fallback if SDK not installed

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
            'groq': settings.GROQ_RPM,
            'default': settings.GEMINI_RPM  # Default rate limit for unknown services
        }
        
        # Daily quota tracking (sliding window - last 24 hours)
        self._daily_usage: Dict[str, deque] = defaultdict(deque)
        self._daily_limits = {
            'gemini': settings.GEMINI_DAILY_LIMIT,
            'openrouter': settings.OPENROUTER_DAILY_LIMIT,
            'groq': settings.GROQ_DAILY_LIMIT,
        }
        
        # Quota exhaustion flag (fail-fast when quota is definitively exhausted)
        self._quota_exhausted: Dict[str, bool] = defaultdict(bool)
        
        self._lock = asyncio.Lock()
        # "Penalty Box" - stores end_time if a service is blocked
        self._blocked_until: Dict[str, datetime] = {}

    async def acquire_slot(self, service: str):
        """Blocks until a slot is available for the given service."""
        while True:
            wait_time = 0.0
            
            async with self._lock:
                now = datetime.now(timezone.utc)
                
                # Check all constraints
                self._check_quota_exhaustion(service)
                wait_time = self._check_penalty_box(service, now)
                
                if wait_time == 0:
                    wait_time = self._check_daily_quota(service, now)
                
                if wait_time == 0:
                    wait_time = self._check_rpm_and_acquire(service, now)
                    if wait_time == 0:
                         # Successfully acquired
                         return

            # If we need to wait, sleep OUTSIDE the lock
            if wait_time > 0:
                await asyncio.sleep(wait_time)
                # Loop back and try again

    def _check_quota_exhaustion(self, service: str):
        """Fail-fast if quota is exhausted."""
        if self._quota_exhausted.get(service, False):
            raise RuntimeError(
                f"Service {service} quota exhausted by previous API call. "
                f"No more requests will be accepted until quota resets."
            )

    def _check_penalty_box(self, service: str, now: datetime) -> float:
        """Check if service is in penalty box. Returns wait time in seconds."""
        if service in self._blocked_until:
            if now < self._blocked_until[service]:
                wait_time = (self._blocked_until[service] - now).total_seconds()
                logger.warning(f"Service {service} is blocked. Waiting {wait_time:.1f}s...")
                return wait_time
            else:
                del self._blocked_until[service]  # Release block
        return 0.0

    def _check_daily_quota(self, service: str, now: datetime) -> float:
        """Check daily quota limits. Returns wait time or raises error if exhausted."""
        if service not in self._daily_limits:
            return 0.0

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
        return 0.0

    def _check_rpm_and_acquire(self, service: str, now: datetime) -> float:
        """Check RPM limits and acquire slot if available. Returns wait time in seconds."""
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
                return wait_time
        
        # Success! Record and return 0 wait time
        self._services[service].append(now)
        # Also track for daily quota
        if service in self._daily_limits:
            self._daily_usage[service].append(now)
        return 0.0

    async def block_service(self, service: str, seconds: float):
        """Manually blocks a service (used when we hit a 429/Quota error)."""
        async with self._lock:
            logger.error(f"Blocking {service} for {seconds}s due to API rejection.")
            self._blocked_until[service] = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    
    async def mark_quota_exhausted(self, service: str):
        """Mark service as quota-exhausted (fail-fast for all future requests)."""
        async with self._lock:
            self._quota_exhausted[service] = True
            logger.error(
                f"🚫 Service {service} marked as QUOTA EXHAUSTED. "
                f"All future requests will fail immediately until quota resets."
            )

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
    """
    Extracts wait time from API error responses.
    Handles multiple formats:
    - Standard HTTP Retry-After header
    - Google API metadata retry-after-ms
    - Gemini SDK error body retryDelay (e.g., '12s' or '12.5s')
    - Error message "Please retry in X.XXs"
    """
    try:
        # 1. Check standard Retry-After header
        if hasattr(exception, 'response') and exception.response:
            headers = getattr(exception.response, 'headers', {})
            val = headers.get('Retry-After') or headers.get('retry-after')
            if val:
                if val.isdigit(): 
                    return float(val)
                return (parsedate_to_datetime(val) - datetime.now(timezone.utc)).total_seconds()
        
        # 2. Check Google API core metadata
        if hasattr(exception, 'metadata') and isinstance(exception.metadata, dict):
            if ms := exception.metadata.get('retry-after-ms'):
                return float(ms) / 1000.0
        
        # 3. Parse Gemini SDK error message for retry delay
        # Gemini errors contain: "Please retry in 12.579418093s."
        error_str = str(exception)
        retry_match = re.search(r'retry in ([\d.]+)s', error_str, re.IGNORECASE)
        if retry_match:
            retry_seconds = float(retry_match.group(1))
            logger.debug(f"Parsed retry delay from Gemini error: {retry_seconds}s")
            return retry_seconds
        
        # 4. Parse retryDelay from JSON error body (format: '12s' or '12.5s')
        # Gemini errors contain: {'retryDelay': '12s'}
        delay_match = re.search(r"'retryDelay':\s*'([\d.]+)s'", error_str)
        if delay_match:
            retry_seconds = float(delay_match.group(1))
            logger.debug(f"Parsed retryDelay from error body: {retry_seconds}s")
            return retry_seconds
            
    except Exception as e:
        logger.debug(f"Failed to parse retry-after: {e}")
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
    
    # Build list of retryable exceptions (include Gemini SDK errors if available)
    retryable_exceptions = [ResourceExhausted, TooManyRequests, ServiceUnavailable, InternalServerError]
    if GeminiClientError is not None:
        retryable_exceptions.append(GeminiClientError)
    
    # Define retry logic
    retryer = AsyncRetrying(
        stop=stop_after_attempt(settings.RETRY_MAX_ATTEMPTS),
        wait=custom_wait_generator,  # Uses our clean wait logic
        retry=retry_if_exception_type(tuple(retryable_exceptions)),
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
                # STEP C: Handle rate limit errors
                await _handle_rate_limit_error(e, service)
                raise e
            except Exception as e:
                # STEP D: Check if this is a Gemini SDK error (429)
                if GeminiClientError is not None and isinstance(e, GeminiClientError):
                    await _handle_rate_limit_error(e, service)
                    raise e
                # Other exceptions - just re-raise
                raise


async def _handle_rate_limit_error(e: Exception, service: str) -> None:
    """
    Smart handling of rate limit errors:
    - If server provides a short retry delay (< 60s), it's a transient RPM limit -> retry
    - If no retry delay or very long delay, it's likely a hard quota limit -> fail fast
    """
    error_message = str(e).lower()
    retry_delay = parse_retry_after(e)
    
    # Check for hard quota indicators (billing issues, upgrade required, etc.)
    hard_quota_keywords = ['billing', 'upgrade', 'daily limit']
    is_hard_quota = any(keyword in error_message for keyword in hard_quota_keywords)
    
    # Hard quota with no reasonable retry delay -> fail fast
    if is_hard_quota or (retry_delay == 0 and 'quota' in error_message):
        await rate_limiter.mark_quota_exhausted(service)
        logger.error(
            f"🚫 API quota exhausted for {service}. "
            f"Error: {str(e)[:200]}... "
            f"This is a hard limit that won't resolve with retries."
        )
        raise RuntimeError(
            f"API quota exhausted for {service}. Check your billing/plan. "
            f"Original error: {str(e)[:300]}"
        ) from e
    
    # Transient rate limit -> block service and retry after delay
    wait_time = retry_delay if retry_delay > 0 else settings.RETRY_MIN_QUOTA_DELAY
    await rate_limiter.block_service(service, wait_time)
    
    if retry_delay > 0:
        logger.warning(
            f"⚠️ Rate limit for {service}. Server says retry in {wait_time:.1f}s. "
            f"Blocking service and will retry..."
        )
    else:
        logger.warning(
            f"⚠️ Rate limit for {service} (no retry delay specified). "
            f"Using default delay of {wait_time}s..."
        )