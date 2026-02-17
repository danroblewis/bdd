# Taskboard

A CLI task management tool built with Python.

## MANDATORY WORKFLOW

### Step 1: Decompose the task
Before writing ANY code, delegate to the `decomposer` agent:

```
Task(decomposer, "Read the task requirements, analyze all test and source files, and produce a detailed implementation checklist.")
```

The decomposer will return a numbered checklist. **Do not skip any items.**

### Step 2: Implement every checklist item
Work through the checklist in order. After each item, run tests:
```
python -m pytest tests/ -v
```

### Step 3: Final verification
After completing ALL items, run tests one more time. Every test must pass.

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
