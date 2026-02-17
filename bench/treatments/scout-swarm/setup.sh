#!/bin/bash
# Setup script for the scout-swarm treatment
# Like full-bdd but with ALL MCP tools enabled and 3 parallel read-only
# scout agents that pre-digest the codebase through a motivational lens
# before the main agent implements.

set -euo pipefail

cd "$WORKSPACE"

BENCH_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BDD_SERVER="$(cd "$(dirname "$0")/../../.." && pwd)/bdd_server.py"
HOOK_SCRIPT="$(cd "$(dirname "$0")/../../.." && pwd)/framework/hooks/inject-context.sh"
WRITE_HOOK_SCRIPT="$(cd "$(dirname "$0")/../../.." && pwd)/framework/hooks/inject-write-context.sh"
VENV_PYTHON="$BENCH_ROOT/.venv/bin/python3"

# --- catalog.json (enriched descriptions of existing functionality) ---
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

# --- bdd.json (test config — cobertura coverage for index building) ---
cat > bdd.json << EOF
{
  "test_command": "$VENV_PYTHON -m pytest tests/ -v --tb=short --junitxml=.bdd/results.xml --cov=src/taskboard --cov-report=xml:.bdd/coverage.xml",
  "results_format": "junit",
  "results_file": ".bdd/results.xml",
  "coverage_format": "cobertura",
  "coverage_file": ".bdd/coverage.xml"
}
EOF

# --- .mcp.json (registers bdd_server.py with ALL tools — no exclusions) ---
# scout-swarm needs bdd_motivation and bdd_tree available for scout agents
cat > .mcp.json << EOF
{
  "mcpServers": {
    "bdd": {
      "command": "$VENV_PYTHON",
      "args": ["$BDD_SERVER", "$WORKSPACE"]
    }
  }
}
EOF

# --- Scout agent definitions ---
mkdir -p .claude/agents

cat > .claude/agents/scout-architecture.md << 'AGENT_EOF'
---
name: scout-architecture
description: Analyzes catalog.json and source files to map module responsibilities to catalog motivations.
tools: Read, Glob
model: haiku
maxTurns: 10
---

You are an architecture analyst. Your job is to explain WHY each module in this project exists by connecting source code to the motivational catalog.

## Your Process

1. Read `catalog.json` — understand the goal/expectation/facet hierarchy
2. Read all source files in `src/taskboard/` (models.py, store.py, cli.py, display.py)
3. For each module, identify which catalog expectations it serves

## Your Output

Return a markdown "Architecture Motivation Map" with this structure:

### Architecture Motivation Map

**Goal**: g-001 — [goal text]

#### models.py
- **Why it exists**: Serves [expectations] — [explain the design motivation]
- **Design pattern**: [describe the pattern and why it was chosen]
- **Connection points**: [how it connects to other modules]

#### store.py
- **Why it exists**: Serves [expectations] — [explain]
- **Design pattern**: [describe]
- **Connection points**: [how it connects]

#### cli.py
- **Why it exists**: Serves [expectations] — [explain]
- **Design pattern**: [describe the dispatch pattern and why]
- **Connection points**: [how it connects]
- **Extension point**: [how to add new commands safely]

#### display.py
- **Why it exists**: Serves [expectations] — [explain]
- **Design pattern**: [describe]
- **Connection points**: [how it connects]

### Module Boundaries
- [Explain which module owns what responsibility]
- [Explain what should NOT cross module boundaries]

## Rules
- Focus on WHY, not just WHAT — every module exists to serve specific stakeholder expectations
- Identify the design philosophy that unifies the architecture
- Note where the architecture is extensible vs rigid
AGENT_EOF

cat > .claude/agents/scout-impact.md << 'AGENT_EOF'
---
name: scout-impact
description: Identifies which existing catalog motivations a new feature will touch, extend, or coexist with.
tools: Read, Grep
model: haiku
maxTurns: 10
---

You are an impact analyst. Your job is to identify which existing architectural motivations will be affected by a new feature.

## Your Process

1. Read `catalog.json` — understand all existing expectations and facets
2. Read the task prompt (it will be in CLAUDE.md or provided to you)
3. For each existing expectation, determine if the new feature will:
   - **EXTEND** it (add new capability within the same motivation)
   - **TOUCH** it (modify code that implements it)
   - **COEXIST** with it (share modules but not interfere)
   - **IGNORE** it (completely unrelated)

## Your Output

Return a markdown "Impact Analysis" with this structure:

### Impact Analysis for: [feature name]

#### Expectations That Will Be EXTENDED
- **e-XXX**: [text] — [how the feature extends this expectation]

#### Expectations That Will Be TOUCHED
- **e-XXX**: [text] — [what code will be modified and why care is needed]

#### Expectations That COEXIST
- **e-XXX**: [text] — [shares module but safe to leave alone]

#### Safe Extension Points
- [Where new code can be added without modifying existing behavior]
- [Which patterns to follow when extending]

#### Risk Areas
- [Where the new feature might accidentally break existing expectations]
- [Specific functions or patterns that must be preserved]

## Rules
- Be specific — name exact functions and patterns at risk
- Every existing expectation should appear in exactly one category
- The agent implementing the feature will use this to know what to preserve
AGENT_EOF

cat > .claude/agents/scout-patterns.md << 'AGENT_EOF'
---
name: scout-patterns
description: Extracts recurring code patterns from source files and notes which catalog expectations motivated each pattern.
tools: Read, Glob
model: haiku
maxTurns: 10
---

You are a pattern analyst. Your job is to extract the recurring code patterns from this project and explain which motivations drove each pattern.

## Your Process

1. Read all source files in `src/taskboard/` (models.py, store.py, cli.py, display.py)
2. Read `catalog.json` to understand which expectations each pattern serves
3. Identify recurring patterns and their motivational origins

## Your Output

Return a markdown "Pattern Guide" with this structure:

### Pattern Guide

#### Pattern 1: CLI Dispatch
- **Where**: cli.py — `build_parser()` + `commands` dict + `cmd_X()` handlers
- **Motivated by**: e-008 (consistent CLI dispatch)
- **How it works**: [step-by-step description]
- **To add a new command**:
  1. Add subparser in `build_parser()` with arguments
  2. Write `cmd_X(args, store)` handler function
  3. Add entry to `commands` dict in `main()`
- **Do NOT**: [common mistakes to avoid]

#### Pattern 2: Store CRUD
- **Where**: store.py — `_load()` / `_save()` with locking
- **Motivated by**: e-009 (reliable persistence)
- **How it works**: [description]
- **To add a new query/mutation**:
  1. [Steps]
- **Do NOT**: [mistakes to avoid]

#### Pattern 3: Data Model
- **Where**: models.py — `Task` dataclass
- **Motivated by**: e-006 (serialization + defaults)
- **How it works**: [description]
- **To add a new field**:
  1. [Steps]
- **Do NOT**: [mistakes to avoid]

#### Pattern 4: Display Formatting
- **Where**: display.py — `format_task()` / `format_table()`
- **Motivated by**: e-007 (rich terminal display)
- **How it works**: [description]
- **To add new display logic**:
  1. [Steps]
- **Do NOT**: [mistakes to avoid]

### Anti-Patterns
- [Things the codebase deliberately avoids and why]

## Rules
- Every pattern should trace back to a catalog expectation
- Include concrete code snippets showing the pattern
- Make the "To add" sections directly actionable
AGENT_EOF

# --- .claude/settings.json (merge PostToolUse hooks into existing settings) ---
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

# --- Initialize .bdd directory ---
mkdir -p .bdd
echo "$VENV_PYTHON" > .bdd/venv_python

# --- Pre-build the index by running tests + coverage ---
"$VENV_PYTHON" "$BDD_SERVER" "$WORKSPACE" test >/dev/null 2>&1 || true

echo "BDD system initialized (scout-swarm): catalog.json, bdd.json, .mcp.json (all tools), 3 scout agents, hooks, index"
