"""Response classes.

``Response`` itself is implemented in Rust.  The subclasses below assign the
Rust-managed fields directly instead of calling ``super().__init__`` because
extension-type ``__new__``/``__init__`` inheritance is not reliable across
Python versions.
"""
from __future__ import annotations

from typing import Any, Mapping

from ._core import Response


class JSONResponse(Response):
    """Serialize ``content`` as JSON."""

    def __init__(
        self,
        content: Any = None,
        status_code: int = 200,
        headers: Mapping[str, str] | None = None,
        media_type: str | None = None,
    ) -> None:
        self.status_code = status_code
        self.headers = dict(headers or {})
        self.media_type = media_type or "application/json"
        self.body = content


class PlainTextResponse(Response):
    def __init__(
        self,
        content: str = "",
        status_code: int = 200,
        headers: Mapping[str, str] | None = None,
        media_type: str | None = None,
    ) -> None:
        self.status_code = status_code
        self.headers = dict(headers or {})
        self.media_type = media_type or "text/plain; charset=utf-8"
        self.body = content


class HTMLResponse(Response):
    def __init__(
        self,
        content: str = "",
        status_code: int = 200,
        headers: Mapping[str, str] | None = None,
        media_type: str | None = None,
    ) -> None:
        self.status_code = status_code
        self.headers = dict(headers or {})
        self.media_type = media_type or "text/html; charset=utf-8"
        self.body = content


class RedirectResponse(Response):
    def __init__(
        self,
        url: str,
        status_code: int = 307,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        merged = dict(headers or {})
        merged.setdefault("location", url)
        self.headers = merged
        self.media_type = None
        self.body = b""


__all__ = [
    "Response",
    "JSONResponse",
    "PlainTextResponse",
    "HTMLResponse",
    "RedirectResponse",
]
