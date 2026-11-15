# Application

The `Application` object owns your settings, URLconf, middleware, exception
handlers, and lifecycle hooks. It wraps the Rust `AppCore` server.

## Example

```python
from alphaapi import Application, JsonResponse, path

async def index(request):
    return JsonResponse({"ok": True})

app = Application(
    urlpatterns=[path("", index, name="index")],
    title="Demo",
)

if __name__ == "__main__":
    app.run(port=8000)
```

## Schema and test client

`app.openapi()` returns an OpenAPI 3.1 document built from your routes and typed
view parameters. Set `ENABLE_OPENAPI = True` to mount the JSON schema and
Swagger UI routes automatically. See [OpenAPI](openapi.md).

`app.test_client()` returns a [Client](testing.md) that runs the real server on
an ephemeral loopback port.

## Reference

::: alphaapi.app.Application
    options:
      members:
        - add_url_patterns
        - reverse
        - openapi
        - test_client
        - on_startup
        - on_shutdown
        - exception_handler
        - stop
        - run
        - runserver

::: alphaapi.app.import_string
