"""Optional Jinja2 template integration."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .conf import settings
from .http import HttpResponse


class TemplateEngine:
    """A thin wrapper around a Jinja2 environment."""

    def __init__(
        self,
        directories: list[str | Path] | None = None,
        *,
        autoescape: bool = True,
    ) -> None:
        try:
            from jinja2 import Environment, FileSystemLoader, select_autoescape
        except ImportError as error:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "Template support requires jinja2; install it with "
                "'pip install alphaapi[templates]'"
            ) from error

        configured = directories
        if configured is None:
            configured = []
            root = getattr(settings, "TEMPLATES_DIR", None)
            if root:
                configured.append(root)
            app_root = Path.cwd() / "templates"
            configured.append(app_root)

        self.environment = Environment(
            loader=FileSystemLoader([str(path) for path in configured]),
            autoescape=autoescape
            and select_autoescape(("html", "htm", "xml")),
        )

    def render(self, template_name: str, context: Mapping[str, Any] | None = None) -> str:
        return self.environment.get_template(template_name).render(dict(context or {}))

    def render_string(self, source: str, context: Mapping[str, Any] | None = None) -> str:
        return self.environment.from_string(source).render(dict(context or {}))


class TemplateResponse(HttpResponse):
    """Render a Jinja2 template into an HTML response."""

    def __init__(
        self,
        request: Any,
        template_name: str,
        context: Mapping[str, Any] | None = None,
        *,
        status: int = 200,
        headers: Mapping[str, str] | None = None,
        content_type: str | None = None,
        engine: TemplateEngine | None = None,
    ) -> None:
        values = dict(context or {})
        values.setdefault("request", request)
        renderer = engine or TemplateEngine()
        html = renderer.render(template_name, values)
        super().__init__(
            html,
            status=status,
            headers=headers,
            content_type=content_type or "text/html; charset=utf-8",
        )


_default_engine: TemplateEngine | None = None


def get_engine() -> TemplateEngine:
    global _default_engine
    if _default_engine is None:
        _default_engine = TemplateEngine()
    return _default_engine


def render(template_name: str, context: Mapping[str, Any] | None = None) -> str:
    return get_engine().render(template_name, context)


__all__ = ["TemplateEngine", "TemplateResponse", "get_engine", "render"]
