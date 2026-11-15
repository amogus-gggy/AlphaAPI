from __future__ import annotations

from alphaapi import (
    Application,
    Client,
    ClientResponse,
    HttpResponse,
    JsonResponse,
    path,
)
from alphaapi.urls import clear_patterns


def _build() -> Application:
    clear_patterns()

    async def info(request):
        return JsonResponse(
            {
                "method": request.method,
                "path": request.path,
                "query": request.query_string,
                "x_header": request.headers.get("x-test"),
                "body": request.text(),
            }
        )

    async def echo_json(request):
        return JsonResponse(request.json())

    async def set_cookie(request):
        response = JsonResponse({"set": True})
        response.set_cookie("flavor", "oatmeal", path="/")
        return response

    async def delete_cookie(request):
        response = JsonResponse({"deleted": True})
        response.delete_cookie("flavor", path="/")
        return response

    async def cookie(request):
        return JsonResponse({"flavor": request.COOKIES.get("flavor")})

    async def plain(request):
        return HttpResponse("plain text")

    return Application(
        urlpatterns=[
            path("info/", info, name="info"),
            path("echo/", echo_json, name="echo"),
            path("set/", set_cookie, name="set"),
            path("delete/", delete_cookie, name="delete"),
            path("cookie/", cookie, name="cookie"),
            path("plain/", plain, name="plain"),
        ]
    )


def test_client_context_and_basic_requests():
    client = Client(_build())
    with client:
        assert client.port is not None
        response = client.get("/info/?a=1", headers={"x-test": "yes"})
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/json")
        assert response.text.startswith("{")
        assert response.json()["query"] == "a=1"
        assert response.json()["x_header"] == "yes"

        status, headers, body = response
        assert status == response.status_code
        assert headers is response.headers
        assert body == response.content
    client.close()
    client.close()


def test_client_sends_json_and_form_data():
    with Client(_build()) as client:
        response = client.post("/echo/", json={"a": [1, 2]})
        assert response.json() == {"a": [1, 2]}

        response = client.post("/info/", data={"a": "1", "b": "two"})
        data = response.json()
        assert data["method"] == "POST"
        assert data["body"] == "a=1&b=two"

        response = client.post("/info/", body="raw")
        assert response.json()["body"] == "raw"


def test_client_http_methods():
    with Client(_build()) as client:
        assert client.put("/info/").json()["method"] == "PUT"
        assert client.patch("/info/").json()["method"] == "PATCH"
        assert client.delete("/info/").json()["method"] == "DELETE"
        assert client.options("/info/").status_code == 200
        head = client.head("/plain/")
        assert head.status_code == 200
        assert head.headers["content-length"] == "10"
        assert head.content == b""


def test_client_cookie_jar_persists_and_deletes():
    with Client(_build()) as client:
        assert client.get("/cookie/").json()["flavor"] is None
        client.get("/set/")
        assert client.get("/cookie/").json()["flavor"] == "oatmeal"
        client.get("/delete/")
        assert client.get("/cookie/").json()["flavor"] is None


def test_client_explicit_cookies():
    with Client(_build()) as client:
        response = client.get("/cookie/", cookies={"flavor": "chocolate"})
        assert response.json()["flavor"] == "chocolate"


def test_client_starts_once_per_instance():
    app = _build()
    with Client(app) as client:
        port = client.port
        client.get("/info/")
        assert client.port == port


def test_client_response_dataclass():
    response = ClientResponse(201, {"x": "y"}, b'{"ok":true}')
    assert response.status_code == 201
    assert response.text == '{"ok":true}'
    assert response.json() == {"ok": True}
    assert list(response) == [201, {"x": "y"}, b'{"ok":true}']
