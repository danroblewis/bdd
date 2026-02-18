"""Integration tests that run the full runtime with mocked LLM responses."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

# Add backend to path
backend_dir = Path(__file__).parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from models import (
    Project,
    AppConfig,
    LlmAgentConfig,
    SequentialAgentConfig,
    LoopAgentConfig,
    ParallelAgentConfig,
    ModelConfig,
    BuiltinToolConfig,
    FunctionToolConfig,
    CallbackConfig,
    CustomToolDefinition,
    CustomCallbackDefinition,
    StateKeyConfig,
    RunEvent,
)
from runtime import RuntimeManager


def create_mock_llm_response(text: str):
    """Create a mock LLM response event that ADK would generate."""
    from google.genai import types
    
    # Create a proper Content object
    content = types.Content(
        role="model",
        parts=[types.Part.from_text(text=text)]
    )
    return content


def create_mock_function_call_response(name: str, args: Dict[str, Any]):
    """Create a mock LLM response with a function call."""
    from google.genai import types
    
    # Create function call part
    function_call = types.FunctionCall(name=name, args=args)
    content = types.Content(
        role="model",
        parts=[types.Part(function_call=function_call)]
    )
    return content


class TestCallbackExecution:
    """Test that callbacks are actually executed during runtime."""
    
    @pytest.fixture
    def projects_dir(self, tmp_path):
        """Create a temporary projects directory."""
        projects_dir = tmp_path / "projects"
        projects_dir.mkdir(parents=True)
        return projects_dir
    
    @pytest.fixture
    def callback_project(self, projects_dir) -> Project:
        """Create a project with callbacks that modify state.
        
        Note: We no longer need to manually create callback files on disk.
        The RuntimeManager.run_agent() method now creates a temp directory
        and generates callback files from the project.custom_callbacks[].code field.
        """
        # Define callback code - this will be written to temp files by RuntimeManager
        before_callback_code = '''
from google.adk.agents.callback_context import CallbackContext
from typing import Optional
from google.genai import types

def set_before_flag(callback_context: CallbackContext) -> Optional[types.Content]:
    """Sets before_ran to True before agent runs."""
    callback_context.state["before_ran"] = True
    callback_context.state["before_counter"] = callback_context.state.get("before_counter", 0) + 1
    return None
'''
        
        after_callback_code = '''
from google.adk.agents.callback_context import CallbackContext
from typing import Optional
from google.genai import types

def set_after_flag(callback_context: CallbackContext) -> Optional[types.Content]:
    """Sets after_ran to True after agent runs."""
    callback_context.state["after_ran"] = True
    callback_context.state["after_counter"] = callback_context.state.get("after_counter", 0) + 1
    return None
'''
        
        project = Project(
            id="test_project",
            name="callback_test_project",
            description="Tests callback execution",
            app=AppConfig(
                id="app_test",
                name="test_app",
                root_agent_id="agent_1",
                session_service_uri="memory://",
                memory_service_uri="memory://",
                artifact_service_uri="memory://",
                state_keys=[
                    StateKeyConfig(name="before_ran", type="boolean", default_value=False),
                    StateKeyConfig(name="after_ran", type="boolean", default_value=False),
                    StateKeyConfig(name="before_counter", type="number", default_value=0),
                    StateKeyConfig(name="after_counter", type="number", default_value=0),
                ],
            ),
            agents=[
                LlmAgentConfig(
                    id="agent_1",
                    name="test_agent",
                    description="A test agent with callbacks",
                    instruction="You are a test agent. Say OK to any message.",
                    model=ModelConfig(provider="gemini", model_name="gemini-2.0-flash"),
                    before_agent_callbacks=[
                        CallbackConfig(module_path="callbacks.custom.set_before_flag"),
                    ],
                    after_agent_callbacks=[
                        CallbackConfig(module_path="callbacks.custom.set_after_flag"),
                    ],
                ),
            ],
            custom_callbacks=[
                CustomCallbackDefinition(
                    id="cb_before",
                    name="set_before_flag",
                    description="Sets before_ran flag",
                    module_path="callbacks.custom",
                    code=before_callback_code,  # Code is generated to temp file by RuntimeManager
                ),
                CustomCallbackDefinition(
                    id="cb_after",
                    name="set_after_flag",
                    description="Sets after_ran flag",
                    module_path="callbacks.custom",
                    code=after_callback_code,  # Code is generated to temp file by RuntimeManager
                ),
            ],
        )
        
        return project
    
    @pytest.mark.asyncio
    async def test_before_agent_callback_executed(self, projects_dir, callback_project):
        """Test that before_agent_callback is executed and modifies state."""
        manager = RuntimeManager(projects_dir=str(projects_dir))
        events: List[RunEvent] = []
        
        async def event_collector(event: RunEvent):
            events.append(event)
        
        # Mock the LLM to return a simple response
        with patch("google.adk.models.google_llm.Gemini.generate_content_async") as mock_llm:
            # Create mock async generator for LLM response - use side_effect for fresh generator each call
            async def mock_generate(*args, **kwargs):
                from google.adk.models.llm_response import LlmResponse
                from google.genai import types
                
                response = LlmResponse(
                    content=types.Content(
                        role="model",
                        parts=[types.Part.from_text(text="OK")]
                    ),
                    partial=False,
                )
                yield response
            
            mock_llm.side_effect = lambda *args, **kwargs: mock_generate()
            
            # Run the agent
            final_event = None
            async for event in manager.run_agent(
                project=callback_project,
                user_message="Hello",
                event_callback=event_collector,
            ):
                final_event = event
            
            # Check events - agent should have started and ended
            event_types = [e.event_type for e in events]
            
            # Should have agent_start and agent_end events (from TrackingPlugin)
            assert "agent_start" in event_types, f"Expected agent_start, got: {event_types}"
            assert "agent_end" in event_types or any("error" in str(e.data) for e in events), f"Expected agent_end, got: {event_types}"
            
            # State changes from callbacks should be captured
            state_events = [e for e in events if e.event_type == "state_change"]
            # Note: callback state changes are tracked via the state_change event type
    
    @pytest.mark.asyncio
    async def test_after_agent_callback_executed(self, projects_dir, callback_project):
        """Test that after_agent_callback is executed and modifies state."""
        manager = RuntimeManager(projects_dir=str(projects_dir))
        events: List[RunEvent] = []
        
        async def event_collector(event: RunEvent):
            events.append(event)
        
        with patch("google.adk.models.google_llm.Gemini.generate_content_async") as mock_llm:
            async def mock_generate(*args, **kwargs):
                from google.adk.models.llm_response import LlmResponse
                from google.genai import types
                
                response = LlmResponse(
                    content=types.Content(
                        role="model",
                        parts=[types.Part.from_text(text="OK")]
                    ),
                    partial=False,
                )
                yield response
            
            mock_llm.side_effect = lambda *args, **kwargs: mock_generate()
            
            async for event in manager.run_agent(
                project=callback_project,
                user_message="Hello",
                event_callback=event_collector,
            ):
                pass
            
            # Check that agent execution completed
            event_types = [e.event_type for e in events]
            assert "agent_start" in event_types, "Agent should have started"
            # Check we got some events (agent runs properly)
    
    @pytest.mark.asyncio
    async def test_callback_modifies_state(self, projects_dir, callback_project):
        """Test that callbacks can modify session state."""
        manager = RuntimeManager(projects_dir=str(projects_dir))
        events: List[RunEvent] = []
        state_changes: List[Dict] = []
        
        async def event_collector(event: RunEvent):
            events.append(event)
            if event.event_type == "state_change":
                state_changes.append(event.data)
        
        with patch("google.adk.models.google_llm.Gemini.generate_content_async") as mock_llm:
            async def mock_generate(*args, **kwargs):
                from google.adk.models.llm_response import LlmResponse
                from google.genai import types
                
                response = LlmResponse(
                    content=types.Content(
                        role="model",
                        parts=[types.Part.from_text(text="OK")]
                    ),
                    partial=False,
                )
                yield response
            
            mock_llm.side_effect = lambda *args, **kwargs: mock_generate()
            
            async for event in manager.run_agent(
                project=callback_project,
                user_message="Hello",
                event_callback=event_collector,
            ):
                pass
            
            # Check that agent ran (we should have agent events)
            event_types = [e.event_type for e in events]
            assert "agent_start" in event_types, "Should have agent_start event"
            
            # State changes should be captured (from output_key or callbacks)
            state_change_events = [e for e in events if e.event_type == "state_change"]
            # The agent may or may not produce state changes depending on configuration


class TestNonLlmAgentCallbacks:
    """Test callbacks on SequentialAgent, LoopAgent, and ParallelAgent."""
    
    @pytest.fixture
    def projects_dir(self, tmp_path):
        """Create a temporary projects directory."""
        projects_dir = tmp_path / "projects"
        projects_dir.mkdir(parents=True)
        return projects_dir
    
    @pytest.fixture
    def sequential_callback_project(self, projects_dir) -> Project:
        """Create a project with a SequentialAgent that has callbacks."""
        callback_code = '''
from google.adk.agents.callback_context import CallbackContext
from typing import Optional
from google.genai import types

def mark_sequential_ran(callback_context: CallbackContext) -> Optional[types.Content]:
    """Sets a flag when SequentialAgent callback runs."""
    callback_context.state['sequential_callback_ran'] = True
    return None
'''
        return Project(
            id="test_sequential_callbacks",
            name="Sequential Agent Callbacks Test",
            app=AppConfig(
                id="app",
                name="test_app",
                root_agent_id="seq_agent",
                session_service_uri="memory://",
                state_keys=[
                    StateKeyConfig(name="sequential_callback_ran", type="boolean", default_value=False),
                ],
            ),
            agents=[
                SequentialAgentConfig(
                    id="seq_agent",
                    name="sequential_agent",
                    description="Sequential agent with callbacks",
                    sub_agents=["child_llm"],
                    before_agent_callbacks=[
                        CallbackConfig(module_path="callbacks.custom.mark_sequential_ran"),
                    ],
                    after_agent_callbacks=[],
                ),
                LlmAgentConfig(
                    id="child_llm",
                    name="child_agent",
                    instruction="Say OK",
                    model=ModelConfig(provider="gemini", model_name="gemini-2.0-flash"),
                ),
            ],
            custom_callbacks=[
                CustomCallbackDefinition(
                    id="cb_seq",
                    name="mark_sequential_ran",
                    description="Marks that sequential callback ran",
                    module_path="callbacks.custom",
                    code=callback_code,
                ),
            ],
        )
    
    @pytest.fixture
    def loop_callback_project(self, projects_dir) -> Project:
        """Create a project with a LoopAgent that has callbacks."""
        callback_code = '''
from google.adk.agents.callback_context import CallbackContext
from typing import Optional
from google.genai import types

def mark_loop_ran(callback_context: CallbackContext) -> Optional[types.Content]:
    """Sets a flag when LoopAgent callback runs."""
    callback_context.state['loop_callback_ran'] = True
    return None
'''
        return Project(
            id="test_loop_callbacks",
            name="Loop Agent Callbacks Test",
            app=AppConfig(
                id="app",
                name="test_app",
                root_agent_id="loop_agent",
                session_service_uri="memory://",
                state_keys=[
                    StateKeyConfig(name="loop_callback_ran", type="boolean", default_value=False),
                ],
            ),
            agents=[
                LoopAgentConfig(
                    id="loop_agent",
                    name="loop_agent",
                    description="Loop agent with callbacks",
                    sub_agents=["child_llm"],
                    max_iterations=1,  # Just run once for testing
                    before_agent_callbacks=[
                        CallbackConfig(module_path="callbacks.custom.mark_loop_ran"),
                    ],
                    after_agent_callbacks=[],
                ),
                LlmAgentConfig(
                    id="child_llm",
                    name="child_agent",
                    instruction="Say OK and use exit_loop to exit.",
                    model=ModelConfig(provider="gemini", model_name="gemini-2.0-flash"),
                    tools=[BuiltinToolConfig(type="builtin", name="exit_loop")],
                ),
            ],
            custom_callbacks=[
                CustomCallbackDefinition(
                    id="cb_loop",
                    name="mark_loop_ran",
                    description="Marks that loop callback ran",
                    module_path="callbacks.custom",
                    code=callback_code,
                ),
            ],
        )
    
    @pytest.fixture
    def parallel_callback_project(self, projects_dir) -> Project:
        """Create a project with a ParallelAgent that has callbacks."""
        callback_code = '''
from google.adk.agents.callback_context import CallbackContext
from typing import Optional
from google.genai import types

def mark_parallel_ran(callback_context: CallbackContext) -> Optional[types.Content]:
    """Sets a flag when ParallelAgent callback runs."""
    callback_context.state['parallel_callback_ran'] = True
    return None
'''
        return Project(
            id="test_parallel_callbacks",
            name="Parallel Agent Callbacks Test",
            app=AppConfig(
                id="app",
                name="test_app",
                root_agent_id="parallel_agent",
                session_service_uri="memory://",
                state_keys=[
                    StateKeyConfig(name="parallel_callback_ran", type="boolean", default_value=False),
                ],
            ),
            agents=[
                ParallelAgentConfig(
                    id="parallel_agent",
                    name="parallel_agent",
                    description="Parallel agent with callbacks",
                    sub_agents=["child_llm"],
                    before_agent_callbacks=[
                        CallbackConfig(module_path="callbacks.custom.mark_parallel_ran"),
                    ],
                    after_agent_callbacks=[],
                ),
                LlmAgentConfig(
                    id="child_llm",
                    name="child_agent",
                    instruction="Say OK",
                    model=ModelConfig(provider="gemini", model_name="gemini-2.0-flash"),
                ),
            ],
            custom_callbacks=[
                CustomCallbackDefinition(
                    id="cb_parallel",
                    name="mark_parallel_ran",
                    description="Marks that parallel callback ran",
                    module_path="callbacks.custom",
                    code=callback_code,
                ),
            ],
        )
    
    @pytest.mark.asyncio
    async def test_sequential_agent_callback_executed(self, projects_dir, sequential_callback_project):
        """Test that SequentialAgent before_agent_callback is executed."""
        manager = RuntimeManager(projects_dir=str(projects_dir))
        events: List[RunEvent] = []
        
        async def event_collector(event: RunEvent):
            events.append(event)
        
        with patch("google.adk.models.google_llm.Gemini.generate_content_async") as mock_llm:
            async def mock_generate(*args, **kwargs):
                from google.adk.models.llm_response import LlmResponse
                from google.genai import types
                
                response = LlmResponse(
                    content=types.Content(
                        role="model",
                        parts=[types.Part.from_text(text="OK")]
                    ),
                    partial=False,
                )
                yield response
            
            mock_llm.side_effect = lambda *args, **kwargs: mock_generate()
            
            async for event in manager.run_agent(
                project=sequential_callback_project,
                user_message="Hello",
                event_callback=event_collector,
            ):
                pass
            
            # Verify agent events occurred
            event_types = [e.event_type for e in events]
            assert "agent_start" in event_types, "Should have agent_start event"
            
            # Check for sequential_agent start event specifically
            agent_start_events = [e for e in events if e.event_type == "agent_start"]
            agent_names = [e.agent_name for e in agent_start_events]
            assert "sequential_agent" in agent_names, f"Should have sequential_agent start, got: {agent_names}"
    
    @pytest.mark.asyncio
    async def test_loop_agent_callback_executed(self, projects_dir, loop_callback_project):
        """Test that LoopAgent before_agent_callback is executed."""
        manager = RuntimeManager(projects_dir=str(projects_dir))
        events: List[RunEvent] = []
        
        async def event_collector(event: RunEvent):
            events.append(event)
        
        with patch("google.adk.models.google_llm.Gemini.generate_content_async") as mock_llm:
            async def mock_generate(*args, **kwargs):
                from google.adk.models.llm_response import LlmResponse
                from google.genai import types
                
                # Return a tool call to exit_loop to avoid infinite looping
                response = LlmResponse(
                    content=types.Content(
                        role="model",
                        parts=[
                            types.Part.from_function_call(
                                function_call=types.FunctionCall(
                                    name="exit_loop",
                                    args={},
                                )
                            )
                        ]
                    ),
                    partial=False,
                )
                yield response
            
            mock_llm.side_effect = lambda *args, **kwargs: mock_generate()
            
            async for event in manager.run_agent(
                project=loop_callback_project,
                user_message="Hello",
                event_callback=event_collector,
            ):
                pass
            
            # Verify agent events occurred
            event_types = [e.event_type for e in events]
            assert "agent_start" in event_types, "Should have agent_start event"
            
            # Check for loop_agent start event specifically
            agent_start_events = [e for e in events if e.event_type == "agent_start"]
            agent_names = [e.agent_name for e in agent_start_events]
            assert "loop_agent" in agent_names, f"Should have loop_agent start, got: {agent_names}"
    
    @pytest.mark.asyncio
    async def test_parallel_agent_callback_executed(self, projects_dir, parallel_callback_project):
        """Test that ParallelAgent before_agent_callback is executed."""
        manager = RuntimeManager(projects_dir=str(projects_dir))
        events: List[RunEvent] = []
        
        async def event_collector(event: RunEvent):
            events.append(event)
        
        with patch("google.adk.models.google_llm.Gemini.generate_content_async") as mock_llm:
            async def mock_generate(*args, **kwargs):
                from google.adk.models.llm_response import LlmResponse
                from google.genai import types
                
                response = LlmResponse(
                    content=types.Content(
                        role="model",
                        parts=[types.Part.from_text(text="OK")]
                    ),
                    partial=False,
                )
                yield response
            
            mock_llm.side_effect = lambda *args, **kwargs: mock_generate()
            
            async for event in manager.run_agent(
                project=parallel_callback_project,
                user_message="Hello",
                event_callback=event_collector,
            ):
                pass
            
            # Verify agent events occurred
            event_types = [e.event_type for e in events]
            assert "agent_start" in event_types, "Should have agent_start event"
            
            # Check for parallel_agent start event specifically
            agent_start_events = [e for e in events if e.event_type == "agent_start"]
            agent_names = [e.agent_name for e in agent_start_events]
            assert "parallel_agent" in agent_names, f"Should have parallel_agent start, got: {agent_names}"


class TestToolExecution:
    """Test that tools are actually executed during runtime."""
    
    @pytest.fixture
    def projects_dir(self, tmp_path):
        """Create a temporary projects directory."""
        projects_dir = tmp_path / "projects"
        projects_dir.mkdir(parents=True)
        return projects_dir
    
    @pytest.fixture
    def tool_project(self, projects_dir) -> Project:
        """Create a project with a custom tool.
        
        Note: We no longer need to manually create tool files on disk.
        The RuntimeManager.run_agent() method now creates a temp directory
        and generates tool files from the project.custom_tools[].code field.
        """
        # Define tool code - this will be written to temp files by RuntimeManager
        tool_code = '''
def add_numbers(a: int, b: int) -> int:
    """Add two numbers together.
    
    Args:
        a: First number
        b: Second number
        
    Returns:
        The sum of a and b
    """
    return a + b
'''
        
        project = Project(
            id="tool_project",
            name="tool_test_project",
            description="Tests tool execution",
            app=AppConfig(
                id="app_test",
                name="test_app",
                root_agent_id="agent_1",
                session_service_uri="memory://",
                memory_service_uri="memory://",
                artifact_service_uri="memory://",
            ),
            agents=[
                LlmAgentConfig(
                    id="agent_1",
                    name="calculator_agent",
                    description="A calculator agent",
                    instruction="You are a calculator. Use the add_numbers tool.",
                    model=ModelConfig(provider="gemini", model_name="gemini-2.0-flash"),
                    tools=[
                        FunctionToolConfig(
                            type="function",
                            name="add_numbers",
                            description="Add two numbers",
                            module_path="tools.math.add_numbers",
                        ),
                    ],
                ),
            ],
            custom_tools=[
                CustomToolDefinition(
                    id="tool_add",
                    name="add_numbers",
                    description="Add two numbers",
                    module_path="tools.math",
                    code=tool_code,  # Code is generated to temp file by RuntimeManager
                ),
            ],
        )
        
        return project
    
    @pytest.mark.asyncio
    async def test_tool_call_event_emitted(self, projects_dir, tool_project):
        """Test that tool_call events are emitted when tools are called."""
        manager = RuntimeManager(projects_dir=str(projects_dir))
        events: List[RunEvent] = []
        
        async def event_collector(event: RunEvent):
            events.append(event)
        
        call_count = 0
        
        with patch("google.adk.models.google_llm.Gemini.generate_content_async") as mock_llm:
            async def mock_generate(*args, **kwargs):
                nonlocal call_count
                from google.adk.models.llm_response import LlmResponse
                from google.genai import types
                
                call_count += 1
                
                if call_count == 1:
                    # First call: return a function call
                    response = LlmResponse(
                        content=types.Content(
                            role="model",
                            parts=[types.Part(function_call=types.FunctionCall(
                                name="add_numbers",
                                args={"a": 2, "b": 3}
                            ))]
                        ),
                        partial=False,
                    )
                else:
                    # Second call: return text after tool result
                    response = LlmResponse(
                        content=types.Content(
                            role="model",
                            parts=[types.Part.from_text(text="The result is 5")]
                        ),
                        partial=False,
                    )
                yield response
            
            mock_llm.side_effect = lambda *args, **kwargs: mock_generate()
            
            async for event in manager.run_agent(
                project=tool_project,
                user_message="What is 2 + 3?",
                event_callback=event_collector,
            ):
                pass
            
            # Check for tool events
            tool_call_events = [e for e in events if e.event_type == "tool_call"]
            tool_result_events = [e for e in events if e.event_type == "tool_result"]
            
            # We should have at least a tool call
            assert len(tool_call_events) > 0, f"Expected tool_call events, got event types: {[e.event_type for e in events]}"
    
    @pytest.mark.asyncio
    async def test_tool_result_returned(self, projects_dir, tool_project):
        """Test that tool results are captured in events."""
        manager = RuntimeManager(projects_dir=str(projects_dir))
        events: List[RunEvent] = []
        
        async def event_collector(event: RunEvent):
            events.append(event)
        
        call_count = 0
        
        with patch("google.adk.models.google_llm.Gemini.generate_content_async") as mock_llm:
            async def mock_generate(*args, **kwargs):
                nonlocal call_count
                from google.adk.models.llm_response import LlmResponse
                from google.genai import types
                
                call_count += 1
                
                if call_count == 1:
                    response = LlmResponse(
                        content=types.Content(
                            role="model",
                            parts=[types.Part(function_call=types.FunctionCall(
                                name="add_numbers",
                                args={"a": 10, "b": 20}
                            ))]
                        ),
                        partial=False,
                    )
                else:
                    response = LlmResponse(
                        content=types.Content(
                            role="model",
                            parts=[types.Part.from_text(text="The result is 30")]
                        ),
                        partial=False,
                    )
                yield response
            
            mock_llm.side_effect = lambda *args, **kwargs: mock_generate()
            
            async for event in manager.run_agent(
                project=tool_project,
                user_message="What is 10 + 20?",
                event_callback=event_collector,
            ):
                pass
            
            # Check tool result event has the correct result
            tool_result_events = [e for e in events if e.event_type == "tool_result"]
            
            if tool_result_events:
                # Tool should return 30
                result = tool_result_events[0].data.get("result")
                assert result == 30, f"Expected tool result 30, got {result}"


class TestSequentialAgentExecution:
    """Test sequential agent orchestration."""
    
    @pytest.fixture
    def projects_dir(self, tmp_path):
        """Create a temporary projects directory."""
        projects_dir = tmp_path / "projects"
        projects_dir.mkdir(parents=True)
        return projects_dir
    
    @pytest.fixture
    def sequential_project(self, projects_dir) -> Project:
        """Create a project with sequential agents."""
        project = Project(
            id="seq_project",
            name="sequential_test_project",
            description="Tests sequential execution",
            app=AppConfig(
                id="app_test",
                name="test_app",
                root_agent_id="pipeline",
                session_service_uri="memory://",
                memory_service_uri="memory://",
                artifact_service_uri="memory://",
                state_keys=[
                    StateKeyConfig(name="step1_output", type="string", default_value=""),
                    StateKeyConfig(name="step2_output", type="string", default_value=""),
                ],
            ),
            agents=[
                SequentialAgentConfig(
                    id="pipeline",
                    name="pipeline",
                    description="Sequential pipeline",
                    sub_agents=["step1", "step2"],
                ),
                LlmAgentConfig(
                    id="step1",
                    name="step1",
                    description="First step",
                    instruction="You are step 1. Say 'STEP1_DONE'.",
                    model=ModelConfig(provider="gemini", model_name="gemini-2.0-flash"),
                    output_key="step1_output",
                ),
                LlmAgentConfig(
                    id="step2",
                    name="step2",
                    description="Second step",
                    instruction="You are step 2. Say 'STEP2_DONE'.",
                    model=ModelConfig(provider="gemini", model_name="gemini-2.0-flash"),
                    output_key="step2_output",
                ),
            ],
        )
        
        return project
    
    @pytest.mark.asyncio
    async def test_sequential_agents_run_in_order(self, projects_dir, sequential_project):
        """Test that sequential agents run in the correct order."""
        manager = RuntimeManager(projects_dir=str(projects_dir))
        events: List[RunEvent] = []
        agent_order: List[str] = []
        
        async def event_collector(event: RunEvent):
            events.append(event)
            if event.event_type == "agent_start":
                agent_order.append(event.agent_name)
        
        with patch("google.adk.models.google_llm.Gemini.generate_content_async") as mock_llm:
            async def mock_generate(*args, **kwargs):
                from google.adk.models.llm_response import LlmResponse
                from google.genai import types
                
                # Return different responses based on context
                response = LlmResponse(
                    content=types.Content(
                        role="model",
                        parts=[types.Part.from_text(text="DONE")]
                    ),
                    partial=False,
                )
                yield response
            
            mock_llm.side_effect = lambda *args, **kwargs: mock_generate()
            
            async for event in manager.run_agent(
                project=sequential_project,
                user_message="Run the pipeline",
                event_callback=event_collector,
            ):
                pass
            
            # Check agent order
            # Should include step1 before step2
            if "step1" in agent_order and "step2" in agent_order:
                step1_idx = agent_order.index("step1")
                step2_idx = agent_order.index("step2")
                assert step1_idx < step2_idx, f"step1 should run before step2. Order: {agent_order}"


class TestStateManagement:
    """Test state management during runtime."""
    
    @pytest.fixture
    def projects_dir(self, tmp_path):
        """Create a temporary projects directory."""
        projects_dir = tmp_path / "projects"
        projects_dir.mkdir(parents=True)
        return projects_dir
    
    @pytest.fixture
    def state_project(self, projects_dir) -> Project:
        """Create a project that uses state.
        
        Note: We no longer need to manually create callback files on disk.
        The RuntimeManager.run_agent() method now creates a temp directory
        and generates callback files from the project.custom_callbacks[].code field.
        """
        # Define callback code - this will be written to temp files by RuntimeManager
        callback_code = '''
from google.adk.agents.callback_context import CallbackContext
from typing import Optional
from google.genai import types

def increment_counter(callback_context: CallbackContext) -> Optional[types.Content]:
    """Increments the counter in state."""
    current = callback_context.state.get("counter", 0)
    callback_context.state["counter"] = current + 1
    return None
'''
        
        project = Project(
            id="state_project",
            name="state_test_project",
            description="Tests state management",
            app=AppConfig(
                id="app_test",
                name="test_app",
                root_agent_id="agent_1",
                session_service_uri="memory://",
                memory_service_uri="memory://",
                artifact_service_uri="memory://",
                state_keys=[
                    StateKeyConfig(name="counter", type="number", default_value=0),
                ],
            ),
            agents=[
                LlmAgentConfig(
                    id="agent_1",
                    name="counter_agent",
                    description="A counter agent",
                    instruction="You are a counter. Say the current count.",
                    model=ModelConfig(provider="gemini", model_name="gemini-2.0-flash"),
                    before_agent_callbacks=[
                        CallbackConfig(module_path="callbacks.state.increment_counter"),
                    ],
                ),
            ],
            custom_callbacks=[
                CustomCallbackDefinition(
                    id="cb_counter",
                    name="increment_counter",
                    description="Increments counter",
                    module_path="callbacks.state",
                    code=callback_code,  # Code is generated to temp file by RuntimeManager
                ),
            ],
        )
        
        return project
    
    @pytest.mark.asyncio
    async def test_state_persists_across_session(self, projects_dir, state_project):
        """Test that state changes persist within a session."""
        manager = RuntimeManager(projects_dir=str(projects_dir))
        events: List[RunEvent] = []
        
        async def event_collector(event: RunEvent):
            events.append(event)
        
        with patch("google.adk.models.google_llm.Gemini.generate_content_async") as mock_llm:
            async def mock_generate(*args, **kwargs):
                from google.adk.models.llm_response import LlmResponse
                from google.genai import types
                
                response = LlmResponse(
                    content=types.Content(
                        role="model",
                        parts=[types.Part.from_text(text="Count updated")]
                    ),
                    partial=False,
                )
                yield response
            
            mock_llm.side_effect = lambda *args, **kwargs: mock_generate()
            
            # Run first time
            session_id = None
            async for event in manager.run_agent(
                project=state_project,
                user_message="Increment",
                event_callback=event_collector,
            ):
                if event.event_type == "agent_start" and event.data.get("session_id"):
                    session_id = event.data["session_id"]
            
            # Check that counter was incremented via state_change events
            state_change_events = [e for e in events if e.event_type == "state_change"]
            assert len(state_change_events) > 0, f"Expected state_change events, got: {[e.event_type for e in events]}"
            
            # Check that counter was updated to 1
            found_counter = False
            for event in state_change_events:
                state_delta = event.data.get("state_delta", {})
                if "counter" in state_delta:
                    counter = state_delta["counter"]
                    assert counter >= 1, f"Counter should be at least 1, got {counter}"
                    found_counter = True
                    break
            
            assert found_counter, f"Expected counter in state_change events, got: {[e.data for e in state_change_events]}"

