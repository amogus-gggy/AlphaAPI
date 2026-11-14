"""Class-based views."""
from __future__ import annotations

import inspect
from typing import Any, Callable

from .http import HttpResponse, HttpResponseNotAllowed, HttpResponseRedirect


async def _await_if_needed(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


class View:
    """Base class for async-native class-based views.

    Subclasses implement methods named after HTTP verbs::

        class ItemView(View):
            async def get(self, request, item_id):
                return JsonResponse({"id": item_id})

            async def post(self, request, item_id):
                ...
    """

    http_method_names = [
        "get",
        "post",
        "put",
        "patch",
        "delete",
        "head",
        "options",
        "trace",
    ]

    def __init__(self, **kwargs: Any) -> None:
        for key, value in kwargs.items():
            setattr(self, key, value)

    def _allowed_methods(self) -> list[str]:
        methods = [
            method.upper()
            for method in self.http_method_names
            if method != "head" and hasattr(self, method)
        ]
        # HEAD is served by an explicit ``head`` method when present, or by
        # falling back to ``get``.  It is not supported when neither exists.
        if hasattr(self, "head") or hasattr(self, "get"):
            methods.append("HEAD")
        return methods

    async def dispatch(self, request: Any, *args: Any, **kwargs: Any) -> Any:
        method = request.method.lower()
        if method == "head":
            handler = getattr(self, "head", None) or getattr(
                self, "get", self.http_method_not_allowed
            )
        else:
            handler = getattr(self, method, self.http_method_not_allowed)
        return await _await_if_needed(handler(request, *args, **kwargs))

    def http_method_not_allowed(self, request: Any, *args: Any, **kwargs: Any) -> Any:
        return HttpResponseNotAllowed(self._allowed_methods())

    def options(self, request: Any, *args: Any, **kwargs: Any) -> Any:
        response = HttpResponse(b"", status=204)
        response["Allow"] = ", ".join(self._allowed_methods())
        return response

    @classmethod
    def as_view(cls, **initkwargs: Any) -> Callable[..., Any]:
        for key in initkwargs:
            if key in cls.http_method_names:
                raise TypeError(f"method name {key!r} is not allowed in as_view()")
            if not hasattr(cls, key):
                raise TypeError(f"{cls.__name__} has no attribute {key!r}")

        async def view(request: Any, *args: Any, **kwargs: Any) -> Any:
            self = cls(**initkwargs)
            return await _await_if_needed(self.dispatch(request, *args, **kwargs))

        view.view_class = cls  # type: ignore[attr-defined]
        view.view_initkwargs = initkwargs  # type: ignore[attr-defined]
        view.__name__ = cls.__name__
        view.__qualname__ = cls.__qualname__
        view.__doc__ = cls.__doc__
        view.__alphaapi_async__ = True  # type: ignore[attr-defined]
        return view


class RedirectView(View):
    """Redirect to another URL.

    Subclasses (or ``as_view(url=...)``) provide the target in ``url``.
    """

    url: str | None = None
    permanent = False

    def get(self, request: Any, *args: Any, **kwargs: Any) -> Any:
        url = self.url
        if not url:
            raise ValueError("RedirectView requires a url")
        response = HttpResponseRedirect(url)
        if self.permanent:
            response.status = 301
        return response


__all__ = ["View", "RedirectView"]
