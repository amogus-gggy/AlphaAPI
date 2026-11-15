# Streaming and files

Use streaming responses for large bodies, server-sent events, and files that
should not be loaded into memory.

## Streaming responses

`StreamingHttpResponse` accepts a synchronous iterable, an async iterable, or a
callable that returns one. Chunks may be `bytes`, `str`, or any value the
framework can serialize to JSON.

```python
from alphaapi import StreamingHttpResponse

async def numbers(request):
    async def chunks():
        for number in range(5):
            yield {"number": number}
            yield "\n"

    return StreamingHttpResponse(chunks(), content_type="application/json")
```

Synchronous generators work too, including views that are plain `def`:

```python
def download(request):
    def chunks():
        yield b"first\n"
        yield b"second\n"

    return StreamingHttpResponse(chunks(), content_type="text/plain")
```

An async generator passed from a synchronous view is still valid; the server
drives it on the event loop.

## Server-sent events

`SseResponse` formats mappings as SSE fields and sends plain strings or bytes
unchanged. It sets `Cache-Control: no-cache` and `X-Accel-Buffering: no` for
proxies.

```python
from alphaapi import SseResponse

async def events(request):
    async def stream():
        yield {"event": "tick", "id": 1, "data": {"value": 42}}
        yield {"data": "done"}

    return SseResponse(stream())
```

A mapping produces:

```text
event: tick
id: 1
data: {"value":42}

data: done

```

## File responses

`FileResponse` streams a file from disk and sets `Content-Length`, `ETag`,
`Last-Modified`, and `Accept-Ranges`.

```python
from alphaapi import FileResponse

async def report(request):
    return FileResponse("reports/latest.pdf", request=request)
```

Pass `request=` to enable conditional and range requests:

- `If-None-Match` / `If-Modified-Since` return `304 Not Modified`.
- A single `Range: bytes=...` returns `206 Partial Content`.
- An unsatisfiable range returns `416` with `Content-Range: bytes */<size>`.

To force a download:

```python
return FileResponse("report.csv", as_attachment=True, filename="report.csv")
```

`FileResponse` raises `FileNotFoundError` when the path does not exist. Prefer
[static files](static-files.md) for serving directories.

## Reference

::: alphaapi.http.response.StreamingHttpResponse

::: alphaapi.http.response.SseResponse

::: alphaapi.http.response.FileResponse
