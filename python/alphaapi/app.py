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
from types import SimpleNamespace
from typing import Any, Callable, Iterable

from . import _core
from .apps import AppRegistry
from .conf import Settings, settings
from .exceptions import HTTPException, Http404, PermissionDenied
from .http import (
    HttpRequest,
    HttpResponse,
    HttpResponseForbidden,
    HttpResponseNotFound,
    JsonResponse,
)
from .middleware import is_async_callable
from .params import build_param_specs, wants_request
from .urls import ImproperlyConfigured, ResolvedPattern, flatten, reverse as reverse_url
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
        if settings_module:
            settings.configure_from_module(settings_module)
        if settings_config:
            settings.configure(**settings_config)
        if title is not None:
            settings.TITLE = title
        if version is not None:
            settings.VERSION = version
        if debug is not None:
            settings.DEBUG = debug
        if installed_apps is not None:
            settings.INSTALLED_APPS = list(installed_apps)

        self.settings: Settings = settings
        self.title = self.settings.TITLE
        self.version = self.settings.VERSION
        self.debug = bool(self.settings.DEBUG)

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
        # Named-route registry scoped to this application, so two Application
        # instances in one process cannot pollute each other's reverse().
        self._named_patterns: dict[str, Any] = {}
        self._resolved: list[ResolvedPattern] = []
        self._chains: dict[int, tuple[Any, Any]] = {}
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

    def reverse(
        self,
        viewname: str,
        args: Iterable[Any] | None = None,
        kwargs: dict[str, Any] | None = None,
    ) -> str:
        """Build a URL for a named route of *this application only*.

        The registry is per-application (not process-global), so multiple
        ``Application`` instances can coexist without leaking names into each
        other's ``reverse()``.
        """
        self._ensure_resolved()
        return reverse_url(viewname, args=args, kwargs=kwargs, registry=self._named_patterns)

    def _ensure_resolved(self) -> None:
        if self._resolved:
            return
        self._resolved = list(flatten(self._urlpatterns))
        for pattern in self._resolved:
            if pattern.full_name:
                self._named_patterns[pattern.full_name] = pattern
            if pattern.name and pattern.name not in self._named_patterns:
                self._named_patterns[pattern.name] = pattern

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
    ) -> tuple[Callable[..., Any], bool, Callable[..., Any], bool]:
        view = self._resolve_view(pattern.view)
        converters = pattern.converters

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

        view_wants_request = wants_request(view)

        def call_view(request: HttpRequest) -> Any:
            values = dict(pattern.kwargs)
            resolver_match = getattr(request, "resolver_match", None)
            if resolver_match is not None:
                values.update(resolver_match.kwargs)
            # Typed query/header/body values live outside resolver_match, which
            # is reserved for the URL-converter kwargs.
            values.update(getattr(request, "_alpha_kwargs", {}))
            if view_wants_request:
                return view(request, **values)
            return view(**values)

        has_middleware = bool(self.middleware)
        view_is_async = _is_view_async(view)

        if view_is_async or has_middleware:
            # The middleware chain is built once per application (see
            # ``_get_chain``) so stateful middleware keeps a single instance,
            # matching Django semantics.
            chain = self._get_chain(call_view)

            async def async_handler(raw_request: Any, **kwargs: Any) -> Any:
                request = HttpRequest(raw_request)
                path_kwargs, extra_kwargs = split_kwargs(kwargs)
                request._alpha_kwargs = extra_kwargs  # type: ignore[attr-defined]
                try:
                    request.resolver_match = SimpleNamespace(  # type: ignore[attr-defined]
                        kwargs=path_kwargs,
                        url_name=pattern.name,
                        route=pattern.django_path,
                    )
                    response = chain(request)
                    if inspect.isawaitable(response):
                        response = await response
                except Http404 as error:
                    if self._has_exception_handler(type(error)):
                        raise
                    return _ensure_response(
                        HttpResponseNotFound(str(error) or "Not Found")
                    )
                except PermissionDenied as error:
                    if self._has_exception_handler(type(error)):
                        raise
                    return _ensure_response(
                        HttpResponseForbidden(str(error) or "Forbidden")
                    )
                return _ensure_response(response)

            async_handler.__alphaapi_async__ = True  # type: ignore[attr-defined]
            return async_handler, True, view, view_wants_request

        def sync_handler(raw_request: Any, **kwargs: Any) -> Any:
            request = HttpRequest(raw_request)
            path_kwargs, extra_kwargs = split_kwargs(kwargs)
            request._alpha_kwargs = extra_kwargs  # type: ignore[attr-defined]
            try:
                request.resolver_match = SimpleNamespace(  # type: ignore[attr-defined]
                    kwargs=path_kwargs,
                    url_name=pattern.name,
                    route=pattern.django_path,
                )
                return _ensure_response(call_view(request))
            except Http404 as error:
                if self._has_exception_handler(type(error)):
                    raise
                return HttpResponseNotFound(str(error) or "Not Found")
            except PermissionDenied as error:
                if self._has_exception_handler(type(error)):
                    raise
                return HttpResponseForbidden(str(error) or "Forbidden")

        return sync_handler, False, view, view_wants_request

    def _get_chain(self, final: Callable[..., Any]) -> Callable[..., Any]:
        """Return a memoized middleware chain ending in ``final``.

        Middleware classes are instantiated exactly once per application, no
        matter how many routes share the chain.  Stateful middleware (rate
        limiters, caches, connection pools) therefore behaves like it does in
        Django instead of being silently duplicated per route.
        """
        key = id(final)
        cached = self._chains.get(key)
        if cached is not None:
            return cached[1]
        handler = self._build_async_chain(final)
        # Keep a strong reference to ``final`` alongside the chain so its
        # ``id`` cannot be reused by another object while the chain lives.
        self._chains[key] = (final, handler)
        return handler

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
        wants_request: bool = True,
    ) -> dict[str, Any]:
        params: list[dict[str, Any]] = []
        if wants_request:
            # Only views that actually declare a ``request`` parameter receive
            # the raw request object.  Views without it keep the lazy hot path:
            # no headers/query/body materialization in Rust (see README).
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
                    "positional": False,
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
        # Only flip the guard flag *after* the work succeeds; otherwise a
        # partial registration would be silently skipped on the next run().
        self._ensure_resolved()
        for pattern in self._resolved:
            handler, is_async, view, wants_request = self._make_handler(pattern)
            spec = self._build_spec(pattern, is_async, view, wants_request)
            for method in HTTP_METHODS:
                self._core.add_route(method, pattern.router_path, handler, spec)
        self._registered = True

    def _ensure_exception_handlers(self) -> None:
        if self._handlers_registered:
            return
        self._core.set_http_exception_type(HTTPException)
        for exc_type, handler in self._exception_handlers.items():
            if is_async_callable(handler):

                async def wrapped(
                    raw_request: Any, exception: Any, _handler: Any = handler
                ) -> Any:
                    return await _handler(HttpRequest(raw_request), exception)

            else:

                def wrapped(raw_request: Any, exception: Any, _handler: Any = handler) -> Any:
                    return _handler(HttpRequest(raw_request), exception)

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
