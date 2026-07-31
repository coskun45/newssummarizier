"""
In-process login attempt throttling.

Single-instance in-memory limiter — sufficient for this app's single-process deployment.
Tracks failed login attempts per (lowercased) email and locks the account out for a cooldown
period after too many failures, to blunt brute-force attempts against /api/auth/login.
"""
import time
from threading import Lock

MAX_FAILED_ATTEMPTS = 5
WINDOW_SECONDS = 15 * 60  # 15 minutes
LOCKOUT_SECONDS = 15 * 60  # 15 minutes

_lock = Lock()
# email -> (failure_count, first_failure_ts, locked_until_ts)
_attempts: dict[str, tuple[int, float, float]] = {}


def _key(email: str) -> str:
    return email.strip().lower()


def seconds_until_unlocked(email: str) -> float:
    """Return remaining lockout seconds for `email`, or 0 if not locked."""
    with _lock:
        entry = _attempts.get(_key(email))
        if not entry:
            return 0.0
        _, _, locked_until = entry
        remaining = locked_until - time.monotonic()
        return remaining if remaining > 0 else 0.0


def record_failure(email: str) -> None:
    """Record a failed login attempt, locking the account out if the threshold is exceeded."""
    now = time.monotonic()
    key = _key(email)
    with _lock:
        count, first_ts, locked_until = _attempts.get(key, (0, now, 0.0))
        if now - first_ts > WINDOW_SECONDS:
            # Window expired — start a fresh count.
            count, first_ts = 0, now
        count += 1
        if count >= MAX_FAILED_ATTEMPTS:
            locked_until = now + LOCKOUT_SECONDS
        _attempts[key] = (count, first_ts, locked_until)


def record_success(email: str) -> None:
    """Clear any tracked failures for `email` after a successful login."""
    with _lock:
        _attempts.pop(_key(email), None)
