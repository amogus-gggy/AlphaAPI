# Views

Views are callables that accept an `HttpRequest` and return a response (or a
value AlphaAPI can turn into one).

## Function views

```python
async def item(request, item_id: int):
    return JsonResponse({"item_id": item_id})
```

Both `async def` and plain `def` are supported. Async views and any view wrapped
by middleware run on AlphaAPI's dedicated asyncio loop.

## Class-based views

```python
from alphaapi import JsonResponse, View

class ItemView(View):
    async def get(self, request, item_id: int):
        return JsonResponse({"item_id": item_id})

    async def delete(self, request, item_id: int):
        return HttpResponse(b"", status=204)
```

`View` provides:

- Method dispatch based on the request method.
- A `HEAD` fallback to `GET` when `GET` exists.
- Automatic `OPTIONS` responses with an `Allow` header.
- `405 Method Not Allowed` when no handler exists.

If `HEAD` is requested and the view implements neither `head` nor `get`, the
response is `405` rather than an attribute error.

## Reference

::: alphaapi.views.View
    options:
      members:
        - http_method_names
        - dispatch
        - http_method_not_allowed
        - options
        - as_view

::: alphaapi.views.RedirectView
    options:
      members:
        - get
