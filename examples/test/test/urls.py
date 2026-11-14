"""URLconf for the test project."""
from __future__ import annotations

from alphaapi import path

from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path("health/", views.health, name="health"),
]
