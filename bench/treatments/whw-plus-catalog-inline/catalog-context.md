# Taskboard — Behavior Catalog

This catalog describes the expected behavior of the system. Each entry traces from a high-level goal through specific expectations down to testable facets.

## Goal: Fast CLI-based task management (g-001)

> Provide fast CLI-based task management with persistent storage, rich display, and extensible architecture

### Expectation: Add tasks via CLI (e-001) [crud]
> Users can add tasks with title, priority, and tags via the CLI

- **f-001** `cli.py:cmd_add` parses `add <title> [--priority N] [--tags a,b]` via argparse subparser and calls `store.add(title, priority, tags)` — prints confirmation with `format_task()`
  - Test: `tests/test_taskboard.py::TestCLI::test_add_command`
- **f-002** `store.py:TaskStore.add()` creates a Task with auto-incremented ID from `next_id` field, sets `created_at` to ISO timestamp, appends to tasks list, persists to JSON with file locking (`fcntl LOCK_EX`)
  - Test: `tests/test_taskboard.py::TestStore::test_add_and_get`

### Expectation: List and filter tasks (e-002) [crud]
> Users can list all tasks or filter by status

- **f-003** `cli.py:cmd_list` parses `list [--status todo|done]` and calls `store.list(status=)` — output goes through `display.format_table()` which renders each task with status icon, priority stars, and tags
  - Test: `tests/test_taskboard.py::TestCLI::test_list_command`
- **f-004** `store.py:TaskStore.list(status=None)` returns all tasks, or filters by status string match — reads JSON with `LOCK_SH` for safe concurrent access
  - Test: `tests/test_taskboard.py::TestStore::test_list_by_status`

### Expectation: Mark tasks as done (e-003) [crud]
> Users can mark tasks as done

- **f-005** `cli.py:cmd_done` parses `done <id>` and calls `store.update(id, status='done')` — prints confirmation or 'not found' with exit code 1
  - Test: `tests/test_taskboard.py::TestCLI::test_done_command`

### Expectation: Remove tasks (e-004) [crud]
> Users can remove tasks permanently

- **f-006** `cli.py:cmd_remove` parses `remove <id>` and calls `store.remove(id)` which deletes the task dict from the tasks list and persists — returns exit 1 if not found
  - Test: `tests/test_taskboard.py::TestCLI::test_remove_command`

### Expectation: Edit tasks (e-005) [crud]
> Users can edit task title and priority

- **f-007** `cli.py:cmd_edit` parses `edit <id> [--title TEXT] [--priority N]` and calls `store.update(id, **fields)` — requires at least one of `--title` or `--priority`, exit 2 if neither given
  - Test: `tests/test_taskboard.py::TestCLI::test_edit_title`

### Expectation: Task data model (e-006) [model]
> Task data model supports serialization and sensible defaults

- **f-008** `models.py:Task` is a `@dataclass` with fields: `id(int)`, `title(str)`, `status(str='todo')`, `priority(int=1)`, `tags(list[str]=field(default_factory=list))`, `created_at(str=auto-ISO)`. Has `to_dict()` and `from_dict()` for JSON roundtrip
  - Test: `tests/test_taskboard.py::TestModels::test_task_roundtrip`

### Expectation: Rich terminal display (e-007) [display]
> Tasks display with rich formatting in the terminal

- **f-009** `display.py:format_task()` renders a single task line: status icon `[x]/[ ]` with ANSI color, priority stars (`*` to `***`), title, `#tags` in dim — color only when `stdout.isatty()`. `format_table()` renders a list or 'No tasks.' if empty
  - Test: `tests/test_taskboard.py::TestDisplay::test_format_task_basic`

### Expectation: Argparse CLI dispatch (e-008) [architecture]
> CLI uses argparse subcommands with consistent dispatch pattern

- **f-010** `cli.py:build_parser()` creates `ArgumentParser` with `--store` global flag and subparsers for each command. `main(argv)` calls `build_parser`, resolves store path, creates `TaskStore`, dispatches via `commands` dict. Exit codes: 0=success, 1=not found, 2=invalid args
  - Test: `tests/test_taskboard.py::TestCLI::test_add_command`

### Expectation: Reliable persistence (e-009) [persistence]
> Store persists data reliably with file locking

- **f-011** `store.py:TaskStore` uses `~/.taskboard.json` by default (override via path param). JSON format: `{next_id: int, tasks: [Task dicts]}`. All reads use `fcntl.LOCK_SH`, all writes use `fcntl.LOCK_EX`. `_ensure_file()` creates initial structure if missing
  - Test: `tests/test_taskboard.py::TestStore::test_add_and_get`
