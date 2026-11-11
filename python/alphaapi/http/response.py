"""Django-style HTTP response classes.

Every response ultimately subclasses the Rust-backed ``_core.Response``, so the
hot path (status, headers, body) is still handled by Rust.
"""
from __future__ import annotations

import json
from typing import Any, Mapping

from .._core import Response
from .._helpers import to_builtin


class HttpResponse(Response):
    """An HTTP response with HTML as the default content type."""

    status_code_default = 200

    def __new__(cls, *args: Any, **kwargs: Any) -> "HttpResponse":
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
        self.headers = dict(headers or {})
        if content_type is None:
            encoding = charset or "utf-8"
            content_type = f"text/html; charset={encoding}"
        self.media_type = content_type
        self.body = b"" if content is None else content

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
        headers = dict(self.headers)
        headers[key] = value
        self.headers = headers

    def __setitem__(self, key: str, value: str) -> None:
        self._set_header(key, value)

    def __getitem__(self, key: str) -> str:
        headers = self.headers
        lowered = key.lower()
        for name, value in headers.items():
            if name.lower() == lowered:
                return value
        raise KeyError(key)

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
        self._set_header("Set-Cookie", "; ".join(parts))

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
        self.body = json.dumps(
            to_builtin(data),
            **dict(json_dumps_params or {"ensure_ascii": False}),
        ).encode("utf-8")


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


__all__ = [
    "HttpResponse",
    "JsonResponse",
    "HttpResponseRedirect",
    "HttpResponsePermanentRedirect",
    "HttpResponseNotModified",
    "HttpResponseBadRequest",
    "HttpResponseNotFound",
    "HttpResponseForbidden",
    "HttpResponseNotAllowed",
    "HttpResponseServerError",
]
