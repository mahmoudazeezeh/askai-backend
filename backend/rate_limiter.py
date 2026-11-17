"""Per-client and global request limits (cost control)."""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass

from .authentication import Client
from .settings import Settings
from .usage_tracking import UsageTracker


@dataclass
class LimitStatus:
    per_minute: int
    per_day: int
    per_month: int
    used_today: int
    used_month: int

    def as_dict(self) -> dict:
        return {
            "per_minute": self.per_minute,
            "per_day": self.per_day,
            "per_month": self.per_month,
            "used_today": self.used_today,
            "used_month": self.used_month,
            "left_today": max(0, self.per_day - self.used_today),
            "left_month": max(0, self.per_month - self.used_month),
        }


class LimitExceeded(Exception):
    def __init__(self, message: str, retry_after: int):
        super().__init__(message)
        self.retry_after = retry_after


class RateLimiter:
    def __init__(self, settings: Settings, usage: UsageTracker):
        self.s = settings
        self.usage = usage
        self._minute: dict[str, deque] = {}
        self._lock = threading.Lock()

    def limits_for(self, c: Client) -> LimitStatus:
        return LimitStatus(
            per_minute=c.per_minute if c.per_minute is not None else self.s.limit_per_minute,
            per_day=c.per_day if c.per_day is not None else self.s.limit_per_day,
            per_month=c.per_month if c.per_month is not None else self.s.limit_per_month,
            used_today=self.usage.count_today(c.id),
            used_month=self.usage.count_month(c.id),
        )

    def check_and_reserve(self, c: Client) -> LimitStatus:
        st = self.limits_for(c)
        if st.used_today >= st.per_day:
            raise LimitExceeded(f"Daily limit reached ({st.per_day} requests). Try again tomorrow.", 3600)
        if st.used_month >= st.per_month:
            raise LimitExceeded(f"Monthly limit reached ({st.per_month} requests).", 86400)
        if self.usage.count_today_global() >= self.s.global_per_day:
            raise LimitExceeded("The ASKAI service reached its global daily budget. Try again tomorrow.", 3600)
        with self._lock:
            now = time.time()
            q = self._minute.setdefault(c.id, deque())
            while q and now - q[0] >= 60:
                q.popleft()
            if len(q) >= st.per_minute:
                wait = int(60 - (now - q[0])) + 1
                raise LimitExceeded(
                    f"Too many requests: at most {st.per_minute} per minute. Wait {wait} s.", wait)
            q.append(now)
        return st
