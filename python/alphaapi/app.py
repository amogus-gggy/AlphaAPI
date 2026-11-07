"""The main application and router objects."""
from __future__ import annotations

import asyncio
import dataclasses
import inspect
from typing import Any, Callable, Iterable

from . import _core
from .exceptions import HTTPException
from .introspect import Spec, build_spec
from .responses import HTMLResponse

_SWAGGER_HTML = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title} - Docs</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css" />
  <style>body {{ margin: 0; }}</style>
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
  <script>
    SwaggerUIBundle({{ url: "{openapi_url}", dom_id: "#swagger-ui", deepLinking: true }});
  </script>
</body>
</html>
"""


def _join_paths(prefix: str, path: str) -> str:
    if not prefix:
        return path or "/"
    if not path:
        return prefix
    return prefix.rstrip("/") + "/" + path.lstrip("/")


def _schema_for(param: ParamInfo) -> dict[str, Any]:
    if param.type == "model" and param.model is not None:
        return _model_schema(param.model)
    mapping = {
        "str": {"type": "string"},
        "int": {"type": "integer"},
        "float": {"type": "number"},
        "bool": {"type": "boolean"},
        "json": {},
        "bytes": {"type": "string", "format": "binary"},
        "str_list": {"type": "array", "items": {"type": "string"}},
    }
    return mapping.get(param.type, {})


def _annotation_schema(annotation: Any) -> dict[str, Any]:
    if annotation in (str, "str"):
        return {"type": "string"}
    if annotation in (int, "int"):
        return {"type": "integer"}
    if annotation in (float, "float"):
        return {"type": "number"}
    if annotation in (bool, "bool"):
        return {"type": "boolean"}
    return {}


def _model_schema(model: Any) -> dict[str, Any]:
    dump = getattr(model, "model_json_schema", None)
    if callable(dump):
        try:
            return dump()
        except Exception:
            pass
    legacy = getattr(model, "schema", None)
    if callable(legacy):
        try:
            return legacy()
        except Exception:
            pass
    if dataclasses.is_dataclass(model):
        properties = {
            field.name: _annotation_schema(field.type)
            for field in dataclasses.fields(model)
        }
        return {"type": "object", "title": model.__name__, "properties": properties}
    return {"type": "object"}


@dataclasses.dataclass
class Route:
    path: str
    endpoint: Callable[..., Any]
    methods: tuple[str, ...]
    status_code: int
    tags: list[str]
    summary: str | None
    description: str | None
    include_in_schema: bool
    spec: Spec
    response_description: str = "Successful Response"

    def copy(self, **changes: Any) -> "Route":
        return dataclasses.replace(self, **changes)


class APIRouter:
    """Collects routes. Use ``include_router`` to compose applications."""

    def __init__(self, *, prefix: str = "", tags: Iterable[str] | None = None) -> None:
        self.prefix = prefix or ""
        self.tags = list(tags or [])
        self.routes: list[Route] = []

    # -- route registration -------------------------------------------------

    def api_route(
        self,
        path: str,
        *,
        methods: Iterable[str] | None = None,
        status_code: int = 200,
        tags: Iterable[str] | None = None,
        summary: str | None = None,
        description: str | None = None,
        include_in_schema: bool = True,
        response_description: str = "Successful Response",
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        methods = tuple(method.upper() for method in (methods or ["GET"]))

        def decorator(endpoint: Callable[..., Any]) -> Callable[..., Any]:
            self.add_api_route(
                path,
                endpoint,
                methods=methods,
                status_code=status_code,
                tags=tags,
                summary=summary,
                description=description,
                include_in_schema=include_in_schema,
                response_description=response_description,
            )
            return endpoint

        return decorator

    def add_api_route(
        self,
        path: str,
        endpoint: Callable[..., Any],
        *,
        methods: Iterable[str] | None = None,
        status_code: int = 200,
        tags: Iterable[str] | None = None,
        summary: str | None = None,
        description: str | None = None,
        include_in_schema: bool = True,
        response_description: str = "Successful Response",
    ) -> Route:
        methods = tuple(method.upper() for method in (methods or ["GET"]))
        full_path = _join_paths(self.prefix, path)
        spec = build_spec(endpoint, full_path, status_code)
        route = Route(
            path=full_path,
            endpoint=endpoint,
            methods=methods,
            status_code=status_code,
            tags=self.tags + list(tags or []),
            summary=summary,
            description=description,
            include_in_schema=include_in_schema,
            spec=spec,
            response_description=response_description,
        )
        self.routes.append(route)
        self._on_route_added(route)
        return route

    def include_router(
        self,
        router: "APIRouter",
        *,
        prefix: str = "",
        tags: Iterable[str] | None = None,
    ) -> None:
        extra_tags = self.tags + list(tags or [])
        for route in router.routes:
            self.routes.append(
                route.copy(
                    path=_join_paths(self.prefix, _join_paths(prefix, route.path)),
                    tags=route.tags + extra_tags,
                )
            )
            self._on_route_added(self.routes[-1])

    def _on_route_added(self, route: Route) -> None:  # pragma: no cover - overridden
        pass

    # -- method shortcuts ---------------------------------------------------

    def get(self, path: str, **kwargs: Any) -> Callable[..., Any]:
        return self.api_route(path, methods=["GET"], **kwargs)

    def post(self, path: str, **kwargs: Any) -> Callable[..., Any]:
        return self.api_route(path, methods=["POST"], **kwargs)

    def put(self, path: str, **kwargs: Any) -> Callable[..., Any]:
        return self.api_route(path, methods=["PUT"], **kwargs)

    def patch(self, path: str, **kwargs: Any) -> Callable[..., Any]:
        return self.api_route(path, methods=["PATCH"], **kwargs)

    def delete(self, path: str, **kwargs: Any) -> Callable[..., Any]:
        return self.api_route(path, methods=["DELETE"], **kwargs)

    def options(self, path: str, **kwargs: Any) -> Callable[..., Any]:
        return self.api_route(path, methods=["OPTIONS"], **kwargs)

    def head(self, path: str, **kwargs: Any) -> Callable[..., Any]:
        return self.api_route(path, methods=["HEAD"], **kwargs)


class Alpha(APIRouter):
    """A FastAPI-inspired application backed by a Rust HTTP server.

    Example::

        from alphaapi import Alpha

        app = Alpha()

        @app.get("/")
        def read_root():
            return {"hello": "world"}

        app.run()
    """

    def __init__(
        self,
        *,
        title: str = "AlphaAPI",
        version: str = "0.1.0",
        description: str | None = None,
        docs: bool = True,
        openapi_url: str = "/openapi.json",
        docs_url: str = "/docs",
        prefix: str = "",
        tags: Iterable[str] | None = None,
    ) -> None:
        super().__init__(prefix=prefix, tags=tags)
        self.title = title
        self.version = version
        self.description = description
        self.docs = docs
        self.openapi_url = openapi_url
        self.docs_url = docs_url

        self._core = _core.AppCore()
        self._exception_handlers: dict[type[BaseException], Callable[..., Any]] = {}
        self._startup: list[Callable[..., Any]] = []
        self._shutdown: list[Callable[..., Any]] = []
        self._docs_registered = False
        self._handlers_registered = False

    # -- Rust registration --------------------------------------------------

    def _on_route_added(self, route: Route) -> None:
        spec = route.spec.to_dict()
        for method in route.methods:
            self._core.add_route(method, route.path, route.endpoint, spec)

    # -- lifecycle ----------------------------------------------------------

    def on_startup(self, func: Callable[..., Any]) -> Callable[..., Any]:
        self._startup.append(func)
        return func

    def on_shutdown(self, func: Callable[..., Any]) -> Callable[..., Any]:
        self._shutdown.append(func)
        return func

    def exception_handler(
        self, exc_type: type[BaseException]
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            self._exception_handlers[exc_type] = func
            return func

        return decorator

    @staticmethod
    def _run_lifecycle(funcs: Iterable[Callable[..., Any]]) -> None:
        for func in funcs:
            if inspect.iscoroutinefunction(func):
                asyncio.run(func())
            else:
                result = func()
                if inspect.isawaitable(result):
                    asyncio.run(result)

    def stop(self) -> None:
        """Ask a running server to shut down."""
        self._core.stop()

    # -- OpenAPI / docs -----------------------------------------------------

    def openapi(self) -> dict[str, Any]:
        paths: dict[str, dict[str, Any]] = {}
        for route in self.routes:
            if not route.include_in_schema:
                continue
            for method in route.methods:
                operation: dict[str, Any] = {
                    "summary": route.summary
                    or route.endpoint.__name__.replace("_", " ").title(),
                    "operationId": f"{route.endpoint.__name__}_{method.lower()}",
                    "responses": {
                        str(route.status_code): {
                            "description": route.response_description
                        }
                    },
                }
                if route.description:
                    operation["description"] = route.description
                if route.tags:
                    operation["tags"] = route.tags

                parameters = []
                request_body = None
                for param in route.spec.params:
                    if param.kind in ("path", "query", "header"):
                        entry: dict[str, Any] = {
                            "name": param.alias,
                            "in": param.kind,
                            "required": param.required or param.kind == "path",
                            "schema": _schema_for(param),
                        }
                        if param.description:
                            entry["description"] = param.description
                        parameters.append(entry)
                    elif param.kind == "body":
                        media_type = (
                            "application/octet-stream"
                            if param.type == "bytes"
                            else "application/json"
                        )
                        request_body = {
                            "content": {media_type: {"schema": _schema_for(param)}},
                            "required": param.required,
                        }

                if parameters:
                    operation["parameters"] = parameters
                if request_body is not None:
                    operation["requestBody"] = request_body
                paths.setdefault(route.path, {})[method.lower()] = operation

        info: dict[str, Any] = {"title": self.title, "version": self.version}
        if self.description:
            info["description"] = self.description
        return {
            "openapi": "3.1.0",
            "info": info,
            "paths": paths,
        }

    def _swagger_ui(self) -> HTMLResponse:
        return HTMLResponse(
            _SWAGGER_HTML.format(
                title=self.title,
                openapi_url=self.openapi_url or "/openapi.json",
            )
        )

    def _ensure_docs(self) -> None:
        if self._docs_registered:
            return
        self._docs_registered = True
        if not self.docs:
            return
        if self.openapi_url:
            self.add_api_route(
                self.openapi_url,
                self.openapi,
                methods=["GET"],
                include_in_schema=False,
            )
        if self.docs_url:
            self.add_api_route(
                self.docs_url,
                self._swagger_ui,
                methods=["GET"],
                include_in_schema=False,
            )

    # -- running ------------------------------------------------------------

    def run(
        self,
        host: str = "127.0.0.1",
        port: int = 8000,
        *,
        workers: int | None = None,
        max_body_size: int = 16 * 1024 * 1024,
        access_log: bool = False,
    ) -> None:
        """Start the server and block until shutdown."""
        self._ensure_docs()
        if not self._handlers_registered:
            self._handlers_registered = True
            self._core.set_http_exception_type(HTTPException)
            for exc_type, handler in self._exception_handlers.items():
                self._core.add_exception_handler(exc_type, handler)

        self._run_lifecycle(self._startup)
        try:
            self._core.run(
                host=host,
                port=port,
                workers=workers,
                max_body_size=max_body_size,
                access_log=access_log,
            )
        finally:
            self._run_lifecycle(self._shutdown)

    def __repr__(self) -> str:
        return f"<Alpha {self.title!r} routes={len(self.routes)}>"


__all__ = ["APIRouter", "Alpha", "Route"]
