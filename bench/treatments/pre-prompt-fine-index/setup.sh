#!/bin/bash
# Setup script for pre-prompt-fine-index treatment
# Same as bdd-fine-index (coverage-json + hooks) but adds the anti-tamper pre-prompt.
# Hypothesis: fixes the 80% tamper rate of bdd-fine-index while keeping fine-grained index.

set -euo pipefail
cd "$WORKSPACE"

BENCH_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BDD_SERVER="$(cd "$(dirname "$0")/../../.." && pwd)/bdd_server.py"
HOOK_SCRIPT="$(cd "$(dirname "$0")/../../.." && pwd)/framework/hooks/inject-context.sh"
WRITE_HOOK_SCRIPT="$(cd "$(dirname "$0")/../../.." && pwd)/framework/hooks/inject-write-context.sh"
# --- Subject-aware paths ---
SUBJECT_DIR="$BENCH_ROOT/${SUBJECT:-subject}"
if [[ -f "$SUBJECT_DIR/subject.json" ]]; then
  SUBJECT_VENV=$(python3 -c "import json; print(json.load(open('$SUBJECT_DIR/subject.json')).get('venv_python','.venv/bin/python3'))")
  VENV_PYTHON="$BENCH_ROOT/$SUBJECT_VENV"
else
  VENV_PYTHON="$BENCH_ROOT/.venv/bin/python3"
fi

# --- catalog.json (from subject dir or inline) ---
if [[ -f "$SUBJECT_DIR/catalog.json" ]]; then
  cp "$SUBJECT_DIR/catalog.json" catalog.json
  echo "  Copied catalog.json from $SUBJECT_DIR"
else
# --- inline catalog.json for taskboard subject ---
cat > catalog.json << 'CATALOG_EOF'
{
  "version": 1,
  "nodes": [
    {"id": "g-001", "type": "goal", "text": "Provide fast CLI-based task management with persistent storage, rich display, and extensible architecture", "parent": null, "priority": 1, "labels": ["core"]},
    {"id": "e-001", "type": "expectation", "text": "Users can add tasks with title, priority, and tags via the CLI", "parent": "g-001", "priority": 1, "labels": ["crud"]},
    {"id": "f-001", "type": "facet", "text": "cli.py:cmd_add parses 'add <title> [--priority N] [--tags a,b]' via argparse subparser and calls store.add(title, priority, tags)", "parent": "e-001", "test": "tests/test_taskboard.py::TestCLI::test_add_command", "status": "untested"},
    {"id": "f-002", "type": "facet", "text": "store.py:TaskStore.add() creates a Task with auto-incremented ID, persists to JSON with fcntl LOCK_EX", "parent": "e-001", "test": "tests/test_taskboard.py::TestStore::test_add_and_get", "status": "untested"},
    {"id": "e-002", "type": "expectation", "text": "Users can list all tasks or filter by status", "parent": "g-001", "priority": 1, "labels": ["crud"]},
    {"id": "f-003", "type": "facet", "text": "cli.py:cmd_list parses 'list [--status todo|done]' and calls store.list(status=) with display.format_table()", "parent": "e-002", "test": "tests/test_taskboard.py::TestCLI::test_list_command", "status": "untested"},
    {"id": "f-004", "type": "facet", "text": "store.py:TaskStore.list(status=None) returns all tasks or filters by status", "parent": "e-002", "test": "tests/test_taskboard.py::TestStore::test_list_by_status", "status": "untested"},
    {"id": "e-003", "type": "expectation", "text": "Users can mark tasks as done", "parent": "g-001", "priority": 1, "labels": ["crud"]},
    {"id": "f-005", "type": "facet", "text": "cli.py:cmd_done parses 'done <id>' and calls store.update(id, status='done')", "parent": "e-003", "test": "tests/test_taskboard.py::TestCLI::test_done_command", "status": "untested"},
    {"id": "e-004", "type": "expectation", "text": "Users can remove tasks permanently", "parent": "g-001", "priority": 2, "labels": ["crud"]},
    {"id": "f-006", "type": "facet", "text": "cli.py:cmd_remove parses 'remove <id>' and calls store.remove(id)", "parent": "e-004", "test": "tests/test_taskboard.py::TestCLI::test_remove_command", "status": "untested"},
    {"id": "e-005", "type": "expectation", "text": "Users can edit task title and priority", "parent": "g-001", "priority": 2, "labels": ["crud"]},
    {"id": "f-007", "type": "facet", "text": "cli.py:cmd_edit parses 'edit <id> [--title TEXT] [--priority N]' and calls store.update(id, **fields)", "parent": "e-005", "test": "tests/test_taskboard.py::TestCLI::test_edit_title", "status": "untested"},
    {"id": "e-006", "type": "expectation", "text": "Task data model supports serialization and sensible defaults", "parent": "g-001", "priority": 1, "labels": ["model"]},
    {"id": "f-008", "type": "facet", "text": "models.py:Task is a @dataclass with to_dict() and from_dict() for JSON roundtrip", "parent": "e-006", "test": "tests/test_taskboard.py::TestModels::test_task_roundtrip", "status": "untested"},
    {"id": "e-007", "type": "expectation", "text": "Tasks display with rich formatting in the terminal", "parent": "g-001", "priority": 2, "labels": ["display"]},
    {"id": "f-009", "type": "facet", "text": "display.py:format_task() renders status icon, priority stars, title, tags with ANSI colors", "parent": "e-007", "test": "tests/test_taskboard.py::TestDisplay::test_format_task_basic", "status": "untested"},
    {"id": "e-008", "type": "expectation", "text": "CLI uses argparse subcommands with consistent dispatch pattern", "parent": "g-001", "priority": 1, "labels": ["architecture"]},
    {"id": "f-010", "type": "facet", "text": "cli.py:build_parser() creates ArgumentParser with --store flag and subparsers, main() dispatches via commands dict", "parent": "e-008", "test": "tests/test_taskboard.py::TestCLI::test_add_command", "status": "untested"},
    {"id": "e-009", "type": "expectation", "text": "Store persists data reliably with file locking", "parent": "g-001", "priority": 1, "labels": ["persistence"]},
    {"id": "f-011", "type": "facet", "text": "store.py:TaskStore uses JSON file with fcntl locking for concurrent safety", "parent": "e-009", "test": "tests/test_taskboard.py::TestStore::test_add_and_get", "status": "untested"}
  ]
}
CATALOG_EOF
fi

# --- bdd.json (from subject dir or inline) ---
if [[ -f "$SUBJECT_DIR/bdd.json" ]]; then
  cp "$SUBJECT_DIR/bdd.json" bdd.json
  echo "  Copied bdd.json from $SUBJECT_DIR"
else
cat > bdd.json << EOF
{
  "test_command": "$VENV_PYTHON -m pytest tests/ -v --tb=short --junitxml=.bdd/results.xml --cov=src/taskboard --cov-context=test --cov-report=json:.bdd/coverage.json",
  "results_format": "junit",
  "results_file": ".bdd/results.xml",
  "coverage_format": "coverage-json",
  "coverage_file": ".bdd/coverage.json"
}
EOF
fi

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

# --- PostToolUse hooks (same as bdd-fine-index) ---
mkdir -p .claude/hooks
cp "$HOOK_SCRIPT" .claude/hooks/inject-context.sh
cp "$WRITE_HOOK_SCRIPT" .claude/hooks/inject-write-context.sh
chmod +x .claude/hooks/inject-context.sh .claude/hooks/inject-write-context.sh

python3 -c "
import json
with open('.claude/settings.json') as f: s = json.load(f)
hooks = s.setdefault('hooks', {})
hooks.setdefault('PostToolUse', []).extend([
    {
        'matcher': 'Read',
        'hooks': [{
            'type': 'command',
            'command': '$VENV_PYTHON \"\$CLAUDE_PROJECT_DIR/.claude/hooks/inject-context.sh\" 2>/dev/null || true'
        }]
    },
    {
        'matcher': 'Edit|Write',
        'hooks': [{
            'type': 'command',
            'command': '$VENV_PYTHON \"\$CLAUDE_PROJECT_DIR/.claude/hooks/inject-write-context.sh\" 2>/dev/null || true'
        }]
    }
])
with open('.claude/settings.json', 'w') as f: json.dump(s, f, indent=2)
"

# --- Initialize ---
mkdir -p .bdd
echo "$VENV_PYTHON" > .bdd/venv_python
"$VENV_PYTHON" "$BDD_SERVER" "$WORKSPACE" test >/dev/null 2>&1 || true

echo "pre-prompt-fine-index initialized: fine-grained index + hooks + anti-tamper pre-prompt"
