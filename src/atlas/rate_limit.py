"""In-memory rate limiter for login endpoints."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from fastapi import HTTPException, Request, status


@dataclass
class _ClientRecord:
    failures: int = 0
    blocked_until: float = 0.0


@dataclass
class LoginRateLimiter:
    """Per-IP rate limiter that locks out after repeated login failures.

    Parameters
    ----------
    max_failures:
        How many consecutive failures before the IP is blocked.
    window_seconds:
        The window in which failures are counted. Failures older than this
        are discarded when a new attempt arrives.
    block_seconds:
        How long an IP stays blocked after exceeding ``max_failures``.
    """

    max_failures: int = 5
    window_seconds: float = 300.0
    block_seconds: float = 600.0
    _clients: dict[str, _ClientRecord] = field(default_factory=dict, repr=False)

    def _client_ip(self, request: Request) -> str:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        if request.client:
            return request.client.host
        return "unknown"

    def check(self, request: Request) -> str:
        """Raise 429 if the client is blocked. Returns the client IP."""
        ip = self._client_ip(request)
        now = time.monotonic()
        record = self._clients.get(ip)
        if record and record.blocked_until > now:
            remaining = int(record.blocked_until - now)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Too many login attempts. Try again in {remaining}s.",
            )
        return ip

    def record_failure(self, ip: str) -> None:
        """Record a failed login attempt for *ip*."""
        now = time.monotonic()
        record = self._clients.get(ip)
        if record is None:
            record = _ClientRecord()
            self._clients[ip] = record

        # Reset if the previous window has elapsed.
        if record.blocked_until and record.blocked_until <= now:
            record.failures = 0
            record.blocked_until = 0.0

        record.failures += 1
        if record.failures >= self.max_failures:
            record.blocked_until = now + self.block_seconds

    def record_success(self, ip: str) -> None:
        """Clear failure tracking after a successful login."""
        self._clients.pop(ip, None)

    def cleanup(self) -> None:
        """Remove stale entries to prevent unbounded memory growth."""
        now = time.monotonic()
        stale = [
            ip
            for ip, rec in self._clients.items()
            if rec.blocked_until <= now and rec.failures > 0
        ]
        for ip in stale:
            del self._clients[ip]


# Module-level singleton used by the app.
login_rate_limiter = LoginRateLimiter()
