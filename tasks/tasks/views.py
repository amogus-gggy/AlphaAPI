from __future__ import annotations

from typing import Any

from alphaapi import HTTPException, HttpResponse, JsonResponse, View

from .store import Task, store

def _payload(request: Any, *, partial: bool = False) -> dict[str, Any]:
    try:
        data = request.json()
    except ValueError:
        raise HTTPException(400, "Request body must be valid JSON") from None

    if not isinstance(data, dict):
        raise HTTPException(400, "Request body must be a JSON object")

    if not partial or "title" in data:
        title = data.get("title")
        if not isinstance(title, str) or not title.strip():
            raise HTTPException(400, "title must be a non-empty string")
        data["title"] = title.strip()

    if "done" in data and not isinstance(data["done"], bool):
        raise HTTPException(400, "done must be a boolean")

    if "tags" in data:
        tags = data["tags"]
        if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
            raise HTTPException(400, "tags must be a list of strings")

    return data

async def task_collection(request):
    if request.method == "GET":
        raw_done = request.GET.get("done")
        done = None if raw_done is None else raw_done.lower() in {"1", "true", "yes"}
        tag = request.GET.get("tag")
        tasks = store.list(done=done, tag=tag)
        return JsonResponse({"items": [task.to_dict() for task in tasks]})

    data = _payload(request)
    task = store.create(
        title=data["title"],
        done=data.get("done", False),
        tags=data.get("tags", []),
    )
    return JsonResponse(task.to_dict(), status=201)

class TaskView(View):
    async def get(self, request, task_id: int):
        task = store.get(task_id)
        if task is None:
            raise HTTPException(404, f"Task {task_id} was not found")
        return JsonResponse(task.to_dict())

    async def put(self, request, task_id: int):
        task = store.get(task_id)
        if task is None:
            raise HTTPException(404, f"Task {task_id} was not found")
        data = _payload(request)
        store.replace(
            task,
            title=data["title"],
            done=data.get("done", False),
            tags=data.get("tags", []),
        )
        return JsonResponse(task.to_dict())

    async def patch(self, request, task_id: int):
        task = store.get(task_id)
        if task is None:
            raise HTTPException(404, f"Task {task_id} was not found")
        data = _payload(request, partial=True)
        store.replace(
            task,
            title=data.get("title", task.title),
            done=data.get("done", task.done),
            tags=data.get("tags", task.tags),
        )
        return JsonResponse(task.to_dict())

    async def delete(self, request, task_id: int):
        if not store.delete(task_id):
            raise HTTPException(404, f"Task {task_id} was not found")
        return HttpResponse(b"", status=204)
