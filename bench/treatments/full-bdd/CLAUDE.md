# Taskboard

A CLI task management tool.

## Stack
- Python 3.11+, no external dependencies
- pytest for testing

## Build & Test
- Run tests: use the `bdd_test` MCP tool (not pytest directly)
- Run app: `python -m taskboard <command>`

## Architecture
- cli.py: argparse-based CLI, dispatches to handler functions
- store.py: JSON file persistence, loads/saves ~/.taskboard.json
- models.py: Task dataclass with id, title, status, priority, tags, created_at
- display.py: formats tasks for terminal output

## BDD System

This project uses Behavior Test Curation. The `catalog.json` file is the source of truth for stakeholder intent.

### Available MCP Tools
- `bdd_status` — Catalog summary (counts, progress %, satisfied expectations)
- `bdd_next` — Next unsatisfied expectation with facets and parent goal context
- `bdd_tree` — Full catalog hierarchy with status filters
- `bdd_motivation` — Why does code exist (goal→expectation→facet chains)
- `bdd_locate` — Where is a facet/expectation implemented
- `bdd_test` — Run tests, parse results, rebuild index, update facet statuses
- `bdd_add` — Add goals/expectations/facets to the catalog
- `bdd_link` — Connect a facet to a test identifier

### Workflow
1. Call `bdd_next` to find the next unsatisfied expectation
2. Read the relevant code — the hook will show you why it exists
3. Implement the change
4. Call `bdd_test` to run tests and update facet statuses
5. Every code change should trace to a catalog entry
