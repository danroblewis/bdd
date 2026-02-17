# Taskboard

A CLI task management tool.

## Stack
- Python 3.11+, no external dependencies
- pytest for testing

## Build & Test
- Run tests: `python -m pytest tests/ -v`
- Run app: `python -m taskboard <command>`

## Architecture
- cli.py: argparse-based CLI, dispatches to handler functions
- store.py: JSON file persistence, loads/saves ~/.taskboard.json
- models.py: Task dataclass with id, title, status, priority, tags, created_at
- display.py: formats tasks for terminal output

## Conventions
- All commands go through cli.py dispatch
- Store handles all file I/O, returns Task objects
- Tests use tmp_path fixture for isolated storage
