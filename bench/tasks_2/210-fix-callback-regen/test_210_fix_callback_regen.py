"""Acceptance tests for task 210 - fix callback regeneration on save."""
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
    CallbackConfig,
    CustomCallbackDefinition,
)
from project_manager import ProjectManager


def _make_project_with_callback(
    callback_code: str = "def my_callback(context):\n    pass",
    project_id: str = "proj_cb_regen",
) -> Project:
    """Create a test project with a custom callback."""
    return Project(
        id=project_id,
        name="Callback Regen Test",
        description="Testing callback regeneration",
        app=AppConfig(
            id="app_cb",
            name="CB App",
            root_agent_id="agent_1",
            session_service_uri="memory://",
            memory_service_uri="memory://",
            artifact_service_uri="memory://",
        ),
        agents=[
            LlmAgentConfig(
                id="agent_1",
                name="cb_agent",
                description="Agent with callbacks",
                instruction="You are a helpful assistant.",
                model=ModelConfig(provider="gemini", model_name="gemini-2.0-flash"),
                before_agent_callbacks=[
                    CallbackConfig(module_path="callbacks.my_callback"),
                ],
            ),
        ],
        custom_callbacks=[
            CustomCallbackDefinition(
                id="cb_1",
                name="my_callback",
                description="A test callback",
                module_path="callbacks.my_callback",
                code=callback_code,
            ),
        ],
    )


def _find_callback_py_files(project_dir: Path) -> list[Path]:
    """Find all .py files in the callbacks subdirectory of a project."""
    callbacks_dir = project_dir / "callbacks"
    if not callbacks_dir.exists():
        return []
    return list(callbacks_dir.rglob("*.py"))


class TestCallbackRegenOnSave:
    """Tests for callback file regeneration during save_project."""

    def test_save_custom_callbacks_is_invoked(self, tmp_path):
        """_save_custom_callbacks must be called (or its logic present) during save_project."""
        pm = ProjectManager(str(tmp_path))
        project = _make_project_with_callback()

        with patch.object(pm, "_save_custom_callbacks", wraps=pm._save_custom_callbacks) as mock_save_cb:
            pm.save_project(project)
            mock_save_cb.assert_called_once()

    def test_callback_py_file_is_written(self, tmp_path):
        """When saving a project with a callback that has code, a .py file should be written."""
        pm = ProjectManager(str(tmp_path))
        project = _make_project_with_callback(
            callback_code="def my_callback(context):\n    return 'hello'"
        )
        pm.save_project(project)

        project_dir = tmp_path / project.id
        py_files = _find_callback_py_files(project_dir)
        assert len(py_files) > 0, (
            f"Expected at least one .py file in callbacks directory. "
            f"Project dir contents: {list(project_dir.rglob('*'))}"
        )

        # At least one file should contain the callback code
        found_code = False
        for py_file in py_files:
            content = py_file.read_text()
            if "my_callback" in content:
                found_code = True
                break
        assert found_code, (
            f"At least one callback .py file should contain 'my_callback'. "
            f"Files found: {[f.name for f in py_files]}"
        )

    def test_callback_code_updates_on_resave(self, tmp_path):
        """When callback code is changed and re-saved, the .py file must reflect the new code."""
        pm = ProjectManager(str(tmp_path))

        # First save with original code
        original_code = "def my_callback(context):\n    return 'version_1'"
        project = _make_project_with_callback(callback_code=original_code)
        pm.save_project(project)

        project_dir = tmp_path / project.id
        py_files_v1 = _find_callback_py_files(project_dir)
        assert len(py_files_v1) > 0, "Should have callback .py file after first save"

        # Read the original file content
        original_contents = {}
        for f in py_files_v1:
            original_contents[f.name] = f.read_text()

        # Now update the callback code and re-save
        updated_code = "def my_callback(context):\n    return 'version_2_updated'"
        project.custom_callbacks[0].code = updated_code
        pm.save_project(project)

        # Check that the .py file now has the updated code
        py_files_v2 = _find_callback_py_files(project_dir)
        assert len(py_files_v2) > 0, "Should still have callback .py file after re-save"

        found_updated = False
        for py_file in py_files_v2:
            content = py_file.read_text()
            if "version_2_updated" in content:
                found_updated = True
                break

        assert found_updated, (
            "After re-saving with updated callback code, the .py file should contain "
            "'version_2_updated'. This indicates callback files are regenerated on save. "
            f"Files: {[(f.name, f.read_text()[:100]) for f in py_files_v2]}"
        )

        # Also verify the old code is no longer present
        old_code_still_present = False
        for py_file in py_files_v2:
            content = py_file.read_text()
            if "version_1" in content and "version_2" not in content:
                old_code_still_present = True
                break
        assert not old_code_still_present, (
            "Old callback code ('version_1') should not persist after re-save with new code"
        )

    def test_remaining_callbacks_correct_after_removal(self, tmp_path):
        """If a callback is removed and project re-saved, remaining callbacks should be correct."""
        pm = ProjectManager(str(tmp_path))

        # Create project with two callbacks
        project = Project(
            id="proj_cb_removal",
            name="Callback Removal Test",
            app=AppConfig(
                id="app_cb_rm",
                name="CB Removal App",
                root_agent_id="agent_1",
                session_service_uri="memory://",
                memory_service_uri="memory://",
                artifact_service_uri="memory://",
            ),
            agents=[
                LlmAgentConfig(
                    id="agent_1",
                    name="removal_agent",
                    instruction="You are helpful.",
                    model=ModelConfig(provider="gemini", model_name="gemini-2.0-flash"),
                    before_agent_callbacks=[
                        CallbackConfig(module_path="callbacks.cb_keep"),
                        CallbackConfig(module_path="callbacks.cb_remove"),
                    ],
                ),
            ],
            custom_callbacks=[
                CustomCallbackDefinition(
                    id="cb_keep",
                    name="cb_keep",
                    description="Callback to keep",
                    module_path="callbacks.cb_keep",
                    code="def cb_keep(context):\n    return 'kept'",
                ),
                CustomCallbackDefinition(
                    id="cb_remove",
                    name="cb_remove",
                    description="Callback to remove",
                    module_path="callbacks.cb_remove",
                    code="def cb_remove(context):\n    return 'removed'",
                ),
            ],
        )

        pm.save_project(project)

        project_dir = tmp_path / project.id
        py_files_before = _find_callback_py_files(project_dir)
        assert len(py_files_before) > 0, "Should have callback files after initial save"

        # Remove one callback from the project and re-save
        project.custom_callbacks = [
            cb for cb in project.custom_callbacks if cb.name != "cb_remove"
        ]
        project.agents[0].before_agent_callbacks = [
            CallbackConfig(module_path="callbacks.cb_keep"),
        ]
        pm.save_project(project)

        # Check that the remaining callback is still correct
        py_files_after = _find_callback_py_files(project_dir)
        found_kept = False
        for py_file in py_files_after:
            content = py_file.read_text()
            if "cb_keep" in content:
                found_kept = True
                break

        assert found_kept, (
            "After removing one callback, the remaining callback 'cb_keep' should still "
            f"be present in callback files. Files: {[(f.name, f.read_text()[:80]) for f in py_files_after]}"
        )
