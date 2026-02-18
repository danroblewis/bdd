"""Generic agent runner for executing ADK agents within the playground.

This module provides a simple way to run ADK agents defined in the agents/
directory and retrieve their output. It handles:
- Dynamic model configuration (from project settings or defaults)
- Environment variable management (API keys)
- Session management
- Output extraction (from output_key or generated text)

Usage:
    from agent_runner import run_agent

    result = await run_agent(
        agent_name="prompt_generator",
        message="Generate a prompt for a weather assistant",
        model_config=project.app.models[0] if project.app.models else None,
        env_vars=project.app.env_vars,
    )
    
    if result["success"]:
        output = result["output"]
"""

import importlib
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


async def run_agent(
    agent_name: str,
    message: str,
    model_config: Optional[Any] = None,
    env_vars: Optional[Dict[str, str]] = None,
    output_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Run an ADK agent and return its output.
    
    Args:
        agent_name: Name of the agent directory under agents/ (e.g., "prompt_generator")
        message: The user message to send to the agent
        model_config: Optional model configuration object with provider, model_name, api_base
        env_vars: Optional environment variables to set (e.g., API keys)
        output_key: Optional key to extract from session state. If not provided,
                   uses the agent's output_key if defined, otherwise extracts
                   text from the generated response.
    
    Returns:
        Dict with:
        - success: bool
        - output: str (the agent's response)
        - error: str (if success is False)
        - traceback: str (if success is False)
    """
    from google.adk import Agent
    from google.adk.runners import Runner
    from google.adk.sessions.in_memory_session_service import InMemorySessionService
    from google.adk.memory.in_memory_memory_service import InMemoryMemoryService
    from google.adk.artifacts.in_memory_artifact_service import InMemoryArtifactService
    from google.genai import types
    
    # Track original env vars for restoration
    old_env = {}
    
    try:
        # Set API keys from provided env_vars
        if env_vars:
            for key in ["GOOGLE_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", 
                        "GROQ_API_KEY", "TOGETHER_API_KEY", "OPENROUTER_API_KEY"]:
                if key in env_vars:
                    old_env[key] = os.environ.get(key)
                    os.environ[key] = env_vars[key]
        
        # Load the agent module dynamically
        agents_dir = Path(__file__).parent / "agents" / agent_name
        if not agents_dir.exists():
            raise ValueError(f"Agent directory not found: {agents_dir}")
        
        # Add agents directory to path if not already there
        agents_parent = str(agents_dir.parent)
        if agents_parent not in sys.path:
            sys.path.insert(0, agents_parent)
        
        # Import the agent module
        try:
            agent_module = importlib.import_module(f"{agent_name}.agent")
            # Reload to pick up any changes
            importlib.reload(agent_module)
        except ImportError as e:
            raise ValueError(f"Failed to import agent module {agent_name}.agent: {e}")
        
        # Get the root_agent from the module
        if not hasattr(agent_module, "root_agent"):
            raise ValueError(f"Agent module {agent_name}.agent must define 'root_agent'")
        
        root_agent = agent_module.root_agent
        
        # Override model if model_config is provided
        if model_config:
            if hasattr(model_config, "provider") and model_config.provider == "litellm":
                from google.adk.models.lite_llm import LiteLlm
                model = LiteLlm(
                    model=model_config.model_name,
                    api_base=getattr(model_config, "api_base", None),
                )
            elif hasattr(model_config, "model_name"):
                model = model_config.model_name
            else:
                model = None
            
            if model:
                # Create a new agent with the overridden model
                root_agent = Agent(
                    name=root_agent.name,
                    model=model,
                    instruction=root_agent.instruction,
                    description=getattr(root_agent, "description", None),
                    tools=getattr(root_agent, "tools", None),
                    output_key=getattr(root_agent, "output_key", None),
                )
        
        # Determine output_key
        effective_output_key = output_key or getattr(root_agent, "output_key", None)
        
        # Create runner with in-memory services
        runner = Runner(
            app_name=agent_name,
            agent=root_agent,
            session_service=InMemorySessionService(),
            memory_service=InMemoryMemoryService(),
            artifact_service=InMemoryArtifactService(),
        )
        
        # Create session
        session = await runner.session_service.create_session(
            app_name=agent_name,
            user_id=f"{agent_name}_user",
        )
        
        # Run the agent
        generated_text = ""
        async for event in runner.run_async(
            session_id=session.id,
            user_id=f"{agent_name}_user",
            new_message=types.Content(
                role="user",
                parts=[types.Part.from_text(text=message)]
            ),
        ):
            # Collect text from events (fallback if no output_key)
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if hasattr(part, "text") and part.text:
                        generated_text += part.text
        
        # Extract output
        output = ""
        if effective_output_key:
            # Get from session state
            final_session = await runner.session_service.get_session(
                app_name=agent_name,
                user_id=f"{agent_name}_user",
                session_id=session.id,
            )
            output = final_session.state.get(effective_output_key, "").strip() if final_session else ""
        
        # Fall back to generated text if output_key didn't produce output
        if not output:
            output = generated_text.strip()
        
        # Close the runner
        await runner.close()
        
        return {
            "success": True,
            "output": output,
        }
        
    except Exception as e:
        import traceback
        logger.error(f"Agent {agent_name} failed: {e}", exc_info=True)
        return {
            "success": False,
            "output": None,
            "error": str(e),
            "traceback": traceback.format_exc(),
        }
    
    finally:
        # Restore original environment variables
        for key, value in old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def clean_code_output(code: str) -> str:
    """Clean up code output by removing markdown formatting.
    
    Args:
        code: Raw code string that may include markdown code blocks
    
    Returns:
        Clean code string
    """
    code = code.strip()
    
    # Remove markdown code blocks
    if code.startswith("```python"):
        code = code[9:]
    elif code.startswith("```"):
        code = code[3:]
    
    if code.endswith("```"):
        code = code[:-3]
    
    return code.strip()


def extract_json_from_text(text: str) -> str:
    """Extract JSON from text that may include markdown or other content.
    
    Args:
        text: Raw text that may contain JSON
    
    Returns:
        Extracted JSON string
    """
    text = text.strip()
    
    # Try to extract JSON if it's wrapped in markdown code blocks
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        parts = text.split("```")
        if len(parts) >= 2:
            text = parts[1].strip()
    
    # Try to find JSON object in the text
    json_start = text.find('{')
    json_end = text.rfind('}')
    if json_start != -1 and json_end != -1 and json_end > json_start:
        text = text[json_start:json_end + 1]
    
    return text

