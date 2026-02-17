import pytest
from taskboard.cli import main
from taskboard.store import TaskStore


@pytest.fixture
def store_path(tmp_path):
    return tmp_path / "tasks.json"


def _add(store_path, title):
    main(["--store", str(store_path), "add", title])


class TestStartCommand:
    def test_start_marks_in_progress(self, store_path, capsys):
        _add(store_path, "My task")
        ret = main(["--store", str(store_path), "start", "1"])
        assert ret == 0
        store = TaskStore(store_path)
        task = store.get(1)
        assert task.status == "in-progress"

    def test_start_already_in_progress(self, store_path, capsys):
        _add(store_path, "My task")
        main(["--store", str(store_path), "start", "1"])
        capsys.readouterr()
        ret = main(["--store", str(store_path), "start", "1"])
        assert ret == 0
        out = capsys.readouterr().out
        assert "already in progress" in out.lower()

    def test_start_done_task_fails(self, store_path, capsys):
        _add(store_path, "My task")
        main(["--store", str(store_path), "done", "1"])
        capsys.readouterr()
        ret = main(["--store", str(store_path), "start", "1"])
        assert ret == 1
        err = capsys.readouterr().err
        assert "already done" in err.lower()

    def test_start_nonexistent_task(self, store_path, capsys):
        ret = main(["--store", str(store_path), "start", "99"])
        assert ret == 1
        err = capsys.readouterr().err
        assert "not found" in err.lower()


class TestDoneFromInProgress:
    def test_done_from_in_progress(self, store_path, capsys):
        _add(store_path, "My task")
        main(["--store", str(store_path), "start", "1"])
        ret = main(["--store", str(store_path), "done", "1"])
        assert ret == 0
        store = TaskStore(store_path)
        task = store.get(1)
        assert task.status == "done"

    def test_done_from_todo_still_works(self, store_path, capsys):
        _add(store_path, "My task")
        ret = main(["--store", str(store_path), "done", "1"])
        assert ret == 0
        store = TaskStore(store_path)
        task = store.get(1)
        assert task.status == "done"


class TestListInProgress:
    def test_list_filter_in_progress(self, store_path, capsys):
        _add(store_path, "Todo task")
        _add(store_path, "Started task")
        _add(store_path, "Done task")
        main(["--store", str(store_path), "start", "2"])
        main(["--store", str(store_path), "done", "3"])
        capsys.readouterr()
        ret = main(["--store", str(store_path), "list", "--status", "in-progress"])
        assert ret == 0
        out = capsys.readouterr().out
        assert "Started task" in out
        assert "Todo task" not in out
        assert "Done task" not in out


class TestInProgressDisplay:
    def test_in_progress_icon(self, store_path, capsys):
        _add(store_path, "Active task")
        main(["--store", str(store_path), "start", "1"])
        capsys.readouterr()
        main(["--store", str(store_path), "list"])
        out = capsys.readouterr().out
        assert "[-]" in out

    def test_todo_icon_unchanged(self, store_path, capsys):
        _add(store_path, "Pending task")
        capsys.readouterr()
        main(["--store", str(store_path), "list"])
        out = capsys.readouterr().out
        assert "[ ]" in out
