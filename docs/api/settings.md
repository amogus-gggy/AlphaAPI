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
| `TITLE` | `"AlphaAPI"` |
| `VERSION` | `"0.1.0"` |

The `ALPHAAPI_SETTINGS_MODULE` environment variable selects a settings module
when no explicit module is configured.

## Reference

::: alphaapi.conf.Settings
    options:
      members:
        - configure
        - configure_from_module

::: alphaapi.conf.DEFAULTS
