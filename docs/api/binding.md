# Binding parameters

AlphaAPI can read query parameters, headers, path values, and JSON bodies
straight from your view signature. The Rust core validates and coerces values
before the view runs, so views receive normal Python values instead of raw
strings.

```python
from alphaapi import Header, JsonResponse, Query, path

async def search(
    request,
    q: str,
    limit: int = 10,
    ratio: float = 1.0,
    tags: list[str] = Query(default=None),
    x_api_key: str = Header(...),
):
    return JsonResponse({
        "q": q,
        "limit": limit,
        "ratio": ratio,
        "tags": tags,
    })
```

## The request parameter

By convention the first parameter is the request object. Parameters named
`request` are always treated as the request. For backwards compatibility an
unannotated first parameter is also treated as the request, so
`lambda req: ...` keeps working.

Views that do not need the request can omit it; the first parameter is then a
typed binding:

```python
async def total(q: str, count: int = 1):
    return JsonResponse({"q": q, "count": count})
```

## Where values come from

| Declaration | Source |
| --- | --- |
| `q: str` | Query string |
| `q: str = Query(...)` | Query string |
| `x_token: str = Header(...)` | Request header |
| `payload: dict = Body(...)` | JSON request body |
| Pydantic model annotation | JSON request body |
| Parameter named in a path converter | URL path |

Path-converter parameters such as `<int:item_id>` are bound automatically:

```python
async def item(request, item_id: int):
    ...
```

`Path(...)` is available for readability, but path parameters are discovered
from the route itself.

## Query parameters

Query parameters are required unless they have a default or an `Optional` /
`None` default.

```python
async def list_items(
    request,
    q: str | None = None,
    limit: int = 20,
    active: bool = True,
    tags: list[str] = Query(default=None),
):
    ...
```

Mutable defaults such as `Query(default=[])` are shallow-copied per request,
but `None` is still the clearest way to express "not supplied". Repeated query
keys become a `list[str]`:

```text
/items/?tag=python&tag=rust
```

```python
tags == ["python", "rust"]
```

Supported scalar types are `str`, `int`, `float`, `bool`, `bytes`, and
`list[str]`. For request bodies, JSON-compatible annotations such as `dict` or
`list[dict]` are also accepted.

## Headers

Header names are case-insensitive. Underscores in parameter names map to
hyphens, and an explicit `alias=` overrides that:

```python
from alphaapi import Header

async def protected(
    request,
    x_token: str = Header(...),                 # X-Token
    x_api_key: str = Header(alias="x-api-key"), # X-Api-Key
):
    ...
```

## Request bodies

Use `Body(...)` for a required JSON body, or annotate with a Pydantic model to
have the body validated and converted automatically:

```python
from pydantic import BaseModel, Field
from alphaapi import Body, JsonResponse

class Item(BaseModel):
    name: str
    quantity: int = Field(default=1, ge=0)

async def create_item(request, item: Item):
    return JsonResponse({"name": item.name, "quantity": item.quantity}, status=201)

async def upload_raw(request, raw: bytes = Body(...)):
    return JsonResponse({"size": len(raw)})
```

`dict`, `list`, and `bytes` bodies are supported without Pydantic.

## Validation errors

Validation happens before the view is called. Invalid input returns `422` with
FastAPI-style details:

```json
{
  "detail": [
    {
      "loc": ["query", "limit"],
      "msg": "Input should be a valid integer",
      "type": "int_parsing"
    }
  ]
}
```

Locations use `query`, `header`, `path`, and `body`.

## OpenAPI

Typed parameters and Pydantic models are included automatically in the
generated OpenAPI document. See [OpenAPI](openapi.md).

## Reference

::: alphaapi.params.Query

::: alphaapi.params.Header

::: alphaapi.params.Body

::: alphaapi.params.Path

::: alphaapi.params.Param

::: alphaapi.params.build_param_specs

::: alphaapi.params.infer_type

::: alphaapi.params.wants_request
