"""Cross-Origin Resource Sharing middleware."""
from __future__ import annotations

from typing import Any

from .conf import settings
from .http import HttpResponse
from .middleware import call_next


class CorsMiddleware:
    """Add CORS headers and answer preflight requests.

    Configure through ``CORS_ALLOWED_ORIGINS``, ``CORS_ALLOW_ALL_ORIGINS`` and
    the related settings in :mod:`alphaapi.conf`.
    """

    def __init__(self, get_response: Any) -> None:
        self.get_response = get_response

    def _allowed_origin(self, origin: str) -> str | None:
        if not origin:
            return None
        if bool(getattr(settings, "CORS_ALLOW_ALL_ORIGINS", False)):
            return origin
        allowed = [str(item) for item in getattr(settings, "CORS_ALLOWED_ORIGINS", [])]
        if origin in allowed:
            return origin
        return None

    async def __call__(self, request: Any) -> Any:
        origin = request.headers.get("origin", "")
        allowed = self._allowed_origin(origin)

        requested_method = request.headers.get("access-control-request-method")
        if request.method == "OPTIONS" and requested_method:
            response = HttpResponse(b"", status=204)
        else:
            response = await call_next(self.get_response, request)

        if allowed:
            headers = response.headers
            headers["Access-Control-Allow-Origin"] = allowed
            headers.add("Vary", "Origin")
            if bool(getattr(settings, "CORS_ALLOW_CREDENTIALS", False)):
                headers["Access-Control-Allow-Credentials"] = "true"
            if request.method == "OPTIONS" and requested_method:
                headers["Access-Control-Allow-Methods"] = ", ".join(
                    str(item)
                    for item in getattr(settings, "CORS_ALLOWED_METHODS", ["GET"])
                )
                headers["Access-Control-Allow-Headers"] = ", ".join(
                    str(item)
                    for item in getattr(settings, "CORS_ALLOWED_HEADERS", ["*"])
                )
                headers["Access-Control-Max-Age"] = str(
                    getattr(settings, "CORS_MAX_AGE", 600)
                )
        return response


__all__ = ["CorsMiddleware"]
