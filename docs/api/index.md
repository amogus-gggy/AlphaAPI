# API reference

These pages are generated automatically from AlphaAPI's source code and
docstrings using [mkdocstrings](https://mkdocstrings.github.io/). Signatures,
source links, and docstrings stay in sync with the codebase.

## Modules

<div class="grid cards" markdown>

-   **[Application](application.md)** — the application object, lifecycle hooks,
    and exception handlers.

-   **[Requests](requests.md)** — `HttpRequest`, `QueryDict`, and request data.

-   **[Responses](responses.md)** — HTML, JSON, redirects, errors, cookies, and
    headers.

-   **[Views](views.md)** — function views, `View`, and `RedirectView`.

-   **[Routing](routing.md)** — `path()`, `include()`, converters, `reverse()`,
    and `resolve()`.

-   **[Settings](settings.md)** — defaults and the settings object.

-   **[Exceptions](exceptions.md)** — `HTTPException`, `Http404`, and friends.

-   **[Middleware](middleware.md)** — the middleware protocol and base class.

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
    HttpResponse,
    JsonResponse,
    HttpRequest,
    HTTPException,
    View,
    include,
    path,
    reverse,
    settings,
)
```
