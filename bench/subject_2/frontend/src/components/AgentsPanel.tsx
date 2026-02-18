import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { Bot, Workflow, Repeat, GitBranch, Trash2, ChevronRight, ChevronDown, GripVertical, Wand2, Loader, Users, Wrench, Key, Plus } from 'lucide-react';
import { useStore } from '../hooks/useStore';
import type { AgentConfig, LlmAgentConfig, SequentialAgentConfig, LoopAgentConfig, ParallelAgentConfig, ToolConfig, AppModelConfig, ModelConfig, StateKeyConfig } from '../utils/types';
import AgentEditor from './AgentEditor';
import { generateAgentConfig } from '../utils/api';

const AGENT_TYPES = [
  { type: 'LlmAgent', label: 'LLM Agent', icon: Bot, color: '#00f5d4', description: 'AI-powered agent with model reasoning' },
  { type: 'SequentialAgent', label: 'Sequential', icon: Workflow, color: '#7b2cbf', description: 'Run sub-agents in order' },
  { type: 'LoopAgent', label: 'Loop', icon: Repeat, color: '#ffd93d', description: 'Repeat sub-agents until exit' },
  { type: 'ParallelAgent', label: 'Parallel', icon: GitBranch, color: '#ff6b6b', description: 'Run sub-agents simultaneously' },
];

function generateId() {
  return `agent_${Date.now().toString(36)}`;
}

function appModelToModelConfig(appModel: AppModelConfig): ModelConfig {
  return {
    provider: appModel.provider,
    model_name: appModel.model_name,
    api_base: appModel.api_base,
    temperature: appModel.temperature,
    max_output_tokens: appModel.max_output_tokens,
    top_p: appModel.top_p,
    top_k: appModel.top_k,
    fallbacks: []
  };
}

function createDefaultAgent(type: string, defaultModel?: AppModelConfig): AgentConfig {
  const id = generateId();
  // Default names must be valid (alphanumeric + underscore only)
  const defaultNames: Record<string, string> = {
    'LlmAgent': 'new_agent',
    'SequentialAgent': 'new_sequence',
    'LoopAgent': 'new_loop',
    'ParallelAgent': 'new_parallel',
  };
  const base = { id, name: defaultNames[type] || 'new_agent', description: '' };
  
  // Use default model from app config, or fall back to gemini
  const modelConfig: ModelConfig = defaultModel 
    ? appModelToModelConfig(defaultModel)
    : { provider: 'gemini', model_name: 'gemini-2.0-flash', fallbacks: [] };
  
  switch (type) {
    case 'LlmAgent':
      return {
        ...base,
        type: 'LlmAgent',
        model: modelConfig,
        instruction: '',
        include_contents: 'default',
        disallow_transfer_to_parent: false,
        disallow_transfer_to_peers: false,
        tools: [],
        sub_agents: [],
        output_key: defaultNames[type] || 'new_agent',  // Auto-assign output_key based on name
        before_agent_callbacks: [],
        after_agent_callbacks: [],
        before_model_callbacks: [],
        after_model_callbacks: [],
        before_tool_callbacks: [],
        after_tool_callbacks: [],
      } as LlmAgentConfig;
    case 'SequentialAgent':
      return { ...base, type: 'SequentialAgent', sub_agents: [], before_agent_callbacks: [], after_agent_callbacks: [] } as SequentialAgentConfig;
    case 'LoopAgent':
      return { ...base, type: 'LoopAgent', sub_agents: [], max_iterations: 10, before_agent_callbacks: [], after_agent_callbacks: [] } as LoopAgentConfig;
    case 'ParallelAgent':
      return { ...base, type: 'ParallelAgent', sub_agents: [], before_agent_callbacks: [], after_agent_callbacks: [] } as ParallelAgentConfig;
    default:
      throw new Error(`Unknown agent type: ${type}`);
  }
}

interface AgentsPanelProps {
  onSelectAgent?: (id: string | null) => void;
}

export default function AgentsPanel({ onSelectAgent }: AgentsPanelProps) {
  const { project, addAgent, removeAgent, updateAgent, updateProject, selectedAgentId, setSelectedAgentId, mcpServers } = useStore();
  const [expandedAgents, setExpandedAgents] = useState<Set<string>>(new Set());
  const [showQuickSetup, setShowQuickSetup] = useState(false);
  const [quickSetupDescription, setQuickSetupDescription] = useState('');
  // Track multiple concurrent generations: Map of temp ID -> description
  const [generatingAgents, setGeneratingAgents] = useState<Map<string, string>>(new Map());
  const [sidebarWidth, setSidebarWidth] = useState(380);
  const [isResizing, setIsResizing] = useState(false);
  const resizeRef = useRef<HTMLDivElement>(null);
  const [draggedAgentId, setDraggedAgentId] = useState<string | null>(null);
  const draggedAgentIdRef = useRef<string | null>(null);
  const [dropTarget, setDropTarget] = useState<{ agentId: string; type: 'sub_agent' | 'tool' } | null>(null);
  // For reordering: track insert position within a parent's sub_agents
  const [insertTarget, setInsertTarget] = useState<{ parentId: string; index: number } | null>(null);
  const agentsListRef = useRef<HTMLDivElement>(null);
  const scrollIntervalRef = useRef<number | null>(null);
  
  // Handle sidebar resize
  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    setIsResizing(true);
  }, []);
  
  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!isResizing) return;
      const newWidth = Math.min(Math.max(200, e.clientX), 600);
      setSidebarWidth(newWidth);
    };
    
    const handleMouseUp = () => {
      setIsResizing(false);
    };
    
    if (isResizing) {
      document.addEventListener('mousemove', handleMouseMove);
      document.addEventListener('mouseup', handleMouseUp);
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';
    }
    
    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };
  }, [isResizing]);
  
  // Expand all agents by default when project loads or agents change
  useEffect(() => {
    if (project) {
      const agentsWithSubAgents = project.agents
        .filter(a => 'sub_agents' in a && a.sub_agents.length > 0)
        .map(a => a.id);
      setExpandedAgents(new Set(agentsWithSubAgents));
    }
  }, [project?.id, project?.agents.length]);
  
  if (!project) return null;

  // Fast lookup for hierarchy checks (and safer cycle detection)
  const agentById = useMemo(() => new Map(project.agents.map(a => [a.id, a])), [project.agents]);
  
  // Start quick setup - runs in background, can be called multiple times concurrently
  function startQuickSetup() {
    if (!quickSetupDescription.trim() || !project) return;
    
    const tempId = `generating_${Date.now()}`;
    const description = quickSetupDescription;
    
    // Add to generating list and close modal immediately
    setGeneratingAgents(prev => new Map(prev).set(tempId, description));
    setShowQuickSetup(false);
    setQuickSetupDescription('');
    
    // Run generation in background
    generateAgentConfig(project.id, description)
      .then(result => {
        if (result.success && result.config) {
          const config = result.config;
          
          // Build tools array from the generated config
          const tools: ToolConfig[] = [];
          
          // Add builtin tools
          if (config.tools?.builtin) {
            for (const toolName of config.tools.builtin) {
              tools.push({ type: 'builtin', name: toolName });
            }
          }
          
          // Add MCP server tools
          if (config.tools?.mcp) {
            for (const mcpConfig of config.tools.mcp) {
              const serverConfig = mcpServers.find(s => s.name === mcpConfig.server);
              if (serverConfig) {
                tools.push({
                  type: 'mcp',
                  server: { ...serverConfig, tool_filter: mcpConfig.tools }
                });
              }
            }
          }
          
          // Add custom tools
          if (config.tools?.custom) {
            for (const toolName of config.tools.custom) {
              const customTool = project.custom_tools.find(t => t.name === toolName);
              if (customTool) {
                tools.push({ type: 'function', name: toolName, module_path: customTool.module_path });
              }
            }
          }
          
          // Add agent tools
          if (config.tools?.agents) {
            for (const agentId of config.tools.agents) {
              const targetAgent = project.agents.find(a => a.id === agentId);
              if (targetAgent) {
                tools.push({ type: 'agent', agent_id: agentId, name: targetAgent.name });
              }
            }
          }
          
          // Get default model
          const models = project.app.models || [];
          const defaultModel = models.find(m => m.id === project.app.default_model_id) || models[0];
          
          // Create the new agent
          const agentName = config.name || 'new_agent';
          const newAgent: LlmAgentConfig = {
            id: `agent_${Date.now().toString(36)}`,
            type: 'LlmAgent',
            name: agentName,
            description: config.description || '',
            instruction: config.instruction || '',
            output_key: config.output_key || agentName,  // Set output_key (defaults to agent name)
            model: defaultModel ? {
              provider: defaultModel.provider,
              model_name: defaultModel.model_name,
              api_base: defaultModel.api_base,
              temperature: defaultModel.temperature,
              max_output_tokens: defaultModel.max_output_tokens,
              top_p: defaultModel.top_p,
              top_k: defaultModel.top_k,
              fallbacks: []
            } : { provider: 'gemini', model_name: 'gemini-2.0-flash', fallbacks: [] },
            include_contents: 'default',
            disallow_transfer_to_parent: false,
            disallow_transfer_to_peers: false,
            tools,
            sub_agents: config.sub_agents || [],
            before_agent_callbacks: [],
            after_agent_callbacks: [],
            before_model_callbacks: [],
            after_model_callbacks: [],
            before_tool_callbacks: [],
            after_tool_callbacks: [],
          };
          
          addAgent(newAgent);
          setSelectedAgentId(newAgent.id);
          onSelectAgent?.(newAgent.id);
        } else {
          console.error('Failed to generate agent:', result.error);
        }
      })
      .catch(e => {
        console.error('Error generating agent:', e);
      })
      .finally(() => {
        setGeneratingAgents(prev => {
          const next = new Map(prev);
          next.delete(tempId);
          return next;
        });
      });
  }
  
  const selectedAgent = project.agents.find(a => a.id === selectedAgentId);
  
  function selectAgent(id: string) {
    setSelectedAgentId(id);
    onSelectAgent?.(id);
  }
  
  function handleAddAgent(type: string) {
    if (!project) return;
    const models = project.app.models || [];
    const defaultModel = models.find(m => m.id === project.app.default_model_id) || models[0];
    
    const agent = createDefaultAgent(type, defaultModel);
    addAgent(agent);
    selectAgent(agent.id);
  }
  
  function handleDeleteAgent(id: string, e: React.MouseEvent) {
    e.stopPropagation();
    if (!confirm('Delete this agent?')) return;
    removeAgent(id);
    if (selectedAgentId === id) {
      onSelectAgent?.(null);
    }
  }
  
  function toggleExpand(id: string) {
    const next = new Set(expandedAgents);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setExpandedAgents(next);
  }
  
  // State key management functions
  function addStateKey() {
    if (!project) return;
    const newKey: StateKeyConfig = {
      name: `state_key_${project.app.state_keys.length + 1}`,
      description: '',
      type: 'string',
      scope: 'session'
    };
    updateProject({ 
      app: { ...project.app, state_keys: [...project.app.state_keys, newKey] } 
    });
  }
  
  function updateStateKey(index: number, updates: Partial<StateKeyConfig>) {
    if (!project) return;
    const keys = [...project.app.state_keys];
    keys[index] = { ...keys[index], ...updates };
    updateProject({ 
      app: { ...project.app, state_keys: keys } 
    });
  }
  
  function removeStateKey(index: number) {
    if (!project) return;
    updateProject({ 
      app: { ...project.app, state_keys: project.app.state_keys.filter((_, i) => i !== index) } 
    });
  }
  
  // Auto-scroll while dragging near edges
  function handleListDragOver(e: React.DragEvent) {
    if (!agentsListRef.current || !draggedAgentIdRef.current) return;
    
    const rect = agentsListRef.current.getBoundingClientRect();
    const y = e.clientY - rect.top;
    const scrollZone = 60;
    const scrollSpeed = 8;
    
    if (y < scrollZone) {
      const speed = Math.max(1, scrollSpeed * (1 - y / scrollZone));
      agentsListRef.current.scrollTop -= speed;
    } else if (y > rect.height - scrollZone) {
      const speed = Math.max(1, scrollSpeed * (1 - (rect.height - y) / scrollZone));
      agentsListRef.current.scrollTop += speed;
    }
  }
  
  // Drag and drop handlers
  function handleDragStart(e: React.DragEvent, agentId: string) {
    e.dataTransfer.setData('text/plain', agentId);
    e.dataTransfer.effectAllowed = 'move';
    draggedAgentIdRef.current = agentId;
    requestAnimationFrame(() => setDraggedAgentId(agentId));
  }
  
  function handleDragEnd() {
    draggedAgentIdRef.current = null;
    setDraggedAgentId(null);
    setDropTarget(null);
    setInsertTarget(null);
    if (scrollIntervalRef.current) {
      cancelAnimationFrame(scrollIntervalRef.current);
      scrollIntervalRef.current = null;
    }
  }
  
  // Handle insert position for reordering sub-agents
  function handleInsertDragOver(e: React.DragEvent, parentId: string, index: number) {
    if (!project) return;
    e.preventDefault();
    e.stopPropagation();
    const currentDraggedId = draggedAgentIdRef.current;
    if (!currentDraggedId) return;
    
    const parentAgent = project.agents.find(a => a.id === parentId);
    if (!parentAgent || !('sub_agents' in parentAgent)) return;
    
    // Prevent creating cycles (dragging a parent into its own descendant)
    if (isInSubtree(currentDraggedId, parentId)) return;

    e.dataTransfer.dropEffect = 'move';
    setInsertTarget({ parentId, index });
    setDropTarget(null);
  }
  
  function handleInsertDrop(e: React.DragEvent, parentId: string, index: number) {
    if (!project) return;
    e.preventDefault();
    e.stopPropagation();
    
    const sourceAgentId = e.dataTransfer.getData('text/plain');
    if (!sourceAgentId) return;

    // Prevent creating cycles (dragging a parent into its own descendant)
    if (sourceAgentId === parentId || isInSubtree(sourceAgentId, parentId)) {
      setInsertTarget(null);
      return;
    }
    
    const parentAgent = project.agents.find(a => a.id === parentId);
    if (!parentAgent || !('sub_agents' in parentAgent)) return;
    
    // Remove from any existing parent
    project.agents.forEach(a => {
      if ('sub_agents' in a && a.sub_agents.includes(sourceAgentId)) {
        updateAgent(a.id, { sub_agents: a.sub_agents.filter(id => id !== sourceAgentId) });
      }
    });
    
    // Insert at the specified position
    const newSubAgents = [...parentAgent.sub_agents.filter(id => id !== sourceAgentId)];
    newSubAgents.splice(index, 0, sourceAgentId);
    updateAgent(parentId, { sub_agents: newSubAgents });
    
    setExpandedAgents(prev => new Set([...prev, parentId]));
    setDraggedAgentId(null);
    setInsertTarget(null);
  }
  
  function handleDragOver(e: React.DragEvent, targetAgentId: string, dropType: 'sub_agent' | 'tool') {
    if (!project) return;
    const currentDraggedId = draggedAgentIdRef.current;
    e.preventDefault();
    e.stopPropagation();
    
    if (currentDraggedId === targetAgentId) return;

    // Prevent creating cycles (dragging a parent into its own descendant)
    if (currentDraggedId && isInSubtree(currentDraggedId, targetAgentId)) return;
    
    e.dataTransfer.dropEffect = 'move';
    setDropTarget({ agentId: targetAgentId, type: dropType });
    setInsertTarget(null);
  }
  
  function handleDragLeave(e: React.DragEvent) {
    const relatedTarget = e.relatedTarget as HTMLElement;
    if (!relatedTarget || !e.currentTarget.contains(relatedTarget)) {
      setDropTarget(null);
    }
  }
  
  function handleDrop(e: React.DragEvent, targetAgentId: string, dropType: 'sub_agent' | 'tool') {
    if (!project) return;
    e.preventDefault();
    e.stopPropagation();
    
    const sourceAgentId = e.dataTransfer.getData('text/plain');
    if (!sourceAgentId || sourceAgentId === targetAgentId) return;

    // Prevent creating cycles (dragging a parent into its own descendant)
    if (dropType === 'sub_agent' && isInSubtree(sourceAgentId, targetAgentId)) {
      setDraggedAgentId(null);
      setDropTarget(null);
      setInsertTarget(null);
      return;
    }
    
    const targetAgent = project.agents.find(a => a.id === targetAgentId);
    const sourceAgent = project.agents.find(a => a.id === sourceAgentId);
    if (!targetAgent || !sourceAgent) return;
    
    if (dropType === 'sub_agent') {
      if ('sub_agents' in targetAgent) {
        project.agents.forEach(a => {
          if ('sub_agents' in a && a.sub_agents.includes(sourceAgentId)) {
            updateAgent(a.id, { sub_agents: a.sub_agents.filter(id => id !== sourceAgentId) });
          }
        });
        
        if (!targetAgent.sub_agents.includes(sourceAgentId)) {
          updateAgent(targetAgentId, { sub_agents: [...targetAgent.sub_agents, sourceAgentId] });
          setExpandedAgents(prev => new Set([...prev, targetAgentId]));
        }
      }
    } else if (dropType === 'tool') {
      if ('tools' in targetAgent) {
        const llmAgent = targetAgent as LlmAgentConfig;
        const alreadyAdded = llmAgent.tools.some(t => t.type === 'agent' && t.agent_id === sourceAgentId);
        if (!alreadyAdded) {
          updateAgent(targetAgentId, {
            tools: [...llmAgent.tools, { type: 'agent', agent_id: sourceAgentId, name: sourceAgent.name }]
          });
        }
      }
    }
    
    setDraggedAgentId(null);
    setDropTarget(null);
  }
  
  // Returns true if `searchId` is anywhere in `rootId`'s sub_agents subtree.
  // This is cycle-safe (it won't recurse infinitely even if the project is already cyclic).
  function isInSubtree(rootId: string, searchId: string): boolean {
    if (rootId === searchId) return true;
    const stack: string[] = [rootId];
    const visited = new Set<string>();
    while (stack.length) {
      const currentId = stack.pop()!;
      if (visited.has(currentId)) continue;
      visited.add(currentId);
      const agent = agentById.get(currentId);
      if (!agent || !('sub_agents' in agent)) continue;
      for (const subId of agent.sub_agents) {
        if (subId === searchId) return true;
        stack.push(subId);
      }
    }
    return false;
  }
  
  function getAgentIcon(type: string) {
    const config = AGENT_TYPES.find(t => t.type === type);
    return config ? config.icon : Bot;
  }
  
  function getAgentColor(type: string) {
    const config = AGENT_TYPES.find(t => t.type === type);
    return config ? config.color : '#888';
  }
  
  // Build a tree structure for agents with sub_agents
  function renderAgentTree(agents: AgentConfig[], depth = 0, path = new Set<string>()): React.ReactNode {
    return agents.map(agent => {
      const Icon = getAgentIcon(agent.type);
      const color = getAgentColor(agent.type);
      const hasSubAgents = 'sub_agents' in agent && agent.sub_agents.length > 0;
      const canHaveSubAgents = 'sub_agents' in agent;
      const canHaveTools = agent.type === 'LlmAgent';
      const isExpanded = expandedAgents.has(agent.id);
      const isDragging = draggedAgentId === agent.id;
      const isDropTargetSubAgent = dropTarget?.agentId === agent.id && dropTarget?.type === 'sub_agent';
      const isDropTargetTool = dropTarget?.agentId === agent.id && dropTarget?.type === 'tool';
      const isCycle = path.has(agent.id);
      const canRenderChildren = hasSubAgents && isExpanded && !isCycle;
      
      // Map over sub_agents to preserve order, not filter which loses order
      const subAgents = canRenderChildren && project
        ? agent.sub_agents.map(id => project.agents.find(a => a.id === id)).filter((a): a is AgentConfig => a !== undefined)
        : [];
      
      const showDropOverlay = draggedAgentId && draggedAgentId !== agent.id && (canHaveSubAgents || canHaveTools);
      
      return (
        <div key={agent.id} className="agent-tree-item">
          <div 
            className={`agent-item ${selectedAgentId === agent.id ? 'selected' : ''} ${isDragging ? 'dragging' : ''} ${showDropOverlay ? 'drop-target' : ''}`}
            onClick={() => selectAgent(agent.id)}
            style={{ paddingLeft: 12 + depth * 20 }}
            draggable
            onDragStart={(e) => handleDragStart(e, agent.id)}
            onDragEnd={handleDragEnd}
            onDragOver={(e) => {
              if (showDropOverlay) {
                e.preventDefault();
                e.stopPropagation();
              }
            }}
          >
            <div className="drag-handle">
              <GripVertical size={12} />
            </div>
            {hasSubAgents ? (
              <button 
                className="expand-btn"
                onClick={(e) => { e.stopPropagation(); toggleExpand(agent.id); }}
              >
                {isExpanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
              </button>
            ) : (
              <span style={{ width: 20 }} />
            )}
            <div className="agent-icon" style={{ background: color }}>
              <Icon size={14} />
            </div>
            <span className="agent-name">{agent.name}</span>
            <button className="delete-btn" onClick={(e) => handleDeleteAgent(agent.id, e)}>
              <Trash2 size={14} />
            </button>
            
            {/* Overlay drop zones - only show when hovering while dragging */}
            {showDropOverlay && (
              <div className="drop-overlay">
                {canHaveSubAgents && (
                  <div 
                    className={`drop-zone-overlay ${isDropTargetSubAgent ? 'active' : ''}`}
                    onDragOver={(e) => handleDragOver(e, agent.id, 'sub_agent')}
                    onDragLeave={handleDragLeave}
                    onDrop={(e) => handleDrop(e, agent.id, 'sub_agent')}
                  >
                    <Users size={12} />
                    <span>Sub-agent</span>
                  </div>
                )}
                {canHaveTools && (
                  <div 
                    className={`drop-zone-overlay ${isDropTargetTool ? 'active' : ''}`}
                    onDragOver={(e) => handleDragOver(e, agent.id, 'tool')}
                    onDragLeave={handleDragLeave}
                    onDrop={(e) => handleDrop(e, agent.id, 'tool')}
                  >
                    <Wrench size={12} />
                    <span>Tool</span>
                  </div>
                )}
              </div>
            )}
          </div>
          
          {canRenderChildren && (
            <div className="sub-agents">
              {/* Insert indicator at the top */}
              {draggedAgentId && draggedAgentId !== agent.id && (
                <div 
                  className={`insert-indicator ${insertTarget?.parentId === agent.id && insertTarget?.index === 0 ? 'active' : ''}`}
                  style={{ marginLeft: 12 + (depth + 1) * 20 }}
                  onDragOver={(e) => handleInsertDragOver(e, agent.id, 0)}
                  onDragLeave={() => setInsertTarget(null)}
                  onDrop={(e) => handleInsertDrop(e, agent.id, 0)}
                />
              )}
              {subAgents.map((subAgent, idx) => (
                <React.Fragment key={subAgent.id}>
                  {renderAgentTree([subAgent], depth + 1, new Set([...path, agent.id]))}
                  {/* Insert indicator after each sub-agent */}
                  {draggedAgentId && draggedAgentId !== agent.id && draggedAgentId !== subAgent.id && (
                    <div 
                      className={`insert-indicator ${insertTarget?.parentId === agent.id && insertTarget?.index === idx + 1 ? 'active' : ''}`}
                      style={{ marginLeft: 12 + (depth + 1) * 20 }}
                      onDragOver={(e) => handleInsertDragOver(e, agent.id, idx + 1)}
                      onDragLeave={() => setInsertTarget(null)}
                      onDrop={(e) => handleInsertDrop(e, agent.id, idx + 1)}
                    />
                  )}
                </React.Fragment>
              ))}
            </div>
          )}
        </div>
      );
    });
  }
  
  // Get root-level agents (not sub-agents of any other agent).
  // If a cycle exists, this set may include every agent, leaving no roots; fall back to showing all agents.
  const subAgentIds = new Set(project.agents.flatMap(a => 'sub_agents' in a ? a.sub_agents : []));
  const computedRootAgents = project.agents.filter(a => !subAgentIds.has(a.id));
  const rootAgents = computedRootAgents.length > 0 ? computedRootAgents : project.agents;
  
  return (
    <div className="agents-panel">
      <style>{`
        .agents-panel {
          display: flex;
          gap: 20px;
          height: calc(100vh - 120px);
        }
        
        .agents-sidebar {
          flex-shrink: 0;
          display: flex;
          flex-direction: column;
          background: var(--bg-secondary);
          border: 1px solid var(--border-color);
          border-radius: var(--radius-lg);
          overflow: hidden;
        }
        
        .sidebar-resizer {
          width: 6px;
          flex-shrink: 0;
          cursor: col-resize;
          background: transparent;
          transition: background 0.15s ease;
          display: flex;
          align-items: center;
          justify-content: center;
        }
        
        .sidebar-resizer:hover,
        .sidebar-resizer.resizing {
          background: var(--accent-primary);
        }
        
        .sidebar-resizer::after {
          content: '';
          width: 2px;
          height: 40px;
          background: var(--border-color);
          border-radius: 1px;
          opacity: 0.5;
          transition: opacity 0.15s ease;
        }
        
        .sidebar-resizer:hover::after,
        .sidebar-resizer.resizing::after {
          opacity: 0;
        }
        
        .sidebar-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 12px 16px;
          border-bottom: 1px solid var(--border-color);
        }
        
        .sidebar-header h3 {
          font-size: 14px;
          font-weight: 600;
        }
        
        .agents-list {
          flex: 1;
          overflow-y: auto;
          padding: 8px;
        }
        
        .state-keys-section {
          border-top: 1px solid var(--border-color);
          padding: 12px;
          background: var(--bg-tertiary);
        }
        
        .state-keys-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          margin-bottom: 8px;
        }
        
        .state-keys-header h4 {
          display: flex;
          align-items: center;
          gap: 6px;
          font-size: 12px;
          font-weight: 600;
          color: var(--text-secondary);
          text-transform: uppercase;
          letter-spacing: 0.5px;
          margin: 0;
        }
        
        .state-keys-header .btn-icon {
          padding: 4px;
          color: var(--text-muted);
          border-radius: var(--radius-sm);
          transition: all 0.15s ease;
        }
        
        .state-keys-header .btn-icon:hover {
          color: var(--text-primary);
          background: var(--bg-secondary);
        }
        
        .state-keys-list {
          display: flex;
          flex-direction: column;
          gap: 4px;
          max-height: 150px;
          overflow-y: auto;
        }
        
        .state-keys-list .empty-hint {
          font-size: 11px;
          color: var(--text-muted);
          margin: 0;
        }
        
        .state-key-item {
          display: flex;
          align-items: center;
          gap: 4px;
        }
        
        .state-key-item input {
          flex: 1;
          min-width: 0;
          padding: 4px 6px;
          font-size: 11px;
          background: var(--bg-secondary);
          border: 1px solid var(--border-color);
          border-radius: var(--radius-sm);
        }
        
        .state-key-item select {
          width: 50px;
          flex-shrink: 0;
          padding: 4px 2px;
          font-size: 10px;
          background: var(--bg-secondary);
          border: 1px solid var(--border-color);
          border-radius: var(--radius-sm);
        }
        
        .state-key-item .btn-icon {
          padding: 4px;
          color: var(--text-muted);
          flex-shrink: 0;
          opacity: 0;
          transition: all 0.15s ease;
        }
        
        .state-key-item:hover .btn-icon {
          opacity: 1;
        }
        
        .state-key-item .btn-icon.delete:hover {
          color: var(--error);
        }
        
        .agent-item {
          display: flex;
          align-items: center;
          gap: 5px;
          padding: 5px;
          border-radius: var(--radius-md);
          cursor: pointer;
          transition: all 0.15s ease;
        }
        
        .agent-item:hover {
          background: var(--bg-tertiary);
        }
        
        .agent-item.selected {
          background: var(--bg-hover);
          border: 1px solid var(--accent-primary);
        }
        
        .expand-btn {
          padding: 2px;
          color: var(--text-muted);
        }
        
        .agent-icon {
          display: flex;
          align-items: center;
          justify-content: center;
          width: 25px;
          height: 25px;
          border-radius: var(--radius-sm);
          color: white;
        }
        
        .agent-name {
          flex: 1;
          font-weight: 500;
          font-size: 13px;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        
        .agent-type {
          font-size: 11px;
          color: var(--text-muted);
          padding: 2px 6px;
          background: var(--bg-primary);
          border-radius: var(--radius-sm);
        }
        
        .delete-btn {
          padding: 4px;
          color: var(--text-muted);
          opacity: 0;
          transition: all 0.15s ease;
        }
        
        .agent-item:hover .delete-btn {
          opacity: 1;
        }
        
        .delete-btn:hover {
          color: var(--error);
        }
        
        .drag-handle {
          display: flex;
          align-items: center;
          justify-content: center;
          color: var(--text-muted);
          opacity: 0.4;
          cursor: grab;
          padding: 4px;
          margin-left: -10px;
          margin-right: 4px;
          border-radius: var(--radius-sm);
          transition: all 0.15s ease;
        }
        
        .agent-item:hover .drag-handle {
          opacity: 0.8;
          background: var(--bg-tertiary);
        }
        
        .agent-item:active .drag-handle {
          cursor: grabbing;
        }
        
        .agent-item.dragging {
          opacity: 0.5;
          background: var(--bg-tertiary);
          border: 1px dashed var(--accent-primary);
        }
        
        .agent-item.drop-target {
          position: relative;
        }
        
        .drop-overlay {
          position: absolute;
          top: 0;
          right: 8px;
          bottom: 0;
          display: flex;
          align-items: center;
          gap: 4px;
          opacity: 1;
          pointer-events: auto;
          z-index: 10;
        }
        
        .drop-zone-overlay {
          display: flex;
          align-items: center;
          gap: 4px;
          padding: 4px 8px;
          font-size: 10px;
          font-weight: 600;
          text-transform: uppercase;
          letter-spacing: 0.5px;
          color: var(--text-muted);
          background: var(--bg-secondary);
          border: 1px solid var(--border-color);
          border-radius: var(--radius-sm);
          cursor: pointer;
          transition: all 0.15s ease;
        }
        
        .drop-zone-overlay:hover,
        .drop-zone-overlay.active {
          border-color: var(--accent-primary);
          background: var(--accent-primary);
          color: white;
        }
        
        .insert-indicator {
          position: relative;
          height: 0;
          margin: 0;
        }
        
        /* Invisible drop target that extends above/below */
        .insert-indicator::before {
          content: '';
          position: absolute;
          left: 0;
          right: 0;
          top: -8px;
          bottom: -8px;
          z-index: 10;
        }
        
        /* Visual indicator line - only shows when active */
        .insert-indicator::after {
          content: '';
          position: absolute;
          left: 0;
          right: 12px;
          top: -1px;
          height: 2px;
          border-radius: 1px;
          background: transparent;
          transition: background 0.15s ease, box-shadow 0.15s ease;
          pointer-events: none;
        }
        
        .insert-indicator:hover::after,
        .insert-indicator.active::after {
          background: var(--accent-primary);
          box-shadow: 0 0 8px rgba(124, 58, 237, 0.5);
        }
        
        .sub-agents {
          position: relative;
        }

        .agent-editor-area {
          flex: 1;
          min-width: 0;
        }
        
        .empty-state {
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          height: 100%;
          color: var(--text-muted);
          text-align: center;
          padding: 40px;
        }
        
        .empty-state svg {
          margin-bottom: 16px;
          opacity: 0.3;
        }
        
        .type-selector {
          position: fixed;
          inset: 0;
          background: rgba(0, 0, 0, 0.6);
          display: flex;
          align-items: center;
          justify-content: center;
          z-index: 100;
        }
        
        .type-selector-content {
          background: var(--bg-secondary);
          border: 1px solid var(--border-color);
          border-radius: var(--radius-lg);
          padding: 24px;
          max-width: 500px;
          width: 100%;
        }
        
        .type-selector h2 {
          margin-bottom: 20px;
        }
        
        .header-buttons {
          display: flex;
          gap: 4px;
        }
        
        .quick-add-btn {
          display: flex;
          align-items: center;
          justify-content: center;
          width: 28px;
          height: 28px;
          border-radius: var(--radius-sm);
          color: white;
          border: none;
          cursor: pointer;
          transition: all 0.15s ease;
          opacity: 0.85;
        }
        
        .quick-add-btn:hover {
          opacity: 1;
          transform: scale(1.05);
        }
        
        .generating-badge {
          display: inline-flex;
          align-items: center;
          gap: 4px;
          margin-left: 8px;
          padding: 2px 6px;
          background: var(--accent-primary);
          color: white;
          border-radius: 10px;
          font-size: 11px;
          font-weight: 500;
        }
        
        .quick-setup-content {
          background: var(--bg-secondary);
          border: 1px solid var(--border-color);
          border-radius: var(--radius-lg);
          padding: 24px;
          max-width: 600px;
          width: 100%;
        }
        
        .quick-setup-content h2 {
          display: flex;
          align-items: center;
          gap: 10px;
          margin-bottom: 12px;
        }
        
        .quick-setup-content h2 svg {
          color: var(--accent-primary);
        }
        
        .quick-setup-desc {
          color: var(--text-secondary);
          margin-bottom: 16px;
          font-size: 14px;
        }
        
        .quick-setup-form textarea {
          width: 100%;
          min-height: 100px;
          margin-bottom: 16px;
          font-size: 14px;
          line-height: 1.5;
        }
        
        .quick-setup-info {
          background: var(--bg-tertiary);
          border-radius: var(--radius-md);
          padding: 12px 16px;
          margin-bottom: 16px;
          font-size: 13px;
        }
        
        .quick-setup-info strong {
          display: block;
          margin-bottom: 8px;
          color: var(--text-primary);
        }
        
        .quick-setup-info ul {
          margin: 0;
          padding-left: 20px;
          color: var(--text-muted);
        }
        
        .quick-setup-info li {
          margin-bottom: 4px;
        }
        
        .quick-setup-actions {
          display: flex;
          justify-content: flex-end;
          gap: 12px;
        }
        
        .spin {
          animation: spin 1s linear infinite;
        }
        
        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
        
        .type-options {
          display: grid;
          grid-template-columns: repeat(2, 1fr);
          gap: 12px;
        }
        
        .type-option {
          display: flex;
          align-items: flex-start;
          gap: 12px;
          padding: 16px;
          background: var(--bg-tertiary);
          border: 1px solid var(--border-color);
          border-radius: var(--radius-md);
          cursor: pointer;
          transition: all 0.15s ease;
          text-align: left;
        }
        
        .type-option:hover {
          border-color: var(--accent-primary);
          background: var(--bg-hover);
        }
        
        .type-option-icon {
          display: flex;
          align-items: center;
          justify-content: center;
          width: 40px;
          height: 40px;
          border-radius: var(--radius-md);
          color: white;
          flex-shrink: 0;
        }
        
        .type-option-info h4 {
          margin-bottom: 4px;
        }
        
        .type-option-info p {
          font-size: 12px;
          color: var(--text-muted);
        }
      `}</style>
      
      <aside className="agents-sidebar" style={{ width: sidebarWidth }}>
        <div className="sidebar-header">
          <h3>Agents ({project.agents.length}){generatingAgents.size > 0 && <span className="generating-badge"><Loader size={12} className="spin" /> {generatingAgents.size}</span>}</h3>
          <div className="header-buttons">
            {AGENT_TYPES.map(({ type, icon: Icon, color }) => (
              <button 
                key={type}
                className="quick-add-btn"
                style={{ background: color }}
                onClick={() => handleAddAgent(type)}
                title={`Add ${type}`}
              >
                <Icon size={14} />
              </button>
            ))}
            <button 
              className="btn btn-secondary btn-sm" 
              onClick={() => setShowQuickSetup(true)}
              title="AI-powered agent setup"
            >
              <Wand2 size={14} />
            </button>
          </div>
        </div>
        <div 
          className="agents-list" 
          ref={agentsListRef}
          onDragOver={handleListDragOver}
        >
          {project.agents.length === 0 ? (
            <div className="empty-state">
              <Bot size={32} />
              <p>No agents yet</p>
            </div>
          ) : (
            renderAgentTree(rootAgents)
          )}
        </div>
        
        {/* State Keys Section */}
        <div className="state-keys-section">
          <div className="state-keys-header">
            <h4><Key size={14} /> State Keys</h4>
            <button className="btn-icon" onClick={addStateKey} title="Add state key">
              <Plus size={14} />
            </button>
          </div>
          <div className="state-keys-list">
            {project.app.state_keys.length === 0 ? (
              <p className="empty-hint">Auto-created when you set output_key</p>
            ) : (
              project.app.state_keys.map((key, index) => (
                <div key={index} className="state-key-item">
                  <input
                    type="text"
                    value={key.name}
                    onChange={(e) => updateStateKey(index, { name: e.target.value })}
                    placeholder="Key name"
                  />
                  <select
                    value={key.type}
                    onChange={(e) => updateStateKey(index, { type: e.target.value as any })}
                  >
                    <option value="string">str</option>
                    <option value="number">num</option>
                    <option value="boolean">bool</option>
                    <option value="object">obj</option>
                    <option value="array">arr</option>
                  </select>
                  <button 
                    className="btn-icon delete" 
                    onClick={() => removeStateKey(index)}
                    title="Remove state key"
                  >
                    <Trash2 size={12} />
                  </button>
                </div>
              ))
            )}
          </div>
        </div>
      </aside>
      
      <div 
        ref={resizeRef}
        className={`sidebar-resizer ${isResizing ? 'resizing' : ''}`}
        onMouseDown={handleMouseDown}
      />
      
      <div className="agent-editor-area">
        {selectedAgent ? (
          <AgentEditor agent={selectedAgent} />
        ) : (
          <div className="empty-state card">
            <Bot size={48} />
            <p>Select an agent to edit<br />or create a new one</p>
          </div>
        )}
      </div>
      
      {showQuickSetup && (
        <div className="type-selector" onClick={() => setShowQuickSetup(false)}>
          <div className="quick-setup-content" onClick={e => e.stopPropagation()}>
            <h2><Wand2 size={20} /> Quick Agent Setup</h2>
            <p className="quick-setup-desc">
              Describe what you want this agent to do. Runs in the background - you can start multiple!
            </p>
            
            <div className="quick-setup-form">
              <textarea
                value={quickSetupDescription}
                onChange={(e) => setQuickSetupDescription(e.target.value)}
                placeholder="Example: An agent that searches the web for information and summarizes the results. It should be able to search Google and handle multiple queries in parallel."
                rows={5}
                autoFocus
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && quickSetupDescription.trim()) {
                    startQuickSetup();
                  }
                }}
              />
              
              <div className="quick-setup-info">
                <strong>Available resources:</strong>
                <ul>
                  <li>{project.app.state_keys.length} state keys</li>
                  <li>{mcpServers.length} MCP servers</li>
                  <li>{project.custom_tools.length} custom tools</li>
                  <li>{project.agents.length} existing agents</li>
                </ul>
              </div>
              
              <div className="quick-setup-actions">
                <button 
                  className="btn btn-secondary"
                  onClick={() => setShowQuickSetup(false)}
                >
                  Cancel
                </button>
                <button 
                  className="btn btn-primary"
                  onClick={startQuickSetup}
                  disabled={!quickSetupDescription.trim()}
                >
                  <Wand2 size={14} />
                  Generate (⌘↵)
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

