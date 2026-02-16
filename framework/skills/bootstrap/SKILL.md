---
name: bootstrap
description: Use to set up a new project for BDD development. Creates catalog, test runner, and fills in CLAUDE.md project details.
user-invocable: true
allowed-tools: Bash, Read, Edit, Write, Glob, Grep
---

Bootstrap a project for BDD development.

## Steps

1. **Run setup**: Run `bdd setup` (or `bdd setup <project-dir>`) to create the framework files, catalog, bdd.json template, and .mcp.json.

2. **Detect project type**: Look at the project files to determine the tech stack:
   - Check for `Cargo.toml` (Rust), `package.json` (Node), `pyproject.toml`/`setup.py` (Python), `go.mod` (Go), etc.
   - Check for existing test infrastructure

3. **Set up test directory**: Create a `tests/` directory (if it doesn't exist) for behavior tests.

4. **Set up native test infrastructure with per-test coverage**: Based on the detected project type, configure behavior tests using the project's native test framework and per-test coverage tool:

   - **Python**: Create `tests/test_behavior.py` using pytest. Install `pytest-cov`.
   - **Rust**: Create `tests/behavior.rs` (integration tests). Install `cargo-llvm-cov`.
   - **Node.js**: Create `tests/behavior.test.js` using jest or vitest.
   - **Go**: Create `tests/behavior_test.go`.

   Each behavior test must:
   - Launch or invoke the FULL program (not isolated units)
   - Validate behavior from the user's perspective
   - Be linked to a catalog facet via `bdd_link`

   Coverage collection is CRITICAL infrastructure. It is NOT optional. Per-test coverage enables line-level mapping from source code back to the facets and expectations that justify its existence.

5. **Configure bdd.json**: Edit `bdd.json` with the correct test command, results format/file, and coverage format/file for the project. See `.claude/rules/setup.md` for language-specific examples.

6. **Fill in CLAUDE.md**: Edit `.claude/CLAUDE.md` to fill in the Project Details section:
   - Stack (detected from step 2)
   - Build command
   - Test command (configured via `bdd.json`)
   - Key paths

7. **Verify pipeline**: Call `bdd_test()` to verify that:
   - Tests execute and produce results
   - Facet statuses are updated automatically
   - The index is built with motivation mapping

8. **Consider introspection**: If the project has a visual or interactive component, suggest building an introspection service (reference `.claude/rules/introspection.md`).

9. **Seed initial expectations**: Ask the user what they want the project to do, then use `/suggest` to populate the catalog.

10. **Report**: Call `bdd_status()` and `bdd_tree()` to confirm the setup.
