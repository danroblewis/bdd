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

## Workflow: Scout First, Then Implement

You have 3 scout agents available that will analyze the codebase from different angles. Launch them ALL in parallel FIRST, then use their briefings to guide your implementation.

### Phase 1: Launch Scouts (parallel)
Launch all 3 scouts at the same time using the Task tool:

1. **Scout-Architecture**: Analyzes catalog.json and source files to explain WHY each module exists, what design patterns it follows, and how modules connect through shared motivations.
2. **Scout-Impact**: Reads your task prompt and catalog.json to identify which existing motivations your feature will touch, extend, or coexist with.
3. **Scout-Patterns**: Reads all source files to identify recurring code patterns (dispatch, CRUD, display) and notes which catalog expectations motivated each pattern.

### Phase 2: Read Briefings
After all 3 scouts complete, read their outputs carefully. They contain:
- An architecture motivation map (which module serves which goal)
- An impact analysis (which existing expectations you need to respect)
- A pattern guide (how to follow existing conventions)

### Phase 3: Implement
With the scouts' analysis in mind:
4. Implement changes following the patterns identified by Scout-Patterns
5. Respect the expectations identified by Scout-Impact
6. Follow the module boundaries explained by Scout-Architecture
7. Work in order: model → store → CLI → display

### Phase 4: Verify
8. Call `bdd_test()` to run tests and verify everything passes

## Available Agents

| Agent | Purpose | Tools |
|-------|---------|-------|
| `scout-architecture` | Map module responsibilities to catalog motivations | Read, Glob |
| `scout-impact` | Identify which motivations the new feature touches | Read, Grep |
| `scout-patterns` | Extract recurring code patterns and their motivations | Read, Glob |

## Available MCP Tools

| Tool | Description |
|------|-------------|
| `bdd_status(check?)` | Catalog summary: counts, progress, unsatisfied expectations. |
| `bdd_locate(node_id)` | Find implementation files and line ranges for a facet or expectation. |
| `bdd_test()` | Run full test suite, parse results + coverage, rebuild index, update facet statuses. |
| `bdd_add(type, text, parent?, ...)` | Add a goal, expectation, or facet to the catalog. |
| `bdd_link(facet_id, test_id)` | Connect a facet to a test identifier. |

## Completion Checklist

- New endpoints are added to `main.py` with proper HTTP methods and status codes
- Service logic goes in the appropriate service module, not in route handlers
- Pydantic models for request/response bodies are defined in `models.py`
- Service methods handle the not-found case (raise HTTPException(404) or return None)
- All existing tests still pass (regression)
- New functionality has tests
