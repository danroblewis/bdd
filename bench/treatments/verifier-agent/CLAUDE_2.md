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

## MANDATORY WORKFLOW

### Step 1: Read tests first
Read `tests/test_taskboard.py` to understand all expected behavior.

### Step 2: Implement changes
Implement across all layers (model -> store -> CLI -> display -> tests).

### Step 3: Verify with the verifier agent
After implementing, delegate to the `verifier` agent to run tests and get diagnostic feedback:

```
Task(verifier, "Run all tests, analyze any failures, and tell me exactly what needs to be fixed.")
```

### Step 4: Fix issues
Follow the verifier's feedback to fix any failing tests. Repeat steps 3-4 until all tests pass.

## Source Layout

| File | Purpose |
|------|---------|
| `src/taskboard/models.py` | `Task` dataclass |
| `src/taskboard/store.py` | `TaskStore` — JSON file persistence with `fcntl` locking |
| `src/taskboard/cli.py` | `build_parser()` + subcommand handlers + `commands` dispatch dict |
| `src/taskboard/display.py` | `format_task()` + `format_table()` with ANSI colors |
| `tests/test_taskboard.py` | Regression suite |

## Rules

- **NEVER delete or modify existing tests.**
- Every `args.X` in a handler needs a matching `add_argument()` in `build_parser()`
- New commands must be added to the `commands` dict in `main()`
