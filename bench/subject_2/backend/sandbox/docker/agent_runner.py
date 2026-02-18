"""Agent runner that executes inside the Docker sandbox.

This script:
1. Receives the project configuration via environment or mounted file
2. Loads and executes the ADK agent
3. Spawns stdio MCP servers as subprocesses
4. Streams events back to the host via HTTP/WebSocket

All network traffic goes through the HTTP_PROXY (gateway).
"""

import asyncio
import json
import logging
import os
import sys
import time
import traceback
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiohttp
from aiohttp import web

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def parse_adk_error(error_msg: str) -> dict:
    """Parse common ADK errors and provide helpful hints.
    
    Returns a dict with:
      - message: The user-friendly error message
      - hint: Optional suggestion to fix the issue
      - error_type: Categorized error type
    """
    import re
    
    # Context variable not found
    match = re.search(r"Context variable not found: `(\w+)`", error_msg)
    if match:
        var_name = match.group(1)
        return {
            "message": f"Missing state variable: {var_name}",
            "hint": f"Add '{var_name}' as a State Key in your App configuration, or use '{{{var_name}?}}' (with ?) in your instruction to make it optional.",
            "error_type": "missing_state_variable",
            "variable": var_name,
        }
    
    # Artifact not found
    match = re.search(r"Artifact (\w+) not found", error_msg)
    if match:
        artifact_name = match.group(1)
        return {
            "message": f"Missing artifact: {artifact_name}",
            "hint": f"The artifact '{artifact_name}' referenced in the instruction doesn't exist. Create it or use '{{artifact:{artifact_name}?}}' to make it optional.",
            "error_type": "missing_artifact",
            "artifact": artifact_name,
        }
    
    # Tool not found
    match = re.search(r"Tool '(\w+)' not found|Unknown tool: (\w+)", error_msg)
    if match:
        tool_name = match.group(1) or match.group(2)
        return {
            "message": f"Unknown tool: {tool_name}",
            "hint": f"The tool '{tool_name}' is not available. Check your tool configuration or remove references to this tool.",
            "error_type": "missing_tool",
            "tool": tool_name,
        }
    
    # Agent transfer failed
    match = re.search(r"Agent '(\w+)' not found|Cannot transfer to agent: (\w+)", error_msg)
    if match:
        agent_name = match.group(1) or match.group(2)
        return {
            "message": f"Cannot find agent: {agent_name}",
            "hint": f"The agent '{agent_name}' doesn't exist. Check the agent name spelling or add it as a sub-agent.",
            "error_type": "missing_agent",
            "agent": agent_name,
        }
    
    # LLM/API errors
    if "rate limit" in error_msg.lower():
        return {
            "message": "Rate limit exceeded",
            "hint": "The LLM API rate limit was exceeded. Wait a moment and try again, or consider using a different model.",
            "error_type": "rate_limit",
        }
    
    if "api key" in error_msg.lower() or "authentication" in error_msg.lower():
        return {
            "message": "API authentication error",
            "hint": "Check your API key configuration. Make sure the appropriate API key environment variable is set.",
            "error_type": "auth_error",
        }
    
    if "timeout" in error_msg.lower():
        return {
            "message": "Request timeout",
            "hint": "The request took too long. Try increasing the timeout in your model configuration, or use a faster model.",
            "error_type": "timeout",
        }
    
    # Default: return the original message
    return {
        "message": error_msg,
        "hint": None,
        "error_type": "unknown",
    }


def extract_exception_details(exc: Exception) -> dict:
    """Extract meaningful error details from an exception.
    
    Handles ExceptionGroup (Python 3.11+) specially to extract sub-exceptions.
    
    Returns a dict with:
      - message: User-friendly error message
      - hint: Optional suggestion to fix
      - error_type: Categorized error type
      - raw: Original exception string
      - stack_trace: Full stack trace
      - sub_errors: List of sub-error dicts (for ExceptionGroup)
    """
    # Capture the full stack trace
    stack_trace = ''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    
    # Handle ExceptionGroup (Python 3.11+ with asyncio.TaskGroup)
    if sys.version_info >= (3, 11):
        if isinstance(exc, ExceptionGroup):
            sub_errors = []
            for sub_exc in exc.exceptions:
                parsed = parse_adk_error(str(sub_exc))
                parsed["exception_type"] = type(sub_exc).__name__
                # Capture stack trace for each sub-exception
                parsed["stack_trace"] = ''.join(
                    traceback.format_exception(type(sub_exc), sub_exc, sub_exc.__traceback__)
                )
                sub_errors.append(parsed)
            
            # Combine messages
            messages = [e["message"] for e in sub_errors]
            hints = [e["hint"] for e in sub_errors if e.get("hint")]
            
            return {
                "message": f"Errors in parallel execution: {'; '.join(messages)}",
                "hint": hints[0] if hints else None,  # Show first hint
                "error_type": "parallel_execution_error",
                "raw": str(exc),
                "stack_trace": stack_trace,
                "sub_errors": sub_errors,
                "is_exception_group": True,
            }
    
    # Single exception
    parsed = parse_adk_error(str(exc))
    parsed["exception_type"] = type(exc).__name__
    parsed["raw"] = str(exc)
    parsed["stack_trace"] = stack_trace
    parsed["is_exception_group"] = False
    return parsed


# MCP imports - optional, may not be available
try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False
    logger.warning("MCP SDK not available - MCP tool execution disabled")


# Configuration
HOST_URL = os.environ.get("HOST_URL", "http://host.docker.internal:8080")
WORKSPACE_PATH = os.environ.get("WORKSPACE_PATH", "/workspace")
PROJECT_CONFIG_PATH = os.environ.get("PROJECT_CONFIG_PATH", "/config/project.json")
API_PORT = int(os.environ.get("API_PORT", "5000"))
MCP_SERVERS_CONFIG = os.environ.get("MCP_SERVERS_CONFIG", "{}")


def create_session_service_from_uri(uri: str):
    """Create a session service from a URI."""
    from google.adk.sessions.in_memory_session_service import InMemorySessionService
    
    if uri.startswith("memory://"):
        return InMemorySessionService()
    elif uri.startswith("sqlite://"):
        try:
            from google.adk.sessions.sqlite_session_service import SqliteSessionService
            db_path = uri[9:]
            # Ensure parent directory exists
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            logger.info(f"Using SQLite session service: {db_path}")
            return SqliteSessionService(db_path=db_path)
        except ImportError as e:
            logger.warning(f"SqliteSessionService not available: {e}")
            return InMemorySessionService()
    elif uri.startswith("file://"):
        try:
            # Try to import from /app (mounted) or workspace
            if "/app" not in sys.path:
                sys.path.insert(0, "/app")
            if WORKSPACE_PATH not in sys.path:
                sys.path.insert(0, WORKSPACE_PATH)
            from file_session_service import FileSessionService
            base_dir = uri[7:]
            Path(base_dir).mkdir(parents=True, exist_ok=True)
            logger.info(f"Using File session service: {base_dir}")
            return FileSessionService(base_dir=base_dir)
        except ImportError as e:
            logger.warning(f"FileSessionService not available ({e}), using in-memory")
            return InMemorySessionService()
    else:
        return InMemorySessionService()


def create_memory_service_from_uri(uri: str):
    """Create a memory service from a URI."""
    from google.adk.memory.in_memory_memory_service import InMemoryMemoryService
    
    if uri.startswith("memory://"):
        return InMemoryMemoryService()
    elif uri.startswith("file://"):
        try:
            # Try to import from /app (mounted) or workspace
            if "/app" not in sys.path:
                sys.path.insert(0, "/app")
            if WORKSPACE_PATH not in sys.path:
                sys.path.insert(0, WORKSPACE_PATH)
            from file_memory_service import FileMemoryService
            base_dir = uri[7:]
            Path(base_dir).mkdir(parents=True, exist_ok=True)
            logger.info(f"Using File memory service: {base_dir}")
            return FileMemoryService(base_dir=base_dir)
        except ImportError as e:
            logger.warning(f"FileMemoryService not available ({e}), using in-memory")
            return InMemoryMemoryService()
    else:
        return InMemoryMemoryService()


def create_artifact_service_from_uri(uri: str):
    """Create an artifact service from a URI."""
    from google.adk.artifacts.in_memory_artifact_service import InMemoryArtifactService
    
    if uri.startswith("memory://"):
        return InMemoryArtifactService()
    elif uri.startswith("file://"):
        try:
            from google.adk.artifacts.file_artifact_service import FileArtifactService
            root_dir = uri[7:]
            Path(root_dir).mkdir(parents=True, exist_ok=True)
            logger.info(f"Using File artifact service: {root_dir}")
            return FileArtifactService(root_dir=root_dir)
        except ImportError:
            logger.warning("FileArtifactService not available, using in-memory")
            return InMemoryArtifactService()
    else:
        return InMemoryArtifactService()


class MCPSessionManager:
    """Manages MCP server connections for tool execution.
    
    This allows external callers to execute MCP tools inside the container,
    useful for Tool Watches and debugging.
    """
    
    # Browser-related MCP servers that need Docker-friendly Chrome flags
    BROWSER_MCP_SERVERS = {
        "chrome_devtools", "chrome-devtools", "puppeteer", "playwright", 
        "browser", "browserbase", "web-browser"
    }
    
    # Docker-friendly Chrome args for chrome-devtools-mcp
    # These are passed as --chromeArg=<flag> when chrome-devtools-mcp is detected
    DOCKER_CHROME_ARGS_FOR_DEVTOOLS_MCP = [
        "--chromeArg=--no-sandbox",           # Chrome sandbox doesn't work as root in Docker
        "--chromeArg=--disable-dev-shm-usage",  # /dev/shm is too small in Docker
        "--chromeArg=--disable-gpu",          # No GPU in container
        "--chromeArg=--ignore-certificate-errors",  # Ignore SSL errors (proxy intercepts HTTPS)
        "--headless",                         # Run headless (no display needed)
        "--acceptInsecureCerts",              # chrome-devtools-mcp flag to accept self-signed certs
    ]
    
    # Generic Docker-friendly Chrome flags (for other browser automation)
    DOCKER_CHROME_FLAGS = [
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--headless=new",
        "--ignore-certificate-errors",  # Ignore SSL errors (proxy intercepts HTTPS)
    ]
    
    def __init__(self):
        self._sessions: Dict[str, Any] = {}  # server_name -> (session, context_manager)
        self._server_configs: Dict[str, dict] = {}
        self._load_configs()
    
    def _load_configs(self):
        """Load MCP server configurations from environment."""
        try:
            config = json.loads(MCP_SERVERS_CONFIG)
            if isinstance(config, dict):
                # Handle format from docker_manager: {"stdio_mcp_servers": [{"name": ..., "command": ...}]}
                if "stdio_mcp_servers" in config:
                    for server in config["stdio_mcp_servers"]:
                        name = server.get("name")
                        if name:
                            self._server_configs[name] = {
                                "command": server.get("command", ""),
                                "args": server.get("args", []),
                                "env": server.get("env", {}),
                            }
                else:
                    # Direct format: {"server_name": {"command": ...}}
                    self._server_configs = config
                logger.info(f"Loaded {len(self._server_configs)} MCP server configs: {list(self._server_configs.keys())}")
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse MCP_SERVERS_CONFIG: {e}")
    
    def _is_browser_mcp_server(self, server_name: str, args: List[str]) -> bool:
        """Check if this MCP server is browser-related and needs Docker Chrome flags."""
        # Check server name
        name_lower = server_name.lower()
        for browser_name in self.BROWSER_MCP_SERVERS:
            if browser_name in name_lower:
                return True
        
        # Check args for browser-related packages
        args_str = " ".join(args).lower()
        browser_packages = ["chrome-devtools-mcp", "puppeteer", "playwright", "browserbase"]
        for pkg in browser_packages:
            if pkg in args_str:
                return True
        
        return False
    
    def _is_chrome_devtools_mcp(self, args: List[str]) -> bool:
        """Check if this is specifically chrome-devtools-mcp."""
        args_str = " ".join(args).lower()
        return "chrome-devtools-mcp" in args_str
    
    def list_servers(self) -> List[dict]:
        """List available MCP servers."""
        servers = []
        for name, config in self._server_configs.items():
            servers.append({
                "name": name,
                "command": config.get("command", ""),
                "args": config.get("args", []),
                "connected": name in self._sessions,
            })
        return servers
    
    async def connect(self, server_name: str) -> Optional[Any]:
        """Connect to an MCP server if not already connected."""
        if not MCP_AVAILABLE:
            raise RuntimeError("MCP SDK not available")
        
        if server_name in self._sessions:
            return self._sessions[server_name]["session"]
        
        if server_name not in self._server_configs:
            raise ValueError(f"Unknown MCP server: {server_name}")
        
        config = self._server_configs[server_name]
        original_args = config.get("args", [])
        
        # Build environment with proxy variables
        env = {}
        for key in ["HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "UV_HTTP_PROXY", 
                    "UV_HTTPS_PROXY", "NPM_CONFIG_PROXY", "NPM_CONFIG_HTTPS_PROXY",
                    "http_proxy", "https_proxy", "no_proxy"]:
            if key in os.environ:
                env[key] = os.environ[key]
        
        # Pass through Chrome/browser-related environment variables
        for key in ["CHROME_BIN", "CHROMIUM_BIN", "CHROMEDRIVER_BIN", "GOOGLE_CHROME_BIN",
                    "PUPPETEER_SKIP_DOWNLOAD", "PUPPETEER_EXECUTABLE_PATH",
                    "PUPPETEER_ARGS", "CHROME_ARGS", "DISPLAY"]:
            if key in os.environ:
                env[key] = os.environ[key]
        
        # Add server-specific env vars
        if config.get("env"):
            env.update(config["env"])
        
        # Check if this is a browser-related MCP server
        is_browser = self._is_browser_mcp_server(server_name, original_args)
        is_devtools = self._is_chrome_devtools_mcp(original_args)
        args = list(original_args)
        
        if is_devtools:
            logger.info(f"Detected chrome-devtools-mcp server '{server_name}', adding Docker Chrome args")
            # Inject Docker-friendly Chrome args in chrome-devtools-mcp format
            existing_args_str = " ".join(args)
            for flag in self.DOCKER_CHROME_ARGS_FOR_DEVTOOLS_MCP:
                # Check if this flag or its equivalent is already present
                flag_base = flag.split("=")[-1] if "=" in flag else flag
                if flag_base not in existing_args_str and flag not in existing_args_str:
                    args.append(flag)
            logger.info(f"chrome-devtools-mcp args: {args}")
        elif is_browser:
            logger.info(f"Detected browser MCP server '{server_name}', adding Docker Chrome flags")
            # Inject Docker-friendly Chrome flags if not already present
            existing_args = set(args)
            for flag in self.DOCKER_CHROME_FLAGS:
                if flag not in existing_args:
                    args.append(flag)
            logger.info(f"Browser MCP server args: {args}")
        
        server_params = StdioServerParameters(
            command=config.get("command", ""),
            args=args,
            env=env if env else None,
        )
        
        logger.info(f"Starting MCP server '{server_name}': {config.get('command')} {' '.join(args)}")
        
        try:
            # Create the stdio client context manager
            client_cm = stdio_client(server_params)
            read_stream, write_stream = await client_cm.__aenter__()
            
            # Create and initialize the session
            session = ClientSession(read_stream, write_stream)
            await session.__aenter__()
            await session.initialize()
            
            self._sessions[server_name] = {
                "session": session,
                "client_cm": client_cm,
            }
            
            logger.info(f"Connected to MCP server: {server_name}")
            return session
            
        except Exception as e:
            logger.error(f"Failed to connect to MCP server {server_name}: {e}", exc_info=True)
            raise
    
    async def disconnect(self, server_name: str):
        """Disconnect from an MCP server."""
        if server_name not in self._sessions:
            return
        
        try:
            session_data = self._sessions.pop(server_name)
            await session_data["session"].__aexit__(None, None, None)
            await session_data["client_cm"].__aexit__(None, None, None)
            logger.info(f"Disconnected from MCP server: {server_name}")
        except Exception as e:
            logger.warning(f"Error disconnecting from {server_name}: {e}")
    
    async def disconnect_all(self):
        """Disconnect from all MCP servers."""
        for server_name in list(self._sessions.keys()):
            await self.disconnect(server_name)
    
    async def list_tools(self, server_name: str) -> List[dict]:
        """List tools available from an MCP server."""
        session = await self.connect(server_name)
        result = await session.list_tools()
        
        tools = []
        for tool in result.tools:
            tools.append({
                "name": tool.name,
                "description": tool.description or "",
                "input_schema": tool.inputSchema if hasattr(tool, "inputSchema") else {},
            })
        return tools
    
    async def call_tool(self, server_name: str, tool_name: str, args: dict) -> Any:
        """Call a tool on an MCP server."""
        logger.info(f"Calling MCP tool '{tool_name}' on server '{server_name}' with args: {args}")
        
        try:
            session = await self.connect(server_name)
            result = await session.call_tool(tool_name, args)
        except Exception as e:
            logger.error(f"MCP tool call failed: {tool_name} on {server_name}: {e}", exc_info=True)
            raise
        
        # Convert result to JSON-serializable format
        is_error = getattr(result, "isError", False)
        if hasattr(result, "content"):
            content = []
            for item in result.content:
                if hasattr(item, "text"):
                    content.append({"type": "text", "text": item.text})
                    # Log errors prominently
                    if is_error:
                        logger.error(f"MCP tool '{tool_name}' error: {item.text}")
                elif hasattr(item, "data"):
                    content.append({"type": "data", "data": str(item.data)})
                else:
                    content.append({"type": "unknown", "value": str(item)})
            return {"content": content, "isError": is_error}
        return {"result": str(result)}


# Global MCP session manager
mcp_manager = MCPSessionManager()


class TrackingPlugin:
    """Plugin that tracks all events during agent execution.
    
    This mirrors the TrackingPlugin from runtime.py to capture
    model_call, model_response, tool_call, tool_result, etc.
    """
    
    def __init__(self, emit_callback):
        self.emit_callback = emit_callback
        self.token_counts = {"input": 0, "output": 0}
    
    async def _emit(self, event: Dict[str, Any]):
        """Emit an event."""
        try:
            await self.emit_callback(event)
        except Exception as e:
            logger.error(f"Failed to emit event {event.get('event_type')}: {e}")
    
    async def _emit_error(self, source: str, error: Exception, context: str = ""):
        """Emit an error event that will show in the message list."""
        import traceback
        await self._emit({
            "event_type": "callback_error",
            "timestamp": time.time(),
            "agent_name": "system",
            "data": {
                "source": source,
                "error": str(error),
                "error_type": type(error).__name__,
                "context": context,
                "traceback": traceback.format_exc(),
            },
        })
    
    def _get_branch(self, context) -> str | None:
        """Extract branch from callback_context or tool_context for parallel execution tracking."""
        if hasattr(context, "_invocation_context"):
            return getattr(context._invocation_context, "branch", None)
        return None
    
    async def before_agent_callback(self, *, agent, callback_context, **kwargs):
        try:
            await self._emit({
                "event_type": "agent_start",
                "timestamp": time.time(),
                "agent_name": agent.name,
                "branch": self._get_branch(callback_context),
                "data": {"instruction": getattr(agent, "instruction", "") or ""},
            })
        except Exception as e:
            logger.error(f"Error in before_agent_callback for {agent.name}: {e}")
            await self._emit_error("before_agent_callback", e, f"agent={agent.name}")
        return None
    
    async def after_agent_callback(self, *, agent, callback_context, **kwargs):
        try:
            await self._emit({
                "event_type": "agent_end",
                "timestamp": time.time(),
                "agent_name": agent.name,
                "branch": self._get_branch(callback_context),
                "data": {},
            })
        except Exception as e:
            logger.error(f"Error in after_agent_callback for {agent.name}: {e}")
            await self._emit_error("after_agent_callback", e, f"agent={agent.name}")
        return None
    
    async def on_event_callback(self, *, invocation_context, event, **kwargs):
        if hasattr(event, "actions") and event.actions and event.actions.state_delta:
            state_delta = dict(event.actions.state_delta)
            author = getattr(event, "author", None) or "system"
            branch = getattr(invocation_context, "branch", None)
            
            # Check for callback instrumentation events (keys like _cb_start_xxx or _cb_end_xxx)
            callback_keys = [k for k in state_delta.keys() if k.startswith("_cb_start_") or k.startswith("_cb_end_")]
            for key in callback_keys:
                cb_event = state_delta.pop(key)
                if isinstance(cb_event, dict):
                    event_type = "callback_start" if cb_event.get("type") == "callback_start" else "callback_end"
                    await self._emit({
                        "event_type": event_type,
                        "timestamp": cb_event.get("ts", time.time()),
                        "agent_name": author,
                        "branch": branch,
                        "data": {
                            "callback_name": cb_event.get("name", "unknown"),
                            "callback_type": cb_event.get("callback_type", ""),
                        },
                    })
            
            # Emit state change for remaining state delta (if any)
            if state_delta:
                await self._emit({
                    "event_type": "state_change",
                    "timestamp": time.time(),
                    "agent_name": author,
                    "branch": branch,
                    "data": {"state_delta": state_delta},
                })
        return None
    
    async def before_model_callback(self, *, callback_context, llm_request, **kwargs):
        try:
            contents = self._serialize_contents(getattr(llm_request, "contents", None))
            
            system_instruction = None
            if hasattr(llm_request, "config") and llm_request.config:
                si = getattr(llm_request.config, "system_instruction", None)
                if si:
                    if isinstance(si, str):
                        system_instruction = si
                    elif hasattr(si, "parts"):
                        system_instruction = "".join(
                            getattr(p, "text", "") for p in si.parts if hasattr(p, "text")
                        )
            
            tool_names = list(getattr(llm_request, "tools_dict", {}).keys())
            
            await self._emit({
                "event_type": "model_call",
                "timestamp": time.time(),
                "agent_name": getattr(callback_context, "agent_name", None) or "system",
                "branch": self._get_branch(callback_context),
                "data": {
                    "contents": contents,
                    "system_instruction": system_instruction,
                    "tool_names": tool_names,
                    "tool_count": len(tool_names),
                },
            })
        except Exception as e:
            logger.error(f"Error in before_model_callback: {e}")
            await self._emit_error("before_model_callback", e, "")
        return None
    
    async def after_model_callback(self, *, callback_context, llm_response, **kwargs):
        try:
            response_parts = []
            if hasattr(llm_response, "content") and llm_response.content:
                if hasattr(llm_response.content, "parts") and llm_response.content.parts:
                    for part in llm_response.content.parts:
                        if hasattr(part, "text") and part.text:
                            part_data = {"type": "text", "text": part.text}
                            if hasattr(part, "thought") and part.thought:
                                part_data["thought"] = True
                            response_parts.append(part_data)
                        elif hasattr(part, "function_call") and part.function_call:
                            fc = part.function_call
                            response_parts.append({
                                "type": "function_call",
                                "name": getattr(fc, "name", "unknown"),
                                "args": dict(getattr(fc, "args", {})) if hasattr(fc, "args") else {},
                            })
            
            if hasattr(llm_response, "usage_metadata") and llm_response.usage_metadata:
                usage = llm_response.usage_metadata
                self.token_counts["input"] += getattr(usage, "prompt_token_count", 0) or 0
                self.token_counts["output"] += getattr(usage, "candidates_token_count", 0) or 0
            
            await self._emit({
                "event_type": "model_response",
                "timestamp": time.time(),
                "agent_name": getattr(callback_context, "agent_name", None) or "system",
                "branch": self._get_branch(callback_context),
                "data": {"parts": response_parts, "token_counts": dict(self.token_counts)},
            })
        except Exception as e:
            logger.error(f"Error in after_model_callback: {e}")
            await self._emit_error("after_model_callback", e, "")
        return None
    
    async def before_tool_callback(self, *, tool, tool_args, tool_context, **kwargs):
        try:
            # Serialize args safely
            safe_args = {}
            if tool_args:
                for k, v in tool_args.items():
                    try:
                        json.dumps(v)  # Test if serializable
                        safe_args[k] = v
                    except (TypeError, ValueError):
                        safe_args[k] = str(v)
            
            await self._emit({
                "event_type": "tool_call",
                "timestamp": time.time(),
                "agent_name": getattr(tool_context, "agent_name", None) or "system",
                "branch": self._get_branch(tool_context),
                "data": {"tool_name": tool.name, "args": safe_args},
            })
        except Exception as e:
            logger.error(f"Error in before_tool_callback for {tool.name}: {e}")
            await self._emit_error("before_tool_callback", e, f"tool={tool.name}")
        return None
    
    async def after_tool_callback(self, *, tool, tool_args, tool_context, result, **kwargs):
        try:
            branch = self._get_branch(tool_context)
            if hasattr(tool_context, "_event_actions") and tool_context._event_actions.state_delta:
                await self._emit({
                    "event_type": "state_change",
                    "timestamp": time.time(),
                    "agent_name": getattr(tool_context, "agent_name", None) or "system",
                    "branch": branch,
                    "data": {"state_delta": dict(tool_context._event_actions.state_delta)},
                })
            
            # Serialize result safely
            safe_result = result
            try:
                json.dumps(result)
            except (TypeError, ValueError):
                safe_result = str(result)
            
            await self._emit({
                "event_type": "tool_result",
                "timestamp": time.time(),
                "agent_name": getattr(tool_context, "agent_name", None) or "system",
                "branch": branch,
                "data": {"tool_name": tool.name, "result": safe_result},
            })
        except Exception as e:
            logger.error(f"Error in after_tool_callback for {tool.name}: {e}")
            await self._emit_error("after_tool_callback", e, f"tool={tool.name}")
        return None
    
    def _serialize_contents(self, contents) -> list:
        if not contents:
            return []
        
        result = []
        for content in contents:
            content_data = {"role": getattr(content, "role", "unknown"), "parts": []}
            
            if hasattr(content, "parts") and content.parts:
                for part in content.parts:
                    part_data = {}
                    if hasattr(part, "text") and part.text:
                        part_data = {"type": "text", "text": part.text}
                    elif hasattr(part, "function_call") and part.function_call:
                        fc = part.function_call
                        part_data = {
                            "type": "function_call",
                            "name": getattr(fc, "name", "unknown"),
                            "args": dict(getattr(fc, "args", {})) if hasattr(fc, "args") else {},
                        }
                    elif hasattr(part, "function_response") and part.function_response:
                        fr = part.function_response
                        part_data = {
                            "type": "function_response",
                            "name": getattr(fr, "name", "unknown"),
                            "response": getattr(fr, "response", None),
                        }
                    if part_data:
                        content_data["parts"].append(part_data)
            
            result.append(content_data)
        
        return result


class AgentRunner:
    """Runs ADK agents inside the sandbox."""
    
    def __init__(self):
        self.generated_code: Optional[str] = None
        self.project_name: Optional[str] = None
        self.app_id: Optional[str] = None
        self.project_config: Optional[Dict[str, Any]] = None
        self.running = False
        self.session_id: Optional[str] = None
        self.events: List[Dict[str, Any]] = []
        self._event_queue: asyncio.Queue = asyncio.Queue()
    
    async def load_project(self, data: Dict[str, Any]):
        """Load generated Python code for the project.
        
        Args:
            data: Dict with 'code' (generated Python code), 'project_name', and 'app_id'
        """
        self.generated_code = data.get("code")
        # self.generated_code.replace("localhost", "host.docker.internal")
        self.project_name = data.get("project_name", "sandbox_app")
        self.app_id = data.get("app_id")
        
        # Load project config from mounted file for service URIs
        try:
            if Path(PROJECT_CONFIG_PATH).exists():
                with open(PROJECT_CONFIG_PATH) as f:
                    self.project_config = json.load(f)
                logger.info(f"Loaded project config from {PROJECT_CONFIG_PATH}")
        except Exception as e:
            logger.warning(f"Failed to load project config: {e}")
            self.project_config = None
        
        logger.info(f"Loaded project: {self.project_name} (app_id={self.app_id}, {len(self.generated_code or '')} chars)")
    
    async def run_agent(
        self,
        user_message: str,
        session_id: Optional[str] = None,
    ) -> str:
        """Run the agent with the given message.
        
        Returns:
            The session ID
        """
        if not self.generated_code:
            raise ValueError("No project loaded")
        
        self.session_id = session_id or str(uuid.uuid4())[:8]
        self.running = True
        self.events = []
        
        try:
            # Add workspace to path
            workspace = Path(WORKSPACE_PATH)
            if str(workspace) not in sys.path:
                sys.path.insert(0, str(workspace))
            
            # Import ADK components
            from google.adk.runners import Runner
            from google.adk.plugins import BasePlugin
            from google.genai import types
            
            # Create tracking plugin to capture all events
            tracker = TrackingPlugin(emit_callback=self._emit_event)
            
            # Wrap tracker as BasePlugin
            class TrackingPluginWrapper(BasePlugin):
                def __init__(self, tracker):
                    super().__init__(name="tracking")
                    self.tracker = tracker
                
                async def before_agent_callback(self, *, agent, callback_context):
                    return await self.tracker.before_agent_callback(agent=agent, callback_context=callback_context)
                
                async def after_agent_callback(self, *, agent, callback_context):
                    return await self.tracker.after_agent_callback(agent=agent, callback_context=callback_context)
                
                async def before_model_callback(self, *, callback_context, llm_request):
                    return await self.tracker.before_model_callback(callback_context=callback_context, llm_request=llm_request)
                
                async def after_model_callback(self, *, callback_context, llm_response):
                    return await self.tracker.after_model_callback(callback_context=callback_context, llm_response=llm_response)
                
                async def before_tool_callback(self, *, tool, tool_args, tool_context):
                    return await self.tracker.before_tool_callback(tool=tool, tool_args=tool_args, tool_context=tool_context)
                
                async def after_tool_callback(self, *, tool, tool_args, tool_context, result):
                    return await self.tracker.after_tool_callback(tool=tool, tool_args=tool_args, tool_context=tool_context, result=result)
                
                async def on_event_callback(self, *, invocation_context, event):
                    return await self.tracker.on_event_callback(invocation_context=invocation_context, event=event)
            
            # Execute the generated code to get the app
            logger.info(f"Executing generated code ({len(self.generated_code)} chars)")
            namespace = {"__builtins__": __builtins__, "__name__": "__main__"}
            exec(compile(self.generated_code, "<generated>", "exec"), namespace)
            
            if "app" not in namespace:
                raise ValueError("Generated code did not produce an 'app' variable")
            
            app = namespace["app"]
            
            # Add tracking plugin to the app
            if hasattr(app, "plugins") and app.plugins is not None:
                app.plugins.append(TrackingPluginWrapper(tracker))
            else:
                app.plugins = [TrackingPluginWrapper(tracker)]
            
            # Create services from project config URIs (or use in-memory defaults)
            app_config = self.project_config.get("app", {}) if self.project_config else {}
            session_uri = app_config.get("session_service_uri", "memory://")
            memory_uri = app_config.get("memory_service_uri", "memory://")
            artifact_uri = app_config.get("artifact_service_uri", "memory://")
            
            logger.info(f"Creating services: session={session_uri}, memory={memory_uri}, artifact={artifact_uri}")
            
            session_service = create_session_service_from_uri(session_uri)
            memory_service = create_memory_service_from_uri(memory_uri)
            artifact_service = create_artifact_service_from_uri(artifact_uri)
            
            # Create runner
            runner = Runner(
                app=app,
                session_service=session_service,
                artifact_service=artifact_service,
                memory_service=memory_service,
            )
            
            # Create session
            adk_session = await runner.session_service.create_session(
                app_name=app.name,
                user_id="playground_user",
                session_id=self.session_id,
            )
            
            # Emit session info event (so frontend can track session_id)
            session_reused = self.session_id is not None and adk_session.id == self.session_id
            await self._emit_event({
                "event_type": "agent_start",
                "timestamp": time.time(),
                "agent_name": "system",
                "data": {"session_id": adk_session.id, "session_reused": session_reused},
            })
            
            # Emit user message event (for test case creation)
            await self._emit_event({
                "event_type": "user_message",
                "timestamp": time.time(),
                "agent_name": "user",
                "data": {"message": user_message},
            })
            
            # Run the agent - events are captured by the TrackingPlugin callbacks
            content = types.Content(
                role="user",
                parts=[types.Part.from_text(text=user_message)],
            )
            
            # Run with retry logic for connection failures
            max_retries = 3
            retry_delay = 2  # seconds
            last_error = None
            
            for attempt in range(max_retries):
                try:
                    async for event in runner.run_async(
                        user_id=adk_session.user_id,
                        session_id=adk_session.id,
                        new_message=content,
                    ):
                        if not self.running:
                            break
                        # Process the event to extract tool calls/results that plugin callbacks might miss
                        await self._process_event(event)
                    # Success - break out of retry loop
                    break
                except BaseException as e:
                    last_error = e
                    error_info = extract_exception_details(e)
                    error_str = error_info.get("raw", str(e)).lower()
                    
                    # Check if this is a retryable connection error
                    is_retryable = any(msg in error_str for msg in [
                        'connection', 'disconnected', 'closed', 'timeout',
                        'reset', 'refused', 'unavailable', 'server error'
                    ])
                    
                    if is_retryable and attempt < max_retries - 1:
                        logger.warning(f"Agent run failed (attempt {attempt + 1}/{max_retries}): {error_info['message']}")
                        await self._emit_event({
                            "event_type": "callback_start",
                            "timestamp": time.time(),
                            "agent_name": "system",
                            "data": {"message": f"Connection error, retrying ({attempt + 2}/{max_retries})..."},
                        })
                        await asyncio.sleep(retry_delay * (attempt + 1))  # Exponential backoff
                        continue
                    else:
                        # Emit error event with detailed, user-friendly information
                        logger.error(f"Agent run error: {error_info['message']}")
                        await self._emit_event({
                            "event_type": "agent_end",
                            "timestamp": time.time(),
                            "agent_name": "system",
                            "data": {
                                "error": error_info["message"],
                                "hint": error_info.get("hint"),
                                "error_type": error_info.get("error_type"),
                                "exception_type": error_info.get("exception_type"),
                                "is_exception_group": error_info.get("is_exception_group", False),
                                "sub_errors": error_info.get("sub_errors"),
                                "raw_error": error_info.get("raw"),
                                "stack_trace": error_info.get("stack_trace"),
                            },
                        })
                        # Don't re-raise - we've already reported the error
                        break
            
            # Check for compaction events after run completes
            try:
                final_session = await runner.session_service.get_session(
                    app_name=self.project_name,
                    user_id=adk_session.user_id,
                    session_id=adk_session.id,
                )
                if final_session and final_session.events:
                    for event in final_session.events:
                        if hasattr(event, 'actions') and event.actions and hasattr(event.actions, 'compaction') and event.actions.compaction:
                            compaction = event.actions.compaction
                            # Get summary text from compacted content
                            summary_text = ""
                            if hasattr(compaction, 'compacted_content') and compaction.compacted_content:
                                content = compaction.compacted_content
                                if hasattr(content, 'parts') and content.parts:
                                    for part in content.parts:
                                        if hasattr(part, 'text') and part.text:
                                            summary_text = part.text[:500] + "..." if len(part.text) > 500 else part.text
                                            break
                            
                            await self._emit_event({
                                "event_type": "compaction",
                                "timestamp": time.time(),
                                "agent_name": "system",
                                "data": {
                                    "start_timestamp": getattr(compaction, 'start_timestamp', None),
                                    "end_timestamp": getattr(compaction, 'end_timestamp', None),
                                    "summary_preview": summary_text,
                                    "event_timestamp": getattr(event, 'timestamp', None),
                                },
                            })
            except Exception as e:
                logger.warning(f"Failed to check for compaction events: {e}")
            
            await runner.close()
            
        except Exception as e:
            logger.error(f"Agent run failed: {e}", exc_info=True)
            await self._emit_event({
                "type": "error",
                "error": str(e),
                "timestamp": time.time(),
            })
        finally:
            self.running = False
        
        return self.session_id
    
    async def _process_event(self, event):
        """Process an ADK Event for additional data.
        
        Note: Tool calls and results are already emitted by TrackingPlugin callbacks,
        so we don't emit them here to avoid duplication.
        
        This method can be extended to process other event data in the future.
        """
        # Currently, all needed events are captured by TrackingPlugin callbacks.
        # This method is kept for potential future use (e.g., capturing state changes
        # or other event data that callbacks might miss).
        pass
    
    async def _emit_event(self, event: Dict[str, Any]):
        """Emit an event to the queue and notify host."""
        self.events.append(event)
        await self._event_queue.put(event)
        
        # Also send to host webhook with app_id
        # Must use proxy since we're on an internal network
        proxy_url = os.environ.get("HTTP_PROXY")
        try:
            event_with_app_id = {**event, "app_id": self.app_id}
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{HOST_URL}/api/sandbox/event",
                    json=event_with_app_id,
                    proxy=proxy_url,  # Route through gateway
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    if resp.status != 200:
                        logger.warning(f"Event webhook returned {resp.status}")
        except Exception as e:
            logger.warning(f"Failed to notify host: {e}")
    
    def stop(self):
        """Stop the current run."""
        self.running = False


# Global runner instance
runner = AgentRunner()


# HTTP API handlers
async def health_check(request: web.Request) -> web.Response:
    """Health check endpoint."""
    return web.json_response({"status": "ok", "running": runner.running})


async def load_project(request: web.Request) -> web.Response:
    """Load project configuration."""
    data = await request.json()
    await runner.load_project(data)
    return web.json_response({"status": "loaded"})


async def run_agent(request: web.Request) -> web.Response:
    """Run the agent."""
    data = await request.json()
    user_message = data.get("message", "")
    session_id = data.get("session_id")
    wait_for_completion = data.get("wait", True)  # Default to sync mode
    
    if not user_message:
        return web.json_response({"error": "message required"}, status=400)
    
    if wait_for_completion:
        # Run synchronously and wait for completion
        try:
            result_session_id = await runner.run_agent(user_message, session_id)
            return web.json_response({
                "status": "completed",
                "session_id": result_session_id,
                "events": runner.events,
            })
        except Exception as e:
            logger.error(f"Agent run failed: {e}")
            return web.json_response({
                "status": "error",
                "error": str(e),
                "events": runner.events,
            }, status=500)
    else:
        # Run in background (async mode)
        asyncio.create_task(runner.run_agent(user_message, session_id))
        return web.json_response({
            "status": "started",
            "session_id": runner.session_id,
        })


async def stop_agent(request: web.Request) -> web.Response:
    """Stop the current run."""
    runner.stop()
    return web.json_response({"status": "stopped"})


async def get_events(request: web.Request) -> web.Response:
    """Get all events from the current/last run."""
    return web.json_response({"events": runner.events})


async def stream_events(request: web.Request) -> web.StreamResponse:
    """Stream events via Server-Sent Events."""
    response = web.StreamResponse(
        status=200,
        reason="OK",
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
    await response.prepare(request)
    
    while True:
        try:
            event = await asyncio.wait_for(
                runner._event_queue.get(),
                timeout=30,
            )
            data = json.dumps(event)
            await response.write(f"data: {data}\n\n".encode())
        except asyncio.TimeoutError:
            # Send keepalive
            await response.write(b": keepalive\n\n")
        except Exception:
            break
    
    return response


async def mcp_list_servers(request: web.Request) -> web.Response:
    """List available MCP servers."""
    try:
        servers = mcp_manager.list_servers()
        return web.json_response({"servers": servers})
    except Exception as e:
        logger.error(f"Failed to list MCP servers: {e}")
        return web.json_response({"error": str(e)}, status=500)


async def mcp_list_tools(request: web.Request) -> web.Response:
    """List tools from an MCP server."""
    try:
        data = await request.json()
        server_name = data.get("server")
        if not server_name:
            return web.json_response({"error": "server name required"}, status=400)
        
        tools = await mcp_manager.list_tools(server_name)
        return web.json_response({"tools": tools})
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=404)
    except Exception as e:
        logger.error(f"Failed to list MCP tools: {e}")
        return web.json_response({"error": str(e)}, status=500)


async def mcp_call_tool(request: web.Request) -> web.Response:
    """Call a tool on an MCP server."""
    try:
        data = await request.json()
        server_name = data.get("server")
        tool_name = data.get("tool")
        args = data.get("args", {})
        
        if not server_name:
            return web.json_response({"error": "server name required"}, status=400)
        if not tool_name:
            return web.json_response({"error": "tool name required"}, status=400)
        
        result = await mcp_manager.call_tool(server_name, tool_name, args)
        return web.json_response({"result": result})
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=404)
    except Exception as e:
        logger.error(f"Failed to call MCP tool: {e}", exc_info=True)
        return web.json_response({"error": str(e)}, status=500)


async def mcp_disconnect(request: web.Request) -> web.Response:
    """Disconnect from an MCP server."""
    try:
        data = await request.json()
        server_name = data.get("server")
        if server_name:
            await mcp_manager.disconnect(server_name)
        else:
            await mcp_manager.disconnect_all()
        return web.json_response({"status": "disconnected"})
    except Exception as e:
        logger.error(f"Failed to disconnect MCP: {e}")
        return web.json_response({"error": str(e)}, status=500)


def create_app() -> web.Application:
    """Create the HTTP API application."""
    app = web.Application()
    
    # Agent endpoints
    app.router.add_get("/health", health_check)
    app.router.add_post("/project", load_project)
    app.router.add_post("/run", run_agent)
    app.router.add_post("/stop", stop_agent)
    app.router.add_get("/events", get_events)
    app.router.add_get("/events/stream", stream_events)
    
    # MCP endpoints - for Tool Watches and debugging
    app.router.add_get("/mcp/servers", mcp_list_servers)
    app.router.add_post("/mcp/tools", mcp_list_tools)
    app.router.add_post("/mcp/call", mcp_call_tool)
    app.router.add_post("/mcp/disconnect", mcp_disconnect)
    
    return app


async def main():
    """Run the agent runner API."""
    # Check if project config exists
    config_path = Path(PROJECT_CONFIG_PATH)
    if config_path.exists():
        with open(config_path) as f:
            config = json.load(f)
        await runner.load_project(config)
    
    app = create_app()
    app_runner = web.AppRunner(app)
    await app_runner.setup()
    
    site = web.TCPSite(app_runner, "0.0.0.0", API_PORT)
    await site.start()
    
    logger.info(f"Agent runner API running on port {API_PORT}")
    
    # Keep running
    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())

