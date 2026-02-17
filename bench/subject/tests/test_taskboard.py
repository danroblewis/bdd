import json
import pytest
from pathlib import Path

from taskboard.models import Task
from taskboard.store import TaskStore
from taskboard.cli import main
from taskboard.display import format_task, format_table


@pytest.fixture
def store_path(tmp_path):
    return tmp_path / "tasks.json"


@pytest.fixture
def store(store_path):
    return TaskStore(store_path)


class TestModels:
    def test_task_defaults(self):
        t = Task(id=1, title="Test")
        assert t.status == "todo"
        assert t.priority == 1
        assert t.tags == []

    def test_task_roundtrip(self):
        t = Task(id=1, title="Test", priority=2, tags=["work"])
        d = t.to_dict()
        t2 = Task.from_dict(d)
        assert t2.id == t.id
        assert t2.title == t.title
        assert t2.priority == t.priority
        assert t2.tags == t.tags


class TestStore:
    def test_add_and_get(self, store):
        task = store.add("Buy milk")
        assert task.id == 1
        assert task.title == "Buy milk"
        fetched = store.get(1)
        assert fetched is not None
        assert fetched.title == "Buy milk"

    def test_auto_increment_id(self, store):
        t1 = store.add("First")
        t2 = store.add("Second")
        assert t1.id == 1
        assert t2.id == 2

    def test_list_all(self, store):
        store.add("A")
        store.add("B")
        tasks = store.list()
        assert len(tasks) == 2

    def test_list_by_status(self, store):
        store.add("A")
        store.add("B")
        store.update(1, status="done")
        todo = store.list(status="todo")
        done = store.list(status="done")
        assert len(todo) == 1
        assert len(done) == 1

    def test_update(self, store):
        store.add("Original")
        updated = store.update(1, title="Changed")
        assert updated is not None
        assert updated.title == "Changed"

    def test_update_nonexistent(self, store):
        assert store.update(99, title="X") is None

    def test_remove(self, store):
        store.add("Temp")
        assert store.remove(1) is True
        assert store.get(1) is None

    def test_remove_nonexistent(self, store):
        assert store.remove(99) is False

    def test_add_with_tags(self, store):
        task = store.add("Tagged", tags=["work", "urgent"])
        assert task.tags == ["work", "urgent"]

    def test_add_with_priority(self, store):
        task = store.add("Important", priority=3)
        assert task.priority == 3


class TestCLI:
    def test_add_command(self, store_path, capsys):
        ret = main(["--store", str(store_path), "add", "My task"])
        assert ret == 0
        out = capsys.readouterr().out
        assert "Added task 1" in out

    def test_list_command(self, store_path, capsys):
        main(["--store", str(store_path), "add", "Task one"])
        ret = main(["--store", str(store_path), "list"])
        assert ret == 0
        out = capsys.readouterr().out
        assert "Task one" in out

    def test_done_command(self, store_path, capsys):
        main(["--store", str(store_path), "add", "Finish this"])
        ret = main(["--store", str(store_path), "done", "1"])
        assert ret == 0
        out = capsys.readouterr().out
        assert "Marked task 1 as done" in out

    def test_done_already_done(self, store_path, capsys):
        main(["--store", str(store_path), "add", "Already done task"])
        main(["--store", str(store_path), "done", "1"])
        ret = main(["--store", str(store_path), "done", "1"])
        assert ret == 0
        out = capsys.readouterr().out
        assert "already done" in out

    def test_remove_command(self, store_path, capsys):
        main(["--store", str(store_path), "add", "Temp task"])
        ret = main(["--store", str(store_path), "remove", "1"])
        assert ret == 0
        out = capsys.readouterr().out
        assert "Removed task 1" in out

    def test_edit_title(self, store_path, capsys):
        main(["--store", str(store_path), "add", "Old title"])
        ret = main(["--store", str(store_path), "edit", "1", "--title", "New title"])
        assert ret == 0

    def test_edit_nothing(self, store_path, capsys):
        main(["--store", str(store_path), "add", "Task"])
        ret = main(["--store", str(store_path), "edit", "1"])
        assert ret == 2


class TestDisplay:
    def test_format_task_basic(self):
        t = Task(id=1, title="Test task", priority=1)
        s = format_task(t)
        assert "1" in s
        assert "Test task" in s

    def test_format_table_empty(self):
        assert format_table([]) == "No tasks."

    def test_format_table_multiple(self):
        tasks = [
            Task(id=1, title="A"),
            Task(id=2, title="B"),
        ]
        s = format_table(tasks)
        assert "A" in s
        assert "B" in s
