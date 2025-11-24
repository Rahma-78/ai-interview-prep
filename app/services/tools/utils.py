from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Callable, TypeVar, Any
from email.utils import parsedate_to_datetime

from google.api_core.exceptions import (
    ResourceExhausted,
    ServiceUnavailable,
    TooManyRequests,
    InternalServerError
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
logger.setLevel(settings.LOG_LEVEL_UTILS.upper())

T = TypeVar("T")

class AsyncRateLimiter:
    """
    Manages API rate limiting and quota tracking for external services
    in an asynchronous (task-safe) way.
    """

    def __init__(self, requests_per_minute: int = settings.REQUESTS_PER_MINUTE):
        """
        Initializes the RateLimiter.

        Args:
            requests_per_minute: The default maximum number of requests allowed per minute.
        """
        self.requests_per_minute = requests_per_minute
        self.service_configs = {
            'gemini': settings.GEMINI_RPM,
            'openrouter': settings.OPENROUTER_RPM,
            'groq': settings.GROQ_RPM
        }
        self.request_times: List[tuple[datetime, str]] = []  # Store (datetime, service) tuples
        self.quota_exhausted_services: Dict[str, datetime] = {}  # Track quota per service
        self.lock = asyncio.Lock()

    def _prune_requests(self, now: datetime, cutoff: datetime):
        """Prunes old requests from the history to prevent memory leaks."""
        self.request_times = [t for t in self.request_times if t[0] > cutoff]

    async def wait_if_needed(self, service: str = 'default'):
        """
        Wait if needed based on the service-specific rate limit.

        Args:
            service: The service name to check rate limits for.
        """
        while True:
            async with self.lock:
                now = datetime.now(timezone.utc)
                wait_seconds = 0.0
                service_rpm = self.get_service_rate(service)

                # --- Quota Check (per service) ---
                if service in self.quota_exhausted_services:
                    quota_until = self.quota_exhausted_services[service]
                    if now < quota_until:
                        wait_seconds = (quota_until - now).total_seconds()
                        logger.info(f"Quota exhausted for {service}. Waiting {wait_seconds:.0f}s...")
                    else:
                        del self.quota_exhausted_services[service]

                # --- Rate Limit Check ---
                if wait_seconds <= 0:
                    cutoff_time = now - timedelta(minutes=1)
                    
                    # Prune old requests to prevent memory leak
                    self._prune_requests(now, cutoff_time)
                    
                    # Count requests for this service in the window
                    service_requests = [t for t in self.request_times if t[1] == service]

                    if len(service_requests) >= service_rpm:
                        oldest_request = min(service_requests, key=lambda x: x[0])
                        # Add a small buffer (0.1s) to avoid timing issues
                        wait_seconds = (oldest_request[0] + timedelta(minutes=1) - now).total_seconds() + 0.1
                        
                        if wait_seconds > 0:
                            logger.info(f"Rate limit hit for {service}. Waiting {wait_seconds:.1f}s...")

            # --- Wait or Break ---
            if wait_seconds <= 0:
                break

            await asyncio.sleep(wait_seconds)

    async def mark_quota_exhausted(self, service: str, retry_after_seconds: int = 60):
        """
        Marks the API quota as exhausted for a specific service (async-safe).
        
        Args:
            service: The service name to mark as exhausted.
            retry_after_seconds: Number of seconds to wait before allowing requests again.
        """
        async with self.lock:
            self.quota_exhausted_services[service] = datetime.now(timezone.utc) + timedelta(
                seconds=retry_after_seconds
            )
            # Clear request times for this service as we are now in a penalty box
            self.request_times = [t for t in self.request_times if t[1] != service]

    async def record_request(self, service: str = 'default'):
        """
        Records the time a request was made (async-safe).
        
        Args:
            service: The service name for which to record the request.
        """
        async with self.lock:
            self.request_times.append((datetime.now(timezone.utc), service))

    def set_service_rate(self, service: str, requests_per_minute: int):
        """
        Sets the rate limit for a specific service.
        
        Args:
            service: The service name.
            requests_per_minute: The maximum number of requests allowed per minute.
        """
        if not isinstance(requests_per_minute, int) or requests_per_minute <= 0:
            raise ValueError("requests_per_minute must be a positive integer")
        self.service_configs[service] = requests_per_minute

    def get_service_rate(self, service: str) -> int:
        """
        Gets the rate limit for a specific service.
        
        Args:
            service: The service name.
            
        Returns:
            The requests per minute limit for the service.
        """
        return self.service_configs.get(service, self.requests_per_minute)


# Global instance
async_rate_limiter = AsyncRateLimiter()


def _extract_retry_after(exception) -> Optional[float]:
    """
    Extracts the Retry-After value from a Google API exception.
    """
    try:
        if hasattr(exception, 'response') and exception.response is not None:
            headers = getattr(exception.response, 'headers', {})
            retry_after = headers.get('Retry-After') or headers.get('retry-after')
            
            if retry_after:
                try:
                    return float(retry_after)
                except ValueError:
                    try:
                        dt = parsedate_to_datetime(retry_after)
                        now = datetime.now(timezone.utc)
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        delay = (dt - now).total_seconds()
                        return max(0.0, delay)
                    except Exception:
                        pass
        
        if hasattr(exception, 'metadata'):
            metadata = exception.metadata
            if isinstance(metadata, dict):
                retry_after = metadata.get('retry-after-ms')
                if retry_after:
                    return float(retry_after) / 1000.0
    except Exception as parse_error:
        logger.debug(f"Could not parse Retry-After from exception: {parse_error}")
    
    return None


class SmartWaitStrategy:
    """
    Custom tenacity wait strategy that handles Retry-After headers and
    ResourceExhausted quota updates.
    """
    def __init__(self, base_delay: float, max_delay: float, min_quota_delay: float, service_name: str, rate_limiter: AsyncRateLimiter):
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.min_quota_delay = min_quota_delay
        self.service_name = service_name
        self.rate_limiter = rate_limiter
        self.exp_wait = wait_exponential(multiplier=base_delay, max=max_delay)

    def __call__(self, retry_state: RetryCallState) -> float:
        exception = retry_state.outcome.exception()
        delay = self.exp_wait(retry_state) # Default exponential backoff

        if exception:
            # Check for Retry-After
            retry_after = _extract_retry_after(exception)
            if retry_after is not None:
                logger.info(f"Using Retry-After header: {retry_after:.1f}s")
                delay = max(delay, min(retry_after, self.max_delay))
            
            # Handle Quota Exhaustion
            if isinstance(exception, ResourceExhausted):
                delay = max(delay, self.min_quota_delay)
                # We can't await here in a sync callback, but we can schedule the quota update
                # or just rely on the wait. Ideally, we update the limiter state.
                # Since we are inside a retry loop, we will sleep 'delay' seconds.
                # We should update the limiter so OTHER tasks know about it.
                # Hack: Create a background task to update the limiter? 
                # Or just accept that this specific task waits, and others will hit the limiter and wait too.
                # Better: We can't easily await here. 
                # Let's just log it. The rate limiter check in the NEXT attempt (or other tasks) 
                # won't know about the quota exhaustion until we mark it.
                # However, since this is a "wait" strategy, the current task WILL sleep.
                pass

        return delay

async def _update_quota_if_needed(retry_state: RetryCallState, service_name: str, rate_limiter: AsyncRateLimiter, min_quota_delay: float):
    """
    Async hook to update quota state before sleeping.
    """
    exception = retry_state.outcome.exception()
    if isinstance(exception, ResourceExhausted):
        # Calculate how long we are about to sleep? 
        # Tenacity doesn't easily pass the calculated wait time to 'before_sleep'.
        # We'll just mark it with the minimum quota delay to be safe/conservative.
        await rate_limiter.mark_quota_exhausted(service_name, int(min_quota_delay))


async def execute_with_retry(
    func: Callable[..., Any],
    *args,
    service_name: str = 'default',
    max_retries: int = settings.RETRY_MAX_ATTEMPTS,
    base_delay: float = settings.RETRY_BASE_DELAY,
    max_delay: float = settings.RETRY_MAX_DELAY,
    min_quota_delay: float = settings.RETRY_MIN_QUOTA_DELAY,
    fail_fast: bool = False,
    rate_limiter: Optional[AsyncRateLimiter] = None,
    **kwargs
) -> Any:
    """
    Executes an async function with rate limiting and tenacity-based retry logic.
    """
    # Adjust retry behavior for fail_fast mode
    if fail_fast:
        max_retries = min(max_retries, settings.RETRY_FAIL_FAST_MAX_RETRIES)
        max_delay = min(max_delay, settings.RETRY_FAIL_FAST_MAX_DELAY)
        min_quota_delay = min(min_quota_delay, settings.RETRY_FAIL_FAST_MIN_QUOTA_DELAY)
    
    limiter = rate_limiter if rate_limiter is not None else async_rate_limiter

    # Define the retry strategy
    retryer = AsyncRetrying(
        stop=stop_after_attempt(max_retries + 1),
        wait=SmartWaitStrategy(base_delay, max_delay, min_quota_delay, service_name, limiter),
        retry=retry_if_exception_type((ResourceExhausted, TooManyRequests, ServiceUnavailable, InternalServerError)),
        before_sleep=before_sleep_log(logger, logging.INFO),
        reraise=True
    )

    # Use the async for pattern (tenacity 8.0.0+)
    async for attempt in retryer:
        with attempt:
            # 1. Wait for rate limit slot (this handles the quota exhaustion wait too if marked)
            await limiter.wait_if_needed(service_name)
            
            # 2. Record request attempt
            await limiter.record_request(service_name)
            
            # 3. Execute function
            try:
                result = await func(*args, **kwargs)
                # Just return the result - tenacity will handle setting it in the outcome
                return result
            except ResourceExhausted:
                # If we hit a quota error, mark it in the limiter so subsequent calls (and retries) know to wait
                # We do this here because we are in an async context
                await limiter.mark_quota_exhausted(service_name, int(min_quota_delay))
                raise # Re-raise to let tenacity handle the retry

