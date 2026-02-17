import pytest
from taskboard.cli import main


@pytest.fixture
def store_path(tmp_path):
    return tmp_path / "tasks.json"


class TestPriorityValidation:
    def test_add_priority_zero_rejected(self, store_path, capsys):
        ret = main(["--store", str(store_path), "add", "Task", "--priority", "0"])
        assert ret == 2
        err = capsys.readouterr().err
        assert "priority" in err.lower()

    def test_add_priority_too_high_rejected(self, store_path, capsys):
        ret = main(["--store", str(store_path), "add", "Task", "--priority", "4"])
        assert ret == 2
        err = capsys.readouterr().err
        assert "priority" in err.lower()

    def test_add_valid_priorities_work(self, store_path, capsys):
        for p in [1, 2, 3]:
            ret = main(["--store", str(store_path), "add", f"Task p{p}", "--priority", str(p)])
            assert ret == 0

    def test_edit_priority_invalid_rejected(self, store_path, capsys):
        main(["--store", str(store_path), "add", "Task"])
        capsys.readouterr()
        ret = main(["--store", str(store_path), "edit", "1", "--priority", "5"])
        assert ret == 2
        err = capsys.readouterr().err
        assert "priority" in err.lower()


class TestTitleValidation:
    def test_add_empty_title_rejected(self, store_path, capsys):
        ret = main(["--store", str(store_path), "add", ""])
        assert ret == 2
        err = capsys.readouterr().err
        assert "title" in err.lower()

    def test_add_whitespace_title_rejected(self, store_path, capsys):
        ret = main(["--store", str(store_path), "add", "   "])
        assert ret == 2
        err = capsys.readouterr().err
        assert "title" in err.lower()

    def test_add_valid_title_works(self, store_path, capsys):
        ret = main(["--store", str(store_path), "add", "Buy milk"])
        assert ret == 0

    def test_edit_title_empty_rejected(self, store_path, capsys):
        main(["--store", str(store_path), "add", "Original"])
        capsys.readouterr()
        ret = main(["--store", str(store_path), "edit", "1", "--title", ""])
        assert ret == 2
        err = capsys.readouterr().err
        assert "title" in err.lower()
