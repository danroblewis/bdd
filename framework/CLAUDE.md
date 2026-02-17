# Project Instructions

This project uses **Behavior Test Curation** (Emergent Alignment) as its development methodology. The catalog (`catalog.json`) is the single source of truth for stakeholder intent.

## Methodology

You have BDD catalog tools available via MCP — use `/bdd` to learn the full methodology.

The short version:
- The catalog contains **goals** (broad intent), **expectations** (specific wants), and **facets** (testable pieces).
- Call `bdd_motivation` when reading code to understand WHY it exists.
- Call `bdd_next` to find what to work on next.
- **ALWAYS use `bdd_test` to run tests.** Never run the test command from bdd.json directly. `bdd_test` runs the tests AND updates facet statuses and the motivation index. Running tests any other way leaves the catalog stale.
- Every code change should trace to a catalog entry.
- Write behavior tests (full program, user perspective), not unit tests.

## Self-Improvement

Build tools that help you work. If you notice a recurring need — introspection, automation, data access — create an MCP tool for it. The `bdd_server.py` pattern (FastMCP + project-local server) works for any project-specific tooling.

## Project Overview

This is a **Benchmark Framework for BDD Agent Techniques** — a system to empirically measure how different AI agent configurations (hooks, MCP tools, prompts, context files) affect task completion quality, efficiency, and cost. Agents implement features in a real subject project (taskboard CLI) and results are compared across treatments.

## Project Details

**Stack:** Python 3.11+, Bash, FastMCP, pytest, coverage.py, JUnit XML

**Test:**
```bash
# configured via bdd.json, run with bdd_test MCP tool
```

**Key Paths:**
- `bdd_server.py` — FastMCP server: catalog tools (bdd_test, bdd_status, bdd_locate, bdd_add, bdd_link), test/coverage parsing, index management
- `loop.sh` — Autonomous BDD loop: plan → implement → test (4 phases, max iterations)
- `bench/run.sh` — Execute single benchmark (task x treatment), produces metrics.json
- `bench/run-all.sh` — Batch runner: all task x treatment combinations in parallel
- `bench/analyze.py` — Aggregate results into comparison tables and CSV
- `bench/subject/` — Subject project (taskboard CLI: Python, argparse, JSON store, 22 regression tests)
- `bench/tasks/` — 5 benchmark tasks (001-add-search through 005-add-due-dates), each with prompt.md + acceptance test
- `bench/treatments/` — Treatment variants (baseline, why-how-what, full-bdd, bdd-fine-index, etc.), each with treatment.yaml + optional setup.sh/CLAUDE.md/context files
- `bench/results/` — Timestamped run results (metrics.json per run)
- `framework/hooks/` — Reusable hook scripts (inject-context.sh for Read, inject-write-context.sh for Write/Edit)
- `framework/skills/` — MCP skill implementations (bdd, bootstrap, curate, status, suggest)

## Benchmark Workflow

1. `run.sh --task <name> --treatment <name>` creates an isolated workspace, applies treatment config, runs Claude agent, measures results
2. `run-all.sh` orchestrates batches across all task x treatment combinations
3. `analyze.py` reads all metrics.json files and generates comparison tables (detail, summary, integrity)

## Treatment System

Each treatment is a directory under `bench/treatments/` with a `treatment.yaml`:
```yaml
name: "treatment-name"
description: "What this treatment tests"
claude_md: "CLAUDE.md"        # or null
context_files: ["context.md"]  # or []
setup_script: "setup.sh"      # optional: creates catalog, MCP config, hooks
pre_prompt: "instruction text" # optional: injected before task prompt
```

Treatments range from simple (baseline: nothing added) to complex (full-bdd: catalog + MCP tools + PostToolUse hooks + coverage index).
