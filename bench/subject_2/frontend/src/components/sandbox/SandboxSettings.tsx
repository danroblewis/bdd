/**
 * Sandbox Settings component.
 * 
 * Configuration UI for the Docker sandbox including:
 * - Sandbox enable/disable toggle
 * - MCP server status display
 * - Allowlist management with pattern editor
 * - Resource limits configuration
 */

import { useState, useEffect, useCallback } from 'react';
import { 
  Shield, Server, Globe, Plus, Trash2, Edit2, Save,
  AlertTriangle, CheckCircle, XCircle, Clock,
  ChevronDown, ChevronRight, Settings, RefreshCw
} from 'lucide-react';
import type { 
  SandboxConfig, AllowlistPattern, PatternType, 
  MCPContainerStatus, SandboxInstance 
} from '../../utils/types';
import { 
  getSandboxStatus, getSandboxAllowlist, addAllowlistPattern,
  removeAllowlistPattern, persistAllowlist, getMcpContainerStatus,
  updateSandboxConfig
} from '../../utils/api';
import { PatternTester } from './PatternTester';

interface SandboxSettingsProps {
  appId: string;
  projectId: string;
  config: SandboxConfig;
  onConfigChange: (config: Partial<SandboxConfig>) => void;
  onSave: () => void;
}

// Pattern type badges
const PATTERN_TYPE_COLORS: Record<PatternType, string> = {
  exact: 'bg-blue-900/50 text-blue-300',
  wildcard: 'bg-purple-900/50 text-purple-300',
  regex: 'bg-orange-900/50 text-orange-300',
};

// MCP status icons
function getMcpStatusIcon(status: string) {
  switch (status) {
    case 'running':
      return <CheckCircle size={14} className="text-green-400" />;
    case 'error':
      return <XCircle size={14} className="text-red-400" />;
    case 'starting':
      return <Clock size={14} className="text-yellow-400 animate-pulse" />;
    default:
      return <AlertTriangle size={14} className="text-gray-400" />;
  }
}

export function SandboxSettings({
  appId,
  projectId,
  config,
  onConfigChange,
  onSave,
}: SandboxSettingsProps) {
  const [allowlist, setAllowlist] = useState<{ auto: string[]; user: AllowlistPattern[] }>({
    auto: [],
    user: [],
  });
  const [mcpStatus, setMcpStatus] = useState<MCPContainerStatus[]>([]);
  const [sandboxStatus, setSandboxStatus] = useState<SandboxInstance | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  
  // New pattern form
  const [showAddPattern, setShowAddPattern] = useState(false);
  const [newPattern, setNewPattern] = useState('');
  const [newPatternType, setNewPatternType] = useState<PatternType>('wildcard');
  
  // Expanded sections
  const [expandAllowlist, setExpandAllowlist] = useState(true);
  const [expandMcp, setExpandMcp] = useState(true);
  const [expandLimits, setExpandLimits] = useState(false);
  
  // Load data
  const loadData = useCallback(async () => {
    if (!appId) return;
    
    setLoading(true);
    setError(null);
    
    try {
      const [statusRes, allowlistRes, mcpRes] = await Promise.all([
        getSandboxStatus(appId),
        getSandboxAllowlist(appId).catch(() => ({ auto: [], user: [] })),
        getMcpContainerStatus(appId).catch(() => ({ mcp_servers: [] })),
      ]);
      
      setSandboxStatus(statusRes.instance || null);
      setAllowlist({ auto: allowlistRes.auto, user: allowlistRes.user });
      setMcpStatus(mcpRes.mcp_servers);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, [appId]);
  
  useEffect(() => {
    loadData();
  }, [loadData]);
  
  // Add pattern
  const handleAddPattern = async () => {
    if (!newPattern.trim()) return;
    
    try {
      await addAllowlistPattern(appId, newPattern.trim(), newPatternType, false, projectId);
      setNewPattern('');
      setShowAddPattern(false);
      loadData();
    } catch (err) {
      setError((err as Error).message);
    }
  };
  
  // Remove pattern
  const handleRemovePattern = async (patternId: string) => {
    try {
      await removeAllowlistPattern(appId, patternId);
      loadData();
    } catch (err) {
      setError((err as Error).message);
    }
  };
  
  // Save allowlist to project
  const handlePersistAllowlist = async () => {
    try {
      await persistAllowlist(appId, projectId);
      // Show success feedback
    } catch (err) {
      setError((err as Error).message);
    }
  };
  
  return (
    <div className="flex flex-col h-full bg-[#0a0a0f] text-gray-200 font-sans text-sm">
      {/* Header */}
      <div className="flex items-center gap-2 p-3 border-b border-gray-800 bg-[#12121a]">
        <Shield size={16} className="text-cyan-400" />
        <span className="font-semibold">Sandbox Settings</span>
        <div className="flex-1" />
        <button
          onClick={loadData}
          className="p-1 hover:bg-gray-700 rounded"
          title="Refresh"
        >
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
        </button>
      </div>
      
      {/* Error banner */}
      {error && (
        <div className="p-2 bg-red-900/30 border-b border-red-800 text-red-300 text-xs">
          {error}
        </div>
      )}
      
      <div className="flex-1 overflow-auto p-3 space-y-4">
        {/* Enable toggle */}
        <div className="flex items-center gap-3 p-3 bg-[#12121a] rounded border border-gray-800">
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={config.enabled}
              onChange={(e) => onConfigChange({ enabled: e.target.checked })}
              className="rounded"
            />
            <span className="font-medium">Enable Docker Sandbox</span>
          </label>
          <div className="flex-1 text-xs text-gray-500">
            Run agents and MCP servers in an isolated container
          </div>
        </div>
        
        {/* MCP Server Status */}
        <div className="bg-[#12121a] rounded border border-gray-800">
          <button
            onClick={() => setExpandMcp(!expandMcp)}
            className="w-full flex items-center gap-2 p-3 hover:bg-gray-800/50"
          >
            {expandMcp ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            <Server size={14} className="text-cyan-400" />
            <span className="font-medium">MCP Servers</span>
            <span className="text-xs text-gray-500">
              ({mcpStatus.length} configured)
            </span>
          </button>
          
          {expandMcp && (
            <div className="border-t border-gray-800 p-3 space-y-2">
              {mcpStatus.length === 0 ? (
                <div className="text-xs text-gray-500 italic">
                  No MCP servers configured
                </div>
              ) : (
                mcpStatus.map((mcp) => (
                  <div 
                    key={mcp.name}
                    className="flex items-center gap-2 p-2 bg-[#0a0a0f] rounded border border-gray-700"
                  >
                    {getMcpStatusIcon(mcp.status)}
                    <span className="font-mono text-xs">{mcp.name}</span>
                    <span className="text-xs text-gray-500">({mcp.transport})</span>
                    <div className="flex-1" />
                    <span className={`text-xs ${
                      mcp.status === 'running' ? 'text-green-400' :
                      mcp.status === 'error' ? 'text-red-400' :
                      'text-gray-400'
                    }`}>
                      {mcp.status}
                    </span>
                    {mcp.error && (
                      <span className="text-xs text-red-400 truncate max-w-[200px]" title={mcp.error}>
                        {mcp.error}
                      </span>
                    )}
                  </div>
                ))
              )}
              
              <div className="text-xs text-gray-500 italic mt-2">
                ⚠️ MCP servers with network access (e.g., fetch) can reach any URL unless blocked by allowlist
              </div>
            </div>
          )}
        </div>
        
        {/* Network Allowlist */}
        <div className="bg-[#12121a] rounded border border-gray-800">
          <button
            onClick={() => setExpandAllowlist(!expandAllowlist)}
            className="w-full flex items-center gap-2 p-3 hover:bg-gray-800/50"
          >
            {expandAllowlist ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            <Globe size={14} className="text-cyan-400" />
            <span className="font-medium">Network Allowlist</span>
            <span className="text-xs text-gray-500">
              ({allowlist.auto.length + allowlist.user.length} patterns)
            </span>
          </button>
          
          {expandAllowlist && (
            <div className="border-t border-gray-800">
              {/* Auto patterns */}
              {allowlist.auto.length > 0 && (
                <div className="p-3 border-b border-gray-800">
                  <div className="text-xs text-gray-500 mb-2">
                    Auto-detected (LLM providers, MCP servers):
                  </div>
                  <div className="flex flex-wrap gap-1">
                    {allowlist.auto.map((pattern, i) => (
                      <span 
                        key={i}
                        className="px-2 py-0.5 bg-gray-800 rounded text-xs font-mono"
                      >
                        {pattern}
                      </span>
                    ))}
                  </div>
                </div>
              )}
              
              {/* User patterns */}
              <div className="p-3 space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-xs text-gray-500">User-defined patterns:</span>
                  <div className="flex gap-2">
                    <button
                      onClick={handlePersistAllowlist}
                      className="px-2 py-1 text-xs bg-gray-700 rounded hover:bg-gray-600 flex items-center gap-1"
                      title="Save to project"
                    >
                      <Save size={12} />
                      Save
                    </button>
                    <button
                      onClick={() => setShowAddPattern(true)}
                      className="px-2 py-1 text-xs bg-cyan-600 rounded hover:bg-cyan-500 flex items-center gap-1"
                    >
                      <Plus size={12} />
                      Add
                    </button>
                  </div>
                </div>
                
                {allowlist.user.length === 0 ? (
                  <div className="text-xs text-gray-500 italic">
                    No user-defined patterns
                  </div>
                ) : (
                  <div className="space-y-1">
                    {allowlist.user.map((pattern) => (
                      <div 
                        key={pattern.id}
                        className="flex items-center gap-2 p-2 bg-[#0a0a0f] rounded border border-gray-700"
                      >
                        <span className={`px-1.5 py-0.5 rounded text-[10px] ${PATTERN_TYPE_COLORS[pattern.pattern_type]}`}>
                          {pattern.pattern_type}
                        </span>
                        <span className="font-mono text-xs flex-1">{pattern.pattern}</span>
                        <span className="text-xs text-gray-500">{pattern.source}</span>
                        <button
                          onClick={() => handleRemovePattern(pattern.id)}
                          className="p-1 hover:bg-red-900/30 rounded text-gray-500 hover:text-red-400"
                        >
                          <Trash2 size={12} />
                        </button>
                      </div>
                    ))}
                  </div>
                )}
                
                {/* Add pattern form */}
                {showAddPattern && (
                  <div className="p-3 bg-[#0a0a0f] rounded border border-cyan-800 mt-2 space-y-3">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-medium text-cyan-400">Add Pattern</span>
                      <button
                        onClick={() => setShowAddPattern(false)}
                        className="text-gray-500 hover:text-gray-300"
                      >
                        ×
                      </button>
                    </div>
                    
                    <input
                      type="text"
                      value={newPattern}
                      onChange={(e) => setNewPattern(e.target.value)}
                      placeholder="e.g., *.example.com/*"
                      className="w-full px-3 py-2 bg-[#1a1a24] border border-gray-600 rounded text-sm font-mono"
                    />
                    
                    <div className="flex gap-3">
                      {(['exact', 'wildcard', 'regex'] as PatternType[]).map((type) => (
                        <label key={type} className="flex items-center gap-1 text-xs">
                          <input
                            type="radio"
                            checked={newPatternType === type}
                            onChange={() => setNewPatternType(type)}
                          />
                          {type}
                        </label>
                      ))}
                    </div>
                    
                    {newPattern && (
                      <PatternTester
                        pattern={newPattern}
                        patternType={newPatternType}
                        testUrls={['api.example.com/v1/data', 'cdn.example.com/assets/logo.png']}
                        showHelp={true}
                      />
                    )}
                    
                    <div className="flex justify-end gap-2">
                      <button
                        onClick={() => setShowAddPattern(false)}
                        className="px-3 py-1 text-xs bg-gray-700 rounded hover:bg-gray-600"
                      >
                        Cancel
                      </button>
                      <button
                        onClick={handleAddPattern}
                        className="px-3 py-1 text-xs bg-cyan-600 rounded hover:bg-cyan-500"
                      >
                        Add Pattern
                      </button>
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
        
        {/* Resource Limits */}
        <div className="bg-[#12121a] rounded border border-gray-800">
          <button
            onClick={() => setExpandLimits(!expandLimits)}
            className="w-full flex items-center gap-2 p-3 hover:bg-gray-800/50"
          >
            {expandLimits ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            <Settings size={14} className="text-cyan-400" />
            <span className="font-medium">Resource Limits</span>
          </button>
          
          {expandLimits && (
            <div className="border-t border-gray-800 p-3 space-y-3">
              {/* Unknown request action */}
              <div className="flex items-center gap-3">
                <label className="text-xs text-gray-400 w-40">Unknown requests:</label>
                <select
                  value={config.unknown_action}
                  onChange={(e) => onConfigChange({ unknown_action: e.target.value as 'ask' | 'deny' | 'allow' })}
                  className="px-2 py-1 bg-[#1a1a24] border border-gray-600 rounded text-xs"
                >
                  <option value="ask">Ask for approval</option>
                  <option value="deny">Deny automatically</option>
                  <option value="allow">Allow automatically</option>
                </select>
              </div>
              
              {/* Approval timeout */}
              <div className="flex items-center gap-3">
                <label className="text-xs text-gray-400 w-40">Approval timeout:</label>
                <input
                  type="number"
                  value={config.approval_timeout}
                  onChange={(e) => onConfigChange({ approval_timeout: parseInt(e.target.value) })}
                  min={5}
                  max={300}
                  className="px-2 py-1 bg-[#1a1a24] border border-gray-600 rounded text-xs w-20"
                />
                <span className="text-xs text-gray-500">seconds</span>
              </div>
              
              {/* Agent memory limit */}
              <div className="flex items-center gap-3">
                <label className="text-xs text-gray-400 w-40">Agent memory limit:</label>
                <input
                  type="number"
                  value={config.agent_memory_limit_mb}
                  onChange={(e) => onConfigChange({ agent_memory_limit_mb: parseInt(e.target.value) })}
                  min={256}
                  max={8192}
                  step={256}
                  className="px-2 py-1 bg-[#1a1a24] border border-gray-600 rounded text-xs w-20"
                />
                <span className="text-xs text-gray-500">MB</span>
              </div>
              
              {/* Agent CPU limit */}
              <div className="flex items-center gap-3">
                <label className="text-xs text-gray-400 w-40">Agent CPU limit:</label>
                <input
                  type="number"
                  value={config.agent_cpu_limit}
                  onChange={(e) => onConfigChange({ agent_cpu_limit: parseFloat(e.target.value) })}
                  min={0.5}
                  max={8}
                  step={0.5}
                  className="px-2 py-1 bg-[#1a1a24] border border-gray-600 rounded text-xs w-20"
                />
                <span className="text-xs text-gray-500">cores</span>
              </div>
              
              {/* Run timeout */}
              <div className="flex items-center gap-3">
                <label className="text-xs text-gray-400 w-40">Run timeout:</label>
                <input
                  type="number"
                  value={config.run_timeout}
                  onChange={(e) => onConfigChange({ run_timeout: parseInt(e.target.value) })}
                  min={60}
                  max={86400}
                  step={60}
                  className="px-2 py-1 bg-[#1a1a24] border border-gray-600 rounded text-xs w-24"
                />
                <span className="text-xs text-gray-500">
                  seconds ({config.run_timeout >= 3600 
                    ? `${Math.floor(config.run_timeout / 3600)}h ${Math.floor((config.run_timeout % 3600) / 60)}m`
                    : `${Math.floor(config.run_timeout / 60)}m`})
                </span>
              </div>
            </div>
          )}
        </div>
      </div>
      
      {/* Footer */}
      <div className="flex items-center gap-2 p-3 border-t border-gray-800 bg-[#12121a]">
        <div className="flex-1 text-xs text-gray-500">
          {sandboxStatus ? (
            <>
              Sandbox: <span className={
                sandboxStatus.status === 'running' ? 'text-green-400' :
                sandboxStatus.status === 'error' ? 'text-red-400' :
                'text-gray-400'
              }>
                {sandboxStatus.status}
              </span>
            </>
          ) : (
            'Sandbox not started'
          )}
        </div>
        <button
          onClick={onSave}
          className="px-4 py-2 bg-cyan-600 rounded hover:bg-cyan-500 flex items-center gap-2"
        >
          <Save size={14} />
          Save Settings
        </button>
      </div>
    </div>
  );
}


