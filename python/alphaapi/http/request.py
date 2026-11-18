"""HTTP request helpers.

The low-level request object lives in Rust (``alphaapi._core.Request``).
``HttpRequest`` is the Python-facing Django-style wrapper used by views and
middleware.
"""
from __future__ import annotations

from collections.abc import Iterable
from http.cookies import SimpleCookie
from typing import Any
from urllib.parse import parse_qsl, urljoin

from .._core import Request as _RawRequest
from .multipart import parse_multipart


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
        self.content_type = self.headers.get("content-type", "")
        self._get_cache: QueryDict | None = None
        self._meta_cache: dict[str, Any] | None = None
        self._cookie_cache: dict[str, str] | None = None
        self._post_cache: QueryDict | None = None
        self._files_cache: dict[str, Any] | None = None

    @property
    def META(self) -> dict[str, Any]:
        """CGI-style metadata, built on first access."""
        if self._meta_cache is None:
            meta: dict[str, Any] = {
                "REQUEST_METHOD": self.method,
                "PATH_INFO": self.path,
                "QUERY_STRING": self.query_string,
                "REMOTE_ADDR": self.client,
                "CONTENT_TYPE": self.content_type,
                "CONTENT_LENGTH": self.headers.get("content-length", ""),
                "HTTP_HOST": self.headers.get("host", ""),
            }
            for name, value in self.headers.items():
                key = "HTTP_" + name.upper().replace("-", "_")
                if key not in meta:
                    meta[key] = value
            self._meta_cache = meta
        return self._meta_cache

    @META.setter
    def META(self, value: dict[str, Any]) -> None:
        self._meta_cache = value

    @property
    def GET(self) -> QueryDict:
        if self._get_cache is None:
            self._get_cache = QueryDict(self._raw.query_params)
        return self._get_cache

    @GET.setter
    def GET(self, value: Any) -> None:
        self._get_cache = value

    @property
    def COOKIES(self) -> dict[str, str]:
        if self._cookie_cache is None:
            self._cookie_cache = _parse_cookies(self.headers.get("cookie", ""))
        return self._cookie_cache

    @COOKIES.setter
    def COOKIES(self, value: dict[str, str]) -> None:
        self._cookie_cache = value

    def _ensure_form(self) -> None:
        if self._post_cache is None:
            self._post_cache, self._files_cache = self._parse_form()

    @property
    def POST(self) -> QueryDict:
        self._ensure_form()
        assert self._post_cache is not None
        return self._post_cache

    @POST.setter
    def POST(self, value: Any) -> None:
        self._post_cache = value

    @property
    def FILES(self) -> dict[str, Any]:
        self._ensure_form()
        assert self._files_cache is not None
        return self._files_cache

    @FILES.setter
    def FILES(self, value: dict[str, Any]) -> None:
        self._files_cache = value

    def _parse_form(self) -> tuple[QueryDict, dict[str, Any]]:
        content_type = self.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type == "application/x-www-form-urlencoded":
            try:
                text = self._raw.body.decode("utf-8", "replace")
            except Exception:
                return QueryDict(), {}
            return QueryDict(parse_qsl(text, keep_blank_values=True)), {}

        if content_type == "multipart/form-data":
            from ..conf import settings

            fields, files = parse_multipart(
                self._raw.body,
                self.headers.get("content-type", ""),
                max_file_size=getattr(settings, "MAX_UPLOAD_SIZE", None),
            )
            post = QueryDict(fields)
            mapped: dict[str, Any] = {
                name: values[0] if len(values) == 1 else values
                for name, values in files.items()
            }
            return post, mapped

        return QueryDict(), {}

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

    @property
    def scheme(self) -> str:
        if self.is_secure():
            return "https"
        return "http"

    def is_secure(self) -> bool:
        from ..conf import settings

        if not bool(getattr(settings, "TRUST_PROXY_HEADERS", False)):
            return False
        header = getattr(settings, "SECURE_PROXY_SSL_HEADER", "x-forwarded-proto")
        value = self.headers.get(header.lower(), "")
        return value.split(",", 1)[0].strip().lower() == "https"

    def get_full_path(self) -> str:
        return self.path + (f"?{self.query_string}" if self.query_string else "")

    def build_absolute_uri(self, location: str | None = None) -> str:
        host = self.get_host()
        base = f"{self.scheme}://{host}" if host else f"{self.scheme}://localhost"
        if location is None:
            return base + self.get_full_path()
        return urljoin(base + self.path, location)

    def accepts(self, content_type: str) -> bool:
        accept = self.headers.get("accept", "*/*")
        content_type = content_type.split(";", 1)[0].strip().lower()
        for item in accept.split(","):
            candidate = item.split(";", 1)[0].strip().lower()
            if candidate in {"*/*", content_type}:
                return True
            if candidate.endswith("/*") and content_type.startswith(candidate[:-1]):
                return True
        return False

    def __getitem__(self, key: str) -> Any:
        try:
            return self.META[key]
        except KeyError as error:
            raise KeyError(key) from error

    def __repr__(self) -> str:
        return f"<HttpRequest {self.method} {self.path}>"


__all__ = ["HttpRequest", "QueryDict"]
