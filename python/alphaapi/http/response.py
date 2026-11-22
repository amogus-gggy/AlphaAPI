"""Django-style HTTP response classes.

Every response ultimately subclasses the Rust-backed ``_core.Response``, so the
hot path (status, headers, body) is still handled by Rust.
"""
from __future__ import annotations

import json
import mimetypes
import os
from collections.abc import AsyncIterable, Iterable, Iterator, Mapping, MutableMapping
from email.utils import formatdate, parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .._core import Response, dumps
from .._helpers import to_builtin


def _coerce_header_items(headers: Any) -> list[tuple[str, str]]:
    if isinstance(headers, Headers):
        return headers.items(multi=True)
    if hasattr(headers, "items"):
        return [(str(key), str(value)) for key, value in headers.items()]
    return [(str(key), str(value)) for key, value in headers]


class Headers(MutableMapping[str, str]):
    """A mutable, multi-value view over a response's headers.

    Normal mapping access (``headers[key]``) returns the most recently added
    value, while :meth:`add` and :meth:`get_all` preserve repeated fields such
    as multiple ``Set-Cookie`` headers.
    """

    def __init__(self, response: HttpResponse) -> None:
        self._response = response

    def __getitem__(self, key: str) -> str:
        values = self._response.get_all_headers(key)
        if not values:
            raise KeyError(key)
        return values[-1]

    def __setitem__(self, key: str, value: str) -> None:
        self._response.set_header(str(key), str(value))

    def __delitem__(self, key: str) -> None:
        if not self._response.remove_header(key):
            raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        seen: set[str] = set()
        for name, _ in self._response.header_items():
            lowered = name.lower()
            if lowered not in seen:
                seen.add(lowered)
                yield name

    def __len__(self) -> int:
        return sum(1 for _ in self)

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and bool(self._response.get_all_headers(key))

    def add(self, key: str, value: str) -> None:
        """Append a value without removing existing values for ``key``."""
        self._response.add_header(str(key), str(value))

    def get_all(self, key: str) -> list[str]:
        """Return every value for ``key`` in insertion order."""
        return list(self._response.get_all_headers(key))

    # Django-compatible alias.
    getlist = get_all

    def items(self, multi: bool = False) -> Any:
        if multi:
            return list(self._response.header_items())
        return [(name, self[name]) for name in self]

    def __repr__(self) -> str:
        return repr(dict(self.items()))


class HttpResponse(Response):
    """An HTTP response with HTML as the default content type."""

    status_code_default = 200

    def __new__(cls, *args: Any, **kwargs: Any) -> HttpResponse:
        # The Rust base type has its own ``__new__`` with a narrower signature;
        # Django-style constructor keywords (``status``, ``content_type``, ...)
        # are handled by ``__init__`` below.
        return Response.__new__(cls)

    def __init__(
        self,
        content: Any = b"",
        *,
        status: int | None = None,
        status_code: int | None = None,
        content_type: str | None = None,
        charset: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        code = status_code if status_code is not None else status
        if code is None:
            code = self.status_code_default
        self.status_code = code
        self.headers = headers or {}
        if content_type is None:
            from ..conf import settings

            encoding = charset or getattr(settings, "DEFAULT_CHARSET", "utf-8")
            content_type = f"text/html; charset={encoding}"
        self.media_type = content_type
        self.body = b"" if content is None else content

    # The Rust base declares ``headers`` as ``dict[str, str]``; the subclass
    # intentionally exposes the multi-value ``Headers`` view instead.
    @property  # type: ignore[override]
    def headers(self) -> Headers:
        view = self.__dict__.get("_headers_view")
        if view is None:
            view = Headers(self)
            self.__dict__["_headers_view"] = view
        return view

    @headers.setter
    def headers(self, value: Any) -> None:
        self.clear_headers()
        view = self.headers
        for key, item in _coerce_header_items(value or {}):
            view.add(key, item)

    # -- Django-compatible conveniences -------------------------------------

    @property
    def status(self) -> int:
        return self.status_code

    @status.setter
    def status(self, value: int) -> None:
        self.status_code = value

    @property
    def content(self) -> bytes:
        return self.body

    @content.setter
    def content(self, value: Any) -> None:
        self.body = value

    def _set_header(self, key: str, value: str) -> None:
        self.headers[key] = value

    def __setitem__(self, key: str, value: str) -> None:
        self._set_header(key, value)

    def __getitem__(self, key: str) -> str:
        return self.headers[key]

    def set_cookie(
        self,
        key: str,
        value: str = "",
        *,
        max_age: int | None = None,
        expires: str | None = None,
        path: str = "/",
        domain: str | None = None,
        secure: bool = False,
        httponly: bool = False,
        samesite: str | None = "lax",
    ) -> None:
        parts = [f"{key}={value}", f"Path={path}"]
        if domain:
            parts.append(f"Domain={domain}")
        if max_age is not None:
            parts.append(f"Max-Age={max_age}")
        if expires:
            parts.append(f"Expires={expires}")
        if secure:
            parts.append("Secure")
        if httponly:
            parts.append("HttpOnly")
        if samesite:
            parts.append(f"SameSite={samesite}")
        # Cookies are a repeated header: never replace an earlier Set-Cookie.
        self.headers.add("Set-Cookie", "; ".join(parts))

    def delete_cookie(self, key: str, *, path: str = "/", domain: str | None = None) -> None:
        self.set_cookie(
            key,
            "",
            max_age=0,
            expires="Thu, 01 Jan 1970 00:00:00 GMT",
            path=path,
            domain=domain,
        )

    def __repr__(self) -> str:
        return f"<{type(self).__name__} status={self.status_code}>"


class JsonResponse(HttpResponse):
    """Serialize ``data`` as JSON (``application/json``)."""

    def __init__(
        self,
        data: Any,
        *,
        status: int = 200,
        headers: Mapping[str, str] | None = None,
        json_dumps_params: Mapping[str, Any] | None = None,
        safe: bool = True,
    ) -> None:
        super().__init__(
            b"",
            status=status,
            content_type="application/json",
            headers=headers,
        )
        if safe and not isinstance(data, (dict, list)):
            raise TypeError(
                "In order to allow non-dict/list objects to be serialized, "
                "pass safe=False to JsonResponse."
            )
        if json_dumps_params:
            # Custom ``json.dumps`` options are rare; keep them working by
            # falling back to the standard library for that case.
            payload = json.dumps(
                to_builtin(data),
                **dict(json_dumps_params),
            ).encode("utf-8")
        else:
            # Serialize in Rust, including the fallback that normalizes
            # Pydantic models, dataclasses, enums, datetimes, and so on.
            payload = dumps(data)
        self.body = payload


class StreamingHttpResponse(HttpResponse):
    """A response whose body is produced incrementally.

    ``streaming_content`` may be any sync iterable/iterator or an async
    iterable/iterator.  Each item must be ``bytes``, ``str``, or a value that
    can be JSON-encoded by the framework.
    """

    def __init__(
        self,
        streaming_content: Iterable[Any] | AsyncIterable[Any],
        *,
        status: int = 200,
        content_type: str | None = None,
        headers: Mapping[str, str] | None = None,
        charset: str | None = None,
    ) -> None:
        if callable(streaming_content) and not hasattr(streaming_content, "__iter__"):
            streaming_content = streaming_content()
        super().__init__(
            b"",
            status=status,
            content_type=content_type or "text/html; charset=utf-8",
            headers=headers,
            charset=charset,
        )
        self.streaming_content = streaming_content
        self.__alphaapi_stream__ = streaming_content

    def __iter__(self) -> Iterator[Any]:
        if hasattr(self.streaming_content, "__aiter__"):
            raise TypeError("async streaming responses cannot be iterated synchronously")
        return iter(self.streaming_content)


def _content_disposition(filename: str) -> str:
    """Build a valid ``Content-Disposition`` value for a download."""
    ascii_name = filename.encode("ascii", "ignore").decode("ascii") or "download"
    ascii_name = ascii_name.replace("\\", "\\\\").replace('"', '\\"')
    value = f'attachment; filename="{ascii_name}"'
    if any(ord(character) > 127 for character in filename):
        value += f"; filename*=UTF-8''{quote(filename, safe='')}"
    return value


class FileResponse(StreamingHttpResponse):
    """Stream a file from disk without loading it into memory.

    When ``request`` is supplied, the response honours ``If-None-Match``,
    ``If-Modified-Since`` and single-range ``Range`` requests.
    """

    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        status: int = 200,
        content_type: str | None = None,
        headers: Mapping[str, str] | None = None,
        as_attachment: bool = False,
        filename: str | None = None,
        chunk_size: int = 64 * 1024,
        request: Any = None,
    ) -> None:
        self.path = Path(path)
        stat = self.path.stat()
        self.stat = stat
        if content_type is None:
            content_type = mimetypes.guess_type(str(self.path))[0]
        content_type = content_type or "application/octet-stream"

        etag = f'"{stat.st_size:x}-{int(stat.st_mtime):x}"'
        last_modified = formatdate(stat.st_mtime, usegmt=True)
        merged: dict[str, str] = dict(headers or {})
        merged.setdefault("ETag", etag)
        merged.setdefault("Last-Modified", last_modified)
        merged.setdefault("Accept-Ranges", "bytes")

        self._start = 0
        self._length = stat.st_size
        no_body = status in {204, 304}

        if request is not None and not no_body:
            if self._is_not_modified(request, etag, stat.st_mtime):
                status = 304
                no_body = True
                merged.pop("Content-Length", None)
                self._length = 0
            else:
                parsed = self._parse_range(request.headers.get("range", ""), stat.st_size)
                if parsed == "invalid":
                    merged.pop("Content-Length", None)
                    merged["Content-Range"] = f"bytes */{stat.st_size}"
                    status = 416
                    no_body = True
                    self._length = 0
                elif isinstance(parsed, tuple):
                    self._start, end = parsed
                    self._length = end - self._start + 1
                    status = 206
                    merged["Content-Range"] = (
                        f"bytes {self._start}-{end}/{stat.st_size}"
                    )

        if not no_body:
            merged.setdefault("Content-Length", str(self._length))
        if as_attachment:
            name = filename or self.path.name
            merged.setdefault("Content-Disposition", _content_disposition(name))

        super().__init__(
            self._iter_file(chunk_size),
            status=status,
            content_type=content_type,
            headers=merged,
        )

    @staticmethod
    def _is_not_modified(request: Any, etag: str, mtime: float) -> bool:
        if_none_match = request.headers.get("if-none-match", "")
        if if_none_match:
            candidates = [item.strip() for item in if_none_match.split(",")]
            for candidate in candidates:
                if candidate == "*" or candidate.removeprefix("W/") == etag:
                    return True
            return False

        if_modified_since = request.headers.get("if-modified-since", "")
        if if_modified_since:
            try:
                since = parsedate_to_datetime(if_modified_since).timestamp()
            except (TypeError, ValueError, OverflowError):
                return False
            return int(mtime) <= int(since)
        return False

    @staticmethod
    def _parse_range(value: str, size: int) -> tuple[int, int] | None | str:
        if not value:
            return None
        unit, separator, spec = value.partition("=")
        if not separator or unit.strip().lower() != "bytes":
            return None
        # Only the first range is served; multipart ranges are uncommon for
        # files and rejecting them keeps the implementation small.
        spec = spec.split(",", 1)[0].strip()
        start_text, _, end_text = spec.partition("-")
        try:
            if not start_text:
                suffix = int(end_text)
                if suffix <= 0:
                    return "invalid"
                start = max(0, size - suffix)
                end = size - 1
            else:
                start = int(start_text)
                end = int(end_text) if end_text else size - 1
        except ValueError:
            return "invalid"

        if start < 0 or start >= size or start > end:
            return "invalid"
        return start, min(end, size - 1)

    def _iter_file(self, chunk_size: int) -> Iterator[bytes]:
        remaining = self._length
        with self.path.open("rb") as handle:
            if self._start:
                handle.seek(self._start)
            while remaining > 0:
                chunk = handle.read(min(chunk_size, remaining))
                if not chunk:
                    return
                remaining -= len(chunk)
                yield chunk


class SseResponse(StreamingHttpResponse):
    """Server-Sent Events response.

    Iterables may yield plain strings/bytes (sent as-is) or mappings, which are
    formatted as ``event:``/``id:``/``data:`` fields.
    """

    def __init__(
        self,
        streaming_content: Iterable[Any] | AsyncIterable[Any],
        *,
        status: int = 200,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        merged = {
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
        merged.update(headers or {})
        super().__init__(
            self._format_iterable(streaming_content),
            status=status,
            content_type="text/event-stream; charset=utf-8",
            headers=merged,
        )

    @classmethod
    def _format_chunk(cls, item: Any) -> Any:
        if isinstance(item, (bytes, str)):
            return item
        if isinstance(item, Mapping):
            lines: list[str] = []
            if item.get("event") is not None:
                lines.append(f"event: {item['event']}")
            if item.get("id") is not None:
                lines.append(f"id: {item['id']}")
            data = item.get("data", "")
            if not isinstance(data, str):
                data = json.dumps(to_builtin(data), separators=(",", ":"))
            for line in data.splitlines() or [""]:
                lines.append(f"data: {line}")
            return "\n".join(lines) + "\n\n"
        return f"data: {item}\n\n"

    @classmethod
    def _format_iterable(
        cls, source: Iterable[Any] | AsyncIterable[Any]
    ) -> Any:
        if hasattr(source, "__aiter__"):
            async def async_generator():
                async for item in source:
                    yield cls._format_chunk(item)
            return async_generator()

        def generator():
            for item in source:
                yield cls._format_chunk(item)
        return generator()


class HttpResponseRedirectBase(HttpResponse):
    status_code_default = 302
    allowed_schemes = ("http", "https", "ftp")

    def __init__(self, redirect_to: str, *args: Any, **kwargs: Any) -> None:
        super().__init__(
            b"",
            *args,
            status=kwargs.pop("status", None) or self.status_code_default,
            **kwargs,
        )
        self._set_header("Location", redirect_to)


class HttpResponseRedirect(HttpResponseRedirectBase):
    status_code_default = 302


class HttpResponsePermanentRedirect(HttpResponseRedirectBase):
    status_code_default = 301


class HttpResponseNotModified(HttpResponse):
    status_code_default = 304

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(b"", *args, **kwargs)


class HttpResponseBadRequest(HttpResponse):
    status_code_default = 400


class HttpResponseNotFound(HttpResponse):
    status_code_default = 404


class HttpResponseForbidden(HttpResponse):
    status_code_default = 403


class HttpResponseNotAllowed(HttpResponse):
    status_code_default = 405

    def __init__(self, permitted_methods: list[str], *args: Any, **kwargs: Any) -> None:
        super().__init__(b"", *args, **kwargs)
        self._set_header("Allow", ", ".join(permitted_methods))


class HttpResponseServerError(HttpResponse):
    status_code_default = 500


class HttpResponseConflict(HttpResponse):
    status_code_default = 409


class HttpResponseGone(HttpResponse):
    status_code_default = 410


class HttpResponseTooManyRequests(HttpResponse):
    status_code_default = 429


class HttpResponseServiceUnavailable(HttpResponse):
    status_code_default = 503


class HttpResponseGatewayTimeout(HttpResponse):
    status_code_default = 504


__all__ = [
    "HttpResponse",
    "JsonResponse",
    "StreamingHttpResponse",
    "SseResponse",
    "FileResponse",
    "HttpResponseRedirect",
    "HttpResponsePermanentRedirect",
    "HttpResponseNotModified",
    "HttpResponseBadRequest",
    "HttpResponseNotFound",
    "HttpResponseForbidden",
    "HttpResponseNotAllowed",
    "HttpResponseServerError",
    "HttpResponseConflict",
    "HttpResponseGone",
    "HttpResponseTooManyRequests",
    "HttpResponseServiceUnavailable",
    "HttpResponseGatewayTimeout",
]
