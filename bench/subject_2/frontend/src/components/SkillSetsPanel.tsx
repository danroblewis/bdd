/**
 * SkillSets Panel - Manage vector database toolsets
 * 
 * Each SkillSet is a separate vector store that can be attached to agents.
 * Similar to MCP servers, SkillSets provide tools for semantic search.
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { 
  Plus, Trash2, Search, Upload, Link, ChevronDown, ChevronRight, 
  Database, FileText, Globe, RefreshCw, Settings, X
} from 'lucide-react';
import { useStore } from '../hooks/useStore';
import { 
  getSkillSetStats, getSkillSetEntries, searchSkillSet,
  addSkillSetUrl, uploadSkillSetFile, clearSkillSet, deleteSkillSetSource,
  checkEmbeddingsAvailable, SkillSetStats, SkillSetSearchResult
} from '../utils/api';
import type { SkillSetConfig, Project } from '../utils/types';

const generateId = () => Math.random().toString(36).substring(2, 10);

// Default new SkillSet
const createDefaultSkillSet = (): SkillSetConfig => ({
  id: generateId(),
  name: 'New SkillSet',
  description: '',
  embedding_model: undefined,
  app_model_id: undefined,
  external_store_type: undefined,
  external_store_config: {},
  search_enabled: true,
  preload_enabled: true,
  preload_top_k: 3,
  preload_min_score: 0.4,
  sources: [],
  entry_count: 0,
});

export function SkillSetsPanel() {
  const { project, setProject } = useStore();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [stats, setStats] = useState<SkillSetStats | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<SkillSetSearchResult[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [sourcesExpanded, setSourcesExpanded] = useState(false);
  const [urlInput, setUrlInput] = useState('');
  const [isAddingUrl, setIsAddingUrl] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [embeddingsAvailable, setEmbeddingsAvailable] = useState<boolean | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const skillsets = project?.skillsets || [];
  const selected = skillsets.find(s => s.id === selectedId);

  // Check embeddings availability
  useEffect(() => {
    checkEmbeddingsAvailable()
      .then(r => setEmbeddingsAvailable(r.available))
      .catch(() => setEmbeddingsAvailable(false));
  }, []);

  // Auto-select first skillset
  useEffect(() => {
    if (skillsets.length > 0 && !selectedId) {
      setSelectedId(skillsets[0].id);
    }
  }, [skillsets, selectedId]);

  // Load stats when selection changes
  useEffect(() => {
    if (!project || !selectedId) return;
    loadStats();
  }, [project?.id, selectedId]);

  const loadStats = useCallback(async () => {
    if (!project || !selectedId) return;
    try {
      const data = await getSkillSetStats(project.id, selectedId);
      setStats(data);
      // Update entry count in project
      updateSkillSet(selectedId, { entry_count: data.entry_count });
    } catch (err) {
      console.error('Failed to load stats:', err);
    }
  }, [project?.id, selectedId]);

  const updateProject = (updates: Partial<Project>) => {
    if (!project) return;
    setProject({ ...project, ...updates });
  };

  const updateSkillSet = (id: string, updates: Partial<SkillSetConfig>) => {
    if (!project) return;
    setProject({
      ...project,
      skillsets: project.skillsets.map(s => s.id === id ? { ...s, ...updates } : s),
    });
  };

  const handleAddSkillSet = () => {
    if (!project) return;
    const newSkillSet = createDefaultSkillSet();
    updateProject({ skillsets: [...skillsets, newSkillSet] });
    setSelectedId(newSkillSet.id);
  };

  const handleDeleteSkillSet = (id: string) => {
    if (!project) return;
    if (!confirm('Delete this SkillSet and all its data?')) return;
    updateProject({ skillsets: skillsets.filter(s => s.id !== id) });
    if (selectedId === id) {
      setSelectedId(skillsets.length > 1 ? skillsets[0].id : null);
    }
    setStats(null);
    setSearchResults([]);
  };

  const handleSearch = async () => {
    if (!project || !selectedId || !searchQuery.trim()) return;
    setIsSearching(true);
    setError(null);
    try {
      const data = await searchSkillSet(project.id, selectedId, searchQuery.trim(), 10, 0.0);
      setSearchResults(data.results);
    } catch (err) {
      setError('Search failed');
      console.error(err);
    } finally {
      setIsSearching(false);
    }
  };

  const handleAddUrl = async () => {
    if (!project || !selectedId || !urlInput.trim()) return;
    setIsAddingUrl(true);
    setError(null);
    try {
      const result = await addSkillSetUrl(project.id, selectedId, urlInput.trim());
      setUrlInput('');
      await loadStats();
      alert(`Added ${result.chunks_added} chunks from ${result.source_name}`);
    } catch (err: any) {
      setError(err.message || 'Failed to fetch URL');
    } finally {
      setIsAddingUrl(false);
    }
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !project || !selectedId) return;
    setError(null);
    try {
      const result = await uploadSkillSetFile(project.id, selectedId, file);
      await loadStats();
      alert(`Added ${result.chunks_added} chunks from ${result.source_name}`);
    } catch (err: any) {
      setError(err.message || 'Upload failed');
    }
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const handleClearAll = async () => {
    if (!project || !selectedId) return;
    if (!confirm('Delete all entries in this SkillSet?')) return;
    try {
      await clearSkillSet(project.id, selectedId);
      await loadStats();
      setSearchResults([]);
    } catch (err) {
      setError('Clear failed');
    }
  };

  // Score to gradient background
  const getScoreBackground = (score: number) => {
    // Score is 0-1, higher is more relevant
    const percent = Math.round(score * 100);
    const hue = 160; // Teal/cyan
    const saturation = 70;
    const lightness = 20 + (1 - score) * 15; // Darker = more relevant
    const alpha = 0.15 + score * 0.25;
    return `linear-gradient(90deg, hsla(${hue}, ${saturation}%, ${lightness}%, ${alpha}) 0%, transparent ${percent}%)`;
  };

  if (!project) return null;

  return (
    <div className="skillsets-panel">
      <style>{`
        .skillsets-panel {
          display: flex;
          height: 100%;
          gap: 16px;
        }
        
        .skillset-list {
          width: 240px;
          min-width: 240px;
          display: flex;
          flex-direction: column;
          gap: 8px;
        }
        
        .skillset-list-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 8px 0;
        }
        
        .skillset-list-header h3 {
          font-size: 14px;
          font-weight: 600;
          color: var(--text-secondary);
          margin: 0;
        }
        
        .skillset-item {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 10px 12px;
          background: var(--bg-secondary);
          border-radius: 8px;
          cursor: pointer;
          transition: all 0.15s;
        }
        
        .skillset-item:hover {
          background: var(--bg-tertiary);
        }
        
        .skillset-item.selected {
          background: var(--accent-muted);
          border: 1px solid var(--accent);
        }
        
        .skillset-item-info {
          flex: 1;
          min-width: 0;
        }
        
        .skillset-item-name {
          font-size: 13px;
          font-weight: 500;
          color: var(--text-primary);
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        
        .skillset-item-count {
          font-size: 11px;
          color: var(--text-tertiary);
        }
        
        .skillset-item-delete {
          opacity: 0;
          padding: 4px;
          border-radius: 4px;
          color: var(--text-tertiary);
          transition: all 0.15s;
        }
        
        .skillset-item:hover .skillset-item-delete {
          opacity: 1;
        }
        
        .skillset-item-delete:hover {
          background: var(--error-muted);
          color: var(--error);
        }
        
        .skillset-detail {
          flex: 1;
          display: flex;
          flex-direction: column;
          gap: 16px;
          min-width: 0;
        }
        
        .skillset-header {
          display: flex;
          align-items: flex-start;
          gap: 12px;
        }
        
        .skillset-header-info {
          flex: 1;
        }
        
        .skillset-name-input {
          font-size: 18px;
          font-weight: 600;
          background: transparent;
          border: none;
          color: var(--text-primary);
          width: 100%;
          padding: 0;
        }
        
        .skillset-name-input:focus {
          outline: none;
          border-bottom: 1px solid var(--accent);
        }
        
        .skillset-desc-input {
          font-size: 13px;
          color: var(--text-secondary);
          background: transparent;
          border: none;
          width: 100%;
          padding: 4px 0;
          resize: none;
        }
        
        .skillset-desc-input:focus {
          outline: none;
          border-bottom: 1px solid var(--border);
        }
        
        .skillset-stats {
          display: flex;
          gap: 16px;
          font-size: 12px;
          color: var(--text-tertiary);
        }
        
        .skillset-stat {
          display: flex;
          align-items: center;
          gap: 4px;
        }
        
        .skillset-stat strong {
          color: var(--text-secondary);
        }
        
        .search-section {
          display: flex;
          gap: 8px;
        }
        
        .search-input-wrapper {
          flex: 1;
          position: relative;
        }
        
        .search-input {
          width: 100%;
          padding: 10px 12px;
          background: var(--bg-secondary);
          border: 1px solid var(--border);
          border-radius: 8px;
          color: var(--text-primary);
          font-size: 13px;
        }
        
        .search-input:focus {
          outline: none;
          border-color: var(--accent);
        }
        
        .search-results {
          flex: 1;
          overflow-y: auto;
          display: flex;
          flex-direction: column;
          gap: 2px;
        }
        
        .search-result {
          padding: 8px 12px;
          border-radius: 6px;
          font-size: 13px;
          line-height: 1.4;
          color: var(--text-secondary);
          position: relative;
        }
        
        .search-result-score {
          position: absolute;
          right: 8px;
          top: 8px;
          font-size: 11px;
          font-weight: 500;
          color: var(--accent);
          background: var(--bg-primary);
          padding: 2px 6px;
          border-radius: 4px;
        }
        
        .search-result-text {
          padding-right: 50px;
          max-height: 60px;
          overflow: hidden;
        }
        
        .search-result-source {
          font-size: 11px;
          color: var(--text-tertiary);
          margin-top: 4px;
        }
        
        .add-sources-section {
          background: var(--bg-secondary);
          border-radius: 8px;
          overflow: hidden;
        }
        
        .add-sources-header {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 10px 12px;
          cursor: pointer;
          user-select: none;
        }
        
        .add-sources-header:hover {
          background: var(--bg-tertiary);
        }
        
        .add-sources-header h4 {
          flex: 1;
          font-size: 13px;
          font-weight: 500;
          margin: 0;
          color: var(--text-secondary);
        }
        
        .add-sources-content {
          padding: 12px;
          border-top: 1px solid var(--border);
          display: flex;
          flex-direction: column;
          gap: 12px;
        }
        
        .source-row {
          display: flex;
          gap: 8px;
          align-items: center;
        }
        
        .source-input {
          flex: 1;
          padding: 8px 10px;
          background: var(--bg-primary);
          border: 1px solid var(--border);
          border-radius: 6px;
          color: var(--text-primary);
          font-size: 13px;
        }
        
        .source-input:focus {
          outline: none;
          border-color: var(--accent);
        }
        
        .clear-button {
          display: flex;
          align-items: center;
          gap: 4px;
          padding: 6px 10px;
          background: var(--error-muted);
          border: none;
          border-radius: 6px;
          color: var(--error);
          font-size: 12px;
          cursor: pointer;
        }
        
        .clear-button:hover {
          background: var(--error);
          color: white;
        }
        
        .empty-state {
          flex: 1;
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          gap: 12px;
          color: var(--text-tertiary);
        }
        
        .empty-state svg {
          opacity: 0.3;
        }
        
        .btn-icon {
          display: flex;
          align-items: center;
          justify-content: center;
          padding: 8px;
          background: var(--bg-secondary);
          border: 1px solid var(--border);
          border-radius: 6px;
          color: var(--text-secondary);
          cursor: pointer;
          transition: all 0.15s;
        }
        
        .btn-icon:hover {
          background: var(--bg-tertiary);
          color: var(--text-primary);
        }
        
        .error-banner {
          padding: 8px 12px;
          background: var(--error-muted);
          border-radius: 6px;
          color: var(--error);
          font-size: 12px;
          display: flex;
          align-items: center;
          gap: 8px;
        }
        
        .error-banner button {
          margin-left: auto;
          background: none;
          border: none;
          color: inherit;
          cursor: pointer;
        }
        
        input[type="file"] {
          display: none;
        }
      `}</style>

      {/* SkillSet List */}
      <div className="skillset-list">
        <div className="skillset-list-header">
          <h3>SkillSets</h3>
          <button className="btn-icon" onClick={handleAddSkillSet} title="Add SkillSet">
            <Plus size={16} />
          </button>
        </div>
        
        {skillsets.length === 0 ? (
          <div className="empty-state" style={{ padding: '40px 0' }}>
            <Database size={32} />
            <span>No SkillSets</span>
            <button className="btn-primary" onClick={handleAddSkillSet}>
              <Plus size={14} /> Create SkillSet
            </button>
          </div>
        ) : (
          skillsets.map(s => (
            <div 
              key={s.id}
              className={`skillset-item ${selectedId === s.id ? 'selected' : ''}`}
              onClick={() => setSelectedId(s.id)}
            >
              <Database size={16} style={{ color: 'var(--accent)', flexShrink: 0 }} />
              <div className="skillset-item-info">
                <div className="skillset-item-name">{s.name}</div>
                <div className="skillset-item-count">{s.entry_count || 0} entries</div>
              </div>
              <button 
                className="skillset-item-delete"
                onClick={(e) => { e.stopPropagation(); handleDeleteSkillSet(s.id); }}
              >
                <Trash2 size={14} />
              </button>
            </div>
          ))
        )}
      </div>

      {/* Detail View */}
      {selected ? (
        <div className="skillset-detail">
          {/* Header */}
          <div className="skillset-header">
            <div className="skillset-header-info">
              <input
                className="skillset-name-input"
                value={selected.name}
                onChange={e => updateSkillSet(selected.id, { name: e.target.value })}
                placeholder="SkillSet Name"
              />
              <textarea
                className="skillset-desc-input"
                value={selected.description}
                onChange={e => updateSkillSet(selected.id, { description: e.target.value })}
                placeholder="Description (optional)"
                rows={1}
              />
              
              {/* Model Selection */}
              <div className="skillset-model">
                <label style={{ fontSize: '12px', color: 'var(--text-secondary)', marginRight: '8px' }}>
                  Embedding Model:
                </label>
                <select
                  style={{
                    flex: 1,
                    padding: '4px 8px',
                    fontSize: '12px',
                    background: 'var(--bg-secondary)',
                    border: '1px solid var(--border)',
                    borderRadius: '4px',
                    color: 'var(--text-primary)',
                  }}
                  value={selected.embedding_model || 'text-embedding-004'}
                  onChange={e => updateSkillSet(selected.id, { embedding_model: e.target.value })}
                >
                  <optgroup label="Google Gemini">
                    <option value="text-embedding-004">text-embedding-004 (768d)</option>
                    <option value="text-embedding-005">text-embedding-005</option>
                  </optgroup>
                  <optgroup label="OpenAI">
                    <option value="text-embedding-3-small">text-embedding-3-small (1536d)</option>
                    <option value="text-embedding-3-large">text-embedding-3-large (3072d)</option>
                  </optgroup>
                  <optgroup label="Cohere">
                    <option value="embed-english-v3.0">embed-english-v3.0 (1024d)</option>
                    <option value="embed-multilingual-v3.0">embed-multilingual-v3.0 (1024d)</option>
                  </optgroup>
                </select>
              </div>
              
              <div className="skillset-stats">
                <span className="skillset-stat">
                  <strong>{stats?.entry_count || 0}</strong> entries
                </span>
                <span className="skillset-stat">
                  <strong>{Object.keys(stats?.sources || {}).length}</strong> sources
                </span>
                {embeddingsAvailable === false && (
                  <span className="skillset-stat" style={{ color: 'var(--warning)' }}>
                    ⚠ No embeddings
                  </span>
                )}
              </div>
            </div>
            <button className="btn-icon" onClick={loadStats} title="Refresh">
              <RefreshCw size={16} />
            </button>
          </div>

          {error && (
            <div className="error-banner">
              {error}
              <button onClick={() => setError(null)}><X size={14} /></button>
            </div>
          )}

          {/* Search */}
          <div className="search-section">
            <div className="search-input-wrapper">
              <input
                className="search-input"
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && handleSearch()}
                placeholder="Search this SkillSet..."
              />
            </div>
            <button 
              className="btn-primary" 
              onClick={handleSearch}
              disabled={isSearching || !searchQuery.trim()}
            >
              <Search size={14} />
              {isSearching ? 'Searching...' : 'Search'}
            </button>
          </div>

          {/* Search Results */}
          <div className="search-results">
            {searchResults.length === 0 && !isSearching && searchQuery && (
              <div className="empty-state">
                <span>No results found</span>
              </div>
            )}
            {searchResults.map(r => (
              <div 
                key={r.id} 
                className="search-result"
                style={{ background: getScoreBackground(r.score) }}
              >
                <span className="search-result-score">{(r.score * 100).toFixed(0)}%</span>
                <div className="search-result-text">{r.text}</div>
                <div className="search-result-source">{r.source_name}</div>
              </div>
            ))}
          </div>

          {/* Add Sources (Collapsible) */}
          <div className="add-sources-section">
            <div 
              className="add-sources-header"
              onClick={() => setSourcesExpanded(!sourcesExpanded)}
            >
              {sourcesExpanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
              <h4>Add Sources</h4>
            </div>
            
            {sourcesExpanded && (
              <div className="add-sources-content">
                {/* URL Input */}
                <div className="source-row">
                  <Globe size={16} style={{ color: 'var(--text-tertiary)' }} />
                  <input
                    className="source-input"
                    value={urlInput}
                    onChange={e => setUrlInput(e.target.value)}
                    onKeyDown={e => e.key === 'Enter' && handleAddUrl()}
                    placeholder="Enter URL (e.g., llms.txt file)"
                  />
                  <button 
                    className="btn-primary" 
                    onClick={handleAddUrl}
                    disabled={isAddingUrl || !urlInput.trim()}
                  >
                    <Link size={14} />
                    {isAddingUrl ? 'Loading...' : 'Add'}
                  </button>
                </div>
                
                {/* File Upload */}
                <div className="source-row">
                  <FileText size={16} style={{ color: 'var(--text-tertiary)' }} />
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept=".txt,.md,.json,.csv,.html"
                    onChange={handleFileUpload}
                  />
                  <button 
                    className="btn-primary" 
                    onClick={() => fileInputRef.current?.click()}
                  >
                    <Upload size={14} />
                    Upload File
                  </button>
                  <span style={{ fontSize: '12px', color: 'var(--text-tertiary)' }}>
                    .txt, .md, .json, .csv
                  </span>
                </div>

                {/* Clear All */}
                {(stats?.entry_count || 0) > 0 && (
                  <div className="source-row" style={{ marginTop: '8px' }}>
                    <button className="clear-button" onClick={handleClearAll}>
                      <Trash2 size={12} />
                      Clear All Entries ({stats?.entry_count || 0})
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      ) : skillsets.length > 0 ? (
        <div className="skillset-detail">
          <div className="empty-state">
            <Database size={48} />
            <span>Select a SkillSet</span>
          </div>
        </div>
      ) : null}
    </div>
  );
}

