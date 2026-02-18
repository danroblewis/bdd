"""Data models for the Docker sandbox.

Based on the design in DOCKER_PLAN.md.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class PatternType(str, Enum):
    """Type of pattern matching for allowlist entries."""
    EXACT = "exact"           # Exact domain match
    WILDCARD = "wildcard"     # Glob-style wildcards (* matches anything)
    REGEX = "regex"           # Full regex pattern


class AllowlistPattern(BaseModel):
    """A single pattern in the network allowlist."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    pattern: str
    pattern_type: PatternType = PatternType.WILDCARD
    added_at: Optional[datetime] = None
    source: str = "user"  # "auto", "user", "mcp:<name>", "approved"
    
    def matches(self, url: str) -> bool:
        """Check if this pattern matches the given URL.
        
        Args:
            url: The URL or host to check (e.g., "api.github.com" or 
                 "api.github.com/repos/...")
        
        Returns:
            True if this pattern matches the URL
        """
        if self.pattern_type == PatternType.EXACT:
            # Exact match or URL starts with pattern followed by /
            return url == self.pattern or url.startswith(self.pattern + "/")
        
        elif self.pattern_type == PatternType.WILDCARD:
            # Convert glob pattern to regex
            # Escape regex special chars except *
            regex = re.escape(self.pattern).replace(r"\*", ".*")
            try:
                return bool(re.match(f"^{regex}$", url))
            except re.error:
                return False
        
        elif self.pattern_type == PatternType.REGEX:
            # Strip "regex:" prefix if present
            pattern = self.pattern
            if pattern.startswith("regex:"):
                pattern = pattern[6:]
            try:
                return bool(re.match(pattern, url))
            except re.error:
                return False
        
        return False
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize for YAML storage."""
        return {
            "id": self.id,
            "pattern": self.pattern,
            "type": self.pattern_type.value,
            "added": self.added_at.isoformat() if self.added_at else None,
            "source": self.source,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AllowlistPattern":
        """Load from YAML dict."""
        return cls(
            id=data.get("id", str(uuid.uuid4())[:8]),
            pattern=data["pattern"],
            pattern_type=PatternType(data.get("type", "wildcard")),
            added_at=datetime.fromisoformat(data["added"]) if data.get("added") else None,
            source=data.get("source", "user"),
        )


class NetworkAllowlist(BaseModel):
    """Complete allowlist with auto and user-defined patterns."""
    auto: List[str] = Field(default_factory=list)  # Auto-populated, not persisted
    user: List[AllowlistPattern] = Field(default_factory=list)  # User-defined, persisted
    
    # Default allowed domains (LLM providers + infrastructure + internal communication)
    DEFAULT_LLM_DOMAINS: List[str] = [
        # LLM API providers
        "generativelanguage.googleapis.com",
        "api.anthropic.com",
        "api.openai.com",
        "*.openai.azure.com",  # Azure OpenAI (e.g., companyname.openai.azure.com)
        "api.groq.com",
        "api.mistral.ai",
        "api.together.xyz",
        # PyPI (for pip install in containers)
        "pypi.org",
        "files.pythonhosted.org",
        # npm registry (for npx in containers)
        "registry.npmjs.org",
        "npmjs.org",
        "*.npmjs.org",
        # GitHub (for package downloads)
        "github.com",
        "*.github.com",
        "raw.githubusercontent.com",
        "objects.githubusercontent.com",
        # Node.js downloads
        "nodejs.org",
        "*.nodejs.org",
        # Host communication (for agent events going through proxy)
        "host.docker.internal",
        # Internal container communication (host→agent via proxy)
        "sandbox-agent-*",  # Wildcard for agent containers
    ]
    
    def all_patterns(self) -> List[AllowlistPattern]:
        """Get all patterns (auto converted to AllowlistPattern + user)."""
        auto_patterns = []
        for i, p in enumerate(self.auto):
            # Detect pattern type from pattern string
            if "*" in p or "?" in p:
                ptype = PatternType.WILDCARD
            elif p.startswith("^") or p.endswith("$"):
                ptype = PatternType.REGEX
            else:
                ptype = PatternType.EXACT
            
            auto_patterns.append(AllowlistPattern(
                id=f"auto-{i}",
                pattern=p, 
                pattern_type=ptype, 
                source="auto"
            ))
        return auto_patterns + self.user
    
    def matches(self, url: str) -> Optional[AllowlistPattern]:
        """Check if any pattern matches the URL.
        
        Returns:
            The matching pattern, or None if no match
        """
        for pattern in self.all_patterns():
            if pattern.matches(url):
                return pattern
        return None
    
    def add_user_pattern(
        self,
        pattern: str,
        pattern_type: PatternType = PatternType.WILDCARD,
        source: str = "user",
    ) -> AllowlistPattern:
        """Add a user-defined pattern."""
        p = AllowlistPattern(
            pattern=pattern,
            pattern_type=pattern_type,
            added_at=datetime.now(),
            source=source,
        )
        self.user.append(p)
        return p
    
    def remove_user_pattern(self, pattern_id: str) -> bool:
        """Remove a user-defined pattern by ID."""
        for i, p in enumerate(self.user):
            if p.id == pattern_id:
                self.user.pop(i)
                return True
        return False
    
    def to_yaml_dict(self) -> Dict[str, Any]:
        """Serialize user patterns for YAML storage."""
        return {
            "user": [p.to_dict() for p in self.user]
        }
    
    @classmethod
    def from_yaml_dict(cls, data: Dict[str, Any]) -> "NetworkAllowlist":
        """Load from YAML dict."""
        user_patterns = []
        for p in data.get("user", []):
            user_patterns.append(AllowlistPattern.from_dict(p))
        return cls(user=user_patterns)
    
    def with_defaults(self) -> "NetworkAllowlist":
        """Return a copy with default LLM domains added to auto."""
        return NetworkAllowlist(
            auto=list(set(self.auto + self.DEFAULT_LLM_DOMAINS)),
            user=list(self.user),
        )


class MCPServerSandboxConfig(BaseModel):
    """Configuration for an MCP server in the sandbox."""
    name: str
    transport: str = "stdio"  # "stdio" or "sse"
    command: Optional[str] = None
    args: List[str] = Field(default_factory=list)
    env: Dict[str, str] = Field(default_factory=dict)
    allowed_domains: List[str] = Field(default_factory=list)  # Known domains this MCP uses
    memory_limit_mb: int = 256
    cpu_limit: float = 0.5


class VolumeMount(BaseModel):
    """A volume mount configuration for the Docker sandbox."""
    host_path: str  # Path on the host machine
    container_path: str  # Path inside the container
    mode: str = "ro"  # "ro" (read-only) or "rw" (read-write)
    
    def to_docker_volume(self) -> Dict[str, Any]:
        """Convert to Docker SDK volume format."""
        return {self.host_path: {"bind": self.container_path, "mode": self.mode}}


class SandboxConfig(BaseModel):
    """App-scoped sandbox configuration (persisted in project YAML)."""
    enabled: bool = False
    # If true, allow outbound connections to any host (no approvals/deny).
    # Traffic is still routed through the gateway proxy via the internal network.
    allow_all_network: bool = False
    allowlist: NetworkAllowlist = Field(default_factory=NetworkAllowlist)
    unknown_action: str = "ask"  # "ask", "deny", "allow"
    approval_timeout: int = 120
    agent_memory_limit_mb: int = 512
    agent_cpu_limit: float = 1.0
    mcp_memory_limit_mb: int = 256  # Per MCP container
    mcp_cpu_limit: float = 0.5  # Per MCP container
    run_timeout: int = 300
    volume_mounts: List[VolumeMount] = Field(default_factory=list)  # Host directories to mount


class NetworkRequestStatus(str, Enum):
    """Status of a network request."""
    PENDING = "pending"
    ALLOWED = "allowed"
    DENIED = "denied"
    COMPLETED = "completed"
    ERROR = "error"


class NetworkRequest(BaseModel):
    """A network request captured by the proxy."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp: datetime = Field(default_factory=datetime.now)
    method: str
    url: str
    host: str
    status: NetworkRequestStatus = NetworkRequestStatus.PENDING
    source: str = "agent"  # "agent" or "mcp:<server_name>"
    matched_pattern: Optional[str] = None  # Which pattern allowed this request
    source_agent: Optional[str] = None  # Which agent triggered the MCP call
    response_status: Optional[int] = None
    response_time_ms: Optional[float] = None
    response_size: Optional[int] = None
    is_llm_provider: bool = False
    headers: Optional[Dict[str, str]] = Field(default_factory=dict)


class MCPContainerStatus(BaseModel):
    """Runtime status of an MCP server container."""
    name: str
    container_id: Optional[str] = None
    status: str = "pending"  # "pending", "starting", "running", "stopped", "error"
    transport: str = "stdio"
    endpoint: Optional[str] = None  # For SSE: "http://mcp-github:8080"
    error: Optional[str] = None


class ApprovalDecision(BaseModel):
    """User's decision when approving a network request."""
    request_id: str
    action: str  # "deny", "allow_once", "allow_pattern"
    pattern: Optional[str] = None  # The pattern to allow (if allow_pattern)
    pattern_type: PatternType = PatternType.WILDCARD
    persist: bool = False  # Save to project config


class SandboxStatus(str, Enum):
    """Status of the sandbox."""
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    ERROR = "error"


class SandboxInstance(BaseModel):
    """Runtime state of a sandbox instance."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    app_id: str
    status: SandboxStatus = SandboxStatus.STOPPED
    gateway_container_id: Optional[str] = None
    agent_container_id: Optional[str] = None
    mcp_containers: List[MCPContainerStatus] = Field(default_factory=list)
    network_requests: List[NetworkRequest] = Field(default_factory=list)
    pending_approvals: List[str] = Field(default_factory=list)  # Request IDs awaiting approval
    started_at: Optional[datetime] = None
    error: Optional[str] = None
    
    # Configuration used for this instance
    config: Optional[SandboxConfig] = None

