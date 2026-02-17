import pytest
from taskboard.cli import main


@pytest.fixture
def store_path(tmp_path):
    return tmp_path / "tasks.json"


def _add(store_path, title, **kw):
    args = ["--store", str(store_path), "add", title]
    if "priority" in kw:
        args += ["--priority", str(kw["priority"])]
    main(args)


class TestStatsCommand:
    def test_stats_empty(self, store_path, capsys):
        ret = main(["--store", str(store_path), "stats"])
        assert ret == 0
        out = capsys.readouterr().out
        assert "No tasks" in out

    def test_stats_total_count(self, store_path, capsys):
        _add(store_path, "Task 1")
        _add(store_path, "Task 2")
        _add(store_path, "Task 3")
        capsys.readouterr()
        ret = main(["--store", str(store_path), "stats"])
        assert ret == 0
        out = capsys.readouterr().out
        assert "Total: 3" in out

    def test_stats_todo_done_counts(self, store_path, capsys):
        _add(store_path, "Task 1")
        _add(store_path, "Task 2")
        _add(store_path, "Task 3")
        main(["--store", str(store_path), "done", "1"])
        capsys.readouterr()
        ret = main(["--store", str(store_path), "stats"])
        assert ret == 0
        out = capsys.readouterr().out
        assert "Todo: 2" in out
        assert "Done: 1" in out

    def test_stats_priority_breakdown(self, store_path, capsys):
        _add(store_path, "Low task", priority=1)
        _add(store_path, "Med task", priority=2)
        _add(store_path, "High task", priority=3)
        _add(store_path, "Another low", priority=1)
        capsys.readouterr()
        ret = main(["--store", str(store_path), "stats"])
        assert ret == 0
        out = capsys.readouterr().out
        assert "Priority 1: 2" in out
        assert "Priority 2: 1" in out
        assert "Priority 3: 1" in out

    def test_stats_omits_unused_priorities(self, store_path, capsys):
        _add(store_path, "High only", priority=3)
        capsys.readouterr()
        ret = main(["--store", str(store_path), "stats"])
        assert ret == 0
        out = capsys.readouterr().out
        assert "Priority 3: 1" in out
        assert "Priority 1" not in out
        assert "Priority 2" not in out

    def test_stats_all_done(self, store_path, capsys):
        _add(store_path, "Task 1")
        _add(store_path, "Task 2")
        main(["--store", str(store_path), "done", "1"])
        main(["--store", str(store_path), "done", "2"])
        capsys.readouterr()
        ret = main(["--store", str(store_path), "stats"])
        assert ret == 0
        out = capsys.readouterr().out
        assert "Todo: 0" in out
        assert "Done: 2" in out
