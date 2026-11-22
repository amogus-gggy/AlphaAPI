"""Typed request parameter markers and signature inspection.

The Rust core already knows how to extract query, header, body and path values
and coerce them to Python types.  This module bridges view signatures to that
spec so handlers can declare parameters directly::

    async def search(
        request,
        q: str,
        limit: int = 10,
        x_token: str = Header(...),
        payload: Item = Body(...),
    ): ...

Markers are intentionally lightweight: they only carry metadata.  Validation and
coercion happen in the Rust hot path, with Pydantic models (when installed)
validating body payloads.
"""
from __future__ import annotations

import inspect
import types
import typing
from dataclasses import dataclass
from typing import Any, get_args, get_origin

_MISSING = object()

# ``types.UnionType`` only exists on Python 3.10+; keep the 3.9 fallback.
_UNION_ORIGINS: tuple[Any, ...] = (typing.Union,)
if hasattr(types, "UnionType"):
    _UNION_ORIGINS = _UNION_ORIGINS + (types.UnionType,)


@dataclass(frozen=True)
class Param:
    """Metadata for one request parameter."""

    kind: str
    default: Any = _MISSING
    alias: str | None = None
    required: bool | None = None
    model: Any = None


def _make(
    kind: str,
    default: Any = _MISSING,
    *,
    alias: str | None = None,
    required: bool | None = None,
    model: Any = None,
) -> Param:
    if default is Ellipsis:
        default = _MISSING
    return Param(
        kind=kind,
        default=default,
        alias=alias,
        required=required,
        model=model,
    )


def Query(
    default: Any = _MISSING,
    *,
    alias: str | None = None,
    required: bool | None = None,
) -> Param:
    """Bind a query-string value (repeated values become ``list[str]``)."""
    return _make("query", default, alias=alias, required=required)


def Header(
    default: Any = _MISSING,
    *,
    alias: str | None = None,
    required: bool | None = None,
) -> Param:
    """Bind a request header.  Header names are matched case-insensitively."""
    return _make("header", default, alias=alias, required=required)


def Body(
    default: Any = _MISSING,
    *,
    alias: str | None = None,
    required: bool | None = None,
    model: Any = None,
) -> Param:
    """Bind the JSON request body (or a named field when ``alias`` is set)."""
    return _make("body", default, alias=alias, required=required, model=model)


def Path(
    default: Any = _MISSING,
    *,
    alias: str | None = None,
    required: bool | None = None,
) -> Param:
    """Explicitly mark a path parameter.

    Path-converter parameters are discovered from the route automatically, so
    this is mainly useful for readability.
    """
    return _make("path", default, alias=alias, required=required)


def _unwrap_annotation(annotation: Any) -> Any:
    """Strip ``Annotated``/``Optional`` wrappers for type inference."""
    if annotation is inspect.Parameter.empty:
        return inspect.Parameter.empty

    origin = get_origin(annotation)
    if origin is typing.Annotated:
        args = get_args(annotation)
        return _unwrap_annotation(args[0]) if args else annotation

    if origin in _UNION_ORIGINS:
        values = [arg for arg in get_args(annotation) if arg is not type(None)]
        if len(values) == 1:
            return _unwrap_annotation(values[0])
    return annotation


def _is_model_class(annotation: Any) -> bool:
    if not isinstance(annotation, type):
        return False
    return hasattr(annotation, "model_validate") or hasattr(annotation, "parse_obj")


def infer_type(annotation: Any, kind: str) -> tuple[str, Any]:
    """Return ``(rust_type_name, model_class)`` for an annotation."""
    annotation = _unwrap_annotation(annotation)

    if annotation is inspect.Parameter.empty:
        return ("str", None)

    if _is_model_class(annotation):
        return ("model", annotation)

    origin = get_origin(annotation)
    args = get_args(annotation)

    if annotation is bytes:
        return ("bytes", None)
    if annotation is bool:
        return ("bool", None)
    if annotation is int:
        return ("int", None)
    if annotation is float:
        return ("float", None)
    if annotation is str:
        return ("str", None)

    sequence_origins = {
        list,
        tuple,
        set,
        frozenset,
        typing.List,  # noqa: UP006
        typing.Tuple,  # noqa: UP006
        typing.Set,  # noqa: UP006
        typing.FrozenSet,  # noqa: UP006
    }
    if origin in sequence_origins or annotation in sequence_origins:
        if not args or _unwrap_annotation(args[0]) is str:
            return ("str_list", None)
        return ("json", None)

    if kind == "body":
        return ("json", None)
    if kind == "query" and origin is not None:
        return ("str_list", None)
    return ("str", None)


def _marker_kind(value: Any) -> str | None:
    if isinstance(value, Param):
        return value.kind
    return None


def _signature(view: Any) -> inspect.Signature | None:
    try:
        return inspect.signature(view, eval_str=True)
    except (TypeError, ValueError, NameError):
        try:
            return inspect.signature(view)
        except (TypeError, ValueError):
            return None


def wants_request(view: Any) -> bool:
    """Return whether ``view`` expects the request object as its first argument.

    Parameters named ``request`` are always treated as the request.  For
    backwards compatibility an unannotated first parameter (for example
    ``lambda req: ...``) is also treated as the request, while an annotated
    first parameter such as ``q: str`` is a typed binding.
    """
    signature = _signature(view)
    if signature is None:
        return True
    parameters = list(signature.parameters.values())
    if not parameters:
        return False
    first = parameters[0]
    if first.kind in (
        inspect.Parameter.VAR_POSITIONAL,
        inspect.Parameter.VAR_KEYWORD,
    ):
        return False
    if first.name in {"self", "cls"}:
        return False
    if first.name == "request":
        return True
    if first.default is not inspect.Parameter.empty:
        return False
    if isinstance(first.default, Param):
        return False
    return first.annotation is inspect.Parameter.empty


def positional_only_names(view: Any) -> set[str]:
    """Return parameter names declared positional-only (``def f(x, /)``)."""
    signature = _signature(view)
    if signature is None:
        return set()
    return {
        name
        for name, parameter in signature.parameters.items()
        if parameter.kind is inspect.Parameter.POSITIONAL_ONLY
    }


def build_param_specs(
    view: Any,
    path_names: set[str],
) -> list[dict[str, Any]]:
    """Build the Rust parameter spec for the non-request parameters of ``view``."""
    signature = _signature(view)
    if signature is None:
        return []

    specs: list[dict[str, Any]] = []
    for index, (name, parameter) in enumerate(signature.parameters.items()):
        if name in {"self", "cls"}:
            continue
        if parameter.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            continue

        marker = parameter.default if isinstance(parameter.default, Param) else None
        annotation = parameter.annotation

        # Backwards compatibility: the first positional parameter is the
        # request object even when it is not named ``request`` (for example
        # ``lambda req: ...``).  Annotated or explicitly marked parameters are
        # treated as typed bindings instead.
        if (
            index == 0
            and name != "request"
            and marker is None
            and annotation is inspect.Parameter.empty
            and parameter.kind
            in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            )
        ):
            continue

        if name == "request":
            continue

        if name in path_names:
            # Path converter params are already added by the router.  Honour an
            # explicit Path marker only for aliases/custom names, which are not
            # supported by Django path syntax without a separate converter.
            continue

        kind = _marker_kind(marker) if marker is not None else None
        if kind is None:
            unwrapped = _unwrap_annotation(annotation)
            kind = "body" if _is_model_class(unwrapped) else "query"

        default: Any = _MISSING
        if marker is not None:
            if marker.default is not _MISSING:
                default = marker.default
        elif parameter.default is not inspect.Parameter.empty:
            default = parameter.default

        required = (
            marker.required
            if marker is not None and marker.required is not None
            else default is _MISSING
        )

        ty, model = infer_type(annotation, kind)
        if marker is not None and marker.model is not None:
            model = marker.model
            ty = "model"

        alias = marker.alias if marker and marker.alias else name
        if kind == "header" and not (marker and marker.alias):
            alias = name.replace("_", "-")

        specs.append(
            {
                "name": name,
                "alias": alias,
                "kind": kind,
                "type": ty,
                "required": bool(required),
                "default": None if default is _MISSING else default,
                "model": model,
                "positional": parameter.kind is inspect.Parameter.POSITIONAL_ONLY,
            }
        )
    return specs


__all__ = [
    "Param",
    "Query",
    "Header",
    "Body",
    "Path",
    "infer_type",
    "build_param_specs",
    "positional_only_names",
    "wants_request",
]
