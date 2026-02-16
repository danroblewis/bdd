---
name: curate
description: Use at the start of a session or after completing a feature to audit alignment between tests and catalog. Use proactively.
user-invocable: true
allowed-tools: Read, Grep, Glob
---

Audit the alignment between behavior tests and the BDD catalog.

## Steps

1. Call `bdd_tree()` to see the full catalog with statuses.

2. Call `bdd_status()` to get summary numbers.

3. Find behavior test files in the project's test directory.

4. Produce three lists:

   **Covered** — Facets with status `passing` that have linked tests.

   **Uncovered** — Facets with status `untested` or no linked test. These need behavior tests written.

   **Orphaned** — Test files that don't correspond to any facet in the catalog. These are candidates for removal or for adding corresponding facets.

5. For each uncovered facet, suggest a test filename and brief outline of what the test would assert.

6. For each orphaned test, ask whether the corresponding expectation was removed intentionally or should be re-added.

7. Look for expectations without facets — these need decomposition.

8. Summarize: N covered, N uncovered, N orphaned, N expectations needing decomposition.
