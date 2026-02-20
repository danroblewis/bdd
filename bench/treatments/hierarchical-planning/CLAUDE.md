# Implementation Guide

A planning team has already analyzed the task, the codebase, and the design catalog. Their output is in the `.planning/` directory. Your job is to execute the plan.

## Before You Start

1. **Read `.planning/implementation-plan.md`** — this is your primary guide. It contains the exact steps, files, functions, and behaviors to implement, in dependency order.
2. Optionally skim `.planning/expectations.md` (what the user needs) and `.planning/goals-alignment.md` (architectural context) if you need background on WHY something is being done.
3. Read `prompt.txt` if you need the original task description.

## Workflow

1. Follow the implementation plan step by step, in the order specified
2. For each step: read the target file, make the change, move to the next step
3. After completing all steps, write the tests described in the Test Plan section
4. Run `bdd_test()` to verify all tests pass (both new and regression)
5. If tests fail, fix issues and re-run `bdd_test()`

## Rules

- **Follow the plan** — the planning team already analyzed the architecture, patterns, and risks. Do not redesign.
- **Respect existing patterns** — the plan specifies which patterns to follow. Match them exactly.
- **Check the regression checklist** — the plan lists specific existing tests and behaviors that must not break.
- **Do not skip steps** — each step may be a dependency for later steps.

## Available MCP Tools

| Tool | Description |
|------|-------------|
| `bdd_status(check?)` | Catalog summary: counts, progress, unsatisfied expectations. |
| `bdd_locate(node_id)` | Find implementation files and line ranges for a facet or expectation. |
| `bdd_test()` | Run full test suite, parse results + coverage, rebuild index, update facet statuses. |
| `bdd_add(type, text, parent?, ...)` | Add a goal, expectation, or facet to the catalog. |
| `bdd_link(facet_id, test_id)` | Connect a facet to a test identifier. |
