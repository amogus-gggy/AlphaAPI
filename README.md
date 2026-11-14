# AlphaAPI

A Django-shaped, **async-native** Python web framework with an HTTP core written
in Rust.

AlphaAPI borrows Django's project layout and ergonomics — settings modules,
URLconfs, function and class-based views, middleware and an app registry — while
using an async-first execution model and a Rust HTTP server.

It deliberately ships **no ORM** and no database layer. Bring your own data
access (SQLAlchemy, asyncpg, raw SQL, an HTTP client, ...). There is also **no
FastAPI compatibility layer**: the public API is its own.

> Status: early preview. The public API is intentionally small and may evolve.

## Install (from source)

```bash
python -m venv .venv
. .venv/bin/activate
pip install maturin
maturin develop --release
```

## Quick start

```python
# main.py
from alphaapi import Application, JsonResponse, path, settings

settings.configure(TITLE="Demo")

async def index(request):
    return JsonResponse({"hello": "world"})

async def read_item(request, item_id: int):
    return JsonResponse({"item_id": item_id, "q": request.GET.get("q")})

urlpatterns = [
    path("", index, name="index"),
    path("items/<int:item_id>/", read_item, name="item"),
]

app = Application(urlpatterns=urlpatterns)

if __name__ == "__main__":
    app.run(port=8000)
```

```bash
python main.py
# or
alphaapi runserver main:app --port 8000
```

## Scaffold a project

Create a new project and app from the CLI:

```bash
alphaapi startproject mysite
cd mysite

# Optional: create a reusable app inside the project
alphaapi startapp blog

# Run it
python manage.py --port 8000
# or
alphaapi runserver mysite.app:app --port 8000
```

`startproject` creates:

```text
mysite/
├── manage.py
└── mysite/
    ├── __init__.py
    ├── app.py          # `app = Application(...)`
    ├── settings.py
    ├── urls.py
    └── views.py
```

The generated home page is a Django-style welcome screen showing the AlphaAPI
version, the project name, and suggested next steps. Edit `mysite/views.py` to
replace it.

`startapp` creates a reusable package with `apps.py`, `urls.py`, `views.py`
and an empty `__init__.py`. Add its config to `INSTALLED_APPS` and include its
URLconf:

```python
INSTALLED_APPS = ["blog.apps.BlogConfig"]

urlpatterns = [
    path("blog/", include("blog.urls")),
]
```

Both commands accept an optional destination directory:

```bash
alphaapi startproject mysite /tmp/mysite
alphaapi startapp blog /tmp/mysite
```

## Run the bundled example project

```bash
cd examples
python manage.py --port 8000
# or, without manage.py
alphaapi runserver project.app:app --port 8000
```

The single-file example can be run from the repository root:

```bash
python examples/basic.py
```

## A Django-shaped project

```text
project/
├── manage.py
├── settings.py
├── urls.py
├── views.py
└── middleware.py
```

```python
# settings.py
DEBUG = True
ROOT_URLCONF = "project.urls"
MIDDLEWARE = ["project.middleware.TimingMiddleware"]
INSTALLED_APPS = []
TITLE = "My project"
```

```python
# urls.py
from alphaapi import include, path
from . import views

api_patterns = [
    path("health/", views.health, name="health"),
]

urlpatterns = [
    path("", views.index, name="index"),
    path("items/<int:item_id>/", views.item, name="item"),
    path("api/", include((api_patterns, "api"))),
]
```

```python
# app.py
from alphaapi import Application

app = Application(settings_module="project.settings")
```

```bash
alphaapi runserver project.app:app --reload
```

The [`examples/`](examples/) directory contains both a single-file app and the
project layout above.

## Settings

Settings are read from the module named by `ALPHAAPI_SETTINGS_MODULE`, from
`Application(settings_module=...)`, or configured directly for small scripts:

```python
from alphaapi.conf import settings

settings.configure(
    DEBUG=True,
    ROOT_URLCONF="project.urls",
    MIDDLEWARE=[],
    MAX_BODY_SIZE=16 * 1024 * 1024,
)
```

Default settings:

| Setting           | Default        |
| ----------------- | -------------- |
| `DEBUG`           | `False`        |
| `SECRET_KEY`      | `""`           |
| `ALLOWED_HOSTS`   | `["*"]`        |
| `INSTALLED_APPS`  | `[]`           |
| `MIDDLEWARE`      | `[]`           |
| `ROOT_URLCONF`    | `None`         |
| `DEFAULT_CHARSET` | `"utf-8"`      |
| `MAX_BODY_SIZE`   | `16 MiB`       |
| `ACCESS_LOG`      | `False`        |
| `TITLE`           | `"AlphaAPI"`   |
| `VERSION`         | `"0.1.0"`      |

## URLs

`path()` supports Django's standard converters:

```python
path("items/<int:item_id>/", view)
path("posts/<slug:slug>/", view)
path("files/<path:rest>", view)
path("users/<uuid:user_id>/", view)
```

Routes are matched by the Rust router. Composition uses `include()` with an
optional namespace or `(patterns, app_name)` pair:

```python
path("api/", include("project.api_urls"))
path("api/", include((api_patterns, "api")))
```

Build URLs by name:

```python
from alphaapi import reverse

reverse("item", kwargs={"item_id": 42})   # "/items/42/"
reverse("api:health")                    # "/api/health/"
```

## Views

Views are functions or classes that receive an `HttpRequest` and return an
`HttpResponse` (or a value that AlphaAPI normalizes for convenience).

### Function views

```python
from alphaapi import JsonResponse

async def item(request, item_id: int):
    return JsonResponse({"id": item_id, "q": request.GET.getlist("q")})
```

Both `async def` and plain `def` views are supported. New code should prefer
`async def`; AlphaAPI executes async views on a dedicated Python event loop.

### Class-based views

```python
from alphaapi import JsonResponse, View

class ItemView(View):
    async def get(self, request, item_id: int):
        return JsonResponse({"id": item_id})

    async def post(self, request, item_id: int):
        return JsonResponse({"created": request.json()}, status=201)


urlpatterns = [
    path("items/<int:item_id>/", ItemView.as_view()),
]
```

`View` handles method dispatch, `HEAD` fallback to `GET`, `OPTIONS`, and `405`
responses automatically. Passing a `View` subclass directly to `path()` also
works and calls `as_view()` for you.

### Request API

| Attribute / method | Meaning |
| ------------------ | ------- |
| `request.method` | HTTP method |
| `request.path`, `request.path_info` | Request path |
| `request.GET` | Query parameters (`QueryDict`, `.getlist()` for repeats) |
| `request.POST` | URL-encoded form fields (`QueryDict`) |
| `request.COOKIES` | Parsed cookies |
| `request.headers` | Lowercase header mapping |
| `request.body` | Raw body bytes |
| `request.json()` | Parse JSON body |
| `request.text()` | Body as text |
| `request.client` | Client IP address |
| `request.META` | CGI-style metadata mapping |

### Responses

```python
from alphaapi import (
    HttpResponse,
    JsonResponse,
    HttpResponseNotFound,
    HttpResponseRedirect,
)

HttpResponse("hello", content_type="text/plain; charset=utf-8")
HttpResponseNotFound("missing")
HttpResponseRedirect("/items/")
JsonResponse({"ok": True}, status=201)
```

Returning a `dict`, `list`, `str`, or `bytes` is also accepted and normalized
automatically.

### Exceptions

```python
from alphaapi import HTTPException, Http404, PermissionDenied

raise HTTPException(status_code=418, detail="I'm a teapot")
raise Http404("No such item")
raise PermissionDenied("Not allowed")
```

`HTTPException` becomes a JSON `{"detail": ...}` response. `Http404` and
`PermissionDenied` render 404/403 responses. Custom handlers can be registered:

```python
@app.exception_handler(MyError)
def handle_my_error(request, exc):
    return JsonResponse({"error": str(exc)}, status=400)
```

## Middleware

Middleware wraps the view callable, Django style:

```python
class TimingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    async def __call__(self, request):
        response = await self.get_response(request)
        response["X-Elapsed"] = "0.001"
        return response
```

List it in `MIDDLEWARE`. Async middleware is recommended; middleware runs inside
the async pipeline whenever it is configured.

## Apps

Reusable packages can expose an `AppConfig` and be listed in `INSTALLED_APPS`:

```python
# blog/apps.py
from alphaapi import AppConfig

class BlogConfig(AppConfig):
    name = "blog"
    verbose_name = "Blog"

    def ready(self):
        ...
```

```python
INSTALLED_APPS = ["blog.apps.BlogConfig"]
```

There are no models, migrations, admin, or database assumptions attached to
apps.

## Lifecycle

```python
@app.on_startup
async def startup():
    ...

@app.on_shutdown
async def shutdown():
    ...
```

Startup and shutdown hooks may be sync or async.

## CLI

```bash
alphaapi startproject mysite
alphaapi startapp blog

alphaapi runserver project.app:app --host 127.0.0.1 --port 8000
alphaapi runserver project.app:app --reload
alphaapi runserver project.app:app --settings project.settings
```

`manage.py` style entry points are just thin wrappers around `alphaapi.cli`.
Generated projects include a working `manage.py`.

## Benchmarks

See [`benchmarks/`](benchmarks/) for a comparison against FastAPI. The bundled
runner compiles a tiny std-only Rust load generator (`benchmarks/loadgen.rs`) so
the results are not capped by a GIL-bound Python client:

```bash
pip install -e '.[bench]'
python benchmarks/bench.py --fastapi
```

Output on a 2-core Celeron N3350 (5,000 requests, concurrency 16, `/json`):

```text
server                        req/s         time   errors
----------------------------------------------------------
AlphaAPI                      9,363       0.534s        0
FastAPI + uvicorn               415      12.042s        0
```

Absolute numbers vary with CPU frequency scaling; the relative gap has stayed
around 12–22x. Use `--python-load` to fall back to the dependency-free Python
load client.

## Documentation

The documentation site is built with [MkDocs Material](https://squidfunk.github.io/mkdocs-material/)
and [mkdocstrings](https://mkdocstrings.github.io/), so the API reference is
generated from the source and docstrings.

```bash
pip install -e '.[docs]'
mkdocs serve          # live preview at http://127.0.0.1:8000
mkdocs build --strict # static site in ./site
```

The site includes a getting-started guide, a task API tutorial, a blog tutorial,
a deployment guide, and the complete API reference. Pushing changes to `main`
runs the `docs` GitHub Actions workflow and deploys the site to GitHub Pages.

## Testing

```bash
pytest -q
```

## How it works

The Python layer resolves URLconfs at startup and hands a compact route
specification to the Rust core. At request time the Rust server parses and routes
the request, converts typed path converters, builds the Python request object,
and calls the view. Response serialization for dict/list values also happens in
Rust.

### Hot-path design

- **Zero-copy bodies.** Request bodies are kept as reference-counted `Bytes`.
  Single-frame bodies pass through without copying, and response bodies are
  handed to `hyper` as `Bytes`.
- **Direct JSON encoding.** The Rust serializer walks Python dicts/lists and
  writes JSON bytes directly, avoiding a `Python → serde_json::Value → bytes`
  round-trip.
- **Lazy request materialization.** Headers, query maps, path params and the
  full request object are only built when a route needs them.
- **Rust path matching.** `matchit` handles routing; Django path converters are
  translated to the Rust router's syntax once at startup.
- **Short path to Python.** Sync views without middleware run inline on the
  Tokio worker via a direct GIL attach. Async views and middleware run on a
  dedicated asyncio loop.
- **GIL-aware worker count.** Tokio workers default to half the available cores
  (minimum one); raise `workers=` if sync views block on I/O.

## Limits

- No ORM, database layer, migrations, or admin.
- No template engine or static-file serving built in.
- No regular-expression URL routes; use path converters.
- No WebSocket support.
- One body representation per view (access it through the request).
- HTTP/2 and TLS are not built in; place the server behind a reverse proxy if
  you need them.
- Sync views should stay short. Long CPU-bound work should move to async code or
  another process.
- Async exception handlers are not driven automatically; exception handlers run
  synchronously.

## License

MIT
