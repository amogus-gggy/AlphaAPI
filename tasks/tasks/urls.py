from __future__ import annotations

from alphaapi import path

from . import views

urlpatterns = [
    path("tasks/", views.task_collection, name="task-collection"),
    path("tasks/<int:task_id>/", views.TaskView.as_view(), name="task-detail"),
]
