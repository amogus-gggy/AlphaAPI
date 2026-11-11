"""HTTP request helpers.

The low-level request object lives in Rust (``alphaapi._core.Request``).
``HttpRequest`` is the Python-facing Django-style wrapper used by views and
middleware.
"""
from __future__ import annotations

from http.cookies import SimpleCookie
from typing import Any, Iterable
from urllib.parse import parse_qsl

from .._core import Request as _RawRequest


class QueryDict(dict):
    """A small ``dict`` with Django's repeated-key helpers."""

    def __init__(self, data: Any = None) -> None:
        super().__init__()
        if data is None:
            return
        if isinstance(data, QueryDict):
            for key in data:
                self[key] = data.getlist(key)
            return
        if hasattr(data, "items"):
            for key, value in data.items():
                if isinstance(value, (list, tuple)):
                    self[key] = [str(item) for item in value]
                else:
                    self[key] = str(value)
            return
        for key, value in data:
            self.add(key, value)

    def add(self, key: str, value: Any) -> None:
        existing = dict.get(self, key)
        if existing is None:
            dict.__setitem__(self, key, str(value))
        elif isinstance(existing, list):
            existing.append(str(value))
        else:
            dict.__setitem__(self, key, [existing, str(value)])

    def getlist(self, key: str, default: Iterable[Any] | None = None) -> list[str]:
        value = dict.get(self, key)
        if value is None:
            return list(default or [])
        if isinstance(value, list):
            return list(value)
        return [value]

    def get(self, key: str, default: Any = None) -> Any:
        if key in self:
            return self[key]
        return default

    def __getitem__(self, key: str) -> Any:
        value = dict.__getitem__(self, key)
        if isinstance(value, list):
            return value[-1]
        return value

    def dict(self) -> dict[str, Any]:
        return {key: self[key] for key in self}


def _parse_cookies(header: str) -> dict[str, str]:
    if not header:
        return {}
    cookie = SimpleCookie()
    try:
        cookie.load(header)
    except Exception:
        return {}
    return {key: morsel.value for key, morsel in cookie.items()}


class HttpRequest:
    """Django-style request passed to views and middleware."""

    def __init__(self, raw: _RawRequest) -> None:
        self._raw = raw
        self.method = raw.method
        self.path = raw.path
        self.path_info = raw.path
        self.query_string = raw.query_string
        self.client = raw.client
        self.headers = raw.headers
        self.META = {
            "REQUEST_METHOD": self.method,
            "PATH_INFO": self.path,
            "QUERY_STRING": self.query_string,
            "REMOTE_ADDR": self.client,
            "CONTENT_TYPE": self.headers.get("content-type", ""),
            "CONTENT_LENGTH": self.headers.get("content-length", ""),
            "HTTP_HOST": self.headers.get("host", ""),
        }
        self.GET = QueryDict(raw.query_params)
        self.POST = self._parse_form()
        self.COOKIES = _parse_cookies(self.headers.get("cookie", ""))

    def _parse_form(self) -> QueryDict:
        content_type = self.headers.get("content-type", "").split(";", 1)[0].strip()
        if content_type != "application/x-www-form-urlencoded":
            return QueryDict()
        try:
            text = self._raw.body.decode("utf-8", "replace")
        except Exception:
            return QueryDict()
        return QueryDict(parse_qsl(text, keep_blank_values=True))

    @property
    def body(self) -> bytes:
        return self._raw.body

    @property
    def raw(self) -> _RawRequest:
        return self._raw

    def json(self) -> Any:
        """Parse the request body as JSON."""
        return self._raw.json()

    def text(self) -> str:
        return self._raw.text()

    def header(self, name: str, default: Any = None) -> Any:
        return self._raw.header(name.lower(), default)

    def get_host(self) -> str:
        return self.headers.get("host", "")

    def is_secure(self) -> bool:
        return self.headers.get("x-forwarded-proto", "http") == "https"

    def __getitem__(self, key: str) -> Any:
        try:
            return self.META[key]
        except KeyError as error:
            raise KeyError(key) from error

    def __repr__(self) -> str:
        return f"<HttpRequest {self.method} {self.path}>"


__all__ = ["HttpRequest", "QueryDict"]
