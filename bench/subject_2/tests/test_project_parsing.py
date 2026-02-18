"""Tests for project parsing and code generation."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

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
    MCPToolConfig,
    MCPServerConfig,
    CallbackConfig,
    CustomCallbackDefinition,
)
from runtime import RuntimeManager
from code_generator import generate_python_code


class TestProjectParsing:
    """Tests for parsing project configurations."""
    
    def test_simple_project_parsing(self, simple_project):
        """Test that a simple project can be parsed."""
        assert simple_project.id == "test_project"
        assert simple_project.name == "Test Project"
        assert len(simple_project.agents) == 1
        assert simple_project.app.root_agent_id == "agent_1"
    
    def test_agent_config_parsing(self, simple_project):
        """Test that agent configuration is correctly parsed."""
        agent = simple_project.agents[0]
        assert isinstance(agent, LlmAgentConfig)
        assert agent.id == "agent_1"
        assert agent.name == "test_agent"
        assert "helpful assistant" in agent.instruction
    
    def test_model_config_parsing(self, simple_project):
        """Test that model configuration is correctly parsed."""
        agent = simple_project.agents[0]
        assert agent.model is not None
        assert agent.model.provider == "gemini"
        assert agent.model.model_name == "gemini-2.0-flash"
    
    def test_sequential_agent_parsing(self, sequential_agent_project):
        """Test parsing of sequential agent configuration."""
        seq_agent = None
        for agent in sequential_agent_project.agents:
            if isinstance(agent, SequentialAgentConfig):
                seq_agent = agent
                break
        
        assert seq_agent is not None
        assert seq_agent.name == "sequential_controller"
        assert len(seq_agent.sub_agents) == 2
        assert "agent_1" in seq_agent.sub_agents
        assert "agent_2" in seq_agent.sub_agents
    
    def test_loop_agent_parsing(self, loop_agent_project):
        """Test parsing of loop agent configuration."""
        loop_agent = None
        for agent in loop_agent_project.agents:
            if isinstance(agent, LoopAgentConfig):
                loop_agent = agent
                break
        
        assert loop_agent is not None
        assert loop_agent.name == "loop_controller"
        assert loop_agent.max_iterations == 3
        assert len(loop_agent.sub_agents) == 1
    
    def test_builtin_tool_parsing(self, loop_agent_project):
        """Test parsing of builtin tool configuration."""
        # Find the agent with tools
        agent_with_tools = None
        for agent in loop_agent_project.agents:
            if isinstance(agent, LlmAgentConfig) and agent.tools:
                agent_with_tools = agent
                break
        
        assert agent_with_tools is not None
        assert len(agent_with_tools.tools) == 1
        tool = agent_with_tools.tools[0]
        assert isinstance(tool, BuiltinToolConfig)
        assert tool.name == "exit_loop"
    
    def test_callback_config_parsing(self, project_with_callbacks):
        """Test parsing of callback configuration."""
        agent = project_with_callbacks.agents[0]
        assert len(agent.before_agent_callbacks) == 1
        callback = agent.before_agent_callbacks[0]
        assert callback.module_path == "callbacks.custom"
    
    def test_custom_callback_definition_parsing(self, project_with_callbacks):
        """Test parsing of custom callback definitions."""
        assert len(project_with_callbacks.custom_callbacks) == 1
        callback = project_with_callbacks.custom_callbacks[0]
        assert callback.name == "set_foo"
        assert "callback_context.state['foo']" in callback.code


class TestCodeGeneration:
    """Tests for generating Python code from project configuration."""
    
    def test_runtime_manager_init(self, temp_projects_dir):
        """Test RuntimeManager initialization."""
        manager = RuntimeManager(projects_dir=str(temp_projects_dir))
        assert manager.projects_dir == temp_projects_dir
        assert manager.sessions == {}
    
    def test_generate_code_includes_agent(self, simple_project):
        """Test that generated code includes the agent."""
        code = generate_python_code(simple_project)
        
        assert "Agent(" in code
        assert 'name="test_agent"' in code
        assert "gemini-2.0-flash" in code
    
    def test_generate_code_includes_app(self, simple_project):
        """Test that generated code includes the App."""
        code = generate_python_code(simple_project)
        
        assert "from google.adk.apps import App" in code
        assert "app = App(" in code
        # App name is sanitized to be a valid identifier
        assert 'name="Test_App"' in code
    
    def test_generate_code_includes_imports(self, simple_project):
        """Test that generated code includes necessary imports."""
        code = generate_python_code(simple_project)
        
        assert "from google.adk.agents import Agent" in code
    
    def test_generate_sequential_agent_code(self, sequential_agent_project):
        """Test code generation for sequential agents."""
        code = generate_python_code(sequential_agent_project)
        
        assert "from google.adk.agents import SequentialAgent" in code
        assert "SequentialAgent(" in code
    
    def test_generate_loop_agent_code(self, loop_agent_project):
        """Test code generation for loop agents."""
        code = generate_python_code(loop_agent_project)
        
        assert "from google.adk.agents import LoopAgent" in code
        assert "LoopAgent(" in code
        assert "max_iterations=3" in code
    
    def test_generate_code_with_builtin_tool(self, loop_agent_project):
        """Test code generation includes builtin tools."""
        code = generate_python_code(loop_agent_project)
        
        assert "from google.adk.tools import exit_loop" in code
        assert "exit_loop" in code


class TestCodeExecution:
    """Tests for executing generated code."""
    
    def test_execute_code_produces_app(self, temp_projects_dir, simple_project):
        """Test that executing generated code produces an app."""
        manager = RuntimeManager(projects_dir=str(temp_projects_dir))
        
        # Prepare temp dir for imports
        manager._prepare_temp_dir(simple_project, "test_session")
        
        try:
            app = manager._execute_generated_code(simple_project)
            
            assert app is not None
            # App name is sanitized to be a valid identifier
            assert app.name == "Test_App"
            assert app.root_agent is not None
        finally:
            manager._cleanup_temp_dir("test_session")


class TestProjectValidation:
    """Tests for project validation."""
    
    def test_project_generates_valid_code(self, temp_projects_dir):
        """Test that a project generates syntactically valid code."""
        project = Project(
            id="valid_project",
            name="Valid Project",
            app=AppConfig(
                id="app_valid",
                name="Valid App",
                root_agent_id="agent_1",
                session_service_uri="memory://",
            ),
            agents=[
                LlmAgentConfig(
                    id="agent_1",
                    name="real_agent",
                    instruction="I exist",
                ),
            ],
        )
        
        code = generate_python_code(project)
        
        # Code should be valid Python
        compile(code, "<test>", "exec")
    
    def test_project_with_missing_sub_agents_generates_code(self, temp_projects_dir):
        """Test that projects with missing sub-agents still generate code."""
        project = Project(
            id="missing_sub",
            name="Missing Sub-agents",
            app=AppConfig(
                id="app_missing",
                name="Missing App",
                root_agent_id="seq_agent",
                session_service_uri="memory://",
            ),
            agents=[
                SequentialAgentConfig(
                    id="seq_agent",
                    name="sequential",
                    sub_agents=["nonexistent_1", "nonexistent_2"],
                ),
            ],
        )
        
        code = generate_python_code(project)
        
        # Should still generate code (may reference nonexistent agents)
        assert "SequentialAgent(" in code
