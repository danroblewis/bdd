import React, { useState } from 'react';
import { ModelAutocomplete } from './ModelAutocomplete';
import { testModelConfig } from '../utils/api';
import { Zap, Loader2, CheckCircle, XCircle } from 'lucide-react';
import './ModelConfigForm.css';

export type ModelProvider = 'gemini' | 'anthropic' | 'openai' | 'groq' | 'together' | 'litellm';

export interface ModelConfigValues {
  model_name?: string;
  provider?: ModelProvider;
  api_base?: string;
  temperature?: number;
  max_output_tokens?: number;
  top_p?: number;
  top_k?: number;
  // Retry and timeout settings (especially useful for local models like Ollama)
  num_retries?: number;
  request_timeout?: number;
}

interface ModelConfigFormProps {
  projectId: string;
  values: ModelConfigValues;
  onChange: (updates: Partial<ModelConfigValues>) => void;
  className?: string;
}

const PROVIDERS: { value: ModelProvider; label: string }[] = [
  { value: 'gemini', label: 'Gemini' },
  { value: 'anthropic', label: 'Anthropic' },
  { value: 'openai', label: 'OpenAI' },
  { value: 'groq', label: 'Groq' },
  { value: 'together', label: 'Together (via LiteLLM)' },
  { value: 'litellm', label: 'LiteLLM / Other' },
];

/**
 * Helper to detect provider from model ID format
 */
function detectProvider(modelId: string, currentProvider?: string): ModelProvider {
  if (modelId.startsWith('openai/')) return 'openai';
  if (modelId.startsWith('groq/')) return 'groq';
  if (modelId.startsWith('together_ai/') || modelId.startsWith('together/')) return 'together';
  if (modelId.startsWith('ollama/')) return 'litellm';
  if (modelId.startsWith('claude-')) return 'anthropic';
  if (modelId.startsWith('gemini-')) return 'gemini';
  if (modelId.includes('/')) return 'litellm';
  return (currentProvider as ModelProvider) || 'gemini';
}

/**
 * Reusable model configuration form with autocomplete, temperature, tokens, etc.
 * Used in both App configurator and Agent configurator.
 */
export function ModelConfigForm({
  projectId,
  values,
  onChange,
  className = '',
}: ModelConfigFormProps) {
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null);

  const handleTest = async () => {
    if (!values.model_name || !values.provider) {
      setTestResult({ success: false, message: 'Please select a model first' });
      return;
    }

    setTesting(true);
    setTestResult(null);

    try {
      const result = await testModelConfig(projectId, {
        provider: values.provider,
        model_name: values.model_name,
        api_base: values.api_base,
      });

      if (result.success) {
        setTestResult({ 
          success: true, 
          message: result.response?.slice(0, 100) || 'Model responded successfully!' 
        });
      } else {
        setTestResult({ 
          success: false, 
          message: result.error || 'Test failed' 
        });
      }
    } catch (error: any) {
      setTestResult({ 
        success: false, 
        message: error.message || 'Connection failed' 
      });
    } finally {
      setTesting(false);
    }
  };

  return (
    <div className={`model-config-form ${className}`}>
      <div className="model-config-row">
        <div className="model-config-field" style={{ flex: 1 }}>
          <label>Provider</label>
          <select
            value={values.provider || 'gemini'}
            onChange={(e) => {
              onChange({ provider: e.target.value as ModelProvider });
              setTestResult(null);
            }}
          >
            {PROVIDERS.map(p => (
              <option key={p.value} value={p.value}>{p.label}</option>
            ))}
          </select>
        </div>
        <div className="model-config-field" style={{ flex: 3 }}>
          <label>Model</label>
          <ModelAutocomplete
            projectId={projectId}
            value={values.model_name || ''}
            provider={values.provider}
            apiBase={values.api_base}
            onChange={(modelId, provider) => {
              const detectedProvider = detectProvider(modelId, provider);
              onChange({ 
                model_name: modelId,
                provider: detectedProvider,
              });
              setTestResult(null);
            }}
            placeholder="Search models..."
          />
        </div>
        <div className="model-config-field" style={{ flex: 2 }}>
          <label>API Base (optional)</label>
          <input
            type="text"
            value={values.api_base || ''}
            onChange={(e) => {
              onChange({ api_base: e.target.value || undefined });
              setTestResult(null);
            }}
            placeholder={
              values.provider === 'gemini' ? 'https://generativelanguage.googleapis.com' :
              values.provider === 'anthropic' ? 'https://api.anthropic.com' :
              values.provider === 'openai' ? 'https://api.openai.com/v1' :
              values.provider === 'groq' ? 'https://api.groq.com/openai/v1' :
              values.provider === 'together' ? 'https://api.together.xyz/v1' :
              'http://localhost:11434'
            }
          />
        </div>
        <div className="model-config-field model-test-field">
          <label>&nbsp;</label>
          <button
            type="button"
            className={`model-test-btn ${testResult?.success === true ? 'success' : testResult?.success === false ? 'error' : ''}`}
            onClick={handleTest}
            disabled={testing || !values.model_name}
            title={testResult?.message || 'Test model connection'}
          >
            {testing ? (
              <Loader2 size={14} className="spinning" />
            ) : testResult?.success === true ? (
              <CheckCircle size={14} />
            ) : testResult?.success === false ? (
              <XCircle size={14} />
            ) : (
              <Zap size={14} />
            )}
            {testing ? 'Testing...' : 'Test'}
          </button>
        </div>
      </div>
      <div className="model-config-row">
        <div className="model-config-field">
          <label>Temperature</label>
          <input
            type="number"
            step="0.1"
            min="0"
            max="2"
            value={values.temperature ?? ''}
            onChange={(e) => onChange({ temperature: e.target.value ? parseFloat(e.target.value) : undefined })}
            placeholder="Default"
          />
        </div>
        <div className="model-config-field">
          <label>Max Tokens</label>
          <input
            type="number"
            min="1"
            value={values.max_output_tokens ?? ''}
            onChange={(e) => onChange({ max_output_tokens: e.target.value ? parseInt(e.target.value) : undefined })}
            placeholder="Default"
          />
        </div>
        <div className="model-config-field">
          <label>Top P</label>
          <input
            type="number"
            step="0.1"
            min="0"
            max="1"
            value={values.top_p ?? ''}
            onChange={(e) => onChange({ top_p: e.target.value ? parseFloat(e.target.value) : undefined })}
            placeholder="Default"
          />
        </div>
        <div className="model-config-field">
          <label>Top K</label>
          <input
            type="number"
            min="1"
            value={values.top_k ?? ''}
            onChange={(e) => onChange({ top_k: e.target.value ? parseInt(e.target.value) : undefined })}
            placeholder="Default"
          />
        </div>
      </div>
      {/* Retry and timeout settings - useful for local/slow models */}
      <div className="model-config-row">
        <div className="model-config-field">
          <label title="Number of times to retry on connection failure">Retries</label>
          <input
            type="number"
            min="0"
            max="10"
            value={values.num_retries ?? ''}
            onChange={(e) => onChange({ num_retries: e.target.value ? parseInt(e.target.value) : undefined })}
            placeholder="3"
          />
        </div>
        <div className="model-config-field" style={{ flex: 2 }}>
          <label title="Maximum time to wait for a response (in seconds)">Timeout (seconds)</label>
          <input
            type="number"
            min="10"
            max="3600"
            step="10"
            value={values.request_timeout ?? ''}
            onChange={(e) => onChange({ request_timeout: e.target.value ? parseInt(e.target.value) : undefined })}
            placeholder="600 (10 min)"
          />
        </div>
        <div className="model-config-field" style={{ flex: 3 }}>
          <label>&nbsp;</label>
          <span className="model-config-hint" style={{ fontSize: '11px', color: '#666', marginTop: '4px' }}>
            Increase timeout for slow models like local Ollama
          </span>
        </div>
      </div>
    </div>
  );
}

