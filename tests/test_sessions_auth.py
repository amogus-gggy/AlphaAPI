from __future__ import annotations

import json

import pytest
from alphaapi import (
    AnonymousUser,
    Application,
    AuthenticationMiddleware,
    Client,
    JsonResponse,
    SessionMiddleware,
    SimpleUser,
    login,
    logout,
    path,
)
from alphaapi.sessions import MemorySessionStore
from alphaapi.urls import clear_patterns


def _json(response):
    return json.loads(response.content)


def _resolver(request):
    user_id = getattr(request, "session", {}).get("_auth_user_id")
    if user_id is None:
        return None
    return SimpleUser(username="sam", user_id=user_id)


def _build(middleware=None):
    clear_patterns()

    async def login_view(request):
        login(request, SimpleUser(username="sam", user_id=7))
        return JsonResponse({"logged_in": True})

    async def logout_view(request):
        logout(request)
        return JsonResponse({"logged_out": True})

    async def whoami(request):
        return JsonResponse(
            {
                "user": request.session.get("_auth_user_id"),
                "username": request.user.username,
                "authenticated": request.user.is_authenticated,
                "anonymous": request.user.is_anonymous,
            }
        )

    return Application(
        urlpatterns=[
            path("login/", login_view, name="login"),
            path("logout/", logout_view, name="logout"),
            path("whoami/", whoami, name="whoami"),
        ],
        middleware=middleware or [SessionMiddleware, AuthenticationMiddleware],
    )


def test_session_login_and_logout(settings_override):
    settings_override(
        SECRET_KEY="session-secret",
        SESSION_COOKIE_NAME="sid",
        SESSION_COOKIE_AGE=3600,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="strict",
        AUTH_USER_RESOLVER=_resolver,
    )
    with Client(_build()) as client:
        anonymous = _json(client.get("/whoami/"))
        assert anonymous == {
            "user": None,
            "username": "",
            "authenticated": False,
            "anonymous": True,
        }

        response = client.get("/login/")
        assert response.status_code == 200
        cookie = response.headers["set-cookie"]
        assert "sid=" in cookie
        assert "HttpOnly" in cookie
        assert "SameSite=strict" in cookie
        assert "Max-Age=3600" in cookie

        authenticated = _json(client.get("/whoami/"))
        assert authenticated["user"] == 7
        assert authenticated["username"] == "sam"
        assert authenticated["authenticated"] is True

        response = client.get("/logout/")
        cookie = response.headers["set-cookie"]
        assert "Max-Age=0" in cookie
        assert _json(client.get("/whoami/"))["user"] is None


def test_session_cookie_secure_attribute(settings_override):
    settings_override(
        SECRET_KEY="session-secret",
        SESSION_COOKIE_SECURE=True,
    )
    with Client(_build()) as client:
        response = client.get("/login/")
        assert "Secure" in response.headers["set-cookie"]


# This test deliberately exercises the empty-secret path; the warning it
# triggers is expected behaviour, so acknowledge it here.
@pytest.mark.filterwarnings("ignore:SessionMiddleware is enabled but SECRET_KEY is empty")
def test_session_without_secret_key(settings_override):
    settings_override(SECRET_KEY="")
    with Client(_build()) as client:
        assert client.get("/login/").status_code == 200
        assert client.get("/whoami/").status_code == 200


def test_authentication_without_resolver(settings_override):
    # Sessions are exercised elsewhere; give the middleware a secret so the
    # only behaviour under test is the missing resolver.
    settings_override(AUTH_USER_RESOLVER=None, SECRET_KEY="sessions-secret")
    with Client(_build()) as client:
        data = _json(client.get("/whoami/"))
        assert data["anonymous"] is True
        assert data["username"] == ""


def test_memory_session_store():
    store = MemorySessionStore()

    key = store.save(None, {"a": 1}, 60)
    assert store.load(key) == {"a": 1}
    assert store.load("missing") is None

    updated = store.save(key, {"a": 2}, 60)
    assert updated == key
    assert store.load(key) == {"a": 2}

    store.delete(key)
    assert store.load(key) is None

    expired = store.save(None, {"a": 3}, -1)
    assert store.load(expired) is None


def test_login_and_logout_require_session():
    # Calling the helpers directly requires an attached session.
    class FakeRequest:
        pass

    with pytest.raises(RuntimeError):
        login(FakeRequest(), SimpleUser("x"))
    with pytest.raises(RuntimeError):
        logout(FakeRequest())


def test_anonymous_user_repr():
    user = AnonymousUser()
    assert str(user) == "AnonymousUser"
    assert "AnonymousUser" in repr(user)
