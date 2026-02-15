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

4. **Create test runner**: Create a `tests/run_all.sh` script that:
   - Finds and runs all behavior test scripts (`tests/test_*.sh`)
   - Reports pass/fail for each
   - Exits non-zero if any test fails

5. **Fill in CLAUDE.md**: Edit `.claude/CLAUDE.md` to fill in the Project Details section:
   - Stack (detected from step 2)
   - Build command
   - Test command (`./tests/run_all.sh`)
   - Key paths

6. **Update settings.json**: Add project-specific Bash permissions to `.claude/settings.json`:
   - Build commands (e.g., `Bash(cargo build*)`, `Bash(npm run*)`)
   - Test commands (e.g., `Bash(./tests/run_all.sh*)`)
   - Any project-specific tools

7. **Consider introspection**: If the project has a visual or interactive component, suggest building an introspection service (reference `.claude/rules/introspection.md`).

8. **Seed initial expectations**: Ask the user what they want the project to do, then use `/suggest` to populate the catalog.

9. **Report**: Show `bdd status` and `bdd tree` to confirm the setup.
