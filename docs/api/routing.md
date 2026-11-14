# Routing

Routes use Django path syntax and are matched by the Rust router.

```python
from alphaapi import include, path

urlpatterns = [
    path("", views.index, name="index"),
    path("items/<int:item_id>/", views.item, name="item"),
    path("posts/<slug:slug>/", views.post, name="post"),
    path("files/<path:rest>", views.files, name="files"),
    path("api/", include("project.api_urls")),
]
```

Supported converters:

| Converter | Matches | Python type |
| --- | --- | --- |
| `str` | Any text except `/` | `str` |
| `int` | Digits | `int` |
| `float` | Decimal number | `float` |
| `slug` | Letters, digits, `-`, `_` | `str` |
| `uuid` | UUID text | `uuid.UUID` |
| `path` | Any text including `/` | `str` |

Custom converters are registered with `register_converter()`.

```python
from alphaapi import PathConverter, register_converter

class HexConverter(PathConverter):
    regex = "[0-9a-f]+"

    def to_python(self, value):
        return int(value, 16)

register_converter(HexConverter, "hex")
```

## Includes and namespaces

```python
# project/urls.py
urlpatterns = [
    path("blog/", include("blog.urls")),
    path("api/", include((api_patterns, "api"))),
]
```

If the included module defines `app_name`, its route names are namespaced
automatically:

```python
reverse("blog:post-detail", kwargs={"slug": "hello"})
reverse("api:health")
```

## Reference

::: alphaapi.urls.path

::: alphaapi.urls.include

::: alphaapi.urls.register_converter

::: alphaapi.urls.reverse

::: alphaapi.urls.resolve

::: alphaapi.urls.flatten

::: alphaapi.urls.register_patterns

::: alphaapi.urls.clear_patterns

## Types

::: alphaapi.urls.URLPattern

::: alphaapi.urls.URLResolver

::: alphaapi.urls.ResolvedPattern

::: alphaapi.urls.PathConverter

::: alphaapi.urls.NoReverseMatch

::: alphaapi.urls.ImproperlyConfigured
