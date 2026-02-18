# Project Instructions

This project uses **Behavior-Driven Development** with a catalog-first methodology. The catalog (`catalog.json`) is the single source of truth for stakeholder intent.

## Design Context System

When you read or edit source files, you'll see **design notes** — natural-language explanations of why the code exists and what design decisions it reflects. These read like a senior developer's comments, not data structures.

**On Read**: You'll see which user expectations the code implements, what patterns it follows, and why it was designed that way.

**On Write/Edit**: You'll see what user expectations your change affects and which other files share those expectations (so you can check for breakage). Edits are logged to `.bdd/edit_log.json`.

These notes are generated from the project's motivation catalog. Trust them for architectural guidance.

## Catalog Structure

The catalog contains three levels:
- **Goals** — broad stakeholder intent (what the system should achieve)
- **Expectations** — specific user-facing wants under each goal
- **Facets** — testable implementation details linked to test cases

Every code change should trace to a catalog entry.

## Workflow

1. **Read source files** — design notes appear automatically explaining why each module exists and what patterns to follow
2. **Implement changes** — post-edit notes tell you what expectations you affected and what else to check
3. **Run `bdd_test()`** to execute tests, rebuild the index, and update catalog statuses
4. Repeat until all relevant facets pass

## Rules

- **ALWAYS use `bdd_test` to run tests.** Never run the test command directly. `bdd_test` runs the tests AND updates facet statuses and the motivation index. Running tests any other way leaves the catalog stale.
- Every code change should trace to a catalog entry.
- Write behavior tests (full program, user perspective), not unit tests.

## Available MCP Tools

| Tool | Description |
|------|-------------|
| `bdd_test()` | Run full test suite, parse results + coverage, rebuild index, update facet statuses. |
| `bdd_status(check?)` | Catalog summary: counts, progress, unsatisfied expectations. Pass `check="all"` for health diagnostics. |
| `bdd_locate(node_id)` | Find implementation files and line ranges for a facet or expectation. |
| `bdd_add(type, text, parent?, ...)` | Add a goal, expectation, or facet to the catalog. |
| `bdd_link(facet_id, test_id)` | Connect a facet to a test identifier. |
