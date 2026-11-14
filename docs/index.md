---
hide:
  - navigation
  - toc
---

# Build fast APIs with a Django-shaped Python framework

**AlphaAPI** combines Django's project layout and developer ergonomics with an
async-first execution model and an HTTP core written in Rust.

[Get started](getting-started.md){ .md-button .md-button--primary }
[Browse tutorials](tutorials/index.md){ .md-button }

---

## Why AlphaAPI?

<div class="grid cards" markdown>

-   :material-rocket-launch-outline:{ .lg .middle } **Fast by default**

    ---

    Routing, request parsing, and JSON serialization happen in Rust. Python is
    only involved where your application code needs it.

    [:octicons-arrow-right-24: See the architecture](getting-started.md#how-it-works)

-   :fontawesome-solid-code:{ .lg .middle } **Django ergonomics**

    ---

    Settings modules, URLconfs, function views, class-based views, middleware,
    app configs, and the `manage.py` workflow you already know.

    [:octicons-arrow-right-24: Build a project](tutorials/deployment.md)

-   :material-language-python:{ .lg .middle } **Async-native**

    ---

    `async def` views and middleware run on a dedicated asyncio loop. Plain
    `def` views stay on the fast synchronous path.

    [:octicons-arrow-right-24: Write your first view](getting-started.md#your-first-view)

-   :material-database-off-outline:{ .lg .middle } **Bring your own stack**

    ---

    No ORM, no migrations, no hidden database assumptions. Use SQLAlchemy,
    asyncpg, an HTTP client, or plain SQL.

    [:octicons-arrow-right-24: Build a task API](tutorials/task-api.md)

</div>

## Quick start

```bash
python -m venv .venv
. .venv/bin/activate
pip install maturin
maturin develop --release
```

Create `main.py`:

```python title="main.py"
from alphaapi import Application, JsonResponse, path

async def index(request):
    return JsonResponse({"hello": "world"})

async def read_item(request, item_id: int):
    return JsonResponse({"item_id": item_id, "q": request.GET.get("q")})

app = Application(
    urlpatterns=[
        path("", index, name="index"),
        path("items/<int:item_id>/", read_item, name="item"),
    ]
)

if __name__ == "__main__":
    app.run(port=8000)
```

Run it:

```bash
python main.py
```

```bash
curl http://127.0.0.1:8000/items/42/?q=hello
# {"item_id":42,"q":"hello"}
```

## What you get

| Feature | AlphaAPI |
| --- | --- |
| HTTP server | Rust + hyper |
| Routing | Rust `matchit` router with Django path converters |
| Views | Sync and async functions and classes |
| JSON | Rust serializer for dicts, lists, and built-in types |
| Settings | Django-style settings module |
| Middleware | Django-style async middleware |
| CLI | `startproject`, `startapp`, `runserver` |
| Database / ORM | Bring your own |

## Explore the docs

- **[Getting started](getting-started.md)** — install, scaffold, and run.
- **[Tutorials](tutorials/index.md)** — build a task API, a blog, and deploy.
- **[API reference](api/index.md)** — auto-generated from the source and
  docstrings.
