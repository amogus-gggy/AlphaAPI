"""Security-related middleware and helpers."""
from __future__ import annotations

from typing import Any

from .conf import settings
from .http import HttpResponsePermanentRedirect
from .middleware import call_next


def host_is_allowed(host: str, allowed_hosts: list[str] | tuple[str, ...]) -> bool:
    """Return whether ``host`` (with optional port) matches ``ALLOWED_HOSTS``."""
    if not allowed_hosts:
        return False
    hostname = host.rsplit(":", 1)[0].strip("[]").lower()
    for pattern in allowed_hosts:
        candidate = str(pattern).lower()
        if candidate == "*":
            return True
        if candidate.startswith("."):
            if hostname == candidate[1:] or hostname.endswith(candidate):
                return True
        elif hostname == candidate:
            return True
    return False


class SecurityMiddleware:
    """Apply configurable security headers and optional HTTPS redirects."""

    def __init__(self, get_response: Any) -> None:
        self.get_response = get_response

    async def __call__(self, request: Any) -> Any:
        if bool(getattr(settings, "SECURE_SSL_REDIRECT", False)) and not request.is_secure():
            return HttpResponsePermanentRedirect(
                "https://" + request.get_host() + request.get_full_path()
            )

        response = await call_next(self.get_response, request)
        if not bool(getattr(settings, "SECURITY_HEADERS", True)):
            return response

        headers = response.headers
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", str(getattr(settings, "X_FRAME_OPTIONS", "DENY")))
        headers.setdefault(
            "Referrer-Policy",
            str(getattr(settings, "SECURE_REFERRER_POLICY", "same-origin")),
        )
        hsts = int(getattr(settings, "SECURE_HSTS_SECONDS", 0) or 0)
        if hsts > 0:
            value = f"max-age={hsts}"
            if bool(getattr(settings, "SECURE_HSTS_INCLUDE_SUBDOMAINS", False)):
                value += "; includeSubDomains"
            headers.setdefault("Strict-Transport-Security", value)
        return response


__all__ = ["SecurityMiddleware", "host_is_allowed"]
