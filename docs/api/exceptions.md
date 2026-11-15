# Exceptions

Raise `HTTPException` (or one of its subclasses) to return a JSON error response
without a traceback.

```python
from alphaapi import HTTPException, Http404, PermissionDenied

raise HTTPException(418, detail="I'm a teapot", headers={"X-Tea": "earl-grey"})
raise Http404("Item not found")
raise PermissionDenied("You cannot do that")
```

The response body is:

```json
{"detail": "Item not found"}
```

## Custom handlers

```python
@app.exception_handler(Http404)
def handle_missing(request, exception):
    return JsonResponse({"error": str(exception)}, status=404)
```

Exception handlers receive the `HttpRequest` and the exception instance.
Handlers are matched in registration order against the exception type. Handlers
may be sync or async.

## Reference

::: alphaapi.exceptions.HTTPException

::: alphaapi.exceptions.Http404

::: alphaapi.exceptions.PermissionDenied

::: alphaapi.exceptions.BadRequest

::: alphaapi.exceptions.RequestValidationError
