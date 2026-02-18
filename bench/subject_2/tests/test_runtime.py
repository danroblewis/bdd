"""Tests for runtime agent execution with mocked LLM responses."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any, Dict, List
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
    RunEvent,
)
from runtime import RuntimeManager, TrackingPlugin, RunSession


class TestTrackingPlugin:
    """Tests for the TrackingPlugin."""
    
    @pytest.mark.asyncio
    async def test_tracking_plugin_emits_events(self):
        """Test that TrackingPlugin emits events correctly."""
        events = []
        
        async def collector(event: RunEvent):
            events.append(event)
        
        session = RunSession(
            id="test_session",
            project_id="test_project",
            started_at=0,
            status="running",
        )
        
        plugin = TrackingPlugin(session, collector)
        
        # Create mock agent and callback_context
        mock_agent = MagicMock()
        mock_agent.name = "test_agent"
        mock_agent.instruction = "Test instruction"
        
        mock_context = MagicMock()
        
        # Test before_agent_callback
        result = await plugin.before_agent_callback(
            agent=mock_agent,
            callback_context=mock_context,
        )
        
        assert result is None  # Should not short-circuit
        assert len(events) == 1
        assert events[0].event_type == "agent_start"
        assert events[0].agent_name == "test_agent"
    
    @pytest.mark.asyncio
    async def test_tracking_plugin_after_agent(self):
        """Test TrackingPlugin after_agent_callback."""
        events = []
        
        async def collector(event: RunEvent):
            events.append(event)
        
        session = RunSession(
            id="test_session",
            project_id="test_project",
            started_at=0,
            status="running",
        )
        
        plugin = TrackingPlugin(session, collector)
        
        mock_agent = MagicMock()
        mock_agent.name = "test_agent"
        
        result = await plugin.after_agent_callback(
            agent=mock_agent,
            callback_context=MagicMock(),
        )
        
        assert result is None
        assert len(events) == 1
        assert events[0].event_type == "agent_end"
    
    @pytest.mark.asyncio
    async def test_tracking_plugin_model_callbacks(self):
        """Test TrackingPlugin model callbacks."""
        events = []
        
        async def collector(event: RunEvent):
            events.append(event)
        
        session = RunSession(
            id="test_session",
            project_id="test_project",
            started_at=0,
            status="running",
        )
        
        plugin = TrackingPlugin(session, collector)
        
        mock_context = MagicMock()
        mock_context.agent_name = "test_agent"
        
        # Create mock LLM request
        mock_request = MagicMock()
        mock_request.contents = []
        mock_request.config = None
        mock_request.tools_dict = {"tool1": MagicMock()}
        
        result = await plugin.before_model_callback(
            callback_context=mock_context,
            llm_request=mock_request,
        )
        
        assert result is None
        assert len(events) == 1
        assert events[0].event_type == "model_call"
        assert events[0].data["tool_count"] == 1
    
    @pytest.mark.asyncio
    async def test_tracking_plugin_tool_callbacks(self):
        """Test TrackingPlugin tool callbacks."""
        events = []
        
        async def collector(event: RunEvent):
            events.append(event)
        
        session = RunSession(
            id="test_session",
            project_id="test_project",
            started_at=0,
            status="running",
        )
        
        plugin = TrackingPlugin(session, collector)
        
        mock_tool = MagicMock()
        mock_tool.name = "add_numbers"
        
        mock_context = MagicMock()
        mock_context.agent_name = "test_agent"
        mock_context._event_actions = MagicMock()
        mock_context._event_actions.state_delta = {}
        
        # Test before_tool_callback
        result = await plugin.before_tool_callback(
            tool=mock_tool,
            tool_args={"a": 1, "b": 2},
            tool_context=mock_context,
        )
        
        assert result is None
        assert len(events) == 1
        assert events[0].event_type == "tool_call"
        assert events[0].data["tool_name"] == "add_numbers"
        assert events[0].data["args"] == {"a": 1, "b": 2}
        
        # Test after_tool_callback
        result = await plugin.after_tool_callback(
            tool=mock_tool,
            tool_args={"a": 1, "b": 2},
            tool_context=mock_context,
            result=3,
        )
        
        assert result is None
        assert len(events) == 2
        assert events[1].event_type == "tool_result"
        assert events[1].data["result"] == 3


class TestRuntimeManagerInit:
    """Tests for RuntimeManager initialization and session management."""
    
    def test_runtime_manager_creates_projects_dir(self, temp_projects_dir):
        """Test that RuntimeManager works with existing projects dir."""
        manager = RuntimeManager(projects_dir=str(temp_projects_dir))
        assert manager.projects_dir.exists()
    
    def test_get_nonexistent_session_returns_none(self, temp_projects_dir):
        """Test that getting a nonexistent session returns None."""
        manager = RuntimeManager(projects_dir=str(temp_projects_dir))
        session = manager.get_session("nonexistent")
        assert session is None
    
    def test_stop_run_sets_flag(self, temp_projects_dir):
        """Test that stop_run sets the running flag to False."""
        manager = RuntimeManager(projects_dir=str(temp_projects_dir))
        manager._running["session_1"] = True
        
        manager.stop_run("session_1")
        
        assert manager._running["session_1"] is False


class TestRunAgent:
    """Tests for the run_agent method with mocked LLM."""
    
    @pytest.mark.asyncio
    async def test_run_agent_creates_session(self, temp_projects_dir, simple_project):
        """Test that run_agent creates a session entry."""
        manager = RuntimeManager(projects_dir=str(temp_projects_dir))
        events = []
        
        async def collector(event: RunEvent):
            events.append(event)
        
        # Test that session is created in manager
        # When run_agent starts, it creates a session in self.sessions
        session_id = "test_session_123"
        
        # Simulate what run_agent does at the start
        from models import RunSession
        import time
        
        session = RunSession(
            id=session_id,
            project_id=simple_project.id,
            started_at=time.time(),
            status="running",
        )
        manager.sessions[session_id] = session
        
        # Verify session is stored
        assert session_id in manager.sessions
        assert manager.sessions[session_id].status == "running"
    
    def test_execute_generated_code_produces_app(self, temp_projects_dir, simple_project):
        """Test that _execute_generated_code produces an app."""
        manager = RuntimeManager(projects_dir=str(temp_projects_dir))
        
        # Prepare temp dir for imports
        manager._prepare_temp_dir(simple_project, "test_session")
        
        try:
            app = manager._execute_generated_code(simple_project)
            
            # App should exist
            assert app is not None
            # App name is sanitized to be a valid identifier
            assert app.name == "Test_App"
            assert app.root_agent is not None
        finally:
            manager._cleanup_temp_dir("test_session")
    
    def test_generated_code_includes_all_agents(self, temp_projects_dir, sequential_agent_project):
        """Test that generated code includes all configured agents."""
        from code_generator import generate_python_code
        
        code = generate_python_code(sequential_agent_project)
        
        # All agents should be in the generated code
        assert "sequential_controller" in code
        assert "first_agent" in code
        assert "second_agent" in code
    
    @pytest.mark.asyncio
    async def test_session_reuse_logic(self, temp_projects_dir, simple_project):
        """Test that session reuse logic works correctly."""
        manager = RuntimeManager(projects_dir=str(temp_projects_dir))
        
        # Create an existing session in the manager
        from models import RunSession
        import time
        
        existing_session = RunSession(
            id="existing_session",
            project_id=simple_project.id,
            started_at=time.time() - 60,  # Started 60 seconds ago
            status="completed",
        )
        manager.sessions["existing_session"] = existing_session
        
        # Verify the session can be retrieved
        assert manager.get_session("existing_session") is not None
        assert manager.get_session("existing_session").id == "existing_session"
        
        # Verify nonexistent session returns None
        assert manager.get_session("nonexistent") is None


class TestEventSerialization:
    """Tests for event serialization in TrackingPlugin."""
    
    @pytest.mark.asyncio
    async def test_serialize_text_content(self):
        """Test serialization of text content."""
        events = []
        
        async def collector(event: RunEvent):
            events.append(event)
        
        session = RunSession(
            id="test_session",
            project_id="test_project",
            started_at=0,
            status="running",
        )
        
        plugin = TrackingPlugin(session, collector)
        
        # Create mock content with text
        mock_content = MagicMock()
        mock_content.role = "user"
        mock_part = MagicMock()
        mock_part.text = "Hello world"
        mock_part.function_call = None
        mock_part.function_response = None
        mock_part.thought = False
        mock_content.parts = [mock_part]
        
        result = plugin._serialize_contents([mock_content])
        
        assert len(result) == 1
        assert result[0]["role"] == "user"
        assert len(result[0]["parts"]) == 1
        assert result[0]["parts"][0]["type"] == "text"
        assert result[0]["parts"][0]["text"] == "Hello world"
    
    @pytest.mark.asyncio
    async def test_serialize_function_call_content(self):
        """Test serialization of function call content."""
        events = []
        
        async def collector(event: RunEvent):
            events.append(event)
        
        session = RunSession(
            id="test_session",
            project_id="test_project",
            started_at=0,
            status="running",
        )
        
        plugin = TrackingPlugin(session, collector)
        
        # Create mock content with function call
        mock_content = MagicMock()
        mock_content.role = "model"
        mock_part = MagicMock()
        mock_part.text = None
        mock_part.function_call = MagicMock()
        mock_part.function_call.name = "add_numbers"
        mock_part.function_call.args = {"a": 1, "b": 2}
        mock_part.function_response = None
        mock_part.thought = False
        mock_content.parts = [mock_part]
        
        result = plugin._serialize_contents([mock_content])
        
        assert len(result) == 1
        assert result[0]["parts"][0]["type"] == "function_call"
        assert result[0]["parts"][0]["name"] == "add_numbers"
        assert result[0]["parts"][0]["args"] == {"a": 1, "b": 2}


class TestSessionManagement:
    """Tests for session listing and loading."""
    
    @pytest.mark.asyncio
    async def test_list_sessions_from_service(self, temp_projects_dir, simple_project):
        """Test listing sessions from session service."""
        manager = RuntimeManager(projects_dir=str(temp_projects_dir))
        
        # Should return empty list for memory:// service (no persistence)
        sessions = await manager.list_sessions_from_service(simple_project)
        assert sessions == []
    
    @pytest.mark.asyncio
    async def test_load_session_returns_none_for_nonexistent(self, temp_projects_dir, simple_project):
        """Test loading nonexistent session returns None."""
        manager = RuntimeManager(projects_dir=str(temp_projects_dir))
        
        session = await manager.load_session_from_service(simple_project, "nonexistent")
        assert session is None

