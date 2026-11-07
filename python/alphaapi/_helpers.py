"""Helpers used by the Rust core to normalize Python values to JSON."""
from __future__ import annotations

import dataclasses
import datetime
import decimal
import enum
import pathlib
import uuid
from typing import Any


def to_builtin(value: Any) -> Any:
    """Recursively convert ``value`` into JSON-friendly Python builtins."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")

    if isinstance(value, dict):
        return {key: to_builtin(item) for key, item in value.items()}

    if isinstance(value, (list, tuple, set, frozenset)):
        return [to_builtin(item) for item in value]

    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            dumped = model_dump(mode="json")
        except TypeError:
            dumped = model_dump()
        return to_builtin(dumped)

    legacy_dict = getattr(value, "dict", None)
    if callable(legacy_dict) and hasattr(value, "__fields__"):
        return to_builtin(legacy_dict())

    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return to_builtin(dataclasses.asdict(value))

    if isinstance(value, enum.Enum):
        return to_builtin(value.value)

    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()

    if isinstance(value, datetime.timedelta):
        return value.total_seconds()

    if isinstance(value, uuid.UUID):
        return str(value)

    if isinstance(value, decimal.Decimal):
        return float(value)

    if isinstance(value, pathlib.PurePath):
        return str(value)

    if isinstance(value, BaseException):
        return str(value)

    return value
