"""Safe static-file serving."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .http import FileResponse, HttpResponseNotFound


class StaticFiles:
    """Serve files below ``directory`` under a URL prefix."""

    def __init__(self, directory: str | Path, url_prefix: str = "/static/") -> None:
        self.directory = Path(directory).resolve()
        self.url_prefix = "/" + url_prefix.strip("/") + "/"

    def _resolve(self, path: str) -> Path | None:
        relative = path.lstrip("/")
        candidate = (self.directory / relative).resolve()
        try:
            candidate.relative_to(self.directory)
        except ValueError:
            return None
        if candidate.is_file():
            return candidate
        return None

    def __call__(self, request: Any, path: str = "", **kwargs: Any) -> Any:
        candidate = self._resolve(path)
        if candidate is None:
            return HttpResponseNotFound("Static file not found")
        return FileResponse(candidate, request=request)


def static(
    route: str,
    directory: str | Path,
    *,
    name: str | None = None,
) -> Any:
    """Build a URL pattern serving static files.

    ``route`` should end with a ``<path:...>`` converter, for example
    ``static("assets/<path:path>", "assets")``.
    """
    from .urls import path

    return path(route, StaticFiles(directory, route.split("<", 1)[0]), name=name)


__all__ = ["StaticFiles", "static"]
