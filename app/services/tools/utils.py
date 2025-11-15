from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional

"""
Utility functions and classes for the interview preparation tools.

This module provides:
- URL search caching mechanism
- Rate limiting for API calls
- Global configuration constants
"""

# Global cache for URL searches
SEARCH_CACHE: Dict[str, str] = {}


class RateLimiter:
    """
    Manages API rate limiting and quota tracking for external services.
    """

    def __init__(self, requests_per_minute: int = 10):
        """
        Initializes the RateLimiter.

        Args:
            requests_per_minute: The maximum number of requests allowed per minute.
        """
        self.requests_per_minute = requests_per_minute
        self.request_times: List[datetime] = []
        self.quota_exhausted_until: Optional[datetime] = None

    def wait_if_needed(self):
        """
        Pauses execution if the rate limit has been hit or the quota is exhausted.
        """
        now = datetime.now()

        if self.quota_exhausted_until and now < self.quota_exhausted_until:
            wait_seconds = (self.quota_exhausted_until - now).total_seconds()
            logging.info(f"⏳ Quota exhausted. Waiting {wait_seconds:.0f}s...")
            time.sleep(wait_seconds + 1)
            self.quota_exhausted_until = None
            self.request_times = []
            return

        cutoff_time = now - timedelta(minutes=1)
        self.request_times = [t for t in self.request_times if t > cutoff_time]

        if len(self.request_times) >= self.requests_per_minute:
            oldest_request = self.request_times[0]
            wait_time = (oldest_request + timedelta(minutes=1) - now).total_seconds()
            if wait_time > 0:
                logging.info(f" Rate limit approaching. Waiting {wait_time:.1f}s...")
                time.sleep(wait_time)
                self.request_times = []

    def mark_quota_exhausted(self, retry_after_seconds: int = 60):
        """
        Marks the API quota as exhausted.

        Args:
            retry_after_seconds: The number of seconds to wait before retrying.
        """
        self.quota_exhausted_until = datetime.now() + timedelta(
            seconds=retry_after_seconds
        )
        self.request_times = []

    def record_request(self):
        """
        Records the time a request was made to track rate limits.
        """
        self.request_times.append(datetime.now())


# Global rate limiter for search requests
search_rate_limiter = RateLimiter(requests_per_minute=10)
