---
name: bdd
description: Learn the BDD catalog methodology — how to use MCP tools to understand why code exists, find what to work on, and trace every change to stakeholder intent.
user-invocable: true
allowed-tools: Read, Glob, Grep
---

BDD Catalog Methodology — quick reference for agents.

## The Hierarchy

The catalog (`catalog.json`) maps stakeholder intent to testable behavior:

- **Goals** — broad stakeholder intent (e.g., "The game should feel responsive")
- **Expectations** — specific wants under a goal (e.g., "Controls respond within one frame")
- **Facets** — testable pieces under an expectation (e.g., "pressing A produces visual feedback by next render")

Status flows upward: facets have explicit status (untested/failing/passing). An expectation is satisfied when ALL its facets are passing.

## Why This Matters

Without the catalog, you're guessing at intent. The catalog tells you:
- **What to build** — unsatisfied expectations, ordered by priority
- **Why code exists** — every source line traces back to a facet, expectation, and goal
- **What's safe to change** — if no facet covers it, it's dead weight

## Your MCP Tools

You have 8 tools available:

### Understanding Context
- **`bdd_motivation(file, start_line?, end_line?)`** — Call this when reading unfamiliar code. It returns the goal > expectation > facet chain explaining WHY those lines exist.
- **`bdd_locate(node_id)`** — Given a facet or expectation ID, find which files and lines implement it.
- **`bdd_tree()`** — See the full catalog hierarchy with statuses.
- **`bdd_status()`** — Counts, progress percentage, satisfied/unsatisfied expectations.

### Finding Work
- **`bdd_next()`** — Returns the highest-priority unsatisfied expectation with its facets and parent goal context. This is what to work on.

### Modifying the Catalog
- **`bdd_add(node_type, text, parent?, priority?, labels?)`** — Add a goal, expectation, or facet. Act immediately; humans prune later.
- **`bdd_link(facet_id, test_id)`** — Connect a facet to its test identifier (e.g., `tests/test_calc.py::test_add`).

### Running Tests
- **`bdd_test()`** — Run the test suite, parse results and coverage, rebuild the index, return summary. Call this after making changes.

## Workflow

1. **Starting a session**: Call `bdd_next()` to find what to work on.
2. **Reading code**: Call `bdd_motivation(file)` to understand why it exists before changing it.
3. **Planning changes**: Call `bdd_locate(facet_id)` to find what files to modify.
4. **Decomposing work**: If an expectation has no facets, use `bdd_add("facet", ...)` to break it into testable pieces.
5. **Linking tests**: After writing a test, use `bdd_link(facet_id, test_id)` to connect it.
6. **Verifying**: Call `bdd_test()` after changes to update the index and confirm progress.

## Rules

- **Every code change should trace to a catalog entry.** If you can't point to a facet, you're probably doing speculative work.
- **Write behavior tests, not unit tests.** Tests should exercise the full program from the user's perspective.
- **Act then review.** When the human describes what they want, add expectations immediately. The human prunes.
- **Trust priority ordering.** `bdd_next()` returns work in priority order. Follow it.
- **Coverage is mandatory infrastructure.** Per-test coverage enables the motivation mapping from code back to intent. Without it, you're working blind.
