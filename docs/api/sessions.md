# Sessions and authentication

AlphaAPI includes cookie-backed sessions and lightweight authentication
helpers. There is deliberately no user model or database dependency.

## Sessions

Add `SessionMiddleware` to expose `request.session`:

```python
from alphaapi import Application, SessionMiddleware

app = Application(urlpatterns=[], middleware=[SessionMiddleware])
```

```python
async def cart(request):
    request.session["items"] = request.session.get("items", 0) + 1
    return JsonResponse({"items": request.session["items"]})
```

Changes are saved automatically when the session is modified. Calling
`session.flush()` clears the data and removes the cookie.

Settings:

```python
SESSION_COOKIE_NAME = "sessionid"
SESSION_COOKIE_AGE = 60 * 60 * 24 * 14
SESSION_COOKIE_SECURE = False
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "lax"
```

The session key is stored in the cookie. When `SECRET_KEY` is set, the key is
signed so clients cannot tamper with it.

### Session stores

The default store is process-local memory. It is fine for development and
single-process deployments. For multiple workers or hosts, subclass
`SessionStore` and pass an instance to the middleware:

```python
from alphaapi import MemorySessionStore, SessionMiddleware

store = MemorySessionStore()


def session_middleware(get_response):
    return SessionMiddleware(get_response, store=store)


app = Application(
    urlpatterns=[],
    middleware=[session_middleware],
)
```

Implement `load`, `save`, and `delete` to use Redis, a database, or another
shared backend.

## Authentication

Authentication is pluggable. Provide a resolver that maps a request to a user,
then add `AuthenticationMiddleware`:

```python
from alphaapi import Application, AuthenticationMiddleware, SessionMiddleware

def get_user(request):
    user_id = request.session.get("_auth_user_id")
    if user_id is None:
        return None
    return load_user(user_id)  # your application code

app = Application(
    urlpatterns=[],
    middleware=[SessionMiddleware, AuthenticationMiddleware],
)
```

```python
AUTH_USER_RESOLVER = "project.auth.get_user"
```

The resolver may also be passed directly:

```python
AuthenticationMiddleware(get_response, resolver=get_user)
```

`request.user` is always set. Without a resolver or matching user it is an
`AnonymousUser`; otherwise it is whatever object your resolver returns.

Convenience helpers store the user id and username in the session:

```python
from alphaapi import login, logout

async def sign_in(request):
    user = authenticate(request)  # your application code
    login(request, user)
    return JsonResponse({"ok": True})

async def sign_out(request):
    logout(request)
    return JsonResponse({"ok": True})
```

`login()` and `logout()` require `SessionMiddleware` and raise `RuntimeError`
when no session is attached.

`SimpleUser` is a small dataclass suitable for examples and simple projects:

```python
from alphaapi import SimpleUser

user = SimpleUser(username="sam", user_id=7)
```

## Reference

::: alphaapi.sessions.SessionMiddleware

::: alphaapi.sessions.Session

::: alphaapi.sessions.SessionStore

::: alphaapi.sessions.MemorySessionStore

::: alphaapi.auth.AuthenticationMiddleware

::: alphaapi.auth.AnonymousUser

::: alphaapi.auth.SimpleUser

::: alphaapi.auth.login

::: alphaapi.auth.logout
