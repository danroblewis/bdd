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

## Workflow: Scout First, Then Implement

You have 3 scout agents available that will analyze the codebase from different angles. Launch them ALL in parallel FIRST, then use their briefings to guide your implementation.

### Phase 1: Launch Scouts (parallel)
Launch all 3 scouts at the same time using the Task tool:

1. **Scout-Architecture**: Analyzes catalog.json and source files to explain WHY each module exists, what design patterns it follows, and how modules connect through shared motivations.
2. **Scout-Impact**: Reads your task prompt and catalog.json to identify which existing motivations your feature will touch, extend, or coexist with.
3. **Scout-Patterns**: Reads all source files to identify recurring code patterns (dispatch, CRUD, display) and notes which catalog expectations motivated each pattern.

### Phase 2: Read Briefings
After all 3 scouts complete, read their outputs carefully. They contain:
- An architecture motivation map (which module serves which goal)
- An impact analysis (which existing expectations you need to respect)
- A pattern guide (how to follow existing conventions)

### Phase 3: Implement
With the scouts' analysis in mind:
4. Implement changes following the patterns identified by Scout-Patterns
5. Respect the expectations identified by Scout-Impact
6. Follow the module boundaries explained by Scout-Architecture
7. Work in order: model → store → CLI → display

### Phase 4: Verify
8. Call `bdd_test()` to run tests and verify everything passes

## Available Agents

| Agent | Purpose | Tools |
|-------|---------|-------|
| `scout-architecture` | Map module responsibilities to catalog motivations | Read, Glob |
| `scout-impact` | Identify which motivations the new feature touches | Read, Grep |
| `scout-patterns` | Extract recurring code patterns and their motivations | Read, Glob |

## Available MCP Tools

| Tool | Description |
|------|-------------|
| `bdd_status(check?)` | Catalog summary: counts, progress, unsatisfied expectations. |
| `bdd_locate(node_id)` | Find implementation files and line ranges for a facet or expectation. |
| `bdd_test()` | Run full test suite, parse results + coverage, rebuild index, update facet statuses. |
| `bdd_add(type, text, parent?, ...)` | Add a goal, expectation, or facet to the catalog. |
| `bdd_link(facet_id, test_id)` | Connect a facet to a test identifier. |

## Completion Checklist

- Every `args.X` reference in a command handler has a matching `add_argument()` in `build_parser()`
- New commands are added to the `commands` dict in `main()`
- Store methods handle the not-found case (return None or False)
- All existing tests still pass (regression)
- New functionality has tests
