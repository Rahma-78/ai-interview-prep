from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, Optional, Dict
from app.core.config import settings


async def retry_with_backoff(func, *args, max_retries=None, **kwargs):
    """
    Retry a function with exponential backoff.
    
    Args:
        func: The function to retry
        max_retries: Maximum number of retries (defaults to settings.MAX_RETRIES)
        *args: Positional arguments to pass to func
        **kwargs: Keyword arguments to pass to func
        
    Returns:
        The result of func(*args, **kwargs)
        
    Raises:
        The last exception if all retries fail
    """
    if max_retries is None:
        max_retries = settings.MAX_RETRIES
        
    for attempt in range(max_retries + 1):  # +1 to include the initial attempt
        try:
            return await func(*args, **kwargs)
        except asyncio.TimeoutError as e:
            if attempt == max_retries:
                raise
            
            # Calculate backoff time (exponential with jitter)
            backoff = min(2 ** attempt, 10) + (0.1 * (attempt + 1))
            await asyncio.sleep(backoff)
        except Exception as e:
            # For non-timeout errors, don't retry
            raise

async def call_llm_with_retry(llm_instance, prompt: str, timeout: int) -> str:
    """
    Calls an LLM with a given prompt, timeout, and retry logic.

    Args:
        llm_instance: The LLM instance to use for the call.
        prompt: The prompt to send to the LLM.
        timeout: The timeout for the LLM call.

    Returns:
        The LLM response as a string.
    
    Raises:
        asyncio.TimeoutError: If the call times out after all retries.
    """
    async def make_llm_call():
        return await asyncio.wait_for(
            asyncio.to_thread(
                llm_instance.call,
                messages=[{"role": "user", "content": prompt}]
            ),
            timeout=timeout
        )
    
    response = await retry_with_backoff(make_llm_call)
    return str(response) if response is not None else ""
class AsyncRateLimiter:
    """
    Manages API rate limiting and quota tracking for external services
    in an asynchronous (task-safe) way.
    """

    def __init__(self, requests_per_minute: int = 10):
        """
        Initializes the RateLimiter.

        Args:
            requests_per_minute: The maximum number of requests allowed per minute.
        """
        self.requests_per_minute = requests_per_minute
        self.service_configs = {
            'gemini': requests_per_minute,
            'openrouter': requests_per_minute,
            'groq': requests_per_minute
        }
        self.request_times: List[tuple] = []  # Store (datetime, service) tuples
        self.quota_exhausted_until: Optional[datetime] = None

        # 1. Add an asyncio.Lock for task-safety
        self.lock = asyncio.Lock()

    async def wait_if_needed(self, service: str = 'default'):
        """
        Wait if needed based on the service-specific rate limit.

        Args:
            service: The service name to check rate limits for.
        """
        while True:
            # Calculate wait time with lock held
            async with self.lock:
                now = datetime.now()
                wait_seconds = 0.0
                service_rpm = self.get_service_rate(service)

                # --- Quota Check ---
                if self.quota_exhausted_until and now < self.quota_exhausted_until:
                    wait_seconds = (self.quota_exhausted_until - now).total_seconds()
                    logging.info(f" Quota exhausted. Waiting {wait_seconds:.0f}s...")
                    # Don't reset quota_exhausted_until here - will be reset after wait

                # --- Rate Limit Check ---
                elif self.request_times:
                    cutoff_time = now - timedelta(minutes=1)
                    # Filter all requests by time first to ensure consistency
                    self.request_times = [t for t in self.request_times if t[0] > cutoff_time]
                    # Then filter by service
                    service_requests = [t for t in self.request_times if t[1] == service]

                    if len(service_requests) >= service_rpm:
                        oldest_request = min(service_requests, key=lambda x: x[0])
                        # Add a small buffer (0.1s) to avoid timing issues
                        wait_seconds = (oldest_request[0] + timedelta(minutes=1) - now).total_seconds() + 0.1

                        if wait_seconds > 0:
                            logging.info(f" Rate limit hit for {service}. Waiting {wait_seconds:.1f}s...")

            # --- Wait or Break ---
            if wait_seconds <= 0:
                break

            # Sleep outside of lock to avoid blocking other tasks
            await asyncio.sleep(wait_seconds)

            # After waiting, check if we were waiting due to quota exhaustion
            async with self.lock:
                if self.quota_exhausted_until and datetime.now() >= self.quota_exhausted_until:
                    # Now it's safe to reset quota_exhausted_after
                    self.quota_exhausted_until = None
                    self.request_times = []

    async def mark_quota_exhausted(self, retry_after_seconds: int = 60):
        """
        Marks the API quota as exhausted (async-safe).

        Args:
            retry_after_seconds: Number of seconds to wait before allowing requests again.
        """
        # Use 'async with' for simple, atomic state changes
        async with self.lock:
            self.quota_exhausted_until = datetime.now() + timedelta(
                seconds=retry_after_seconds
            )
            self.request_times = []

    async def record_request(self, service: str = 'default'):
        """
        Records the time a request was made (async-safe).

        Args:
            service: The service name for which to record the request.
        """
        # Use 'async with' for simple, atomic state changes
        async with self.lock:
            self.request_times.append((datetime.now(), service))

    def set_service_rate(self, service: str, requests_per_minute: int):
        """
        Sets the rate limit for a specific service.

        Args:
            service: The service name (e.g., 'gemini', 'openrouter', 'groq').
            requests_per_minute: The maximum number of requests allowed per minute for this service.

        Raises:
            ValueError: If requests_per_minute is not a positive integer.
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


# --- Your new global instance ---
async_rate_limiter = AsyncRateLimiter(requests_per_minute=settings.REQUESTS_PER_MINUTE)
