# Templates

Jinja2 integration is optional. Install the extra to use it:

```bash
pip install "alphaapi[templates]"
```

## Configure a directory

```python
TEMPLATES_DIR = "/srv/myapp/templates"
```

`TemplateEngine` searches `TEMPLATES_DIR` first and then `./templates` in the
current working directory. Autoescaping is enabled for HTML, HTM, and XML
templates.

```python
from alphaapi import TemplateEngine

engine = TemplateEngine(["/srv/myapp/templates"])
html = engine.render("page.html", {"title": "Home"})
fragment = engine.render_string("Hello {{ name }}", {"name": "Sam"})
```

## Render a response

`TemplateResponse` renders a template and returns an HTML response. The request
is added to the context automatically as `request`:

```python
from alphaapi import TemplateResponse

async def index(request):
    return TemplateResponse(request, "index.html", {"items": []})
```

Pass an engine explicitly when you use a custom directory or settings:

```python
return TemplateResponse(request, "index.html", engine=engine)
```

## Render a string

`render()` uses the process-wide default engine, configured from
`TEMPLATES_DIR`:

```python
from alphaapi import render

async def inline(request):
    html = render("index.html", {"items": []})
    return HttpResponse(html, content_type="text/html; charset=utf-8")
```

## Reference

::: alphaapi.templates.TemplateEngine

::: alphaapi.templates.TemplateResponse

::: alphaapi.templates.render

::: alphaapi.templates.get_engine
