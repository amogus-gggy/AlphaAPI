# Requests

Views that declare a request receive an `HttpRequest`. It exposes parsed query
parameters, form data, uploaded files, cookies, headers, and the raw body.
Query/form/cookie metadata is computed lazily on first access, and views that
omit the request entirely avoid materialising it in the core at all.

```python
async def inspect(request):
    return JsonResponse({
        "method": request.method,
        "path": request.path,
        "query": request.GET.dict(),
        "tags": request.GET.getlist("tag"),
        "form": request.POST.dict(),
        "files": list(request.FILES),
        "token": request.headers.get("x-token"),
        "body": request.json(),
        "client": request.client,
    })
```

## Common attributes

| Attribute | Meaning |
| --- | --- |
| `request.method` | HTTP method |
| `request.path`, `request.path_info` | Request path |
| `request.GET` | Query parameters (`QueryDict`) |
| `request.POST` | URL-encoded or multipart text fields (`QueryDict`) |
| `request.FILES` | Uploaded files, grouped by field name |
| `request.COOKIES` | Parsed cookies |
| `request.headers` | Lowercase header mapping |
| `request.body` | Raw body bytes |
| `request.json()` | Parse the body as JSON |
| `request.text()` | Decode the body as text |
| `request.client` | Client IP (proxy-aware when enabled) |
| `request.META` | CGI-style metadata mapping |

`QueryDict` keeps repeated values. `request.POST["tag"]` returns the last value,
while `request.POST.getlist("tag")` returns every value.

## Forms and uploads

`request.POST` handles both `application/x-www-form-urlencoded` and
`multipart/form-data`. Uploaded files are available through `request.FILES`:

```python
from alphaapi import JsonResponse

async def upload(request):
    upload = request.FILES["document"]
    return JsonResponse({
        "name": upload.filename,
        "size": upload.size,
        "content_type": upload.content_type,
    })
```

A field with one file maps to an `UploadedFile`; a repeated field maps to a list.
`UploadedFile` supports `read()`, `seek()`, `tell()`, `chunks()`,
`multiple_chunks()`, and `close()`.

```python
for chunk in request.FILES["document"].chunks(chunk_size=64 * 1024):
    ...
```

## Proxy-aware URLs

When `TRUST_PROXY_HEADERS` is enabled, these helpers use forwarded headers:

```python
request.scheme                 # "http" or "https"
request.is_secure()
request.get_host()
request.get_full_path()        # path plus query string
request.build_absolute_uri("/next/")
request.accepts("application/json")
```

## Reference

::: alphaapi.http.request.HttpRequest
    options:
      members:
        - body
        - raw
        - json
        - text
        - header
        - get_host
        - is_secure
        - get_full_path
        - build_absolute_uri
        - accepts

::: alphaapi.http.request.QueryDict
    options:
      members:
        - add
        - getlist
        - get
        - dict

::: alphaapi.http.multipart.UploadedFile

::: alphaapi.http.multipart.parse_multipart
