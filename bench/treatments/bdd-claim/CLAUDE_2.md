# ADK Playground

A web UI for building and testing Google ADK agents, with a Python FastAPI backend.

## Stack & Architecture

- **Python 3.11+** with **FastAPI** backend
- **pytest** + **pytest-asyncio** for testing
- Entry point: `uvicorn backend.main:app`

### Source Layout

| File | Purpose |
|------|---------|
| `backend/models.py` | Pydantic models: Project, AgentConfig (LLM/Sequential/Loop/Parallel), ToolConfig, EvalSet, RunEvent, etc. |
| `backend/project_manager.py` | `ProjectManager` — YAML project persistence, backup/restore, custom tool/callback file generation. |
| `backend/code_generator.py` | `generate_python_code(project)` — transforms Project config into executable Python using ADK SDK. |
| `backend/runtime.py` | `RuntimeManager` — executes generated agent code, `TrackingPlugin` for event tracking, service factory functions. |
| `backend/main.py` | FastAPI app with REST/WebSocket endpoints for project CRUD, agent execution, eval, model listing, MCP tools. |
| `backend/evaluation_service.py` | `EvaluationService` — ROUGE scoring, trajectory matching, LLM-as-judge evaluation. |
| `backend/adk_evaluation_service.py` | Bridge layer converting Playground eval format to ADK's native `LocalEvalService`. |
| `backend/model_service.py` | `list_all_models()` — discovers models from Gemini, Anthropic, OpenAI, Groq, Together, Ollama providers. |
| `backend/knowledge_service.py` | `KnowledgeServiceManager`, `SkillSetStore` — vector embeddings and semantic search for agent knowledge. |
| `backend/known_mcp_servers.py` | `KNOWN_MCP_SERVERS` registry and `load_mcp_servers_from_file()` for MCP server discovery. |
| `backend/skillset.py` | `SkillSet` toolset — `SearchSkillSetTool` for semantic search, knowledge preloading into agent instructions. |
| `backend/sandbox/` | Docker sandbox: `SandboxManager`, `MCPContainerManager`, network allowlist, webhook handler. |
| `tests/` | 5 test files + conftest.py: test_callbacks, test_integration, test_project_parsing, test_runtime, test_sample_projects. |

### Patterns

- **FastAPI routing:** Endpoints in `main.py` call service modules (project_manager, runtime, evaluation_service) — routes are thin dispatchers
- **Service layer:** Business logic lives in service modules (project_manager.py, evaluation_service.py, runtime.py), not in route handlers
- **Code generation pipeline:** Project config (YAML/Pydantic) → `code_generator.generate_python_code()` → `runtime.RuntimeManager._execute_generated_code()`
- **Adding a new feature:** Add Pydantic model if needed → add service method → add FastAPI route → add tests

## Workflow — Claim Before You Change

**IMPORTANT: Before modifying any source file, you MUST identify which catalog facet(s) you are about to affect.**

1. **Read the task prompt** to understand what to implement
2. **Use `bdd_motivation(file_path)`** on any file you plan to modify — this tells you which facets map to that file and why the code exists
3. **Use `bdd_locate(facet_id)`** to find where a specific facet is implemented, confirming you're editing the right code
4. **State which facet you're implementing** before each edit — e.g. "I'm modifying f-001 (cmd_add parser) to add the --search flag"
5. **Implement the change** across all layers (model -> store -> CLI -> display -> tests)
6. **Run `bdd_test()`** to execute tests, rebuild the index, and update catalog statuses
7. **Use `bdd_next()`** to find remaining work if multiple changes are needed

### Why claim first?

The catalog tracks stakeholder intent. By identifying which facet you're touching *before* you edit, you:
- Confirm you're changing the right code for the right reason
- Avoid accidentally breaking unrelated behavior
- Keep your changes aligned with what stakeholders actually want

If you're adding **new** functionality that doesn't map to an existing facet, use `bdd_add` to create a new facet first, then proceed.

## Completion Checklist

- New endpoints are added to `main.py` with proper HTTP methods and status codes
- Service logic goes in the appropriate service module, not in route handlers
- Pydantic models for request/response bodies are defined in `models.py`
- Service methods handle the not-found case (raise HTTPException(404) or return None)
- All existing tests still pass (regression)
- New functionality has tests

## Available MCP Tools

| Tool | Description |
|------|-------------|
| `bdd_status(check?)` | Catalog summary: counts, progress, unsatisfied expectations. Pass `check="all"` for health diagnostics. |
| `bdd_motivation(file_path)` | **Use before editing.** Shows which facets map to a file and why the code exists. |
| `bdd_next()` | Find what to work on next — returns the highest-priority unsatisfied facet. |
| `bdd_locate(node_id)` | Find implementation files and line ranges for a facet or expectation. |
| `bdd_test()` | Run full test suite, parse results + coverage, rebuild index, update facet statuses. |
| `bdd_add(type, text, parent?, ...)` | Add a goal, expectation, or facet to the catalog. |
| `bdd_link(facet_id, test_id)` | Connect a facet to a test identifier (e.g. `tests/test_foo.py::test_bar`). |
