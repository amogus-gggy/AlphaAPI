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

## Reference

::: alphaapi.app.Application
    options:
      members:
        - add_url_patterns
        - reverse
        - on_startup
        - on_shutdown
        - exception_handler
        - stop
        - run
        - runserver

::: alphaapi.app.import_string
