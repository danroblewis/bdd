# Context for: Refactor store.py for pluggable backends

The main change is in `src/taskboard/store.py`.

## Current architecture
`TaskStore` directly uses `json` + `fcntl` for file I/O. The file path is passed
to the constructor and all read/write operations are in `_read_data()` / `_write_data()`.

## Refactoring approach
1. Create an abstract `Backend` base class with `load()`, `save(data)`, `exists()` methods
2. Extract current file I/O into `JsonFileBackend(path)` implementing `Backend`
3. Create `MemoryBackend()` that stores data in a dict (for testing)
4. Modify `TaskStore.__init__` to accept either `path` (backwards compat) or `backend`
5. Replace `_read_data()` → `self.backend.load()`, `_write_data()` → `self.backend.save()`

## Critical: backwards compatibility
`TaskStore(path)` and `TaskStore(path=some_path)` must still work. Existing tests
must pass without modification.

## Run tests
`python -m pytest tests/ -v`
