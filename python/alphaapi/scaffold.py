"""Project and app scaffolding used by ``alphaapi startproject/startapp``."""
from __future__ import annotations

import re
import secrets
from pathlib import Path

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class ScaffoldError(Exception):
    """Raised when a project or app cannot be created."""


def _validate_name(name: str) -> None:
    if not _IDENTIFIER.match(name):
        raise ScaffoldError(
            f"invalid name {name!r}: use a Python identifier "
            "(letters, digits and underscores, not starting with a digit)"
        )


def _camel_case(name: str) -> str:
    return "".join(part.capitalize() for part in name.split("_"))


def _write(path: Path, content: str, *, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(path.stat().st_mode | 0o111)


def _prepare_destination(destination: Path, name: str) -> None:
    if destination.exists() and not destination.is_dir():
        raise ScaffoldError(f"{destination} already exists and is not a directory")
    if destination.exists() and any(destination.iterdir()):
        raise ScaffoldError(f"{destination} already exists and is not empty")
    destination.mkdir(parents=True, exist_ok=True)
    _validate_name(name)


PROJECT_MANAGE = '''#!/usr/bin/env python
"""Manage the {name} AlphaAPI project."""
from __future__ import annotations

import sys

from alphaapi.cli import main

if __name__ == "__main__":
    main(["runserver", "{name}.app:app", *sys.argv[1:]])
'''

PROJECT_APP = '''"""Application entry point."""
from __future__ import annotations

from alphaapi import Application

app = Application(settings_module=f"{__package__}.settings")
'''

PROJECT_SETTINGS = '''"""Settings for the {name} project."""

DEBUG = True
SECRET_KEY = "{secret_key}"
ROOT_URLCONF = "{name}.urls"
INSTALLED_APPS: list[str] = []
MIDDLEWARE: list[str] = []
TITLE = "{name}"
VERSION = "0.1.0"
ACCESS_LOG = True
'''

PROJECT_URLS = '''"""URLconf for the {name} project."""
from __future__ import annotations

from alphaapi import path

from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path("health/", views.health, name="health"),
]
'''

PROJECT_VIEWS = '''"""Views for the __PROJECT_NAME__ project."""
from __future__ import annotations

from alphaapi import HttpResponse
from alphaapi.welcome import welcome_page


async def index(request):
    return HttpResponse(welcome_page("__PROJECT_NAME__"))


async def health(request):
    return HttpResponse("ok", content_type="text/plain; charset=utf-8")
'''

APP_INIT = '''"""{name} application package."""
'''

APP_APPS = '''"""Configuration for the {name} app."""
from __future__ import annotations

from alphaapi import AppConfig


class {class_name}Config(AppConfig):
    name = "{name}"
    verbose_name = "{name}"
'''

APP_URLS = '''"""{name} URLconf."""
from __future__ import annotations

from alphaapi import path

from . import views

app_name = "{name}"

urlpatterns = [
    path("", views.index, name="index"),
]
'''

APP_VIEWS = '''"""{name} views."""
from __future__ import annotations

from alphaapi import JsonResponse


async def index(request):
    return JsonResponse({{"app": "{name}", "ok": True}})
'''


def startproject(name: str, directory: str | Path | None = None) -> Path:
    """Create a new AlphaAPI project and return its root directory."""
    _validate_name(name)
    destination = Path(directory) if directory else Path.cwd() / name
    _prepare_destination(destination, name)

    package = destination / name
    _write(destination / "manage.py", PROJECT_MANAGE.format(name=name), executable=True)
    _write(package / "__init__.py", "")
    _write(package / "app.py", PROJECT_APP)
    _write(
        package / "settings.py",
        PROJECT_SETTINGS.format(
            name=name,
            secret_key=secrets.token_urlsafe(50),
        ),
    )
    _write(package / "urls.py", PROJECT_URLS.format(name=name))
    _write(package / "views.py", PROJECT_VIEWS.replace("__PROJECT_NAME__", name))
    return destination


def startapp(name: str, directory: str | Path | None = None) -> Path:
    """Create a new reusable app and return its directory."""
    _validate_name(name)
    destination = (Path(directory) if directory else Path.cwd()) / name
    _prepare_destination(destination, name)

    _write(destination / "__init__.py", APP_INIT.format(name=name))
    _write(
        destination / "apps.py",
        APP_APPS.format(name=name, class_name=_camel_case(name)),
    )
    _write(destination / "urls.py", APP_URLS.format(name=name))
    _write(destination / "views.py", APP_VIEWS.format(name=name))
    return destination


__all__ = ["ScaffoldError", "startproject", "startapp"]
