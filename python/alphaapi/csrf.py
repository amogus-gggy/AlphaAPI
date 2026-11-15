"""CSRF protection middleware."""
from __future__ import annotations

import hmac
import secrets
from typing import Any

from .conf import settings
from .http import HttpResponseForbidden
from .middleware import call_next

SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}


def get_token(request: Any) -> str:
    token = getattr(request, "csrf_token", None)
    if token:
        return token
    token = secrets.token_urlsafe(32)
    request.csrf_token = token
    return token


class CsrfMiddleware:
    """Require a matching CSRF token for unsafe HTTP methods."""

    def __init__(self, get_response: Any) -> None:
        self.get_response = get_response

    async def __call__(self, request: Any) -> Any:
        cookie_name = str(getattr(settings, "CSRF_COOKIE_NAME", "csrftoken"))
        header_name = str(getattr(settings, "CSRF_HEADER_NAME", "x-csrftoken")).lower()
        cookie_token = request.COOKIES.get(cookie_name, "")
        request.csrf_token = cookie_token or secrets.token_urlsafe(32)

        exempt = [
            str(prefix)
            for prefix in getattr(settings, "CSRF_EXEMPT_PATHS", [])
        ]
        if request.method not in SAFE_METHODS and not any(
            request.path.startswith(prefix) for prefix in exempt
        ):
            submitted = request.headers.get(header_name, "")
            if not submitted:
                submitted = request.POST.get("csrfmiddlewaretoken", "")
            if not cookie_token or not submitted or not hmac.compare_digest(
                str(cookie_token).encode("utf-8"), str(submitted).encode("utf-8")
            ):
                return HttpResponseForbidden("CSRF verification failed")

        response = await call_next(self.get_response, request)
        if cookie_token != request.csrf_token:
            response.set_cookie(
                cookie_name,
                request.csrf_token,
                path="/",
                secure=bool(getattr(settings, "CSRF_COOKIE_SECURE", False)),
                httponly=bool(getattr(settings, "CSRF_COOKIE_HTTPONLY", False)),
                samesite=getattr(settings, "CSRF_COOKIE_SAMESITE", "lax"),
            )
        response.headers.add("Vary", "Cookie")
        return response


__all__ = ["CsrfMiddleware", "get_token"]
