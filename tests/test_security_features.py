from __future__ import annotations

import json

import pytest
from alphaapi import (
    Application,
    Client,
    CorsMiddleware,
    CsrfMiddleware,
    HttpResponse,
    JsonResponse,
    SecurityMiddleware,
    get_token,
    path,
)
from alphaapi.security import host_is_allowed
from alphaapi.signed_cookies import dumps, loads, sign_object, unsign_object
from alphaapi.urls import clear_patterns


def _json(response):
    return json.loads(response.content)


def _plain_app(**settings) -> Application:
    clear_patterns()

    async def plain(request):
        return HttpResponse("plain")

    return Application(
        urlpatterns=[path("plain/", plain, name="plain")],
        settings_config=settings,
    )


def test_host_is_allowed_helper():
    assert host_is_allowed("example.com", ["example.com"]) is True
    assert host_is_allowed("example.com:8000", ["example.com"]) is True
    assert host_is_allowed("api.example.com", [".example.com"]) is True
    assert host_is_allowed("example.com", [".example.com"]) is True
    assert host_is_allowed("evil.com", ["example.com"]) is False
    assert host_is_allowed("anything", ["*"]) is True
    assert host_is_allowed("anything", []) is False


def test_allowed_hosts_validation(settings_override):
    settings_override(ALLOWED_HOSTS=["example.com"])
    app = _plain_app()
    with Client(app) as client:
        assert client.get("/plain/").status_code == 400
        assert (
            client.get("/plain/", headers={"host": "example.com"}).status_code == 200
        )
        assert (
            client.get("/plain/", headers={"host": "api.example.com"}).status_code
            == 400
        )

    settings_override(ALLOWED_HOSTS=[".example.com"])
    app = _plain_app()
    with Client(app) as client:
        assert (
            client.get("/plain/", headers={"host": "api.example.com"}).status_code
            == 200
        )


def test_security_headers_from_core(settings_override):
    settings_override(
        ALLOWED_HOSTS=["*"],
        SECURITY_HEADERS=True,
        SECURE_HSTS_SECONDS=3600,
        SECURE_HSTS_INCLUDE_SUBDOMAINS=True,
        SECURE_REFERRER_POLICY="no-referrer",
        X_FRAME_OPTIONS="SAMEORIGIN",
    )
    with Client(_plain_app()) as client:
        headers = client.get("/plain/").headers
        assert headers["x-content-type-options"] == "nosniff"
        assert headers["x-frame-options"] == "SAMEORIGIN"
        assert headers["referrer-policy"] == "no-referrer"
        assert (
            headers["strict-transport-security"]
            == "max-age=3600; includeSubDomains"
        )

    settings_override(SECURITY_HEADERS=False)
    with Client(_plain_app()) as client:
        headers = client.get("/plain/").headers
        assert "x-content-type-options" not in headers


def test_security_middleware_headers_and_redirect(settings_override):
    clear_patterns()

    async def plain(request):
        return HttpResponse("plain")

    def build():
        return Application(
            urlpatterns=[path("plain/", plain, name="plain")],
            middleware=[SecurityMiddleware],
        )

    settings_override(SECURE_SSL_REDIRECT=False)
    with Client(build()) as client:
        headers = client.get("/plain/").headers
        assert headers["x-content-type-options"] == "nosniff"

    settings_override(SECURE_SSL_REDIRECT=True, TRUST_PROXY_HEADERS=False)
    with Client(build()) as client:
        response = client.get("/plain/")
        assert response.status_code == 301
        assert response.headers["location"].startswith("https://")


def test_trusted_proxy_headers(settings_override):
    clear_patterns()

    async def info(request):
        return JsonResponse(
            {
                "client": request.client,
                "scheme": request.scheme,
                "secure": request.is_secure(),
                "absolute": request.build_absolute_uri("/next/"),
                "full_path": request.get_full_path(),
            }
        )

    def build():
        return Application(urlpatterns=[path("info/", info, name="info")])

    settings_override(TRUST_PROXY_HEADERS=False, TRUSTED_PROXIES=[])
    with Client(build()) as client:
        data = _json(client.get("/info/?a=1"))
        assert data["client"].startswith("127.0.0.1")
        assert data["scheme"] == "http"
        assert data["secure"] is False
        assert data["full_path"] == "/info/?a=1"
        assert data["absolute"].startswith("http://127.0.0.1:")

    settings_override(
        TRUST_PROXY_HEADERS=True,
        TRUSTED_PROXIES=["127.0.0.1"],
    )
    with Client(build()) as client:
        data = _json(
            client.get(
                "/info/",
                headers={
                    "x-forwarded-for": "203.0.113.9, 10.0.0.1",
                    "x-forwarded-proto": "https",
                },
            )
        )
        assert data["client"] == "203.0.113.9"
        assert data["scheme"] == "https"
        assert data["secure"] is True
        assert data["absolute"].startswith("https://")

    settings_override(TRUSTED_PROXIES=[])
    with Client(build()) as client:
        data = _json(
            client.get("/info/", headers={"x-forwarded-for": "203.0.113.9"})
        )
        assert data["client"].startswith("127.0.0.1")


def test_cors_allowed_origins_and_preflight(settings_override):
    clear_patterns()
    settings_override(
        CORS_ALLOWED_ORIGINS=["https://ok.test"],
        CORS_ALLOW_ALL_ORIGINS=False,
        CORS_ALLOW_CREDENTIALS=True,
        CORS_MAX_AGE=120,
    )

    async def plain(request):
        return HttpResponse("plain")

    app = Application(
        urlpatterns=[path("plain/", plain, name="plain")],
        middleware=[CorsMiddleware],
    )
    with Client(app) as client:
        response = client.get("/plain/", headers={"origin": "https://ok.test"})
        assert response.headers["access-control-allow-origin"] == "https://ok.test"
        assert response.headers["access-control-allow-credentials"] == "true"
        assert "Origin" in response.headers["vary"]

        response = client.get("/plain/", headers={"origin": "https://bad.test"})
        assert "access-control-allow-origin" not in response.headers

        response = client.options(
            "/plain/",
            headers={
                "origin": "https://ok.test",
                "access-control-request-method": "POST",
            },
        )
        assert response.status_code == 204
        assert "POST" in response.headers["access-control-allow-methods"]
        assert response.headers["access-control-allow-headers"] == "*"
        assert response.headers["access-control-max-age"] == "120"


def test_cors_allow_all_origins(settings_override):
    clear_patterns()
    settings_override(CORS_ALLOW_ALL_ORIGINS=True, CORS_ALLOWED_ORIGINS=[])

    async def plain(request):
        return HttpResponse("plain")

    app = Application(
        urlpatterns=[path("plain/", plain, name="plain")],
        middleware=[CorsMiddleware],
    )
    with Client(app) as client:
        response = client.get("/plain/", headers={"origin": "https://any.test"})
        assert response.headers["access-control-allow-origin"] == "https://any.test"


def test_csrf_requires_matching_token(settings_override):
    clear_patterns()
    settings_override(SECRET_KEY="csrf-secret", CSRF_EXEMPT_PATHS=["/exempt/"])

    async def form(request):
        return JsonResponse({"ok": True})

    async def token(request):
        return JsonResponse({"token": get_token(request)})

    app = Application(
        urlpatterns=[
            path("form/", form, name="form"),
            path("exempt/", form, name="exempt"),
            path("token/", token, name="token"),
        ],
        middleware=[CsrfMiddleware],
    )
    with Client(app) as client:
        assert client.get("/form/").status_code == 200
        assert client.post("/form/", data={"a": "b"}).status_code == 403

        token_value = _json(client.get("/token/"))["token"]
        response = client.post(
            "/form/",
            data={"a": "b"},
            headers={"x-csrftoken": token_value},
        )
        assert response.status_code == 200

        response = client.post(
            "/form/",
            data={"a": "b"},
            headers={"x-csrftoken": "wrong"},
        )
        assert response.status_code == 403

        assert client.post("/exempt/", data={"a": "b"}).status_code == 200


def test_csrf_accepts_form_field_token(settings_override):
    clear_patterns()
    settings_override(SECRET_KEY="csrf-secret")

    async def form(request):
        return JsonResponse({"ok": True})

    async def token(request):
        return JsonResponse({"token": get_token(request)})

    app = Application(
        urlpatterns=[path("form/", form, name="form"), path("token/", token, name="token")],
        middleware=[CsrfMiddleware],
    )
    with Client(app) as client:
        token_value = _json(client.get("/token/"))["token"]
        response = client.post(
            "/form/",
            data={"csrfmiddlewaretoken": token_value},
        )
        assert response.status_code == 200


def test_signed_cookie_roundtrip(settings_override):
    settings_override(SECRET_KEY="signed-secret")
    token = dumps({"user": 1})
    assert loads(token) == {"user": 1}

    signed = sign_object({"user": 2})
    assert unsign_object(signed) == {"user": 2}
    assert unsign_object(signed, max_age=3600) == {"user": 2}
    with pytest.raises(ValueError):
        unsign_object(signed, max_age=0)

    with pytest.raises(ValueError):
        loads(token + "tampered")


def test_signed_cookie_requires_secret(settings_override):
    settings_override(SECRET_KEY="")
    with pytest.raises(RuntimeError):
        dumps("x")
