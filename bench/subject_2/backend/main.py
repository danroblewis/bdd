"""FastAPI backend for ADK Playground."""

from __future__ import annotations

import asyncio
import json
import time
import logging
import os
import platform
import re
import subprocess
import sys
import uuid

logger = logging.getLogger(__name__)
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from models import (
    Project, AppConfig, AgentConfig, LlmAgentConfig, SequentialAgentConfig,
    LoopAgentConfig, ParallelAgentConfig, CustomToolDefinition, MCPServerConfig,
    RunEvent, EvalSet, EvalCase, EvalInvocation, ExpectedToolCall,
    EvalSetResult, EvalCaseResult, InvocationResult, ToolTrajectoryMatchType,
    EvalConfig, EvalMetricConfig, EvalMetricType, EvalCriterion, JudgeModelOptions,
    MetricResult, Rubric, EnabledMetric,
)
from project_manager import ProjectManager
from runtime import RuntimeManager
from known_mcp_servers import KNOWN_MCP_SERVERS, BUILTIN_TOOLS
from agent_runner import run_agent, clean_code_output, extract_json_from_text

# Import sandbox API router
try:
    from sandbox.api import router as sandbox_router
    SANDBOX_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Sandbox module not available: {e}")
    SANDBOX_AVAILABLE = False
    sandbox_router = None

# Get projects directory from environment variable, default to ~/.adk-playground/projects
# This can be overridden by setting ADK_PLAYGROUND_PROJECTS_DIR environment variable
# or by passing --projects-dir command line argument (handled in adk_playground/__init__.py)
_projects_dir_env = os.environ.get("ADK_PLAYGROUND_PROJECTS_DIR")
if _projects_dir_env:
    PROJECTS_DIR = Path(_projects_dir_env)
else:
    PROJECTS_DIR = Path.home() / ".adk-playground" / "projects"
PROJECTS_DIR.mkdir(parents=True, exist_ok=True)

# Initialize managers
project_manager = ProjectManager(str(PROJECTS_DIR))
runtime_manager = RuntimeManager(str(PROJECTS_DIR))


# ============================================================================
# MCP Connection Pool
# ============================================================================

class MCPConnectionPool:
    """Manages persistent MCP server connections to avoid startup delays."""
    
    def __init__(self):
        self._toolsets: dict[str, any] = {}  # server_key -> MCPToolset
        self._tools_cache: dict[str, list] = {}  # server_key -> list of tools
        self._lock = asyncio.Lock()
        self._last_access: dict[str, float] = {}  # server_key -> timestamp
        self._cleanup_task: asyncio.Task | None = None
    
    def _get_server_key(self, config: dict) -> str:
        """Generate a unique key for a server configuration."""
        conn_type = config.get("connection_type", "stdio")
        if conn_type == "stdio":
            return f"stdio:{config.get('command')}:{':'.join(config.get('args', []))}"
        elif conn_type in ("sse", "http"):
            return f"{conn_type}:{config.get('url')}"
        return f"unknown:{hash(str(config))}"
    
    async def get_toolset(self, config: dict, timeout: float = 30.0):
        """Get or create a toolset for the given server config.
        
        Args:
            config: Server configuration dict
            timeout: Timeout in seconds for MCP session creation (default: 30)
        """
        import sys
        import time
        
        if sys.version_info < (3, 10):
            raise RuntimeError(f"MCP requires Python 3.10+, but you have Python {sys.version_info.major}.{sys.version_info.minor}")
        
        from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset
        from google.adk.tools.mcp_tool.mcp_session_manager import (
            StdioConnectionParams,
            SseConnectionParams,
        )
        
        # Use timeout from config if specified, otherwise use parameter
        session_timeout = float(config.get("timeout", timeout))
        
        server_key = self._get_server_key(config)
        
        async with self._lock:
            # Check if we already have this toolset
            if server_key in self._toolsets:
                self._last_access[server_key] = time.time()
                return self._toolsets[server_key]
            
            # Create new connection
            connection_type = config.get("connection_type", "stdio")
            
            if connection_type == "stdio":
                command = config.get("command")
                if not command:
                    raise ValueError("Command is required for stdio connection")
                
                connection_params = StdioConnectionParams(
                    server_params={
                        "command": command,
                        "args": config.get("args", []),
                        "env": config.get("env"),
                    },
                    timeout=session_timeout,  # Pass timeout to MCP session
                )
            elif connection_type == "sse":
                url = config.get("url")
                if not url:
                    raise ValueError("URL is required for SSE connection")
                connection_params = SseConnectionParams(
                    url=url,
                    headers=config.get("headers"),
                    timeout=session_timeout,  # Pass timeout to MCP session
                )
            else:
                raise ValueError(f"Unknown connection type: {connection_type}")
            
            toolset = MCPToolset(connection_params=connection_params)
            self._toolsets[server_key] = toolset
            self._last_access[server_key] = time.time()
            
            # Start cleanup task if not running
            if self._cleanup_task is None or self._cleanup_task.done():
                self._cleanup_task = asyncio.create_task(self._cleanup_loop())
            
            return toolset
    
    async def get_tools(self, config: dict, timeout: float = 30.0) -> list:
        """Get tools from a server, using cache if available."""
        import time
        
        server_key = self._get_server_key(config)
        
        # Check cache first
        if server_key in self._tools_cache:
            self._last_access[server_key] = time.time()
            return self._tools_cache[server_key]
        
        # Get toolset and fetch tools (pass timeout for session creation)
        toolset = await self.get_toolset(config, timeout=timeout)
        tools = await asyncio.wait_for(toolset.get_tools(), timeout=timeout)
        
        # Cache the tools
        self._tools_cache[server_key] = tools
        return tools
    
    async def call_tool(self, config: dict, tool_name: str, arguments: dict, timeout: float = 30.0):
        """Call a tool on an MCP server."""
        toolset = await self.get_toolset(config, timeout=timeout)
        tools = await self.get_tools(config, timeout=timeout)
        
        # Find the tool
        tool = next((t for t in tools if t.name == tool_name), None)
        if not tool:
            raise ValueError(f"Tool '{tool_name}' not found on server")
        
        # Call the tool using keyword arguments
        # MCP tools have run_async(*, args: dict, tool_context: ToolContext)
        # We create a minimal mock tool context for direct calls
        from unittest.mock import MagicMock
        mock_context = MagicMock()
        mock_context.actions = MagicMock()
        
        result = await asyncio.wait_for(
            tool.run_async(args=arguments, tool_context=mock_context),
            timeout=timeout
        )
        return result
    
    async def invalidate(self, config: dict = None):
        """Invalidate cached connections. If config is None, invalidate all."""
        async with self._lock:
            if config is None:
                self._toolsets.clear()
                self._tools_cache.clear()
                self._last_access.clear()
            else:
                server_key = self._get_server_key(config)
                self._toolsets.pop(server_key, None)
                self._tools_cache.pop(server_key, None)
                self._last_access.pop(server_key, None)
    
    async def _cleanup_loop(self):
        """Periodically clean up idle connections."""
        import time
        
        IDLE_TIMEOUT = 300  # 5 minutes
        CHECK_INTERVAL = 60  # 1 minute
        
        while True:
            await asyncio.sleep(CHECK_INTERVAL)
            
            now = time.time()
            to_remove = []
            
            async with self._lock:
                for server_key, last_access in self._last_access.items():
                    if now - last_access > IDLE_TIMEOUT:
                        to_remove.append(server_key)
                
                for server_key in to_remove:
                    self._toolsets.pop(server_key, None)
                    self._tools_cache.pop(server_key, None)
                    self._last_access.pop(server_key, None)
                    print(f"[MCP Pool] Closed idle connection: {server_key}")


# Global MCP connection pool
mcp_pool = MCPConnectionPool()

# Determine if we're in production mode (serving static files)
# Set ADK_PLAYGROUND_MODE=dev to use separate frontend dev server
# Default is production mode (serves built frontend from package)
PRODUCTION_MODE = os.environ.get("ADK_PLAYGROUND_MODE", "production").lower() == "production"

# Lifespan handler for startup/shutdown
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app):
    """Handle app startup and shutdown."""
    # Startup - start the backup service
    project_manager.start_backup_service()
    logger.info("📦 Backup service started (backups every 60 seconds if changed)")
    yield
    # Shutdown - stop backup service and cleanup Docker containers
    project_manager.stop_backup_service()
    if SANDBOX_AVAILABLE:
        try:
            from sandbox.docker_manager import get_sandbox_manager
            manager = get_sandbox_manager()
            if manager._initialized:
                logger.info("🧹 Cleaning up Docker containers on shutdown...")
                await manager.cleanup()
                logger.info("✅ Docker containers cleaned up")
        except Exception as e:
            logger.error(f"Error cleaning up Docker containers: {e}")

# Create FastAPI app
app = FastAPI(
    title="ADK Playground",
    description="Visual builder and runtime for Google ADK agents",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS for frontend (only in dev mode)
if not PRODUCTION_MODE:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "http://localhost:3001",
            "http://localhost:5173",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:3001",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Include sandbox router
if SANDBOX_AVAILABLE and sandbox_router is not None:
    app.include_router(sandbox_router)
    logger.info("Sandbox API routes enabled")


# ============================================================================
# Project Endpoints
# ============================================================================

@app.get("/api/projects")
async def list_projects():
    """List all projects."""
    return {"projects": project_manager.list_projects()}


@app.post("/api/projects")
async def create_project(data: dict):
    """Create a new project."""
    project = project_manager.create_project(
        name=data.get("name", "New Project"),
        description=data.get("description", ""),
    )
    return {"project": project.model_dump(mode="json", by_alias=True)}


@app.get("/api/projects/{project_id}")
async def get_project(project_id: str):
    """Get a project by ID."""
    project = project_manager.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"project": project.model_dump(mode="json", by_alias=True)}


@app.put("/api/projects/{project_id}")
async def update_project(project_id: str, data: dict):
    """Update a project."""
    project = project_manager.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Update from dict
    try:
        updated = Project.model_validate({**project.model_dump(), **data, "id": project_id})
        project_manager.save_project(updated)
        return {"project": updated.model_dump(mode="json")}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/projects/{project_id}")
async def delete_project(project_id: str):
    """Delete a project."""
    if project_manager.delete_project(project_id):
        return {"success": True}
    raise HTTPException(status_code=404, detail="Project not found")


# ============================================================================
# Project Backups
# ============================================================================

@app.get("/api/projects/{project_id}/backups")
async def list_project_backups(project_id: str):
    """List available backups for a project."""
    project = project_manager.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    backups = project_manager.list_backups(project_id)
    return {"backups": backups}


@app.post("/api/projects/{project_id}/backups/restore")
async def restore_project_backup(project_id: str, data: dict):
    """Restore a project from a backup.
    
    Body: { "filename": "project_id_YYYYMMDD_HHMMSS.yaml.gz" }
    """
    project = project_manager.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    filename = data.get("filename")
    if not filename:
        raise HTTPException(status_code=400, detail="Missing filename")
    
    restored = project_manager.restore_backup(project_id, filename)
    if not restored:
        raise HTTPException(status_code=400, detail="Failed to restore backup")
    
    return {"project": restored.model_dump(mode="json", by_alias=True)}


@app.post("/api/projects/{project_id}/backups/create")
async def create_project_backup(project_id: str):
    """Manually create a backup of a project."""
    project = project_manager.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Force a backup regardless of changes
    project_manager._last_backup_hashes.pop(project_id, None)
    success = project_manager._backup_project(project_id)
    
    if success:
        backups = project_manager.list_backups(project_id)
        return {"success": True, "latest": backups[0] if backups else None}
    
    return {"success": False, "error": "Backup failed"}


# ============================================================================
# YAML Import/Export
# ============================================================================

@app.get("/api/projects/{project_id}/yaml")
async def get_project_yaml(project_id: str):
    """Get project as YAML."""
    yaml_content = project_manager.get_project_yaml(project_id)
    if not yaml_content:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"yaml": yaml_content}


@app.put("/api/projects/{project_id}/yaml")
async def update_project_yaml(project_id: str, data: dict):
    """Update project from YAML."""
    yaml_content = data.get("yaml", "")
    project = project_manager.update_project_from_yaml(project_id, yaml_content)
    if not project:
        raise HTTPException(status_code=400, detail="Invalid YAML")
    return {"project": project.model_dump(mode="json", by_alias=True)}


@app.get("/api/projects/{project_id}/code")
async def get_project_code(project_id: str):
    """Get the generated Python code for a project.
    
    This is the actual code that runs when agents are executed.
    """
    from code_generator import generate_python_code
    
    project = project_manager.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    try:
        code = generate_python_code(project)
        return {"code": code}
    except Exception as e:
        logger.error(f"Failed to generate code: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Agent Endpoints
# ============================================================================

@app.get("/api/projects/{project_id}/agents")
async def list_agents(project_id: str):
    """List all agents in a project."""
    project = project_manager.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"agents": [a.model_dump(mode="json", by_alias=True) for a in project.agents]}


@app.post("/api/projects/{project_id}/agents")
async def create_agent(project_id: str, data: dict):
    """Create a new agent."""
    project = project_manager.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    agent_type = data.get("type", "LlmAgent")
    try:
        if agent_type == "LlmAgent":
            agent = LlmAgentConfig.model_validate(data)
        elif agent_type == "SequentialAgent":
            agent = SequentialAgentConfig.model_validate(data)
        elif agent_type == "LoopAgent":
            agent = LoopAgentConfig.model_validate(data)
        elif agent_type == "ParallelAgent":
            agent = ParallelAgentConfig.model_validate(data)
        else:
            raise ValueError(f"Unknown agent type: {agent_type}")
        
        project.agents.append(agent)
        project_manager.save_project(project)
        return {"agent": agent.model_dump(mode="json", by_alias=True)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.put("/api/projects/{project_id}/agents/{agent_id}")
async def update_agent(project_id: str, agent_id: str, data: dict):
    """Update an agent."""
    project = project_manager.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    for i, agent in enumerate(project.agents):
        if agent.id == agent_id:
            agent_type = data.get("type", agent.type)
            try:
                if agent_type == "LlmAgent":
                    updated = LlmAgentConfig.model_validate(data)
                elif agent_type == "SequentialAgent":
                    updated = SequentialAgentConfig.model_validate(data)
                elif agent_type == "LoopAgent":
                    updated = LoopAgentConfig.model_validate(data)
                elif agent_type == "ParallelAgent":
                    updated = ParallelAgentConfig.model_validate(data)
                else:
                    raise ValueError(f"Unknown agent type: {agent_type}")
                
                project.agents[i] = updated
                project_manager.save_project(project)
                return {"agent": updated.model_dump(mode="json", by_alias=True)}
            except Exception as e:
                raise HTTPException(status_code=400, detail=str(e))
    
    raise HTTPException(status_code=404, detail="Agent not found")


@app.delete("/api/projects/{project_id}/agents/{agent_id}")
async def delete_agent(project_id: str, agent_id: str):
    """Delete an agent."""
    project = project_manager.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    project.agents = [a for a in project.agents if a.id != agent_id]
    project_manager.save_project(project)
    return {"success": True}


# ============================================================================
# Custom Tools Endpoints
# ============================================================================

@app.get("/api/projects/{project_id}/tools")
async def list_custom_tools(project_id: str):
    """List all custom tools in a project."""
    project = project_manager.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"tools": [t.model_dump(mode="json") for t in project.custom_tools]}


@app.post("/api/projects/{project_id}/tools")
async def create_custom_tool(project_id: str, data: dict):
    """Create a new custom tool."""
    project = project_manager.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    try:
        tool = CustomToolDefinition.model_validate(data)
        project.custom_tools.append(tool)
        project_manager.save_project(project)
        return {"tool": tool.model_dump(mode="json")}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.put("/api/projects/{project_id}/tools/{tool_id}")
async def update_custom_tool(project_id: str, tool_id: str, data: dict):
    """Update a custom tool."""
    project = project_manager.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    for i, tool in enumerate(project.custom_tools):
        if tool.id == tool_id:
            try:
                updated = CustomToolDefinition.model_validate(data)
                project.custom_tools[i] = updated
                project_manager.save_project(project)
                return {"tool": updated.model_dump(mode="json")}
            except Exception as e:
                raise HTTPException(status_code=400, detail=str(e))
    
    raise HTTPException(status_code=404, detail="Tool not found")


@app.delete("/api/projects/{project_id}/tools/{tool_id}")
async def delete_custom_tool(project_id: str, tool_id: str):
    """Delete a custom tool."""
    project = project_manager.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    project.custom_tools = [t for t in project.custom_tools if t.id != tool_id]
    project_manager.save_project(project)
    return {"success": True}


# ============================================================================
# Reference Data Endpoints
# ============================================================================

@app.get("/api/mcp-servers")
async def list_mcp_servers():
    """List known MCP servers."""
    return {"servers": [s.model_dump(mode="json") for s in KNOWN_MCP_SERVERS]}


@app.get("/api/builtin-tools")
async def list_builtin_tools():
    """List built-in ADK tools."""
    return {"tools": BUILTIN_TOOLS}


# ============================================================================
# Model Listing
# ============================================================================

class ListModelsRequest(BaseModel):
    """Request to list available models."""
    google_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    groq_api_key: Optional[str] = None
    check_ollama: bool = True


@app.post("/api/models")
async def list_available_models(request: ListModelsRequest):
    """List available models from all configured providers.
    
    Pass API keys to fetch models from each provider's API.
    Keys can also come from environment variables.
    """
    from model_service import list_all_models
    
    providers = await list_all_models(
        google_api_key=request.google_api_key,
        anthropic_api_key=request.anthropic_api_key,
        openai_api_key=request.openai_api_key,
        groq_api_key=request.groq_api_key,
        check_ollama=request.check_ollama,
    )
    
    return {"providers": {k: v.model_dump() for k, v in providers.items()}}


@app.get("/api/models/{project_id}")
async def list_models_for_project(
    project_id: str, 
    provider: Optional[str] = None,
    api_base: Optional[str] = None
):
    """List available models for a specific provider using project's API keys.
    
    Args:
        project_id: The project ID
        provider: Which provider to fetch models from (gemini, anthropic, openai, groq, litellm/ollama)
        api_base: Optional API base URL for Ollama/LiteLLM
    """
    from model_service import (
        list_gemini_models, list_anthropic_models, list_openai_models,
        list_groq_models, list_ollama_models, ProviderModels
    )
    
    project = project_manager.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Get API keys from project's env_vars
    env_vars = project.app.env_vars or {}
    
    providers: dict = {}
    
    # If no provider specified, return empty (user should select a provider first)
    if not provider:
        return {"providers": {}}
    
    provider = provider.lower()
    
    if provider == "gemini":
        key = env_vars.get("GOOGLE_API_KEY") or env_vars.get("GEMINI_API_KEY")
        result = await list_gemini_models(key)
        providers["gemini"] = result.model_dump()
    elif provider == "anthropic":
        key = env_vars.get("ANTHROPIC_API_KEY")
        result = await list_anthropic_models(key)
        providers["anthropic"] = result.model_dump()
    elif provider == "openai":
        key = env_vars.get("OPENAI_API_KEY")
        result = await list_openai_models(key)
        providers["openai"] = result.model_dump()
    elif provider == "groq":
        key = env_vars.get("GROQ_API_KEY")
        result = await list_groq_models(key)
        providers["groq"] = result.model_dump()
    elif provider in ("litellm", "ollama"):
        # For LiteLLM, we fetch from Ollama using the provided api_base
        base_url = api_base or "http://localhost:11434"
        result = await list_ollama_models(base_url)
        providers["ollama"] = result.model_dump()
    
    return {"providers": providers}


# ============================================================================
# Model Testing
# ============================================================================

class TestModelRequest(BaseModel):
    """Request to test a model configuration."""
    provider: str
    model_name: str
    api_base: Optional[str] = None
    api_key: Optional[str] = None  # Override key for testing
    prompt: str = "Say 'Hello! Model test successful.' in exactly those words."

@app.post("/api/projects/{project_id}/test-model")
async def test_model_config(project_id: str, request: TestModelRequest):
    """Test a model configuration by sending a simple prompt.
    
    Returns the model's response or an error message.
    """
    import traceback
    
    project = project_manager.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    try:
        # Get API keys from project env_vars
        env_vars = project.app.env_vars or {}
        
        # Temporarily set environment variables for the test
        old_env = {}
        keys_to_set = {
            "GOOGLE_API_KEY": request.api_key or env_vars.get("GOOGLE_API_KEY") or env_vars.get("GEMINI_API_KEY"),
            "GEMINI_API_KEY": request.api_key or env_vars.get("GEMINI_API_KEY") or env_vars.get("GOOGLE_API_KEY"),
            "ANTHROPIC_API_KEY": request.api_key or env_vars.get("ANTHROPIC_API_KEY"),
            "OPENAI_API_KEY": request.api_key or env_vars.get("OPENAI_API_KEY"),
            "GROQ_API_KEY": request.api_key or env_vars.get("GROQ_API_KEY"),
            "TOGETHER_API_KEY": request.api_key or env_vars.get("TOGETHER_API_KEY"),
            "OPENROUTER_API_KEY": request.api_key or env_vars.get("OPENROUTER_API_KEY"),
        }
        
        for key, value in keys_to_set.items():
            if value:
                old_env[key] = os.environ.get(key)
                os.environ[key] = value
        
        try:
            from google.adk import Agent
            from google.adk.runners import Runner
            from google.adk.sessions.in_memory_session_service import InMemorySessionService
            from google.genai import types
            
            # Create model based on provider
            if request.provider in ("litellm", "openai", "groq", "together"):
                from google.adk.models.lite_llm import LiteLlm
                model = LiteLlm(
                    model=request.model_name,
                    api_base=request.api_base,
                )
            elif request.provider == "anthropic":
                from google.adk.models.anthropic_llm import AnthropicLlm
                model = AnthropicLlm(model=request.model_name)
            else:
                # Gemini or other - use model name directly
                model = request.model_name
            
            # Create a simple test agent
            test_agent = Agent(
                name="model_test",
                model=model,
                instruction="You are a helpful assistant. Follow the user's instructions exactly.",
            )
            
            runner = Runner(
                app_name="model_test",
                agent=test_agent,
                session_service=InMemorySessionService(),
            )
            
            session = await runner.session_service.create_session(
                app_name="model_test",
                user_id="test_user",
            )
            
            # Run the test prompt
            response_text = ""
            async for event in runner.run_async(
                session_id=session.id,
                user_id="test_user",
                new_message=types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=request.prompt)]
                ),
            ):
                pass
            
            # Get response from session state
            final_session = await runner.session_service.get_session(
                app_name="model_test",
                user_id="test_user",
                session_id=session.id,
            )
            
            # Extract response from session events
            if final_session and final_session.events:
                for event in reversed(final_session.events):
                    if hasattr(event, 'content') and event.content:
                        for part in event.content.parts:
                            if hasattr(part, 'text') and part.text:
                                response_text = part.text
                                break
                    if response_text:
                        break
            
            await runner.close()
            
            return {
                "success": True,
                "response": response_text or "Model responded but no text extracted",
                "model": request.model_name,
                "provider": request.provider,
            }
            
        finally:
            # Restore environment
            for key, value in old_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
                    
    except Exception as e:
        logger.error(f"Model test failed: {e}")
        return {
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc(),
            "model": request.model_name,
            "provider": request.provider,
        }


# ============================================================================
# MCP Server Testing
# ============================================================================

class TestMcpRequest(BaseModel):
    """Request to test an MCP server connection."""
    connection_type: str = "stdio"
    command: Optional[str] = None
    args: Optional[List[str]] = None
    env: Optional[dict] = None
    url: Optional[str] = None
    headers: Optional[dict] = None
    timeout: int = 30

@app.post("/api/test-mcp-server")
async def test_mcp_server(request: TestMcpRequest):
    """Test an MCP server connection and list its available tools."""
    import traceback
    
    try:
        # Build config dict for the pool
        config = {
            "connection_type": request.connection_type,
            "command": request.command,
            "args": request.args or [],
            "env": request.env,
            "url": request.url,
            "headers": request.headers,
            "timeout": request.timeout,
        }
        
        # Get tools using the connection pool (keeps connection open)
        tools = await mcp_pool.get_tools(config, timeout=request.timeout)
        
        # Extract tool information
        tool_list = []
        for tool in tools:
            tool_info = {
                "name": tool.name,
                "description": getattr(tool, "description", "") or "",
            }
            # Try to get parameters schema from various sources
            if hasattr(tool, "parameters") and tool.parameters:
                tool_info["parameters"] = tool.parameters
            elif hasattr(tool, "_schema") and tool._schema:
                tool_info["parameters"] = tool._schema
            elif hasattr(tool, "raw_mcp_tool") and hasattr(tool.raw_mcp_tool, "inputSchema"):
                # MCP tools store schema in raw_mcp_tool.inputSchema
                tool_info["parameters"] = tool.raw_mcp_tool.inputSchema
            tool_list.append(tool_info)
        
        return {
            "success": True,
            "tools": tool_list,
            "message": f"Successfully connected! Found {len(tool_list)} tools."
        }
        
    except asyncio.TimeoutError:
        return {
            "success": False,
            "error": f"Connection timed out after {request.timeout} seconds. The MCP server may be slow to start. Try increasing the timeout.",
            "hint": "Some MCP servers (especially those using npm/npx) can take 30+ seconds on first run to download dependencies.",
            "tools": []
        }
    except ConnectionError as e:
        error_msg = str(e)
        # Check if this is a timeout during session creation
        if "TimeoutError" in error_msg or "timed out" in error_msg.lower():
            return {
                "success": False,
                "error": f"MCP server startup timed out. The server took too long to initialize.",
                "hint": f"Current timeout is {request.timeout}s. Try increasing it to 60+ seconds, especially for npm-based servers that need to download dependencies.",
                "traceback": traceback.format_exc(),
                "tools": []
            }
        return {
            "success": False,
            "error": error_msg,
            "traceback": traceback.format_exc(),
            "tools": []
        }
    except Exception as e:
        error_msg = str(e)
        # Provide helpful hints for common errors
        hint = None
        if "spawn" in error_msg.lower() or "not found" in error_msg.lower() or "ENOENT" in error_msg:
            hint = "The command or executable was not found. Make sure the MCP server is installed and the command path is correct."
        elif "permission" in error_msg.lower():
            hint = "Permission denied. Check that you have execute permissions for the MCP server command."
        elif "timeout" in error_msg.lower():
            hint = f"The operation timed out. Try increasing the timeout (current: {request.timeout}s)."
        
        return {
            "success": False,
            "error": error_msg,
            "hint": hint,
            "traceback": traceback.format_exc(),
            "tools": []
        }


@app.post("/api/projects/{project_id}/mcp-servers/{server_name}/test-connection")
async def test_project_mcp_server(project_id: str, server_name: str):
    """Test an MCP server connection by server name, looking up from project or known servers."""
    import sys
    import traceback
    
    # Check Python version - MCP requires 3.10+
    if sys.version_info < (3, 10):
        return {
            "success": False,
            "error": f"MCP requires Python 3.10+, but you have Python {sys.version_info.major}.{sys.version_info.minor}",
            "tools": []
        }
    
    # Load project to get its MCP servers
    project_path = PROJECTS_DIR / f"{project_id}.yaml"
    server_config = None
    
    if project_path.exists():
        with open(project_path, "r") as f:
            project_data = yaml.safe_load(f) or {}
        
        # Look in project's MCP servers
        for server in project_data.get("mcp_servers", []):
            if server.get("name") == server_name:
                server_config = server
                break
    
    # If not found in project, check known servers
    if not server_config:
        for known_server in KNOWN_MCP_SERVERS:
            if known_server.name == server_name:
                server_config = known_server.model_dump()
                break
    
    if not server_config:
        return {
            "success": False,
            "error": f"MCP server '{server_name}' not found in project or known servers",
            "tools": []
        }
    
    try:
        # Get tools using the connection pool (keeps connection open for reuse)
        timeout = server_config.get("timeout", 30)
        tools = await mcp_pool.get_tools(server_config, timeout=timeout)
        
        # Extract tool information
        tool_list = []
        for tool in tools:
            tool_info = {
                "name": getattr(tool, "name", str(tool)),
                "description": getattr(tool, "description", ""),
            }
            # Try to get parameters schema from various sources
            if hasattr(tool, "parameters") and tool.parameters:
                tool_info["parameters"] = tool.parameters
            elif hasattr(tool, "_schema") and tool._schema:
                tool_info["parameters"] = tool._schema
            elif hasattr(tool, "raw_mcp_tool") and hasattr(tool.raw_mcp_tool, "inputSchema"):
                # MCP tools store schema in raw_mcp_tool.inputSchema
                tool_info["parameters"] = tool.raw_mcp_tool.inputSchema
            tool_list.append(tool_info)
        
        return {
            "success": True,
            "tools": tool_list
        }
        
    except asyncio.TimeoutError:
        timeout = server_config.get("timeout", 30)
        return {
            "success": False,
            "error": f"Connection timed out after {timeout} seconds. The MCP server may not be responding.",
            "tools": []
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc(),
            "tools": []
        }


class RunMcpToolRequest(BaseModel):
    """Request to run an MCP tool."""
    server_name: str
    tool_name: str
    arguments: dict = {}
    sandbox_mode: bool = False  # If true, execute in Docker sandbox
    app_id: Optional[str] = None  # Required when sandbox_mode is true


@app.post("/api/projects/{project_id}/run-mcp-tool")
async def run_mcp_tool(project_id: str, request: RunMcpToolRequest):
    """Run an MCP tool and return its result.
    
    When sandbox_mode is True and app_id is provided, the tool is executed
    inside the Docker sandbox container, allowing inspection of the container's
    filesystem and state.
    """
    import traceback
    
    # If sandbox mode, route to sandbox container
    if request.sandbox_mode and request.app_id:
        from sandbox.docker_manager import get_sandbox_manager
        sandbox_manager = get_sandbox_manager()
        
        sandbox_result = await sandbox_manager.mcp_call_tool(
            app_id=request.app_id,
            server_name=request.server_name,
            tool_name=request.tool_name,
            args=request.arguments,
        )
        
        if "error" in sandbox_result:
            return {"success": False, "error": sandbox_result["error"]}
        
        # Extract result from sandbox response
        result_data = sandbox_result.get("result", sandbox_result)
        
        # Handle nested content structure from MCP
        if isinstance(result_data, dict) and "content" in result_data:
            content = result_data["content"]
            if isinstance(content, list):
                texts = []
                for part in content:
                    if isinstance(part, dict) and "text" in part:
                        texts.append(part["text"])
                if texts:
                    return {"success": True, "result": "\n".join(texts), "sandbox": True}
            return {"success": True, "result": str(content), "sandbox": True}
        
        return {"success": True, "result": str(result_data), "sandbox": True}
    
    # Original host-based execution
    # Find the server config
    project_path = PROJECTS_DIR / f"{project_id}.yaml"
    server_config = None
    
    if project_path.exists():
        with open(project_path, "r") as f:
            project_data = yaml.safe_load(f) or {}
        
        for server in project_data.get("mcp_servers", []):
            if server.get("name") == request.server_name:
                server_config = server
                break
    
    if not server_config:
        for known_server in KNOWN_MCP_SERVERS:
            if known_server.name == request.server_name:
                server_config = known_server.model_dump()
                break
    
    if not server_config:
        return {
            "success": False,
            "error": f"MCP server '{request.server_name}' not found"
        }
    
    try:
        timeout = server_config.get("timeout", 30)
        result = await mcp_pool.call_tool(
            server_config, 
            request.tool_name, 
            request.arguments, 
            timeout=timeout
        )
        
        # Try to extract text from MCP result
        if hasattr(result, 'content') and result.content:
            # MCP results often have content as a list of parts
            if isinstance(result.content, list):
                texts = []
                for part in result.content:
                    if hasattr(part, 'text'):
                        texts.append(part.text)
                    elif isinstance(part, dict) and 'text' in part:
                        texts.append(part['text'])
                if texts:
                    return {"success": True, "result": "\n".join(texts)}
            return {"success": True, "result": str(result.content)}
        
        return {"success": True, "result": str(result)}
        
    except asyncio.TimeoutError:
        return {
            "success": False,
            "error": f"Tool call timed out after {server_config.get('timeout', 30)} seconds"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }


# ============================================================================
# Runtime WebSocket
# ============================================================================

class ConnectionManager:
    """Manage WebSocket connections."""
    
    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}
    
    async def connect(self, websocket: WebSocket, session_id: str):
        # Note: websocket should already be accepted before calling this
        self.active_connections[session_id] = websocket
    
    def disconnect(self, session_id: str):
        if session_id in self.active_connections:
            del self.active_connections[session_id]
    
    async def send_event(self, session_id: str, event: dict):
        if session_id in self.active_connections:
            await self.active_connections[session_id].send_json(event)


connection_manager = ConnectionManager()


@app.websocket("/ws/run/{project_id}")
async def run_agent_ws(websocket: WebSocket, project_id: str):
    """WebSocket endpoint for running agents with real-time updates."""
    project = project_manager.get_project(project_id)
    if not project:
        await websocket.close(code=4004, reason="Project not found")
        return
    
    session_id = None
    sandbox_instance = None
    try:
        await websocket.accept()
        
        # Wait for initial message with user input
        data = await websocket.receive_json()
        user_message = data.get("message", "")
        requested_session_id = data.get("session_id")  # Optional: reuse existing session
        agent_id = data.get("agent_id")  # Optional: run specific agent instead of root
        sandbox_mode = data.get("sandbox_mode", False)  # Run in Docker sandbox
        
        session_id = None  # Will be set from first event
        
        async def event_callback(event: RunEvent):
            await connection_manager.send_event(session_id, event.model_dump(mode="json"))
        
        # Check if sandbox mode requested
        if sandbox_mode and SANDBOX_AVAILABLE:
            # Run in Docker sandbox
            await websocket.send_json({"type": "sandbox_starting"})
            
            from sandbox.docker_manager import get_sandbox_manager
            from sandbox.models import SandboxConfig
            from sandbox.webhook_handler import webhook_handler
            from sandbox.allowlist_persistence import load_sandbox_config_from_project
            
            sandbox_manager = get_sandbox_manager()
            app_id = project.app.id if project.app else project_id
            
            # Clear any cached events from previous runs BEFORE starting
            await webhook_handler.clear(app_id)
            
            logger.info(f"🚀 Starting sandbox: manager id={id(sandbox_manager)}, app_id={app_id}")
            
            # Initialize sandbox if not already done
            if not sandbox_manager._initialized:
                await sandbox_manager.initialize()
            
            # Get project file path - use same path as project_manager (module-level)
            project_yaml_path = project_manager.get_project_path(project_id)
            if project_yaml_path:
                workspace_path = Path(project_yaml_path)  # Use actual file path
            else:
                workspace_path = PROJECTS_DIR / project_id if PROJECTS_DIR.exists() else Path.cwd()
            
            logger.info(f"📂 Loading sandbox config from: {workspace_path}")
            
            # Load persisted sandbox config from project (includes saved allowlist patterns)
            config = load_sandbox_config_from_project(workspace_path)
            config.enabled = True  # Ensure sandbox is enabled for this run
            
            if config.allowlist.user:
                logger.info(f"📋 Loaded {len(config.allowlist.user)} saved allowlist patterns from project")
                for p in config.allowlist.user:
                    logger.info(f"   - {p.pattern} ({p.pattern_type.value})")
            
            sandbox_instance = await sandbox_manager.start_sandbox(
                app_id=app_id,
                config=config,
                project_config=project.model_dump(),
                workspace_path=workspace_path,
            )
            
            await websocket.send_json({
                "type": "sandbox_started",
                "sandbox_id": app_id,
                "gateway_port": sandbox_instance.gateway_container_id[:12] if sandbox_instance.gateway_container_id else None,
            })
            
            # Set up event streaming from webhook
            logger.info(f"📝 Subscribing to events for app_id={app_id}")
            events_storage = await webhook_handler.get_or_create(app_id)
            event_queue: asyncio.Queue = asyncio.Queue()
            
            # Subscriber to forward events to queue immediately
            def on_event(event_data):
                event_type = event_data.get("type")
                logger.info(f"📩 WebSocket received event: {event_type}")
                if event_type == "agent_event":
                    event_queue.put_nowait(event_data.get("data", {}))
                elif event_type == "network_request":
                    # Forward network request events (including approval_required)
                    event_queue.put_nowait({
                        "type": "network_request",
                        **event_data.get("data", {})
                    })
            
            events_storage.subscribe(on_event)
            logger.info(f"📝 Subscribed, {len(events_storage.subscribers)} total subscribers")
            session_sent = False
            
            try:
                # Start the agent run WITHOUT waiting for completion
                # The container will post events to /api/sandbox/event as they happen
                async def run_agent_background():
                    return await sandbox_manager.send_message(
                        app_id, 
                        user_message, 
                        requested_session_id,
                        project_config=project.model_dump(),
                    )
                
                agent_task = asyncio.create_task(run_agent_background())
                
                # Stream events as they arrive via webhook
                while not agent_task.done():
                    try:
                        event = await asyncio.wait_for(event_queue.get(), timeout=0.1)
                        # Send session_started on first event with session_id
                        if not session_sent:
                            sess_id = event.get("session_id") or event.get("data", {}).get("session_id")
                            if sess_id:
                                await websocket.send_json({"type": "session_started", "session_id": sess_id})
                                session_sent = True
                        await websocket.send_json(event)
                    except asyncio.TimeoutError:
                        continue
                
                # Get the result
                result = await agent_task
                
                # Drain any remaining events
                while not event_queue.empty():
                    event = event_queue.get_nowait()
                    await websocket.send_json(event)
                
                # Check for errors
                if "error" in result:
                    await websocket.send_json({
                        "type": "error",
                        "error": result["error"],
                    })
                
                await websocket.send_json({"type": "completed"})
            finally:
                events_storage.unsubscribe(on_event)
            
            return
        
        # Run the agent locally (optionally a specific agent instead of root, optionally reuse session)
        async for event in runtime_manager.run_agent(
            project, 
            user_message, 
            event_callback, 
            agent_id=agent_id,
            session_id=requested_session_id,  # Pass through to reuse existing session
        ):
            # First event contains session_id info
            if not session_id and event.event_type == "agent_start":
                logger.info(f"[WS] agent_start event: agent_name={event.agent_name}, data={event.data}")
                if event.data.get("session_id"):
                    session_id = event.data["session_id"]
                    await connection_manager.connect(websocket, session_id)
                    # Send session_id to client
                    logger.info(f"[WS] Sending session_started: {session_id}")
                    await websocket.send_json({"type": "session_started", "session_id": session_id})
            
            await websocket.send_json(event.model_dump(mode="json"))
        
        # Send completion message
        await websocket.send_json({"type": "completed"})
        
    except WebSocketDisconnect:
        if session_id:
            runtime_manager.stop_run(session_id)
    except Exception as e:
        import traceback
        error_msg = f"{str(e)}\n{traceback.format_exc()}"
        print(f"WebSocket error: {error_msg}")
        try:
            await websocket.send_json({"type": "error", "error": str(e), "traceback": traceback.format_exc()})
        except Exception:
            pass  # WebSocket might be closed
    finally:
        if session_id:
            connection_manager.disconnect(session_id)


# ============================================================================
# HTTP Run Endpoint (for simpler testing)
# ============================================================================

class RunRequest(BaseModel):
    message: str
    session_id: Optional[str] = None


@app.post("/api/projects/{project_id}/run")
async def run_agent_http(project_id: str, request: RunRequest):
    """HTTP endpoint to run agent (collects all events and returns them)."""
    project = project_manager.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    events = []
    
    async def collect_event(event: RunEvent):
        events.append(event.model_dump(mode="json"))
    
    try:
        async for event in runtime_manager.run_agent(project, request.message, collect_event):
            events.append(event.model_dump(mode="json"))
        return {"events": events, "status": "completed"}
    except Exception as e:
        import traceback
        return {"events": events, "status": "error", "error": str(e), "traceback": traceback.format_exc()}


# ============================================================================
# Session History Endpoints
# ============================================================================

@app.get("/api/sessions")
async def list_sessions():
    """List all run sessions."""
    sessions = list(runtime_manager.sessions.values())
    return {"sessions": [s.model_dump(mode="json") for s in sessions]}


@app.get("/api/projects/{project_id}/sessions")
async def list_project_sessions(project_id: str):
    """List all sessions from the session service for a project."""
    project = project_manager.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    sessions = await runtime_manager.list_sessions_from_service(project)
    return {"sessions": sessions}


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    """Get a session by ID."""
    session = runtime_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"session": session.model_dump(mode="json")}


@app.get("/api/projects/{project_id}/sessions/{session_id}/load")
async def load_session(project_id: str, session_id: str):
    """Load a session's events from the session service."""
    project = project_manager.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    session = await runtime_manager.load_session_from_service(project, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    return {"session": session.model_dump(mode="json")}


# ============================================================================
# Artifacts API
# ============================================================================

@app.get("/api/projects/{project_id}/sessions/{session_id}/artifacts")
async def list_artifacts(project_id: str, session_id: str):
    """List all artifacts for a session."""
    from runtime import create_artifact_service_from_uri
    
    project = project_manager.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    artifact_service = create_artifact_service_from_uri(project.app.artifact_service_uri or "memory://")
    
    try:
        # List artifacts for this session
        artifacts = await artifact_service.list_artifact_keys(
            app_name=project.app.name,
            user_id="playground_user",
            session_id=session_id,
        )
        
        # Build artifact info list
        artifact_list = []
        for filename in artifacts:
            # Try to get the latest version info
            try:
                artifact = await artifact_service.load_artifact(
                    app_name=project.app.name,
                    user_id="playground_user",
                    session_id=session_id,
                    filename=filename,
                )
                
                # Determine if it's an image based on mime type or filename
                mime_type = None
                is_image = False
                size = None
                
                if artifact:
                    # Check for inline_data which has mime_type
                    if hasattr(artifact, 'inline_data') and artifact.inline_data:
                        mime_type = getattr(artifact.inline_data, 'mime_type', None)
                        data = getattr(artifact.inline_data, 'data', None)
                        if data:
                            if isinstance(data, bytes):
                                size = len(data)
                            elif isinstance(data, str):
                                # Base64 encoded
                                size = len(data) * 3 // 4  # Approximate decoded size
                    elif hasattr(artifact, 'text'):
                        mime_type = 'text/plain'
                        size = len(artifact.text) if artifact.text else 0
                    
                    # Check filename extension as fallback
                    if not mime_type:
                        ext = filename.lower().split('.')[-1] if '.' in filename else ''
                        mime_map = {
                            'png': 'image/png',
                            'jpg': 'image/jpeg',
                            'jpeg': 'image/jpeg',
                            'gif': 'image/gif',
                            'webp': 'image/webp',
                            'svg': 'image/svg+xml',
                            'txt': 'text/plain',
                            'json': 'application/json',
                            'html': 'text/html',
                            'css': 'text/css',
                            'js': 'application/javascript',
                            'pdf': 'application/pdf',
                        }
                        mime_type = mime_map.get(ext, 'application/octet-stream')
                    
                    is_image = mime_type and mime_type.startswith('image/')
                
                artifact_list.append({
                    "filename": filename,
                    "mime_type": mime_type,
                    "is_image": is_image,
                    "size": size,
                })
            except Exception as e:
                logger.warning(f"Failed to get artifact info for {filename}: {e}")
                artifact_list.append({
                    "filename": filename,
                    "mime_type": None,
                    "is_image": False,
                    "size": None,
                })
        
        return {"artifacts": artifact_list}
    except Exception as e:
        logger.error(f"Failed to list artifacts: {e}", exc_info=True)
        return {"artifacts": [], "error": str(e)}


@app.get("/api/projects/{project_id}/sessions/{session_id}/artifacts/{filename:path}")
async def get_artifact(project_id: str, session_id: str, filename: str):
    """Get a specific artifact's content."""
    from runtime import create_artifact_service_from_uri
    from fastapi.responses import Response
    import base64
    
    project = project_manager.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    artifact_service = create_artifact_service_from_uri(project.app.artifact_service_uri or "memory://")
    
    try:
        artifact = await artifact_service.load_artifact(
            app_name=project.app.name,
            user_id="playground_user",
            session_id=session_id,
            filename=filename,
        )
        
        if not artifact:
            raise HTTPException(status_code=404, detail="Artifact not found")
        
        # Handle different artifact types
        if hasattr(artifact, 'inline_data') and artifact.inline_data:
            mime_type = getattr(artifact.inline_data, 'mime_type', 'application/octet-stream')
            data = getattr(artifact.inline_data, 'data', b'')
            
            # Handle base64 encoded data
            if isinstance(data, str):
                try:
                    data = base64.b64decode(data)
                except Exception:
                    data = data.encode('utf-8')
            
            return Response(
                content=data,
                media_type=mime_type,
                headers={
                    "Content-Disposition": f'inline; filename="{filename}"'
                }
            )
        elif hasattr(artifact, 'text') and artifact.text:
            return Response(
                content=artifact.text,
                media_type='text/plain',
                headers={
                    "Content-Disposition": f'inline; filename="{filename}"'
                }
            )
        else:
            raise HTTPException(status_code=500, detail="Unknown artifact format")
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get artifact {filename}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/sessions/{session_id}/save-to-memory")
async def save_session_to_memory(session_id: str):
    """Save a session to memory service."""
    session = runtime_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Get the project for this session
    project = project_manager.get_project(session.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found for session")
    
    result = await runtime_manager.save_session_to_memory(project, session_id)
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "Failed to save to memory"))
    
    return result


# ============================================================================
# AI-Assisted Prompt Generation
# ============================================================================

class GeneratePromptRequest(BaseModel):
    agent_id: str
    context: Optional[str] = None  # Optional user hints
    agent_config: Optional[Dict[str, Any]] = None  # Optional: agent config if not yet saved

@app.post("/api/projects/{project_id}/generate-prompt")
async def generate_agent_prompt(project_id: str, request: GeneratePromptRequest):
    """Generate an instruction prompt for an agent using AI."""
    project = project_manager.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Find the target agent - first try in saved project, then use provided config
    target_agent = None
    agent_ids_in_project = [a.id for a in project.agents]
    for agent in project.agents:
        if agent.id == request.agent_id:
            target_agent = agent
            break
    
    # If agent not found in saved project, try to use provided agent_config
    if not target_agent and request.agent_config:
        try:
            # Parse the agent config from the request
            from models import AgentConfig
            target_agent = AgentConfig(**request.agent_config)
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Agent not found and provided agent_config is invalid: {str(e)}"
            )
    
    if not target_agent:
        raise HTTPException(
            status_code=404, 
            detail=f"Agent not found. Looking for '{request.agent_id}', available agents: {agent_ids_in_project}. If this is a new agent, please provide 'agent_config' in the request."
        )
    
    # Build context about the entire agent network
    agent_summaries = []
    for agent in project.agents:
        summary = {
            "name": agent.name,
            "type": agent.type,
            "description": getattr(agent, "description", "") or "",
        }
        if agent.type == "LlmAgent":
            # Handle different tool types
            tool_names = []
            for t in getattr(agent, "tools", []):
                if hasattr(t, "name") and t.name:
                    tool_names.append(f"{t.type}:{t.name}")
                elif hasattr(t, "server") and t.server:
                    tool_names.append(f"{t.type}:{t.server.name}")
                elif hasattr(t, "agent_id"):
                    tool_names.append(f"{t.type}:{t.agent_id}")
                else:
                    tool_names.append(t.type)
            summary["tools"] = tool_names
            summary["current_instruction"] = getattr(agent, "instruction", "")[:200] if getattr(agent, "instruction", "") else ""
        elif agent.type in ["SequentialAgent", "LoopAgent", "ParallelAgent"]:
            summary["sub_agents"] = getattr(agent, "sub_agent_ids", [])
        
        if agent.id == request.agent_id:
            summary["is_target"] = True
        agent_summaries.append(summary)
    
    # If target_agent is not in saved project, add it to summaries
    if target_agent.id not in agent_ids_in_project:
        summary: Dict[str, Any] = {
            "name": target_agent.name,
            "type": target_agent.type,
            "description": getattr(target_agent, "description", "") or "",
            "is_target": True,
        }
        if target_agent.type == "LlmAgent":
            # Handle different tool types
            tool_names = []
            for t in getattr(target_agent, "tools", []):
                if hasattr(t, "name") and t.name:
                    tool_names.append(f"{t.type}:{t.name}")
                elif hasattr(t, "server") and t.server:
                    tool_names.append(f"{t.type}:{t.server.name}")
                elif hasattr(t, "agent_id"):
                    tool_names.append(f"{t.type}:{t.agent_id}")
                else:
                    tool_names.append(t.type)
            summary["tools"] = tool_names
            summary["current_instruction"] = getattr(target_agent, "instruction", "")[:200] if getattr(target_agent, "instruction", "") else ""
        elif target_agent.type in ["SequentialAgent", "LoopAgent", "ParallelAgent"]:
            summary["sub_agents"] = getattr(target_agent, "sub_agent_ids", [])
        agent_summaries.append(summary)
    
    # Build context message for the prompt_generator agent
    # The agent's instruction already contains the "how to write prompts" guidance
    # We just need to provide the project and agent context
    context_message = f"""## Project Context
Project Name: {project.name}
Project Description: {project.description or 'No description'}

## Agent Network
The following agents exist in this project:

"""
    for summary in agent_summaries:
        marker = ">>> TARGET AGENT <<<" if summary.get("is_target") else ""
        context_message += f"""
### {summary['name']} ({summary['type']}) {marker}
- Description: {summary['description'] or 'No description yet'}
"""
        if summary.get("tools"):
            context_message += f"- Tools: {', '.join(summary['tools'])}\n"
        if summary.get("sub_agents"):
            context_message += f"- Sub-agents: {', '.join(summary['sub_agents'])}\n"
        if summary.get("current_instruction"):
            context_message += f"- Current instruction preview: {summary['current_instruction']}...\n"
    
    context_message += f"""
## Target Agent
Write an instruction prompt for: **{target_agent.name}**
"""
    if request.context:
        context_message += f"""
## Additional Context from User
{request.context}
"""
    
    # Get model config from project
    model_config = None
    if project.app.models and len(project.app.models) > 0:
        if project.app.default_model_id:
            model_config = next((m for m in project.app.models if m.id == project.app.default_model_id), None)
        if not model_config:
            model_config = project.app.models[0]
    
    # Run the prompt_generator agent
    result = await run_agent(
        agent_name="prompt_generator",
        message=context_message,
        model_config=model_config,
        env_vars=project.app.env_vars,
        output_key="generated_prompt",
    )
    
    if result["success"]:
        # Strip markdown code blocks if present
        output = result["output"]
        if output:
            output = output.strip()
            # Remove opening code fence (```markdown, ```text, ```, etc.)
            if output.startswith("```"):
                first_newline = output.find("\n")
                if first_newline != -1:
                    output = output[first_newline + 1:]
            # Remove closing code fence
            if output.rstrip().endswith("```"):
                output = output.rstrip()[:-3].rstrip()
        return {"prompt": output, "success": True}
    else:
        return {
            "prompt": None,
            "success": False,
            "error": result.get("error"),
            "traceback": result.get("traceback"),
        }


# ============================================================================
# AI-Assisted Tool Code Generation
# ============================================================================

class GenerateToolCodeRequest(BaseModel):
    tool_name: str
    tool_description: str
    state_keys_used: List[str] = []
    context: Optional[str] = None  # Additional hints from user

@app.post("/api/projects/{project_id}/generate-tool-code")
async def generate_tool_code(project_id: str, request: GenerateToolCodeRequest):
    """Generate Python code for an ADK tool using AI."""
    import traceback
    import sys
    
    print(f"[generate-tool-code] Starting for project {project_id}", file=sys.stderr, flush=True)
    
    project = project_manager.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    print(f"[generate-tool-code] Project found: {project.name}", file=sys.stderr, flush=True)
    
    try:
        # Build context about available state keys
        state_keys_info = []
        for key in project.app.state_keys:
            state_keys_info.append(f"- {key.name} ({key.type}): {key.description or 'No description'}")
        
        # Build the user prompt
        user_prompt = f"""Write an ADK tool with the following specifications:

**Tool Name:** {request.tool_name}
**Description:** {request.tool_description}

**Available State Keys:**
{chr(10).join(state_keys_info) if state_keys_info else 'No state keys defined yet.'}

**State Keys This Tool Should Use:**
{', '.join(request.state_keys_used) if request.state_keys_used else 'None specified - decide based on the tool purpose.'}

{f"**Additional Requirements:** {request.context}" if request.context else ""}

Write the complete Python code for this tool. Include appropriate imports at the top if needed (like `from google.adk.tools.tool_context import ToolContext`). Make sure the function name matches the tool name (use snake_case).
"""
        
        # Get model config from project
        model_config = None
        if project.app.models and len(project.app.models) > 0:
            if project.app.default_model_id:
                model_config = next((m for m in project.app.models if m.id == project.app.default_model_id), None)
            if not model_config:
                model_config = project.app.models[0]
        
        # Run the tool_code_generator agent
        result = await run_agent(
            agent_name="tool_code_generator",
            message=user_prompt,
            model_config=model_config,
            env_vars=project.app.env_vars,
            output_key="generated_code",
        )
        
        if result["success"]:
            code = clean_code_output(result["output"])
            return {"code": code, "success": True}
        else:
            print(f"[generate-tool-code] ERROR: {result.get('error')}", file=sys.stderr, flush=True)
            return {
                "code": None,
                "success": False,
                "error": result.get("error"),
                "traceback": result.get("traceback"),
            }
        
    except Exception as e:
        import traceback
        print(f"[generate-tool-code] ERROR: {e}", file=sys.stderr, flush=True)
        print(traceback.format_exc(), file=sys.stderr, flush=True)
        return {
            "code": None,
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc(),
        }


# ============================================================================
# AI-Assisted Callback Code Generation
# ============================================================================

class GenerateCallbackCodeRequest(BaseModel):
    callback_name: str
    callback_description: str
    callback_type: str  # e.g., "before_agent", "after_agent", "before_model", etc.
    state_keys_used: List[str] = []
    context: Optional[str] = None  # Additional hints from user

@app.post("/api/projects/{project_id}/generate-callback-code")
async def generate_callback_code(project_id: str, request: GenerateCallbackCodeRequest):
    """Generate Python code for an ADK callback using AI."""
    import traceback
    import sys
    
    print(f"[generate-callback-code] Starting for project {project_id}", file=sys.stderr, flush=True)
    
    project = project_manager.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    print(f"[generate-callback-code] Project found: {project.name}", file=sys.stderr, flush=True)
    
    try:
        # Build context about available state keys
        state_keys_info = []
        for key in project.app.state_keys:
            state_keys_info.append(f"- {key.name} ({key.type}): {key.description or 'No description'}")
        
        # Build the user prompt
        user_prompt = f"""Write an ADK callback with the following specifications:

**Callback Name:** {request.callback_name}
**Description:** {request.callback_description}
**Callback Type:** {request.callback_type}

**Available State Keys:**
{chr(10).join(state_keys_info) if state_keys_info else 'No state keys defined yet.'}

**State Keys This Callback Should Use:**
{', '.join(request.state_keys_used) if request.state_keys_used else 'None specified - decide based on the callback purpose.'}

{f"**Additional Requirements:** {request.context}" if request.context else ""}

Write the complete Python code for this callback. Include appropriate imports at the top if needed. Make sure the function name matches the callback name (use snake_case). The callback type is {request.callback_type}, so use the appropriate signature:
- For before_agent/after_agent: `(callback_context: CallbackContext) -> Optional[types.Content]`
- For before_model: `(*, callback_context: CallbackContext, llm_request: LlmRequest) -> Optional[LlmResponse]`
- For after_model: `(*, callback_context: CallbackContext, llm_response: LlmResponse, model_response_event: Optional[Event] = None) -> Optional[LlmResponse]`
- For before_tool: `(tool: BaseTool, tool_args: Dict[str, Any], tool_context: ToolContext) -> Optional[Dict]`
- For after_tool: `(tool: BaseTool, tool_args: Dict[str, Any], tool_context: ToolContext, result: Dict) -> Optional[Dict]`
"""
        
        # Get model config from project
        model_config = None
        if project.app.models and len(project.app.models) > 0:
            if project.app.default_model_id:
                model_config = next((m for m in project.app.models if m.id == project.app.default_model_id), None)
            if not model_config:
                model_config = project.app.models[0]
        
        # Run the callback_code_generator agent
        result = await run_agent(
            agent_name="callback_code_generator",
            message=user_prompt,
            model_config=model_config,
            env_vars=project.app.env_vars,
            output_key="generated_code",
        )
        
        if result["success"]:
            code = clean_code_output(result["output"])
            return {"code": code, "success": True}
        else:
            print(f"[generate-callback-code] ERROR: {result.get('error')}", file=sys.stderr, flush=True)
            return {
                "code": None,
                "success": False,
                "error": result.get("error"),
                "traceback": result.get("traceback"),
            }
        
    except Exception as e:
        import traceback
        print(f"[generate-callback-code] ERROR: {e}", file=sys.stderr, flush=True)
        print(traceback.format_exc(), file=sys.stderr, flush=True)
        return {
            "code": None,
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc(),
        }


# ============================================================================
# AI-Assisted Agent Configuration
# ============================================================================

class GenerateAgentConfigRequest(BaseModel):
    description: str  # User's description of what the agent should do

@app.post("/api/projects/{project_id}/generate-agent-config")
async def generate_agent_config(project_id: str, request: GenerateAgentConfigRequest):
    """Generate a complete agent configuration using AI."""
    project = project_manager.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Get available tools
    builtin_tools = [t["name"] for t in BUILTIN_TOOLS]
    mcp_servers_info = []
    for server in KNOWN_MCP_SERVERS:
        mcp_servers_info.append({
            "name": server.name,
            "description": server.description,
            "tools": server.tool_filter or [],
        })
    
    # Get existing agents for sub-agent selection
    existing_agents = [{"id": a.id, "name": a.name, "description": a.description, "type": a.type} for a in project.agents]
    
    # Get custom tools
    custom_tools = [{"name": t.name, "description": t.description} for t in project.custom_tools]
    
    # Build context message for the agent_config_generator agent
    # The agent's instruction already contains the "how to generate configs" guidance
    # We just need to provide the user's request and available resources
    context_message = f"""## User's Request
{request.description}

## Available Resources

### Built-in Tools
{json.dumps(builtin_tools, indent=2)}

### MCP Servers (with their tools)
{json.dumps(mcp_servers_info, indent=2)}

### Custom Tools in Project
{json.dumps(custom_tools, indent=2)}

### Existing Agents (can be used as sub-agents)
{json.dumps(existing_agents, indent=2)}
"""

    # Get model config from project
    model_config = None
    if project.app.models and len(project.app.models) > 0:
        if project.app.default_model_id:
            model_config = next((m for m in project.app.models if m.id == project.app.default_model_id), None)
        if not model_config:
            model_config = project.app.models[0]
    
    # Retry logic for models that don't always return JSON
    max_retries = 3
    last_error = None
    last_raw_response = None
    
    for attempt in range(max_retries):
        if attempt == 0:
            # First attempt: use the context message
            message = context_message
        else:
            # Retry: ask for just the JSON, referencing the failed attempt
            message = f"""Your previous response was not valid JSON. Here's what you returned:

{last_raw_response[:2000] if last_raw_response else 'No response'}

The error was: {last_error}

Please return ONLY the JSON object with the agent configuration. No explanation, no markdown, just the raw JSON starting with {{ and ending with }}. Make sure to close all brackets and quotes properly."""
        
        # Run the agent_config_generator agent
        result = await run_agent(
            agent_name="agent_config_generator",
            message=message,
            model_config=model_config,
            env_vars=project.app.env_vars,
            output_key="generated_config",
        )
        
        if not result["success"]:
            return {
                "config": None,
                "success": False,
                "error": result.get("error"),
                "traceback": result.get("traceback"),
            }
        
        # Extract and parse JSON from the response
        generated_text = result["output"]
        last_raw_response = generated_text
        
        # Try to extract JSON
        json_text = extract_json_from_text(generated_text)
        
        try:
            config = json.loads(json_text)
            return {"config": config, "success": True, "attempts": attempt + 1}
        except json.JSONDecodeError as e:
            last_error = str(e)
            if attempt < max_retries - 1:
                continue  # Try again
            else:
                # All retries exhausted
                return {
                    "config": None,
                    "success": False,
                    "error": f"Failed to parse JSON after {max_retries} attempts: {last_error}",
                    "raw_response": last_raw_response[:2000] if last_raw_response else None,
                    "attempts": max_retries,
                }
    
    # Should not reach here, but just in case
    return {"config": None, "success": False, "error": "Unknown error"}


# ============================================================================
# Watch Tool Execution
# ============================================================================

class WatchToolRequest(BaseModel):
    type: str  # 'builtin', 'mcp', 'custom'
    tool_name: str
    args: dict = {}
    mcp_server: Optional[str] = None
    sandbox_mode: bool = False  # If true, execute in Docker sandbox
    app_id: Optional[str] = None  # Required when sandbox_mode is true

@app.post("/api/projects/{project_id}/execute-tool")
async def execute_watch_tool(project_id: str, request: WatchToolRequest):
    """Execute a tool call for watch functionality.
    
    This is used by the Watch panel to execute read-only tool calls
    to query external state.
    
    When sandbox_mode is True and app_id is provided, MCP tools are
    executed inside the Docker sandbox container, allowing inspection
    of the container's filesystem and state.
    """
    project = project_manager.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    try:
        result = None
        
        if request.type == 'builtin':
            # Execute built-in tool
            if request.tool_name == 'google_search':
                # Google search requires API key and special handling
                result = {"error": "Google search not available in watch mode"}
            elif request.tool_name == 'exit_loop':
                result = {"info": "exit_loop is a control tool, not queryable"}
            else:
                result = {"error": f"Unknown built-in tool: {request.tool_name}"}
        
        elif request.type == 'custom':
            # Execute custom tool
            custom_tool = next((t for t in project.custom_tools if t.name == request.tool_name), None)
            if not custom_tool:
                result = {"error": f"Custom tool not found: {request.tool_name}"}
            else:
                # Create a sandboxed execution environment
                local_vars = {}
                try:
                    # Execute the tool code to define the function
                    exec(custom_tool.code, {"__builtins__": __builtins__}, local_vars)
                    
                    # Find the function (should be the tool name)
                    func = local_vars.get(request.tool_name)
                    if func and callable(func):
                        # Create a mock tool context for read-only execution
                        class MockToolContext:
                            state = {}
                            def __init__(self):
                                self.actions = type('Actions', (), {'state_delta': {}})()
                        
                        mock_ctx = MockToolContext()
                        result = func(mock_ctx, **request.args)
                    else:
                        result = {"error": f"Function {request.tool_name} not found in tool code"}
                except Exception as e:
                    result = {"error": f"Tool execution error: {str(e)}"}
        
        elif request.type == 'mcp':
            # Execute MCP tool
            if not request.mcp_server:
                result = {"error": "MCP server name required"}
            elif request.sandbox_mode and request.app_id:
                # Execute in Docker sandbox container
                from sandbox.docker_manager import get_sandbox_manager
                sandbox_manager = get_sandbox_manager()
                
                sandbox_result = await sandbox_manager.mcp_call_tool(
                    app_id=request.app_id,
                    server_name=request.mcp_server,
                    tool_name=request.tool_name,
                    args=request.args,
                )
                
                if "error" in sandbox_result:
                    result = {"error": sandbox_result["error"]}
                else:
                    result = sandbox_result.get("result", sandbox_result)
            else:
                # Execute on host (original behavior)
                # Find the MCP server config
                mcp_config = next((s for s in project.mcp_servers if s.name == request.mcp_server), None)
                if not mcp_config:
                    mcp_config = next((s for s in KNOWN_MCP_SERVERS if s.name == request.mcp_server), None)
                
                if not mcp_config:
                    result = {"error": f"MCP server not found: {request.mcp_server}"}
                else:
                    # Execute MCP tool on host using mcp_pool
                    try:
                        tool_result = await mcp_pool.call_tool(
                            server_name=request.mcp_server,
                            tool_name=request.tool_name,
                            args=request.args,
                        )
                        result = tool_result
                    except Exception as e:
                        result = {"error": f"MCP tool execution failed: {str(e)}"}
        
        else:
            result = {"error": f"Unknown tool type: {request.type}"}
        
        return {
            "success": True,
            "result": result,
            "tool_name": request.tool_name,
            "tool_type": request.type,
            "sandbox_mode": request.sandbox_mode,
        }
        
    except Exception as e:
        import traceback
        return {
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc(),
        }


# ============================================================================
# Health Check
# ============================================================================

@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok"}


@app.get("/api/version")
async def get_version():
    """Get version and build information."""
    version_info = {
        "version": "0.1.0",
    }
    
    # Try to read version from package metadata
    try:
        from importlib.metadata import version
        version_info["version"] = version("adk-playground")
    except Exception:
        pass
    
    return version_info


# ============================================================================
# System Metrics API
# ============================================================================

@app.get("/api/system/metrics")
async def get_system_metrics():
    """Get system metrics for the machine running the backend.
    
    Useful for monitoring local model inference or heavy workloads.
    Returns CPU, memory, disk, and GPU (if available) metrics.
    """
    metrics = {
        "timestamp": time.time(),
        "platform": platform.system(),
        "cpu": {},
        "memory": {},
        "disk": {},
        "gpu": [],
        "available": {
            "psutil": False,
            "gpu": False,
        }
    }
    
    # Try to get CPU and memory metrics via psutil
    try:
        import psutil
        metrics["available"]["psutil"] = True
        
        # CPU metrics
        cpu_percent = psutil.cpu_percent(interval=0.1, percpu=True)
        cpu_freq = psutil.cpu_freq()
        load_avg = None
        try:
            load_avg = list(os.getloadavg())  # Unix only
        except (AttributeError, OSError):
            pass
        
        metrics["cpu"] = {
            "percent": psutil.cpu_percent(interval=None),  # Overall CPU %
            "percent_per_core": cpu_percent,
            "count": psutil.cpu_count(),
            "count_physical": psutil.cpu_count(logical=False),
            "frequency_mhz": cpu_freq.current if cpu_freq else None,
            "frequency_max_mhz": cpu_freq.max if cpu_freq else None,
            "load_avg_1m": load_avg[0] if load_avg else None,
            "load_avg_5m": load_avg[1] if load_avg else None,
            "load_avg_15m": load_avg[2] if load_avg else None,
        }
        
        # Memory metrics
        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()
        metrics["memory"] = {
            "total_gb": round(mem.total / (1024**3), 2),
            "available_gb": round(mem.available / (1024**3), 2),
            "used_gb": round(mem.used / (1024**3), 2),
            "percent": mem.percent,
            "swap_total_gb": round(swap.total / (1024**3), 2),
            "swap_used_gb": round(swap.used / (1024**3), 2),
            "swap_percent": swap.percent,
        }
        
        # Disk metrics (root partition)
        try:
            disk = psutil.disk_usage('/')
            metrics["disk"] = {
                "total_gb": round(disk.total / (1024**3), 2),
                "used_gb": round(disk.used / (1024**3), 2),
                "free_gb": round(disk.free / (1024**3), 2),
                "percent": disk.percent,
            }
        except Exception:
            pass
            
    except ImportError:
        logger.debug("psutil not available for system metrics")
    
    # Try to get NVIDIA GPU metrics via pynvml
    try:
        import pynvml
        pynvml.nvmlInit()
        metrics["available"]["gpu"] = True
        
        device_count = pynvml.nvmlDeviceGetCount()
        for i in range(device_count):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)
            name = pynvml.nvmlDeviceGetName(handle)
            if isinstance(name, bytes):
                name = name.decode('utf-8')
            
            # Memory info
            mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
            
            # Utilization
            try:
                util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                gpu_util = util.gpu
                mem_util = util.memory
            except pynvml.NVMLError:
                gpu_util = None
                mem_util = None
            
            # Temperature
            try:
                temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
            except pynvml.NVMLError:
                temp = None
            
            # Power
            try:
                power = pynvml.nvmlDeviceGetPowerUsage(handle) / 1000  # mW to W
                power_limit = pynvml.nvmlDeviceGetPowerManagementLimit(handle) / 1000
            except pynvml.NVMLError:
                power = None
                power_limit = None
            
            metrics["gpu"].append({
                "index": i,
                "name": name,
                "memory_total_gb": round(mem_info.total / (1024**3), 2),
                "memory_used_gb": round(mem_info.used / (1024**3), 2),
                "memory_free_gb": round(mem_info.free / (1024**3), 2),
                "memory_percent": round(mem_info.used / mem_info.total * 100, 1),
                "utilization_percent": gpu_util,
                "memory_utilization_percent": mem_util,
                "temperature_c": temp,
                "power_w": round(power, 1) if power else None,
                "power_limit_w": round(power_limit, 1) if power_limit else None,
            })
        
        pynvml.nvmlShutdown()
    except ImportError:
        logger.debug("pynvml not available for GPU metrics")
    except Exception as e:
        logger.debug(f"Error getting GPU metrics: {e}")
    
    # Try to get Apple Silicon GPU metrics (macOS) using ioreg
    if platform.system() == "Darwin" and not metrics["gpu"]:
        try:
            # Get GPU name from system_profiler
            gpu_name = "Apple Silicon GPU"
            try:
                name_result = subprocess.run(
                    ["system_profiler", "SPDisplaysDataType", "-json"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if name_result.returncode == 0:
                    name_data = json.loads(name_result.stdout)
                    displays = name_data.get("SPDisplaysDataType", [])
                    if displays:
                        gpu_name = displays[0].get("sppci_model", gpu_name)
            except Exception:
                pass
            
            # Get GPU utilization from ioreg (IOAccelerator)
            result = subprocess.run(
                ["ioreg", "-r", "-c", "IOAccelerator"],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode == 0:
                output = result.stdout
                
                # Parse PerformanceStatistics
                # Look for: "Device Utilization %" = 74
                device_util = None
                renderer_util = None
                tiler_util = None
                in_use_memory = None
                alloc_memory = None
                
                # Find Device Utilization %
                match = re.search(r'"Device Utilization %"\s*=\s*(\d+)', output)
                if match:
                    device_util = int(match.group(1))
                
                # Find Renderer Utilization %
                match = re.search(r'"Renderer Utilization %"\s*=\s*(\d+)', output)
                if match:
                    renderer_util = int(match.group(1))
                
                # Find Tiler Utilization %
                match = re.search(r'"Tiler Utilization %"\s*=\s*(\d+)', output)
                if match:
                    tiler_util = int(match.group(1))
                
                # Find In use system memory (bytes)
                match = re.search(r'"In use system memory"\s*=\s*(\d+)', output)
                if match:
                    in_use_memory = int(match.group(1))
                
                # Find Alloc system memory (bytes)
                match = re.search(r'"Alloc system memory"\s*=\s*(\d+)', output)
                if match:
                    alloc_memory = int(match.group(1))
                
                # Use Device Utilization as the primary metric, fall back to Renderer
                utilization = device_util if device_util is not None else renderer_util
                
                # Calculate memory percent if we have both values
                memory_percent = None
                memory_used_gb = None
                memory_total_gb = None
                if in_use_memory is not None and alloc_memory is not None and alloc_memory > 0:
                    memory_percent = round(in_use_memory / alloc_memory * 100, 1)
                    memory_used_gb = round(in_use_memory / (1024**3), 2)
                    memory_total_gb = round(alloc_memory / (1024**3), 2)
                
                if utilization is not None:
                    metrics["gpu"].append({
                        "index": 0,
                        "name": gpu_name,
                        "type": "apple_silicon",
                        "utilization_percent": utilization,
                        "renderer_utilization_percent": renderer_util,
                        "tiler_utilization_percent": tiler_util,
                        "memory_used_gb": memory_used_gb,
                        "memory_total_gb": memory_total_gb,
                        "memory_percent": memory_percent,
                    })
                    metrics["available"]["gpu"] = True
        except Exception as e:
            logger.debug(f"Error getting Apple Silicon GPU metrics: {e}")
    
    # Try to get Raspberry Pi GPU metrics (Linux with V3D)
    if platform.system() == "Linux" and not metrics["gpu"]:
        try:
            # Check for V3D GPU stats (Raspberry Pi 4/5)
            gpu_stats_path = "/sys/devices/platform/axi/1002000000.v3d/gpu_stats"
            if not os.path.exists(gpu_stats_path):
                # Try alternative path for Pi 4
                gpu_stats_path = "/sys/devices/platform/soc/fe800000.v3d/gpu_stats"
            
            if os.path.exists(gpu_stats_path):
                # Read GPU stats
                with open(gpu_stats_path, 'r') as f:
                    lines = f.readlines()
                
                # Parse render queue stats (format: queue timestamp jobs runtime)
                render_runtime = None
                render_timestamp = None
                for line in lines:
                    parts = line.strip().split()
                    if len(parts) >= 4 and parts[0] == 'render':
                        render_timestamp = int(parts[1])
                        render_runtime = int(parts[3])
                        break
                
                # Calculate GPU utilization using cached previous reading
                gpu_util = None
                if render_runtime is not None and render_timestamp is not None:
                    cache_key = "rpi_gpu_stats"
                    if not hasattr(get_system_metrics, '_cache'):
                        get_system_metrics._cache = {}
                    
                    prev = get_system_metrics._cache.get(cache_key)
                    if prev:
                        time_delta = render_timestamp - prev['timestamp']
                        runtime_delta = render_runtime - prev['runtime']
                        if time_delta > 0:
                            # runtime is in nanoseconds, timestamp is also in nanoseconds
                            gpu_util = min(100, round((runtime_delta / time_delta) * 100, 1))
                    
                    # Store current reading for next calculation
                    get_system_metrics._cache[cache_key] = {
                        'timestamp': render_timestamp,
                        'runtime': render_runtime
                    }
                
                # Get Pi model name
                gpu_name = "Raspberry Pi GPU"
                try:
                    with open('/proc/device-tree/model', 'r') as f:
                        model = f.read().strip().replace('\x00', '')
                        if 'Raspberry Pi' in model:
                            gpu_name = model.split(' Rev')[0] + " V3D"
                except Exception:
                    pass
                
                # Get GPU memory usage from bo_stats (requires read access to debugfs)
                gpu_mem_used_kb = None
                gpu_mem_total_kb = None
                try:
                    bo_stats_path = "/sys/kernel/debug/dri/1002000000.v3d/bo_stats"
                    if os.path.exists(bo_stats_path):
                        with open(bo_stats_path, 'r') as f:
                            content = f.read()
                        match = re.search(r'allocated bo size \(kb\):\s*(\d+)', content)
                        if match:
                            gpu_mem_used_kb = int(match.group(1))
                except Exception:
                    pass
                
                # Get CMA total from /proc/meminfo (this is the GPU memory pool)
                try:
                    with open('/proc/meminfo', 'r') as f:
                        for line in f:
                            if line.startswith('CmaTotal:'):
                                match = re.search(r'CmaTotal:\s*(\d+)', line)
                                if match:
                                    gpu_mem_total_kb = int(match.group(1))
                                break
                except Exception:
                    pass
                
                if gpu_util is not None:
                    gpu_info = {
                        "index": 0,
                        "name": gpu_name,
                        "type": "raspberry_pi",
                        "utilization_percent": gpu_util,
                    }
                    
                    # Add memory info if available
                    if gpu_mem_used_kb is not None and gpu_mem_total_kb is not None:
                        gpu_info["memory_used_gb"] = round(gpu_mem_used_kb / (1024 * 1024), 3)
                        gpu_info["memory_total_gb"] = round(gpu_mem_total_kb / (1024 * 1024), 3)
                        gpu_info["memory_percent"] = round(gpu_mem_used_kb / gpu_mem_total_kb * 100, 1) if gpu_mem_total_kb > 0 else None
                    
                    metrics["gpu"].append(gpu_info)
                    metrics["available"]["gpu"] = True
        except Exception as e:
            logger.debug(f"Error getting Raspberry Pi GPU metrics: {e}")
    
    return metrics


# ============================================================================
# Knowledge Base API
# ============================================================================

from knowledge_service import get_knowledge_manager, KnowledgeEntry, SearchResult, chunk_text, fetch_url_content


# ============================================================================
# SkillSet API Endpoints
# ============================================================================

class AddSkillSetTextRequest(BaseModel):
    text: str
    source_id: str = ""
    source_name: str = "manual"


class AddSkillSetURLRequest(BaseModel):
    url: str
    source_name: Optional[str] = None  # Defaults to URL
    chunk_size: int = 500
    chunk_overlap: int = 50


class SearchSkillSetRequest(BaseModel):
    query: str
    top_k: int = 10
    min_score: float = 0.0


def get_skillset_model(project_id: str, skillset_id: str) -> str:
    """Get the embedding model name for a skillset."""
    project = project_manager.get_project(project_id)
    if not project:
        return "text-embedding-004"  # Default Gemini embedding model
    
    skillset = next((s for s in project.skillsets if s.id == skillset_id), None)
    if not skillset:
        return "text-embedding-004"
    
    # Use configured embedding model, or app model, or default
    if skillset.embedding_model:
        return skillset.embedding_model
    elif skillset.app_model_id:
        app_model = next((m for m in project.app.models if m.id == skillset.app_model_id), None)
        if app_model:
            return app_model.model_name
    
    return "text-embedding-004"


@app.get("/api/projects/{project_id}/skillsets/{skillset_id}/entries")
async def list_skillset_entries(project_id: str, skillset_id: str, limit: int = 100):
    """List entries in a skillset store."""
    manager = get_knowledge_manager()
    model_name = get_skillset_model(project_id, skillset_id)
    store = manager.get_store(project_id, skillset_id, model_name)
    entries = store.list_all(limit=limit)
    return {
        "entries": [
            {
                "id": e.id,
                "text": e.text[:200] + ("..." if len(e.text) > 200 else ""),
                "full_text": e.text,
                "source_id": e.source_id,
                "source_name": e.source_name,
                "created_at": e.created_at,
                "has_embedding": len(e.embedding) > 0,
            }
            for e in entries
        ],
        "total": len(entries),
    }


@app.get("/api/projects/{project_id}/skillsets/{skillset_id}/stats")
async def skillset_stats(project_id: str, skillset_id: str):
    """Get statistics for a skillset store."""
    manager = get_knowledge_manager()
    model_name = get_skillset_model(project_id, skillset_id)
    store = manager.get_store(project_id, skillset_id, model_name)
    return store.stats()


@app.post("/api/projects/{project_id}/skillsets/{skillset_id}/text")
async def add_skillset_text(project_id: str, skillset_id: str, request: AddSkillSetTextRequest):
    """Add text entry to a skillset store."""
    manager = get_knowledge_manager()
    model_name = get_skillset_model(project_id, skillset_id)
    store = manager.get_store(project_id, skillset_id, model_name)
    entry = store.add(
        text=request.text,
        source_id=request.source_id,
        source_name=request.source_name,
    )
    return {
        "id": entry.id,
        "text": entry.text[:200] + ("..." if len(entry.text) > 200 else ""),
        "source_name": entry.source_name,
        "created_at": entry.created_at,
        "has_embedding": len(entry.embedding) > 0,
    }


@app.post("/api/projects/{project_id}/skillsets/{skillset_id}/url")
async def add_skillset_url(project_id: str, skillset_id: str, request: AddSkillSetURLRequest):
    """Fetch content from URL and add to skillset store."""
    try:
        content = await fetch_url_content(request.url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to fetch URL: {str(e)}")
    
    source_name = request.source_name or request.url
    
    # Chunk the content
    chunks = chunk_text(content, request.chunk_size, request.chunk_overlap)
    
    manager = get_knowledge_manager()
    model_name = get_skillset_model(project_id, skillset_id)
    store = manager.get_store(project_id, skillset_id, model_name)
    
    # Generate a source_id for this URL
    import hashlib
    source_id = hashlib.sha256(request.url.encode()).hexdigest()[:12]
    
    entries = store.add_batch(
        texts=chunks,
        source_id=source_id,
        source_name=source_name,
    )
    
    return {
        "source_id": source_id,
        "source_name": source_name,
        "url": request.url,
        "chunks_added": len(entries),
        "total_chars": len(content),
    }


@app.post("/api/projects/{project_id}/skillsets/{skillset_id}/file")
async def add_skillset_file(
    project_id: str,
    skillset_id: str,
    file: UploadFile = File(...),
    chunk_size: int = 500,
    chunk_overlap: int = 50,
):
    """Upload a file and add its content to skillset store."""
    content = await file.read()
    
    # Try to decode as text
    try:
        text_content = content.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text_content = content.decode("latin-1")
        except:
            raise HTTPException(status_code=400, detail="Could not decode file as text")
    
    source_name = file.filename or "uploaded_file"
    
    # Chunk the content
    chunks = chunk_text(text_content, chunk_size, chunk_overlap)
    
    manager = get_knowledge_manager()
    model_name = get_skillset_model(project_id, skillset_id)
    store = manager.get_store(project_id, skillset_id, model_name)
    
    # Generate a source_id for this file
    import hashlib
    source_id = hashlib.sha256(content).hexdigest()[:12]
    
    entries = store.add_batch(
        texts=chunks,
        source_id=source_id,
        source_name=source_name,
    )
    
    return {
        "source_id": source_id,
        "source_name": source_name,
        "filename": file.filename,
        "chunks_added": len(entries),
        "total_chars": len(text_content),
    }


@app.post("/api/projects/{project_id}/skillsets/{skillset_id}/search")
async def search_skillset(project_id: str, skillset_id: str, request: SearchSkillSetRequest):
    """Search a skillset store."""
    manager = get_knowledge_manager()
    model_name = get_skillset_model(project_id, skillset_id)
    store = manager.get_store(project_id, skillset_id, model_name)
    results = store.search(
        query=request.query,
        top_k=request.top_k,
        min_score=request.min_score,
    )
    return {
        "query": request.query,
        "results": [
            {
                "id": r.entry.id,
                "text": r.entry.text,
                "score": round(r.score, 4),
                "source_id": r.entry.source_id,
                "source_name": r.entry.source_name,
                "created_at": r.entry.created_at,
            }
            for r in results
        ],
        "count": len(results),
    }


@app.delete("/api/projects/{project_id}/skillsets/{skillset_id}/entries/{entry_id}")
async def delete_skillset_entry(project_id: str, skillset_id: str, entry_id: str):
    """Delete a specific entry from a skillset store."""
    manager = get_knowledge_manager()
    model_name = get_skillset_model(project_id, skillset_id)
    store = manager.get_store(project_id, skillset_id, model_name)
    if store.remove(entry_id):
        return {"deleted": True, "id": entry_id}
    raise HTTPException(status_code=404, detail="Entry not found")


@app.delete("/api/projects/{project_id}/skillsets/{skillset_id}/sources/{source_id}")
async def delete_skillset_source(project_id: str, skillset_id: str, source_id: str):
    """Delete all entries from a specific source."""
    manager = get_knowledge_manager()
    model_name = get_skillset_model(project_id, skillset_id)
    store = manager.get_store(project_id, skillset_id, model_name)
    count = store.remove_by_source(source_id)
    return {"deleted": count, "source_id": source_id}


@app.delete("/api/projects/{project_id}/skillsets/{skillset_id}/entries")
async def clear_skillset(project_id: str, skillset_id: str):
    """Clear all entries in a skillset store."""
    manager = get_knowledge_manager()
    model_name = get_skillset_model(project_id, skillset_id)
    store = manager.get_store(project_id, skillset_id, model_name)
    count = store.clear()
    return {"cleared": count}


@app.get("/api/skillsets/embeddings-available")
async def check_embeddings_available():
    """Check if embeddings are available."""
    manager = get_knowledge_manager()
    return {"available": manager.embeddings_available()}


# ============================================================================
# Evaluation API Endpoints
# ============================================================================

# Try to use ADK-based evaluation, fall back to custom implementation
try:
    from adk_evaluation_service import AdkEvaluationService
    USE_ADK_EVAL = True
except ImportError:
    USE_ADK_EVAL = False

from evaluation_service import create_evaluation_service, ResponseEvaluator, TrajectoryEvaluator


# Create evaluation service
eval_service = None
adk_eval_service = None

def get_eval_service():
    """Get or create the evaluation service (legacy)."""
    global eval_service
    if eval_service is None:
        eval_service = create_evaluation_service(runtime_manager)
    return eval_service

def get_adk_eval_service():
    """Get or create the ADK-based evaluation service."""
    global adk_eval_service
    if adk_eval_service is None and USE_ADK_EVAL:
        adk_eval_service = AdkEvaluationService(runtime_manager)
    return adk_eval_service


class CreateEvalSetRequest(BaseModel):
    """Request to create an evaluation set."""
    name: str
    description: str = ""
    eval_config: Optional[Dict[str, Any]] = None  # Uses EvalConfig structure


class CreateEvalCaseRequest(BaseModel):
    """Request to create an evaluation case."""
    name: str
    description: str = ""
    invocations: List[Dict[str, Any]] = []
    initial_state: Dict[str, Any] = {}
    expected_final_state: Optional[Dict[str, Any]] = None
    rubrics: List[Dict[str, str]] = []
    tags: List[str] = []


class RunEvalSetRequest(BaseModel):
    """Request to run an evaluation set."""
    agent_id: Optional[str] = None


class RunEvalCaseRequest(BaseModel):
    """Request to run a single evaluation case."""
    agent_id: Optional[str] = None


class QuickEvalRequest(BaseModel):
    """Request to run a quick evaluation (single message)."""
    user_message: str
    expected_response: Optional[str] = None
    expected_tool_calls: List[Dict[str, Any]] = []
    agent_id: Optional[str] = None


@app.get("/api/projects/{project_id}/eval-sets")
async def list_eval_sets(project_id: str):
    """List all evaluation sets in a project."""
    project = project_manager.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    return {
        "eval_sets": [es.model_dump(mode="json") for es in project.eval_sets]
    }


@app.post("/api/projects/{project_id}/eval-sets")
async def create_eval_set(project_id: str, request: CreateEvalSetRequest):
    """Create a new evaluation set."""
    project = project_manager.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    import time
    
    # Parse eval_config if provided
    eval_config = None
    if request.eval_config:
        eval_config = EvalConfig(**request.eval_config)
    else:
        eval_config = EvalConfig()  # Use defaults
    
    eval_set = EvalSet(
        id=str(uuid.uuid4())[:8],
        name=request.name,
        description=request.description,
        eval_config=eval_config,
        created_at=time.time(),
        updated_at=time.time(),
    )
    
    project.eval_sets.append(eval_set)
    project_manager.save_project(project)
    
    return {"eval_set": eval_set.model_dump(mode="json")}


@app.get("/api/projects/{project_id}/eval-sets/{eval_set_id}")
async def get_eval_set(project_id: str, eval_set_id: str):
    """Get an evaluation set by ID."""
    project = project_manager.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    eval_set = next((es for es in project.eval_sets if es.id == eval_set_id), None)
    if not eval_set:
        raise HTTPException(status_code=404, detail="Eval set not found")
    
    return {"eval_set": eval_set.model_dump(mode="json")}


@app.put("/api/projects/{project_id}/eval-sets/{eval_set_id}")
async def update_eval_set(project_id: str, eval_set_id: str, data: dict):
    """Update an evaluation set."""
    project = project_manager.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    import time
    
    for i, es in enumerate(project.eval_sets):
        if es.id == eval_set_id:
            # Handle eval_config specially
            if "eval_config" in data and isinstance(data["eval_config"], dict):
                # Parse metrics if present
                config_data = data["eval_config"]
                if "metrics" in config_data:
                    parsed_metrics = []
                    for m in config_data["metrics"]:
                        if isinstance(m.get("metric"), str):
                            try:
                                m["metric"] = EvalMetricType(m["metric"])
                            except ValueError:
                                pass
                        parsed_metrics.append(m)
                    config_data["metrics"] = parsed_metrics
                
                if "default_trajectory_match_type" in config_data:
                    try:
                        config_data["default_trajectory_match_type"] = ToolTrajectoryMatchType(
                            config_data["default_trajectory_match_type"]
                        )
                    except ValueError:
                        pass
            
            # Update fields
            updated_data = es.model_dump()
            updated_data.update(data)
            updated_data["updated_at"] = time.time()
            
            project.eval_sets[i] = EvalSet.model_validate(updated_data)
            project_manager.save_project(project)
            
            return {"eval_set": project.eval_sets[i].model_dump(mode="json")}
    
    raise HTTPException(status_code=404, detail="Eval set not found")


@app.delete("/api/projects/{project_id}/eval-sets/{eval_set_id}")
async def delete_eval_set(project_id: str, eval_set_id: str):
    """Delete an evaluation set."""
    project = project_manager.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    original_len = len(project.eval_sets)
    project.eval_sets = [es for es in project.eval_sets if es.id != eval_set_id]
    
    if len(project.eval_sets) == original_len:
        raise HTTPException(status_code=404, detail="Eval set not found")
    
    project_manager.save_project(project)
    return {"success": True}


class GenerateEvalSetRequest(BaseModel):
    """Request to generate an eval set using AI."""
    agent_id: Optional[str] = None  # Which agent to generate tests for (defaults to root)
    context: Optional[str] = None  # Additional context or focus areas


@app.post("/api/projects/{project_id}/generate-eval-set")
async def generate_eval_set(project_id: str, request: GenerateEvalSetRequest):
    """Generate an evaluation set using AI based on the project's agents."""
    import time
    import json
    import traceback
    
    project = project_manager.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    try:
        # Find the target agent
        target_agent_id = request.agent_id or project.app.root_agent_id
        target_agent = next((a for a in project.agents if a.id == target_agent_id), None)
        
        if not target_agent:
            raise HTTPException(status_code=404, detail=f"Agent '{target_agent_id}' not found")
        
        # Build context about the agent for the AI
        agent_info = {
            "name": target_agent.name,
            "type": target_agent.type,
            "description": getattr(target_agent, "description", ""),
            "instruction": getattr(target_agent, "instruction", ""),
        }
        
        # Collect tool information
        tools_info = []
        if hasattr(target_agent, "tools"):
            for tool in (target_agent.tools or []):
                if tool.get("type") == "builtin":
                    tools_info.append({"type": "builtin", "name": tool.get("name")})
                elif tool.get("type") == "mcp":
                    server = tool.get("server", {})
                    tools_info.append({
                        "type": "mcp",
                        "server": server.get("name"),
                        "tools": server.get("tool_filter"),
                    })
                elif tool.get("type") == "function":
                    tools_info.append({"type": "function", "name": tool.get("name")})
        
        # Collect state key information
        state_keys_info = []
        for key in project.app.state_keys:
            state_keys_info.append({
                "name": key.name,
                "type": key.type,
                "description": key.description,
            })
        
        # Build context message for the eval_set_generator agent
        # The agent's instruction already contains the "how to generate test sets" guidance
        # We just need to provide the agent configuration and available resources
        context_message = f"""## Agent to Test

**Name:** {agent_info['name']}
**Type:** {agent_info['type']}
**Description:** {agent_info['description'] or 'No description provided'}

**Instruction:**
{agent_info['instruction'] or 'No instruction provided'}

## Available Tools
{json.dumps(tools_info, indent=2) if tools_info else 'No tools configured'}

## State Keys
{json.dumps(state_keys_info, indent=2) if state_keys_info else 'No state keys defined'}

{f"## Additional Context / Focus Areas{chr(10)}{request.context}" if request.context else ""}
"""
        
        # Get model config from project
        model_config = None
        if project.app.models and len(project.app.models) > 0:
            if project.app.default_model_id:
                model_config = next((m for m in project.app.models if m.id == project.app.default_model_id), None)
            if not model_config:
                model_config = project.app.models[0]
        
        # Run the eval_set_generator agent
        result = await run_agent(
            agent_name="eval_set_generator",
            message=context_message,
            model_config=model_config,
            env_vars=project.app.env_vars,
            output_key="generated_eval_set",
        )
        
        if not result["success"]:
            return {
                "success": False,
                "error": result.get("error"),
                "traceback": result.get("traceback"),
            }
        
        # Parse the generated JSON
        output = result["output"]
        json_str = extract_json_from_text(output)
        
        try:
            generated = json.loads(json_str)
        except json.JSONDecodeError as e:
            return {
                "success": False,
                "error": f"Failed to parse AI output as JSON: {e}",
                "raw_output": output,
            }
        
        # Create the eval set
        eval_set_id = f"eval_set_{int(time.time())}_{target_agent.name}"
        
        # Convert generated cases to proper format
        eval_cases = []
        for i, case_data in enumerate(generated.get("eval_cases", [])):
            case_id = f"case_{i+1}_{case_data.get('name', 'unnamed')}"
            
            # Parse expected tool calls
            expected_tool_calls = []
            for tc in case_data.get("expected_tool_calls", []):
                expected_tool_calls.append(ExpectedToolCall(
                    name=tc.get("name", ""),
                    args=tc.get("args"),
                    args_match_mode=tc.get("args_match_mode", "ignore"),
                ))
            
            # Parse rubrics
            rubrics = []
            for r in case_data.get("rubrics", []):
                if isinstance(r, dict) and "rubric" in r:
                    rubrics.append(Rubric(rubric=r["rubric"]))
                elif isinstance(r, str):
                    rubrics.append(Rubric(rubric=r))
            
            # Create invocation from user_message
            invocations = [EvalInvocation(
                id=f"inv_1",
                user_message=case_data.get("user_message", ""),
                expected_response=case_data.get("expected_response"),
                expected_tool_calls=expected_tool_calls,
                rubrics=rubrics,
            )]
            
            # Enable rubric-based LLM judge metrics if we have rubrics
            enabled_metrics = []
            if rubrics:
                # Enable rubric-based response quality judge with 0.7 threshold
                enabled_metrics.append(EnabledMetric(
                    metric="rubric_based_final_response_quality_v1",
                    threshold=0.7
                ))
                # If there are expected tool calls, also enable tool use quality judge
                if expected_tool_calls:
                    enabled_metrics.append(EnabledMetric(
                        metric="rubric_based_tool_use_quality_v1",
                        threshold=0.7
                    ))
            
            eval_case = EvalCase(
                id=case_id,
                name=case_data.get("name", f"test_case_{i+1}"),
                description=case_data.get("description", ""),
                invocations=invocations,
                expected_final_state=case_data.get("expected_final_state"),
                rubrics=rubrics,  # Also add rubrics at case level
                enabled_metrics=enabled_metrics,
                target_agent=target_agent_id if target_agent_id != project.app.root_agent_id else None,
            )
            eval_cases.append(eval_case)
        
        # Create the eval set
        eval_set = EvalSet(
            id=eval_set_id,
            name=generated.get("name", f"Tests for {target_agent.name}"),
            description=generated.get("description", f"AI-generated test set for {target_agent.name}"),
            eval_cases=eval_cases,
            eval_config=EvalConfig(),
            created_at=time.time(),
            updated_at=time.time(),
        )
        
        # Save to project
        project.eval_sets.append(eval_set)
        project_manager.save_project(project)
        
        return {
            "success": True,
            "eval_set": eval_set.model_dump(mode="json"),
            "cases_generated": len(eval_cases),
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc(),
        }


@app.post("/api/projects/{project_id}/eval-sets/{eval_set_id}/cases")
async def create_eval_case(project_id: str, eval_set_id: str, request: CreateEvalCaseRequest):
    """Create a new evaluation case in an eval set."""
    project = project_manager.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    eval_set = next((es for es in project.eval_sets if es.id == eval_set_id), None)
    if not eval_set:
        raise HTTPException(status_code=404, detail="Eval set not found")
    
    import time
    
    # Parse invocations
    invocations = []
    for inv_data in request.invocations:
        expected_tool_calls = []
        for tc in inv_data.get("expected_tool_calls", []):
            expected_tool_calls.append(ExpectedToolCall(
                name=tc.get("name", ""),
                args=tc.get("args"),
                args_match_mode=tc.get("args_match_mode", "ignore"),
            ))
        
        # Parse trajectory match type for invocation
        try:
            inv_match_type = ToolTrajectoryMatchType(inv_data.get("tool_trajectory_match_type", "in_order"))
        except ValueError:
            inv_match_type = ToolTrajectoryMatchType.IN_ORDER
        
        # Parse rubrics
        inv_rubrics = [Rubric(rubric=r.get("rubric", "")) for r in inv_data.get("rubrics", [])]
        
        invocations.append(EvalInvocation(
            id=inv_data.get("id", str(uuid.uuid4())[:8]),
            user_message=inv_data.get("user_message", ""),
            expected_response=inv_data.get("expected_response"),
            expected_tool_calls=expected_tool_calls,
            tool_trajectory_match_type=inv_match_type,
            rubrics=inv_rubrics,
        ))
    
    # Parse case-level rubrics
    case_rubrics = [Rubric(rubric=r.get("rubric", "")) for r in request.rubrics]
    
    eval_case = EvalCase(
        id=str(uuid.uuid4())[:8],
        name=request.name,
        description=request.description,
        invocations=invocations,
        initial_state=request.initial_state,
        expected_final_state=request.expected_final_state,
        rubrics=case_rubrics,
        tags=request.tags,
    )
    
    eval_set.eval_cases.append(eval_case)
    eval_set.updated_at = time.time()
    project_manager.save_project(project)
    
    return {"eval_case": eval_case.model_dump(mode="json")}


@app.put("/api/projects/{project_id}/eval-sets/{eval_set_id}/cases/{case_id}")
async def update_eval_case(project_id: str, eval_set_id: str, case_id: str, data: dict):
    """Update an evaluation case."""
    project = project_manager.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    eval_set = next((es for es in project.eval_sets if es.id == eval_set_id), None)
    if not eval_set:
        raise HTTPException(status_code=404, detail="Eval set not found")
    
    import time
    
    for i, case in enumerate(eval_set.eval_cases):
        if case.id == case_id:
            # Parse invocations if provided
            if "invocations" in data:
                invocations = []
                for inv_data in data["invocations"]:
                    expected_tool_calls = []
                    for tc in inv_data.get("expected_tool_calls", []):
                        expected_tool_calls.append(ExpectedToolCall(
                            name=tc.get("name", ""),
                            args=tc.get("args"),
                            args_match_mode=tc.get("args_match_mode", "ignore"),
                        ))
                    
                    # Parse trajectory match type
                    try:
                        inv_match_type = ToolTrajectoryMatchType(
                            inv_data.get("tool_trajectory_match_type", "in_order")
                        )
                    except ValueError:
                        inv_match_type = ToolTrajectoryMatchType.IN_ORDER
                    
                    # Parse rubrics
                    inv_rubrics = [Rubric(rubric=r.get("rubric", "")) for r in inv_data.get("rubrics", [])]
                    
                    invocations.append(EvalInvocation(
                        id=inv_data.get("id", str(uuid.uuid4())[:8]),
                        user_message=inv_data.get("user_message", ""),
                        expected_response=inv_data.get("expected_response"),
                        expected_tool_calls=expected_tool_calls,
                        tool_trajectory_match_type=inv_match_type,
                        rubrics=inv_rubrics,
                    ))
                data["invocations"] = invocations
            
            # Parse case-level rubrics if provided
            if "rubrics" in data:
                data["rubrics"] = [Rubric(rubric=r.get("rubric", "")) for r in data["rubrics"]]
            
            # Update fields
            updated_data = case.model_dump()
            updated_data.update(data)
            
            eval_set.eval_cases[i] = EvalCase.model_validate(updated_data)
            eval_set.updated_at = time.time()
            project_manager.save_project(project)
            
            return {"eval_case": eval_set.eval_cases[i].model_dump(mode="json")}
    
    raise HTTPException(status_code=404, detail="Eval case not found")


@app.delete("/api/projects/{project_id}/eval-sets/{eval_set_id}/cases/{case_id}")
async def delete_eval_case(project_id: str, eval_set_id: str, case_id: str):
    """Delete an evaluation case."""
    project = project_manager.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    eval_set = next((es for es in project.eval_sets if es.id == eval_set_id), None)
    if not eval_set:
        raise HTTPException(status_code=404, detail="Eval set not found")
    
    import time
    
    original_len = len(eval_set.eval_cases)
    eval_set.eval_cases = [c for c in eval_set.eval_cases if c.id != case_id]
    
    if len(eval_set.eval_cases) == original_len:
        raise HTTPException(status_code=404, detail="Eval case not found")
    
    eval_set.updated_at = time.time()
    project_manager.save_project(project)
    return {"success": True}


@app.post("/api/projects/{project_id}/eval-sets/{eval_set_id}/run")
async def run_eval_set(project_id: str, eval_set_id: str, request: RunEvalSetRequest):
    """Run all evaluation cases in an eval set."""
    project = project_manager.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    eval_set = next((es for es in project.eval_sets if es.id == eval_set_id), None)
    if not eval_set:
        raise HTTPException(status_code=404, detail="Eval set not found")
    
    try:
        # Try ADK-based evaluation first
        adk_service = get_adk_eval_service()
        if adk_service:
            try:
                result = await adk_service.run_eval_set(
                    project=project,
                    eval_set=eval_set,
                )
                return {"result": result.model_dump(mode="json")}
            except Exception as adk_err:
                logger.warning(f"ADK evaluation failed, falling back to custom: {adk_err}")
        
        # Fall back to custom evaluation service
        service = get_eval_service()
        result = await service.run_eval_set(
            project=project,
            eval_set=eval_set,
            agent_id=request.agent_id,
        )
        
        return {"result": result.model_dump(mode="json")}
    
    except Exception as e:
        import traceback
        raise HTTPException(
            status_code=500,
            detail=f"Evaluation failed: {str(e)}\n{traceback.format_exc()}"
        )


@app.post("/api/projects/{project_id}/eval-sets/{eval_set_id}/cases/{case_id}/run")
async def run_eval_case(
    project_id: str,
    eval_set_id: str,
    case_id: str,
    request: RunEvalCaseRequest
):
    """Run a single evaluation case."""
    project = project_manager.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    eval_set = next((es for es in project.eval_sets if es.id == eval_set_id), None)
    if not eval_set:
        raise HTTPException(status_code=404, detail="Eval set not found")
    
    eval_case = next((c for c in eval_set.eval_cases if c.id == case_id), None)
    if not eval_case:
        raise HTTPException(status_code=404, detail="Eval case not found")
    
    try:
        # Try ADK-based evaluation first
        adk_service = get_adk_eval_service()
        if adk_service:
            try:
                result = await adk_service.run_eval_case(
                    project=project,
                    eval_case=eval_case,
                    eval_config=eval_set.eval_config,
                    eval_set_id=eval_set.id,
                    eval_set_name=eval_set.name,
                )
                return {"result": result.model_dump(mode="json")}
            except Exception as adk_err:
                logger.warning(f"ADK evaluation failed, falling back to custom: {adk_err}")
        
        # Fall back to custom evaluation service
        service = get_eval_service()
        result = await service.run_eval_case(
            project=project,
            eval_case=eval_case,
            eval_config=eval_set.eval_config,
            agent_id=request.agent_id,
            eval_set_id=eval_set.id,
            eval_set_name=eval_set.name,
        )
        
        return {"result": result.model_dump(mode="json")}
    
    except Exception as e:
        import traceback
        raise HTTPException(
            status_code=500,
            detail=f"Evaluation failed: {str(e)}\n{traceback.format_exc()}"
        )


@app.post("/api/projects/{project_id}/quick-eval")
async def quick_eval(project_id: str, request: QuickEvalRequest):
    """Run a quick evaluation with a single message.
    
    This is useful for testing without creating a full eval set.
    """
    project = project_manager.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    try:
        # Create a temporary eval case
        expected_tool_calls = []
        for tc in request.expected_tool_calls:
            expected_tool_calls.append(ExpectedToolCall(
                name=tc.get("name", ""),
                args=tc.get("args"),
                args_match_mode=tc.get("args_match_mode", "ignore"),
            ))
        
        invocation = EvalInvocation(
            id="quick_eval",
            user_message=request.user_message,
            expected_response=request.expected_response,
            expected_tool_calls=expected_tool_calls,
            tool_trajectory_match_type=ToolTrajectoryMatchType.IN_ORDER,
            rubrics=[],
        )
        
        eval_case = EvalCase(
            id="quick_eval_case",
            name="Quick Evaluation",
            invocations=[invocation],
            rubrics=[],
            tags=[],
        )
        
        # Create default eval config
        eval_config = EvalConfig()
        
        service = get_eval_service()
        result = await service.run_eval_case(
            project=project,
            eval_case=eval_case,
            eval_config=eval_config,
            agent_id=request.agent_id,
        )
        
        return {"result": result.model_dump(mode="json")}
    
    except Exception as e:
        import traceback
        raise HTTPException(
            status_code=500,
            detail=f"Evaluation failed: {str(e)}\n{traceback.format_exc()}"
        )


# ============================================================================
# EVAL RUN HISTORY ENDPOINTS
# ============================================================================

def _get_eval_history_dir(project_id: str) -> Path:
    """Get the directory for storing eval run history."""
    project_dir = project_manager.projects_dir / project_id
    history_dir = project_dir / "eval_history"
    history_dir.mkdir(parents=True, exist_ok=True)
    return history_dir


@app.post("/api/projects/{project_id}/eval-history")
async def save_eval_run(project_id: str, data: dict):
    """Save an evaluation run result to history."""
    history_dir = _get_eval_history_dir(project_id)
    run_id = data.get("id") or f"{int(time.time() * 1000)}"
    file_path = history_dir / f"{run_id}.json"
    
    with open(file_path, "w") as f:
        json.dump(data, f, indent=2)
    
    return {"success": True, "run_id": run_id}


@app.get("/api/projects/{project_id}/eval-history")
async def list_eval_runs(project_id: str):
    """List all saved evaluation runs for a project."""
    history_dir = _get_eval_history_dir(project_id)
    runs = []
    
    for file_path in sorted(history_dir.glob("*.json"), reverse=True):
        try:
            with open(file_path) as f:
                data = json.load(f)
                runs.append({
                    "id": data.get("id", file_path.stem),
                    "eval_set_name": data.get("eval_set_name", "Unknown"),
                    "started_at": data.get("started_at", 0),
                    "ended_at": data.get("ended_at", 0),
                    "total_cases": data.get("total_cases", 0),
                    "passed_cases": data.get("passed_cases", 0),
                    "failed_cases": data.get("failed_cases", 0),
                    "overall_pass_rate": data.get("overall_pass_rate", 0),
                })
        except Exception as e:
            logger.warning(f"Failed to read eval history file {file_path}: {e}")
    
    return {"runs": runs}


@app.get("/api/projects/{project_id}/eval-history/{run_id}")
async def get_eval_run(project_id: str, run_id: str):
    """Get a specific saved evaluation run."""
    history_dir = _get_eval_history_dir(project_id)
    file_path = history_dir / f"{run_id}.json"
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Eval run not found")
    
    with open(file_path) as f:
        data = json.load(f)
    
    return {"run": data}


@app.delete("/api/projects/{project_id}/eval-history/{run_id}")
async def delete_eval_run(project_id: str, run_id: str):
    """Delete a saved evaluation run."""
    history_dir = _get_eval_history_dir(project_id)
    file_path = history_dir / f"{run_id}.json"
    
    if file_path.exists():
        file_path.unlink()
    
    return {"success": True}


@app.post("/api/eval/compare-text")
async def compare_text(data: dict):
    """Compare two text strings using ROUGE-1 scoring.
    
    Useful for testing the fuzzy matching without running an agent.
    """
    reference = data.get("reference", "")
    candidate = data.get("candidate", "")
    threshold = data.get("threshold", 0.7)
    
    evaluator = ResponseEvaluator(threshold=threshold)
    score, passed = evaluator.evaluate(candidate, reference)
    
    return {
        "score": score,
        "passed": passed,
        "threshold": threshold,
        "reference": reference,
        "candidate": candidate,
    }


@app.post("/api/eval/compare-tools")
async def compare_tools(data: dict):
    """Compare tool call trajectories.
    
    Useful for testing trajectory matching without running an agent.
    """
    actual = data.get("actual", [])  # [{"name": ..., "args": ...}, ...]
    expected = data.get("expected", [])  # [{"name": ..., "args": ..., "args_match_mode": ...}, ...]
    match_type = data.get("match_type", "in_order")
    
    try:
        mt = ToolTrajectoryMatchType(match_type)
    except ValueError:
        mt = ToolTrajectoryMatchType.IN_ORDER
    
    # Parse expected tool calls
    expected_calls = []
    for tc in expected:
        expected_calls.append(ExpectedToolCall(
            name=tc.get("name", ""),
            args=tc.get("args"),
            args_match_mode=tc.get("args_match_mode", "exact"),
        ))
    
    evaluator = TrajectoryEvaluator(match_type=mt)
    score, passed = evaluator.evaluate(actual, expected_calls)
    
    return {
        "score": score,
        "passed": passed,
        "match_type": match_type,
        "actual": actual,
        "expected": expected,
    }


# ============================================================================
# ============================================================================
# Session to Eval Case Conversion
# ============================================================================

class SessionToEvalCaseRequest(BaseModel):
    """Request to convert a session to an eval case."""
    session_id: str
    eval_set_id: str
    case_name: str = "Test Case from Session"
    expected_response: Optional[str] = None


@app.post("/api/projects/{project_id}/session-to-eval-case")
async def session_to_eval_case(project_id: str, request: SessionToEvalCaseRequest):
    """Convert a session into an eval case.
    
    This extracts user messages and tool calls from a session and creates
    an eval case that can be used for regression testing.
    """
    project = project_manager.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    eval_set = next((es for es in project.eval_sets if es.id == request.eval_set_id), None)
    if not eval_set:
        raise HTTPException(status_code=404, detail="Eval set not found")
    
    # Load the session
    session = await runtime_manager.load_session_from_service(project, request.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Extract invocations from session events
    # Group events by invocation (user message to next user message)
    invocations: List[EvalInvocation] = []
    current_user_message = None
    current_tool_calls: List[ExpectedToolCall] = []
    current_response = None
    
    for event in session.events:
        if event.event_type == "user_message" or (
            event.event_type == "model_call" and 
            event.data.get("contents") and 
            any(c.get("role") == "user" for c in event.data.get("contents", []))
        ):
            # If we have a previous user message, save the invocation
            if current_user_message:
                invocations.append(EvalInvocation(
                    id=str(uuid.uuid4())[:8],
                    user_message=current_user_message,
                    expected_response=current_response or request.expected_response,
                    expected_tool_calls=current_tool_calls,
                    tool_trajectory_match_type=ToolTrajectoryMatchType.IN_ORDER,
                    rubrics=[],
                ))
            
            # Extract user message from event
            if event.event_type == "user_message":
                current_user_message = event.data.get("message", "")
            else:
                # Extract from model_call contents
                contents = event.data.get("contents", [])
                for content in contents:
                    if content.get("role") == "user":
                        parts = content.get("parts", [])
                        for part in parts:
                            if isinstance(part, dict) and part.get("text"):
                                current_user_message = part.get("text", "")
                                break
                            elif isinstance(part, str):
                                current_user_message = part
                                break
            
            current_tool_calls = []
            current_response = None
            
        elif event.event_type == "tool_call":
            # Record tool call
            current_tool_calls.append(ExpectedToolCall(
                name=event.data.get("tool_name", ""),
                args=event.data.get("args", {}),
                args_match_mode="subset",  # Default to subset for flexibility
            ))
            
        elif event.event_type == "model_response":
            # Extract response text
            parts = event.data.get("response_content", {}).get("parts", [])
            if not parts:
                parts = event.data.get("parts", [])
            for part in parts:
                if isinstance(part, dict) and part.get("type") == "text" and part.get("text"):
                    current_response = part.get("text", "")
                    break
    
    # Don't forget the last invocation
    if current_user_message:
        invocations.append(EvalInvocation(
            id=str(uuid.uuid4())[:8],
            user_message=current_user_message,
            expected_response=current_response or request.expected_response,
            expected_tool_calls=current_tool_calls,
            tool_trajectory_match_type=ToolTrajectoryMatchType.IN_ORDER,
            rubrics=[],
        ))
    
    if not invocations:
        raise HTTPException(status_code=400, detail="No user messages found in session")
    
    # Calculate token counts from session
    total_tokens = 0
    for event in session.events:
        if event.event_type == "model_response":
            token_counts = event.data.get("token_counts", {})
            total_tokens += token_counts.get("input_tokens", 0) + token_counts.get("output_tokens", 0)
    
    # Create the eval case
    import time
    eval_case = EvalCase(
        id=str(uuid.uuid4())[:8],
        name=request.case_name,
        description=f"Created from session {request.session_id}",
        invocations=invocations,
        initial_state={},
        expected_final_state=session.final_state if session.final_state else None,
        rubrics=[],
        tags=["from_session"],
    )
    
    # Add to eval set
    eval_set.eval_cases.append(eval_case)
    eval_set.updated_at = time.time()
    project_manager.save_project(project)
    
    return {
        "eval_case": eval_case.model_dump(mode="json"),
        "session_token_count": total_tokens,
    }


# ============================================================================
# Eval Set Export/Import
# ============================================================================

@app.get("/api/projects/{project_id}/eval-sets/{eval_set_id}/export")
async def export_eval_set(project_id: str, eval_set_id: str):
    """Export an eval set as JSON (compatible with `adk eval` format)."""
    project = project_manager.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    eval_set = next((es for es in project.eval_sets if es.id == eval_set_id), None)
    if not eval_set:
        raise HTTPException(status_code=404, detail="Eval set not found")
    
    # Convert to ADK-compatible eval format
    # ADK expects a list of eval cases with specific structure
    adk_format = {
        "name": eval_set.name,
        "description": eval_set.description,
        "eval_cases": [],
        "eval_config": eval_set.eval_config.model_dump(mode="json"),
    }
    
    for case in eval_set.eval_cases:
        adk_case = {
            "eval_id": case.id,
            "name": case.name,
            "description": case.description,
            "conversation": [],
            "session_input": {
                "state": case.initial_state,
            } if case.initial_state else None,
            "final_session_state": case.expected_final_state,
            "rubrics": [r.model_dump(mode="json") for r in case.rubrics],
        }
        
        for inv in case.invocations:
            adk_inv = {
                "user_content": {
                    "role": "user",
                    "parts": [{"text": inv.user_message}],
                },
                "final_response": {
                    "role": "model",
                    "parts": [{"text": inv.expected_response or ""}],
                } if inv.expected_response else None,
                "intermediate_data": {
                    "tool_uses": [
                        {"name": tc.name, "args": tc.args or {}}
                        for tc in inv.expected_tool_calls
                    ],
                },
                "rubrics": [r.model_dump(mode="json") for r in inv.rubrics],
            }
            adk_case["conversation"].append(adk_inv)
        
        adk_format["eval_cases"].append(adk_case)
    
    return adk_format


@app.post("/api/projects/{project_id}/eval-sets/import")
async def import_eval_set(project_id: str, data: dict):
    """Import an eval set from JSON.
    
    Accepts both the playground format and ADK eval format.
    """
    project = project_manager.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    import time
    
    # Try to detect format and convert
    if "eval_cases" in data and isinstance(data.get("eval_cases"), list):
        # Could be either format, check first case structure
        first_case = data["eval_cases"][0] if data["eval_cases"] else {}
        
        if "invocations" in first_case:
            # Playground format - parse directly
            try:
                eval_set = EvalSet(
                    id=str(uuid.uuid4())[:8],
                    name=data.get("name", "Imported Eval Set"),
                    description=data.get("description", ""),
                    eval_cases=[EvalCase.model_validate(c) for c in data["eval_cases"]],
                    eval_config=EvalConfig.model_validate(data.get("eval_config", {})) if data.get("eval_config") else EvalConfig(),
                    created_at=time.time(),
                    updated_at=time.time(),
                )
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Invalid playground format: {e}")
        
        elif "conversation" in first_case:
            # ADK format - convert
            eval_cases = []
            for adk_case in data["eval_cases"]:
                invocations = []
                for adk_inv in adk_case.get("conversation", []):
                    user_content = adk_inv.get("user_content", {})
                    user_parts = user_content.get("parts", [])
                    user_message = ""
                    for part in user_parts:
                        if isinstance(part, dict) and part.get("text"):
                            user_message = part["text"]
                            break
                    
                    final_response = adk_inv.get("final_response", {})
                    response_parts = final_response.get("parts", []) if final_response else []
                    expected_response = ""
                    for part in response_parts:
                        if isinstance(part, dict) and part.get("text"):
                            expected_response = part["text"]
                            break
                    
                    intermediate = adk_inv.get("intermediate_data", {})
                    tool_uses = intermediate.get("tool_uses", [])
                    expected_tool_calls = [
                        ExpectedToolCall(
                            name=tu.get("name", ""),
                            args=tu.get("args"),
                            args_match_mode="subset",
                        )
                        for tu in tool_uses
                    ]
                    
                    invocations.append(EvalInvocation(
                        id=str(uuid.uuid4())[:8],
                        user_message=user_message,
                        expected_response=expected_response or None,
                        expected_tool_calls=expected_tool_calls,
                        tool_trajectory_match_type=ToolTrajectoryMatchType.IN_ORDER,
                        rubrics=[Rubric.model_validate(r) for r in adk_inv.get("rubrics", [])],
                    ))
                
                session_input = adk_case.get("session_input", {})
                eval_cases.append(EvalCase(
                    id=adk_case.get("eval_id", str(uuid.uuid4())[:8]),
                    name=adk_case.get("name", "Imported Case"),
                    description=adk_case.get("description", ""),
                    invocations=invocations,
                    initial_state=session_input.get("state", {}) if session_input else {},
                    expected_final_state=adk_case.get("final_session_state"),
                    rubrics=[Rubric.model_validate(r) for r in adk_case.get("rubrics", [])],
                    tags=["imported"],
                ))
            
            eval_set = EvalSet(
                id=str(uuid.uuid4())[:8],
                name=data.get("name", "Imported Eval Set"),
                description=data.get("description", ""),
                eval_cases=eval_cases,
                eval_config=EvalConfig.model_validate(data.get("eval_config", {})) if data.get("eval_config") else EvalConfig(),
                created_at=time.time(),
                updated_at=time.time(),
            )
        else:
            raise HTTPException(status_code=400, detail="Unknown eval format")
    else:
        raise HTTPException(status_code=400, detail="Invalid eval set format: missing eval_cases")
    
    project.eval_sets.append(eval_set)
    project_manager.save_project(project)
    
    return {"eval_set": eval_set.model_dump(mode="json")}


# Static Files (for production)
# ============================================================================

# Mount frontend build in production mode
# This serves the built frontend assets and handles SPA routing
if PRODUCTION_MODE:
    frontend_build = None
    
    # First, try using importlib.resources (modern approach for package data)
    try:
        from importlib.resources import files
        try:
            # Try to access frontend/dist from the package
            frontend_dist = files("adk_playground.frontend") / "dist"
            # Convert Traversable to Path
            import tempfile
            import shutil
            with tempfile.TemporaryDirectory() as tmpdir:
                # Copy files from package to temp directory
                dist_path = Path(tmpdir) / "dist"
                dist_path.mkdir()
                for item in frontend_dist.iterdir():
                    if item.is_file():
                        shutil.copy(item, dist_path / item.name)
                    elif item.is_dir():
                        shutil.copytree(item, dist_path / item.name, dirs_exist_ok=True)
                if (dist_path / "index.html").exists():
                    # Use the temp directory (or better, find the actual package location)
                    # Actually, let's try to get the real path
                    try:
                        import adk_playground
                        pkg_root = Path(adk_playground.__file__).parent
                        real_dist = pkg_root / "frontend" / "dist"
                        if real_dist.exists() and (real_dist / "index.html").exists():
                            frontend_build = real_dist
                            print(f"✅ Found frontend/dist at package: {frontend_build}", file=sys.stderr)
                    except:
                        pass
        except (ModuleNotFoundError, TypeError, AttributeError, Exception) as e:
            print(f"importlib.resources.files failed: {e}", file=sys.stderr)
    except ImportError:
        # Fallback for older Python versions
        try:
            from importlib import resources
            with resources.path("adk_playground.frontend", "dist") as dist_path:
                if Path(dist_path).exists() and (Path(dist_path) / "index.html").exists():
                    frontend_build = Path(dist_path)
                    print(f"✅ Found frontend/dist via importlib.resources.path: {frontend_build}", file=sys.stderr)
        except (ImportError, ModuleNotFoundError, TypeError, FileNotFoundError, ValueError) as e:
            print(f"importlib.resources.path failed: {e}", file=sys.stderr)
    
    # Fallback: try relative to package root
    if not frontend_build:
        try:
            import adk_playground
            _package_root = Path(adk_playground.__file__).parent
            # Try frontend/dist first
            _package_frontend = _package_root / "frontend" / "dist"
            if _package_frontend.exists() and (_package_frontend / "index.html").exists():
                frontend_build = _package_frontend
                print(f"✅ Found frontend/dist at package root: {frontend_build}", file=sys.stderr)
            # If not, try frontend directly (files might be in frontend/ not frontend/dist/)
            elif not frontend_build:
                _package_frontend_direct = _package_root / "frontend"
                if _package_frontend_direct.exists() and (_package_frontend_direct / "index.html").exists():
                    frontend_build = _package_frontend_direct
                    print(f"✅ Found frontend at package root: {frontend_build}", file=sys.stderr)
        except (ImportError, AttributeError) as e:
            print(f"Package root check failed: {e}", file=sys.stderr)
            pass
    
    # Last resort: try source location (for development)
    if not frontend_build:
        _backend_dir = Path(__file__).parent
        _source_frontend = _backend_dir.parent / "frontend" / "dist"
        if _source_frontend.exists() and (_source_frontend / "index.html").exists():
            frontend_build = _source_frontend
            print(f"✅ Found frontend/dist at source location: {frontend_build}", file=sys.stderr)
    
    if frontend_build and frontend_build.exists():
        # Serve static assets (JS, CSS, images, etc.) from /assets
        assets_dir = frontend_build / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")
        
        # Serve index.html for all non-API/WebSocket routes (SPA routing)
        # This must be last to catch all other routes
        @app.get("/{full_path:path}")
        async def serve_spa(full_path: str):
            """Serve index.html for SPA routing, but exclude API and WebSocket routes."""
            # Don't serve index.html for API or WebSocket routes
            if full_path.startswith(("api/", "ws/", "assets/")):
                raise HTTPException(status_code=404, detail="Not found")
            
            index_file = frontend_build / "index.html"
            if index_file.exists():
                from fastapi.responses import FileResponse
                return FileResponse(str(index_file))
            raise HTTPException(status_code=404, detail="Frontend not built. Run 'npm run build' in frontend/")
    else:
        import sys
        print("WARNING: Production mode enabled but frontend/dist not found.", file=sys.stderr)
        print("Run 'npm run build' in the frontend/ directory to build the frontend.", file=sys.stderr)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)

