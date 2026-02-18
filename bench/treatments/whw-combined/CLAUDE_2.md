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

## Workflow — FOLLOW THIS ORDER

1. **Read tests first.** Open `tests/test_taskboard.py` and understand what every existing test expects.
2. **Read the task prompt** to understand what to implement.
3. **Read the relevant source files** to understand the current code.
4. **Implement the change** across all layers (model -> store -> CLI -> display -> tests).
5. **Run tests after every change** using the `bdd_test()` MCP tool.
6. **If tests fail, fix your implementation** — never modify or delete existing tests.
7. **Add tests for new functionality** that follow the same patterns as existing tests.

## Rules

- **NEVER delete or modify existing tests.** They are the specification.
- **NEVER skip or mark tests as expected failures.**
- If a test fails after your change, your code is wrong — fix the code, not the test.
- Every `args.X` reference in a command handler needs a matching `add_argument()` in `build_parser()`.
- New commands must be added to the `commands` dict in `main()`.
- Store methods must handle the not-found case (return None or False).

## Test Command

Use `bdd_test()` MCP tool to run tests. It runs the full suite and reports results.

