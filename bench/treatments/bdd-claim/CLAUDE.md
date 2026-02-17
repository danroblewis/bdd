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

## Workflow — Claim Before You Change

**IMPORTANT: Before modifying any source file, you MUST identify which catalog facet(s) you are about to affect.**

1. **Read the task prompt** to understand what to implement
2. **Use `bdd_motivation(file_path)`** on any file you plan to modify — this tells you which facets map to that file and why the code exists
3. **Use `bdd_locate(facet_id)`** to find where a specific facet is implemented, confirming you're editing the right code
4. **State which facet you're implementing** before each edit — e.g. "I'm modifying f-001 (cmd_add parser) to add the --search flag"
5. **Implement the change** across all layers (model -> store -> CLI -> display -> tests)
6. **Run `bdd_test()`** to execute tests, rebuild the index, and update catalog statuses
7. **Use `bdd_next()`** to find remaining work if multiple changes are needed

### Why claim first?

The catalog tracks stakeholder intent. By identifying which facet you're touching *before* you edit, you:
- Confirm you're changing the right code for the right reason
- Avoid accidentally breaking unrelated behavior
- Keep your changes aligned with what stakeholders actually want

If you're adding **new** functionality that doesn't map to an existing facet, use `bdd_add` to create a new facet first, then proceed.

## Completion Checklist

- Every `args.X` reference in a command handler has a matching `add_argument()` in `build_parser()`
- New commands are added to the `commands` dict in `main()`
- Store methods handle the not-found case (return None or False)
- All existing tests still pass (regression)
- New functionality has tests

## Available MCP Tools

| Tool | Description |
|------|-------------|
| `bdd_status(check?)` | Catalog summary: counts, progress, unsatisfied expectations. Pass `check="all"` for health diagnostics. |
| `bdd_motivation(file_path)` | **Use before editing.** Shows which facets map to a file and why the code exists. |
| `bdd_next()` | Find what to work on next — returns the highest-priority unsatisfied facet. |
| `bdd_locate(node_id)` | Find implementation files and line ranges for a facet or expectation. |
| `bdd_test()` | Run full test suite, parse results + coverage, rebuild index, update facet statuses. |
| `bdd_add(type, text, parent?, ...)` | Add a goal, expectation, or facet to the catalog. |
| `bdd_link(facet_id, test_id)` | Connect a facet to a test identifier (e.g. `tests/test_foo.py::test_bar`). |
