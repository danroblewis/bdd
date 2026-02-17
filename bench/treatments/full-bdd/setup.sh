#!/bin/bash
# Setup script for the full-bdd treatment
# Bootstraps the complete BDD system: catalog, config, MCP server, and hooks.

set -euo pipefail

cd "$WORKSPACE"

BDD_SERVER="$(cd "$(dirname "$0")/../../.." && pwd)/bdd_server.py"
HOOK_SCRIPT="$(cd "$(dirname "$0")/../../.." && pwd)/framework/hooks/inject-context.sh"

# --- catalog.json (nodes format matching bdd_server.py) ---
cat > catalog.json << 'EOF'
{
  "version": 1,
  "nodes": [
    {
      "id": "g-001",
      "type": "goal",
      "text": "Provide fast CLI-based task management",
      "parent": null,
      "priority": 1,
      "labels": ["core"]
    },
    {
      "id": "e-001",
      "type": "expectation",
      "text": "Users can add tasks with title, priority, and tags",
      "parent": "g-001",
      "priority": 1,
      "labels": []
    },
    {
      "id": "f-001",
      "type": "facet",
      "text": "cli.py:cmd_add parses title, priority, tags and calls store.add()",
      "parent": "e-001",
      "test": "tests/test_taskboard.py::test_add_task",
      "status": "untested"
    },
    {
      "id": "f-002",
      "type": "facet",
      "text": "store.py:add() creates Task with auto-incremented ID and persists to JSON",
      "parent": "e-001",
      "test": "tests/test_taskboard.py::test_persistence",
      "status": "untested"
    },
    {
      "id": "e-002",
      "type": "expectation",
      "text": "Users can list and filter tasks",
      "parent": "g-001",
      "priority": 1,
      "labels": []
    },
    {
      "id": "f-003",
      "type": "facet",
      "text": "cli.py:cmd_list calls store.list() with optional status filter",
      "parent": "e-002",
      "test": "tests/test_taskboard.py::test_list_tasks",
      "status": "untested"
    },
    {
      "id": "e-003",
      "type": "expectation",
      "text": "Users can mark tasks as done",
      "parent": "g-001",
      "priority": 1,
      "labels": []
    },
    {
      "id": "f-004",
      "type": "facet",
      "text": "cli.py:cmd_done calls store.update(id, status='done')",
      "parent": "e-003",
      "test": "tests/test_taskboard.py::test_done",
      "status": "untested"
    },
    {
      "id": "e-004",
      "type": "expectation",
      "text": "Users can remove tasks",
      "parent": "g-001",
      "priority": 2,
      "labels": []
    },
    {
      "id": "f-005",
      "type": "facet",
      "text": "cli.py:cmd_remove calls store.remove(id)",
      "parent": "e-004",
      "test": "tests/test_taskboard.py::test_remove",
      "status": "untested"
    },
    {
      "id": "e-005",
      "type": "expectation",
      "text": "Users can edit task properties",
      "parent": "g-001",
      "priority": 2,
      "labels": []
    },
    {
      "id": "f-006",
      "type": "facet",
      "text": "cli.py:cmd_edit updates title and/or priority via store.update()",
      "parent": "e-005",
      "test": "tests/test_taskboard.py::test_edit",
      "status": "untested"
    }
  ]
}
EOF

# --- bdd.json (test config for bdd_server.py) ---
cat > bdd.json << 'EOF'
{
  "test_command": "python -m pytest tests/ -v --tb=short --junitxml=.bdd/results.xml",
  "results_format": "junit",
  "results_file": ".bdd/results.xml",
  "coverage_format": "coverage-json",
  "coverage_file": ".bdd/coverage.json"
}
EOF

# --- .mcp.json (registers bdd_server.py as MCP server) ---
cat > .mcp.json << EOF
{
  "mcpServers": {
    "bdd": {
      "command": "python3",
      "args": ["$BDD_SERVER", "$WORKSPACE"]
    }
  }
}
EOF

# --- .claude/settings.json (PostToolUse hook for Read) ---
mkdir -p .claude/hooks
cp "$HOOK_SCRIPT" .claude/hooks/inject-context.sh
chmod +x .claude/hooks/inject-context.sh

cat > .claude/settings.json << 'EOF'
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Read",
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"$CLAUDE_PROJECT_DIR/.claude/hooks/inject-context.sh\" 2>/dev/null || true"
          }
        ]
      }
    ]
  }
}
EOF

# --- Initialize .bdd directory ---
mkdir -p .bdd

echo "BDD system initialized: catalog.json, bdd.json, .mcp.json, hooks"
