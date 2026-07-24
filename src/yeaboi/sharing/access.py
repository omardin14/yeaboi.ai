"""Shared access credentials and brute-force protection for browser sharing."""

from __future__ import annotations

import secrets
import threading
import time
from collections.abc import Callable

_JOIN_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def make_token() -> str:
    """Return a fresh ~128-bit URL-safe access token."""
    return secrets.token_urlsafe(16)


def make_join_code() -> str:
    """Return an unambiguous, human-typable ``XXXX-XXXX`` access code."""
    raw = "".join(secrets.choice(_JOIN_ALPHABET) for _ in range(8))
    return f"{raw[:4]}-{raw[4:]}"


class JoinLimiter:
    """Thread-safe failed-code throttle shared by Retro and static output sharing."""

    _MAX_FAILS = 8
    _LOCKOUT_S = 300.0

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._lock = threading.Lock()
        self._fails: dict[str, tuple[int, float]] = {}
        self._clock = clock

    def blocked(self, ip: str) -> bool:
        with self._lock:
            entry = self._fails.get(ip)
            if entry is None:
                return False
            count, first = entry
            if count < self._MAX_FAILS:
                return False
            if self._clock() - first < self._LOCKOUT_S:
                return True
            del self._fails[ip]
            return False

    def record_failure(self, ip: str) -> None:
        with self._lock:
            count, first = self._fails.get(ip, (0, self._clock()))
            if self._clock() - first >= self._LOCKOUT_S:
                count, first = 0, self._clock()
            self._fails[ip] = (count + 1, first)

    def record_success(self, ip: str) -> None:
        with self._lock:
            self._fails.pop(ip, None)
