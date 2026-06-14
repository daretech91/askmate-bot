"""
rate_limiter.py — In-memory sliding-window rate limiter per user.
Limits requests to max_requests within window_seconds.
"""

import time
from collections import defaultdict, deque
from threading import Lock


class RateLimiter:
    def __init__(self, max_requests: int = 10, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._windows: dict[int, deque] = defaultdict(deque)
        self._lock = Lock()

    def check(self, user_id: int) -> tuple[bool, int]:
        """
        Returns (allowed, retry_after_seconds).
        allowed=True if under limit, False if rate limited.
        """
        now = time.monotonic()
        cutoff = now - self.window_seconds

        with self._lock:
            window = self._windows[user_id]

            # Evict timestamps outside the window
            while window and window[0] < cutoff:
                window.popleft()

            if len(window) >= self.max_requests:
                # Time until the oldest request falls outside the window
                retry_after = int(self.window_seconds - (now - window[0])) + 1
                return False, retry_after

            window.append(now)
            return True, 0
