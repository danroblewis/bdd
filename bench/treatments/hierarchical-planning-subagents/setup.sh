#!/bin/bash
# Setup script for hierarchical-planning-subagents treatment
# Runs a SINGLE planning claude invocation that uses 3 sequential sub-agents
# (Expectations → Goals → Facets) via the Task tool, producing planning
# artifacts. The implementation agent then starts fresh with only the plan.

set -euo pipefail

cd "$WORKSPACE"

BENCH_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BDD_SERVER="$(cd "$(dirname "$0")/../../.." && pwd)/bdd_server.py"
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
fi

# --- bdd.json (from subject dir or inline) ---
if [[ -f "$SUBJECT_DIR/bdd.json" ]]; then
  cp "$SUBJECT_DIR/bdd.json" bdd.json
  echo "  Copied bdd.json from $SUBJECT_DIR"
else
cat > bdd.json << EOF
{
  "test_command": "$VENV_PYTHON -m pytest tests/ -v --tb=short --junitxml=.bdd/results.xml --cov=src/taskboard --cov-report=xml:.bdd/coverage.xml",
  "results_format": "junit",
  "results_file": ".bdd/results.xml",
  "coverage_format": "cobertura",
  "coverage_file": ".bdd/coverage.xml"
}
EOF
fi

# --- .mcp.json for planning phase ---
# Planning agents need bdd_tree, bdd_status, bdd_add, bdd_locate but not bdd_test
cat > .mcp.json << EOF
{
  "mcpServers": {
    "bdd": {
      "command": "$VENV_PYTHON",
      "args": ["$BDD_SERVER", "$WORKSPACE", "--exclude-tools", "bdd_next,bdd_motivation,bdd_test"]
    }
  }
}
EOF

# --- Initialize .bdd directory ---
mkdir -p .bdd
echo "$VENV_PYTHON" > .bdd/venv_python

# --- Pre-build the index ---
"$VENV_PYTHON" "$BDD_SERVER" "$WORKSPACE" test >/dev/null 2>&1 || true

# =============================================================================
# SUB-AGENT DEFINITIONS
# =============================================================================

mkdir -p .claude/agents

# --- Expectations Agent (CEO) ---
cat > .claude/agents/expectations.md << 'AGENT_EOF'
---
name: expectations
description: Product strategist — analyzes the feature request and identifies user expectations
tools: Read, Glob, Grep, Write
maxTurns: 8
---

You are a Product Strategist analyzing a feature request. Your role is the "CEO perspective" — understand what the customer needs and express it in stakeholder language, not code.

## Your Task

1. Read `prompt.txt` — this describes the feature to implement
2. Read `catalog.json` — this shows current goals, expectations, and facets
3. Read the existing test file(s) in `tests/` to understand current coverage
4. Call `bdd_status()` to understand the current state of the catalog

## Your Output

Write your analysis to `.planning/expectations.md` using the Write tool. Structure it as:

# Expectations Analysis

## Feature Summary
[1-2 sentences: what the user wants in plain language]

## New Expectations Needed
For each new expectation this feature requires:
### Expectation: [short title]
- **What**: [what the user should be able to do]
- **Why**: [why this matters to the user]
- **Acceptance criteria**: [how to verify it works — observable behavior, not implementation]

## Existing Expectations Affected
- **[e-XXX]**: [how this existing expectation is affected — extended, constrained, or unchanged but related]

## Priority Order
[Number the expectations in implementation order — which should be built first?]

## Key Constraints
[Any constraints from the task prompt — error handling requirements, backwards compatibility, specific behaviors]

## Rules
- Express everything from the USER's perspective, not the developer's
- Focus on WHAT and WHY, not HOW to implement
- Each expectation should be independently testable
- Do not suggest implementation details — that is for later planning phases
AGENT_EOF

# --- Goals Agent (Staff Engineer) ---
cat > .claude/agents/goals.md << 'AGENT_EOF'
---
name: goals
description: Technical architect — aligns expectations with project architecture and goals
tools: Read, Glob, Grep, Write
maxTurns: 10
---

You are a Technical Architect (Staff Engineer perspective). The Expectations Agent has identified what the customer needs. Your job is to align those expectations with the project's existing architecture and goals.

## Your Task

1. Read `.planning/expectations.md` — the expectations analysis from the previous phase
2. Read `catalog.json` — understand the goal/expectation/facet hierarchy
3. Read the source code to understand the architecture:
   - Use the Glob tool to find all source files
   - Read the key source files to understand module responsibilities and patterns
4. Call `bdd_tree()` to see the full catalog hierarchy
5. Call `bdd_status()` to see the current state

## Your Responsibilities

- Map each new expectation to the existing goal hierarchy — does it fit under an existing goal or need a new one?
- Identify architectural patterns the implementation must follow (e.g., CLI dispatch pattern, store CRUD pattern)
- Spot risks where the new feature might break existing behavior
- Optionally use `bdd_add()` to register new expectations in the catalog if appropriate

## Your Output

Write your analysis to `.planning/goals-alignment.md` using the Write tool. Structure it as:

# Goals Alignment

## Expectation-to-Goal Mapping
For each new expectation from the Expectations analysis:
### [Expectation title]
- **Maps to goal**: [g-XXX] or [NEW GOAL: description]
- **Rationale**: [why this expectation belongs under this goal]
- **Related expectations**: [existing e-XXX that share scope]

## Architectural Patterns to Follow
### Pattern: [name]
- **Where**: [file:function]
- **How it works**: [brief description]
- **For this feature**: [how to apply this pattern to the new expectations]

## Module Boundaries
- **models.py**: [what new model changes are needed, if any]
- **store.py**: [what new store methods are needed, if any]
- **cli.py**: [what new CLI commands/args are needed, if any]
- **display.py**: [what new display logic is needed, if any]

## Risk Areas
- [Specific functions/patterns that might break]
- [Edge cases to watch for]
- [Existing tests that exercise at-risk code]

## Recommended Approach (High-Level)
[1-paragraph summary of how the implementation should proceed — which modules to touch in what order]
AGENT_EOF

# --- Facets Agent (Manager) ---
cat > .claude/agents/facets.md << 'AGENT_EOF'
---
name: facets
description: Engineering manager — breaks expectations into concrete implementation steps with exact file/function specifications
tools: Read, Glob, Grep, Write
maxTurns: 12
---

You are an Engineering Manager. The Expectations Agent identified what the customer needs. The Goals Agent aligned those expectations with the architecture. Your job is to break this down into concrete, ordered implementation tasks (facets) that an engineer can execute.

## Your Task

1. Read `.planning/expectations.md` — the expectations analysis
2. Read `.planning/goals-alignment.md` — the architectural alignment
3. Read `catalog.json` — the design catalog
4. Read ALL source files — you need to understand the exact code to specify precise changes:
   - Use the Glob tool to find all source files
   - Read each source file completely
5. Read the existing test files in `tests/`
6. Read `prompt.txt` for any specific requirements
7. Use `bdd_locate()` to find where existing facets are implemented
8. Use `bdd_add()` to register new facets in the catalog — each facet should specify:
   - type: "facet"
   - text: precise description of what to implement (file, function, behavior)
   - parent: the expectation ID it serves

## Your Output

Write your implementation plan to `.planning/implementation-plan.md` using the Write tool. This is the PRIMARY artifact the implementation agent will follow. Be extremely specific. Structure it as:

# Implementation Plan

## Overview
[1-2 sentences summarizing the full scope of work]

## Implementation Order

Work items are ordered by dependency: model changes first, then store, then CLI, then display.

### Step 1: [title]
- **File**: [exact path, e.g., src/taskboard/models.py]
- **What to do**: [precise description — add field X to dataclass, add method Y, modify function Z]
- **Why**: [which expectation this serves]
- **Details**: [specific behavior, defaults, edge cases, error handling]
- **Watch out for**: [anything that could break — existing tests, related code]

### Step 2: [title]
...

## Test Plan
For each new behavior:
### Test: [test name, e.g., test_search_by_title]
- **File**: tests/test_taskboard.py (or new test file)
- **Class**: [TestXxx]
- **What it verifies**: [specific assertion]
- **Setup**: [what test data is needed]

## Regression Checklist
- [ ] All existing tests in tests/test_taskboard.py still pass
- [ ] [specific existing test]: still passes because [reason]
- [ ] [specific function]: not broken by [change]

## Summary
- Total files to modify: [N]
- Total new functions/methods: [N]
- Total new tests: [N]
- Estimated complexity: [low/medium/high]

## Rules
- Be EXACT about file paths, function names, parameter names
- Specify default values and error handling for every new function
- Every step should be independently verifiable
- Follow the existing patterns identified in the Goals alignment
- The implementation agent will follow this plan literally — do not leave ambiguity
AGENT_EOF

# =============================================================================
# PLANNING PHASE — Single claude run with 3 sequential sub-agents
# =============================================================================

mkdir -p .planning
PLAN_START=$(date +%s)

# Move CLAUDE.md out of the way so the planning agent doesn't see implementation instructions
if [[ -f CLAUDE.md ]]; then
  mv CLAUDE.md .planning/CLAUDE.md.impl
fi

echo "  Planning phase: single claude run with 3 sub-agents (max 15 turns)..."

set +e
env -u CLAUDECODE claude -p \
  --dangerously-skip-permissions \
  --max-turns 15 \
  --disallowedTools "Edit,Bash,EnterPlanMode" \
  > .planning/orchestrator-output.txt 2>.planning/orchestrator-stderr.txt \
  << 'ORCHESTRATOR_PROMPT'
You are a Planning Orchestrator. You manage a team of 3 specialist agents who will analyze a feature request and produce an implementation plan. You must run them IN SEQUENCE because each depends on the previous agent's output.

## Your Workflow

Execute these 3 steps in order. For each step, use the Task tool to launch the named agent. Wait for each agent to complete before launching the next.

### Step 1: Launch the `expectations` agent
Tell it: "Analyze the feature request in prompt.txt and the existing catalog. Write your expectations analysis to .planning/expectations.md."

Wait for it to complete. Then verify .planning/expectations.md was created by reading it.

### Step 2: Launch the `goals` agent
Tell it: "Read the expectations analysis in .planning/expectations.md, then analyze the source code and catalog architecture. Write your goals alignment to .planning/goals-alignment.md."

Wait for it to complete. Then verify .planning/goals-alignment.md was created by reading it.

### Step 3: Launch the `facets` agent
Tell it: "Read .planning/expectations.md and .planning/goals-alignment.md, then analyze all source code in detail. Write a concrete implementation plan to .planning/implementation-plan.md."

Wait for it to complete. Then verify .planning/implementation-plan.md was created by reading it.

## Rules
- Launch agents ONE AT A TIME, in order — each depends on the previous output
- Do NOT do any analysis yourself — delegate everything to the agents
- After all 3 complete, briefly confirm which artifacts were created
- Do NOT edit any source code
ORCHESTRATOR_PROMPT
ORCH_EXIT=$?
set -e

PLAN_END=$(date +%s)
PLAN_TIME=$((PLAN_END - PLAN_START))
echo "  Planning orchestrator finished (exit=$ORCH_EXIT, ${PLAN_TIME}s)"

# Log planning timing
cat > .planning/timing.json << EOF
{
  "total_seconds": $PLAN_TIME,
  "orchestrator_exit": $ORCH_EXIT
}
EOF

# Restore CLAUDE.md for the implementation agent
if [[ -f .planning/CLAUDE.md.impl ]]; then
  mv .planning/CLAUDE.md.impl CLAUDE.md
fi

# --- Reconfigure .mcp.json for implementation phase ---
# Implementation agent needs bdd_test but not bdd_tree
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

# List planning artifacts
echo "  Planning artifacts:"
for f in .planning/expectations.md .planning/goals-alignment.md .planning/implementation-plan.md; do
  if [[ -f "$f" ]]; then
    echo "    [OK] $f ($(wc -l < "$f") lines)"
  else
    echo "    [MISSING] $f"
  fi
done

echo "hierarchical-planning-subagents initialized: catalog.json, bdd.json, .mcp.json, 3 agent defs, planning artifacts"
