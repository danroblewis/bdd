Refactor `store.py` to support pluggable storage backends.

Requirements:
- Create an abstract base class `Backend` with methods: `load() -> dict`, `save(data: dict)`, `exists() -> bool`
- Refactor the existing JSON file storage into a `JsonFileBackend` class that implements `Backend`
- Add a new `MemoryBackend` class that stores data in memory (useful for testing)
- `TaskStore` should accept a `backend` parameter instead of (or in addition to) a `path` parameter
- `TaskStore(path="some/path")` should still work (backwards compatible, defaults to JsonFileBackend)
- All existing tests must continue to pass without modification
