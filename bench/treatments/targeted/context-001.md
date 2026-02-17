# Context for: Add search command

You'll be adding a new CLI command. Here's what you need to know:

## Adding a new command
1. Add a `cmd_search(args)` function in `src/taskboard/cli.py`
2. Add a subparser in `build_parser()` (see existing commands for pattern)
3. Register it in the `commands` dict in `main()`

## Key APIs
- `store.list(status=None)` returns all tasks (optionally filtered by status)
- `format_table(tasks)` renders a list of tasks for terminal output
- Tests use `--store <path>` to isolate storage to tmp_path

## Run tests
`python -m pytest tests/ -v`
