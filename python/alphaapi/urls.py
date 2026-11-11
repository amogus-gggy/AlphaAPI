"""URL routing, Django style.

Routes are declared with ``path()`` and composed with ``include()``::

    urlpatterns = [
        path("", views.index, name="index"),
        path("items/<int:item_id>/", views.item, name="item"),
        path("api/", include("project.api_urls")),
    ]

AlphaAPI uses its Rust router for matching, so routes support the standard
Django path converters (``str``, ``int``, ``float``, ``slug``, ``uuid`` and
``path``) but not arbitrary regular expressions.
"""
from __future__ import annotations

import importlib
import re
import types
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator

_CONVERTER_RE = re.compile(
    r"<(?:(?P<converter>[a-zA-Z_][a-zA-Z0-9_]*):)?"
    r"(?P<name>[a-zA-Z_][a-zA-Z0-9_]*)>"
)


class NoReverseMatch(Exception):
    """Raised when ``reverse()`` cannot build a URL."""


class ImproperlyConfigured(Exception):
    """Raised when URLconf/settings configuration is invalid."""


class PathConverter:
    regex = "[^/]+"
    type_name = "str"

    def to_python(self, value: Any) -> Any:
        return value

    def to_url(self, value: Any) -> str:
        return str(value)


class StringConverter(PathConverter):
    regex = "[^/]+"


class IntConverter(PathConverter):
    regex = "[0-9]+"
    type_name = "int"

    def to_python(self, value: Any) -> int:
        return int(value)


class FloatConverter(PathConverter):
    regex = "[0-9]+(?:\\.[0-9]+)?"
    type_name = "float"

    def to_python(self, value: Any) -> float:
        return float(value)


class SlugConverter(PathConverter):
    regex = "[-a-zA-Z0-9_]+"


class UUIDConverter(PathConverter):
    regex = "[0-9a-fA-F-]{32,36}"

    def to_python(self, value: Any) -> uuid.UUID:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))

    def to_url(self, value: Any) -> str:
        return str(value)


class PathConverterType(PathConverter):
    regex = ".+"


DEFAULT_CONVERTERS: dict[str, PathConverter] = {
    "str": StringConverter(),
    "int": IntConverter(),
    "float": FloatConverter(),
    "slug": SlugConverter(),
    "uuid": UUIDConverter(),
    "path": PathConverterType(),
}

_CONVERTERS = dict(DEFAULT_CONVERTERS)


def register_converter(converter: type[PathConverter] | PathConverter, type_name: str) -> None:
    if isinstance(converter, type):
        converter = converter()
    _CONVERTERS[type_name] = converter


def get_converter(type_name: str) -> PathConverter:
    try:
        return _CONVERTERS[type_name]
    except KeyError as error:
        raise ImproperlyConfigured(
            f"unknown path converter {type_name!r}"
        ) from error


def _join_route(prefix: str, route: str) -> str:
    if not prefix:
        return route
    if not route:
        return prefix
    return prefix.rstrip("/") + "/" + route.lstrip("/")


def _parse_converters(route: str) -> tuple[str, dict[str, PathConverter]]:
    converters: dict[str, PathConverter] = {}

    def replace(match: re.Match[str]) -> str:
        converter_name = match.group("converter") or "str"
        name = match.group("name")
        converter = get_converter(converter_name)
        converters[name] = converter
        if converter_name == "path":
            return "{*" + name + "}"
        return "{" + name + "}"

    router_path = _CONVERTER_RE.sub(replace, route)
    if not router_path.startswith("/"):
        router_path = "/" + router_path
    return router_path, converters


@dataclass
class URLPattern:
    route: str
    view: Any
    kwargs: dict[str, Any] = field(default_factory=dict)
    name: str | None = None
    converters: dict[str, PathConverter] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _, found = _parse_converters(self.route)
        self.converters.update(found)

    @property
    def router_path(self) -> str:
        return _parse_converters(self.route)[0]

    def __repr__(self) -> str:
        name = f", name={self.name!r}" if self.name else ""
        return f"<URLPattern {self.route!r}{name}>"


class URLResolver:
    """An include target: a module, a list of patterns, or a ``(patterns, app_name)`` pair."""

    def __init__(
        self,
        source: Any,
        *,
        namespace: str | None = None,
        app_name: str | None = None,
    ) -> None:
        self.source = source
        self.namespace = namespace
        self.app_name = app_name
        self._patterns: list[Any] | None = None

    @property
    def patterns(self) -> list[Any]:
        if self._patterns is None:
            self._patterns, discovered_name = _load_patterns(self.source)
            if self.app_name is None:
                self.app_name = discovered_name
        return self._patterns

    def __repr__(self) -> str:
        return f"<URLResolver {self.source!r}>"


def path(
    route: str,
    view: Any,
    kwargs: dict[str, Any] | None = None,
    name: str | None = None,
) -> URLPattern:
    """Register a route using Django path syntax."""
    return URLPattern(route=route, view=view, kwargs=dict(kwargs or {}), name=name)


def include(
    arg: Any,
    namespace: str | None = None,
) -> URLResolver:
    """Include another URLconf or an explicit list of patterns."""
    app_name = None
    if isinstance(arg, (tuple, list)) and len(arg) == 2:
        candidate_patterns, candidate_name = arg
        if isinstance(candidate_patterns, (list, tuple)) and isinstance(
            candidate_name, str
        ):
            arg = candidate_patterns
            app_name = candidate_name
    return URLResolver(arg, namespace=namespace, app_name=app_name)


def _load_patterns(source: Any) -> tuple[list[Any], str | None]:
    if isinstance(source, str):
        module = importlib.import_module(source)
        return _patterns_from_module(module)
    if isinstance(source, types.ModuleType):
        return _patterns_from_module(source)
    if isinstance(source, (list, tuple)):
        return list(source), None
    urlpatterns = getattr(source, "urlpatterns", None)
    if urlpatterns is not None:
        return list(urlpatterns), getattr(source, "app_name", None)
    raise ImproperlyConfigured(f"cannot load URL patterns from {source!r}")


def _patterns_from_module(module: types.ModuleType) -> tuple[list[Any], str | None]:
    urlpatterns = getattr(module, "urlpatterns", None)
    if urlpatterns is None:
        raise ImproperlyConfigured(
            f"module {module.__name__!r} does not define urlpatterns"
        )
    return list(urlpatterns), getattr(module, "app_name", None)


@dataclass
class ResolvedPattern:
    django_path: str
    router_path: str
    view: Any
    kwargs: dict[str, Any]
    name: str | None
    converters: dict[str, PathConverter]
    namespace: str | None = None

    @property
    def full_name(self) -> str | None:
        if not self.name:
            return None
        return f"{self.namespace}:{self.name}" if self.namespace else self.name


def flatten(patterns: Iterable[Any], prefix: str = "") -> Iterator[ResolvedPattern]:
    """Expand nested includes into a flat list of resolved patterns."""
    for pattern in patterns:
        if isinstance(pattern, URLResolver):
            yield from flatten(pattern.patterns, prefix)
            continue
        if not isinstance(pattern, URLPattern):
            raise ImproperlyConfigured(f"invalid URL pattern: {pattern!r}")

        full_path = _join_route(prefix, pattern.route)
        if isinstance(pattern.view, URLResolver):
            resolver = pattern.view
            namespace = resolver.namespace or resolver.app_name
            child_prefix = full_path
            for child in flatten(resolver.patterns, child_prefix):
                if namespace and child.namespace:
                    child.namespace = f"{namespace}:{child.namespace}"
                elif namespace:
                    child.namespace = namespace
                yield child
            continue

        router_path, converters = _parse_converters(full_path)
        yield ResolvedPattern(
            django_path=full_path,
            router_path=router_path,
            view=pattern.view,
            kwargs=dict(pattern.kwargs),
            name=pattern.name,
            converters=converters,
        )


_NAMED_PATTERNS: dict[str, ResolvedPattern] = {}


def register_patterns(patterns: Iterable[Any]) -> list[ResolvedPattern]:
    """Flatten ``patterns`` and remember named routes for ``reverse()``."""
    resolved = list(flatten(patterns))
    for pattern in resolved:
        if pattern.full_name:
            _NAMED_PATTERNS[pattern.full_name] = pattern
        if pattern.name and pattern.name not in _NAMED_PATTERNS:
            _NAMED_PATTERNS[pattern.name] = pattern
    return resolved


def clear_patterns() -> None:
    _NAMED_PATTERNS.clear()


def reverse(
    viewname: str,
    args: Iterable[Any] | None = None,
    kwargs: dict[str, Any] | None = None,
) -> str:
    """Build a URL for a named pattern."""
    try:
        pattern = _NAMED_PATTERNS[viewname]
    except KeyError as error:
        raise NoReverseMatch(f"no URL pattern named {viewname!r}") from error

    remaining_args = list(args or [])
    remaining_kwargs = dict(kwargs or {})

    def replace(match: re.Match[str]) -> str:
        converter_name = match.group("converter") or "str"
        name = match.group("name")
        converter = pattern.converters.get(name) or get_converter(converter_name)
        if remaining_args:
            value = remaining_args.pop(0)
        elif name in remaining_kwargs:
            value = remaining_kwargs.pop(name)
        else:
            raise NoReverseMatch(
                f"missing argument {name!r} for URL pattern {viewname!r}"
            )
        return converter.to_url(value)

    built = _CONVERTER_RE.sub(replace, pattern.django_path)
    if remaining_args or remaining_kwargs:
        raise NoReverseMatch(
            f"too many arguments for URL pattern {viewname!r}"
        )
    if not built.startswith("/"):
        built = "/" + built
    return built


def _path_regex(django_path: str) -> re.Pattern[str]:
    parts: list[str] = []
    last = 0
    for match in _CONVERTER_RE.finditer(django_path):
        parts.append(re.escape(django_path[last : match.start()]))
        converter_name = match.group("converter") or "str"
        parts.append(f"(?P<{match.group('name')}>{get_converter(converter_name).regex})")
        last = match.end()
    parts.append(re.escape(django_path[last:]))
    return re.compile("^" + "".join(parts) + "$")


def resolve(path: str, patterns: Iterable[Any] | None = None) -> ResolvedPattern | None:
    """Resolve a request path to a ``ResolvedPattern`` (best-effort helper)."""
    source = patterns
    if source is None:
        from .conf import settings

        if not settings.ROOT_URLCONF:
            return None
        source = _load_patterns(settings.ROOT_URLCONF)[0]
    for pattern in flatten(source):
        match = _path_regex(pattern.django_path).match(path)
        if match:
            pattern.kwargs.update(
                {
                    name: pattern.converters.get(name, get_converter("str")).to_python(value)
                    for name, value in match.groupdict().items()
                }
            )
            return pattern
    return None


__all__ = [
    "path",
    "include",
    "register_converter",
    "reverse",
    "resolve",
    "flatten",
    "register_patterns",
    "clear_patterns",
    "URLPattern",
    "URLResolver",
    "ResolvedPattern",
    "PathConverter",
    "NoReverseMatch",
    "ImproperlyConfigured",
]
