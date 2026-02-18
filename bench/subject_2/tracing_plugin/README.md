# ADK Tracing Plugin

A plugin for Google ADK that captures detailed execution traces of agent runs, enabling debugging, visualization, and analysis of agent behavior.

## Features

- **Complete execution tracing** - Captures agent lifecycle, model calls, tool invocations, and state changes
- **Structured event format** - Well-defined event schema for easy parsing and analysis
- **Multiple output modes** - Callback-based streaming, file export, or in-memory collection
- **Zero modification to agents** - Drop-in plugin that works with any ADK agent
- **Compatible with ADK Playground** - Export files can be imported into the Run visualization

## Installation

```bash
# Copy the plugin to your project
cp -r adk_playground/tracing_plugin /path/to/your/project/
```

## Quick Start

### With `adk run`

Create an `agent.py` that uses the tracing plugin:

```python
from google.adk import Agent
from google.adk.apps import App
from tracing_plugin import TracingPlugin

root_agent = Agent(
    name="my_agent",
    model="gemini-2.0-flash",
    instruction="You are a helpful assistant.",
)

# Create tracing plugin - exports to JSON on completion
tracing = TracingPlugin(
    export_path="./traces/run_{timestamp}.json",
    include_llm_content=True,
)

app = App(
    name="my_app",
    root_agent=root_agent,
    plugins=[tracing],
)
```

Run your agent:
```bash
adk run my_agent/
```

After the run completes, find your trace in `./traces/run_2024-12-09T12-30-00.json`.

### Programmatic Usage

```python
from google.adk import Agent, Runner
from google.adk.sessions import InMemorySessionService
from tracing_plugin import TracingPlugin

# Collect events in memory
events = []
tracing = TracingPlugin(on_event=lambda e: events.append(e))

runner = Runner(
    agent=my_agent,
    session_service=InMemorySessionService(),
    plugins=[tracing],
)

# Run your agent
async for event in runner.run_async(...):
    pass

# Access captured events
print(f"Captured {len(tracing.events)} events")
tracing.export_json("my_run.json")
```

### Real-time Streaming

```python
import asyncio
from tracing_plugin import TracingPlugin

async def stream_to_websocket(event):
    await websocket.send(event.to_json())

tracing = TracingPlugin(on_event=stream_to_websocket)
```

## Event Types

| Event Type | Description | Data Fields |
|------------|-------------|-------------|
| `agent_start` | Agent begins execution | `instruction` |
| `agent_end` | Agent completes execution | - |
| `model_call` | LLM request sent | `contents`, `system_instruction`, `tool_names` |
| `model_response` | LLM response received | `parts`, `finish_reason`, `token_counts` |
| `tool_call` | Tool invocation started | `tool_name`, `args` |
| `tool_result` | Tool returned result | `tool_name`, `result` |
| `state_change` | Session state modified | `state_delta` |

## Event Schema

```json
{
  "timestamp": 1702123456.789,
  "event_type": "tool_call",
  "agent_name": "researcher",
  "data": {
    "tool_name": "web_search",
    "args": {"query": "ADK python documentation"}
  }
}
```

## Export Format

The JSON export includes metadata for import into visualization tools:

```json
{
  "version": 1,
  "exportedAt": "2024-12-09T12:30:00.000Z",
  "source": "adk-tracing-plugin",
  "config": {
    "include_llm_content": true
  },
  "events": [
    { "timestamp": ..., "event_type": "agent_start", ... },
    ...
  ]
}
```

## Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `export_path` | `str` | `None` | Path to export JSON on completion. Supports `{timestamp}` placeholder. |
| `on_event` | `Callable` | `None` | Callback function for each event (sync or async) |
| `include_llm_content` | `bool` | `True` | Include full LLM request/response content |
| `include_tool_results` | `bool` | `True` | Include full tool results |
| `max_content_length` | `int` | `None` | Truncate content fields to this length |

## Future Enhancements

### OpenTelemetry Integration
```python
from tracing_plugin import TracingPlugin
from tracing_plugin.exporters import OTelExporter

tracing = TracingPlugin(
    exporters=[OTelExporter(endpoint="http://jaeger:4317")]
)
```

### Langfuse/LangSmith Export
```python
from tracing_plugin.exporters import LangfuseExporter

tracing = TracingPlugin(
    exporters=[LangfuseExporter(api_key="...")]
)
```

### Chrome Trace Format
Export traces viewable in Chrome's `chrome://tracing`:
```python
tracing.export_chrome_trace("trace.json")
```

### Streaming Formats
- Server-Sent Events (SSE)
- WebSocket
- NDJSON (newline-delimited JSON)

## Import into ADK Playground

The exported JSON files are compatible with ADK Playground's Run visualization:

1. Open ADK Playground
2. Navigate to the Run tab
3. Click "Load" button
4. Select your exported trace file

## Contributing

This plugin is part of the ADK Playground project. Contributions welcome!

## License

Apache 2.0 - Same as ADK

