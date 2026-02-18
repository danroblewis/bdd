import React, { useState, useEffect, useRef, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { api } from '../utils/api';
import './ModelAutocomplete.css';

interface ModelInfo {
  id: string;
  name: string;
  provider: string;
  description?: string;
  context_window?: number;
  supports_tools?: boolean;
  supports_vision?: boolean;
  supports_json_mode?: boolean;
  supports_streaming?: boolean;
}

interface ProviderModels {
  provider: string;
  models: ModelInfo[];
  error?: string;
}

interface ModelAutocompleteProps {
  projectId: string;
  value: string;
  provider?: string;
  apiBase?: string;  // Used to invalidate cache when API base changes
  onChange: (modelId: string, provider: string) => void;
  placeholder?: string;
}

// Cache for models by project
const modelsCache: Record<string, { providers: Record<string, ProviderModels>; timestamp: number }> = {};
const CACHE_TTL = 5 * 60 * 1000; // 5 minutes

export function ModelAutocomplete({
  projectId,
  value,
  provider,
  apiBase,
  onChange,
  placeholder = "Search models...",
}: ModelAutocompleteProps) {
  // Create a cache key that includes provider and apiBase so changing them invalidates cache
  const cacheKey = `${projectId}:${provider || ''}:${apiBase || ''}`;
  const [query, setQuery] = useState(value || '');
  const [isOpen, setIsOpen] = useState(false);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [highlightedIndex, setHighlightedIndex] = useState(-1);
  const [dropdownPosition, setDropdownPosition] = useState({ top: 0, left: 0, width: 0 });
  const inputRef = useRef<HTMLInputElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Update dropdown position when opening
  useEffect(() => {
    if (isOpen && inputRef.current) {
      const rect = inputRef.current.getBoundingClientRect();
      setDropdownPosition({
        top: rect.bottom + window.scrollY + 4,
        left: rect.left + window.scrollX,
        width: rect.width,
      });
    }
  }, [isOpen]);

  // Fetch models from API
  const fetchModels = useCallback(async () => {
    // Check cache first (using cacheKey which includes apiBase)
    const cached = modelsCache[cacheKey];
    if (cached && Date.now() - cached.timestamp < CACHE_TTL) {
      const allModels: ModelInfo[] = [];
      Object.values(cached.providers).forEach(p => {
        allModels.push(...p.models);
      });
      setModels(allModels);
      return;
    }

    setLoading(true);
    setError(null);
    try {
      // Build query params - provider is required, apiBase is optional
      const params = new URLSearchParams();
      if (provider) {
        params.append('provider', provider);
      }
      if (apiBase) {
        params.append('api_base', apiBase);
      }
      const url = `/models/${projectId}${params.toString() ? '?' + params.toString() : ''}`;
      const response = await api.get<{ providers: Record<string, ProviderModels> }>(url);
      
      // Cache the response with cacheKey
      modelsCache[cacheKey] = {
        providers: response.providers,
        timestamp: Date.now(),
      };
      
      // Flatten all models
      const allModels: ModelInfo[] = [];
      Object.values(response.providers).forEach(p => {
        if (p.models && p.models.length > 0) {
          allModels.push(...p.models);
        }
      });
      
      setModels(allModels);
    } catch (e: any) {
      setError(e.message || 'Failed to fetch models');
    } finally {
      setLoading(false);
    }
  }, [projectId, cacheKey, apiBase, provider]);

  // Fetch models on mount and when projectId changes
  useEffect(() => {
    fetchModels();
  }, [fetchModels]);

  // Sync query with value prop
  useEffect(() => {
    setQuery(value || '');
  }, [value]);

  // Filter models based on query (match any part)
  // Provider filtering is now done on the backend
  const filteredModels = models.filter(m => {
    const searchTerm = query.toLowerCase();
    return (
      m.id.toLowerCase().includes(searchTerm) ||
      m.name.toLowerCase().includes(searchTerm) ||
      m.provider.toLowerCase().includes(searchTerm)
    );
  });

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(e.target as Node) &&
        inputRef.current &&
        !inputRef.current.contains(e.target as Node)
      ) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // Handle keyboard navigation
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (!isOpen) {
      if (e.key === 'ArrowDown' || e.key === 'Enter') {
        setIsOpen(true);
        e.preventDefault();
      }
      return;
    }

    switch (e.key) {
      case 'ArrowDown':
        setHighlightedIndex(i => Math.min(i + 1, filteredModels.length - 1));
        e.preventDefault();
        break;
      case 'ArrowUp':
        setHighlightedIndex(i => Math.max(i - 1, 0));
        e.preventDefault();
        break;
      case 'Enter':
        if (highlightedIndex >= 0 && highlightedIndex < filteredModels.length) {
          selectModel(filteredModels[highlightedIndex]);
        }
        e.preventDefault();
        break;
      case 'Escape':
        setIsOpen(false);
        break;
    }
  };

  const selectModel = (model: ModelInfo) => {
    setQuery(model.id);
    onChange(model.id, model.provider);
    setIsOpen(false);
  };

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setQuery(e.target.value);
    setIsOpen(true);
    setHighlightedIndex(-1);
    // Also update the parent with the raw value in case they type a custom model
    onChange(e.target.value, provider || 'gemini');
  };

  const getProviderBadgeClass = (provider: string) => {
    switch (provider.toLowerCase()) {
      case 'gemini': return 'provider-gemini';
      case 'anthropic': return 'provider-anthropic';
      case 'openai': return 'provider-openai';
      case 'groq': return 'provider-groq';
      case 'together': return 'provider-together';
      case 'ollama': return 'provider-ollama';
      default: return 'provider-other';
    }
  };

  const dropdown = isOpen ? (
    <div 
      ref={dropdownRef} 
      className="model-autocomplete-dropdown model-autocomplete-dropdown-portal"
      style={{
        position: 'fixed',
        top: dropdownPosition.top,
        left: dropdownPosition.left,
        width: dropdownPosition.width,
      }}
    >
      {loading && (
        <div className="model-autocomplete-loading">Loading models...</div>
      )}
      
      {error && (
        <div className="model-autocomplete-error">{error}</div>
      )}
      
      {!loading && !error && filteredModels.length === 0 && (
        <div className="model-autocomplete-empty">
          {query ? 'No matching models' : 'No models available'}
        </div>
      )}
      
      {!loading && filteredModels.length > 0 && (
        <div className="model-autocomplete-list">
          {filteredModels.slice(0, 50).map((model, index) => (
            <div
              key={`${model.provider}-${model.id}`}
              className={`model-autocomplete-item ${
                index === highlightedIndex ? 'highlighted' : ''
              }`}
              onClick={() => selectModel(model)}
              onMouseEnter={() => setHighlightedIndex(index)}
            >
              <span className={`provider-badge ${getProviderBadgeClass(model.provider)}`}>
                {model.provider}
              </span>
              <span className="model-id">{model.id}</span>
              {model.context_window && (
                <span className="model-context" title={`${model.context_window.toLocaleString()} token context`}>
                  {Math.round(model.context_window / 1000)}K
                </span>
              )}
              {model.supports_tools && (
                <span className="model-feature" title="Supports function calling / tools">🔧</span>
              )}
              {model.supports_vision && (
                <span className="model-feature" title="Supports image/vision input">👁️</span>
              )}
              {model.supports_json_mode && (
                <span className="model-feature" title="Supports structured JSON output">📋</span>
              )}
            </div>
          ))}
          {filteredModels.length > 50 && (
            <div className="model-autocomplete-more">
              +{filteredModels.length - 50} more...
            </div>
          )}
        </div>
      )}
    </div>
  ) : null;

  return (
    <div className="model-autocomplete">
      <input
        ref={inputRef}
        type="text"
        value={query}
        onChange={handleInputChange}
        onFocus={() => setIsOpen(true)}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        className="model-autocomplete-input"
      />
      {dropdown && createPortal(dropdown, document.body)}
    </div>
  );
}

// Hook to invalidate the cache
export function invalidateModelsCache(projectId?: string) {
  if (projectId) {
    delete modelsCache[projectId];
  } else {
    Object.keys(modelsCache).forEach(key => delete modelsCache[key]);
  }
}

