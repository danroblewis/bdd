import pytest
from taskboard.cli import main


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


class TestSearch:
    def test_search_finds_match(self, store_path, capsys):
        _add(store_path, "Buy groceries")
        _add(store_path, "Buy new shoes")
        _add(store_path, "Walk the dog")
        capsys.readouterr()  # flush add output
        ret = main(["--store", str(store_path), "search", "buy"])
        assert ret == 0
        out = capsys.readouterr().out
        assert "Buy groceries" in out
        assert "Buy new shoes" in out
        assert "Walk the dog" not in out

    def test_search_case_insensitive(self, store_path, capsys):
        _add(store_path, "READ the book")
        capsys.readouterr()  # flush add output
        ret = main(["--store", str(store_path), "search", "read"])
        assert ret == 0
        out = capsys.readouterr().out
        assert "READ the book" in out

    def test_search_no_match(self, store_path, capsys):
        _add(store_path, "Buy milk")
        capsys.readouterr()  # flush add output
        ret = main(["--store", str(store_path), "search", "zebra"])
        out = capsys.readouterr().out
        assert "No matching tasks" in out

    def test_search_with_status_filter(self, store_path, capsys):
        _add(store_path, "Buy milk")
        _add(store_path, "Buy eggs")
        main(["--store", str(store_path), "done", "1"])
        capsys.readouterr()  # flush add/done output
        ret = main(["--store", str(store_path), "search", "buy", "--status", "todo"])
        assert ret == 0
        out = capsys.readouterr().out
        assert "Buy eggs" in out
        assert "Buy milk" not in out

    def test_search_empty_store(self, store_path, capsys):
        ret = main(["--store", str(store_path), "search", "anything"])
        out = capsys.readouterr().out
        assert "No matching tasks" in out
