import { useState, useEffect, useCallback, useRef } from 'react';
import { 
  Plus, Play, FolderTree, FileCheck, Trash2, ChevronRight, ChevronDown, 
  CheckCircle, XCircle, Clock, AlertCircle, Settings, Target, Percent,
  MessageSquare, RefreshCw, Download, Upload, ExternalLink, Link2, Code, Copy
} from 'lucide-react';
import Editor from '@monaco-editor/react';
import { useStore } from '../hooks/useStore';
import { api } from '../utils/api';

// ADK Prebuilt Metrics
type EvalMetricType = 
  | 'tool_trajectory_avg_score'
  | 'response_match_score'
  | 'response_evaluation_score'
  | 'final_response_match_v2'
  | 'safety_v1'
  | 'hallucinations_v1'
  | 'rubric_based_final_response_quality_v1'
  | 'rubric_based_tool_use_quality_v1';

const METRIC_INFO: Record<EvalMetricType, { name: string; description: string; requiresJudge: boolean; scale: [number, number] }> = {
  tool_trajectory_avg_score: { 
    name: 'Tool Trajectory', 
    description: 'Did the agent call the right tools in the expected order?',
    requiresJudge: false,
    scale: [0, 1],
  },
  response_match_score: { 
    name: 'Response Match (ROUGE-1)', 
    description: 'Does the response contain expected text? (fuzzy word matching)',
    requiresJudge: false,
    scale: [0, 1],
  },
  response_evaluation_score: { 
    name: 'Response Evaluation (LLM)', 
    description: 'LLM-judged semantic match of final response',
    requiresJudge: true,
    scale: [1, 5],  // 1-5 scale
  },
  final_response_match_v2: { 
    name: 'Response Quality v2 (LLM)', 
    description: 'Enhanced LLM-judged response quality check',
    requiresJudge: true,
    scale: [0, 1],
  },
  safety_v1: { 
    name: 'Safety', 
    description: 'Is the response safe and harmless? (Vertex AI)',
    requiresJudge: true,
    scale: [0, 1],
  },
  hallucinations_v1: { 
    name: 'Hallucination Detection', 
    description: 'Are all claims supported by context? No false information?',
    requiresJudge: true,
    scale: [0, 1],
  },
  rubric_based_final_response_quality_v1: { 
    name: 'Rubric: Response Quality', 
    description: 'Custom rubric-based quality assessment of responses',
    requiresJudge: true,
    scale: [0, 1],
  },
  rubric_based_tool_use_quality_v1: { 
    name: 'Rubric: Tool Use Quality', 
    description: 'Custom rubric-based assessment of tool usage',
    requiresJudge: true,
    scale: [0, 1],
  },
};

// Format score based on metric type
const formatMetricScore = (metric: string, score?: number | null, threshold?: number | null) => {
  if (score === null || score === undefined) return { value: '-', comparison: '' };
  
  const info = METRIC_INFO[metric as EvalMetricType];
  const scale = info?.scale || [0, 1];
  
  if (scale[0] === 1 && scale[1] === 5) {
    // 1-5 scale - show as raw number
    const thresholdVal = threshold ?? 3.5;
    return { 
      value: score.toFixed(1), 
      comparison: `${thresholdVal.toFixed(1)} / ${scale[1].toFixed(1)}` 
    };
  } else {
    // 0-1 scale - show as percentage
    const thresholdVal = threshold ?? 0.7;
    return { 
      value: `${Math.round(score * 100)}%`, 
      comparison: `${Math.round(thresholdVal * 100)}% min` 
    };
  }
};

interface JudgeModelOptions {
  judge_model: string;
  num_samples: number;
}

interface EvalCriterion {
  threshold: number;
  judge_model_options?: JudgeModelOptions;
}

interface EvalMetricConfig {
  metric: EvalMetricType;
  enabled: boolean;
  criterion: EvalCriterion;
}

interface ExpectedToolCall {
  name: string;
  args?: Record<string, any>;
  args_match_mode: 'exact' | 'subset' | 'ignore';
}

interface Rubric {
  rubric: string;
}

interface EvalInvocation {
  id: string;
  user_message: string;
  expected_response?: string;
  expected_tool_calls: ExpectedToolCall[];
  tool_trajectory_match_type: 'exact' | 'in_order' | 'any_order';
  rubrics: Rubric[];
}

interface EvalConfig {
  metrics: EvalMetricConfig[];
  default_trajectory_match_type: 'exact' | 'in_order' | 'any_order';
  num_runs: number;
  judge_model?: string;  // LLM judge model - if empty, uses App's default model
}

// LLM Judges that can be enabled per test case
interface EnabledMetric {
  metric: EvalMetricType;
  threshold: number;
}

interface EvalCase {
  id: string;
  name: string;
  description: string;
  invocations: EvalInvocation[];
  initial_state: Record<string, any>;
  expected_final_state?: Record<string, any>;
  rubrics: Rubric[];
  enabled_metrics: EnabledMetric[];
  tags: string[];
  target_agent?: string;  // Optional: test a specific sub-agent instead of root_agent
}

interface EvalSet {
  id: string;
  name: string;
  description: string;
  eval_cases: EvalCase[];
  eval_config: EvalConfig;
  created_at: number;
  updated_at: number;
}

interface MetricResult {
  metric: string;
  score?: number;
  threshold: number;
  passed: boolean;
  details?: string;
  rationale?: string;  // LLM judge reasoning/explanation
  error?: string;
}

interface InvocationResult {
  invocation_id: string;
  user_message: string;
  actual_response?: string;
  actual_tool_calls: { name: string; args: Record<string, any> }[];
  expected_response?: string;
  expected_tool_calls: { name: string; args: Record<string, any> }[];
  metric_results: MetricResult[];
  rubric_results: Record<string, any>[];
  passed: boolean;
  error?: string;
  // Token usage
  input_tokens?: number;
  output_tokens?: number;
}

interface EvalCaseResult {
  eval_case_id: string;
  eval_case_name: string;
  session_id: string;
  metric_results: MetricResult[];
  passed: boolean;
  invocation_results: InvocationResult[];
  duration_ms: number;
  error?: string;
  // Token usage
  total_input_tokens?: number;
  total_output_tokens?: number;
  total_tokens?: number;
}

interface EvalSetResult {
  id: string;
  eval_set_id: string;
  eval_set_name: string;
  total_cases: number;
  passed_cases: number;
  failed_cases: number;
  error_cases: number;
  metric_pass_rates: Record<string, number>;
  metric_avg_scores: Record<string, number>;
  overall_pass_rate: number;
  case_results: EvalCaseResult[];
  duration_ms: number;
}

// Default eval config with most useful metrics
const DEFAULT_EVAL_CONFIG: EvalConfig = {
  metrics: [
    { metric: 'tool_trajectory_avg_score', enabled: true, criterion: { threshold: 1.0 } },
    { metric: 'response_match_score', enabled: true, criterion: { threshold: 0.7 } },
  ],
  default_trajectory_match_type: 'in_order',
  num_runs: 1
};

function generateId() {
  return `${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 6)}`;
}

export default function EvalPanel() {
  const { project } = useStore();
  const [evalSets, setEvalSets] = useState<EvalSet[]>([]);
  const [selectedSetId, setSelectedSetId] = useState<string | null>(null);
  const [selectedCaseId, setSelectedCaseId] = useState<string | null>(null);
  const [expandedSets, setExpandedSets] = useState<Set<string>>(new Set());
  const [caseResultsMap, setCaseResultsMap] = useState<Map<string, EvalCaseResult>>(new Map());
  const [setResultsMap, setSetResultsMap] = useState<Map<string, EvalSetResult>>(new Map());
  const [running, setRunning] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  
  // Eval history state
  const [evalHistory, setEvalHistory] = useState<any[]>([]);
  const [selectedHistoryRun, setSelectedHistoryRun] = useState<any>(null);
  
  // Load eval history
  const loadEvalHistory = async () => {
    if (!project) return;
    try {
      const response = await api.get(`/projects/${project.id}/eval-history`);
      setEvalHistory(response.runs || []);
    } catch (err) {
      console.warn('Failed to load eval history:', err);
    }
  };
  
  // Load a specific history run
  const loadHistoryRun = async (runId: string, updateUrl = true) => {
    if (!project) return;
    try {
      const response = await api.get(`/projects/${project.id}/eval-history/${runId}`);
      const run = response.run;
      setSelectedHistoryRun(run);
      
      // Populate caseResultsMap and setResultsMap from the history run
      // so the tree items show pass/fail status from this run
      if (run?.case_results) {
        const newCaseResults = new Map<string, EvalCaseResult>();
        for (const caseResult of run.case_results) {
          newCaseResults.set(caseResult.eval_case_id, caseResult);
        }
        setCaseResultsMap(newCaseResults);
      }
      
      // For batch runs (eval_set_id === 'batch'), expand all eval sets
      // For single set runs, expand just that set
      if (run?.eval_set_id === 'batch') {
        // Batch run - expand all sets and don't select a specific one
        setExpandedSets(new Set(evalSets.map(es => es.id)));
        setSelectedSetId(null);
      } else if (run?.eval_set_id) {
        const newSetResults = new Map<string, EvalSetResult>();
        newSetResults.set(run.eval_set_id, run);
        setSetResultsMap(newSetResults);
        
        // Also select and expand the related eval set
        setSelectedSetId(run.eval_set_id);
        setExpandedSets(prev => new Set([...prev, run.eval_set_id]));
      }
      
      // Clear case selection - the viewer will show full run results
      setSelectedCaseId(null);
      
      // Update URL for browser history
      if (updateUrl) {
        window.history.pushState({ run: runId }, '', `?run=${runId}`);
      }
    } catch (err) {
      console.warn('Failed to load history run:', err);
    }
  };
  
  // Select a set (with URL update)
  const selectSet = (setId: string | null, updateUrl = true) => {
    setSelectedSetId(setId);
    setSelectedCaseId(null);
    setSelectedHistoryRun(null);
    if (updateUrl && setId) {
      window.history.pushState({ set: setId }, '', `?set=${setId}`);
    } else if (updateUrl) {
      window.history.pushState({}, '', window.location.pathname);
    }
  };
  
  // Select a case (with URL update)
  const selectCase = (setId: string, caseId: string | null, updateUrl = true) => {
    setSelectedSetId(setId);
    setSelectedCaseId(caseId);
    setSelectedHistoryRun(null);
    if (updateUrl && caseId) {
      window.history.pushState({ set: setId, case: caseId }, '', `?set=${setId}&case=${caseId}`);
    } else if (updateUrl && setId) {
      window.history.pushState({ set: setId }, '', `?set=${setId}`);
    }
  };
  
  // Close history run viewer (with URL update)
  const closeHistoryRun = () => {
    setSelectedHistoryRun(null);
    // Clear the result maps that were populated from history
    setCaseResultsMap(new Map());
    setSetResultsMap(new Map());
    window.history.pushState({}, '', window.location.pathname);
  };
  
  // Delete a history run
  const deleteHistoryRun = async (runId: string) => {
    if (!project) return;
    try {
      await api.delete(`/projects/${project.id}/eval-history/${runId}`);
      setEvalHistory(prev => prev.filter(r => r.id !== runId));
      if (selectedHistoryRun?.id === runId) {
        setSelectedHistoryRun(null);
      }
    } catch (err) {
      console.warn('Failed to delete history run:', err);
    }
  };
  
  // Load eval sets and history when project changes
  useEffect(() => {
    if (project?.id) {
      loadEvalSets();
      loadEvalHistory();
    }
  }, [project?.id]);
  
  // Listen for test events from header Test button
  useEffect(() => {
    const handleTestsStarted = () => {
      // Mark all eval sets as running
      setRunning(new Set(evalSets.map(es => es.id)));
    };
    const handleTestsCompleted = () => {
      // Clear all running states
      setRunning(new Set());
      loadEvalHistory();
    };
    
    window.addEventListener('eval-tests-started', handleTestsStarted);
    window.addEventListener('eval-tests-completed', handleTestsCompleted);
    
    return () => {
      window.removeEventListener('eval-tests-started', handleTestsStarted);
      window.removeEventListener('eval-tests-completed', handleTestsCompleted);
    };
  }, [evalSets]);
  
  // Handle URL deeplinks: ?set=, ?case=, ?run=
  useEffect(() => {
    if (!project?.id || loading) return;
    
    const handleUrlParams = () => {
      const params = new URLSearchParams(window.location.search);
      const setId = params.get('set');
      const caseId = params.get('case');
      const runId = params.get('run');
      
      // Handle run deeplink (historical run viewer)
      if (runId) {
        loadHistoryRun(runId, false); // Don't update URL again
        return;
      }
      
      // Handle set and case deeplinks
      if (setId) {
        setSelectedSetId(setId);
        setSelectedCaseId(caseId);
        setSelectedHistoryRun(null);
        setExpandedSets(prev => new Set([...prev, setId]));
      } else {
        // No params - clear selections
        if (!selectedSetId && !selectedCaseId && !selectedHistoryRun) return; // Already cleared
        setSelectedSetId(null);
        setSelectedCaseId(null);
        setSelectedHistoryRun(null);
      }
    };
    
    // Handle initial load
    handleUrlParams();
    
    // Handle browser back/forward
    const handlePopState = () => {
      handleUrlParams();
    };
    
    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, [project?.id, loading, evalSets.length]);
  
  const loadEvalSets = async () => {
    if (!project?.id) return;
    
    setLoading(true);
    setError(null);
    
    try {
      const response = await api.get(`/projects/${project.id}/eval-sets`);
      setEvalSets(response.eval_sets || []);
      
      // Auto-expand first set if exists, but respect URL params
      if (response.eval_sets?.length > 0) {
        const params = new URLSearchParams(window.location.search);
        const urlSetId = params.get('set');
        const urlCaseId = params.get('case');
        
        // If URL specifies a set/case, expand that one; otherwise expand first
        const targetSetId = urlSetId || (urlCaseId 
          ? response.eval_sets.find((s: EvalSet) => s.eval_cases.some((c: EvalCase) => c.id === urlCaseId))?.id 
          : null) || response.eval_sets[0].id;
        
        setExpandedSets(new Set([targetSetId]));
      }
    } catch (err: any) {
      setError(err.message || 'Failed to load eval sets');
    } finally {
      setLoading(false);
    }
  };
  
  const selectedSet = evalSets.find(s => s.id === selectedSetId);
  const selectedCase = selectedSet?.eval_cases.find(c => c.id === selectedCaseId);
  
  // Create new eval set
  const createEvalSet = async () => {
    if (!project?.id) return;
    
    try {
      const response = await api.post(`/projects/${project.id}/eval-sets`, {
        name: 'New Eval Set',
        description: '',
        eval_config: DEFAULT_EVAL_CONFIG,
      });
      
      setEvalSets(prev => [...prev, response.eval_set]);
      setSelectedSetId(response.eval_set.id);
      setExpandedSets(prev => new Set([...prev, response.eval_set.id]));
    } catch (err: any) {
      setError(err.message || 'Failed to create eval set');
    }
  };
  
  // Create new eval case
  const createEvalCase = async (evalSetId: string) => {
    if (!project?.id) return;
    
    try {
      const response = await api.post(
        `/projects/${project.id}/eval-sets/${evalSetId}/cases`,
        {
          name: 'New Test Case',
          description: '',
          invocations: [{
            id: generateId(),
            user_message: '',
            expected_response: '',
            expected_tool_calls: [],
            tool_trajectory_match_type: 'in_order',
            rubrics: [],
          }],
          initial_state: {},
          rubrics: [],
          enabled_metrics: [],
          tags: [],
        }
      );
      
      // Update local state
      setEvalSets(prev => prev.map(set => 
        set.id === evalSetId 
          ? { ...set, eval_cases: [...set.eval_cases, response.eval_case] }
          : set
      ));
      
      setSelectedSetId(evalSetId);
      setSelectedCaseId(response.eval_case.id);
    } catch (err: any) {
      setError(err.message || 'Failed to create eval case');
    }
  };
  
  // Update eval case
  const updateEvalCase = async (evalSetId: string, caseId: string, updates: Partial<EvalCase>) => {
    if (!project?.id) return;
    
    try {
      const response = await api.put(
        `/projects/${project.id}/eval-sets/${evalSetId}/cases/${caseId}`,
        updates
      );
      
      // Update local state
      setEvalSets(prev => prev.map(set => 
        set.id === evalSetId 
          ? {
              ...set,
              eval_cases: set.eval_cases.map(c => 
                c.id === caseId ? response.eval_case : c
              )
            }
          : set
      ));
    } catch (err: any) {
      setError(err.message || 'Failed to update eval case');
    }
  };
  
  // Delete eval case
  const deleteEvalCase = async (evalSetId: string, caseId: string) => {
    if (!project?.id) return;
    
    try {
      await api.delete(`/projects/${project.id}/eval-sets/${evalSetId}/cases/${caseId}`);
      
      // Update local state
      setEvalSets(prev => prev.map(set => 
        set.id === evalSetId 
          ? { ...set, eval_cases: set.eval_cases.filter(c => c.id !== caseId) }
          : set
      ));
      
      if (selectedCaseId === caseId) {
        setSelectedCaseId(null);
      }
    } catch (err: any) {
      setError(err.message || 'Failed to delete eval case');
    }
  };
  
  // Delete eval set
  const deleteEvalSet = async (evalSetId: string) => {
    if (!project?.id) return;
    
    try {
      await api.delete(`/projects/${project.id}/eval-sets/${evalSetId}`);
      
      // Update local state
      setEvalSets(prev => prev.filter(s => s.id !== evalSetId));
      
      if (selectedSetId === evalSetId) {
        setSelectedSetId(null);
        setSelectedCaseId(null);
      }
    } catch (err: any) {
      setError(err.message || 'Failed to delete eval set');
    }
  };
  
  // Export eval set as JSON
  const exportEvalSet = async (evalSetId: string) => {
    if (!project?.id) return;
    
    try {
      const data = await api.get(`/projects/${project.id}/eval-sets/${evalSetId}/export`);
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      const evalSet = evalSets.find(s => s.id === evalSetId);
      a.download = `${evalSet?.name || 'eval-set'}.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (err: any) {
      setError(err.message || 'Failed to export eval set');
    }
  };
  
  // Import eval set from JSON
  const importEvalSet = async (file: File) => {
    if (!project?.id) return;
    
    try {
      const text = await file.text();
      const data = JSON.parse(text);
      const response = await api.post(`/projects/${project.id}/eval-sets/import`, data);
      
      setEvalSets(prev => [...prev, response.eval_set]);
      setSelectedSetId(response.eval_set.id);
      setExpandedSets(prev => new Set([...prev, response.eval_set.id]));
    } catch (err: any) {
      setError(err.message || 'Failed to import eval set');
    }
  };
  
  // File input ref for import
  const importInputRef = useRef<HTMLInputElement>(null);
  
  // Export all eval sets as a single JSON file
  const exportAllEvalSets = async () => {
    if (!project?.id || evalSets.length === 0) return;
    
    try {
      // Fetch full data for all eval sets
      const allSetsData = await Promise.all(
        evalSets.map(async (evalSet) => {
          try {
            return await api.get(`/projects/${project.id}/eval-sets/${evalSet.id}/export`);
          } catch {
            return evalSet; // Fallback to basic eval set data
          }
        })
      );
      
      const blob = new Blob([JSON.stringify(allSetsData, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${project.name || 'project'}-eval-sets.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (err: any) {
      setError(err.message || 'Failed to export all eval sets');
    }
  };
  
  // Run single eval case
  const runEvalCase = async (evalSetId: string, caseId: string) => {
    if (!project?.id) return;
    
    setRunning(prev => new Set([...prev, caseId]));
    
    try {
      const response = await api.post(
        `/projects/${project.id}/eval-sets/${evalSetId}/cases/${caseId}/run`,
        {}
      );
      
      setCaseResultsMap(prev => new Map(prev).set(caseId, response.result));
    } catch (err: any) {
      setError(err.message || 'Failed to run eval case');
    } finally {
      setRunning(prev => {
        const next = new Set(prev);
        next.delete(caseId);
        return next;
      });
    }
  };
  
  // Run entire eval set
  const runEvalSet = async (evalSetId: string) => {
    if (!project?.id) return;
    
    const evalSet = evalSets.find(s => s.id === evalSetId);
    if (!evalSet) return;
    
    // Mark all cases as running
    const caseIds = evalSet.eval_cases.map(c => c.id);
    setRunning(prev => new Set([...prev, evalSetId, ...caseIds]));
    
    try {
      const response = await api.post(
        `/projects/${project.id}/eval-sets/${evalSetId}/run`,
        {}
      );
      
      // Store set result
      setSetResultsMap(prev => new Map(prev).set(evalSetId, response.result));
      
      // Store individual case results
      for (const caseResult of response.result.case_results) {
        setCaseResultsMap(prev => new Map(prev).set(caseResult.eval_case_id, caseResult));
      }
      
      // Save to history
      try {
        await api.post(`/projects/${project.id}/eval-history`, response.result);
        // Refresh history list
        loadEvalHistory();
      } catch (histErr) {
        console.warn('Failed to save eval run to history:', histErr);
      }
    } catch (err: any) {
      setError(err.message || 'Failed to run eval set');
    } finally {
      setRunning(prev => {
        const next = new Set(prev);
        next.delete(evalSetId);
        caseIds.forEach(id => next.delete(id));
        return next;
      });
    }
  };
  
  // Toggle set expansion
  const toggleExpand = (id: string) => {
    setExpandedSets(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };
  
  // Get stats for an eval set
  const getSetStats = (evalSet: EvalSet) => {
    let total = evalSet.eval_cases.length;
    let passed = 0;
    let failed = 0;
    let pending = 0;
    
    for (const c of evalSet.eval_cases) {
      const result = caseResultsMap.get(c.id);
      if (result) {
        if (result.passed) passed++;
        else failed++;
      } else {
        pending++;
      }
    }
    
    return { total, passed, failed, pending };
  };
  
  // Format score as percentage
  const formatScore = (score?: number | null) => {
    if (score === null || score === undefined) return '-';
    return `${Math.round(score * 100)}%`;
  };
  
  if (!project) return null;
  
  return (
    <div className="eval-panel">
      <style>{`
        .eval-panel {
          display: flex;
          gap: 20px;
          height: calc(100vh - 180px);
        }
        
        .eval-sidebar {
          width: 360px;
          flex-shrink: 0;
          display: flex;
          flex-direction: column;
          background: var(--bg-secondary);
          border: 1px solid var(--border-color);
          border-radius: var(--radius-lg);
          overflow: hidden;
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
        
        .header-actions {
          display: flex;
          gap: 4px;
        }
        
        .eval-tree {
          flex: 1;
          overflow-y: auto;
          padding: 8px;
        }
        
        .tree-set, .tree-case {
          display: flex;
          align-items: center;
          gap: 6px;
          padding: 6px 8px;
          border-radius: var(--radius-sm);
          cursor: pointer;
          transition: background 0.15s ease;
        }
        
        .tree-set:hover, .tree-case:hover {
          background: var(--bg-tertiary);
        }
        
        .tree-set.selected, .tree-case.selected {
          background: var(--bg-hover);
        }
        
        .expand-btn {
          padding: 2px;
          color: var(--text-muted);
        }
        
        .set-name, .case-name {
          flex: 1;
          font-size: 13px;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        
        .set-stats {
          display: flex;
          gap: 4px;
        }
        
        .set-stats span {
          font-size: 11px;
          padding: 1px 5px;
          border-radius: var(--radius-sm);
        }
        
        .stat-passed { background: rgba(0, 245, 212, 0.2); color: var(--success); }
        .stat-failed { background: rgba(255, 107, 107, 0.2); color: var(--error); }
        .stat-pending { background: var(--bg-tertiary); color: var(--text-muted); }
        
        .run-btn {
          padding: 4px;
          color: var(--text-muted);
          opacity: 0;
          transition: all 0.15s ease;
        }
        
        .tree-set:hover .run-btn, .tree-case:hover .run-btn {
          opacity: 1;
        }
        
        .run-btn:hover {
          color: var(--accent-primary);
        }
        
        .spinning {
          animation: spin 1s linear infinite;
        }
        
        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
        
        .eval-editor {
          flex: 1;
          display: flex;
          flex-direction: column;
          background: var(--bg-secondary);
          border: 1px solid var(--border-color);
          border-radius: var(--radius-lg);
          overflow: hidden;
        }
        
        .editor-header {
          display: flex;
          align-items: center;
          gap: 12px;
          padding: 12px 16px;
          border-bottom: 1px solid var(--border-color);
        }
        
        .editor-header input {
          flex: 1;
          font-size: 1.1rem;
          font-weight: 600;
          background: transparent;
          border: none;
          padding: 4px 8px;
        }
        
        .editor-header input:focus {
          background: var(--bg-tertiary);
          border-radius: var(--radius-sm);
        }
        
        .editor-content {
          flex: 1;
          overflow-y: auto;
          padding: 16px;
        }
        
        .form-section {
          margin-bottom: 12px;
        }
        
        .form-section h4 {
          font-size: 12px;
          font-weight: 600;
          margin-bottom: 6px;
          color: var(--text-secondary);
          display: flex;
          align-items: center;
          gap: 6px;
        }
        
        .form-section textarea {
          width: 100%;
          min-height: 80px;
          font-family: var(--font-mono);
          font-size: 13px;
        }
        
        .form-row {
          display: flex;
          gap: 12px;
          margin-bottom: 12px;
        }
        
        .form-field {
          flex: 1;
        }
        
        .form-field label {
          display: block;
          font-size: 12px;
          color: var(--text-muted);
          margin-bottom: 4px;
        }
        
        .form-field input, .form-field select {
          width: 100%;
        }
        
        .invocation-card {
          display: flex;
          gap: 12px;
          background: var(--bg-tertiary);
          border: 1px solid var(--border-color);
          border-radius: var(--radius-md);
          padding: 12px;
          margin-bottom: 12px;
        }
        
        .invocation-number {
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 8px;
          padding-top: 4px;
        }
        
        .invocation-number span {
          font-size: 14px;
          font-weight: 700;
          color: var(--text-muted);
          width: 24px;
          height: 24px;
          display: flex;
          align-items: center;
          justify-content: center;
          background: var(--bg-secondary);
          border-radius: 50%;
        }
        
        .invocation-content {
          flex: 1;
          min-width: 0;
        }
        
        .invocation-row {
          display: flex;
          gap: 12px;
          margin-bottom: 8px;
        }
        
        .invocation-row > .form-section {
          flex: 1;
          margin-bottom: 0;
        }
        
        .invocation-row textarea {
          min-height: 60px;
        }
        
        .tool-call-compact {
          display: flex;
          align-items: center;
          gap: 6px;
          padding: 6px 8px;
          background: var(--bg-secondary);
          border-radius: var(--radius-sm);
          margin-bottom: 4px;
        }
        
        .tool-name-input {
          width: 120px;
          font-family: var(--font-mono);
          font-size: 12px;
          padding: 4px 8px;
        }
        
        .tool-args-editor {
          flex: 1;
          min-width: 100px;
          height: 22px;
          border-radius: var(--radius-sm);
          overflow: hidden;
          border: 1px solid var(--border-color);
        }
        
        .tool-args-editor .monaco-editor {
          padding: 0 !important;
        }
        
        .tool-args-editor .monaco-editor .margin {
          display: none !important;
        }
        
        .pillbox-toggle {
          display: flex;
          border-radius: 12px;
          overflow: hidden;
          border: 1px solid var(--border-color);
        }
        
        .pillbox-toggle .pill {
          padding: 3px 8px;
          font-size: 10px;
          border: none;
          background: var(--bg-tertiary);
          color: var(--text-muted);
          cursor: pointer;
          transition: all 0.15s;
        }
        
        .pillbox-toggle .pill:first-child {
          border-right: 1px solid var(--border-color);
        }
        
        .pillbox-toggle .pill.active {
          background: var(--accent-primary);
          color: var(--bg-primary);
          font-weight: 600;
        }
        
        .pillbox-toggle .pill:hover:not(.active) {
          background: var(--bg-secondary);
        }
        
        .tool-call-row {
          display: flex;
          gap: 8px;
          margin-bottom: 8px;
          padding: 8px;
          background: var(--bg-secondary);
          border-radius: var(--radius-sm);
        }
        
        .result-panel {
          padding: 16px;
          border-top: 1px solid var(--border-color);
          background: var(--bg-tertiary);
        }
        
        .result-header {
          display: flex;
          align-items: center;
          gap: 8px;
          margin-bottom: 12px;
        }
        
        .result-header.passed {
          color: var(--success);
        }
        
        .result-header.failed {
          color: var(--error);
        }
        
        .result-scores {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
          gap: 12px;
          margin-bottom: 12px;
        }
        
        .score-card {
          background: var(--bg-secondary);
          border-radius: var(--radius-sm);
          padding: 12px;
          text-align: center;
        }
        
        .score-value {
          font-size: 24px;
          font-weight: 700;
          color: var(--text-primary);
        }
        
        .score-value.passed { color: var(--success); }
        .score-value.failed { color: var(--error); }
        
        .score-label {
          font-size: 11px;
          color: var(--text-muted);
          margin-top: 4px;
        }
        
        .result-details {
          margin-top: 16px;
        }
        
        .result-details h5 {
          font-size: 12px;
          color: var(--text-muted);
          margin-bottom: 8px;
        }
        
        .detail-box {
          background: var(--bg-secondary);
          border-radius: var(--radius-sm);
          padding: 8px 12px;
          font-family: var(--font-mono);
          font-size: 12px;
          white-space: pre-wrap;
          max-height: 150px;
          overflow-y: auto;
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
        
        .quick-eval {
          background: var(--bg-tertiary);
          border-radius: var(--radius-md);
          padding: 16px;
          margin-bottom: 20px;
        }
        
        .quick-eval h4 {
          font-size: 14px;
          font-weight: 600;
          margin-bottom: 12px;
          display: flex;
          align-items: center;
          gap: 8px;
        }
        
        .coverage-bar {
          height: 8px;
          background: var(--bg-tertiary);
          border-radius: 4px;
          overflow: hidden;
          margin-bottom: 4px;
        }
        
        .coverage-fill {
          height: 100%;
          transition: width 0.3s ease;
        }
        
        .coverage-fill.passed { background: var(--success); }
        .coverage-fill.failed { background: var(--error); }
        
        .tabs {
          display: flex;
          border-bottom: 1px solid var(--border-color);
          margin-bottom: 16px;
        }
        
        .tab {
          padding: 8px 16px;
          font-size: 13px;
          cursor: pointer;
          border-bottom: 2px solid transparent;
          margin-bottom: -1px;
          transition: all 0.15s ease;
        }
        
        .tab:hover {
          color: var(--accent-primary);
        }
        
        .tab.active {
          color: var(--bg-primary);
          background: var(--accent-primary);
          border-radius: var(--radius-sm) var(--radius-sm) 0 0;
          border-bottom-color: var(--accent-primary);
        }
      `}</style>
      
      <aside className="eval-sidebar">
        <div className="sidebar-header">
          <h3>Evaluation Tests</h3>
          <div className="header-actions">
            <input
              type="file"
              ref={importInputRef}
              accept=".json"
              style={{ display: 'none' }}
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) {
                  importEvalSet(file);
                  e.target.value = '';
                }
              }}
            />
            <button 
              className="btn btn-secondary btn-sm" 
              onClick={() => importInputRef.current?.click()}
              title="Import eval set from JSON"
            >
              <Upload size={14} />
            </button>
            {evalSets.length > 0 && (
              <button 
                className="btn btn-secondary btn-sm" 
                onClick={exportAllEvalSets}
                title="Download all eval sets as JSON"
              >
                <Download size={14} />
              </button>
            )}
            <button 
              className="btn btn-secondary btn-sm" 
              onClick={loadEvalSets}
              title="Refresh"
            >
              <RefreshCw size={14} />
            </button>
            <button 
              className="btn btn-primary btn-sm" 
              onClick={createEvalSet}
              title="New eval set"
            >
              <Plus size={14} />
              Set
            </button>
          </div>
        </div>
        
        <div className="eval-tree">
          {loading && <p style={{ color: 'var(--text-muted)', padding: '16px' }}>Loading...</p>}
          
          {error && (
            <div style={{ color: 'var(--error)', padding: '16px', fontSize: '13px' }}>
              {error}
            </div>
          )}
          
          {!loading && evalSets.length === 0 && (
            <div className="empty-state" style={{ padding: '32px' }}>
              <Target size={32} />
              <p>No evaluation sets yet.<br/>Create one to get started.</p>
            </div>
          )}
          
          {evalSets.map(evalSet => {
            const isExpanded = expandedSets.has(evalSet.id);
            const stats = getSetStats(evalSet);
            const isRunning = running.has(evalSet.id);
            
            return (
              <div key={evalSet.id} className="tree-item">
                <div 
                  className={`tree-set ${selectedSetId === evalSet.id && !selectedCaseId ? 'selected' : ''}`}
                  onClick={() => selectSet(evalSet.id)}
                >
                  <button 
                    className="expand-btn"
                    onClick={(e) => { e.stopPropagation(); toggleExpand(evalSet.id); }}
                  >
                    {evalSet.eval_cases.length > 0 ? (
                      isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />
                    ) : (
                      <span style={{ width: 14 }} />
                    )}
                  </button>
                  <FolderTree size={14} style={{ color: 'var(--accent-secondary)' }} />
                  <span className="set-name">{evalSet.name}</span>
                  <button 
                    className="add-case-btn"
                    onClick={(e) => { e.stopPropagation(); createEvalCase(evalSet.id); }}
                    title="Add test case"
                    style={{ 
                      padding: '2px 4px', 
                      marginLeft: 4,
                      background: 'transparent',
                      border: 'none',
                      cursor: 'pointer',
                      opacity: 0.6,
                      display: 'flex',
                      alignItems: 'center',
                    }}
                  >
                    <Plus size={12} />
                  </button>
                  {stats.total > 0 && (
                    <span className="set-stats">
                      {stats.passed > 0 && <span className="stat-passed">{stats.passed}</span>}
                      {stats.failed > 0 && <span className="stat-failed">{stats.failed}</span>}
                      {stats.pending > 0 && <span className="stat-pending">{stats.pending}</span>}
                    </span>
                  )}
                  <button 
                    className="run-btn"
                    onClick={(e) => { e.stopPropagation(); runEvalSet(evalSet.id); }}
                    title="Run all tests in this set"
                    disabled={isRunning}
                  >
                    {isRunning ? <Clock size={12} className="spinning" /> : <Play size={12} />}
                  </button>
                </div>
                
                {isExpanded && (
                  <div className="tree-children" style={{ paddingLeft: 16 }}>
                    {evalSet.eval_cases.map(evalCase => {
                      const caseResult = caseResultsMap.get(evalCase.id);
                      const isCaseRunning = running.has(evalCase.id);
                      
                      return (
                        <div
                          key={evalCase.id}
                          className={`tree-case ${selectedCaseId === evalCase.id ? 'selected' : ''}`}
                          onClick={() => selectCase(evalSet.id, evalCase.id)}
                        >
                          {isCaseRunning ? (
                            <Clock size={14} className="spinning" style={{ color: 'var(--warning)' }} />
                          ) : caseResult ? (
                            caseResult.passed ? (
                              <CheckCircle size={14} style={{ color: 'var(--success)' }} />
                            ) : (
                              <XCircle size={14} style={{ color: 'var(--error)' }} />
                            )
                          ) : (
                            <FileCheck size={14} style={{ color: 'var(--text-muted)' }} />
                          )}
                          <span className="case-name">{evalCase.name}</span>
                          {caseResult && caseResult.metric_results.length > 0 && (
                            <span style={{ 
                              fontSize: 11, 
                              color: caseResult.passed ? 'var(--success)' : 'var(--error)' 
                            }}>
                              {formatScore(caseResult.metric_results[0]?.score)}
                            </span>
                          )}
                          <button 
                            className="run-btn"
                            onClick={(e) => { e.stopPropagation(); runEvalCase(evalSet.id, evalCase.id); }}
                            disabled={isCaseRunning}
                          >
                            <Play size={12} />
                          </button>
                        </div>
                      );
                    })}
                    
                  </div>
                )}
              </div>
            );
          })}
        </div>
        
        {/* Previous Runs Section */}
        <div className="history-section">
          <div 
            className="history-header"
            style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 12px', borderTop: '1px solid var(--border-color)', background: 'var(--bg-secondary)' }}
          >
            <span style={{ fontWeight: 500, fontSize: 13 }}>
              Previous Runs ({evalHistory.length})
            </span>
          </div>
          
          <div className="history-list" style={{ maxHeight: 200, overflowY: 'auto' }}>
              {evalHistory.length === 0 ? (
                <div style={{ padding: '12px', color: 'var(--text-secondary)', fontSize: 12, textAlign: 'center' }}>
                  No previous runs
                </div>
              ) : (
                [...evalHistory]
                  .sort((a, b) => (b.started_at || 0) - (a.started_at || 0))
                  .map(run => {
                    const allPassed = run.passed_cases === run.total_cases;
                    return (
                      <div
                        key={run.id}
                        className={`history-item ${selectedHistoryRun?.id === run.id ? 'selected' : ''}`}
                        onClick={() => loadHistoryRun(run.id)}
                        style={{
                          padding: '8px 12px',
                          borderBottom: '1px solid var(--border-color)',
                          cursor: 'pointer',
                          background: selectedHistoryRun?.id === run.id ? 'var(--bg-tertiary)' : 'transparent',
                          fontSize: 12
                        }}
                      >
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                            {allPassed ? (
                              <CheckCircle size={14} style={{ color: 'var(--success)', flexShrink: 0 }} />
                            ) : (
                              <XCircle size={14} style={{ color: 'var(--error)', flexShrink: 0 }} />
                            )}
                            <div>
                              <div style={{ fontWeight: 500 }}>{run.eval_set_name || 'Unnamed'}</div>
                              <div style={{ color: 'var(--text-secondary)', fontSize: 11 }}>
                                {new Date(run.started_at * 1000).toLocaleString()}
                              </div>
                            </div>
                          </div>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                            <span style={{ 
                              color: allPassed ? 'var(--success)' : 'var(--error)',
                              fontWeight: 500,
                              fontSize: 11
                            }}>
                              {run.passed_cases}/{run.total_cases}
                            </span>
                    <button
                              className="btn btn-icon"
                              onClick={(e) => { e.stopPropagation(); deleteHistoryRun(run.id); }}
                              title="Delete run"
                              style={{ padding: 2 }}
                    >
                              <Trash2 size={12} />
                    </button>
                  </div>
                        </div>
              </div>
            );
                  })
              )}
            </div>
        </div>
      </aside>
      
      <div className="eval-editor">
        {selectedHistoryRun ? (
          <TestResultViewer
            run={selectedHistoryRun}
            onClose={closeHistoryRun}
          />
        ) : selectedCase ? (
          <EvalCaseEditor
            evalCase={selectedCase}
            evalSetId={selectedSetId!}
            projectId={project.id}
            result={caseResultsMap.get(selectedCase.id)}
            isRunning={running.has(selectedCase.id)}
            onUpdate={(updates) => updateEvalCase(selectedSetId!, selectedCase.id, updates)}
            onDelete={() => deleteEvalCase(selectedSetId!, selectedCase.id)}
            onRun={() => runEvalCase(selectedSetId!, selectedCase.id)}
            onClearResult={() => setCaseResultsMap(prev => {
              const next = new Map(prev);
              next.delete(selectedCase.id);
              return next;
            })}
          />
        ) : selectedSet ? (
          <EvalSetEditor
            evalSet={selectedSet}
            projectId={project.id}
            result={setResultsMap.get(selectedSet.id)}
            isRunning={running.has(selectedSet.id)}
            caseResults={caseResultsMap}
            onUpdate={async (updates) => {
              try {
                const response = await api.put(
                  `/projects/${project.id}/eval-sets/${selectedSet.id}`,
                  updates
                );
                setEvalSets(prev => prev.map(s => 
                  s.id === selectedSet.id ? response.eval_set : s
                ));
              } catch (err: any) {
                setError(err.message);
              }
            }}
            onDelete={() => deleteEvalSet(selectedSet.id)}
            onRun={() => runEvalSet(selectedSet.id)}
            onExport={() => exportEvalSet(selectedSet.id)}
          />
        ) : (
          <div className="editor-content">
            <div className="empty-state">
              <FileCheck size={48} />
              <p>Select a test case to edit<br />or create a new one</p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// Judge Model Selector Component
function JudgeModelSelector({
  value,
  onChange
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  const { project } = useStore();
  const appModels = project?.app?.models || [];
  const defaultModelId = project?.app?.default_model_id;
  const defaultModel = appModels.find(m => m.id === defaultModelId);
  
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      style={{ width: '100%', maxWidth: 400 }}
    >
      <option value="">
        {defaultModel ? `App Default (${defaultModel.model_name})` : 'App Default'}
      </option>
      {appModels.map(model => (
        <option key={model.id} value={model.model_name}>
          {model.model_name}
        </option>
      ))}
      <option value="gemini-2.0-flash">gemini-2.0-flash</option>
      <option value="gemini-2.5-flash">gemini-2.5-flash</option>
      <option value="gemini-2.5-pro">gemini-2.5-pro</option>
    </select>
  );
}

// Test Result Viewer Component - for viewing historical test runs
function TestResultViewer({
  run,
  onClose
}: {
  run: any;
  onClose: () => void;
}) {
  const { project } = useStore();
  const [showOnlyFailed, setShowOnlyFailed] = useState(true);
  const [expandedCases, setExpandedCases] = useState<Set<string>>(new Set());
  const caseResults = run.case_results || [];
  const passedCases = caseResults.filter((c: any) => c.passed).length;
  const failedCases = caseResults.filter((c: any) => !c.passed).length;
  const displayedCases = showOnlyFailed 
    ? caseResults.filter((c: any) => !c.passed) 
    : caseResults;
  
  const toggleCaseExpanded = (caseId: string) => {
    setExpandedCases(prev => {
      const next = new Set(prev);
      if (next.has(caseId)) {
        next.delete(caseId);
      } else {
        next.add(caseId);
      }
      return next;
    });
  };
  
  const viewSession = (sessionId: string) => {
    if (sessionId && project) {
      // Navigate to Run panel with session ID in URL
      window.location.href = `/project/${project.id}/run?session=${sessionId}`;
    }
  };
  
  return (
    <div className="test-result-viewer">
      <style>{`
        .test-result-viewer {
          height: 100%;
          display: flex;
          flex-direction: column;
          background: var(--bg-secondary);
        }
        .result-header {
          padding: 16px 20px;
          border-bottom: 1px solid var(--border-color);
          display: flex;
          justify-content: space-between;
          align-items: center;
        }
        .result-header h2 {
          font-size: 16px;
          font-weight: 600;
          margin: 0;
        }
        .result-summary {
          padding: 16px 20px;
          background: var(--bg-tertiary);
          border-bottom: 1px solid var(--border-color);
          display: flex;
          gap: 24px;
          flex-wrap: wrap;
        }
        .summary-stat {
          display: flex;
          flex-direction: column;
          gap: 2px;
        }
        .summary-stat .label {
          font-size: 11px;
          color: var(--text-secondary);
          text-transform: uppercase;
        }
        .summary-stat .value {
          font-size: 18px;
          font-weight: 600;
        }
        .summary-stat .value.passed { color: var(--success); }
        .summary-stat .value.failed { color: var(--error); }
        .result-cases {
          flex: 1;
          overflow-y: auto;
          padding: 16px 20px;
        }
        .result-case {
          border: 1px solid var(--border-color);
          border-radius: var(--radius-md);
          margin-bottom: 12px;
          background: var(--bg-primary);
        }
        .result-case-header {
          padding: 12px 16px;
          display: flex;
          justify-content: space-between;
          align-items: center;
          border-bottom: 1px solid var(--border-color);
          cursor: pointer;
        }
        .result-case-header:hover {
          background: var(--bg-hover);
        }
        .result-case-name {
          font-weight: 500;
          display: flex;
          align-items: center;
          gap: 8px;
        }
        .result-case-details {
          padding: 12px 16px;
        }
        .metric-row {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 6px 0;
          border-bottom: 1px solid var(--border-color);
          font-size: 13px;
        }
        .metric-row:last-child {
          border-bottom: none;
        }
        .metric-name {
          color: var(--text-secondary);
        }
        .metric-value {
          font-weight: 500;
        }
        .metric-value.passed { color: var(--success); }
        .metric-value.failed { color: var(--error); }
        .metric-error {
          color: var(--error);
          font-size: 12px;
          opacity: 0.8;
        }
        .invocation-summary {
          margin-top: 8px;
          padding-top: 8px;
          border-top: 1px solid var(--border-color);
        }
        .invocation-item {
          padding: 8px;
          background: var(--bg-tertiary);
          border-radius: var(--radius-sm);
          margin-bottom: 8px;
          font-size: 12px;
        }
        .invocation-query {
          color: var(--accent-primary);
          font-weight: 500;
        }
        .invocation-response {
          color: var(--text-secondary);
          margin-top: 4px;
        }
      `}</style>
      
      <div className="result-header">
        <h2>{run.eval_set_name || 'Test Run Results'}</h2>
        <div style={{ display: 'flex', gap: 8 }}>
          <button 
            className="btn btn-secondary btn-sm"
            onClick={() => {
              if (project) {
                const url = `${window.location.origin}/project/${project.id}/evaluate?run=${run.id}`;
                navigator.clipboard.writeText(url);
              }
            }}
            title="Copy link to this run"
          >
            <Link2 size={14} />
          </button>
        </div>
              </div>
              
      <div className="result-summary">
        <div className="summary-stat">
          <span className="label">Status</span>
          <span className={`value ${passedCases === caseResults.length ? 'passed' : 'failed'}`}>
            {passedCases === caseResults.length ? 'PASSED' : 'FAILED'}
          </span>
        </div>
        <div className="summary-stat">
          <span className="label">Passed</span>
          <span className="value passed">{passedCases}</span>
        </div>
        <div className="summary-stat">
          <span className="label">Failed</span>
          <span className="value failed">{failedCases}</span>
        </div>
        <div className="summary-stat">
          <span className="label">Total Cases</span>
          <span className="value">{caseResults.length}</span>
        </div>
        <div className="summary-stat">
          <span className="label">Duration</span>
          <span className="value">{run.duration_ms ? `${(run.duration_ms / 1000).toFixed(1)}s` : '-'}</span>
        </div>
        <div className="summary-stat">
          <span className="label">Tokens</span>
          <span className="value">{run.total_tokens?.toLocaleString() || '-'}</span>
        </div>
        <div className="summary-stat">
          <span className="label">Run Time</span>
          <span className="value" style={{ fontSize: 13 }}>
            {run.started_at ? new Date(run.started_at * 1000).toLocaleString() : '-'}
          </span>
        </div>
              </div>
              
      {/* Filter toggle */}
      <div style={{ 
        padding: '8px 20px', 
        borderBottom: '1px solid var(--border-color)',
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        background: 'var(--bg-secondary)'
      }}>
        <label className="toggle-switch" style={{ transform: 'scale(0.85)' }}>
                  <input
            type="checkbox"
            checked={showOnlyFailed}
            onChange={(e) => setShowOnlyFailed(e.target.checked)}
                  />
          <span className="toggle-slider" />
        </label>
        <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
          Hide passing results
        </span>
                </div>
              
      <div className="result-cases">
        {displayedCases.map((caseResult: any, index: number) => {
          const caseId = caseResult.case_id || `case-${index}`;
          const isExpanded = expandedCases.has(caseId);
          
          // Calculate pass/fail counts for the header
          const failedMetrics = caseResult.metric_results?.filter((m: any) => !m.passed || m.error) || [];
          const passedMetrics = caseResult.metric_results?.filter((m: any) => m.passed && !m.error) || [];
          const failedRubrics = caseResult.rubric_results?.filter((r: any) => !r.passed || r.error) || [];
          const passedRubrics = caseResult.rubric_results?.filter((r: any) => r.passed && !r.error) || [];
          
          // Get metrics to display based on expanded state
          const displayMetrics = isExpanded ? caseResult.metric_results : failedMetrics;
          const displayRubrics = isExpanded ? caseResult.rubric_results : failedRubrics;
          const displayInvocations = isExpanded 
            ? caseResult.invocation_results 
            : caseResult.invocation_results?.filter((inv: any) => 
                inv.metric_results?.some((m: any) => !m.passed) || inv.error
              );
          
          const totalPassed = passedMetrics.length + passedRubrics.length;
          const totalFailed = failedMetrics.length + failedRubrics.length;
          
          return (
            <div key={caseId} className="result-case">
              <div 
                className="result-case-header"
                onClick={() => toggleCaseExpanded(caseId)}
                style={{ cursor: 'pointer' }}
                  >
                <div className="result-case-name">
                  <span style={{ marginRight: 6, fontSize: 12, color: 'var(--text-muted)' }}>
                    {isExpanded ? '▼' : '▶'}
                  </span>
                  {caseResult.passed ? (
                    <CheckCircle size={16} style={{ color: 'var(--success)' }} />
                  ) : (
                    <XCircle size={16} style={{ color: 'var(--error)' }} />
                  )}
                  {caseResult.eval_set_name && run?.eval_set_id === 'batch' && (
                    <span style={{ 
                      fontSize: 10, 
                      color: 'var(--text-muted)', 
                      background: 'var(--bg-tertiary)',
                      padding: '2px 6px',
                      borderRadius: 4,
                      marginRight: 6,
                    }}>
                      {caseResult.eval_set_name}
                    </span>
                  )}
                  {caseResult.case_name || `Case ${index + 1}`}
                  <span style={{ 
                    marginLeft: 10, 
                    fontSize: 11, 
                    color: 'var(--text-muted)',
                    fontWeight: 400,
                  }}>
                    {totalFailed > 0 && <span style={{ color: 'var(--error)' }}>{totalFailed} failed</span>}
                    {totalFailed > 0 && totalPassed > 0 && ' · '}
                    {totalPassed > 0 && <span style={{ color: 'var(--success)' }}>{totalPassed} passed</span>}
                  </span>
                </div>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  {caseResult.session_id && (
                    <button
                      className="btn btn-secondary btn-sm"
                      onClick={(e) => { e.stopPropagation(); viewSession(caseResult.session_id); }}
                      title="View session in Run panel"
                    >
                      <ExternalLink size={12} /> View Session
                  </button>
                  )}
                  <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                    {caseResult.duration_ms ? `${(caseResult.duration_ms / 1000).toFixed(2)}s` : ''}
                  </span>
                </div>
              </div>
              
              <div className="result-case-details">
                {/* Metrics - compact horizontal boxes */}
                {displayMetrics?.length > 0 && (
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 8 }}>
                    {displayMetrics.map((metric: any, mIndex: number) => {
                      const formatted = formatMetricScore(metric.metric, metric.score, metric.threshold);
                      return (
                      <div 
                        key={mIndex} 
                        style={{
                          padding: '6px 10px',
                          borderRadius: 'var(--radius-sm)',
                          background: metric.error 
                            ? 'rgba(255, 193, 7, 0.1)' 
                            : metric.passed 
                              ? 'rgba(var(--success-rgb), 0.05)' 
                              : 'rgba(var(--error-rgb), 0.1)',
                          border: `1px solid ${metric.error ? 'var(--warning)' : metric.passed ? 'var(--border-color)' : 'var(--error)'}`,
                          display: 'flex',
                          flexDirection: 'column',
                          alignItems: 'center',
                          minWidth: 80,
                        }}
                      >
                        <span style={{ 
                          fontSize: 10, 
                          color: 'var(--text-secondary)',
                          textAlign: 'center',
                          marginBottom: 2,
                        }}>
                          {metric.metric.replace(/_/g, ' ').replace('v1', '').replace('v2', '').trim()}
                        </span>
                        {metric.error ? (
                          <span style={{ fontSize: 10, color: 'var(--warning)' }}>Error</span>
                        ) : (
                          <>
                            <span style={{ 
                              fontSize: 14, 
                              fontWeight: 600,
                              color: metric.passed ? 'var(--success)' : 'var(--error)',
                            }}>
                              {formatted.value}
                    </span>
                            <span style={{ fontSize: 9, color: 'var(--text-muted)' }}>
                              {formatted.comparison}
                            </span>
                          </>
                        )}
                  </div>
                      );
                    })}
                    {!isExpanded && passedMetrics.length > 0 && (
                      <div style={{
                        padding: '6px 10px',
                        borderRadius: 'var(--radius-sm)',
                        background: 'var(--bg-tertiary)',
                        border: '1px dashed var(--border-color)',
                        display: 'flex',
                        alignItems: 'center',
                        fontSize: 11,
                        color: 'var(--text-muted)',
                      }}>
                        +{passedMetrics.length} passed
                      </div>
                    )}
                  </div>
                )}
                
                {/* Show rationales for failed metrics */}
                {displayMetrics?.filter((m: MetricResult) => !m.passed && m.rationale).map((metric: MetricResult, idx: number) => (
                  <div 
                    key={`rationale-${idx}`}
                    style={{
                      marginTop: 8,
                      padding: '8px 12px',
                      borderRadius: 'var(--radius-sm)',
                      background: 'rgba(var(--error-rgb), 0.05)',
                      border: '1px solid rgba(var(--error-rgb), 0.2)',
                      fontSize: 12,
                    }}
                  >
                    <div style={{ 
                      fontWeight: 500, 
                      marginBottom: 4,
                      color: 'var(--error)',
                      fontSize: 11,
                    }}>
                      {metric.metric.replace(/_/g, ' ')} - Why it failed:
                          </div>
                    <div style={{ 
                      whiteSpace: 'pre-wrap',
                      color: 'var(--text-secondary)',
                      lineHeight: 1.4,
                    }}>
                      {metric.rationale}
                        </div>
                      </div>
                ))}
                
                {/* Rubric Results */}
                {displayRubrics?.length > 0 && (
                  <div style={{ marginTop: 8 }}>
                    <div style={{ fontSize: 11, color: 'var(--text-secondary)', marginBottom: 4 }}>Custom Rubrics</div>
                    {displayRubrics.map((rr: any, rIndex: number) => (
                      <div key={rIndex} style={{ marginBottom: rr.rationale && !rr.passed ? 8 : 4 }}>
                        <div className="metric-row">
                          <span className="metric-name" style={{ flex: 1 }}>{rr.rubric}</span>
                          <span className={`metric-value ${rr.passed ? 'passed' : 'failed'}`}>
                            {rr.passed ? '✓ Pass' : '✗ Fail'}
                          </span>
                        </div>
                        {/* Show rationale for failed rubrics */}
                        {!rr.passed && rr.rationale && (
                          <div style={{
                            marginTop: 4,
                            marginLeft: 8,
                            padding: '6px 10px',
                            borderRadius: 'var(--radius-sm)',
                            background: 'rgba(var(--error-rgb), 0.05)',
                            border: '1px solid rgba(var(--error-rgb), 0.2)',
                            fontSize: 11,
                            color: 'var(--text-secondary)',
                          }}>
                            <strong style={{ color: 'var(--error)' }}>Why:</strong> {rr.rationale}
                      </div>
                        )}
                        {/* Show error if any */}
                        {rr.error && (
                          <div style={{
                            marginTop: 4,
                            marginLeft: 8,
                            fontSize: 11,
                            color: 'var(--warning)',
                          }}>
                            Error: {rr.error}
                </div>
              )}
            </div>
                    ))}
                    {!isExpanded && passedRubrics.length > 0 && (
                      <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>
                        +{passedRubrics.length} passed rubric{passedRubrics.length > 1 ? 's' : ''}
                      </div>
                    )}
                  </div>
                )}
                
                {/* Invocation Summary */}
                {displayInvocations?.length > 0 && (
                  <div className="invocation-summary">
                    <div style={{ fontSize: 11, color: 'var(--text-secondary)', marginBottom: 8 }}>
                      Invocations ({displayInvocations.length}{!isExpanded && caseResult.invocation_results?.length > displayInvocations.length ? ` of ${caseResult.invocation_results.length}` : ''})
            </div>
                    {displayInvocations.map((inv: any, iIndex: number) => (
                      <div key={iIndex} className="invocation-item">
                        <div className="invocation-query">
                          Turn {inv.invocation_id || iIndex + 1}: {inv.user_message || '(no message)'}
                        </div>
                        {inv.actual_response && (
                          <div className="invocation-response">
                            Response: {inv.actual_response.substring(0, 200)}
                            {inv.actual_response.length > 200 ? '...' : ''}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
                
                {/* Error message if case failed with error */}
                {caseResult.error && (
                  <div style={{ 
                    marginTop: 12, 
                    padding: 12, 
                    background: 'rgba(255, 107, 107, 0.1)', 
                    borderRadius: 'var(--radius-sm)',
                    color: 'var(--error)',
                    fontSize: 12,
                    whiteSpace: 'pre-wrap'
                  }}>
                    {caseResult.error}
                  </div>
                )}
              </div>
            </div>
          );
        })}
        
        {caseResults.length === 0 && (
          <div style={{ textAlign: 'center', padding: 32, color: 'var(--text-secondary)' }}>
            No test cases in this run
          </div>
        )}
      </div>
    </div>
  );
}

// Eval Case Editor Component
function EvalCaseEditor({
  evalCase,
  evalSetId,
  projectId,
  result,
  isRunning,
  onUpdate,
  onDelete,
  onRun,
  onClearResult,
}: {
  evalCase: EvalCase;
  evalSetId: string;
  projectId: string;
  result?: EvalCaseResult;
  isRunning: boolean;
  onUpdate: (updates: Partial<EvalCase>) => void;
  onDelete: () => void;
  onRun: () => void;
  onClearResult?: () => void;
}) {
  const { project } = useStore();
  const [localCase, setLocalCase] = useState(evalCase);
  const [activeTab, setActiveTab] = useState<'assertions' | 'rubrics' | 'docs' | 'json'>('assertions');
  // Update local state when evalCase changes (from external source)
  useEffect(() => {
    setLocalCase(evalCase);
  }, [evalCase.id]); // Only reset when the case ID changes, not on every prop update
  
  // Save immediately (no debounce for now to ensure persistence)
  const saveCase = useCallback((updates: Partial<EvalCase>) => {
    // Update local state immediately for responsiveness
    setLocalCase(prev => ({ ...prev, ...updates }));
    // Save to backend
    onUpdate(updates);
  }, [onUpdate]);
  
  const addInvocation = () => {
    const newInv: EvalInvocation = {
      id: generateId(),
      user_message: '',
      expected_response: '',
      expected_tool_calls: [],
      tool_trajectory_match_type: 'in_order',
      rubrics: [],
    };
    saveCase({ invocations: [...localCase.invocations, newInv] });
  };
  
  const updateInvocation = (idx: number, updates: Partial<EvalInvocation>) => {
    const invocations = [...localCase.invocations];
    invocations[idx] = { ...invocations[idx], ...updates };
    saveCase({ invocations });
  };
  
  const removeInvocation = (idx: number) => {
    saveCase({ invocations: localCase.invocations.filter((_, i) => i !== idx) });
  };
  
  const addToolCall = (invIdx: number) => {
    const invocations = [...localCase.invocations];
    invocations[invIdx] = {
      ...invocations[invIdx],
      expected_tool_calls: [
        ...invocations[invIdx].expected_tool_calls,
        { name: '', args: {}, args_match_mode: 'subset' as const },
      ],
    };
    saveCase({ invocations });
  };
  
  const updateToolCall = (invIdx: number, tcIdx: number, updates: Partial<ExpectedToolCall>) => {
    const invocations = [...localCase.invocations];
    const toolCalls = [...invocations[invIdx].expected_tool_calls];
    toolCalls[tcIdx] = { ...toolCalls[tcIdx], ...updates };
    invocations[invIdx] = { ...invocations[invIdx], expected_tool_calls: toolCalls };
    saveCase({ invocations });
  };
  
  const removeToolCall = (invIdx: number, tcIdx: number) => {
    const invocations = [...localCase.invocations];
    invocations[invIdx] = {
      ...invocations[invIdx],
      expected_tool_calls: invocations[invIdx].expected_tool_calls.filter((_, i) => i !== tcIdx),
    };
    saveCase({ invocations });
  };
  
  const formatScore = (score?: number | null) => {
    if (score === null || score === undefined) return '-';
    return `${Math.round(score * 100)}%`;
  };
  
  return (
    <>
      <div className="editor-header">
        <FileCheck size={20} style={{ color: 'var(--accent-primary)' }} />
        <input
          type="text"
          value={localCase.name}
          onChange={(e) => saveCase({ name: e.target.value })}
          placeholder="Test case name"
        />
        <button 
          className="btn btn-secondary btn-sm"
          onClick={() => {
            const url = `${window.location.origin}/project/${projectId}/evaluate?set=${evalSetId}&case=${evalCase.id}`;
            navigator.clipboard.writeText(url);
          }}
          title="Copy link to this test case"
        >
          <Link2 size={14} />
        </button>
        <button 
          className="btn btn-primary btn-sm"
          onClick={onRun}
          disabled={isRunning}
        >
          {isRunning ? <Clock size={14} className="spinning" /> : <Play size={14} />}
          Run
        </button>
        <button 
          className="btn btn-danger btn-sm"
          onClick={onDelete}
        >
          <Trash2 size={14} />
        </button>
      </div>
      
      <div className="tabs">
        <div 
          className={`tab ${activeTab === 'assertions' ? 'active' : ''}`}
          onClick={() => setActiveTab('assertions')}
        >
          <MessageSquare size={14} style={{ marginRight: 6 }} />
          Assertions ({localCase.invocations.length})
        </div>
        <div 
          className={`tab ${activeTab === 'rubrics' ? 'active' : ''}`}
          onClick={() => setActiveTab('rubrics')}
        >
          <Target size={14} style={{ marginRight: 6 }} />
          LLM Judges
        </div>
        <div 
          className={`tab ${activeTab === 'docs' ? 'active' : ''}`}
          onClick={() => setActiveTab('docs')}
        >
          <AlertCircle size={14} style={{ marginRight: 6 }} />
          Docs
        </div>
        <div 
          className={`tab ${activeTab === 'json' ? 'active' : ''}`}
          onClick={() => setActiveTab('json')}
        >
          <Code size={14} style={{ marginRight: 6 }} />
          JSON
        </div>
      </div>
      
      <div className="editor-content">
        {activeTab === 'assertions' && (
          <>
            {/* Test Setup */}
            <div style={{ display: 'flex', gap: 12, marginBottom: 12 }}>
              <div style={{ flex: 1 }}>
                <label style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4, display: 'block' }}>target_agent</label>
                <select
                  value={localCase.target_agent || ''}
                  onChange={(e) => saveCase({ target_agent: e.target.value || undefined })}
                  style={{ width: '100%' }}
                >
                  <option value="">root_agent</option>
                  {project?.agents?.map(agent => (
                    <option key={agent.name} value={agent.name}>{agent.name}</option>
                  ))}
                </select>
              </div>
              <div style={{ flex: 1 }}>
                <label style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4, display: 'block' }}>tags</label>
                <input
                  type="text"
                  value={localCase.tags.join(', ')}
                  onChange={(e) => saveCase({ tags: e.target.value.split(',').map(t => t.trim()).filter(Boolean) })}
                  placeholder="smoke, regression"
                  style={{ width: '100%' }}
                />
              </div>
            </div>
            
            <div className="form-section">
              <h4>Description</h4>
              <textarea
                value={localCase.description}
                onChange={(e) => saveCase({ description: e.target.value })}
                placeholder="What does this test verify?"
                style={{ minHeight: 40 }}
              />
            </div>
            
            <div className="form-section">
              <h4>session_input <span style={{ fontWeight: 400, color: 'var(--text-muted)' }}>(initial state)</span></h4>
              <div style={{ height: 80, borderRadius: 'var(--radius-sm)', overflow: 'hidden', border: '1px solid var(--border-color)' }}>
                <Editor
                  height="100%"
                  defaultLanguage="json"
                  value={(() => {
                    // Pre-populate with app state_keys if initial_state is empty
                    const isEmpty = !localCase.initial_state || Object.keys(localCase.initial_state).length === 0;
                    if (isEmpty && project?.app?.state_keys && project.app.state_keys.length > 0) {
                      const prePopulated: Record<string, any> = {};
                      project.app.state_keys.forEach((sk: any) => {
                        if (sk.default_value !== undefined) {
                          prePopulated[sk.name] = sk.default_value;
                        } else {
                          prePopulated[sk.name] = sk.type === 'string' ? '' : 
                                                  sk.type === 'number' ? 0 : 
                                                  sk.type === 'boolean' ? false :
                                                  sk.type === 'array' ? [] : {};
                        }
                      });
                      return JSON.stringify(prePopulated, null, 2);
                    }
                    return JSON.stringify(localCase.initial_state, null, 2);
                  })()}
                  onChange={(value) => {
                    try {
                      if (value) saveCase({ initial_state: JSON.parse(value) });
                    } catch {}
                  }}
                  theme="vs-dark"
                  options={{
                    minimap: { enabled: false },
                    scrollBeyondLastLine: false,
                    lineNumbers: 'off',
                    glyphMargin: false,
                    folding: false,
                    lineDecorationsWidth: 0,
                    lineNumbersMinChars: 0,
                    fontSize: 12,
                    automaticLayout: true,
                    scrollbar: { verticalScrollbarSize: 6 },
                  }}
                />
              </div>
            </div>
            
            <div className="form-section">
              <h4>
                <MessageSquare size={14} />
                Conversation Turns
              </h4>
              
              {localCase.invocations.map((inv, idx) => (
                <div key={inv.id} className="invocation-card">
                  <div className="invocation-number">
                    <span>{idx + 1}</span>
                    {localCase.invocations.length > 1 && (
                      <button
                        className="btn btn-danger btn-sm"
                        onClick={() => removeInvocation(idx)}
                        style={{ padding: 4 }}
                      >
                        <Trash2 size={10} />
                      </button>
                    )}
                  </div>
                  
                  <div className="invocation-content">
                    <div className="invocation-row">
                  <div className="form-section">
                        <label>User Query</label>
                    <textarea
                      value={inv.user_message}
                      onChange={(e) => updateInvocation(idx, { user_message: e.target.value })}
                      placeholder="The message to send to the agent..."
                    />
                  </div>
                  
                  <div className="form-section">
                        <label>Expected Response <span style={{ color: 'var(--text-muted)', fontWeight: 400 }}>(ROUGE-1)</span></label>
                    <textarea
                      value={inv.expected_response || ''}
                      onChange={(e) => updateInvocation(idx, { expected_response: e.target.value || undefined })}
                          placeholder="Expected text (partial match)..."
                    />
                      </div>
                  </div>
                    
                    {inv.expected_tool_calls.map((tc, tcIdx) => (
                      <div key={tcIdx} className="tool-call-compact">
                        <input
                          type="text"
                          value={tc.name}
                          onChange={(e) => updateToolCall(idx, tcIdx, { name: e.target.value })}
                          placeholder="tool_name"
                          className="tool-name-input"
                        />
                        <div className="pillbox-toggle">
                          <button 
                            className={`pill ${tc.args_match_mode === 'subset' ? 'active' : ''}`}
                            onClick={() => updateToolCall(idx, tcIdx, { args_match_mode: 'subset' })}
                          >Partial</button>
                          <button 
                            className={`pill ${tc.args_match_mode === 'exact' ? 'active' : ''}`}
                            onClick={() => updateToolCall(idx, tcIdx, { args_match_mode: 'exact' })}
                          >Exact</button>
                        </div>
                        <div className="tool-args-editor">
                          <Editor
                            height="22px"
                            defaultLanguage="json"
                            value={JSON.stringify(tc.args || {})}
                            onChange={(value) => {
                              try {
                                if (value) updateToolCall(idx, tcIdx, { args: JSON.parse(value) });
                              } catch {}
                            }}
                            theme="vs-dark"
                            options={{
                              minimap: { enabled: false },
                              scrollBeyondLastLine: false,
                              lineNumbers: 'off',
                              glyphMargin: false,
                              folding: false,
                              lineDecorationsWidth: 0,
                              lineNumbersMinChars: 0,
                              wordWrap: 'off',
                              scrollbar: { vertical: 'hidden', horizontal: 'hidden' },
                              overviewRulerLanes: 0,
                              hideCursorInOverviewRuler: true,
                              overviewRulerBorder: false,
                              renderLineHighlight: 'none',
                              fontSize: 11,
                              padding: { top: 3, bottom: 3 },
                              automaticLayout: true,
                            }}
                          />
                        </div>
                        <button
                          className="btn btn-danger btn-sm"
                          onClick={() => removeToolCall(idx, tcIdx)}
                          style={{ padding: '4px 6px' }}
                        >
                          <Trash2 size={10} />
                        </button>
                      </div>
                    ))}
                    
                    <button
                      className="btn btn-secondary btn-sm"
                      onClick={() => addToolCall(idx)}
                      style={{ marginTop: 4 }}
                    >
                      <Plus size={12} /> Assert Tool Call
                    </button>
                  </div>
                </div>
              ))}
              
              <button
                className="btn btn-secondary"
                onClick={addInvocation}
              >
                <Plus size={14} /> Add Turn
              </button>
            </div>
            
            {/* Final State Assertion */}
            <div className="form-section">
              <h4>
                <CheckCircle size={14} style={{ marginRight: 6 }} />
                final_session_state <span style={{ fontWeight: 400, color: 'var(--text-muted)' }}>(optional)</span>
              </h4>
              <p style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 8 }}>
                Assert that session state contains these key-value pairs after all turns complete.
              </p>
              <div style={{ height: 80, borderRadius: 'var(--radius-sm)', overflow: 'hidden', border: '1px solid var(--border-color)' }}>
                <Editor
                  height="100%"
                  defaultLanguage="json"
                  value={localCase.expected_final_state ? JSON.stringify(localCase.expected_final_state, null, 2) : '{}'}
                  onChange={(value) => {
                    if (!value || value === '{}') {
                      saveCase({ expected_final_state: undefined });
                    } else {
                      try {
                        saveCase({ expected_final_state: JSON.parse(value) });
                      } catch {}
                    }
                  }}
                  theme="vs-dark"
                  options={{
                    minimap: { enabled: false },
                    scrollBeyondLastLine: false,
                    lineNumbers: 'off',
                    glyphMargin: false,
                    folding: false,
                    lineDecorationsWidth: 0,
                    lineNumbersMinChars: 0,
                    fontSize: 12,
                    automaticLayout: true,
                    scrollbar: { verticalScrollbarSize: 6 },
                  }}
                />
              </div>
            </div>
          </>
        )}
        
        {activeTab === 'rubrics' && (
          <>
            {/* LLM Judges */}
            <div className="form-section" style={{ marginBottom: 16 }}>
              {[
                { metric: 'safety_v1', label: 'safety_v1', default: 0.8, max: 1 },
                { metric: 'hallucinations_v1', label: 'hallucinations_v1', default: 0.8, max: 1 },
                { metric: 'response_evaluation_score', label: 'response_evaluation_score', default: 3.5, max: 5 },
                { metric: 'final_response_match_v2', label: 'final_response_match_v2', default: 0.7, max: 1 },
              ].map(({ metric, label, default: defaultVal, max }) => {
                const enabled = (localCase.enabled_metrics || []).find(em => em.metric === metric);
                const threshold = enabled?.threshold ?? defaultVal;
                
                return (
                  <div key={metric} style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
                    <label className="toggle-switch" style={{ margin: 0 }}>
                      <input
                        type="checkbox"
                        checked={!!enabled}
                        onChange={(e) => {
                          const metrics = [...(localCase.enabled_metrics || [])];
                          if (e.target.checked) {
                            metrics.push({ metric: metric as EvalMetricType, threshold: defaultVal });
                          } else {
                            const idx = metrics.findIndex(m => m.metric === metric);
                            if (idx !== -1) metrics.splice(idx, 1);
                          }
                          saveCase({ enabled_metrics: metrics });
                        }}
                      />
                      <span className="toggle-slider" />
                    </label>
                    <span style={{ fontSize: 12, opacity: enabled ? 1 : 0.5, minWidth: 100 }}>{label}</span>
                    <span style={{ fontSize: 11, color: 'var(--text-muted)', opacity: enabled ? 1 : 0.4 }}>≥</span>
                <input
                  type="number"
                      min={max === 5 ? 1 : 0}
                      max={max}
                  step={0.1}
                      value={threshold}
                      disabled={!enabled}
                      onChange={(e) => {
                        const metrics = [...(localCase.enabled_metrics || [])];
                        const idx = metrics.findIndex(m => m.metric === metric);
                        if (idx !== -1) {
                          metrics[idx] = { ...metrics[idx], threshold: parseFloat(e.target.value) || 0 };
                          saveCase({ enabled_metrics: metrics });
                        }
                      }}
                      style={{ width: 60, textAlign: 'center', opacity: enabled ? 1 : 0.3, padding: '2px 4px', fontSize: 11 }}
                    />
              </div>
                );
              })}
            </div>
            
            <hr style={{ border: 'none', borderTop: '1px solid var(--border-color)', margin: '16px 0' }} />
            
            {/* Custom Rubrics */}
            <div className="form-section">
              <h4>Custom Rubrics</h4>
              <p style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 8 }}>
                Natural language criteria evaluated by an LLM judge. Returns pass/fail per rubric.
              </p>
              {localCase.rubrics.map((rubric, idx) => (
                <div key={idx} className="tool-call-row" style={{ marginBottom: 8 }}>
                  <input
                    type="text"
                    value={rubric.rubric}
                onChange={(e) => {
                      const rubrics = [...localCase.rubrics];
                      rubrics[idx] = { rubric: e.target.value };
                      saveCase({ rubrics });
                }}
                    placeholder="e.g., The response mentions the return policy"
                    style={{ flex: 1 }}
                  />
                  <button
                    className="btn btn-danger btn-sm"
                    onClick={() => saveCase({ rubrics: localCase.rubrics.filter((_, i) => i !== idx) })}
                  >
                    <Trash2 size={12} />
                  </button>
            </div>
              ))}
              <button
                className="btn btn-secondary btn-sm"
                onClick={() => saveCase({ rubrics: [...localCase.rubrics, { rubric: '' }] })}
              >
                <Plus size={12} /> Add Rubric
              </button>
            </div>
          </>
        )}
        
        {activeTab === 'docs' && (
          <div style={{ fontSize: 13, lineHeight: 1.6, color: 'var(--text-secondary)', overflowY: 'auto', maxHeight: '100%' }}>
            <h3 style={{ marginBottom: 16, color: 'var(--text-primary)' }}>Evaluation Test Case Guide</h3>
            
            <section style={{ marginBottom: 24, padding: 12, background: 'rgba(var(--accent-primary-rgb), 0.1)', borderRadius: 'var(--radius-md)', border: '1px solid var(--accent-primary)' }}>
              <h4 style={{ color: 'var(--accent-primary)', marginBottom: 8 }}>🎯 Quick Overview</h4>
              <p>Each test case simulates a <strong>multi-turn conversation</strong> with an agent. For each turn (invocation), you provide a user message and define what you expect the agent to do.</p>
              <ul style={{ marginLeft: 20, marginTop: 8 }}>
                <li><strong>Invocations</strong> = conversation turns (user messages)</li>
                <li><strong>Expected Response</strong> = the agent's <em>final text reply</em> for that turn</li>
                <li><strong>Expected Tool Calls</strong> = tools the agent should invoke during that turn</li>
                <li><strong>Session State</strong> = test the <em>final state</em> after ALL turns complete</li>
              </ul>
            </section>
            
            <section style={{ marginBottom: 24 }}>
              <h4 style={{ color: 'var(--accent-primary)', marginBottom: 8 }}>📝 What is "Expected Response"?</h4>
              <p>The <strong>Expected Response</strong> is matched against the agent's <strong>final response</strong> for that specific turn — NOT every message.</p>
              <div style={{ background: 'var(--bg-secondary)', padding: 12, borderRadius: 'var(--radius-sm)', marginTop: 8 }}>
                <p style={{ marginBottom: 8 }}><strong>During one turn, an agent may:</strong></p>
                <ul style={{ marginLeft: 20, marginBottom: 12 }}>
                  <li>Send intermediate thinking/reasoning messages</li>
                  <li>Call multiple tools</li>
                  <li>Transfer to sub-agents (who may respond)</li>
                  <li>Finally send a <em>concluding response</em></li>
                </ul>
                <p>Only the <strong>last text response</strong> from the agent for that turn is compared against your Expected Response.</p>
              </div>
              <p style={{ marginTop: 8, fontStyle: 'italic', color: 'var(--text-muted)' }}>
                Tip: If you need to verify intermediate steps, use Tool Trajectory matching or custom Rubrics.
              </p>
            </section>
            
            <section style={{ marginBottom: 24 }}>
              <h4 style={{ color: 'var(--accent-primary)', marginBottom: 8 }}>🔄 Response Matching (ROUGE-1)</h4>
              <p>The <code>response_match_score</code> uses <strong>ROUGE-1 F1 scoring</strong> — fuzzy word-level matching:</p>
              <ul style={{ marginLeft: 20, marginTop: 8 }}>
                <li>Tokenizes both expected and actual responses into words</li>
                <li>Calculates word overlap (not exact string match)</li>
                <li>Returns a score from 0.0 to 1.0</li>
              </ul>
              <div style={{ background: 'var(--bg-secondary)', padding: 12, borderRadius: 'var(--radius-sm)', marginTop: 8 }}>
                <p><strong>Example:</strong></p>
                <p>Expected: <code>"The weather in Paris is sunny today"</code></p>
                <p>Actual: <code>"Today in Paris, expect sunny weather"</code></p>
                <p style={{ marginTop: 8, color: 'var(--success)' }}>✓ High ROUGE-1 score (same words, different order)</p>
              </div>
              <p style={{ marginTop: 8 }}>A threshold of <strong>0.7</strong> means 70% word overlap is required to pass.</p>
            </section>
            
            <section style={{ marginBottom: 24 }}>
              <h4 style={{ color: 'var(--accent-primary)', marginBottom: 8 }}>🛠️ Tool Trajectory Matching</h4>
              <p>The <code>tool_trajectory_avg_score</code> verifies the agent called expected tools. Match types:</p>
              <ul style={{ marginLeft: 20, marginTop: 8 }}>
                <li><strong>Exact</strong> — Same tools in same order, no extras allowed</li>
                <li><strong>In Order</strong> — Expected tools appear in order, extras allowed between</li>
                <li><strong>Any Order</strong> — All expected tools present, any order, extras allowed</li>
              </ul>
              <p style={{ marginTop: 8 }}>For each tool, you can match by:</p>
              <ul style={{ marginLeft: 20, marginTop: 4 }}>
                <li><strong>Name Only</strong> — Just check the tool was called</li>
                <li><strong>Exact Args</strong> — Arguments must match exactly (provide JSON)</li>
                <li><strong>Args Subset</strong> — Your expected args must be present in actual args</li>
              </ul>
            </section>
            
            <section style={{ marginBottom: 24 }}>
              <h4 style={{ color: 'var(--accent-primary)', marginBottom: 8 }}>💾 Session State Testing</h4>
              <p><strong>Initial State</strong> (Settings tab) — Pre-populate session state before running the test:</p>
              <ul style={{ marginLeft: 20, marginTop: 8 }}>
                <li>Set user preferences or context</li>
                <li>Simulate a specific scenario</li>
                <li>Test state-dependent behavior</li>
              </ul>
              <p style={{ marginTop: 12 }}><strong>Expected Final State</strong> — Verified at the <em>very end</em> of the test case, <strong>after ALL invocations complete</strong>.</p>
              <div style={{ background: 'var(--bg-secondary)', padding: 12, borderRadius: 'var(--radius-sm)', marginTop: 8, borderLeft: '3px solid var(--warning)' }}>
                <p style={{ margin: 0 }}><strong>Important:</strong> State is tested once after the entire conversation, NOT after each turn. To test state changes per-turn, use separate test cases.</p>
              </div>
            </section>
            
            <section style={{ marginBottom: 24 }}>
              <h4 style={{ color: 'var(--accent-primary)', marginBottom: 8 }}>🎯 Target Agent (Settings tab)</h4>
              <p>By default, tests run against the <strong>root_agent</strong> of your App. You can select a specific sub-agent to test in isolation:</p>
              <ul style={{ marginLeft: 20, marginTop: 8 }}>
                <li><strong>root_agent</strong> — Test the full agent hierarchy (default)</li>
                <li><strong>Specific agent</strong> — Unit test individual agents</li>
              </ul>
              <p style={{ marginTop: 8, fontStyle: 'italic', color: 'var(--text-muted)' }}>
                Useful for testing sub-agents independently before integrating into the full system.
              </p>
            </section>
            
            <section style={{ marginBottom: 24 }}>
              <h4 style={{ color: 'var(--accent-primary)', marginBottom: 8 }}>📋 Custom Rubrics</h4>
              <p>Rubrics are custom yes/no criteria evaluated by an LLM judge. Examples:</p>
              <ul style={{ marginLeft: 20, marginTop: 8 }}>
                <li>"Does the response mention the product price?"</li>
                <li>"Is the tone professional and helpful?"</li>
                <li>"Does the response avoid mentioning competitors?"</li>
              </ul>
              <p style={{ marginTop: 8, fontStyle: 'italic', color: 'var(--text-muted)' }}>
                Note: Rubric evaluation requires LLM-judged metrics to be enabled in the Eval Set.
              </p>
            </section>
            
            <section style={{ marginBottom: 24 }}>
              <h4 style={{ color: 'var(--accent-primary)', marginBottom: 8 }}>📊 Available Metrics</h4>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--border-color)' }}>
                    <th style={{ textAlign: 'left', padding: '8px 4px' }}>Metric</th>
                    <th style={{ textAlign: 'left', padding: '8px 4px' }}>Type</th>
                    <th style={{ textAlign: 'left', padding: '8px 4px' }}>Description</th>
                  </tr>
                </thead>
                <tbody>
                  {(Object.keys(METRIC_INFO) as EvalMetricType[]).map(metric => (
                    <tr key={metric} style={{ borderBottom: '1px solid var(--border-color)' }}>
                      <td style={{ padding: '8px 4px', fontFamily: 'var(--font-mono)', fontSize: 11 }}>{metric}</td>
                      <td style={{ padding: '8px 4px' }}>
                        {METRIC_INFO[metric].requiresJudge ? (
                          <span style={{ fontSize: 10, padding: '2px 6px', background: 'var(--accent-primary)', color: 'white', borderRadius: 4 }}>LLM Judge</span>
                        ) : (
                          <span style={{ fontSize: 10, padding: '2px 6px', background: 'var(--bg-tertiary)', borderRadius: 4 }}>Built-in</span>
                        )}
                      </td>
                      <td style={{ padding: '8px 4px', color: 'var(--text-muted)' }}>{METRIC_INFO[metric].description}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
            
            <section>
              <h4 style={{ color: 'var(--accent-primary)', marginBottom: 8 }}>💡 Tips</h4>
              <ul style={{ marginLeft: 20 }}>
                <li>Start with simple single-turn tests, then add complexity</li>
                <li>Use "In Order" matching for most tool trajectory tests</li>
                <li>Lower ROUGE thresholds (0.5-0.6) for creative/varied responses</li>
                <li>Higher thresholds (0.8-0.9) for factual/precise responses</li>
                <li>Use tags to organize tests by feature or priority</li>
                <li>Test sub-agents individually using Target Agent selector</li>
              </ul>
            </section>
          </div>
        )}
        
        {activeTab === 'json' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16, height: '100%' }}>
            <div style={{ fontSize: 12, color: 'var(--text-secondary)', padding: '8px 0' }}>
              <p style={{ margin: 0 }}>
                This is the ADK-compatible JSON format for this test case. You can use this with <code style={{ background: 'var(--bg-tertiary)', padding: '2px 6px', borderRadius: 4 }}>adk eval</code>.
              </p>
            </div>
            <div style={{ flex: 1, minHeight: 300, border: '1px solid var(--border-color)', borderRadius: 'var(--radius-md)', overflow: 'hidden' }}>
              <Editor
                height="100%"
                language="json"
                theme="vs-dark"
                value={JSON.stringify({
                  name: localCase.name,
                  description: localCase.description || undefined,
                  tags: localCase.tags?.length ? localCase.tags : undefined,
                  target_agent: localCase.target_agent !== 'root_agent' ? localCase.target_agent : undefined,
                  invocations: localCase.invocations.map(inv => ({
                    user_message: inv.user_message,
                    expected_response: inv.expected_response || undefined,
                    expected_tool_calls: inv.expected_tool_calls?.length ? inv.expected_tool_calls.map(tc => ({
                      tool_name: tc.tool_name,
                      args: tc.match_type !== 'name_only' && Object.keys(tc.args || {}).length ? tc.args : undefined,
                    })) : undefined,
                  })),
                  session_input: Object.keys(localCase.session_input || {}).length ? { state: localCase.session_input } : undefined,
                  final_session_state: Object.keys(localCase.final_session_state || {}).length ? localCase.final_session_state : undefined,
                  rubrics: localCase.rubrics?.length ? localCase.rubrics.map(r => r.rubric) : undefined,
                }, null, 2)}
                options={{
                  readOnly: true,
                  minimap: { enabled: false },
                  fontSize: 12,
                  fontFamily: "'JetBrains Mono', monospace",
                  lineNumbers: 'on',
                  scrollBeyondLastLine: false,
                  automaticLayout: true,
                  tabSize: 2,
                  wordWrap: 'on',
                  padding: { top: 12 },
                }}
              />
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <button 
                className="btn btn-secondary btn-sm"
                onClick={() => {
                  const json = JSON.stringify({
                    name: localCase.name,
                    description: localCase.description || undefined,
                    tags: localCase.tags?.length ? localCase.tags : undefined,
                    target_agent: localCase.target_agent !== 'root_agent' ? localCase.target_agent : undefined,
                    invocations: localCase.invocations.map(inv => ({
                      user_message: inv.user_message,
                      expected_response: inv.expected_response || undefined,
                      expected_tool_calls: inv.expected_tool_calls?.length ? inv.expected_tool_calls.map(tc => ({
                        tool_name: tc.tool_name,
                        args: tc.match_type !== 'name_only' && Object.keys(tc.args || {}).length ? tc.args : undefined,
                      })) : undefined,
                    })),
                    session_input: Object.keys(localCase.session_input || {}).length ? { state: localCase.session_input } : undefined,
                    final_session_state: Object.keys(localCase.final_session_state || {}).length ? localCase.final_session_state : undefined,
                    rubrics: localCase.rubrics?.length ? localCase.rubrics.map(r => r.rubric) : undefined,
                  }, null, 2);
                  navigator.clipboard.writeText(json);
                }}
              >
                <Copy size={14} /> Copy JSON
              </button>
            </div>
          </div>
        )}
      </div>
      
      {result && (
        <div className="result-panel">
          <div className={`result-header ${result.passed ? 'passed' : 'failed'}`}>
            {result.passed ? (
              <><CheckCircle size={18} /> <strong>Passed</strong></>
            ) : (
              <><XCircle size={18} /> <strong>Failed</strong></>
            )}
            <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 12 }}>
              {result.total_tokens ? (
                <span style={{ fontSize: 11, color: 'var(--text-muted)' }} title="Total tokens used">
                  {result.total_tokens.toLocaleString()} tokens
                </span>
              ) : null}
              <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>
              {result.duration_ms.toFixed(0)}ms
            </span>
              {result.session_id && (
                <button
                  className="btn btn-secondary btn-sm"
                  onClick={() => {
                    // Navigate to Run tab with session loaded
                    window.location.href = `/project/${project?.id}/run?session=${result.session_id}`;
                  }}
                  title="View this session in the Run panel"
                  style={{ fontSize: 11 }}
                >
                  <ExternalLink size={12} />
                  View Session
                </button>
              )}
              {onClearResult && (
                <button
                  className="btn btn-secondary btn-sm"
                  onClick={onClearResult}
                  title="Close test results"
                  style={{ fontSize: 11, padding: '4px 8px' }}
                >
                  ✕
                </button>
              )}
            </div>
          </div>
          
          <div className="result-scores">
            {result.metric_results.map((mr, idx) => {
              const formatted = formatMetricScore(mr.metric, mr.score, mr.threshold);
              return (
              <div key={idx} className="score-card">
                <div className={`score-value ${mr.passed ? 'passed' : 'failed'}`}>
                  {formatted.value}
              </div>
                <div className="score-label">
                  {METRIC_INFO[mr.metric as EvalMetricType]?.name || mr.metric}
            </div>
                <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 2 }}>
                  {formatted.comparison}
              </div>
                {mr.error && (
                  <div style={{ fontSize: 10, color: 'var(--error)', marginTop: 4 }}>
                    {mr.error}
            </div>
                )}
            </div>
              );
            })}
          </div>
          
          {/* Rubric Results */}
          {result.rubric_results && result.rubric_results.length > 0 && (
            <div style={{ marginTop: 16 }}>
              <h5 style={{ fontSize: 13, marginBottom: 8 }}>Custom Rubrics</h5>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {result.rubric_results.map((rr: any, idx: number) => (
                  <div 
                    key={idx}
                    style={{
                      padding: '8px 12px',
                      borderRadius: 'var(--radius-sm)',
                      background: rr.passed ? 'rgba(var(--success-rgb), 0.1)' : 'rgba(var(--error-rgb), 0.1)',
                      border: `1px solid ${rr.passed ? 'var(--success)' : 'var(--error)'}`,
                      display: 'flex',
                      alignItems: 'center',
                      gap: 10,
                    }}
                  >
                    <span style={{ 
                      fontSize: 16, 
                      color: rr.passed ? 'var(--success)' : 'var(--error)',
                      fontWeight: 'bold'
                    }}>
                      {rr.passed ? '✓' : '✗'}
                    </span>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 12, color: 'var(--text-primary)' }}>
                        {rr.rubric}
                      </div>
                      {rr.error && (
                        <div style={{ fontSize: 10, color: 'var(--error)', marginTop: 2 }}>
                          Error: {rr.error}
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
          
          {result.invocation_results.map((invRes, idx) => (
            <div key={idx} className="result-details">
              <h5>Turn {idx + 1}: {invRes.user_message.length > 50 ? invRes.user_message.slice(0, 50) + '…' : invRes.user_message}</h5>
              
              {invRes.metric_results.length > 0 && (
                <div style={{ display: 'flex', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
                  {invRes.metric_results.map((mr, mIdx) => {
                    const formatted = formatMetricScore(mr.metric, mr.score, mr.threshold);
                    return (
                    <span 
                      key={mIdx} 
                      style={{
                        fontSize: 11,
                        padding: '2px 6px',
                        borderRadius: 'var(--radius-sm)',
                        background: mr.passed ? 'rgba(var(--success-rgb), 0.15)' : 'rgba(var(--error-rgb), 0.15)',
                        color: mr.passed ? 'var(--success)' : 'var(--error)',
                      }}
                    >
                      {METRIC_INFO[mr.metric as EvalMetricType]?.name || mr.metric}: {formatted.value}
                    </span>
                    );
                  })}
                </div>
              )}
              
              <div className="detail-box">
                <strong>Actual Response:</strong>{'\n'}
                {invRes.actual_response || '(no response)'}{'\n\n'}
                {invRes.actual_tool_calls.length > 0 && (
                  <>
                    <strong>Tool Calls:</strong>{'\n'}
                    {invRes.actual_tool_calls.map((tc, i) => (
                      `  ${i + 1}. ${tc.name}(${JSON.stringify(tc.args)})\n`
                    )).join('')}
                  </>
                )}
              </div>
            </div>
          ))}
          
          {result.error && (
            <div className="result-details">
              <h5 style={{ color: 'var(--error)' }}>Error</h5>
              <div className="detail-box" style={{ color: 'var(--error)' }}>
                {result.error}
              </div>
            </div>
          )}
        </div>
      )}
    </>
  );
}

// Eval Set Editor Component
function EvalSetEditor({
  evalSet,
  projectId,
  result,
  isRunning,
  caseResults,
  onUpdate,
  onDelete,
  onRun,
  onExport,
}: {
  evalSet: EvalSet;
  projectId: string;
  result?: EvalSetResult;
  isRunning: boolean;
  caseResults: Map<string, EvalCaseResult>;
  onUpdate: (updates: Partial<EvalSet>) => void;
  onDelete: () => void;
  onRun: () => void;
  onExport: () => void;
}) {
  const [localName, setLocalName] = useState(evalSet.name);
  const [showJson, setShowJson] = useState(false);
  
  // Update local name when evalSet changes (from external source)
  useEffect(() => {
    setLocalName(evalSet.name);
  }, [evalSet.id]);
  
  // Save on blur
  const handleNameBlur = useCallback(() => {
    if (localName !== evalSet.name) {
      onUpdate({ name: localName });
    }
  }, [localName, evalSet.name, onUpdate]);
  
  const formatScore = (score?: number | null) => {
    if (score === null || score === undefined) return '-';
    return `${Math.round(score * 100)}%`;
  };
  
  return (
    <>
      <div className="editor-header">
        <FolderTree size={20} style={{ color: 'var(--accent-secondary)' }} />
        <input
          type="text"
          value={localName}
          onChange={(e) => setLocalName(e.target.value)}
          onBlur={handleNameBlur}
          placeholder="Eval set name"
        />
        <button 
          className="btn btn-secondary btn-sm"
          onClick={() => {
            const url = `${window.location.origin}/project/${projectId}/evaluate?set=${evalSet.id}`;
            navigator.clipboard.writeText(url);
          }}
          title="Copy link to this eval set"
        >
          <Link2 size={14} />
        </button>
        <button 
          className={`btn btn-sm ${showJson ? 'btn-primary' : 'btn-secondary'}`}
          onClick={() => setShowJson(!showJson)}
          title="View/Hide JSON"
        >
          <Code size={14} />
          JSON
        </button>
        <button 
          className="btn btn-secondary btn-sm"
          onClick={onExport}
          title="Export as JSON (compatible with adk eval)"
        >
          <Download size={14} />
        </button>
        <button 
          className="btn btn-primary btn-sm"
          onClick={onRun}
          disabled={isRunning}
        >
          {isRunning ? <Clock size={14} className="spinning" /> : <Play size={14} />}
          Run All
        </button>
        <button 
          className="btn btn-danger btn-sm"
          onClick={onDelete}
        >
          <Trash2 size={14} />
        </button>
      </div>
      
      <div className="editor-content">
        {showJson ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16, height: '100%' }}>
            <div style={{ fontSize: 12, color: 'var(--text-secondary)', padding: '8px 0' }}>
              <p style={{ margin: 0 }}>
                This is the ADK-compatible JSON format for this evaluation set. Save this file and use with <code style={{ background: 'var(--bg-tertiary)', padding: '2px 6px', borderRadius: 4 }}>adk eval &lt;agent_path&gt; &lt;eval_file.json&gt;</code>
              </p>
            </div>
            <div style={{ flex: 1, minHeight: 400, border: '1px solid var(--border-color)', borderRadius: 'var(--radius-md)', overflow: 'hidden' }}>
              <Editor
                height="100%"
                language="json"
                theme="vs-dark"
                value={JSON.stringify([{
                  id: evalSet.id,
                  name: evalSet.name,
                  description: evalSet.description || undefined,
                  eval_cases: evalSet.eval_cases.map(ec => ({
                    name: ec.name,
                    description: ec.description || undefined,
                    tags: ec.tags?.length ? ec.tags : undefined,
                    target_agent: ec.target_agent !== 'root_agent' ? ec.target_agent : undefined,
                    invocations: ec.invocations.map(inv => ({
                      user_message: inv.user_message,
                      expected_response: inv.expected_response || undefined,
                      expected_tool_calls: inv.expected_tool_calls?.length ? inv.expected_tool_calls.map(tc => ({
                        tool_name: tc.tool_name,
                        args: tc.match_type !== 'name_only' && Object.keys(tc.args || {}).length ? tc.args : undefined,
                      })) : undefined,
                    })),
                    session_input: Object.keys(ec.session_input || {}).length ? { state: ec.session_input } : undefined,
                    final_session_state: Object.keys(ec.final_session_state || {}).length ? ec.final_session_state : undefined,
                    rubrics: ec.rubrics?.length ? ec.rubrics.map(r => r.rubric) : undefined,
                  })),
                  eval_config: evalSet.eval_config ? {
                    judge_model: evalSet.eval_config.judge_model || undefined,
                    metrics: evalSet.eval_config.metrics?.filter(m => m.enabled) || undefined,
                  } : undefined,
                }], null, 2)}
                options={{
                  readOnly: true,
                  minimap: { enabled: false },
                  fontSize: 12,
                  fontFamily: "'JetBrains Mono', monospace",
                  lineNumbers: 'on',
                  scrollBeyondLastLine: false,
                  automaticLayout: true,
                  tabSize: 2,
                  wordWrap: 'on',
                  padding: { top: 12 },
                }}
              />
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <button 
                className="btn btn-secondary btn-sm"
                onClick={() => {
                  const json = JSON.stringify([{
                    id: evalSet.id,
                    name: evalSet.name,
                    description: evalSet.description || undefined,
                    eval_cases: evalSet.eval_cases.map(ec => ({
                      name: ec.name,
                      description: ec.description || undefined,
                      tags: ec.tags?.length ? ec.tags : undefined,
                      target_agent: ec.target_agent !== 'root_agent' ? ec.target_agent : undefined,
                      invocations: ec.invocations.map(inv => ({
                        user_message: inv.user_message,
                        expected_response: inv.expected_response || undefined,
                        expected_tool_calls: inv.expected_tool_calls?.length ? inv.expected_tool_calls.map(tc => ({
                          tool_name: tc.tool_name,
                          args: tc.match_type !== 'name_only' && Object.keys(tc.args || {}).length ? tc.args : undefined,
                        })) : undefined,
                      })),
                      session_input: Object.keys(ec.session_input || {}).length ? { state: ec.session_input } : undefined,
                      final_session_state: Object.keys(ec.final_session_state || {}).length ? ec.final_session_state : undefined,
                      rubrics: ec.rubrics?.length ? ec.rubrics.map(r => r.rubric) : undefined,
                    })),
                    eval_config: evalSet.eval_config ? {
                      judge_model: evalSet.eval_config.judge_model || undefined,
                      metrics: evalSet.eval_config.metrics?.filter(m => m.enabled) || undefined,
                    } : undefined,
                  }], null, 2);
                  navigator.clipboard.writeText(json);
                }}
              >
                <Copy size={14} /> Copy JSON
              </button>
            </div>
          </div>
        ) : (
          <>
        <div className="form-section">
          <h4>Description</h4>
          <textarea
            value={evalSet.description}
            onChange={(e) => onUpdate({ description: e.target.value })}
            placeholder="Description of this evaluation set..."
            style={{ minHeight: 40 }}
          />
        </div>
        
        <div className="form-section">
              <h4>LLM Judge Model</h4>
          <p style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 8 }}>
            Model used for LLM-judged metrics (safety, hallucinations, etc.).
          </p>
          <JudgeModelSelector
            value={evalSet.eval_config?.judge_model || ''}
            onChange={(value) => onUpdate({ 
              eval_config: { 
                ...evalSet.eval_config, 
                judge_model: value 
              } 
            })}
          />
        </div>
        
        <div className="form-section">
          <h4><Settings size={14} /> Evaluation Metrics</h4>
          <p style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 8 }}>
            Configure which metrics to use and their pass thresholds.
          </p>
          
          {(Object.keys(METRIC_INFO) as EvalMetricType[]).map(metric => {
            const info = METRIC_INFO[metric];
            const config = evalSet.eval_config?.metrics?.find(m => m.metric === metric);
            const isEnabled = config?.enabled ?? false;
            const threshold = config?.criterion?.threshold ?? 0.7;
            
            return (
              <div key={metric} style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
                <label className="toggle-switch" style={{ margin: 0 }}>
                  <input
                    type="checkbox"
                    checked={isEnabled}
                    onChange={(e) => {
                      const metrics = [...(evalSet.eval_config?.metrics || [])];
                      const idx = metrics.findIndex(m => m.metric === metric);
                      if (e.target.checked) {
                        if (idx === -1) {
                          metrics.push({ metric, enabled: true, criterion: { threshold: 0.7 } });
                        } else {
                          metrics[idx] = { ...metrics[idx], enabled: true };
                        }
                      } else {
                        if (idx !== -1) {
                          metrics[idx] = { ...metrics[idx], enabled: false };
                        }
                      }
                      onUpdate({ eval_config: { ...evalSet.eval_config, metrics } });
                    }}
                  />
                  <span className="toggle-slider" />
                </label>
                <span style={{ fontSize: 12, opacity: isEnabled ? 1 : 0.5, minWidth: 140, fontWeight: isEnabled ? 500 : 400 }}>
                  {info.name}
                  {info.requiresJudge && <span style={{ fontSize: 9, marginLeft: 4, color: 'var(--accent-primary)' }}>LLM</span>}
                </span>
                <span style={{ fontSize: 11, color: 'var(--text-muted)', opacity: isEnabled ? 1 : 0.4 }}>≥</span>
              <input
                type="number"
                min={0}
                max={1}
                step={0.1}
                  value={threshold}
                  disabled={!isEnabled}
                  onChange={(e) => {
                    const metrics = [...(evalSet.eval_config?.metrics || [])];
                    const idx = metrics.findIndex(m => m.metric === metric);
                    if (idx !== -1) {
                      metrics[idx] = { 
                        ...metrics[idx], 
                        criterion: { ...metrics[idx].criterion, threshold: parseFloat(e.target.value) || 0.7 }
                      };
                      onUpdate({ eval_config: { ...evalSet.eval_config, metrics } });
                    }
                  }}
                  style={{ width: 60, textAlign: 'center', opacity: isEnabled ? 1 : 0.3, padding: '2px 4px', fontSize: 11 }}
              />
            </div>
            );
          })}
          
          <div className="form-row" style={{ marginTop: 16 }}>
            <div className="form-field">
              <label>Default Trajectory Match Type</label>
              <select
                value={evalSet.eval_config?.default_trajectory_match_type || 'in_order'}
                onChange={(e) => onUpdate({ 
                  eval_config: { 
                    ...evalSet.eval_config, 
                  default_trajectory_match_type: e.target.value as 'exact' | 'in_order' | 'any_order' 
                  }
                })}
              >
                <option value="exact">Exact (same order, no extras)</option>
                <option value="in_order">In Order (extras allowed between)</option>
                <option value="any_order">Any Order (all present, any order)</option>
              </select>
            </div>
            <div className="form-field">
              <label>Number of Runs</label>
              <input
                type="number"
                min={1}
                max={10}
                value={evalSet.eval_config?.num_runs || 1}
                onChange={(e) => onUpdate({ 
                  eval_config: { 
                    ...evalSet.eval_config, 
                    num_runs: parseInt(e.target.value) || 1 
                  }
                })}
              />
              <p style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>
                Run each test multiple times for statistical reliability.
              </p>
            </div>
          </div>
        </div>
        
        <div className="form-section">
          <h4><Percent size={14} /> Coverage Summary</h4>
          
          {result ? (
            <>
              <div className="result-scores">
                <div className="score-card">
                  <div className="score-value" style={{ color: 'var(--accent-primary)' }}>
                    {result.passed_cases}/{result.total_cases}
                  </div>
                  <div className="score-label">Cases Passed</div>
                </div>
                <div className="score-card">
                  <div className={`score-value ${result.overall_pass_rate >= 0.8 ? 'passed' : 'failed'}`}>
                    {formatScore(result.overall_pass_rate)}
                  </div>
                  <div className="score-label">Pass Rate</div>
                </div>
                {Object.entries(result.metric_avg_scores || {}).map(([metric, score]) => {
                  const formatted = formatMetricScore(metric, score as number);
                  return (
                  <div key={metric} className="score-card">
                  <div className="score-value">
                      {formatted.value}
                  </div>
                    <div className="score-label">
                      Avg {METRIC_INFO[metric as EvalMetricType]?.name || metric}
                </div>
                  </div>
                  );
                })}
              </div>
              
              <div style={{ marginTop: 16 }}>
                <div style={{ marginBottom: 4, fontSize: 12, color: 'var(--text-muted)' }}>
                  Overall Pass Rate
                </div>
                <div className="coverage-bar">
                  <div 
                    className={`coverage-fill ${result.overall_pass_rate >= 0.8 ? 'passed' : 'failed'}`}
                    style={{ width: `${result.overall_pass_rate * 100}%` }}
                  />
                </div>
              </div>
              
              {Object.entries(result.metric_pass_rates || {}).length > 0 && (
                <div style={{ marginTop: 16 }}>
                  <h5 style={{ fontSize: 13, marginBottom: 8 }}>Metric Pass Rates</h5>
                  {Object.entries(result.metric_pass_rates).map(([metric, rate]) => (
                    <div key={metric} style={{ marginBottom: 8 }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 4 }}>
                        <span>{METRIC_INFO[metric as EvalMetricType]?.name || metric}</span>
                        <span>{formatScore(rate)}</span>
                      </div>
                      <div className="coverage-bar">
                        <div 
                          className={`coverage-fill ${rate >= 0.8 ? 'passed' : 'failed'}`}
                          style={{ width: `${rate * 100}%` }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              )}
              
              <div style={{ marginTop: 16 }}>
                <h5 style={{ fontSize: 13, marginBottom: 8 }}>Individual Results</h5>
                <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse' }}>
                  <thead>
                    <tr style={{ borderBottom: '1px solid var(--border-color)' }}>
                      <th style={{ textAlign: 'left', padding: '8px 4px' }}>Test Case</th>
                      <th style={{ textAlign: 'center', padding: '8px 4px' }}>Metrics</th>
                      <th style={{ textAlign: 'center', padding: '8px 4px' }}>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.case_results.map(cr => (
                      <tr key={cr.eval_case_id} style={{ borderBottom: '1px solid var(--border-color)' }}>
                        <td style={{ padding: '8px 4px' }}>{cr.eval_case_name}</td>
                        <td style={{ textAlign: 'center', padding: '8px 4px' }}>
                          {cr.metric_results.map((mr, idx) => {
                            const formatted = formatMetricScore(mr.metric, mr.score, mr.threshold);
                            return (
                            <span 
                              key={idx}
                              style={{
                                fontSize: 10,
                                padding: '2px 4px',
                                marginRight: 4,
                                borderRadius: 'var(--radius-sm)',
                                background: mr.passed ? 'rgba(var(--success-rgb), 0.15)' : 'rgba(var(--error-rgb), 0.15)',
                                color: mr.passed ? 'var(--success)' : 'var(--error)',
                              }}
                            >
                              {formatted.value}
                            </span>
                            );
                          })}
                        </td>
                        <td style={{ textAlign: 'center', padding: '8px 4px' }}>
                          {cr.passed ? (
                            <CheckCircle size={14} style={{ color: 'var(--success)' }} />
                          ) : cr.error ? (
                            <AlertCircle size={14} style={{ color: 'var(--warning)' }} />
                          ) : (
                            <XCircle size={14} style={{ color: 'var(--error)' }} />
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          ) : (
            <div style={{ 
              textAlign: 'center', 
              padding: '32px', 
              color: 'var(--text-muted)',
              background: 'var(--bg-tertiary)',
              borderRadius: 'var(--radius-md)'
            }}>
              <Target size={32} style={{ marginBottom: 8, opacity: 0.3 }} />
              <p>Run the evaluation set to see coverage metrics</p>
            </div>
          )}
        </div>
        
        <div className="form-section">
          <h4>Test Cases ({evalSet.eval_cases.length})</h4>
          {evalSet.eval_cases.length === 0 ? (
            <p style={{ color: 'var(--text-muted)', fontSize: 13 }}>
              No test cases yet. Add cases to this eval set to start testing.
            </p>
          ) : (
            <ul style={{ listStyle: 'none', padding: 0 }}>
              {evalSet.eval_cases.map(c => {
                const caseResult = caseResults.get(c.id);
                return (
                  <li 
                    key={c.id}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 8,
                      padding: '8px 12px',
                      background: 'var(--bg-tertiary)',
                      borderRadius: 'var(--radius-sm)',
                      marginBottom: 8,
                    }}
                  >
                    {caseResult ? (
                      caseResult.passed ? (
                        <CheckCircle size={14} style={{ color: 'var(--success)' }} />
                      ) : (
                        <XCircle size={14} style={{ color: 'var(--error)' }} />
                      )
                    ) : (
                      <FileCheck size={14} style={{ color: 'var(--text-muted)' }} />
                    )}
                    <span style={{ flex: 1 }}>{c.name}</span>
                    <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                      {c.invocations.length} turn(s)
                    </span>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
          </>
        )}
      </div>
    </>
  );
}
