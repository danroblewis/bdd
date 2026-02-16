# Behavior Test Curation Methodology

You are developing under a behavior-test-curation methodology called **Emergent Alignment**. The product converges toward stakeholder intent through curation of a living catalog — not through spec documents or upfront design.

## The Catalog

The `catalog.json` file is the single source of truth. It contains three node types in a hierarchy:

- **Goals** — broad stakeholder intent (e.g., "The game should feel responsive")
- **Expectations** — specific wants under a goal (e.g., "Controls respond within one frame")
- **Facets** — testable pieces under an expectation (e.g., "pressing A produces visual feedback by next render")

Status flows upward: facets have explicit status (untested/failing/passing), and expectations and goals are satisfied when ALL their descendant facets are passing.

## Process

1. **Capture** — Humans express what they want. You add goals and expectations to the catalog using `bdd_add`. Act immediately, human prunes later.
2. **Decompose** — Break expectations into testable facets. Each facet tests ONE specific behavior from the user's perspective.
3. **Express** — Write behavior tests for each facet using the project's native test framework (pytest, cargo test, jest, go test, etc.). Each test exercises the FULL program — launching or invoking the complete application, not isolated units. Link tests with `bdd_link`. Every test run MUST collect per-test code coverage.
4. **Curate** — Humans add, remove, and reprioritize. The catalog is always the truth. When expectations are removed, corresponding tests and code can be simplified.
5. **Respond** — Write code to make the current test suite pass. The agent loop picks up unsatisfied expectations via `bdd_next`.

## Your Role

- Write and modify code to make behavior tests pass
- Decompose expectations into facets when they don't have them yet
- Write behavior tests for untested facets
- Call `bdd_test` after changes to run tests, update statuses, and rebuild the index
- Never write code that isn't motivated by a catalog entry
- When you see related unaddressed concerns, propose new expectations

## What NOT to Do

- Do not create spec documents or design documents
- Do not write unit tests for internal implementation details (behavior tests only)
- Do not resist architectural changes — the test suite defines correctness, not the architecture
- Do not keep code alive just because it exists — if no test or expectation requires it, it can go
- Do not modify catalog.json directly — always use the MCP tools

## Priority

Work is prioritized by the `priority` field on expectations (lower number = higher priority). `bdd_next` returns the highest-priority unsatisfied expectation. Trust the priority ordering — it reflects stakeholder intent.

## Coverage

Per-test code coverage collection is mandatory infrastructure, not optional. The `bdd_test` tool handles running tests and building the index automatically.

The index (`.bdd/index.json`) has line-level granularity: it maps each source file line to the specific facet IDs whose tests exercise that line. This creates a living map of WHY each line of code exists — which stakeholder behaviors it supports.

When the agent reads a source file, the inject-context hook looks up the lines being read in the index and surfaces the motivation chain (goal > expectation > facet). The agent can also call `bdd_motivation` directly for any file.

Without coverage, the motivation chain from source code back to stakeholder intent is broken, and the agent is working blind.
