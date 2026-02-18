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

"""Trace event definitions."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, Literal


# Event types that can be captured
EventType = Literal[
    "agent_start",
    "agent_end", 
    "tool_call",
    "tool_result",
    "model_call",
    "model_response",
    "state_change",
    "transfer",
]


@dataclass
class TraceEvent:
    """A single trace event from agent execution.
    
    Attributes:
        timestamp: Unix timestamp when the event occurred
        event_type: The type of event
        agent_name: Name of the agent that generated this event
        data: Additional event-specific data
    """
    timestamp: float
    event_type: EventType
    agent_name: str
    data: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return asdict(self)
    
    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict())
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TraceEvent":
        """Create from dictionary representation."""
        return cls(
            timestamp=data["timestamp"],
            event_type=data["event_type"],
            agent_name=data["agent_name"],
            data=data.get("data", {}),
        )
    
    @classmethod
    def from_json(cls, json_str: str) -> "TraceEvent":
        """Create from JSON string."""
        return cls.from_dict(json.loads(json_str))


@dataclass
class TraceExport:
    """Container for exporting traces with metadata.
    
    This format is compatible with ADK Playground's Run import feature.
    """
    version: int = 1
    exported_at: str = ""
    source: str = "adk-tracing-plugin"
    project_id: str | None = None
    project_name: str | None = None
    agent_id: str | None = None
    config: Dict[str, Any] = field(default_factory=dict)
    events: list[TraceEvent] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "version": self.version,
            "exportedAt": self.exported_at,
            "source": self.source,
            "projectId": self.project_id,
            "projectName": self.project_name,
            "agentId": self.agent_id,
            "config": self.config,
            "events": [e.to_dict() for e in self.events],
        }
    
    def to_json(self, indent: int = 2) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TraceExport":
        """Create from dictionary representation."""
        return cls(
            version=data.get("version", 1),
            exported_at=data.get("exportedAt", ""),
            source=data.get("source", "unknown"),
            project_id=data.get("projectId"),
            project_name=data.get("projectName"),
            agent_id=data.get("agentId"),
            config=data.get("config", {}),
            events=[TraceEvent.from_dict(e) for e in data.get("events", [])],
        )
    
    @classmethod
    def from_json(cls, json_str: str) -> "TraceExport":
        """Create from JSON string."""
        return cls.from_dict(json.loads(json_str))

