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
    "TITLE": "AlphaAPI",
    "VERSION": "0.1.0",
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
