"""Acceptance tests for task 208 - MCP server health check endpoint."""
from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Add backend to path
backend_dir = Path(__file__).parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))


class TestMCPHealthCheckEndpoint:
    """Tests for POST /api/mcp/health-check endpoint."""

    def test_endpoint_exists(self):
        """The /api/mcp/health-check endpoint must be registered."""
        from main import app

        routes = [r.path for r in app.routes]
        assert "/api/mcp/health-check" in routes, (
            f"POST /api/mcp/health-check route must exist. "
            f"Available routes: {routes}"
        )

    def test_healthy_server_returns_success(self):
        """When MCP server connects and returns tools, response should be healthy."""
        from main import app

        from fastapi.testclient import TestClient

        # Create mock tools
        mock_tool_1 = MagicMock()
        mock_tool_1.name = "tool_a"
        mock_tool_2 = MagicMock()
        mock_tool_2.name = "tool_b"
        mock_tool_3 = MagicMock()
        mock_tool_3.name = "tool_c"
        mock_tools = [mock_tool_1, mock_tool_2, mock_tool_3]

        with patch("main.mcp_pool") as mock_pool:
            # Mock get_tools to return our mock tools
            mock_pool.get_tools = AsyncMock(return_value=mock_tools)
            # Also mock get_toolset in case implementation uses that instead
            mock_toolset = MagicMock()
            mock_toolset.get_tools = AsyncMock(return_value=mock_tools)
            mock_pool.get_toolset = AsyncMock(return_value=mock_toolset)

            client = TestClient(app)
            resp = client.post(
                "/api/mcp/health-check",
                json={
                    "command": "echo",
                    "args": ["hello"],
                    "type": "stdio",
                },
            )

        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}: {resp.text}"
        )
        data = resp.json()
        assert data["healthy"] is True, f"Expected healthy=True, got {data}"
        assert data["tools_count"] == 3, (
            f"Expected tools_count=3, got {data['tools_count']}"
        )
        assert data["latency_ms"] >= 0, (
            f"Expected latency_ms >= 0, got {data['latency_ms']}"
        )

    def test_unhealthy_server_returns_error(self):
        """When MCP server connection fails, response should indicate unhealthy."""
        from main import app

        from fastapi.testclient import TestClient

        with patch("main.mcp_pool") as mock_pool:
            # Mock get_tools to raise an exception
            mock_pool.get_tools = AsyncMock(
                side_effect=Exception("Connection refused")
            )
            mock_pool.get_toolset = AsyncMock(
                side_effect=Exception("Connection refused")
            )

            client = TestClient(app)
            resp = client.post(
                "/api/mcp/health-check",
                json={
                    "command": "nonexistent_server",
                    "args": [],
                    "type": "stdio",
                },
            )

        assert resp.status_code == 200, (
            f"Expected 200 even for unhealthy server, got {resp.status_code}: {resp.text}"
        )
        data = resp.json()
        assert data["healthy"] is False, f"Expected healthy=False, got {data}"
        assert data["error"] is not None, (
            f"Expected error message for unhealthy server, got {data}"
        )
        assert len(data["error"]) > 0, "Error message should not be empty"

    def test_response_has_all_required_fields(self):
        """Response must always contain all 4 required fields."""
        from main import app

        from fastapi.testclient import TestClient

        # Test with a healthy server scenario
        with patch("main.mcp_pool") as mock_pool:
            mock_pool.get_tools = AsyncMock(return_value=[])
            mock_toolset = MagicMock()
            mock_toolset.get_tools = AsyncMock(return_value=[])
            mock_pool.get_toolset = AsyncMock(return_value=mock_toolset)

            client = TestClient(app)
            resp = client.post(
                "/api/mcp/health-check",
                json={
                    "command": "echo",
                    "args": [],
                    "type": "stdio",
                },
            )

        assert resp.status_code == 200
        data = resp.json()

        required_fields = ["healthy", "tools_count", "error", "latency_ms"]
        for field in required_fields:
            assert field in data, (
                f"Response missing required field '{field}'. "
                f"Got keys: {list(data.keys())}"
            )

        # Verify types
        assert isinstance(data["healthy"], bool), (
            f"healthy must be bool, got {type(data['healthy'])}"
        )
        assert isinstance(data["tools_count"], int), (
            f"tools_count must be int, got {type(data['tools_count'])}"
        )
        assert data["error"] is None or isinstance(data["error"], str), (
            f"error must be str or null, got {type(data['error'])}"
        )
        assert isinstance(data["latency_ms"], (int, float)), (
            f"latency_ms must be numeric, got {type(data['latency_ms'])}"
        )

    def test_latency_is_positive_for_healthy_server(self):
        """latency_ms should be a positive number for a successful health check."""
        from main import app

        from fastapi.testclient import TestClient

        mock_tool = MagicMock()
        mock_tool.name = "some_tool"

        with patch("main.mcp_pool") as mock_pool:
            mock_pool.get_tools = AsyncMock(return_value=[mock_tool])
            mock_toolset = MagicMock()
            mock_toolset.get_tools = AsyncMock(return_value=[mock_tool])
            mock_pool.get_toolset = AsyncMock(return_value=mock_toolset)

            client = TestClient(app)
            resp = client.post(
                "/api/mcp/health-check",
                json={
                    "url": "http://localhost:9999/sse",
                    "type": "sse",
                },
            )

        data = resp.json()
        assert data["healthy"] is True
        assert data["latency_ms"] > 0, (
            f"latency_ms should be positive, got {data['latency_ms']}"
        )
