"""Pydantic models for the ADK Playground API."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, Field
from enum import Enum


# ============================================================================
# Enums
# ============================================================================

class AgentType(str, Enum):
    LLM = "LlmAgent"
    SEQUENTIAL = "SequentialAgent"
    LOOP = "LoopAgent"
    PARALLEL = "ParallelAgent"


class ServiceType(str, Enum):
    MEMORY = "memory://"
    SQLITE = "sqlite://"
    POSTGRES = "postgresql://"


class MCPConnectionType(str, Enum):
    STDIO = "stdio"
    SSE = "sse"
    HTTP = "http"


# ============================================================================
# State Key Configuration
# ============================================================================

class StateKeyConfig(BaseModel):
    """Configuration for a session state key."""
    name: str
    description: str = ""
    type: Literal["string", "number", "boolean", "object", "array"] = "string"
    default_value: Optional[Any] = None
    scope: Literal["session", "user", "app", "temp"] = "session"


# ============================================================================
# Tool Configurations
# ============================================================================

class FunctionToolConfig(BaseModel):
    """Configuration for a Python function tool."""
    type: Literal["function"] = "function"
    name: str
    description: str = ""
    module_path: str  # e.g., "tools.my_module.my_function"
    
    
class MCPServerConfig(BaseModel):
    """Configuration for an MCP server."""
    name: str
    description: str = ""
    connection_type: MCPConnectionType = MCPConnectionType.STDIO
    # Stdio params
    command: Optional[str] = None
    args: List[str] = Field(default_factory=list)
    env: Dict[str, str] = Field(default_factory=dict)
    # SSE/HTTP params
    url: Optional[str] = None
    headers: Dict[str, str] = Field(default_factory=dict)
    timeout: float = 10.0
    # Tool filtering (null = no filter/all tools, [] = no tools, ["a","b"] = only those tools)
    tool_filter: Optional[List[str]] = None
    tool_name_prefix: Optional[str] = None


class MCPToolConfig(BaseModel):
    """Configuration for an MCP toolset."""
    type: Literal["mcp"] = "mcp"
    server: MCPServerConfig


class AgentToolConfig(BaseModel):
    """Configuration for wrapping an agent as a tool."""
    type: Literal["agent"] = "agent"
    agent_id: str
    skip_summarization: bool = False


class BuiltinToolConfig(BaseModel):
    """Configuration for a built-in ADK tool."""
    type: Literal["builtin"] = "builtin"
    name: str  # e.g., "google_search", "exit_loop", "load_memory"


class SkillSetToolConfig(BaseModel):
    """Configuration for a SkillSet as a tool."""
    type: Literal["skillset"] = "skillset"
    skillset_id: str  # Reference to project.skillsets[].id


ToolConfig = Union[FunctionToolConfig, MCPToolConfig, AgentToolConfig, BuiltinToolConfig, SkillSetToolConfig]


# ============================================================================
# Agent Configurations
# ============================================================================

class ModelConfig(BaseModel):
    """Configuration for the LLM model."""
    provider: Literal["gemini", "litellm", "anthropic", "openai", "groq", "together"] = "gemini"
    model_name: str = "gemini-2.0-flash"
    # LiteLLM specific
    api_base: Optional[str] = None
    fallbacks: List[str] = Field(default_factory=list)
    # Generation config
    temperature: Optional[float] = None
    max_output_tokens: Optional[int] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    # Retry and timeout settings (especially useful for local models like Ollama)
    num_retries: Optional[int] = None  # Number of retries on failure (default: 3 for litellm)
    request_timeout: Optional[float] = None  # Timeout in seconds per request (default: 600)
    # Marker for linking to an App model - if set, this config mirrors an App model
    app_model_id: Optional[str] = Field(default=None, alias="_appModelId")
    
    model_config = {"populate_by_name": True, "by_alias": True}


class CallbackConfig(BaseModel):
    """Configuration for a callback function."""
    module_path: str
    

class LlmAgentConfig(BaseModel):
    """Configuration for an LlmAgent."""
    type: Literal["LlmAgent"] = "LlmAgent"
    id: str
    name: str
    description: str = ""
    model: Optional[ModelConfig] = None
    instruction: str = ""
    output_key: Optional[str] = None
    include_contents: Literal["default", "none"] = "default"
    disallow_transfer_to_parent: bool = False
    disallow_transfer_to_peers: bool = False
    tools: List[ToolConfig] = Field(default_factory=list)
    sub_agents: List[str] = Field(default_factory=list)  # Agent IDs
    # Callbacks
    before_agent_callbacks: List[CallbackConfig] = Field(default_factory=list)
    after_agent_callbacks: List[CallbackConfig] = Field(default_factory=list)
    before_model_callbacks: List[CallbackConfig] = Field(default_factory=list)
    after_model_callbacks: List[CallbackConfig] = Field(default_factory=list)
    before_tool_callbacks: List[CallbackConfig] = Field(default_factory=list)
    after_tool_callbacks: List[CallbackConfig] = Field(default_factory=list)


class SequentialAgentConfig(BaseModel):
    """Configuration for a SequentialAgent."""
    type: Literal["SequentialAgent"] = "SequentialAgent"
    id: str
    name: str
    description: str = ""
    sub_agents: List[str] = Field(default_factory=list)
    before_agent_callbacks: List[CallbackConfig] = Field(default_factory=list)
    after_agent_callbacks: List[CallbackConfig] = Field(default_factory=list)


class LoopAgentConfig(BaseModel):
    """Configuration for a LoopAgent."""
    type: Literal["LoopAgent"] = "LoopAgent"
    id: str
    name: str
    description: str = ""
    sub_agents: List[str] = Field(default_factory=list)
    max_iterations: Optional[int] = None
    before_agent_callbacks: List[CallbackConfig] = Field(default_factory=list)
    after_agent_callbacks: List[CallbackConfig] = Field(default_factory=list)


class ParallelAgentConfig(BaseModel):
    """Configuration for a ParallelAgent."""
    type: Literal["ParallelAgent"] = "ParallelAgent"
    id: str
    name: str
    description: str = ""
    sub_agents: List[str] = Field(default_factory=list)
    before_agent_callbacks: List[CallbackConfig] = Field(default_factory=list)
    after_agent_callbacks: List[CallbackConfig] = Field(default_factory=list)


AgentConfig = Union[LlmAgentConfig, SequentialAgentConfig, LoopAgentConfig, ParallelAgentConfig]


# ============================================================================
# Plugin Configurations
# ============================================================================

class PluginConfig(BaseModel):
    """Configuration for a plugin."""
    type: Literal[
        "ReflectAndRetryToolPlugin",
        "ContextFilterPlugin",
        "LoggingPlugin",
        "GlobalInstructionPlugin",
        "SaveFilesAsArtifactsPlugin",
        "MultimodalToolResultsPlugin"
    ]
    name: str = ""
    
    # ReflectAndRetryToolPlugin options
    max_retries: Optional[int] = None
    throw_exception_if_retry_exceeded: Optional[bool] = None
    
    # ContextFilterPlugin options
    num_invocations_to_keep: Optional[int] = None
    
    # GlobalInstructionPlugin options
    global_instruction: Optional[str] = None


# ============================================================================
# App Configuration
# ============================================================================

class CompactionConfig(BaseModel):
    """Configuration for event compaction."""
    enabled: bool = False
    max_events: int = 100
    summarize: bool = True


class ContextCacheConfig(BaseModel):
    """Configuration for context caching."""
    enabled: bool = False
    ttl_seconds: int = 3600


class ResumabilityConfig(BaseModel):
    """Configuration for resumability."""
    enabled: bool = False


class ArtifactConfig(BaseModel):
    """Configuration for an artifact."""
    name: str
    description: str = ""
    type: Literal["file", "image", "data"] = "file"


class AppModelConfig(BaseModel):
    """Configuration for a model preset in the app."""
    id: str
    name: str
    provider: Literal["gemini", "litellm", "anthropic", "openai", "groq", "together"] = "gemini"
    model_name: str = "gemini-2.0-flash"
    api_base: Optional[str] = None
    temperature: Optional[float] = None
    max_output_tokens: Optional[int] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    # Retry and timeout settings
    num_retries: Optional[int] = None  # Number of retries on failure
    request_timeout: Optional[float] = None  # Timeout in seconds per request
    is_default: bool = False


class AppConfig(BaseModel):
    """Full configuration for an ADK App."""
    id: str
    name: str
    description: str = ""
    
    # Root agent
    root_agent_id: Optional[str] = None
    
    # Services - use URI scheme to select implementation:
    # Session: memory://, sqlite://{path}, postgresql://{conn}, mysql://{conn}, agentengine://{project}/{location}/{engine_id}
    # Memory: memory://, rag://{corpus}, agentengine://{project}/{location}/{engine_id}
    # Artifact: memory://, file://{path}, gs://{bucket}
    session_service_uri: str = "sqlite://./sessions.db"
    memory_service_uri: str = "memory://"
    artifact_service_uri: str = "file://./artifacts"
    
    # Configuration
    compaction: CompactionConfig = Field(default_factory=CompactionConfig)
    context_cache: ContextCacheConfig = Field(default_factory=ContextCacheConfig)
    resumability: ResumabilityConfig = Field(default_factory=ResumabilityConfig)
    
    # Plugins
    plugins: List[PluginConfig] = Field(default_factory=list)
    
    # State keys
    state_keys: List[StateKeyConfig] = Field(default_factory=list)
    
    # Artifacts
    artifacts: List[ArtifactConfig] = Field(default_factory=list)
    
    # Models
    models: List[AppModelConfig] = Field(default_factory=list)
    default_model_id: Optional[str] = None
    
    # Environment variables (for API keys, etc.)
    env_vars: Dict[str, str] = Field(default_factory=dict)
    
    # Sandbox configuration (network allowlist, etc.)
    # Uses Dict to avoid circular imports with sandbox/models.py
    sandbox: Optional[Dict[str, Any]] = None


# ============================================================================
# Project (Full workspace)
# ============================================================================

class CustomToolDefinition(BaseModel):
    """A custom Python tool defined by the user."""
    id: str
    name: str
    description: str = ""
    module_path: str  # e.g., "my_tools.utilities.helper"
    code: str  # Python code
    state_keys_used: List[str] = Field(default_factory=list)


class CustomCallbackDefinition(BaseModel):
    """A custom Python callback defined by the user."""
    id: str
    name: str
    description: str = ""
    module_path: str  # e.g., "callbacks.my_callbacks.logger"
    code: str  # Python code
    state_keys_used: List[str] = Field(default_factory=list)


class WatchExpression(BaseModel):
    """A tool watch expression for monitoring MCP tool results."""
    id: str
    serverName: str
    toolName: str
    args: Dict[str, Any] = Field(default_factory=dict)
    transform: Optional[str] = None


class SkillSetSourceConfig(BaseModel):
    """Configuration for a source in a SkillSet."""
    id: str
    type: Literal["file", "url", "text"] = "text"
    name: str  # Display name
    path: Optional[str] = None  # File path or URL
    text: Optional[str] = None  # Direct text content
    added_at: float = 0.0


class SkillSetConfig(BaseModel):
    """Configuration for a SkillSet (vector database toolset)."""
    id: str
    name: str
    description: str = ""
    
    # Model configuration for embeddings
    embedding_model: Optional[str] = None  # None = use app default
    app_model_id: Optional[str] = None  # Reference to app model
    
    # External vector store (placeholder for future)
    external_store_type: Optional[Literal["pinecone", "weaviate", "qdrant", "chromadb"]] = None
    external_store_config: Dict[str, Any] = Field(default_factory=dict)
    
    # Tool settings
    search_enabled: bool = True
    preload_enabled: bool = True
    preload_top_k: int = 3
    preload_min_score: float = 0.4
    
    # Sources
    sources: List[SkillSetSourceConfig] = Field(default_factory=list)
    
    # Entry count (for display)
    entry_count: int = 0


class Project(BaseModel):
    """A complete ADK Playground project."""
    id: str
    name: str
    description: str = ""
    
    # App configuration
    app: AppConfig
    
    # All agents
    agents: List[AgentConfig] = Field(default_factory=list)
    
    # Custom tools
    custom_tools: List[CustomToolDefinition] = Field(default_factory=list)
    custom_callbacks: List[CustomCallbackDefinition] = Field(default_factory=list)
    
    # Known MCP servers for quick selection
    mcp_servers: List[MCPServerConfig] = Field(default_factory=list)
    
    # SkillSets (vector database toolsets)
    skillsets: List[SkillSetConfig] = Field(default_factory=list)
    
    # Tool watches (persisted for the Run2 panel)
    watches: List[WatchExpression] = Field(default_factory=list)
    
    # Evaluation sets
    eval_sets: List["EvalSet"] = Field(default_factory=list)


# ============================================================================
# Runtime Models
# ============================================================================

class RunEvent(BaseModel):
    """An event from an agent run."""
    timestamp: float
    event_type: Literal["agent_start", "agent_end", "tool_call", "tool_result", 
                        "model_call", "model_response", "state_change", "transfer",
                        "callback_start", "callback_end", "callback_error", "user_message"]
    agent_name: str
    branch: Optional[str] = None  # For parallel execution tracking (e.g., "parallel_agent.sub_agent_a")
    data: Dict[str, Any] = Field(default_factory=dict)


class RunSession(BaseModel):
    """A session from running an agent."""
    id: str
    project_id: str
    started_at: float
    ended_at: Optional[float] = None
    status: Literal["running", "completed", "error"] = "running"
    events: List[RunEvent] = Field(default_factory=list)
    final_state: Dict[str, Any] = Field(default_factory=dict)
    token_counts: Dict[str, int] = Field(default_factory=dict)


# ============================================================================
# Evaluation Models (ADK-Compatible)
# ============================================================================

class EvalMetricType(str, Enum):
    """ADK prebuilt evaluation metrics."""
    TOOL_TRAJECTORY_AVG_SCORE = "tool_trajectory_avg_score"
    RESPONSE_MATCH_SCORE = "response_match_score"
    RESPONSE_EVALUATION_SCORE = "response_evaluation_score"
    FINAL_RESPONSE_MATCH_V2 = "final_response_match_v2"
    SAFETY_V1 = "safety_v1"
    HALLUCINATIONS_V1 = "hallucinations_v1"
    RUBRIC_BASED_FINAL_RESPONSE_QUALITY_V1 = "rubric_based_final_response_quality_v1"
    RUBRIC_BASED_TOOL_USE_QUALITY_V1 = "rubric_based_tool_use_quality_v1"


class ToolTrajectoryMatchType(str, Enum):
    """Match type for tool trajectory evaluation."""
    EXACT = "exact"
    IN_ORDER = "in_order"
    ANY_ORDER = "any_order"


class JudgeModelOptions(BaseModel):
    """Options for LLM-as-judge metrics."""
    judge_model: str = "gemini-2.5-flash"
    num_samples: int = 5


class EvalCriterion(BaseModel):
    """A criterion for an evaluation metric."""
    threshold: float = 0.7
    judge_model_options: Optional[JudgeModelOptions] = None


class EvalMetricConfig(BaseModel):
    """Configuration for a single evaluation metric."""
    metric: EvalMetricType
    enabled: bool = True
    criterion: EvalCriterion = Field(default_factory=lambda: EvalCriterion())


class ExpectedToolCall(BaseModel):
    """An expected tool call with optional argument matching."""
    name: str
    args: Optional[Dict[str, Any]] = None
    args_match_mode: Literal["exact", "subset", "ignore"] = "ignore"


class Rubric(BaseModel):
    """A custom rubric for evaluation."""
    rubric: str


class EvalInvocation(BaseModel):
    """A single invocation (turn) in a conversation for evaluation."""
    id: str = ""
    user_message: str
    expected_response: Optional[str] = None
    expected_tool_calls: List[ExpectedToolCall] = Field(default_factory=list)
    tool_trajectory_match_type: ToolTrajectoryMatchType = ToolTrajectoryMatchType.IN_ORDER
    rubrics: List[Rubric] = Field(default_factory=list)


class EnabledMetric(BaseModel):
    """An LLM-judged metric enabled for a test case with its pass threshold."""
    metric: str  # e.g., 'safety_v1', 'hallucinations_v1', etc.
    threshold: float  # Score must be >= this to pass


class EvalCase(BaseModel):
    """An evaluation case - a complete conversation to test."""
    id: str
    name: str
    description: str = ""
    invocations: List[EvalInvocation] = Field(default_factory=list)
    initial_state: Dict[str, Any] = Field(default_factory=dict)
    expected_final_state: Optional[Dict[str, Any]] = None
    rubrics: List[Rubric] = Field(default_factory=list)
    enabled_metrics: List[EnabledMetric] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    target_agent: Optional[str] = None  # Optional: test a specific sub-agent instead of root_agent


class EvalConfig(BaseModel):
    """Evaluation configuration - which metrics to use and their thresholds."""
    metrics: List[EvalMetricConfig] = Field(default_factory=lambda: [
        EvalMetricConfig(metric=EvalMetricType.TOOL_TRAJECTORY_AVG_SCORE, criterion=EvalCriterion(threshold=1.0)),
        EvalMetricConfig(metric=EvalMetricType.RESPONSE_MATCH_SCORE, criterion=EvalCriterion(threshold=0.7)),
    ])
    default_trajectory_match_type: ToolTrajectoryMatchType = ToolTrajectoryMatchType.IN_ORDER
    num_runs: int = 1
    # LLM judge model - if empty, uses the App's default model
    judge_model: str = ""


class EvalSet(BaseModel):
    """A set of evaluation cases (test suite)."""
    id: str
    name: str
    description: str = ""
    eval_cases: List[EvalCase] = Field(default_factory=list)
    eval_config: EvalConfig = Field(default_factory=EvalConfig)
    created_at: float = 0.0
    updated_at: float = 0.0


class MetricResult(BaseModel):
    """Result for a single metric."""
    metric: str
    score: Optional[float] = None
    threshold: float = 0.7
    passed: bool = True
    details: Optional[str] = None
    rationale: Optional[str] = None  # LLM judge reasoning/explanation
    error: Optional[str] = None


class InvocationResult(BaseModel):
    """Result of a single invocation evaluation."""
    invocation_id: str
    user_message: str
    actual_response: Optional[str] = None
    actual_tool_calls: List[Dict[str, Any]] = Field(default_factory=list)
    expected_response: Optional[str] = None
    expected_tool_calls: List[Dict[str, Any]] = Field(default_factory=list)
    metric_results: List[MetricResult] = Field(default_factory=list)
    rubric_results: List[Dict[str, Any]] = Field(default_factory=list)
    passed: bool = True
    error: Optional[str] = None
    # Token usage for this invocation
    input_tokens: int = 0
    output_tokens: int = 0
    # Session ID from the agent run (for "View Session" functionality)
    session_id: Optional[str] = None


class EvalCaseResult(BaseModel):
    """Result of running a single evaluation case."""
    eval_case_id: str
    eval_case_name: str
    eval_set_id: str = ""
    eval_set_name: str = ""
    session_id: str
    metric_results: List[MetricResult] = Field(default_factory=list)
    rubric_results: List[Dict[str, Any]] = Field(default_factory=list)
    passed: bool = True
    invocation_results: List[InvocationResult] = Field(default_factory=list)
    final_state: Dict[str, Any] = Field(default_factory=dict)
    expected_final_state: Optional[Dict[str, Any]] = None
    state_matched: Optional[bool] = None
    started_at: float = 0.0
    ended_at: float = 0.0
    duration_ms: float = 0.0
    error: Optional[str] = None
    # Token usage
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tokens: int = 0


class EvalSetResult(BaseModel):
    """Results from running an entire evaluation set."""
    id: str
    eval_set_id: str
    eval_set_name: str
    project_id: str
    started_at: float = 0.0
    ended_at: float = 0.0
    duration_ms: float = 0.0
    case_results: List[EvalCaseResult] = Field(default_factory=list)
    total_cases: int = 0
    passed_cases: int = 0
    failed_cases: int = 0
    error_cases: int = 0
    metric_pass_rates: Dict[str, float] = Field(default_factory=dict)
    metric_avg_scores: Dict[str, float] = Field(default_factory=dict)
    overall_pass_rate: float = 0.0

