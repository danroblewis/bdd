"""Acceptance tests for task 206 - code generation dry-run validation."""
from __future__ import annotations

import sys
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
    AgentToolConfig,
    FunctionToolConfig,
)


def _make_valid_project() -> Project:
    """Create a project that should pass validation."""
    return Project(
        id="valid_proj",
        name="Valid Project",
        app=AppConfig(
            id="app_valid",
            name="Valid App",
            root_agent_id="agent_1",
            session_service_uri="memory://",
            memory_service_uri="memory://",
            artifact_service_uri="memory://",
        ),
        agents=[
            LlmAgentConfig(
                id="agent_1",
                name="valid_agent",
                instruction="You are a helpful assistant.",
                model=ModelConfig(provider="gemini", model_name="gemini-2.0-flash"),
            ),
        ],
    )


def _make_project_no_instruction() -> Project:
    """Create a project where an agent has no instruction (should warn)."""
    return Project(
        id="no_instr_proj",
        name="No Instruction Project",
        app=AppConfig(
            id="app_noinstr",
            name="No Instruction App",
            root_agent_id="agent_1",
            session_service_uri="memory://",
            memory_service_uri="memory://",
            artifact_service_uri="memory://",
        ),
        agents=[
            LlmAgentConfig(
                id="agent_1",
                name="empty_instruction_agent",
                instruction="",  # Empty instruction
                model=ModelConfig(provider="gemini", model_name="gemini-2.0-flash"),
            ),
        ],
    )


def _make_project_no_model() -> Project:
    """Create a project where an agent has no model config (should warn)."""
    return Project(
        id="no_model_proj",
        name="No Model Project",
        app=AppConfig(
            id="app_nomodel",
            name="No Model App",
            root_agent_id="agent_1",
            session_service_uri="memory://",
            memory_service_uri="memory://",
            artifact_service_uri="memory://",
        ),
        agents=[
            LlmAgentConfig(
                id="agent_1",
                name="no_model_agent",
                instruction="You are helpful.",
                model=None,  # No model
            ),
        ],
    )


class TestValidateGeneratedCodeFunction:
    """Tests for validate_generated_code function."""

    def test_function_exists(self):
        """validate_generated_code must exist in code_generator."""
        from code_generator import validate_generated_code
        assert callable(validate_generated_code)

    def test_valid_project_returns_valid(self):
        """A valid project should return valid=True."""
        from code_generator import validate_generated_code

        project = _make_valid_project()
        result = validate_generated_code(project)

        assert isinstance(result, dict), f"Expected dict, got {type(result)}"
        assert "valid" in result, "Result must have 'valid' key"
        assert "errors" in result, "Result must have 'errors' key"
        assert "warnings" in result, "Result must have 'warnings' key"
        assert result["valid"] is True, f"Valid project should return valid=True, got {result}"
        assert isinstance(result["errors"], list), "errors must be a list"
        assert isinstance(result["warnings"], list), "warnings must be a list"
        assert len(result["errors"]) == 0, (
            f"Valid project should have no errors, got: {result['errors']}"
        )

    def test_no_instruction_gives_warning(self):
        """An agent with no instruction should produce a warning."""
        from code_generator import validate_generated_code

        project = _make_project_no_instruction()
        result = validate_generated_code(project)

        assert isinstance(result, dict)
        assert "warnings" in result
        # Should have at least one warning about missing/empty instruction
        warning_text = " ".join(result["warnings"]).lower()
        assert "instruction" in warning_text or len(result["warnings"]) > 0, (
            f"Should warn about empty instruction, got warnings: {result['warnings']}"
        )

    def test_no_model_gives_warning(self):
        """An agent with no model config should produce a warning."""
        from code_generator import validate_generated_code

        project = _make_project_no_model()
        result = validate_generated_code(project)

        assert isinstance(result, dict)
        assert "warnings" in result
        # Should have at least one warning about missing model
        warning_text = " ".join(result["warnings"]).lower()
        assert "model" in warning_text or len(result["warnings"]) > 0, (
            f"Should warn about missing model, got warnings: {result['warnings']}"
        )

    def test_compilation_check(self):
        """The function should use compile() to check generated code syntax."""
        from code_generator import validate_generated_code

        project = _make_valid_project()
        result = validate_generated_code(project)

        # For a valid project, the code should compile without errors
        assert result["valid"] is True
        assert len(result["errors"]) == 0


class TestValidateEndpoint:
    """Tests for POST /api/projects/{project_id}/validate endpoint."""

    def test_endpoint_exists(self):
        """POST /api/projects/{project_id}/validate must be registered."""
        from main import app

        routes = [r.path for r in app.routes]
        assert "/api/projects/{project_id}/validate" in routes, (
            f"POST /api/projects/{project_id}/validate route must exist. "
            f"Available routes: {routes}"
        )

    def test_validate_endpoint_returns_result(self):
        """The validate endpoint should return validation results."""
        from main import app, project_manager as pm

        from fastapi.testclient import TestClient

        project = _make_valid_project()
        pm.save_project(project)

        try:
            client = TestClient(app)
            resp = client.post(f"/api/projects/{project.id}/validate")
            assert resp.status_code == 200, (
                f"Expected 200, got {resp.status_code}: {resp.text}"
            )
            data = resp.json()
            assert "valid" in data, f"Response must contain 'valid' field: {data}"
            assert "errors" in data, f"Response must contain 'errors' field: {data}"
            assert "warnings" in data, f"Response must contain 'warnings' field: {data}"
        finally:
            pm.delete_project(project.id)

    def test_validate_endpoint_404_for_missing(self):
        """Validate endpoint should return 404 for missing project."""
        from main import app

        from fastapi.testclient import TestClient

        client = TestClient(app)
        resp = client.post("/api/projects/nonexistent_validate/validate")
        assert resp.status_code in (404, 400), (
            f"Expected error status, got {resp.status_code}"
        )
