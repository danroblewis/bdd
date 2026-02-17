import json
import fcntl
from pathlib import Path

from .models import Task


class TaskStore:
    def __init__(self, path: str | Path | None = None):
        if path is None:
            path = Path.home() / ".taskboard.json"
        self.path = Path(path)
        self._ensure_file()

    def _ensure_file(self):
        if not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._write_data({"next_id": 1, "tasks": []})

    def _read_data(self) -> dict:
        with open(self.path, "r") as f:
            fcntl.flock(f, fcntl.LOCK_SH)
            try:
                return json.load(f)
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    def _write_data(self, data: dict):
        with open(self.path, "w") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                json.dump(data, f, indent=2)
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    def add(self, title: str, priority: int = 1, tags: list[str] | None = None) -> Task:
        data = self._read_data()
        task = Task(
            id=data["next_id"],
            title=title,
            priority=priority,
            tags=tags or [],
        )
        data["tasks"].append(task.to_dict())
        data["next_id"] += 1
        self._write_data(data)
        return task

    def get(self, task_id: int) -> Task | None:
        data = self._read_data()
        for t in data["tasks"]:
            if t["id"] == task_id:
                return Task.from_dict(t)
        return None

    def list(self, status: str | None = None) -> list[Task]:
        data = self._read_data()
        tasks = [Task.from_dict(t) for t in data["tasks"]]
        if status is not None:
            tasks = [t for t in tasks if t.status == status]
        return tasks

    def update(self, task_id: int, **fields) -> Task | None:
        data = self._read_data()
        for i, t in enumerate(data["tasks"]):
            if t["id"] == task_id:
                t.update(fields)
                data["tasks"][i] = t
                self._write_data(data)
                return Task.from_dict(t)
        return None

    def remove(self, task_id: int) -> bool:
        data = self._read_data()
        original_len = len(data["tasks"])
        data["tasks"] = [t for t in data["tasks"] if t["id"] != task_id]
        if len(data["tasks"]) < original_len:
            self._write_data(data)
            return True
        return False
