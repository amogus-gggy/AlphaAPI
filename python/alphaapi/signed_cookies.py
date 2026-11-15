"""Signed cookie helpers backed by HMAC-SHA256."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

from .conf import settings


def _secret() -> bytes:
    secret = str(getattr(settings, "SECRET_KEY", "") or "")
    if not secret:
        raise RuntimeError("SECRET_KEY must be configured to use signed cookies")
    return secret.encode("utf-8")


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _signature(payload: bytes) -> str:
    return _b64encode(hmac.new(_secret(), payload, hashlib.sha256).digest())


def dumps(value: Any) -> str:
    """Serialize and sign a JSON-compatible value."""
    payload = json.dumps(value, separators=(",", ":"), default=str).encode("utf-8")
    return f"{_b64encode(payload)}.{_signature(payload)}"


def loads(token: str, *, max_age: int | None = None) -> Any:
    """Verify a token produced by :func:`dumps` and return its value."""
    try:
        encoded, signature = token.split(".", 1)
        payload = _b64decode(encoded)
    except (ValueError, TypeError) as error:
        raise ValueError("invalid signed cookie") from error

    expected = _signature(payload)
    if not hmac.compare_digest(signature, expected):
        raise ValueError("invalid signed cookie signature")

    value = json.loads(payload.decode("utf-8"))
    if max_age is not None and isinstance(value, dict):
        issued = value.get("__issued")
        if issued is not None and time.time() - float(issued) > max_age:
            raise ValueError("signed cookie has expired")
    return value


def sign_object(value: Any) -> str:
    """Sign a value and embed an issue timestamp for optional ``max_age`` checks."""
    return dumps({"__issued": int(time.time()), "value": value})


def unsign_object(token: str, *, max_age: int | None = None) -> Any:
    payload = loads(token, max_age=max_age)
    if isinstance(payload, dict) and "value" in payload:
        return payload["value"]
    return payload


__all__ = ["dumps", "loads", "sign_object", "unsign_object"]
