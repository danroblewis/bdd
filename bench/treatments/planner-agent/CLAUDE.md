# Taskboard

A CLI task management tool built with Python.

## MANDATORY WORKFLOW

You MUST follow this exact workflow for every task:

### Step 1: Plan with the planner agent
Before writing ANY code, delegate to the `planner` agent:

```
Task(planner, "Analyze the task requirements, read all test files and source files, and produce a detailed implementation plan with specific code changes needed for each file.")
```

The planner will read tests and source code and return a structured plan. **Wait for the plan before writing any code.**

### Step 2: Implement the plan
Follow the planner's output step by step. Implement changes across all layers.

### Step 3: Run tests
Run `python -m pytest tests/ -v` after every change. If tests fail, fix your implementation — never modify existing tests.

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
