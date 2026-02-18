"""Acceptance tests for task 204 - project tags support."""
from __future__ import annotations

import sys
import yaml
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Add backend to path
backend_dir = Path(__file__).parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from models import Project, AppConfig, LlmAgentConfig, ModelConfig
from project_manager import ProjectManager


def _make_project(pid: str = "tag_proj", name: str = "Tag Project", **overrides) -> Project:
    defaults = dict(
        id=pid,
        name=name,
        app=AppConfig(
            id=f"app_{pid}",
            name=name,
            root_agent_id="agent_1",
            session_service_uri="memory://",
            memory_service_uri="memory://",
            artifact_service_uri="memory://",
        ),
        agents=[
            LlmAgentConfig(
                id="agent_1",
                name="agent",
                instruction="Test",
                model=ModelConfig(provider="gemini", model_name="gemini-2.0-flash"),
            ),
        ],
    )
    defaults.update(overrides)
    return Project(**defaults)


class TestProjectModelTags:
    """Tests that the Project model has a tags field."""

    def test_project_has_tags_field(self):
        """Project model must have a tags field."""
        p = _make_project()
        assert hasattr(p, "tags"), "Project model must have a 'tags' field"

    def test_tags_default_empty_list(self):
        """tags should default to an empty list."""
        p = _make_project()
        assert p.tags == [], f"Default tags should be [], got {p.tags}"

    def test_tags_can_be_set(self):
        """tags can be set to a list of strings."""
        p = _make_project(tags=["alpha", "beta"])
        assert p.tags == ["alpha", "beta"]

    def test_tags_serialized_to_dict(self):
        """tags should appear in model_dump output."""
        p = _make_project(tags=["production", "v2"])
        data = p.model_dump(mode="json")
        assert "tags" in data, "tags must be in serialized output"
        assert data["tags"] == ["production", "v2"]


class TestTagsPersistInYaml:
    """Tests that tags are persisted in the project YAML file."""

    def test_tags_saved_to_yaml(self, tmp_path):
        """Saving a project with tags should persist them in the YAML file."""
        pm = ProjectManager(str(tmp_path))
        p = _make_project(tags=["important", "test"])
        pm.save_project(p)

        # Read the YAML file directly
        yaml_path = tmp_path / f"{p.id}.yaml"
        assert yaml_path.exists(), "Project YAML file should exist"
        with open(yaml_path) as f:
            data = yaml.safe_load(f)
        assert "tags" in data, "tags must be in YAML"
        assert data["tags"] == ["important", "test"]

    def test_tags_loaded_from_yaml(self, tmp_path):
        """Loading a project should restore its tags."""
        pm = ProjectManager(str(tmp_path))
        p = _make_project(tags=["restored_tag"])
        pm.save_project(p)

        # Clear cache and reload
        pm._cache.clear()
        loaded = pm.get_project(p.id)
        assert loaded is not None
        assert loaded.tags == ["restored_tag"]


class TestTagFilterEndpoint:
    """Tests for GET /api/projects?tag=TAG filtering."""

    def test_list_projects_with_tag_filter(self):
        """GET /api/projects?tag=TAG should filter results."""
        from main import app

        from fastapi.testclient import TestClient

        client = TestClient(app)

        # Create projects with different tags via the API
        # First create them via project_manager
        from main import project_manager as pm

        p1 = _make_project(pid="tagfilt1", name="Tagged One", tags=["web", "prod"])
        p2 = _make_project(pid="tagfilt2", name="Tagged Two", tags=["api", "prod"])
        p3 = _make_project(pid="tagfilt3", name="No Match", tags=["desktop"])
        pm.save_project(p1)
        pm.save_project(p2)
        pm.save_project(p3)

        try:
            # Filter by 'prod' tag
            resp = client.get("/api/projects?tag=prod")
            assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
            data = resp.json()
            projects = data.get("projects", data)
            if isinstance(projects, list):
                project_ids = [p.get("id", "") for p in projects]
                assert "tagfilt1" in project_ids, "Should include project with 'prod' tag"
                assert "tagfilt2" in project_ids, "Should include project with 'prod' tag"
                # tagfilt3 should NOT be in results
                assert "tagfilt3" not in project_ids, (
                    "Should not include project without 'prod' tag"
                )
        finally:
            # Cleanup
            pm.delete_project("tagfilt1")
            pm.delete_project("tagfilt2")
            pm.delete_project("tagfilt3")


class TestTagsUpdateEndpoint:
    """Tests for PUT /api/projects/{project_id}/tags endpoint."""

    def test_tags_endpoint_exists(self):
        """PUT /api/projects/{project_id}/tags must be a registered route."""
        from main import app

        routes = [r.path for r in app.routes]
        assert "/api/projects/{project_id}/tags" in routes, (
            "PUT /api/projects/{project_id}/tags route must exist"
        )

    def test_update_tags(self):
        """PUT /api/projects/{project_id}/tags should update tags."""
        from main import app, project_manager as pm

        from fastapi.testclient import TestClient

        p = _make_project(pid="tagupd1", name="Update Tags")
        pm.save_project(p)

        try:
            client = TestClient(app)
            resp = client.put(
                f"/api/projects/{p.id}/tags",
                json={"tags": ["new_tag", "another"]},
            )
            assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

            # Verify tags were updated
            pm._cache.clear()
            loaded = pm.get_project(p.id)
            assert loaded is not None
            assert "new_tag" in loaded.tags
            assert "another" in loaded.tags
        finally:
            pm.delete_project("tagupd1")

    def test_update_tags_404(self):
        """Updating tags on non-existent project should return error."""
        from main import app

        from fastapi.testclient import TestClient

        client = TestClient(app)
        resp = client.put(
            "/api/projects/nonexistent_xyz/tags",
            json={"tags": ["tag"]},
        )
        assert resp.status_code in (404, 400, 422), (
            f"Expected error status for non-existent project, got {resp.status_code}"
        )
