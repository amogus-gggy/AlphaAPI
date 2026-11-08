"""Tests for the FastAPI backward-compatibility layer."""
from __future__ import annotations

import warnings

import http.client
import pytest

import alphaapi.compat.fastapi as compat

compat.install(warn=False)
from fastapi import (  # noqa: E402
    APIRouter,
    Cookie,
    Depends,
    FastAPI,
    HTTPException,
    Query,
    Request,
    status,
)
from fastapi.responses import JSONResponse  # noqa: E402


def test_install_warns_once():
    with pytest.warns(compat.CompatibilityWarning):
        compat.install()


def build_app() -> FastAPI:
    app = FastAPI(
        title="Compat API",
        version="1.2.3",
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    @app.get("/items/{item_id}", status_code=status.HTTP_200_OK, tags=["items"])
    def read_item(item_id: int, q: str | None = Query(default=None, alias="alias_q")):
        return {"item_id": item_id, "q": q}

    @app.post("/items", status_code=201)
    def create_item(payload: dict):
        return {"created": payload}

    @app.get("/cookie")
    def read_cookie(s: str = Cookie(default="none")):
        return {"s": s}

    @app.get("/dep")
    def with_dep(token: str = Depends(lambda: "tok-123")):
        return {"token": token}

    @app.get("/async")
    async def async_route():
        return {"async": True}

    @app.get("/request")
    def request_route(request: Request):
        return {"method": request.method, "path": request.url.path, "q": request.query_params.get("a")}

    @app.get("/raise", response_model=None)
    def raise_http():
        raise HTTPException(status_code=418, detail="teapot", headers={"x-tea": "yes"})

    def get_app(app=app):
        return app

    app.router = app

    sub = APIRouter(prefix="/sub", tags=["sub"])

    @sub.get("/ping")
    def ping():
        return {"pong": True}

    app.include_router(sub)
    return app


@pytest.fixture(scope="module")
def client(start_server):
    return start_server(build_app())


def test_path_and_alias_query(client):
    st, _, body = client.request("GET", "/items/3?alias_q=zzz")
    assert st == 200
    import json
    assert json.loads(body) == {"item_id": 3, "q": "zzz"}


def test_post_body(client):
    import json
    st, _, body = client.request(
        "POST", "/items", body=json.dumps({"a": 1}).encode(),
        headers={"content-type": "application/json"},
    )
    assert st == 201
    assert json.loads(body) == {"created": {"a": 1}}


def test_cookie_compat(client):
    import json
    st, _, body = client.request("GET", "/cookie", headers={"cookie": "s=abc"})
    assert st == 200
    assert json.loads(body) == {"s": "abc"}


def test_dependency_compat(client):
    import json
    st, _, body = client.request("GET", "/dep")
    assert st == 200
    assert json.loads(body) == {"token": "tok-123"}


def test_async_route(client):
    import json
    st, _, body = client.request("GET", "/async")
    assert st == 200
    assert json.loads(body) == {"async": True}


def test_request_adapter(client):
    import json
    st, _, body = client.request("GET", "/request?a=7")
    assert st == 200
    assert json.loads(body) == {"method": "GET", "path": "/request", "q": "7"}


def test_http_exception_compat(client):
    import json
    st, headers, body = client.request("GET", "/raise")
    assert st == 418
    assert headers.get("x-tea") == "yes"
    assert json.loads(body) == {"detail": "teapot"}


def test_include_router(client):
    import json
    st, _, body = client.request("GET", "/sub/ping")
    assert st == 200
    assert json.loads(body) == {"pong": True}


def test_openapi_and_docs(client):
    import json
    st, _, body = client.request("GET", "/openapi.json")
    assert st == 200
    schema = json.loads(body)
    assert schema["info"]["title"] == "Compat API"
    assert "/items/{item_id}" in schema["paths"]

    st, _, body = client.request("GET", "/docs")
    assert st == 200
    assert b"SwaggerUIBundle" in body


def test_404(client):
    st, _, body = client.request("GET", "/nope")
    assert st == 404
    import json
    assert json.loads(body) == {"detail": "Not Found"}
