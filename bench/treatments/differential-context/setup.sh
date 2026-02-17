#!/bin/bash
# Setup script for differential-context treatment
# Same as full-bdd but uses differential hook variants that track what
# has been shown and only inject NEW motivation chains.

set -euo pipefail

cd "$WORKSPACE"

BENCH_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BDD_SERVER="$(cd "$(dirname "$0")/../../.." && pwd)/bdd_server.py"
HOOK_SCRIPT="$(cd "$(dirname "$0")/../../.." && pwd)/framework/hooks/inject-context-differential.sh"
WRITE_HOOK_SCRIPT="$(cd "$(dirname "$0")/../../.." && pwd)/framework/hooks/inject-write-context-differential.sh"
VENV_PYTHON="$BENCH_ROOT/.venv/bin/python3"

# --- catalog.json (same as full-bdd) ---
cat > catalog.json << 'CATALOG_EOF'
{
  "version": 1,
  "nodes": [
    {
      "id": "g-001",
      "type": "goal",
      "text": "Provide fast CLI-based task management with persistent storage, rich display, and extensible architecture",
      "parent": null,
      "priority": 1,
      "labels": ["core"]
    },
    {
      "id": "e-001",
      "type": "expectation",
      "text": "Users can add tasks with title, priority, and tags via the CLI",
      "parent": "g-001",
      "priority": 1,
      "labels": ["crud"]
    },
    {
      "id": "f-001",
      "type": "facet",
      "text": "cli.py:cmd_add parses 'add <title> [--priority N] [--tags a,b]' via argparse subparser and calls store.add(title, priority, tags) — prints confirmation with format_task()",
      "parent": "e-001",
      "test": "tests/test_taskboard.py::TestCLI::test_add_command",
      "status": "untested"
    },
    {
      "id": "f-002",
      "type": "facet",
      "text": "store.py:TaskStore.add() creates a Task with auto-incremented ID from next_id field, sets created_at to ISO timestamp, appends to tasks list, persists to JSON with file locking (fcntl LOCK_EX)",
      "parent": "e-001",
      "test": "tests/test_taskboard.py::TestStore::test_add_and_get",
      "status": "untested"
    },
    {
      "id": "e-002",
      "type": "expectation",
      "text": "Users can list all tasks or filter by status",
      "parent": "g-001",
      "priority": 1,
      "labels": ["crud"]
    },
    {
      "id": "f-003",
      "type": "facet",
      "text": "cli.py:cmd_list parses 'list [--status todo|done]' and calls store.list(status=) — output goes through display.format_table() which renders each task with status icon, priority stars, and tags",
      "parent": "e-002",
      "test": "tests/test_taskboard.py::TestCLI::test_list_command",
      "status": "untested"
    },
    {
      "id": "f-004",
      "type": "facet",
      "text": "store.py:TaskStore.list(status=None) returns all tasks, or filters by status string match — reads JSON with LOCK_SH for safe concurrent access",
      "parent": "e-002",
      "test": "tests/test_taskboard.py::TestStore::test_list_by_status",
      "status": "untested"
    },
    {
      "id": "e-003",
      "type": "expectation",
      "text": "Users can mark tasks as done",
      "parent": "g-001",
      "priority": 1,
      "labels": ["crud"]
    },
    {
      "id": "f-005",
      "type": "facet",
      "text": "cli.py:cmd_done parses 'done <id>' and calls store.update(id, status='done') — prints confirmation or 'not found' with exit code 1",
      "parent": "e-003",
      "test": "tests/test_taskboard.py::TestCLI::test_done_command",
      "status": "untested"
    },
    {
      "id": "e-004",
      "type": "expectation",
      "text": "Users can remove tasks permanently",
      "parent": "g-001",
      "priority": 2,
      "labels": ["crud"]
    },
    {
      "id": "f-006",
      "type": "facet",
      "text": "cli.py:cmd_remove parses 'remove <id>' and calls store.remove(id) which deletes the task dict from the tasks list and persists — returns exit 1 if not found",
      "parent": "e-004",
      "test": "tests/test_taskboard.py::TestCLI::test_remove_command",
      "status": "untested"
    },
    {
      "id": "e-005",
      "type": "expectation",
      "text": "Users can edit task title and priority",
      "parent": "g-001",
      "priority": 2,
      "labels": ["crud"]
    },
    {
      "id": "f-007",
      "type": "facet",
      "text": "cli.py:cmd_edit parses 'edit <id> [--title TEXT] [--priority N]' and calls store.update(id, **fields) — requires at least one of --title or --priority, exit 2 if neither given",
      "parent": "e-005",
      "test": "tests/test_taskboard.py::TestCLI::test_edit_title",
      "status": "untested"
    },
    {
      "id": "e-006",
      "type": "expectation",
      "text": "Task data model supports serialization and sensible defaults",
      "parent": "g-001",
      "priority": 1,
      "labels": ["model"]
    },
    {
      "id": "f-008",
      "type": "facet",
      "text": "models.py:Task is a @dataclass with fields: id(int), title(str), status(str='todo'), priority(int=1), tags(list[str]=field(default_factory=list)), created_at(str=auto-ISO). Has to_dict() and from_dict() for JSON roundtrip",
      "parent": "e-006",
      "test": "tests/test_taskboard.py::TestModels::test_task_roundtrip",
      "status": "untested"
    },
    {
      "id": "e-007",
      "type": "expectation",
      "text": "Tasks display with rich formatting in the terminal",
      "parent": "g-001",
      "priority": 2,
      "labels": ["display"]
    },
    {
      "id": "f-009",
      "type": "facet",
      "text": "display.py:format_task() renders a single task line: status icon [x]/[ ] with ANSI color, priority stars (* to ***), title, #tags in dim — color only when stdout.isatty(). format_table() renders a list or 'No tasks.' if empty",
      "parent": "e-007",
      "test": "tests/test_taskboard.py::TestDisplay::test_format_task_basic",
      "status": "untested"
    },
    {
      "id": "e-008",
      "type": "expectation",
      "text": "CLI uses argparse subcommands with consistent dispatch pattern",
      "parent": "g-001",
      "priority": 1,
      "labels": ["architecture"]
    },
    {
      "id": "f-010",
      "type": "facet",
      "text": "cli.py:build_parser() creates ArgumentParser with --store global flag and subparsers for each command. main(argv) calls build_parser, resolves store path, creates TaskStore, dispatches via commands dict mapping name->handler. Exit codes: 0=success, 1=not found, 2=invalid args",
      "parent": "e-008",
      "test": "tests/test_taskboard.py::TestCLI::test_add_command",
      "status": "untested"
    },
    {
      "id": "e-009",
      "type": "expectation",
      "text": "Store persists data reliably with file locking",
      "parent": "g-001",
      "priority": 1,
      "labels": ["persistence"]
    },
    {
      "id": "f-011",
      "type": "facet",
      "text": "store.py:TaskStore uses ~/.taskboard.json by default (override via path param). JSON format: {next_id: int, tasks: [Task dicts]}. All reads use fcntl.LOCK_SH, all writes use fcntl.LOCK_EX. _ensure_file() creates initial structure if missing",
      "parent": "e-009",
      "test": "tests/test_taskboard.py::TestStore::test_add_and_get",
      "status": "untested"
    }
  ]
}
CATALOG_EOF

# --- bdd.json ---
cat > bdd.json << EOF
{
  "test_command": "$VENV_PYTHON -m pytest tests/ -v --tb=short --junitxml=.bdd/results.xml --cov=src/taskboard --cov-report=xml:.bdd/coverage.xml",
  "results_format": "junit",
  "results_file": ".bdd/results.xml",
  "coverage_format": "cobertura",
  "coverage_file": ".bdd/coverage.xml"
}
EOF

# --- .mcp.json ---
cat > .mcp.json << EOF
{
  "mcpServers": {
    "bdd": {
      "command": "$VENV_PYTHON",
      "args": ["$BDD_SERVER", "$WORKSPACE", "--exclude-tools", "bdd_next,bdd_motivation,bdd_tree"]
    }
  }
}
EOF

# --- .claude/settings.json (differential hooks) ---
mkdir -p .claude/hooks
cp "$HOOK_SCRIPT" .claude/hooks/inject-context-differential.sh
cp "$WRITE_HOOK_SCRIPT" .claude/hooks/inject-write-context-differential.sh
chmod +x .claude/hooks/inject-context-differential.sh .claude/hooks/inject-write-context-differential.sh

python3 -c "
import json
with open('.claude/settings.json') as f: s = json.load(f)
hooks = s.setdefault('hooks', {})
hooks.setdefault('PostToolUse', []).extend([
    {
        'matcher': 'Read',
        'hooks': [{
            'type': 'command',
            'command': '$VENV_PYTHON \"\$CLAUDE_PROJECT_DIR/.claude/hooks/inject-context-differential.sh\" 2>/dev/null || true'
        }]
    },
    {
        'matcher': 'Edit|Write',
        'hooks': [{
            'type': 'command',
            'command': '$VENV_PYTHON \"\$CLAUDE_PROJECT_DIR/.claude/hooks/inject-write-context-differential.sh\" 2>/dev/null || true'
        }]
    }
])
with open('.claude/settings.json', 'w') as f: json.dump(s, f, indent=2)
"

# --- Initialize .bdd directory + empty session ---
mkdir -p .bdd
echo "$VENV_PYTHON" > .bdd/venv_python
echo '{}' > .bdd/session_seen.json

# --- Pre-build the index ---
"$VENV_PYTHON" "$BDD_SERVER" "$WORKSPACE" test >/dev/null 2>&1 || true

echo "differential-context initialized: catalog.json, bdd.json, .mcp.json, differential hooks, session_seen.json, index"
