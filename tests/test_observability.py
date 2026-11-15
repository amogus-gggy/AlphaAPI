from __future__ import annotations

import json

from alphaapi import (
    Application,
    Client,
    HttpResponse,
    RequestIdMiddleware,
    path,
)
from alphaapi.observability import (
    Metrics,
    MetricsMiddleware,
    health_response,
    metrics,
    metrics_response,
    readiness_response,
)
from alphaapi.urls import clear_patterns


def _json(response):
    return json.loads(response.content)


def test_request_id_middleware(settings_override):
    clear_patterns()

    async def plain(request):
        return HttpResponse("plain")

    app = Application(
        urlpatterns=[path("plain/", plain, name="plain")],
        middleware=[RequestIdMiddleware],
        settings_config={"ALLOWED_HOSTS": ["*"]},
    )
    with Client(app) as client:
        generated = client.get("/plain/")
        assert generated.headers["x-request-id"]

        propagated = client.get(
            "/plain/", headers={"x-request-id": "request-123"}
        )
        assert propagated.headers["x-request-id"] == "request-123"


def test_metrics_registry():
    registry = Metrics()
    registry.observe_request("GET", "/a/", 200, 0.5)
    registry.observe_request("GET", "/a/", 200, 0.25)
    registry.observe_request("POST", "/b/", 500, 1.0)

    rendered = registry.render()
    assert "# TYPE alphaapi_requests_total counter" in rendered
    assert 'method="GET",route="/a/",status="200"} 2' in rendered
    assert "alphaapi_request_duration_seconds_sum" in rendered
    assert "alphaapi_request_duration_seconds_count" in rendered

    registry.reset()
    assert "alphaapi_requests_total{" not in registry.render()


def test_metrics_middleware_and_endpoint(settings_override):
    metrics.reset()
    clear_patterns()

    async def plain(request):
        return HttpResponse("plain")

    app = Application(
        urlpatterns=[
            path("plain/", plain, name="plain"),
            path("metrics/", metrics_response, name="metrics"),
        ],
        middleware=[MetricsMiddleware],
        settings_config={"ALLOWED_HOSTS": ["*"]},
    )
    with Client(app) as client:
        assert client.get("/plain/").status_code == 200

        response = client.get("/metrics/")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/plain")
        assert "alphaapi_requests_total" in response.text
        assert 'route="plain/"' in response.text


def test_health_and_readiness_views():
    health = health_response()
    readiness = readiness_response()
    assert health.status_code == 200
    assert _json(health) == {"status": "ok"}
    assert readiness.status_code == 200
    assert _json(readiness) == {"status": "ready"}


def test_access_log_text_and_json(capfd, settings_override):
    clear_patterns()

    async def plain(request):
        return HttpResponse("plain")

    app = Application(
        urlpatterns=[path("plain/", plain, name="plain")],
        settings_config={"ALLOWED_HOSTS": ["*"]},
    )
    settings_override(ACCESS_LOG=True, ACCESS_LOG_JSON=False)
    with Client(app) as client:
        client.get("/plain/")
    captured = capfd.readouterr()
    assert "GET /plain/ 200" in captured.err

    settings_override(ACCESS_LOG=True, ACCESS_LOG_JSON=True)
    with Client(app) as client:
        client.get("/plain/")
    captured = capfd.readouterr()
    assert '"method":"GET"' in captured.err
    assert '"path":"/plain/"' in captured.err
    assert '"status":200' in captured.err
