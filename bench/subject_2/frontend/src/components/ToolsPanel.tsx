import { useState, useEffect, useRef, useCallback } from 'react';
import { Plus, Wrench, Trash2, Folder, FolderOpen, Code, Key, Save, Lock, Package, Server, Globe, Sparkles, Loader, RefreshCw } from 'lucide-react';
import { useStore } from '../hooks/useStore';
import type { CustomToolDefinition, BuiltinTool, MCPServerConfig } from '../utils/types';
import Editor, { Monaco } from '@monaco-editor/react';
import { generateToolCode, testMcpServer } from '../utils/api';
import { registerCompletion } from 'monacopilot';

function generateId() {
  return `tool_${Date.now().toString(36)}`;
}

// Validation function for names (alphanumeric and underscore only)
function isValidName(name: string): boolean {
  return /^[a-zA-Z0-9_]+$/.test(name);
}

const DEFAULT_TOOL_CODE = `def my_tool(tool_context: ToolContext, param1: str) -> dict:
    """Description of what this tool does.
    
    This description is shown to the LLM to help it understand when and how to use this tool.
    Be clear and specific about what the tool does and when it should be used.
    
    Args:
        tool_context: The tool context (MUST be the first parameter, named 'tool_context').
            Provides access to state, actions, memory, artifacts, and more.
        param1: Description of this parameter. The LLM uses this to understand what to pass.
            Use type hints (str, int, bool, dict, list, etc.) - the LLM uses these!
    
    Returns:
        A dictionary with the result. This will be converted to JSON and sent to the LLM.
        Always return a dict, even for errors: {"success": False, "error": "message"}
    """
    # ============================================================
    # State Management
    # ============================================================
    # Read state: value = tool_context.state.get('key', default_value)
    # Read state: value = tool_context.state['key']
    # Write state: tool_context.state['key'] = value
    # State changes are automatically tracked in state_delta
    
    # ============================================================
    # Control Flow Actions
    # ============================================================
    # Escalate to parent agent (exit loops):
    #   tool_context.actions.escalate = True
    #   tool_context.actions.skip_summarization = True
    
    # Skip LLM summarization of tool result:
    #   tool_context.actions.skip_summarization = True
    
    # Access state delta (changes made in this tool):
    #   delta = tool_context.actions.state_delta
    
    # ============================================================
    # Context Information
    # ============================================================
    # Agent info: tool_context.agent_name
    # Invocation info: tool_context.invocation_id
    # Function call ID: tool_context.function_call_id
    
    # ============================================================
    # Memory Service (async)
    # ============================================================
    # Search memory: results = await tool_context.search_memory(query)
    #   Returns: SearchMemoryResponse with .memories list
    
    # ============================================================
    # Artifacts (async)
    # ============================================================
    # List artifacts: artifacts = await tool_context.list_artifacts()
    # Load artifact: artifact = await tool_context.load_artifact(filename, version=None)
    # Save artifact: version = await tool_context.save_artifact(filename, artifact, custom_metadata=None)
    # Example:
    #   from google.genai import types
    #   artifact = types.Part.from_text(text="some content")
    #   version = await tool_context.save_artifact("report.txt", artifact)
    
    # ============================================================
    # Authentication
    # ============================================================
    # Request credentials: tool_context.request_credential(auth_config)
    # Get auth response: credential = tool_context.get_auth_response(auth_config)
    
    # ============================================================
    # User Confirmation
    # ============================================================
    # Request user confirmation before proceeding:
    #   tool_context.request_confirmation(hint="Are you sure?", payload={"action": "delete"})
    
    # ============================================================
    # Error Handling
    # ============================================================
    # Always handle errors gracefully and return informative messages:
    #   try:
    #       result = process(param1)
    #       return {"success": True, "result": result}
    #   except ValueError as e:
    #       return {"success": False, "error": f"Invalid input: {e}"}
    #   except Exception as e:
    #       return {"success": False, "error": f"Unexpected error: {e}"}
    
    # ============================================================
    # Async Tools
    # ============================================================
    # If you need async operations, make the function async:
    #   async def my_async_tool(tool_context: ToolContext, query: str) -> dict:
    #       results = await tool_context.search_memory(query)
    #       return {"memories": [m.text for m in results.memories]}
    
    return {"result": "success"}
`;

interface ToolsPanelProps {
  onSelectTool?: (id: string | null) => void;
}

export default function ToolsPanel({ onSelectTool }: ToolsPanelProps) {
  const { project, updateProject, addCustomTool, updateCustomTool, removeCustomTool, selectedToolId, setSelectedToolId, builtinTools, mcpServers: knownMcpServers } = useStore();
  const [editingCode, setEditingCode] = useState('');
  const [selectedBuiltinTool, setSelectedBuiltinTool] = useState<BuiltinTool | null>(null);
  const [activeTab, setActiveTab] = useState<'tools' | 'mcp'>('tools');
  const [selectedMcpServer, setSelectedMcpServer] = useState<string | null>(null);
  const [mcpJsonCode, setMcpJsonCode] = useState('');
  const [hasMcpChanges, setHasMcpChanges] = useState(false);
  const [isGeneratingCode, setIsGeneratingCode] = useState(false);
  const [isTestingMcp, setIsTestingMcp] = useState(false);
  const [mcpTestResult, setMcpTestResult] = useState<{ success: boolean; tools: { name: string; description: string }[]; message?: string; error?: string } | null>(null);
  const [toolNameError, setToolNameError] = useState<string | null>(null);
  const [mcpServerStatus, setMcpServerStatus] = useState<Record<string, 'unknown' | 'connected' | 'error' | 'testing'>>({});
  const [mcpServerErrors, setMcpServerErrors] = useState<Record<string, string>>({});
  const [mcpJsonEditorValue, setMcpJsonEditorValue] = useState('');
  
  if (!project) return null;
  
  const projectMcpServers = project.mcp_servers || [];
  const selectedTool = project.custom_tools.find(t => t.id === selectedToolId);
  const selectedMcp = projectMcpServers.find(s => s.name === selectedMcpServer);
  
  
  function selectTool(id: string | null) {
    setSelectedToolId(id);
    onSelectTool?.(id);
  }
  
  useEffect(() => {
    if (selectedTool) {
      setEditingCode(selectedTool.code);
      // Clear error when switching tools
      setToolNameError(null);
    }
  }, [selectedToolId]);
  
  useEffect(() => {
    if (selectedMcp) {
      setMcpJsonCode(JSON.stringify(selectedMcp, null, 2));
      setHasMcpChanges(false);
    }
  }, [selectedMcpServer]);
  
  // Sync the full mcp.json editor with project's MCP servers
  useEffect(() => {
    if (!project) return;
    const mcpJson = convertToMcpJson(project.mcp_servers || []);
    setMcpJsonEditorValue(JSON.stringify(mcpJson, null, 2));
  }, [project?.mcp_servers]);
  
  // Auto-test MCP servers when switching to MCP tab or when servers change
  useEffect(() => {
    if (activeTab === 'mcp' && projectMcpServers.length > 0) {
      // Only test servers that haven't been tested yet
      const untestedServers = projectMcpServers.filter(
        s => !mcpServerStatus[s.name] || mcpServerStatus[s.name] === 'unknown'
      );
      if (untestedServers.length > 0) {
        // Test each untested server
        untestedServers.forEach(server => {
          testMcpServerConnection(server.name);
        });
      }
    }
  }, [activeTab, projectMcpServers.length]);
  
  // Convert our MCP server config to standard mcp.json format
  function convertToMcpJson(servers: MCPServerConfig[]): { mcpServers: Record<string, any> } {
    const mcpServers: Record<string, any> = {};
    for (const server of servers) {
      const config: any = {};
      if (server.connection_type === 'stdio') {
        config.command = server.command || '';
        config.args = server.args || [];
        if (Object.keys(server.env || {}).length > 0) {
          config.env = server.env;
        }
      } else if (server.connection_type === 'sse') {
        config.url = server.url || '';
        if (Object.keys(server.headers || {}).length > 0) {
          config.headers = server.headers;
        }
      }
      if (server.timeout && server.timeout !== 30) {
        config.timeout = server.timeout;
      }
      if (server.tool_filter) {
        config.tool_filter = server.tool_filter;
      }
      if (server.tool_name_prefix) {
        config.tool_name_prefix = server.tool_name_prefix;
      }
      mcpServers[server.name] = config;
    }
    return { mcpServers };
  }
  
  // Convert standard mcp.json format back to our config
  function convertFromMcpJson(mcpJson: { mcpServers: Record<string, any> }): MCPServerConfig[] {
    const servers: MCPServerConfig[] = [];
    for (const [name, config] of Object.entries(mcpJson.mcpServers || {})) {
      const server: MCPServerConfig = {
        name,
        description: config.description || '',
        connection_type: config.url ? 'sse' : 'stdio',
        command: config.command,
        args: config.args || [],
        env: config.env || {},
        url: config.url,
        headers: config.headers || {},
        timeout: config.timeout || 30,
        tool_filter: config.tool_filter || null,
        tool_name_prefix: config.tool_name_prefix,
      };
      servers.push(server);
    }
    return servers;
  }
  
  // Handle mcp.json editor changes
  function handleMcpJsonEditorChange(value: string | undefined) {
    if (value === undefined) return;
    setMcpJsonEditorValue(value);
  }
  
  // Save mcp.json changes to project
  function handleSaveMcpJson() {
    try {
      const parsed = JSON.parse(mcpJsonEditorValue);
      const servers = convertFromMcpJson(parsed);
      updateProject({ mcp_servers: servers });
    } catch (e) {
      alert('Invalid JSON: ' + (e as Error).message);
    }
  }
  
  // Test a specific MCP server connection
  async function testMcpServerConnection(serverName: string) {
    const server = projectMcpServers.find(s => s.name === serverName);
    if (!server) return;
    
    setMcpServerStatus(prev => ({ ...prev, [serverName]: 'testing' }));
    setMcpServerErrors(prev => ({ ...prev, [serverName]: '' })); // Clear previous error
    
    try {
      const result = await testMcpServer({
        connection_type: server.connection_type,
        command: server.command,
        args: server.args,
        env: server.env,
        url: server.url,
        headers: server.headers,
        timeout: server.timeout,
      });
      
      setMcpServerStatus(prev => ({ ...prev, [serverName]: result.success ? 'connected' : 'error' }));
      if (!result.success && result.error) {
        setMcpServerErrors(prev => ({ ...prev, [serverName]: result.error || 'Unknown error' }));
      }
    } catch (e) {
      setMcpServerStatus(prev => ({ ...prev, [serverName]: 'error' }));
      setMcpServerErrors(prev => ({ ...prev, [serverName]: (e as Error).message }));
    }
  }
  
  // Add a known MCP server to the project
  function addKnownMcpServer(serverName: string) {
    const knownServer = knownMcpServers.find(s => s.name === serverName);
    if (!knownServer) return;
    
    // Check if already added
    if (projectMcpServers.some(s => s.name === serverName)) {
      alert(`Server "${serverName}" is already configured`);
      return;
    }
    
    // Add to project
    const newServer: MCPServerConfig = {
      name: knownServer.name,
      description: knownServer.description || '',
      connection_type: knownServer.connection_type,
      command: knownServer.command,
      args: knownServer.args || [],
      env: knownServer.env || {},
      url: knownServer.url,
      headers: knownServer.headers || {},
      timeout: knownServer.timeout || 30,
      tool_filter: knownServer.tool_filter || null,
      tool_name_prefix: knownServer.tool_name_prefix,
    };
    
    updateProject({ mcp_servers: [...projectMcpServers, newServer] });
  }
  
  // Test all MCP servers
  async function testAllMcpServers() {
    for (const server of projectMcpServers) {
      await testMcpServerConnection(server.name);
    }
  }
  
  function handleAddTool() {
    const id = generateId();
    const tool: CustomToolDefinition = {
      id,
      name: 'new_tool',
      description: '',
      module_path: 'tools.custom',
      code: DEFAULT_TOOL_CODE,
      state_keys_used: []
    };
    addCustomTool(tool);
    selectTool(id);
  }
  
  function handleDeleteTool(id: string, e: React.MouseEvent) {
    e.stopPropagation();
    if (!confirm('Delete this tool?')) return;
    removeCustomTool(id);
    if (selectedToolId === id) {
      onSelectTool?.(null);
    }
  }
  
  function handleUpdateTool(updates: Partial<CustomToolDefinition>) {
    if (!selectedTool) return;
    
    // Validate name if it's being updated
    if (updates.name !== undefined) {
      if (updates.name === '') {
        setToolNameError(null);
      } else if (!isValidName(updates.name)) {
        setToolNameError('Name can only contain letters, numbers, and underscores');
      } else {
        setToolNameError(null);
      }
    }
    
    updateCustomTool(selectedTool.id, updates);
  }
  
  function handleCodeChange(value: string | undefined) {
    if (value !== undefined && selectedTool) {
      setEditingCode(value);
      // Auto-save code changes like other fields
      handleUpdateTool({ code: value });
    }
  }
  
  async function handleWriteTool() {
    if (!selectedTool) return;
    
    setIsGeneratingCode(true);
    try {
      const result = await generateToolCode(
        project.id,
        selectedTool.name,
        selectedTool.description,
        selectedTool.state_keys_used
      );
      
      if (result.success && result.code) {
        setEditingCode(result.code);
        handleUpdateTool({ code: result.code });
      } else {
        console.error('Failed to generate tool code:', result.error);
        alert('Failed to generate tool code: ' + (result.error || 'Unknown error'));
      }
    } catch (error) {
      console.error('Error generating tool code:', error);
      alert('Error generating tool code: ' + (error as Error).message);
    } finally {
      setIsGeneratingCode(false);
    }
  }
  
  // Monaco editor mount handler for Monacopilot
  const completionCleanupRef = useRef<(() => void) | null>(null);
  
  const handleEditorMount = useCallback((editor: any, monaco: Monaco) => {
    // Clean up previous completion registration
    if (completionCleanupRef.current && typeof completionCleanupRef.current === 'function') {
      try {
      completionCleanupRef.current();
      } catch (e) {
        // Ignore cleanup errors
      }
    }
    
    // Register Monacopilot completion
    try {
    const cleanup = registerCompletion(monaco, editor, {
      language: 'python',
      endpoint: '/api/code-completion',
      trigger: 'onTyping', // Also supports 'onIdle' or 'onDemand'
    });
    
      // Only store if it's actually a function
      if (typeof cleanup === 'function') {
    completionCleanupRef.current = cleanup;
      } else {
        completionCleanupRef.current = null;
      }
    } catch (e) {
      // If registration fails, clear the ref
      completionCleanupRef.current = null;
    }
  }, []);
  
  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (completionCleanupRef.current && typeof completionCleanupRef.current === 'function') {
        try {
        completionCleanupRef.current();
        } catch (e) {
          // Ignore cleanup errors
        }
      }
    };
  }, []);
  
  // MCP Server management
  function handleAddMcpServer() {
    const newServer: MCPServerConfig = {
      name: `mcp_server_${Date.now().toString(36)}`,
      description: 'New MCP Server',
      connection_type: 'stdio',
      command: 'npx',
      args: ['-y', '@modelcontextprotocol/server-example'],
      env: {},
      headers: {},
      timeout: 10,
      // tool_filter: null means no filter (all tools available)
    };
    updateProject({
      mcp_servers: [...projectMcpServers, newServer]
    });
    setSelectedMcpServer(newServer.name);
  }
  
  
  function handleDeleteMcpServer(name: string, e: React.MouseEvent) {
    e.stopPropagation();
    if (!confirm('Delete this MCP server?')) return;
    updateProject({
      mcp_servers: projectMcpServers.filter(s => s.name !== name)
    });
    if (selectedMcpServer === name) {
      setSelectedMcpServer(null);
    }
  }
  
  function handleMcpJsonChange(value: string | undefined) {
    if (value !== undefined) {
      setMcpJsonCode(value);
      setHasMcpChanges(value !== JSON.stringify(selectedMcp, null, 2));
    }
  }
  
  function handleSaveMcpServer() {
    if (!selectedMcp) return;
    try {
      const parsed = JSON.parse(mcpJsonCode) as MCPServerConfig;
      // Ensure name is preserved or updated
      const oldName = selectedMcp.name;
      const newServers = projectMcpServers.map(s => 
        s.name === oldName ? parsed : s
      );
      updateProject({ mcp_servers: newServers });
      setSelectedMcpServer(parsed.name);
      setHasMcpChanges(false);
    } catch (e) {
      alert('Invalid JSON: ' + (e as Error).message);
    }
  }
  
  async function handleTestMcpServer() {
    setIsTestingMcp(true);
    setMcpTestResult(null);
    
    try {
      // Parse the current JSON to get config
      const config = JSON.parse(mcpJsonCode) as MCPServerConfig;
      
      const result = await testMcpServer({
        connection_type: config.connection_type,
        command: config.command,
        args: config.args,
        env: config.env,
        url: config.url,
        headers: config.headers,
        timeout: config.timeout || 30,
      });
      
      setMcpTestResult(result);
      
      // If successful and we found tools, offer to update the tool_filter
      if (result.success && result.tools.length > 0) {
        const updatedConfig = {
          ...config,
          tool_filter: result.tools.map(t => t.name),
        };
        setMcpJsonCode(JSON.stringify(updatedConfig, null, 2));
        setHasMcpChanges(true);
      }
    } catch (e) {
      setMcpTestResult({
        success: false,
        tools: [],
        error: (e as Error).message,
      });
    } finally {
      setIsTestingMcp(false);
    }
  }
  
  // Group tools by module path
  const toolsByModule: Record<string, CustomToolDefinition[]> = {};
  project.custom_tools.forEach(tool => {
    const module = tool.module_path || 'tools';
    if (!toolsByModule[module]) toolsByModule[module] = [];
    toolsByModule[module].push(tool);
  });
  
  return (
    <div className="tools-panel">
      <style>{`
        .tools-panel {
          display: flex;
          gap: 20px;
          height: calc(100vh - 180px);
        }
        
        .tools-sidebar {
          width: 280px;
          flex-shrink: 0;
          display: flex;
          flex-direction: column;
          background: var(--bg-secondary);
          border: 1px solid var(--border-color);
          border-radius: var(--radius-lg);
          overflow: hidden;
        }
        
        .sidebar-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 12px 16px;
          border-bottom: 1px solid var(--border-color);
        }
        
        .sidebar-header h3 {
          font-size: 14px;
          font-weight: 600;
        }
        
        .tools-tree {
          flex: 1;
          overflow-y: auto;
          padding: 8px;
        }
        
        .module-group {
          margin-bottom: 8px;
        }
        
        .module-header {
          display: flex;
          align-items: center;
          gap: 6px;
          padding: 6px 8px;
          color: var(--text-muted);
          font-size: 12px;
          font-weight: 600;
          text-transform: uppercase;
        }
        
        .module-header svg {
          color: var(--accent-secondary);
        }
        
        .tool-item {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 8px 12px;
          margin-left: 20px;
          border-radius: var(--radius-md);
          cursor: pointer;
          transition: all 0.15s ease;
        }
        
        .tool-item:hover {
          background: var(--bg-tertiary);
        }
        
        .tool-item.selected {
          background: var(--bg-hover);
          border: 1px solid var(--accent-primary);
        }
        
        .tool-item svg {
          color: var(--accent-primary);
          flex-shrink: 0;
        }
        
        .tool-name {
          flex: 1;
          font-size: 13px;
          font-weight: 500;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        
        .delete-btn {
          padding: 4px;
          color: var(--text-muted);
          opacity: 0;
          transition: all 0.15s ease;
        }
        
        .tool-item:hover .delete-btn {
          opacity: 1;
        }
        
        .delete-btn:hover {
          color: var(--error);
        }
        
        .tool-editor {
          flex: 1;
          display: flex;
          flex-direction: column;
          background: var(--bg-secondary);
          border: 1px solid var(--border-color);
          border-radius: var(--radius-lg);
          overflow: hidden;
        }
        
        .editor-header {
          display: flex;
          align-items: center;
          gap: 12px;
          padding: 12px 16px;
          border-bottom: 1px solid var(--border-color);
        }
        
        .editor-header input {
          flex: 1;
          font-size: 1.1rem;
          font-weight: 600;
          background: transparent;
          border: none;
          padding: 4px 8px;
        }
        
        .editor-header input:focus {
          background: var(--bg-tertiary);
          border-radius: var(--radius-sm);
        }
        
        .editor-meta {
          display: flex;
          gap: 16px;
          padding: 12px 16px;
          border-bottom: 1px solid var(--border-color);
          background: var(--bg-tertiary);
        }
        
        .meta-field {
          display: flex;
          flex-direction: column;
          gap: 4px;
        }
        
        .meta-field label {
          font-size: 11px;
          text-transform: uppercase;
          color: var(--text-muted);
        }
        
        .meta-field input, .meta-field textarea {
          padding: 6px 10px;
          font-size: 13px;
        }
        
        .meta-field.grow {
          flex: 1;
        }
        
        .code-actions {
          display: flex;
          align-items: center;
          gap: 12px;
          padding: 8px 16px;
          background: var(--bg-tertiary);
          border-bottom: 1px solid var(--border-color);
        }
        
        .code-actions .btn {
          display: inline-flex;
          align-items: center;
          gap: 6px;
        }
        
        .code-actions .action-hint {
          font-size: 11px;
          color: var(--text-muted);
        }
        
        .spinning {
          animation: spin 1s linear infinite;
        }
        
        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
        
        .code-editor {
          flex: 1;
          min-height: 0;
        }
        
        .state-keys-panel {
          padding: 12px 16px;
          border-top: 1px solid var(--border-color);
          background: var(--bg-tertiary);
        }
        
        .state-keys-panel h4 {
          font-size: 12px;
          font-weight: 600;
          margin-bottom: 8px;
          display: flex;
          align-items: center;
          gap: 6px;
        }
        
        .state-keys-panel h4 svg {
          color: var(--accent-primary);
        }
        
        .state-key-chips {
          display: flex;
          flex-wrap: wrap;
          gap: 6px;
        }
        
        .state-key-chip {
          display: flex;
          align-items: center;
          gap: 4px;
          padding: 4px 8px;
          background: var(--bg-secondary);
          border-radius: var(--radius-sm);
          font-size: 12px;
          cursor: pointer;
          transition: all 0.15s ease;
        }
        
        .state-key-chip:hover {
          background: var(--bg-hover);
        }
        
        .state-key-chip.selected {
          background: var(--accent-primary);
          color: var(--bg-primary);
        }
        
        .state-key-chip input {
          width: 12px;
          height: 12px;
          margin: 0;
        }
        
        .empty-state {
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          height: 100%;
          color: var(--text-muted);
          text-align: center;
          padding: 40px;
        }
        
        .empty-state svg {
          margin-bottom: 16px;
          opacity: 0.3;
        }
        
        .unsaved-badge {
          font-size: 11px;
          padding: 2px 8px;
          background: rgba(255, 217, 61, 0.15);
          color: var(--warning);
          border-radius: 999px;
        }
        
        .tool-item.builtin svg {
          color: var(--accent-secondary);
        }
        
        .tool-item.builtin .tool-name {
          color: var(--text-secondary);
        }
        
        .builtin-tool-info {
          padding: 24px;
          flex: 1;
          overflow-y: auto;
        }
        
        .info-section {
          margin-bottom: 24px;
        }
        
        .info-section h4 {
          font-size: 12px;
          font-weight: 600;
          text-transform: uppercase;
          color: var(--text-muted);
          margin-bottom: 8px;
        }
        
        .info-section p {
          font-size: 14px;
          line-height: 1.6;
          color: var(--text-secondary);
          margin-bottom: 8px;
        }
        
        .info-section code {
          display: block;
          padding: 12px 16px;
          background: var(--bg-primary);
          border-radius: var(--radius-md);
          font-family: var(--font-mono);
          font-size: 13px;
          color: var(--accent-primary);
        }
        
        .badge-muted {
          background: var(--bg-tertiary);
          color: var(--text-muted);
          font-size: 11px;
          padding: 2px 8px;
          border-radius: 999px;
        }
        
        .sidebar-tabs {
          display: flex;
          border-bottom: 1px solid var(--border-color);
        }
        
        .sidebar-tab {
          flex: 1;
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 6px;
          padding: 12px;
          font-size: 13px;
          font-weight: 500;
          color: var(--text-muted);
          background: transparent;
          border: none;
          cursor: pointer;
          transition: all 0.15s ease;
        }
        
        .sidebar-tab:hover {
          color: var(--text-primary);
          background: var(--bg-tertiary);
        }
        
        .sidebar-tab.active {
          color: var(--accent-primary);
          background: var(--bg-tertiary);
          border-bottom: 2px solid var(--accent-primary);
        }
        
        .tool-type-badge {
          font-size: 10px;
          padding: 2px 6px;
          background: var(--bg-primary);
          color: var(--text-muted);
          border-radius: 4px;
          text-transform: uppercase;
        }
        
        .mcp-info {
          padding: 12px 16px;
          background: var(--bg-tertiary);
          border-bottom: 1px solid var(--border-color);
          font-size: 13px;
          color: var(--text-secondary);
        }
        
        .mcp-test-result {
          padding: 12px 16px;
          border-bottom: 1px solid var(--border-color);
          font-size: 13px;
        }
        
        .mcp-test-result.success {
          background: rgba(0, 245, 212, 0.1);
          border-left: 3px solid var(--accent-primary);
        }
        
        .mcp-test-result.error {
          background: rgba(255, 107, 107, 0.1);
          border-left: 3px solid var(--error);
        }
        
        .mcp-test-result .test-result-header {
          font-weight: 600;
          margin-bottom: 8px;
        }
        
        .mcp-test-result.success .test-result-header {
          color: var(--accent-primary);
        }
        
        .mcp-test-result.error .test-result-header {
          color: var(--error);
        }
        
        .mcp-test-result .test-result-error {
          color: var(--error);
          font-family: var(--font-mono);
          font-size: 12px;
          white-space: pre-wrap;
          word-break: break-word;
        }
        
        .mcp-test-result .test-result-tools ul {
          margin: 8px 0;
          padding-left: 20px;
          max-height: 200px;
          overflow-y: auto;
        }
        
        .mcp-test-result .test-result-tools li {
          margin: 4px 0;
          line-height: 1.4;
        }
        
        .mcp-test-result .test-result-tools code {
          background: var(--bg-primary);
          padding: 2px 6px;
          border-radius: 4px;
          font-size: 12px;
        }
        
        .mcp-test-result .hint {
          margin-top: 8px;
          font-size: 12px;
          color: var(--text-muted);
          font-style: italic;
        }
        
        .spin {
          animation: spin 1s linear infinite;
        }
        
        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
        
        .mcp-servers-list {
          flex: 1;
          overflow-y: auto;
          padding: 8px;
        }
        
        .mcp-server-item-wrapper {
          margin-bottom: 6px;
        }
        
        .mcp-server-item {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 10px 12px;
          background: var(--bg-tertiary);
          border-radius: var(--radius-md);
          transition: all 0.15s ease;
        }
        
        .mcp-server-item:hover {
          background: var(--bg-primary);
        }
        
        .mcp-server-error {
          padding: 6px 12px;
          margin-top: 2px;
          background: rgba(var(--error-rgb, 239, 68, 68), 0.1);
          border-radius: 0 0 var(--radius-md) var(--radius-md);
          font-size: 11px;
          color: var(--text-secondary);
          word-break: break-word;
          max-height: 60px;
          overflow-y: auto;
        }
        
        .mcp-server-info {
          display: flex;
          align-items: center;
          gap: 8px;
        }
        
        .mcp-server-name {
          font-weight: 500;
        }
        
        .mcp-status-badge {
          width: 8px;
          height: 8px;
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 8px;
        }
        
        .mcp-status-badge.unknown {
          color: var(--text-muted);
        }
        
        .mcp-status-badge.connected {
          color: var(--accent-primary);
        }
        
        .mcp-status-badge.error {
          color: var(--error);
        }
        
        .mcp-status-badge.testing {
          color: var(--accent-secondary);
        }
        
        .mcp-server-actions {
          display: flex;
          align-items: center;
          gap: 8px;
        }
        
        .mcp-server-type {
          font-size: 11px;
          color: var(--text-muted);
          text-transform: uppercase;
        }
        
        .mcp-json-editor {
          display: flex;
          flex-direction: column;
          height: 100%;
        }
        
        .mcp-json-info {
          padding: 12px 16px;
          background: var(--bg-tertiary);
          border-bottom: 1px solid var(--border-color);
          font-size: 13px;
          color: var(--text-secondary);
        }
        
        .mcp-json-info code {
          background: var(--bg-primary);
          padding: 2px 6px;
          border-radius: 4px;
          font-family: var(--font-mono);
        }
        
        .mcp-help {
          padding: 16px;
          border-top: 1px solid var(--border-color);
          background: var(--bg-tertiary);
        }
        
        .mcp-help h4 {
          font-size: 12px;
          font-weight: 600;
          color: var(--text-muted);
          text-transform: uppercase;
          margin-bottom: 12px;
        }
        
        .schema-fields {
          display: flex;
          flex-direction: column;
          gap: 8px;
        }
        
        .schema-field {
          display: flex;
          align-items: baseline;
          gap: 12px;
          font-size: 12px;
        }
        
        .schema-field code {
          font-family: var(--font-mono);
          color: var(--accent-primary);
          background: var(--bg-secondary);
          padding: 2px 6px;
          border-radius: 4px;
          min-width: 120px;
        }
        
        .schema-field span {
          color: var(--text-muted);
        }
        
        .tool-item.known-server svg {
          color: var(--accent-secondary);
        }
        
        .known-server-preview {
          flex: 1;
          padding: 20px;
          overflow-y: auto;
        }
        
        .preview-section {
          margin-bottom: 20px;
        }
        
        .preview-section h4 {
          font-size: 12px;
          font-weight: 600;
          text-transform: uppercase;
          color: var(--text-muted);
          margin-bottom: 8px;
        }
        
        .preview-section p {
          font-size: 14px;
          line-height: 1.6;
          color: var(--text-secondary);
        }
        
        .preview-section > code {
          display: block;
          padding: 12px;
          background: var(--bg-primary);
          border-radius: var(--radius-sm);
          font-family: var(--font-mono);
          font-size: 13px;
          color: var(--accent-primary);
          word-break: break-all;
        }
        
        .env-vars {
          display: flex;
          flex-direction: column;
          gap: 8px;
        }
        
        .env-var {
          display: flex;
          align-items: center;
          gap: 12px;
          padding: 8px 12px;
          background: var(--bg-tertiary);
          border-radius: var(--radius-sm);
        }
        
        .env-var code {
          font-family: var(--font-mono);
          color: var(--accent-primary);
          font-size: 12px;
        }
        
        .env-value {
          font-size: 12px;
          color: var(--text-muted);
          font-family: var(--font-mono);
        }
        
        .env-required {
          font-size: 11px;
          padding: 2px 8px;
          background: rgba(255, 107, 107, 0.15);
          color: var(--error);
          border-radius: 999px;
        }
        
        .tool-badges {
          display: flex;
          flex-wrap: wrap;
          gap: 6px;
        }
        
        .tool-badge {
          padding: 4px 10px;
          background: rgba(0, 245, 212, 0.1);
          color: var(--accent-primary);
          border-radius: 999px;
          font-size: 12px;
          font-family: var(--font-mono);
        }
        
        .config-preview {
          padding: 12px;
          background: var(--bg-primary);
          border-radius: var(--radius-sm);
          font-family: var(--font-mono);
          font-size: 12px;
          overflow-x: auto;
          max-height: 200px;
          overflow-y: auto;
        }
      `}</style>
      
      <aside className="tools-sidebar">
        <div className="sidebar-tabs">
          <button 
            className={`sidebar-tab ${activeTab === 'tools' ? 'active' : ''}`}
            onClick={() => {
              setActiveTab('tools');
              // Clear MCP-specific selections when switching to tools
              setSelectedMcpServer(null);
            }}
          >
            <Wrench size={14} />
            Tools
          </button>
          <button 
            className={`sidebar-tab ${activeTab === 'mcp' ? 'active' : ''}`}
            onClick={() => {
              setActiveTab('mcp');
              // Clear selections so mcp.json editor shows
              setSelectedToolId(null);
              setSelectedBuiltinTool(null);
              setSelectedMcpServer(null);
            }}
          >
            <Server size={14} />
            MCP
          </button>
        </div>
        
        {activeTab === 'tools' ? (
          <>
            <div className="sidebar-header">
              <h3>Custom Tools ({project.custom_tools.length})</h3>
              <button className="btn btn-primary btn-sm" onClick={handleAddTool}>
                <Plus size={14} />
                New
              </button>
            </div>
            <div className="tools-tree">
              {/* Built-in Tools Section */}
              {builtinTools.length > 0 && (
                <div className="module-group">
                  <div className="module-header">
                    <Package size={14} />
                    Built-in Tools
                  </div>
                  {builtinTools.map(tool => (
                    <div
                      key={tool.name}
                      className={`tool-item builtin ${selectedBuiltinTool?.name === tool.name ? 'selected' : ''}`}
                      onClick={() => {
                        setSelectedBuiltinTool(tool);
                        selectTool(null);
                        setSelectedMcpServer(null);
                      }}
                    >
                      <Lock size={14} />
                      <span className="tool-name">{tool.name}</span>
                    </div>
                  ))}
                </div>
              )}
              
              {/* Custom Tools Section */}
              {project.custom_tools.length === 0 && builtinTools.length === 0 ? (
                <div className="empty-state">
                  <Code size={32} />
                  <p>No tools defined yet</p>
                </div>
              ) : project.custom_tools.length > 0 && (
                Object.entries(toolsByModule).map(([module, tools]) => (
                  <div key={module} className="module-group">
                    <div className="module-header">
                      <FolderOpen size={14} />
                      {module}
                    </div>
                    {tools.map(tool => (
                      <div
                        key={tool.id}
                        className={`tool-item ${selectedToolId === tool.id ? 'selected' : ''}`}
                        onClick={() => {
                          selectTool(tool.id);
                          setSelectedBuiltinTool(null);
                          setSelectedMcpServer(null);
                        }}
                      >
                        <Wrench size={14} />
                        <span className="tool-name">{tool.name}</span>
                        <button className="delete-btn" onClick={(e) => handleDeleteTool(tool.id, e)}>
                          <Trash2 size={14} />
                        </button>
                      </div>
                    ))}
                  </div>
                ))
              )}
            </div>
          </>
        ) : (
          <>
            <div className="sidebar-header">
              <h3>MCP Servers ({projectMcpServers.length})</h3>
              <button className="btn btn-secondary btn-sm" onClick={testAllMcpServers} title="Test all server connections">
                <RefreshCw size={14} />
              </button>
            </div>
            <div className="mcp-servers-list">
              {projectMcpServers.length === 0 ? (
                <div className="empty-state">
                  <Server size={32} />
                  <p>No MCP servers configured</p>
                  <p style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                    Edit the JSON to add servers
                  </p>
                </div>
              ) : (
                projectMcpServers.map(server => {
                  const status = mcpServerStatus[server.name] || 'unknown';
                  const errorMsg = mcpServerErrors[server.name];
                  return (
                    <div key={server.name} className="mcp-server-item-wrapper">
                      <div className="mcp-server-item">
                        <div className="mcp-server-info">
                          <Server size={14} />
                          <span className="mcp-server-name">{server.name}</span>
                          <span className={`mcp-status-badge ${status}`}>
                            {status === 'testing' ? <Loader size={10} className="spin" /> : null}
                            {status === 'unknown' && '●'}
                            {status === 'connected' && '●'}
                            {status === 'error' && '●'}
                          </span>
                        </div>
                        <div className="mcp-server-actions">
                          <span className="mcp-server-type">{server.connection_type}</span>
                          <button 
                            className="btn btn-sm" 
                            onClick={() => testMcpServerConnection(server.name)}
                            disabled={status === 'testing'}
                            title="Test server connection"
                            style={{ display: 'flex', alignItems: 'center', gap: 4 }}
                          >
                            {status === 'testing' ? <Loader size={12} className="spin" /> : <RefreshCw size={12} />}
                            <span style={{ fontSize: 11 }}>Test</span>
                          </button>
                        </div>
                      </div>
                      {status === 'error' && errorMsg && (
                        <div className="mcp-server-error">
                          <span style={{ fontWeight: 500, color: 'var(--error)' }}>Error:</span> {errorMsg}
                        </div>
                      )}
                    </div>
                  );
                })
              )}
            </div>
          </>
        )}
      </aside>
      
      <div className="tool-editor">
        {selectedBuiltinTool ? (
          <>
            <div className="editor-header">
              <Lock size={20} style={{ color: 'var(--accent-secondary)' }} />
              <span style={{ fontSize: '1.1rem', fontWeight: 600 }}>{selectedBuiltinTool.name}</span>
              <span className="badge badge-muted">Built-in</span>
            </div>
            
            <div className="builtin-tool-info">
              <div className="info-section">
                <h4>Description</h4>
                <p>{selectedBuiltinTool.description || 'No description available.'}</p>
              </div>
              
              <div className="info-section">
                <h4>Usage</h4>
                <p>This is a built-in tool provided by ADK. Add it to any LLM agent's tools list to enable it.</p>
                <code>tools: ["{selectedBuiltinTool.name}"]</code>
              </div>
              
              <div className="info-section">
                <h4>Note</h4>
                <p>Built-in tools are read-only and cannot be modified. Create a custom tool if you need different behavior.</p>
              </div>
            </div>
          </>
        ) : selectedTool ? (
          <>
            <div className="editor-header">
              <Wrench size={20} style={{ color: 'var(--accent-primary)' }} />
              <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 4 }}>
              <input
                type="text"
                value={selectedTool.name}
                onChange={(e) => handleUpdateTool({ name: e.target.value })}
                placeholder="Tool name"
                  style={{ borderColor: toolNameError ? 'var(--error)' : undefined }}
                />
                {toolNameError && (
                  <span style={{ fontSize: 11, color: 'var(--error)', marginTop: -4 }}>
                    {toolNameError}
                  </span>
                )}
              </div>
            </div>
            
            <div className="editor-meta">
              <div className="meta-field grow">
                <label>Description</label>
                <input
                  type="text"
                  value={selectedTool.description}
                  onChange={(e) => handleUpdateTool({ description: e.target.value })}
                  placeholder="What does this tool do?"
                />
              </div>
              <div className="meta-field">
                <label>Module Path</label>
                <input
                  type="text"
                  value={selectedTool.module_path}
                  onChange={(e) => handleUpdateTool({ module_path: e.target.value })}
                  placeholder="tools.custom"
                  style={{ width: 180 }}
                />
              </div>
            </div>
            
            <div className="code-actions">
              <button 
                className="btn btn-secondary btn-sm"
                onClick={handleWriteTool}
                disabled={isGeneratingCode || !selectedTool.name || !selectedTool.description}
                title={!selectedTool.name || !selectedTool.description ? 'Add a name and description first' : 'Generate code using AI'}
              >
                {isGeneratingCode ? (
                  <>
                    <Loader size={14} className="spinning" />
                    Generating...
                  </>
                ) : (
                  <>
                    <Sparkles size={14} />
                    Write Tool
                  </>
                )}
              </button>
              <span className="action-hint">
                AI will generate code based on the tool name, description, and selected state keys
              </span>
            </div>
            
            <div className="code-editor">
              <Editor
                height="100%"
                language="python"
                theme="vs-dark"
                value={editingCode}
                onChange={handleCodeChange}
                onMount={handleEditorMount}
                options={{
                  minimap: { enabled: false },
                  fontSize: 13,
                  fontFamily: "'JetBrains Mono', monospace",
                  lineNumbers: 'on',
                  scrollBeyondLastLine: false,
                  automaticLayout: true,
                  tabSize: 4,
                  insertSpaces: true,
                  padding: { top: 12 },
                }}
              />
            </div>
            
            <div className="state-keys-panel">
              <h4><Key size={14} /> State Keys Used</h4>
              <div className="state-key-chips">
                {project.app.state_keys.length === 0 ? (
                  <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                    No state keys defined. Add them in App Config.
                  </span>
                ) : (
                  project.app.state_keys.map(key => {
                    const isUsed = selectedTool.state_keys_used.includes(key.name);
                    return (
                      <label
                        key={key.name}
                        className={`state-key-chip ${isUsed ? 'selected' : ''}`}
                        title={key.description}
                      >
                        <input
                          type="checkbox"
                          checked={isUsed}
                          onChange={(e) => {
                            const newKeys = e.target.checked
                              ? [...selectedTool.state_keys_used, key.name]
                              : selectedTool.state_keys_used.filter(k => k !== key.name);
                            handleUpdateTool({ state_keys_used: newKeys });
                          }}
                        />
                        {key.name}
                        <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>
                          ({key.type})
                        </span>
                      </label>
                    );
                  })
                )}
              </div>
            </div>
          </>
        ) : selectedMcp ? (
          <>
            <div className="editor-header">
              <Server size={20} style={{ color: 'var(--accent-primary)' }} />
              <span style={{ fontSize: '1.1rem', fontWeight: 600 }}>{selectedMcp.name}</span>
              <span className="badge badge-info">{selectedMcp.connection_type}</span>
              {hasMcpChanges && <span className="unsaved-badge">Unsaved</span>}
              <button 
                className="btn btn-secondary btn-sm"
                onClick={handleTestMcpServer}
                disabled={isTestingMcp}
                title="Test connection and discover available tools"
              >
                {isTestingMcp ? <Loader size={14} className="spin" /> : <Globe size={14} />}
                {isTestingMcp ? 'Testing...' : 'Test Connection'}
              </button>
              <button 
                className="btn btn-primary btn-sm"
                onClick={handleSaveMcpServer}
                disabled={!hasMcpChanges}
              >
                <Save size={14} />
                Save
              </button>
            </div>
            
            {mcpTestResult && (
              <div className={`mcp-test-result ${mcpTestResult.success ? 'success' : 'error'}`}>
                {mcpTestResult.success ? (
                  <>
                    <div className="test-result-header">
                      ✓ Connected! Found {mcpTestResult.tools.length} tools
                    </div>
                    {mcpTestResult.tools.length > 0 && (
                      <div className="test-result-tools">
                        <strong>Available tools:</strong>
                        <ul>
                          {mcpTestResult.tools.map(tool => (
                            <li key={tool.name}>
                              <code>{tool.name}</code>
                              {tool.description && <span> — {tool.description}</span>}
                            </li>
                          ))}
                        </ul>
                        <p className="hint">The tool_filter has been updated with these tools. Click "Save" to apply.</p>
                      </div>
                    )}
                  </>
                ) : (
                  <>
                    <div className="test-result-header">✗ Connection failed</div>
                    <div className="test-result-error">{mcpTestResult.error}</div>
                  </>
                )}
              </div>
            )}
            
            <div className="mcp-info">
              <p>Configure your MCP server using JSON. Click "Test Connection" to verify and discover available tools.</p>
            </div>
            
            <div className="code-editor">
              <Editor
                height="100%"
                language="json"
                theme="vs-dark"
                value={mcpJsonCode}
                onChange={handleMcpJsonChange}
                options={{
                  minimap: { enabled: false },
                  fontSize: 13,
                  fontFamily: "'JetBrains Mono', monospace",
                  lineNumbers: 'on',
                  scrollBeyondLastLine: false,
                  automaticLayout: true,
                  tabSize: 2,
                  insertSpaces: true,
                  padding: { top: 12 },
                  formatOnPaste: true,
                }}
              />
            </div>
            
            <div className="mcp-help">
              <h4>Schema Reference</h4>
              <div className="schema-fields">
                <div className="schema-field">
                  <code>name</code>
                  <span>Unique identifier for this server</span>
                </div>
                <div className="schema-field">
                  <code>description</code>
                  <span>Human-readable description</span>
                </div>
                <div className="schema-field">
                  <code>connection_type</code>
                  <span>"stdio" | "sse" | "http"</span>
                </div>
                <div className="schema-field">
                  <code>command</code>
                  <span>Command to run (for stdio)</span>
                </div>
                <div className="schema-field">
                  <code>args</code>
                  <span>Array of command arguments</span>
                </div>
                <div className="schema-field">
                  <code>env</code>
                  <span>Environment variables object</span>
                </div>
                <div className="schema-field">
                  <code>url</code>
                  <span>Server URL (for sse/http)</span>
                </div>
                <div className="schema-field">
                  <code>tool_filter</code>
                  <span>Array of tool names to include (null/omit = all tools, [] = no tools)</span>
                </div>
              </div>
            </div>
          </>
        ) : activeTab === 'mcp' ? (
          <div className="mcp-json-editor">
            <div className="editor-header">
              <Server size={20} style={{ color: 'var(--accent-primary)' }} />
              <span style={{ fontSize: '1.1rem', fontWeight: 600 }}>mcp.json</span>
              <span className="badge badge-muted">Model Context Protocol</span>
              <select
                value=""
                onChange={(e) => {
                  if (e.target.value) {
                    addKnownMcpServer(e.target.value);
                  }
                }}
                style={{ 
                  padding: '6px 10px', 
                  fontSize: '12px', 
                  borderRadius: '6px',
                  background: 'var(--bg-tertiary)',
                  border: '1px solid var(--border-color)',
                  color: 'var(--text-primary)',
                }}
              >
                <option value="">+ Add known server...</option>
                {knownMcpServers
                  .filter(s => !projectMcpServers.some(ps => ps.name === s.name))
                  .map(server => (
                    <option key={server.name} value={server.name}>
                      {server.name} - {server.description || 'No description'}
                    </option>
                  ))
                }
              </select>
              <button 
                className="btn btn-primary btn-sm"
                onClick={handleSaveMcpJson}
              >
                <Save size={14} />
                Apply Changes
              </button>
            </div>
            
            <div className="mcp-json-info">
              <p>
                Configure your MCP servers using the standard <code>mcp.json</code> format.
                Select a known server from the dropdown to add its configuration.
              </p>
            </div>
            
            <div className="editor-content" style={{ flex: 1 }}>
              <Editor
                height="100%"
                defaultLanguage="json"
                value={mcpJsonEditorValue}
                onChange={handleMcpJsonEditorChange}
                theme="vs-dark"
                options={{
                  minimap: { enabled: false },
                  fontSize: 14,
                  lineNumbers: 'on',
                  scrollBeyondLastLine: false,
                  wordWrap: 'on',
                  tabSize: 2,
                  formatOnPaste: true,
                  formatOnType: true,
                }}
              />
            </div>
          </div>
        ) : (
          <div className="empty-state">
            <Code size={48} />
            <p>Select a tool to view<br />or create a new custom tool</p>
          </div>
        )}
      </div>
    </div>
  );
}

