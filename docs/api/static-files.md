# Static files

AlphaAPI can serve files from a directory with safe path resolution. Files are
streamed with `FileResponse`, so ranges and conditional requests work without
loading the file into memory.

## Built-in static route

Configure a directory and URL prefix:

```python
STATIC_ROOT = "/srv/myapp/static"
STATIC_URL = "/static/"
```

`Application` adds a route for `STATIC_URL + "<path:path>"` automatically. A
request to `/static/css/app.css` serves `<STATIC_ROOT>/css/app.css`.

Static serving is intended for development and simple deployments. A CDN or
reverse proxy is usually a better choice in production.

## Explicit static route

Use `static()` when you want a different prefix or several directories:

```python
from alphaapi import static

urlpatterns = [
    static("assets/<path:path>", "assets", name="assets"),
    static("downloads/<path:path>", "/srv/downloads", name="downloads"),
]
```

The route must end with a `<path:...>` converter. The prefix is derived from
the part before the converter.

`StaticFiles` is also a callable view if you prefer to build the pattern
yourself:

```python
from alphaapi import StaticFiles, path

urlpatterns = [
    path("public/<path:path>", StaticFiles("public", "/public/"), name="public"),
]
```

## Safety

Paths are resolved relative to the configured directory. Requests that escape
the directory with `..`, absolute paths, or symlinks pointing outside it return
`404`. Only regular files are served.

Missing files return `404 Not Found`.

## Reference

::: alphaapi.staticfiles.StaticFiles

::: alphaapi.staticfiles.static
