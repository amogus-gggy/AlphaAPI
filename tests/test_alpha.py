from __future__ import annotations

import asyncio
import json
import threading
from uuid import UUID

import pytest
from alphaapi import (
    Application,
    Http404,
    HTTPException,
    HttpResponse,
    HttpResponseRedirect,
    JsonResponse,
    MiddlewareMixin,
    PermissionDenied,
    View,
    include,
    path,
    reverse,
)
from alphaapi.urls import clear_patterns


class Boom(Exception):
    pass


class AddHeaderMiddleware(MiddlewareMixin):
    async def __call__(self, request):
        response = await self.get_response(request)
        response["x-middleware"] = "on"
        return response


class ItemView(View):
    async def get(self, request, item_id: int):
        return JsonResponse({"item_id": item_id, "kind": "class"})

    async def post(self, request, item_id: int):
        payload = await asyncio.to_thread(request.json)
        return JsonResponse({"item_id": item_id, "payload": payload}, status=201)

    async def delete(self, request, item_id: int):
        return HttpResponse(b"", status=204)


class OnlyGetView(View):
    async def get(self, request):
        return JsonResponse({"only": "get"})


class OnlyPostView(View):
    async def post(self, request):
        return JsonResponse({"only": "post"})


def build_app() -> Application:
    clear_patterns()

    async def index(request):
        return JsonResponse({"hello": "world"})

    async def item(request, item_id: int):
        return JsonResponse(
            {
                "item_id": item_id,
                "q": request.GET.get("q"),
                "tags": request.GET.getlist("tag"),
            }
        )

    async def required(request):
        q = request.GET.get("q")
        if q is None:
            raise HTTPException(422, "q is required")
        return JsonResponse({"q": q})

    async def header_view(request):
        token = request.headers.get("x-token")
        if token is None:
            raise HTTPException(422, "x-token header is required")
        return JsonResponse({"token": token})

    async def echo(request):
        return JsonResponse({"payload": request.json()})

    async def form(request):
        return JsonResponse({"form": request.POST.dict()})

    async def cookie(request):
        return JsonResponse({"s": request.COOKIES.get("s")})

    async def text(request):
        return HttpResponse("plain text", content_type="text/plain; charset=utf-8")

    async def raw_bytes(request):
        return HttpResponse(b"\x00\x01\x02", content_type="application/octet-stream")

    async def custom(request):
        return JsonResponse({"custom": True}, status=202, headers={"x-demo": "yes"})

    async def teapot(request):
        raise HTTPException(418, detail="I'm a teapot", headers={"x-tea": "earl-grey"})

    async def missing(request):
        raise Http404("No such item")

    async def forbidden(request):
        raise PermissionDenied("Nope")

    async def boom(request):
        raise Boom("custom boom")

    async def async_route(request, value: int):
        await asyncio.sleep(0.001)
        return JsonResponse({"value": value, "double": value * 2})

    async def redirect(request):
        return HttpResponseRedirect("/")

    def sync_view(request):
        return JsonResponse({"sync": True})

    async def methods(request):
        return JsonResponse({"method": request.method})

    async def uuid_view(request, value):
        return JsonResponse({"value": str(value), "is_uuid": isinstance(value, UUID)})

    async def wildcard(request, rest):
        return JsonResponse({"rest": rest})

    async def request_info(request):
        return JsonResponse(
            {
                "method": request.method,
                "path": request.path,
                "query": request.GET.dict(),
                "x": request.headers.get("x-test"),
                "body": request.text(),
            }
        )

    async def two_cookies(request):
        response = HttpResponse("cookies")
        response.set_cookie("first", "one")
        response.set_cookie("second", "two")
        return response

    api_patterns = [
        path("ping/", lambda request: JsonResponse({"pong": True}), name="ping"),
    ]
    v2_patterns = [
        path("ping/", lambda request: JsonResponse({"pong": 2}), name="ping"),
    ]

    urlpatterns = [
        path("", index, name="index"),
        path("items/<int:item_id>/", item, name="item"),
        path("required/", required, name="required"),
        path("header/", header_view, name="header"),
        path("echo/", echo, name="echo"),
        path("form/", form, name="form"),
        path("cookie/", cookie, name="cookie"),
        path("text/", text, name="text"),
        path("bytes/", raw_bytes, name="bytes"),
        path("custom/", custom, name="custom"),
        path("teapot/", teapot, name="teapot"),
        path("missing/", missing, name="missing"),
        path("forbidden/", forbidden, name="forbidden"),
        path("boom/", boom, name="boom"),
        path("async/<int:value>/", async_route, name="async"),
        path("redirect/", redirect, name="redirect"),
        path("methods/", methods, name="methods"),
        path("sync/", sync_view, name="sync"),
        path("uuid/<uuid:value>/", uuid_view, name="uuid"),
        path("files/<path:rest>", wildcard, name="files"),
        path("request/", request_info, name="request-info"),
        path("cbv/<int:item_id>/", ItemView.as_view(), name="cbv"),
        path("auto-cbv/<int:item_id>/", ItemView, name="auto-cbv"),
        path("only-get/", OnlyGetView.as_view(), name="only-get"),
        path("only-post/", OnlyPostView.as_view(), name="only-post"),
        path("cookies/", two_cookies, name="cookies"),
        path("api/", include((api_patterns, "api"))),
        path("api/v2/", include((v2_patterns, "api_v2"))),
    ]

    app = Application(
        urlpatterns=urlpatterns,
        title="Test API",
        version="9.9.9",
        middleware=[AddHeaderMiddleware],
        installed_apps=["alphaapi"],
    )

    @app.exception_handler(Boom)
    def handle_boom(request, exc):
        return JsonResponse({"handled": str(exc)}, status=409)

    return app


@pytest.fixture(scope="session")
def client(start_server):
    return start_server(build_app())


def json_body(response):
    return json.loads(response[2])


def test_index_and_middleware(client):
    status, headers, body = client.request("GET", "/")
    assert status == 200
    assert headers["content-type"] == "application/json"
    assert headers["x-middleware"] == "on"
    assert json.loads(body) == {"hello": "world"}


def test_path_converter_and_query(client):
    status, _, body = client.request("GET", "/items/42/?q=hi&tag=a&tag=b")
    assert status == 200
    assert json.loads(body) == {"item_id": 42, "q": "hi", "tags": ["a", "b"]}


def test_invalid_path_converter_returns_404(client):
    status, _, body = client.request("GET", "/items/nope/")
    assert status == 404
    assert b"No match for item_id" in body


def test_query_access_and_http_exception(client):
    status, _, body = client.request("GET", "/required/?q=ok")
    assert status == 200
    assert json.loads(body) == {"q": "ok"}

    status, _, body = client.request("GET", "/required/")
    assert status == 422
    assert json.loads(body)["detail"] == "q is required"


def test_header_access(client):
    status, _, body = client.request("GET", "/header/", headers={"x-token": "secret"})
    assert status == 200
    assert json.loads(body) == {"token": "secret"}


def test_json_body(client):
    payload = json.dumps({"name": "apple", "price": 1.5}).encode()
    status, _, body = client.request(
        "POST", "/echo/", body=payload, headers={"content-type": "application/json"}
    )
    assert status == 200
    assert json.loads(body) == {"payload": {"name": "apple", "price": 1.5}}


def test_form_body(client):
    status, _, body = client.request(
        "POST",
        "/form/",
        body=b"a=1&b=hello+world",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert status == 200
    assert json.loads(body) == {"form": {"a": "1", "b": "hello world"}}


def test_cookies(client):
    status, _, body = client.request("GET", "/cookie/", headers={"cookie": "s=abc"})
    assert status == 200
    assert json.loads(body) == {"s": "abc"}


def test_text_bytes_and_custom_responses(client):
    status, headers, body = client.request("GET", "/text/")
    assert status == 200
    assert headers["content-type"].startswith("text/plain")
    assert body == b"plain text"

    status, headers, body = client.request("GET", "/bytes/")
    assert status == 200
    assert headers["content-type"] == "application/octet-stream"
    assert body == b"\x00\x01\x02"

    status, headers, body = client.request("GET", "/custom/")
    assert status == 202
    assert headers["x-demo"] == "yes"
    assert json.loads(body) == {"custom": True}


def test_http_exception_with_headers(client):
    status, headers, body = client.request("GET", "/teapot/")
    assert status == 418
    assert headers["x-tea"] == "earl-grey"
    assert json.loads(body) == {"detail": "I'm a teapot"}


def test_django_exceptions(client):
    status, headers, body = client.request("GET", "/missing/")
    assert status == 404
    assert headers["content-type"].startswith("text/html")
    assert b"No such item" in body

    status, headers, body = client.request("GET", "/forbidden/")
    assert status == 403
    assert b"Nope" in body


def test_custom_exception_handler(client):
    status, _, body = client.request("GET", "/boom/")
    assert status == 409
    assert json.loads(body) == {"handled": "custom boom"}


def test_custom_http404_handler(start_server):
    async def missing(request):
        raise Http404("custom missing")

    app = Application(urlpatterns=[path("", missing)])

    @app.exception_handler(Http404)
    def handle_missing(request, exc):
        return JsonResponse({"missing": str(exc)}, status=404)

    server = start_server(app)
    status, _, body = server.request("GET", "/")
    assert status == 404
    assert json.loads(body) == {"missing": "custom missing"}


def test_async_view(client):
    status, _, body = client.request("GET", "/async/21/")
    assert status == 200
    assert json.loads(body) == {"value": 21, "double": 42}


def test_sync_view_uses_fast_path(start_server):
    app = Application(
        urlpatterns=[path("", lambda request: JsonResponse({"sync": True}))]
    )
    server = start_server(app)
    status, _, body = server.request("GET", "/")
    assert status == 200
    assert json.loads(body) == {"sync": True}


def test_redirect(client):
    status, headers, body = client.request("GET", "/redirect/")
    assert status == 302
    assert headers["location"] == "/"
    assert body == b""


def test_all_http_methods_with_function_view(client):
    for method in ("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"):
        status, headers, body = client.request(method, "/methods/")
        assert status in (200, 204)
        if method != "HEAD":
            assert json.loads(body)["method"] == method


def test_class_based_view(client):
    status, _, body = client.request("GET", "/cbv/7/")
    assert status == 200
    assert json.loads(body) == {"item_id": 7, "kind": "class"}

    status, _, body = client.request("POST", "/cbv/7/", body=b'{"x": 1}')
    assert status == 201
    assert json.loads(body) == {"item_id": 7, "payload": {"x": 1}}

    status, _, body = client.request("DELETE", "/cbv/7/")
    assert status == 204
    assert body == b""

    status, headers, _ = client.request("PUT", "/cbv/7/")
    assert status == 405
    assert "GET" in headers["allow"]


def test_class_view_without_as_view(client):
    status, _, body = client.request("GET", "/auto-cbv/3/")
    assert status == 200
    assert json.loads(body) == {"item_id": 3, "kind": "class"}


def test_head_falls_back_to_get(client):
    status, headers, body = client.request("HEAD", "/only-get/")
    assert status == 200
    assert body == b""
    assert int(headers["content-length"]) > 0


def test_head_without_get_returns_405(client):
    status, headers, body = client.request("HEAD", "/only-post/")
    assert status == 405
    assert "POST" in headers["allow"]
    assert body == b""


def test_multiple_set_cookie_headers(client):
    import http.client

    connection = http.client.HTTPConnection("127.0.0.1", client.port, timeout=10)
    try:
        connection.request("GET", "/cookies/")
        response = connection.getresponse()
        response.read()
        cookies = [
            value
            for name, value in response.getheaders()
            if name.lower() == "set-cookie"
        ]
    finally:
        connection.close()

    assert len(cookies) == 2
    assert cookies[0].startswith("first=one")
    assert cookies[1].startswith("second=two")


def test_json_response_is_serialized_in_rust(monkeypatch):
    from alphaapi.http import response as response_module

    def fail(*args, **kwargs):
        raise AssertionError("JsonResponse must not call json.dumps")

    monkeypatch.setattr(response_module.json, "dumps", fail)
    response = JsonResponse({"hello": "world", "items": [1, 2]})
    assert json.loads(response.body) == {"hello": "world", "items": [1, 2]}
    assert response.media_type == "application/json"


def test_options_includes_allow(client):
    status, headers, body = client.request("OPTIONS", "/only-get/")
    assert status == 204
    assert "GET" in headers["allow"]
    assert body == b""


def test_uuid_and_path_converters(client):
    value = "12345678-1234-5678-1234-567812345678"
    status, _, body = client.request("GET", f"/uuid/{value}/")
    assert status == 200
    assert json.loads(body) == {"value": value, "is_uuid": True}

    status, _, body = client.request("GET", "/files/a/b/c.txt")
    assert status == 200
    assert json.loads(body) == {"rest": "a/b/c.txt"}


def test_request_object(client):
    status, _, body = client.request(
        "GET", "/request/?a=1&a=2&b=3", headers={"x-test": "yes"}
    )
    assert status == 200
    data = json.loads(body)
    assert data["method"] == "GET"
    assert data["path"] == "/request/"
    assert data["query"] == {"a": "2", "b": "3"}
    assert data["x"] == "yes"


def test_include_and_namespaces(client):
    status, _, body = client.request("GET", "/api/ping/")
    assert status == 200
    assert json.loads(body) == {"pong": True}

    status, _, body = client.request("GET", "/api/v2/ping/")
    assert status == 200
    assert json.loads(body) == {"pong": 2}


def test_reverse(client):
    assert reverse("index") == "/"
    assert reverse("item", kwargs={"item_id": 9}) == "/items/9/"
    assert reverse("api:ping") == "/api/ping/"
    assert reverse("api_v2:ping") == "/api/v2/ping/"


def test_404_and_405(client):
    status, _, body = client.request("GET", "/nope/")
    assert status == 404
    assert json.loads(body) == {"detail": "Not Found"}


def test_lifecycle_hooks(start_server):
    started = threading.Event()
    stopped = threading.Event()
    clear_patterns()
    app = Application(urlpatterns=[path("", lambda request: JsonResponse({"ok": True}))])

    @app.on_startup
    async def startup():
        started.set()

    @app.on_shutdown
    def shutdown():
        stopped.set()

    server = start_server(app)
    assert started.wait(5)
    assert not stopped.is_set()
    server.stop()
    assert stopped.wait(5)


def test_body_limit(start_server):
    clear_patterns()
    app = Application(
        urlpatterns=[
            path("x/", lambda request: JsonResponse({"size": len(request.body)}))
        ]
    )
    app.settings.MAX_BODY_SIZE = 1024

    server = start_server(app)
    status, _, body = server.request("POST", "/x/", body=b"x" * 2048)
    assert status == 413
    assert json.loads(body)["detail"] == "Request body too large"
