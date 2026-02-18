import { useState, useEffect } from 'react';
import { Copy, Download, Upload, RefreshCw, Check, AlertCircle } from 'lucide-react';
import { useStore } from '../hooks/useStore';
import { getProjectYaml, updateProjectFromYaml } from '../utils/api';
import Editor from '@monaco-editor/react';

export default function YamlPanel() {
  const { project, setProject } = useStore();
  const [yaml, setYaml] = useState('');
  const [loading, setLoading] = useState(true);
  const [hasChanges, setHasChanges] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  
  if (!project) return null;
  
  useEffect(() => {
    loadYaml();
  }, [project.id]);
  
  async function loadYaml() {
    setLoading(true);
    setError(null);
    try {
      const content = await getProjectYaml(project.id);
      setYaml(content);
      setHasChanges(false);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }
  
  function handleYamlChange(value: string | undefined) {
    if (value !== undefined) {
      setYaml(value);
      setHasChanges(true);
      setError(null);
    }
  }
  
  async function handleApply() {
    setLoading(true);
    setError(null);
    try {
      const updated = await updateProjectFromYaml(project.id, yaml);
      setProject(updated);
      setHasChanges(false);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }
  
  function handleCopy() {
    navigator.clipboard.writeText(yaml);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }
  
  function handleDownload() {
    const blob = new Blob([yaml], { type: 'text/yaml' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${project.name}.yaml`;
    a.click();
    URL.revokeObjectURL(url);
  }
  
  function handleUpload() {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.yaml,.yml';
    input.onchange = async (e) => {
      const file = (e.target as HTMLInputElement).files?.[0];
      if (!file) return;
      
      const text = await file.text();
      setYaml(text);
      setHasChanges(true);
    };
    input.click();
  }
  
  return (
    <div className="yaml-panel">
      <style>{`
        .yaml-panel {
          display: flex;
          flex-direction: column;
          height: calc(100vh - 180px);
          background: var(--bg-secondary);
          border: 1px solid var(--border-color);
          border-radius: var(--radius-lg);
          overflow: hidden;
        }
        
        .yaml-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 12px 16px;
          border-bottom: 1px solid var(--border-color);
        }
        
        .yaml-title {
          display: flex;
          align-items: center;
          gap: 8px;
        }
        
        .yaml-title h3 {
          font-size: 14px;
          font-weight: 600;
        }
        
        .status-badge {
          display: flex;
          align-items: center;
          gap: 4px;
          padding: 4px 8px;
          font-size: 11px;
          border-radius: 999px;
        }
        
        .status-badge.warning {
          background: rgba(255, 217, 61, 0.15);
          color: var(--warning);
        }
        
        .status-badge.error {
          background: rgba(255, 107, 107, 0.15);
          color: var(--error);
        }
        
        .status-badge.success {
          background: rgba(0, 245, 212, 0.15);
          color: var(--success);
        }
        
        .yaml-actions {
          display: flex;
          gap: 8px;
        }
        
        .yaml-editor {
          flex: 1;
          min-height: 0;
        }
        
        .yaml-info {
          padding: 12px 16px;
          border-top: 1px solid var(--border-color);
          background: var(--bg-tertiary);
          font-size: 12px;
          color: var(--text-muted);
        }
        
        .yaml-info p {
          margin-bottom: 8px;
        }
        
        .yaml-info code {
          background: var(--bg-secondary);
          padding: 2px 6px;
          border-radius: var(--radius-sm);
        }
      `}</style>
      
      <div className="yaml-header">
        <div className="yaml-title">
          <h3>Project Configuration</h3>
          {hasChanges && (
            <span className="status-badge warning">
              <AlertCircle size={12} />
              Unsaved changes
            </span>
          )}
          {error && (
            <span className="status-badge error">
              <AlertCircle size={12} />
              {error}
            </span>
          )}
          {copied && (
            <span className="status-badge success">
              <Check size={12} />
              Copied!
            </span>
          )}
        </div>
        <div className="yaml-actions">
          <button className="btn btn-secondary btn-sm" onClick={handleCopy} title="Copy to clipboard">
            <Copy size={14} />
            Copy
          </button>
          <button className="btn btn-secondary btn-sm" onClick={handleDownload} title="Download YAML">
            <Download size={14} />
            Download
          </button>
          <button className="btn btn-secondary btn-sm" onClick={handleUpload} title="Upload YAML">
            <Upload size={14} />
            Upload
          </button>
          <button className="btn btn-secondary btn-sm" onClick={loadYaml} title="Reload from server">
            <RefreshCw size={14} />
            Reload
          </button>
          <button 
            className="btn btn-primary btn-sm" 
            onClick={handleApply}
            disabled={!hasChanges || loading}
          >
            Apply Changes
          </button>
        </div>
      </div>
      
      <div className="yaml-editor">
        <Editor
          height="100%"
          language="yaml"
          theme="vs-dark"
          value={yaml}
          onChange={handleYamlChange}
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
            wordWrap: 'on',
          }}
        />
      </div>
      
      <div className="yaml-info">
        <p>
          This YAML represents your entire project configuration including the app, agents, tools, and state keys.
        </p>
        <p>
          You can edit the YAML directly, then click <code>Apply Changes</code> to update the project.
          Use <code>Download</code> to save a backup or <code>Upload</code> to import a configuration.
        </p>
      </div>
    </div>
  );
}

