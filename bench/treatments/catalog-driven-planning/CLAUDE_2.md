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

## Workflow: Think in Goals, Then Code

You have a BDD catalog that describes WHY this project's code exists. Your workflow is to FIRST understand the existing motivations, THEN articulate your own intent in catalog terms, THEN implement.

### Phase 1: Understand Existing Motivations
1. Call `bdd_tree()` to see the full goal → expectation → facet hierarchy
2. Call `bdd_motivation("src/taskboard/cli.py")` (and other source files) to understand why each module is structured the way it is
3. Read the source files — understand how the existing code serves its catalog motivations

### Phase 2: Articulate Your Intent
Before writing ANY code:
4. Use `bdd_add(type="expectation", text="...", parent="g-001")` to create a new expectation describing what the user wants from your feature
5. Use `bdd_add(type="facet", text="...", parent="<your-expectation-id>")` to create facets — one per testable piece:
   - One facet per new CLI command or argument
   - One facet per new store method or query
   - One facet per display change
6. Call `bdd_tree()` again to review your plan — your new nodes should fit naturally alongside the existing ones

### Phase 3: Implement
7. Work through your facets in order: model → store → CLI → display
8. Call `bdd_test()` after major changes to run tests and update statuses

### Phase 4: Verify Alignment
9. Call `bdd_status()` — your new facets should show progress
10. Call `bdd_tree(status_filter="unsatisfied")` — ideally empty when done

## Available MCP Tools

| Tool | When to Use | Description |
|------|-------------|-------------|
| `bdd_tree(node_id?, status_filter?, max_depth?)` | Phase 1 & 2: understand and review your plan | Show catalog hierarchy. Use `status_filter="unsatisfied"` to see what's left. |
| `bdd_motivation(file, start_line?, end_line?)` | Phase 1: understand why code exists | Returns goal→expectation→facet chains for code in a file. |
| `bdd_add(type, text, parent?, priority?, labels?)` | Phase 2: articulate your intent | Add goal, expectation, or facet. Types: "goal", "expectation", "facet". |
| `bdd_link(facet_id, test_id)` | Phase 3: connect facets to tests | Link a facet to a test identifier after writing tests. |
| `bdd_status(check?)` | Phase 4: verify alignment | Catalog summary with progress. Use `check="all"` for health diagnostics. |
| `bdd_locate(node_id)` | Any phase: find implementation | Files and line ranges for a facet or expectation. |
| `bdd_test()` | Phase 3 & 4: run tests | Run test suite, rebuild index, update facet statuses. |
| `bdd_next()` | Phase 3: find next work item | Returns highest-priority unsatisfied expectation. |

## Completion Checklist

- New endpoints are added to `main.py` with proper HTTP methods and status codes
- Service logic goes in the appropriate service module, not in route handlers
- Pydantic models for request/response bodies are defined in `models.py`
- Service methods handle the not-found case (raise HTTPException(404) or return None)
- All existing tests still pass (regression)
- New functionality has tests
