# Taskboard

A CLI task management tool built with Python.

## Stack & Architecture

- **Python 3.11+**, no external dependencies at runtime
- **pytest** + **pytest-cov** for testing
- Entry point: `python -m taskboard <command>`

### Source Layout

| File | Purpose |
|------|---------|
| `src/taskboard/models.py` | `Task` dataclass: id, title, status, priority, tags, created_at. `to_dict()`/`from_dict()` for JSON. |
| `src/taskboard/store.py` | `TaskStore` — JSON file persistence with `fcntl` locking. Methods: `add`, `get`, `list`, `update`, `remove`. Default path: `~/.taskboard.json`. |
| `src/taskboard/cli.py` | `build_parser()` creates argparse with `--store` global flag + subparsers. `main(argv)` dispatches via `commands` dict. Exit codes: 0=ok, 1=not found, 2=bad args. |
| `src/taskboard/display.py` | `format_task()` — status icon + priority stars + tags with ANSI colors. `format_table()` — multi-task list or "No tasks." |
| `tests/test_taskboard.py` | Regression suite: TestModels, TestStore, TestCLI, TestDisplay classes. |

### Patterns

- **CLI dispatch:** `build_parser()` -> `args = parser.parse_args(argv)` -> `commands = {"add": cmd_add, ...}` -> `return commands[args.command](args, store)`
- **Store CRUD:** Every method does `_load()` with LOCK_SH or `_save()` with LOCK_EX. JSON format: `{"next_id": int, "tasks": [dicts]}`
- **Adding a new command:** Add subparser in `build_parser()`, add `cmd_X(args, store)` handler, add to `commands` dict in `main()`

## Workflow — FOLLOW THIS ORDER

1. **Read tests first.** Open `tests/test_taskboard.py` and understand what every existing test expects. These 22 tests are the contract — they must all keep passing.
2. **Read the task prompt** to understand what to implement.
3. **Read the relevant source files** to understand the current code before making changes.
4. **Implement the change** across all layers (model -> store -> CLI -> display -> tests).
5. **Run tests after every change:** `python -m pytest tests/ -v`
6. **If tests fail, fix your implementation** — never modify or delete existing tests.
7. **Add tests for new functionality** that follow the same patterns as existing tests.

## Rules

- **NEVER delete or modify existing tests.** They are the specification.
- **NEVER skip or mark tests as expected failures.**
- If a test fails after your change, your code is wrong — fix the code, not the test.
- Every `args.X` reference in a command handler needs a matching `add_argument()` in `build_parser()`.
- New commands must be added to the `commands` dict in `main()`.
- Store methods must handle the not-found case (return None or False).

## Build & Test

- Run tests: `python -m pytest tests/ -v`
- Run app: `python -m taskboard <command>`
