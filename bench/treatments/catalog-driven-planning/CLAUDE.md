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

## Workflow: Think in Goals, Then Code

You have a BDD catalog that describes WHY this project's code exists. Your workflow is to FIRST understand the existing motivations, THEN articulate your own intent in catalog terms, THEN implement.

### Phase 1: Understand Existing Motivations
1. Call `bdd_tree()` to see the full goal → expectation → facet hierarchy
2. Call `bdd_motivation("src/taskboard/cli.py")` (and other source files) to understand why each module is structured the way it is
3. Read the source files — understand how the existing code serves its catalog motivations

### Phase 2: Articulate Your Intent
Before writing ANY code:
4. Use `bdd_add(type="expectation", text="...", parent="g-001")` to create a new expectation describing what the user wants from your feature
5. Use `bdd_add(type="facet", text="...", parent="<your-expectation-id>")` to create facets — one per testable piece:
   - One facet per new CLI command or argument
   - One facet per new store method or query
   - One facet per display change
6. Call `bdd_tree()` again to review your plan — your new nodes should fit naturally alongside the existing ones

### Phase 3: Implement
7. Work through your facets in order: model → store → CLI → display
8. Call `bdd_test()` after major changes to run tests and update statuses

### Phase 4: Verify Alignment
9. Call `bdd_status()` — your new facets should show progress
10. Call `bdd_tree(status_filter="unsatisfied")` — ideally empty when done

## Available MCP Tools

| Tool | When to Use | Description |
|------|-------------|-------------|
| `bdd_tree(node_id?, status_filter?, max_depth?)` | Phase 1 & 2: understand and review your plan | Show catalog hierarchy. Use `status_filter="unsatisfied"` to see what's left. |
| `bdd_motivation(file, start_line?, end_line?)` | Phase 1: understand why code exists | Returns goal→expectation→facet chains for code in a file. |
| `bdd_add(type, text, parent?, priority?, labels?)` | Phase 2: articulate your intent | Add goal, expectation, or facet. Types: "goal", "expectation", "facet". |
| `bdd_link(facet_id, test_id)` | Phase 3: connect facets to tests | Link a facet to a test identifier after writing tests. |
| `bdd_status(check?)` | Phase 4: verify alignment | Catalog summary with progress. Use `check="all"` for health diagnostics. |
| `bdd_locate(node_id)` | Any phase: find implementation | Files and line ranges for a facet or expectation. |
| `bdd_test()` | Phase 3 & 4: run tests | Run test suite, rebuild index, update facet statuses. |
| `bdd_next()` | Phase 3: find next work item | Returns highest-priority unsatisfied expectation. |

## Completion Checklist

- Every `args.X` reference in a command handler has a matching `add_argument()` in `build_parser()`
- New commands are added to the `commands` dict in `main()`
- Store methods handle the not-found case (return None or False)
- All existing tests still pass (regression)
- New functionality has tests
