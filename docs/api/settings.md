# Settings

Settings are uppercase attributes read from a settings module, configured on the
`Application`, or set directly on the global `settings` object.

```python
# project/settings.py
DEBUG = False
SECRET_KEY = "load-me-from-the-environment"
ROOT_URLCONF = "project.urls"
INSTALLED_APPS = ["blog.apps.BlogConfig"]
MIDDLEWARE = ["project.middleware.TimingMiddleware"]

MAX_BODY_SIZE = 2 * 1024 * 1024
ACCESS_LOG = True
TITLE = "My project"
VERSION = "1.0.0"
```

```python
# project/app.py
from alphaapi import Application

app = Application(settings_module=f"{__package__}.settings")
```

For small scripts and tests:

```python
from alphaapi.conf import settings

settings.configure(DEBUG=True, TITLE="Scratch")
```

## Defaults

### Core

| Setting | Default |
| --- | --- |
| `DEBUG` | `False` |
| `SECRET_KEY` | `""` |
| `ALLOWED_HOSTS` | `["*"]` |
| `INSTALLED_APPS` | `[]` |
| `MIDDLEWARE` | `[]` |
| `ROOT_URLCONF` | `None` |
| `DEFAULT_CHARSET` | `"utf-8"` |
| `MAX_BODY_SIZE` | `16 MiB` |
| `ACCESS_LOG` | `False` |
| `ACCESS_LOG_JSON` | `False` |
| `TITLE` | `"AlphaAPI"` |
| `VERSION` | `"0.1.0"` |

### Proxy and security

| Setting | Default |
| --- | --- |
| `TRUST_PROXY_HEADERS` | `False` |
| `TRUSTED_PROXIES` | `[]` |
| `SECURE_PROXY_SSL_HEADER` | `"x-forwarded-proto"` |
| `SECURE_SSL_REDIRECT` | `False` |
| `SECURITY_HEADERS` | `True` |
| `SECURE_HSTS_SECONDS` | `0` |
| `SECURE_HSTS_INCLUDE_SUBDOMAINS` | `False` |
| `SECURE_REFERRER_POLICY` | `"same-origin"` |
| `X_FRAME_OPTIONS` | `"DENY"` |

See [Security](security.md) for host validation, CORS, CSRF, and signed cookies.

### Runtime limits

| Setting | Default |
| --- | --- |
| `REQUEST_TIMEOUT` | `None` |
| `MAX_CONCURRENT_REQUESTS` | `None` |
| `OFFLOAD_SYNC_VIEWS` | `False` |

`REQUEST_TIMEOUT` is in seconds. `MAX_CONCURRENT_REQUESTS` caps in-flight
requests. `OFFLOAD_SYNC_VIEWS` moves blocking sync views off the Tokio worker
threads.

### HTTP/2

All tuning values default to `None`, which keeps the server defaults.

| Setting |
| --- |
| `HTTP2_MAX_CONCURRENT_STREAMS` |
| `HTTP2_INITIAL_WINDOW_SIZE` |
| `HTTP2_KEEP_ALIVE_INTERVAL` |
| `HTTP2_KEEP_ALIVE_TIMEOUT` |

### Static files, templates, and OpenAPI

| Setting | Default |
| --- | --- |
| `STATIC_URL` | `"/static/"` |
| `STATIC_ROOT` | `None` |
| `TEMPLATES_DIR` | `None` |
| `ENABLE_OPENAPI` | `False` |
| `OPENAPI_URL` | `"/openapi.json"` |
| `DOCS_URL` | `"/docs"` |
| `OPENAPI_TITLE` | `None` |

See [Static files](static-files.md), [Templates](templates.md), and
[OpenAPI](openapi.md).

### CORS

| Setting | Default |
| --- | --- |
| `CORS_ALLOWED_ORIGINS` | `[]` |
| `CORS_ALLOW_ALL_ORIGINS` | `False` |
| `CORS_ALLOW_CREDENTIALS` | `False` |
| `CORS_ALLOWED_HEADERS` | `["*"]` |
| `CORS_ALLOWED_METHODS` | `["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]` |
| `CORS_MAX_AGE` | `600` |

### Sessions and authentication

| Setting | Default |
| --- | --- |
| `SESSION_COOKIE_NAME` | `"sessionid"` |
| `SESSION_COOKIE_AGE` | `1209600` (14 days) |
| `SESSION_COOKIE_SECURE` | `False` |
| `SESSION_COOKIE_HTTPONLY` | `True` |
| `SESSION_COOKIE_SAMESITE` | `"lax"` |
| `AUTH_USER_RESOLVER` | `None` |

### CSRF

| Setting | Default |
| --- | --- |
| `CSRF_COOKIE_NAME` | `"csrftoken"` |
| `CSRF_HEADER_NAME` | `"x-csrftoken"` |
| `CSRF_COOKIE_SECURE` | `False` |
| `CSRF_COOKIE_HTTPONLY` | `False` |
| `CSRF_COOKIE_SAMESITE` | `"lax"` |
| `CSRF_EXEMPT_PATHS` | `[]` |

## Environment

The `ALPHAAPI_SETTINGS_MODULE` environment variable selects a settings module
when no explicit module is configured. The CLI `--settings` flag sets it before
loading the app.

## Reference

::: alphaapi.conf.Settings
    options:
      members:
        - configure
        - configure_from_module

::: alphaapi.conf.DEFAULTS
