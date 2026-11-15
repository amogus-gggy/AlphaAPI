# Security

AlphaAPI ships host validation, security headers, HTTPS redirects, CORS, CSRF
protection, and signed-cookie helpers. All of them are configured through
settings and can be enabled per project.

## Allowed hosts

`ALLOWED_HOSTS` is enforced by the Rust core for every request. The default is
`["*"]`, which is convenient in development but should be tightened in
production.

```python
ALLOWED_HOSTS = ["example.com", ".example.com"]
```

- A plain entry matches the host exactly.
- A leading dot also allows subdomains: `.example.com` matches both
  `example.com` and `api.example.com`.
- `"*"` disables host checking.
- Ports are ignored when matching.

Requests with a missing or disallowed `Host` header receive `400 Bad Request`.

## Security headers

Security headers are applied by default (`SECURITY_HEADERS = True`) even without
middleware:

```python
SECURITY_HEADERS = True
X_FRAME_OPTIONS = "DENY"
SECURE_REFERRER_POLICY = "same-origin"
SECURE_HSTS_SECONDS = 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
```

When `SECURE_HSTS_SECONDS` is greater than zero, `Strict-Transport-Security` is
sent with that max-age.

`SecurityMiddleware` additionally supports HTTPS redirects and applies the same
headers at the Python layer:

```python
from alphaapi import Application, SecurityMiddleware

app = Application(
    urlpatterns=[],
    middleware=[SecurityMiddleware],
)
```

```python
SECURE_SSL_REDIRECT = True
```

A request that is not already HTTPS receives a `301` redirect.

## Proxy headers

When AlphaAPI runs behind a trusted reverse proxy, enable forwarded headers:

```python
TRUST_PROXY_HEADERS = True
TRUSTED_PROXIES = ["127.0.0.1", "10.1.2.3"]
SECURE_PROXY_SSL_HEADER = "x-forwarded-proto"
```

With `TRUST_PROXY_HEADERS` enabled, `request.client` uses the first
`X-Forwarded-For` value when the direct peer matches an entry in
`TRUSTED_PROXIES` (exact IPs, or `"*"`). `request.scheme`,
`request.is_secure()`, and `request.build_absolute_uri()` use
`X-Forwarded-Proto`. Leave `TRUST_PROXY_HEADERS = False` when clients can
connect directly, otherwise they can spoof these headers.

## CORS

Add `CorsMiddleware` and configure the origins you trust:

```python
from alphaapi import Application, CorsMiddleware

app = Application(urlpatterns=[], middleware=[CorsMiddleware])
```

```python
CORS_ALLOWED_ORIGINS = ["https://app.example.com"]
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOWED_HEADERS = ["*"]
CORS_ALLOWED_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]
CORS_MAX_AGE = 600
```

Preflight `OPTIONS` requests with `Access-Control-Request-Method` receive `204`
and the configured allow headers/methods. Disallowed origins receive no CORS
headers.

`CORS_ALLOW_ALL_ORIGINS = True` reflects the request origin. Do not combine it
with credentials unless you fully understand the risk.

## CSRF

`CsrfMiddleware` protects unsafe methods (`POST`, `PUT`, `PATCH`, `DELETE`).
Safe methods are always allowed.

```python
from alphaapi import Application, CsrfMiddleware, get_token

app = Application(urlpatterns=[], middleware=[CsrfMiddleware])
```

```python
CSRF_COOKIE_NAME = "csrftoken"
CSRF_HEADER_NAME = "x-csrftoken"
CSRF_EXEMPT_PATHS = ["/api/webhooks/"]
```

The submitted token may come from the configured header or from a
`csrfmiddlewaretoken` form field. It must match the cookie. Failed checks return
`403 CSRF verification failed`.

Render a token into forms with `get_token(request)`:

```python
async def form(request):
    return HttpResponse(f'<input type="hidden" name="csrfmiddlewaretoken" value="{get_token(request)}">')
```

## Signed cookies

Signed cookies use HMAC-SHA256 with `SECRET_KEY`. Configure a strong secret
before using them.

```python
from alphaapi import dumps_signed, loads_signed

token = dumps_signed({"user_id": 42})
value = loads_signed(token)          # {"user_id": 42}
value = loads_signed(token, max_age=3600)
```

`loads_signed` raises `ValueError` for tampered or expired tokens. Use
`sign_object` / `unsign_object` from `alphaapi.signed_cookies` when you want the
issue timestamp embedded automatically.

## Reference

::: alphaapi.security.SecurityMiddleware

::: alphaapi.security.host_is_allowed

::: alphaapi.cors.CorsMiddleware

::: alphaapi.csrf.CsrfMiddleware

::: alphaapi.csrf.get_token

::: alphaapi.signed_cookies.dumps

::: alphaapi.signed_cookies.loads

::: alphaapi.signed_cookies.sign_object

::: alphaapi.signed_cookies.unsign_object
