import pytest
from taskboard.cli import main


@pytest.fixture
def store_path(tmp_path):
    return tmp_path / "tasks.json"


def _add(store_path, title):
    main(["--store", str(store_path), "add", title])


class TestTagCommand:
    def test_tag_adds_tag(self, store_path, capsys):
        _add(store_path, "Task one")
        ret = main(["--store", str(store_path), "tag", "1", "urgent"])
        assert ret == 0

    def test_tag_shows_in_list(self, store_path, capsys):
        _add(store_path, "Task one")
        main(["--store", str(store_path), "tag", "1", "urgent"])
        main(["--store", str(store_path), "list"])
        out = capsys.readouterr().out
        assert "urgent" in out

    def test_tag_no_duplicates(self, store_path, capsys):
        _add(store_path, "Task one")
        main(["--store", str(store_path), "tag", "1", "urgent"])
        main(["--store", str(store_path), "tag", "1", "urgent"])
        # Should only have one "urgent" tag
        from taskboard.store import TaskStore
        store = TaskStore(store_path)
        task = store.get(1)
        count = sum(1 for t in task.tags if t.lower() == "urgent")
        assert count == 1

    def test_tag_nonexistent_task(self, store_path, capsys):
        ret = main(["--store", str(store_path), "tag", "99", "foo"])
        assert ret == 1


class TestUntagCommand:
    def test_untag_removes_tag(self, store_path, capsys):
        _add(store_path, "Task one")
        main(["--store", str(store_path), "tag", "1", "urgent"])
        ret = main(["--store", str(store_path), "untag", "1", "urgent"])
        assert ret == 0
        from taskboard.store import TaskStore
        store = TaskStore(store_path)
        task = store.get(1)
        assert "urgent" not in task.tags

    def test_untag_nonexistent_tag_is_noop(self, store_path, capsys):
        _add(store_path, "Task one")
        ret = main(["--store", str(store_path), "untag", "1", "nonexistent"])
        assert ret == 0

    def test_untag_nonexistent_task(self, store_path, capsys):
        ret = main(["--store", str(store_path), "untag", "99", "foo"])
        assert ret == 1


class TestListByTag:
    def test_list_filters_by_tag(self, store_path, capsys):
        _add(store_path, "Work task")
        _add(store_path, "Home task")
        main(["--store", str(store_path), "tag", "1", "work"])
        main(["--store", str(store_path), "tag", "2", "home"])
        ret = main(["--store", str(store_path), "list", "--tag", "work"])
        assert ret == 0
        out = capsys.readouterr().out
        assert "Work task" in out
        assert "Home task" not in out

    def test_list_tag_case_insensitive(self, store_path, capsys):
        _add(store_path, "Task one")
        main(["--store", str(store_path), "tag", "1", "Urgent"])
        ret = main(["--store", str(store_path), "list", "--tag", "urgent"])
        assert ret == 0
        out = capsys.readouterr().out
        assert "Task one" in out

    def test_list_tag_no_match(self, store_path, capsys):
        _add(store_path, "Task one")
        ret = main(["--store", str(store_path), "list", "--tag", "nonexistent"])
        out = capsys.readouterr().out
        assert "No tasks" in out
