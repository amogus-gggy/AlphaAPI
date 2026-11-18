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


def package_version() -> str:
    """Return the installed distribution version (or the source fallback)."""
    try:
        from importlib.metadata import version

        return version("alphaapi")
    except Exception:  # pragma: no cover - only hit for source checkouts
        return "0.1.0"


def load_module_settings(module_path: str) -> dict[str, Any]:
    """Import ``module_path`` and return its uppercase attributes."""
    module = importlib.import_module(module_path)
    return {key: getattr(module, key) for key in dir(module) if key.isupper()}


DEFAULTS: dict[str, Any] = {
    "DEBUG": False,
    "SECRET_KEY": "",
    "ALLOWED_HOSTS": ["*"],
    "INSTALLED_APPS": [],
    "MIDDLEWARE": [],
    "ROOT_URLCONF": None,
    "DEFAULT_CHARSET": "utf-8",
    "MAX_BODY_SIZE": 16 * 1024 * 1024,
    "MAX_UPLOAD_SIZE": 16 * 1024 * 1024,
    "ACCESS_LOG": False,
    "ACCESS_LOG_JSON": False,
    "TITLE": "AlphaAPI",
    "VERSION": package_version(),
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


class ScopedSettings:
    """A settings view with per-application overrides.

    Reads fall through to the process-wide :data:`settings` object, while
    writes are kept local to this view.  This lets several ``Application``
    instances coexist without one silently mutating another's configuration:
    values changed later on the global object are still visible unless this
    application explicitly overrode them.
    """

    def __init__(
        self, base: Settings | None = None, overrides: dict[str, Any] | None = None
    ) -> None:
        object.__setattr__(self, "_base", base if base is not None else settings)
        object.__setattr__(self, "_overrides", dict(overrides or {}))

    def __getattr__(self, name: str) -> Any:
        overrides = object.__getattribute__(self, "_overrides")
        if name in overrides:
            return overrides[name]
        return getattr(object.__getattribute__(self, "_base"), name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name.startswith("_"):
            object.__setattr__(self, name, value)
        else:
            self._overrides[name] = value

    def __dir__(self) -> list[str]:
        return sorted(set(dir(self._base)) | set(self._overrides))

    def configure(self, **options: Any) -> None:
        for key, value in options.items():
            if not key.isupper():
                raise TypeError(f"setting names must be uppercase, got {key!r}")
            self._overrides[key] = value

    def configure_from_module(self, module_path: str) -> None:
        self._overrides.update(load_module_settings(module_path))

    @property
    def overrides(self) -> dict[str, Any]:
        """A copy of the values that differ from the global settings."""
        return dict(self._overrides)


settings = Settings()


__all__ = [
    "settings",
    "Settings",
    "ScopedSettings",
    "DEFAULTS",
    "load_module_settings",
    "package_version",
]
