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
