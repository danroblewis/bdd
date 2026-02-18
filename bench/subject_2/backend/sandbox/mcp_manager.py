"""MCP server container manager.

This module manages MCP server containers for the sandbox:
- SSE-based MCP servers run as separate containers
- Stdio-based MCP servers run as subprocesses in the agent container

Based on DOCKER_PLAN.md specification.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from .models import MCPContainerStatus, MCPServerSandboxConfig

logger = logging.getLogger(__name__)

# Check if docker is available
try:
    import docker
    from docker.errors import DockerException, NotFound
    DOCKER_AVAILABLE = True
except ImportError:
    DOCKER_AVAILABLE = False
    docker = None
    DockerException = Exception
    NotFound = Exception


# Known MCP servers and their network requirements
# This helps auto-populate allowlist entries
KNOWN_MCP_SERVERS: Dict[str, Dict[str, Any]] = {
    "filesystem": {
        "transport": "stdio",
        "network_access": False,
        "allowed_domains": [],
        "risk_level": "low",
    },
    "time": {
        "transport": "stdio",
        "network_access": False,
        "allowed_domains": [],
        "risk_level": "low",
    },
    "sqlite": {
        "transport": "stdio",
        "network_access": False,
        "allowed_domains": [],
        "risk_level": "low",
    },
    "memory": {
        "transport": "stdio",
        "network_access": False,
        "allowed_domains": [],
        "risk_level": "low",
    },
    "github": {
        "transport": "stdio",
        "network_access": True,
        "allowed_domains": ["api.github.com", "github.com"],
        "risk_level": "medium",
    },
    "gitlab": {
        "transport": "stdio",
        "network_access": True,
        "allowed_domains": ["gitlab.com", "*.gitlab.com"],
        "risk_level": "medium",
    },
    "slack": {
        "transport": "stdio",
        "network_access": True,
        "allowed_domains": ["slack.com", "api.slack.com"],
        "risk_level": "medium",
    },
    "google-drive": {
        "transport": "stdio",
        "network_access": True,
        "allowed_domains": ["*.googleapis.com"],
        "risk_level": "medium",
    },
    "brave-search": {
        "transport": "stdio",
        "network_access": True,
        "allowed_domains": ["api.search.brave.com"],
        "risk_level": "medium",
    },
    "fetch": {
        "transport": "stdio",
        "network_access": True,
        "allowed_domains": [],  # Can access any URL
        "risk_level": "high",
    },
    "puppeteer": {
        "transport": "stdio",
        "network_access": True,
        "allowed_domains": [],  # Can access any URL
        "risk_level": "high",
    },
    "browserbase": {
        "transport": "stdio",
        "network_access": True,
        "allowed_domains": [],  # Can access any URL
        "risk_level": "high",
    },
}


class MCPContainerManager:
    """Manages MCP server containers in the sandbox."""
    
    MCP_BASE_IMAGE = "adk-sandbox-mcp"
    
    def __init__(self, client=None):
        """Initialize the MCP container manager.
        
        Args:
            client: Optional Docker client (uses global if not provided)
        """
        self.client = client
        self.containers: Dict[str, MCPContainerStatus] = {}
    
    def get_mcp_server_info(self, server_name: str) -> Optional[Dict[str, Any]]:
        """Get info about a known MCP server.
        
        Args:
            server_name: Name of the MCP server (e.g., "github", "fetch")
        
        Returns:
            Server info dict or None if unknown
        """
        # Normalize name
        name = server_name.lower().replace("mcp-server-", "").replace("_", "-")
        return KNOWN_MCP_SERVERS.get(name)
    
    def get_allowed_domains_for_mcp(
        self,
        mcp_configs: List[MCPServerSandboxConfig],
    ) -> List[str]:
        """Get all allowed domains for a list of MCP servers.
        
        Args:
            mcp_configs: List of MCP server configurations
        
        Returns:
            List of domains that should be auto-allowed
        """
        domains = []
        for config in mcp_configs:
            # Check known servers
            info = self.get_mcp_server_info(config.name)
            if info:
                domains.extend(info.get("allowed_domains", []))
            # Also add explicitly configured domains
            domains.extend(config.allowed_domains)
        return list(set(domains))
    
    def is_high_risk_mcp(self, server_name: str) -> bool:
        """Check if an MCP server is high risk (can access any URL).
        
        Args:
            server_name: Name of the MCP server
        
        Returns:
            True if the server can access arbitrary URLs
        """
        info = self.get_mcp_server_info(server_name)
        if info:
            return info.get("risk_level") == "high"
        # Unknown servers are considered high risk
        return True
    
    def parse_mcp_configs_from_project(
        self,
        project_config: Dict[str, Any],
    ) -> List[MCPServerSandboxConfig]:
        """Parse MCP server configurations from project config.
        
        Args:
            project_config: Full project configuration dict
        
        Returns:
            List of MCP server sandbox configurations
        """
        configs = []
        
        # Get MCP servers from project
        mcp_servers = project_config.get("mcp_servers", [])
        
        for server in mcp_servers:
            name = server.get("name", "unknown")
            connection_type = server.get("connection_type", "stdio")
            
            # Get known server info
            info = self.get_mcp_server_info(name)
            
            config = MCPServerSandboxConfig(
                name=name,
                transport=connection_type,
                command=server.get("command"),
                args=server.get("args", []),
                env=server.get("env", {}),
                allowed_domains=info.get("allowed_domains", []) if info else [],
            )
            configs.append(config)
        
        # Also check agents for MCP tools
        for agent in project_config.get("agents", []):
            for tool in agent.get("tools", []):
                if tool.get("type") == "mcp":
                    server = tool.get("server", {})
                    name = server.get("name", "unknown")
                    
                    # Skip if already added
                    if any(c.name == name for c in configs):
                        continue
                    
                    info = self.get_mcp_server_info(name)
                    
                    config = MCPServerSandboxConfig(
                        name=name,
                        transport=server.get("connection_type", "stdio"),
                        command=server.get("command"),
                        args=server.get("args", []),
                        env=server.get("env", {}),
                        allowed_domains=info.get("allowed_domains", []) if info else [],
                    )
                    configs.append(config)
        
        return configs
    
    async def start_sse_container(
        self,
        config: MCPServerSandboxConfig,
        network_name: str,
        session_id: str,
    ) -> MCPContainerStatus:
        """Start an SSE MCP server container.
        
        Args:
            config: MCP server configuration
            network_name: Docker network to join
            session_id: Session ID for naming
        
        Returns:
            Container status
        """
        if not DOCKER_AVAILABLE or not self.client:
            return MCPContainerStatus(
                name=config.name,
                status="error",
                transport="sse",
                error="Docker not available",
            )
        
        status = MCPContainerStatus(
            name=config.name,
            status="starting",
            transport="sse",
        )
        self.containers[config.name] = status
        
        try:
            # Build command
            command = []
            if config.command:
                command = [config.command] + config.args
            
            # Environment with proxy settings
            env = {
                "HTTP_PROXY": "http://gateway:8080",
                "HTTPS_PROXY": "http://gateway:8080",
                "NO_PROXY": "localhost,127.0.0.1,gateway,agent-runner",
                "MCP_SERVER_NAME": config.name,
                **config.env,
            }
            
            # Start container
            container = self.client.containers.run(
                image=self.MCP_BASE_IMAGE,
                name=f"mcp-{config.name}-{session_id}",
                command=command if command else None,
                detach=True,
                network=network_name,
                environment=env,
                mem_limit=f"{config.memory_limit_mb}m",
                cpu_period=100000,
                cpu_quota=int(config.cpu_limit * 100000),
            )
            
            status.container_id = container.id
            status.status = "running"
            status.endpoint = f"http://mcp-{config.name}:8080"
            
            logger.info(f"Started MCP container {config.name}: {container.id[:12]}")
            
        except Exception as e:
            status.status = "error"
            status.error = str(e)
            logger.error(f"Failed to start MCP container {config.name}: {e}")
        
        return status
    
    async def stop_container(self, name: str) -> bool:
        """Stop an MCP server container.
        
        Args:
            name: MCP server name
        
        Returns:
            True if stopped successfully
        """
        if name not in self.containers:
            return False
        
        status = self.containers[name]
        if not status.container_id or not self.client:
            return False
        
        try:
            container = self.client.containers.get(status.container_id)
            container.stop(timeout=5)
            container.remove()
            status.status = "stopped"
            del self.containers[name]
            logger.info(f"Stopped MCP container {name}")
            return True
        except NotFound:
            del self.containers[name]
            return True
        except Exception as e:
            logger.error(f"Error stopping MCP container {name}: {e}")
            return False
    
    async def stop_all(self):
        """Stop all MCP server containers."""
        for name in list(self.containers.keys()):
            await self.stop_container(name)
    
    def get_status(self, name: str) -> Optional[MCPContainerStatus]:
        """Get status of an MCP server container."""
        return self.containers.get(name)
    
    def get_all_status(self) -> List[MCPContainerStatus]:
        """Get status of all MCP server containers."""
        return list(self.containers.values())
    
    def get_stdio_config_for_agent(
        self,
        mcp_configs: List[MCPServerSandboxConfig],
    ) -> Dict[str, Any]:
        """Get MCP configuration to send to the agent container.
        
        Stdio MCP servers are spawned inside the agent container,
        so we need to tell it which servers to start.
        
        Args:
            mcp_configs: List of MCP server configurations
        
        Returns:
            Configuration dict for the agent container
        """
        stdio_servers = []
        for config in mcp_configs:
            if config.transport == "stdio":
                stdio_servers.append({
                    "name": config.name,
                    "command": config.command,
                    "args": config.args,
                    "env": config.env,
                })
        
        return {"stdio_mcp_servers": stdio_servers}


