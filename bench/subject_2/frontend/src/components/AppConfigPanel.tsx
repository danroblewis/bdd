import { useState } from 'react';
import { Plus, Trash2, Database, Settings2, Zap, Clock, RefreshCw, Cpu, Star, Lock, Eye, EyeOff, Shield, Globe, HardDrive, FolderOpen } from 'lucide-react';
import { useStore } from '../hooks/useStore';
import type { PluginConfig, ArtifactConfig, AppModelConfig, AllowlistPattern, PatternType, SandboxConfig, NetworkAllowlist, VolumeMount } from '../utils/types';
import { ModelConfigForm } from './ModelConfigForm';

// Common environment variables with descriptions
const COMMON_ENV_VARS = [
  { key: 'GOOGLE_API_KEY', description: 'API key for Gemini models' },
  { key: 'OPENAI_API_KEY', description: 'API key for OpenAI models (via LiteLLM)' },
  { key: 'GROQ_API_KEY', description: 'API key for Groq models' },
  { key: 'ANTHROPIC_API_KEY', description: 'API key for Anthropic Claude models' },
  { key: 'TOGETHER_API_KEY', description: 'API key for Together (via LiteLLM, e.g. together_ai/* models)' },
  { key: 'AZURE_OPENAI_API_KEY', description: 'API key for Azure OpenAI Service' },
  { key: 'AZURE_API_BASE', description: 'Base URL for Azure OpenAI endpoint (e.g., https://your-resource.openai.azure.com)' },
  { key: 'AZURE_API_VERSION', description: 'API version for Azure OpenAI (e.g., 2024-02-15-preview)' },
  { key: 'GOOGLE_GENAI_USE_VERTEXAI', description: 'Set to "1" to use Vertex AI instead of API key' },
  { key: 'GOOGLE_CLOUD_PROJECT', description: 'Google Cloud project ID for Vertex AI' },
  { key: 'GOOGLE_CLOUD_REGION', description: 'Google Cloud region for Vertex AI (e.g., us-central1)' },
];

// Validation function for names (alphanumeric and underscore only)
function isValidName(name: string): boolean {
  return /^[a-zA-Z0-9_]+$/.test(name);
}

export default function AppConfigPanel() {
  const { project, updateProject } = useStore();
  const [appNameError, setAppNameError] = useState<string | null>(null);
  
  if (!project) return null;
  
  const { app } = project;
  
  function updateApp(updates: Partial<typeof app>) {
    updateProject({
      app: { ...app, ...updates }
    });
  }
  
  function handleAppNameChange(value: string) {
    if (value === '') {
      setAppNameError(null);
      updateApp({ name: value });
      return;
    }
    
    if (!isValidName(value)) {
      setAppNameError('Name can only contain letters, numbers, and underscores');
    } else {
      setAppNameError(null);
    }
    
    updateApp({ name: value });
  }
  
  function addPlugin(type: PluginConfig['type'] = 'ReflectAndRetryToolPlugin') {
    let newPlugin: PluginConfig;
    switch (type) {
      case 'ReflectAndRetryToolPlugin':
        newPlugin = {
      type: 'ReflectAndRetryToolPlugin',
      name: 'reflect_retry',
      max_retries: 3,
      throw_exception_if_retry_exceeded: false
    };
        break;
      case 'ContextFilterPlugin':
        newPlugin = {
          type: 'ContextFilterPlugin',
          name: 'context_filter',
          num_invocations_to_keep: 5
        };
        break;
      case 'LoggingPlugin':
        newPlugin = {
          type: 'LoggingPlugin',
          name: 'logging'
        };
        break;
      case 'GlobalInstructionPlugin':
        newPlugin = {
          type: 'GlobalInstructionPlugin',
          name: 'global_instruction',
          global_instruction: ''
        };
        break;
      case 'SaveFilesAsArtifactsPlugin':
        newPlugin = {
          type: 'SaveFilesAsArtifactsPlugin',
          name: 'save_files'
        };
        break;
      case 'MultimodalToolResultsPlugin':
        newPlugin = {
          type: 'MultimodalToolResultsPlugin',
          name: 'multimodal_tools'
        };
        break;
      default:
        newPlugin = {
          type: 'ReflectAndRetryToolPlugin',
          name: 'reflect_retry',
          max_retries: 3,
          throw_exception_if_retry_exceeded: false
        };
    }
    updateApp({ plugins: [...app.plugins, newPlugin] });
  }
  
  function updatePlugin(index: number, updates: Partial<PluginConfig>) {
    const plugins = [...app.plugins];
    plugins[index] = { ...plugins[index], ...updates };
    updateApp({ plugins });
  }
  
  function removePlugin(index: number) {
    updateApp({ plugins: app.plugins.filter((_, i) => i !== index) });
  }
  
  // Allowlist management
  const sandbox = app.sandbox || { 
    enabled: false, 
    allow_all_network: false,
    allowlist: { auto: [], user: [] },
    unknown_action: 'ask' as const,
    approval_timeout: 30,
    agent_memory_limit_mb: 512,
    agent_cpu_limit: 1.0,
    mcp_memory_limit_mb: 256,
    mcp_cpu_limit: 0.5,
    run_timeout: 3600,  // 1 hour default
    volume_mounts: [],
  };
  const allowlistPatterns = sandbox.allowlist?.user || [];
  const volumeMounts = sandbox.volume_mounts || [];
  
  function updateSandbox(updates: Partial<SandboxConfig>) {
    updateApp({ sandbox: { ...sandbox, ...updates } });
  }
  
  // Sync allowlist patterns to running gateway
  async function syncAllowlistToGateway(patterns: AllowlistPattern[]) {
    const appId = app.id;
    try {
      await fetch(`/api/sandbox/${appId}/allowlist/sync`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          patterns: patterns.map(p => ({
            pattern: p.pattern,
            pattern_type: p.pattern_type,
          })).filter(p => p.pattern), // Only sync non-empty patterns
        }),
      });
    } catch (e) {
      // Ignore errors - gateway might not be running
      console.debug('Could not sync allowlist to gateway:', e);
    }
  }
  
  function addAllowlistPattern() {
    const newPattern: AllowlistPattern = {
      id: `pattern_${Date.now().toString(36)}`,
      pattern: '',
      pattern_type: 'exact',
      source: 'user',
      added_at: new Date().toISOString(),
    };
    const newAllowlist = {
      ...sandbox.allowlist,
      user: [...allowlistPatterns, newPattern],
    };
    updateSandbox({ allowlist: newAllowlist });
  }
  
  function updateAllowlistPattern(index: number, updates: Partial<AllowlistPattern>) {
    const patterns = [...allowlistPatterns];
    patterns[index] = { ...patterns[index], ...updates };
    const newPatterns = patterns;
    updateSandbox({ allowlist: { ...sandbox.allowlist, user: newPatterns } });
    // Sync to gateway when pattern is updated (debounced by user typing)
    if (updates.pattern) {
      syncAllowlistToGateway(newPatterns);
    }
  }
  
  function removeAllowlistPattern(index: number) {
    const patterns = allowlistPatterns.filter((_, i) => i !== index);
    updateSandbox({ allowlist: { ...sandbox.allowlist, user: patterns } });
    // Note: We can't "remove" from gateway, but new patterns won't require approval
  }
  
  // Volume mounts management (supports both files and directories)
  function addVolumeMount() {
    const newMount: VolumeMount = {
      host_path: '',
      container_path: '',
      mode: 'ro',
    };
    updateSandbox({ volume_mounts: [...volumeMounts, newMount] });
  }
  
  function updateVolumeMount(index: number, updates: Partial<VolumeMount>) {
    const mounts = [...volumeMounts];
    mounts[index] = { ...mounts[index], ...updates };
    updateSandbox({ volume_mounts: mounts });
  }
  
  function removeVolumeMount(index: number) {
    const mounts = volumeMounts.filter((_, i) => i !== index);
    updateSandbox({ volume_mounts: mounts });
  }
  
  // Model management
  const models = app.models || [];
  
  function addModel() {
    const id = `model_${Date.now().toString(36)}`;
    const newModel: AppModelConfig = {
      id,
      name: 'New Model',
      provider: 'gemini',
      model_name: 'gemini-2.0-flash',
      is_default: models.length === 0
    };
    updateApp({ 
      models: [...models, newModel],
      default_model_id: models.length === 0 ? id : app.default_model_id
    });
  }
  
  function updateModel(id: string, updates: Partial<AppModelConfig>) {
    const newModels = models.map(m => m.id === id ? { ...m, ...updates } : m);
    updateApp({ models: newModels });
  }
  
  function removeModel(id: string) {
    const newModels = models.filter(m => m.id !== id);
    const newDefault = app.default_model_id === id 
      ? (newModels[0]?.id || undefined)
      : app.default_model_id;
    updateApp({ models: newModels, default_model_id: newDefault });
  }
  
  function setDefaultModel(id: string) {
    updateApp({ default_model_id: id });
  }
  
  // Environment variables management
  const envVars = app.env_vars || {};
  const [showEnvValues, setShowEnvValues] = useState<Record<string, boolean>>({});
  const [newEnvKey, setNewEnvKey] = useState('');
  
  function addEnvVar(key: string = '') {
    const envKey = key || newEnvKey.trim();
    if (!envKey || envVars[envKey] !== undefined) return;
    updateApp({ env_vars: { ...envVars, [envKey]: '' } });
    setNewEnvKey('');
  }
  
  function updateEnvVar(key: string, value: string) {
    updateApp({ env_vars: { ...envVars, [key]: value } });
  }
  
  function removeEnvVar(key: string) {
    const newEnvVars = { ...envVars };
    delete newEnvVars[key];
    updateApp({ env_vars: newEnvVars });
  }
  
  function toggleShowEnvValue(key: string) {
    setShowEnvValues(prev => ({ ...prev, [key]: !prev[key] }));
  }
  
  return (
    <div className="app-config">
      <style>{`
        .app-config {
          display: flex;
          flex-direction: column;
          gap: 24px;
          max-width: 1000px;
        }
        
        .section {
          background: var(--bg-secondary);
          border: 1px solid var(--border-color);
          border-radius: var(--radius-lg);
          padding: 20px;
        }
        
        .section-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          margin-bottom: 16px;
        }
        
        .section-title {
          display: flex;
          align-items: center;
          gap: 10px;
          font-size: 1.1rem;
          font-weight: 600;
        }
        
        .section-title svg {
          color: var(--accent-primary);
        }
        
        .form-grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
          gap: 16px;
        }
        
        .form-group {
          display: flex;
          flex-direction: column;
          gap: 6px;
        }
        
        .form-group.full-width {
          grid-column: 1 / -1;
        }
        
        .toggle-group {
          display: flex;
          align-items: center;
          gap: 12px;
          padding: 12px;
          background: var(--bg-tertiary);
          border-radius: var(--radius-md);
        }
        
        .toggle {
          position: relative;
          width: 44px;
          height: 24px;
          background: var(--bg-hover);
          border-radius: 12px;
          cursor: pointer;
          transition: background 0.2s ease;
        }
        
        .toggle.active {
          background: var(--accent-primary);
        }
        
        .toggle::after {
          content: '';
          position: absolute;
          top: 2px;
          left: 2px;
          width: 20px;
          height: 20px;
          background: white;
          border-radius: 50%;
          transition: transform 0.2s ease;
        }
        
        .toggle.active::after {
          transform: translateX(20px);
        }
        
        .toggle-label {
          flex: 1;
        }
        
        .toggle-label strong {
          display: block;
          margin-bottom: 2px;
        }
        
        .toggle-label span {
          font-size: 12px;
          color: var(--text-muted);
        }
        
        .list-item {
          display: flex;
          align-items: flex-start;
          gap: 12px;
          padding: 12px;
          background: var(--bg-tertiary);
          border-radius: var(--radius-md);
          margin-bottom: 8px;
        }
        
        .list-item-content {
          flex: 1;
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
          gap: 12px;
        }
        
        .list-item input, .list-item select {
          padding: 6px 10px;
          font-size: 13px;
        }
        
        .delete-item {
          padding: 6px;
          color: var(--text-muted);
          border-radius: var(--radius-sm);
          transition: all 0.2s ease;
        }
        
        .delete-item:hover {
          color: var(--error);
          background: rgba(255, 107, 107, 0.1);
        }
        
        .empty-message {
          text-align: center;
          padding: 20px;
          color: var(--text-muted);
          font-size: 13px;
        }
        
        .default-model-btn {
          display: flex;
          align-items: center;
          gap: 6px;
          padding: 6px 12px;
          font-size: 12px;
          color: var(--text-muted);
          background: var(--bg-secondary);
          border-radius: var(--radius-sm);
          transition: all 0.15s ease;
        }
        
        .default-model-btn:hover {
          color: var(--accent-secondary);
          background: var(--bg-hover);
        }
        
        .default-model-btn.is-default {
          color: var(--accent-secondary);
          background: rgba(255, 217, 61, 0.15);
        }
        
        .model-card {
          background: var(--bg-tertiary);
          border-radius: var(--radius-md);
          margin-bottom: 12px;
          overflow: hidden;
        }
        
        .model-card-header {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 12px 16px;
          background: var(--bg-secondary);
          border-bottom: 1px solid var(--border-color);
        }
        
        .model-name-input {
          flex: 1;
          font-size: 14px;
          font-weight: 600;
          background: transparent;
          border: none;
          padding: 4px 8px;
        }
        
        .model-name-input:focus {
          background: var(--bg-tertiary);
          border-radius: var(--radius-sm);
        }
        
        .model-card-body {
          padding: 16px;
        }
        
        .model-row {
          display: flex;
          gap: 12px;
          margin-bottom: 12px;
        }
        
        .model-row:last-child {
          margin-bottom: 0;
        }
        
        .model-row .form-group {
          flex: 1;
        }
        
        .model-row input, .model-row select {
          padding: 8px 10px;
          font-size: 13px;
        }
      `}</style>
      
      {/* Basic Info */}
      <section className="section">
        <div className="section-header">
          <h2 className="section-title">
            <Settings2 size={20} />
            Basic Information
          </h2>
        </div>
        <div className="form-grid">
          <div className="form-group">
            <label>App Name</label>
            <input
              type="text"
              value={app.name}
              onChange={(e) => handleAppNameChange(e.target.value)}
              style={{ borderColor: appNameError ? 'var(--error)' : undefined }}
            />
            {appNameError && (
              <span style={{ fontSize: 11, color: 'var(--error)', marginTop: 4 }}>
                {appNameError}
              </span>
            )}
          </div>
          <div className="form-group">
            <label>Root Agent</label>
            <select
              value={app.root_agent_id || ''}
              onChange={(e) => updateApp({ root_agent_id: e.target.value || undefined })}
            >
              <option value="">Select an agent...</option>
              {project.agents.map((agent) => (
                <option key={agent.id} value={agent.id}>{agent.name}</option>
              ))}
            </select>
          </div>
        </div>
      </section>
      
      {/* Services */}
      <section className="section">
        <div className="section-header">
          <h2 className="section-title">
            <Database size={20} />
            Services
          </h2>
          <span className="section-hint">Configure session, memory, and artifact storage backends</span>
        </div>
        <div className="form-grid">
          {/* Session Service */}
          <div className="form-group">
            <label>Session Service</label>
            <select
              value={app.session_service_uri.split('://')[0]}
              onChange={(e) => {
                const type = e.target.value;
                const defaults: Record<string, string> = {
                  'memory': 'memory://',
                  'file': 'file://~/.adk-playground/sessions',
                  'sqlite': 'sqlite://~/.adk-playground/sessions.db',
                  'postgresql': 'postgresql://user:pass@localhost:5432/adk_sessions',
                  'mysql': 'mysql://user:pass@localhost:3306/adk_sessions',
                  'agentengine': 'agentengine://project/us-central1/engine-id',
                };
                updateApp({ session_service_uri: defaults[type] || type + '://' });
              }}
            >
              <option value="memory">In-Memory (dev only)</option>
              <option value="file">File System (JSON)</option>
              <option value="sqlite">SQLite (local)</option>
              <option value="postgresql">PostgreSQL</option>
              <option value="mysql">MySQL</option>
              <option value="agentengine">Vertex AI Agent Engine</option>
            </select>
            {app.session_service_uri.startsWith('file://') && (
              <input
                type="text"
                value={app.session_service_uri.replace('file://', '')}
                onChange={(e) => updateApp({ session_service_uri: 'file://' + e.target.value })}
                placeholder="~/.adk-playground/sessions"
                style={{ marginTop: 8 }}
              />
            )}
            {app.session_service_uri.startsWith('sqlite://') && (
              <input
                type="text"
                value={app.session_service_uri.replace('sqlite://', '')}
                onChange={(e) => updateApp({ session_service_uri: 'sqlite://' + e.target.value })}
                placeholder="~/.adk-playground/sessions.db"
                style={{ marginTop: 8 }}
              />
            )}
            {(app.session_service_uri.startsWith('postgresql://') || app.session_service_uri.startsWith('mysql://')) && (
              <input
                type="text"
                value={app.session_service_uri}
                onChange={(e) => updateApp({ session_service_uri: e.target.value })}
                placeholder="postgresql://user:pass@localhost:5432/db"
                style={{ marginTop: 8 }}
              />
            )}
            {app.session_service_uri.startsWith('agentengine://') && (
              <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 8 }}>
                <input
                  type="text"
                  value={app.session_service_uri.split('/')[2] || ''}
                  onChange={(e) => {
                    const parts = app.session_service_uri.split('/');
                    parts[2] = e.target.value;
                    updateApp({ session_service_uri: parts.join('/') });
                  }}
                  placeholder="project-id"
                />
                <input
                  type="text"
                  value={app.session_service_uri.split('/')[3] || ''}
                  onChange={(e) => {
                    const parts = app.session_service_uri.split('/');
                    parts[3] = e.target.value;
                    updateApp({ session_service_uri: parts.join('/') });
                  }}
                  placeholder="location (e.g., us-central1)"
                />
                <input
                  type="text"
                  value={app.session_service_uri.split('/')[4] || ''}
                  onChange={(e) => {
                    const parts = app.session_service_uri.split('/');
                    parts[4] = e.target.value;
                    updateApp({ session_service_uri: parts.join('/') });
                  }}
                  placeholder="agent-engine-id"
                />
          </div>
            )}
            <span className="help-text" style={{ marginTop: 4, fontSize: 11, color: 'var(--text-dim)' }}>
              {app.session_service_uri.startsWith('memory://') && 'Sessions stored in memory, lost on restart'}
              {app.session_service_uri.startsWith('file://') && 'Sessions stored as JSON files, preserves UI events'}
              {app.session_service_uri.startsWith('sqlite://') && 'Persists to local SQLite file'}
              {app.session_service_uri.startsWith('postgresql://') && 'Production-ready PostgreSQL backend'}
              {app.session_service_uri.startsWith('mysql://') && 'Production-ready MySQL backend'}
              {app.session_service_uri.startsWith('agentengine://') && 'Vertex AI Agent Engine managed sessions'}
            </span>
          </div>
          
          {/* Memory Service */}
          <div className="form-group">
            <label>Memory Service</label>
            <select
              value={app.memory_service_uri.split('://')[0]}
              onChange={(e) => {
                const type = e.target.value;
                const defaults: Record<string, string> = {
                  'memory': 'memory://',
                  'file': 'file://~/.adk-playground/memory',
                  'rag': 'rag://rag-corpus-id',
                  'agentengine': 'agentengine://project/us-central1/engine-id',
                };
                updateApp({ memory_service_uri: defaults[type] || type + '://' });
              }}
            >
              <option value="memory">In-Memory (keyword matching)</option>
              <option value="file">File System (keyword matching)</option>
              <option value="rag">Vertex AI RAG</option>
              <option value="agentengine">Vertex AI Memory Bank</option>
            </select>
            {app.memory_service_uri.startsWith('file://') && (
              <input
                type="text"
                value={app.memory_service_uri.replace('file://', '')}
                onChange={(e) => updateApp({ memory_service_uri: 'file://' + e.target.value })}
                placeholder="~/.adk-playground/memory"
                style={{ marginTop: 8 }}
              />
            )}
            {app.memory_service_uri.startsWith('rag://') && (
              <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 8 }}>
                <input
                  type="text"
                  value={app.memory_service_uri.replace('rag://', '')}
                  onChange={(e) => updateApp({ memory_service_uri: 'rag://' + e.target.value })}
                  placeholder="rag-corpus-id or full resource path"
                />
                <span className="help-text" style={{ fontSize: 11, color: 'var(--text-dim)' }}>
                  Format: projects/PROJECT/locations/LOCATION/ragCorpora/CORPUS_ID
                </span>
          </div>
            )}
            {app.memory_service_uri.startsWith('agentengine://') && (
              <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 8 }}>
                <input
                  type="text"
                  value={app.memory_service_uri.split('/')[2] || ''}
                  onChange={(e) => {
                    const parts = app.memory_service_uri.split('/');
                    parts[2] = e.target.value;
                    updateApp({ memory_service_uri: parts.join('/') });
                  }}
                  placeholder="project-id"
                />
                <input
                  type="text"
                  value={app.memory_service_uri.split('/')[3] || ''}
                  onChange={(e) => {
                    const parts = app.memory_service_uri.split('/');
                    parts[3] = e.target.value;
                    updateApp({ memory_service_uri: parts.join('/') });
                  }}
                  placeholder="location (e.g., us-central1)"
                />
                <input
                  type="text"
                  value={app.memory_service_uri.split('/')[4] || ''}
                  onChange={(e) => {
                    const parts = app.memory_service_uri.split('/');
                    parts[4] = e.target.value;
                    updateApp({ memory_service_uri: parts.join('/') });
                  }}
                  placeholder="agent-engine-id"
                />
              </div>
            )}
            <span className="help-text" style={{ marginTop: 4, fontSize: 11, color: 'var(--text-dim)' }}>
              {app.memory_service_uri.startsWith('memory://') && 'Simple keyword matching, good for prototyping'}
              {app.memory_service_uri.startsWith('file://') && 'Persists memories as JSON files'}
              {app.memory_service_uri.startsWith('rag://') && 'Semantic search using Vertex AI RAG corpus'}
              {app.memory_service_uri.startsWith('agentengine://') && 'Managed memory via Agent Engine Memory Bank'}
            </span>
          </div>
          
          {/* Artifact Service */}
          <div className="form-group">
            <label>Artifact Service</label>
            <select
              value={app.artifact_service_uri.split('://')[0] === 'gs' ? 'gs' : app.artifact_service_uri.split('://')[0]}
              onChange={(e) => {
                const type = e.target.value;
                const defaults: Record<string, string> = {
                  'memory': 'memory://',
                  'file': 'file://~/.adk-playground/artifacts',
                  'gs': 'gs://your-bucket-name',
                };
                updateApp({ artifact_service_uri: defaults[type] || type + '://' });
              }}
            >
              <option value="memory">In-Memory (dev only)</option>
              <option value="file">File System</option>
              <option value="gs">Google Cloud Storage</option>
            </select>
            {app.artifact_service_uri.startsWith('file://') && (
              <input
                type="text"
                value={app.artifact_service_uri.replace('file://', '')}
                onChange={(e) => updateApp({ artifact_service_uri: 'file://' + e.target.value })}
                placeholder="~/.adk-playground/artifacts"
                style={{ marginTop: 8 }}
              />
            )}
            {app.artifact_service_uri.startsWith('gs://') && (
              <input
                type="text"
                value={app.artifact_service_uri.replace('gs://', '')}
                onChange={(e) => updateApp({ artifact_service_uri: 'gs://' + e.target.value })}
                placeholder="bucket-name/optional-prefix"
                style={{ marginTop: 8 }}
              />
            )}
            <span className="help-text" style={{ marginTop: 4, fontSize: 11, color: 'var(--text-dim)' }}>
              {app.artifact_service_uri.startsWith('memory://') && 'Artifacts stored in memory, lost on restart'}
              {app.artifact_service_uri.startsWith('file://') && 'Persists to local filesystem'}
              {app.artifact_service_uri.startsWith('gs://') && 'Production-ready Google Cloud Storage backend'}
            </span>
          </div>
        </div>
      </section>
      
      {/* Environment Variables */}
      <section className="section">
        <div className="section-header">
          <h2 className="section-title">
            <Lock size={20} />
            Environment Variables
          </h2>
        </div>
        <p style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 16 }}>
          Set API keys and other environment variables. These are passed to the agent runtime.
        </p>
        
        {/* Quick add common env vars */}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 16 }}>
          {COMMON_ENV_VARS.filter(ev => envVars[ev.key] === undefined).map(ev => (
            <button
              key={ev.key}
              className="btn btn-secondary btn-sm"
              onClick={() => addEnvVar(ev.key)}
              title={ev.description}
            >
              <Plus size={12} />
              {ev.key}
            </button>
          ))}
        </div>
        
        {/* Env var list */}
        {Object.keys(envVars).length === 0 ? (
          <p className="empty-message">
            No environment variables set. Click a button above to add common variables, or add a custom one below.
          </p>
        ) : (
          Object.entries(envVars).map(([key, value]) => (
            <div key={key} className="list-item" style={{ alignItems: 'center' }}>
              <div style={{ flex: 1, display: 'flex', gap: 12, alignItems: 'center' }}>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 13, minWidth: 200 }}>
                  {key}
                </span>
                <div style={{ flex: 1, display: 'flex', gap: 8, alignItems: 'center' }}>
                  <input
                    type={showEnvValues[key] ? 'text' : 'password'}
                    value={value}
                    onChange={(e) => updateEnvVar(key, e.target.value)}
                    placeholder="Enter value..."
                    style={{ flex: 1 }}
                  />
                  <button
                    className="delete-item"
                    onClick={() => toggleShowEnvValue(key)}
                    title={showEnvValues[key] ? 'Hide value' : 'Show value'}
                  >
                    {showEnvValues[key] ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                </div>
              </div>
              <button className="delete-item" onClick={() => removeEnvVar(key)}>
                <Trash2 size={16} />
              </button>
            </div>
          ))
        )}
        
        {/* Add custom env var */}
        <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
          <input
            type="text"
            value={newEnvKey}
            onChange={(e) => setNewEnvKey(e.target.value.toUpperCase().replace(/[^A-Z0-9_]/g, ''))}
            placeholder="CUSTOM_VAR_NAME"
            style={{ flex: 1, fontFamily: 'var(--font-mono)' }}
            onKeyDown={(e) => e.key === 'Enter' && addEnvVar()}
          />
          <button 
            className="btn btn-secondary btn-sm" 
            onClick={() => addEnvVar()}
            disabled={!newEnvKey.trim()}
          >
            <Plus size={14} />
            Add Variable
          </button>
        </div>
      </section>
      
      {/* Models */}
      <section className="section">
        <div className="section-header">
          <h2 className="section-title">
            <Cpu size={20} />
            Models
          </h2>
          <button className="btn btn-secondary btn-sm" onClick={addModel}>
            <Plus size={14} />
            Add Model
          </button>
        </div>
        
        {models.length === 0 ? (
          <p className="empty-message">
            No models configured. Add models that agents can use.
          </p>
        ) : (
          models.map((model) => (
            <div key={model.id} className="model-card">
              <div className="model-card-header">
                <input
                  type="text"
                  value={model.name}
                  onChange={(e) => updateModel(model.id, { name: e.target.value })}
                  placeholder="Model name"
                  className="model-name-input"
                />
                <button
                  className={`default-model-btn ${app.default_model_id === model.id ? 'is-default' : ''}`}
                  onClick={() => setDefaultModel(model.id)}
                  title={app.default_model_id === model.id ? 'Default model' : 'Set as default'}
                >
                  <Star size={14} fill={app.default_model_id === model.id ? 'currentColor' : 'none'} />
                </button>
                <button className="delete-item" onClick={() => removeModel(model.id)}>
                  <Trash2 size={16} />
                </button>
              </div>
              <div className="model-card-body">
                <ModelConfigForm
                  projectId={project.id}
                  values={model}
                  onChange={(updates) => updateModel(model.id, updates)}
                />
              </div>
            </div>
          ))
        )}
      </section>
      
      {/* Advanced Options & Plugins - Two Column Layout */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
        {/* Advanced Options */}
        <section className="section" style={{ margin: 0 }}>
          <div className="section-header">
            <h2 className="section-title">
              <Zap size={20} />
              Advanced Options
            </h2>
          </div>
          
          <div className="toggle-group">
            <div 
              className={`toggle ${app.compaction.enabled ? 'active' : ''}`}
              onClick={() => updateApp({ 
                compaction: { ...app.compaction, enabled: !app.compaction.enabled } 
              })}
            />
            <div className="toggle-label">
              <strong>Event Compaction</strong>
              <span>Summarize old events</span>
            </div>
            {app.compaction.enabled && (
              <input
                type="number"
                value={app.compaction.max_events}
                onChange={(e) => updateApp({
                  compaction: { ...app.compaction, max_events: parseInt(e.target.value) || 100 }
                })}
                style={{ width: 60, padding: '4px 6px', fontSize: 12 }}
                placeholder="Max"
              />
            )}
          </div>
          
          <div className="toggle-group" style={{ marginTop: 10 }}>
            <div 
              className={`toggle ${app.context_cache.enabled ? 'active' : ''}`}
              onClick={() => updateApp({ 
                context_cache: { ...app.context_cache, enabled: !app.context_cache.enabled } 
              })}
            />
            <div className="toggle-label">
              <strong>Context Caching</strong>
              <span>Cache static instructions</span>
            </div>
            {app.context_cache.enabled && (
              <input
                type="number"
                value={app.context_cache.ttl_seconds}
                onChange={(e) => updateApp({
                  context_cache: { ...app.context_cache, ttl_seconds: parseInt(e.target.value) || 3600 }
                })}
                style={{ width: 70, padding: '4px 6px', fontSize: 12 }}
                placeholder="TTL"
              />
            )}
          </div>
          
          <div className="toggle-group" style={{ marginTop: 10 }}>
            <div 
              className={`toggle ${app.resumability.enabled ? 'active' : ''}`}
              onClick={() => updateApp({ 
                resumability: { ...app.resumability, enabled: !app.resumability.enabled } 
              })}
            />
            <div className="toggle-label">
              <strong>Resumability</strong>
              <span>Pause/resume execution</span>
            </div>
          </div>
        </section>
        
        {/* Plugins */}
        <section className="section" style={{ margin: 0 }}>
          <div className="section-header">
            <h2 className="section-title">
              <RefreshCw size={20} />
              Plugins
            </h2>
            <div className="plugin-add-dropdown">
              <select 
                className="btn btn-secondary btn-sm"
                value=""
                onChange={(e) => {
                  if (e.target.value) {
                    addPlugin(e.target.value as PluginConfig['type']);
                    e.target.value = '';
                  }
                }}
                style={{ paddingRight: 8 }}
              >
                <option value="">+ Add...</option>
                <option value="ReflectAndRetryToolPlugin">Reflect & Retry Tool</option>
                <option value="ContextFilterPlugin">Context Filter</option>
                <option value="LoggingPlugin">Logging</option>
                <option value="GlobalInstructionPlugin">Global Instruction</option>
                <option value="SaveFilesAsArtifactsPlugin">Save Files as Artifacts</option>
                <option value="MultimodalToolResultsPlugin">Multimodal Tool Results</option>
              </select>
            </div>
          </div>
          
          {app.plugins.length === 0 ? (
            <p className="empty-message">
              No plugins configured.
            </p>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {app.plugins.map((plugin, index) => (
                <div key={index} style={{ 
                  display: 'flex', 
                  flexDirection: 'column',
                  gap: 8,
                  padding: '8px',
                  background: 'var(--bg-secondary)',
                  borderRadius: 4,
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <select
                      value={plugin.type}
                      onChange={(e) => updatePlugin(index, { type: e.target.value as PluginConfig['type'] })}
                      style={{ flex: 1, fontSize: 12 }}
                    >
                      <option value="ReflectAndRetryToolPlugin">Reflect & Retry Tool</option>
                      <option value="ContextFilterPlugin">Context Filter</option>
                      <option value="LoggingPlugin">Logging</option>
                      <option value="GlobalInstructionPlugin">Global Instruction</option>
                      <option value="SaveFilesAsArtifactsPlugin">Save Files as Artifacts</option>
                      <option value="MultimodalToolResultsPlugin">Multimodal Tool Results</option>
                    </select>
                    <button 
                      className="delete-item" 
                      onClick={() => removePlugin(index)}
                      style={{ padding: 4, flexShrink: 0 }}
                    >
                      <Trash2 size={12} />
                    </button>
                  </div>
                  
                  {/* Plugin-specific configuration - compact */}
                  {plugin.type === 'ReflectAndRetryToolPlugin' && (
                    <div style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 11 }}>
                      <span>Retries:</span>
                      <input
                        type="number"
                        min="0"
                        max="10"
                        value={plugin.max_retries ?? 3}
                        onChange={(e) => updatePlugin(index, { max_retries: parseInt(e.target.value) || 0 })}
                        style={{ width: 50, padding: '2px 4px', fontSize: 11 }}
                      />
                    </div>
                  )}
                  
                  {plugin.type === 'ContextFilterPlugin' && (
                    <div style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 11 }}>
                      <span>Keep:</span>
                      <input
                        type="number"
                        min="1"
                        max="100"
                        value={plugin.num_invocations_to_keep ?? 5}
                        onChange={(e) => updatePlugin(index, { num_invocations_to_keep: parseInt(e.target.value) || 1 })}
                        style={{ width: 50, padding: '2px 4px', fontSize: 11 }}
                      />
                      <span style={{ color: 'var(--text-muted)' }}>invocations</span>
                    </div>
                  )}
                  
                  {plugin.type === 'GlobalInstructionPlugin' && (
                    <textarea
                      value={plugin.global_instruction ?? ''}
                      onChange={(e) => updatePlugin(index, { global_instruction: e.target.value })}
                      placeholder="Global instruction for all agents..."
                      rows={2}
                      style={{ width: '100%', fontSize: 11 }}
                    />
                  )}
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
      
      {/* Sandbox Settings */}
      <section className="section">
        <div className="section-header">
          <h2 className="section-title">
            <Clock size={20} />
            Sandbox Limits
          </h2>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12 }}>
          <div className="form-field">
            <label>Run Timeout</label>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <input
                type="number"
                value={sandbox.run_timeout}
                onChange={(e) => updateSandbox({ run_timeout: parseInt(e.target.value) || 3600 })}
                min={60}
                max={86400}
                step={60}
                style={{ width: 100 }}
              />
              <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                {sandbox.run_timeout >= 3600 
                  ? `${Math.floor(sandbox.run_timeout / 3600)}h ${Math.floor((sandbox.run_timeout % 3600) / 60)}m`
                  : `${Math.floor(sandbox.run_timeout / 60)}m`}
              </span>
            </div>
            <p className="field-hint">Max time for agent run (seconds)</p>
          </div>
          <div className="form-field">
            <label>Agent Memory</label>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <input
                type="number"
                value={sandbox.agent_memory_limit_mb}
                onChange={(e) => updateSandbox({ agent_memory_limit_mb: parseInt(e.target.value) || 512 })}
                min={128}
                max={8192}
                step={128}
                style={{ width: 100 }}
              />
              <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>MB</span>
            </div>
            <p className="field-hint">Memory limit for agent container</p>
          </div>
          <div className="form-field">
            <label>Agent CPU</label>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <input
                type="number"
                value={sandbox.agent_cpu_limit}
                onChange={(e) => updateSandbox({ agent_cpu_limit: parseFloat(e.target.value) || 1.0 })}
                min={0.25}
                max={8}
                step={0.25}
                style={{ width: 100 }}
              />
              <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>cores</span>
            </div>
            <p className="field-hint">CPU limit for agent container</p>
          </div>
        </div>
      </section>
      
      {/* Network Allowlist & Volume Mounts - Two Column Layout */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
        {/* Network Allowlist */}
        <section className="section" style={{ margin: 0 }}>
          <div className="section-header">
            <h2 className="section-title">
              <Shield size={20} />
              Network Allowlist
            </h2>
            <button className="btn btn-secondary btn-sm" onClick={addAllowlistPattern}>
              <Plus size={14} />
              Add
            </button>
          </div>

          <div className="toggle-group" style={{ marginBottom: 10 }}>
            <div
              className={`toggle ${sandbox.allow_all_network ? 'active' : ''}`}
              onClick={() => updateSandbox({
                allow_all_network: !sandbox.allow_all_network,
                // In allow-all mode, approvals/deny no longer apply.
                unknown_action: !sandbox.allow_all_network ? 'allow' : sandbox.unknown_action,
              })}
            />
            <div className="toggle-label">
              <strong>Allow all network connections</strong>
              <span>Disables approval/deny; still routes through the sandbox proxy</span>
            </div>
          </div>
          
          {allowlistPatterns.length === 0 ? (
            <p className="empty-message" style={{ fontSize: 11 }}>
              No custom patterns. LLM APIs allowed by default.
            </p>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {allowlistPatterns.map((pattern, index) => (
                <div key={pattern.id || index} style={{ 
                  display: 'flex', 
                  alignItems: 'center', 
                  gap: 6,
                  padding: '6px 8px',
                  background: 'var(--bg-secondary)',
                  borderRadius: 4,
                }}>
                  <Globe size={14} style={{ color: 'var(--text-muted)', flexShrink: 0 }} />
                  <input
                    type="text"
                    value={pattern.pattern}
                    onChange={(e) => updateAllowlistPattern(index, { pattern: e.target.value })}
                    placeholder="*.example.com"
                    style={{ flex: 1, padding: '4px 6px', fontSize: 11 }}
                  />
                  <select
                    value={pattern.pattern_type}
                    onChange={(e) => updateAllowlistPattern(index, { pattern_type: e.target.value as PatternType })}
                    style={{ padding: '4px', fontSize: 10, width: 70 }}
                  >
                    <option value="exact">exact</option>
                    <option value="wildcard">wild</option>
                    <option value="regex">regex</option>
                  </select>
                  <button 
                    className="delete-item" 
                    onClick={() => removeAllowlistPattern(index)}
                    style={{ padding: 4 }}
                  >
                    <Trash2 size={12} />
                  </button>
                </div>
              ))}
            </div>
          )}
        </section>
        
        {/* Volume Mounts */}
        <section className="section" style={{ margin: 0 }}>
          <div className="section-header">
            <h2 className="section-title">
              <HardDrive size={20} />
              File & Volume Mounts
            </h2>
            <button className="btn btn-secondary btn-sm" onClick={addVolumeMount}>
              <Plus size={14} />
              Add
            </button>
          </div>
          <p className="field-hint" style={{ fontSize: 10, marginBottom: 8 }}>
            Mount files or directories from host into the sandbox container.
          </p>
          
          {volumeMounts.length === 0 ? (
            <p className="empty-message" style={{ fontSize: 11 }}>
              No mounts. Example: <code>~/.mcp.conf.yml</code> → <code>/root/.mcp.conf.yml</code>
            </p>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {volumeMounts.map((mount, index) => (
                <div key={index} style={{ 
                  display: 'flex', 
                  alignItems: 'center', 
                  gap: 6,
                  padding: '6px 8px',
                  background: 'var(--bg-secondary)',
                  borderRadius: 4,
                }}>
                  <FolderOpen size={14} style={{ color: 'var(--text-muted)', flexShrink: 0 }} />
                  <input
                    type="text"
                    value={mount.host_path}
                    onChange={(e) => updateVolumeMount(index, { host_path: e.target.value })}
                    placeholder="~/.mcp.conf.yml"
                    style={{ flex: 1, padding: '4px 6px', fontSize: 11 }}
                    title="Host path (file or directory)"
                  />
                  <span style={{ color: 'var(--text-muted)', fontSize: 10 }}>→</span>
                  <input
                    type="text"
                    value={mount.container_path}
                    onChange={(e) => updateVolumeMount(index, { container_path: e.target.value })}
                    placeholder="/root/.mcp.conf.yml"
                    style={{ width: 120, padding: '4px 6px', fontSize: 11 }}
                    title="Container path"
                  />
                  <select
                    value={mount.mode}
                    onChange={(e) => updateVolumeMount(index, { mode: e.target.value as 'ro' | 'rw' })}
                    style={{ padding: '4px', fontSize: 10, width: 50 }}
                  >
                    <option value="ro">ro</option>
                    <option value="rw">rw</option>
                  </select>
                  <button 
                    className="delete-item" 
                    onClick={() => removeVolumeMount(index)}
                    style={{ padding: 4 }}
                  >
                    <Trash2 size={12} />
                  </button>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

