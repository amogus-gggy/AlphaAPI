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

## Reference

::: alphaapi.middleware.MiddlewareMixin

::: alphaapi.middleware.is_async_callable
