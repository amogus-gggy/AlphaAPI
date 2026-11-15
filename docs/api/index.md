# API reference

These pages are generated automatically from AlphaAPI's source code and
docstrings using [mkdocstrings](https://mkdocstrings.github.io/). Signatures,
source links, and docstrings stay in sync with the codebase.

## Modules

<div class="grid cards" markdown>

-   **[Application](application.md)** — the application object, lifecycle hooks,
    exception handlers, OpenAPI helpers, and test client.

-   **[Requests](requests.md)** — `HttpRequest`, `QueryDict`, form data, files,
    proxy-aware URL helpers.

-   **[Responses](responses.md)** — HTML, JSON, redirects, errors, cookies, and
    headers.

-   **[Binding parameters](binding.md)** — typed query, header, path, and body
    values from view signatures.

-   **[Streaming and files](streaming.md)** — streaming responses, SSE, and
    disk-backed file responses.

-   **[Views](views.md)** — function views, `View`, and `RedirectView`.

-   **[Routing](routing.md)** — `path()`, `include()`, converters, `reverse()`,
    and `resolve()`.

-   **[Settings](settings.md)** — defaults and the settings object.

-   **[Exceptions](exceptions.md)** — `HTTPException`, `Http404`, and friends.

-   **[Middleware](middleware.md)** — the middleware protocol and base class.

-   **[Security](security.md)** — hosts, headers, proxy headers, CORS, CSRF, and
    signed cookies.

-   **[Sessions and auth](sessions.md)** — cookie sessions, session stores, and
    pluggable authentication.

-   **[Observability](observability.md)** — request IDs, metrics, health checks,
    and access logs.

-   **[OpenAPI](openapi.md)** — schema generation and Swagger UI routes.

-   **[Static files](static-files.md)** — safe directory serving and `static()`.

-   **[Templates](templates.md)** — optional Jinja2 integration.

-   **[Testing](testing.md)** — the real-server test client.

-   **[CLI](cli.md)** — `startproject`, `startapp`, `runserver`, `routes`, and
    `check`.

-   **[Apps](apps.md)** — `AppConfig`, `AppRegistry`, and `INSTALLED_APPS`.

-   **[Low-level core](core.md)** — the Rust-backed `Request`, `Response`, and
    `AppCore` types.

</div>

## Top-level exports

Most public names are re-exported from `alphaapi`:

```python
from alphaapi import (
    Application,
    AppConfig,
    Client,
    CorsMiddleware,
    CsrfMiddleware,
    FileResponse,
    Header,
    HttpRequest,
    HttpResponse,
    JsonResponse,
    MetricsMiddleware,
    Query,
    RequestIdMiddleware,
    SecurityMiddleware,
    SessionMiddleware,
    SseResponse,
    StaticFiles,
    StreamingHttpResponse,
    TemplateResponse,
    UploadedFile,
    View,
    include,
    path,
    reverse,
    settings,
)
```

See [Binding parameters](binding.md), [Security](security.md), and
[Sessions and authentication](sessions.md) for the middleware and helper APIs.
