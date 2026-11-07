"""Parameter markers, mirroring the ergonomics of FastAPI's ``Query`` & co."""
from __future__ import annotations

from typing import Any

MISSING: Any = object()


class Param:
    """Base class for all parameter markers."""

    __slots__ = ("default", "alias", "description")

    def __init__(
        self,
        default: Any = MISSING,
        *,
        alias: str | None = None,
        description: str | None = None,
    ) -> None:
        # ``...`` is the conventional "required" marker.
        self.default = MISSING if default is Ellipsis else default
        self.alias = alias
        self.description = description


class Query(Param):
    """Mark a function argument as a query parameter."""


class Path(Param):
    """Mark a function argument as a path parameter."""


class Header(Param):
    """Mark a function argument as a header."""


class Body(Param):
    """Mark a function argument as the request body."""


__all__ = ["MISSING", "Param", "Query", "Path", "Header", "Body"]
