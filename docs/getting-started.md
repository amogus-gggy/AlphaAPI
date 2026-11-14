# Getting started

This guide takes you from a clean checkout to a running AlphaAPI project.

## Requirements

- Python 3.9 or newer
- A Rust toolchain (`rustup`) for building the extension
- `maturin`

## Install from source

```bash
git clone https://github.com/amogus-gggy/AlphaAPI.git
cd AlphaAPI

python -m venv .venv
. .venv/bin/activate
pip install maturin

# Development build (fast rebuilds)
maturin develop
```

For production or benchmarking, build with optimizations:

```bash
maturin develop --release
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
| `request.POST` | URL-encoded form fields |
| `request.COOKIES` | Parsed cookies |
| `request.headers` | Lowercase header mapping |
| `request.body` | Raw body bytes |
| `request.json()` | Parse the body as JSON |
| `request.text()` | Decode the body as text |

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
