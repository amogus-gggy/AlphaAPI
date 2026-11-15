from __future__ import annotations

import json

import pytest
from alphaapi import (
    Application,
    Body,
    Client,
    Header,
    JsonResponse,
    Query,
    StaticFiles,
    TemplateEngine,
    TemplateResponse,
    path,
    static,
)
from alphaapi.openapi import docs_view, openapi_view
from alphaapi.urls import clear_patterns

try:
    from pydantic import BaseModel
except ImportError:  # pragma: no cover - optional dependency
    BaseModel = None  # type: ignore[assignment]


class Widget(BaseModel if BaseModel is not None else object):  # type: ignore[misc]
    name: str
    size: int = 1


def _build() -> Application:
    clear_patterns()

    async def widget(request, payload: Widget = Body(...)):  # noqa: B008
        return JsonResponse({"name": payload.name})

    async def search(
        request,
        q: str,
        x_token: str = Header(...),
        limit: int = Query(5),
    ):
        return JsonResponse({"q": q, "limit": limit})

    async def by_id(request, item_id: int):
        return JsonResponse({"item_id": item_id})

    return Application(
        urlpatterns=[
            path("widgets/", widget, name="widget"),
            path("search/", search, name="search"),
            path("items/<int:item_id>/", by_id, name="by-id"),
        ]
    )


def test_openapi_document_includes_typed_parameters():
    document = _build().openapi()
    assert document["openapi"] == "3.1.0"

    search = document["paths"]["/search/"]["get"]
    parameters = {param["name"]: param for param in search["parameters"]}
    assert parameters["q"]["in"] == "query"
    assert parameters["q"]["required"] is True
    assert parameters["q"]["schema"] == {"type": "string"}
    assert parameters["x-token"]["in"] == "header"
    assert parameters["limit"]["schema"] == {"type": "integer", "default": 5}

    widget = document["paths"]["/widgets/"]["post"]
    assert widget["requestBody"]["required"] is True
    reference = widget["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    assert reference.endswith("/Widget")
    assert "Widget" in document["components"]["schemas"]

    item = document["paths"]["/items/{item_id}/"]["get"]
    assert item["parameters"][0]["in"] == "path"
    assert item["parameters"][0]["schema"] == {"type": "integer"}


def test_openapi_and_docs_views():
    app = _build()
    openapi = openapi_view(app)
    docs = docs_view(app)
    response = openapi(None)
    assert response.status_code == 200
    assert json.loads(response.body)["openapi"] == "3.1.0"

    response = docs(None)
    assert response.status_code == 200
    assert b"SwaggerUIBundle" in response.body
    assert b"/openapi.json" in response.body


def test_builtin_static_and_openapi_routes(tmp_path, settings_override):
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("<h1>Home</h1>")

    settings_override(
        ALLOWED_HOSTS=["*"],
        STATIC_ROOT=str(site),
        STATIC_URL="/assets/",
        ENABLE_OPENAPI=True,
        OPENAPI_URL="/schema.json",
        DOCS_URL="/reference",
    )
    clear_patterns()
    app = Application(urlpatterns=[])
    with Client(app) as client:
        response = client.get("/assets/index.html")
        assert response.status_code == 200
        assert response.content == b"<h1>Home</h1>"

        assert client.get("/assets/missing.txt").status_code == 404

        schema = client.get("/schema.json")
        assert schema.status_code == 200
        assert json.loads(schema.content)["openapi"] == "3.1.0"

        docs = client.get("/reference")
        assert docs.status_code == 200
        assert b"SwaggerUIBundle" in docs.content


def test_static_helper_and_traversal(tmp_path):
    root = tmp_path / "public"
    root.mkdir()
    (root / "app.js").write_text("console.log(1)")
    outside = tmp_path / "secret.txt"
    outside.write_text("secret")

    static_view = StaticFiles(root, "/public/")
    assert static_view._resolve("app.js") == (root / "app.js").resolve()
    assert static_view._resolve("../secret.txt") is None

    clear_patterns()
    app = Application(
        urlpatterns=[static("public/<path:path>", root, name="public")]
    )
    with Client(app) as client:
        assert client.get("/public/app.js").content == b"console.log(1)"
        assert client.get("/public/../secret.txt").status_code == 404


def test_template_engine_and_response(tmp_path, settings_override):
    pytest.importorskip("jinja2")
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "hello.html").write_text("<h1>{{ name }}</h1>{{ raw }}")
    (templates / "escape.html").write_text("{{ value }}")

    engine = TemplateEngine([templates])
    assert engine.render("hello.html", {"name": "Sam", "raw": ""}) == "<h1>Sam</h1>"
    assert engine.render_string("{{ 1 + 1 }}") == "2"
    assert "&lt;script&gt;" in engine.render("escape.html", {"value": "<script>"})

    response = TemplateResponse(None, "hello.html", {"name": "Ana"}, engine=engine)
    assert response.status_code == 200
    assert response.media_type.startswith("text/html")
    assert b"<h1>Ana</h1>" in response.body


def test_global_template_render_uses_settings(tmp_path, settings_override):
    pytest.importorskip("jinja2")
    from alphaapi import render
    from alphaapi.templates import get_engine

    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "page.html").write_text("Hello {{ who }}")

    settings_override(TEMPLATES_DIR=str(templates))
    import alphaapi.templates as templates_module

    templates_module._default_engine = None
    assert render("page.html", {"who": "team"}) == "Hello team"
    assert get_engine() is not None
    templates_module._default_engine = None
