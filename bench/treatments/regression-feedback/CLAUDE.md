# Taskboard

A CLI task management tool built with Python.

## Automatic Test Feedback

After every source file edit, regression tests run automatically and you'll see the results. Use this feedback to catch issues immediately.

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
