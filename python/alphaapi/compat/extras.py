"""Extra FastAPI compatibility shims.

Everything here is best-effort. Features that AlphaAPI cannot provide are
implemented as inert placeholders that warn or raise clear errors instead of
silently pretending to work.
"""
from __future__ import annotations

import dataclasses
import http.client
import json as _json
import os
import socket
import threading
import time
import types
import urllib.parse
import warnings
from typing import Any, Callable, Mapping, Sequence

from .fastapi import (
    HTTPException,
    Request,
    _warn_unsupported,
)


# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class HTTPBasicCredentials:
    username: str
    password: str


@dataclasses.dataclass
class HTTPAuthorizationCredentials:
    scheme: str
    credentials: str


@dataclasses.dataclass
class OAuth2PasswordRequestForm:
    username: str = ""
    password: str = ""
    scope: str = ""
    grant_type: str | None = None
    client_id: str | None = None
    client_secret: str | None = None


class SecurityScopes:
    def __init__(self, scopes: Sequence[str] | None = None):
        self.scopes = list(scopes or [])


class SecurityRequirement(dict):
    pass


class _SecurityBase:
    scheme_name: str | None = None
    scopes: Mapping[str, str] | None = None

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.scheme_name = kwargs.get("scheme_name") or getattr(self, "scheme_name", None)

    def __call__(self, request: Request) -> Any:
        _warn_unsupported(f"{self.__class__.__name__} security dependency")
        raise HTTPException(status_code=401, detail="Not authenticated")

    def make_not_authenticated_error(self) -> HTTPException:
        return HTTPException(status_code=401, detail="Not authenticated")


SecurityBase = _SecurityBase


class HTTPBasic(_SecurityBase):
    pass


class HTTPBearer(_SecurityBase):
    def __init__(self, *, bearerFormat: str | None = None, scheme_name: str | None = None,
                 description: str | None = None, auto_error: bool = True):
        super().__init__(scheme_name=scheme_name, description=description, auto_error=auto_error)
        self.bearerFormat = bearerFormat
        self.auto_error = auto_error


class HTTPDigest(_SecurityBase):
    pass


class OAuth2(_SecurityBase):
    flows: Mapping[str, Any] | None = None

    def __init__(self, *, flows: Mapping[str, Any] | None = None, scheme_name: str | None = None,
                 description: str | None = None, auto_error: bool = True):
        super().__init__(scheme_name=scheme_name, description=description, auto_error=auto_error)
        self.flows = flows or {}


class OAuth2PasswordBearer(OAuth2):
    def __init__(self, tokenUrl: str, *, scheme_name: str | None = None,
                 scopes: Mapping[str, str] | None = None, description: str | None = None,
                 auto_error: bool = True):
        super().__init__(scheme_name=scheme_name, description=description, auto_error=auto_error)
        self.tokenUrl = tokenUrl
        self.scopes = scopes


class OAuth2AuthorizationCodeBearer(OAuth2):
    def __init__(self, authorizationUrl: str, tokenUrl: str, *, refreshUrl: str | None = None,
                 scheme_name: str | None = None, scopes: Mapping[str, str] | None = None,
                 description: str | None = None, auto_error: bool = True):
        super().__init__(scheme_name=scheme_name, description=description, auto_error=auto_error)
        self.authorizationUrl = authorizationUrl
        self.tokenUrl = tokenUrl
        self.refreshUrl = refreshUrl
        self.scopes = scopes


class OpenIdConnect(OAuth2):
    def __init__(self, openIdConnectUrl: str, *, scheme_name: str | None = None,
                 description: str | None = None, auto_error: bool = True):
        super().__init__(scheme_name=scheme_name, description=description, auto_error=auto_error)
        self.openIdConnectUrl = openIdConnectUrl


class APIKeyBase(_SecurityBase):
    pass


class APIKeyQuery(APIKeyBase):
    def __init__(self, name: str, *, scheme_name: str | None = None,
                 description: str | None = None, auto_error: bool = True):
        super().__init__(scheme_name=scheme_name, description=description, auto_error=auto_error)
        self.name = name


class APIKeyHeader(APIKeyQuery):
    pass


class APIKeyCookie(APIKeyQuery):
    pass


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

class Middleware:
    def __init__(self, cls: Any, **options: Any):
        self.cls = cls
        self.options = options


class BaseHTTPMiddleware:
    def __init__(self, app: Any, dispatch: Callable[..., Any] | None = None, **kwargs: Any):
        self.app = app
        self.dispatch_func = dispatch

    async def __call__(self, scope, receive, send):
        _warn_unsupported("BaseHTTPMiddleware")
        return await self.app(scope, receive, send)

    async def dispatch(self, request, call_next):
        return await call_next(request)


class _PassthroughMiddleware:
    def __init__(self, app: Any, **options: Any):
        self.app = app
        self.options = options
        _warn_unsupported(f"{self.__class__.__name__} (middleware is not applied)")

    async def __call__(self, scope, receive, send):
        return await self.app(scope, receive, send)


class CORSMiddleware(_PassthroughMiddleware):
    pass


class GZipMiddleware(_PassthroughMiddleware):
    pass


class HTTPSRedirectMiddleware(_PassthroughMiddleware):
    pass


class TrustedHostMiddleware(_PassthroughMiddleware):
    pass


# ---------------------------------------------------------------------------
# Static files / templates
# ---------------------------------------------------------------------------

class StaticFiles:
    def __init__(self, *, directory: str | os.PathLike[str] | None = None, packages: Any = None,
                 html: bool = False, check_dir: bool = True, **kwargs: Any):
        self.directory = str(directory) if directory is not None else None
        self.html = html
        self.packages = packages
        if check_dir and self.directory and not os.path.isdir(self.directory):
            raise RuntimeError(f"Directory {self.directory!r} does not exist")

    async def __call__(self, scope, receive, send):
        _warn_unsupported("StaticFiles mounting")
        raise RuntimeError("StaticFiles requires app.mount(), which AlphaAPI compat does not support")


class Jinja2Templates:
    def __init__(self, directory: str | os.PathLike[str] | Sequence[str], **env_options: Any):
        try:
            import jinja2
        except Exception as exc:  # pragma: no cover - depends on environment
            raise RuntimeError("Jinja2 is required for Jinja2Templates") from exc
        self.env = jinja2.Environment(loader=jinja2.FileSystemLoader(directory), **env_options)
        self.directory = directory

    def TemplateResponse(self, *args: Any, **kwargs: Any):
        _warn_unsupported("Jinja2Templates.TemplateResponse")
        from alphaapi.responses import HTMLResponse
        name = args[0] if args else kwargs.get("name")
        context = args[1] if len(args) > 1 else kwargs.get("context", {})
        if not isinstance(context, Mapping):
            context = {}
        template = self.env.get_template(str(name))
        return HTMLResponse(template.render(**dict(context)))


# ---------------------------------------------------------------------------
# SSE
# ---------------------------------------------------------------------------

class EventSourceResponse:
    def __init__(self, content: Any, status_code: int = 200, headers: Mapping[str, str] | None = None,
                 media_type: str | None = None, background: Any = None):
        _warn_unsupported("EventSourceResponse (server-sent events)")
        self.content = content
        self.status_code = status_code
        self.headers = dict(headers or {})
        self.media_type = media_type or "text/event-stream"
        self.background = background


# ---------------------------------------------------------------------------
# TestClient (starts the Alpha Rust server on a free port)
# ---------------------------------------------------------------------------

class _TestResponse:
    def __init__(self, status_code: int, headers: Mapping[str, str], content: bytes):
        self.status_code = status_code
        self.headers = dict(headers)
        self.content = content
        self.text = content.decode("utf-8", "replace")

    def json(self) -> Any:
        return _json.loads(self.content)

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300

    def __repr__(self) -> str:
        return f"<TestResponse [{self.status_code}]>"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class TestClient:
    """Minimal FastAPI TestClient replacement.

    It starts the AlphaAPI Rust server in a background thread for each client.
    For native ASGI testing use Starlette's TestClient with real FastAPI.
    """

    __test__ = False

    def __init__(self, app: Any, base_url: str = "http://testserver", raise_server_exceptions: bool = True,
                 root_path: str = "", backend: str = "asyncio", backend_options: dict | None = None,
                 cookies: Any = None, headers: Any = None, follow_redirects: bool = True):
        self.app = app
        self.base_url = base_url
        self.raise_server_exceptions = raise_server_exceptions
        self.follow_redirects = follow_redirects
        self.headers = dict(headers or {})
        self.cookies = dict(cookies or {})
        self._port: int | None = None
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "TestClient":
        self._start()
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    def _start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        port = _free_port()
        self._port = port
        self._thread = threading.Thread(
            target=self.app.run,
            kwargs={"host": "127.0.0.1", "port": port},
            daemon=True,
        )
        self._thread.start()
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                    return
            except OSError:
                time.sleep(0.02)
        raise RuntimeError("AlphaAPI test server did not start")

    def close(self) -> None:
        try:
            self.app.stop()
        except Exception:
            pass
        if self._thread:
            self._thread.join(timeout=10)

    def request(self, method: str, url: str, *, content: bytes | None = None, data: Any = None,
                files: Any = None, json: Any = None, params: Any = None, headers: Mapping[str, str] | None = None,
                cookies: Any = None, **kwargs: Any) -> _TestResponse:
        self._start()
        parsed = urllib.parse.urlsplit(url)
        path = parsed.path or "/"
        query = parsed.query
        if params:
            extra = urllib.parse.urlencode(params, doseq=True)
            query = f"{query}&{extra}" if query else extra
        if query:
            path = f"{path}?{query}"
        body = content
        merged_headers = dict(self.headers)
        merged_headers.update(headers or {})
        if json is not None:
            body = _json.dumps(json).encode()
            merged_headers.setdefault("content-type", "application/json")
        elif data is not None and body is None:
            if isinstance(data, (dict, list)):
                body = urllib.parse.urlencode(data, doseq=True).encode()
                merged_headers.setdefault("content-type", "application/x-www-form-urlencoded")
            else:
                body = data
        if files:
            _warn_unsupported("TestClient files/multipart uploads")
        all_cookies = {**self.cookies, **dict(cookies or {})}
        if all_cookies:
            merged_headers.setdefault("cookie", "; ".join(f"{k}={v}" for k, v in all_cookies.items()))
        conn = http.client.HTTPConnection("127.0.0.1", self._port, timeout=30)
        try:
            conn.request(method.upper(), path, body=body, headers=merged_headers)
            response = conn.getresponse()
            payload = response.read()
            return _TestResponse(response.status, {k.lower(): v for k, v in response.getheaders()}, payload)
        finally:
            conn.close()

    def get(self, url: str, **kwargs: Any) -> _TestResponse:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> _TestResponse:
        return self.request("POST", url, **kwargs)

    def put(self, url: str, **kwargs: Any) -> _TestResponse:
        return self.request("PUT", url, **kwargs)

    def patch(self, url: str, **kwargs: Any) -> _TestResponse:
        return self.request("PATCH", url, **kwargs)

    def delete(self, url: str, **kwargs: Any) -> _TestResponse:
        return self.request("DELETE", url, **kwargs)

    def options(self, url: str, **kwargs: Any) -> _TestResponse:
        return self.request("OPTIONS", url, **kwargs)

    def head(self, url: str, **kwargs: Any) -> _TestResponse:
        return self.request("HEAD", url, **kwargs)

    def websocket_connect(self, url: str, **kwargs: Any):
        _warn_unsupported("TestClient.websocket_connect")
        raise RuntimeError("WebSockets are not supported by AlphaAPI compat")


# ---------------------------------------------------------------------------
# Misc module factories
# ---------------------------------------------------------------------------

def make_openapi_module() -> types.ModuleType:
    mod = types.ModuleType("fastapi.openapi")
    models = types.ModuleType("fastapi.openapi.models")
    for name in ("OpenAPI", "Info", "Contact", "License", "Server", "ServerVariable", "Components",
                 "Schema", "Reference", "Parameter", "RequestBody", "Response", "Operation",
                 "PathItem", "Paths", "MediaType", "Example", "Tag", "ExternalDocumentation",
                 "SecurityRequirement", "SecurityScheme", "OAuthFlows", "OAuthFlow"):
        setattr(models, name, type(name, (dict,), {}))
    utils = types.ModuleType("fastapi.openapi.utils")

    def get_openapi(*args: Any, **kwargs: Any) -> dict:
        app = kwargs.get("app") or (args[0] if args else None)
        if hasattr(app, "openapi"):
            return app.openapi()
        return {"openapi": "3.1.0", "info": {"title": "API", "version": "0.1.0"}, "paths": {}}

    utils.get_openapi = get_openapi
    utils.get_openapi_path = lambda *a, **k: {}
    utils.get_openapi_operation_id = lambda *a, **k: "operation"
    utils.get_openapi_operation_parameters = lambda *a, **k: []
    utils.get_openapi_operation_request_body = lambda *a, **k: None
    utils.get_openapi_security_definitions = lambda *a, **k: ({}, [])
    utils.get_openapi_operation_metadata = lambda *a, **k: {}
    docs = types.ModuleType("fastapi.openapi.docs")
    docs.get_swagger_ui_html = lambda **kwargs: ""
    docs.get_redoc_html = lambda **kwargs: ""
    docs.get_swagger_ui_oauth2_redirect_html = lambda: ""
    constants = types.ModuleType("fastapi.openapi.constants")
    constants.OPENAPI_DOCS_URL = "/docs"
    mod.models = models
    mod.utils = utils
    mod.docs = docs
    mod.constants = constants
    return mod


def make_misc_modules() -> dict[str, types.ModuleType]:
    modules: dict[str, types.ModuleType] = {}

    utils = types.ModuleType("fastapi.utils")
    utils.generate_operation_id_for_path = lambda **kwargs: "operation"
    utils.create_model_field = lambda *a, **k: None
    utils.create_response_field = lambda *a, **k: None
    utils.create_cloned_field = lambda *a, **k: None
    utils.is_body_field = lambda *a, **k: False
    utils.deep_dict_update = lambda d, u: d.update(u) or d
    utils.get_model_definitions = lambda *a, **k: {}
    utils.get_path_param_names = lambda path: [
        part[1:-1] for part in str(path).split("/") if part.startswith("{") and part.endswith("}")
    ]
    modules["fastapi.utils"] = utils

    types_mod = types.ModuleType("fastapi.types")
    types_mod.ModelNameMap = dict
    modules["fastapi.types"] = types_mod

    logger = types.ModuleType("fastapi.logger")
    import logging
    logger.logger = logging.getLogger("fastapi")
    modules["fastapi.logger"] = logger

    concurrency = types.ModuleType("fastapi.concurrency")
    async def _run_in_threadpool(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        import asyncio
        return await asyncio.to_thread(func, *args, **kwargs)
    concurrency.run_in_threadpool = _run_in_threadpool
    concurrency.contextmanager_in_threadpool = lambda cm: cm
    concurrency.asynccontextmanager_in_threadpool = lambda cm: cm
    modules["fastapi.concurrency"] = concurrency

    eh = types.ModuleType("fastapi.exception_handlers")
    eh.http_exception_handler = None
    eh.request_validation_exception_handler = None
    eh.websocket_request_validation_exception_handler = None
    modules["fastapi.exception_handlers"] = eh

    return modules
