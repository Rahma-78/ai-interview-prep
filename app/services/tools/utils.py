from __future__ import annotations
import asyncio
import logging
import random
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Callable, TypeVar, Any

from google.api_core.exceptions import (
    ResourceExhausted,
    ServiceUnavailable,
    TooManyRequests,
    InternalServerError
)

from app.core.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T")

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
            'gemini': settings.GEMINI_RPM,
            'openrouter': requests_per_minute,
            'groq': requests_per_minute
        }
        self.request_times: List[tuple] = []  # Store (datetime, service) tuples
        self.quota_exhausted_services: Dict[str, datetime] = {}  # Track quota per service

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

                # --- Quota Check (per service) ---
                if service in self.quota_exhausted_services:
                    quota_until = self.quota_exhausted_services[service]
                    if now < quota_until:
                        wait_seconds = (quota_until - now).total_seconds()
                        logger.info(f"Quota exhausted for {service}. Waiting {wait_seconds:.0f}s...")
                    else:
                        # Quota period expired, reset for this service
                        del self.quota_exhausted_services[service]

                # --- Rate Limit Check ---
                if wait_seconds <= 0 and self.request_times:
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
                            logger.info(f"Rate limit hit for {service}. Waiting {wait_seconds:.1f}s...")

            # --- Wait or Break ---
            if wait_seconds <= 0:
                break

            # Sleep outside of lock to avoid blocking other tasks
            await asyncio.sleep(wait_seconds)

    async def mark_quota_exhausted(self, service: str, retry_after_seconds: int = 60):
        """
        Marks the API quota as exhausted for a specific service (async-safe).

        Args:
            service: The service name to mark as exhausted.
            retry_after_seconds: Number of seconds to wait before allowing requests again.
        """
        # Use 'async with' for simple, atomic state changes
        async with self.lock:
            self.quota_exhausted_services[service] = datetime.now() + timedelta(
                seconds=retry_after_seconds
            )
            # Optionally clear request times for this service
            self.request_times = [(t, s) for t, s in self.request_times if s != service]

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


# Global instance
async_rate_limiter = AsyncRateLimiter(requests_per_minute=settings.REQUESTS_PER_MINUTE)


async def execute_with_retry(
    func: Callable[..., Any],
    *args,
    service_name: str = 'default',
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    min_quota_delay: float = 30.0,
    fail_fast: bool = False,
    rate_limiter: Optional[AsyncRateLimiter] = None,
    **kwargs
) -> Any:
    """
    Executes an async function with rate limiting and exponential backoff retry logic.
    Handles specific Google Cloud API exceptions.

    Args:
        func: The async function to execute.
        *args: Positional arguments for the function.
        service_name: Name of the service for rate limiting (e.g., 'gemini').
        max_retries: Maximum number of retries.
        base_delay: Initial delay for backoff in seconds.
        max_delay: Maximum delay for backoff in seconds.
        min_quota_delay: Minimum delay for ResourceExhausted exceptions in seconds.
        fail_fast: If True, reduces retries and delays for user-facing requests.
        rate_limiter: Optional custom AsyncRateLimiter instance. Uses global if None.
        **kwargs: Keyword arguments for the function.

    Returns:
        The result of the function call.

    Raises:
        Exception: The last exception encountered if all retries fail.
    """
    # Adjust retry behavior for fail_fast mode (user-facing requests)
    if fail_fast:
        max_retries = min(max_retries, 1)  # At most 1 retry
        max_delay = min(max_delay, 5.0)    # Cap at 5 seconds
        min_quota_delay = min(min_quota_delay, 3.0)  # Reduce quota delay
    
    # Use provided rate limiter or fall back to global
    limiter = rate_limiter if rate_limiter is not None else async_rate_limiter
    last_exception = None

    for attempt in range(max_retries + 1):
        try:
            # 1. Wait for rate limit slot
            await limiter.wait_if_needed(service_name)

            # 2. Record request attempt
            await limiter.record_request(service_name)

            # 3. Execute function
            return await func(*args, **kwargs)

        except (ResourceExhausted, TooManyRequests) as e:
            last_exception = e
            logger.warning(f"Rate limit/Quota exceeded for {service_name} (Attempt {attempt + 1}/{max_retries + 1}): {e}")
            
            if attempt < max_retries:
                # Try to extract Retry-After from exception metadata
                retry_after = _extract_retry_after(e)
                
                if retry_after is not None:
                    # Use the server's recommended delay
                    delay = min(retry_after, max_delay)
                    logger.info(f"Using Retry-After header: {delay:.1f}s")
                else:
                    # Fallback to exponential backoff with jitter
                    delay = min(base_delay * (2 ** attempt) + random.uniform(0, 1), max_delay)
                
                # Apply minimum quota delay for ResourceExhausted
                if isinstance(e, ResourceExhausted):
                    delay = max(delay, min_quota_delay)
                    await limiter.mark_quota_exhausted(service_name, int(delay))
                
                logger.info(f"Retrying in {delay:.2f}s...")
                await asyncio.sleep(delay)
            else:
                logger.error(f"Max retries reached for {service_name}. Last error: {e}")
                raise

        except (ServiceUnavailable, InternalServerError) as e:
            last_exception = e
            logger.warning(f"Service error for {service_name} (Attempt {attempt + 1}/{max_retries + 1}): {e}")
            
            if attempt < max_retries:
                delay = min(base_delay * (2 ** attempt) + random.uniform(0, 1), max_delay)
                logger.info(f"Retrying in {delay:.2f}s...")
                await asyncio.sleep(delay)
            else:
                raise

        except Exception as e:
            # Non-retriable exception
            logger.error(f"Non-retriable error in {service_name}: {e}")
            raise e

    if last_exception:
        raise last_exception


def _extract_retry_after(exception) -> Optional[float]:
    """
    Extracts the Retry-After value from a Google API exception.
    
    Args:
        exception: The exception object from Google API.
    
    Returns:
        The retry-after delay in seconds, or None if not found.
    """
    try:
        # Google API exceptions may have response metadata
        if hasattr(exception, 'response') and exception.response is not None:
            # Check for Retry-After header
            headers = getattr(exception.response, 'headers', {})
            retry_after = headers.get('Retry-After') or headers.get('retry-after')
            
            if retry_after:
                # Can be an integer (seconds) or HTTP date
                try:
                    return float(retry_after)
                except ValueError:
                    # If it's a date string, we'd need to parse it
                    # For now, return None and use fallback
                    pass
        
        # Check metadata attribute (some Google exceptions use this)
        if hasattr(exception, 'metadata'):
            metadata = exception.metadata
            if isinstance(metadata, dict):
                retry_after = metadata.get('retry-after-ms')
                if retry_after:
                    return float(retry_after) / 1000.0  # Convert ms to seconds
                    
    except Exception as parse_error:
        logger.debug(f"Could not parse Retry-After from exception: {parse_error}")
    
    return None
