"""Framework exceptions."""
from __future__ import annotations

import http
from collections.abc import Mapping
from typing import Any


class HTTPException(Exception):
    """Raise to return a specific HTTP error response.

    The Rust core recognises this class and converts it into a JSON response
    without printing a traceback.
    """

    status_code: int = 500
    default_detail: str = "Internal Server Error"

    def __init__(
        self,
        status_code: int | None = None,
        detail: Any = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        if status_code is not None:
            self.status_code = status_code
        self.detail = (
            detail
            if detail is not None
            else http.HTTPStatus(self.status_code).phrase
        )
        self.headers = dict(headers or {})
        super().__init__(self.detail)


class Http404(HTTPException):
    """The requested resource does not exist."""

    status_code = 404

    def __init__(self, *args: Any) -> None:
        super().__init__(404, args[0] if args else "Not Found")


class PermissionDenied(HTTPException):
    """The authenticated user is not allowed to perform this action."""

    status_code = 403

    def __init__(self, *args: Any) -> None:
        super().__init__(403, args[0] if args else "Forbidden")


class BadRequest(HTTPException):
    status_code = 400

    def __init__(self, detail: Any = "Bad Request") -> None:
        super().__init__(400, detail)


class RequestValidationError(HTTPException):
    """Raised when a request cannot be validated."""

    def __init__(self, detail: Any = "Request validation failed") -> None:
        super().__init__(422, detail)


__all__ = [
    "HTTPException",
    "Http404",
    "PermissionDenied",
    "BadRequest",
    "RequestValidationError",
]
