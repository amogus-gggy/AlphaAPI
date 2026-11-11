"""The AlphaAPI application object.

The design is deliberately Django-shaped: settings, URLconfs, function and
class-based views, middleware and an app registry.  Everything is async-native,
and the HTTP server/routing hot path stays in Rust.
"""
from __future__ import annotations

import asyncio
import importlib
import inspect
from types import SimpleNamespace
from typing import Any, Callable, Iterable

from . import _core
from .apps import AppRegistry, apps as default_apps
from .conf import Settings, settings
from .exceptions import HTTPException, Http404, PermissionDenied
from .http import (
    HttpRequest,
    HttpResponse,
    HttpResponseForbidden,
    HttpResponseNotFound,
    JsonResponse,
)
from .urls import (
    ImproperlyConfigured,
    ResolvedPattern,
    register_patterns,
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

        self.apps: AppRegistry = default_apps
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

        self._core = _core.AppCore()
        self._exception_handlers: dict[type[BaseException], Callable[..., Any]] = {}
        self._startup: list[Callable[..., Any]] = []
        self._shutdown: list[Callable[..., Any]] = []
        self._resolved: list[ResolvedPattern] = []
        self._registered = False
        self._handlers_registered = False

    # -- URL configuration --------------------------------------------------

    @property
    def urlpatterns(self) -> list[Any]:
        return list(self._urlpatterns)

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
        self._ensure_resolved()
        return reverse_url(viewname, args=args, kwargs=kwargs)

    def _ensure_resolved(self) -> None:
        if self._resolved:
            return
        self._resolved = register_patterns(self._urlpatterns)

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

    def _make_handler(self, pattern: ResolvedPattern) -> tuple[Callable[..., Any], bool]:
        view = self._resolve_view(pattern.view)
        converters = pattern.converters

        def convert_kwargs(values: dict[str, Any]) -> dict[str, Any]:
            converted: dict[str, Any] = {}
            for name, value in values.items():
                converter = converters.get(name)
                if converter is None:
                    converted[name] = value
                    continue
                try:
                    converted[name] = converter.to_python(value)
                except (TypeError, ValueError) as error:
                    raise Http404(
                        f"No match for {name}={value!r} in URL {pattern.django_path!r}"
                    ) from error
            return converted

        def call_view(request: HttpRequest, **kwargs: Any) -> Any:
            values = dict(pattern.kwargs)
            resolver_match = getattr(request, "resolver_match", None)
            if resolver_match is not None:
                values.update(resolver_match.kwargs)
            values.update(kwargs)
            return view(request, **values)

        has_middleware = bool(self.middleware)
        view_is_async = _is_view_async(view)

        if view_is_async or has_middleware:
            chain = self._build_async_chain(call_view)

            async def async_handler(raw_request: Any, **kwargs: Any) -> Any:
                request = HttpRequest(raw_request)
                try:
                    request.resolver_match = SimpleNamespace(  # type: ignore[attr-defined]
                        kwargs=convert_kwargs(kwargs),
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
            return async_handler, True

        def sync_handler(raw_request: Any, **kwargs: Any) -> Any:
            request = HttpRequest(raw_request)
            try:
                request.resolver_match = SimpleNamespace(  # type: ignore[attr-defined]
                    kwargs=convert_kwargs(kwargs),
                    url_name=pattern.name,
                    route=pattern.django_path,
                )
                return _ensure_response(call_view(request, **request.resolver_match.kwargs))
            except Http404 as error:
                if self._has_exception_handler(type(error)):
                    raise
                return HttpResponseNotFound(str(error) or "Not Found")
            except PermissionDenied as error:
                if self._has_exception_handler(type(error)):
                    raise
                return HttpResponseForbidden(str(error) or "Forbidden")

        return sync_handler, False

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

    def _build_spec(self, pattern: ResolvedPattern, is_async: bool) -> dict[str, Any]:
        params: list[dict[str, Any]] = [
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
        ]
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
        return {
            "params": params,
            "is_async": is_async,
            "status_code": 200,
        }

    def _ensure_registered(self) -> None:
        if self._registered:
            return
        self._registered = True
        self._ensure_resolved()
        for pattern in self._resolved:
            handler, is_async = self._make_handler(pattern)
            spec = self._build_spec(pattern, is_async)
            for method in HTTP_METHODS:
                self._core.add_route(method, pattern.router_path, handler, spec)

    def _ensure_exception_handlers(self) -> None:
        if self._handlers_registered:
            return
        self._handlers_registered = True
        self._core.set_http_exception_type(HTTPException)
        for exc_type, handler in self._exception_handlers.items():
            def wrapped(raw_request: Any, exception: Any, _handler: Any = handler) -> Any:
                return _handler(HttpRequest(raw_request), exception)

            self._core.add_exception_handler(exc_type, wrapped)

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

    # ``runserver`` is the Django-flavoured alias.
    runserver = run

    def __repr__(self) -> str:
        return f"<Application {self.title!r} routes={len(self._urlpatterns)}>"


__all__ = ["Application", "HTTP_METHODS", "import_string"]
