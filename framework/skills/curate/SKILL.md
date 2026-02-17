---
name: curate
description: Use at the start of a session or after completing a feature to audit alignment between tests and catalog. Use proactively.
user-invocable: true
allowed-tools: Read, Grep, Glob
---

Audit the alignment between behavior tests and the BDD catalog.

## Steps

1. Call `bdd_check()` to scan for catalog issues (orphans, contradictions, overloaded tests, status mismatches).

2. Call `bdd_tree()` to see the full catalog with statuses.

3. Call `bdd_status()` to get summary numbers.

4. Find behavior test files in the project's test directory.

5. Produce three lists:

   **Covered** — Facets with status `passing` that have linked tests.

   **Uncovered** — Facets with status `untested` or no linked test. These need behavior tests written.

   **Orphaned** — Test files that don't correspond to any facet in the catalog. These are candidates for removal or for adding corresponding facets.

6. For each uncovered facet, suggest a test filename and brief outline of what the test would assert.

7. For each orphaned test, ask whether the corresponding expectation was removed intentionally or should be re-added.

8. Look for expectations without facets — these need decomposition.

9. Summarize: N covered, N uncovered, N orphaned, N expectations needing decomposition.
