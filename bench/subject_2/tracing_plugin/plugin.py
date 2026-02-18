# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""ADK Tracing Plugin implementation."""

from __future__ import annotations

import asyncio
import atexit
import inspect
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Optional, TYPE_CHECKING

from google.adk.plugins import BasePlugin

from .events import TraceEvent, TraceExport

if TYPE_CHECKING:
    from google.adk.agents.base_agent import BaseAgent
    from google.adk.agents.callback_context import CallbackContext
    from google.adk.agents.invocation_context import InvocationContext
    from google.adk.events.event import Event
    from google.adk.models.llm_request import LlmRequest
    from google.adk.models.llm_response import LlmResponse
    from google.adk.tools.base_tool import BaseTool
    from google.adk.tools.tool_context import ToolContext


class TracingPlugin(BasePlugin):
    """Plugin that captures detailed execution traces of ADK agent runs.
    
    This plugin intercepts all agent, model, and tool callbacks to build
    a comprehensive trace of the agent's execution. Traces can be:
    - Collected in memory for programmatic access
    - Streamed via callback for real-time monitoring
    - Exported to JSON files for later analysis
    
    Example:
        # Export to file on completion
        tracing = TracingPlugin(export_path="./traces/run_{timestamp}.json")
        
        # Stream events via callback
        tracing = TracingPlugin(on_event=lambda e: print(e.to_json()))
        
        # Collect in memory
        tracing = TracingPlugin()
        # ... run agent ...
        print(f"Captured {len(tracing.events)} events")
    
    Args:
        export_path: Path to export JSON on run completion. Supports {timestamp} placeholder.
        on_event: Callback function invoked for each event. Can be sync or async.
        include_llm_content: Whether to include full LLM request/response content.
        include_tool_results: Whether to include full tool results.
        max_content_length: Maximum length for content fields (None = no limit).
    """
    
    def __init__(
        self,
        export_path: Optional[str] = None,
        on_event: Optional[Callable[[TraceEvent], Any]] = None,
        include_llm_content: bool = True,
        include_tool_results: bool = True,
        max_content_length: Optional[int] = None,
    ):
        super().__init__(name="tracing")
        self.export_path = export_path
        self.on_event = on_event
        self.include_llm_content = include_llm_content
        self.include_tool_results = include_tool_results
        self.max_content_length = max_content_length
        
        # State
        self.events: list[TraceEvent] = []
        self.token_counts = {"input": 0, "output": 0}
        self._start_time: Optional[float] = None
        self._root_agent_name: Optional[str] = None
        
        # Register atexit handler for export
        if self.export_path:
            atexit.register(self._atexit_export)
    
    def _atexit_export(self):
        """Export trace on process exit if we have events."""
        if self.events and self.export_path:
            try:
                self.export_json(self.export_path)
            except Exception as e:
                print(f"[TracingPlugin] Failed to export on exit: {e}")
    
    def _truncate(self, value: Any) -> Any:
        """Truncate value if max_content_length is set."""
        if self.max_content_length is None:
            return value
        if isinstance(value, str) and len(value) > self.max_content_length:
            return value[:self.max_content_length] + "..."
        return value
    
    def _emit(self, event: TraceEvent):
        """Emit an event to all outputs."""
        self.events.append(event)
        
        if self.on_event:
            result = self.on_event(event)
            # Handle async callbacks
            if asyncio.iscoroutine(result):
                asyncio.create_task(result)
    
    def _serialize_contents(self, contents) -> list:
        """Serialize LLM contents to a structured format for display."""
        if not contents:
            return []
        
        result = []
        for content in contents:
            content_data = {
                "role": getattr(content, "role", "unknown"),
                "parts": []
            }
            
            if hasattr(content, "parts") and content.parts:
                for part in content.parts:
                    part_data = {}
                    
                    # Text content
                    if hasattr(part, "text") and part.text:
                        part_data["type"] = "text"
                        part_data["text"] = self._truncate(part.text)
                    
                    # Function call
                    elif hasattr(part, "function_call") and part.function_call:
                        fc = part.function_call
                        part_data["type"] = "function_call"
                        part_data["name"] = getattr(fc, "name", "unknown")
                        part_data["args"] = dict(getattr(fc, "args", {})) if hasattr(fc, "args") else {}
                    
                    # Function response
                    elif hasattr(part, "function_response") and part.function_response:
                        fr = part.function_response
                        part_data["type"] = "function_response"
                        part_data["name"] = getattr(fr, "name", "unknown")
                        response = getattr(fr, "response", None)
                        if response:
                            part_data["response"] = self._truncate(response) if self.include_tool_results else "(truncated)"
                    
                    # Thought (for reasoning models)
                    if hasattr(part, "thought") and part.thought:
                        part_data["thought"] = True
                    
                    if part_data:
                        content_data["parts"].append(part_data)
            
            result.append(content_data)
        
        return result
    
    def export_json(self, path: Optional[str] = None) -> str:
        """Export trace to a JSON file.
        
        Args:
            path: File path. If None, uses self.export_path. 
                  Supports {timestamp} placeholder.
        
        Returns:
            The actual path the file was written to.
        """
        export_path = path or self.export_path
        if not export_path:
            raise ValueError("No export path specified")
        
        # Replace {timestamp} placeholder
        timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
        export_path = export_path.replace("{timestamp}", timestamp)
        
        # Ensure directory exists
        Path(export_path).parent.mkdir(parents=True, exist_ok=True)
        
        # Build export
        export = TraceExport(
            exported_at=datetime.now().isoformat(),
            agent_id=self._root_agent_name,
            config={
                "include_llm_content": self.include_llm_content,
                "include_tool_results": self.include_tool_results,
                "max_content_length": self.max_content_length,
            },
            events=self.events,
        )
        
        with open(export_path, "w") as f:
            f.write(export.to_json())
        
        print(f"[TracingPlugin] Exported {len(self.events)} events to {export_path}")
        return export_path
    
    def clear(self):
        """Clear all captured events."""
        self.events = []
        self.token_counts = {"input": 0, "output": 0}
        self._start_time = None
    
    # =========================================================================
    # BasePlugin Callbacks
    # =========================================================================
    
    async def before_run_callback(
        self, *, invocation_context: "InvocationContext"
    ):
        """Called before the runner starts."""
        self._start_time = time.time()
        if hasattr(invocation_context, "agent") and invocation_context.agent:
            self._root_agent_name = invocation_context.agent.name
        return None
    
    async def after_run_callback(
        self, *, invocation_context: "InvocationContext"
    ):
        """Called after the runner completes."""
        # Export if path is configured (in addition to atexit)
        if self.export_path and self.events:
            self.export_json()
        return None
    
    async def on_event_callback(
        self, *, invocation_context: "InvocationContext", event: "Event"
    ):
        """Called for every event - captures state changes from output_key etc."""
        # Check if the event has state_delta (e.g., from output_key)
        if hasattr(event, "actions") and event.actions and event.actions.state_delta:
            state_delta = event.actions.state_delta
            if state_delta:
                agent_name = getattr(event, "author", None) or "system"
                self._emit(TraceEvent(
                    timestamp=time.time(),
                    event_type="state_change",
                    agent_name=agent_name,
                    data={
                        "state_delta": dict(state_delta),
                    },
                ))
        return None
    
    async def before_agent_callback(
        self, *, agent: "BaseAgent", callback_context: "CallbackContext"
    ):
        """Called before an agent runs."""
        instruction = ""
        if hasattr(agent, "instruction") and agent.instruction:
            instruction = self._truncate(agent.instruction) if self.include_llm_content else "(present)"
        
        self._emit(TraceEvent(
            timestamp=time.time(),
            event_type="agent_start",
            agent_name=agent.name,
            data={"instruction": instruction},
        ))
        return None
    
    async def after_agent_callback(
        self, *, agent: "BaseAgent", callback_context: "CallbackContext"
    ):
        """Called after an agent runs."""
        self._emit(TraceEvent(
            timestamp=time.time(),
            event_type="agent_end",
            agent_name=agent.name,
            data={},
        ))
        return None
    
    async def before_model_callback(
        self, *, callback_context: "CallbackContext", llm_request: "LlmRequest"
    ):
        """Called before an LLM call."""
        data: Dict[str, Any] = {}
        
        if self.include_llm_content:
            # Serialize contents to structured format
            if hasattr(llm_request, "contents") and llm_request.contents:
                data["contents"] = self._serialize_contents(llm_request.contents)
            
            # Get system instruction if present
            if hasattr(llm_request, "config") and llm_request.config:
                if hasattr(llm_request.config, "system_instruction"):
                    si = llm_request.config.system_instruction
                    if si and hasattr(si, "parts"):
                        system_instruction = "".join(
                            getattr(p, "text", "") for p in si.parts if hasattr(p, "text")
                        )
                        data["system_instruction"] = self._truncate(system_instruction)
        
        # Get tool names (always include for context)
        tool_names = []
        if hasattr(llm_request, "tools_dict") and llm_request.tools_dict:
            tool_names = list(llm_request.tools_dict.keys())
        data["tool_names"] = tool_names
        data["tool_count"] = len(tool_names)
        
        agent_name = getattr(callback_context, "agent_name", None) or "system"
        self._emit(TraceEvent(
            timestamp=time.time(),
            event_type="model_call",
            agent_name=agent_name,
            data=data,
        ))
        return None
    
    async def after_model_callback(
        self, *, callback_context: "CallbackContext", llm_response: "LlmResponse"
    ):
        """Called after an LLM call."""
        data: Dict[str, Any] = {}
        
        if self.include_llm_content:
            # Serialize the response content
            response_parts = []
            if hasattr(llm_response, "content") and llm_response.content:
                if hasattr(llm_response.content, "parts"):
                    for part in llm_response.content.parts:
                        part_data = {}
                        
                        if hasattr(part, "text") and part.text:
                            part_data["type"] = "text"
                            part_data["text"] = self._truncate(part.text)
                            if hasattr(part, "thought") and part.thought:
                                part_data["thought"] = True
                        
                        elif hasattr(part, "function_call") and part.function_call:
                            fc = part.function_call
                            part_data["type"] = "function_call"
                            part_data["name"] = getattr(fc, "name", "unknown")
                            part_data["args"] = dict(getattr(fc, "args", {})) if hasattr(fc, "args") else {}
                        
                        if part_data:
                            response_parts.append(part_data)
            data["parts"] = response_parts
        
        # Track token usage if available
        if hasattr(llm_response, "usage_metadata") and llm_response.usage_metadata:
            usage = llm_response.usage_metadata
            input_tokens = 0
            output_tokens = 0
            if hasattr(usage, "prompt_token_count"):
                input_tokens = usage.prompt_token_count or 0
                self.token_counts["input"] += input_tokens
            if hasattr(usage, "candidates_token_count"):
                output_tokens = usage.candidates_token_count or 0
                self.token_counts["output"] += output_tokens
            data["tokens"] = {"input": input_tokens, "output": output_tokens}
        
        data["token_counts"] = dict(self.token_counts)
        
        # Get finish reason
        if hasattr(llm_response, "candidates") and llm_response.candidates:
            if len(llm_response.candidates) > 0:
                finish_reason = getattr(llm_response.candidates[0], "finish_reason", None)
                if finish_reason:
                    data["finish_reason"] = str(finish_reason)
        
        agent_name = getattr(callback_context, "agent_name", None) or "system"
        self._emit(TraceEvent(
            timestamp=time.time(),
            event_type="model_response",
            agent_name=agent_name,
            data=data,
        ))
        return None
    
    async def before_tool_callback(
        self,
        *,
        tool: "BaseTool",
        tool_args: dict[str, Any],
        tool_context: "ToolContext",
    ):
        """Called before a tool is executed."""
        agent_name = getattr(tool_context, "agent_name", None) or "system"
        
        self._emit(TraceEvent(
            timestamp=time.time(),
            event_type="tool_call",
            agent_name=agent_name,
            data={
                "tool_name": tool.name,
                "args": tool_args,
            },
        ))
        return None
    
    async def after_tool_callback(
        self,
        *,
        tool: "BaseTool",
        tool_args: dict[str, Any],
        tool_context: "ToolContext",
        result: dict,
    ):
        """Called after a tool is executed."""
        agent_name = getattr(tool_context, "agent_name", None) or "system"
        
        # Track state changes from tools
        if hasattr(tool_context, "_event_actions") and tool_context._event_actions.state_delta:
            self._emit(TraceEvent(
                timestamp=time.time(),
                event_type="state_change",
                agent_name=agent_name,
                data={
                    "state_delta": dict(tool_context._event_actions.state_delta),
                },
            ))
        
        # Emit tool result
        result_data: Dict[str, Any] = {"tool_name": tool.name}
        if self.include_tool_results:
            result_data["result"] = result
        else:
            result_data["result"] = "(truncated)"
        
        self._emit(TraceEvent(
            timestamp=time.time(),
            event_type="tool_result",
            agent_name=agent_name,
            data=result_data,
        ))
        return None

