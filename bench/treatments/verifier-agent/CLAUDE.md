# Taskboard

A CLI task management tool built with Python.

## MANDATORY WORKFLOW

### Step 1: Read tests first
Read `tests/test_taskboard.py` to understand all expected behavior.

### Step 2: Implement changes
Implement across all layers (model -> store -> CLI -> display -> tests).

### Step 3: Verify with the verifier agent
After implementing, delegate to the `verifier` agent to run tests and get diagnostic feedback:

```
Task(verifier, "Run all tests, analyze any failures, and tell me exactly what needs to be fixed.")
```

### Step 4: Fix issues
Follow the verifier's feedback to fix any failing tests. Repeat steps 3-4 until all tests pass.

## Source Layout

| File | Purpose |
|------|---------|
| `src/taskboard/models.py` | `Task` dataclass |
| `src/taskboard/store.py` | `TaskStore` — JSON file persistence with `fcntl` locking |
| `src/taskboard/cli.py` | `build_parser()` + subcommand handlers + `commands` dispatch dict |
| `src/taskboard/display.py` | `format_task()` + `format_table()` with ANSI colors |
| `tests/test_taskboard.py` | Regression suite |

## Rules

- **NEVER delete or modify existing tests.**
- Every `args.X` in a handler needs a matching `add_argument()` in `build_parser()`
- New commands must be added to the `commands` dict in `main()`
