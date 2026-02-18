import { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import { createPortal } from 'react-dom';
import * as d3 from 'd3';
import { 
  Play, Square, Clock, Cpu, Wrench, GitBranch, MessageSquare, Database, 
  ChevronDown, ChevronRight, Zap, Filter, Search, Terminal, Eye,
  CheckCircle, XCircle, AlertTriangle, Copy, RefreshCw, Layers, Plus, Trash2, X,
  Download, Upload, Code, TestTube, FileBox, Image, File, Activity
} from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import { useStore } from '../hooks/useStore';
import type { RunEvent, Project, MCPServerConfig, ApprovalRequest, PatternType } from '../utils/types';
import { createRunWebSocket, fetchJSON, getMcpServers, saveSessionToMemory, listProjectSessions, loadSession, listArtifacts, getArtifactUrl, getSystemMetrics, type ArtifactInfo, type SystemMetrics } from '../utils/api';
import { NetworkApprovalDialog } from './sandbox/NetworkApprovalDialog';
import AgentGraph from './AgentGraph';

// Wireshark-inspired color scheme for event types
const EVENT_COLORS: Record<string, { bg: string; fg: string; border: string }> = {
  agent_start: { bg: '#2d1f4e', fg: '#c4b5fd', border: '#7c3aed' },
  agent_end: { bg: '#2d1f4e', fg: '#c4b5fd', border: '#7c3aed' },
  tool_call: { bg: '#0d3331', fg: '#5eead4', border: '#14b8a6' },
  tool_result: { bg: '#0d3331', fg: '#5eead4', border: '#14b8a6' },
  model_call: { bg: '#3d2f0d', fg: '#fde047', border: '#eab308' },
  model_response: { bg: '#3d2f0d', fg: '#fde047', border: '#eab308' },
  callback_error: { bg: '#450a0a', fg: '#fca5a5', border: '#dc2626' },
  state_change: { bg: '#3d0d1f', fg: '#fda4af', border: '#f43f5e' },
  transfer: { bg: '#0d2d3d', fg: '#7dd3fc', border: '#0ea5e9' },
  callback_start: { bg: '#1a1a2e', fg: '#a29bfe', border: '#6c5ce7' },
  callback_end: { bg: '#1a1a2e', fg: '#a29bfe', border: '#6c5ce7' },
  error: { bg: '#450a0a', fg: '#fca5a5', border: '#dc2626' },
};

// Event type icons
const EVENT_ICONS: Record<string, React.FC<{ size: number }>> = {
  agent_start: GitBranch,
  agent_end: GitBranch,
  tool_call: Wrench,
  tool_result: Wrench,
  model_call: Cpu,
  model_response: MessageSquare,
  state_change: Database,
  transfer: Zap,
  callback_start: Code,
  callback_end: Code,
  callback_error: AlertTriangle,
};

// Agent color palette - visually distinct colors for identifying agents
// Using muted tones that work well as pill backgrounds with light text
const AGENT_COLORS = [
  { bg: '#0e7490', fg: '#e0f2fe' },  // Cyan (muted)
  { bg: '#6d28d9', fg: '#ede9fe' },  // Purple (muted)
  { bg: '#047857', fg: '#d1fae5' },  // Emerald (muted)
  { bg: '#b91c1c', fg: '#fee2e2' },  // Red (muted)
  { bg: '#b45309', fg: '#fef3c7' },  // Amber (muted)
  { bg: '#1d4ed8', fg: '#dbeafe' },  // Blue (muted)
  { bg: '#be185d', fg: '#fce7f3' },  // Pink (muted)
  { bg: '#4d7c0f', fg: '#ecfccb' },  // Lime (muted)
  { bg: '#7c3aed', fg: '#ede9fe' },  // Violet (muted)
  { bg: '#0f766e', fg: '#ccfbf1' },  // Teal (muted)
  { bg: '#c2410c', fg: '#ffedd5' },  // Orange (muted)
  { bg: '#4338ca', fg: '#e0e7ff' },  // Indigo (muted)
];

// Cache for agent name -> color index mapping
const agentColorCache = new Map<string, number>();

// Get a consistent color for an agent name
function getAgentColor(agentName: string): { bg: string; fg: string } {
  // Special cases for system agents
  if (agentName === 'sandbox' || agentName === 'system') {
    return { bg: '#374151', fg: '#9ca3af' };  // Gray for system
  }
  
  // Check cache first
  let colorIndex = agentColorCache.get(agentName);
  if (colorIndex === undefined) {
    // Generate a hash from the agent name for consistent color assignment
    let hash = 0;
    for (let i = 0; i < agentName.length; i++) {
      hash = ((hash << 5) - hash) + agentName.charCodeAt(i);
      hash = hash & hash; // Convert to 32bit integer
    }
    colorIndex = Math.abs(hash) % AGENT_COLORS.length;
    agentColorCache.set(agentName, colorIndex);
  }
  
  return AGENT_COLORS[colorIndex];
}

// Single-line event summary renderer
function getEventSummary(event: RunEvent): string {
  switch (event.event_type) {
    case 'agent_start':
      return `START ${event.agent_name}`;
    case 'agent_end':
      if (event.data?.error) {
        const hint = event.data?.hint ? ` 💡 ${event.data.hint.slice(0, 100)}` : '';
        return `END ${event.agent_name} [ERROR] ${event.data.error}${hint}`;
      }
      return `END ${event.agent_name}`;
    case 'tool_call':
      const args = Object.entries(event.data?.args || {})
        .map(([k, v]) => {
          const valStr = v !== undefined && v !== null ? JSON.stringify(v) : 'null';
          return `${k}=${valStr.slice(0, 500)}${valStr.length > 500 ? '...' : ''}`;
        })
        .join(', ');
      const argsStr = args || '';
      return `CALL ${event.data?.tool_name || 'unknown'}(${argsStr.slice(0, 1000)}${argsStr.length > 1000 ? '...' : ''})`;
    case 'tool_result':
      const result = event.data?.result;
      let resultPreview = '';
      if (result?.content?.[0]?.text) {
        resultPreview = String(result.content[0].text).slice(0, 500);
      } else if (typeof result === 'string') {
        resultPreview = result.slice(0, 500);
      } else if (result !== undefined && result !== null) {
        const jsonStr = JSON.stringify(result);
        resultPreview = jsonStr ? jsonStr.slice(0, 500) : '';
      } else {
        resultPreview = '';
      }
      return `RESULT ${event.data?.tool_name || 'unknown'} → ${resultPreview}${resultPreview.length >= 500 ? '...' : ''}`;
    case 'model_call':
      return `LLM_REQ ${event.data?.contents?.length || 0} msgs, ${event.data?.tool_count || 0} tools`;
    case 'model_response':
      const parts = event.data?.response_content?.parts || event.data?.parts || [];
      const fnCall = parts.find((p: any) => p?.type === 'function_call');
      if (fnCall) return `LLM_RSP → ${fnCall.name || 'unknown'}()`;
      const textPart = parts.find((p: any) => p?.type === 'text');
      if (textPart?.text) {
        const text = String(textPart.text);
        return `LLM_RSP "${text.slice(0, 50)}${text.length > 50 ? '...' : ''}"`;
      }
      return `LLM_RSP (${event.data?.finish_reason || 'complete'})`;
    case 'state_change':
      const keys = Object.keys(event.data?.state_delta || {});
      return `STATE ${keys.join(', ')}`;
    case 'transfer':
      return `TRANSFER → ${event.data?.target || 'unknown'}`;
    case 'callback_start':
      const callbackName = event.data?.callback_name || 'unknown';
      const callbackType = event.data?.callback_type || '';
      // Special handling for network_approval
      if (callbackName === 'network_approval') {
        return `⏳ AWAITING APPROVAL ${event.data?.host || event.data?.url || ''}`;
      }
      return `CALLBACK START ${callbackType ? `[${callbackType}]` : ''} ${callbackName}`;
    case 'callback_end':
      const endCallbackName = event.data?.callback_name || 'unknown';
      const endCallbackType = event.data?.callback_type || '';
      const hadError = event.data?.error ? ' [ERROR]' : '';
      // Special handling for network_approval
      if (endCallbackName === 'network_approval') {
        const action = event.data?.action;
        if (action === 'deny') {
          return `🚫 DENIED ${event.data?.host || ''}`;
        }
        return `✅ APPROVED ${event.data?.pattern || event.data?.host || ''}`;
      }
      return `CALLBACK END ${endCallbackType ? `[${endCallbackType}]` : ''} ${endCallbackName}${hadError}`;
    case 'callback_error':
      const errorSource = event.data?.source || 'unknown';
      const errorMsg = event.data?.error || 'Unknown error';
      return `⚠️ ERROR in ${errorSource}: ${errorMsg.slice(0, 50)}${errorMsg.length > 50 ? '...' : ''}`;
    case 'compaction':
      const preview = event.data?.summary_preview || '';
      return `📦 COMPACTION "${preview.slice(0, 80)}${preview.length > 80 ? '...' : ''}"`;
    default:
      return event.event_type?.toUpperCase() || 'UNKNOWN';
  }
}

// Format timestamp as relative time
function formatTimestamp(timestamp: number, baseTime: number): string {
  const delta = timestamp - baseTime;
  if (delta < 1) return `+${(delta * 1000).toFixed(0)}ms`;
  if (delta < 60) return `+${delta.toFixed(2)}s`;
  return `+${Math.floor(delta / 60)}m${(delta % 60).toFixed(0)}s`;
}

// Syntax highlighting for container logs
function highlightLogLine(line: string): React.ReactNode {
  // Color scheme
  const colors = {
    timestamp: '#71717a',      // Gray - ISO timestamps at start of lines
    bracket: '#a78bfa',        // Purple - content in square brackets
    ip: '#22d3ee',             // Cyan - IP addresses
    domain: '#34d399',         // Green - domain names and hostnames
    url: '#60a5fa',            // Blue - URLs and paths
    method: '#f472b6',         // Pink - HTTP methods
    status: '#4ade80',         // Green - success status codes
    statusError: '#f87171',    // Red - error status codes  
    number: '#fbbf24',         // Yellow - numbers with units
    keyword: '#c084fc',        // Light purple - keywords
    info: '#22d3ee',           // Cyan - INFO level
    warning: '#fbbf24',        // Yellow - WARNING level
    error: '#f87171',          // Red - ERROR level
    debug: '#71717a',          // Gray - DEBUG level
  };

  const parts: React.ReactNode[] = [];
  let remaining = line;
  let keyIndex = 0;

  const addPart = (text: string, color?: string) => {
    if (!text) return;
    parts.push(
      color 
        ? <span key={keyIndex++} style={{ color }}>{text}</span>
        : <span key={keyIndex++}>{text}</span>
    );
  };

  // Process line with regex patterns
  const patterns: Array<{ regex: RegExp; color: string; group?: number }> = [
    // ISO timestamp at start of line (2025-12-14T15:02:06.947686251Z)
    { regex: /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z?\s*)/, color: colors.timestamp },
    // Square bracket content [anything]
    { regex: /(\[[^\]]+\])/, color: colors.bracket },
    // HTTP methods
    { regex: /\b(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS|CONNECT)\b/, color: colors.method },
    // HTTP status codes 2xx/3xx (success)
    { regex: /\b([23]\d{2})\s+(OK|Created|Accepted|No Content|Moved|Found|Not Modified)\b/, color: colors.status },
    // HTTP status codes 4xx/5xx (error)
    { regex: /\b([45]\d{2})\s+\w+/, color: colors.statusError },
    // << response prefix with status
    { regex: /(<< \d{3} \w+)/, color: colors.status },
    // URLs and paths (http://... or /path/to/something)
    { regex: /(https?:\/\/[^\s]+)/, color: colors.url },
    { regex: /(\s)(\/[a-zA-Z0-9_\-./]+)/, color: colors.url, group: 2 },
    // IP:port patterns
    { regex: /(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d+)/, color: colors.ip },
    // IP addresses
    { regex: /(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})/, color: colors.ip },
    // Domain names (sandbox-agent-xxx:port, host.docker.internal, etc)
    { regex: /(sandbox-agent-[a-zA-Z0-9_-]+:\d+)/, color: colors.domain },
    { regex: /(host\.docker\.internal:\d+)/, color: colors.domain },
    { regex: /([a-zA-Z][a-zA-Z0-9-]*\.(?:com|org|net|io|dev|local|internal)(?::\d+)?)/, color: colors.domain },
    // Numbers with units (200b, 2.1k, 155b, etc)
    { regex: /\b(\d+(?:\.\d+)?[kmgb])\b/i, color: colors.number },
    // Log levels
    { regex: /\b(INFO)\b/, color: colors.info },
    { regex: /\b(WARNING|WARN)\b/, color: colors.warning },
    { regex: /\b(ERROR|CRITICAL|FATAL)\b/, color: colors.error },
    { regex: /\b(DEBUG)\b/, color: colors.debug },
    // Python module paths (aiohttp.access, google_adk.google.adk.models, etc)
    { regex: /([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*){2,})/, color: colors.domain },
    // Keywords
    { regex: /\b(client|server|connect|disconnect|completion|model|provider)\b/i, color: colors.keyword },
  ];

  // Simple approach: process patterns one at a time on remaining text
  while (remaining.length > 0) {
    let earliestMatch: { index: number; length: number; text: string; color: string } | null = null;

    for (const { regex, color, group } of patterns) {
      const match = remaining.match(regex);
      if (match && match.index !== undefined) {
        const matchIndex = group ? remaining.indexOf(match[group], match.index) : match.index;
        const matchText = group ? match[group] : match[0];
        if (!earliestMatch || matchIndex < earliestMatch.index) {
          earliestMatch = {
            index: matchIndex,
            length: matchText.length,
            text: matchText,
            color,
          };
        }
      }
    }

    if (earliestMatch) {
      // Add text before match
      if (earliestMatch.index > 0) {
        addPart(remaining.slice(0, earliestMatch.index));
      }
      // Add matched text with color
      addPart(earliestMatch.text, earliestMatch.color);
      // Continue with remaining text
      remaining = remaining.slice(earliestMatch.index + earliestMatch.length);
    } else {
      // No more matches, add remaining text
      addPart(remaining);
      break;
    }
  }

  return <>{parts}</>;
}

// Highlight full log content
function HighlightedLogs({ content }: { content: string }) {
  const lines = content.split('\n');
  return (
    <>
      {lines.map((line, i) => (
        <div key={i}>{highlightLogLine(line)}</div>
      ))}
    </>
  );
}

// Full event detail renderer
function EventDetail({ event }: { event: RunEvent }) {
  const [expandedSections, setExpandedSections] = useState<Set<string>>(new Set(['instruction', 'messages', 'result', 'response', 'state_delta', 'data']));
  const [stringModalContent, setStringModalContent] = useState<string | null>(null);
  
  const toggleSection = (section: string) => {
    const next = new Set(expandedSections);
    if (next.has(section)) next.delete(section);
    else next.add(section);
    setExpandedSections(next);
  };
  
  const renderValue = (value: any, depth = 0, inline = false): React.ReactNode => {
    const indent = '  '.repeat(depth);
    const childIndent = '  '.repeat(depth + 1);
    
    if (value === null) return <span className="json-null">null</span>;
    if (value === undefined) return <span className="json-undefined">undefined</span>;
    if (typeof value === 'boolean') return <span className="json-boolean">{value.toString()}</span>;
    if (typeof value === 'number') return <span className="json-number">{value}</span>;
    if (typeof value === 'string') {
      // Escape special characters for display
      const escaped = value.replace(/\\/g, '\\\\').replace(/"/g, '\\"').replace(/\n/g, '\\n').replace(/\t/g, '\\t');
      // Make strings clickable to open in markdown modal
      const handleClick = () => setStringModalContent(value);
      if (escaped.length > 300 && depth > 0) {
        return (
          <span 
            className="json-string json-string-clickable" 
            onClick={handleClick}
            title="Click to view as Markdown"
          >
            "{escaped.slice(0, 300)}..." <span className="json-truncated">({value.length} chars)</span>
          </span>
        );
      }
      return (
        <span 
          className="json-string json-string-clickable" 
          onClick={handleClick}
          title="Click to view as Markdown"
        >
          "{escaped}"
        </span>
      );
    }
    if (Array.isArray(value)) {
      if (value.length === 0) return <span className="json-bracket">[]</span>;
      // Check if array contains only primitives and is short
      const isSimple = value.every(v => v === null || typeof v !== 'object') && value.length <= 3;
      if (isSimple) {
        return (
          <span className="json-inline">
            <span className="json-bracket">[</span>
            {value.map((item, i) => (
              <span key={i}>
                {renderValue(item, depth + 1, true)}
                {i < value.length - 1 && <span className="json-comma">, </span>}
              </span>
            ))}
            <span className="json-bracket">]</span>
          </span>
        );
      }
      return (
        <span className="json-block">
          <span className="json-bracket">[</span>
          {value.map((item, i) => (
            <span key={i}>
              {'\n' + childIndent}
              {renderValue(item, depth + 1)}
              {i < value.length - 1 && <span className="json-comma">,</span>}
            </span>
          ))}
          {'\n' + indent}<span className="json-bracket">]</span>
        </span>
      );
    }
    if (typeof value === 'object') {
      const entries = Object.entries(value);
      if (entries.length === 0) return <span className="json-bracket">{'{}'}</span>;
      // Check if object is simple (few keys, primitive values)
      const isSimple = entries.length <= 2 && entries.every(([, v]) => v === null || typeof v !== 'object');
      if (isSimple && inline) {
        return (
          <span className="json-inline">
            <span className="json-bracket">{'{'}</span>
            {entries.map(([k, v], i) => (
              <span key={k}>
                <span className="json-key">"{k}"</span>
                <span className="json-colon">: </span>
                {renderValue(v, depth + 1, true)}
                {i < entries.length - 1 && <span className="json-comma">, </span>}
              </span>
            ))}
            <span className="json-bracket">{'}'}</span>
          </span>
        );
      }
      return (
        <span className="json-block">
          <span className="json-bracket">{'{'}</span>
          {entries.map(([k, v], i) => (
            <span key={k}>
              {'\n' + childIndent}
              <span className="json-key">"{k}"</span>
              <span className="json-colon">: </span>
              {renderValue(v, depth + 1)}
              {i < entries.length - 1 && <span className="json-comma">,</span>}
            </span>
          ))}
          {'\n' + indent}<span className="json-bracket">{'}'}</span>
        </span>
      );
    }
    return String(value);
  };
  
  return (
    <div className="event-detail">
      {/* Header */}
      <div className="detail-header">
        <span className="detail-type">{event.event_type}</span>
        <span 
          className="detail-agent"
          style={{ 
            backgroundColor: getAgentColor(event.agent_name).bg,
            color: getAgentColor(event.agent_name).fg,
            padding: '2px 8px',
            borderRadius: '4px',
            fontWeight: 600,
          }}
        >
          {event.agent_name}
        </span>
        <span className="detail-time">{new Date(event.timestamp * 1000).toISOString()}</span>
      </div>
      
      {/* Error Details - show prominently if there's an error */}
      {event.data?.error && (
        <div className="detail-section" style={{ borderColor: '#dc2626' }}>
          <div className="section-header" style={{ color: '#fca5a5' }}>
            <AlertTriangle size={12} style={{ color: '#ef4444' }} />
            <span>⚠️ Error</span>
          </div>
          <div className="section-content" style={{ color: '#fca5a5' }}>
            <div style={{ marginBottom: '8px' }}>
              <strong>Message:</strong> {event.data.error}
            </div>
            {event.data.hint && (
              <div style={{ 
                marginBottom: '8px', 
                padding: '8px 12px', 
                backgroundColor: 'rgba(34, 197, 94, 0.1)', 
                borderRadius: '6px',
                borderLeft: '3px solid #22c55e',
              }}>
                <strong style={{ color: '#22c55e' }}>💡 Hint:</strong>{' '}
                <span style={{ color: '#86efac' }}>{event.data.hint}</span>
              </div>
            )}
            {event.data.error_type && event.data.error_type !== 'unknown' && (
              <div style={{ fontSize: '0.9em', opacity: 0.8 }}>
                <strong>Type:</strong> {event.data.error_type}
              </div>
            )}
            {event.data.sub_errors && event.data.sub_errors.length > 0 && (
              <div style={{ marginTop: '12px' }}>
                <strong>Sub-errors ({event.data.sub_errors.length}):</strong>
                {event.data.sub_errors.map((subErr: any, i: number) => (
                  <div key={i} style={{ 
                    marginTop: '8px', 
                    marginLeft: '12px', 
                    padding: '8px', 
                    backgroundColor: 'rgba(220, 38, 38, 0.1)',
                    borderRadius: '4px',
                  }}>
                    <div><strong>{subErr.exception_type}:</strong> {subErr.message}</div>
                    {subErr.hint && (
                      <div style={{ 
                        marginTop: '4px', 
                        color: '#86efac', 
                        fontSize: '0.9em' 
                      }}>
                        💡 {subErr.hint}
                      </div>
                    )}
                    {subErr.stack_trace && (
                      <details style={{ marginTop: '6px' }}>
                        <summary style={{ cursor: 'pointer', opacity: 0.7, fontSize: '0.9em' }}>
                          Stack trace
                        </summary>
                        <pre style={{ 
                          marginTop: '4px', 
                          padding: '6px', 
                          backgroundColor: '#1a1a1a', 
                          borderRadius: '4px',
                          fontSize: '0.75em',
                          overflow: 'auto',
                          maxHeight: '200px',
                          whiteSpace: 'pre-wrap',
                          wordBreak: 'break-word',
                          fontFamily: 'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace',
                        }}>
                          {subErr.stack_trace}
                        </pre>
                      </details>
                    )}
                  </div>
                ))}
              </div>
            )}
            {event.data.stack_trace && (
              <details style={{ marginTop: '12px' }}>
                <summary style={{ cursor: 'pointer', opacity: 0.8, fontWeight: 500 }}>
                  📋 Stack Trace
                </summary>
                <pre style={{ 
                  marginTop: '4px', 
                  padding: '8px', 
                  backgroundColor: '#1a1a1a', 
                  borderRadius: '4px',
                  fontSize: '0.8em',
                  overflow: 'auto',
                  maxHeight: '400px',
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-word',
                  fontFamily: 'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace',
                  lineHeight: '1.4',
                }}>
                  {event.data.stack_trace}
                </pre>
              </details>
            )}
            {event.data.raw_error && event.data.raw_error !== event.data.error && !event.data.stack_trace && (
              <details style={{ marginTop: '8px' }}>
                <summary style={{ cursor: 'pointer', opacity: 0.7 }}>Raw error</summary>
                <pre style={{ 
                  marginTop: '4px', 
                  padding: '8px', 
                  backgroundColor: '#1a1a1a', 
                  borderRadius: '4px',
                  fontSize: '0.85em',
                  overflow: 'auto',
                  maxHeight: '200px',
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-word'
                }}>
                  {event.data.raw_error}
                </pre>
              </details>
            )}
          </div>
        </div>
      )}
      
      {/* Event Data - full JSON */}
      <div className="detail-section">
        <div className="section-header" onClick={() => toggleSection('data')}>
          {expandedSections.has('data') ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          <span>Event Data</span>
        </div>
        {expandedSections.has('data') && (
          <div className="section-content json-viewer">
            {renderValue(event.data)}
          </div>
        )}
      </div>
      
      {/* Type-specific rendering */}
      {event.event_type === 'agent_start' && event.data?.instruction && (
        <div className="detail-section">
          <div className="section-header" onClick={() => toggleSection('instruction')}>
            {expandedSections.has('instruction') ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
            <span>Instruction</span>
            <span className="char-count">{event.data.instruction.length} chars</span>
          </div>
          {expandedSections.has('instruction') && (
            <div className="section-content">
              <pre className="instruction-text">{event.data.instruction}</pre>
            </div>
          )}
        </div>
      )}
      
      {event.event_type === 'model_call' && event.data?.contents && (
        <div className="detail-section">
          <div className="section-header" onClick={() => toggleSection('messages')}>
            {expandedSections.has('messages') ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
            <span>Messages ({event.data.contents.length})</span>
          </div>
          {expandedSections.has('messages') && (
            <div className="section-content">
              {event.data.contents.map((content: any, i: number) => (
                <div key={i} className="message-item">
                  <span className={`message-role ${content.role}`}>{content.role}</span>
                  <div className="message-parts">
                    {content.parts?.map((part: any, j: number) => (
                      <div key={j} className="message-part">
                        {part.text && <pre>{part.text}</pre>}
                        {part.function_call && (
                          <div className="function-call">
                            <strong>{part.function_call.name}</strong>
                            <pre>{JSON.stringify(part.function_call.args, null, 2)}</pre>
                          </div>
                        )}
                        {part.function_response && (
                          <div className="function-response">
                            <strong>{part.function_response.name}</strong>
                            <pre>{JSON.stringify(part.function_response.response, null, 2)}</pre>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
      
      {event.event_type === 'tool_result' && (
        <div className="detail-section">
          <div className="section-header" onClick={() => toggleSection('result')}>
            {expandedSections.has('result') ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
            <span>Tool Result</span>
          </div>
          {expandedSections.has('result') && (
            <div className="section-content">
              <pre className="result-content">
                {event.data?.result?.content?.[0]?.text || 
                 (typeof event.data?.result === 'string' ? event.data.result : JSON.stringify(event.data?.result, null, 2))}
              </pre>
            </div>
          )}
        </div>
      )}
      
      {event.event_type === 'model_response' && event.data?.parts && (
        <div className="detail-section">
          <div className="section-header" onClick={() => toggleSection('response')}>
            {expandedSections.has('response') ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
            <span>Response ({event.data.parts.length} part{event.data.parts.length !== 1 ? 's' : ''})</span>
            {event.data.token_counts && (
              <span className="token-badge">
                {event.data.token_counts.input}↑ {event.data.token_counts.output}↓
              </span>
            )}
          </div>
          {expandedSections.has('response') && (
            <div className="section-content">
              {event.data.parts.map((part: any, i: number) => (
                <div key={i} className="response-part">
                  {part.type === 'text' && part.text && (
                    <pre className="response-text">{part.text}</pre>
                  )}
                  {part.type === 'function_call' && (
                    <div className="function-call">
                      <strong>→ {part.name}()</strong>
                      {part.args && Object.keys(part.args).length > 0 && (
                        <pre>{JSON.stringify(part.args, null, 2)}</pre>
                      )}
                    </div>
                  )}
                  {part.thought && (
                    <div className="thought-indicator">💭 Thinking</div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
      
      {(event.event_type === 'callback_start' || event.event_type === 'callback_end') && (
        <div className="detail-section">
          <div className="section-header" onClick={() => toggleSection('callback_info')}>
            {expandedSections.has('callback_info') ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
            <span>Callback Information</span>
          </div>
          {expandedSections.has('callback_info') && (
            <div className="section-content">
              <div><strong>Name:</strong> {event.data?.callback_name || 'unknown'}</div>
              <div><strong>Type:</strong> {event.data?.callback_type || 'unknown'}</div>
              <div><strong>Module Path:</strong> {event.data?.module_path || 'unknown'}</div>
              {event.data?.error && (
                <div style={{ color: '#ef4444', marginTop: '8px' }}>
                  <div><strong>Error:</strong> {event.data.error}</div>
                  {event.data?.error_type && (
                    <div style={{ marginTop: '4px', fontSize: '0.9em', opacity: 0.8 }}>
                      <strong>Type:</strong> {event.data.error_type}
                    </div>
                  )}
                  {event.data?.stack_trace && (
                    <div style={{ marginTop: '8px' }}>
                      <strong>Stack Trace:</strong>
                      <pre style={{ 
                        marginTop: '4px', 
                        padding: '8px', 
                        backgroundColor: '#1a1a1a', 
                        borderRadius: '4px',
                        fontSize: '0.85em',
                        overflow: 'auto',
                        maxHeight: '300px',
                        whiteSpace: 'pre-wrap',
                        wordBreak: 'break-word'
                      }}>
                        {event.data.stack_trace}
                      </pre>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      )}
      
      {event.event_type === 'callback_error' && (
        <div className="detail-section" style={{ borderColor: '#dc2626' }}>
          <div className="section-header" onClick={() => toggleSection('error_info')} style={{ color: '#fca5a5' }}>
            {expandedSections.has('error_info') ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
            <span>⚠️ Error Details</span>
          </div>
          {expandedSections.has('error_info') && (
            <div className="section-content" style={{ color: '#fca5a5' }}>
              <div><strong>Source:</strong> {event.data?.source || 'unknown'}</div>
              <div><strong>Error Type:</strong> {event.data?.error_type || 'unknown'}</div>
              <div style={{ marginTop: '8px' }}><strong>Message:</strong> {event.data?.error || 'No error message'}</div>
              {event.data?.context && (
                <div style={{ marginTop: '8px' }}><strong>Context:</strong> {event.data.context}</div>
              )}
              {event.data?.traceback && (
                <div style={{ marginTop: '8px' }}>
                  <strong>Stack Trace:</strong>
                  <pre style={{ 
                    marginTop: '4px', 
                    padding: '8px', 
                    backgroundColor: '#1a1a1a', 
                    borderRadius: '4px',
                    fontSize: '0.85em',
                    overflow: 'auto',
                    maxHeight: '400px',
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-word',
                    color: '#fca5a5'
                  }}>
                    {event.data.traceback}
                  </pre>
                </div>
              )}
            </div>
          )}
        </div>
      )}
      
      {event.event_type === 'state_change' && event.data?.state_delta && (
        <div className="detail-section">
          <div className="section-header" onClick={() => toggleSection('state_delta')}>
            {expandedSections.has('state_delta') ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
            <span>State Changes ({Object.keys(event.data.state_delta).length})</span>
          </div>
          {expandedSections.has('state_delta') && (
            <div className="section-content">
              {Object.entries(event.data.state_delta).map(([key, value]: [string, any]) => (
                <div key={key} className="state-delta-item">
                  <div className="state-delta-key">{key}</div>
                  <pre className="state-delta-value">
                    {typeof value === 'string' ? value : JSON.stringify(value, null, 2)}
                  </pre>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
      
      {event.event_type === 'compaction' && (
        <div className="detail-section">
          <div className="section-header" onClick={() => toggleSection('compaction_info')}>
            {expandedSections.has('compaction_info') ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
            <span>📦 Compaction Details</span>
          </div>
          {expandedSections.has('compaction_info') && (
            <div className="section-content">
              <div style={{ marginBottom: '12px', padding: '8px', background: 'rgba(147, 51, 234, 0.1)', borderRadius: '4px', border: '1px solid rgba(147, 51, 234, 0.3)' }}>
                <div style={{ fontSize: '11px', color: '#a855f7', marginBottom: '4px', fontWeight: 600 }}>
                  Event Compaction Occurred
                </div>
                <div style={{ fontSize: '12px', color: '#e4e4e7' }}>
                  ADK has summarized older events to manage context window limits.
                </div>
              </div>
              {event.data?.start_timestamp && event.data?.end_timestamp && (
                <div style={{ marginBottom: '8px' }}>
                  <strong>Time Range Compacted:</strong>{' '}
                  {new Date(event.data.start_timestamp * 1000).toLocaleTimeString()} - {new Date(event.data.end_timestamp * 1000).toLocaleTimeString()}
                </div>
              )}
              {event.data?.summary_preview && (
                <div>
                  <strong>Summary Preview:</strong>
                  <pre style={{ 
                    marginTop: '8px', 
                    padding: '12px', 
                    backgroundColor: '#1a1a1a', 
                    borderRadius: '4px',
                    fontSize: '11px',
                    overflow: 'auto',
                    maxHeight: '300px',
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-word',
                    border: '1px solid #27272a'
                  }}>
                    {event.data.summary_preview}
                  </pre>
                </div>
              )}
            </div>
          )}
        </div>
      )}
      
      {/* String Markdown Modal */}
      {stringModalContent && (
        <StringMarkdownModal 
          content={stringModalContent} 
          onClose={() => setStringModalContent(null)} 
        />
      )}
    </div>
  );
}

// String Markdown Modal - for viewing JSON strings as formatted markdown
function StringMarkdownModal({ content, onClose }: { content: string; onClose: () => void }) {
  return (
    <div 
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        backgroundColor: 'rgba(0, 0, 0, 0.8)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 2000,
      }}
      onClick={onClose}
    >
      <div 
        style={{
          backgroundColor: '#1a1a1e',
          borderRadius: '8px',
          border: '1px solid #3f3f46',
          width: '90%',
          maxWidth: '1200px',
          height: '85%',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '12px 16px',
          borderBottom: '1px solid #3f3f46',
          backgroundColor: '#27272a',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Eye size={16} />
            <span style={{ fontWeight: 600 }}>String Content</span>
            <span style={{ color: '#71717a', fontSize: '12px' }}>({content.length} chars)</span>
          </div>
          <button
            onClick={onClose}
            style={{
              background: 'none',
              border: 'none',
              color: '#a1a1aa',
              cursor: 'pointer',
              padding: '4px',
              display: 'flex',
              alignItems: 'center',
            }}
          >
            <X size={18} />
          </button>
        </div>
        
        {/* Content */}
        <div style={{
          flex: 1,
          overflow: 'auto',
          padding: '20px',
        }}>
          <pre style={{
            fontSize: '12px',
            lineHeight: '1.5',
            color: '#e4e4e7',
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
            fontFamily: 'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace',
            margin: 0,
          }}>
            {content}
          </pre>
        </div>
        
        {/* Footer with raw view toggle */}
        <div style={{
          padding: '8px 16px',
          borderTop: '1px solid #3f3f46',
          backgroundColor: '#27272a',
          display: 'flex',
          justifyContent: 'flex-end',
          gap: '8px',
        }}>
          <button
            onClick={() => navigator.clipboard.writeText(content)}
            style={{
              background: '#3f3f46',
              border: 'none',
              borderRadius: '4px',
              padding: '6px 12px',
              color: '#e4e4e7',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '4px',
              fontSize: '12px',
            }}
          >
            <Copy size={12} />
            Copy
          </button>
        </div>
      </div>
    </div>
  );
}

// State version type for versioned modal
interface StateVersion {
  value: any;
  eventIndex: number;
  timestamp: number;
}

// Versioned Markdown modal component - supports navigating through state versions
function VersionedMarkdownModal({ 
  title, 
  versions, 
  initialVersionIndex,
  onClose 
}: { 
  title: string; 
  versions: StateVersion[];
  initialVersionIndex: number;
  onClose: () => void;
}) {
  const [currentIndex, setCurrentIndex] = useState(initialVersionIndex);
  
  // Keyboard navigation
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'ArrowUp' || e.key === 'ArrowLeft') {
        e.preventDefault();
        setCurrentIndex(prev => Math.max(0, prev - 1));
      } else if (e.key === 'ArrowDown' || e.key === 'ArrowRight') {
        e.preventDefault();
        setCurrentIndex(prev => Math.min(versions.length - 1, prev + 1));
      } else if (e.key === 'Escape') {
        onClose();
      }
    };
    
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [versions.length, onClose]);
  
  const [copied, setCopied] = useState(false);
  
  const currentVersion = versions[currentIndex];
  const content = typeof currentVersion.value === 'string' 
    ? currentVersion.value 
    : JSON.stringify(currentVersion.value, null, 2);
  
  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error('Failed to copy:', err);
    }
  };
  
  return createPortal(
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3>{title}</h3>
          {versions.length > 1 && (
            <div className="version-nav">
              <button 
                className="version-btn"
                onClick={() => setCurrentIndex(prev => Math.max(0, prev - 1))}
                disabled={currentIndex === 0}
                title="Previous version (↑)"
              >
                ▲
              </button>
              <span className="version-info">
                v{currentIndex + 1}/{versions.length}
                <span className="version-event"> (event #{currentVersion.eventIndex})</span>
              </span>
              <button 
                className="version-btn"
                onClick={() => setCurrentIndex(prev => Math.min(versions.length - 1, prev + 1))}
                disabled={currentIndex === versions.length - 1}
                title="Next version (↓)"
              >
                ▼
              </button>
            </div>
          )}
          <button 
            className="modal-copy-btn" 
            onClick={handleCopy}
            title="Copy to clipboard"
          >
            {copied ? <CheckCircle size={16} /> : <Copy size={16} />}
            {copied ? 'Copied!' : 'Copy'}
          </button>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>
        <div className="modal-body markdown-content">
          <ReactMarkdown>{content}</ReactMarkdown>
        </div>
        {versions.length > 1 && (
          <div className="modal-footer">
            <span className="version-hint">
              Use ↑↓ arrow keys to navigate versions • 
              Set at {new Date(currentVersion.timestamp * 1000).toLocaleTimeString()}
            </span>
          </div>
        )}
      </div>
      <style>{`
        .modal-overlay {
          position: fixed;
          inset: 0;
          background: rgba(0, 0, 0, 0.7);
          display: flex;
          align-items: center;
          justify-content: center;
          z-index: 10000;
        }
        .modal-content {
          background: var(--bg-primary, #1a1a1f);
          border-radius: var(--radius-lg, 12px);
          width: 90%;
          max-width: 800px;
          max-height: 90vh;
          display: flex;
          flex-direction: column;
          box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5);
        }
        .modal-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 16px 20px;
          border-bottom: 1px solid var(--border-color, #333);
        }
        .modal-header h3 {
          margin: 0;
          font-size: 16px;
          font-weight: 600;
          color: var(--text-primary, #fff);
        }
        .modal-close {
          background: none;
          border: none;
          font-size: 24px;
          color: var(--text-secondary, #888);
          cursor: pointer;
          padding: 0;
          width: 32px;
          height: 32px;
          display: flex;
          align-items: center;
          justify-content: center;
          border-radius: var(--radius-sm, 4px);
        }
        .modal-close:hover {
          background: var(--bg-hover, #333);
          color: var(--text-primary, #fff);
        }
        .modal-body {
          flex: 1;
          overflow-y: auto;
          padding: 20px;
        }
        .markdown-content {
          line-height: 1.6;
          font-family: 'Outfit', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
          font-size: 14px;
          color: var(--text-primary, #fff);
        }
        .markdown-content h1,
        .markdown-content h2,
        .markdown-content h3,
        .markdown-content h4 {
          margin-top: 1em;
          margin-bottom: 0.5em;
          font-weight: 600;
        }
        .markdown-content h1 { font-size: 1.5em; }
        .markdown-content h2 { font-size: 1.3em; }
        .markdown-content h3 { font-size: 1.1em; }
        .markdown-content p {
          margin: 0.5em 0;
        }
        .markdown-content code {
          background: var(--bg-tertiary, #2a2a2f);
          padding: 2px 6px;
          border-radius: var(--radius-sm, 4px);
          font-family: var(--font-mono, monospace);
          font-size: 0.9em;
        }
        .markdown-content pre {
          background: var(--bg-tertiary, #2a2a2f);
          padding: 12px;
          border-radius: var(--radius-md, 8px);
          overflow-x: auto;
          margin: 1em 0;
        }
        .markdown-content pre code {
          background: none;
          padding: 0;
        }
        .markdown-content ul,
        .markdown-content ol {
          margin: 0.5em 0;
          padding-left: 1.5em;
        }
        .markdown-content blockquote {
          border-left: 3px solid var(--accent-primary, #3b82f6);
          padding-left: 1em;
          margin: 1em 0;
          color: var(--text-secondary, #888);
        }
        .markdown-content strong {
          font-weight: 700;
          color: var(--text-primary, #fff);
        }
        .markdown-content em {
          font-style: italic;
          color: var(--text-secondary, #888);
        }
        .markdown-content a {
          color: var(--accent-primary, #3b82f6);
          text-decoration: underline;
        }
        .markdown-content li {
          margin: 0.25em 0;
        }
        .version-nav {
          display: flex;
          align-items: center;
          gap: 8px;
          margin-right: auto;
          margin-left: 16px;
        }
        .version-btn {
          background: var(--bg-tertiary, #2a2a2f);
          border: 1px solid var(--border-color, #333);
          color: var(--text-secondary, #888);
          cursor: pointer;
          padding: 4px 8px;
          border-radius: var(--radius-sm, 4px);
          font-size: 12px;
        }
        .version-btn:hover:not(:disabled) {
          background: var(--bg-hover, #333);
          color: var(--text-primary, #fff);
        }
        .version-btn:disabled {
          opacity: 0.4;
          cursor: not-allowed;
        }
        .version-info {
          font-size: 12px;
          color: var(--text-secondary, #888);
          font-weight: 500;
        }
        .version-event {
          color: var(--text-muted, #666);
          font-weight: normal;
        }
        .modal-footer {
          padding: 8px 20px;
          border-top: 1px solid var(--border-color, #333);
          background: var(--bg-secondary, #222);
        }
        .version-hint {
          font-size: 11px;
          color: var(--text-muted, #666);
        }
        .modal-copy-btn {
          display: flex;
          align-items: center;
          gap: 6px;
          background: var(--bg-tertiary, #2a2a2f);
          border: 1px solid var(--border-color, #333);
          color: var(--text-secondary, #888);
          cursor: pointer;
          padding: 6px 12px;
          border-radius: var(--radius-sm, 4px);
          font-size: 12px;
          margin-left: auto;
        }
        .modal-copy-btn:hover {
          background: var(--bg-hover, #333);
          color: var(--text-primary, #fff);
        }
      `}</style>
    </div>,
    document.body
  );
}

// Markdown modal component (simple version for non-versioned content)
function MarkdownModal({ content, title, onClose }: { content: string; title: string; onClose: () => void }) {
  const [copied, setCopied] = useState(false);
  
  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error('Failed to copy:', err);
    }
  };
  
  return createPortal(
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3>{title}</h3>
          <button 
            className="modal-copy-btn" 
            onClick={handleCopy}
            title="Copy to clipboard"
          >
            {copied ? <CheckCircle size={16} /> : <Copy size={16} />}
            {copied ? 'Copied!' : 'Copy'}
          </button>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>
        <div className="modal-body markdown-content">
          <ReactMarkdown>{content}</ReactMarkdown>
        </div>
      </div>
      <style>{`
        .modal-overlay {
          position: fixed;
          inset: 0;
          background: rgba(0, 0, 0, 0.7);
          display: flex;
          align-items: center;
          justify-content: center;
          z-index: 10000;
        }
        .modal-content {
          background: var(--bg-primary, #1a1a1f);
          border-radius: var(--radius-lg, 12px);
          width: 90%;
          max-width: 800px;
          max-height: 90vh;
          display: flex;
          flex-direction: column;
          box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5);
        }
        .modal-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 16px 20px;
          border-bottom: 1px solid var(--border-color, #333);
        }
        .modal-header h3 {
          margin: 0;
          font-size: 16px;
          font-weight: 600;
          color: var(--text-primary, #fff);
        }
        .modal-close {
          background: none;
          border: none;
          font-size: 24px;
          color: var(--text-secondary, #888);
          cursor: pointer;
          padding: 0;
          width: 32px;
          height: 32px;
          display: flex;
          align-items: center;
          justify-content: center;
          border-radius: var(--radius-sm, 4px);
        }
        .modal-close:hover {
          background: var(--bg-hover, #333);
          color: var(--text-primary, #fff);
        }
        .modal-copy-btn {
          display: flex;
          align-items: center;
          gap: 6px;
          background: var(--bg-tertiary, #2a2a2f);
          border: 1px solid var(--border-color, #333);
          color: var(--text-secondary, #888);
          cursor: pointer;
          padding: 6px 12px;
          border-radius: var(--radius-sm, 4px);
          font-size: 12px;
          margin-left: auto;
        }
        .modal-copy-btn:hover {
          background: var(--bg-hover, #333);
          color: var(--text-primary, #fff);
        }
        .modal-body {
          flex: 1;
          overflow-y: auto;
          padding: 20px;
        }
        .markdown-content {
          line-height: 1.6;
          font-family: 'Outfit', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
          font-size: 14px;
          color: var(--text-primary, #fff);
        }
        .markdown-content h1,
        .markdown-content h2,
        .markdown-content h3,
        .markdown-content h4 {
          margin-top: 1em;
          margin-bottom: 0.5em;
          font-weight: 600;
        }
        .markdown-content h1 { font-size: 1.5em; }
        .markdown-content h2 { font-size: 1.3em; }
        .markdown-content h3 { font-size: 1.1em; }
        .markdown-content p {
          margin: 0.5em 0;
        }
        .markdown-content code {
          background: var(--bg-tertiary, #2a2a2f);
          padding: 2px 6px;
          border-radius: var(--radius-sm, 4px);
          font-family: var(--font-mono, monospace);
          font-size: 0.9em;
        }
        .markdown-content pre {
          background: var(--bg-tertiary, #2a2a2f);
          padding: 12px;
          border-radius: var(--radius-md, 8px);
          overflow-x: auto;
          margin: 1em 0;
        }
        .markdown-content pre code {
          background: none;
          padding: 0;
        }
        .markdown-content ul,
        .markdown-content ol {
          margin: 0.5em 0;
          padding-left: 1.5em;
        }
        .markdown-content blockquote {
          border-left: 3px solid var(--accent-primary, #3b82f6);
          padding-left: 1em;
          margin: 1em 0;
          color: var(--text-secondary, #888);
        }
        .markdown-content strong {
          font-weight: 700;
          color: var(--text-primary, #fff);
        }
        .markdown-content em {
          font-style: italic;
          color: var(--text-secondary, #888);
        }
        .markdown-content a {
          color: var(--accent-primary, #3b82f6);
          text-decoration: underline;
        }
        .markdown-content a:hover {
          opacity: 0.8;
        }
        .markdown-content li {
          margin: 0.25em 0;
        }
        .markdown-content hr {
          border: none;
          border-top: 1px solid var(--border-color, #333);
          margin: 1em 0;
        }
        .markdown-content table {
          border-collapse: collapse;
          width: 100%;
          margin: 1em 0;
        }
        .markdown-content th,
        .markdown-content td {
          border: 1px solid var(--border-color, #333);
          padding: 8px 12px;
          text-align: left;
        }
        .markdown-content th {
          background: var(--bg-tertiary, #2a2a2f);
          font-weight: 600;
        }
        .markdown-content img {
          max-width: 100%;
          height: auto;
        }
      `}</style>
    </div>,
    document.body
  );
}

// State snapshot component - shows state after selected event
function StateSnapshot({ events, selectedEventIndex, project }: { 
  events: RunEvent[]; 
  selectedEventIndex: number | null;
  project: Project | null;
}) {
  const [modalState, setModalState] = useState<{ 
    key: string; 
    versions: StateVersion[]; 
    initialVersionIndex: number;
  } | null>(null);
  
  // Build version history for all state keys
  const { state, stateVersions } = useMemo(() => {
    const snapshot: Record<string, { value: any; timestamp: number | null; defined: boolean; description?: string; type?: string }> = {};
    const versions: Record<string, StateVersion[]> = {};
    
    // First, add all state keys defined in the App config
    if (project?.app?.state_keys) {
      project.app.state_keys.forEach(key => {
        snapshot[key.name] = { 
          value: undefined, 
          timestamp: null, 
          defined: true,
          description: key.description,
          type: key.type
        };
        versions[key.name] = [];
      });
    }
    
    // Also add output_keys from agents
    if (project?.agents) {
      project.agents.forEach(agent => {
        if (agent.type === 'LlmAgent' && (agent as any).output_key) {
          const outputKey = (agent as any).output_key;
          if (!snapshot[outputKey]) {
            snapshot[outputKey] = {
              value: undefined,
              timestamp: null,
              defined: true,
              description: `Output from ${agent.name}`,
              type: 'string'
            };
            versions[outputKey] = [];
          }
        }
      });
    }
    
    // Collect ALL versions from all events (not just up to selected)
    events
      .filter(e => e.event_type === 'state_change')
      .forEach((e, _i) => {
        if (e.data?.state_delta) {
          // Find the event index in the original events array
          const eventIndex = events.indexOf(e);
          Object.entries(e.data.state_delta).forEach(([key, value]) => {
            if (!versions[key]) versions[key] = [];
            versions[key].push({
              value,
              eventIndex,
              timestamp: e.timestamp,
            });
          });
        }
      });
    
    // If an event is selected, show state up to and including that event
    // Otherwise show state at end of all events
    const relevantEvents = selectedEventIndex !== null
      ? events.slice(0, selectedEventIndex + 1)
      : events;
    
    relevantEvents
      .filter(e => e.event_type === 'state_change')
      .forEach(e => {
        if (e.data?.state_delta) {
          Object.entries(e.data.state_delta).forEach(([key, value]) => {
            snapshot[key] = { 
              ...snapshot[key],
              value, 
              timestamp: e.timestamp,
              defined: snapshot[key]?.defined ?? false
            };
          });
        }
      });
    
    return { state: snapshot, stateVersions: versions };
  }, [events, selectedEventIndex, project]);
  
  // Calculate which version index to show initially based on selectedEventIndex
  const getInitialVersionIndex = (key: string): number => {
    const versions = stateVersions[key] || [];
    if (versions.length === 0) return 0;
    
    if (selectedEventIndex === null) {
      // Show the last version
      return versions.length - 1;
    }
    
    // Find the version at or just before the selected event
    let bestIndex = 0;
    for (let i = 0; i < versions.length; i++) {
      if (versions[i].eventIndex <= selectedEventIndex) {
        bestIndex = i;
      } else {
        break;
      }
    }
    return bestIndex;
  };
  
  const entries = Object.entries(state);
  
  return (
    <>
      {modalState && (
        <VersionedMarkdownModal
          title={modalState.key}
          versions={modalState.versions}
          initialVersionIndex={modalState.initialVersionIndex}
          onClose={() => setModalState(null)}
        />
      )}
    <div className="state-snapshot">
      <style>{`
        .state-entry.unset {
          opacity: 0.6;
        }
        .state-entry.unset .state-value {
          font-style: italic;
          color: #888;
        }
        .state-type {
          font-size: 10px;
          color: #888;
          margin-left: 8px;
        }
        .state-version-count {
          font-size: 10px;
          color: #666;
          margin-left: 4px;
        }
        .state-desc {
          font-size: 11px;
          color: #666;
          margin-top: 2px;
        }
        .state-value-row {
          display: flex;
          align-items: flex-start;
          gap: 8px;
        }
        .state-value-row .state-value {
          flex: 1;
        }
        .state-copy-btn {
          flex-shrink: 0;
          background: var(--bg-tertiary);
          border: 1px solid var(--border-color);
          color: var(--text-muted);
          cursor: pointer;
          padding: 4px 8px;
          border-radius: var(--radius-sm);
          font-size: 10px;
          display: flex;
          align-items: center;
          gap: 4px;
          opacity: 0.6;
          transition: opacity 0.15s;
        }
        .state-entry:hover .state-copy-btn {
          opacity: 1;
        }
        .state-copy-btn:hover {
          background: var(--bg-hover);
          color: var(--text-primary);
        }
      `}</style>
      <div className="state-header">
        {selectedEventIndex !== null 
          ? `State after event #${selectedEventIndex}` 
          : events.length > 0 ? 'State at end of run' : 'Defined State Keys'}
      </div>
      {entries.length === 0 ? (
        <div className="state-empty">No state keys defined</div>
      ) : (
        entries.map(([key, { value, timestamp, defined, description, type }]) => {
          const versions = stateVersions[key] || [];
          const displayValue = value === undefined 
            ? '(not set)' 
            : typeof value === 'string' 
              ? value 
              : JSON.stringify(value, null, 2);
          
          return (
          <div key={key} className={`state-entry ${value === undefined ? 'unset' : ''}`}>
            <div className="state-key">
              {key}
              {type && <span className="state-type">({type})</span>}
                {versions.length > 1 && (
                  <span className="state-version-count" title="Number of versions">
                    [{versions.length} versions]
                  </span>
                )}
            </div>
              <div className="state-value-row">
            <div 
              className="state-value"
              onClick={() => {
                    if (value !== undefined && versions.length > 0) {
                      setModalState({
                        key,
                        versions,
                        initialVersionIndex: getInitialVersionIndex(key),
                      });
                }
              }}
              style={{ cursor: value !== undefined ? 'pointer' : 'default' }}
                  title={value !== undefined 
                    ? versions.length > 1 
                      ? `Click to view (${versions.length} versions, use ↑↓ to navigate)` 
                      : 'Click to view in markdown viewer' 
                    : undefined}
                >
                  {displayValue}
                </div>
                {value !== undefined && (
                  <StateCopyButton value={displayValue} />
                )}
            </div>
            {description && <div className="state-desc">{description}</div>}
            {timestamp && (
              <div className="state-time">{new Date(timestamp * 1000).toLocaleTimeString()}</div>
            )}
          </div>
          );
        })
      )}
    </div>
    </>
  );
}

// Small copy button for state values
function StateCopyButton({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);
  
  const handleCopy = async (e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch (err) {
      console.error('Failed to copy:', err);
    }
  };
  
  return (
    <button 
      className="state-copy-btn" 
      onClick={handleCopy}
      title="Copy to clipboard"
    >
      {copied ? <CheckCircle size={12} /> : <Copy size={12} />}
    </button>
  );
}

// Artifacts Panel component - shows artifacts stored in the session
function ArtifactsPanel({ project, sessionId }: { 
  project: Project | null;
  sessionId: string | null;
}) {
  const [artifacts, setArtifacts] = useState<ArtifactInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedArtifact, setSelectedArtifact] = useState<string | null>(null);
  const [imageModalSrc, setImageModalSrc] = useState<string | null>(null);
  
  // Fetch artifacts when session changes
  useEffect(() => {
    if (!project?.id || !sessionId) {
      setArtifacts([]);
      return;
    }
    
    const fetchArtifacts = async () => {
      setLoading(true);
      setError(null);
      try {
        const artifactList = await listArtifacts(project.id, sessionId);
        setArtifacts(artifactList);
      } catch (e: any) {
        setError(e.message || 'Failed to load artifacts');
        setArtifacts([]);
      } finally {
        setLoading(false);
      }
    };
    
    fetchArtifacts();
  }, [project?.id, sessionId]);
  
  const formatSize = (bytes: number | null) => {
    if (bytes === null) return '';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };
  
  const handleDownload = (filename: string) => {
    if (!project?.id || !sessionId) return;
    const url = getArtifactUrl(project.id, sessionId, filename);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };
  
  const handlePreview = (artifact: ArtifactInfo) => {
    if (!project?.id || !sessionId) return;
    if (artifact.is_image) {
      const url = getArtifactUrl(project.id, sessionId, artifact.filename);
      setImageModalSrc(url);
    }
  };
  
  return (
    <>
      {/* Image Modal */}
      {imageModalSrc && (
        <div 
          className="artifact-image-modal"
          onClick={() => setImageModalSrc(null)}
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: 'rgba(0, 0, 0, 0.85)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 10000,
            cursor: 'pointer',
          }}
        >
          <div 
            onClick={(e) => e.stopPropagation()}
            style={{
              maxWidth: '90vw',
              maxHeight: '90vh',
              position: 'relative',
            }}
          >
            <button
              onClick={() => setImageModalSrc(null)}
              style={{
                position: 'absolute',
                top: -40,
                right: 0,
                background: 'transparent',
                border: 'none',
                color: '#fff',
                cursor: 'pointer',
                padding: 8,
              }}
            >
              <X size={24} />
            </button>
            <img 
              src={imageModalSrc} 
              alt="Artifact preview"
              style={{
                maxWidth: '90vw',
                maxHeight: '85vh',
                objectFit: 'contain',
                borderRadius: 8,
              }}
            />
          </div>
        </div>
      )}
      
      <div className="artifacts-panel">
        <style>{`
          .artifacts-panel {
            padding: 8px;
          }
          .artifacts-header {
            font-size: 11px;
            font-weight: 600;
            color: #a1a1aa;
            padding: 8px;
            background: #18181b;
            border-radius: 4px;
            margin-bottom: 8px;
          }
          .artifacts-empty {
            padding: 16px;
            text-align: center;
            color: #71717a;
            font-size: 12px;
          }
          .artifacts-loading {
            padding: 16px;
            text-align: center;
            color: #71717a;
            font-size: 12px;
          }
          .artifacts-error {
            padding: 12px;
            background: rgba(239, 68, 68, 0.1);
            border: 1px solid rgba(239, 68, 68, 0.3);
            border-radius: 4px;
            color: #fca5a5;
            font-size: 11px;
          }
          .artifact-item {
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 8px 10px;
            background: #18181b;
            border-radius: 4px;
            margin-bottom: 4px;
            cursor: pointer;
            transition: background 0.15s;
          }
          .artifact-item:hover {
            background: #27272a;
          }
          .artifact-icon {
            flex-shrink: 0;
            color: #71717a;
          }
          .artifact-icon.image {
            color: #60a5fa;
          }
          .artifact-info {
            flex: 1;
            min-width: 0;
          }
          .artifact-name {
            font-size: 12px;
            color: #e4e4e7;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
          }
          .artifact-meta {
            font-size: 10px;
            color: #71717a;
            margin-top: 2px;
          }
          .artifact-actions {
            display: flex;
            gap: 4px;
            flex-shrink: 0;
          }
          .artifact-btn {
            background: transparent;
            border: none;
            color: #71717a;
            cursor: pointer;
            padding: 4px;
            border-radius: 4px;
            display: flex;
            align-items: center;
            justify-content: center;
          }
          .artifact-btn:hover {
            background: #3f3f46;
            color: #e4e4e7;
          }
          .artifact-preview {
            width: 100%;
            margin-top: 8px;
            border-radius: 4px;
            overflow: hidden;
            background: #09090b;
          }
          .artifact-preview img {
            width: 100%;
            height: auto;
            display: block;
          }
        `}</style>
        
        <div className="artifacts-header">
          {sessionId ? 'Session Artifacts' : 'No Session Selected'}
        </div>
        
        {loading ? (
          <div className="artifacts-loading">
            <RefreshCw size={16} className="spin" style={{ marginBottom: 8 }} />
            <div>Loading artifacts...</div>
          </div>
        ) : error ? (
          <div className="artifacts-error">{error}</div>
        ) : !sessionId ? (
          <div className="artifacts-empty">
            <FileBox size={24} style={{ marginBottom: 8, opacity: 0.5 }} />
            <div>Start a session to see artifacts</div>
          </div>
        ) : artifacts.length === 0 ? (
          <div className="artifacts-empty">
            <FileBox size={24} style={{ marginBottom: 8, opacity: 0.5 }} />
            <div>No artifacts in this session</div>
            <div style={{ fontSize: 10, marginTop: 4, color: '#52525b' }}>
              Use tool_context.save_artifact() to save artifacts
            </div>
          </div>
        ) : (
          artifacts.map((artifact) => (
            <div key={artifact.filename} className="artifact-item">
              <div className={`artifact-icon ${artifact.is_image ? 'image' : ''}`}>
                {artifact.is_image ? <Image size={16} /> : <File size={16} />}
              </div>
              <div className="artifact-info">
                <div className="artifact-name" title={artifact.filename}>
                  {artifact.filename}
                </div>
                <div className="artifact-meta">
                  {artifact.mime_type || 'unknown type'}
                  {artifact.size !== null && ` • ${formatSize(artifact.size)}`}
                </div>
              </div>
              <div className="artifact-actions">
                {artifact.is_image && (
                  <button 
                    className="artifact-btn" 
                    title="Preview"
                    onClick={() => handlePreview(artifact)}
                  >
                    <Eye size={14} />
                  </button>
                )}
                <button 
                  className="artifact-btn" 
                  title="Download"
                  onClick={() => handleDownload(artifact.filename)}
                >
                  <Download size={14} />
                </button>
              </div>
              
              {/* Inline preview for images when selected */}
              {artifact.is_image && selectedArtifact === artifact.filename && project?.id && sessionId && (
                <div className="artifact-preview">
                  <img 
                    src={getArtifactUrl(project.id, sessionId, artifact.filename)} 
                    alt={artifact.filename}
                  />
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </>
  );
}

// Import WatchExpression type from store
import type { WatchExpression } from '../hooks/useStore';

// Extract clean result text from MCP response
function extractResultText(result: any): { text: string; isError: boolean } {
  if (!result) return { text: '', isError: false };
  
  // Handle API response wrapper
  if (result.success === false) {
    return { text: result.error || 'Unknown error', isError: true };
  }
  
  let data = result.result || result;
  
  // If it's a string that looks like a Python dict, try to parse it
  if (typeof data === 'string') {
    // Try to convert Python-style dict to JSON
    try {
      const jsonStr = data
        .replace(/'/g, '"')
        .replace(/True/g, 'true')
        .replace(/False/g, 'false')
        .replace(/None/g, 'null');
      data = JSON.parse(jsonStr);
    } catch {
      // Not parseable, return as-is
      return { text: data, isError: false };
    }
  }
  
  // Handle MCP content format
  if (data.content && Array.isArray(data.content)) {
    const texts = data.content
      .filter((p: any) => p.type === 'text')
      .map((p: any) => p.text);
    return { 
      text: texts.join('\n'), 
      isError: data.isError === true 
    };
  }
  
  // Fallback
  return { 
    text: typeof data === 'string' ? data : JSON.stringify(data, null, 2),
    isError: false 
  };
}

// Apply transform to result - supports dot notation and JavaScript expressions
// Dot notation: e.g., ".items[0].name", ".content[].text" (simple path access)
// JavaScript: starts with "js:" (e.g., "js:value.split('\n')[0]")
function applyTransform(text: string, transform: string | undefined): string {
  if (!transform || !transform.trim()) return text;
  
  const trimmed = transform.trim();
  
  // Try to parse the text as JSON first
  let data: any = text;
  try {
    data = JSON.parse(text);
  } catch {
    // Keep as string if not valid JSON
  }
  
  // JavaScript transform (explicit prefix)
  if (trimmed.startsWith('js:')) {
    const jsExpr = trimmed.slice(3).trim();
    try {
      // eslint-disable-next-line no-new-func
      const fn = new Function('value', 'data', `return ${jsExpr}`);
      const result = fn(text, data);
      return typeof result === 'string' ? result : JSON.stringify(result, null, 2);
    } catch (e) {
      return `[JS error: ${e}]`;
    }
  }
  
  // Simple dot notation property access (e.g., ".items[0].name")
  if (trimmed.startsWith('.')) {
        try {
          const path = trimmed.slice(1).split('.').filter(Boolean);
          let result: any = data;
          for (const key of path) {
        // Handle array index like [0] or items[0]
            const match = key.match(/^(\w+)?\[(\d+)\]$/);
            if (match) {
              if (match[1]) result = result[match[1]];
              result = result[parseInt(match[2])];
            } else {
              result = result[key];
            }
          }
      if (result === null || result === undefined) {
        return '[No match]';
      }
          return typeof result === 'string' ? result : JSON.stringify(result, null, 2);
    } catch (e: any) {
      return `[Path error: ${e.message}]`;
        }
      }
  
  // Try as JavaScript expression
      try {
        // eslint-disable-next-line no-new-func
        const fn = new Function('value', 'data', `return ${trimmed}`);
        const result = fn(text, data);
        return typeof result === 'string' ? result : JSON.stringify(result, null, 2);
      } catch (e: any) {
    return `[Transform error: ${e.message}]`;
  }
}

// Tool Watch Panel component
// Note: Auto-refresh is now handled at the RunPanel level so watches run even when this tab isn't visible
function ToolWatchPanel({ project, selectedEventIndex, sandboxMode }: { project: Project; selectedEventIndex: number | null; sandboxMode: boolean }) {
  // Use global store for watches so they persist across tab switches
  const { watches, updateWatch, addWatch: storeAddWatch, removeWatch: storeRemoveWatch, runEvents } = useStore();
  
  const [showDialog, setShowDialog] = useState(false);
  const [editingWatchId, setEditingWatchId] = useState<string | null>(null);  // null = adding new
  const [availableTools, setAvailableTools] = useState<Record<string, any[]>>({});
  const [loadingServers, setLoadingServers] = useState<Set<string>>(new Set());
  
  // Form state (used for both add and edit)
  const [formServerName, setFormServerName] = useState('');
  const [formToolName, setFormToolName] = useState('');
  const [formArgs, setFormArgs] = useState<Record<string, any>>({});
  const [formTransform, setFormTransform] = useState('');
  const [knownServers, setKnownServers] = useState<MCPServerConfig[]>([]);
  
  // Test run state for dialog
  const [testResult, setTestResult] = useState<string | null>(null);
  const [testError, setTestError] = useState<string | null>(null);
  const [isTestRunning, setIsTestRunning] = useState(false);
  
  // Fetch known MCP servers on mount
  useEffect(() => {
    getMcpServers().then(setKnownServers).catch(console.error);
  }, []);
  
  // Combine project servers with known servers
  const mcpServers = useMemo(() => {
    const projectServers = project.mcp_servers || [];
    const projectServerNames = new Set(projectServers.map(s => s.name));
    // Add known servers that aren't already in project
    const additionalServers = knownServers.filter(s => !projectServerNames.has(s.name));
    return [...projectServers, ...additionalServers];
  }, [project.mcp_servers, knownServers]);
  
  // Load tools for a server by name
  const loadServerTools = useCallback(async (serverName: string) => {
    if (availableTools[serverName] || loadingServers.has(serverName)) return;
    
    setLoadingServers(prev => new Set([...prev, serverName]));
    try {
      const result = await fetchJSON<{ success: boolean; tools: any[] }>(
        `/projects/${project.id}/mcp-servers/${encodeURIComponent(serverName)}/test-connection`,
        { method: 'POST' }
      );
      if (result.success) {
        setAvailableTools(prev => ({ ...prev, [serverName]: result.tools }));
      }
    } catch (err) {
      console.error('Failed to load tools:', err);
    } finally {
      setLoadingServers(prev => {
        const next = new Set(prev);
        next.delete(serverName);
        return next;
      });
    }
  }, [project.id, availableTools, loadingServers]);
  
  // Update args when tool changes (only when adding new, not editing)
  useEffect(() => {
    if (editingWatchId) return;  // Don't auto-update args when editing
    if (!formServerName || !formToolName) {
      setFormArgs({});
      return;
    }
    const tools = availableTools[formServerName] || [];
    const tool = tools.find(t => t.name === formToolName);
    if (!tool?.parameters?.properties) {
      setFormArgs({});
      return;
    }
    const placeholders: Record<string, any> = {};
    Object.entries(tool.parameters.properties).forEach(([key, schema]: [string, any]) => {
      if (schema.type === 'string') placeholders[key] = schema.default || '';
      else if (schema.type === 'number' || schema.type === 'integer') placeholders[key] = schema.default || 0;
      else if (schema.type === 'boolean') placeholders[key] = schema.default || false;
      else placeholders[key] = schema.default || null;
    });
    setFormArgs(placeholders);
  }, [formServerName, formToolName, availableTools, editingWatchId]);
  
  // Open dialog for adding new watch
  const openAddDialog = () => {
    setEditingWatchId(null);
    setFormServerName('');
    setFormToolName('');
    setFormArgs({});
    setFormTransform('');
    setTestResult(null);
    setTestError(null);
    setShowDialog(true);
  };
  
  // Open dialog for editing existing watch
  const openEditDialog = (watch: WatchExpression) => {
    setEditingWatchId(watch.id);
    setFormServerName(watch.serverName);
    setFormToolName(watch.toolName);
    setFormArgs({ ...watch.args });
    setFormTransform(watch.transform || '');
    // Pre-populate test result with existing result if available
    if (watch.result) {
      const { text } = extractResultText(watch.result);
      setTestResult(text);
      setTestError(null);
    } else {
      setTestResult(null);
      setTestError(null);
    }
    // Load tools for the server if not already loaded
    if (!availableTools[watch.serverName]) {
      loadServerTools(watch.serverName);
    }
    setShowDialog(true);
  };
  
  // Test run tool in dialog
  const testRunTool = async () => {
    if (!formServerName || !formToolName) return;
    
    setIsTestRunning(true);
    setTestError(null);
    
    // Get the app_id for sandbox mode
    const appId = project.app?.id || `app_${project.id}`;
    
    try {
      const result = await fetchJSON(`/projects/${project.id}/run-mcp-tool`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          server_name: formServerName,
          tool_name: formToolName,
          arguments: formArgs,
          sandbox_mode: sandboxMode,  // Use sandbox mode if enabled
          app_id: sandboxMode ? appId : undefined,
        }),
      });
      
      const { text, isError } = extractResultText(result);
      if (isError) {
        setTestError(text);
        setTestResult(null);
      } else {
        setTestResult(text);
        setTestError(null);
      }
    } catch (err) {
      setTestError(String(err));
      setTestResult(null);
    } finally {
      setIsTestRunning(false);
    }
  };
  
  // Live preview of transform applied to test result
  const transformPreview = useMemo(() => {
    if (!testResult) return null;
    if (!formTransform || !formTransform.trim()) return testResult;
    return applyTransform(testResult, formTransform);
  }, [testResult, formTransform]);
  
  // Save (add or update) watch
  const saveWatch = () => {
    if (!formServerName || !formToolName) return;
    
    if (editingWatchId) {
      // Update existing watch
      updateWatch(editingWatchId, {
        serverName: formServerName,
        toolName: formToolName,
        args: { ...formArgs },
        transform: formTransform || undefined,
      });
      // Re-run the watch with new config
      const updatedWatch = watches.find(w => w.id === editingWatchId);
      if (updatedWatch) {
        runWatch({ ...updatedWatch, serverName: formServerName, toolName: formToolName, args: formArgs, transform: formTransform || undefined, history: updatedWatch.history || [] });
      }
    } else {
      // Add new watch
      const watch: WatchExpression = {
        id: `watch-${Date.now()}`,
        serverName: formServerName,
        toolName: formToolName,
        args: { ...formArgs },
        transform: formTransform || undefined,
        history: [],
      };
      storeAddWatch(watch);
      // Run immediately
      runWatch(watch);
    }
    
    setShowDialog(false);
  };
  
  const removeWatch = (id: string) => {
    storeRemoveWatch(id);
  };
  
  const runWatch = useCallback(async (watch: WatchExpression, eventIndex?: number) => {
    updateWatch(watch.id, { isLoading: true, error: undefined });
    
    const currentEventIndex = eventIndex ?? runEvents.length - 1;
    const timestamp = Date.now();
    
    // Get the app_id for sandbox mode
    const appId = project.app?.id || `app_${project.id}`;
    
    try {
      const result = await fetchJSON(`/projects/${project.id}/run-mcp-tool`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          server_name: watch.serverName,
          tool_name: watch.toolName,
          arguments: watch.args,
          sandbox_mode: sandboxMode,  // Execute in Docker sandbox if enabled
          app_id: sandboxMode ? appId : undefined,
        }),
      });
      
      // Add to history
      const newSnapshot = { eventIndex: currentEventIndex, timestamp, result };
      const history = [...(watch.history || []), newSnapshot];
      
      updateWatch(watch.id, { result, isLoading: false, lastRun: timestamp, history });
    } catch (err) {
      // Add error to history
      const newSnapshot = { eventIndex: currentEventIndex, timestamp, error: String(err) };
      const history = [...(watch.history || []), newSnapshot];
      
      updateWatch(watch.id, { error: String(err), isLoading: false, lastRun: timestamp, history });
    }
  }, [project.id, project.app?.id, updateWatch, runEvents.length, sandboxMode]);
  
  
  const runAllWatches = () => {
    watches.forEach(watch => runWatch(watch));
  };
  
  const selectedToolSchema = useMemo(() => {
    if (!formServerName || !formToolName) return null;
    const tools = availableTools[formServerName] || [];
    return tools.find(t => t.name === formToolName);
  }, [formServerName, formToolName, availableTools]);
  
  return (
    <div className="tool-watch-panel">
      <div className="watch-header">
        <Eye size={14} />
        <span>Tool Watch</span>
        <span className="watch-auto-badge" title="Watches auto-refresh on every event">⚡ Auto</span>
        <div className="watch-actions">
          <button className="watch-btn" onClick={runAllWatches} title="Refresh all">
            <RefreshCw size={12} />
          </button>
          <button className="watch-btn" onClick={openAddDialog} title="Add watch">
            <Plus size={12} />
          </button>
        </div>
      </div>
      
      {watches.length === 0 ? (
        <div className="watch-empty">
          <Eye size={20} style={{ opacity: 0.3 }} />
          <span>No watch expressions</span>
          <button className="add-watch-btn" onClick={openAddDialog}>
            <Plus size={12} /> Add Tool Watch
          </button>
        </div>
      ) : (
        <div className="watch-list">
          {watches.map(watch => {
            // Find the result at or before the selected event index
            let resultToShow = watch.result;
            let errorToShow = watch.error;
            
            if (selectedEventIndex !== null && watch.history && watch.history.length > 0) {
              // Find the most recent snapshot at or before selectedEventIndex
              const relevantSnapshots = watch.history.filter(s => s.eventIndex <= selectedEventIndex);
              if (relevantSnapshots.length > 0) {
                const latestSnapshot = relevantSnapshots[relevantSnapshots.length - 1];
                resultToShow = latestSnapshot.result;
                errorToShow = latestSnapshot.error;
              } else {
                // No snapshots at or before this event
                resultToShow = undefined;
                errorToShow = undefined;
              }
            }
            
            const { text, isError } = resultToShow 
              ? extractResultText(resultToShow)
              : { text: '', isError: false };
            const displayText = resultToShow ? applyTransform(text, watch.transform) : '';
            const hasError = errorToShow || isError;
            
            return (
              <div key={watch.id} className={`watch-item ${hasError ? 'error' : ''}`}>
                <div className="watch-item-header">
                  <span className="watch-expr">
                    <span className="watch-server">{watch.serverName}</span>
                    <span className="watch-tool">{watch.toolName}</span>
                    {Object.keys(watch.args).length > 0 && (
                      <span className="watch-args">
                        ({Object.entries(watch.args).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(', ')})
                      </span>
                    )}
                    {selectedEventIndex !== null && (
                      <span className="watch-time-indicator">@{selectedEventIndex}</span>
                    )}
                  </span>
                  <div className="watch-item-actions">
                    <button onClick={() => openEditDialog(watch)} title="Edit watch">
                      <Wrench size={10} />
                    </button>
                    <button onClick={() => runWatch(watch)} title="Refresh">
                      {watch.isLoading ? <RefreshCw size={10} className="spin" /> : <RefreshCw size={10} />}
                    </button>
                    <button onClick={() => removeWatch(watch.id)} title="Remove">
                      <Trash2 size={10} />
                    </button>
                  </div>
                </div>
                <div className="watch-result">
                  {watch.isLoading ? (
                    <span className="loading">Loading...</span>
                  ) : errorToShow ? (
                    <span className="error">{errorToShow}</span>
                  ) : resultToShow ? (
                    <pre className={isError ? 'error-text' : ''}>{displayText}</pre>
                  ) : (
                    <span className="no-result">{selectedEventIndex !== null ? 'No data at this event' : 'Not yet run'}</span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
      
      {/* Add/Edit Watch Dialog */}
      {showDialog && (
        <div className="watch-dialog-overlay" onClick={() => setShowDialog(false)}>
          <div className="watch-dialog" onClick={e => e.stopPropagation()}>
            <div className="dialog-header">
              <span>{editingWatchId ? 'Edit Watch' : 'Add Tool Watch'}</span>
              <button onClick={() => setShowDialog(false)}><X size={14} /></button>
            </div>
            
            <div className="dialog-body">
              <div className="form-row">
                <label>MCP Server</label>
                <select 
                  value={formServerName} 
                  onChange={e => {
                    setFormServerName(e.target.value);
                    if (!editingWatchId) setFormToolName('');  // Only clear tool when adding new
                    if (e.target.value) loadServerTools(e.target.value);
                  }}
                >
                  <option value="">Select server...</option>
                  {mcpServers.map(server => (
                    <option key={server.name} value={server.name}>{server.name}</option>
                  ))}
                </select>
              </div>
              
              <div className="form-row">
                <label>Tool</label>
                <select 
                  value={formToolName} 
                  onChange={e => setFormToolName(e.target.value)}
                  disabled={!formServerName || loadingServers.has(formServerName)}
                >
                  <option value="">
                    {loadingServers.has(formServerName) ? 'Loading tools...' : 'Select tool...'}
                  </option>
                  {(availableTools[formServerName] || []).map(tool => (
                    <option key={tool.name} value={tool.name}>{tool.name}</option>
                  ))}
                </select>
              </div>
              
              {selectedToolSchema?.description && (
                <div className="tool-desc">{selectedToolSchema.description}</div>
              )}
              
              {selectedToolSchema?.parameters?.properties && Object.keys(selectedToolSchema.parameters.properties).length > 0 && (
                <div className="tool-args">
                  <label>Arguments</label>
                  {Object.entries(selectedToolSchema.parameters.properties).map(([key, schema]: [string, any]) => (
                    <div key={key} className="arg-row">
                      <span className="arg-name">
                        {key}
                        {selectedToolSchema.parameters.required?.includes(key) && <span className="required">*</span>}
                      </span>
                      <input
                        type={schema.type === 'number' || schema.type === 'integer' ? 'number' : 'text'}
                        value={typeof formArgs[key] === 'object' ? JSON.stringify(formArgs[key]) : formArgs[key] ?? ''}
                        onChange={e => setFormArgs(prev => ({ ...prev, [key]: e.target.value }))}
                        placeholder={schema.description?.slice(0, 40) || key}
                      />
                    </div>
                  ))}
                </div>
              )}
              
              {/* Test Section */}
              {formServerName && formToolName && (
                <div className="test-section">
                  <div className="test-header">
                    <label>Test & Preview</label>
                    <button 
                      className="test-btn"
                      onClick={testRunTool}
                      disabled={isTestRunning}
                    >
                      {isTestRunning ? <RefreshCw size={12} className="spin" /> : <Play size={12} />}
                      {isTestRunning ? 'Running...' : 'Test Run'}
                    </button>
                  </div>
                  
                  {testError && (
                    <div className="test-result error">
                      <span className="test-label">Error:</span>
                      <pre>{testError}</pre>
                    </div>
                  )}
                  
                  {testResult && (
                    <div className="test-result">
                      <span className="test-label">Raw Result:</span>
                      <pre>{testResult}</pre>
                    </div>
                  )}
                </div>
              )}
              
              <div className="form-row transform-row">
                <label>Transform (optional)</label>
                <input
                  type="text"
                  value={formTransform}
                  onChange={e => setFormTransform(e.target.value)}
                  placeholder="e.g., .items[0].name or .content[].text"
                />
                <div className="transform-hints">
                  <span className="hint-title">Path:</span>
                  <code onClick={() => setFormTransform('.items[0].name')}>.items[0].name</code>
                  <code onClick={() => setFormTransform('.content[0].text')}>.content[0].text</code>
                  <code onClick={() => setFormTransform('.result.data')}>.result.data</code>
                  <span className="hint-title">JS:</span>
                  <code onClick={() => setFormTransform("js:value.split('\\n')[0]")}>js:value.split('\n')[0]</code>
                  <code onClick={() => setFormTransform('js:data.items?.length')}>js:data.items?.length</code>
                </div>
              </div>
              
              {/* Live Transform Preview */}
              {testResult && formTransform && (
                <div className="transform-preview">
                  <span className="test-label">Transform Preview:</span>
                  <pre className={transformPreview?.startsWith('[Transform error') ? 'error' : ''}>
                    {transformPreview}
                  </pre>
                </div>
              )}
            </div>
            
            <div className="dialog-footer">
              <button className="cancel-btn" onClick={() => setShowDialog(false)}>Cancel</button>
              <button className="add-btn" onClick={saveWatch} disabled={!formServerName || !formToolName}>
                {editingWatchId ? 'Save Changes' : 'Add Watch'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// Legacy MCP Tool Runner removed - replaced by ToolWatchPanel
/*
function MCPToolRunnerLegacy({ project, onResult }: { project: Project; onResult: (result: any) => void }) {
  // ... legacy code removed ...
}
*/

// Placeholder to keep structure, not actually used
const _MCPToolRunnerRemovedPlaceholder = () => (
  <div className="mcp-runner">
    <div className="runner-header">
      <Terminal size={14} />
      <span>Deprecated - use Tool Watch instead</span>
    </div>
  </div>
);
void _MCPToolRunnerRemovedPlaceholder; // silence unused warning

// Legacy MCPToolRunner removed - functionality replaced by ToolWatchPanel

// D3 Time Series Chart Component for Metrics
interface MetricsChartProps {
  data: Array<{ timestamp: number; value: number }>;
  color: string;
  label: string;
  currentValue: number;
  unit?: string;
  height?: number;
}

function MetricsTimeSeriesChart({ data, color, label, currentValue, unit = '%', height = 80 }: MetricsChartProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [dimensions, setDimensions] = useState({ width: 200, height });

  // Handle resize
  useEffect(() => {
    if (!containerRef.current) return;
    
    const resizeObserver = new ResizeObserver(entries => {
      for (const entry of entries) {
        setDimensions({
          width: entry.contentRect.width,
          height,
        });
      }
    });
    
    resizeObserver.observe(containerRef.current);
    return () => resizeObserver.disconnect();
  }, [height]);

  // Draw chart with D3
  useEffect(() => {
    if (!svgRef.current || data.length < 2) return;

    const svg = d3.select(svgRef.current);
    svg.selectAll('*').remove();

    const margin = { top: 8, right: 8, bottom: 10, left: 8 };
    const width = dimensions.width - margin.left - margin.right;
    const chartHeight = dimensions.height - margin.top - margin.bottom;

    if (width <= 0 || chartHeight <= 0) return;

    const g = svg.append('g')
      .attr('transform', `translate(${margin.left},${margin.top})`);

    // Scales - use -5 as min so 0% line is visible above the bottom
    const xScale = d3.scaleTime()
      .domain(d3.extent(data, d => d.timestamp) as [number, number])
      .range([0, width]);

    const yScale = d3.scaleLinear()
      .domain([-5, 100])
      .range([chartHeight, 0]);

    // Gradient fill - sanitize label for valid SVG ID
    const gradientId = `gradient-${label.replace(/[^a-zA-Z0-9]/g, '-')}`;
    const defs = svg.append('defs');
    const gradient = defs.append('linearGradient')
      .attr('id', gradientId)
      .attr('x1', '0%')
      .attr('y1', '0%')
      .attr('x2', '0%')
      .attr('y2', '100%');
    
    gradient.append('stop')
      .attr('offset', '0%')
      .attr('stop-color', color)
      .attr('stop-opacity', 0.3);
    
    gradient.append('stop')
      .attr('offset', '100%')
      .attr('stop-color', color)
      .attr('stop-opacity', 0.05);

    // Area generator
    const area = d3.area<{ timestamp: number; value: number }>()
      .x(d => xScale(d.timestamp))
      .y0(chartHeight)
      .y1(d => yScale(d.value))
      .curve(d3.curveMonotoneX);

    // Line generator
    const line = d3.line<{ timestamp: number; value: number }>()
      .x(d => xScale(d.timestamp))
      .y(d => yScale(d.value))
      .curve(d3.curveMonotoneX);

    // Draw area
    g.append('path')
      .datum(data)
      .attr('fill', `url(#${gradientId})`)
      .attr('d', area);

    // Draw line
    g.append('path')
      .datum(data)
      .attr('fill', 'none')
      .attr('stroke', color)
      .attr('stroke-width', 2)
      .attr('d', line);

    // Draw current value dot
    if (data.length > 0) {
      const lastPoint = data[data.length - 1];
      g.append('circle')
        .attr('cx', xScale(lastPoint.timestamp))
        .attr('cy', yScale(lastPoint.value))
        .attr('r', 4)
        .attr('fill', color)
        .attr('stroke', '#18181b')
        .attr('stroke-width', 2);
    }

  }, [data, dimensions, color, label]);

  return (
    <div ref={containerRef} className="metrics-chart-container">
      <div className="metrics-chart-header">
        <span className="metrics-chart-label">{label}</span>
        <span className="metrics-chart-value" style={{ color }}>
          {currentValue.toFixed(1)}{unit}
        </span>
      </div>
      <svg
        ref={svgRef}
        width={dimensions.width}
        height={dimensions.height}
        style={{ display: 'block' }}
      />
    </div>
  );
}

// CPU Stats Time Series Chart Component (min, avg, max)
interface CpuStatsChartProps {
  data: Array<{ timestamp: number; cores: number[] }>;
  height?: number;
}

function CpuStatsTimeSeriesChart({ data, height = 80 }: CpuStatsChartProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [dimensions, setDimensions] = useState({ width: 200, height });

  // Handle resize
  useEffect(() => {
    if (!containerRef.current) return;
    
    const resizeObserver = new ResizeObserver(entries => {
      for (const entry of entries) {
        setDimensions({
          width: entry.contentRect.width,
          height,
        });
      }
    });
    
    resizeObserver.observe(containerRef.current);
    return () => resizeObserver.disconnect();
  }, [height]);

  // Calculate stats for each timestamp
  const statsData = useMemo(() => {
    return data.map(d => {
      const cores = d.cores.filter(c => c !== undefined && c !== null);
      if (cores.length === 0) {
        return { timestamp: d.timestamp, min: 0, avg: 0, max: 0 };
      }
      const min = Math.min(...cores);
      const max = Math.max(...cores);
      const avg = cores.reduce((a, b) => a + b, 0) / cores.length;
      return { timestamp: d.timestamp, min, avg, max };
    });
  }, [data]);

  // Get number of cores and current values
  const numCores = data.length > 0 ? data[0].cores.length : 0;
  const currentStats = statsData.length > 0 ? statsData[statsData.length - 1] : { min: 0, avg: 0, max: 0 };

  // Draw chart with D3
  useEffect(() => {
    if (!svgRef.current || statsData.length < 2) return;

    const svg = d3.select(svgRef.current);
    svg.selectAll('*').remove();

    const margin = { top: 8, right: 8, bottom: 10, left: 8 };
    const width = dimensions.width - margin.left - margin.right;
    const chartHeight = dimensions.height - margin.top - margin.bottom;

    if (width <= 0 || chartHeight <= 0) return;

    const g = svg.append('g')
      .attr('transform', `translate(${margin.left},${margin.top})`);

    // Scales - use -5 as min so 0% line is visible above the bottom
    const xScale = d3.scaleTime()
      .domain(d3.extent(statsData, d => d.timestamp) as [number, number])
      .range([0, width]);

    const yScale = d3.scaleLinear()
      .domain([-5, 100])
      .range([chartHeight, 0]);

    // Gradient for the min-max range fill
    const defs = svg.append('defs');
    const gradient = defs.append('linearGradient')
      .attr('id', 'cpu-range-gradient')
      .attr('x1', '0%')
      .attr('y1', '0%')
      .attr('x2', '0%')
      .attr('y2', '100%');
    
    gradient.append('stop')
      .attr('offset', '0%')
      .attr('stop-color', '#34d399')
      .attr('stop-opacity', 0.3);
    
    gradient.append('stop')
      .attr('offset', '100%')
      .attr('stop-color', '#34d399')
      .attr('stop-opacity', 0.1);

    // Area generator for min-max range
    const area = d3.area<{ timestamp: number; min: number; max: number }>()
      .x(d => xScale(d.timestamp))
      .y0(d => yScale(d.min))
      .y1(d => yScale(d.max))
      .curve(d3.curveMonotoneX);

    // Draw the min-max range area
    g.append('path')
      .datum(statsData)
      .attr('fill', 'url(#cpu-range-gradient)')
      .attr('d', area);

    // Line generators
    const lineGenerator = d3.line<{ timestamp: number; min: number; avg: number; max: number }>()
      .curve(d3.curveMonotoneX);

    // Draw max line (lighter)
    g.append('path')
      .datum(statsData)
      .attr('fill', 'none')
      .attr('stroke', '#34d399')
      .attr('stroke-width', 1)
      .attr('stroke-opacity', 0.4)
      .attr('stroke-dasharray', '2,2')
      .attr('d', lineGenerator.x(d => xScale(d.timestamp)).y(d => yScale(d.max)));

    // Draw min line (lighter)
    g.append('path')
      .datum(statsData)
      .attr('fill', 'none')
      .attr('stroke', '#34d399')
      .attr('stroke-width', 1)
      .attr('stroke-opacity', 0.4)
      .attr('stroke-dasharray', '2,2')
      .attr('d', lineGenerator.x(d => xScale(d.timestamp)).y(d => yScale(d.min)));

    // Draw avg line (solid, prominent)
    g.append('path')
      .datum(statsData)
      .attr('fill', 'none')
      .attr('stroke', '#34d399')
      .attr('stroke-width', 2)
      .attr('d', lineGenerator.x(d => xScale(d.timestamp)).y(d => yScale(d.avg)));

    // Draw current value dot for avg
    if (statsData.length > 0) {
      const lastPoint = statsData[statsData.length - 1];
      g.append('circle')
        .attr('cx', xScale(lastPoint.timestamp))
        .attr('cy', yScale(lastPoint.avg))
        .attr('r', 4)
        .attr('fill', '#34d399')
        .attr('stroke', '#18181b')
        .attr('stroke-width', 2);
    }

  }, [statsData, dimensions]);

  return (
    <div ref={containerRef} className="metrics-chart-container">
      <div className="metrics-chart-header">
        <span className="metrics-chart-label">CPU ({numCores} cores)</span>
        <span className="metrics-chart-value" style={{ color: '#34d399' }}>
          {currentStats.avg.toFixed(1)}%
        </span>
      </div>
      <svg
        ref={svgRef}
        width={dimensions.width}
        height={dimensions.height}
        style={{ display: 'block' }}
      />
    </div>
  );
}

export default function RunPanel() {
  const { project, updateProject, isRunning, setIsRunning, runEvents, addRunEvent, clearRunEvents, clearWatchHistories, runAgentId, setRunAgentId, watches, updateWatch, currentSessionId, setCurrentSessionId } = useStore();
  
  // UI state
  const [userInput, setUserInput] = useState('');
  const [ws, setWs] = useState<WebSocket | null>(null);
  const [selectedEventIndex, setSelectedEventIndex] = useState<number | null>(null);
  const [timeRange, setTimeRange] = useState<[number, number] | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [eventTypeFilter, setEventTypeFilter] = useState<Set<string>>(new Set(['agent_start', 'agent_end', 'tool_call', 'tool_result', 'model_call', 'model_response', 'state_change', 'callback_start', 'callback_end', 'callback_error']));
  const [sandboxMode, setSandboxMode] = useState(() => {
    // Load from localStorage, default to true
    const stored = localStorage.getItem('sandboxMode');
    return stored !== null ? stored === 'true' : true;
  });
  
  // Save sandboxMode to localStorage when it changes
  useEffect(() => {
    localStorage.setItem('sandboxMode', String(sandboxMode));
  }, [sandboxMode]);
  
  const [pendingApproval, setPendingApproval] = useState<ApprovalRequest | null>(null);  // Pending network approval request
  const [showLogsModal, setShowLogsModal] = useState(false);  // Show container logs modal
  const [containerLogs, setContainerLogs] = useState<{ agent?: string; gateway?: string }>({});
  const [logsLoading, setLogsLoading] = useState(false);
  const [logsTab, setLogsTab] = useState<'agent' | 'gateway'>('agent');
  const logsContainerRef = useRef<HTMLDivElement>(null);
  const logsUserAtBottomRef = useRef(true);  // Track if user is at bottom of logs
  const logsPrevScrollHeightRef = useRef(0);  // Track previous scroll height for position retention
  const [hideCompleteResponses, setHideCompleteResponses] = useState(true);
  const [showStatePanel, setShowStatePanel] = useState(true);
  const [showToolRunner, setShowToolRunner] = useState(false);
  const [showArtifactsPanel, setShowArtifactsPanel] = useState(false);
  const [sidebarWidth, setSidebarWidth] = useState(360);
  const [isResizing, setIsResizing] = useState(false);
  const [isAgentGraphOpen, setIsAgentGraphOpen] = useState(false);
  const [wasCancelled, setWasCancelled] = useState(false);
  
  // System metrics drawer state
  const [isMetricsDrawerOpen, setIsMetricsDrawerOpen] = useState(false);
  const [systemMetrics, setSystemMetrics] = useState<SystemMetrics | null>(null);
  const [metricsHistory, setMetricsHistory] = useState<Array<{
    timestamp: number;
    cpu: number;
    cpuCores: number[];
    memory: number;
    gpu?: number;
    gpuMemory?: number;
  }>>([]);
  const [metricsError, setMetricsError] = useState<string | null>(null);
  const metricsIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const MAX_METRICS_HISTORY = 20; // Keep 60 data points (1 minute at 1s interval)
  
  // Check if any model uses localhost (for showing metrics panel)
  const hasLocalModel = useMemo(() => {
    if (!project) return false;
    
    const isLocalhostUrl = (url: string | undefined): boolean => {
      if (!url) return false;
      const lower = url.toLowerCase();
      return lower.includes('localhost') || 
             lower.includes('127.0.0.1') || 
             lower.includes('0.0.0.0') ||
             lower.includes('host.docker.internal');
    };
    
    const isLocalModel = (provider: string | undefined, apiBase: string | undefined): boolean => {
      // Explicit localhost URL
      if (isLocalhostUrl(apiBase)) return true;
      // LiteLLM with empty base URL defaults to localhost
      if (provider === 'litellm' && !apiBase) return true;
      return false;
    };
    
    // Check app-level models
    for (const model of project.app.models || []) {
      if (isLocalModel(model.provider, model.api_base)) return true;
    }
    
    // Check agent-level models
    for (const agent of project.agents || []) {
      if (agent.type === 'LlmAgent' && agent.model) {
        if (isLocalModel(agent.model.provider, agent.model.api_base)) return true;
      }
    }
    
    return false;
  }, [project]);
  
  // Close metrics drawer if no local models
  useEffect(() => {
    if (!hasLocalModel && isMetricsDrawerOpen) {
      setIsMetricsDrawerOpen(false);
    }
  }, [hasLocalModel, isMetricsDrawerOpen]);
  
  // Compute run state for AgentGraph visualization
  const agentGraphRunState = useMemo((): 'idle' | 'running' | 'completed' | 'failed' | 'cancelled' => {
    if (isRunning) return 'running';
    if (runEvents.length === 0) return 'idle';
    
    // Check if the run was cancelled by the user
    if (wasCancelled) return 'cancelled';
    
    // Check if the run ended with an error
    // Look at the last few events for error indicators
    const lastEvents = runEvents.slice(-5);
    const hasError = lastEvents.some(event => {
      // Guard against malformed events
      if (!event || !event.event_type) return false;
      
      // Check for explicit error data
      if (event.data?.error) return true;
      if (event.event_type === 'callback_error') return true;
      if (event.event_type === 'agent_end' && event.data?.error) return true;
      
      // Check for "[ERROR]" in the event summary text
      const summary = getEventSummary(event);
      if (summary.includes('[ERROR]')) return true;
      
      // Check for error indicators in response text
      if (event.event_type === 'model_response') {
        const parts = event.data?.response_content?.parts || event.data?.parts || [];
        const textPart = parts.find((p: any) => p?.type === 'text');
        if (textPart?.text && (
          textPart.text.includes('[ERROR]') ||
          textPart.text.toLowerCase().includes('error:') ||
          textPart.text.toLowerCase().includes('exception:')
        )) {
          return true;
        }
      }
      
      return false;
    });
    
    if (hasError) return 'failed';
    
    // If we have events and no errors, consider it completed
    return 'completed';
  }, [isRunning, runEvents, wasCancelled]);
  
  // Prompt history and suggestions
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [promptHistory, setPromptHistory] = useState<Array<{ prompt: string; count: number }>>([]);
  const inputRef = useRef<HTMLInputElement>(null);
  
  // Load prompt history from LocalStorage on mount (scoped by project)
  useEffect(() => {
    if (!project) return;
    const storageKey = `promptHistory_${project.id}`;
    const stored = localStorage.getItem(storageKey);
    if (stored) {
      try {
        const parsed = JSON.parse(stored) as Record<string, number>;
        const history = Object.entries(parsed)
          .map(([prompt, count]) => ({ prompt, count }))
          .sort((a, b) => b.count - a.count);
        setPromptHistory(history);
      } catch (e) {
        console.error('Failed to parse prompt history:', e);
      }
    } else {
      setPromptHistory([]);  // Clear when switching projects
    }
  }, [project?.id]);
  
  // Save prompt to history
  const savePromptToHistory = useCallback((prompt: string) => {
    const trimmed = prompt.trim();
    if (!trimmed || !project) return;
    
    const storageKey = `promptHistory_${project.id}`;
    const stored = localStorage.getItem(storageKey);
    const history: Record<string, number> = stored ? JSON.parse(stored) : {};
    history[trimmed] = (history[trimmed] || 0) + 1;
    localStorage.setItem(storageKey, JSON.stringify(history));
    
    // Update state
    const updated = Object.entries(history)
      .map(([p, count]) => ({ prompt: p, count }))
      .sort((a, b) => b.count - a.count);
    setPromptHistory(updated);
  }, [project]);
  
  // Filter suggestions based on current input
  const filteredSuggestions = useMemo(() => {
    const query = userInput.toLowerCase().trim();
    return promptHistory
      .filter(h => !query || h.prompt.toLowerCase().includes(query))
      .slice(0, 10); // Limit to top 10
  }, [promptHistory, userInput]);
  
  // Column widths for resizable table columns
  const [columnWidths, setColumnWidths] = useState([60, 80, 100, 80, 1]); // Last one is flex (fr)
  const [resizingColumn, setResizingColumn] = useState<number | null>(null);
  const columnResizeStartX = useRef(0);
  const columnResizeStartWidth = useRef(0);
  
  // Session selector state
  const [availableSessions, setAvailableSessions] = useState<Array<{
    id: string;
    started_at: number;
    ended_at?: number;
    duration?: number;
    event_count: number;
  }>>([]);
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [loadingSessions, setLoadingSessions] = useState(false);
  
  // Auto-refresh watches at the panel level (so they run even when Tool tab isn't visible)
  const lastWatchEventCountRef = useRef(0);
  
  // Run a single watch - defined at panel level for auto-refresh
  const runWatchFromPanel = useCallback(async (watch: WatchExpression, eventIndex?: number) => {
    if (!project) return;
    updateWatch(watch.id, { isLoading: true, error: undefined });
    
    const currentEventIndex = eventIndex ?? runEvents.length - 1;
    const timestamp = Date.now();
    
    // Get the app_id for sandbox mode
    const appId = project.app?.id || `app_${project.id}`;
    
    try {
      const result = await fetchJSON(`/projects/${project.id}/run-mcp-tool`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          server_name: watch.serverName,
          tool_name: watch.toolName,
          arguments: watch.args,
          sandbox_mode: sandboxMode,  // Execute in Docker sandbox if enabled
          app_id: sandboxMode ? appId : undefined,
        }),
      });
      
      // Add to history
      const newSnapshot = { eventIndex: currentEventIndex, timestamp, result };
      const history = [...(watch.history || []), newSnapshot];
      
      updateWatch(watch.id, { result, isLoading: false, lastRun: timestamp, history });
    } catch (err) {
      // Add error to history
      const newSnapshot = { eventIndex: currentEventIndex, timestamp, error: String(err) };
      const history = [...(watch.history || []), newSnapshot];
      
      updateWatch(watch.id, { error: String(err), isLoading: false, lastRun: timestamp, history });
    }
  }, [project?.id, project?.app?.id, updateWatch, runEvents.length, sandboxMode]);
  
  // Auto-refresh watches when new events are added (runs at panel level, not ToolWatchPanel)
  useEffect(() => {
    if (runEvents.length > lastWatchEventCountRef.current && watches.length > 0) {
      const newEventIndex = runEvents.length - 1;
      // New event(s) added, refresh all watches that aren't already loading
      watches.forEach(watch => {
        if (!watch.isLoading) {
          runWatchFromPanel(watch, newEventIndex);
        }
      });
    }
    lastWatchEventCountRef.current = runEvents.length;
  }, [runEvents.length, watches, runWatchFromPanel]);
  
  // Initialize selectedAgentId from store (allows opening Run with specific agent)
  useEffect(() => {
    if (runAgentId !== null) {
      setSelectedAgentIdLocal(runAgentId);
      setRunAgentId(null); // Clear after using
    }
  }, [runAgentId, setRunAgentId]);
  
  const [selectedAgentIdLocal, setSelectedAgentIdLocal] = useState<string | null>(null); // null = root agent
  
  const eventListRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  
  // Fetch system metrics when drawer is open
  useEffect(() => {
    if (!isMetricsDrawerOpen) {
      // Clear interval when drawer closes
      if (metricsIntervalRef.current) {
        clearInterval(metricsIntervalRef.current);
        metricsIntervalRef.current = null;
      }
      return;
    }
    
    // Fetch metrics immediately
    const fetchMetrics = async () => {
      try {
        const metrics = await getSystemMetrics();
        setSystemMetrics(metrics);
        setMetricsError(null);
        
        // Add to history for time series
        setMetricsHistory(prev => {
          const newPoint = {
            timestamp: Date.now(),
            cpu: metrics.cpu.percent || 0,
            cpuCores: metrics.cpu.percent_per_core || [],
            memory: metrics.memory.percent || 0,
            gpu: metrics.gpu[0]?.utilization_percent ?? undefined,
            gpuMemory: metrics.gpu[0]?.memory_percent ?? undefined,
          };
          const updated = [...prev, newPoint];
          // Keep only last MAX_METRICS_HISTORY points
          return updated.slice(-MAX_METRICS_HISTORY);
        });
      } catch (err) {
        setMetricsError(err instanceof Error ? err.message : 'Failed to fetch metrics');
      }
    };
    
    fetchMetrics();
    
    // Poll every 1 second
    metricsIntervalRef.current = setInterval(fetchMetrics, 1000);
    
    return () => {
      if (metricsIntervalRef.current) {
        clearInterval(metricsIntervalRef.current);
        metricsIntervalRef.current = null;
      }
    };
  }, [isMetricsDrawerOpen]);
  
  // Handle sidebar resize
  useEffect(() => {
    if (!isResizing) return;
    
    const handleMouseMove = (e: MouseEvent) => {
      if (!containerRef.current) return;
      const containerRect = containerRef.current.getBoundingClientRect();
      const newWidth = containerRect.right - e.clientX;
      // Clamp between 200 and 600 pixels
      setSidebarWidth(Math.min(600, Math.max(200, newWidth)));
    };
    
    const handleMouseUp = () => {
      setIsResizing(false);
    };
    
    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);
    
    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isResizing]);
  
  // Handle column resize
  useEffect(() => {
    if (resizingColumn === null) return;
    
    const handleMouseMove = (e: MouseEvent) => {
      const delta = e.clientX - columnResizeStartX.current;
      const newWidth = Math.max(40, columnResizeStartWidth.current + delta);
      setColumnWidths(prev => {
        const updated = [...prev];
        updated[resizingColumn] = newWidth;
        return updated;
      });
    };
    
    const handleMouseUp = () => {
      setResizingColumn(null);
    };
    
    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    
    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };
  }, [resizingColumn]);
  
  // Start column resize
  const handleColumnResizeStart = (columnIndex: number, e: React.MouseEvent) => {
    e.preventDefault();
    columnResizeStartX.current = e.clientX;
    columnResizeStartWidth.current = columnWidths[columnIndex];
    setResizingColumn(columnIndex);
  };
  
  // Generate grid template from column widths
  const gridTemplateColumns = columnWidths.map((w, i) => 
    i === columnWidths.length - 1 ? `minmax(${w}px, 1fr)` : `${w}px`
  ).join(' ');
  
  // Calculate time bounds
  const timeBounds = useMemo(() => {
    if (runEvents.length === 0) return { min: 0, max: 0 };
    return {
      min: runEvents[0].timestamp,
      max: runEvents[runEvents.length - 1].timestamp,
    };
  }, [runEvents]);
  
  // Filter events
  const filteredEvents = useMemo(() => {
    return runEvents.filter((event, i) => {
      // Time range filter
      if (timeRange) {
        if (event.timestamp < timeRange[0] || event.timestamp > timeRange[1]) return false;
      }
      
      // Event type filter
      if (eventTypeFilter.size > 0 && !eventTypeFilter.has(event.event_type)) return false;
      
      // Hide "LLM_RESP (complete)" type responses - those without text or function_call in parts
      if (hideCompleteResponses && event.event_type === 'model_response') {
        const parts = event.data?.response_content?.parts || event.data?.parts || [];
        const hasFnCall = parts.some((p: any) => p.type === 'function_call');
        const hasText = parts.some((p: any) => p.type === 'text');
        // If no function_call and no text part, this would display as "LLM_RSP (complete)"
        if (!hasFnCall && !hasText) return false;
      }
      
      // Search filter
      if (searchQuery) {
        const str = JSON.stringify(event).toLowerCase();
        if (!str.includes(searchQuery.toLowerCase())) return false;
      }
      
      return true;
    });
  }, [runEvents, timeRange, eventTypeFilter, searchQuery, hideCompleteResponses]);
  
  // Compute cumulative token counts from model_response events up to selected event
  const tokenCounts = useMemo(() => {
    let input = 0;
    let output = 0;
    const endIndex = selectedEventIndex !== null ? selectedEventIndex + 1 : runEvents.length;
    for (let i = 0; i < endIndex; i++) {
      const event = runEvents[i];
      if (event.event_type === 'model_response' && event.data?.token_counts) {
        input += event.data.token_counts.input || 0;
        output += event.data.token_counts.output || 0;
      }
    }
    return { input, output, total: input + output };
  }, [runEvents, selectedEventIndex]);
  
  const selectedEvent = selectedEventIndex !== null ? runEvents[selectedEventIndex] : null;
  
  // Load available sessions when project changes
  useEffect(() => {
    if (!project) {
      setAvailableSessions([]);
      return;
    }
    
    const loadSessions = async () => {
      setLoadingSessions(true);
      try {
        const sessions = await listProjectSessions(project.id);
        setAvailableSessions(sessions);
      } catch (error) {
        console.error('Failed to load sessions:', error);
        setAvailableSessions([]);
      } finally {
        setLoadingSessions(false);
      }
    };
    
    loadSessions();
  }, [project]);
  
  // Handle session selection
  const handleSessionSelect = useCallback(async (sessionId: string | null) => {
    if (!project) {
      setSelectedSessionId(null);
      return;
    }
    
    // If sessionId is null (user selected "Load Session..."), clear the session
    if (!sessionId) {
      clearRunEvents();
      clearWatchHistories();
      setCurrentSessionId(null);
      setSelectedSessionId(null);
      setSelectedEventIndex(null);
      setTimeRange(null);
      return;
    }
    
    try {
      const session = await loadSession(project.id, sessionId);
      
      // Clear current events and load session events
      clearRunEvents();
      clearWatchHistories();
      setCurrentSessionId(session.id);
      setSelectedSessionId(sessionId);
      setSelectedEventIndex(null);
      setTimeRange(null);
      
      // Add all events from the session
      for (const event of session.events) {
        addRunEvent(event);
      }
    } catch (error: any) {
      alert(`Failed to load session: ${error.message || 'Unknown error'}`);
    }
  }, [project, clearRunEvents, clearWatchHistories, setCurrentSessionId, addRunEvent]);
  
  // Handle ?session= query parameter from URL (e.g., from "View Session" in Eval panel)
  useEffect(() => {
    if (!project || availableSessions.length === 0 || loadingSessions) return;
    
    const params = new URLSearchParams(window.location.search);
    const sessionIdFromUrl = params.get('session');
    
    if (sessionIdFromUrl) {
      // Check if this session exists in available sessions
      const sessionExists = availableSessions.some(s => s.id === sessionIdFromUrl);
      if (sessionExists) {
        // Load the session
        handleSessionSelect(sessionIdFromUrl);
        
        // Clean up the URL by removing the query parameter
        const newUrl = window.location.pathname;
        window.history.replaceState({}, '', newUrl);
      } else {
        console.warn(`Session ${sessionIdFromUrl} not found in available sessions`);
      }
    }
  }, [project, availableSessions, loadingSessions, handleSessionSelect]);
  
  // Auto-scroll to new events
  useEffect(() => {
    if (isRunning && eventListRef.current) {
      eventListRef.current.scrollTop = eventListRef.current.scrollHeight;
    }
  }, [runEvents.length, isRunning]);
  
  // Handle run
  const handleRun = useCallback((messageOverride?: string) => {
    const message = messageOverride ?? userInput;
    if (!project || !message.trim() || isRunning) return;
    
    // Open the agent graph drawer when run starts
    setIsAgentGraphOpen(true);
    
    // Save prompt to history
    savePromptToHistory(message);
    setShowSuggestions(false);
    setUserInput(message);
    
    // Close existing connection
    if (ws) {
      ws.close();
      setWs(null);
    }
    
    // Always start fresh - clear events and start a new session
      clearRunEvents();
    clearWatchHistories();
    setSelectedSessionId(null);
    setCurrentSessionId(null);  // Clear so we get a new session
    setIsRunning(true);
    setWasCancelled(false);  // Reset cancelled state for new run
    setSelectedEventIndex(null);
    setTimeRange(null);
    
    const websocket = createRunWebSocket(project.id);
    setWs(websocket);
    
    websocket.onopen = () => {
      websocket.send(JSON.stringify({ 
        message: message,
        agent_id: selectedAgentIdLocal || undefined,  // null means use root agent
        // Always start a new session (don't pass session_id)
        sandbox_mode: sandboxMode,  // Run in Docker sandbox
      }));
    };
    
    websocket.onmessage = (event) => {
      const data = JSON.parse(event.data);
      // Check if this is the first agent_start event with session_id (from backend)
      if (data.event_type === 'agent_start' && data.data?.session_id) {
        const sid = data.data.session_id;
        const isReused = data.data.session_reused === true;
        setCurrentSessionId(sid);
        // Update selectedSessionId to match
        if (sid && availableSessions.some(s => s.id === sid)) {
          setSelectedSessionId(sid);
        }
        // If session was reused, we're appending - don't clear events
        // Events were already loaded when session was selected
        // If it's a new session, events were already cleared in handleRun
      } else if (data.type === 'session_started') {
        setCurrentSessionId(data.session_id);
        // Update selectedSessionId to match
        if (data.session_id && availableSessions.some(s => s.id === data.session_id)) {
          setSelectedSessionId(data.session_id);
        }
      } else if (data.type === 'sandbox_starting') {
        addRunEvent({
          timestamp: Date.now() / 1000,
          event_type: 'agent_start',
          agent_name: 'sandbox',
          data: { message: 'Starting Docker sandbox...' }
        });
      } else if (data.type === 'sandbox_started') {
        addRunEvent({
          timestamp: Date.now() / 1000,
          event_type: 'agent_start',
          agent_name: 'sandbox',
          data: { message: `Sandbox started (ID: ${data.sandbox_id})` }
        });
      } else if (data.type === 'sandbox_response') {
        addRunEvent({
          timestamp: Date.now() / 1000,
          event_type: 'model_response',
          agent_name: 'sandbox',
          data: data.data
        });
      } else if (data.event_type === 'approval_required' || (data.type === 'network_request' && data.event_type === 'approval_required')) {
        // Show approval dialog for unknown network requests
        const approvalRequest: ApprovalRequest = {
          id: data.id,
          method: data.method || 'GET',
          url: data.url,
          host: data.host,
          source: data.source || 'agent',
          headers: data.headers || {},
          timeout: data.timeout || 30,
        };
        setPendingApproval(approvalRequest);
        addRunEvent({
          timestamp: Date.now() / 1000,
          event_type: 'callback_start',
          agent_name: 'sandbox',
          data: { 
            callback_name: 'network_approval',
            callback_type: 'approval',
            message: `⚠️ Network request to ${data.host} requires approval`,
            host: data.host,
            url: data.url,
          }
        });
      } else if (data.type === 'completed') {
        setIsRunning(false);
        websocket.close();
      } else if (data.type === 'error') {
        setIsRunning(false);
        addRunEvent({
          timestamp: Date.now() / 1000,
          event_type: 'agent_end',
          agent_name: 'system',
          data: { error: data.error }
        });
      } else {
        addRunEvent(data);
      }
    };
    
    websocket.onerror = (event) => {
      console.error('WebSocket error:', event);
      setIsRunning(false);
      addRunEvent({
        timestamp: Date.now() / 1000,
        event_type: 'agent_end',
        agent_name: 'system',
        data: { 
          error: 'Connection error. The server may have timed out or the LLM request failed. Try again or check if your model server is running.',
          retryable: true
        }
      });
    };
    
    websocket.onclose = (event) => {
      // Only handle unexpected closures - if completed, the message handler already set isRunning=false
      if (isRunning) {
      setIsRunning(false);
        // Check if this was an abnormal closure (not code 1000/normal)
        if (event.code !== 1000 && event.code !== 1005) {
          addRunEvent({
            timestamp: Date.now() / 1000,
            event_type: 'agent_end',
            agent_name: 'system',
            data: { 
              error: `Connection closed unexpectedly (code: ${event.code}). This may be due to a timeout or server error. Try increasing the request timeout in your model configuration.`,
              retryable: true
            }
          });
        }
      }
    };
  }, [project, userInput, isRunning, ws, clearRunEvents, clearWatchHistories, setIsRunning, addRunEvent, selectedAgentIdLocal, setCurrentSessionId, sandboxMode, savePromptToHistory]);
  
  // Handle stop
  const handleStop = useCallback(() => {
    ws?.close();
    setIsRunning(false);
    setWasCancelled(true);
  }, [ws, setIsRunning]);

  // Handle network approval
  const handleApprove = useCallback(async (pattern?: string, patternType?: PatternType, persist?: boolean) => {
    if (!pendingApproval || !project) return;
    
    const appId = project.app?.id || project.id;
    const action = pattern ? 'allow_pattern' : 'allow_once';
    const patternValue = pattern || pendingApproval.host;
    const patternTypeValue = patternType || 'exact';
    
    // Include project_id as query param for persistence
    const url = persist 
      ? `/sandbox/${appId}/approval?project_id=${project.id}`
      : `/sandbox/${appId}/approval`;
    try {
      await fetchJSON(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          request_id: pendingApproval.id,
          action,
          pattern: patternValue,
          pattern_type: patternTypeValue,
          persist: persist || false,
        }),
      });
      
      // If persisting, update the local project state so App config shows the pattern
      if (persist && action === 'allow_pattern') {
        const existingPatterns = project.app?.sandbox?.allowlist?.user || [];
        const newPattern = {
          id: `pattern_${Date.now().toString(36)}`,
          pattern: patternValue,
          pattern_type: patternTypeValue,
          source: 'approved',
          added_at: new Date().toISOString(),
        };
        updateProject({
          app: {
            ...project.app,
            sandbox: {
              ...project.app?.sandbox,
              enabled: project.app?.sandbox?.enabled ?? false,
              allow_all_network: project.app?.sandbox?.allow_all_network ?? false,
              allowlist: {
                auto: project.app?.sandbox?.allowlist?.auto || [],
                user: [...existingPatterns, newPattern],
              },
              unknown_action: project.app?.sandbox?.unknown_action ?? 'ask',
              approval_timeout: project.app?.sandbox?.approval_timeout ?? 30,
              agent_memory_limit_mb: project.app?.sandbox?.agent_memory_limit_mb ?? 512,
              agent_cpu_limit: project.app?.sandbox?.agent_cpu_limit ?? 1.0,
              mcp_memory_limit_mb: project.app?.sandbox?.mcp_memory_limit_mb ?? 256,
              mcp_cpu_limit: project.app?.sandbox?.mcp_cpu_limit ?? 0.5,
              run_timeout: project.app?.sandbox?.run_timeout ?? 3600,
            },
          },
        });
      }
      
      addRunEvent({
        timestamp: Date.now() / 1000,
        event_type: 'callback_end',
        agent_name: 'sandbox',
        data: { 
          callback_name: 'network_approval',
          callback_type: 'approval',
          message: `✅ Approved: ${patternValue}`,
          pattern: patternValue,
          action: action,
        }
      });
    } catch (e) {
      console.error('Failed to approve:', e);
    }
    setPendingApproval(null);
  }, [pendingApproval, project, addRunEvent, updateProject]);

  // Handle network denial
  const handleDeny = useCallback(async () => {
    if (!pendingApproval || !project) return;
    
    const appId = project.app?.id || project.id;
    try {
      await fetchJSON(`/sandbox/${appId}/approval`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          request_id: pendingApproval.id,
          action: 'deny',
        }),
      });
      addRunEvent({
        timestamp: Date.now() / 1000,
        event_type: 'callback_end',
        agent_name: 'sandbox',
        data: { 
          callback_name: 'network_approval',
          callback_type: 'approval',
          message: `❌ Denied: ${pendingApproval.host}`,
          host: pendingApproval.host,
          action: 'deny',
        }
      });
    } catch (e) {
      console.error('Failed to deny:', e);
    }
    setPendingApproval(null);
  }, [pendingApproval, project, addRunEvent]);
  
  // Fetch container logs (tail=500 to limit size)
  const fetchContainerLogs = useCallback(async (showLoadingState = true) => {
    if (!project) return;
    
    const appId = project.app?.id || `app_${project.id}`;
    if (showLoadingState) setLogsLoading(true);
    
    try {
      const [agentResult, gatewayResult] = await Promise.all([
        fetchJSON(`/sandbox/${appId}/logs?container=agent&tail=500`).catch(() => null),
        fetchJSON(`/sandbox/${appId}/logs?container=gateway&tail=500`).catch(() => null),
      ]);
      
      setContainerLogs({
        agent: agentResult?.logs || agentResult?.error || 'No logs available',
        gateway: gatewayResult?.logs || gatewayResult?.error || 'No logs available',
      });
    } catch (e) {
      console.error('Failed to fetch logs:', e);
      setContainerLogs({
        agent: `Error fetching logs: ${e}`,
        gateway: `Error fetching logs: ${e}`,
      });
    } finally {
      if (showLoadingState) setLogsLoading(false);
    }
  }, [project]);
  
  // Open logs modal and fetch logs
  const openLogsModal = useCallback(() => {
    setShowLogsModal(true);
    fetchContainerLogs();
  }, [fetchContainerLogs]);
  
  // Handle logs scroll position retention
  useEffect(() => {
    if (!showLogsModal || !logsContainerRef.current || logsLoading) return;
    
    const container = logsContainerRef.current;
    const prevScrollHeight = logsPrevScrollHeightRef.current;
    const newScrollHeight = container.scrollHeight;
    
    // Small timeout to ensure content is rendered
    setTimeout(() => {
      if (!logsContainerRef.current) return;
      
      if (logsUserAtBottomRef.current) {
        // User was at bottom, scroll to new bottom
        logsContainerRef.current.scrollTop = logsContainerRef.current.scrollHeight;
      } else if (prevScrollHeight > 0 && newScrollHeight > prevScrollHeight) {
        // User scrolled up, maintain their position by offsetting for new content
        const heightDiff = newScrollHeight - prevScrollHeight;
        logsContainerRef.current.scrollTop += heightDiff;
      }
      
      // Update the previous scroll height for next comparison
      logsPrevScrollHeightRef.current = logsContainerRef.current.scrollHeight;
    }, 50);
  }, [showLogsModal, logsTab, containerLogs, logsLoading]);
  
  // Reset scroll tracking when modal opens or tab changes
  useEffect(() => {
    if (showLogsModal) {
      logsUserAtBottomRef.current = true;
      logsPrevScrollHeightRef.current = 0;
    }
  }, [showLogsModal, logsTab]);
  
  // Handle scroll event to detect if user is at bottom
  const handleLogsScroll = useCallback(() => {
    if (!logsContainerRef.current) return;
    
    const container = logsContainerRef.current;
    const threshold = 50; // Consider "at bottom" if within 50px
    const isAtBottom = container.scrollHeight - container.scrollTop - container.clientHeight < threshold;
    logsUserAtBottomRef.current = isAtBottom;
  }, []);
  
  // Auto-refresh logs every 3 seconds when modal is open
  useEffect(() => {
    if (!showLogsModal) return;
    
    const intervalId = setInterval(() => {
      fetchContainerLogs(false); // Don't show loading state for auto-refresh
    }, 3000);
    
    return () => clearInterval(intervalId);
  }, [showLogsModal, fetchContainerLogs]);
  
  // Keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Cmd/Ctrl + Enter to run
      if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
        e.preventDefault();
        handleRun();
        return;
      }
      
      // Arrow keys to navigate event list
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        // Don't intercept if user is typing in an input
        if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) {
          return;
        }
        
        e.preventDefault();
        
        if (filteredEvents.length === 0) return;
        
        if (e.key === 'ArrowDown') {
          if (selectedEventIndex === null) {
            // Select first event
            const firstIndex = runEvents.indexOf(filteredEvents[0]);
            setSelectedEventIndex(firstIndex);
          } else {
            // Find current position in filtered list and move down
            const currentFilteredIndex = filteredEvents.findIndex(
              ev => runEvents.indexOf(ev) === selectedEventIndex
            );
            if (currentFilteredIndex < filteredEvents.length - 1) {
              const nextIndex = runEvents.indexOf(filteredEvents[currentFilteredIndex + 1]);
              setSelectedEventIndex(nextIndex);
            }
          }
        } else if (e.key === 'ArrowUp') {
          if (selectedEventIndex === null) {
            // Select last event
            const lastIndex = runEvents.indexOf(filteredEvents[filteredEvents.length - 1]);
            setSelectedEventIndex(lastIndex);
          } else {
            // Find current position in filtered list and move up
            const currentFilteredIndex = filteredEvents.findIndex(
              ev => runEvents.indexOf(ev) === selectedEventIndex
            );
            if (currentFilteredIndex > 0) {
              const prevIndex = runEvents.indexOf(filteredEvents[currentFilteredIndex - 1]);
              setSelectedEventIndex(prevIndex);
            }
          }
        }
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [handleRun, filteredEvents, selectedEventIndex, runEvents]);
  
  // Download run as JSON file
  const handleDownloadRun = useCallback(() => {
    if (runEvents.length === 0) return;
    
    const exportData = {
      version: 1,
      exportedAt: new Date().toISOString(),
      projectId: project?.id,
      projectName: project?.name,
      agentId: selectedAgentIdLocal || project?.app?.root_agent_id,
      events: runEvents,
    };
    
    const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `run-${project?.name || 'export'}-${new Date().toISOString().slice(0, 19).replace(/:/g, '-')}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }, [runEvents, project, selectedAgentIdLocal]);
  
  // Save session to memory
  const handleSaveToMemory = useCallback(async () => {
    if (!currentSessionId || !project) {
      alert('No active session to save');
      return;
    }
    
    try {
      const result = await saveSessionToMemory(currentSessionId);
      if (result.success) {
        alert(result.message || 'Session saved to memory successfully');
        // Refresh sessions list
        try {
          const sessions = await listProjectSessions(project.id);
          setAvailableSessions(sessions);
        } catch (e) {
          // Ignore refresh errors
        }
      } else {
        alert(`Failed to save to memory: ${result.error || 'Unknown error'}`);
      }
    } catch (error: any) {
      alert(`Error saving to memory: ${error.message || 'Unknown error'}`);
    }
  }, [currentSessionId, project]);
  
  // Create test case from current session
  const [showTestCaseDialog, setShowTestCaseDialog] = useState(false);
  const [testCaseEvalSets, setTestCaseEvalSets] = useState<Array<{id: string; name: string}>>([]);
  const [selectedEvalSetId, setSelectedEvalSetId] = useState<string>('');
  const [testCaseName, setTestCaseName] = useState('Test Case from Session');
  const [creatingTestCase, setCreatingTestCase] = useState(false);
  
  const handleCreateTestCase = useCallback(async () => {
    if (!currentSessionId || !project) {
      alert('No active session to create test case from');
      return;
    }
    
    // Load eval sets
    try {
      const response = await fetchJSON<{eval_sets: Array<{id: string; name: string}>}>(`/projects/${project.id}/eval-sets`);
      setTestCaseEvalSets(response.eval_sets || []);
      
      // If no eval sets, show alert and return
      if (!response.eval_sets || response.eval_sets.length === 0) {
        const createNew = confirm('No evaluation sets found. Would you like to create one first?\n\nGo to the Evals tab to create an evaluation set.');
        if (createNew) {
          // Navigate to evals tab
          window.location.href = `/project/${project.id}/evals`;
        }
        return;
      }
      
      setSelectedEvalSetId(response.eval_sets[0].id);
      setShowTestCaseDialog(true);
    } catch (error: any) {
      alert(`Error loading eval sets: ${error.message || 'Unknown error'}`);
    }
  }, [currentSessionId, project]);
  
  const handleConfirmCreateTestCase = useCallback(async () => {
    if (!currentSessionId || !project || !selectedEvalSetId) {
      alert('Please select an evaluation set');
      return;
    }
    
    setCreatingTestCase(true);
    try {
      const response = await fetchJSON<{eval_case: any; session_token_count: number}>(`/projects/${project.id}/session-to-eval-case`, {
        method: 'POST',
        body: JSON.stringify({
          session_id: currentSessionId,
          eval_set_id: selectedEvalSetId,
          case_name: testCaseName,
        }),
      });
      
      setShowTestCaseDialog(false);
      alert(`Test case "${response.eval_case.name}" created successfully!\n\nToken count: ${response.session_token_count.toLocaleString()} tokens\n\nGo to the Evals tab to view and edit the test case.`);
    } catch (error: any) {
      alert(`Error creating test case: ${error.message || 'Unknown error'}`);
    } finally {
      setCreatingTestCase(false);
    }
  }, [currentSessionId, project, selectedEvalSetId, testCaseName]);
  
  // Upload run from JSON file
  const handleUploadRun = useCallback(() => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.json';
    input.onchange = async (e) => {
      const file = (e.target as HTMLInputElement).files?.[0];
      if (!file) return;
      
      try {
        const text = await file.text();
        const data = JSON.parse(text);
        
        if (!data.events || !Array.isArray(data.events)) {
          alert('Invalid run file: missing events array');
          return;
        }
        
        // Clear current events and load the imported ones
        clearRunEvents();
        clearWatchHistories();
        setSelectedEventIndex(null);
        setTimeRange(null);
        
        // Add events one by one (or bulk if store supports it)
        data.events.forEach((event: RunEvent) => {
          addRunEvent(event);
        });
        
      } catch (err) {
        alert(`Failed to load run file: ${err}`);
      }
    };
    input.click();
  }, [clearRunEvents, clearWatchHistories, addRunEvent]);
  
  // Scroll selected event into view
  useEffect(() => {
    if (selectedEventIndex !== null) {
      const element = document.querySelector(`.event-row.selected`);
      element?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  }, [selectedEventIndex]);
  
  if (!project) {
    return <div className="run-panel empty">No project loaded</div>;
  }
  
  return (
    <div className={`run-panel ${isResizing ? 'resizing' : ''}`}>
      <style>{`
        .run-panel {
          display: flex;
          flex-direction: column;
          width: 100%;
          height: 100%;
          background: #0a0a0f;
          color: #e4e4e7;
          font-family: 'SF Mono', 'Consolas', 'Monaco', monospace;
          font-size: 12px;
        }
        
        .run-panel.resizing {
          cursor: col-resize;
          user-select: none;
        }
        
        .run-panel.resizing * {
          cursor: col-resize;
        }
        
        .run-panel.empty {
          align-items: center;
          justify-content: center;
          color: #71717a;
        }
        
        /* Input Area */
        .input-area {
          display: flex;
          gap: 8px;
          padding: 8px;
          background: #18181b;
          border-bottom: 1px solid #27272a;
        }
        
        .input-area .agent-selector {
          background: #09090b;
          border: 1px solid #27272a;
          border-radius: 4px;
          padding: 8px 12px;
          color: #e4e4e7;
          font-family: inherit;
          font-size: 11px;
          min-width: 140px;
          max-width: 200px;
          cursor: pointer;
        }
        
        .input-area .agent-selector:focus {
          outline: none;
          border-color: #3b82f6;
        }
        
        .input-area .agent-selector:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }
        
        .input-area input {
          flex: 1;
          background: #09090b;
          border: 1px solid #27272a;
          border-radius: 4px;
          padding: 8px 12px;
          color: #e4e4e7;
          font-family: inherit;
          font-size: 12px;
        }
        
        .input-area input:focus {
          outline: none;
          border-color: #3b82f6;
        }
        
        .input-area button {
          display: flex;
          align-items: center;
          gap: 6px;
          padding: 8px 16px;
          background: #3b82f6;
          border: none;
          border-radius: 4px;
          color: white;
          font-family: inherit;
          font-size: 12px;
          cursor: pointer;
        }
        
        .input-area button:hover {
          background: #2563eb;
        }
        
        .input-area button.stop {
          background: #ef4444;
        }
        
        .input-area button.stop:hover {
          background: #dc2626;
        }
        
        .input-area button:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }
        
        /* Toolbar */
        .toolbar {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 6px 8px;
          background: #18181b;
          border-bottom: 1px solid #27272a;
        }
        
        .toolbar-section {
          display: flex;
          align-items: center;
          gap: 4px;
        }
        
        .toolbar-divider {
          width: 1px;
          height: 20px;
          background: #27272a;
          margin: 0 8px;
        }
        
        .toolbar input {
          background: #09090b;
          border: 1px solid #27272a;
          border-radius: 4px;
          padding: 4px 8px;
          color: #e4e4e7;
          font-family: inherit;
          font-size: 11px;
          width: 200px;
        }
        
        .toolbar input:focus {
          outline: none;
          border-color: #3b82f6;
        }
        
        .filter-chip {
          padding: 3px 8px;
          background: #27272a;
          border: 1px solid #3f3f46;
          border-radius: 4px;
          color: #a1a1aa;
          font-size: 10px;
          cursor: pointer;
        }
        
        .filter-chip:hover {
          background: #3f3f46;
        }
        
        .filter-chip.active {
          background: #3b82f6;
          border-color: #3b82f6;
          color: white;
        }
        
        .toolbar-btn {
          display: flex;
          align-items: center;
          gap: 4px;
          padding: 4px 8px;
          background: transparent;
          border: 1px solid #3f3f46;
          border-radius: 4px;
          color: #a1a1aa;
          font-size: 10px;
          cursor: pointer;
        }
        
        .toolbar-btn:hover {
          background: #27272a;
          color: #e4e4e7;
        }
        
        .toolbar-btn.active {
          background: #27272a;
          border-color: #3b82f6;
          color: #3b82f6;
        }
        
        /* Main Content */
        .main-content {
          display: flex;
          flex: 1;
          min-height: 0;
        }
        
        /* Event List (Packet List) */
        .event-list-container {
          flex: 1;
          display: flex;
          flex-direction: column;
          border-right: 1px solid #27272a;
        }
        
        .event-list-header {
          display: grid;
          gap: 0;
          background: #18181b;
          border-bottom: 1px solid #27272a;
          font-size: 10px;
          font-weight: 600;
          color: #71717a;
          text-transform: uppercase;
        }
        
        .event-list-header .header-cell {
          padding: 6px 8px;
          background: #18181b;
          position: relative;
          display: flex;
          align-items: center;
          min-width: 0;
          overflow: hidden;
        }
        
        .event-list-header .header-cell span {
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        
        .column-resize-handle {
          position: absolute;
          right: 0;
          top: 0;
          bottom: 0;
          width: 6px;
          cursor: col-resize;
          background: transparent;
          z-index: 1;
        }
        
        .column-resize-handle:hover,
        .column-resize-handle.active {
          background: #3b82f6;
        }
        
        .event-list {
          flex: 1;
          overflow-y: auto;
          background: #09090b;
        }
        
        .event-row {
          display: grid;
          gap: 0;
          border-bottom: 1px solid #18181b;
          cursor: pointer;
          transition: background 0.1s;
        }
        
        .event-row:hover {
          filter: brightness(1.2);
        }
        
        .event-row.selected {
          outline: 1px solid #3b82f6;
          outline-offset: -1px;
        }
        
        .event-row > div {
          padding: 3px 8px;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        
        .event-row .index { color: #71717a; font-size: 10px; }
        .event-row .time { font-size: 10px; }
        .event-row .agent { 
          font-weight: 500;
          display: flex;
          align-items: center;
        }
        .event-row .agent-badge {
          display: inline-block;
          padding: 1px 6px;
          border-radius: 3px;
          font-size: 10px;
          font-weight: 600;
          max-width: 100%;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .event-row .type { 
          font-size: 10px; 
          text-transform: uppercase;
          display: flex;
          align-items: center;
          gap: 4px;
        }
        .event-row .summary { font-size: 11px; }
        
        /* Time Range Selector */
        .time-range {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 6px 8px;
          background: #18181b;
          border-bottom: 1px solid #27272a;
        }
        
        .time-range label {
          font-size: 10px;
          color: #71717a;
        }
        
        .time-range input[type="datetime-local"] {
          background: #09090b;
          border: 1px solid #27272a;
          border-radius: 4px;
          padding: 2px 6px;
          color: #e4e4e7;
          font-family: inherit;
          font-size: 10px;
        }
        
        .time-range button {
          padding: 2px 8px;
          background: #27272a;
          border: 1px solid #3f3f46;
          border-radius: 4px;
          color: #a1a1aa;
          font-size: 10px;
          cursor: pointer;
        }
        
        .time-range button:hover {
          background: #3f3f46;
        }
        
        /* Side Panel */
        .side-panel-container {
          display: flex;
          flex-shrink: 0;
        }
        
        .resize-handle {
          width: 4px;
          background: #27272a;
          cursor: col-resize;
          transition: background 0.15s;
        }
        
        .resize-handle:hover,
        .resize-handle.active {
          background: #3b82f6;
        }
        
        .side-panel {
          display: flex;
          flex-direction: column;
          background: #0f0f14;
          min-width: 0;
        }
        
        .side-panel-tabs {
          display: flex;
          background: #18181b;
          border-bottom: 1px solid #27272a;
        }
        
        .side-panel-tab {
          flex: 1;
          padding: 8px;
          background: transparent;
          border: none;
          color: #71717a;
          font-size: 11px;
          cursor: pointer;
          border-bottom: 2px solid transparent;
        }
        
        .side-panel-tab:hover {
          color: #a1a1aa;
        }
        
        .side-panel-tab.active {
          color: #e4e4e7;
          border-bottom-color: #3b82f6;
        }
        
        .side-panel-content {
          flex: 1;
          overflow-y: auto;
        }
        
        /* Event Detail */
        .event-detail {
          padding: 8px;
        }
        
        .detail-header {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
          padding: 8px;
          background: #18181b;
          border-radius: 4px;
          margin-bottom: 8px;
        }
        
        .detail-type {
          padding: 2px 8px;
          background: #3b82f6;
          border-radius: 4px;
          font-size: 10px;
          font-weight: 600;
          text-transform: uppercase;
        }
        
        .detail-agent {
          color: #a1a1aa;
          font-size: 11px;
        }
        
        .detail-time {
          color: #71717a;
          font-size: 10px;
          margin-left: auto;
        }
        
        .detail-section {
          margin-bottom: 8px;
          background: #18181b;
          border-radius: 4px;
          overflow: hidden;
        }
        
        .section-header {
          display: flex;
          align-items: center;
          gap: 6px;
          padding: 6px 8px;
          background: #27272a;
          cursor: pointer;
          font-size: 11px;
          font-weight: 500;
        }
        
        .section-header:hover {
          background: #3f3f46;
        }
        
        .section-content {
          padding: 8px;
          font-size: 11px;
          line-height: 1.5;
        }
        
        /* JSON Viewer */
        .json-viewer {
          font-family: 'SF Mono', 'Consolas', monospace;
          font-size: 11px;
          line-height: 1.4;
          white-space: pre;
          overflow-x: auto;
        }

        .json-key { color: #93c5fd; }
        .json-string { color: #86efac; }
        .json-string-clickable { 
          cursor: pointer; 
          text-decoration-style: dotted;
          text-underline-offset: 2px;
        }
        .json-string-clickable:hover { 
          color: #4ade80;
          text-decoration-style: solid;
        }
        .json-number { color: #fde047; }
        .json-boolean { color: #f472b6; }
        .json-null { color: #71717a; }
        .json-undefined { color: #71717a; font-style: italic; }
        .json-truncated { color: #71717a; font-size: 10px; }
        .json-bracket { color: #a1a1aa; }
        .json-colon { color: #a1a1aa; }
        .json-comma { color: #a1a1aa; }
        .json-block { display: inline; }
        .json-inline { display: inline; }
        
        /* Message Items */
        .message-item {
          margin-bottom: 8px;
          padding: 8px;
          background: #09090b;
          border-radius: 4px;
        }
        
        .message-role {
          display: inline-block;
          padding: 2px 6px;
          border-radius: 4px;
          font-size: 10px;
          font-weight: 600;
          text-transform: uppercase;
          margin-bottom: 4px;
        }
        
        .message-role.user { background: #3b82f6; }
        .message-role.model { background: #22c55e; }
        .message-role.assistant { background: #22c55e; }
        .message-role.system { background: #a855f7; }
        
        .message-parts pre {
          margin: 4px 0;
          padding: 8px;
          background: #18181b;
          border-radius: 4px;
          white-space: pre-wrap;
          word-break: break-all;
          font-size: 11px;
        }
        
        .function-call, .function-response {
          margin: 4px 0;
          padding: 8px;
          background: #18181b;
          border-radius: 4px;
          border-left: 3px solid #3b82f6;
        }
        
        .function-response {
          border-left-color: #22c55e;
        }
        
        .result-content {
          white-space: pre-wrap;
          word-break: break-all;
          background: #18181b;
          padding: 8px;
          border-radius: 4px;
          max-height: 300px;
          overflow-y: auto;
        }
        
        .token-badge, .char-count {
          margin-left: auto;
          font-size: 10px;
          color: #71717a;
          background: #27272a;
          padding: 2px 6px;
          border-radius: 4px;
        }
        
        .instruction-text {
          white-space: pre-wrap;
          word-break: break-word;
          background: #18181b;
          padding: 8px;
          border-radius: 4px;
          margin: 0;
          font-size: 11px;
          max-height: 400px;
          overflow-y: auto;
          border-left: 3px solid #a855f7;
        }
        
        .response-part {
          margin-bottom: 8px;
        }
        
        .response-part:last-child {
          margin-bottom: 0;
        }
        
        .response-text {
          white-space: pre-wrap;
          word-break: break-word;
          background: #18181b;
          padding: 8px;
          border-radius: 4px;
          margin: 0;
          font-size: 11px;
          max-height: 400px;
          overflow-y: auto;
        }
        
        .thought-indicator {
          font-size: 10px;
          color: #a855f7;
          margin-top: 4px;
        }
        
        .state-delta-item {
          margin-bottom: 8px;
          background: #18181b;
          border-radius: 4px;
          overflow: hidden;
        }
        
        .state-delta-item:last-child {
          margin-bottom: 0;
        }
        
        .state-delta-key {
          padding: 6px 8px;
          background: #27272a;
          font-size: 11px;
          font-weight: 600;
          color: #22c55e;
          font-family: 'JetBrains Mono', 'Fira Code', monospace;
        }
        
        .state-delta-value {
          padding: 8px;
          margin: 0;
          font-size: 11px;
          white-space: pre-wrap;
          word-break: break-word;
          max-height: 300px;
          overflow-y: auto;
        }
        
        /* State Snapshot */
        .state-snapshot {
          padding: 8px;
        }
        
        .state-header {
          padding: 8px;
          margin-bottom: 8px;
          background: #18181b;
          border-radius: 4px;
          font-size: 11px;
          color: #a1a1aa;
          text-align: center;
        }
        
        .state-header {
          padding: 6px 8px;
          font-size: 10px;
          color: #71717a;
          text-transform: uppercase;
          letter-spacing: 0.5px;
          border-bottom: 1px solid #27272a;
          margin-bottom: 8px;
        }
        
        .state-empty {
          padding: 16px;
          text-align: center;
          color: #71717a;
        }
        
        .state-entry {
          padding: 8px;
          background: #18181b;
          border-radius: 4px;
          margin-bottom: 6px;
        }
        
        .state-key {
          font-weight: 600;
          color: #93c5fd;
          font-size: 11px;
          margin-bottom: 4px;
        }
        
        .state-value {
          font-family: 'SF Mono', 'Consolas', monospace;
          font-size: 11px;
          color: #86efac;
          white-space: pre-wrap;
          word-break: break-all;
          max-height: 100px;
          overflow-y: auto;
          transition: background 0.15s ease;
        }
        .state-value:hover {
          background: rgba(255, 255, 255, 0.05);
        }
        
        .state-time {
          font-size: 10px;
          color: #71717a;
          margin-top: 4px;
        }
        
        /* MCP Runner */
        .mcp-runner {
          padding: 8px;
        }
        
        .runner-header {
          display: flex;
          align-items: center;
          gap: 6px;
          padding: 8px;
          background: #18181b;
          border-radius: 4px;
          margin-bottom: 8px;
          font-weight: 600;
        }
        
        .runner-form {
          display: flex;
          flex-direction: column;
          gap: 8px;
        }
        
        .form-row {
          display: flex;
          flex-direction: column;
          gap: 4px;
        }
        
        .form-row label {
          font-size: 10px;
          color: #71717a;
          text-transform: uppercase;
        }
        
        .form-row select, .form-row input {
          background: #09090b;
          border: 1px solid #27272a;
          border-radius: 4px;
          padding: 6px 8px;
          color: #e4e4e7;
          font-family: inherit;
          font-size: 11px;
        }
        
        .form-row select:focus, .form-row input:focus {
          outline: none;
          border-color: #3b82f6;
        }
        
        .tool-description {
          padding: 8px;
          background: #18181b;
          border-radius: 4px;
          font-size: 11px;
          color: #a1a1aa;
        }
        
        .tool-params {
          background: #18181b;
          border-radius: 4px;
          padding: 8px;
        }
        
        .params-header {
          font-size: 10px;
          color: #71717a;
          text-transform: uppercase;
          margin-bottom: 8px;
        }
        
        .param-row {
          display: flex;
          flex-direction: column;
          gap: 4px;
          margin-bottom: 8px;
        }
        
        .param-row label {
          font-size: 10px;
          color: #a1a1aa;
        }
        
        .param-row .required {
          color: #ef4444;
          margin-left: 2px;
        }
        
        .run-btn {
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 6px;
          padding: 8px 16px;
          background: #22c55e;
          border: none;
          border-radius: 4px;
          color: white;
          font-family: inherit;
          font-size: 11px;
          cursor: pointer;
        }
        
        .run-btn:hover {
          background: #16a34a;
        }
        
        .run-btn:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }
        
        .spin {
          animation: spin 1s linear infinite;
        }
        
        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
        
        /* Tool Watch Panel */
        .tool-watch-panel {
          height: 100%;
          display: flex;
          flex-direction: column;
        }
        
        .watch-header {
          display: flex;
          align-items: center;
          gap: 6px;
          padding: 8px;
          background: #18181b;
          border-radius: 4px;
          font-weight: 600;
          font-size: 12px;
        }
        
        .watch-auto-badge {
          font-size: 9px;
          color: #10b981;
          background: rgba(16, 185, 129, 0.15);
          padding: 2px 6px;
          border-radius: 4px;
          font-weight: 500;
        }
        
        .watch-header .watch-actions {
          margin-left: auto;
          display: flex;
          gap: 4px;
        }
        
        .watch-btn {
          display: flex;
          align-items: center;
          justify-content: center;
          padding: 4px;
          background: transparent;
          border: none;
          border-radius: 3px;
          color: #a1a1aa;
          cursor: pointer;
        }
        
        .watch-btn:hover {
          background: #27272a;
          color: #e4e4e7;
        }
        
        .watch-btn.active {
          background: #22c55e30;
          color: #22c55e;
        }
        
        .watch-btn.active:hover {
          background: #22c55e50;
        }
        
        .watch-empty {
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          gap: 8px;
          padding: 24px;
          color: #71717a;
          font-size: 11px;
        }
        
        .add-watch-btn {
          display: flex;
          align-items: center;
          gap: 4px;
          padding: 6px 12px;
          background: #27272a;
          border: none;
          border-radius: 4px;
          color: #e4e4e7;
          font-size: 11px;
          cursor: pointer;
        }
        
        .add-watch-btn:hover {
          background: #3f3f46;
        }
        
        .watch-list {
          flex: 1;
          overflow-y: auto;
          padding: 8px;
        }
        
        .watch-item {
          background: #18181b;
          border: 1px solid #27272a;
          border-radius: 4px;
          margin-bottom: 6px;
        }
        
        .watch-item.error {
          border-color: #7f1d1d;
        }
        
        .watch-item-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 6px 8px;
          background: #0c0c0d;
          border-radius: 4px 4px 0 0;
          border-bottom: 1px solid #27272a;
        }
        
        .watch-expr {
          font-family: 'SF Mono', 'Consolas', monospace;
          font-size: 10px;
          display: flex;
          align-items: center;
          gap: 4px;
          overflow: hidden;
        }
        
        .watch-server {
          color: #71717a;
        }
        
        .watch-server::after {
          content: '/';
          margin: 0 2px;
          color: #3f3f46;
        }
        
        .watch-tool {
          color: #fbbf24;
        }
        
        .watch-args {
          color: #71717a;
          font-size: 9px;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        
        .watch-time-indicator {
          color: #3b82f6;
          font-size: 9px;
          font-weight: 500;
          margin-left: 4px;
          background: #3b82f620;
          padding: 1px 4px;
          border-radius: 3px;
          flex-shrink: 0;
        }
        
        .watch-item-actions {
          display: flex;
          gap: 4px;
          flex-shrink: 0;
        }
        
        .watch-item-actions button {
          display: flex;
          align-items: center;
          justify-content: center;
          padding: 3px;
          background: transparent;
          border: none;
          border-radius: 3px;
          color: #71717a;
          cursor: pointer;
        }
        
        .watch-item-actions button:hover {
          background: #27272a;
          color: #e4e4e7;
        }
        
        .watch-result {
          padding: 8px 10px;
          font-family: 'SF Mono', 'Consolas', monospace;
          font-size: 11px;
          max-height: 200px;
          overflow-y: auto;
          background: #0c0c0d;
          border-radius: 0 0 4px 4px;
        }
        
        .watch-result .loading {
          color: #71717a;
          font-style: italic;
        }
        
        .watch-result .error {
          color: #ef4444;
        }
        
        .watch-result .no-result {
          color: #52525b;
          font-style: italic;
        }
        
        .watch-result pre {
          margin: 0;
          white-space: pre-wrap;
          word-break: break-word;
          color: #86efac;
          line-height: 1.4;
        }
        
        .watch-result pre.error-text {
          color: #fca5a5;
        }
        
        .form-hint {
          font-size: 10px;
          color: #71717a;
          margin-top: 4px;
        }
        
        .transform-hints {
          display: flex;
          flex-wrap: wrap;
          gap: 4px 8px;
          margin-top: 6px;
          font-size: 10px;
          align-items: center;
        }
        
        .transform-hints .hint-title {
          color: #71717a;
          font-weight: 500;
        }
        
        .transform-hints code {
          background: #27272a;
          color: #a1a1aa;
          padding: 2px 6px;
          border-radius: 3px;
          font-family: 'JetBrains Mono', 'Fira Code', monospace;
          font-size: 9px;
          cursor: pointer;
          transition: all 0.15s;
        }
        
        .transform-hints code:hover {
          background: #3f3f46;
          color: #e4e4e7;
        }
        
        /* Test Section in Dialog */
        .test-section {
          background: #0c0c0d;
          border-radius: 4px;
          padding: 10px;
          margin-bottom: 12px;
        }
        
        .test-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          margin-bottom: 8px;
        }
        
        .test-header label {
          font-size: 10px;
          color: #71717a;
          text-transform: uppercase;
        }
        
        .test-btn {
          display: flex;
          align-items: center;
          gap: 4px;
          padding: 4px 10px;
          background: #27272a;
          border: none;
          border-radius: 4px;
          color: #e4e4e7;
          font-size: 11px;
          cursor: pointer;
        }
        
        .test-btn:hover:not(:disabled) {
          background: #3f3f46;
        }
        
        .test-btn:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }
        
        .test-result {
          margin-bottom: 8px;
        }
        
        .test-result.error pre {
          color: #fca5a5;
        }
        
        .test-label {
          display: block;
          font-size: 10px;
          color: #71717a;
          margin-bottom: 4px;
        }
        
        .test-result pre {
          margin: 0;
          padding: 8px;
          background: #18181b;
          border-radius: 4px;
          font-size: 10px;
          color: #86efac;
          white-space: pre-wrap;
          word-break: break-word;
          max-height: 120px;
          overflow-y: auto;
        }
        
        .transform-preview {
          background: #0c0c0d;
          border-radius: 4px;
          padding: 10px;
          margin-top: 8px;
        }
        
        .transform-preview pre {
          margin: 0;
          padding: 8px;
          background: #18181b;
          border-radius: 4px;
          font-size: 10px;
          color: #93c5fd;
          white-space: pre-wrap;
          word-break: break-word;
          max-height: 100px;
          overflow-y: auto;
        }
        
        .transform-preview pre.error {
          color: #fca5a5;
        }
        
        /* Watch Dialog */
        .watch-dialog-overlay {
          position: fixed;
          top: 0;
          left: 0;
          right: 0;
          bottom: 0;
          background: rgba(0, 0, 0, 0.7);
          display: flex;
          align-items: center;
          justify-content: center;
          z-index: 10000;
        }
        
        .watch-dialog {
          background: #18181b;
          border: 1px solid #27272a;
          border-radius: 8px;
          width: 500px;
          max-height: 85vh;
          display: flex;
          flex-direction: column;
        }
        
        .dialog-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 12px 16px;
          border-bottom: 1px solid #27272a;
          font-weight: 600;
        }
        
        .dialog-header button {
          display: flex;
          align-items: center;
          justify-content: center;
          padding: 4px;
          background: transparent;
          border: none;
          border-radius: 4px;
          color: #71717a;
          cursor: pointer;
        }
        
        .dialog-header button:hover {
          background: #27272a;
          color: #e4e4e7;
        }
        
        .dialog-body {
          padding: 16px;
          overflow-y: auto;
        }
        
        .dialog-body .form-row {
          display: flex;
          flex-direction: column;
          gap: 4px;
          margin-bottom: 12px;
        }
        
        .dialog-body .form-row label {
          font-size: 11px;
          color: #a1a1aa;
          font-weight: 500;
        }
        
        .dialog-body .form-row select,
        .dialog-body .form-row input {
          background: #09090b;
          border: 1px solid #27272a;
          border-radius: 4px;
          padding: 8px 10px;
          color: #e4e4e7;
          font-family: inherit;
          font-size: 12px;
        }
        
        .dialog-body .form-row select:focus,
        .dialog-body .form-row input:focus {
          outline: none;
          border-color: #3b82f6;
        }
        
        .tool-desc {
          padding: 8px 10px;
          background: #0c0c0d;
          border-radius: 4px;
          font-size: 11px;
          color: #a1a1aa;
          margin-bottom: 12px;
        }
        
        .tool-args {
          background: #0c0c0d;
          border-radius: 4px;
          padding: 10px;
        }
        
        .tool-args > label {
          font-size: 10px;
          color: #71717a;
          text-transform: uppercase;
          display: block;
          margin-bottom: 8px;
        }
        
        .arg-row {
          display: flex;
          align-items: center;
          gap: 8px;
          margin-bottom: 6px;
        }
        
        .arg-row .arg-name {
          font-size: 11px;
          color: #a1a1aa;
          min-width: 80px;
        }
        
        .arg-row .required {
          color: #ef4444;
          margin-left: 2px;
        }
        
        .arg-row input {
          flex: 1;
          background: #09090b;
          border: 1px solid #27272a;
          border-radius: 4px;
          padding: 6px 8px;
          color: #e4e4e7;
          font-family: inherit;
          font-size: 11px;
        }
        
        .arg-row input:focus {
          outline: none;
          border-color: #3b82f6;
        }
        
        .dialog-footer {
          display: flex;
          justify-content: flex-end;
          gap: 8px;
          padding: 12px 16px;
          border-top: 1px solid #27272a;
        }
        
        .cancel-btn {
          padding: 8px 16px;
          background: transparent;
          border: 1px solid #27272a;
          border-radius: 4px;
          color: #a1a1aa;
          font-size: 12px;
          cursor: pointer;
        }
        
        .cancel-btn:hover {
          background: #27272a;
          color: #e4e4e7;
        }
        
        .add-btn {
          padding: 8px 16px;
          background: #3b82f6;
          border: none;
          border-radius: 4px;
          color: white;
          font-size: 12px;
          cursor: pointer;
        }
        
        .add-btn:hover:not(:disabled) {
          background: #2563eb;
        }
        
        .add-btn:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }

        /* Empty State */
        .empty-state {
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          height: 200px;
          color: #71717a;
          gap: 8px;
        }
        
        /* Stats Bar */
        .stats-bar {
          display: flex;
          align-items: center;
          gap: 16px;
          padding: 4px 8px;
          background: #18181b;
        }
        
        .stats-bar-spacer {
          flex: 1;
        }
        
        .stats-bar-btn {
          display: flex;
          align-items: center;
          gap: 4px;
          padding: 4px 8px;
          background: #27272a;
          border: 1px solid #3f3f46;
          border-radius: 4px;
          color: #a1a1aa;
          font-size: 11px;
          cursor: pointer;
          transition: all 0.15s;
        }
        
        .stats-bar-btn:hover:not(:disabled) {
          background: #3f3f46;
          color: #e4e4e7;
        }
        
        .stats-bar-btn:disabled {
          opacity: 0.5;
          cursor: not-allowed;
          border-top: 1px solid #27272a;
          font-size: 10px;
          color: #71717a;
        }
        
        .stat-item {
          display: flex;
          align-items: center;
          gap: 4px;
        }
        
        .stat-value {
          color: #e4e4e7;
          font-weight: 600;
        }
        
        .token-stats {
          padding: 4px 10px;
        }
        
        .token-value {
          display: flex;
          gap: 8px;
          font-family: var(--font-mono);
        }
        
        .token-in {
          color: #34d399;
        }
        
        .token-out {
          color: #f472b6;
        }
        
        .token-total {
          color: #a78bfa;
          font-weight: 700;
        }
        
        /* Metrics Bottom Drawer */
        .metrics-toggle-button {
          position: fixed;
          bottom: 0;
          left: 50%;
          transform: translateX(-50%);
          background: #27272a;
          border: 1px solid #3f3f46;
          border-bottom: none;
          border-radius: 12px 12px 0 0;
          padding: 6px 16px;
          color: #a1a1aa;
          cursor: pointer;
          display: flex;
          align-items: center;
          gap: 6px;
          font-size: 11px;
          font-weight: 500;
          z-index: 1001;
          transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
          box-shadow: 0 -2px 10px rgba(0, 0, 0, 0.2);
        }
        
        .metrics-toggle-button:hover {
          background: #3f3f46;
          color: #e4e4e7;
        }
        
        .metrics-toggle-button.open {
          bottom: 140px;
          background: #22d3ee22;
          border-color: #22d3ee;
          color: #22d3ee;
        }
        
        .metrics-bottom-drawer {
          position: fixed;
          bottom: 0;
          left: 0;
          right: 0;
          height: 140px;
          background: linear-gradient(180deg, #1a1a1f 0%, #18181b 100%);
          border-top: 1px solid #3f3f46;
          border-radius: 20px 20px 0 0;
          transform: translateY(100%);
          transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1);
          z-index: 1000;
          box-shadow: 0 -4px 20px rgba(0, 0, 0, 0.4);
        }
        
        .metrics-bottom-drawer.open {
          transform: translateY(0);
        }
        
        .metrics-bottom-drawer .metrics-drawer-content {
          height: 100%;
          padding: 12px 20px;
          display: flex;
          align-items: center;
          justify-content: center;
        }
        
        .metrics-charts-row {
          display: flex;
          gap: 20px;
          width: 100%;
          height: 100%;
          max-width: 1400px;
        }
        
        .metrics-chart-container {
          flex: 1;
          min-width: 200px;
          max-width: 400px;
          display: flex;
          flex-direction: column;
          background: #27272a;
          border-radius: 12px;
          padding: 8px 12px;
          overflow: hidden;
        }
        
        .metrics-chart-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 4px;
        }
        
        .metrics-chart-label {
          font-size: 10px;
          font-weight: 600;
          color: #a1a1aa;
          text-transform: uppercase;
          letter-spacing: 0.05em;
        }
        
        .metrics-chart-value {
          font-size: 14px;
          font-weight: 700;
          font-family: 'SF Mono', 'Consolas', monospace;
        }
        
        .metrics-error {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 16px;
          background: #450a0a;
          border: 1px solid #dc2626;
          border-radius: 6px;
          color: #fca5a5;
          font-size: 12px;
        }
        
        .metrics-loading {
          display: flex;
          align-items: center;
          gap: 8px;
          color: #71717a;
          font-size: 12px;
        }
        
        .metrics-notice {
          font-size: 11px;
          color: #71717a;
          padding: 12px 16px;
          background: #27272a;
          border-radius: 8px;
        }
        
        .metrics-notice code {
          background: #3f3f46;
          padding: 1px 4px;
          border-radius: 3px;
          color: #22d3ee;
        }
        
        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
        
        .spin {
          animation: spin 1s linear infinite;
        }
      `}</style>
      
      {/* Agent Network Graph */}
      <AgentGraph 
        agents={project.agents}
        events={runEvents}
        selectedEventIndex={selectedEventIndex}
        isOpen={isAgentGraphOpen}
        onOpenChange={setIsAgentGraphOpen}
        runState={agentGraphRunState}
      />
      
      {/* Input Area */}
      <div className="input-area">
        <select
          className="agent-selector"
          value={selectedAgentIdLocal || ''}
          onChange={e => setSelectedAgentIdLocal(e.target.value || null)}
          disabled={isRunning}
          title="Select which agent to run"
        >
          <option value="">
            {project.app.root_agent_id 
              ? `Root: ${project.agents.find(a => a.id === project.app.root_agent_id)?.name || project.app.root_agent_id}`
              : 'No root agent'}
          </option>
          {project.agents.filter(a => a.id !== project.app.root_agent_id).map(agent => (
            <option key={agent.id} value={agent.id}>
              {agent.name} ({agent.type.replace('Agent', '')})
            </option>
          ))}
        </select>
        <select
          className="agent-selector"
          value={selectedSessionId || ''}
          onChange={e => handleSessionSelect(e.target.value || null)}
          disabled={isRunning || loadingSessions}
          style={{ minWidth: 180 }}
          title="Load a saved session"
        >
          <option value="">{loadingSessions ? 'Loading...' : 'Load Session...'}</option>
          {availableSessions.map(session => {
            const date = new Date(session.started_at * 1000);
            const duration = session.duration ? `${session.duration.toFixed(1)}s` : '?';
            return (
              <option key={session.id} value={session.id}>
                {date.toLocaleString()} ({session.event_count} events, {duration})
              </option>
            );
          })}
        </select>
        <div style={{ position: 'relative', flex: 1, display: 'flex' }}>
          <input
            ref={inputRef}
            type="text"
            placeholder="Enter your query..."
            value={userInput}
            onChange={e => setUserInput(e.target.value)}
            onFocus={() => setShowSuggestions(true)}
            onBlur={() => setTimeout(() => setShowSuggestions(false), 150)}
            onKeyDown={e => {
              if (e.key === 'Enter' && !e.shiftKey) {
                handleRun();
              } else if (e.key === 'Escape') {
                setShowSuggestions(false);
              }
            }}
            disabled={isRunning}
            style={{ flex: 1 }}
          />
          {showSuggestions && filteredSuggestions.length > 0 && (
            <div style={{
              position: 'absolute',
              top: '100%',
              left: 0,
              right: 0,
              background: '#18181b',
              border: '1px solid #3f3f46',
              borderRadius: '6px',
              marginTop: '4px',
              maxHeight: '240px',
              overflowY: 'auto',
              zIndex: 100,
              boxShadow: '0 4px 12px rgba(0,0,0,0.4)',
            }}>
              {filteredSuggestions.map((item, idx) => (
                <div
                  key={idx}
                  style={{
                    padding: '8px 12px',
                    fontSize: '12px',
                    color: '#e4e4e7',
                    cursor: 'pointer',
                    borderBottom: idx < filteredSuggestions.length - 1 ? '1px solid #27272a' : 'none',
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                  }}
                  onMouseDown={(e) => {
                    e.preventDefault();
                    handleRun(item.prompt);
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.background = '#27272a';
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.background = 'transparent';
                  }}
                >
                  <span style={{ 
                    overflow: 'hidden', 
                    textOverflow: 'ellipsis', 
                    whiteSpace: 'nowrap',
                    flex: 1,
                    marginRight: '8px',
                  }}>
                    {item.prompt}
                  </span>
                  <span style={{ 
                    fontSize: '10px', 
                    color: '#71717a',
                    flexShrink: 0,
                  }}>
                    ×{item.count}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
        {isRunning ? (
          <button className="stop" onClick={handleStop}>
            <Square size={14} />
            Stop
          </button>
        ) : (
          <button onClick={() => handleRun()} disabled={!userInput.trim()}>
            <Play size={14} />
            Run
          </button>
        )}
        
        {/* Sandbox mode toggle */}
        <label 
          style={{ 
            display: 'flex', 
            alignItems: 'center', 
            gap: '4px', 
            marginLeft: '12px',
            fontSize: '11px',
            color: sandboxMode ? '#22d3ee' : '#71717a',
            cursor: 'pointer',
          }}
          title="Run in isolated Docker container"
        >
          <input
            type="checkbox"
            checked={sandboxMode}
            onChange={(e) => setSandboxMode(e.target.checked)}
            disabled={isRunning}
            style={{ accentColor: '#22d3ee' }}
          />
          🐳 Sandbox
        </label>
        
        {/* View container logs button */}
        {sandboxMode && (
          <button
            onClick={openLogsModal}
            style={{
              background: 'transparent',
              border: '1px solid #3f3f46',
              borderRadius: '4px',
              padding: '2px 8px',
              marginLeft: '8px',
              fontSize: '11px',
              color: '#a1a1aa',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '4px',
            }}
            title="View container logs"
          >
            📋 Logs
          </button>
        )}
        
      </div>
      
      {/* Toolbar */}
      <div className="toolbar">
        <div className="toolbar-section">
          <Search size={12} style={{ color: '#71717a' }} />
          <input
            type="text"
            placeholder="Filter events..."
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
          />
        </div>
        
        <div className="toolbar-divider" />
        
        <div className="toolbar-section">
          {['agent_start', 'agent_end', 'tool_call', 'tool_result', 'model_call', 'model_response', 'state_change', 'callback_error'].map(type => (
            <button
              key={type}
              className={`filter-chip ${eventTypeFilter.has(type) ? 'active' : ''}`}
              onClick={() => {
                const next = new Set(eventTypeFilter);
                if (next.has(type)) next.delete(type);
                else next.add(type);
                setEventTypeFilter(next);
              }}
            >
              {type.replace('_', ' ')}
            </button>
          ))}
          <button
            className={`filter-chip ${eventTypeFilter.has('callback_start') && eventTypeFilter.has('callback_end') ? 'active' : ''}`}
            onClick={() => {
              const next = new Set(eventTypeFilter);
              const hasCallbacks = next.has('callback_start') && next.has('callback_end');
              if (hasCallbacks) {
                next.delete('callback_start');
                next.delete('callback_end');
              } else {
                next.add('callback_start');
                next.add('callback_end');
              }
              setEventTypeFilter(next);
            }}
            title="Show/hide callback events"
          >
            callback
          </button>
          <button
            className={`filter-chip ${hideCompleteResponses ? 'active' : ''}`}
            onClick={() => setHideCompleteResponses(!hideCompleteResponses)}
            title="Hide LLM_RESP (complete) events"
          >
            hide (complete)
          </button>
        </div>
        
        <div className="toolbar-divider" />
        
        <div className="toolbar-section">
          <button
            className={`toolbar-btn ${showStatePanel ? 'active' : ''}`}
            onClick={() => { setShowStatePanel(!showStatePanel); setShowToolRunner(false); setShowArtifactsPanel(false); }}
          >
            <Database size={12} />
            State
          </button>
          <button
            className={`toolbar-btn ${showArtifactsPanel ? 'active' : ''}`}
            onClick={() => { setShowArtifactsPanel(!showArtifactsPanel); setShowStatePanel(false); setShowToolRunner(false); }}
          >
            <FileBox size={12} />
            Artifacts
          </button>
          <button
            className={`toolbar-btn ${showToolRunner ? 'active' : ''}`}
            onClick={() => { setShowToolRunner(!showToolRunner); setShowStatePanel(false); setShowArtifactsPanel(false); }}
          >
            <Terminal size={12} />
            Tools
          </button>
        </div>
        
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 10, color: '#71717a' }}>{filteredEvents.length} / {runEvents.length} events</span>
          {timeRange && (
            <button 
              className="toolbar-btn"
              onClick={() => setTimeRange(null)}
            >
              Clear Range
            </button>
          )}
        </div>
      </div>
      
      {/* Main Content */}
      <div className="main-content" ref={containerRef}>
        {/* Event List */}
        <div className="event-list-container">
          <div className="event-list-header" style={{ gridTemplateColumns }}>
            <div className="header-cell">
              <span>#</span>
              <div 
                className={`column-resize-handle ${resizingColumn === 0 ? 'active' : ''}`}
                onMouseDown={(e) => handleColumnResizeStart(0, e)}
              />
            </div>
            <div className="header-cell">
              <span>Time</span>
              <div 
                className={`column-resize-handle ${resizingColumn === 1 ? 'active' : ''}`}
                onMouseDown={(e) => handleColumnResizeStart(1, e)}
              />
            </div>
            <div className="header-cell">
              <span>Agent</span>
              <div 
                className={`column-resize-handle ${resizingColumn === 2 ? 'active' : ''}`}
                onMouseDown={(e) => handleColumnResizeStart(2, e)}
              />
            </div>
            <div className="header-cell">
              <span>Type</span>
              <div 
                className={`column-resize-handle ${resizingColumn === 3 ? 'active' : ''}`}
                onMouseDown={(e) => handleColumnResizeStart(3, e)}
              />
            </div>
            <div className="header-cell">
              <span>Info</span>
            </div>
          </div>
          
          <div className="event-list" ref={eventListRef}>
            {filteredEvents.length === 0 ? (
              <div className="empty-state">
                <Layers size={24} />
                <span>{runEvents.length === 0 ? 'No events yet' : 'No matching events'}</span>
              </div>
            ) : (
              filteredEvents.map((event, i) => {
                const globalIndex = runEvents.indexOf(event);
                const colors = EVENT_COLORS[event.event_type] || EVENT_COLORS.error;
                const Icon = EVENT_ICONS[event.event_type] || MessageSquare;
                
                return (
                  <div
                    key={globalIndex}
                    className={`event-row ${selectedEventIndex === globalIndex ? 'selected' : ''}`}
                    style={{ background: colors.bg, gridTemplateColumns }}
                    onClick={() => setSelectedEventIndex(globalIndex)}
                    onDoubleClick={() => {
                      // Switch to Details tab
                      setShowStatePanel(false);
                      setShowToolRunner(false);
                      setShowArtifactsPanel(false);
                    }}
                  >
                    <div className="index">{globalIndex}</div>
                    <div className="time" style={{ color: colors.fg }}>
                      {formatTimestamp(event.timestamp, timeBounds.min)}
                    </div>
                    <div className="agent">
                      <span 
                        className="agent-badge"
                        style={{ 
                          backgroundColor: getAgentColor(event.agent_name).bg,
                          color: getAgentColor(event.agent_name).fg,
                        }}
                      >
                        {event.agent_name}
                      </span>
                    </div>
                    <div className="type" style={{ color: colors.fg }}>
                      <Icon size={10} />
                      {event.event_type.split('_')[0]}
                    </div>
                    <div className="summary">{getEventSummary(event)}</div>
                  </div>
                );
              })
            )}
          </div>
        </div>
        
        {/* Side Panel with Resize Handle */}
        <div className="side-panel-container" style={{ width: sidebarWidth }}>
          <div 
            className={`resize-handle ${isResizing ? 'active' : ''}`}
            onMouseDown={() => setIsResizing(true)}
          />
          <div className="side-panel" style={{ width: sidebarWidth - 4 }}>
          <div className="side-panel-tabs">
            <button 
              className={`side-panel-tab ${!showStatePanel && !showToolRunner && !showArtifactsPanel ? 'active' : ''}`}
              onClick={() => { setShowStatePanel(false); setShowToolRunner(false); setShowArtifactsPanel(false); }}
            >
              <Eye size={12} style={{ marginRight: 4 }} />
              Details
            </button>
            <button 
              className={`side-panel-tab ${showStatePanel ? 'active' : ''}`}
              onClick={() => { setShowStatePanel(true); setShowToolRunner(false); setShowArtifactsPanel(false); }}
            >
              <Database size={12} style={{ marginRight: 4 }} />
              State
            </button>
            <button 
              className={`side-panel-tab ${showArtifactsPanel ? 'active' : ''}`}
              onClick={() => { setShowArtifactsPanel(true); setShowStatePanel(false); setShowToolRunner(false); }}
            >
              <FileBox size={12} style={{ marginRight: 4 }} />
              Artifacts
            </button>
            <button 
              className={`side-panel-tab ${showToolRunner ? 'active' : ''}`}
              onClick={() => { setShowToolRunner(true); setShowStatePanel(false); setShowArtifactsPanel(false); }}
            >
              <Terminal size={12} style={{ marginRight: 4 }} />
              Tools
            </button>
          </div>
          
          <div className="side-panel-content">
            {showToolRunner ? (
              <ToolWatchPanel project={project} selectedEventIndex={selectedEventIndex} sandboxMode={sandboxMode} />
            ) : showArtifactsPanel ? (
              <ArtifactsPanel project={project} sessionId={currentSessionId} />
            ) : showStatePanel ? (
              <StateSnapshot 
                events={runEvents} 
                selectedEventIndex={selectedEventIndex}
                project={project}
              />
            ) : selectedEvent ? (
              <EventDetail event={selectedEvent} />
            ) : (
              <div className="empty-state">
                <Eye size={24} />
                <span>Select an event to view details</span>
              </div>
            )}
          </div>
        </div>
        </div>
      </div>
      
      {/* Stats Bar */}
      <div className="stats-bar">
        <div className="stat-item">
          <span>Events:</span>
          <span className="stat-value">{runEvents.length}</span>
        </div>
        <div className="stat-item">
          <span>Tool Calls:</span>
          <span className="stat-value">{runEvents.filter(e => e.event_type === 'tool_call').length}</span>
        </div>
        <div className="stat-item">
          <span>Model Calls:</span>
          <span className="stat-value">{runEvents.filter(e => e.event_type === 'model_call').length}</span>
        </div>
        <div className="stat-item">
          <span>Callbacks:</span>
          <span className="stat-value">{runEvents.filter(e => e.event_type === 'callback_start').length}</span>
        </div>
        <div className="stat-item">
          <span>State Changes:</span>
          <span className="stat-value">{runEvents.filter(e => e.event_type === 'state_change').length}</span>
        </div>
        {runEvents.length > 0 && (
          <div className="stat-item">
            <span>Duration:</span>
            <span className="stat-value">
              {((runEvents[runEvents.length - 1].timestamp - runEvents[0].timestamp) * 1000).toFixed(0)}ms
            </span>
          </div>
        )}
        {tokenCounts.total > 0 && (
          <div className="stat-item token-stats">
            <span className="stat-value token-value">
              <span className="token-in" title="Input tokens">{tokenCounts.input.toLocaleString()}↑</span>
              <span className="token-out" title="Output tokens">{tokenCounts.output.toLocaleString()}↓</span>
              <span className="token-total" title="Total tokens">{tokenCounts.total.toLocaleString()}</span>
            </span>
          </div>
        )}
        <div className="stats-bar-spacer" />
        <button 
          className="stats-bar-btn" 
          onClick={handleUploadRun}
          title="Load a saved run"
        >
          <Upload size={12} />
          Load
        </button>
        <button 
          className="stats-bar-btn" 
          onClick={handleDownloadRun}
          disabled={runEvents.length === 0}
          title="Save current run to file"
        >
          <Download size={12} />
          Save
        </button>
        <button 
          className="stats-bar-btn" 
          onClick={handleSaveToMemory}
          disabled={!currentSessionId || runEvents.length === 0}
          title="Save current session to memory"
        >
          <Database size={12} />
          Save to Memory
        </button>
        <button 
          className="stats-bar-btn" 
          onClick={handleCreateTestCase}
          disabled={!currentSessionId || runEvents.length === 0}
          title="Create evaluation test case from this session"
          style={{ background: 'rgba(var(--accent-primary-rgb), 0.15)' }}
        >
          <TestTube size={12} />
          Create Test Case
        </button>
      </div>
      
      {/* Test Case Creation Dialog */}
      {showTestCaseDialog && (
        <div 
          className="dialog-overlay"
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: 'rgba(0,0,0,0.5)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
          }}
          onClick={() => setShowTestCaseDialog(false)}
        >
          <div 
            className="dialog-content"
            style={{
              background: 'var(--bg-secondary)',
              borderRadius: 'var(--radius-md)',
              padding: 24,
              width: 400,
              maxWidth: '90vw',
              border: '1px solid var(--border-color)',
            }}
            onClick={e => e.stopPropagation()}
          >
            <h3 style={{ marginBottom: 16, display: 'flex', alignItems: 'center', gap: 8 }}>
              <TestTube size={18} />
              Create Test Case from Session
            </h3>
            
            <div style={{ marginBottom: 16 }}>
              <label style={{ display: 'block', marginBottom: 4, fontSize: 12, color: 'var(--text-muted)' }}>
                Test Case Name
              </label>
              <input
                type="text"
                value={testCaseName}
                onChange={(e) => setTestCaseName(e.target.value)}
                placeholder="Enter test case name"
                style={{
                  width: '100%',
                  padding: '8px 12px',
                  background: 'var(--bg-tertiary)',
                  border: '1px solid var(--border-color)',
                  borderRadius: 'var(--radius-sm)',
                  color: 'var(--text-primary)',
                }}
              />
            </div>
            
            <div style={{ marginBottom: 20 }}>
              <label style={{ display: 'block', marginBottom: 4, fontSize: 12, color: 'var(--text-muted)' }}>
                Add to Evaluation Set
              </label>
              <select
                value={selectedEvalSetId}
                onChange={(e) => setSelectedEvalSetId(e.target.value)}
                style={{
                  width: '100%',
                  padding: '8px 12px',
                  background: 'var(--bg-tertiary)',
                  border: '1px solid var(--border-color)',
                  borderRadius: 'var(--radius-sm)',
                  color: 'var(--text-primary)',
                }}
              >
                {testCaseEvalSets.map(es => (
                  <option key={es.id} value={es.id}>{es.name}</option>
                ))}
              </select>
            </div>
            
            <p style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 16 }}>
              This will extract user messages and tool calls from the current session
              to create a replayable test case. You can edit the expected responses
              and tool calls in the Evals tab after creation.
            </p>
            
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button 
                className="btn btn-secondary"
                onClick={() => setShowTestCaseDialog(false)}
              >
                Cancel
              </button>
              <button 
                className="btn btn-primary"
                onClick={handleConfirmCreateTestCase}
                disabled={creatingTestCase || !selectedEvalSetId}
              >
                {creatingTestCase ? 'Creating...' : 'Create Test Case'}
              </button>
            </div>
          </div>
        </div>
      )}
      
      {/* Network Approval Dialog for sandbox mode */}
      {pendingApproval && (
        <NetworkApprovalDialog
          request={pendingApproval}
          timeout={pendingApproval.timeout || 30}
          onApprove={handleApprove}
          onDeny={handleDeny}
          onClose={() => setPendingApproval(null)}
        />
      )}
      
      {/* Container Logs Modal */}
      {showLogsModal && (
        <div 
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            backgroundColor: 'rgba(0, 0, 0, 0.7)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
          }}
          onClick={() => setShowLogsModal(false)}
        >
          <div
            style={{
              backgroundColor: '#18181b',
              borderRadius: '8px',
              border: '1px solid #3f3f46',
              width: '90%',
              maxWidth: '1400px',
              height: '80%',
              display: 'flex',
              flexDirection: 'column',
              overflow: 'hidden',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            {/* Header */}
            <div style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              padding: '12px 16px',
              borderBottom: '1px solid #3f3f46',
              backgroundColor: '#27272a',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Terminal size={16} />
                <span style={{ fontWeight: 600 }}>Container Logs</span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <button
                  onClick={fetchContainerLogs}
                  disabled={logsLoading}
                  style={{
                    background: '#3f3f46',
                    border: 'none',
                    borderRadius: '4px',
                    padding: '4px 8px',
                    color: '#e4e4e7',
                    cursor: logsLoading ? 'wait' : 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '4px',
                    fontSize: '12px',
                  }}
                >
                  <RefreshCw size={12} className={logsLoading ? 'animate-spin' : ''} />
                  Refresh
                </button>
                <button
                  onClick={() => setShowLogsModal(false)}
                  style={{
                    background: 'transparent',
                    border: 'none',
                    color: '#71717a',
                    cursor: 'pointer',
                    padding: '4px',
                  }}
                >
                  <X size={16} />
                </button>
              </div>
            </div>
            
            {/* Tabs */}
            <div style={{
              display: 'flex',
              gap: '0',
              borderBottom: '1px solid #3f3f46',
              backgroundColor: '#27272a',
            }}>
              <button
                onClick={() => setLogsTab('agent')}
                style={{
                  padding: '8px 16px',
                  background: logsTab === 'agent' ? '#18181b' : 'transparent',
                  border: 'none',
                  borderBottom: logsTab === 'agent' ? '2px solid #22d3ee' : '2px solid transparent',
                  color: logsTab === 'agent' ? '#22d3ee' : '#a1a1aa',
                  cursor: 'pointer',
                  fontSize: '13px',
                }}
              >
                🤖 Agent
              </button>
              <button
                onClick={() => setLogsTab('gateway')}
                style={{
                  padding: '8px 16px',
                  background: logsTab === 'gateway' ? '#18181b' : 'transparent',
                  border: 'none',
                  borderBottom: logsTab === 'gateway' ? '2px solid #22d3ee' : '2px solid transparent',
                  color: logsTab === 'gateway' ? '#22d3ee' : '#a1a1aa',
                  cursor: 'pointer',
                  fontSize: '13px',
                }}
              >
                🌐 Gateway
              </button>
            </div>
            
            {/* Log content */}
            <div 
              ref={logsContainerRef}
              onScroll={handleLogsScroll}
              style={{
                flex: 1,
                overflow: 'auto',
                padding: '12px',
                fontFamily: 'ui-monospace, monospace',
                fontSize: '11px',
                lineHeight: '1.5',
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-all',
                color: '#d4d4d8',
                backgroundColor: '#09090b',
              }}
            >
              {logsLoading ? (
                <div style={{ color: '#71717a', textAlign: 'center', padding: '20px' }}>
                  Loading logs...
                </div>
              ) : containerLogs[logsTab] ? (
                <HighlightedLogs content={containerLogs[logsTab]!} />
              ) : (
                <div style={{ color: '#71717a' }}>No logs available</div>
              )}
            </div>
          </div>
        </div>
      )}
      
      {/* System Metrics Bottom Drawer */}
      {hasLocalModel && (
        <>
          {/* Metrics Toggle Button */}
          <button
            className={`metrics-toggle-button ${isMetricsDrawerOpen ? 'open' : ''}`}
            onClick={() => setIsMetricsDrawerOpen(!isMetricsDrawerOpen)}
            title="Toggle system metrics"
          >
            <Activity size={14} />
            <ChevronDown 
              size={14} 
              style={{ 
                transform: isMetricsDrawerOpen ? 'rotate(0deg)' : 'rotate(180deg)',
                transition: 'transform 0.3s ease'
              }} 
            />
          </button>
          
          {/* Bottom Drawer */}
          <div className={`metrics-bottom-drawer ${isMetricsDrawerOpen ? 'open' : ''}`}>
            <div className="metrics-drawer-content">
              {metricsError ? (
                <div className="metrics-error">
                  <AlertTriangle size={16} />
                  <span>{metricsError}</span>
                </div>
              ) : !systemMetrics ? (
                <div className="metrics-loading">
                  <RefreshCw size={16} className="spin" />
                  <span>Loading metrics...</span>
                </div>
              ) : !systemMetrics.available.psutil ? (
                <div className="metrics-notice" style={{ margin: 'auto' }}>
                  Install <code>psutil</code> for system metrics
                </div>
              ) : (
                <div className="metrics-charts-row">
                  {/* CPU Stats Chart (min/avg/max) */}
                  <CpuStatsTimeSeriesChart
                    data={metricsHistory.map(m => ({ timestamp: m.timestamp, cores: m.cpuCores }))}
                  />
                  
                  {/* Memory Chart */}
                  <MetricsTimeSeriesChart
                    data={metricsHistory.map(m => ({ timestamp: m.timestamp, value: m.memory }))}
                    color="#a78bfa"
                    label="Memory"
                    currentValue={systemMetrics.memory.percent || 0}
                  />
                  
                  {/* GPU Chart (if available) */}
                  {systemMetrics.available.gpu && systemMetrics.gpu[0]?.utilization_percent !== undefined && (
                    <MetricsTimeSeriesChart
                      data={metricsHistory.filter(m => m.gpu !== undefined).map(m => ({ timestamp: m.timestamp, value: m.gpu! }))}
                      color="#fb923c"
                      label={`GPU${systemMetrics.gpu[0]?.name ? ` (${systemMetrics.gpu[0].name.slice(0, 20)})` : ''}`}
                      currentValue={systemMetrics.gpu[0]?.utilization_percent || 0}
                    />
                  )}
                  
                  {/* GPU Memory Chart (if available) */}
                  {systemMetrics.available.gpu && systemMetrics.gpu[0]?.memory_percent !== undefined && (
                    <MetricsTimeSeriesChart
                      data={metricsHistory.filter(m => m.gpuMemory !== undefined).map(m => ({ timestamp: m.timestamp, value: m.gpuMemory! }))}
                      color="#f472b6"
                      label="GPU VRAM"
                      currentValue={systemMetrics.gpu[0]?.memory_percent || 0}
                    />
                  )}
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}


