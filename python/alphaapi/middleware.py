"""Middleware helpers.

Middleware is a callable that receives the next handler and returns a handler::

    class TimingMiddleware:
        def __init__(self, get_response):
            self.get_response = get_response

        async def __call__(self, request):
            response = await self.get_response(request)
            response["X-Elapsed"] = "0.001"
            return response

Middleware may be sync or async.  When any middleware is configured, routes
run on AlphaAPI's async event loop so both styles can be composed.
"""
from __future__ import annotations

import inspect
from typing import Any, Callable


class MiddlewareMixin:
    """Convenience base class for class-based middleware."""

    def __init__(self, get_response: Callable[..., Any]) -> None:
        self.get_response = get_response

    def __call__(self, request: Any) -> Any:
        return self.get_response(request)


def is_async_callable(value: Any) -> bool:
    if inspect.iscoroutinefunction(value):
        return True
    call = getattr(value, "__call__", None)
    return call is not None and inspect.iscoroutinefunction(call)


async def call_next(get_response: Callable[..., Any], request: Any) -> Any:
    """Invoke ``get_response`` and await the result when necessary."""
    response = get_response(request)
    if inspect.isawaitable(response):
        response = await response
    return response


__all__ = ["MiddlewareMixin", "is_async_callable", "call_next"]
