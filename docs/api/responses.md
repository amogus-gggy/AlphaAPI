# Responses

Return an explicit response object for full control over status, headers, and
body, or return a plain value and let AlphaAPI normalize it.

```python
from alphaapi import HttpResponse, JsonResponse

async def created(request):
    response = JsonResponse({"ok": True}, status=201)
    response["X-Request-ID"] = "abc123"
    response.set_cookie("session", "value", httponly=True, secure=True)
    response.set_cookie("theme", "dark")  # a second Set-Cookie header
    return response
```

## Header behaviour

`response.headers` is a mutable, multi-value mapping:

- `response["X-Name"] = "value"` replaces all values for that header.
- `response.headers.add("Set-Cookie", value)` appends without replacing.
- `response.headers.get_all("Set-Cookie")` returns every value.
- `response.headers.items(multi=True)` returns every `(name, value)` pair.

`set_cookie()` and `delete_cookie()` append rather than replace, so multiple
cookies work correctly.

## Reference

::: alphaapi.http.response.HttpResponse
    options:
      members:
        - status
        - content
        - set_cookie
        - delete_cookie

::: alphaapi.http.response.JsonResponse

::: alphaapi.http.response.Headers
    options:
      members:
        - add
        - get_all
        - getlist
        - items

## Redirects

::: alphaapi.http.response.HttpResponseRedirect

::: alphaapi.http.response.HttpResponsePermanentRedirect

## Status helpers

::: alphaapi.http.response.HttpResponseNotModified

::: alphaapi.http.response.HttpResponseBadRequest

::: alphaapi.http.response.HttpResponseNotFound

::: alphaapi.http.response.HttpResponseForbidden

::: alphaapi.http.response.HttpResponseNotAllowed

::: alphaapi.http.response.HttpResponseServerError
