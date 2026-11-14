# Apps

An app is a reusable package registered in `INSTALLED_APPS`. Apps can expose an
`AppConfig` with metadata and a `ready()` hook.

```python title="blog/apps.py"
from alphaapi import AppConfig

class BlogConfig(AppConfig):
    name = "blog"
    verbose_name = "Blog"

    def ready(self):
        # run setup code after the registry is populated
        ...
```

```python title="project/settings.py"
INSTALLED_APPS = ["blog.apps.BlogConfig"]
```

## Reference

::: alphaapi.apps.AppConfig
    options:
      members:
        - name
        - verbose_name
        - path
        - label
        - ready

::: alphaapi.apps.AppRegistry
    options:
      members:
        - populate
        - register
        - get
        - ready

::: alphaapi.apps.apps
