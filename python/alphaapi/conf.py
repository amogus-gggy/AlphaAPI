"""Project settings.

AlphaAPI follows Django's settings convention: a module named by the
``ALPHAAPI_SETTINGS_MODULE`` environment variable (or passed explicitly) holds
uppercase settings, and application code reads them through the ``settings``
object.

Example::

    # project/settings.py
    DEBUG = True
    ROOT_URLCONF = "project.urls"
    MIDDLEWARE = ["project.middleware.TimingMiddleware"]

    # code
    from alphaapi.conf import settings
    print(settings.DEBUG)
"""
from __future__ import annotations

import importlib
import os
from typing import Any


DEFAULTS: dict[str, Any] = {
    "DEBUG": False,
    "SECRET_KEY": "",
    "ALLOWED_HOSTS": ["*"],
    "INSTALLED_APPS": [],
    "MIDDLEWARE": [],
    "ROOT_URLCONF": None,
    "DEFAULT_CHARSET": "utf-8",
    "MAX_BODY_SIZE": 16 * 1024 * 1024,
    "ACCESS_LOG": False,
    "ACCESS_LOG_JSON": False,
    "TITLE": "AlphaAPI",
    "VERSION": "0.1.0",
    # Proxy / security
    "TRUST_PROXY_HEADERS": False,
    "TRUSTED_PROXIES": [],
    "SECURE_PROXY_SSL_HEADER": "x-forwarded-proto",
    "SECURE_SSL_REDIRECT": False,
    "SECURITY_HEADERS": True,
    "SECURE_HSTS_SECONDS": 0,
    "SECURE_HSTS_INCLUDE_SUBDOMAINS": False,
    "SECURE_REFERRER_POLICY": "same-origin",
    "X_FRAME_OPTIONS": "DENY",
    # Runtime limits
    "REQUEST_TIMEOUT": None,
    "MAX_CONCURRENT_REQUESTS": None,
    "OFFLOAD_SYNC_VIEWS": False,
    # HTTP/2 tuning
    "HTTP2_MAX_CONCURRENT_STREAMS": None,
    "HTTP2_INITIAL_WINDOW_SIZE": None,
    "HTTP2_KEEP_ALIVE_INTERVAL": None,
    "HTTP2_KEEP_ALIVE_TIMEOUT": None,
    # Static files / templates
    "STATIC_URL": "/static/",
    "STATIC_ROOT": None,
    "TEMPLATES_DIR": None,
    "APPEND_SLASH": False,
    # OpenAPI
    "ENABLE_OPENAPI": False,
    "OPENAPI_URL": "/openapi.json",
    "DOCS_URL": "/docs",
    "OPENAPI_TITLE": None,
    # CORS
    "CORS_ALLOWED_ORIGINS": [],
    "CORS_ALLOW_ALL_ORIGINS": False,
    "CORS_ALLOW_CREDENTIALS": False,
    "CORS_ALLOWED_HEADERS": ["*"],
    "CORS_ALLOWED_METHODS": ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    "CORS_MAX_AGE": 600,
    # Sessions
    "SESSION_COOKIE_NAME": "sessionid",
    "SESSION_COOKIE_AGE": 60 * 60 * 24 * 14,
    "SESSION_COOKIE_SECURE": False,
    "SESSION_COOKIE_HTTPONLY": True,
    "SESSION_COOKIE_SAMESITE": "lax",
    "SESSION_ENGINE": "memory",
    # CSRF
    "CSRF_COOKIE_NAME": "csrftoken",
    "CSRF_HEADER_NAME": "x-csrftoken",
    "CSRF_COOKIE_SECURE": False,
    "CSRF_COOKIE_HTTPONLY": False,
    "CSRF_COOKIE_SAMESITE": "lax",
    "CSRF_TRUSTED_ORIGINS": [],
    "CSRF_EXEMPT_PATHS": [],
    # Authentication
    "AUTH_USER_RESOLVER": None,
}


class Settings:
    """A lazy, attribute-based view over project settings.

    Settings are read from a module when first accessed, so importing
    ``alphaapi`` never has the side effect of importing the project.
    """

    def __init__(self) -> None:
        object.__setattr__(self, "_values", dict(DEFAULTS))
        object.__setattr__(self, "_loaded", False)
        object.__setattr__(self, "_module", None)

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        self._ensure_loaded()
        try:
            return self._values[name]
        except KeyError as error:
            raise AttributeError(f"setting {name!r} is not configured") from error

    def __setattr__(self, name: str, value: Any) -> None:
        if name.startswith("_"):
            object.__setattr__(self, name, value)
        else:
            self._values[name] = value

    def __dir__(self) -> list[str]:
        self._ensure_loaded()
        return sorted(self._values)

    def configure(self, **options: Any) -> None:
        """Update settings directly (mostly useful for small scripts/tests)."""
        for key, value in options.items():
            if not key.isupper():
                raise TypeError(f"setting names must be uppercase, got {key!r}")
            self._values[key] = value
        object.__setattr__(self, "_loaded", True)

    def configure_from_module(self, module_path: str) -> None:
        """Load settings from an importable module."""
        module = importlib.import_module(module_path)
        object.__setattr__(self, "_module", module)
        for key in dir(module):
            if key.isupper():
                self._values[key] = getattr(module, key)
        object.__setattr__(self, "_loaded", True)

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        module_path = os.environ.get("ALPHAAPI_SETTINGS_MODULE")
        if module_path:
            self.configure_from_module(module_path)
        else:
            object.__setattr__(self, "_loaded", True)


settings = Settings()


__all__ = ["settings", "Settings", "DEFAULTS"]
