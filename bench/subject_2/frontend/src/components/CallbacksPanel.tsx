import { useState, useEffect, useRef } from 'react';
import { Plus, Trash2, Code, Key, Save, Loader, Sparkles } from 'lucide-react';
import { useStore } from '../hooks/useStore';
import type { CustomCallbackDefinition } from '../utils/types';
import Editor, { Monaco } from '@monaco-editor/react';
import { registerCompletion } from 'monacopilot';
import { generateCallbackCode } from '../utils/api';

function generateId() {
  return `callback_${Date.now().toString(36)}`;
}

// Validation function for names (alphanumeric and underscore only)
function isValidName(name: string): boolean {
  return /^[a-zA-Z0-9_]+$/.test(name);
}

// Template functions for different callback types
function getCallbackTemplate(type: string): string {
  switch (type) {
    case 'before_agent':
    case 'after_agent':
      return `from google.adk.agents.callback_context import CallbackContext
from typing import Optional
from google.genai import types

def my_callback(callback_context: CallbackContext) -> Optional[types.Content]:
    """Description of what this callback does.
    
    Args:
        callback_context: The callback context containing agent and state information.
            MUST be named 'callback_context' (enforced by ADK).
    
    Returns:
        Optional[types.Content]: Return a Content object to short-circuit (before_*) or add response (after_*), or None to proceed normally.
    """
    # ============================================================
    # State Management
    # ============================================================
    # Read state: callback_context.state.get('key', default_value)
    # Write state: callback_context.state['key'] = value
    # State changes are automatically tracked in state_delta
    
    # ============================================================
    # Short-circuiting Execution (before_agent only)
    # ============================================================
    # Return Content to skip agent execution:
    #   return types.Content(
    #       role="assistant",
    #       parts=[types.Part.from_text(text="Custom response")]
    #   )
    
    return None
`;

    case 'before_model':
      return `from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest, LlmResponse
from typing import Optional

def my_callback(*, callback_context: CallbackContext, llm_request: LlmRequest) -> Optional[LlmResponse]:
    """Description of what this callback does.
    
    Args:
        callback_context: The callback context (MUST be named 'callback_context').
        llm_request: The LLM request about to be made.
    
    Returns:
        Optional[LlmResponse]: Return LlmResponse to short-circuit, or None to proceed.
    """
    # ============================================================
    # State Management
    # ============================================================
    # Read state: callback_context.state.get('key', default_value)
    # Write state: callback_context.state['key'] = value
    
    # ============================================================
    # Short-circuiting Execution
    # ============================================================
    # Return LlmResponse to skip model call:
    #   from google.genai import types
    #   return LlmResponse(
    #       contents=[types.Content(role="assistant", parts=[types.Part.from_text(text="Custom response")])]
    #   )
    
    return None
`;

    case 'after_model':
      return `from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmResponse
from typing import Optional

def my_callback(*, callback_context: CallbackContext, llm_response: LlmResponse) -> Optional[LlmResponse]:
    """Description of what this callback does.
    
    Args:
        callback_context: The callback context (MUST be named 'callback_context').
        llm_response: The LLM response that was received.
    
    Returns:
        Optional[LlmResponse]: Return modified LlmResponse or None to keep original.
    """
    # ============================================================
    # State Management
    # ============================================================
    # Read state: callback_context.state.get('key', default_value)
    # Write state: callback_context.state['key'] = value
    
    # ============================================================
    # Accessing Response
    # ============================================================
    # Access response content: llm_response.content
    # Access usage metadata: llm_response.usage_metadata
    
    return None
`;

    case 'before_tool':
      return `from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext
from typing import Dict, Any, Optional

def my_callback(tool: BaseTool, tool_args: Dict[str, Any], tool_context: ToolContext) -> Optional[Dict]:
    """Description of what this callback does.
    
    Args:
        tool: The tool about to be called.
        tool_args: The arguments passed to the tool.
        tool_context: The tool context.
    
    Returns:
        Optional[Dict]: Return modified args or None to use original.
    """
    # ============================================================
    # State Management
    # ============================================================
    # Access state via tool_context: tool_context.state.get('key')
    # Modify tool_args to change what gets passed to the tool
    
    return None
`;

    case 'after_tool':
      return `from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext
from typing import Dict, Any, Optional

def my_callback(tool: BaseTool, tool_args: Dict[str, Any], tool_context: ToolContext, result: Dict) -> Optional[Dict]:
    """Description of what this callback does.
    
    Args:
        tool: The tool that was called.
        tool_args: The arguments that were passed.
        tool_context: The tool context.
        result: The result from the tool.
    
    Returns:
        Optional[Dict]: Return modified result or None to keep original.
    """
    # ============================================================
    # State Management
    # ============================================================
    # Access state via tool_context: tool_context.state.get('key')
    # Modify result to change what gets returned
    
    return None
`;

    default:
      return getCallbackTemplate('before_agent');
  }
}

const DEFAULT_CALLBACK_CODE = getCallbackTemplate('before_agent');

interface CallbacksPanelProps {
  onSelectCallback?: (id: string | null) => void;
}

export default function CallbacksPanel({ onSelectCallback }: CallbacksPanelProps) {
  const { project, updateProject, addCustomCallback, updateCustomCallback, removeCustomCallback } = useStore();
  const [editingCode, setEditingCode] = useState('');
  const [selectedCallbackId, setSelectedCallbackId] = useState<string | null>(null);
  const [callbackNameError, setCallbackNameError] = useState<string | null>(null);
  const [isGeneratingCode, setIsGeneratingCode] = useState(false);
  const monacoRef = useRef<Monaco | null>(null);
  
  if (!project) return null;
  
  const callbacks = project.custom_callbacks || [];
  const selectedCallback = callbacks.find(c => c.id === selectedCallbackId);
  
  function selectCallback(id: string | null) {
    setSelectedCallbackId(id);
    onSelectCallback?.(id);
  }
  
  useEffect(() => {
    if (selectedCallback) {
      setEditingCode(selectedCallback.code);
      setCallbackNameError(null);
    } else {
      setEditingCode('');
    }
  }, [selectedCallbackId, selectedCallback]);
  
  function handleAddCallback() {
    const id = generateId();
    const callbackName = 'new_callback';
    const callback: CustomCallbackDefinition = {
      id,
      name: callbackName,
      description: '',
      module_path: `callbacks.${callbackName}`,
      code: getCallbackTemplate('before_agent'),
      state_keys_used: []
    };
    addCustomCallback(callback);
    selectCallback(id);
  }
  
  function handleDeleteCallback(id: string, e: React.MouseEvent) {
    e.stopPropagation();
    if (!confirm('Delete this callback?')) return;
    removeCustomCallback(id);
    if (selectedCallbackId === id) {
      onSelectCallback?.(null);
      setSelectedCallbackId(null);
      setEditingCode('');
    }
  }
  
  function handleSaveCallback() {
    if (!selectedCallbackId) return;
    
    // Get fresh callback data from the store
    const latestCallback = callbacks.find(c => c.id === selectedCallbackId);
    if (!latestCallback) return;
    
    const name = latestCallback.name.trim();
    if (!name) {
      alert('Please enter a name');
      return;
    }
    
    if (!isValidName(name)) {
      setCallbackNameError('Name must contain only alphanumeric characters and underscores');
      return;
    }
    
    // Check for duplicate names (excluding current)
    const duplicate = callbacks.find(c => c.name === name && c.id !== latestCallback.id);
    if (duplicate) {
      setCallbackNameError('A callback with this name already exists');
      return;
    }
    
    updateCustomCallback(latestCallback.id, {
      code: editingCode,
      name,
      description: latestCallback.description,
      module_path: `callbacks.${name}`,  // Update module_path to match the function name
      state_keys_used: latestCallback.state_keys_used
    });
    setCallbackNameError(null);
  }
  
  function handleMonacoMount(editor: any, monaco: Monaco) {
    monacoRef.current = monaco;
    try {
      registerCompletion(monaco, {
        endpoint: '/api/code-completion',
        language: 'python',
      });
    } catch (e) {
      // Ignore registration errors
      console.warn('Failed to register Monacopilot completion:', e);
    }
  }
  
  async function handleGenerateCallback() {
    if (!selectedCallback) return;
    
    setIsGeneratingCode(true);
    try {
      // Try to infer callback type from name/description, default to before_agent
      let callbackType = 'before_agent';
      const nameLower = selectedCallback.name.toLowerCase();
      const descLower = selectedCallback.description.toLowerCase();
      
      if (nameLower.includes('after_agent') || descLower.includes('after agent')) {
        callbackType = 'after_agent';
      } else if (nameLower.includes('before_model') || descLower.includes('before model')) {
        callbackType = 'before_model';
      } else if (nameLower.includes('after_model') || descLower.includes('after model')) {
        callbackType = 'after_model';
      } else if (nameLower.includes('before_tool') || descLower.includes('before tool')) {
        callbackType = 'before_tool';
      } else if (nameLower.includes('after_tool') || descLower.includes('after tool')) {
        callbackType = 'after_tool';
      } else if (nameLower.includes('before_agent') || descLower.includes('before agent')) {
        callbackType = 'before_agent';
      }
      
      const result = await generateCallbackCode(
        project.id,
        selectedCallback.name,
        selectedCallback.description,
        callbackType,
        selectedCallback.state_keys_used
      );
      
      if (result.success && result.code) {
        setEditingCode(result.code);
        updateCustomCallback(selectedCallback.id, { code: result.code });
      } else {
        console.error('Failed to generate callback code:', result.error);
        alert('Failed to generate callback code: ' + (result.error || 'Unknown error'));
      }
    } catch (error) {
      console.error('Error generating callback code:', error);
      alert('Error generating callback code: ' + (error as Error).message);
    } finally {
      setIsGeneratingCode(false);
    }
  }
  
  const availableStateKeys = project.app?.state_keys?.map(k => k.name) || [];
  
  return (
    <div className="tools-panel">
      <style>{`
        .tools-panel {
          display: flex;
          height: 100%;
          background: var(--bg-primary);
        }
        
        .tools-sidebar {
          width: 250px;
          border-right: 1px solid var(--border-color);
          display: flex;
          flex-direction: column;
          background: var(--bg-secondary);
        }
        
        .tools-sidebar-header {
          padding: 16px;
          border-bottom: 1px solid var(--border-color);
          display: flex;
          align-items: center;
          justify-content: space-between;
        }
        
        .tools-list {
          flex: 1;
          overflow-y: auto;
        }
        
        .tool-item {
          padding: 12px 16px;
          cursor: pointer;
          border-bottom: 1px solid var(--border-color);
          display: flex;
          align-items: center;
          justify-content: space-between;
          transition: background 0.15s;
        }
        
        .tool-item:hover {
          background: var(--bg-hover);
        }
        
        .tool-item.selected {
          background: var(--bg-active);
        }
        
        .tool-item-name {
          font-weight: 500;
          color: var(--text-primary);
        }
        
        .tool-item-type {
          font-size: 11px;
          color: var(--text-secondary);
          margin-top: 2px;
        }
        
        .tool-item-actions {
          display: flex;
          gap: 4px;
        }
        
        .tools-editor {
          flex: 1;
          display: flex;
          flex-direction: column;
          overflow: hidden;
        }
        
        .tools-editor-header {
          padding: 16px;
          border-bottom: 1px solid var(--border-color);
          display: flex;
          align-items: center;
          justify-content: space-between;
        }
        
        .tools-editor-content {
          flex: 1;
          display: flex;
          flex-direction: column;
          overflow: hidden;
          min-height: 0;
        }
        
        .form-group {
          margin-bottom: 16px;
        }
        
        .form-group label {
          display: block;
          margin-bottom: 6px;
          font-weight: 500;
          color: var(--text-primary);
        }
        
        .form-group input,
        .form-group select,
        .form-group textarea {
          width: 100%;
          padding: 8px 12px;
          border: 1px solid var(--border-color);
          border-radius: var(--radius-sm);
          background: var(--bg-primary);
          color: var(--text-primary);
          font-family: inherit;
        }
        
        .form-group input.error {
          border-color: #ef4444;
        }
        
        .error-message {
          color: #ef4444;
          font-size: 12px;
          margin-top: 4px;
        }
        
        .code-editor-container {
          flex: 1;
          min-height: 400px;
          height: 400px;
          border: 1px solid var(--border-color);
          border-radius: var(--radius-sm);
          overflow: hidden;
        }
        
        .spinning {
          animation: spin 1s linear infinite;
        }
        
        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
      `}</style>
      
      <div className="tools-sidebar">
        <div className="tools-sidebar-header">
          <h3>Callbacks</h3>
          <button
            className="btn btn-primary btn-sm"
            onClick={handleAddCallback}
            title="Add Callback"
          >
            <Plus size={16} />
          </button>
        </div>
        <div className="tools-list">
          {callbacks.length === 0 ? (
            <div style={{ padding: '16px', color: 'var(--text-secondary)', fontSize: '14px' }}>
              No callbacks yet. Click + to add one.
            </div>
          ) : (
            callbacks.map(callback => (
              <div
                key={callback.id}
                className={`tool-item ${selectedCallbackId === callback.id ? 'selected' : ''}`}
                onClick={() => selectCallback(callback.id)}
              >
                <div style={{ flex: 1 }}>
                  <div className="tool-item-name">{callback.name}</div>
                  {callback.description && (
                    <div className="tool-item-type" style={{ fontSize: '11px', color: 'var(--text-secondary)', marginTop: '2px' }}>
                      {callback.description}
                    </div>
                  )}
                </div>
                <div className="tool-item-actions">
                  <button
                    className="btn btn-icon btn-sm"
                    onClick={(e) => handleDeleteCallback(callback.id, e)}
                    title="Delete"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>
            ))
          )}
        </div>
      </div>
      
      <div className="tools-editor">
        {selectedCallback ? (
          <>
            <div className="tools-editor-header">
              <h3>Edit Callback</h3>
              <button
                className="btn btn-primary btn-sm"
                onClick={handleSaveCallback}
              >
                <Save size={16} style={{ marginRight: '6px' }} />
                Save
              </button>
            </div>
            <div className="tools-editor-content" style={{ padding: '16px', overflowY: 'auto' }}>
              <div className="form-group">
                <label>Name</label>
                <input
                  type="text"
                  value={selectedCallback.name}
                  onChange={(e) => {
                    const name = e.target.value;
                    // Update both name and module_path to keep them in sync
                    updateCustomCallback(selectedCallback.id, { 
                      name,
                      module_path: `callbacks.${name.trim() || 'callback'}`
                    });
                    if (callbackNameError && isValidName(name)) {
                      setCallbackNameError(null);
                    }
                  }}
                  className={callbackNameError ? 'error' : ''}
                />
                {callbackNameError && (
                  <div className="error-message">{callbackNameError}</div>
                )}
              </div>
              
              <div className="form-group">
                <label>Description</label>
                <textarea
                  value={selectedCallback.description}
                  onChange={(e) => updateCustomCallback(selectedCallback.id, { description: e.target.value })}
                  rows={2}
                  placeholder="Describe what this callback does..."
                />
              </div>
              
              <div className="form-group">
                <label>Module Path</label>
                <input
                  type="text"
                  value={selectedCallback.module_path}
                  onChange={(e) => updateCustomCallback(selectedCallback.id, { module_path: e.target.value })}
                  placeholder="callbacks.custom"
                />
              </div>
              
              <div className="form-group">
                <label>State Keys Used</label>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginTop: '8px' }}>
                  {availableStateKeys.map(key => {
                    const isUsed = selectedCallback.state_keys_used.includes(key);
                    return (
                      <button
                        key={key}
                        type="button"
                        className={`btn btn-sm ${isUsed ? 'btn-primary' : 'btn-secondary'}`}
                        onClick={() => {
                          const newKeys = isUsed
                            ? selectedCallback.state_keys_used.filter(k => k !== key)
                            : [...selectedCallback.state_keys_used, key];
                          updateCustomCallback(selectedCallback.id, { state_keys_used: newKeys });
                        }}
                      >
                        <Key size={12} style={{ marginRight: '4px' }} />
                        {key}
                      </button>
                    );
                  })}
                </div>
                {availableStateKeys.length === 0 && (
                  <div style={{ color: 'var(--text-secondary)', fontSize: '12px', marginTop: '4px' }}>
                    No state keys defined in App Config
                  </div>
                )}
              </div>
              
              <div className="form-group">
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
                <label>Code</label>
                  <button 
                    className="btn btn-secondary btn-sm"
                    onClick={handleGenerateCallback}
                    disabled={isGeneratingCode || !selectedCallback.name}
                    title={!selectedCallback.name ? 'Add a name first' : 'Generate code using AI'}
                  >
                    {isGeneratingCode ? (
                      <>
                        <Loader size={14} className="spinning" />
                        Generating...
                      </>
                    ) : (
                      <>
                        <Sparkles size={14} />
                        Generate
                      </>
                    )}
                  </button>
                </div>
                <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '8px' }}>
                  AI will generate code based on the callback name, description, and selected state keys
                </div>
                <div className="code-editor-container">
                  <Editor
                    height="100%"
                    language="python"
                    theme="vs-dark"
                    value={editingCode}
                    onChange={(value) => setEditingCode(value || '')}
                    onMount={handleMonacoMount}
                    options={{
                      minimap: { enabled: false },
                      fontSize: 13,
                      fontFamily: "'JetBrains Mono', monospace",
                      lineNumbers: 'on',
                      scrollBeyondLastLine: false,
                      automaticLayout: true,
                    }}
                  />
                </div>
              </div>
            </div>
          </>
        ) : (
          <div style={{ 
            flex: 1, 
            display: 'flex', 
            alignItems: 'center', 
            justifyContent: 'center',
            color: 'var(--text-secondary)'
          }}>
            Select a callback to edit, or create a new one
          </div>
        )}
      </div>
    </div>
  );
}

