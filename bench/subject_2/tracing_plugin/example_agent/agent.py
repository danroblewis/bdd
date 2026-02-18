"""Example agent that uses the TracingPlugin.

Run with:
    cd adk_playground/tracing_plugin
    adk run example_agent/

After the run, check the ./traces/ directory for the exported JSON file.
"""

import sys
from pathlib import Path
import importlib.util

# Load the tracing_plugin package from parent directory
def load_tracing_plugin():
    plugin_dir = Path(__file__).parent.parent
    
    # Load events module first
    events_spec = importlib.util.spec_from_file_location(
        "tracing_plugin.events",
        plugin_dir / "events.py"
    )
    events_module = importlib.util.module_from_spec(events_spec)
    sys.modules["tracing_plugin.events"] = events_module
    events_spec.loader.exec_module(events_module)
    
    # Load plugin module
    plugin_spec = importlib.util.spec_from_file_location(
        "tracing_plugin.plugin", 
        plugin_dir / "plugin.py"
    )
    plugin_module = importlib.util.module_from_spec(plugin_spec)
    sys.modules["tracing_plugin.plugin"] = plugin_module
    plugin_spec.loader.exec_module(plugin_module)
    
    return plugin_module.TracingPlugin

TracingPlugin = load_tracing_plugin()

from google.adk import Agent
from google.adk.apps import App
from google.adk.tools import exit_loop


def get_current_time() -> str:
    """Get the current date and time."""
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def calculate(expression: str) -> str:
    """Evaluate a mathematical expression.
    
    Args:
        expression: A mathematical expression to evaluate (e.g., "2 + 2", "10 * 5")
    """
    try:
        # Safe evaluation of simple math expressions
        result = eval(expression, {"__builtins__": {}}, {})
        return f"The result of {expression} is {result}"
    except Exception as e:
        return f"Error evaluating '{expression}': {e}"


# Create a simple agent with some tools
root_agent = Agent(
    name="traced_assistant",
    model="gemini-2.0-flash",  # Default model - can be changed in project config
    instruction="""You are a helpful assistant with access to tools.
    
When the user asks you something:
1. Use your tools if needed
2. Provide a helpful response
3. Call exit_loop when you're done to end the conversation

Available tools:
- get_current_time: Returns the current date and time
- calculate: Evaluates math expressions
- exit_loop: Call this when you're finished responding
""",
    tools=[
        get_current_time,
        calculate,
        exit_loop,
    ],
)


# Create tracing plugin that exports to ./traces/
tracing = TracingPlugin(
    export_path="./traces/run_{timestamp}.json",
    include_llm_content=True,
    include_tool_results=True,
)


# Create the app with the tracing plugin
app = App(
    name="example_agent",
    root_agent=root_agent,
    plugins=[tracing],
)

