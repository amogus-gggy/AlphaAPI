"""Request IDs, metrics, and health helpers."""
from __future__ import annotations

import threading
import time
import uuid
from typing import Any

from .http import HttpResponse, JsonResponse
from .middleware import call_next


class RequestIdMiddleware:
    """Propagate or generate an ``X-Request-ID`` for every request."""

    header = "x-request-id"

    def __init__(self, get_response: Any) -> None:
        self.get_response = get_response

    async def __call__(self, request: Any) -> Any:
        incoming = request.headers.get(self.header, "")
        request.request_id = incoming or uuid.uuid4().hex
        response = await call_next(self.get_response, request)
        response.headers.setdefault("X-Request-ID", request.request_id)
        return response


class Metrics:
    """A small, dependency-free Prometheus-compatible metric registry."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._requests: dict[tuple[str, str, str], int] = {}
        self._duration_sum: dict[tuple[str, str], float] = {}
        self._duration_count: dict[tuple[str, str], int] = {}

    def observe_request(
        self, method: str, route: str, status: int, duration: float
    ) -> None:
        key = (method, route, str(status))
        duration_key = (method, route)
        with self._lock:
            self._requests[key] = self._requests.get(key, 0) + 1
            self._duration_sum[duration_key] = (
                self._duration_sum.get(duration_key, 0.0) + duration
            )
            self._duration_count[duration_key] = (
                self._duration_count.get(duration_key, 0) + 1
            )

    def render(self) -> str:
        lines = [
            "# HELP alphaapi_requests_total Total HTTP requests.",
            "# TYPE alphaapi_requests_total counter",
        ]
        with self._lock:
            requests = dict(self._requests)
            duration_sum = dict(self._duration_sum)
            duration_count = dict(self._duration_count)

        for (method, route, status), value in sorted(requests.items()):
            lines.append(
                "alphaapi_requests_total"
                f'{{method="{method}",route="{route}",status="{status}"}} {value}'
            )

        lines.extend(
            [
                "# HELP alphaapi_request_duration_seconds Request duration.",
                "# TYPE alphaapi_request_duration_seconds summary",
            ]
        )
        for key in sorted(duration_sum):
            method, route = key
            labels = f'method="{method}",route="{route}"'
            lines.append(f"alphaapi_request_duration_seconds_sum{{{labels}}} {duration_sum[key]:.9f}")
            lines.append(
                f"alphaapi_request_duration_seconds_count{{{labels}}} {duration_count[key]}"
            )
        return "\n".join(lines) + "\n"

    def reset(self) -> None:
        with self._lock:
            self._requests.clear()
            self._duration_sum.clear()
            self._duration_count.clear()


metrics = Metrics()


class MetricsMiddleware:
    """Record request counts and durations in the global registry."""

    def __init__(self, get_response: Any, registry: Metrics | None = None) -> None:
        self.get_response = get_response
        self.registry = registry or metrics

    async def __call__(self, request: Any) -> Any:
        started = time.perf_counter()
        response = await call_next(self.get_response, request)
        duration = time.perf_counter() - started
        resolver = getattr(request, "resolver_match", None)
        route = getattr(resolver, "route", None) or request.path
        self.registry.observe_request(
            request.method,
            route,
            int(getattr(response, "status_code", 200)),
            duration,
        )
        return response


def metrics_response(request: Any = None) -> HttpResponse:
    """A view returning Prometheus text format."""
    return HttpResponse(
        metrics.render(),
        content_type="text/plain; version=0.0.4; charset=utf-8",
    )


def health_response(request: Any = None) -> JsonResponse:
    return JsonResponse({"status": "ok"})


def readiness_response(request: Any = None) -> JsonResponse:
    return JsonResponse({"status": "ready"})


__all__ = [
    "RequestIdMiddleware",
    "Metrics",
    "MetricsMiddleware",
    "metrics",
    "metrics_response",
    "health_response",
    "readiness_response",
]
