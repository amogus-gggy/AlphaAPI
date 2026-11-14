# Low-level core

These types are implemented in Rust and exposed through `alphaapi._core`. Most
applications use the higher-level classes such as `HttpRequest`,
`HttpResponse`, and `Application`, but the low-level types are available when
you need direct control.

```python
from alphaapi._core import Response, dumps

response = Response(
    b'{"ok":true}',
    status_code=200,
    headers=[("content-type", "application/json")],
    media_type="application/json",
)

# Serialize a value with the Rust JSON encoder.
payload = dumps({"ok": True})
```

## Response headers

`Response.headers` accepts a mapping or an iterable of `(name, value)` pairs.
Use the header methods to preserve repeated fields:

```python
response.add_header("set-cookie", "a=1")
response.add_header("set-cookie", "b=2")
response.get_all_headers("set-cookie")  # ["a=1", "b=2"]
```

## Reference

::: alphaapi._core.Request

::: alphaapi._core.Response
    options:
      members:
        - header_items
        - add_header
        - set_header
        - remove_header
        - get_all_headers
        - clear_headers

::: alphaapi._core.dumps

::: alphaapi._core.AppCore
