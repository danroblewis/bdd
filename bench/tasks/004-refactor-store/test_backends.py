import pytest
from taskboard.store import TaskStore

# These imports should work after refactoring
try:
    from taskboard.store import Backend, JsonFileBackend, MemoryBackend
except ImportError:
    Backend = None
    JsonFileBackend = None
    MemoryBackend = None


class TestBackendAbstraction:
    def test_backend_classes_exist(self):
        assert Backend is not None, "Backend base class not found"
        assert JsonFileBackend is not None, "JsonFileBackend not found"
        assert MemoryBackend is not None, "MemoryBackend not found"

    def test_json_backend_has_required_methods(self):
        assert hasattr(JsonFileBackend, "load")
        assert hasattr(JsonFileBackend, "save")
        assert hasattr(JsonFileBackend, "exists")

    def test_memory_backend_has_required_methods(self):
        assert hasattr(MemoryBackend, "load")
        assert hasattr(MemoryBackend, "save")
        assert hasattr(MemoryBackend, "exists")


class TestMemoryBackend:
    def test_store_with_memory_backend(self):
        backend = MemoryBackend()
        store = TaskStore(backend=backend)
        task = store.add("Test task")
        assert task.id == 1
        assert task.title == "Test task"

    def test_memory_backend_persistence_within_instance(self):
        backend = MemoryBackend()
        store = TaskStore(backend=backend)
        store.add("Task 1")
        store.add("Task 2")
        tasks = store.list()
        assert len(tasks) == 2

    def test_memory_backend_isolation(self):
        b1 = MemoryBackend()
        b2 = MemoryBackend()
        s1 = TaskStore(backend=b1)
        s2 = TaskStore(backend=b2)
        s1.add("In store 1")
        assert len(s1.list()) == 1
        assert len(s2.list()) == 0


class TestBackwardsCompatibility:
    def test_path_parameter_still_works(self, tmp_path):
        store_path = tmp_path / "tasks.json"
        store = TaskStore(path=store_path)
        task = store.add("Legacy test")
        assert task.title == "Legacy test"

    def test_positional_path_still_works(self, tmp_path):
        store_path = tmp_path / "tasks.json"
        store = TaskStore(store_path)
        task = store.add("Positional test")
        assert task.title == "Positional test"

    def test_json_backend_explicit(self, tmp_path):
        store_path = tmp_path / "tasks.json"
        backend = JsonFileBackend(store_path)
        store = TaskStore(backend=backend)
        store.add("Explicit backend")
        tasks = store.list()
        assert len(tasks) == 1
