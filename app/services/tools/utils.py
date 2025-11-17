from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, Optional, Dict



"""
Utility functions and classes for the interview preparation tools.

This module provides:
- URL search caching mechanism
- Rate limiting for API calls
- Global configuration constants
"""



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
        self.request_times: List[datetime] = []
        self.quota_exhausted_until: Optional[datetime] = None
        
        # 1. Add an asyncio.Lock for task-safety
        self.lock = asyncio.Lock()

    async def wait_if_needed(self):
      
        await self.lock.acquire()
        try:
            while True:
                now = datetime.now()
                wait_seconds = 0.0

                # --- Quota Check ---
                if self.quota_exhausted_until and now < self.quota_exhausted_until:
                    wait_seconds = (self.quota_exhausted_until - now).total_seconds()
                    logging.info(f"⏳ Quota exhausted. Waiting {wait_seconds:.0f}s...")
                    self.quota_exhausted_until = None
                    self.request_times = []

                # --- Rate Limit Check  ---
                else:
                    cutoff_time = now - timedelta(minutes=1)
                    self.request_times = [t for t in self.request_times if t > cutoff_time]

                    if len(self.request_times) >= self.requests_per_minute:
                        oldest_request = self.request_times[0]
                        # Add a small buffer (0.1s) to avoid timing issues
                        wait_seconds = (oldest_request + timedelta(minutes=1) - now).total_seconds() + 0.1
                        
                        if wait_seconds > 0:
                            logging.info(f" Rate limit hit. Waiting {wait_seconds:.1f}s...")
                           

                # --- Wait or Break ---
                if wait_seconds <= 0:
                    break
                
                self.lock.release()
                await asyncio.sleep(wait_seconds)
                await self.lock.acquire()

        finally:
            if self.lock.locked():
                self.lock.release()

    async def mark_quota_exhausted(self, retry_after_seconds: int = 60):
        """
        Marks the API quota as exhausted (async-safe).
        """
        # Use 'async with' for simple, atomic state changes
        async with self.lock:
            self.quota_exhausted_until = datetime.now() + timedelta(
                seconds=retry_after_seconds
            )
            self.request_times = []

    async def record_request(self):
        """
        Records the time a request was made (async-safe).
        """
        # Use 'async with' for simple, atomic state changes
        async with self.lock:
            self.request_times.append(datetime.now())

# --- Your new global instance ---
async_rate_limiter = AsyncRateLimiter(requests_per_minute=10)