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

- **CLI dispatch:** `build_parser()` → `args = parser.parse_args(argv)` → `commands = {"add": cmd_add, ...}` → `return commands[args.command](args, store)`
- **Adding a new command:** Add subparser in `build_parser()`, add `cmd_X(args, store)` handler, add to `commands` dict in `main()`

## Workflow

1. **Read the task prompt** to understand what to implement
2. **Read source files** — the hook shows which catalog entries relate to the code you're reading
3. **Implement the change** across all layers (model → store → CLI → display → tests)
4. **Run `bdd_test()`** to execute tests, rebuild the index, and update catalog statuses

## Rules

- **NEVER delete or modify existing tests.** They are the specification.
- Every `args.X` reference in a command handler needs a matching `add_argument()` in `build_parser()`
- New commands must be added to the `commands` dict in `main()`

## Available MCP Tools

| Tool | Description |
|------|-------------|
| `bdd_status(check?)` | Catalog summary |
| `bdd_locate(node_id)` | Find implementation files for a facet |
| `bdd_test()` | Run tests, rebuild index, update statuses |
| `bdd_add(type, text, parent?, ...)` | Add catalog entry |
| `bdd_link(facet_id, test_id)` | Connect facet to test |
