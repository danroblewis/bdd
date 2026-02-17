# Taskboard

A CLI task management tool built with Python.

## Workflow

1. **Read `tests/test_taskboard.py` first** — the system enforces this. You cannot edit source files until you've read the test file.
2. Read the relevant source files to understand the current code.
3. Implement your changes across all layers (model -> store -> CLI -> display -> tests).
4. Run `python -m pytest tests/ -v` after every change.
5. If tests fail, fix your implementation — never modify existing tests.

## Source Layout

| File | Purpose |
|------|---------|
| `src/taskboard/models.py` | `Task` dataclass |
| `src/taskboard/store.py` | `TaskStore` — JSON file persistence with `fcntl` locking |
| `src/taskboard/cli.py` | `build_parser()` + subcommand handlers + `commands` dispatch dict |
| `src/taskboard/display.py` | `format_task()` + `format_table()` with ANSI colors |
| `tests/test_taskboard.py` | Regression suite |

## Patterns

- **CLI dispatch:** `build_parser()` -> `commands = {"add": cmd_add, ...}` -> `return commands[args.command](args, store)`
- **Adding a new command:** Add subparser in `build_parser()`, add `cmd_X(args, store)` handler, add to `commands` dict in `main()`

## Rules

- **NEVER delete or modify existing tests.**
- Every `args.X` in a handler needs a matching `add_argument()` in `build_parser()`
- New commands must be added to the `commands` dict in `main()`
