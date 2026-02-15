# Behavior Test Curation Methodology

You are developing under a behavior-test-curation methodology called **Emergent Alignment**. The product converges toward stakeholder intent through curation of a living catalog — not through spec documents or upfront design.

## The Catalog

The `catalog.json` file is the single source of truth. It contains three node types in a hierarchy:

- **Goals** — broad stakeholder intent (e.g., "The game should feel responsive")
- **Expectations** — specific wants under a goal (e.g., "Controls respond within one frame")
- **Facets** — testable pieces under an expectation (e.g., "pressing A produces visual feedback by next render")

Status flows upward: facets have explicit status (untested/failing/passing), and expectations and goals are satisfied when ALL their descendant facets are passing.

## Process

1. **Capture** — Humans express what they want. You add goals and expectations to the catalog using `bdd add`. Act immediately, human prunes later.
2. **Decompose** — Break expectations into testable facets. Each facet tests ONE specific behavior from the user's perspective.
3. **Express** — Write behavior tests for each facet. Link them with `bdd link`. Tests are shell scripts that exit 0 on pass.
4. **Curate** — Humans add, remove, and reprioritize. The catalog is always the truth. When expectations are removed, corresponding tests and code can be simplified.
5. **Respond** — Write code to make the current test suite pass. The agent loop picks up unsatisfied expectations via `bdd next`.

## Your Role

- Write and modify code to make behavior tests pass
- Decompose expectations into facets when they don't have them yet
- Write behavior tests for untested facets
- Update facet statuses after running tests (`bdd mark`)
- Never write code that isn't motivated by a catalog entry
- When you see related unaddressed concerns, propose new expectations

## What NOT to Do

- Do not create spec documents or design documents
- Do not write unit tests for internal implementation details (behavior tests only)
- Do not resist architectural changes — the test suite defines correctness, not the architecture
- Do not keep code alive just because it exists — if no test or expectation requires it, it can go
- Do not modify catalog.json directly — always use the `bdd` CLI

## Priority

Work is prioritized by the `priority` field on expectations (lower number = higher priority). The `bdd next` command returns the highest-priority unsatisfied expectation. Trust the priority ordering — it reflects stakeholder intent.
