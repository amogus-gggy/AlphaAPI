"""Session middleware backed by a process-local store.

Sessions are intentionally small and dependency-free.  For multi-process
deployments provide a shared backend by subclassing ``SessionStore`` and passing
it to ``SessionMiddleware``.
"""
from __future__ import annotations

import secrets
import threading
import time
from typing import Any

from .conf import settings
from .middleware import call_next
from .signed_cookies import dumps, loads


class Session(dict):
    """A mutable session mapping."""

    def __init__(self, store: "SessionStore", key: str | None = None) -> None:
        super().__init__()
        self.store = store
        self.session_key = key
        self.modified = False
        self.accessed = False

    def __setitem__(self, key: str, value: Any) -> None:
        super().__setitem__(key, value)
        self.modified = True

    def __delitem__(self, key: str) -> None:
        super().__delitem__(key)
        self.modified = True

    def update(self, *args: Any, **kwargs: Any) -> None:
        super().update(*args, **kwargs)
        self.modified = True

    def pop(self, key: str, *args: Any) -> Any:
        self.modified = True
        return super().pop(key, *args)

    def setdefault(self, key: str, default: Any = None) -> Any:
        self.modified = True
        return super().setdefault(key, default)

    def clear(self) -> None:
        super().clear()
        self.modified = True

    def flush(self) -> None:
        """Delete the session data and mark it for removal."""
        super().clear()
        self.modified = True
        self.accessed = True

    def cycle_key(self) -> None:
        if self.session_key:
            self.store.delete(self.session_key)
        self.session_key = None
        self.modified = True

    def is_empty(self) -> bool:
        return not bool(self)


class SessionStore:
    """Interface for session backends."""

    def load(self, key: str) -> dict[str, Any] | None:  # pragma: no cover - interface
        raise NotImplementedError

    def save(self, key: str | None, data: dict[str, Any], max_age: int) -> str:
        raise NotImplementedError

    def delete(self, key: str) -> None:  # pragma: no cover - interface
        raise NotImplementedError


class MemorySessionStore(SessionStore):
    def __init__(self) -> None:
        self._data: dict[str, tuple[dict[str, Any], float]] = {}
        self._lock = threading.Lock()

    def _purge(self) -> None:
        now = time.time()
        expired = [key for key, (_, expiry) in self._data.items() if expiry <= now]
        for key in expired:
            self._data.pop(key, None)

    def load(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            self._purge()
            entry = self._data.get(key)
            if entry is None:
                return None
            data, _ = entry
            return dict(data)

    def save(self, key: str | None, data: dict[str, Any], max_age: int) -> str:
        with self._lock:
            self._purge()
            key = key or secrets.token_urlsafe(32)
            self._data[key] = (dict(data), time.time() + max_age)
            return key

    def delete(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)


_default_store = MemorySessionStore()


def _encode_key(key: str) -> str:
    secret = str(getattr(settings, "SECRET_KEY", "") or "")
    return dumps(key) if secret else key


def _decode_key(token: str) -> str | None:
    secret = str(getattr(settings, "SECRET_KEY", "") or "")
    if not secret:
        return token or None
    try:
        value = loads(token)
    except ValueError:
        return None
    return str(value)


class SessionMiddleware:
    """Attach ``request.session`` and persist changes in a cookie."""

    def __init__(self, get_response: Any, store: SessionStore | None = None) -> None:
        self.get_response = get_response
        self.store = store or _default_store

    async def __call__(self, request: Any) -> Any:
        cookie_name = str(getattr(settings, "SESSION_COOKIE_NAME", "sessionid"))
        max_age = int(getattr(settings, "SESSION_COOKIE_AGE", 1209600))
        token = request.COOKIES.get(cookie_name, "")
        key = _decode_key(token) if token else None
        data = self.store.load(key) if key else None
        session = Session(self.store, key if data is not None else None)
        if data:
            dict.update(session, data)
            session.accessed = True
        request.session = session

        response = await call_next(self.get_response, request)

        if session.modified:
            if session.is_empty():
                if session.session_key:
                    self.store.delete(session.session_key)
                response.delete_cookie(
                    cookie_name,
                    path="/",
                    domain=None,
                )
            else:
                key = self.store.save(session.session_key, dict(session), max_age)
                session.session_key = key
                response.set_cookie(
                    cookie_name,
                    _encode_key(key),
                    max_age=max_age,
                    path="/",
                    secure=bool(getattr(settings, "SESSION_COOKIE_SECURE", False)),
                    httponly=bool(getattr(settings, "SESSION_COOKIE_HTTPONLY", True)),
                    samesite=getattr(settings, "SESSION_COOKIE_SAMESITE", "lax"),
                )
        return response


__all__ = ["Session", "SessionStore", "MemorySessionStore", "SessionMiddleware"]
