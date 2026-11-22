# Getting started

This guide takes you from a clean checkout to a running AlphaAPI project.

## Requirements

- Python 3.9 or newer
- A Rust toolchain (`rustup`) for building the extension from source

## Install

```bash
python -m venv .venv
. .venv/bin/activate
pip install alphaapi
```

To develop from source, clone the repository and install the editable package
(requires a Rust toolchain):

```bash
git clone https://github.com/amogus-gggy/AlphaAPI.git
cd AlphaAPI
pip install -e .
```

## Scaffold a project

```bash
alphaapi startproject mysite
cd mysite
python manage.py --port 8000
```

The generated layout looks like this:

```text
mysite/
├── manage.py
└── mysite/
    ├── __init__.py
    ├── app.py          # Application(...)
    ├── settings.py
    ├── urls.py
    └── views.py
```

Open <http://127.0.0.1:8000/> to see the welcome page.

## Your first view

Edit `mysite/views.py`:

```python title="mysite/views.py"
from alphaapi import JsonResponse

async def index(request):
    return JsonResponse({"message": "Hello, AlphaAPI!"})
```

Then run the server again:

```bash
python manage.py --port 8000
```

```bash
curl http://127.0.0.1:8000/
# {"message":"Hello, AlphaAPI!"}
```

## Add a route with a path parameter

```python title="mysite/urls.py"
from alphaapi import path

from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path("items/<int:item_id>/", views.item, name="item"),
]
```

```python title="mysite/views.py"
from alphaapi import JsonResponse

async def index(request):
    return JsonResponse({"message": "Hello, AlphaAPI!"})

async def item(request, item_id: int):
    return JsonResponse({"item_id": item_id, "q": request.GET.get("q")})
```

The `<int:item_id>` converter validates the value before your view runs. A
request to `/items/not-a-number/` returns `404` instead of calling the view.

## Read the request

```python
async def inspect(request):
    return JsonResponse({
        "method": request.method,
        "path": request.path,
        "query": request.GET.dict(),
        "user_agent": request.headers.get("user-agent"),
        "client": request.client,
    })
```

Common request attributes:

| Attribute | Description |
| --- | --- |
| `request.method` | HTTP method |
| `request.path` | Request path |
| `request.GET` | Query parameters (`QueryDict`) |
| `request.POST` | URL-encoded form fields and multipart text fields |
| `request.FILES` | Uploaded files (`UploadedFile`) |
| `request.COOKIES` | Parsed cookies |
| `request.headers` | Lowercase header mapping |
| `request.body` | Raw body bytes |
| `request.json()` | Parse the body as JSON |
| `request.text()` | Decode the body as text |
| `request.client` | Client IP address |

## Bind typed parameters

Instead of reading query parameters by hand, declare them in the view
signature. AlphaAPI validates and coerces them before calling the view:

```python title="mysite/views.py"
from alphaapi import Header, JsonResponse, Query

async def search(
    request,
    q: str,
    limit: int = 10,
    tags: list[str] = Query(default=None),
    x_api_key: str = Header(...),
):
    return JsonResponse({"q": q, "limit": limit, "tags": tags})
```

`/search/?q=pen&limit=5&tags=ink&tags=paper` calls the view with `q="pen"`,
`limit=5`, and `tags=["ink", "paper"]`. Missing required values or bad types
return `422` with a JSON error. See
[Binding parameters](api/binding.md) for headers, bodies, Pydantic models, and
views that omit the request argument.

## Multipart uploads

`request.POST` and `request.FILES` handle `multipart/form-data` automatically:

```python
async def upload(request):
    upload = request.FILES["document"]
    return JsonResponse({
        "name": upload.filename,
        "size": upload.size,
        "content_type": upload.content_type,
    })
```

## Stream responses and files

Use `StreamingHttpResponse`, `SseResponse`, and `FileResponse` for bodies that
should not be built in memory:

```python
from alphaapi import FileResponse, SseResponse, StreamingHttpResponse

async def numbers(request):
    async def chunks():
        for number in range(5):
            yield {"number": number}
            yield "\n"

    return StreamingHttpResponse(chunks(), content_type="application/json")

async def events(request):
    async def stream():
        yield {"event": "tick", "data": {"value": 42}}

    return SseResponse(stream())

async def report(request):
    return FileResponse("reports/latest.pdf", request=request)
```

Passing `request=` to `FileResponse` enables `ETag`, `Last-Modified`, and range
requests. See [Streaming and files](api/streaming.md).


## Return a response

You can return a response object explicitly:

```python
from alphaapi import HttpResponse, JsonResponse, HttpResponseRedirect

return HttpResponse("plain text", content_type="text/plain; charset=utf-8")
return JsonResponse({"ok": True}, status=201)
return HttpResponseRedirect("/login/")
```

Or return a plain value and let AlphaAPI normalize it:

```python
return {"ok": True}    # JSON
return "hello"         # text/plain
return b"raw bytes"    # application/octet-stream
return None            # 204 No Content
```

## Run with reload

```bash
alphaapi runserver mysite.app:app --reload
```

The reloader watches Python and TOML files and restarts the server when they
change. It is intended for development only.

## Test your app

`Client` starts the real server on an ephemeral loopback port, so tests exercise
routing, middleware, cookies, and streaming end to end:

```python title="tests/test_app.py"
from alphaapi import Client

from mysite.app import app


def test_index():
    with Client(app) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert response.json() == {"message": "Hello, AlphaAPI!"}
```

You can also use `app.test_client()`. See [Testing](api/testing.md) for JSON,
form, cookie, and raw-body helpers.

## Inspect and validate

```bash
alphaapi routes mysite.app:app
alphaapi check mysite.app:app
```

`routes` prints every resolved route; `check` validates the application
configuration (for example, an empty `ALLOWED_HOSTS`) and exits non-zero on
errors. See [CLI](api/cli.md).

## How it works

AlphaAPI resolves your URLconf at startup and sends a compact route table to the
Rust core. At request time the Rust server:

1. Parses and routes the request.
2. Applies Django path converters.
3. Builds only the request fields your view declared.
4. Calls the Python view.
5. Encodes JSON responses in Rust when possible.

Sync views without middleware run inline on the Tokio worker. Async views and
middleware run on a dedicated asyncio event loop.

## Next steps

- Follow the **[task API tutorial](tutorials/task-api.md)** to build a complete
  CRUD service.
- Learn the **[project layout and deployment workflow](tutorials/deployment.md)**.
- Browse the **[API reference](api/index.md)**.
