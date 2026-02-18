import { useEffect, useState, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { ArrowLeft, Settings, Bot, Wrench, TestTube, FileCode, Code, Save, Layers, Brain, Play, Loader2 } from 'lucide-react';
import { useStore } from '../hooks/useStore';
import { getProject, updateProject as apiUpdateProject, api } from '../utils/api';
import type { AppModelConfig } from '../utils/types';
import AppConfigPanel from './AppConfigPanel';
import AgentsPanel from './AgentsPanel';
import ToolsPanel from './ToolsPanel';
import CallbacksPanel from './CallbacksPanel';
import RunPanel from './RunPanel';
import { SkillSetsPanel } from './SkillSetsPanel';
import EvalPanel from './EvalPanel';
import YamlPanel from './YamlPanel';
import CodePanel from './CodePanel';

const tabs = [
  { id: 'app' as const, label: 'App', icon: Settings },
  { id: 'agents' as const, label: 'Agents', icon: Bot },
  { id: 'tools' as const, label: 'Tools', icon: Wrench },
  { id: 'callbacks' as const, label: 'Callbacks', icon: Code },
  { id: 'run' as const, label: 'Run', icon: Layers },
  // { id: 'skillsets' as const, label: 'SkillSets', icon: Brain },
  { id: 'eval' as const, label: 'Evaluate', icon: TestTube },
  { id: 'yaml' as const, label: 'YAML', icon: FileCode },
  { id: 'code' as const, label: 'Code', icon: Code },
];

type TabId = 'app' | 'agents' | 'tools' | 'callbacks' | 'run' | 'skillsets' | 'eval' | 'yaml' | 'code';
const validTabs: TabId[] = ['app', 'agents', 'tools', 'callbacks', 'run', 'skillsets', 'eval', 'yaml', 'code'];

export default function ProjectEditor() {
  const { projectId, tab, itemId } = useParams<{ projectId: string; tab?: string; itemId?: string }>();
  const navigate = useNavigate();
  const { project, setProject, activeTab, setActiveTab, hasUnsavedChanges, setHasUnsavedChanges, selectedAgentId, setSelectedAgentId, selectedToolId, setSelectedToolId } = useStore();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ passed: number; total: number } | null>(null);
  const initialLoadRef = useRef(true);
  const lastSavedProjectRef = useRef<string | null>(null);
  
  // Sync tab from URL to store
  useEffect(() => {
    if (tab && validTabs.includes(tab as TabId)) {
      setActiveTab(tab as TabId);
    } else if (!tab && projectId) {
      // No tab in URL, redirect to current active tab
      navigate(`/project/${projectId}/${activeTab}`, { replace: true });
    }
  }, [tab, projectId]);
  
  // Sync itemId from URL to store (for agents/tools)
  useEffect(() => {
    if (tab === 'agents' && itemId) {
      setSelectedAgentId(itemId);
    } else if (tab === 'tools' && itemId) {
      setSelectedToolId(itemId);
    }
  }, [tab, itemId]);
  
  // Update URL when tab changes
  function handleTabChange(newTab: TabId) {
    setActiveTab(newTab);
    // Include item ID if switching to agents/tools and one is selected
    if (newTab === 'agents' && selectedAgentId) {
      navigate(`/project/${projectId}/${newTab}/${selectedAgentId}`, { replace: true });
    } else if (newTab === 'tools' && selectedToolId) {
      navigate(`/project/${projectId}/${newTab}/${selectedToolId}`, { replace: true });
    } else {
      navigate(`/project/${projectId}/${newTab}`, { replace: true });
    }
  }
  
  // Helper to update URL with item ID
  function updateItemInUrl(newItemId: string | null) {
    if (newItemId) {
      navigate(`/project/${projectId}/${activeTab}/${newItemId}`, { replace: true });
    } else {
      navigate(`/project/${projectId}/${activeTab}`, { replace: true });
    }
  }
  
  useEffect(() => {
    if (projectId) {
      loadProject(projectId);
    }
    return () => {
      setProject(null);
      setHasUnsavedChanges(false);
    };
  }, [projectId]);
  
  async function loadProject(id: string) {
    initialLoadRef.current = true;
    try {
      const data = await getProject(id);
      setProject(data);
      lastSavedProjectRef.current = JSON.stringify(data);
      setHasUnsavedChanges(false);
    } catch (error) {
      console.error('Failed to load project:', error);
      navigate('/');
    } finally {
      setLoading(false);
      // Reset initial load flag after a small delay to allow the project useEffect to run
      setTimeout(() => {
        initialLoadRef.current = false;
      }, 100);
    }
  }
  
  async function handleSave() {
    if (!project) return;
    
    setSaving(true);
    try {
      // Don't send eval_sets - they're managed separately by EvalPanel
      const { eval_sets, ...projectWithoutEvalSets } = project;
      await apiUpdateProject(project.id, projectWithoutEvalSets);
      lastSavedProjectRef.current = JSON.stringify(project);
      setHasUnsavedChanges(false);
    } catch (error) {
      console.error('Failed to save project:', error);
    } finally {
      setSaving(false);
    }
  }
  
  async function handleTest() {
    if (!project) return;
    
    setTesting(true);
    setTestResult(null);
    window.dispatchEvent(new CustomEvent('eval-tests-started'));
    
    try {
      // Run all eval sets and collect results
      let totalPassed = 0;
      let totalCases = 0;
      const allCaseResults: any[] = [];
      const evalSetNames: string[] = [];
      
      for (const evalSet of project.eval_sets || []) {
        if (evalSet.eval_cases.length === 0) continue;
        
        const response = await api.post(
          `/projects/${project.id}/eval-sets/${evalSet.id}/run`,
          {}
        );
        
        if (response.result) {
          totalPassed += response.result.passed_cases || 0;
          totalCases += response.result.total_cases || 0;
          
          // Collect case results from this eval set
          if (response.result.case_results) {
            allCaseResults.push(...response.result.case_results);
          }
          evalSetNames.push(response.result.eval_set_name || evalSet.name || evalSet.id);
        }
      }
      
      // Save combined batch result to history
      if (allCaseResults.length > 0) {
        const batchResult = {
          id: Date.now().toString(36) + Math.random().toString(36).substr(2, 5),
          eval_set_id: 'batch',  // Special marker for batch runs
          eval_set_name: evalSetNames.length > 1 
            ? `All Tests (${evalSetNames.length} sets)` 
            : evalSetNames[0] || 'All Tests',
          started_at: Date.now() / 1000,
          completed_at: Date.now() / 1000,
          total_cases: totalCases,
          passed_cases: totalPassed,
          failed_cases: totalCases - totalPassed,
          case_results: allCaseResults,
        };
        
        try {
          await api.post(`/projects/${project.id}/eval-history`, batchResult);
        } catch (err) {
          console.warn('Failed to save batch eval run to history:', err);
        }
      }
      
      setTestResult({ passed: totalPassed, total: totalCases });
      
      // Notify EvalPanel to refresh its state
      window.dispatchEvent(new CustomEvent('eval-tests-completed'));
      
      // Clear result after 5 seconds
      setTimeout(() => setTestResult(null), 5000);
    } catch (error) {
      console.error('Failed to run tests:', error);
      setTestResult({ passed: 0, total: -1 }); // -1 indicates error
      setTimeout(() => setTestResult(null), 5000);
    } finally {
      setTesting(false);
    }
  }
  
  // Sync agents when app models change
  const prevAppModelsRef = useRef<AppModelConfig[] | null>(null);
  useEffect(() => {
    if (project && !initialLoadRef.current && prevAppModelsRef.current) {
      const currentModels = project.app.models || [];
      const prevModels = prevAppModelsRef.current || [];
      
      // Check if any app models changed
      const modelsChanged = currentModels.some((model, idx) => {
        const prevModel = prevModels.find(m => m.id === model.id);
        if (!prevModel) return false;
        return (
          prevModel.provider !== model.provider ||
          prevModel.model_name !== model.model_name ||
          prevModel.api_base !== model.api_base ||
          prevModel.temperature !== model.temperature ||
          prevModel.max_output_tokens !== model.max_output_tokens ||
          prevModel.top_p !== model.top_p ||
          prevModel.top_k !== model.top_k
        );
      });
      
      // If models changed, update all agents that reference them
      if (modelsChanged) {
        const defaultModelId = project.app.default_model_id;
        const updatedAgents = project.agents.map(agent => {
          if (agent.type === 'LlmAgent' && agent.model) {
            // Check if agent uses an app model via _appModelId marker
            const appModelId = agent.model._appModelId;
            if (appModelId) {
              const appModel = currentModels.find(m => m.id === appModelId);
              if (appModel) {
                // Update agent's model config to match the app model
                return {
                  ...agent,
                  model: {
                    provider: appModel.provider,
                    model_name: appModel.model_name,
                    api_base: appModel.api_base,
                    temperature: appModel.temperature,
                    max_output_tokens: appModel.max_output_tokens,
                    top_p: appModel.top_p,
                    top_k: appModel.top_k,
                    fallbacks: [],
                    _appModelId: appModelId,
                  },
                };
              }
            } else if (defaultModelId) {
              // Check if agent is using the default model (legacy - no marker)
              // Match by comparing config values
              const defaultModel = currentModels.find(m => m.id === defaultModelId);
              if (defaultModel && 
                  agent.model.provider === defaultModel.provider &&
                  agent.model.model_name === defaultModel.model_name &&
                  agent.model.api_base === defaultModel.api_base) {
                // This agent appears to be using the default model, update it
                return {
                  ...agent,
                  model: {
                    provider: defaultModel.provider,
                    model_name: defaultModel.model_name,
                    api_base: defaultModel.api_base,
                    temperature: defaultModel.temperature,
                    max_output_tokens: defaultModel.max_output_tokens,
                    top_p: defaultModel.top_p,
                    top_k: defaultModel.top_k,
                    fallbacks: [],
                    _appModelId: defaultModelId, // Add marker for future syncs
                  },
                };
              }
            }
          }
          return agent;
        });
        
        // Only update if any agents actually changed
        const agentsChanged = updatedAgents.some((agent, idx) => 
          JSON.stringify(agent) !== JSON.stringify(project.agents[idx])
        );
        
        if (agentsChanged) {
          setProject({
            ...project,
            agents: updatedAgents,
          });
        }
      }
    }
    
    // Update ref for next comparison
    if (project) {
      prevAppModelsRef.current = project.app.models || [];
    }
  }, [project?.app.models, project, setProject]);
  
  // Auto-save on changes (debounced)
  const saveTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  
  useEffect(() => {
    if (project && !initialLoadRef.current && lastSavedProjectRef.current) {
      const currentState = JSON.stringify(project);
      if (currentState !== lastSavedProjectRef.current) {
        setHasUnsavedChanges(true);
        
        // Clear existing timeout
        if (saveTimeoutRef.current) {
          clearTimeout(saveTimeoutRef.current);
        }
        
        // Auto-save after 500ms of no changes (debounce)
        saveTimeoutRef.current = setTimeout(async () => {
          try {
            // Don't send eval_sets - they're managed separately by EvalPanel
            const { eval_sets, ...projectWithoutEvalSets } = project;
            await apiUpdateProject(project.id, projectWithoutEvalSets);
            lastSavedProjectRef.current = JSON.stringify(project);
            setHasUnsavedChanges(false);
          } catch (error) {
            console.error('Auto-save failed:', error);
            // Don't clear hasUnsavedChanges on error - user can manually save
          }
        }, 500);
      }
    }
    
    // Cleanup timeout on unmount
    return () => {
      if (saveTimeoutRef.current) {
        clearTimeout(saveTimeoutRef.current);
      }
    };
  }, [project]);
  
  if (loading) {
    return (
      <div className="loading-screen">
        <style>{`
          .loading-screen {
            height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            color: var(--text-muted);
          }
        `}</style>
        Loading project...
      </div>
    );
  }
  
  if (!project) {
    return null;
  }
  
  return (
    <div className="project-editor">
      <style>{`
        .project-editor {
          height: 100vh;
          display: flex;
          flex-direction: column;
          overflow: hidden;
        }
        
        .top-bar {
          display: flex;
          align-items: center;
          gap: 16px;
          padding: 8px 16px;
          background: var(--bg-secondary);
          border-bottom: 1px solid var(--border-color);
        }
        
        .top-bar-left {
          display: flex;
          align-items: center;
          gap: 12px;
          flex-shrink: 0;
        }
        
        .back-btn {
          display: flex;
          align-items: center;
          gap: 8px;
          color: var(--text-secondary);
          padding: 6px 12px;
          border-radius: var(--radius-md);
          transition: all 0.2s ease;
        }
        
        .back-btn:hover {
          color: var(--text-primary);
          background: var(--bg-tertiary);
        }
        
        .project-name {
          font-size: 1.25rem;
          font-weight: 600;
        }
        
        .top-bar-right {
          display: flex;
          align-items: center;
          gap: 12px;
          flex-shrink: 0;
          margin-left: auto;
        }
        
        .save-indicator {
          font-size: 12px;
          color: var(--text-muted);
        }
        
        .tabs-bar {
          display: flex;
          align-items: center;
          gap: 2px;
        }
        
        .tab-btn {
          display: flex;
          align-items: center;
          gap: 6px;
          padding: 6px 12px;
          border-radius: var(--radius-md);
          color: var(--text-secondary);
          font-weight: 500;
          font-size: 13px;
          transition: all 0.2s ease;
          white-space: nowrap;
        }
        
        .tab-btn svg {
          width: 14px;
          height: 14px;
        }
        
        .tab-btn:hover {
          color: var(--text-primary);
          background: var(--bg-secondary);
        }
        
        .tab-btn.active {
          color: var(--bg-primary);
          background: var(--accent-primary);
        }
        
        .tab-btn.active svg {
          color: var(--bg-primary);
        }
        
        .main-content {
          flex: 1;
          overflow: auto;
          padding: 20px;
        }
      `}</style>
      
      <header className="top-bar">
        <div className="top-bar-left">
          <button className="back-btn" onClick={() => navigate('/')}>
            <ArrowLeft size={18} />
            Project
          </button>
          <h1 className="project-name">{project.name}</h1>
        </div>
        <nav className="tabs-bar">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              className={`tab-btn ${activeTab === tab.id ? 'active' : ''}`}
              onClick={() => handleTabChange(tab.id)}
            >
              <tab.icon size={14} />
              {tab.label}
            </button>
          ))}
        </nav>
        <div className="top-bar-right">
          <button 
            className={`btn ${testResult ? (testResult.total === -1 ? 'btn-error' : testResult.passed === testResult.total ? 'btn-success' : 'btn-warning') : 'btn-secondary'}`}
            onClick={handleTest}
            disabled={testing || !project?.eval_sets?.some(es => es.eval_cases.length > 0)}
            title={project?.eval_sets?.some(es => es.eval_cases.length > 0) ? 'Run all evaluation tests' : 'No test cases defined'}
            style={{ marginRight: 8 }}
          >
            {testing ? <Loader2 size={16} className="spin" /> : <Play size={16} />}
            {testing ? 'Testing...' : testResult ? (testResult.total === -1 ? 'Error' : `${testResult.passed}/${testResult.total}`) : 'Test'}
          </button>
          <button 
            className="btn btn-primary" 
            onClick={handleSave}
            disabled={saving}
          >
            <Save size={16} />
            {saving ? 'Saving...' : 'Save'}
          </button>
        </div>
      </header>
      
      <main className="main-content">
        {activeTab === 'app' && <AppConfigPanel />}
        {activeTab === 'agents' && <AgentsPanel onSelectAgent={updateItemInUrl} />}
        {activeTab === 'tools' && <ToolsPanel onSelectTool={updateItemInUrl} />}
        {activeTab === 'callbacks' && <CallbacksPanel onSelectCallback={updateItemInUrl} />}
        {activeTab === 'run' && <RunPanel />}
        {activeTab === 'skillsets' && <SkillSetsPanel />}
        {activeTab === 'eval' && <EvalPanel />}
        {activeTab === 'yaml' && <YamlPanel />}
        {activeTab === 'code' && <CodePanel />}
      </main>
    </div>
  );
}

