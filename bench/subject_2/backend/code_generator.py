"""
Code Generator - Generates Python code from Project configuration.

This module converts the YAML-based Project model into executable Python code
that uses the ADK SDK. The generated code is the same as what's shown in the
Code tab of the UI.
"""

import json
from typing import Dict, List, Any, Set
from models import (
    Project, AgentConfig, LlmAgentConfig, ToolConfig, 
    MCPServerConfig, SequentialAgentConfig, LoopAgentConfig,
    ParallelAgentConfig, CallbackConfig
)


def escape_triple_quoted(s: str) -> str:
    """Escape a string for use in Python triple-quoted strings (triple double-quotes).
    
    Handles: backslashes, triple-quote sequences, and trailing quotes
    """
    if not s:
        return ""
    # Escape backslashes first, then triple-quotes
    s = s.replace("\\", "\\\\").replace('"""', '\\"\\"\\"')
    # If the string ends with a quote, add a space to prevent """" syntax issues
    if s.endswith('"'):
        s = s + " "
    return s


def sanitize_identifier(name: str) -> str:
    """Sanitize a name to be a valid Python identifier.
    
    Replaces invalid characters (like '-') with underscores.
    Ensures the result starts with a letter or underscore.
    """
    if not name:
        return "_unnamed"
    # Replace any non-alphanumeric/underscore characters with underscore
    safe = "".join(c if c.isalnum() or c == "_" else "_" for c in name)
    # Ensure it starts with a letter or underscore (not a digit)
    if safe and safe[0].isdigit():
        safe = "_" + safe
    return safe or "_unnamed"


def escape_double_quoted(s: str) -> str:
    """Escape a string for use in Python double-quoted strings.
    
    Handles: backslashes, double-quotes, newlines, tabs, carriage returns
    """
    if not s:
        return ""
    # Escape backslashes first
    s = s.replace("\\", "\\\\")
    # Then escape double-quotes
    s = s.replace('"', '\\"')
    # Escape common control characters
    s = s.replace("\n", "\\n")
    s = s.replace("\r", "\\r")
    s = s.replace("\t", "\\t")
    return s


def escape_string(s: str) -> str:
    """Escape for Python triple-quoted string (legacy alias)."""
    return escape_triple_quoted(s)


def generate_model_code(model: dict, model_name: str = "model") -> str:
    """Generate Python code for a model configuration."""
    if not model:
        return ""
    
    model_name_str = model.get("model_name", "gemini-2.0-flash")
    provider = model.get("provider", "gemini")
    
    params = [f'model="{model_name_str}"']
    
    if model.get("api_base"):
        params.append(f'api_base="{model["api_base"]}"')
    if model.get("temperature") is not None:
        params.append(f'temperature={model["temperature"]}')
    if model.get("max_output_tokens") is not None:
        params.append(f'max_output_tokens={model["max_output_tokens"]}')
    if model.get("top_p") is not None:
        params.append(f'top_p={model["top_p"]}')
    if model.get("top_k") is not None:
        params.append(f'top_k={model["top_k"]}')
    
    # Retry and timeout settings (especially important for local models like Ollama)
    num_retries = model.get("num_retries")
    request_timeout = model.get("request_timeout")
    
    # Apply default retries for local/unreliable providers
    if provider in ("litellm", "openai", "groq", "together"):
        # Default to 3 retries and 10 minute timeout for these providers
        if num_retries is None:
            num_retries = 3
        if request_timeout is None:
            request_timeout = 1800  # 30 minutes - local models can be slow
        
        params.append(f'num_retries={num_retries}')
        params.append(f'timeout={request_timeout}')
        
        return f"{model_name} = LiteLlm(\n    {', '.join(params)}\n)"
    elif provider == "anthropic":
        if num_retries is not None:
            params.append(f'num_retries={num_retries}')
        if request_timeout is not None:
            params.append(f'timeout={request_timeout}')
        return f"{model_name} = Claude(\n    {', '.join(params)}\n)"
    else:
        # Gemini - just use string
        return f'{model_name} = "{model_name_str}"  # Gemini model'


def generate_tool_code(tool: ToolConfig, project: Project, agent_var_names: Dict[str, str]) -> str:
    """Generate Python code for a tool reference."""
    tool_type = tool.type
    
    if tool_type == "builtin":
        return tool.name or ""
    elif tool_type == "function":
        return tool.name or "custom_tool"
    elif tool_type == "agent":
        agent_id = getattr(tool, "agent_id", None)
        if agent_id and agent_id in agent_var_names:
            return f"AgentTool(agent={agent_var_names[agent_id]})"
        return ""  # Skip if agent doesn't exist
    elif tool_type == "mcp":
        if tool.server and tool.server.name:
            return f"{sanitize_identifier(tool.server.name)}_tools"
        return ""
    elif tool_type == "skillset":
        skillset_id = getattr(tool, "skillset_id", None)
        if skillset_id and project.skillsets:
            skillset = next((s for s in project.skillsets if s.get("id") == skillset_id), None)
            if skillset:
                safe_name = "".join(c if c.isalnum() or c == "_" else "_" for c in skillset.get("name", ""))
                return f"{safe_name}_skillset"
        return ""
    
    return ""


def _is_browser_mcp_server(server: MCPServerConfig) -> bool:
    """Check if this MCP server is browser-related and needs Docker Chrome args."""
    browser_names = {"chrome_devtools", "chrome-devtools", "puppeteer", "playwright", 
                     "browser", "browserbase", "web-browser"}
    
    # Check server name
    name_lower = server.name.lower() if server.name else ""
    for browser_name in browser_names:
        if browser_name in name_lower:
            return True
    
    # Check args for browser-related packages
    args_str = " ".join(server.args or []).lower()
    browser_packages = ["chrome-devtools-mcp", "puppeteer", "playwright", "browserbase"]
    for pkg in browser_packages:
        if pkg in args_str:
            return True
    
    return False


def _is_chrome_devtools_mcp(server: MCPServerConfig) -> bool:
    """Check if this is specifically chrome-devtools-mcp."""
    args_str = " ".join(server.args or []).lower()
    return "chrome-devtools-mcp" in args_str


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


def generate_mcp_toolset_code(server: MCPServerConfig) -> str:
    """Generate Python code for an MCP toolset.
    
    Note: For stdio connections, we always inject proxy environment variables
    because the MCP library only inherits a limited set of env vars to the
    subprocess (PATH, HOME, etc. but NOT HTTP_PROXY).
    
    For browser MCP servers (like chrome-devtools-mcp), we also inject
    Docker-friendly Chrome args to ensure the browser can run in container.
    """
    lines = []
    
    if server.connection_type == "stdio":
        # Check if this is a browser MCP server that needs Docker Chrome args
        is_devtools = _is_chrome_devtools_mcp(server)
        is_browser = _is_browser_mcp_server(server)
        
        # Prepare args - potentially inject Docker Chrome args
        args = list(server.args or [])
        if is_devtools:
            # Inject Docker Chrome args for chrome-devtools-mcp
            existing_args_str = " ".join(args)
            for flag in DOCKER_CHROME_ARGS_FOR_DEVTOOLS_MCP:
                flag_base = flag.split("=")[-1] if "=" in flag else flag
                if flag_base not in existing_args_str and flag not in existing_args_str:
                    args.append(flag)
        
        lines.append(f"{sanitize_identifier(server.name)}_tools = McpToolset(")
        lines.append("    connection_params=StdioConnectionParams(")
        lines.append("        server_params=StdioServerParameters(")
        if server.command:
            lines.append(f'            command="{server.command}",')
        if args:
            lines.append(f"            args={json.dumps(args)},")
        
        # Always generate env with proxy variables merged in
        # The MCP library only inherits PATH, HOME, etc. - NOT proxy vars
        # Also include Chrome-related env vars for browser MCP servers
        lines.append("            env={")
        lines.append('                **{k: v for k, v in os.environ.items() if k.upper() in ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "UV_HTTP_PROXY", "UV_HTTPS_PROXY", "NPM_CONFIG_PROXY", "NPM_CONFIG_HTTPS_PROXY") or k.lower() in ("http_proxy", "https_proxy", "no_proxy")},')
        if is_browser or is_devtools:
            # Include Chrome-related env vars for browser MCP servers
            lines.append('                **{k: v for k, v in os.environ.items() if k in ("CHROME_BIN", "CHROMIUM_BIN", "CHROMEDRIVER_BIN", "GOOGLE_CHROME_BIN", "PUPPETEER_SKIP_DOWNLOAD", "PUPPETEER_EXECUTABLE_PATH", "PUPPETEER_ARGS", "CHROME_ARGS", "DISPLAY")},')
        if server.env:
            # Add user-specified env vars
            for key, value in server.env.items():
                lines.append(f'                "{key}": {json.dumps(value)},')
        lines.append("            },")
        
        lines.append("        ),")
        if server.timeout:
            lines.append(f"        timeout={server.timeout},")
        lines.append("    ),")
        lines.append(")")
    elif server.connection_type == "sse":
        lines.append(f"{sanitize_identifier(server.name)}_tools = McpToolset(")
        lines.append("    connection_params=SseConnectionParams(")
        if server.url:
            lines.append(f'        url="{server.url}",')
        if server.timeout:
            lines.append(f"        timeout={server.timeout},")
        lines.append("    ),")
        lines.append(")")
    
    return "\n".join(lines)


def generate_skillset_code(skillset: dict, project: Project) -> str:
    """Generate Python code for a SkillSet toolset."""
    lines = []
    safe_name = "".join(c if c.isalnum() or c == "_" else "_" for c in skillset.get("name", ""))
    
    lines.append(f"# SkillSet: {skillset.get('name', '')}")
    lines.append(f"{safe_name}_manager = KnowledgeServiceManager()")
    lines.append(f"{safe_name}_skillset = SkillSet(")
    lines.append(f'    skillset_id="{skillset.get("id", "")}",')
    lines.append(f'    project_id="{project.id}",')
    lines.append(f"    manager={safe_name}_manager,")
    
    embedding_model = skillset.get("embedding_model", "text-embedding-004")
    lines.append(f'    model_name="{embedding_model}",')
    
    lines.append(f'    search_enabled={skillset.get("search_enabled", False)},')
    lines.append(f'    preload_enabled={skillset.get("preload_enabled", False)},')
    
    if skillset.get("preload_top_k"):
        lines.append(f'    preload_top_k={skillset["preload_top_k"]},')
    if skillset.get("preload_min_score"):
        lines.append(f'    preload_min_score={skillset["preload_min_score"]},')
    
    lines.append(")")
    
    return "\n".join(lines)


def generate_agent_code(
    agent: AgentConfig, 
    project: Project, 
    agent_var_names: Dict[str, str]
) -> str:
    """Generate Python code for an agent."""
    var_name = agent_var_names.get(agent.id, f"{agent.name}_agent")
    
    if isinstance(agent, LlmAgentConfig) or agent.type == "LlmAgent":
        params = [f'name="{escape_double_quoted(agent.name)}"']
        
        # Model
        if hasattr(agent, "model") and agent.model:
            params.append(f"model={agent.name}_model")
        
        # Instruction
        if hasattr(agent, "instruction") and agent.instruction:
            params.append(f'instruction="""{escape_string(agent.instruction)}"""')
        
        # Description
        if hasattr(agent, "description") and agent.description:
            params.append(f'description="{escape_double_quoted(agent.description)}"')
        
        # Output key
        if hasattr(agent, "output_key") and agent.output_key:
            params.append(f'output_key="{agent.output_key}"')
        
        # Tools
        if hasattr(agent, "tools") and agent.tools:
            tool_refs = []
            for t in agent.tools:
                tool_code = generate_tool_code(t, project, agent_var_names)
                if tool_code and not tool_code.startswith("#"):
                    tool_refs.append(tool_code)
            if tool_refs:
                params.append(f"tools=[{', '.join(tool_refs)}]")
        
        # Sub-agents
        if hasattr(agent, "sub_agents") and agent.sub_agents:
            # Only include sub-agents that exist in agent_var_names
            sub_agent_vars = [agent_var_names[sid] for sid in agent.sub_agents if sid in agent_var_names]
            if sub_agent_vars:
                params.append(f"sub_agents=[{', '.join(sub_agent_vars)}]")
        
        # Include contents
        if hasattr(agent, "include_contents") and agent.include_contents == "none":
            params.append('include_contents="none"')
        
        # Transfer settings
        if hasattr(agent, "disallow_transfer_to_parent") and agent.disallow_transfer_to_parent:
            params.append("disallow_transfer_to_parent=True")
        if hasattr(agent, "disallow_transfer_to_peers") and agent.disallow_transfer_to_peers:
            params.append("disallow_transfer_to_peers=True")
        
        # Callbacks - ADK uses singular names
        callback_mapping = {
            "before_agent_callbacks": "before_agent_callback",
            "after_agent_callbacks": "after_agent_callback",
            "before_model_callbacks": "before_model_callback",
            "after_model_callbacks": "after_model_callback",
            "before_tool_callbacks": "before_tool_callback",
            "after_tool_callbacks": "after_tool_callback",
        }
        
        # Built-in callbacks that are always available
        BUILTIN_CALLBACKS = {'exit_on_EXIT_LOOP_NOW'}
        
        for config_key, adk_key in callback_mapping.items():
            if hasattr(agent, config_key):
                callbacks = getattr(agent, config_key, []) or []
                if callbacks:
                    # Find callback definitions to get function names
                    callback_refs = []
                    for c in callbacks:
                        full_path = c.module_path if hasattr(c, "module_path") else c.get("module_path", "")
                        
                        # Check for built-in callbacks first
                        if full_path in BUILTIN_CALLBACKS:
                            # Built-in callbacks don't need wrapping
                            callback_refs.append(full_path)
                            continue
                        
                        callback_def = None
                        func_name = None
                        
                        # First, try to match by full path
                        for cb in project.custom_callbacks:
                            if cb.module_path == full_path:
                                callback_def = cb
                                func_name = cb.name
                                break
                        
                        # If not found, try parsing as "module.function"
                        if not callback_def:
                            parts = full_path.rsplit(".", 1)
                            if len(parts) == 2:
                                possible_module, possible_func = parts
                                for cb in project.custom_callbacks:
                                    if cb.module_path == possible_module and cb.name == possible_func:
                                        callback_def = cb
                                        func_name = possible_func
                                        break
                        
                        if callback_def and func_name:
                            # Wrap callback with instrumentation for tracking
                            wrapped = f'_wrap_callback("{func_name}", "{adk_key}", {func_name})'
                            callback_refs.append(wrapped)
                        else:
                            # Fallback - try to extract function name from path
                            parts = full_path.rsplit(".", 1)
                            if len(parts) == 2:
                                fn = parts[1]
                                wrapped = f'_wrap_callback("{fn}", "{adk_key}", {fn})'
                                callback_refs.append(wrapped)
                            else:
                                # Last resort - use full path as string (will likely fail)
                                callback_refs.append(f'"{full_path}"')
                    
                    if len(callbacks) == 1:
                        params.append(f"{adk_key}={callback_refs[0]}")
                    else:
                        params.append(f"{adk_key}=[{', '.join(callback_refs)}]")
        
        params_str = ',\n    '.join(params)
        return f"{var_name} = Agent(\n    {params_str},\n)"
    
    elif isinstance(agent, SequentialAgentConfig) or agent.type == "SequentialAgent":
        params = [f'name="{escape_double_quoted(agent.name)}"']
        sub_agent_vars = [agent_var_names[sid] for sid in (agent.sub_agents or []) if sid in agent_var_names]
        if sub_agent_vars:
            params.append(f"sub_agents=[{', '.join(sub_agent_vars)}]")
        # Add agent callbacks for SequentialAgent
        BUILTIN_CALLBACKS = {'exit_on_EXIT_LOOP_NOW'}
        for callback_type in ["before_agent_callbacks", "after_agent_callbacks"]:
            if hasattr(agent, callback_type):
                callbacks = getattr(agent, callback_type) or []
                if callbacks:
                    adk_key = callback_type.replace("_callbacks", "_callback")
                    callback_refs = []
                    for cb in callbacks:
                        if cb.module_path in BUILTIN_CALLBACKS:
                            callback_refs.append(cb.module_path)
                        else:
                            fn = cb.module_path.split(".")[-1]
                            callback_refs.append(f'_wrap_callback("{fn}", "{adk_key}", {fn})')
                    params.append(f"{adk_key}=[{', '.join(callback_refs)}]")
        params_str = ',\n    '.join(params)
        return f'{var_name} = SequentialAgent(\n    {params_str},\n)'
    
    elif isinstance(agent, LoopAgentConfig) or agent.type == "LoopAgent":
        params = [f'name="{escape_double_quoted(agent.name)}"']
        sub_agent_vars = [agent_var_names[sid] for sid in (agent.sub_agents or []) if sid in agent_var_names]
        if sub_agent_vars:
            params.append(f"sub_agents=[{', '.join(sub_agent_vars)}]")
        if hasattr(agent, "max_iterations") and agent.max_iterations:
            params.append(f"max_iterations={agent.max_iterations}")
        # Add agent callbacks for LoopAgent
        BUILTIN_CALLBACKS = {'exit_on_EXIT_LOOP_NOW'}
        for callback_type in ["before_agent_callbacks", "after_agent_callbacks"]:
            if hasattr(agent, callback_type):
                callbacks = getattr(agent, callback_type) or []
                if callbacks:
                    adk_key = callback_type.replace("_callbacks", "_callback")
                    callback_refs = []
                    for cb in callbacks:
                        if cb.module_path in BUILTIN_CALLBACKS:
                            callback_refs.append(cb.module_path)
                        else:
                            fn = cb.module_path.split(".")[-1]
                            callback_refs.append(f'_wrap_callback("{fn}", "{adk_key}", {fn})')
                    params.append(f"{adk_key}=[{', '.join(callback_refs)}]")
        params_str = ',\n    '.join(params)
        return f"{var_name} = LoopAgent(\n    {params_str},\n)"
    
    elif isinstance(agent, ParallelAgentConfig) or agent.type == "ParallelAgent":
        params = [f'name="{escape_double_quoted(agent.name)}"']
        sub_agent_vars = [agent_var_names[sid] for sid in (agent.sub_agents or []) if sid in agent_var_names]
        if sub_agent_vars:
            params.append(f"sub_agents=[{', '.join(sub_agent_vars)}]")
        # Add agent callbacks for ParallelAgent
        BUILTIN_CALLBACKS = {'exit_on_EXIT_LOOP_NOW'}
        for callback_type in ["before_agent_callbacks", "after_agent_callbacks"]:
            if hasattr(agent, callback_type):
                callbacks = getattr(agent, callback_type) or []
                if callbacks:
                    adk_key = callback_type.replace("_callbacks", "_callback")
                    callback_refs = []
                    for cb in callbacks:
                        if cb.module_path in BUILTIN_CALLBACKS:
                            callback_refs.append(cb.module_path)
                        else:
                            fn = cb.module_path.split(".")[-1]
                            callback_refs.append(f'_wrap_callback("{fn}", "{adk_key}", {fn})')
                    params.append(f"{adk_key}=[{', '.join(callback_refs)}]")
        params_str = ',\n    '.join(params)
        return f'{var_name} = ParallelAgent(\n    {params_str},\n)'
    
    return f"# Unknown agent type: {agent.type}"


def generate_python_code(project: Project) -> str:
    """
    Generate complete Python code from a Project configuration.
    
    This generates the same code shown in the Code tab of the UI.
    """
    lines = []
    
    # Header comment
    lines.append('"""')
    lines.append(f"{escape_triple_quoted(project.name)} - Generated by ADK Playground")
    if project.description:
        lines.append("")
        lines.append(escape_triple_quoted(project.description))
    lines.append('"""')
    lines.append("")
    
    # Environment variables (shown as comments - actual values set by runtime)
    env_vars = project.app.env_vars if project.app and project.app.env_vars else {}
    if env_vars:
        lines.append("# Environment Variables (set these in your environment)")
        for key, value in env_vars.items():
            is_sensitive = "key" in key.lower() or "secret" in key.lower() or "token" in key.lower()
            if value and not is_sensitive:
                lines.append(f'# os.environ["{key}"] = "{value}"')
            else:
                lines.append(f'# os.environ["{key}"] = "..."  # Set your {key}')
        lines.append("")
    
    # Collect imports
    imports: Set[str] = set()
    imports.add("from google.adk.agents import Agent")
    
    has_sequential = any(a.type == "SequentialAgent" for a in project.agents)
    has_loop = any(a.type == "LoopAgent" for a in project.agents)
    has_parallel = any(a.type == "ParallelAgent" for a in project.agents)
    
    if has_sequential:
        imports.add("from google.adk.agents import SequentialAgent")
    if has_loop:
        imports.add("from google.adk.agents import LoopAgent")
    if has_parallel:
        imports.add("from google.adk.agents import ParallelAgent")
    
    # Check for LiteLLM/Anthropic models
    for agent in project.agents:
        if hasattr(agent, "model") and agent.model:
            provider = agent.model.provider if hasattr(agent.model, "provider") else agent.model.get("provider", "")
            if provider in ("litellm", "openai", "groq", "together"):
                imports.add("from google.adk.models.lite_llm import LiteLlm")
            elif provider == "anthropic":
                imports.add("from google.adk.models.anthropic import Claude")
    
    # Check for AgentTool
    for agent in project.agents:
        if hasattr(agent, "tools"):
            for tool in agent.tools:
                if tool.type == "agent":
                    imports.add("from google.adk.tools import AgentTool")
                    break
    
    # Check for built-in tools
    builtin_tools: Set[str] = set()
    for agent in project.agents:
        if hasattr(agent, "tools"):
            for tool in agent.tools:
                if tool.type == "builtin" and tool.name:
                    builtin_tools.add(tool.name)
    
    if "exit_loop" in builtin_tools:
        imports.add("from google.adk.tools import exit_loop")
    if "google_search" in builtin_tools:
        imports.add("from google.adk.tools import google_search")
    
    # Check for MCP
    if project.mcp_servers:
        imports.add("from google.adk.tools.mcp_tool.mcp_toolset import McpToolset")
        has_stdio = any(s.connection_type == "stdio" for s in project.mcp_servers)
        has_sse = any(s.connection_type == "sse" for s in project.mcp_servers)
        if has_stdio:
            imports.add("import os")  # Needed for proxy env var injection
            imports.add("from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams")
            imports.add("from mcp import StdioServerParameters")
        if has_sse:
            imports.add("from google.adk.tools.mcp_tool.mcp_session_manager import SseConnectionParams")
    
    # Check for SkillSets
    used_skillset_ids: Set[str] = set()
    for agent in project.agents:
        if hasattr(agent, "tools"):
            for tool in agent.tools:
                if tool.type == "skillset":
                    skillset_id = getattr(tool, "skillset_id", None)
                    if skillset_id:
                        used_skillset_ids.add(skillset_id)
    
    if used_skillset_ids:
        imports.add("from skillset import SkillSet")
        imports.add("from knowledge_service import KnowledgeServiceManager")
    
    # Always import App
    imports.add("from google.adk.apps import App")
    
    # Check for plugins
    if project.app and project.app.plugins:
        for plugin in project.app.plugins:
            if plugin.type == "ReflectAndRetryToolPlugin":
                imports.add("from google.adk.plugins import ReflectAndRetryToolPlugin")
    
    # Scan custom tools and callbacks for common types they might use
    all_custom_code = ""
    for tool in project.custom_tools:
        all_custom_code += tool.code + "\n"
    for callback in project.custom_callbacks:
        all_custom_code += callback.code + "\n"
    
    # Add imports for types used in custom code
    if "ToolContext" in all_custom_code:
        imports.add("from google.adk.tools.tool_context import ToolContext")
    if "CallbackContext" in all_custom_code:
        imports.add("from google.adk.agents.callback_context import CallbackContext")
    if "types.Content" in all_custom_code or "types.Part" in all_custom_code:
        imports.add("from google.genai import types")
    if "LlmRequest" in all_custom_code:
        imports.add("from google.adk.models.llm_request import LlmRequest")
    if "LlmResponse" in all_custom_code:
        imports.add("from google.adk.models.llm_response import LlmResponse")
    if "Optional[" in all_custom_code or "List[" in all_custom_code or "Dict[" in all_custom_code:
        imports.add("from typing import Optional, List, Dict, Any")
    
    # Add imports
    for imp in sorted(imports):
        lines.append(imp)
    lines.append("")
    
    # Generate callback wrapper right after imports (needed for callback instrumentation)
    if project.custom_callbacks:
        lines.append("")
        lines.append("# --- Callback instrumentation (for event tracking) ---")
        lines.append("def _wrap_callback(name: str, callback_type: str, fn):")
        lines.append("    import functools, inspect, time, uuid")
        lines.append("    @functools.wraps(fn)")
        lines.append("    def sync_wrapper(*args, **kwargs):")
        lines.append("        ctx = kwargs.get('callback_context') or kwargs.get('tool_context')")
        lines.append("        event_id = str(uuid.uuid4())[:8]")
        lines.append("        if ctx and hasattr(ctx, 'state'):")
        lines.append("            ctx.state[f'_cb_start_{event_id}'] = {'type': 'callback_start', 'name': name, 'callback_type': callback_type, 'ts': time.time()}")
        lines.append("        try:")
        lines.append("            return fn(*args, **kwargs)")
        lines.append("        finally:")
        lines.append("            if ctx and hasattr(ctx, 'state'):")
        lines.append("                ctx.state[f'_cb_end_{event_id}'] = {'type': 'callback_end', 'name': name, 'callback_type': callback_type, 'ts': time.time()}")
        lines.append("    @functools.wraps(fn)")
        lines.append("    async def async_wrapper(*args, **kwargs):")
        lines.append("        ctx = kwargs.get('callback_context') or kwargs.get('tool_context')")
        lines.append("        event_id = str(uuid.uuid4())[:8]")
        lines.append("        if ctx and hasattr(ctx, 'state'):")
        lines.append("            ctx.state[f'_cb_start_{event_id}'] = {'type': 'callback_start', 'name': name, 'callback_type': callback_type, 'ts': time.time()}")
        lines.append("        try:")
        lines.append("            return await fn(*args, **kwargs)")
        lines.append("        finally:")
        lines.append("            if ctx and hasattr(ctx, 'state'):")
        lines.append("                ctx.state[f'_cb_end_{event_id}'] = {'type': 'callback_end', 'name': name, 'callback_type': callback_type, 'ts': time.time()}")
        lines.append("    return async_wrapper if inspect.iscoroutinefunction(fn) else sync_wrapper")
        lines.append("# --- End callback instrumentation ---")
        lines.append("")
    
    # Check if any agent uses the built-in exit_on_EXIT_LOOP_NOW callback
    uses_exit_loop_callback = False
    for agent in project.agents:
        for cb_type in ['before_agent_callbacks', 'after_agent_callbacks', 
                        'before_model_callbacks', 'after_model_callbacks']:
            cbs = getattr(agent, cb_type, None) or []
            for cb in cbs:
                if cb.module_path == 'exit_on_EXIT_LOOP_NOW':
                    uses_exit_loop_callback = True
                    break
    
    # Generate built-in callbacks
    if uses_exit_loop_callback:
        lines.append("")
        lines.append("# --- Built-in Callbacks ---")
        lines.append("# exit_on_EXIT_LOOP_NOW: Use as after_model_callback to exit a LoopAgent")
        lines.append("# Instruct your agent to say 'EXIT LOOP NOW' when it's done")
        lines.append("def exit_on_EXIT_LOOP_NOW(*, callback_context, llm_response):")
        lines.append('    """Exit the current LoopAgent when the model says "EXIT LOOP NOW".')
        lines.append("    ")
        lines.append("    Usage: Add as after_model_callback on an agent inside a LoopAgent.")
        lines.append("    Tell the agent: 'When you are satisfied, respond with EXIT LOOP NOW'")
        lines.append('    """')
        lines.append("    text = ''")
        lines.append("    if llm_response.content and llm_response.content.parts:")
        lines.append("        for part in llm_response.content.parts:")
        lines.append("            if hasattr(part, 'text') and part.text:")
        lines.append("                text += part.text")
        lines.append("    if 'EXIT LOOP NOW' in text.upper():")
        lines.append("        callback_context._event_actions.escalate = True")
        lines.append("    return llm_response")
        lines.append("# --- End built-in callbacks ---")
        lines.append("")
    
    lines.append("")
    
    # Build agent variable name map
    agent_var_names: Dict[str, str] = {}
    for agent in project.agents:
        var_name = f"{agent.name}_agent" if not agent.name.endswith("_agent") else agent.name
        agent_var_names[agent.id] = var_name
    
    # Topological sort agents (sub-agents and agent-tools before parents)
    sorted_agents: List[AgentConfig] = []
    visited: Set[str] = set()
    visiting: Set[str] = set()
    
    def visit_agent(agent_id: str):
        if agent_id in visited:
            return
        # Cycle guard: if we re-enter an agent already on the DFS stack,
        # stop descending to avoid infinite recursion.
        if agent_id in visiting:
            return
        agent = next((a for a in project.agents if a.id == agent_id), None)
        if not agent:
            return
        
        visiting.add(agent_id)
        
        # Visit sub-agents first (for delegation)
        for sub_id in (agent.sub_agents or []):
            visit_agent(sub_id)
        
        # Visit agents used as tools (they must be defined before this agent)
        if hasattr(agent, "tools") and agent.tools:
            for tool in agent.tools:
                if tool.type == "agent":
                    tool_agent_id = getattr(tool, "agent_id", None)
                    if tool_agent_id:
                        visit_agent(tool_agent_id)
        
        visiting.discard(agent_id)
        
        visited.add(agent_id)
        sorted_agents.append(agent)
    
    for agent in project.agents:
        visit_agent(agent.id)
    
    # Collect MCP servers used by agents
    used_mcp_servers: Dict[str, MCPServerConfig] = {}
    for agent in sorted_agents:
        if hasattr(agent, "tools"):
            for tool in agent.tools:
                if tool.type == "mcp" and tool.server:
                    used_mcp_servers[tool.server.name] = tool.server
    
    # Generate MCP toolset code
    if used_mcp_servers:
        lines.append("# MCP Server Toolsets")
        for server in used_mcp_servers.values():
            lines.append(generate_mcp_toolset_code(server))
            lines.append("")
        lines.append("")
    
    # Generate SkillSet toolset code
    if used_skillset_ids and project.skillsets:
        lines.append("# SkillSet Toolsets")
        lines.append("# Note: SkillSets store knowledge in ~/.adk-playground/skillsets/{project_id}/")
        for skillset_id in used_skillset_ids:
            skillset = next((s for s in project.skillsets if s.get("id") == skillset_id), None)
            if skillset:
                lines.append(generate_skillset_code(skillset, project))
                lines.append("")
        lines.append("")
    
    # Generate custom tools
    if project.custom_tools:
        lines.append("# Custom Tools")
        for tool in project.custom_tools:
            lines.append(tool.code)
            lines.append("")
        lines.append("")
    
    # Generate custom callbacks
    if project.custom_callbacks:
        lines.append("# Custom Callbacks")
        for callback in project.custom_callbacks:
            lines.append(callback.code)
            lines.append("")
        lines.append("")
    
    # Generate model definitions
    lines.append("# Models")
    for agent in sorted_agents:
        if hasattr(agent, "model") and agent.model:
            model_dict = agent.model.dict() if hasattr(agent.model, "dict") else agent.model
            lines.append(generate_model_code(model_dict, f"{agent.name}_model"))
            lines.append("")
    lines.append("")
    
    # Generate agents
    lines.append("# Agents")
    for agent in sorted_agents:
        lines.append(generate_agent_code(agent, project, agent_var_names))
        lines.append("")
    
    # Get root agent variable name
    root_agent = next((a for a in project.agents if a.id == project.app.root_agent_id), None)
    root_agent_var_name = agent_var_names.get(root_agent.id if root_agent else "", "root_agent")
    
    # Generate App
    lines.append("")
    lines.append("")
    lines.append("# App Configuration")
    lines.append("app = App(")
    # Sanitize app name to be a valid identifier
    safe_app_name = "".join(c if c.isalnum() or c == "_" else "_" for c in project.app.name)
    lines.append(f'    name="{safe_app_name}",')
    lines.append(f"    root_agent={root_agent_var_name},")
    
    if project.app.plugins:
        plugin_lines = []
        for p in project.app.plugins:
            if p.type == "ReflectAndRetryToolPlugin":
                max_retries = p.max_retries if hasattr(p, "max_retries") else 3
                plugin_lines.append(f"        ReflectAndRetryToolPlugin(max_retries={max_retries})")
            else:
                plugin_lines.append(f"        # {p.type}()")
        lines.append("    plugins=[")
        lines.append(",\n".join(plugin_lines))
        lines.append("    ],")
    
    lines.append(")")
    
    # Export root_agent for compatibility
    lines.append("")
    lines.append(f"root_agent = {root_agent_var_name}")
    
    return "\n".join(lines)

