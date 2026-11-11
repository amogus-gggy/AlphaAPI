"""Application registry.

Django projects list reusable apps in ``INSTALLED_APPS``.  AlphaAPI keeps the
same idea, without models or an ORM: an app is a package that may expose an
``AppConfig``, URL patterns, middleware, or startup hooks.
"""
from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any, Iterable


class AppConfig:
    """Metadata and lifecycle hooks for a reusable application."""

    name: str = ""
    verbose_name: str | None = None
    path: str | Path | None = None

    def __init__(self, name: str = "", module: Any = None) -> None:
        if name:
            self.name = name
        self.module = module
        if self.path is None:
            if module is not None and getattr(module, "__file__", None):
                self.path = Path(module.__file__).resolve().parent
            elif self.name:
                try:
                    self.path = Path(
                        importlib.import_module(self.name).__file__
                    ).resolve().parent
                except (ImportError, TypeError):
                    self.path = None

    @property
    def label(self) -> str:
        return self.name.rsplit(".", 1)[-1]

    def ready(self) -> None:
        """Override to run setup code once the app registry is populated."""

    def __repr__(self) -> str:
        return f"<AppConfig {self.name!r}>"


class AppRegistry:
    def __init__(self) -> None:
        self.app_configs: dict[str, AppConfig] = {}
        self._populated = False

    def populate(self, installed_apps: Iterable[Any] | None = None) -> None:
        if self._populated:
            return
        for entry in installed_apps or []:
            self.register(entry)
        for config in self.app_configs.values():
            config.ready()
        self._populated = True

    def register(self, entry: Any) -> AppConfig:
        config = self._load_entry(entry)
        self.app_configs[config.label] = config
        return config

    def get(self, label: str) -> AppConfig | None:
        return self.app_configs.get(label)

    def _load_entry(self, entry: Any) -> AppConfig:
        if isinstance(entry, AppConfig):
            return entry
        if isinstance(entry, type) and issubclass(entry, AppConfig):
            return entry()
        if not isinstance(entry, str):
            raise TypeError(f"invalid INSTALLED_APPS entry: {entry!r}")

        # "package.apps.SomeConfig" points at a class; "package" points at a
        # module that may expose `default_app_config`.
        if "." in entry:
            module_name, _, attribute = entry.rpartition(".")
            try:
                module = importlib.import_module(module_name)
            except ImportError:
                module = importlib.import_module(entry)
            else:
                candidate = getattr(module, attribute, None)
                if isinstance(candidate, type) and issubclass(candidate, AppConfig):
                    return candidate()

        module = importlib.import_module(entry)
        config_class = getattr(module, "default_app_config", None)
        if isinstance(config_class, type) and issubclass(config_class, AppConfig):
            return config_class()
        return AppConfig(name=entry, module=module)

    def ready(self) -> bool:
        return self._populated


apps = AppRegistry()


__all__ = ["AppConfig", "AppRegistry", "apps"]
