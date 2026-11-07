"""Function signature introspection used to bind request data in Rust."""
from __future__ import annotations

import dataclasses
import inspect
import re
import types
import typing
from typing import Any, Callable, get_args, get_origin

from ._core import Request
from .params import MISSING, Body, Header, Param, Path, Query

try:  # Pydantic is optional.
    from pydantic import BaseModel as _PydanticBaseModel
except Exception:  # pragma: no cover - pydantic is not installed
    _PydanticBaseModel = None

_NONE_TYPE = type(None)
_PATH_PARAM_RE = re.compile(r"\{(\*?)([^}:]+)(?::[^}]*)?\}")


@dataclasses.dataclass
class ParamInfo:
    name: str
    alias: str
    kind: str
    type: str
    required: bool
    default: Any = None
    model: Any = None
    positional: bool = True
    description: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "alias": self.alias,
            "kind": self.kind,
            "type": self.type,
            "required": self.required,
            "default": self.default,
            "model": self.model,
            "positional": self.positional,
        }


@dataclasses.dataclass
class Spec:
    params: list[ParamInfo]
    is_async: bool
    status_code: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "params": [param.to_dict() for param in self.params],
            "is_async": self.is_async,
            "status_code": self.status_code,
        }


def path_param_names(path: str) -> set[str]:
    return {match.group(2) for match in _PATH_PARAM_RE.finditer(path)}


def _safe_hints(func: Callable[..., Any]) -> dict[str, Any]:
    try:
        return typing.get_type_hints(func, include_extras=True)
    except Exception:
        pass
    try:
        return inspect.get_annotations(func, eval_str=True)
    except Exception:
        return dict(getattr(func, "__annotations__", {}))


def _split_annotation(annotation: Any) -> tuple[Any, Param | None]:
    """Peel ``Annotated[...]``, ``Optional[...]`` and ``X | None`` wrappers."""
    marker: Param | None = None
    for _ in range(4):
        if annotation is inspect.Parameter.empty:
            return annotation, marker

        origin = get_origin(annotation)
        if origin is typing.Annotated:
            args = get_args(annotation)
            annotation = args[0]
            for extra in args[1:]:
                if isinstance(extra, Param):
                    marker = extra
            continue

        if origin in (typing.Union, types.UnionType):
            args = [arg for arg in get_args(annotation) if arg is not _NONE_TYPE]
            if len(args) == 1:
                annotation = args[0]
                continue
        break
    return annotation, marker


def _is_model_type(annotation: Any) -> bool:
    if not isinstance(annotation, type):
        return False
    if _PydanticBaseModel is not None:
        try:
            if issubclass(annotation, _PydanticBaseModel):
                return True
        except TypeError:
            pass
    return dataclasses.is_dataclass(annotation)


def _is_request_type(annotation: Any) -> bool:
    return isinstance(annotation, type) and issubclass(annotation, Request)


def _infer_kind(
    name: str,
    annotation: Any,
    marker: Param | None,
    path_names: set[str],
) -> str:
    if name in path_names or isinstance(marker, Path):
        return "path"
    if isinstance(marker, Query):
        return "query"
    if isinstance(marker, Header):
        return "header"
    if isinstance(marker, Body):
        return "body"
    if _is_request_type(annotation):
        return "request"

    if annotation in (bytes, bytearray):
        return "body"

    origin = get_origin(annotation)
    if _is_model_type(annotation) or annotation is dict or origin is dict:
        return "body"
    if origin in (list, tuple, set, frozenset):
        args = [arg for arg in get_args(annotation) if arg is not Ellipsis]
        if any(_is_model_type(arg) or arg is dict for arg in args):
            return "body"
    return "query"


def _infer_type(annotation: Any, kind: str) -> tuple[str, Any]:
    if kind == "request":
        return "request", None
    if annotation in (bytes, bytearray):
        return ("bytes" if kind == "body" else "str"), None

    origin = get_origin(annotation)
    if origin in (list, tuple, set, frozenset):
        if kind == "query":
            return "str_list", None
        return "json", None

    if annotation is int:
        return "int", None
    if annotation is float:
        return "float", None
    if annotation is bool:
        return "bool", None
    if annotation is str:
        return "str", None
    if annotation is dict or origin is dict:
        return "json", None
    if _is_model_type(annotation):
        return "model", annotation
    if kind == "body":
        return "json", None
    return "str", None


def _default_alias(name: str, kind: str) -> str:
    if kind == "header":
        return name.replace("_", "-")
    return name


def build_spec(endpoint: Callable[..., Any], path: str, status_code: int) -> Spec:
    signature = inspect.signature(endpoint)
    hints = _safe_hints(endpoint)
    path_names = path_param_names(path)

    params: list[ParamInfo] = []
    seen_body = False

    for name, parameter in signature.parameters.items():
        if parameter.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue

        annotation = hints.get(name, parameter.annotation)
        annotation, marker = _split_annotation(annotation)

        default = parameter.default
        if isinstance(default, Param):
            marker = default
            default = default.default
        elif default is inspect.Parameter.empty:
            default = MISSING

        if marker is not None:
            alias = marker.alias
            description = marker.description
            if marker.default is not MISSING:
                default = marker.default
        else:
            alias = None
            description = None

        kind = _infer_kind(name, annotation, marker, path_names)
        type_name, model = _infer_type(annotation, kind)
        alias = alias or _default_alias(name, kind)
        required = default is MISSING

        if kind == "path":
            required = True
        if kind == "body":
            if seen_body:
                raise TypeError(
                    f"{endpoint!r} has more than one body parameter; "
                    "a route may only declare a single request body"
                )
            seen_body = True

        params.append(
            ParamInfo(
                name=name,
                alias=alias,
                kind=kind,
                type=type_name,
                required=required,
                default=None if required else default,
                model=model,
                positional=parameter.kind
                in (
                    inspect.Parameter.POSITIONAL_ONLY,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                ),
                description=description,
            )
        )

    return Spec(
        params=params,
        is_async=inspect.iscoroutinefunction(endpoint),
        status_code=status_code,
    )
