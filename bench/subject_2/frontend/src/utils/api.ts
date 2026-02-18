import type { Project, AgentConfig, CustomToolDefinition, MCPServerConfig, BuiltinTool } from './types';

const API_BASE = '/api';

export async function fetchJSON<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${url}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
  });
  
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Unknown error' }));
    throw new Error(error.detail || `HTTP ${response.status}`);
  }
  
  return response.json();
}

// Projects
export async function listProjects(): Promise<{ id: string; name: string; description: string }[]> {
  const data = await fetchJSON<{ projects: any[] }>('/projects');
  return data.projects;
}

export async function getProject(id: string): Promise<Project> {
  const data = await fetchJSON<{ project: Project }>(`/projects/${id}`);
  return data.project;
}

export async function createProject(name: string, description: string = ''): Promise<Project> {
  const data = await fetchJSON<{ project: Project }>('/projects', {
    method: 'POST',
    body: JSON.stringify({ name, description }),
  });
  return data.project;
}

export async function updateProject(id: string, updates: Partial<Project>): Promise<Project> {
  const data = await fetchJSON<{ project: Project }>(`/projects/${id}`, {
    method: 'PUT',
    body: JSON.stringify(updates),
  });
  return data.project;
}

export async function deleteProject(id: string): Promise<void> {
  await fetchJSON(`/projects/${id}`, { method: 'DELETE' });
}

// Sessions
export async function saveSessionToMemory(sessionId: string): Promise<{ success: boolean; message?: string; error?: string }> {
  return fetchJSON(`/sessions/${sessionId}/save-to-memory`, {
    method: 'POST',
  });
}

export async function listProjectSessions(projectId: string): Promise<Array<{
  id: string;
  started_at: number;
  ended_at?: number;
  duration?: number;
  event_count: number;
}>> {
  const data = await fetchJSON<{ sessions: any[] }>(`/projects/${projectId}/sessions`);
  return data.sessions;
}

export async function loadSession(projectId: string, sessionId: string): Promise<{
  id: string;
  project_id: string;
  started_at: number;
  ended_at?: number;
  status: string;
  events: any[];
  final_state: Record<string, any>;
  token_counts: Record<string, number>;
}> {
  const data = await fetchJSON<{ session: any }>(`/projects/${projectId}/sessions/${sessionId}/load`);
  return data.session;
}

// Artifacts
export interface ArtifactInfo {
  filename: string;
  mime_type: string | null;
  is_image: boolean;
  size: number | null;
}

export async function listArtifacts(projectId: string, sessionId: string): Promise<ArtifactInfo[]> {
  const data = await fetchJSON<{ artifacts: ArtifactInfo[]; error?: string }>(`/projects/${projectId}/sessions/${sessionId}/artifacts`);
  return data.artifacts || [];
}

export function getArtifactUrl(projectId: string, sessionId: string, filename: string): string {
  return `${API_BASE}/projects/${projectId}/sessions/${sessionId}/artifacts/${encodeURIComponent(filename)}`;
}

// YAML
export async function getProjectYaml(id: string): Promise<string> {
  const data = await fetchJSON<{ yaml: string }>(`/projects/${id}/yaml`);
  return data.yaml;
}

export async function updateProjectFromYaml(id: string, yaml: string): Promise<Project> {
  const data = await fetchJSON<{ project: Project }>(`/projects/${id}/yaml`, {
    method: 'PUT',
    body: JSON.stringify({ yaml }),
  });
  return data.project;
}

// Agents
export async function createAgent(projectId: string, agent: Partial<AgentConfig>): Promise<AgentConfig> {
  const data = await fetchJSON<{ agent: AgentConfig }>(`/projects/${projectId}/agents`, {
    method: 'POST',
    body: JSON.stringify(agent),
  });
  return data.agent;
}

export async function updateAgent(projectId: string, agentId: string, agent: AgentConfig): Promise<AgentConfig> {
  const data = await fetchJSON<{ agent: AgentConfig }>(`/projects/${projectId}/agents/${agentId}`, {
    method: 'PUT',
    body: JSON.stringify(agent),
  });
  return data.agent;
}

export async function deleteAgent(projectId: string, agentId: string): Promise<void> {
  await fetchJSON(`/projects/${projectId}/agents/${agentId}`, { method: 'DELETE' });
}

// Custom Tools
export async function createCustomTool(projectId: string, tool: Partial<CustomToolDefinition>): Promise<CustomToolDefinition> {
  const data = await fetchJSON<{ tool: CustomToolDefinition }>(`/projects/${projectId}/tools`, {
    method: 'POST',
    body: JSON.stringify(tool),
  });
  return data.tool;
}

export async function updateCustomTool(projectId: string, toolId: string, tool: CustomToolDefinition): Promise<CustomToolDefinition> {
  const data = await fetchJSON<{ tool: CustomToolDefinition }>(`/projects/${projectId}/tools/${toolId}`, {
    method: 'PUT',
    body: JSON.stringify(tool),
  });
  return data.tool;
}

export async function deleteCustomTool(projectId: string, toolId: string): Promise<void> {
  await fetchJSON(`/projects/${projectId}/tools/${toolId}`, { method: 'DELETE' });
}

// Reference data
export async function getMcpServers(): Promise<MCPServerConfig[]> {
  const data = await fetchJSON<{ servers: MCPServerConfig[] }>('/mcp-servers');
  return data.servers;
}

export async function getBuiltinTools(): Promise<BuiltinTool[]> {
  const data = await fetchJSON<{ tools: BuiltinTool[] }>('/builtin-tools');
  return data.tools;
}

// WebSocket for running agents
export function createRunWebSocket(projectId: string): WebSocket {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host = window.location.host;
  return new WebSocket(`${protocol}//${host}/ws/run/${projectId}`);
}

// AI-assisted prompt generation
export interface GeneratePromptResult {
  prompt: string | null;
  success: boolean;
  error?: string;
}

export async function generatePrompt(
  projectId: string, 
  agentId: string, 
  context?: string,
  agentConfig?: any  // Optional: agent config if not yet saved
): Promise<GeneratePromptResult> {
  const data = await fetchJSON<GeneratePromptResult>(`/projects/${projectId}/generate-prompt`, {
    method: 'POST',
    body: JSON.stringify({ 
      agent_id: agentId, 
      context,
      agent_config: agentConfig ? agentConfig : undefined,
    }),
  });
  return data;
}

// AI-assisted agent configuration
export interface GeneratedAgentConfig {
  name: string;
  description: string;
  instruction: string;
  tools: {
    builtin: string[];
    mcp: { server: string; tools: string[] }[];
    custom: string[];
    agents: string[];
  };
  sub_agents: string[];
}

export interface GenerateAgentConfigResult {
  config: GeneratedAgentConfig | null;
  success: boolean;
  error?: string;
  raw_response?: string;
}

export async function generateAgentConfig(
  projectId: string,
  description: string
): Promise<GenerateAgentConfigResult> {
  const data = await fetchJSON<GenerateAgentConfigResult>(`/projects/${projectId}/generate-agent-config`, {
    method: 'POST',
    body: JSON.stringify({ description }),
  });
  return data;
}

// AI-assisted tool code generation
export interface GenerateToolCodeResult {
  code: string | null;
  success: boolean;
  error?: string;
}

export async function generateToolCode(
  projectId: string,
  toolName: string,
  toolDescription: string,
  stateKeysUsed: string[] = [],
  context?: string
): Promise<GenerateToolCodeResult> {
  const data = await fetchJSON<GenerateToolCodeResult>(`/projects/${projectId}/generate-tool-code`, {
    method: 'POST',
    body: JSON.stringify({
      tool_name: toolName,
      tool_description: toolDescription,
      state_keys_used: stateKeysUsed,
      context,
    }),
  });
  return data;
}

// AI-assisted callback code generation
export interface GenerateCallbackCodeResult {
  code: string | null;
  success: boolean;
  error?: string;
}

export async function generateCallbackCode(
  projectId: string,
  callbackName: string,
  callbackDescription: string,
  callbackType: string,
  stateKeysUsed: string[] = [],
  context?: string
): Promise<GenerateCallbackCodeResult> {
  const data = await fetchJSON<GenerateCallbackCodeResult>(`/projects/${projectId}/generate-callback-code`, {
    method: 'POST',
    body: JSON.stringify({
      callback_name: callbackName,
      callback_description: callbackDescription,
      callback_type: callbackType,
      state_keys_used: stateKeysUsed,
      context,
    }),
  });
  return data;
}

// MCP Server Testing
export interface McpToolInfo {
  name: string;
  description: string;
}

export interface TestMcpServerResult {
  success: boolean;
  tools: McpToolInfo[];
  message?: string;
  error?: string;
  traceback?: string;
}

export async function testMcpServer(config: {
  connection_type: string;
  command?: string;
  args?: string[];
  env?: Record<string, string>;
  url?: string;
  headers?: Record<string, string>;
  timeout?: number;
}): Promise<TestMcpServerResult> {
  const data = await fetchJSON<TestMcpServerResult>('/test-mcp-server', {
    method: 'POST',
    body: JSON.stringify(config),
  });
  return data;
}

// ============================================================================
// Model Testing API
// ============================================================================

export interface TestModelResult {
  success: boolean;
  response?: string;
  error?: string;
  model: string;
  provider: string;
}

export async function testModelConfig(
  projectId: string,
  config: {
    provider: string;
    model_name: string;
    api_base?: string;
    api_key?: string;
  }
): Promise<TestModelResult> {
  return fetchJSON<TestModelResult>(`/projects/${projectId}/test-model`, {
    method: 'POST',
    body: JSON.stringify(config),
  });
}

// ============================================================================
// SkillSet API
// ============================================================================

export interface SkillSetEntry {
  id: string;
  text: string;
  full_text?: string;
  source_id: string;
  source_name: string;
  created_at: number;
  has_embedding: boolean;
}

export interface SkillSetSearchResult {
  id: string;
  text: string;
  score: number;
  source_id: string;
  source_name: string;
  created_at: number;
}

export interface SkillSetStats {
  entry_count: number;
  has_embeddings: boolean;
  model_name: string;
  sources: Record<string, number>;
}

export async function getSkillSetEntries(
  projectId: string,
  skillsetId: string,
  limit: number = 100
): Promise<{ entries: SkillSetEntry[]; total: number }> {
  return fetchJSON(`/projects/${projectId}/skillsets/${skillsetId}/entries?limit=${limit}`);
}

export async function getSkillSetStats(
  projectId: string,
  skillsetId: string
): Promise<SkillSetStats> {
  return fetchJSON(`/projects/${projectId}/skillsets/${skillsetId}/stats`);
}

export async function addSkillSetText(
  projectId: string,
  skillsetId: string,
  text: string,
  sourceName: string = 'manual'
): Promise<SkillSetEntry> {
  return fetchJSON(`/projects/${projectId}/skillsets/${skillsetId}/text`, {
    method: 'POST',
    body: JSON.stringify({ text, source_name: sourceName }),
  });
}

export async function addSkillSetUrl(
  projectId: string,
  skillsetId: string,
  url: string,
  sourceName?: string,
  chunkSize: number = 500,
  chunkOverlap: number = 50
): Promise<{ source_id: string; source_name: string; chunks_added: number }> {
  return fetchJSON(`/projects/${projectId}/skillsets/${skillsetId}/url`, {
    method: 'POST',
    body: JSON.stringify({
      url,
      source_name: sourceName,
      chunk_size: chunkSize,
      chunk_overlap: chunkOverlap,
    }),
  });
}

export async function uploadSkillSetFile(
  projectId: string,
  skillsetId: string,
  file: File,
  chunkSize: number = 500,
  chunkOverlap: number = 50
): Promise<{ source_id: string; source_name: string; chunks_added: number }> {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('chunk_size', String(chunkSize));
  formData.append('chunk_overlap', String(chunkOverlap));
  
  const response = await fetch(`${API_BASE}/projects/${projectId}/skillsets/${skillsetId}/file`, {
    method: 'POST',
    body: formData,
  });
  
  if (!response.ok) {
    throw new Error(`Upload failed: ${response.statusText}`);
  }
  
  return response.json();
}

export async function searchSkillSet(
  projectId: string,
  skillsetId: string,
  query: string,
  topK: number = 10,
  minScore: number = 0.0
): Promise<{ query: string; results: SkillSetSearchResult[]; count: number }> {
  return fetchJSON(`/projects/${projectId}/skillsets/${skillsetId}/search`, {
    method: 'POST',
    body: JSON.stringify({ query, top_k: topK, min_score: minScore }),
  });
}

export async function deleteSkillSetEntry(
  projectId: string,
  skillsetId: string,
  entryId: string
): Promise<{ deleted: boolean }> {
  return fetchJSON(`/projects/${projectId}/skillsets/${skillsetId}/entries/${entryId}`, {
    method: 'DELETE',
  });
}

export async function deleteSkillSetSource(
  projectId: string,
  skillsetId: string,
  sourceId: string
): Promise<{ deleted: number }> {
  return fetchJSON(`/projects/${projectId}/skillsets/${skillsetId}/sources/${sourceId}`, {
    method: 'DELETE',
  });
}

export async function clearSkillSet(
  projectId: string,
  skillsetId: string
): Promise<{ cleared: number }> {
  return fetchJSON(`/projects/${projectId}/skillsets/${skillsetId}/entries`, {
    method: 'DELETE',
  });
}

export async function checkEmbeddingsAvailable(): Promise<{ available: boolean }> {
  return fetchJSON('/skillsets/embeddings-available');
}

// ============================================================================
// Sandbox API (Docker container isolation)
// ============================================================================

import type { 
  SandboxConfig, SandboxInstance, NetworkRequest, AllowlistPattern,
  PatternType, ApprovalRequest, MCPContainerStatus
} from './types';

export interface StartSandboxResponse {
  status: string;
  instance?: SandboxInstance;
  error?: string;
}

export async function startSandbox(
  appId: string,
  projectId: string,
  config?: Partial<SandboxConfig>
): Promise<StartSandboxResponse> {
  return fetchJSON('/sandbox/start', {
    method: 'POST',
    body: JSON.stringify({
      app_id: appId,
      project_id: projectId,
      config,
    }),
  });
}

export async function stopSandbox(appId: string): Promise<{ status: string }> {
  return fetchJSON(`/sandbox/${appId}/stop`, { method: 'POST' });
}

export async function getSandboxStatus(appId: string): Promise<{
  status: string;
  instance?: SandboxInstance;
}> {
  return fetchJSON(`/sandbox/${appId}/status`);
}

export async function listSandboxes(): Promise<{ sandboxes: SandboxInstance[] }> {
  return fetchJSON('/sandbox/list');
}

export async function getNetworkActivity(appId: string): Promise<{
  requests: NetworkRequest[];
}> {
  return fetchJSON(`/sandbox/${appId}/network`);
}

export async function getSandboxAllowlist(appId: string): Promise<{
  auto: string[];
  user: AllowlistPattern[];
}> {
  return fetchJSON(`/sandbox/${appId}/allowlist`);
}

export async function addAllowlistPattern(
  appId: string,
  pattern: string,
  patternType: PatternType = 'exact',
  persist: boolean = false,
  projectId?: string
): Promise<{ status: string }> {
  return fetchJSON(`/sandbox/${appId}/allowlist`, {
    method: 'POST',
    body: JSON.stringify({
      pattern,
      pattern_type: patternType,
      persist,
      project_id: projectId,
    }),
  });
}

export async function removeAllowlistPattern(
  appId: string,
  patternId: string
): Promise<{ status: string }> {
  return fetchJSON(`/sandbox/${appId}/allowlist/${patternId}`, {
    method: 'DELETE',
  });
}

export async function persistAllowlist(
  appId: string,
  projectId: string
): Promise<{ status: string }> {
  return fetchJSON(`/sandbox/${appId}/allowlist/persist`, {
    method: 'POST',
    body: JSON.stringify({ project_id: projectId }),
  });
}

export async function approveNetworkRequest(
  appId: string,
  requestId: string,
  pattern?: string,
  patternType: PatternType = 'exact',
  persist: boolean = false
): Promise<{ status: string }> {
  return fetchJSON(`/sandbox/${appId}/approval`, {
    method: 'POST',
    body: JSON.stringify({
      request_id: requestId,
      action: pattern ? 'allow_pattern' : 'allow_once',
      pattern,
      pattern_type: patternType,
      persist,
    }),
  });
}

export async function denyNetworkRequest(
  appId: string,
  requestId: string
): Promise<{ status: string }> {
  return fetchJSON(`/sandbox/${appId}/approval`, {
    method: 'POST',
    body: JSON.stringify({
      request_id: requestId,
      action: 'deny',
    }),
  });
}

export async function getMcpContainerStatus(appId: string): Promise<{
  mcp_servers: MCPContainerStatus[];
}> {
  return fetchJSON(`/sandbox/${appId}/mcp-status`);
}

export async function getSandboxConfig(appId: string): Promise<{
  config: SandboxConfig;
}> {
  return fetchJSON(`/sandbox/${appId}/config`);
}

export async function updateSandboxConfig(
  appId: string,
  config: Partial<SandboxConfig>
): Promise<{ status: string }> {
  return fetchJSON(`/sandbox/${appId}/config`, {
    method: 'PUT',
    body: JSON.stringify(config),
  });
}

// WebSocket for sandbox events
export function createSandboxWebSocket(appId: string): WebSocket {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host = window.location.host;
  return new WebSocket(`${protocol}//${host}/api/sandbox/${appId}/events`);
}


// ============================================================================
// Generic API object for simpler CRUD operations
// ============================================================================

// ============================================================================
// Eval Set Generation
// ============================================================================

export interface GenerateEvalSetRequest {
  agent_id?: string;
  context?: string;
}

export interface GenerateEvalSetResponse {
  success: boolean;
  eval_set?: any;
  cases_generated?: number;
  error?: string;
  traceback?: string;
  raw_output?: string;
}

export async function generateEvalSet(
  projectId: string,
  options: GenerateEvalSetRequest = {}
): Promise<GenerateEvalSetResponse> {
  return fetchJSON(`/projects/${projectId}/generate-eval-set`, {
    method: 'POST',
    body: JSON.stringify(options),
  });
}

// Generic API helper for simple cases
export const api = {
  async get<T = any>(url: string): Promise<T> {
    return fetchJSON<T>(url);
  },
  
  async post<T = any>(url: string, body?: any): Promise<T> {
    return fetchJSON<T>(url, {
      method: 'POST',
      body: body ? JSON.stringify(body) : undefined,
    });
  },
  
  async put<T = any>(url: string, body?: any): Promise<T> {
    return fetchJSON<T>(url, {
      method: 'PUT',
      body: body ? JSON.stringify(body) : undefined,
    });
  },
  
  async delete<T = any>(url: string): Promise<T> {
    return fetchJSON<T>(url, {
      method: 'DELETE',
    });
  },
};

// System Metrics
export interface SystemMetrics {
  timestamp: number;
  platform: string;
  cpu: {
    percent: number;
    percent_per_core: number[];
    count: number;
    count_physical: number;
    frequency_mhz: number | null;
    frequency_max_mhz: number | null;
    load_avg_1m: number | null;
    load_avg_5m: number | null;
    load_avg_15m: number | null;
  };
  memory: {
    total_gb: number;
    available_gb: number;
    used_gb: number;
    percent: number;
    swap_total_gb: number;
    swap_used_gb: number;
    swap_percent: number;
  };
  disk: {
    total_gb: number;
    used_gb: number;
    free_gb: number;
    percent: number;
  };
  gpu: Array<{
    index: number;
    name: string;
    memory_total_gb?: number;
    memory_used_gb?: number;
    memory_free_gb?: number;
    memory_percent?: number;
    utilization_percent?: number | null;
    memory_utilization_percent?: number | null;
    temperature_c?: number | null;
    power_w?: number | null;
    power_limit_w?: number | null;
    vram?: string;
    type?: string;
  }>;
  available: {
    psutil: boolean;
    gpu: boolean;
  };
}

export async function getSystemMetrics(): Promise<SystemMetrics> {
  return fetchJSON<SystemMetrics>('/system/metrics');
}

