---
name: bootstrap
description: Use to set up a new project for BDD development. Creates catalog, test runner, and fills in CLAUDE.md project details.
user-invocable: true
allowed-tools: Bash, Read, Edit, Write, Glob, Grep
---

Bootstrap a project for BDD development.

## Steps

1. **Initialize catalog**: Run `bdd init` to create an empty `catalog.json`.

2. **Detect project type**: Look at the project files to determine the tech stack:
   - Check for `Cargo.toml` (Rust), `package.json` (Node), `pyproject.toml`/`setup.py` (Python), `go.mod` (Go), etc.
   - Check for existing test infrastructure

3. **Set up test directory**: Create a `tests/` directory (if it doesn't exist) for behavior tests.

4. **Set up native test infrastructure with per-test coverage**: Based on the detected project type, configure behavior tests using the project's native test framework and per-test coverage tool:

   - **Python**: Create `tests/test_behavior.py` using pytest. Install `pytest-cov`. Test command: `pytest tests/ --cov=<source_pkg> --cov-context=test --cov-report=json:coverage.json && bdd coverage --file coverage.json`
   - **Rust**: Create `tests/behavior.rs` (integration tests). Install `cargo-llvm-cov`. Test command: `cargo llvm-cov --lcov --output-path coverage.lcov && bdd coverage --file coverage.lcov`
   - **Node.js**: Create `tests/behavior.test.js` using jest or vitest. Use `NODE_V8_COVERAGE` for per-test data. Test command: `NODE_V8_COVERAGE=.coverage npx jest && bdd coverage --dir .coverage`
   - **Go**: Create `tests/behavior_test.go`. Test command: `go test -coverprofile=coverage.out ./... && bdd coverage --file coverage.out --format lcov`

   Each behavior test must:
   - Launch or invoke the FULL program (not isolated units)
   - Validate behavior from the user's perspective
   - Be linked to a catalog facet via `bdd link`

   Coverage collection is CRITICAL infrastructure. It is NOT optional. Per-test coverage enables line-level mapping from source code back to the facets and expectations that justify its existence.

5. **Fill in CLAUDE.md**: Edit `.claude/CLAUDE.md` to fill in the Project Details section:
   - Stack (detected from step 2)
   - Build command
   - Test command (the full native test + per-test coverage + `bdd coverage` pipeline from step 4)
   - Key paths

6. **Update settings.json**: Add project-specific Bash permissions to `.claude/settings.json`:
   - Build commands (e.g., `Bash(cargo build*)`, `Bash(npm run*)`)
   - Test commands (e.g., `Bash(pytest*)`, `Bash(cargo test*)`, `Bash(cargo llvm-cov*)`)
   - Coverage commands (e.g., `Bash(bdd coverage*)`)
   - Any project-specific tools

7. **Verify coverage pipeline**: Run the test command once to verify that:
   - Tests execute and produce a per-test coverage report
   - `bdd coverage` successfully parses the report and creates `coverage_map.json`
   - `bdd related <some-source-file>` returns line-level results

8. **Consider introspection**: If the project has a visual or interactive component, suggest building an introspection service (reference `.claude/rules/introspection.md`).

9. **Seed initial expectations**: Ask the user what they want the project to do, then use `/suggest` to populate the catalog.

10. **Report**: Show `bdd status` and `bdd tree` to confirm the setup.
