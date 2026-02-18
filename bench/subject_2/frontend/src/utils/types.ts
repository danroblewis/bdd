// Types matching backend models

export type AgentType = 'LlmAgent' | 'SequentialAgent' | 'LoopAgent' | 'ParallelAgent';
export type ServiceType = 'memory://' | 'sqlite://' | 'postgresql://';
export type MCPConnectionType = 'stdio' | 'sse' | 'http';

export interface StateKeyConfig {
  name: string;
  description: string;
  type: 'string' | 'number' | 'boolean' | 'object' | 'array';
  default_value?: any;
  scope: 'session' | 'user' | 'app' | 'temp';
}

export interface MCPServerConfig {
  name: string;
  description: string;
  connection_type: MCPConnectionType;
  command?: string;
  args: string[];
  env: Record<string, string>;
  url?: string;
  headers: Record<string, string>;
  timeout: number;
  tool_filter?: string[] | null;  // null = no filter (all tools), [] = no tools, ["a","b"] = only those
  tool_name_prefix?: string;
}

export interface ModelConfig {
  provider: 'gemini' | 'litellm' | 'anthropic' | 'openai' | 'groq' | 'together';
  model_name: string;
  api_base?: string;
  fallbacks: string[];
  temperature?: number;
  max_output_tokens?: number;
  top_p?: number;
  top_k?: number;
  // Retry and timeout settings (especially useful for local models like Ollama)
  num_retries?: number;  // Number of retries on failure
  request_timeout?: number;  // Timeout in seconds per request
  // Marker for linking to an App model - if set, this config mirrors an App model
  _appModelId?: string;
}

export interface CallbackConfig {
  module_path: string;
}

export interface ToolConfig {
  type: 'function' | 'mcp' | 'agent' | 'builtin' | 'skillset';
  name?: string;
  description?: string;
  module_path?: string;
  server?: MCPServerConfig;
  agent_id?: string;
  skip_summarization?: boolean;
  skillset_id?: string;  // For skillset type
}

export interface LlmAgentConfig {
  type: 'LlmAgent';
  id: string;
  name: string;
  description: string;
  model?: ModelConfig;
  instruction: string;
  output_key?: string;
  include_contents: 'default' | 'none';
  disallow_transfer_to_parent: boolean;
  disallow_transfer_to_peers: boolean;
  tools: ToolConfig[];
  sub_agents: string[];
  before_agent_callbacks: CallbackConfig[];
  after_agent_callbacks: CallbackConfig[];
  before_model_callbacks: CallbackConfig[];
  after_model_callbacks: CallbackConfig[];
  before_tool_callbacks: CallbackConfig[];
  after_tool_callbacks: CallbackConfig[];
}

export interface SequentialAgentConfig {
  type: 'SequentialAgent';
  id: string;
  name: string;
  description: string;
  sub_agents: string[];
  before_agent_callbacks: CallbackConfig[];
  after_agent_callbacks: CallbackConfig[];
}

export interface LoopAgentConfig {
  type: 'LoopAgent';
  id: string;
  name: string;
  description: string;
  sub_agents: string[];
  max_iterations?: number;
  before_agent_callbacks: CallbackConfig[];
  after_agent_callbacks: CallbackConfig[];
}

export interface ParallelAgentConfig {
  type: 'ParallelAgent';
  id: string;
  name: string;
  description: string;
  sub_agents: string[];
  before_agent_callbacks: CallbackConfig[];
  after_agent_callbacks: CallbackConfig[];
}

export type AgentConfig = LlmAgentConfig | SequentialAgentConfig | LoopAgentConfig | ParallelAgentConfig;

export interface PluginConfig {
  type: 'ReflectAndRetryToolPlugin' | 'ContextFilterPlugin' | 'LoggingPlugin' | 
        'GlobalInstructionPlugin' | 'SaveFilesAsArtifactsPlugin' | 'MultimodalToolResultsPlugin';
  name: string;
  // ReflectAndRetryToolPlugin
  max_retries?: number;
  throw_exception_if_retry_exceeded?: boolean;
  // ContextFilterPlugin
  num_invocations_to_keep?: number;
  // GlobalInstructionPlugin
  global_instruction?: string;
}

export interface CompactionConfig {
  enabled: boolean;
  max_events: number;
  summarize: boolean;
}

export interface ContextCacheConfig {
  enabled: boolean;
  ttl_seconds: number;
}

export interface ResumabilityConfig {
  enabled: boolean;
}

export interface ArtifactConfig {
  name: string;
  description: string;
  type: 'file' | 'image' | 'data';
}

export interface AppModelConfig {
  id: string;
  name: string;
  provider: 'gemini' | 'litellm' | 'anthropic' | 'openai' | 'groq' | 'together';
  model_name: string;
  api_base?: string;
  temperature?: number;
  max_output_tokens?: number;
  top_p?: number;
  top_k?: number;
  // Retry and timeout settings
  num_retries?: number;
  request_timeout?: number;
  is_default?: boolean;
}

export interface AppConfig {
  id: string;
  name: string;
  description: string;
  root_agent_id?: string;
  session_service_uri: string;
  memory_service_uri: string;
  artifact_service_uri: string;
  compaction: CompactionConfig;
  context_cache: ContextCacheConfig;
  resumability: ResumabilityConfig;
  plugins: PluginConfig[];
  state_keys: StateKeyConfig[];
  artifacts: ArtifactConfig[];
  models: AppModelConfig[];
  default_model_id?: string;
  env_vars: Record<string, string>;
  sandbox?: SandboxConfig;
}

export interface CustomToolDefinition {
  id: string;
  name: string;
  description: string;
  module_path: string;
  code: string;
  state_keys_used: string[];
}

export interface CustomCallbackDefinition {
  id: string;
  name: string;
  description: string;
  module_path: string;
  code: string;
  state_keys_used: string[];
}

export interface WatchExpressionConfig {
  id: string;
  serverName: string;
  toolName: string;
  args: Record<string, any>;
  transform?: string;
}

export interface SkillSetSourceConfig {
  id: string;
  type: 'file' | 'url' | 'text';
  name: string;
  path?: string;
  text?: string;
  added_at: number;
}

export interface SkillSetConfig {
  id: string;
  name: string;
  description: string;
  embedding_model?: string;
  app_model_id?: string;
  external_store_type?: 'pinecone' | 'weaviate' | 'qdrant' | 'chromadb';
  external_store_config: Record<string, any>;
  search_enabled: boolean;
  preload_enabled: boolean;
  preload_top_k: number;
  preload_min_score: number;
  sources: SkillSetSourceConfig[];
  entry_count: number;
}

export interface Project {
  id: string;
  name: string;
  description: string;
  app: AppConfig;
  agents: AgentConfig[];
  custom_tools: CustomToolDefinition[];
  custom_callbacks: CustomCallbackDefinition[];
  mcp_servers: MCPServerConfig[];
  skillsets: SkillSetConfig[];
  watches: WatchExpressionConfig[];
  eval_sets?: any[];  // Managed separately by EvalPanel
}

export interface RunEvent {
  timestamp: number;
  event_type: 'agent_start' | 'agent_end' | 'tool_call' | 'tool_result' | 
              'model_call' | 'model_response' | 'state_change' | 'transfer' |
              'callback_start' | 'callback_end' | 'callback_error' | 'user_message';
  agent_name: string;
  branch?: string | null;  // For parallel execution tracking (e.g., "parallel_agent.sub_agent_a")
  data: Record<string, any>;
}

export interface RunSession {
  id: string;
  project_id: string;
  started_at: number;
  ended_at?: number;
  status: 'running' | 'completed' | 'error';
  events: RunEvent[];
  final_state: Record<string, any>;
  token_counts: Record<string, number>;
}

export interface BuiltinTool {
  name: string;
  description: string;
}

export interface WatchToolConfig {
  id: string;
  name: string;  // Display name
  type: 'builtin' | 'mcp' | 'custom';
  tool_name: string;  // Actual tool function name
  args: Record<string, any>;  // Tool arguments
  mcp_server?: string;  // For MCP tools
}

export interface WatchToolResult {
  watch_id: string;
  result: any;
  error?: string;
  timestamp: number;
}

// =============================================================================
// Sandbox Types (Docker container isolation)
// =============================================================================

export type PatternType = 'exact' | 'wildcard' | 'regex';
export type NetworkRequestStatus = 'pending' | 'allowed' | 'denied' | 'completed' | 'error';
export type SandboxStatus = 'stopped' | 'starting' | 'running' | 'stopping' | 'error';

export interface AllowlistPattern {
  id: string;
  pattern: string;
  pattern_type: PatternType;
  added_at?: string;
  source: string;
}

export interface NetworkAllowlist {
  auto: string[];
  user: AllowlistPattern[];
}

export interface VolumeMount {
  host_path: string;      // Path on the host machine
  container_path: string; // Path inside the container
  mode: 'ro' | 'rw';      // Read-only or read-write
}

export interface SandboxConfig {
  enabled: boolean;
  allow_all_network?: boolean;
  allowlist: NetworkAllowlist;
  unknown_action: 'ask' | 'deny' | 'allow';
  approval_timeout: number;
  agent_memory_limit_mb: number;
  agent_cpu_limit: number;
  mcp_memory_limit_mb: number;
  mcp_cpu_limit: number;
  run_timeout: number;
  volume_mounts: VolumeMount[];
}

export interface NetworkRequest {
  id: string;
  timestamp: string;
  method: string;
  url: string;
  host: string;
  status: NetworkRequestStatus;
  source: string;  // "agent" or "mcp:<server_name>"
  matched_pattern?: string;
  source_agent?: string;
  response_status?: number;
  response_time_ms?: number;
  response_size?: number;
  is_llm_provider: boolean;
  headers?: Record<string, string>;
}

export interface MCPContainerStatus {
  name: string;
  container_id?: string;
  status: string;
  transport: string;
  endpoint?: string;
  error?: string;
}

export interface SandboxInstance {
  id: string;
  app_id: string;
  status: SandboxStatus;
  gateway_container_id?: string;
  agent_container_id?: string;
  mcp_containers: MCPContainerStatus[];
  network_requests: NetworkRequest[];
  pending_approvals: string[];
  started_at?: string;
  error?: string;
  config?: SandboxConfig;
}

export interface ApprovalRequest {
  id: string;          // Request ID from gateway
  host: string;
  url: string;
  method: string;
  headers?: Record<string, string>;
  source: string;
  timeout?: number;    // Seconds until auto-deny
  timestamp?: number;
}

