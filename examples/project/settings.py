"""Example project settings."""

_app_package = __name__.rsplit(".", 1)[0]

DEBUG = True
SECRET_KEY = "dev-only-change-me"
ROOT_URLCONF = f"{_app_package}.urls"
INSTALLED_APPS: list[str] = []
MIDDLEWARE = [f"{_app_package}.middleware.TimingMiddleware"]
TITLE = "AlphaAPI project"
VERSION = "0.2.0b"
ACCESS_LOG = True
