import pytest
from taskboard.cli import main


@pytest.fixture
def store_path(tmp_path):
    return tmp_path / "tasks.json"


class TestDoneBugFix:
    def test_done_nonexistent_id_returns_1(self, store_path, capsys):
        """done with nonexistent ID should return exit code 1, not crash."""
        ret = main(["--store", str(store_path), "done", "999"])
        assert ret == 1

    def test_done_nonexistent_id_prints_error(self, store_path, capsys):
        """done with nonexistent ID should print an error message."""
        main(["--store", str(store_path), "done", "999"])
        err = capsys.readouterr().err
        assert "not found" in err.lower()

    def test_done_nonexistent_no_crash(self, store_path):
        """done with nonexistent ID should not raise an exception."""
        try:
            ret = main(["--store", str(store_path), "done", "42"])
        except AttributeError:
            pytest.fail("cmd_done raised AttributeError on nonexistent task ID")
        except Exception as e:
            pytest.fail(f"cmd_done raised unexpected {type(e).__name__}: {e}")

    def test_done_valid_still_works(self, store_path, capsys):
        """Existing done functionality should still work."""
        main(["--store", str(store_path), "add", "Test task"])
        ret = main(["--store", str(store_path), "done", "1"])
        assert ret == 0
        out = capsys.readouterr().out
        assert "Marked task 1 as done" in out

    def test_done_already_done_task(self, store_path, capsys):
        """Marking an already-done task should not crash."""
        main(["--store", str(store_path), "add", "Test task"])
        main(["--store", str(store_path), "done", "1"])
        ret = main(["--store", str(store_path), "done", "1"])
        assert ret == 0
