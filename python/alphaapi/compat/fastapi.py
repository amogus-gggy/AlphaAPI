"""FastAPI backward-compatibility layer for AlphaAPI.

This module monkeypatches the installed ``fastapi`` package so code written for
FastAPI can run on AlphaAPI's Rust HTTP core where supported.

WARNING
-------
This is a **backward-compatibility mod**. It can **degrade performance**, may
**not be optimal**, and may not match FastAPI/Starlette semantics exactly.
Unsupported features may be ignored, partially emulated, or raise clear errors.
Prefer native ``alphaapi`` APIs for production workloads.

Usage
-----
    import alphaapi.compat.fastapi
    alphaapi.compat.fastapi.install()  # emits compatibility warning

    # then existing FastAPI imports work:
    from fastapi import FastAPI

Or install before importing application modules::

    import alphaapi.compat.fastapi as compat
    compat.install()
"""

from __future__ import annotations

import asyncio
import dataclasses
import functools
import inspect
import socket
import sys
import threading
import time
import types
import urllib.parse
import warnings
from typing import Any, Callable, Iterable, Mapping, Sequence

# Native AlphaAPI imports.
from alphaapi import Alpha as _Alpha
from alphaapi import APIRouter as _AlphaRouter
from alphaapi import Request as _AlphaRequest
from alphaapi import Response as _AlphaResponse
from alphaapi.exceptions import HTTPException as _AlphaHTTPException
from alphaapi.params import Body as _ABody
from alphaapi.params import Header as _AHeader
from alphaapi.params import Param as _AParam
from alphaapi.params import Path as _APath
from alphaapi.params import Query as _AQuery
from alphaapi.responses import (
    HTMLResponse as _AHTMLResponse,
    JSONResponse as _AJSONResponse,
    PlainTextResponse as _APlainTextResponse,
    RedirectResponse as _ARedirectResponse,
)


def _join_paths(prefix: str, path: str) -> str:
    if not prefix:
        return path or "/"
    if not path:
        return prefix
    return prefix.rstrip("/") + "/" + path.lstrip("/")

COMPAT_WARNING = (
    "AlphaAPI FastAPI compatibility mode is enabled: this monkeypatches the "
    "`fastapi` module for backward compatibility. It can degrade performance, "
    "may not be optimal, and does not fully implement FastAPI/Starlette "
    "semantics. Unsupported features may be ignored, emulated incompletely, "
    "or raise errors. Prefer native AlphaAPI APIs for production use."
)

_installed = False


class CompatibilityWarning(UserWarning):
    """Emitted when FastAPI compatibility mode is active."""


def _warn(msg: str, *, stacklevel: int = 2) -> None:
    warnings.warn(msg, CompatibilityWarning, stacklevel=stacklevel)


def _warn_unsupported(feature: str) -> None:
    _warn(
        f"FastAPI compatibility: `{feature}` is not fully supported by AlphaAPI; "
        "behavior may differ or be unavailable.",
        stacklevel=3,
    )


# ---------------------------------------------------------------------------
# Params
# ---------------------------------------------------------------------------

class _CompatParam(_AParam):
    _in: str = "query"

    def __init__(self, default: Any = ..., **kwargs: Any):
        # Accept FastAPI's broad kwargs; keep what AlphaAPI can use.
        alias = kwargs.get("alias")
        description = kwargs.get("description")
        super().__init__(default, alias=alias, description=description)
        self.extra = kwargs

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(default={self.default!r}, alias={self.alias!r})"


class Query(_CompatParam, _AQuery):
    _in = "query"


class Path(_CompatParam, _APath):
    _in = "path"


class Header(_CompatParam, _AHeader):
    _in = "header"


class Cookie(_CompatParam, _AHeader):
    _in = "cookie"


class Body(_CompatParam, _ABody):
    _in = "body"

    def __init__(self, default: Any = ..., *, embed: bool | None = None, media_type: str = "application/json", **kwargs: Any):
        super().__init__(default, **kwargs)
        self.embed = embed
        self.media_type = media_type
        self.extra.update({"embed": embed, "media_type": media_type})


class Form(Body):
    _in = "form"

    def __init__(self, default: Any = ..., *, media_type: str = "application/x-www-form-urlencoded", **kwargs: Any):
        super().__init__(default, media_type=media_type, **kwargs)


class File(Form):
    _in = "file"

    def __init__(self, default: Any = ..., *, media_type: str = "multipart/form-data", **kwargs: Any):
        super().__init__(default, media_type=media_type, **kwargs)


# ---------------------------------------------------------------------------
# Dependency/security stubs
# ---------------------------------------------------------------------------

class Depends:
    def __init__(self, dependency: Callable[..., Any] | None = None, *, use_cache: bool = True, scope: str | None = None):
        self.dependency = dependency
        self.use_cache = use_cache
        self.scope = scope

    def __repr__(self) -> str:
        return f"Depends({getattr(self.dependency, '__name__', self.dependency)!r})"


class Security(Depends):
    def __init__(self, dependency: Callable[..., Any] | None = None, *, scopes: Sequence[str] | None = None, use_cache: bool = True):
        super().__init__(dependency, use_cache=use_cache)
        self.scopes = list(scopes or [])


# ---------------------------------------------------------------------------
# Exceptions / responses / datastructures
# ---------------------------------------------------------------------------

class HTTPException(_AlphaHTTPException):
    pass


class RequestValidationError(Exception):
    def __init__(self, errors: Sequence[Any], *, body: Any = None):
        self.errors = list(errors)
        self.body = body
        super().__init__(str(errors))


class WebSocketException(Exception):
    def __init__(self, code: int, reason: str | None = None):
        self.code = code
        self.reason = reason
        super().__init__(reason or str(code))


class ValidationException(Exception):
    def __init__(self, errors: Sequence[Any]):
        self.errors = list(errors)
        super().__init__(str(errors))


class Response(_AlphaResponse):
    """AlphaAPI response with FastAPI's optional ``background`` argument."""

    def __init__(self, content: Any = None, status_code: int = 200,
                 headers: Mapping[str, str] | None = None, media_type: str | None = None,
                 background: Any = None):
        _AlphaResponse.__init__(self, content, status_code=status_code, headers=headers, media_type=media_type)
        self.background = background


class JSONResponse(_AJSONResponse):
    def __init__(self, content: Any = None, status_code: int = 200,
                 headers: Mapping[str, str] | None = None, media_type: str | None = None,
                 background: Any = None):
        super().__init__(content, status_code=status_code, headers=headers, media_type=media_type)
        self.background = background


class PlainTextResponse(_APlainTextResponse):
    def __init__(self, content: Any = None, status_code: int = 200,
                 headers: Mapping[str, str] | None = None, media_type: str | None = None,
                 background: Any = None):
        super().__init__(content, status_code=status_code, headers=headers, media_type=media_type)
        self.background = background


class HTMLResponse(_AHTMLResponse):
    def __init__(self, content: Any = None, status_code: int = 200,
                 headers: Mapping[str, str] | None = None, media_type: str | None = None,
                 background: Any = None):
        super().__init__(content, status_code=status_code, headers=headers, media_type=media_type)
        self.background = background


class RedirectResponse(_ARedirectResponse):
    def __init__(self, url: str, status_code: int = 307,
                 headers: Mapping[str, str] | None = None, background: Any = None):
        super().__init__(url, status_code=status_code, headers=headers)
        self.background = background


class StreamingResponse(Response):
    def __init__(self, content: Any, status_code: int = 200, headers: Mapping[str, str] | None = None, media_type: str | None = None, background: Any = None):
        _warn_unsupported("StreamingResponse")
        body = b"".join(content) if hasattr(content, "__iter__") and not isinstance(content, (bytes, bytearray, str)) else content
        super().__init__(body, status_code=status_code, headers=headers, media_type=media_type)


class FileResponse(Response):
    def __init__(self, path: str, *args: Any, **kwargs: Any):
        _warn_unsupported("FileResponse")
        try:
            with open(path, "rb") as f:
                data = f.read()
        except Exception:
            data = b""
        super().__init__(data, status_code=kwargs.get("status_code", 200), media_type=kwargs.get("media_type", "application/octet-stream"))


class BackgroundTasks:
    def __init__(self, tasks: Sequence[Any] | None = None):
        self.tasks = list(tasks or [])

    def add_task(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        self.tasks.append((func, args, kwargs))
        _warn_unsupported("BackgroundTasks (tasks are not auto-run by AlphaAPI compat core)")


@dataclasses.dataclass
class UploadFile:
    filename: str | None = None
    content_type: str | None = None
    file: Any = None
    headers: Mapping[str, str] | None = None

    async def read(self, size: int = -1) -> bytes:
        if hasattr(self.file, "read"):
            data = self.file.read(size)
            if inspect.isawaitable(data):
                return await data
            return data
        return b""

    async def close(self) -> None:
        if hasattr(self.file, "close"):
            res = self.file.close()
            if inspect.isawaitable(res):
                await res


# ---------------------------------------------------------------------------
# Request compatibility
# ---------------------------------------------------------------------------

class Request:
    """Best-effort Starlette/FastAPI Request adapter over AlphaAPI's request.

    AlphaAPI exposes a Rust-backed request object with a different interface.
    This wrapper provides common attributes/methods used by FastAPI apps.
    Compatibility is partial; for native performance use ``alphaapi.Request``.
    """

    def __init__(self, native: _AlphaRequest | None = None, scope: Mapping[str, Any] | None = None):
        self._native = native
        self.scope = dict(scope or {})
        self.state = types.SimpleNamespace()
        if native is not None:
            self.scope.setdefault("type", "http")
            self.scope.setdefault("method", native.method)
            self.scope.setdefault("path", native.path)
            self.scope.setdefault("query_string", native.query_string.encode() if hasattr(native.query_string, "encode") else native.query_string)
            self.scope.setdefault("headers", [(k.encode(), v.encode()) for k, v in (native.headers or {}).items()])

    @property
    def method(self) -> str:
        return self._native.method if self._native else self.scope.get("method", "GET")

    @property
    def url(self) -> Any:
        path = self._native.path if self._native else self.scope.get("path", "/")
        qs = self._native.query_string if self._native else (self.scope.get("query_string") or b"").decode("latin1")
        full = path + (f"?{qs}" if qs else "")
        return types.SimpleNamespace(path=path, query=qs, __str__=lambda _s: full)

    @property
    def headers(self) -> Mapping[str, str]:
        return self._native.headers if self._native else {}

    @property
    def query_params(self) -> Mapping[str, Any]:
        return self._native.query_params if self._native else {}

    @property
    def path_params(self) -> Mapping[str, str]:
        return self._native.params if self._native else {}

    @property
    def cookies(self) -> Mapping[str, str]:
        raw = self.headers.get("cookie") or self.headers.get("Cookie") or ""
        out: dict[str, str] = {}
        for part in str(raw).split(";"):
            if "=" in part:
                k, v = part.split("=", 1)
                out[k.strip()] = v.strip()
        return out

    @property
    def client(self) -> Any:
        c = self._native.client if self._native else None
        if c and ":" in c:
            host, port = c.rsplit(":", 1)
            try:
                return types.SimpleNamespace(host=host, port=int(port))
            except Exception:
                pass
        return types.SimpleNamespace(host=c, port=None)

    async def body(self) -> bytes:
        return self._native.body if self._native else b""

    async def json(self) -> Any:
        if self._native:
            return self._native.json()
        return None

    async def form(self) -> Any:
        _warn_unsupported("Request.form()")
        return {}

    async def stream(self):
        yield await self.body()


# ---------------------------------------------------------------------------
# Status codes / encoders helpers
# ---------------------------------------------------------------------------

def _make_status_module() -> types.ModuleType:
    mod = types.ModuleType("fastapi.status")
    try:
        from starlette import status as _st
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            for n in dir(_st):
                if n.isupper():
                    setattr(mod, n, getattr(_st, n))
    except Exception:
        for n, v in {
            "HTTP_200_OK": 200, "HTTP_201_CREATED": 201, "HTTP_204_NO_CONTENT": 204,
            "HTTP_400_BAD_REQUEST": 400, "HTTP_401_UNAUTHORIZED": 401,
            "HTTP_403_FORBIDDEN": 403, "HTTP_404_NOT_FOUND": 404,
            "HTTP_405_METHOD_NOT_ALLOWED": 405, "HTTP_422_UNPROCESSABLE_ENTITY": 422,
            "HTTP_500_INTERNAL_SERVER_ERROR": 500,
        }.items():
            setattr(mod, n, v)
    return mod


def jsonable_encoder(obj: Any, *args: Any, **kwargs: Any) -> Any:
    try:
        from fastapi.encoders import jsonable_encoder as _orig  # may be patched later
        if _orig is not jsonable_encoder:
            return _orig(obj, *args, **kwargs)
    except Exception:
        pass
    try:
        from alphaapi._helpers import to_builtin
        return to_builtin(obj)
    except Exception:
        return obj


# ---------------------------------------------------------------------------
# Routing wrappers
# ---------------------------------------------------------------------------

def _resolved_hints(func: Callable[..., Any]) -> dict[str, Any]:
    try:
        import typing
        return typing.get_type_hints(func, include_extras=True)
    except Exception:
        try:
            return inspect.get_annotations(func, eval_str=True)
        except Exception:
            return dict(getattr(func, "__annotations__", {}) or {})


def _annotated_extra(annotation: Any) -> Any | None:
    """Return a Depends/Security or param marker embedded in Annotated."""
    try:
        import typing
        if typing.get_origin(annotation) is typing.Annotated:
            for extra in typing.get_args(annotation)[1:]:
                if isinstance(extra, (Depends, Security)) or extra.__class__.__name__ in {
                    "Depends", "Security", "Cookie", "Form", "File"
                }:
                    return extra
    except Exception:
        pass
    return None


def _strip_annotated(annotation: Any) -> Any:
    try:
        import typing
        if typing.get_origin(annotation) is typing.Annotated:
            return typing.get_args(annotation)[0]
    except Exception:
        pass
    return annotation


def _needs_python_binding(func: Callable[..., Any]) -> bool:
    # FastAPI features AlphaAPI's Rust binder can't fully handle natively.
    try:
        sig = inspect.signature(func)
    except Exception:
        return False
    hints = _resolved_hints(func)
    for p in sig.parameters.values():
        default = p.default
        ann = hints.get(p.name, p.annotation)
        extra = _annotated_extra(ann)
        if extra is not None:
            if isinstance(extra, (Depends, Security, Cookie, Form, File)):
                return True
            if extra.__class__.__name__ in {"Depends", "Security", "Cookie", "Form", "File"}:
                return True
        if isinstance(default, (Depends, Security)) or default.__class__.__name__ in {"Depends", "Security"}:
            return True
        if isinstance(default, Cookie) or default.__class__.__name__ == "Cookie":
            return True
        if isinstance(default, (Form, File)) or default.__class__.__name__ in {"Form", "File"}:
            return True
        if ann is BackgroundTasks or getattr(ann, "__name__", "") == "BackgroundTasks":
            return True
        if ann is Request or (
            getattr(ann, "__name__", "") == "Request"
            and getattr(ann, "__module__", "").startswith("fastapi")
        ) or ann is _AlphaRequest:
            return True
        if isinstance(default, Body) and getattr(default, "embed", None):
            return True
    return False


def _cookie_value(native: _AlphaRequest, name: str, alias: str | None) -> str | None:
    key = alias or name
    raw = (native.headers or {}).get("cookie") or (native.headers or {}).get("Cookie") or ""
    for part in str(raw).split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            if k.strip() == key:
                return v.strip()
    return None


def _call_dependency(dep: Callable[..., Any]) -> Any:
    res = dep()
    if inspect.isawaitable(res):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop and loop.is_running():
            # Can't block; return coroutine object is not useful. Best effort.
            _warn_unsupported("async dependency resolution in sync compat path")
            return None
        return asyncio.run(res)
    return res


def _wrap_handler(func: Callable[..., Any]) -> Callable[..., Any]:
    sig = inspect.signature(func)
    hints = _resolved_hints(func)

    @functools.wraps(func)
    def wrapper(request: _AlphaRequest):
        kwargs: dict[str, Any] = {}
        json_body: Any = None
        for name, p in sig.parameters.items():
            raw_ann = hints.get(name, p.annotation)
            ann = _strip_annotated(raw_ann)
            default = _annotated_extra(raw_ann) or p.default
            if ann is _AlphaRequest or (isinstance(ann, type) and issubclass(ann, _AlphaRequest)):
                kwargs[name] = request
                continue
            if ann is Request or getattr(ann, "__name__", "") == "Request":
                kwargs[name] = Request(request)
                continue
            if isinstance(default, (Depends, Security)) or default.__class__.__name__ in {"Depends", "Security"}:
                dep = getattr(default, "dependency", None)
                kwargs[name] = _call_dependency(dep) if callable(dep) else None
                continue
            if isinstance(default, Cookie) or default.__class__.__name__ == "Cookie":
                alias = getattr(default, "alias", None)
                val = _cookie_value(request, name, alias)
                if val is None:
                    d = getattr(default, "default", ...)
                    if d is ... or getattr(d, "__class__", type(None)).__name__ == "PydanticUndefinedType":
                        raise _AlphaHTTPException(422, detail=f"Missing cookie: {alias or name}")
                    val = d
                kwargs[name] = val
                continue
            if isinstance(default, (Form, File)) or default.__class__.__name__ in {"Form", "File"}:
                _warn_unsupported("Form/File parameters")
                d = getattr(default, "default", None)
                kwargs[name] = None if d is ... else d
                continue
            if ann is BackgroundTasks or getattr(ann, "__name__", "") == "BackgroundTasks":
                kwargs[name] = BackgroundTasks()
                continue
            # Fallback: try to read from path/query/header/body via native request.
            qp = getattr(request, "query_params", {}) or {}
            pp = getattr(request, "params", {}) or {}
            hdrs = getattr(request, "headers", {}) or {}
            if name in pp:
                kwargs[name] = pp[name]
            elif name in qp:
                kwargs[name] = qp[name]
            elif name.replace("_", "-") in hdrs:
                kwargs[name] = hdrs[name.replace("_", "-")]
            else:
                if default is inspect.Parameter.empty:
                    # attempt body/json scalar fallback
                    if json_body is None:
                        try:
                            json_body = request.json()
                        except Exception:
                            json_body = {}
                    if isinstance(json_body, dict) and name in json_body:
                        kwargs[name] = json_body[name]
                    else:
                        kwargs[name] = None
                else:
                    kwargs[name] = default if not isinstance(default, (_AParam, _CompatParam, Depends, Security)) else getattr(default, "default", None)
        result = func(**kwargs)
        if inspect.isawaitable(result):
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop and loop.is_running():
                # Running under async server context? wrap via thread is unsafe; best effort.
                return asyncio.get_event_loop().run_until_complete(result) if False else result
            return asyncio.run(result)
        return result

    # Adjust signature so AlphaAPI doesn't mis-bind parameters.
    wrapper.__signature__ = inspect.Signature([
        inspect.Parameter("request", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=_AlphaRequest)
    ])
    wrapper.__annotations__ = {"request": _AlphaRequest}
    return wrapper


def _wrap_handler_async(func: Callable[..., Any]) -> Callable[..., Any]:
    sig = inspect.signature(func)
    hints = _resolved_hints(func)

    @functools.wraps(func)
    async def wrapper(request: _AlphaRequest):
        kwargs: dict[str, Any] = {}
        json_body: Any = None
        for name, p in sig.parameters.items():
            raw_ann = hints.get(name, p.annotation)
            ann = _strip_annotated(raw_ann)
            default = _annotated_extra(raw_ann) or p.default
            if ann is _AlphaRequest or (isinstance(ann, type) and issubclass(ann, _AlphaRequest)):
                kwargs[name] = request
                continue
            if ann is Request or getattr(ann, "__name__", "") == "Request":
                kwargs[name] = Request(request)
                continue
            if isinstance(default, (Depends, Security)) or default.__class__.__name__ in {"Depends", "Security"}:
                dep = getattr(default, "dependency", None)
                if callable(dep):
                    res = dep()
                    kwargs[name] = await res if inspect.isawaitable(res) else res
                else:
                    kwargs[name] = None
                continue
            if isinstance(default, Cookie) or default.__class__.__name__ == "Cookie":
                alias = getattr(default, "alias", None)
                val = _cookie_value(request, name, alias)
                if val is None:
                    d = getattr(default, "default", ...)
                    if d is ... or getattr(d, "__class__", type(None)).__name__ == "PydanticUndefinedType":
                        raise _AlphaHTTPException(422, detail=f"Missing cookie: {alias or name}")
                    val = d
                kwargs[name] = val
                continue
            if isinstance(default, (Form, File)) or default.__class__.__name__ in {"Form", "File"}:
                _warn_unsupported("Form/File parameters")
                d = getattr(default, "default", None)
                kwargs[name] = None if d is ... else d
                continue
            if ann is BackgroundTasks or getattr(ann, "__name__", "") == "BackgroundTasks":
                kwargs[name] = BackgroundTasks()
                continue
            qp = getattr(request, "query_params", {}) or {}
            pp = getattr(request, "params", {}) or {}
            hdrs = getattr(request, "headers", {}) or {}
            if name in pp:
                kwargs[name] = pp[name]
            elif name in qp:
                kwargs[name] = qp[name]
            elif name.replace("_", "-") in hdrs:
                kwargs[name] = hdrs[name.replace("_", "-")]
            else:
                if default is inspect.Parameter.empty:
                    if json_body is None:
                        try:
                            json_body = request.json()
                        except Exception:
                            json_body = {}
                    if isinstance(json_body, dict) and name in json_body:
                        kwargs[name] = json_body[name]
                    else:
                        kwargs[name] = None
                else:
                    kwargs[name] = default if not isinstance(default, (_AParam, _CompatParam, Depends, Security)) else getattr(default, "default", None)
        result = func(**kwargs)
        if inspect.isawaitable(result):
            result = await result
        return result

    wrapper.__signature__ = inspect.Signature([
        inspect.Parameter("request", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=_AlphaRequest)
    ])
    wrapper.__annotations__ = {"request": _AlphaRequest}
    return wrapper


def _prepare_endpoint(endpoint: Callable[..., Any]) -> Callable[..., Any]:
    if not _needs_python_binding(endpoint):
        return endpoint
    if inspect.iscoroutinefunction(endpoint):
        return _wrap_handler_async(endpoint)
    return _wrap_handler(endpoint)


class _CompatRouterMixin:
    """Shared FastAPI-compatible routing behavior."""

    def _compat_prepare_route_kwargs(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        status_code = kwargs.pop("status_code", None)
        tags = kwargs.pop("tags", None)
        summary = kwargs.pop("summary", None)
        description = kwargs.pop("description", None)
        response_description = kwargs.pop("response_description", "Successful Response")
        include_in_schema = kwargs.pop("include_in_schema", True)
        name = kwargs.pop("name", None)
        deprecated = kwargs.pop("deprecated", None)
        dependencies = kwargs.pop("dependencies", None)
        responses = kwargs.pop("responses", None)
        operation_id = kwargs.pop("operation_id", None)
        response_model = kwargs.pop("response_model", None)
        callbacks = kwargs.pop("callbacks", None)
        openapi_extra = kwargs.pop("openapi_extra", None)
        generate_unique_id_function = kwargs.pop("generate_unique_id_function", None)
        response_class = kwargs.pop("response_class", None)
        for k in ["response_model_include", "response_model_exclude", "response_model_by_alias",
                  "response_model_exclude_unset", "response_model_exclude_defaults", "response_model_exclude_none"]:
            kwargs.pop(k, None)
        if dependencies:
            _warn_unsupported("route dependencies")
        if response_model is not None:
            _warn_unsupported("response_model validation/serialization")
        if callbacks or openapi_extra or operation_id:
            _warn_unsupported("OpenAPI callback/operation metadata extensions")
        if kwargs:
            _warn_unsupported(f"route args: {', '.join(sorted(kwargs.keys()))}")
        return {
            "status_code": status_code or 200,
            "tags": tags,
            "summary": summary,
            "description": description,
            "include_in_schema": include_in_schema,
            "response_description": response_description,
            "_name": name,
        }

    def add_api_route(self, path: str, endpoint: Callable[..., Any], *, methods: list[str] | None = None, **kwargs: Any) -> Any:
        endpoint = _prepare_endpoint(endpoint)
        prepared = self._compat_prepare_route_kwargs(dict(kwargs))
        name = prepared.pop("_name", None)
        if name and not getattr(endpoint, "__name__", None):
            try:
                endpoint.__name__ = name
            except Exception:
                pass
        return super().add_api_route(path, endpoint, methods=methods or ["GET"], **prepared)

    def api_route(self, path: str, **kwargs: Any):
        methods = tuple(kwargs.pop("methods", ["GET"]))
        prepared = self._compat_prepare_route_kwargs(dict(kwargs))
        name = prepared.pop("_name", None)

        def decorator(endpoint: Callable[..., Any]) -> Callable[..., Any]:
            endpoint = _prepare_endpoint(endpoint)
            if name and not getattr(endpoint, "__name__", None):
                try:
                    endpoint.__name__ = name
                except Exception:
                    pass
            _AlphaRouter.add_api_route(self, path, endpoint, methods=list(methods), **prepared)
            return endpoint

        return decorator

    def include_router(self, router: Any, *, prefix: str = "", tags: list[str] | None = None,
                       dependencies: Sequence[Any] | None = None, responses: dict | None = None, **kwargs: Any):
        if dependencies:
            _warn_unsupported("include_router dependencies")
        if kwargs:
            _warn_unsupported(f"include_router args: {', '.join(sorted(kwargs.keys()))}")
        if isinstance(router, _AlphaRouter):
            return _AlphaRouter.include_router(self, router, prefix=prefix, tags=tags)
        if hasattr(router, "routes"):
            extra_tags = list(getattr(self, "tags", [])) + list(tags or [])
            for route in list(getattr(router, "routes", [])):
                try:
                    new_path = _join_paths(getattr(self, "prefix", ""), _join_paths(prefix, route.path))
                    copied = route.copy(path=new_path, tags=list(getattr(route, "tags", [])) + extra_tags)
                    self.routes.append(copied)
                    self._on_route_added(self.routes[-1])
                except Exception:
                    pass
            return None
        return _AlphaRouter.include_router(self, router, prefix=prefix, tags=tags)

    def websocket(self, path: str, name: str | None = None, **kwargs: Any):
        def decorator(func):
            _warn_unsupported("WebSocket routes")
            return func
        return decorator

    def websocket_route(self, path: str, name: str | None = None):
        return self.websocket(path, name=name)

    def on_event(self, event_type: str):
        def decorator(func):
            if event_type == "startup" and hasattr(self, "_startup"):
                self._startup.append(func)
            elif event_type == "shutdown" and hasattr(self, "_shutdown"):
                self._shutdown.append(func)
            else:
                _warn_unsupported(f"on_event({event_type!r})")
            return func
        return decorator


class APIRouter(_CompatRouterMixin, _AlphaRouter):
    """FastAPI-compatible APIRouter backed by AlphaAPI."""

    def __init__(self, *, prefix: str = "", tags: list[str] | None = None, dependencies: Sequence[Any] | None = None,
                 responses: dict[int | str, dict[str, Any]] | None = None, deprecated: bool | None = None,
                 include_in_schema: bool = True, **kwargs: Any):
        super().__init__(prefix=prefix, tags=tags)
        self.dependencies = list(dependencies or [])
        self.responses = responses or {}
        self.deprecated = deprecated
        self.include_in_schema = include_in_schema
        self.default_response_class = kwargs.get("default_response_class", JSONResponse)
        self.callbacks = kwargs.get("callbacks")
        self.on_startup = kwargs.get("on_startup") or []
        self.on_shutdown = kwargs.get("on_shutdown") or []
        self.lifespan = kwargs.get("lifespan")
        if kwargs:
            _warn_unsupported(f"APIRouter args: {', '.join(sorted(kwargs.keys()))}")
        if dependencies:
            _warn_unsupported("router-level dependencies")


class FastAPI(_CompatRouterMixin, _Alpha):
    """FastAPI-compatible application backed by AlphaAPI's Rust core."""

    def __init__(self, *, debug: bool = False, title: str = "FastAPI", summary: str | None = None,
                 description: str = "", version: str = "0.1.0", openapi_url: str | None = "/openapi.json",
                 openapi_tags: list[dict[str, Any]] | None = None, servers: list[dict[str, str | Any]] | None = None,
                 dependencies: Sequence[Any] | None = None, default_response_class: type[Response] = JSONResponse,
                 redirect_slashes: bool = True, docs_url: str | None = "/docs", redoc_url: str | None = "/redoc",
                 swagger_ui_oauth2_redirect_url: str | None = "/docs/oauth2-redirect",
                 swagger_ui_init_oauth: dict[str, Any] | None = None, middleware: Sequence[Any] | None = None,
                 exception_handlers: dict[Any, Any] | None = None, on_startup: Sequence[Callable[[], Any]] | None = None,
                 on_shutdown: Sequence[Callable[[], Any]] | None = None, lifespan: Any = None,
                 root_path: str = "", root_path_in_servers: bool = True, responses: dict[int | str, dict[str, Any]] | None = None,
                 callbacks: list[Any] | None = None, deprecated: bool | None = None, include_in_schema: bool = True,
                 **kwargs: Any):
        _Alpha.__init__(self, title=title, version=version, description=description or None,
                        docs=docs_url is not None, openapi_url=openapi_url or "/openapi.json",
                        docs_url=docs_url or "/docs")
        self.debug = debug
        self.summary = summary
        self.openapi_tags = openapi_tags
        self.servers = servers
        self.dependencies = list(dependencies or [])
        self.default_response_class = default_response_class
        self.redirect_slashes = redirect_slashes
        self.redoc_url = redoc_url
        self.swagger_ui_oauth2_redirect_url = swagger_ui_oauth2_redirect_url
        self.swagger_ui_init_oauth = swagger_ui_init_oauth
        self.middleware_stack = None
        self.user_middleware = list(middleware or [])
        self.root_path = root_path
        self.root_path_in_servers = root_path_in_servers
        self.responses = responses or {}
        self.callbacks = callbacks
        self.deprecated = deprecated
        self.include_in_schema = include_in_schema
        self.state = types.SimpleNamespace()
        self.dependency_overrides: dict[Callable[..., Any], Callable[..., Any]] = {}
        self.router = self
        self.extra = kwargs
        self._lifespan = lifespan
        if exception_handlers:
            for exc, handler in exception_handlers.items():
                self.add_exception_handler(exc, handler)
        if on_startup:
            for f in on_startup:
                self.on_event("startup")(f)
        if on_shutdown:
            for f in on_shutdown:
                self.on_event("shutdown")(f)
        ignored = []
        for k, v, default in [
            ("middleware", middleware, None),
            ("lifespan", lifespan, None),
            ("servers", servers, None),
            ("dependencies", dependencies, None),
            ("callbacks", callbacks, None),
            ("swagger_ui_oauth2_redirect_url", swagger_ui_oauth2_redirect_url, "/docs/oauth2-redirect"),
            ("swagger_ui_init_oauth", swagger_ui_init_oauth, None),
        ]:
            if v and v != default:
                ignored.append(k)
        if not redirect_slashes:
            ignored.append("redirect_slashes=False")
        if kwargs:
            ignored.extend(sorted(kwargs.keys()))
        if ignored:
            _warn_unsupported(f"FastAPI args: {', '.join(ignored)}")

    def add_middleware(self, middleware_class: Any, **options: Any) -> None:
        self.user_middleware.append((middleware_class, options))
        _warn_unsupported(f"middleware {getattr(middleware_class, '__name__', middleware_class)}")

    def middleware(self, middleware_type: str):
        def decorator(func):
            _warn_unsupported(f"middleware decorator ({middleware_type})")
            return func
        return decorator

    def mount(self, path: str, app: Any, name: str | None = None) -> None:
        _warn_unsupported(f"mount({path!r})")

    def add_exception_handler(self, exc_class_or_status_code: Any, handler: Callable[..., Any]) -> None:
        if isinstance(exc_class_or_status_code, int):
            _warn_unsupported(f"status-code exception handler {exc_class_or_status_code}")
            return
        self._exception_handlers[exc_class_or_status_code] = handler

    def exception_handler(self, exc_class_or_status_code: Any):
        def decorator(func):
            self.add_exception_handler(exc_class_or_status_code, func)
            return func
        return decorator

    def on_event(self, event_type: str):
        def decorator(func):
            if event_type == "startup":
                self._startup.append(func)
            elif event_type == "shutdown":
                self._shutdown.append(func)
            else:
                _warn_unsupported(f"on_event({event_type!r})")
            return func
        return decorator

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        """ASGI entry point.

        AlphaAPI itself is not an ASGI app. In compatibility mode we lazily
        start the Rust server in a background thread and proxy ASGI requests to
        it. This lets existing ``uvicorn module:app`` deployments run unchanged,
        at the cost of an extra localhost hop (performance degradation).
        """
        scope_type = scope.get("type") if isinstance(scope, Mapping) else None
        if scope_type == "lifespan":
            await self._asgi_lifespan(receive, send)
            return
        if scope_type == "websocket":
            raise RuntimeError("WebSocket connections are not supported by AlphaAPI compat")
        if scope_type != "http":
            raise RuntimeError(f"Unsupported ASGI scope type: {scope_type!r}")

        body = bytearray()
        while True:
            message = await receive()
            if message.get("type") == "http.request":
                body.extend(message.get("body", b"") or b"")
                if not message.get("more_body", False):
                    break
            elif message.get("type") == "http.disconnect":
                return

        port = self._ensure_proxy_server()
        path = scope.get("root_path", "") + scope.get("path", "/")
        raw_query = scope.get("query_string", b"")
        if isinstance(raw_query, bytes):
            raw_query = raw_query.decode("latin1")
        target = path + (f"?{raw_query}" if raw_query else "")

        headers: list[tuple[bytes, bytes]] = []
        for name, value in scope.get("headers", []) or []:
            lname = name.lower()
            if lname in (b"host", b"content-length", b"connection", b"transfer-encoding"):
                continue
            headers.append((name, value))
        headers.append((b"content-length", str(len(body)).encode()))
        headers.append((b"connection", b"close"))

        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        try:
            request_line = f"{scope.get('method', 'GET')} {target} HTTP/1.1\r\n".encode("latin1")
            writer.write(request_line)
            for name, value in headers:
                writer.write(name + b": " + value + b"\r\n")
            writer.write(b"\r\n")
            if body:
                writer.write(bytes(body))
            await writer.drain()

            raw = await reader.read()
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

        head, _, payload = raw.partition(b"\r\n\r\n")
        lines = head.split(b"\r\n")
        if not lines or len(lines[0].split(b" ", 2)) < 2:
            await send({"type": "http.response.start", "status": 502, "headers": []})
            await send({"type": "http.response.body", "body": b"Bad Gateway"})
            return
        status = int(lines[0].split(b" ", 2)[1])
        response_headers: list[tuple[bytes, bytes]] = []
        for line in lines[1:]:
            if b":" in line:
                k, v = line.split(b":", 1)
                response_headers.append((k.strip(), v.strip()))
        await send({"type": "http.response.start", "status": status, "headers": response_headers})
        await send({"type": "http.response.body", "body": payload})

    def _asgi_proxy_port(self) -> int:
        return getattr(self, "_proxy_port", 0) or 0

    def _ensure_proxy_server(self) -> int:
        port = getattr(self, "_proxy_port", 0)
        thread = getattr(self, "_proxy_thread", None)
        if port and thread and thread.is_alive():
            return port
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        self._proxy_port = port
        thread = threading.Thread(
            target=self.run,
            kwargs={"host": "127.0.0.1", "port": port},
            name="alphaapi-compat-asgi",
            daemon=True,
        )
        self._proxy_thread = thread
        thread.start()
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                    return port
            except OSError:
                time.sleep(0.02)
        raise RuntimeError("AlphaAPI compatibility proxy server did not start")

    def _stop_proxy_server(self) -> None:
        thread = getattr(self, "_proxy_thread", None)
        if not thread:
            return
        try:
            self.stop()
        except Exception:
            pass
        thread.join(timeout=10)
        self._proxy_port = 0
        self._proxy_thread = None

    async def _asgi_lifespan(self, receive: Any, send: Any) -> None:
        while True:
            message = await receive()
            if message.get("type") == "lifespan.startup":
                try:
                    await asyncio.to_thread(self._ensure_proxy_server)
                    await send({"type": "lifespan.startup.complete"})
                except Exception as exc:
                    await send({"type": "lifespan.startup.failed", "message": str(exc)})
            elif message.get("type") == "lifespan.shutdown":
                await asyncio.to_thread(self._stop_proxy_server)
                await send({"type": "lifespan.shutdown.complete"})
                return

# ---------------------------------------------------------------------------
# Monkeypatch installation
# ---------------------------------------------------------------------------

def _patch_module(mod: types.ModuleType, attrs: dict[str, Any]) -> None:
    for k, v in attrs.items():
        try:
            setattr(mod, k, v)
        except Exception:
            pass


def _get_or_create_module(name: str) -> types.ModuleType:
    mod = sys.modules.get(name)
    if mod is None:
        mod = types.ModuleType(name)
        sys.modules[name] = mod
    return mod


def install(*, warn: bool = True) -> None:
    """Monkeypatch the ``fastapi`` module namespace with AlphaAPI-backed compat.

    WARNING: This enables backward-compatibility mode and can degrade
    performance, may not be optimal, and may not match FastAPI semantics.
    """
    global _installed
    if warn:
        warnings.warn(COMPAT_WARNING, CompatibilityWarning, stacklevel=2)
    if _installed:
        return

    # Ensure base module exists (import real fastapi if available, else create).
    try:
        import fastapi as fastapi_mod  # noqa: F401
    except Exception:
        fastapi_mod = _get_or_create_module("fastapi")

    status_mod = _make_status_module()
    sys.modules["fastapi.status"] = status_mod
    try:
        from starlette import status as starlette_status
        sys.modules["starlette.status"] = starlette_status
    except Exception:
        pass

    # Core public API
    public = {
        "FastAPI": FastAPI,
        "APIRouter": APIRouter,
        "Request": Request,
        "Response": Response,
        "HTTPException": HTTPException,
        "WebSocketException": WebSocketException,
        "status": status_mod,
        "Depends": Depends,
        "Security": Security,
        "Query": Query,
        "Path": Path,
        "Header": Header,
        "Cookie": Cookie,
        "Body": Body,
        "Form": Form,
        "File": File,
        "UploadFile": UploadFile,
        "BackgroundTasks": BackgroundTasks,
        "JSONResponse": JSONResponse,
        "PlainTextResponse": PlainTextResponse,
        "HTMLResponse": HTMLResponse,
        "RedirectResponse": RedirectResponse,
        "StreamingResponse": StreamingResponse,
        "FileResponse": FileResponse,
    }
    _patch_module(fastapi_mod, public)
    try:
        fastapi_mod.__dict__.setdefault("__all__", [])
        for k in public:
            if k not in fastapi_mod.__all__:
                fastapi_mod.__all__.append(k)
    except Exception:
        pass

    # Submodules
    applications = _get_or_create_module("fastapi.applications")
    _patch_module(applications, {"FastAPI": FastAPI})
    sys.modules["fastapi.applications"] = applications

    routing = _get_or_create_module("fastapi.routing")
    _patch_module(routing, {"APIRouter": APIRouter, "APIRoute": object})
    sys.modules["fastapi.routing"] = routing

    params_mod = _get_or_create_module("fastapi.params")
    _patch_module(params_mod, {
        "Param": _CompatParam, "Query": Query, "Path": Path, "Header": Header,
        "Cookie": Cookie, "Body": Body, "Form": Form, "File": File,
        "Depends": Depends, "Security": Security,
    })
    sys.modules["fastapi.params"] = params_mod

    param_functions = _get_or_create_module("fastapi.param_functions")
    _patch_module(param_functions, {k: public[k] for k in ["Query","Path","Header","Cookie","Body","Form","File","Depends","Security"]})
    sys.modules["fastapi.param_functions"] = param_functions

    responses_mod = _get_or_create_module("fastapi.responses")
    _patch_module(responses_mod, {
        "Response": Response, "JSONResponse": JSONResponse, "PlainTextResponse": PlainTextResponse,
        "HTMLResponse": HTMLResponse, "RedirectResponse": RedirectResponse,
        "StreamingResponse": StreamingResponse, "FileResponse": FileResponse,
        "UJSONResponse": JSONResponse, "ORJSONResponse": JSONResponse,
    })
    sys.modules["fastapi.responses"] = responses_mod

    exceptions_mod = _get_or_create_module("fastapi.exceptions")
    _patch_module(exceptions_mod, {
        "HTTPException": HTTPException, "WebSocketException": WebSocketException,
        "RequestValidationError": RequestValidationError, "ValidationException": ValidationException,
        "ResponseValidationError": Exception, "WebSocketRequestValidationError": Exception,
        "FastAPIError": Exception, "StarletteHTTPException": HTTPException,
    })
    sys.modules["fastapi.exceptions"] = exceptions_mod

    requests_mod = _get_or_create_module("fastapi.requests")
    _patch_module(requests_mod, {"Request": Request, "HTTPConnection": object})
    sys.modules["fastapi.requests"] = requests_mod

    datastructures_mod = _get_or_create_module("fastapi.datastructures")
    _patch_module(datastructures_mod, {"UploadFile": UploadFile, "DefaultPlaceholder": type("DefaultPlaceholder", (), {})})
    sys.modules["fastapi.datastructures"] = datastructures_mod

    background_mod = _get_or_create_module("fastapi.background")
    _patch_module(background_mod, {"BackgroundTasks": BackgroundTasks, "P": Any})
    sys.modules["fastapi.background"] = background_mod

    encoders_mod = _get_or_create_module("fastapi.encoders")
    _patch_module(encoders_mod, {"jsonable_encoder": jsonable_encoder})
    sys.modules["fastapi.encoders"] = encoders_mod

    dependencies_mod = _get_or_create_module("fastapi.dependencies")
    _get_or_create_module("fastapi.dependencies.models")
    _get_or_create_module("fastapi.dependencies.utils")
    sys.modules["fastapi.dependencies"] = dependencies_mod

    websockets_mod = _get_or_create_module("fastapi.websockets")
    _patch_module(websockets_mod, {"WebSocket": object, "WebSocketDisconnect": Exception, "WebSocketState": object})
    sys.modules["fastapi.websockets"] = websockets_mod

    security_mod = _get_or_create_module("fastapi.security")
    sys.modules["fastapi.security"] = security_mod
    for sub in ["oauth2", "http", "api_key", "open_id_connect_url", "utils", "base"]:
        _get_or_create_module(f"fastapi.security.{sub}")

    # Extended shims (security, middleware, static files, templates, TestClient, SSE, OpenAPI).
    from . import extras  # noqa: WPS433 (local import avoids import cycles)

    def _install_security(module_name: str, names: list[str]) -> None:
        mod = _get_or_create_module(module_name)
        for name in names:
            if hasattr(extras, name):
                setattr(mod, name, getattr(extras, name))
        sys.modules[module_name] = mod

    _install_security("fastapi.security", [
        "SecurityScopes", "SecurityRequirement", "HTTPBasic", "HTTPBasicCredentials",
        "HTTPBearer", "HTTPAuthorizationCredentials", "HTTPDigest", "OAuth2",
        "OAuth2PasswordBearer", "OAuth2PasswordRequestForm", "OAuth2AuthorizationCodeBearer",
        "OpenIdConnect", "APIKeyQuery", "APIKeyHeader", "APIKeyCookie",
    ])
    _install_security("fastapi.security.oauth2", [
        "OAuth2", "OAuth2PasswordBearer", "OAuth2PasswordRequestForm",
        "OAuth2AuthorizationCodeBearer", "SecurityScopes",
    ])
    _install_security("fastapi.security.http", [
        "HTTPBasic", "HTTPBasicCredentials", "HTTPBearer", "HTTPAuthorizationCredentials", "HTTPDigest",
    ])
    _install_security("fastapi.security.api_key", [
        "APIKeyQuery", "APIKeyHeader", "APIKeyCookie",
    ])
    _install_security("fastapi.security.open_id_connect_url", ["OpenIdConnect"])
    _install_security("fastapi.security.base", ["SecurityBase"])
    _install_security("fastapi.security.utils", [])

    # Also expose security names at the top level, as FastAPI does for some.
    _patch_module(fastapi_mod, {
        "OAuth2PasswordBearer": extras.OAuth2PasswordBearer,
        "OAuth2PasswordRequestForm": extras.OAuth2PasswordRequestForm,
        "HTTPBasic": extras.HTTPBasic,
        "HTTPBasicCredentials": extras.HTTPBasicCredentials,
        "HTTPBearer": extras.HTTPBearer,
        "HTTPAuthorizationCredentials": extras.HTTPAuthorizationCredentials,
        "APIKeyHeader": extras.APIKeyHeader,
        "APIKeyQuery": extras.APIKeyQuery,
        "APIKeyCookie": extras.APIKeyCookie,
    })

    middleware_mod = _get_or_create_module("fastapi.middleware")
    _patch_module(middleware_mod, {
        "CORSMiddleware": extras.CORSMiddleware, "GZipMiddleware": extras.GZipMiddleware,
        "HTTPSRedirectMiddleware": extras.HTTPSRedirectMiddleware,
        "TrustedHostMiddleware": extras.TrustedHostMiddleware, "Middleware": extras.Middleware,
        "BaseHTTPMiddleware": extras.BaseHTTPMiddleware,
    })
    for name, cls in [
        ("fastapi.middleware.cors", "CORSMiddleware"),
        ("fastapi.middleware.gzip", "GZipMiddleware"),
        ("fastapi.middleware.httpsredirect", "HTTPSRedirectMiddleware"),
        ("fastapi.middleware.trustedhost", "TrustedHostMiddleware"),
    ]:
        m = _get_or_create_module(name)
        _patch_module(m, {cls: getattr(extras, cls)})
    _patch_module(_get_or_create_module("fastapi.middleware.asyncexitstack"), {})
    _patch_module(_get_or_create_module("fastapi.middleware.wsgi"), {"WSGIMiddleware": extras._PassthroughMiddleware})

    _patch_module(_get_or_create_module("fastapi.staticfiles"), {"StaticFiles": extras.StaticFiles})
    _patch_module(_get_or_create_module("fastapi.templating"), {"Jinja2Templates": extras.Jinja2Templates})
    _patch_module(_get_or_create_module("fastapi.testclient"), {"TestClient": extras.TestClient})
    _patch_module(_get_or_create_module("fastapi.sse"), {"EventSourceResponse": extras.EventSourceResponse})
    _patch_module(fastapi_mod, {"TestClient": extras.TestClient})

    for name, mod in extras.make_misc_modules().items():
        sys.modules[name] = mod
    sys.modules["fastapi.openapi"] = extras.make_openapi_module()
    for name, mod in [
        ("fastapi.openapi.models", sys.modules["fastapi.openapi"].models),
        ("fastapi.openapi.utils", sys.modules["fastapi.openapi"].utils),
        ("fastapi.openapi.docs", sys.modules["fastapi.openapi"].docs),
        ("fastapi.openapi.constants", sys.modules["fastapi.openapi"].constants),
    ]:
        sys.modules[name] = mod

    # Apply docs/static submodule aliases to already-imported fastapi package.
    for name in list(sys.modules):
        if name.startswith("fastapi."):
            try:
                setattr(fastapi_mod, name.split(".", 1)[1].split(".", 1)[0], sys.modules[name])
            except Exception:
                pass

    # Also patch starlette modules commonly used alongside FastAPI.
    try:
        from starlette.responses import Response as SResponse
        _patch_module(_get_or_create_module("starlette.responses"), {"Response": Response, "JSONResponse": JSONResponse, "RedirectResponse": RedirectResponse, "PlainTextResponse": PlainTextResponse, "HTMLResponse": HTMLResponse})
    except Exception:
        pass
    try:
        _patch_module(_get_or_create_module("starlette.requests"), {"Request": Request})
    except Exception:
        pass
    try:
        _patch_module(_get_or_create_module("starlette.exceptions"), {"HTTPException": HTTPException, "WebSocketException": WebSocketException})
    except Exception:
        pass

    _installed = True


install_fastapi_compat = install

__all__ = [
    "install", "install_fastapi_compat", "CompatibilityWarning", "COMPAT_WARNING",
    "FastAPI", "APIRouter", "Request", "Response", "HTTPException", "WebSocketException",
    "RequestValidationError", "ValidationException", "Depends", "Security",
    "Query", "Path", "Header", "Cookie", "Body", "Form", "File",
    "UploadFile", "BackgroundTasks",
    "JSONResponse", "PlainTextResponse", "HTMLResponse", "RedirectResponse",
    "StreamingResponse", "FileResponse", "jsonable_encoder",
]
