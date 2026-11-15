# Build a blog

This tutorial builds a small blog with:

- An HTML index and post pages.
- A JSON API under `/api/`.
- A reusable `blog` app registered in `INSTALLED_APPS`.
- Middleware that adds a request ID and a timing header.
- URL namespaces and named routes.

The storage layer is an in-memory dictionary; swap it for a database later.

## 1. Create the project and app

```bash
alphaapi startproject blogsite
cd blogsite
alphaapi startapp blog
```

The `startapp` command creates:

```text
blog/
├── __init__.py
├── apps.py
├── urls.py
└── views.py
```

## 2. Register the app and middleware

Edit `blogsite/settings.py`:

```python title="blogsite/settings.py"
DEBUG = True
SECRET_KEY = "replace-me"

ROOT_URLCONF = "blogsite.urls"
INSTALLED_APPS = ["blog.apps.BlogConfig"]
MIDDLEWARE = ["blogsite.middleware.RequestContextMiddleware"]

TITLE = "My AlphaAPI Blog"
VERSION = "1.0.0"
ACCESS_LOG = True
```

Create `blogsite/middleware.py`:

```python title="blogsite/middleware.py"
from __future__ import annotations

import time
import uuid

class RequestContextMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    async def __call__(self, request):
        started = time.perf_counter()
        request.request_id = uuid.uuid4().hex
        response = await self.get_response(request)
        elapsed = (time.perf_counter() - started) * 1000
        response["X-Request-ID"] = request.request_id
        response["X-Elapsed-MS"] = f"{elapsed:.2f}"
        return response
```

Middleware runs in the async pipeline. The `get_response` callable may return
either a response or an awaitable, so always `await` it when writing async
middleware.

## 3. Add the post store

Create `blog/store.py`:

```python title="blog/store.py"
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone

@dataclass
class Post:
    slug: str
    title: str
    body: str
    published: bool = True
    created_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

class PostStore:
    def __init__(self) -> None:
        self._posts: dict[str, Post] = {}

    def all(self, *, include_drafts: bool = False) -> list[Post]:
        posts = list(self._posts.values())
        if not include_drafts:
            posts = [post for post in posts if post.published]
        return sorted(posts, key=lambda post: post.created_at, reverse=True)

    def get(self, slug: str) -> Post | None:
        return self._posts.get(slug)

    def create(self, *, slug: str, title: str, body: str, published: bool) -> Post:
        post = Post(
            slug=slug,
            title=title,
            body=body,
            published=published,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self._posts[slug] = post
        return post

store = PostStore()
```

## 4. Write the HTML views

Replace `blog/views.py`:

```python title="blog/views.py"
from __future__ import annotations

from html import escape

from alphaapi import HTTPException, HttpResponse, JsonResponse

from .store import store

def _layout(title: str, content: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)} · My Blog</title>
  <style>
    body {{ font-family: system-ui, sans-serif; max-width: 46rem; margin: 3rem auto; padding: 0 1rem; line-height: 1.6; }}
    a {{ color: #6d28d9; }}
    article {{ border-bottom: 1px solid #ddd; padding-bottom: 1.5rem; margin-bottom: 1.5rem; }}
    .meta {{ color: #666; font-size: 0.9rem; }}
  </style>
</head>
<body>
  <p><a href="/">← All posts</a></p>
  <h1>{escape(title)}</h1>
  {content}
</body>
</html>"""

async def index(request):
    posts = store.all(include_drafts=request.GET.get("drafts") == "1")
    items = "".join(
        f'<article><h2><a href="/posts/{escape(post.slug)}/">{escape(post.title)}</a></h2>'
        f'<p class="meta">{escape(post.created_at)}</p>'
        f'<p>{escape(post.body[:180])}…</p></article>'
        for post in posts
    )
    return HttpResponse(_layout("Posts", items or "<p>No posts yet.</p>"))

async def post_detail(request, slug: str):
    post = store.get(slug)
    if post is None or (not post.published and request.GET.get("drafts") != "1"):
        raise HTTPException(404, "Post not found")
    content = f'<p class="meta">{escape(post.created_at)}</p><p>{escape(post.body)}</p>'
    return HttpResponse(_layout(post.title, content))
```

`HttpResponse` defaults to HTML and escapes are handled explicitly with
`html.escape`. This keeps the example dependency-free; optional Jinja2
integration is covered in [Templates](../api/templates.md).

## 5. Add the JSON API views

Append these views to `blog/views.py`:

```python
async def api_posts(request):
    if request.method == "GET":
        include_drafts = request.GET.get("drafts") == "1"
        return JsonResponse({
            "items": [post.to_dict() for post in store.all(include_drafts=include_drafts)]
        })

    try:
        data = request.json()
    except ValueError:
        raise HTTPException(400, "Request body must be valid JSON") from None

    if not isinstance(data, dict):
        raise HTTPException(400, "Request body must be a JSON object")

    slug = data.get("slug")
    title = data.get("title")
    body = data.get("body")
    if not isinstance(slug, str) or not slug:
        raise HTTPException(400, "slug is required")
    if not isinstance(title, str) or not title:
        raise HTTPException(400, "title is required")
    if not isinstance(body, str) or not body:
        raise HTTPException(400, "body is required")
    if store.get(slug) is not None:
        raise HTTPException(409, f"Post {slug!r} already exists")

    post = store.create(
        slug=slug,
        title=title,
        body=body,
        published=bool(data.get("published", True)),
    )
    return JsonResponse(post.to_dict(), status=201)

async def api_post_detail(request, slug: str):
    post = store.get(slug)
    if post is None:
        raise HTTPException(404, "Post not found")
    return JsonResponse(post.to_dict())
```

## 6. Wire up the blog app URLs

Replace `blog/urls.py`:

```python title="blog/urls.py"
from __future__ import annotations

from alphaapi import path

from . import views

app_name = "blog"

urlpatterns = [
    path("", views.index, name="index"),
    path("posts/<slug:slug>/", views.post_detail, name="post-detail"),
    path("api/posts/", views.api_posts, name="api-posts"),
    path("api/posts/<slug:slug>/", views.api_post_detail, name="api-post-detail"),
]
```

## 7. Include the app in the project URLconf

Edit `blogsite/urls.py`:

```python title="blogsite/urls.py"
from __future__ import annotations

from alphaapi import include, path

from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path("health/", views.health, name="health"),
    path("blog/", include("blog.urls")),
]
```

The `app_name = "blog"` in `blog/urls.py` creates the `blog` namespace. Reverse
URLs like this:

```python
from alphaapi import reverse

reverse("blog:index")                              # "/blog/"
reverse("blog:post-detail", kwargs={"slug": "hi"}) # "/blog/posts/hi/"
```

## 8. Run and try it

```bash
python manage.py --port 8000
```

Create a post through the JSON API:

```bash
curl -X POST http://127.0.0.1:8000/blog/api/posts/ \
  -H 'content-type: application/json' \
  -d '{"slug":"hello","title":"Hello","body":"My first post."}'
```

Open <http://127.0.0.1:8000/blog/> to see the HTML page. Inspect the response
headers to see the middleware output:

```bash
curl -I http://127.0.0.1:8000/blog/
```

```text
X-Request-ID: 4f1c...
X-Elapsed-MS: 0.42
```

## 9. Serve the API at `/api/`

If you prefer a top-level API namespace, include the app twice with different
prefixes only when the inner names differ, or keep the API routes in a separate
module. For example, create `blog/api_urls.py` with `app_name = "blog_api"` and
include it at `path("api/", include("blog.api_urls"))`.

## What you built

- A reusable app registered through `INSTALLED_APPS`.
- HTML and JSON views sharing the same store.
- Async middleware adding response headers.
- URL namespaces and `reverse()` support.
- Consistent `HTTPException` error responses.

## Next steps

- Add authentication middleware and check `request.headers`.
- Add pagination to `api_posts`.
- Read the **[API reference](../api/index.md)** for the full response and
  request surface.
- Follow the **[deployment guide](deployment.md)** before putting the site on a
  server.
