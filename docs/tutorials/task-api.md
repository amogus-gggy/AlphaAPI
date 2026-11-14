# Build a task API

In this tutorial you will build a small JSON API for managing tasks. It supports
listing, creating, reading, updating, and deleting tasks, plus query filters and
basic validation.

The data is kept in memory so the tutorial stays focused on AlphaAPI. Swapping
the store for a database is intentionally left to you.

## 1. Create the project

```bash
alphaapi startproject tasks
cd tasks
```

Start the development server once to make sure everything works:

```bash
python manage.py --port 8000
```

Stop it with ++ctrl+c++ and open the generated files in your editor.

## 2. Add the task store

Create `tasks/store.py`:

```python title="tasks/store.py"
from __future__ import annotations

from dataclasses import asdict, dataclass, field

@dataclass
class Task:
    id: int
    title: str
    done: bool = False
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

class TaskStore:
    def __init__(self) -> None:
        self._items: dict[int, Task] = {}
        self._next_id = 1

    def list(self, *, done: bool | None = None, tag: str | None = None) -> list[Task]:
        items = list(self._items.values())
        if done is not None:
            items = [task for task in items if task.done is done]
        if tag is not None:
            items = [task for task in items if tag in task.tags]
        return items

    def get(self, task_id: int) -> Task | None:
        return self._items.get(task_id)

    def create(self, title: str, done: bool = False, tags: list[str] | None = None) -> Task:
        task = Task(
            id=self._next_id,
            title=title,
            done=done,
            tags=list(tags or []),
        )
        self._items[task.id] = task
        self._next_id += 1
        return task

    def replace(self, task: Task, *, title: str, done: bool, tags: list[str]) -> Task:
        task.title = title
        task.done = done
        task.tags = list(tags)
        return task

    def delete(self, task_id: int) -> bool:
        return self._items.pop(task_id, None) is not None

store = TaskStore()
```

## 3. Write the views

Replace `tasks/views.py` with:

```python title="tasks/views.py"
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
```

`View` handles `HEAD`, `OPTIONS`, and `405 Method Not Allowed` for you. A
`HEAD` request to a task URL falls back to `GET`; a method with no matching
handler returns `405` with an `Allow` header.

## 4. Wire up the URLs

Replace `tasks/urls.py`:

```python title="tasks/urls.py"
from __future__ import annotations

from alphaapi import path

from . import views

urlpatterns = [
    path("tasks/", views.task_collection, name="task-collection"),
    path("tasks/<int:task_id>/", views.TaskView.as_view(), name="task-detail"),
]
```

The `<int:task_id>` converter is validated by the Rust router. A request such as
`/tasks/abc/` returns `404` without invoking Python.

## 5. Run it

```bash
python manage.py --port 8000
```

Create a task:

```bash
curl -X POST http://127.0.0.1:8000/tasks/ \
  -H 'content-type: application/json' \
  -d '{"title":"Write docs","tags":["docs"]}'
```

```json
{"id":1,"title":"Write docs","done":false,"tags":["docs"]}
```

List tasks:

```bash
curl http://127.0.0.1:8000/tasks/
curl 'http://127.0.0.1:8000/tasks/?done=false&tag=docs'
```

Update a task:

```bash
curl -X PATCH http://127.0.0.1:8000/tasks/1/ \
  -H 'content-type: application/json' \
  -d '{"done":true}'
```

Delete a task:

```bash
curl -X DELETE http://127.0.0.1:8000/tasks/1/
# HTTP 204 No Content
```

Validation failures look like this:

```json
{"detail":"title must be a non-empty string"}
```

## 6. Add a health check

A small health endpoint is useful for deployments:

```python title="tasks/views.py"
async def health(request):
    return JsonResponse({"status": "ok"})
```

```python title="tasks/urls.py"
from alphaapi import path

from . import views

urlpatterns = [
    path("health/", views.health, name="health"),
    path("tasks/", views.task_collection, name="task-collection"),
    path("tasks/<int:task_id>/", views.TaskView.as_view(), name="task-detail"),
]
```

## 7. Optional: test it with pytest

Install the development tools:

```bash
pip install pytest
```

Create `test_tasks.py` in the project root:

```python title="test_tasks.py"
from __future__ import annotations

import http.client
import json
import socket
import threading
import time

import pytest

from tasks.app import app

def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]

@pytest.fixture(scope="module")
def server():
    port = free_port()
    thread = threading.Thread(
        target=app.run,
        kwargs={"host": "127.0.0.1", "port": port},
        daemon=True,
    )
    thread.start()

    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                break
        except OSError:
            time.sleep(0.02)
    else:
        pytest.fail("server did not start")

    yield port
    app.stop()
    thread.join(timeout=10)

def request(port: int, method: str, path: str, body: dict | None = None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        payload = None if body is None else json.dumps(body).encode()
        headers = {} if body is None else {"content-type": "application/json"}
        connection.request(method, path, body=payload, headers=headers)
        response = connection.getresponse()
        data = response.read()
        return response.status, data
    finally:
        connection.close()

def test_create_and_read(server):
    status, body = request(server, "POST", "/tasks/", {"title": "Test"})
    assert status == 201
    task = json.loads(body)
    assert task["title"] == "Test"

    status, body = request(server, "GET", f"/tasks/{task['id']}/")
    assert status == 200
    assert json.loads(body)["id"] == task["id"]

def test_missing_task(server):
    status, body = request(server, "GET", "/tasks/999/")
    assert status == 404
    assert "not found" in json.loads(body)["detail"]
```

Run it:

```bash
pytest -q
```

## What you built

- A JSON API with create, read, update, patch, and delete operations.
- Typed path parameters validated before Python runs.
- Query filtering with `request.GET`.
- Class-based view dispatch with automatic `HEAD`, `OPTIONS`, and `405`.
- `HTTPException` for consistent JSON error responses.

## Next steps

- Replace `TaskStore` with a database or an async HTTP client.
- Add pagination with `request.GET.get("limit")` and an `offset` parameter.
- Add API-key middleware in the **[blog tutorial](blog.md)**.
- Learn how to deploy the service in the
  **[deployment guide](deployment.md)**.
