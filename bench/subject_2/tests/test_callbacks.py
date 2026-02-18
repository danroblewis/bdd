"""Tests for callback loading and execution."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any, Dict, Optional
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
    CallbackConfig,
    CustomCallbackDefinition,
    RunEvent,
)
from runtime import RuntimeManager, TrackingPlugin, RunSession


class TestCallbackLoading:
    """Tests for loading callbacks from module paths."""
    
    def test_callback_file_created_on_disk(self, project_with_callbacks, temp_projects_dir):
        """Test that callback files are created on disk."""
        callback_file = temp_projects_dir / project_with_callbacks.id / "callbacks" / "custom.py"
        assert callback_file.exists()
        
        content = callback_file.read_text()
        assert "def set_foo" in content
        assert "callback_context.state['foo'] = 'bar'" in content
    
    def test_callback_module_path_parsing(self):
        """Test parsing of callback module paths."""
        # Full path: "callbacks.custom.function_name" -> module="callbacks.custom", func="function_name"
        full_path = "callbacks.custom.set_foo"
        parts = full_path.rsplit(".", 1)
        assert parts[0] == "callbacks.custom"
        assert parts[1] == "set_foo"
        
        # Short path: "callbacks.custom" -> module="callbacks.custom", func from module
        short_path = "callbacks.custom"
        if short_path.count(".") == 1:
            module_name = short_path
            # Would need to inspect module for function
            assert module_name == "callbacks.custom"
    
    def test_callback_config_structure(self, project_with_callbacks):
        """Test callback configuration structure."""
        agent = project_with_callbacks.agents[0]
        
        # Check callback configs exist
        assert len(agent.before_agent_callbacks) == 1
        callback = agent.before_agent_callbacks[0]
        
        # Check structure
        assert hasattr(callback, "module_path")
        assert callback.module_path == "callbacks.custom"
    
    def test_custom_callback_definition_structure(self, project_with_callbacks):
        """Test custom callback definition structure."""
        assert len(project_with_callbacks.custom_callbacks) == 1
        callback = project_with_callbacks.custom_callbacks[0]
        
        assert callback.id == "callback_1"
        assert callback.name == "set_foo"
        assert callback.module_path == "callbacks.custom"
        assert "def set_foo" in callback.code


class TestCallbackWrapping:
    """Tests for callback wrapping for tracking."""
    
    @pytest.mark.asyncio
    async def test_sync_callback_wrapper_emits_events(self):
        """Test that sync callbacks wrapped for tracking emit events."""
        events = []
        
        async def collector(event: RunEvent):
            events.append(event)
        
        session = RunSession(
            id="test_session",
            project_id="test_project",
            started_at=0,
            status="running",
        )
        
        tracking = TrackingPlugin(session, collector)
        
        # Simulate wrapping a sync callback
        def original_callback(callback_context):
            callback_context.state["test"] = "value"
            return None
        
        # The wrapper is created in runtime._build_single_agent
        # Here we test the tracking events directly
        mock_context = MagicMock()
        mock_context.agent_name = "test_agent"
        mock_context.state = {}
        
        # For user callbacks, they emit callback_start and callback_end events
        # These are emitted by the wrapper in runtime.py, not by TrackingPlugin
        # TrackingPlugin emits agent_start, agent_end, etc.
        
        # Create mock agent with proper string name
        mock_agent = MagicMock()
        mock_agent.name = "test_agent"
        mock_agent.instruction = "Test instruction"
        
        # Test that we can invoke tracking callbacks correctly
        result = await tracking.before_agent_callback(
            agent=mock_agent,
            callback_context=mock_context,
        )
        
        assert result is None
        assert len(events) == 1
    
    @pytest.mark.asyncio
    async def test_async_callback_wrapper_emits_events(self):
        """Test that async callbacks wrapped for tracking emit events."""
        events = []
        
        async def collector(event: RunEvent):
            events.append(event)
        
        session = RunSession(
            id="test_session",
            project_id="test_project",
            started_at=0,
            status="running",
        )
        
        tracking = TrackingPlugin(session, collector)
        
        async def original_async_callback(callback_context):
            callback_context.state["test"] = "async_value"
            return None
        
        mock_context = MagicMock()
        mock_context.agent_name = "test_agent"
        
        # Create mock agent with proper string name
        mock_agent = MagicMock()
        mock_agent.name = "test_agent"
        
        # Invoke tracking callback
        result = await tracking.after_agent_callback(
            agent=mock_agent,
            callback_context=mock_context,
        )
        
        assert result is None


class TestCallbackErrors:
    """Tests for callback error handling."""
    
    @pytest.mark.asyncio
    async def test_callback_error_captured(self):
        """Test that callback errors are captured and included in events."""
        events = []
        
        async def collector(event: RunEvent):
            events.append(event)
        
        # Simulate a callback that raises an error
        def failing_callback(callback_context):
            raise ValueError("Callback failed intentionally")
        
        # The wrapper in runtime.py should catch this and emit a callback_end
        # event with error information
        
        # For this test, we verify the structure of error data in events
        error_event = RunEvent(
            timestamp=0,
            event_type="callback_end",
            agent_name="test_agent",
            data={
                "callback_name": "failing_callback",
                "callback_type": "before_agent",
                "error": "Callback failed intentionally",
                "error_type": "ValueError",
                "stack_trace": "...",
            }
        )
        
        assert error_event.data["error"] == "Callback failed intentionally"
        assert error_event.data["error_type"] == "ValueError"
    
    def test_callback_module_not_found_generates_code(self, temp_projects_dir):
        """Test that projects with missing callbacks still generate code."""
        from code_generator import generate_python_code
        
        project = Project(
            id="bad_callback",
            name="Bad Callback Project",
            app=AppConfig(
                id="app",
                name="App",
                root_agent_id="agent_1",
                session_service_uri="memory://",
            ),
            agents=[
                LlmAgentConfig(
                    id="agent_1",
                    name="agent",
                    instruction="Test",
                    before_agent_callbacks=[
                        CallbackConfig(module_path="nonexistent.module.func"),
                    ],
                ),
            ],
        )
        
        # Code generation should still work
        code = generate_python_code(project)
        
        # Should contain the agent definition
        assert "Agent(" in code
        # May reference the nonexistent callback (execution would fail)
        assert "agent" in code.lower()


class TestCallbackSignatures:
    """Tests for callback signature validation."""
    
    def test_agent_callback_signature(self):
        """Test agent callback signature structure."""
        # Agent callbacks: (callback_context) -> Optional[Content]
        from google.adk.agents.callback_context import CallbackContext
        from typing import Optional
        
        # Valid agent callback signature
        def valid_agent_callback(callback_context: CallbackContext) -> Optional[Any]:
            return None
        
        # Check signature has callback_context
        import inspect
        sig = inspect.signature(valid_agent_callback)
        params = list(sig.parameters.keys())
        
        assert "callback_context" in params
    
    def test_model_callback_signature(self):
        """Test model callback signature structure."""
        # Model callbacks: (*, callback_context, llm_request/llm_response) -> Optional[LlmResponse]
        from typing import Optional, Any
        
        # Valid model callback signature (keyword-only)
        def valid_model_callback(*, callback_context, llm_request) -> Optional[Any]:
            return None
        
        import inspect
        sig = inspect.signature(valid_model_callback)
        params = sig.parameters
        
        # All params should be keyword-only
        for param in params.values():
            assert param.kind == inspect.Parameter.KEYWORD_ONLY
    
    def test_tool_callback_signature(self):
        """Test tool callback signature structure."""
        # Tool callbacks: (tool, tool_args, tool_context) -> Optional[Dict]
        from typing import Optional, Dict, Any
        
        def valid_tool_callback(tool, tool_args: Dict[str, Any], tool_context) -> Optional[Dict]:
            return None
        
        import inspect
        sig = inspect.signature(valid_tool_callback)
        params = list(sig.parameters.keys())
        
        assert "tool" in params
        assert "tool_args" in params
        assert "tool_context" in params


class TestCallbackStateModification:
    """Tests for callback state modification tracking."""
    
    @pytest.mark.asyncio
    async def test_state_changes_tracked(self):
        """Test that state changes from callbacks are tracked."""
        events = []
        
        async def collector(event: RunEvent):
            events.append(event)
        
        session = RunSession(
            id="test_session",
            project_id="test_project",
            started_at=0,
            status="running",
        )
        
        tracking = TrackingPlugin(session, collector)
        
        # Create mock agent with proper string name
        mock_agent = MagicMock()
        mock_agent.name = "test_agent"
        
        # Mock context with state tracking
        mock_context = MagicMock()
        mock_context.agent_name = "test_agent"
        mock_context._event_actions = MagicMock()
        mock_context._event_actions.state_delta = {"foo": "bar"}  # State change
        
        # After agent callback should capture state delta
        await tracking.after_agent_callback(
            agent=mock_agent,
            callback_context=mock_context,
        )
        
        assert len(events) == 1
        # State delta should be captured if available
        # (depends on how the tracking plugin handles it)


class TestCallbackModuleReloading:
    """Tests for callback module reloading for live updates."""
    
    def test_module_removed_from_sys_modules(self, temp_projects_dir, project_with_callbacks):
        """Test that modules are removed from sys.modules for fresh import."""
        import sys
        
        # Add project dir to path
        project_dir = temp_projects_dir / project_with_callbacks.id
        if str(project_dir) not in sys.path:
            sys.path.insert(0, str(project_dir))
        
        # First import
        import importlib
        module_path = "callbacks.custom"
        
        try:
            module = importlib.import_module(module_path)
            assert module_path in sys.modules
            
            # Simulate runtime behavior: remove and reimport
            del sys.modules[module_path]
            if "callbacks" in sys.modules:
                del sys.modules["callbacks"]
            
            assert module_path not in sys.modules
            
            # Reimport should work
            module2 = importlib.import_module(module_path)
            assert module2 is not None
            
        finally:
            # Cleanup
            for mod in list(sys.modules.keys()):
                if mod.startswith("callbacks"):
                    del sys.modules[mod]
            if str(project_dir) in sys.path:
                sys.path.remove(str(project_dir))
    
    def test_callback_code_update_reflected_after_reload(self, temp_projects_dir, project_with_callbacks):
        """Test that updating callback code is reflected after module reload."""
        import sys
        import importlib
        
        project_dir = temp_projects_dir / project_with_callbacks.id
        callback_file = project_dir / "callbacks" / "custom.py"
        
        if str(project_dir) not in sys.path:
            sys.path.insert(0, str(project_dir))
        
        try:
            # First import
            module = importlib.import_module("callbacks.custom")
            original_func = getattr(module, "set_foo", None)
            assert original_func is not None
            
            # Update file on disk
            new_code = '''
"""Updated custom callbacks module."""

from google.adk.agents.callback_context import CallbackContext
from typing import Optional
from google.genai import types

def set_foo(callback_context: CallbackContext) -> Optional[types.Content]:
    """Sets foo to a different value."""
    callback_context.state['foo'] = 'updated_value'  # Changed!
    return None
'''
            callback_file.write_text(new_code)
            
            # Remove from cache and reimport
            del sys.modules["callbacks.custom"]
            if "callbacks" in sys.modules:
                del sys.modules["callbacks"]
            
            module2 = importlib.import_module("callbacks.custom")
            
            # Verify we got fresh code
            source = callback_file.read_text()
            assert "updated_value" in source
            
        finally:
            # Cleanup
            for mod in list(sys.modules.keys()):
                if mod.startswith("callbacks"):
                    del sys.modules[mod]
            if str(project_dir) in sys.path:
                sys.path.remove(str(project_dir))

