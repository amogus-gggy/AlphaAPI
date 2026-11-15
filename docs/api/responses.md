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

Plain return values are normalized too:

```python
return {"ok": True}    # JSON
return "hello"         # text/plain
return b"raw bytes"    # application/octet-stream
return None            # 204 No Content
```

## Header behaviour

`response.headers` is a mutable, multi-value mapping:

- `response["X-Name"] = "value"` replaces all values for that header.
- `response.headers.add("Set-Cookie", value)` appends without replacing.
- `response.headers.get_all("Set-Cookie")` returns every value.
- `response.headers.items(multi=True)` returns every `(name, value)` pair.

`set_cookie()` and `delete_cookie()` append rather than replace, so multiple
cookies work correctly.

The default content type is available as `response.media_type`. The Rust core
adds it to the wire response when the body is sent.

## Streaming, SSE, and files

Use dedicated response classes for incremental bodies:

```python
from alphaapi import FileResponse, SseResponse, StreamingHttpResponse

return StreamingHttpResponse(chunks(), content_type="text/plain")
return SseResponse(event_stream())
return FileResponse("report.pdf", request=request)
```

See [Streaming and files](streaming.md) for ranges, conditional requests, and
event formatting.

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

::: alphaapi.http.response.HttpResponseConflict

::: alphaapi.http.response.HttpResponseGone

::: alphaapi.http.response.HttpResponseTooManyRequests

::: alphaapi.http.response.HttpResponseServiceUnavailable

::: alphaapi.http.response.HttpResponseGatewayTimeout
