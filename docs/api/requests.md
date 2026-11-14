# Requests

Every view receives an `HttpRequest`. It exposes parsed query parameters, form
data, cookies, headers, and the raw body.

```python
async def inspect(request):
    return JsonResponse({
        "method": request.method,
        "path": request.path,
        "query": request.GET.dict(),
        "tags": request.GET.getlist("tag"),
        "token": request.headers.get("x-token"),
        "body": request.json(),
        "client": request.client,
    })
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

::: alphaapi.http.request.QueryDict
    options:
      members:
        - add
        - getlist
        - get
        - dict
