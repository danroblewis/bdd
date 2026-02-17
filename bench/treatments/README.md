# Treatment Inventory

Summary of all benchmark treatments and their external capabilities.

| Treatment | MCP Tools | Hooks | Subagents | Pre-prompt | Context Files | External? |
|---|---|---|---|---|---|---|
| **baseline** | - | - | - | - | - | No |
| **claude-md** | - | - | - | - | CLAUDE.md | No |
| **why-how-what** | - | - | - | - | context.md | No |
| **targeted** | - | - | - | - | per-task .md | No |
| **whw-plus-pre-prompt** | - | - | - | test-first | context.md | No |
| **whw-plus-catalog-inline** | - | - | - | - | context.md + catalog.md | No |
| **pre-prompt-behavioral** | - | - | - | stakeholder | - | No |
| **test-first-workflow** | - | - | - | - | CLAUDE.md | No |
| **edit-guard** | - | PreTool (block edits), PostTool (read flag) | - | test-first | context.md + CLAUDE.md | Hooks only |
| **regression-feedback** | - | PostTool (auto-run tests on edit) | - | test-first | context.md + CLAUDE.md | Hooks only |
| **review-before-stop** | - | Stop (enhanced test+diff gate) | - | test-first | context.md + CLAUDE.md | Hooks only |
| **planner-agent** | - | - | planner (sonnet, read-only) | test-first | context.md + CLAUDE.md | Subagent |
| **prompt-decompose** | - | - | decomposer (sonnet, read-only) | test-first | context.md + CLAUDE.md | Subagent |
| **verifier-agent** | - | - | verifier (haiku, runs tests) | test-first | context.md + CLAUDE.md | Subagent |
| **full-bdd** | bdd_status, bdd_locate, bdd_test, bdd_add, bdd_link | Read + Write/Edit (cobertura index) | - | - | CLAUDE.md | MCP + Hooks |
| **bdd-autodetect** | same as full-bdd | Read + Write/Edit (cobertura index) | - | - | CLAUDE.md | MCP + Hooks |
| **bdd-claim** | + bdd_motivation, bdd_locate | Read only (cobertura index) | - | - | CLAUDE.md | MCP + Hooks |
| **bdd-fine-index** | bdd_status, bdd_locate, bdd_test, bdd_add, bdd_link | Read + Write/Edit (fine coverage-json) | - | - | CLAUDE.md | MCP + Hooks |
| **bdd-fine-no-hooks** | + bdd_motivation, bdd_locate | - | - | - | CLAUDE.md | MCP only |
| **pre-prompt-fine-index** | bdd_status, bdd_locate, bdd_test, bdd_add, bdd_link | Read + Write/Edit (fine coverage-json) | - | test-first | CLAUDE.md | MCP + Hooks |
| **whw-plus-bdd-test** | bdd_test only | - | - | - | context.md + CLAUDE.md | MCP (minimal) |
| **whw-combined** | bdd_test only | - | - | test-first | context.md + CLAUDE.md | MCP (minimal) |

## Categories

**Static only (no external systems):** baseline, claude-md, why-how-what, targeted, whw-plus-pre-prompt, whw-plus-catalog-inline, pre-prompt-behavioral, test-first-workflow

**Hooks only (no MCP/catalog):** edit-guard, regression-feedback, review-before-stop

**Subagents only (no MCP/catalog):** planner-agent, prompt-decompose, verifier-agent

**MCP + BDD catalog:** full-bdd, bdd-autodetect, bdd-claim, bdd-fine-index, bdd-fine-no-hooks, pre-prompt-fine-index, whw-plus-bdd-test, whw-combined
