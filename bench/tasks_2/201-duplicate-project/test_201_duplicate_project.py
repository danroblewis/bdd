"""Acceptance tests for task 201 - project duplication."""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Add backend to path
backend_dir = Path(__file__).parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from models import (
    Project,
    AppConfig,
    LlmAgentConfig,
    ModelConfig,
    CustomToolDefinition,
    FunctionToolConfig,
)
from project_manager import ProjectManager


def _make_project(**overrides) -> Project:
    """Helper to create a test project with agents and tools."""
    defaults = dict(
        id="proj_orig",
        name="Original Project",
        description="An original project",
        app=AppConfig(
            id="app_orig",
            name="Original App",
            root_agent_id="agent_1",
            session_service_uri="memory://",
            memory_service_uri="memory://",
            artifact_service_uri="memory://",
        ),
        agents=[
            LlmAgentConfig(
                id="agent_1",
                name="main_agent",
                description="The main agent",
                instruction="You are a helpful assistant.",
                model=ModelConfig(provider="gemini", model_name="gemini-2.0-flash"),
                tools=[
                    FunctionToolConfig(
                        type="function",
                        name="my_tool",
                        description="A tool",
                        module_path="tools.my_module.my_tool",
                    ),
                ],
            ),
        ],
        custom_tools=[
            CustomToolDefinition(
                id="tool_1",
                name="my_tool",
                description="A custom tool",
                module_path="tools.my_module",
                code="def my_tool(): return 42",
            ),
        ],
    )
    defaults.update(overrides)
    return Project(**defaults)


class TestDuplicateProjectManager:
    """Tests for ProjectManager.duplicate_project method."""

    def test_duplicate_project_method_exists(self, tmp_path):
        """ProjectManager must have a duplicate_project method."""
        pm = ProjectManager(str(tmp_path))
        assert hasattr(pm, "duplicate_project"), (
            "ProjectManager must have a duplicate_project method"
        )
        assert callable(pm.duplicate_project)

    def test_duplicate_creates_new_id(self, tmp_path):
        """Duplicated project must have a different ID from the original."""
        pm = ProjectManager(str(tmp_path))
        original = _make_project()
        pm.save_project(original)

        dup = pm.duplicate_project("proj_orig", "Cloned Project")
        assert dup is not None, "duplicate_project should return a Project"
        assert dup.id != original.id, "Duplicated project must have a new ID"

    def test_duplicate_uses_new_name(self, tmp_path):
        """Duplicated project must use the new name provided."""
        pm = ProjectManager(str(tmp_path))
        original = _make_project()
        pm.save_project(original)

        dup = pm.duplicate_project("proj_orig", "My Clone")
        assert dup.name == "My Clone"

    def test_duplicate_preserves_agents(self, tmp_path):
        """Duplicated project must keep the same agent configurations."""
        pm = ProjectManager(str(tmp_path))
        original = _make_project()
        pm.save_project(original)

        dup = pm.duplicate_project("proj_orig", "Clone")
        assert len(dup.agents) == len(original.agents), (
            "Duplicated project must have the same number of agents"
        )
        # Check the agent details are preserved
        orig_agent = original.agents[0]
        dup_agent = dup.agents[0]
        assert dup_agent.name == orig_agent.name
        assert dup_agent.instruction == orig_agent.instruction

    def test_duplicate_preserves_custom_tools(self, tmp_path):
        """Duplicated project must keep the same custom tools."""
        pm = ProjectManager(str(tmp_path))
        original = _make_project()
        pm.save_project(original)

        dup = pm.duplicate_project("proj_orig", "Clone")
        assert len(dup.custom_tools) == len(original.custom_tools), (
            "Duplicated project must have the same number of custom tools"
        )
        assert dup.custom_tools[0].code == original.custom_tools[0].code

    def test_duplicate_is_persisted(self, tmp_path):
        """Duplicated project must be saved to disk."""
        pm = ProjectManager(str(tmp_path))
        original = _make_project()
        pm.save_project(original)

        dup = pm.duplicate_project("proj_orig", "Clone")
        # Should be loadable by ID
        loaded = pm.get_project(dup.id)
        assert loaded is not None, "Duplicated project must be persisted and loadable"
        assert loaded.name == "Clone"

    def test_duplicate_nonexistent_project(self, tmp_path):
        """Duplicating a non-existent project should return None or raise."""
        pm = ProjectManager(str(tmp_path))
        result = pm.duplicate_project("nonexistent_id", "Clone")
        assert result is None, (
            "duplicate_project should return None for non-existent project"
        )


class TestDuplicateProjectEndpoint:
    """Tests for the POST /api/projects/{project_id}/duplicate endpoint."""

    def test_duplicate_endpoint_exists(self):
        """The /duplicate endpoint must be registered on the FastAPI app."""
        from main import app

        routes = [r.path for r in app.routes]
        assert "/api/projects/{project_id}/duplicate" in routes, (
            "POST /api/projects/{project_id}/duplicate route must exist"
        )

    def test_duplicate_endpoint_returns_project(self, tmp_path):
        """The endpoint should return the duplicated project JSON."""
        from main import app, project_manager as pm

        from fastapi.testclient import TestClient

        # Patch the project_manager's projects_dir to use tmp_path
        original = _make_project()
        pm.save_project(original)

        client = TestClient(app)
        resp = client.post(
            f"/api/projects/{original.id}/duplicate",
            json={"name": "API Clone"},
        )
        assert resp.status_code == 200, f"Expected 200 but got {resp.status_code}: {resp.text}"
        data = resp.json()
        # The response should contain a project with the new name
        project_data = data.get("project", data)
        assert project_data.get("name") == "API Clone" or (
            "name" in project_data and project_data["name"] == "API Clone"
        ), f"Response project name should be 'API Clone', got: {project_data}"

    def test_duplicate_endpoint_404_for_missing(self):
        """The endpoint should return 404 for non-existent project."""
        from main import app

        from fastapi.testclient import TestClient

        client = TestClient(app)
        resp = client.post(
            "/api/projects/nonexistent_999/duplicate",
            json={"name": "Clone"},
        )
        assert resp.status_code in (404, 400, 422), (
            f"Expected error status for non-existent project, got {resp.status_code}"
        )
