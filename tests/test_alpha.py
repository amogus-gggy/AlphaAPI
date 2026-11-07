from __future__ import annotations

import asyncio
import json
import threading
from dataclasses import dataclass

import pytest
from pydantic import BaseModel, Field

from alphaapi import (
    APIRouter,
    Alpha,
    Body,
    Header,
    HTTPException,
    JSONResponse,
    PlainTextResponse,
    Query,
    RedirectResponse,
    Request,
)


class Item(BaseModel):
    name: str
    price: float = Field(gt=0)
    tags: list[str] = []


@dataclass
class Widget:
    label: str
    count: int


class Boom(Exception):
    pass


def build_app() -> Alpha:
    app = Alpha(title="Test API", version="9.9.9", description="test app")

    @app.get("/")
    def root():
        return {"hello": "world"}

    @app.get("/items/{item_id}")
    def read_item(
        item_id: int,
        q: str | None = None,
        limit: int = Query(10),
        active: bool = True,
        ratio: float = 1.5,
    ):
        return {
            "item_id": item_id,
            "q": q,
            "limit": limit,
            "active": active,
            "ratio": ratio,
        }

    @app.get("/tags")
    def tags(tag: list[str] = Query(None)):
        return {"tags": tag}

    @app.get("/required")
    def required(q: str):
        return {"q": q}

    @app.get("/header")
    def header(x_token: str = Header(...)):
        return {"token": x_token}

    @app.post("/items", status_code=201)
    def create_item(item: Item):
        return {"created": item, "name": item.name}

    @app.post("/widgets")
    def create_widget(widget: Widget):
        return {"widget": widget}

    @app.post("/raw")
    def raw(data: bytes):
        return {"size": len(data), "text": data.decode()}

    @app.post("/dict-body")
    def dict_body(payload: dict = Body(...)):
        return payload

    @app.get("/text")
    def text():
        return "plain text"

    @app.get("/bytes")
    def raw_bytes():
        return b"\x00\x01\x02"

    @app.get("/custom")
    def custom():
        return JSONResponse({"custom": True}, status_code=202, headers={"x-demo": "yes"})

    @app.get("/teapot")
    def teapot():
        raise HTTPException(418, detail="I'm a teapot", headers={"x-tea": "earl-grey"})

    @app.get("/boom")
    def boom():
        raise Boom("custom boom")

    @app.exception_handler(Boom)
    def handle_boom(request, exc):
        return JSONResponse({"handled": str(exc)}, status_code=409)

    @app.get("/request")
    def request_info(request: Request):
        return {
            "method": request.method,
            "path": request.path,
            "query": request.query_params,
            "params": request.params,
            "x": request.header("x-test"),
            "body": request.text(),
        }

    @app.get("/async/{value}")
    async def async_route(value: int):
        await asyncio.sleep(0.002)
        return {"value": value, "double": value * 2}

    @app.get("/redirect")
    def redirect():
        return RedirectResponse("/")

    @app.get("/plain-response")
    def plain_response():
        return PlainTextResponse("from response", status_code=203)

    router = APIRouter(prefix="/api", tags=["api"])

    @router.get("/ping")
    def ping():
        return {"pong": True}

    api2 = APIRouter(prefix="/v2")

    @api2.get("/ping")
    def ping2():
        return {"pong": 2}

    router.include_router(api2)
    app.include_router(router)

    return app


@pytest.fixture(scope="session")
def client(start_server):
    return start_server(build_app())


def json_body(response):
    return json.loads(response[2])


def test_root(client):
    status, headers, body = client.request("GET", "/")
    assert status == 200
    assert headers["content-type"] == "application/json"
    assert json.loads(body) == {"hello": "world"}


def test_path_and_query_conversion(client):
    status, _, body = client.request("GET", "/items/42?q=hi&limit=7&active=false&ratio=2.5")
    assert status == 200
    assert json.loads(body) == {
        "item_id": 42,
        "q": "hi",
        "limit": 7,
        "active": False,
        "ratio": 2.5,
    }


def test_query_defaults(client):
    status, _, body = client.request("GET", "/items/1")
    assert status == 200
    assert json.loads(body) == {
        "item_id": 1,
        "q": None,
        "limit": 10,
        "active": True,
        "ratio": 1.5,
    }


def test_invalid_path_type_returns_422(client):
    status, _, body = client.request("GET", "/items/not-an-int")
    assert status == 422
    detail = json.loads(body)["detail"]
    assert detail[0]["loc"] == ["path", "item_id"]
    assert detail[0]["type"] == "int_parsing"


def test_missing_required_query_returns_422(client):
    status, _, body = client.request("GET", "/required")
    assert status == 422
    assert json.loads(body)["detail"][0]["loc"] == ["query", "q"]


def test_invalid_bool_returns_422(client):
    status, _, body = client.request("GET", "/items/1?active=maybe")
    assert status == 422
    assert json.loads(body)["detail"][0]["type"] == "bool_parsing"


def test_query_list(client):
    status, _, body = client.request("GET", "/tags?tag=a&tag=b")
    assert status == 200
    assert json.loads(body) == {"tags": ["a", "b"]}


def test_header_parameter(client):
    status, _, body = client.request("GET", "/header", headers={"x-token": "secret"})
    assert status == 200
    assert json.loads(body) == {"token": "secret"}

    status, _, body = client.request("GET", "/header")
    assert status == 422
    assert json.loads(body)["detail"][0]["loc"] == ["header", "x-token"]


def test_pydantic_body_and_status_code(client):
    payload = json.dumps({"name": "apple", "price": 1.5}).encode()
    status, _, body = client.request(
        "POST", "/items", body=payload, headers={"content-type": "application/json"}
    )
    assert status == 201
    data = json.loads(body)
    assert data["name"] == "apple"
    assert data["created"]["tags"] == []


def test_pydantic_validation_error(client):
    payload = json.dumps({"name": "apple", "price": -1}).encode()
    status, _, body = client.request("POST", "/items", body=payload)
    assert status == 422
    assert json.loads(body)["detail"][0]["loc"][0] == "body"


def test_dataclass_body(client):
    payload = json.dumps({"label": "x", "count": 3}).encode()
    status, _, body = client.request("POST", "/widgets", body=payload)
    assert status == 200
    assert json.loads(body) == {"widget": {"label": "x", "count": 3}}


def test_bytes_body(client):
    status, _, body = client.request("POST", "/raw", body=b"hello")
    assert status == 200
    assert json.loads(body) == {"size": 5, "text": "hello"}


def test_dict_body(client):
    payload = json.dumps({"a": [1, 2, 3]}).encode()
    status, _, body = client.request("POST", "/dict-body", body=payload)
    assert status == 200
    assert json.loads(body) == {"a": [1, 2, 3]}


def test_invalid_json_body(client):
    status, _, body = client.request("POST", "/dict-body", body=b"{not json")
    assert status == 422
    assert json.loads(body)["detail"][0]["type"] == "json_invalid"


def test_text_response(client):
    status, headers, body = client.request("GET", "/text")
    assert status == 200
    assert headers["content-type"].startswith("text/plain")
    assert body == b"plain text"


def test_bytes_response(client):
    status, headers, body = client.request("GET", "/bytes")
    assert status == 200
    assert headers["content-type"] == "application/octet-stream"
    assert body == b"\x00\x01\x02"


def test_custom_json_response(client):
    status, headers, body = client.request("GET", "/custom")
    assert status == 202
    assert headers["x-demo"] == "yes"
    assert json.loads(body) == {"custom": True}


def test_plain_response_class(client):
    status, headers, body = client.request("GET", "/plain-response")
    assert status == 203
    assert body == b"from response"


def test_redirect_response(client):
    status, headers, body = client.request("GET", "/redirect")
    assert status == 307
    assert headers["location"] == "/"
    assert body == b""


def test_http_exception(client):
    status, headers, body = client.request("GET", "/teapot")
    assert status == 418
    assert headers["x-tea"] == "earl-grey"
    assert json.loads(body) == {"detail": "I'm a teapot"}


def test_custom_exception_handler(client):
    status, _, body = client.request("GET", "/boom")
    assert status == 409
    assert json.loads(body) == {"handled": "custom boom"}


def test_request_object(client):
    status, _, body = client.request("GET", "/request?a=1&a=2&b=3", headers={"x-test": "yes"})
    assert status == 200
    data = json.loads(body)
    assert data["method"] == "GET"
    assert data["path"] == "/request"
    assert data["query"] == {"a": ["1", "2"], "b": "3"}
    assert data["x"] == "yes"


def test_async_handler(client):
    status, _, body = client.request("GET", "/async/21")
    assert status == 200
    assert json.loads(body) == {"value": 21, "double": 42}


def test_router_prefix_and_nested_prefix(client):
    status, _, body = client.request("GET", "/api/ping")
    assert status == 200
    assert json.loads(body) == {"pong": True}

    status, _, body = client.request("GET", "/api/v2/ping")
    assert status == 200
    assert json.loads(body) == {"pong": 2}


def test_404(client):
    status, _, body = client.request("GET", "/nope")
    assert status == 404
    assert json.loads(body) == {"detail": "Not Found"}


def test_405_and_allow_header(client):
    status, headers, body = client.request("POST", "/")
    assert status == 405
    assert "GET" in headers["allow"]
    assert json.loads(body) == {"detail": "Method Not Allowed"}


def test_options(client):
    status, headers, body = client.request("OPTIONS", "/")
    assert status == 204
    assert "GET" in headers["allow"]
    assert "HEAD" in headers["allow"]
    assert body == b""


def test_head(client):
    status, headers, body = client.request("HEAD", "/")
    assert status == 200
    assert body == b""
    assert int(headers["content-length"]) > 0


def test_openapi(client):
    status, _, body = client.request("GET", "/openapi.json")
    assert status == 200
    schema = json.loads(body)
    assert schema["openapi"] == "3.1.0"
    assert schema["info"]["title"] == "Test API"
    assert "/items/{item_id}" in schema["paths"]
    item_operation = schema["paths"]["/items"]["post"]
    assert item_operation["requestBody"]["content"]["application/json"]["schema"]["title"] == "Item"
    route_operation = schema["paths"]["/items/{item_id}"]["get"]
    names = {param["name"] for param in route_operation["parameters"]}
    assert {"item_id", "q", "limit", "active", "ratio"} <= names


def test_docs(client):
    status, headers, body = client.request("GET", "/docs")
    assert status == 200
    assert headers["content-type"].startswith("text/html")
    assert b"SwaggerUIBundle" in body


def test_lifecycle_hooks(start_server):
    started = threading.Event()
    stopped = threading.Event()
    app = Alpha(docs=False)

    @app.on_startup
    def startup():
        started.set()

    @app.on_shutdown
    def shutdown():
        stopped.set()

    @app.get("/")
    def root():
        return {"ok": True}

    server = start_server(app)
    assert started.wait(5)
    assert not stopped.is_set()
    server.stop()
    assert stopped.wait(5)


def test_body_limit(start_server):
    app = Alpha(docs=False)

    @app.post("/x")
    def x(data: bytes):
        return {"size": len(data)}

    server = start_server(app)
    status, _, body = server.request("POST", "/x", body=b"x" * (17 * 1024 * 1024))
    assert status == 413
    assert json.loads(body)["detail"] == "Request body too large"
