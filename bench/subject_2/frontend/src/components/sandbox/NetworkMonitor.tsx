/**
 * Network Monitor component for the Docker sandbox.
 * 
 * Displays real-time network activity from the sandbox, showing:
 * - Request source (agent or MCP server)
 * - Method and URL
 * - Status (allowed, denied, pending)
 * - Response time and size
 */

import { useState, useMemo } from 'react';
import { 
  Globe, Filter, Download, Eye, EyeOff, 
  CheckCircle, XCircle, Clock, AlertTriangle,
  Server, Bot
} from 'lucide-react';
import type { NetworkRequest, NetworkRequestStatus } from '../../utils/types';
import { downloadHAR } from './harExport';

interface NetworkMonitorProps {
  requests: NetworkRequest[];
  onRequestClick?: (request: NetworkRequest) => void;
  showLLMCalls?: boolean;
  onToggleLLMCalls?: (show: boolean) => void;
}

// Status colors (Wireshark-inspired)
const STATUS_COLORS: Record<NetworkRequestStatus, { bg: string; fg: string; icon: React.FC<any> }> = {
  pending: { bg: '#3d2f0d', fg: '#fde047', icon: Clock },
  allowed: { bg: '#0d3331', fg: '#5eead4', icon: CheckCircle },
  denied: { bg: '#450a0a', fg: '#fca5a5', icon: XCircle },
  completed: { bg: '#0d3331', fg: '#5eead4', icon: CheckCircle },
  error: { bg: '#450a0a', fg: '#fca5a5', icon: AlertTriangle },
};

function formatBytes(bytes?: number): string {
  if (bytes === undefined || bytes === null) return '-';
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
}

function formatTime(ms?: number): string {
  if (ms === undefined || ms === null) return '-';
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}

function getSourceIcon(source: string) {
  if (source.startsWith('mcp:')) {
    return Server;
  }
  return Bot;
}

function getSourceLabel(source: string): string {
  if (source.startsWith('mcp:')) {
    return source.substring(4);
  }
  return source;
}

export function NetworkMonitor({ 
  requests, 
  onRequestClick,
  showLLMCalls = false,
  onToggleLLMCalls,
}: NetworkMonitorProps) {
  const [filterSource, setFilterSource] = useState<string>('all');
  const [searchQuery, setSearchQuery] = useState('');
  
  // Get unique sources
  const sources = useMemo(() => {
    const unique = new Set(requests.map(r => r.source));
    return Array.from(unique);
  }, [requests]);
  
  // Filter requests
  const filteredRequests = useMemo(() => {
    return requests.filter(req => {
      // Filter by LLM calls
      if (!showLLMCalls && req.is_llm_provider) return false;
      
      // Filter by source
      if (filterSource !== 'all' && req.source !== filterSource) return false;
      
      // Filter by search
      if (searchQuery) {
        const query = searchQuery.toLowerCase();
        if (!req.url.toLowerCase().includes(query) && 
            !req.host.toLowerCase().includes(query)) {
          return false;
        }
      }
      
      return true;
    });
  }, [requests, showLLMCalls, filterSource, searchQuery]);
  
  // Stats
  const stats = useMemo(() => {
    const allowed = requests.filter(r => r.status === 'allowed' || r.status === 'completed').length;
    const denied = requests.filter(r => r.status === 'denied').length;
    const pending = requests.filter(r => r.status === 'pending').length;
    return { total: requests.length, allowed, denied, pending };
  }, [requests]);
  
  return (
    <div className="flex flex-col h-full bg-[#0a0a0f] text-gray-200 font-mono text-xs">
      {/* Header */}
      <div className="flex items-center gap-2 p-2 border-b border-gray-800 bg-[#12121a]">
        <Globe size={14} className="text-cyan-400" />
        <span className="font-semibold text-sm">Network Activity</span>
        <div className="flex-1" />
        
        {/* Search */}
        <input
          type="text"
          placeholder="Filter by URL..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="px-2 py-1 bg-[#1a1a24] border border-gray-700 rounded text-xs w-40"
        />
        
        {/* Source filter */}
        <select
          value={filterSource}
          onChange={(e) => setFilterSource(e.target.value)}
          className="px-2 py-1 bg-[#1a1a24] border border-gray-700 rounded text-xs"
        >
          <option value="all">All Sources</option>
          {sources.map(s => (
            <option key={s} value={s}>{getSourceLabel(s)}</option>
          ))}
        </select>
        
        {/* LLM toggle */}
        <button
          onClick={() => onToggleLLMCalls?.(!showLLMCalls)}
          className={`px-2 py-1 rounded text-xs flex items-center gap-1 ${
            showLLMCalls ? 'bg-cyan-600' : 'bg-gray-700'
          }`}
          title={showLLMCalls ? 'Hide LLM API calls' : 'Show LLM API calls'}
        >
          {showLLMCalls ? <Eye size={12} /> : <EyeOff size={12} />}
          LLM
        </button>
        
        {/* Export */}
        <button
          onClick={() => downloadHAR(filteredRequests)}
          className="px-2 py-1 bg-gray-700 rounded text-xs flex items-center gap-1 hover:bg-gray-600"
          title="Export as HAR"
          disabled={filteredRequests.length === 0}
        >
          <Download size={12} />
          HAR
        </button>
      </div>
      
      {/* Table header */}
      <div className="grid grid-cols-[80px_60px_1fr_100px_60px_60px] gap-2 px-2 py-1 bg-[#16161f] border-b border-gray-800 text-gray-500">
        <div>Source</div>
        <div>Method</div>
        <div>URL</div>
        <div>Status</div>
        <div>Time</div>
        <div>Size</div>
      </div>
      
      {/* Request list */}
      <div className="flex-1 overflow-auto">
        {filteredRequests.length === 0 ? (
          <div className="flex items-center justify-center h-32 text-gray-500">
            No network requests
          </div>
        ) : (
          filteredRequests.map((req) => {
            const statusConfig = STATUS_COLORS[req.status] || STATUS_COLORS.error;
            const StatusIcon = statusConfig.icon;
            const SourceIcon = getSourceIcon(req.source);
            
            return (
              <div
                key={req.id}
                onClick={() => onRequestClick?.(req)}
                className="grid grid-cols-[80px_60px_1fr_100px_60px_60px] gap-2 px-2 py-1 hover:bg-[#1a1a24] cursor-pointer border-b border-gray-800/50"
                style={{ 
                  backgroundColor: req.status === 'pending' ? statusConfig.bg : undefined,
                }}
              >
                {/* Source */}
                <div className="flex items-center gap-1 truncate">
                  <SourceIcon size={12} className="text-gray-500" />
                  <span className="truncate">{getSourceLabel(req.source)}</span>
                </div>
                
                {/* Method */}
                <div className={`font-bold ${
                  req.method === 'POST' ? 'text-green-400' :
                  req.method === 'GET' ? 'text-blue-400' :
                  req.method === 'DELETE' ? 'text-red-400' :
                  'text-gray-400'
                }`}>
                  {req.method}
                </div>
                
                {/* URL */}
                <div className="truncate text-gray-300" title={req.url}>
                  {req.host}{new URL(req.url).pathname}
                </div>
                
                {/* Status */}
                <div className="flex items-center gap-1" style={{ color: statusConfig.fg }}>
                  <StatusIcon size={12} />
                  <span>
                    {req.status === 'completed' && req.response_status 
                      ? req.response_status 
                      : req.status.toUpperCase()}
                  </span>
                </div>
                
                {/* Time */}
                <div className="text-gray-400">
                  {formatTime(req.response_time_ms)}
                </div>
                
                {/* Size */}
                <div className="text-gray-400">
                  {formatBytes(req.response_size)}
                </div>
              </div>
            );
          })
        )}
      </div>
      
      {/* Footer stats */}
      <div className="flex items-center gap-4 px-2 py-1 border-t border-gray-800 bg-[#12121a] text-gray-500">
        <span>Requests: {stats.total}</span>
        <span className="text-green-400">Allowed: {stats.allowed}</span>
        <span className="text-red-400">Denied: {stats.denied}</span>
        <span className="text-yellow-400">Pending: {stats.pending}</span>
        <div className="flex-1" />
        <span>Sources: {sources.map(s => `${getSourceLabel(s)}`).join(' | ')}</span>
      </div>
    </div>
  );
}

