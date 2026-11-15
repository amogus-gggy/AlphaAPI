# Observability

AlphaAPI includes request IDs, a Prometheus-compatible metrics registry, health
helpers, and structured access logs.

## Request IDs

`RequestIdMiddleware` reads `X-Request-ID` or generates one, stores it on
`request.request_id`, and echoes it on the response:

```python
from alphaapi import Application, RequestIdMiddleware

app = Application(urlpatterns=[], middleware=[RequestIdMiddleware])
```

```python
async def handler(request):
    return JsonResponse({"request_id": request.request_id})
```

## Metrics

`MetricsMiddleware` records request counts and durations in a `Metrics`
registry. Add `metrics_response` as a route to expose them:

```python
from alphaapi import (
    Application,
    MetricsMiddleware,
    metrics_response,
    path,
)

app = Application(
    urlpatterns=[path("metrics/", metrics_response, name="metrics")],
    middleware=[MetricsMiddleware],
)
```

The endpoint returns Prometheus text format:

```text
alphaapi_requests_total{method="GET",route="metrics/",status="200"} 1
alphaapi_request_duration_seconds_sum{method="GET",route="metrics/"} 0.000482
alphaapi_request_duration_seconds_count{method="GET",route="metrics/"} 1
```

Use a separate registry when you do not want the process-wide `metrics`
instance:

```python
from alphaapi import Metrics, MetricsMiddleware

registry = Metrics()


def metrics_middleware(get_response):
    return MetricsMiddleware(get_response, registry=registry)
```

`registry.render()` returns the current exposition text and `registry.reset()`
clears it.

!!! note
    Metrics are process-local. If you run multiple workers, scrape each worker
    or aggregate externally.

## Health and readiness

Two ready-made views are available:

```python
from alphaapi import health_response, readiness_response, path

urlpatterns = [
    path("health/", health_response, name="health"),
    path("ready/", readiness_response, name="ready"),
]
```

They return `{"status": "ok"}` and `{"status": "ready"}`. For dependency checks,
write your own readiness view that probes the database or cache.

## Access logs

Enable access logging with settings or the `--access-log` CLI flag:

```python
ACCESS_LOG = True
ACCESS_LOG_JSON = False
```

Set `ACCESS_LOG_JSON = True` for one JSON object per request, which is easier to
ship to a log aggregator.

## Reference

::: alphaapi.observability.RequestIdMiddleware

::: alphaapi.observability.Metrics

::: alphaapi.observability.MetricsMiddleware

::: alphaapi.observability.metrics_response

::: alphaapi.observability.health_response

::: alphaapi.observability.readiness_response
