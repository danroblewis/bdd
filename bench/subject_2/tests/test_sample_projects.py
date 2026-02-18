"""Tests that parse and validate sample project files."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest
import yaml

# Add backend to path
backend_dir = Path(__file__).parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from models import (
    Project,
    LlmAgentConfig,
    SequentialAgentConfig,
    LoopAgentConfig,
)

SAMPLE_PROJECTS_DIR = Path(__file__).parent / "sample_projects"


def load_project_yaml(filename: str) -> Dict[str, Any]:
    """Load a project YAML file."""
    path = SAMPLE_PROJECTS_DIR / filename
    with open(path) as f:
        return yaml.safe_load(f)


class TestSimpleAgent:
    """Tests for the simple agent sample project."""
    
    def test_loads_yaml(self):
        """Test that the YAML file loads correctly."""
        data = load_project_yaml("simple_agent.yaml")
        assert data["id"] == "simple_test"
        assert data["name"] == "Simple Test Project"
    
    def test_parses_to_project(self):
        """Test that the YAML parses to a valid Project."""
        data = load_project_yaml("simple_agent.yaml")
        project = Project.model_validate(data)
        
        assert project.id == "simple_test"
        assert project.app.root_agent_id == "greeter_agent"
    
    def test_agent_configuration(self):
        """Test the agent is configured correctly."""
        data = load_project_yaml("simple_agent.yaml")
        project = Project.model_validate(data)
        
        assert len(project.agents) == 1
        agent = project.agents[0]
        
        assert isinstance(agent, LlmAgentConfig)
        assert agent.name == "greeter"
        assert "friendly greeter" in agent.instruction
    
    def test_model_configuration(self):
        """Test the model is configured correctly."""
        data = load_project_yaml("simple_agent.yaml")
        project = Project.model_validate(data)
        
        agent = project.agents[0]
        assert agent.model is not None
        assert agent.model.provider == "gemini"
        assert agent.model.model_name == "gemini-2.0-flash"


class TestStateAgent:
    """Tests for the state agent sample project."""
    
    def test_loads_yaml(self):
        """Test that the YAML file loads correctly."""
        data = load_project_yaml("state_agent.yaml")
        assert data["id"] == "state_test"
    
    def test_parses_to_project(self):
        """Test that the YAML parses to a valid Project."""
        data = load_project_yaml("state_agent.yaml")
        project = Project.model_validate(data)
        
        assert project.id == "state_test"
    
    def test_state_keys_configured(self):
        """Test that state keys are properly configured."""
        data = load_project_yaml("state_agent.yaml")
        project = Project.model_validate(data)
        
        state_keys = project.app.state_keys
        assert len(state_keys) == 2
        
        counter_key = next((k for k in state_keys if k.name == "counter"), None)
        assert counter_key is not None
        assert counter_key.type == "number"
        assert counter_key.default_value == 0
        
        message_key = next((k for k in state_keys if k.name == "last_message"), None)
        assert message_key is not None
        assert message_key.type == "string"
    
    def test_output_key_configured(self):
        """Test that output_key is configured."""
        data = load_project_yaml("state_agent.yaml")
        project = Project.model_validate(data)
        
        agent = project.agents[0]
        assert agent.output_key == "response"


class TestToolAgent:
    """Tests for the tool agent sample project."""
    
    def test_loads_yaml(self):
        """Test that the YAML file loads correctly."""
        data = load_project_yaml("tool_agent.yaml")
        assert data["id"] == "tool_test"
    
    def test_parses_to_project(self):
        """Test that the YAML parses to a valid Project."""
        data = load_project_yaml("tool_agent.yaml")
        project = Project.model_validate(data)
        
        assert project.id == "tool_test"
    
    def test_tool_configuration(self):
        """Test that tools are properly configured."""
        data = load_project_yaml("tool_agent.yaml")
        project = Project.model_validate(data)
        
        agent = project.agents[0]
        assert len(agent.tools) == 1
        
        tool = agent.tools[0]
        assert tool.type == "function"
        assert tool.name == "add_numbers"
        assert tool.module_path == "tools.math.add_numbers"
    
    def test_custom_tool_definition(self):
        """Test that custom tool definition is present."""
        data = load_project_yaml("tool_agent.yaml")
        project = Project.model_validate(data)
        
        assert len(project.custom_tools) == 1
        tool = project.custom_tools[0]
        
        assert tool.name == "add_numbers"
        assert "def add_numbers" in tool.code
        assert "return a + b" in tool.code


class TestCallbackAgent:
    """Tests for the callback agent sample project."""
    
    def test_loads_yaml(self):
        """Test that the YAML file loads correctly."""
        data = load_project_yaml("callback_agent.yaml")
        assert data["id"] == "callback_test"
    
    def test_parses_to_project(self):
        """Test that the YAML parses to a valid Project."""
        data = load_project_yaml("callback_agent.yaml")
        project = Project.model_validate(data)
        
        assert project.id == "callback_test"
    
    def test_callback_configuration(self):
        """Test that callbacks are properly configured."""
        data = load_project_yaml("callback_agent.yaml")
        project = Project.model_validate(data)
        
        agent = project.agents[0]
        assert len(agent.before_agent_callbacks) == 1
        assert len(agent.after_agent_callbacks) == 1
        
        before_callback = agent.before_agent_callbacks[0]
        assert before_callback.module_path == "callbacks.custom.set_callback_flag"
        
        after_callback = agent.after_agent_callbacks[0]
        assert after_callback.module_path == "callbacks.custom.set_callback_timestamp"
    
    def test_custom_callback_definitions(self):
        """Test that custom callback definitions are present."""
        data = load_project_yaml("callback_agent.yaml")
        project = Project.model_validate(data)
        
        assert len(project.custom_callbacks) == 2
        
        before_cb = next((c for c in project.custom_callbacks if c.name == "set_callback_flag"), None)
        assert before_cb is not None
        assert "callback_context.state['callback_ran'] = True" in before_cb.code
        
        after_cb = next((c for c in project.custom_callbacks if c.name == "set_callback_timestamp"), None)
        assert after_cb is not None
        assert "datetime.datetime.now()" in after_cb.code
    
    def test_state_keys_for_callbacks(self):
        """Test that state keys used by callbacks are configured."""
        data = load_project_yaml("callback_agent.yaml")
        project = Project.model_validate(data)
        
        state_keys = project.app.state_keys
        assert len(state_keys) == 2
        
        flag_key = next((k for k in state_keys if k.name == "callback_ran"), None)
        assert flag_key is not None
        assert flag_key.type == "boolean"
        
        timestamp_key = next((k for k in state_keys if k.name == "callback_timestamp"), None)
        assert timestamp_key is not None
        assert timestamp_key.type == "string"


class TestSequentialAgent:
    """Tests for the sequential agent sample project."""
    
    def test_loads_yaml(self):
        """Test that the YAML file loads correctly."""
        data = load_project_yaml("sequential_agent.yaml")
        assert data["id"] == "sequential_test"
    
    def test_parses_to_project(self):
        """Test that the YAML parses to a valid Project."""
        data = load_project_yaml("sequential_agent.yaml")
        project = Project.model_validate(data)
        
        assert project.id == "sequential_test"
    
    def test_sequential_agent_configuration(self):
        """Test that sequential agent is properly configured."""
        data = load_project_yaml("sequential_agent.yaml")
        project = Project.model_validate(data)
        
        # Find the sequential agent
        seq_agent = None
        for agent in project.agents:
            if isinstance(agent, SequentialAgentConfig):
                seq_agent = agent
                break
        
        assert seq_agent is not None
        assert seq_agent.name == "pipeline"
        assert len(seq_agent.sub_agents) == 2
        assert "step1_agent" in seq_agent.sub_agents
        assert "step2_agent" in seq_agent.sub_agents
    
    def test_sub_agents_present(self):
        """Test that sub-agents are defined."""
        data = load_project_yaml("sequential_agent.yaml")
        project = Project.model_validate(data)
        
        agent_ids = [a.id for a in project.agents]
        assert "step1_agent" in agent_ids
        assert "step2_agent" in agent_ids
    
    def test_output_keys_for_steps(self):
        """Test that each step has an output_key."""
        data = load_project_yaml("sequential_agent.yaml")
        project = Project.model_validate(data)
        
        step1 = next((a for a in project.agents if a.id == "step1_agent"), None)
        step2 = next((a for a in project.agents if a.id == "step2_agent"), None)
        
        assert step1 is not None
        assert step2 is not None
        assert step1.output_key == "step1_output"
        assert step2.output_key == "step2_output"


class TestProjectValidation:
    """Tests for project validation edge cases."""
    
    def test_all_sample_projects_valid(self):
        """Test that all sample project files are valid."""
        sample_files = list(SAMPLE_PROJECTS_DIR.glob("*.yaml"))
        assert len(sample_files) >= 5, "Should have at least 5 sample projects"
        
        for sample_file in sample_files:
            with open(sample_file) as f:
                data = yaml.safe_load(f)
            
            # Should parse without error
            project = Project.model_validate(data)
            assert project.id is not None
            assert project.name is not None
            assert project.app is not None
    
    def test_memory_service_uris(self):
        """Test that sample projects use memory:// for testing."""
        sample_files = list(SAMPLE_PROJECTS_DIR.glob("*.yaml"))
        
        for sample_file in sample_files:
            with open(sample_file) as f:
                data = yaml.safe_load(f)
            
            project = Project.model_validate(data)
            
            # All test projects should use in-memory services
            assert project.app.session_service_uri == "memory://"
            assert project.app.memory_service_uri == "memory://"
            assert project.app.artifact_service_uri == "memory://"

