# Taskboard — Architecture Context

## Why: Personal Task Management
Users need a fast, offline-first way to manage daily tasks from the terminal.
No accounts, no sync, no bloat — just a local JSON file and a CLI.

## How: Single-file JSON Store + Argparse CLI
We chose the simplest possible architecture:
- **Why JSON file**: No database dependency, human-readable, easy to back up
- **Why argparse**: Standard library, no deps, familiar to users
- **Why dataclass**: Immutable-ish, typed, easy to serialize

### What: Task Model (`src/taskboard/models.py`)
- `Task(id, title, status, priority, tags, created_at)` dataclass
- `status` is one of: "todo", "done"
- `id` is auto-incremented integer from store
- `to_dict()` / `from_dict()` for JSON serialization

### What: Store (`src/taskboard/store.py`)
- `TaskStore(path)` — reads/writes `~/.taskboard.json`
- `add(title, priority, tags)` → Task
- `get(id)` → Task | None
- `list(status=None)` → list[Task]
- `update(id, **fields)` → Task
- `remove(id)` → bool
- File locked during writes (fcntl)

### What: CLI (`src/taskboard/cli.py`)
- `main()` parses args, dispatches to `cmd_add`, `cmd_list`, `cmd_done`, etc.
- Each cmd function takes parsed args, calls store, calls display
- Exit codes: 0 success, 1 not found, 2 usage error

### What: Display (`src/taskboard/display.py`)
- `format_task(task)` → single-line string with status icon, priority stars
- `format_table(tasks)` → aligned multi-line output
- Uses ANSI colors only if stdout is a tty

## Build & Test
- Run tests: `python -m pytest tests/ -v`
- Run app: `python -m taskboard <command>`
