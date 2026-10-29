"""Single-user login: one password, a signed session cookie, a global rate limit."""

import hashlib
import hmac
import time
from collections import deque
from threading import Lock

SESSION_DAYS = 30


def sign_session(secret: str, now: float) -> str:
    expires = int(now) + SESSION_DAYS * 86400
    mac = hmac.new(secret.encode(), str(expires).encode(), hashlib.sha256).hexdigest()
    return f"{expires}.{mac}"


def verify_session(secret: str, token: str | None, now: float) -> bool:
    if not token or "." not in token:
        return False
    expires, mac = token.split(".", 1)
    if not expires.isdigit() or int(expires) < now:
        return False
    expected = hmac.new(secret.encode(), expires.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(mac, expected)


def password_matches(expected: str, given: str) -> bool:
    return hmac.compare_digest(expected.encode(), given.encode())


class LoginRateLimiter:
    """At most `limit` login attempts per `window` seconds, all clients together:
    there is only one user, so a burst can only be someone guessing."""

    def __init__(self, limit: int = 5, window: float = 60.0) -> None:
        self._limit = limit
        self._window = window
        self._attempts: deque[float] = deque()
        self._lock = Lock()

    def allow(self, now: float) -> bool:
        with self._lock:
            while self._attempts and self._attempts[0] <= now - self._window:
                self._attempts.popleft()
            if len(self._attempts) >= self._limit:
                return False
            self._attempts.append(now)
            return True


def now() -> float:
    return time.time()
