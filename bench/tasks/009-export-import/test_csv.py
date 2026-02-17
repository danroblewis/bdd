import csv
import pytest
from taskboard.cli import main
from taskboard.store import TaskStore


@pytest.fixture
def store_path(tmp_path):
    return tmp_path / "tasks.json"


def _add(store_path, title, **kw):
    args = ["--store", str(store_path), "add", title]
    if "priority" in kw:
        args += ["--priority", str(kw["priority"])]
    if "tags" in kw:
        args += ["--tags", kw["tags"]]
    main(args)


class TestExport:
    def test_export_creates_file(self, store_path, tmp_path, capsys):
        _add(store_path, "Task one")
        csv_path = tmp_path / "export.csv"
        capsys.readouterr()
        ret = main(["--store", str(store_path), "export", str(csv_path)])
        assert ret == 0
        assert csv_path.exists()

    def test_export_correct_header(self, store_path, tmp_path, capsys):
        _add(store_path, "Task one")
        csv_path = tmp_path / "export.csv"
        capsys.readouterr()
        main(["--store", str(store_path), "export", str(csv_path)])
        with open(csv_path) as f:
            reader = csv.reader(f)
            header = next(reader)
        assert header == ["id", "title", "status", "priority", "tags", "created_at"]

    def test_export_task_data(self, store_path, tmp_path, capsys):
        _add(store_path, "Buy milk", priority=2, tags="shopping,food")
        csv_path = tmp_path / "export.csv"
        capsys.readouterr()
        main(["--store", str(store_path), "export", str(csv_path)])
        with open(csv_path) as f:
            reader = csv.reader(f)
            next(reader)  # skip header
            row = next(reader)
        assert row[1] == "Buy milk"
        assert row[2] == "todo"
        assert row[3] == "2"
        assert "shopping" in row[4]
        assert "food" in row[4]

    def test_export_empty_store(self, store_path, tmp_path, capsys):
        csv_path = tmp_path / "export.csv"
        ret = main(["--store", str(store_path), "export", str(csv_path)])
        assert ret == 0
        out = capsys.readouterr().out
        assert "Exported 0 tasks" in out

    def test_export_message(self, store_path, tmp_path, capsys):
        _add(store_path, "Task one")
        _add(store_path, "Task two")
        csv_path = tmp_path / "export.csv"
        capsys.readouterr()
        ret = main(["--store", str(store_path), "export", str(csv_path)])
        out = capsys.readouterr().out
        assert "Exported 2 tasks" in out


class TestImport:
    def test_import_adds_tasks(self, store_path, tmp_path, capsys):
        csv_path = tmp_path / "import.csv"
        with open(csv_path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["id", "title", "status", "priority", "tags", "created_at"])
            w.writerow(["1", "Imported task", "todo", "1", "", "2026-01-01T00:00:00"])
        ret = main(["--store", str(store_path), "import", str(csv_path)])
        assert ret == 0
        store = TaskStore(store_path)
        tasks = store.list()
        assert len(tasks) == 1
        assert tasks[0].title == "Imported task"

    def test_import_assigns_new_ids(self, store_path, tmp_path, capsys):
        _add(store_path, "Existing task")
        csv_path = tmp_path / "import.csv"
        with open(csv_path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["id", "title", "status", "priority", "tags", "created_at"])
            w.writerow(["99", "New task", "todo", "2", "", "2026-01-01T00:00:00"])
        capsys.readouterr()
        main(["--store", str(store_path), "import", str(csv_path)])
        store = TaskStore(store_path)
        tasks = store.list()
        assert len(tasks) == 2
        imported = [t for t in tasks if t.title == "New task"][0]
        assert imported.id == 2  # new auto-incremented ID, not 99

    def test_import_preserves_tags(self, store_path, tmp_path, capsys):
        csv_path = tmp_path / "import.csv"
        with open(csv_path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["id", "title", "status", "priority", "tags", "created_at"])
            w.writerow(["1", "Tagged task", "todo", "1", "work;urgent", "2026-01-01T00:00:00"])
        main(["--store", str(store_path), "import", str(csv_path)])
        store = TaskStore(store_path)
        task = store.get(1)
        assert "work" in task.tags
        assert "urgent" in task.tags

    def test_import_file_not_found(self, store_path, tmp_path, capsys):
        csv_path = tmp_path / "nonexistent.csv"
        ret = main(["--store", str(store_path), "import", str(csv_path)])
        assert ret == 1
        err = capsys.readouterr().err
        assert "not found" in err.lower()

    def test_import_message(self, store_path, tmp_path, capsys):
        csv_path = tmp_path / "import.csv"
        with open(csv_path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["id", "title", "status", "priority", "tags", "created_at"])
            w.writerow(["1", "Task A", "todo", "1", "", "2026-01-01T00:00:00"])
            w.writerow(["2", "Task B", "done", "2", "", "2026-01-01T00:00:00"])
        ret = main(["--store", str(store_path), "import", str(csv_path)])
        assert ret == 0
        out = capsys.readouterr().out
        assert "Imported 2 tasks" in out


class TestRoundTrip:
    def test_export_then_import(self, store_path, tmp_path, capsys):
        _add(store_path, "Round trip task", priority=3, tags="test,roundtrip")
        csv_path = tmp_path / "roundtrip.csv"
        capsys.readouterr()
        main(["--store", str(store_path), "export", str(csv_path)])
        # Import into a fresh store
        store_path2 = tmp_path / "tasks2.json"
        main(["--store", str(store_path2), "import", str(csv_path)])
        store = TaskStore(store_path2)
        tasks = store.list()
        assert len(tasks) == 1
        assert tasks[0].title == "Round trip task"
        assert tasks[0].priority == 3
        assert "test" in tasks[0].tags
        assert "roundtrip" in tasks[0].tags
