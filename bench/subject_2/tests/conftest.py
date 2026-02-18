"""Pytest configuration and shared fixtures for ADK Playground tests."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Add backend to path for imports
backend_dir = Path(__file__).parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from models import (
    Project,
    AppConfig,
    LlmAgentConfig,
    SequentialAgentConfig,
    LoopAgentConfig,
    ModelConfig,
    BuiltinToolConfig,
    FunctionToolConfig,
    CustomToolDefinition,
    CustomCallbackDefinition,
    CallbackConfig,
    StateKeyConfig,
    RunEvent,
    RunSession,
)


@pytest.fixture
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def temp_projects_dir(tmp_path):
    """Create a temporary projects directory."""
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    return projects_dir


@pytest.fixture
def simple_project() -> Project:
    """Create a simple project with one LlmAgent."""
    return Project(
        id="test_project",
        name="Test Project",
        description="A simple test project",
        app=AppConfig(
            id="app_test",
            name="Test App",
            root_agent_id="agent_1",
            session_service_uri="memory://",
            memory_service_uri="memory://",
            artifact_service_uri="memory://",
        ),
        agents=[
            LlmAgentConfig(
                id="agent_1",
                name="test_agent",
                description="A test agent",
                instruction="You are a helpful assistant. Always respond with exactly: HELLO_WORLD",
                model=ModelConfig(
                    provider="gemini",
                    model_name="gemini-2.0-flash",
                ),
            ),
        ],
    )


@pytest.fixture
def project_with_state_keys() -> Project:
    """Create a project with state keys configured."""
    return Project(
        id="state_project",
        name="State Project",
        description="A project with state keys",
        app=AppConfig(
            id="app_state",
            name="State App",
            root_agent_id="agent_1",
            session_service_uri="memory://",
            memory_service_uri="memory://",
            artifact_service_uri="memory://",
            state_keys=[
                StateKeyConfig(name="counter", type="number", default_value=0),
                StateKeyConfig(name="user_name", type="string", default_value=""),
            ],
        ),
        agents=[
            LlmAgentConfig(
                id="agent_1",
                name="state_agent",
                description="An agent that uses state",
                instruction="You manage state. Increment the counter each time.",
                output_key="last_response",
            ),
        ],
    )


@pytest.fixture
def project_with_callbacks(temp_projects_dir) -> Project:
    """Create a project with callbacks."""
    project = Project(
        id="callback_project",
        name="Callback Project",
        description="A project with callbacks",
        app=AppConfig(
            id="app_callback",
            name="Callback App",
            root_agent_id="agent_1",
            session_service_uri="memory://",
            memory_service_uri="memory://",
            artifact_service_uri="memory://",
        ),
        agents=[
            LlmAgentConfig(
                id="agent_1",
                name="callback_agent",
                description="An agent with callbacks",
                instruction="You are a helpful assistant.",
                before_agent_callbacks=[
                    CallbackConfig(module_path="callbacks.custom"),
                ],
            ),
        ],
        custom_callbacks=[
            CustomCallbackDefinition(
                id="callback_1",
                name="set_foo",
                description="Sets foo in state",
                module_path="callbacks.custom",
                code='''
from google.adk.agents.callback_context import CallbackContext
from typing import Optional
from google.genai import types

def set_foo(callback_context: CallbackContext) -> Optional[types.Content]:
    """Sets foo in session state."""
    callback_context.state['foo'] = 'bar'
    return None
''',
            ),
        ],
    )
    
    # Create callback file on disk
    project_dir = temp_projects_dir / project.id
    callbacks_dir = project_dir / "callbacks"
    callbacks_dir.mkdir(parents=True, exist_ok=True)
    
    callback_file = callbacks_dir / "custom.py"
    callback_file.write_text('''
"""Auto-generated custom callbacks module."""

from google.adk.agents.callback_context import CallbackContext
from typing import Optional
from google.genai import types

def set_foo(callback_context: CallbackContext) -> Optional[types.Content]:
    """Sets foo in session state."""
    callback_context.state['foo'] = 'bar'
    return None
''')
    
    # Create __init__.py for callbacks package
    (callbacks_dir / "__init__.py").write_text("")
    
    return project


@pytest.fixture
def project_with_tools(temp_projects_dir) -> Project:
    """Create a project with custom tools."""
    project = Project(
        id="tools_project",
        name="Tools Project",
        description="A project with tools",
        app=AppConfig(
            id="app_tools",
            name="Tools App",
            root_agent_id="agent_1",
            session_service_uri="memory://",
            memory_service_uri="memory://",
            artifact_service_uri="memory://",
        ),
        agents=[
            LlmAgentConfig(
                id="agent_1",
                name="tool_agent",
                description="An agent with tools",
                instruction="You have a calculator tool. Use it to add numbers.",
                tools=[
                    FunctionToolConfig(
                        type="function",
                        name="add_numbers",
                        description="Adds two numbers",
                        module_path="tools.calculator.add_numbers",
                    ),
                ],
            ),
        ],
        custom_tools=[
            CustomToolDefinition(
                id="tool_1",
                name="add_numbers",
                description="Adds two numbers",
                module_path="tools.calculator",
                code='''
def add_numbers(a: int, b: int) -> int:
    """Add two numbers together."""
    return a + b
''',
            ),
        ],
    )
    
    # Create tool file on disk
    project_dir = temp_projects_dir / project.id
    tools_dir = project_dir / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    
    tool_file = tools_dir / "calculator.py"
    tool_file.write_text('''
"""Calculator tools."""

def add_numbers(a: int, b: int) -> int:
    """Add two numbers together."""
    return a + b
''')
    
    # Create __init__.py for tools package
    (tools_dir / "__init__.py").write_text("")
    
    return project


@pytest.fixture
def sequential_agent_project() -> Project:
    """Create a project with a SequentialAgent."""
    return Project(
        id="sequential_project",
        name="Sequential Project",
        description="A project with sequential agents",
        app=AppConfig(
            id="app_seq",
            name="Sequential App",
            root_agent_id="seq_agent",
            session_service_uri="memory://",
            memory_service_uri="memory://",
            artifact_service_uri="memory://",
        ),
        agents=[
            SequentialAgentConfig(
                id="seq_agent",
                name="sequential_controller",
                description="Controls sequential execution",
                sub_agents=["agent_1", "agent_2"],
            ),
            LlmAgentConfig(
                id="agent_1",
                name="first_agent",
                description="First agent in sequence",
                instruction="You are the first agent. Say 'FIRST'.",
            ),
            LlmAgentConfig(
                id="agent_2",
                name="second_agent",
                description="Second agent in sequence",
                instruction="You are the second agent. Say 'SECOND'.",
            ),
        ],
    )


@pytest.fixture
def loop_agent_project() -> Project:
    """Create a project with a LoopAgent."""
    return Project(
        id="loop_project",
        name="Loop Project",
        description="A project with loop agents",
        app=AppConfig(
            id="app_loop",
            name="Loop App",
            root_agent_id="loop_agent",
            session_service_uri="memory://",
            memory_service_uri="memory://",
            artifact_service_uri="memory://",
        ),
        agents=[
            LoopAgentConfig(
                id="loop_agent",
                name="loop_controller",
                description="Controls looped execution",
                sub_agents=["agent_1"],
                max_iterations=3,
            ),
            LlmAgentConfig(
                id="agent_1",
                name="looping_agent",
                description="Agent that loops",
                instruction="Count up from where you left off. Use exit_loop when you reach 3.",
                tools=[
                    BuiltinToolConfig(type="builtin", name="exit_loop"),
                ],
            ),
        ],
    )


# Mock LLM response helpers

def create_mock_llm_response(text: str, thought: bool = False) -> MagicMock:
    """Create a mock LLM response with text."""
    response = MagicMock()
    response.content = MagicMock()
    
    part = MagicMock()
    part.text = text
    part.thought = thought
    part.function_call = None
    
    response.content.parts = [part]
    response.content.role = "model"
    response.usage_metadata = MagicMock()
    response.usage_metadata.prompt_token_count = 10
    response.usage_metadata.candidates_token_count = 5
    response.candidates = []
    
    return response


def create_mock_function_call_response(name: str, args: Dict[str, Any]) -> MagicMock:
    """Create a mock LLM response with a function call."""
    response = MagicMock()
    response.content = MagicMock()
    
    part = MagicMock()
    part.text = None
    part.thought = False
    part.function_call = MagicMock()
    part.function_call.name = name
    part.function_call.args = args
    
    response.content.parts = [part]
    response.content.role = "model"
    response.usage_metadata = MagicMock()
    response.usage_metadata.prompt_token_count = 10
    response.usage_metadata.candidates_token_count = 5
    response.candidates = []
    
    return response


@pytest.fixture
def mock_llm_text_response():
    """Fixture that returns a function to create mock text responses."""
    return create_mock_llm_response


@pytest.fixture
def mock_llm_function_call():
    """Fixture that returns a function to create mock function call responses."""
    return create_mock_function_call_response


@pytest.fixture
def collected_events() -> List[RunEvent]:
    """Fixture to collect events during test runs."""
    return []


@pytest.fixture
def event_collector(collected_events):
    """Create an async event collector callback."""
    async def collector(event: RunEvent):
        collected_events.append(event)
    return collector

