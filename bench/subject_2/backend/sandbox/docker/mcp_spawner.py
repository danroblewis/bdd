"""MCP server spawner for stdio-based MCP servers.

This module runs inside the agent container and spawns MCP servers
as subprocesses. All subprocesses inherit the HTTP_PROXY environment
variables, ensuring their network traffic goes through the gateway.

Based on DOCKER_PLAN.md specification.
"""

import asyncio
import logging
import os
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class MCPServerProcess:
    """A running MCP server process."""
    name: str
    command: List[str]
    process: Optional[subprocess.Popen] = None
    env: Dict[str, str] = field(default_factory=dict)
    status: str = "stopped"  # stopped, starting, running, error
    error: Optional[str] = None


class MCPSpawner:
    """Spawns and manages MCP server subprocesses."""
    
    def __init__(self):
        self.servers: Dict[str, MCPServerProcess] = {}
    
    def spawn_mcp_server(
        self,
        name: str,
        command: List[str],
        env: Optional[Dict[str, str]] = None,
    ) -> MCPServerProcess:
        """Spawn an MCP server as a subprocess with proxy enforced.
        
        Args:
            name: Name of the MCP server (for tracking)
            command: Command to run (e.g., ["python", "-m", "mcp_server_time"])
            env: Additional environment variables
        
        Returns:
            The MCPServerProcess object
        """
        # Merge proxy settings into environment
        full_env = {
            **os.environ,  # Inherits HTTP_PROXY, HTTPS_PROXY from container
            **(env or {}),
        }
        
        # Add source header for tracking in the proxy
        full_env["MCP_SERVER_NAME"] = name
        
        server = MCPServerProcess(
            name=name,
            command=command,
            env=full_env,
            status="starting",
        )
        
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=full_env,
            )
            server.process = process
            server.status = "running"
            logger.info(f"Started MCP server '{name}' with PID {process.pid}")
        except Exception as e:
            server.status = "error"
            server.error = str(e)
            logger.error(f"Failed to start MCP server '{name}': {e}")
        
        self.servers[name] = server
        return server
    
    def stop_mcp_server(self, name: str) -> bool:
        """Stop an MCP server.
        
        Args:
            name: Name of the server to stop
        
        Returns:
            True if stopped successfully
        """
        if name not in self.servers:
            return False
        
        server = self.servers[name]
        if server.process:
            try:
                server.process.terminate()
                server.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.process.kill()
            except Exception as e:
                logger.error(f"Error stopping MCP server '{name}': {e}")
                return False
        
        server.status = "stopped"
        logger.info(f"Stopped MCP server '{name}'")
        return True
    
    def stop_all(self):
        """Stop all MCP servers."""
        for name in list(self.servers.keys()):
            self.stop_mcp_server(name)
    
    def get_status(self, name: str) -> Optional[Dict[str, Any]]:
        """Get status of an MCP server."""
        if name not in self.servers:
            return None
        
        server = self.servers[name]
        
        # Check if process is still running
        if server.process and server.status == "running":
            poll = server.process.poll()
            if poll is not None:
                server.status = "stopped" if poll == 0 else "error"
                if poll != 0:
                    server.error = f"Process exited with code {poll}"
        
        return {
            "name": server.name,
            "command": server.command,
            "status": server.status,
            "pid": server.process.pid if server.process else None,
            "error": server.error,
        }
    
    def get_all_status(self) -> List[Dict[str, Any]]:
        """Get status of all MCP servers."""
        return [self.get_status(name) for name in self.servers]
    
    async def read_stdout(self, name: str) -> Optional[bytes]:
        """Read from server's stdout (for stdio transport)."""
        if name not in self.servers:
            return None
        
        server = self.servers[name]
        if not server.process or not server.process.stdout:
            return None
        
        # Non-blocking read
        try:
            return server.process.stdout.read1(4096)
        except Exception:
            return None
    
    async def write_stdin(self, name: str, data: bytes) -> bool:
        """Write to server's stdin (for stdio transport)."""
        if name not in self.servers:
            return False
        
        server = self.servers[name]
        if not server.process or not server.process.stdin:
            return False
        
        try:
            server.process.stdin.write(data)
            server.process.stdin.flush()
            return True
        except Exception as e:
            logger.error(f"Error writing to MCP server '{name}': {e}")
            return False


# Global spawner instance
spawner = MCPSpawner()


# Convenience functions for use from agent_runner.py
def spawn_server(name: str, command: List[str], env: Optional[Dict[str, str]] = None):
    """Spawn an MCP server."""
    return spawner.spawn_mcp_server(name, command, env)


def stop_server(name: str):
    """Stop an MCP server."""
    return spawner.stop_mcp_server(name)


def stop_all_servers():
    """Stop all MCP servers."""
    spawner.stop_all()


def get_server_status(name: str):
    """Get status of an MCP server."""
    return spawner.get_status(name)


def get_all_server_status():
    """Get status of all MCP servers."""
    return spawner.get_all_status()


