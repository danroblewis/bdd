"""Known MCP servers with their tools for quick selection."""

from models import MCPServerConfig, MCPConnectionType

import json
import os
from pathlib import Path
from typing import List

# Path to our custom MCP servers
MCP_SERVERS_DIR = os.path.join(os.path.dirname(__file__), "..", "mcp_servers")

# Get MCP config file path from environment variable, default to ~/.adk-playground/mcp.json
_mcp_config_env = os.environ.get("ADK_PLAYGROUND_MCP_CONFIG")
if _mcp_config_env:
    MCP_CONFIG_FILE = Path(_mcp_config_env)
else:
    MCP_CONFIG_FILE = Path.home() / ".adk-playground" / "mcp.json"
# Create parent directory if it doesn't exist
MCP_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)


def load_mcp_servers_from_file() -> List[MCPServerConfig]:
    """Load MCP servers from a standard mcp.json file.
    
    Supports standard mcp.json format:
    {
        "mcpServers": {
            "server-name": {
                "command": "npx",
                "args": ["-y", "@package/server"],
                "env": {"KEY": "value"},
                ...
            }
        }
    }
    
    Returns:
        List of MCPServerConfig objects parsed from the file
    """
    servers = []
    
    if not MCP_CONFIG_FILE.exists():
        return servers
    
    try:
        with open(MCP_CONFIG_FILE, "r") as f:
            data = json.load(f)
        
        # Handle standard mcp.json format with "mcpServers" key
        mcp_servers = data.get("mcpServers", {})
        
        for server_name, server_config in mcp_servers.items():
            try:
                # Convert to MCPServerConfig
                # Default to STDIO if not specified
                connection_type = MCPConnectionType.STDIO
                if "url" in server_config:
                    # If URL is present, assume SSE or HTTP
                    if server_config.get("transport", "sse") == "http":
                        connection_type = MCPConnectionType.HTTP
                    else:
                        connection_type = MCPConnectionType.SSE
                
                config = MCPServerConfig(
                    name=server_name,
                    description=server_config.get("description", ""),
                    connection_type=connection_type,
                    command=server_config.get("command"),
                    args=server_config.get("args", []),
                    env=server_config.get("env", {}),
                    url=server_config.get("url"),
                    headers=server_config.get("headers", {}),
                    timeout=server_config.get("timeout", 10.0),
                    tool_filter=server_config.get("tool_filter"),
                    tool_name_prefix=server_config.get("tool_name_prefix"),
                )
                servers.append(config)
            except Exception as e:
                # Skip invalid server configs but continue loading others
                print(f"Warning: Failed to load MCP server '{server_name}' from {MCP_CONFIG_FILE}: {e}")
                continue
                
    except json.JSONDecodeError as e:
        print(f"Warning: Invalid JSON in {MCP_CONFIG_FILE}: {e}")
    except Exception as e:
        print(f"Warning: Failed to load MCP servers from {MCP_CONFIG_FILE}: {e}")
    
    return servers


# Built-in known MCP servers (hardcoded defaults)
_BUILTIN_MCP_SERVERS = [
    MCPServerConfig(
        name="time",
        description="Get the current time in various formats",
        connection_type=MCPConnectionType.STDIO,
        command="python3",
        args=[os.path.join(MCP_SERVERS_DIR, "time_server.py")],
        timeout=5,
        tool_filter=None,  # All tools
    ),
    MCPServerConfig(
        name="filesystem",
        description="Read and write files on the local filesystem",
        connection_type=MCPConnectionType.STDIO,
        command="npx",
        args=["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
        tool_filter=["read_file", "write_file", "list_directory", "create_directory", 
                     "move_file", "search_files", "get_file_info"],
    ),
    MCPServerConfig(
        name="github",
        description="Interact with GitHub repositories",
        connection_type=MCPConnectionType.STDIO,
        command="npx",
        args=["-y", "@modelcontextprotocol/server-github"],
        env={"GITHUB_PERSONAL_ACCESS_TOKEN": ""},
        tool_filter=["create_or_update_file", "search_repositories", "create_repository",
                     "get_file_contents", "push_files", "create_issue", "create_pull_request",
                     "fork_repository", "create_branch", "list_commits", "list_issues"],
    ),
    MCPServerConfig(
        name="notion",
        description="Read and write Notion pages and databases",
        connection_type=MCPConnectionType.STDIO,
        command="npx",
        args=["-y", "@notionhq/notion-mcp-server"],
        env={"OPENAPI_MCP_HEADERS": '{"Authorization": "Bearer YOUR_TOKEN", "Notion-Version": "2022-06-28"}'},
        tool_filter=["notion_retrieve_page", "notion_query_database", "notion_create_page",
                     "notion_update_page", "notion_search", "notion_create_database",
                     "notion_retrieve_comments", "notion_add_comment"],
    ),
    MCPServerConfig(
        name="kubernetes",
        description="Interact with Kubernetes clusters",
        connection_type=MCPConnectionType.STDIO,
        command="npx",
        args=["-y", "@anthropics/mcp-kubernetes"],
        tool_filter=["kubectl", "get_pods", "get_logs", "describe_resource", "get_events",
                     "get_namespaces", "get_deployments", "get_services"],
    ),
    MCPServerConfig(
        name="slack",
        description="Send messages and interact with Slack",
        connection_type=MCPConnectionType.STDIO,
        command="npx",
        args=["-y", "@modelcontextprotocol/server-slack"],
        env={"SLACK_BOT_TOKEN": "", "SLACK_TEAM_ID": ""},
        tool_filter=["slack_post_message", "slack_reply_to_thread", "slack_add_reaction",
                     "slack_get_channel_history", "slack_get_thread_replies",
                     "slack_list_channels", "slack_get_users"],
    ),
    MCPServerConfig(
        name="puppeteer",
        description="Browser automation and web scraping",
        connection_type=MCPConnectionType.STDIO,
        command="npx",
        args=["-y", "@modelcontextprotocol/server-puppeteer"],
        tool_filter=["puppeteer_navigate", "puppeteer_screenshot", "puppeteer_click",
                     "puppeteer_fill", "puppeteer_select", "puppeteer_hover",
                     "puppeteer_evaluate"],
    ),
    MCPServerConfig(
        name="postgres",
        description="Query PostgreSQL databases",
        connection_type=MCPConnectionType.STDIO,
        command="npx",
        args=["-y", "@modelcontextprotocol/server-postgres"],
        env={"POSTGRES_CONNECTION_STRING": ""},
        tool_filter=["query", "list_tables", "describe_table"],
    ),
    MCPServerConfig(
        name="sqlite",
        description="Query SQLite databases",
        connection_type=MCPConnectionType.STDIO,
        command="npx",
        args=["-y", "@modelcontextprotocol/server-sqlite", "--db-path", "/tmp/db.sqlite"],
        tool_filter=["read_query", "write_query", "create_table", "list_tables", 
                     "describe_table", "append_insight"],
    ),
    MCPServerConfig(
        name="brave-search",
        description="Search the web using Brave Search",
        connection_type=MCPConnectionType.STDIO,
        command="npx",
        args=["-y", "@anthropics/mcp-brave-search"],
        env={"BRAVE_API_KEY": ""},
        tool_filter=["brave_web_search", "brave_local_search"],
    ),
    MCPServerConfig(
        name="google-maps",
        description="Search for places and get directions",
        connection_type=MCPConnectionType.STDIO,
        command="npx",
        args=["-y", "@anthropics/mcp-google-maps"],
        env={"GOOGLE_MAPS_API_KEY": ""},
        tool_filter=["maps_geocode", "maps_reverse_geocode", "maps_search_places",
                     "maps_place_details", "maps_distance_matrix", "maps_directions",
                     "maps_elevation"],
    ),
]

# Load user-defined MCP servers from mcp.json file
_USER_MCP_SERVERS = load_mcp_servers_from_file()

# Combine built-in and user-defined servers
# User-defined servers take precedence if there's a name conflict
KNOWN_MCP_SERVERS = _BUILTIN_MCP_SERVERS.copy()
_user_server_names = {s.name for s in _USER_MCP_SERVERS}
# Remove built-in servers that are overridden by user config
KNOWN_MCP_SERVERS = [s for s in KNOWN_MCP_SERVERS if s.name not in _user_server_names]
# Add user-defined servers
KNOWN_MCP_SERVERS.extend(_USER_MCP_SERVERS)

BUILTIN_TOOLS = [
    {"name": "google_search", "description": "Search Google for information"},
    {"name": "exit_loop", "description": "Exit a LoopAgent loop"},
    {"name": "load_memory", "description": "Load memories from the memory service"},
    {"name": "load_artifacts", "description": "Load artifacts from the artifact service"},
    {"name": "preload_memory", "description": "Preload memory into context"},
    {"name": "transfer_to_agent", "description": "Transfer control to another agent"},
    {"name": "url_context", "description": "Fetch and include URL content"},
    {"name": "skillset", "description": "SkillSet: Search knowledge base and preload relevant context"},
]

