# Project layout & deployment

This guide explains how an AlphaAPI project fits together and how to run it
safely in production.

AlphaAPI includes its own HTTP/1.1 and HTTP/2 (cleartext, prior knowledge)
server. It does **not** expose an ASGI or WSGI application, and TLS is not built
in. In production, put AlphaAPI behind a reverse proxy such as nginx, Caddy, or
a cloud load balancer to terminate TLS.

## Project layout

A scaffolded project looks like this:

```text
blogsite/
├── manage.py
└── blogsite/
    ├── __init__.py
    ├── app.py          # Application(settings_module="blogsite.settings")
    ├── settings.py
    ├── urls.py
    ├── views.py
    └── middleware.py
```

- `manage.py` is a thin wrapper around `alphaapi.cli`.
- `app.py` creates the `Application` singleton.
- `settings.py` contains uppercase settings.
- `urls.py` defines the root URLconf.
- `views.py`, `middleware.py`, and reusable apps contain application code.

## Settings

Settings can come from a module, from `Application(settings_module=...)`, or be
configured directly for scripts.

```python title="blogsite/settings.py"
DEBUG = False
SECRET_KEY = "load-this-from-the-environment"
ROOT_URLCONF = "blogsite.urls"
ALLOWED_HOSTS = ["example.com"]

INSTALLED_APPS = ["blog.apps.BlogConfig"]
MIDDLEWARE = [
    "blogsite.middleware.RequestContextMiddleware",
    "alphaapi.SecurityMiddleware",
    "alphaapi.SessionMiddleware",
]

MAX_BODY_SIZE = 2 * 1024 * 1024
ACCESS_LOG = True
ACCESS_LOG_JSON = True
TITLE = "My Blog"
VERSION = "1.0.0"

SECURITY_HEADERS = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_SSL_REDIRECT = True
TRUST_PROXY_HEADERS = True
TRUSTED_PROXIES = ["127.0.0.1"]

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
```

`ALPHAAPI_SETTINGS_MODULE` selects a settings module when the application is
started through the CLI:

```bash
alphaapi runserver blogsite.app:app --settings blogsite.settings
```

For secrets, read environment variables in `settings.py`:

```python
import os

SECRET_KEY = os.environ["SECRET_KEY"]
DEBUG = os.environ.get("ALPHAAPI_DEBUG") == "1"
```

## Lifecycle hooks

Startup and shutdown hooks are the place for connection pools, background
tasks, and cleanup:

```python title="blogsite/app.py"
from __future__ import annotations

from alphaapi import Application

app = Application(settings_module=f"{__package__}.settings")

@app.on_startup
async def startup():
    # create a database pool, warm caches, etc.
    ...

@app.on_shutdown
async def shutdown():
    # close the pool, flush buffers, etc.
    ...
```

Hooks may be sync or async. They run before the server starts accepting
connections and after it stops.

## Health check

Use the ready-made health helpers, or write your own readiness probe:

```python
from alphaapi import health_response, path, readiness_response

urlpatterns = [
    path("health/", health_response, name="health"),
    path("ready/", readiness_response, name="ready"),
    # ...
]
```

Point your load balancer or container orchestrator at `/health/`. Replace
`readiness_response` with a custom view if readiness should probe the database
or cache.

## Security

`ALLOWED_HOSTS` is enforced by the Rust core. Set it to your real hostnames:

```python
ALLOWED_HOSTS = ["example.com", ".example.com"]
```

Security headers are enabled by default. Enable HSTS only after HTTPS works end
to end, and add `SecurityMiddleware` if you want automatic HTTPS redirects:

```python
SECURITY_HEADERS = True
SECURE_HSTS_SECONDS = 31536000
SECURE_SSL_REDIRECT = True
```

Behind a proxy, enable forwarded headers and list only proxies you control:

```python
TRUST_PROXY_HEADERS = True
TRUSTED_PROXIES = ["127.0.0.1"]
```

Then `request.client` uses the forwarded client address when the peer is a
trusted proxy, and `request.scheme` / `request.build_absolute_uri()` reflect the
forwarded HTTPS scheme. Set `SESSION_COOKIE_SECURE` and `CSRF_COOKIE_SECURE`
too. See [Security](../api/security.md) for CORS, CSRF, and signed cookies.

## Run in development

```bash
python manage.py --port 8000
```

With auto-reload:

```bash
alphaapi runserver blogsite.app:app --reload
```

Never use `--reload` in production. The reloader watches `*.py` and `*.toml`
files and restarts the process.

## Run in production

Start the server directly:

```bash
python manage.py --host 127.0.0.1 --port 8000 --workers 4
```

Bind to loopback and let the reverse proxy handle public traffic. Set
`--access-log` or `ACCESS_LOG = True` to emit request logs.

Workers control the Tokio networking runtime. Python execution is still
serialized by the GIL, so more workers do not make CPU-bound Python faster.
Raise the count when sync views block on I/O, and prefer async views for I/O.

### systemd example

```ini title="/etc/systemd/system/alphaapi-blog.service"
[Unit]
Description=AlphaAPI blog
After=network.target

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/srv/alphaapi/blogsite
Environment="SECRET_KEY=replace-me"
ExecStart=/srv/alphaapi/.venv/bin/python manage.py --host 127.0.0.1 --port 8000 --workers 2
Restart=on-failure
RestartSec=2

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now alphaapi-blog
sudo systemctl status alphaapi-blog
```

## Reverse proxy

AlphaAPI accepts both HTTP/1.1 and HTTP/2 cleartext (h2c, prior knowledge).
Terminate TLS at the proxy and forward requests to the local AlphaAPI port.
Example nginx configuration:

```nginx title="/etc/nginx/sites-available/alphaapi-blog"
server {
    listen 80;
    server_name example.com;

    client_max_body_size 2m;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/alphaapi-blog /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

Use a TLS certificate from Let's Encrypt or your cloud provider at the proxy.

`request.client` contains the peer address of the connection by default. With
`TRUST_PROXY_HEADERS = True` and the proxy listed in `TRUSTED_PROXIES`, it uses
`X-Forwarded-For` and `X-Forwarded-Proto` instead, so client IPs, HTTPS
detection, and absolute URLs stay correct.

## Body size limits

Set `MAX_BODY_SIZE` to the largest request body you expect. The Rust core rejects
larger requests with `413 Payload Too Large` before invoking Python.

```python
MAX_BODY_SIZE = 2 * 1024 * 1024  # 2 MiB
```

The reverse proxy should enforce a compatible limit as well.

## Access logs

```bash
python manage.py --access-log --port 8000
```

or:

```python
ACCESS_LOG = True
ACCESS_LOG_JSON = True
```

Each request emits a line containing the method, path, status, and duration.
JSON logs are one object per line and are easier to ship to an aggregator.

## Metrics

Add the metrics middleware and expose the Prometheus endpoint:

```python
from alphaapi import Application, MetricsMiddleware, metrics_response, path

app = Application(
    urlpatterns=[path("metrics/", metrics_response, name="metrics")],
    middleware=[MetricsMiddleware],
)
```

Metrics are process-local; scrape every worker or aggregate externally. See
[Observability](../api/observability.md).

## Static files

For simple deployments, set `STATIC_ROOT` and `STATIC_URL` and AlphaAPI will
serve files with range and conditional-request support:

```python
STATIC_ROOT = "/srv/alphaapi/blogsite/static"
STATIC_URL = "/static/"
```

In production, prefer the reverse proxy, a CDN, or object storage for CSS,
JavaScript, images, and downloads. Keep application routes under a separate
prefix such as `/api/`. See [Static files](../api/static-files.md).

## Graceful shutdown

The server listens for ++ctrl+c++ and responds to `SIGINT`. With systemd,
`systemctl stop` sends `SIGTERM`; configure your process manager to stop the
service and allow time for in-flight requests to finish. Startup/shutdown hooks
run during the shutdown path.

## Checklist

- [ ] `DEBUG = False` and secrets loaded from the environment.
- [ ] `ALLOWED_HOSTS` set to real hostnames.
- [ ] AlphaAPI bound to `127.0.0.1` behind a TLS-terminating proxy.
- [ ] `TRUST_PROXY_HEADERS` enabled with a trusted proxy list.
- [ ] Secure cookies, CSRF, and HSTS configured.
- [ ] `MAX_BODY_SIZE` set appropriately.
- [ ] Access logging enabled (JSON if you ship logs).
- [ ] Health and readiness endpoints configured.
- [ ] Metrics endpoint scraped if you use `MetricsMiddleware`.
- [ ] Startup/shutdown hooks tested.
- [ ] Static assets served by the proxy or a CDN.
- [ ] Auto-reload disabled.
- [ ] A process manager restarts the service after failures.
- [ ] `alphaapi check` runs clean in deployment.

## Next steps

- Review the **[Application API](../api/application.md)**.
- Browse the auto-generated **[API reference](../api/index.md)**.
- Revisit the **[task API](task-api.md)** and **[blog](blog.md)** tutorials to
  add persistence and authentication.
