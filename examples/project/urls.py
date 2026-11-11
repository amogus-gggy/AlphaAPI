"""Example URLconf."""
from __future__ import annotations

from alphaapi import include, path

from . import views

api_patterns = [
    path("health/", views.health, name="health"),
]

urlpatterns = [
    path("", views.index, name="index"),
    path("items/<int:item_id>/", views.item, name="item"),
    path("items/<int:item_id>/detail/", views.ItemDetailView.as_view(), name="item-detail"),
    path("api/", include((api_patterns, "api"))),
]
