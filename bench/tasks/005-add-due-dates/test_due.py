import pytest
from datetime import date, timedelta
from taskboard.cli import main
from taskboard.store import TaskStore


@pytest.fixture
def store_path(tmp_path):
    return tmp_path / "tasks.json"


def _yesterday():
    return (date.today() - timedelta(days=1)).isoformat()


def _tomorrow():
    return (date.today() + timedelta(days=1)).isoformat()


def _next_week():
    return (date.today() + timedelta(days=7)).isoformat()


class TestAddWithDueDate:
    def test_add_with_due_date(self, store_path, capsys):
        ret = main(["--store", str(store_path), "add", "Task with due", "--due", _tomorrow()])
        assert ret == 0
        store = TaskStore(store_path)
        task = store.get(1)
        assert task.due_date == _tomorrow()

    def test_add_without_due_date(self, store_path, capsys):
        ret = main(["--store", str(store_path), "add", "No due date"])
        assert ret == 0
        store = TaskStore(store_path)
        task = store.get(1)
        assert task.due_date is None


class TestEditDueDate:
    def test_edit_set_due_date(self, store_path, capsys):
        main(["--store", str(store_path), "add", "Task"])
        ret = main(["--store", str(store_path), "edit", "1", "--due", _tomorrow()])
        assert ret == 0
        store = TaskStore(store_path)
        task = store.get(1)
        assert task.due_date == _tomorrow()

    def test_edit_remove_due_date(self, store_path, capsys):
        main(["--store", str(store_path), "add", "Task", "--due", _tomorrow()])
        ret = main(["--store", str(store_path), "edit", "1", "--due", "none"])
        assert ret == 0
        store = TaskStore(store_path)
        task = store.get(1)
        assert task.due_date is None


class TestListSortByDue:
    def test_list_due_sorts_by_date(self, store_path, capsys):
        main(["--store", str(store_path), "add", "Later", "--due", _next_week()])
        main(["--store", str(store_path), "add", "Sooner", "--due", _tomorrow()])
        main(["--store", str(store_path), "add", "No date"])
        ret = main(["--store", str(store_path), "list", "--due"])
        assert ret == 0
        out = capsys.readouterr().out
        lines = [l for l in out.strip().split("\n") if l.strip()]
        # Sooner should come before Later, No date should be last
        sooner_idx = next(i for i, l in enumerate(lines) if "Sooner" in l)
        later_idx = next(i for i, l in enumerate(lines) if "Later" in l)
        nodate_idx = next(i for i, l in enumerate(lines) if "No date" in l)
        assert sooner_idx < later_idx < nodate_idx


class TestOverdueDisplay:
    def test_overdue_task_shows_marker(self, store_path, capsys):
        main(["--store", str(store_path), "add", "Past due task", "--due", _yesterday()])
        main(["--store", str(store_path), "list"])
        out = capsys.readouterr().out
        assert "OVERDUE" in out

    def test_future_task_no_overdue_marker(self, store_path, capsys):
        main(["--store", str(store_path), "add", "Future task", "--due", _tomorrow()])
        main(["--store", str(store_path), "list"])
        out = capsys.readouterr().out
        assert "OVERDUE" not in out

    def test_done_task_not_overdue(self, store_path, capsys):
        main(["--store", str(store_path), "add", "Done task", "--due", _yesterday()])
        main(["--store", str(store_path), "done", "1"])
        main(["--store", str(store_path), "list"])
        out = capsys.readouterr().out
        assert "OVERDUE" not in out


class TestDueDateDisplay:
    def test_due_date_shown_in_output(self, store_path, capsys):
        due = _tomorrow()
        main(["--store", str(store_path), "add", "Task with date", "--due", due])
        main(["--store", str(store_path), "list"])
        out = capsys.readouterr().out
        assert due in out
