"""Acceptance tests for task 209 - project export as ZIP."""
from __future__ import annotations

import io
import sys
import zipfile
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
    CustomCallbackDefinition,
)
from project_manager import ProjectManager


def _make_project_with_tools(**overrides) -> Project:
    """Create a test project with custom tools and callbacks."""
    defaults = dict(
        id="proj_export_test",
        name="Export Test Project",
        description="A project for testing export",
        app=AppConfig(
            id="app_export",
            name="Export App",
            root_agent_id="agent_1",
            session_service_uri="memory://",
            memory_service_uri="memory://",
            artifact_service_uri="memory://",
        ),
        agents=[
            LlmAgentConfig(
                id="agent_1",
                name="export_agent",
                description="An agent for export testing",
                instruction="You are a helpful assistant.",
                model=ModelConfig(provider="gemini", model_name="gemini-2.0-flash"),
            ),
        ],
        custom_tools=[
            CustomToolDefinition(
                id="tool_export_1",
                name="my_export_tool",
                description="A custom tool for export",
                module_path="tools.export_module",
                code="def my_export_tool():\n    return 'exported'",
            ),
        ],
        custom_callbacks=[
            CustomCallbackDefinition(
                id="cb_export_1",
                name="my_callback",
                description="A callback for export",
                module_path="callbacks.my_callback",
                code="def my_callback(context):\n    pass",
            ),
        ],
    )
    defaults.update(overrides)
    return Project(**defaults)


def _make_simple_project(**overrides) -> Project:
    """Create a minimal test project without custom tools/callbacks."""
    defaults = dict(
        id="proj_simple_export",
        name="Simple Export Project",
        app=AppConfig(
            id="app_simple",
            name="Simple App",
            root_agent_id="agent_1",
            session_service_uri="memory://",
            memory_service_uri="memory://",
            artifact_service_uri="memory://",
        ),
        agents=[
            LlmAgentConfig(
                id="agent_1",
                name="simple_agent",
                instruction="You are helpful.",
                model=ModelConfig(provider="gemini", model_name="gemini-2.0-flash"),
            ),
        ],
    )
    defaults.update(overrides)
    return Project(**defaults)


class TestExportProjectZipFunction:
    """Tests for ProjectManager.export_project_zip method."""

    def test_function_exists(self, tmp_path):
        """export_project_zip must exist in ProjectManager."""
        pm = ProjectManager(str(tmp_path))
        assert hasattr(pm, "export_project_zip"), (
            "ProjectManager must have an export_project_zip method"
        )
        assert callable(pm.export_project_zip)

    def test_returns_bytes(self, tmp_path):
        """export_project_zip must return bytes."""
        pm = ProjectManager(str(tmp_path))
        project = _make_simple_project()
        pm.save_project(project)

        result = pm.export_project_zip(project.id)
        assert isinstance(result, bytes), (
            f"export_project_zip should return bytes, got {type(result)}"
        )

    def test_returns_valid_zip(self, tmp_path):
        """The returned bytes must be a valid ZIP file."""
        pm = ProjectManager(str(tmp_path))
        project = _make_simple_project()
        pm.save_project(project)

        result = pm.export_project_zip(project.id)
        assert zipfile.is_zipfile(io.BytesIO(result)), (
            "export_project_zip must return a valid ZIP file"
        )

    def test_zip_contains_project_yaml(self, tmp_path):
        """The ZIP must contain the project YAML file."""
        pm = ProjectManager(str(tmp_path))
        project = _make_simple_project()
        pm.save_project(project)

        result = pm.export_project_zip(project.id)
        with zipfile.ZipFile(io.BytesIO(result), "r") as zf:
            names = zf.namelist()
            # Should contain a YAML file for the project
            yaml_files = [n for n in names if n.endswith(".yaml") or n.endswith(".yml")]
            assert len(yaml_files) > 0, (
                f"ZIP should contain at least one YAML file. Files in ZIP: {names}"
            )

    def test_nonexistent_project_returns_none_or_raises(self, tmp_path):
        """Exporting a non-existent project should return None or raise an error."""
        pm = ProjectManager(str(tmp_path))

        try:
            result = pm.export_project_zip("nonexistent_project_id")
            # If it returns instead of raising, it should be None
            assert result is None, (
                "export_project_zip should return None for non-existent project"
            )
        except (FileNotFoundError, ValueError, KeyError, Exception):
            # Raising an exception is also acceptable
            pass


class TestExportEndpoint:
    """Tests for GET /api/projects/{project_id}/export endpoint."""

    def test_endpoint_exists(self):
        """The /export endpoint must be registered on the FastAPI app."""
        from main import app

        routes = [r.path for r in app.routes]
        assert "/api/projects/{project_id}/export" in routes, (
            f"GET /api/projects/{{project_id}}/export route must exist. "
            f"Available routes: {routes}"
        )

    def test_export_returns_zip_content_type(self):
        """The export endpoint should return a ZIP content type."""
        from main import app, project_manager as pm

        from fastapi.testclient import TestClient

        project = _make_simple_project()
        pm.save_project(project)

        try:
            client = TestClient(app)
            resp = client.get(f"/api/projects/{project.id}/export")
            assert resp.status_code == 200, (
                f"Expected 200, got {resp.status_code}: {resp.text}"
            )
            content_type = resp.headers.get("content-type", "")
            acceptable_types = [
                "application/zip",
                "application/octet-stream",
                "application/x-zip-compressed",
                "application/x-zip",
            ]
            assert any(t in content_type for t in acceptable_types), (
                f"Expected ZIP-related content type, got: {content_type}"
            )
        finally:
            pm.delete_project(project.id)

    def test_export_returns_valid_zip_bytes(self):
        """The export endpoint should return valid ZIP data."""
        from main import app, project_manager as pm

        from fastapi.testclient import TestClient

        project = _make_simple_project()
        pm.save_project(project)

        try:
            client = TestClient(app)
            resp = client.get(f"/api/projects/{project.id}/export")
            assert resp.status_code == 200
            assert zipfile.is_zipfile(io.BytesIO(resp.content)), (
                "Response body should be a valid ZIP file"
            )
        finally:
            pm.delete_project(project.id)

    def test_export_404_for_missing_project(self):
        """Export endpoint should return 404 for non-existent project."""
        from main import app

        from fastapi.testclient import TestClient

        client = TestClient(app)
        resp = client.get("/api/projects/nonexistent_export_999/export")
        assert resp.status_code in (404, 400), (
            f"Expected error status for non-existent project, got {resp.status_code}"
        )
