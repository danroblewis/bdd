# Context for: Fix done command bug

The bug is in `src/taskboard/cli.py` in the `cmd_done` function.

## Current behavior
`cmd_done` calls `store.get(id)` and accesses the result's `.status` attribute
without checking if the result is None. When the task ID doesn't exist,
`store.get()` returns None, causing an `AttributeError`.

## Fix pattern
Check if the result of `store.get()` is None before accessing attributes.
Return exit code 1 with an error message to stderr if the task doesn't exist.

## Key APIs
- `store.get(id)` → Task | None
- `store.update(id, **fields)` → Task | None

## Run tests
`python -m pytest tests/ -v`
