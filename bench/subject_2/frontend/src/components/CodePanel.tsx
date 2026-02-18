import { useState, useEffect } from 'react';
import { Copy, Download, Check, Code, AlertCircle } from 'lucide-react';
import { useStore } from '../hooks/useStore';
import Editor from '@monaco-editor/react';

export default function CodePanel() {
  const { project } = useStore();
  const [copied, setCopied] = useState(false);
  const [pythonCode, setPythonCode] = useState<string>('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  
  // Fetch the generated code from the backend (single source of truth)
  useEffect(() => {
    if (!project) return;
    
    setLoading(true);
    setError(null);
    
    fetch(`/api/projects/${project.id}/code`)
      .then(res => {
        if (!res.ok) throw new Error('Failed to fetch code');
        return res.json();
      })
      .then(data => {
        // Clean up the code for display:
        // 1. Remove the _wrap_callback instrumentation block
        // 2. Simplify _wrap_callback(..., fn) calls to just fn
        let code = data.code || '';
        
        // Remove the instrumentation block (from marker to marker)
        code = code.replace(/\n# --- Callback instrumentation \(for event tracking\) ---[\s\S]*?# --- End callback instrumentation ---\n/g, '');
        
        // Simplify _wrap_callback("name", "type", fn) to just fn
        code = code.replace(/_wrap_callback\("[^"]+",\s*"[^"]+",\s*(\w+)\)/g, '$1');
        
        setPythonCode(code);
        setLoading(false);
      })
      .catch(err => {
        setError(err.message);
        setLoading(false);
        setPythonCode('# Failed to generate code. Please check the backend logs.');
      });
  }, [project]);
  
  if (!project) return null;
  
  function handleCopy() {
    navigator.clipboard.writeText(pythonCode);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }
  
  function handleDownload() {
    if (!project) return;
    const blob = new Blob([pythonCode], { type: 'text/x-python' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${project.name}_agent.py`;
    a.click();
    URL.revokeObjectURL(url);
  }
  
  return (
    <div className="code-panel">
      <style>{`
        .code-panel {
          display: flex;
          flex-direction: column;
          height: calc(100vh - 180px);
          background: var(--bg-secondary);
          border: 1px solid var(--border-color);
          border-radius: var(--radius-lg);
          overflow: hidden;
        }
        
        .code-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 12px 16px;
          border-bottom: 1px solid var(--border-color);
        }
        
        .code-title {
          display: flex;
          align-items: center;
          gap: 8px;
        }
        
        .code-title h3 {
          font-size: 14px;
          font-weight: 600;
        }
        
        .code-title .badge {
          font-size: 11px;
          padding: 2px 6px;
          background: var(--bg-tertiary);
          border-radius: 4px;
          color: var(--text-muted);
        }
        
        .code-title .status-badge {
          display: flex;
          align-items: center;
          gap: 4px;
          font-size: 11px;
          padding: 2px 8px;
          border-radius: 4px;
        }
        
        .code-title .status-badge.success {
          background: rgba(34, 197, 94, 0.15);
          color: #22c55e;
        }
        
        .code-title .status-badge.error {
          background: rgba(239, 68, 68, 0.15);
          color: #ef4444;
        }
        
        .code-actions {
          display: flex;
          gap: 8px;
        }
        
        .code-editor {
          flex: 1;
          min-height: 0;
        }
        
        .code-info {
          padding: 12px 16px;
          border-top: 1px solid var(--border-color);
          background: var(--bg-tertiary);
          font-size: 12px;
          color: var(--text-muted);
        }
        
        .code-info p {
          margin-bottom: 8px;
        }
        
        .code-info code {
          background: var(--bg-secondary);
          padding: 2px 6px;
          border-radius: var(--radius-sm);
        }
        
        .code-loading, .code-error {
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          height: 100%;
          gap: 12px;
          color: #71717a;
        }
        
        .code-error {
          color: #ef4444;
        }
      `}</style>
      
      <div className="code-header">
        <div className="code-title">
          <Code size={16} />
          <h3>Python Code</h3>
          <span className="badge">{loading ? 'Loading...' : 'Generated'}</span>
          {copied && (
            <span className="status-badge success">
              <Check size={12} />
              Copied!
            </span>
          )}
          {error && (
            <span className="status-badge error">
              <AlertCircle size={12} />
              Error
            </span>
          )}
        </div>
        <div className="code-actions">
          <button className="btn btn-secondary btn-sm" onClick={handleCopy} title="Copy to clipboard" disabled={loading || !!error}>
            <Copy size={14} />
            Copy
          </button>
          <button className="btn btn-secondary btn-sm" onClick={handleDownload} title="Download Python file" disabled={loading || !!error}>
            <Download size={14} />
            Download
          </button>
        </div>
      </div>
      
      <div className="code-editor">
        {loading ? (
          <div className="code-loading">
            <div>Loading generated code...</div>
          </div>
        ) : error ? (
          <div className="code-error">
            <AlertCircle size={24} />
            <div>{error}</div>
          </div>
        ) : (
          <Editor
            height="100%"
            language="python"
            theme="vs-dark"
            value={pythonCode}
            options={{
              readOnly: true,
              minimap: { enabled: false },
              fontSize: 13,
              fontFamily: "'JetBrains Mono', monospace",
              lineNumbers: 'on',
              scrollBeyondLastLine: false,
              automaticLayout: true,
              tabSize: 4,
              insertSpaces: true,
              padding: { top: 12 },
              wordWrap: 'on',
            }}
          />
        )}
      </div>
      
      <div className="code-info">
        <p>
          This is the Python code equivalent of your project configuration. 
          You can use this code directly with ADK.
        </p>
        <p>
          Place this in a file named <code>agent.py</code> inside your agent directory, 
          then run with <code>adk web .</code> or <code>adk run your_agent</code>.
        </p>
      </div>
    </div>
  );
}
