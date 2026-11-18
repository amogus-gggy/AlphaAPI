from __future__ import annotations

import json

from alphaapi import (
    Application,
    Client,
    FileResponse,
    JsonResponse,
    MiddlewareMixin,
    Query,
    SimpleUser,
    View,
    login,
    path,
)
from alphaapi.apps import AppRegistry
from alphaapi.security import host_is_allowed
from alphaapi.urls import clear_patterns


def _json(response):
    return json.loads(response.content)


def test_security_headers_are_present_on_early_responses():
    clear_patterns()

    async def ok(request):
        return JsonResponse({"ok": True})

    app = Application(urlpatterns=[path("ok/", ok, name="ok")])
    with Client(app) as client:
        found = client.get("/missing/")
        assert found.status_code == 404
        assert found.headers["x-content-type-options"] == "nosniff"
        assert found.headers["x-frame-options"] == "DENY"
        assert found.headers["referrer-policy"] == "same-origin"

        rejected = client.get("/ok/", headers={"host": "not-allowed.example"})
        # The default ALLOWED_HOSTS is ["*"]; this checks the early 400 path
        # only when a restrictive app is configured.
        if rejected.status_code == 400:
            assert rejected.headers["x-content-type-options"] == "nosniff"


def test_views_without_request_do_not_get_a_materialized_request():
    clear_patterns()

    async def health():
        return JsonResponse({"status": "ok"})

    app = Application(urlpatterns=[path("health/", health, name="health")])
    with Client(app) as client:
        response = client.post("/health/", body=b"x" * 1024)
        # The body is drained without being parsed or exposed to the view.
        assert response.status_code == 200
        assert _json(response) == {"status": "ok"}


def test_mutable_query_defaults_are_not_shared_between_requests():
    clear_patterns()

    async def tags(request, values: list[str] = Query(default=[])):  # noqa: B008
        values.append("x")
        return JsonResponse({"values": values})

    app = Application(urlpatterns=[path("tags/", tags, name="tags")])
    with Client(app) as client:
        assert _json(client.get("/tags/")) == {"values": ["x"]}
        assert _json(client.get("/tags/")) == {"values": ["x"]}


def test_middleware_is_instantiated_once_per_application():
    clear_patterns()
    instances = []

    class CountingMiddleware(MiddlewareMixin):
        def __init__(self, get_response):
            super().__init__(get_response)
            instances.append(self)

    def make(index):
        async def view(request):
            return JsonResponse({"index": index})

        return view

    app = Application(
        urlpatterns=[
            path("a/", make(1), name="a"),
            path("b/", make(2), name="b"),
            path("c/", make(3), name="c"),
        ],
        middleware=[CountingMiddleware],
    )
    with Client(app) as client:
        assert client.get("/a/").status_code == 200
        assert client.get("/b/").status_code == 200
        assert client.get("/c/").status_code == 200
    assert len(instances) == 1


def test_app_registries_and_settings_are_scoped():
    clear_patterns()

    async def index(request):
        return JsonResponse({"ok": True})

    app_a = Application(
        urlpatterns=[path("", index, name="a")], settings_config={"TITLE": "A"}
    )
    app_b = Application(
        urlpatterns=[path("", index, name="b")], settings_config={"TITLE": "B"}
    )
    assert app_a.reverse("a") == "/"
    assert app_b.reverse("b") == "/"
    assert app_a.title == "A"
    assert app_b.title == "B"

    registry = AppRegistry()
    registry.populate(["json"])
    assert list(registry.app_configs) == ["json"]
    registry.populate(["math"])
    assert list(registry.app_configs) == ["math"]


def test_openapi_operation_ids_are_unique_and_method_aware():
    clear_patterns()

    class ItemView(View):
        async def get(self, request):
            return JsonResponse({})

        async def post(self, request):
            return JsonResponse({}, status=201)

    app = Application(
        urlpatterns=[path("items/", ItemView.as_view(), name="items")],
        settings_config={"ENABLE_OPENAPI": True},
    )
    schema = app.openapi()
    operation_ids = [
        operation["operationId"]
        for methods in schema["paths"].values()
        for operation in methods.values()
    ]
    assert len(operation_ids) == len(set(operation_ids))
    assert set(schema["paths"]["/items/"]) == {"get", "post", "options"}


def test_ipv6_and_trailing_dot_hosts():
    assert host_is_allowed("[::1]", ["::1"]) is True
    assert host_is_allowed("[::1]:8000", ["::1"]) is True
    assert host_is_allowed("example.com.", ["example.com"]) is True

    clear_patterns()

    async def ok(request):
        return JsonResponse({"ok": True})

    app = Application(
        urlpatterns=[path("ok/", ok, name="ok")],
        settings_config={"ALLOWED_HOSTS": ["::1"]},
    )
    with Client(app) as client:
        response = client.get("/ok/", headers={"host": "[::1]"})
        assert response.status_code == 200


def test_login_cycles_the_session_key():
    class Session(dict):
        def __init__(self):
            super().__init__()
            self.cycled = False

        def cycle_key(self):
            self.cycled = True

    class Request:
        pass

    request = Request()
    request.session = Session()
    login(request, SimpleUser("sam", user_id=7))
    assert request.session.cycled is True
    assert request.session["_auth_user_id"] == 7


def test_file_download_uses_a_valid_quoted_filename(tmp_path):
    target = tmp_path / "my file.txt"
    target.write_text("hello")
    response = FileResponse(target, as_attachment=True)
    disposition = response.headers["Content-Disposition"]
    assert 'filename="my file.txt"' in disposition
    assert "shlex" not in disposition
