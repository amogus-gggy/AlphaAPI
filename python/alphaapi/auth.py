"""Lightweight authentication helpers.

AlphaAPI deliberately ships no user model.  Applications can plug in a resolver
(``AUTH_USER_RESOLVER`` or the ``resolver=`` argument) that maps a request to a
user object.
"""
from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Callable

from .conf import settings
from .middleware import call_next


class AnonymousUser:
    is_authenticated = False
    is_anonymous = True
    is_staff = False
    is_superuser = False
    username = ""

    def __str__(self) -> str:
        return "AnonymousUser"

    def __repr__(self) -> str:
        return "<AnonymousUser>"


@dataclass
class SimpleUser:
    username: str
    user_id: Any = None
    is_authenticated: bool = True
    is_anonymous: bool = False
    is_staff: bool = False
    is_superuser: bool = False

    def __str__(self) -> str:
        return self.username


def _load_resolver() -> Callable[[Any], Any] | None:
    path = getattr(settings, "AUTH_USER_RESOLVER", None)
    if not path:
        return None
    from .app import import_string

    resolver = import_string(path) if isinstance(path, str) else path
    return resolver if callable(resolver) else None


class AuthenticationMiddleware:
    """Attach ``request.user`` using a pluggable resolver."""

    def __init__(
        self,
        get_response: Any,
        resolver: Callable[[Any], Any] | None = None,
    ) -> None:
        self.get_response = get_response
        self.resolver = resolver or _load_resolver()

    async def __call__(self, request: Any) -> Any:
        user = None
        if self.resolver is not None:
            user = self.resolver(request)
            if inspect.isawaitable(user):
                user = await user
        request.user = user if user is not None else AnonymousUser()
        return await call_next(self.get_response, request)


def login(request: Any, user: Any) -> None:
    session = getattr(request, "session", None)
    if session is None:
        raise RuntimeError("login() requires SessionMiddleware")
    # Rotate the session identifier on privilege change to prevent fixation.
    cycle_key = getattr(session, "cycle_key", None)
    if cycle_key is not None:
        cycle_key()
    session["_auth_user_id"] = getattr(user, "user_id", getattr(user, "pk", None))
    session["_auth_username"] = getattr(user, "username", str(user))
    session.modified = True


def logout(request: Any) -> None:
    session = getattr(request, "session", None)
    if session is None:
        raise RuntimeError("logout() requires SessionMiddleware")
    session.flush()


__all__ = [
    "AnonymousUser",
    "SimpleUser",
    "AuthenticationMiddleware",
    "login",
    "logout",
]
