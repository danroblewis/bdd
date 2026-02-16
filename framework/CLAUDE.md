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

## Project Details

<!-- Fill these in during /bootstrap or manually -->

**Stack:** (describe your tech stack)

**Build:**
```bash
# build command here
```

**Test:**
```bash
# configured via bdd.json, run with bdd_test MCP tool
```

**Key Paths:**
- (list important source directories and files)
