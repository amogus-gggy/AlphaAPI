# Middleware

Middleware wraps the view callable, Django style. A middleware factory receives
the next handler and returns a handler.

```python
class TimingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    async def __call__(self, request):
        response = await self.get_response(request)
        response["X-Elapsed"] = "0.001"
        return response
```

Register it by import path:

```python
MIDDLEWARE = ["project.middleware.TimingMiddleware"]
```

Middleware may be sync or async. When middleware is configured, routes run on
AlphaAPI's async event loop so both styles compose.

## Built-in middleware

| Middleware | Purpose |
| --- | --- |
| `SecurityMiddleware` | HTTPS redirects and security headers |
| `CorsMiddleware` | CORS headers and preflight responses |
| `CsrfMiddleware` | CSRF token verification |
| `SessionMiddleware` | Cookie-backed sessions |
| `AuthenticationMiddleware` | Resolve `request.user` |
| `RequestIdMiddleware` | Propagate or generate `X-Request-ID` |
| `MetricsMiddleware` | Record request counts and durations |

Order matters: place session middleware before authentication, and security /
CORS middleware early so their headers apply to all responses. See
[Security](security.md), [Sessions and auth](sessions.md), and
[Observability](observability.md).

## Reference

::: alphaapi.middleware.MiddlewareMixin

::: alphaapi.middleware.is_async_callable
