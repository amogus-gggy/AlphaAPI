"""The AlphaAPI application object.

The design is deliberately Django-shaped: settings, URLconfs, function and
class-based views, middleware and an app registry.  Everything is async-native,
and the HTTP server/routing hot path stays in Rust.
"""
from __future__ import annotations

import importlib
import inspect
import signal
import threading
from collections.abc import Iterable
from types import SimpleNamespace
from typing import Any, Callable

from . import _core
from .apps import AppRegistry
from .conf import ScopedSettings, Settings, settings
from .exceptions import Http404, HTTPException, PermissionDenied
from .http import (
    HttpRequest,
    HttpResponse,
    HttpResponseForbidden,
    HttpResponseNotFound,
    JsonResponse,
)
from .middleware import is_async_callable
from .params import build_param_specs, positional_only_names, wants_request
from .urls import (
    ImproperlyConfigured,
    ResolvedPattern,
    register_patterns,
)
from .urls import (
    reverse as reverse_url,
)
from .views import View

HTTP_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD", "TRACE")


def import_string(path: str) -> Any:
    module_name, separator, attribute = path.rpartition(".")
    if not separator:
        raise ImportError(f"invalid import path {path!r}")
    module = importlib.import_module(module_name)
    try:
        return getattr(module, attribute)
    except AttributeError as error:
        raise ImportError(f"module {module_name!r} has no attribute {attribute!r}") from error


def _is_view_async(view: Callable[..., Any]) -> bool:
    return inspect.iscoroutinefunction(view) or bool(
        getattr(view, "__alphaapi_async__", False)
    )


def _ensure_response(value: Any) -> Any:
    if isinstance(value, _core.Response):
        return value
    if value is None:
        return HttpResponse(b"", status=204)
    if isinstance(value, str):
        return HttpResponse(value)
    if isinstance(value, (bytes, bytearray)):
        return HttpResponse(bytes(value), content_type="application/octet-stream")
    return JsonResponse(value, safe=False)


class Application:
    """An AlphaAPI project.

    ``urlpatterns`` may be passed directly or discovered from
    ``settings.ROOT_URLCONF``::

        from alphaapi import Application, path
        from . import views

        app = Application(urlpatterns=[path("", views.index)])
    """

    def __init__(
        self,
        *,
        urlpatterns: Iterable[Any] | None = None,
        urls: Iterable[Any] | str | None = None,
        settings_module: str | None = None,
        settings_config: dict[str, Any] | None = None,
        middleware: Iterable[Any] | None = None,
        installed_apps: Iterable[Any] | None = None,
        title: str | None = None,
        version: str | None = None,
        debug: bool | None = None,
    ) -> None:
        # Settings overrides stay local to this application.  Reads fall back
        # to the process-wide settings object, so later global changes (for
        # example in tests) are still observed unless explicitly overridden.
        scoped = ScopedSettings(settings)
        if settings_module:
            scoped.configure_from_module(settings_module)
        if settings_config:
            scoped.configure(**settings_config)
        if title is not None:
            scoped.TITLE = title
        if version is not None:
            scoped.VERSION = version
        if debug is not None:
            scoped.DEBUG = debug
        if installed_apps is not None:
            scoped.INSTALLED_APPS = list(installed_apps)

        self.settings: Settings | ScopedSettings = scoped
        self.title = self.settings.TITLE
        self.version = self.settings.VERSION
        self.debug = bool(self.settings.DEBUG)

        # Each application owns its app registry and named-route table so two
        # applications in one process cannot observe each other's routes/apps.
        self.apps: AppRegistry = AppRegistry()
        self.apps.populate(self.settings.INSTALLED_APPS)

        supplied_urls = urlpatterns if urlpatterns is not None else urls
        self._urlpatterns: list[Any] = []
        if supplied_urls is not None:
            self._urlpatterns.extend(self._coerce_patterns(supplied_urls))
        elif self.settings.ROOT_URLCONF:
            self._urlpatterns.extend(self._load_urlconf(self.settings.ROOT_URLCONF))

        self.middleware: list[Any] = list(
            middleware if middleware is not None else self.settings.MIDDLEWARE
        )

        self._add_builtin_urls()

        self._core = _core.AppCore()
        self._exception_handlers: dict[type[BaseException], Callable[..., Any]] = {}
        self._startup: list[Callable[..., Any]] = []
        self._shutdown: list[Callable[..., Any]] = []
        self._resolved: list[ResolvedPattern] = []
        self._named_patterns: dict[str, ResolvedPattern] = {}
        self._middleware_chain: Callable[..., Any] | None = None
        self._registered = False
        self._handlers_registered = False

    # -- URL configuration --------------------------------------------------

    def _add_builtin_urls(self) -> None:
        """Add optional static/OpenAPI routes before the first resolve."""
        from .urls import path

        existing = {getattr(pattern, "route", None) for pattern in self._urlpatterns}

        static_root = getattr(self.settings, "STATIC_ROOT", None)
        if static_root:
            from .staticfiles import StaticFiles

            prefix = "/" + str(getattr(self.settings, "STATIC_URL", "/static/")).strip("/") + "/"
            route = prefix + "<path:path>"
            if route not in existing:
                self._urlpatterns.append(
                    path(
                        route,
                        StaticFiles(str(static_root), prefix),
                        name="static",
                    )
                )

        if bool(getattr(self.settings, "ENABLE_OPENAPI", False)):
            from .openapi import docs_view, openapi_view

            openapi_url = str(getattr(self.settings, "OPENAPI_URL", "/openapi.json")).lstrip("/")
            docs_url = str(getattr(self.settings, "DOCS_URL", "/docs")).lstrip("/")
            if openapi_url not in {str(route or "").lstrip("/") for route in existing}:
                self._urlpatterns.append(
                    path(openapi_url, openapi_view(self), name="openapi")
                )
            if docs_url not in {str(route or "").lstrip("/") for route in existing}:
                self._urlpatterns.append(path(docs_url, docs_view(self), name="api-docs"))

    @property
    def urlpatterns(self) -> list[Any]:
        return list(self._urlpatterns)

    def openapi(self) -> dict[str, Any]:
        """Return an OpenAPI 3 document for the application."""
        from .openapi import build_openapi

        return build_openapi(self)

    def test_client(self, **kwargs: Any) -> Any:
        from .testing import Client

        return Client(self, **kwargs)

    @staticmethod
    def _coerce_patterns(source: Iterable[Any] | str | Any) -> list[Any]:
        if isinstance(source, str):
            return Application._load_urlconf(source)
        if hasattr(source, "urlpatterns") and not isinstance(source, (list, tuple)):
            return list(source.urlpatterns)
        return list(source)

    @staticmethod
    def _load_urlconf(path: str) -> list[Any]:
        module = importlib.import_module(path)
        patterns = getattr(module, "urlpatterns", None)
        if patterns is None:
            raise ImproperlyConfigured(
                f"URLconf module {path!r} does not define urlpatterns"
            )
        return list(patterns)

    def add_url_patterns(self, patterns: Iterable[Any] | str | Any) -> None:
        """Append more URL patterns before the server starts."""
        if self._registered:
            raise RuntimeError("cannot add URL patterns after the server has started")
        self._urlpatterns.extend(self._coerce_patterns(patterns))
        # Force reverse()/route registration to rebuild from the new list.
        self._resolved = []
        self._named_patterns.clear()

    def reverse(
        self,
        viewname: str,
        args: Iterable[Any] | None = None,
        kwargs: dict[str, Any] | None = None,
    ) -> str:
        self._ensure_resolved()
        return reverse_url(
            viewname, args=args, kwargs=kwargs, registry=self._named_patterns
        )

    def _ensure_resolved(self) -> None:
        if self._resolved:
            return
        self._resolved = register_patterns(
            self._urlpatterns, registry=self._named_patterns
        )

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

    def _run_lifecycle(self, funcs: Iterable[Callable[..., Any]]) -> None:
        # Startup/shutdown hooks run on the same asyncio loop that drives async
        # views, so pools and clients created here stay usable during requests.
        for func in funcs:
            result = func()
            if inspect.isawaitable(result):
                self._core.run_on_event_loop(result)

    def stop(self) -> None:
        """Ask a running server to shut down."""
        self._core.stop()

    # -- request handling ---------------------------------------------------

    def _resolve_view(self, view: Any) -> Callable[..., Any]:
        if isinstance(view, str):
            view = import_string(view)
        if isinstance(view, type):
            if issubclass(view, View):
                view = view.as_view()
            else:
                raise TypeError(
                    f"URL view {view!r} is a class but does not subclass alphaapi.View"
                )
        if not callable(view):
            raise TypeError(f"URL view {view!r} is not callable")
        return view

    def _has_exception_handler(self, exc_type: type[BaseException]) -> bool:
        return any(
            issubclass(exc_type, registered)
            for registered in self._exception_handlers
        )

    def _make_handler(
        self, pattern: ResolvedPattern
    ) -> tuple[Callable[..., Any], bool, Callable[..., Any]]:
        view = self._resolve_view(pattern.view)
        converters = pattern.converters
        view_wants_request = wants_request(view)
        has_middleware = bool(self.middleware)
        # The wrapper only receives a raw request when the view or middleware
        # will actually use one.  This is what keeps the core's lazy request
        # materialisation reachable for views like ``async def health()``.
        handler_needs_request = view_wants_request or has_middleware

        def split_kwargs(
            values: dict[str, Any]
        ) -> tuple[dict[str, Any], dict[str, Any]]:
            path_values: dict[str, Any] = {}
            extra_values: dict[str, Any] = {}
            for name, value in values.items():
                converter = converters.get(name)
                if converter is None:
                    extra_values[name] = value
                    continue
                try:
                    path_values[name] = converter.to_python(value)
                except (TypeError, ValueError) as error:
                    raise Http404(
                        f"No match for {name}={value!r} in URL {pattern.django_path!r}"
                    ) from error
            return path_values, extra_values

        def invoke(
            request: HttpRequest | None,
            path_kwargs: dict[str, Any],
            extra_kwargs: dict[str, Any],
        ) -> Any:
            values = {**pattern.kwargs, **path_kwargs, **extra_kwargs}
            if view_wants_request:
                return view(request, **values)
            return view(**values)

        def build_request(
            raw_request: Any,
            path_kwargs: dict[str, Any],
            extra_kwargs: dict[str, Any],
        ) -> HttpRequest:
            request = HttpRequest(raw_request)
            request._alpha_kwargs = extra_kwargs  # type: ignore[attr-defined]
            request.resolver_match = SimpleNamespace(  # type: ignore[attr-defined]
                kwargs=path_kwargs,
                url_name=pattern.name,
                route=pattern.django_path,
            )
            return request

        def handle_error(error: BaseException) -> Any:
            if isinstance(error, Http404):
                if self._has_exception_handler(type(error)):
                    raise error
                return HttpResponseNotFound(str(error) or "Not Found")
            if isinstance(error, PermissionDenied):
                if self._has_exception_handler(type(error)):
                    raise error
                return HttpResponseForbidden(str(error) or "Forbidden")
            raise error

        view_is_async = _is_view_async(view)

        if view_is_async or has_middleware:
            chain = self._ensure_middleware_chain() if has_middleware else None

            async def async_handler(raw_request: Any = None, **kwargs: Any) -> Any:
                try:
                    path_kwargs, extra_kwargs = split_kwargs(kwargs)
                    request = (
                        build_request(raw_request, path_kwargs, extra_kwargs)
                        if handler_needs_request
                        else None
                    )
                    if has_middleware:
                        assert request is not None and chain is not None
                        request._alpha_handler = (  # type: ignore[attr-defined]
                            lambda req: invoke(req, path_kwargs, extra_kwargs)
                        )
                        response = chain(request)
                    else:
                        response = invoke(request, path_kwargs, extra_kwargs)
                    if inspect.isawaitable(response):
                        response = await response
                except (Http404, PermissionDenied) as error:
                    return _ensure_response(handle_error(error))
                return _ensure_response(response)

            async_handler.__alphaapi_async__ = True  # type: ignore[attr-defined]
            return async_handler, True, view

        def sync_handler(raw_request: Any = None, **kwargs: Any) -> Any:
            try:
                path_kwargs, extra_kwargs = split_kwargs(kwargs)
                request = (
                    build_request(raw_request, path_kwargs, extra_kwargs)
                    if handler_needs_request
                    else None
                )
                return _ensure_response(invoke(request, path_kwargs, extra_kwargs))
            except (Http404, PermissionDenied) as error:
                return _ensure_response(handle_error(error))

        return sync_handler, False, view

    async def _middleware_terminal(self, request: HttpRequest) -> Any:
        """The single endpoint shared by the application-wide middleware chain."""
        handler = getattr(request, "_alpha_handler", None)
        if handler is None:
            raise RuntimeError("middleware received a request without a view")
        result = handler(request)
        if inspect.isawaitable(result):
            result = await result
        return result

    def _ensure_middleware_chain(self) -> Callable[..., Any]:
        if self._middleware_chain is None:
            self._middleware_chain = self._build_async_chain(
                self._middleware_terminal
            )
        return self._middleware_chain

    def _build_async_chain(self, final: Callable[..., Any]) -> Callable[..., Any]:
        async def get_response(request: HttpRequest) -> Any:
            result = final(request)
            if inspect.isawaitable(result):
                result = await result
            return result

        handler: Callable[..., Any] = get_response
        for entry in reversed(self.middleware):
            if isinstance(entry, str):
                entry = import_string(entry)
            handler = entry(handler)
        return handler

    def _build_spec(
        self,
        pattern: ResolvedPattern,
        is_async: bool,
        view: Callable[..., Any],
    ) -> dict[str, Any]:
        params: list[dict[str, Any]] = []
        if wants_request(view) or self.middleware:
            params.append(
                {
                    "name": "request",
                    "alias": "request",
                    "kind": "request",
                    "type": "request",
                    "required": True,
                    "default": None,
                    "model": None,
                    "positional": True,
                }
            )
        # Path values are extracted as strings by Rust and converted by the
        # Django path converters in Python.  This keeps conversion semantics
        # (including custom converters) in one place and produces a 404 rather
        # than a validation error for a non-matching value.
        positional_paths = positional_only_names(view)
        for name in pattern.converters:
            params.append(
                {
                    "name": name,
                    "alias": name,
                    "kind": "path",
                    "type": "str",
                    "required": True,
                    "default": None,
                    "model": None,
                    "positional": name in positional_paths,
                }
            )
        params.extend(build_param_specs(view, set(pattern.converters)))
        return {
            "params": params,
            "is_async": is_async,
            "status_code": 200,
        }

    def _ensure_registered(self) -> None:
        if self._registered:
            return
        # Build everything before touching the core.  If resolution or spec
        # construction fails, the flag stays false and a later call can retry
        # instead of silently starting with a partially registered route table.
        self._ensure_resolved()
        if self.middleware:
            self._ensure_middleware_chain()
        prepared = []
        for pattern in self._resolved:
            handler, is_async, view = self._make_handler(pattern)
            spec = self._build_spec(pattern, is_async, view)
            prepared.append((pattern, handler, spec))
        for pattern, handler, spec in prepared:
            for method in HTTP_METHODS:
                self._core.add_route(method, pattern.router_path, handler, spec)
        self._registered = True

    def _ensure_exception_handlers(self) -> None:
        if self._handlers_registered:
            return
        handlers: list[tuple[type[BaseException], Callable[..., Any]]] = []
        for exc_type, handler in self._exception_handlers.items():
            if is_async_callable(handler):

                async def wrapped(
                    raw_request: Any, exception: Any, _handler: Any = handler
                ) -> Any:
                    return await _handler(HttpRequest(raw_request), exception)

            else:

                def wrapped(raw_request: Any, exception: Any, _handler: Any = handler) -> Any:
                    return _handler(HttpRequest(raw_request), exception)

            handlers.append((exc_type, wrapped))
        self._core.set_http_exception_type(HTTPException)
        for exc_type, wrapped in handlers:
            self._core.add_exception_handler(exc_type, wrapped)
        self._handlers_registered = True

    # -- running ------------------------------------------------------------

    def run(
        self,
        host: str = "127.0.0.1",
        port: int = 8000,
        *,
        workers: int | None = None,
        max_body_size: int | None = None,
        access_log: bool | None = None,
    ) -> None:
        """Start the Rust server and block until shutdown."""
        self._ensure_registered()
        self._ensure_exception_handlers()

        if max_body_size is None:
            max_body_size = int(self.settings.MAX_BODY_SIZE)
        if access_log is None:
            access_log = bool(self.settings.ACCESS_LOG)

        config = {
            "allowed_hosts": [str(item) for item in self.settings.ALLOWED_HOSTS],
            "trusted_proxies": [str(item) for item in self.settings.TRUSTED_PROXIES],
            "trust_proxy_headers": bool(self.settings.TRUST_PROXY_HEADERS),
            "debug": bool(self.settings.DEBUG),
            "access_log_json": bool(self.settings.ACCESS_LOG_JSON),
            "security_headers": bool(self.settings.SECURITY_HEADERS),
            "hsts_seconds": int(self.settings.SECURE_HSTS_SECONDS or 0),
            "hsts_include_subdomains": bool(
                self.settings.SECURE_HSTS_INCLUDE_SUBDOMAINS
            ),
            "referrer_policy": str(self.settings.SECURE_REFERRER_POLICY),
            "x_frame_options": str(self.settings.X_FRAME_OPTIONS),
            "request_timeout": self.settings.REQUEST_TIMEOUT,
            "max_concurrent_requests": self.settings.MAX_CONCURRENT_REQUESTS,
            "offload_sync_views": bool(self.settings.OFFLOAD_SYNC_VIEWS),
            "http2_max_concurrent_streams": self.settings.HTTP2_MAX_CONCURRENT_STREAMS,
            "http2_initial_window_size": self.settings.HTTP2_INITIAL_WINDOW_SIZE,
            "http2_keep_alive_interval": self.settings.HTTP2_KEEP_ALIVE_INTERVAL,
            "http2_keep_alive_timeout": self.settings.HTTP2_KEEP_ALIVE_TIMEOUT,
        }

        # SIGINT needs special care.  The Rust server installs its own handler
        # while it runs, but there is a window before that where Python's
        # default handler would raise KeyboardInterrupt in the middle of
        # startup, and a window during cleanup where it would abort joining the
        # asyncio bridge.  On the main thread, run the blocking server in a
        # worker thread so the main thread can always catch SIGINT and ask the
        # core to stop; the shutdown notification is remembered by the core, so
        # this also covers signals that arrive before the server is listening.
        interrupted = [False]
        failure: list[BaseException] = []

        def _serve() -> None:
            try:
                self._core.run(
                    host=host,
                    port=port,
                    workers=workers,
                    max_body_size=max_body_size,
                    access_log=access_log,
                    config=config,
                )
            except BaseException as error:  # re-raised on the calling thread
                failure.append(error)

        self._core.start_event_loop()
        previous_handler: Any = None
        handler_installed = False
        try:
            self._run_lifecycle(self._startup)
            if threading.current_thread() is threading.main_thread():

                def _on_sigint(signum: int, frame: Any) -> None:
                    interrupted[0] = True

                previous_handler = signal.getsignal(signal.SIGINT)
                signal.signal(signal.SIGINT, _on_sigint)
                handler_installed = True

                worker = threading.Thread(target=_serve, name="alphaapi-server")
                worker.start()
                # Joining with a timeout lets the main thread run pending
                # Python signal handlers even when SIGINT arrives before the
                # Rust core has installed its own handler.  Once seen, stop the
                # core from here rather than inside the signal handler; the
                # core remembers the notification, so early signals are safe.
                while worker.is_alive():
                    worker.join(0.1)
                    if interrupted[0]:
                        self._core.stop()
            else:
                # Callers such as tests drive ``run`` from their own thread and
                # keep control of signals themselves.
                _serve()
        finally:
            if handler_installed:
                signal.signal(signal.SIGINT, previous_handler)
            try:
                self._run_lifecycle(self._shutdown)
            finally:
                self._core.stop_event_loop()

        if failure:
            raise failure[0]
        if interrupted[0]:
            raise KeyboardInterrupt

    # ``runserver`` is the Django-flavoured alias.
    runserver = run

    def __repr__(self) -> str:
        return f"<Application {self.title!r} routes={len(self._urlpatterns)}>"


__all__ = ["Application", "HTTP_METHODS", "import_string"]
