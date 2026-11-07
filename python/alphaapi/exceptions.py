"""Framework exceptions."""
from __future__ import annotations

import http
from typing import Any, Mapping


class HTTPException(Exception):
    """Raise to return a specific HTTP error response.

    The Rust core recognises instances of this class and converts them into
    ``{"detail": ...}`` JSON responses without a Python traceback.
    """

    def __init__(
        self,
        status_code: int,
        detail: Any = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.detail = detail if detail is not None else http.HTTPStatus(status_code).phrase
        self.headers = dict(headers or {})
        super().__init__(self.detail)


class RequestValidationError(HTTPException):
    """Raised when a request cannot be validated."""

    def __init__(self, detail: Any = "Request validation failed") -> None:
        super().__init__(422, detail)


__all__ = ["HTTPException", "RequestValidationError"]
