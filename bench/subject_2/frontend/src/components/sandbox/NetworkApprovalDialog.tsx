/**
 * Network Approval Dialog for the Docker sandbox.
 * 
 * Shows when an unknown domain is requested, allowing the user to:
 * - Deny the request
 * - Allow once
 * - Allow with a pattern (and optionally persist)
 */

import { useState, useEffect, useCallback } from 'react';
import { 
  AlertTriangle, X, Shield, Check, Ban, 
  ChevronDown, Clock
} from 'lucide-react';
import type { ApprovalRequest, PatternType } from '../../utils/types';

interface NetworkApprovalDialogProps {
  request: ApprovalRequest;
  timeout: number;  // seconds
  onApprove: (pattern?: string, patternType?: PatternType, persist?: boolean) => void;
  onDeny: () => void;
  onClose: () => void;
}

// Generate pattern suggestions from URL
function getPatternSuggestions(url: string): Array<{ pattern: string; label: string }> {
  try {
    const parsed = new URL(url);
    const host = parsed.host;
    const path = parsed.pathname;
    
    const suggestions = [
      { pattern: host, label: `${host} (exact domain)` },
      { pattern: `${host}/*`, label: `${host}/* (domain + any path)` },
    ];
    
    // Add subdomain wildcard if applicable
    const parts = host.split('.');
    if (parts.length > 2) {
      const baseDomain = parts.slice(-2).join('.');
      suggestions.push({ 
        pattern: `*.${baseDomain}`, 
        label: `*.${baseDomain} (all subdomains)` 
      });
    }
    
    // Add path-specific pattern
    if (path && path !== '/') {
      const pathParts = path.split('/').filter(Boolean);
      if (pathParts.length > 0) {
        suggestions.push({
          pattern: `${host}/${pathParts[0]}/*`,
          label: `${host}/${pathParts[0]}/* (specific path)`,
        });
      }
    }
    
    return suggestions;
  } catch {
    return [{ pattern: url, label: url }];
  }
}

// Styles
const styles = {
  overlay: {
    position: 'fixed' as const,
    inset: 0,
    backgroundColor: 'rgba(0, 0, 0, 0.85)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    zIndex: 9999,
  },
  dialog: {
    backgroundColor: '#12121a',
    border: '1px solid rgba(245, 158, 11, 0.5)',
    borderRadius: 8,
    boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.5)',
    width: 500,
    maxWidth: '90vw',
    overflow: 'hidden',
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    padding: 12,
    borderBottom: '1px solid #374151',
    backgroundColor: 'rgba(120, 53, 15, 0.2)',
  },
  headerIcon: {
    color: '#fbbf24',
  },
  headerTitle: {
    fontWeight: 600,
    color: '#fcd34d',
    fontSize: 14,
  },
  closeButton: {
    marginLeft: 'auto',
    background: 'none',
    border: 'none',
    color: '#6b7280',
    cursor: 'pointer',
    padding: 4,
    display: 'flex',
    alignItems: 'center',
  },
  content: {
    padding: 16,
    display: 'flex',
    flexDirection: 'column' as const,
    gap: 16,
  },
  sourceText: {
    fontSize: 13,
    color: '#9ca3af',
  },
  requestBox: {
    backgroundColor: '#0a0a0f',
    borderRadius: 6,
    border: '1px solid #374151',
    padding: 12,
    fontFamily: "'SF Mono', 'Consolas', monospace",
    fontSize: 13,
  },
  methodBadge: (method: string) => ({
    fontWeight: 700,
    color: method === 'POST' ? '#4ade80' : method === 'GET' ? '#60a5fa' : '#9ca3af',
    marginRight: 8,
  }),
  urlText: {
    color: '#d1d5db',
    wordBreak: 'break-all' as const,
  },
  headersText: {
    marginTop: 8,
    fontSize: 11,
    color: '#6b7280',
  },
  label: {
    fontSize: 13,
    color: '#9ca3af',
    marginBottom: 6,
  },
  select: {
    width: '100%',
    padding: '10px 12px',
    backgroundColor: '#1a1a24',
    border: '1px solid #4b5563',
    borderRadius: 6,
    fontSize: 13,
    color: '#e5e7eb',
    cursor: 'pointer',
    appearance: 'none' as const,
    backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%236b7280' stroke-width='2'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E")`,
    backgroundRepeat: 'no-repeat',
    backgroundPosition: 'right 12px center',
    paddingRight: 36,
  },
  customInput: {
    width: '100%',
    padding: '10px 12px',
    backgroundColor: '#1a1a24',
    border: '1px solid #4b5563',
    borderRadius: 6,
    fontSize: 13,
    color: '#e5e7eb',
    fontFamily: "'SF Mono', 'Consolas', monospace",
  },
  radioGroup: {
    display: 'flex',
    gap: 16,
    marginTop: 8,
  },
  radioLabel: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
    fontSize: 12,
    color: '#9ca3af',
    cursor: 'pointer',
  },
  backLink: {
    marginLeft: 'auto',
    fontSize: 12,
    color: '#6b7280',
    background: 'none',
    border: 'none',
    cursor: 'pointer',
  },
  checkboxLabel: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    fontSize: 13,
    color: '#9ca3af',
    cursor: 'pointer',
  },
  footer: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    padding: 12,
    borderTop: '1px solid #374151',
    backgroundColor: '#0a0a0f',
  },
  button: (variant: 'deny' | 'once' | 'pattern') => {
    const baseStyle = {
      display: 'flex',
      alignItems: 'center',
      gap: 6,
      padding: '8px 16px',
      borderRadius: 6,
      fontSize: 13,
      fontWeight: 500,
      cursor: 'pointer',
      border: '1px solid',
      transition: 'all 0.15s ease',
    };
    
    switch (variant) {
      case 'deny':
        return {
          ...baseStyle,
          backgroundColor: 'rgba(220, 38, 38, 0.2)',
          borderColor: 'rgba(239, 68, 68, 0.5)',
          color: '#f87171',
        };
      case 'once':
        return {
          ...baseStyle,
          backgroundColor: 'rgba(75, 85, 99, 0.2)',
          borderColor: 'rgba(107, 114, 128, 0.5)',
          color: '#d1d5db',
        };
      case 'pattern':
        return {
          ...baseStyle,
          backgroundColor: 'rgba(22, 163, 74, 0.2)',
          borderColor: 'rgba(34, 197, 94, 0.5)',
          color: '#4ade80',
        };
    }
  },
  timerContainer: {
    marginLeft: 'auto',
    display: 'flex',
    alignItems: 'center',
    gap: 6,
    color: '#6b7280',
    fontSize: 13,
  },
  progressBar: {
    height: 3,
    backgroundColor: '#1f2937',
  },
  progressFill: (progress: number) => ({
    height: '100%',
    backgroundColor: '#f59e0b',
    transition: 'width 1s linear',
    width: `${progress}%`,
  }),
};

export function NetworkApprovalDialog({
  request,
  timeout,
  onApprove,
  onDeny,
  onClose,
}: NetworkApprovalDialogProps) {
  const [selectedPattern, setSelectedPattern] = useState('');
  const [patternType, setPatternType] = useState<PatternType>('exact');
  const [persist, setPersist] = useState(false);
  const [customPattern, setCustomPattern] = useState('');
  const [showCustom, setShowCustom] = useState(false);
  const [timeLeft, setTimeLeft] = useState(timeout);
  
  const suggestions = getPatternSuggestions(request.url);
  
  // Initialize with first suggestion
  useEffect(() => {
    if (suggestions.length > 0 && !selectedPattern) {
      setSelectedPattern(suggestions[0].pattern);
    }
  }, [suggestions, selectedPattern]);
  
  // Countdown timer
  useEffect(() => {
    const interval = setInterval(() => {
      setTimeLeft((prev) => {
        if (prev <= 1) {
          onDeny();
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
    
    return () => clearInterval(interval);
  }, [onDeny]);
  
  const handleApproveOnce = useCallback(() => {
    onApprove();
  }, [onApprove]);
  
  const handleApprovePattern = useCallback(() => {
    const pattern = showCustom ? customPattern : selectedPattern;
    onApprove(pattern, patternType, persist);
  }, [onApprove, showCustom, customPattern, selectedPattern, patternType, persist]);
  
  // Progress bar percentage
  const progress = (timeLeft / timeout) * 100;
  
  // Parse source info
  const isMCP = request.source.startsWith('mcp:');
  const sourceName = isMCP ? request.source.substring(4) : 'agent';
  
  return (
    <div style={styles.overlay}>
      <div style={styles.dialog}>
        {/* Header */}
        <div style={styles.header}>
          <AlertTriangle size={18} style={styles.headerIcon} />
          <span style={styles.headerTitle}>Network Request Approval</span>
          <button style={styles.closeButton} onClick={onClose}>
            <X size={16} />
          </button>
        </div>
        
        {/* Content */}
        <div style={styles.content}>
          {/* Source info */}
          <div style={styles.sourceText}>
            {isMCP ? (
              <>MCP server "<span style={{ color: '#22d3ee' }}>{sourceName}</span>" wants to connect to:</>
            ) : (
              <>Agent wants to connect to:</>
            )}
          </div>
          
          {/* Request details */}
          <div style={styles.requestBox}>
            <div>
              <span style={styles.methodBadge(request.method)}>
                {request.method}
              </span>
              <span style={styles.urlText}>{request.url}</span>
            </div>
            {request.headers && Object.keys(request.headers).length > 0 && (
              <div style={styles.headersText}>
                Headers: {Object.keys(request.headers).join(', ')}
              </div>
            )}
          </div>
          
          {/* Pattern selector */}
          <div>
            <div style={styles.label}>Allow pattern:</div>
            
            {!showCustom ? (
              <select
                value={selectedPattern}
                onChange={(e) => {
                  if (e.target.value === '__custom__') {
                    setShowCustom(true);
                    setCustomPattern(selectedPattern);
                  } else {
                    setSelectedPattern(e.target.value);
                  }
                }}
                style={styles.select}
              >
                {suggestions.map((s) => (
                  <option key={s.pattern} value={s.pattern}>{s.label}</option>
                ))}
                <option value="__custom__">Custom pattern...</option>
              </select>
            ) : (
              <div>
                <input
                  type="text"
                  value={customPattern}
                  onChange={(e) => setCustomPattern(e.target.value)}
                  placeholder="e.g., *.example.com/*"
                  style={styles.customInput}
                />
                <div style={styles.radioGroup}>
                  <label style={styles.radioLabel}>
                    <input
                      type="radio"
                      checked={patternType === 'wildcard'}
                      onChange={() => setPatternType('wildcard')}
                    />
                    Wildcard
                  </label>
                  <label style={styles.radioLabel}>
                    <input
                      type="radio"
                      checked={patternType === 'regex'}
                      onChange={() => setPatternType('regex')}
                    />
                    Regex
                  </label>
                  <button
                    onClick={() => setShowCustom(false)}
                    style={styles.backLink}
                  >
                    ← Back to suggestions
                  </button>
                </div>
              </div>
            )}
          </div>
          
          {/* Persist toggle */}
          <label style={styles.checkboxLabel}>
            <span className="toggle-switch">
              <input
                type="checkbox"
                checked={persist}
                onChange={(e) => setPersist(e.target.checked)}
              />
              <span className="toggle-slider" />
            </span>
            Save to project (persists across sessions)
          </label>
        </div>
        
        {/* Actions */}
        <div style={styles.footer}>
          <button onClick={onDeny} style={styles.button('deny')}>
            <Ban size={14} />
            Deny
          </button>
          <button onClick={handleApproveOnce} style={styles.button('once')}>
            <Check size={14} />
            Allow Once
          </button>
          <button onClick={handleApprovePattern} style={styles.button('pattern')}>
            <Shield size={14} />
            Allow Pattern
          </button>
          
          <div style={styles.timerContainer}>
            <Clock size={14} />
            <span>{timeLeft}s</span>
          </div>
        </div>
        
        {/* Progress bar */}
        <div style={styles.progressBar}>
          <div style={styles.progressFill(progress)} />
        </div>
      </div>
    </div>
  );
}
