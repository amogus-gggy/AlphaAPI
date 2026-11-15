"""OpenAPI schema generation and Swagger UI helpers."""
from __future__ import annotations

from typing import Any

from .http import HttpResponse, JsonResponse
from .params import build_param_specs
from .urls import _CONVERTER_RE

_TYPE_SCHEMAS: dict[str, dict[str, Any]] = {
    "str": {"type": "string"},
    "int": {"type": "integer"},
    "float": {"type": "number"},
    "bool": {"type": "boolean"},
    "bytes": {"type": "string", "format": "binary"},
    "json": {"type": "object"},
    "str_list": {"type": "array", "items": {"type": "string"}},
}


def _model_schema(model: Any, components: dict[str, Any]) -> dict[str, Any]:
    name = getattr(model, "__name__", None) or "Model"
    if name in components:
        return {"$ref": f"#/components/schemas/{name}"}

    if hasattr(model, "model_json_schema"):
        schema = model.model_json_schema()
    elif hasattr(model, "schema"):
        schema = model.schema()
    else:
        schema = {"type": "object"}

    components[name] = schema
    return {"$ref": f"#/components/schemas/{name}"}


def _param_schema(spec: dict[str, Any], components: dict[str, Any]) -> dict[str, Any]:
    if spec.get("type") == "model" and spec.get("model") is not None:
        return _model_schema(spec["model"], components)
    return _TYPE_SCHEMAS.get(str(spec.get("type")), {"type": "string"})


def _openapi_path(django_path: str) -> str:
    return _CONVERTER_RE.sub(lambda match: "{" + match.group("name") + "}", django_path)


def build_openapi(app: Any) -> dict[str, Any]:
    """Build an OpenAPI 3 document from an ``Application``."""
    app._ensure_resolved()
    components: dict[str, Any] = {}
    paths: dict[str, dict[str, Any]] = {}

    for pattern in app._resolved:
        try:
            view = app._resolve_view(pattern.view)
        except Exception:
            continue
        try:
            specs = build_param_specs(view, set(pattern.converters))
        except Exception:
            specs = []

        parameters: list[dict[str, Any]] = []
        for name, converter in pattern.converters.items():
            parameters.append(
                {
                    "name": name,
                    "in": "path",
                    "required": True,
                    "schema": _TYPE_SCHEMAS.get(
                        getattr(converter, "type_name", "str"), {"type": "string"}
                    ),
                }
            )

        request_body: dict[str, Any] | None = None
        for spec in specs:
            kind = spec["kind"]
            if kind in {"query", "header"}:
                parameter = {
                    "name": spec["alias"],
                    "in": kind,
                    "required": bool(spec["required"]),
                    "schema": _param_schema(spec, components),
                }
                if not spec["required"] and spec.get("default") is not None:
                    parameter["schema"] = {
                        **parameter["schema"],
                        "default": spec["default"],
                    }
                parameters.append(parameter)
            elif kind == "body":
                schema = _param_schema(spec, components)
                request_body = {
                    "required": bool(spec["required"]),
                    "content": {"application/json": {"schema": schema}},
                }

        method_names = ["get", "post", "put", "patch", "delete", "options"]
        operation = {
            "operationId": pattern.full_name or f"{method_names[0]}_{pattern.django_path}",
            "parameters": parameters,
            "responses": {
                "200": {
                    "description": "Successful response",
                    "content": {"application/json": {"schema": {"type": "object"}}},
                }
            },
        }
        if request_body is not None:
            operation["requestBody"] = request_body

        path = "/" + _openapi_path(pattern.django_path).lstrip("/")
        entry = paths.setdefault(path, {})
        for method_name in method_names:
            entry[method_name] = dict(operation)

    title = (
        getattr(app.settings, "OPENAPI_TITLE", None)
        or getattr(app, "title", None)
        or "AlphaAPI"
    )
    return {
        "openapi": "3.1.0",
        "info": {
            "title": title,
            "version": str(getattr(app, "version", "0.1.0")),
        },
        "paths": paths,
        "components": {"schemas": components},
    }


def openapi_view(app: Any) -> Any:
    def view(request: Any) -> JsonResponse:
        return JsonResponse(build_openapi(app))

    return view


def docs_view(app: Any) -> Any:
    schema_url = str(getattr(app.settings, "OPENAPI_URL", "/openapi.json"))

    def view(request: Any) -> HttpResponse:
        html = f"""<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <title>{getattr(app, 'title', 'AlphaAPI')} API docs</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css">
  </head>
  <body>
    <div id="swagger-ui"></div>
    <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
    <script>
      SwaggerUIBundle({{url: {schema_url!r}, dom_id: '#swagger-ui'}});
    </script>
  </body>
</html>"""
        return HttpResponse(html, content_type="text/html; charset=utf-8")

    return view


__all__ = ["build_openapi", "openapi_view", "docs_view"]
