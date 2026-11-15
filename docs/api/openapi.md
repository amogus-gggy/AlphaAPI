# OpenAPI

AlphaAPI can generate an OpenAPI 3.1 document from your URLs and typed view
signatures. Schema generation is available even when the built-in routes are
disabled.

```python
document = app.openapi()
```

The document includes:

- Path parameters from Django converters.
- Query parameters from typed view arguments.
- Header parameters from `Header(...)`.
- JSON request bodies from `Body(...)` and Pydantic models.
- Pydantic models under `components.schemas`.

See [Binding parameters](binding.md) for the supported declarations.

## Built-in schema and docs routes

Enable the routes with settings:

```python
ENABLE_OPENAPI = True
OPENAPI_URL = "/openapi.json"
DOCS_URL = "/docs"
OPENAPI_TITLE = "My API"
```

The schema route serves the generated JSON document. The docs route serves a
Swagger UI page that loads the schema.

```python
from alphaapi import Application

app = Application(urlpatterns=[], settings_config={
    "ENABLE_OPENAPI": True,
    "OPENAPI_URL": "/schema.json",
    "DOCS_URL": "/reference",
})
```

The routes are added when the `Application` is created, before the first
resolve. The title falls back to `app.title`, then `"AlphaAPI"`.

## Standalone views

The generators are also public functions:

```python
from alphaapi.openapi import build_openapi, docs_view, openapi_view

schema = build_openapi(app)
schema_view = openapi_view(app)
ui_view = docs_view(app)
```

The Swagger UI assets are loaded from jsDelivr, so the docs route needs network
access in the browser. The schema endpoint has no external dependencies.

## Reference

::: alphaapi.openapi.build_openapi

::: alphaapi.openapi.openapi_view

::: alphaapi.openapi.docs_view
