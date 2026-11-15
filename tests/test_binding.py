from __future__ import annotations

import json

from alphaapi import (
    Application,
    Body,
    Client,
    Header,
    JsonResponse,
    Query,
    path,
)
from alphaapi import (
    Path as PathParam,
)
from alphaapi.urls import clear_patterns

try:
    from pydantic import BaseModel
except ImportError:  # pragma: no cover - optional dependency
    BaseModel = None  # type: ignore[assignment]


class Item(BaseModel if BaseModel is not None else object):  # type: ignore[misc]
    name: str
    qty: int = 1


def _decode(response):
    return json.loads(response.content)


def _app() -> Application:
    clear_patterns()

    async def search(
        request,
        q: str,
        limit: int = 10,
        ratio: float = 1.5,
        flag: bool = False,
        tags: list[str] = Query(default=[]),  # noqa: B008
    ):
        return JsonResponse(
            {
                "q": q,
                "limit": limit,
                "ratio": ratio,
                "flag": flag,
                "tags": tags,
            }
        )

    async def optional(request, name: str | None = None):
        return JsonResponse({"name": name})

    async def headers_view(
        request,
        x_token: str = Header(...),
        x_api_key: str = Header(alias="x-api-key"),
    ):
        return JsonResponse({"token": x_token, "key": x_api_key})

    async def body_view(request, payload: dict = Body(...)):  # noqa: B008
        return JsonResponse({"payload": payload})

    async def bytes_view(request, raw: bytes = Body(...)):
        return JsonResponse({"size": len(raw)})

    async def model_view(request, payload: Item = Body(...)):  # noqa: B008
        return JsonResponse({"name": payload.name, "qty": payload.qty})

    async def path_view(request, item_id: int = PathParam(...)):
        return JsonResponse({"item_id": item_id})

    async def no_request(q: str, count: int = 1):
        return JsonResponse({"q": q, "count": count})

    async def wrong_types(request, value: int = Query(...), enabled: bool = False):
        return JsonResponse({"value": value, "enabled": enabled})

    return Application(
        urlpatterns=[
            path("search/", search, name="search"),
            path("optional/", optional, name="optional"),
            path("headers/", headers_view, name="headers"),
            path("body/", body_view, name="body"),
            path("bytes/", bytes_view, name="bytes"),
            path("model/", model_view, name="model"),
            path("path/<int:item_id>/", path_view, name="path"),
            path("no-request/", no_request, name="no-request"),
            path("wrong/", wrong_types, name="wrong"),
            path("legacy/", lambda req: JsonResponse({"legacy": True}), name="legacy"),
        ]
    )


def test_query_binding_and_coercion():
    with Client(_app()) as client:
        response = client.get(
            "/search/?q=hello&limit=3&ratio=2.5&flag=true&tags=a&tags=b"
        )
        assert response.status_code == 200
        assert _decode(response) == {
            "q": "hello",
            "limit": 3,
            "ratio": 2.5,
            "flag": True,
            "tags": ["a", "b"],
        }


def test_query_defaults_and_optional_none():
    with Client(_app()) as client:
        assert _decode(client.get("/search/?q=hello")) == {
            "q": "hello",
            "limit": 10,
            "ratio": 1.5,
            "flag": False,
            "tags": [],
        }
        assert _decode(client.get("/optional/")) == {"name": None}
        assert _decode(client.get("/optional/?name=sam")) == {"name": "sam"}


def test_query_validation_errors():
    with Client(_app()) as client:
        response = client.get("/search/")
        assert response.status_code == 422
        detail = _decode(response)["detail"][0]
        assert detail["loc"] == ["query", "q"]
        assert detail["type"] == "missing"

        response = client.get("/search/?q=x&limit=nan")
        assert response.status_code == 422
        assert _decode(response)["detail"][0]["loc"] == ["query", "limit"]

        response = client.get("/wrong/?value=x")
        assert response.status_code == 422
        assert _decode(response)["detail"][0]["type"] == "int_parsing"

        response = client.get("/wrong/?value=1&enabled=maybe")
        assert response.status_code == 422
        assert _decode(response)["detail"][0]["type"] == "bool_parsing"


def test_header_binding_aliases_and_required():
    with Client(_app()) as client:
        response = client.get(
            "/headers/",
            headers={"x-token": "abc", "x-api-key": "key"},
        )
        assert response.status_code == 200
        assert _decode(response) == {"token": "abc", "key": "key"}

        response = client.get("/headers/", headers={"x-token": "abc"})
        assert response.status_code == 422
        assert _decode(response)["detail"][0]["loc"] == ["header", "x-api-key"]


def test_body_binding_dict_bytes_and_model():
    with Client(_app()) as client:
        assert _decode(client.post("/body/", json={"a": 1})) == {"payload": {"a": 1}}

        response = client.post("/body/", json=[1, 2])
        assert _decode(response) == {"payload": [1, 2]}

        response = client.post("/bytes/", body=b"hello")
        assert _decode(response) == {"size": 5}

        response = client.post("/body/", body=b"not-json")
        assert response.status_code == 422
        assert _decode(response)["detail"][0]["type"] == "json_invalid"

        response = client.post("/model/", json={"name": "pen", "qty": 2})
        assert _decode(response) == {"name": "pen", "qty": 2}

        response = client.post("/model/", json={"qty": 2})
        assert response.status_code == 422
        assert _decode(response)["detail"][0]["loc"] == ["body", "payload"]


def test_missing_body_is_required():
    with Client(_app()) as client:
        response = client.post("/body/")
        assert response.status_code == 422
        assert _decode(response)["detail"][0]["loc"] == ["body", "payload"]


def test_path_marker_and_legacy_request_argument():
    with Client(_app()) as client:
        assert _decode(client.get("/path/7/")) == {"item_id": 7}
        assert _decode(client.get("/legacy/")) == {"legacy": True}


def test_view_without_request_object():
    with Client(_app()) as client:
        response = client.get("/no-request/?q=x&count=4")
        assert response.status_code == 200
        assert _decode(response) == {"q": "x", "count": 4}


def test_spec_includes_typed_parameters():
    app = _app()
    app._ensure_resolved()
    pattern = next(p for p in app._resolved if p.name == "search")
    _handler, is_async, view = app._make_handler(pattern)
    spec = app._build_spec(pattern, is_async, view)
    names = {param["name"]: param for param in spec["params"]}
    assert names["request"]["kind"] == "request"
    assert names["q"]["kind"] == "query"
    assert names["q"]["type"] == "str"
    assert names["q"]["required"] is True
    assert names["limit"]["type"] == "int"
    assert names["limit"]["default"] == 10
    assert names["tags"]["type"] == "str_list"


def test_unresolvable_local_annotation_falls_back():
    def local_view(request, value: MissingType = Query(...)):  # noqa: F821,B008
        return JsonResponse({"value": value})

    clear_patterns()
    local_app = Application(urlpatterns=[path("local/", local_view)])
    with Client(local_app) as client:
        response = client.get("/local/?value=x")
        assert response.status_code == 200
        assert _decode(response) == {"value": "x"}
