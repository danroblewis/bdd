"""ADK-based Evaluation Service.

This module provides evaluation functionality using ADK's LocalEvalService,
bridging our YAML-based project format with ADK's evaluation infrastructure.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from google.genai import types as genai_types

# Import ADK evaluation modules
try:
    from google.adk.agents.base_agent import BaseAgent
    from google.adk.evaluation.eval_case import (
        EvalCase as AdkEvalCase,
        Invocation as AdkInvocation,
        SessionInput as AdkSessionInput,
    )
    from google.adk.evaluation.eval_set import EvalSet as AdkEvalSet
    from google.adk.evaluation.eval_config import (
        EvalConfig as AdkEvalConfig,
        get_eval_metrics_from_config,
    )
    from google.adk.evaluation.eval_result import EvalCaseResult as AdkEvalCaseResult
    from google.adk.evaluation.in_memory_eval_sets_manager import InMemoryEvalSetsManager
    from google.adk.evaluation.local_eval_service import LocalEvalService
    from google.adk.evaluation.base_eval_service import (
        InferenceRequest,
        InferenceConfig,
        EvaluateRequest,
        EvaluateConfig,
    )
    from google.adk.evaluation.evaluator import EvalStatus
    from google.adk.sessions.in_memory_session_service import InMemorySessionService
    from google.adk.artifacts.in_memory_artifact_service import InMemoryArtifactService
    ADK_EVAL_AVAILABLE = True
except ImportError as e:
    ADK_EVAL_AVAILABLE = False
    ADK_IMPORT_ERROR = str(e)

from models import (
    Project, EvalSet, EvalCase, EvalInvocation, ExpectedToolCall,
    EvalSetResult, EvalCaseResult, InvocationResult, MetricResult,
    ToolTrajectoryMatchType, EvalMetricType, EvalConfig, EvalMetricConfig,
)

logger = logging.getLogger(__name__)


class AdkEvaluationService:
    """Service for running evaluations using ADK's LocalEvalService."""
    
    def __init__(self, runtime_manager):
        self.runtime_manager = runtime_manager
        
        if not ADK_EVAL_AVAILABLE:
            logger.warning(f"ADK evaluation modules not available: {ADK_IMPORT_ERROR}")
    
    def _convert_to_adk_invocation(
        self,
        invocation: EvalInvocation,
        include_expected: bool = True,
    ) -> AdkInvocation:
        """Convert our EvalInvocation to ADK's Invocation format."""
        # Create user content
        user_content = genai_types.Content(
            role="user",
            parts=[genai_types.Part.from_text(text=invocation.user_message)]
        )
        
        # Create expected response content if provided
        final_response = None
        if include_expected and invocation.expected_response:
            final_response = genai_types.Content(
                role="model",
                parts=[genai_types.Part.from_text(text=invocation.expected_response)]
            )
        
        return AdkInvocation(
            invocation_id=invocation.id or str(uuid.uuid4())[:8],
            user_content=user_content,
            final_response=final_response,
        )
    
    def _convert_to_adk_eval_case(
        self,
        eval_case: EvalCase,
        app_name: str,
    ) -> AdkEvalCase:
        """Convert our EvalCase to ADK's EvalCase format."""
        # Create conversation from invocations
        conversation = [
            self._convert_to_adk_invocation(inv)
            for inv in eval_case.invocations
        ]
        
        # Create session input
        session_input = AdkSessionInput(
            app_name=app_name,
            user_id="eval_user",
            state=eval_case.session_input or {},
        )
        
        return AdkEvalCase(
            eval_id=eval_case.id,
            conversation=conversation,
            session_input=session_input,
        )
    
    def _convert_to_adk_eval_config(
        self,
        eval_config: EvalConfig,
    ) -> AdkEvalConfig:
        """Convert our EvalConfig to ADK's EvalConfig format."""
        criteria = {}
        
        # Map our enabled metrics to ADK criteria
        for metric_config in eval_config.enabled_metrics:
            metric_name = metric_config.metric
            threshold = metric_config.threshold
            
            # Map our metric names to ADK metric names
            adk_metric_map = {
                EvalMetricType.RESPONSE_MATCH_SCORE.value: "response_match_score",
                EvalMetricType.TOOL_TRAJECTORY_AVG_SCORE.value: "tool_trajectory_avg_score",
                EvalMetricType.SAFETY_V1.value: "safety_v1",
                EvalMetricType.HALLUCINATIONS_V1.value: "hallucinations_v1",
                EvalMetricType.RESPONSE_EVALUATION_SCORE.value: "response_evaluation_score",
                EvalMetricType.FINAL_RESPONSE_MATCH_V2.value: "final_response_match_v2",
            }
            
            adk_metric_name = adk_metric_map.get(metric_name, metric_name)
            criteria[adk_metric_name] = threshold
        
        return AdkEvalConfig(criteria=criteria)
    
    def _convert_adk_result_to_ours(
        self,
        adk_result: AdkEvalCaseResult,
        eval_case: EvalCase,
        eval_set_id: str = "",
        eval_set_name: str = "",
    ) -> EvalCaseResult:
        """Convert ADK's EvalCaseResult to our EvalCaseResult format."""
        # Extract invocation results
        invocation_results = []
        for idx, per_inv in enumerate(adk_result.eval_metric_result_per_invocation):
            orig_inv = eval_case.invocations[idx] if idx < len(eval_case.invocations) else None
            
            # Get actual response text
            actual_response = ""
            if per_inv.actual_invocation and per_inv.actual_invocation.final_response:
                for part in per_inv.actual_invocation.final_response.parts or []:
                    if hasattr(part, 'text') and part.text:
                        actual_response += part.text
            
            # Get actual tool calls
            actual_tool_calls = []
            if per_inv.actual_invocation and per_inv.actual_invocation.intermediate_data:
                int_data = per_inv.actual_invocation.intermediate_data
                if hasattr(int_data, 'tool_uses'):
                    for fc in int_data.tool_uses:
                        actual_tool_calls.append({
                            "name": fc.name,
                            "args": dict(fc.args) if fc.args else {},
                        })
            
            inv_result = InvocationResult(
                invocation_id=per_inv.actual_invocation.invocation_id if per_inv.actual_invocation else str(idx),
                user_message=orig_inv.user_message if orig_inv else "",
                expected_response=orig_inv.expected_response if orig_inv else None,
                actual_response=actual_response,
                expected_tool_calls=[
                    {"name": tc.name, "args": tc.args, "args_match_mode": tc.args_match_mode}
                    for tc in (orig_inv.expected_tool_calls if orig_inv else [])
                ],
                actual_tool_calls=actual_tool_calls,
                passed=all(
                    mr.eval_status == EvalStatus.PASSED 
                    for mr in per_inv.eval_metric_results
                ),
            )
            
            # Add metric results for this invocation
            for mr in per_inv.eval_metric_results:
                # Extract rationale from rubric_scores if available
                rationale = None
                if mr.details and mr.details.rubric_scores:
                    rationales = [
                        rs.rationale for rs in mr.details.rubric_scores 
                        if rs.rationale
                    ]
                    if rationales:
                        rationale = "\n".join(rationales)
                
                inv_result.metric_results.append(MetricResult(
                    metric=mr.metric_name,
                    score=mr.score or 0.0,
                    threshold=mr.threshold or 0.0,
                    passed=mr.eval_status == EvalStatus.PASSED,
                    rationale=rationale,
                ))
            
            invocation_results.append(inv_result)
        
        # Extract overall metric results
        metric_results = []
        for mr in adk_result.overall_eval_metric_results:
            # Extract rationale from rubric_scores if available
            rationale = None
            if mr.details and mr.details.rubric_scores:
                rationales = [
                    rs.rationale for rs in mr.details.rubric_scores 
                    if rs.rationale
                ]
                if rationales:
                    rationale = "\n".join(rationales)
            
            metric_results.append(MetricResult(
                metric=mr.metric_name,
                score=mr.score or 0.0,
                threshold=mr.threshold or 0.0,
                passed=mr.eval_status == EvalStatus.PASSED,
                rationale=rationale,
            ))
        
        return EvalCaseResult(
            eval_case_id=eval_case.id,
            eval_case_name=eval_case.name,
            eval_set_id=eval_set_id,
            eval_set_name=eval_set_name,
            passed=adk_result.final_eval_status == EvalStatus.PASSED,
            invocation_results=invocation_results,
            metric_results=metric_results,
            session_id=adk_result.session_id,
        )
    
    async def run_eval_set(
        self,
        project: Project,
        eval_set: EvalSet,
    ) -> EvalSetResult:
        """Run all evaluation cases in an eval set using ADK LocalEvalService."""
        if not ADK_EVAL_AVAILABLE:
            raise RuntimeError(f"ADK evaluation modules not available: {ADK_IMPORT_ERROR}")
        
        started_at = time.time()
        app_name = project.name or project.id
        
        # Build the agent from the project
        root_agent = await self._build_agent_for_eval(project, eval_set.eval_config)
        
        # Create in-memory eval sets manager and populate it
        eval_sets_manager = InMemoryEvalSetsManager()
        eval_sets_manager.create_eval_set(app_name, eval_set.id)
        
        # Convert and add our eval cases
        for eval_case in eval_set.eval_cases:
            adk_eval_case = self._convert_to_adk_eval_case(eval_case, app_name)
            eval_sets_manager.add_eval_case(app_name, eval_set.id, adk_eval_case)
        
        # Create LocalEvalService
        session_service = InMemorySessionService()
        artifact_service = InMemoryArtifactService()
        
        eval_service = LocalEvalService(
            root_agent=root_agent,
            eval_sets_manager=eval_sets_manager,
            session_service=session_service,
            artifact_service=artifact_service,
        )
        
        # Create ADK eval config
        adk_eval_config = self._convert_to_adk_eval_config(eval_set.eval_config)
        eval_metrics = get_eval_metrics_from_config(adk_eval_config)
        
        # Run inference phase
        inference_request = InferenceRequest(
            app_name=app_name,
            eval_set_id=eval_set.id,
            inference_config=InferenceConfig(parallelism=1),
        )
        
        inference_results = []
        async for inference_result in eval_service.perform_inference(inference_request):
            inference_results.append(inference_result)
        
        # Run evaluation phase
        evaluate_request = EvaluateRequest(
            inference_results=inference_results,
            evaluate_config=EvaluateConfig(
                eval_metrics=eval_metrics,
                parallelism=1,
            ),
        )
        
        # Collect results
        case_results = []
        passed_count = 0
        
        async for adk_result in eval_service.evaluate(evaluate_request):
            # Find the original eval case
            orig_case = next(
                (c for c in eval_set.eval_cases if c.id == adk_result.eval_id),
                None
            )
            if orig_case:
                result = self._convert_adk_result_to_ours(
                    adk_result, orig_case, eval_set.id, eval_set.name
                )
                case_results.append(result)
                if result.passed:
                    passed_count += 1
        
        completed_at = time.time()
        
        return EvalSetResult(
            id=str(uuid.uuid4())[:8],
            eval_set_id=eval_set.id,
            eval_set_name=eval_set.name,
            started_at=started_at,
            completed_at=completed_at,
            total_cases=len(eval_set.eval_cases),
            passed_cases=passed_count,
            failed_cases=len(eval_set.eval_cases) - passed_count,
            case_results=case_results,
        )
    
    async def run_eval_case(
        self,
        project: Project,
        eval_case: EvalCase,
        eval_config: EvalConfig,
        eval_set_id: str = "",
        eval_set_name: str = "",
    ) -> EvalCaseResult:
        """Run a single evaluation case using ADK LocalEvalService."""
        if not ADK_EVAL_AVAILABLE:
            raise RuntimeError(f"ADK evaluation modules not available: {ADK_IMPORT_ERROR}")
        
        app_name = project.name or project.id
        eval_set_id = f"single_case_{eval_case.id}"
        
        # Build the agent from the project
        root_agent = await self._build_agent_for_eval(project, eval_config)
        
        # Create in-memory eval sets manager
        eval_sets_manager = InMemoryEvalSetsManager()
        eval_sets_manager.create_eval_set(app_name, eval_set_id)
        
        # Convert and add our eval case
        adk_eval_case = self._convert_to_adk_eval_case(eval_case, app_name)
        eval_sets_manager.add_eval_case(app_name, eval_set_id, adk_eval_case)
        
        # Create LocalEvalService
        session_service = InMemorySessionService()
        artifact_service = InMemoryArtifactService()
        
        eval_service = LocalEvalService(
            root_agent=root_agent,
            eval_sets_manager=eval_sets_manager,
            session_service=session_service,
            artifact_service=artifact_service,
        )
        
        # Create ADK eval config
        adk_eval_config = self._convert_to_adk_eval_config(eval_config)
        eval_metrics = get_eval_metrics_from_config(adk_eval_config)
        
        # Run inference
        inference_request = InferenceRequest(
            app_name=app_name,
            eval_set_id=eval_set_id,
            eval_case_ids=[eval_case.id],
            inference_config=InferenceConfig(parallelism=1),
        )
        
        inference_results = []
        async for inference_result in eval_service.perform_inference(inference_request):
            inference_results.append(inference_result)
        
        if not inference_results:
            raise RuntimeError("No inference results generated")
        
        # Run evaluation
        evaluate_request = EvaluateRequest(
            inference_results=inference_results,
            evaluate_config=EvaluateConfig(
                eval_metrics=eval_metrics,
                parallelism=1,
            ),
        )
        
        async for adk_result in eval_service.evaluate(evaluate_request):
            return self._convert_adk_result_to_ours(
                adk_result, eval_case, eval_set_id, eval_set_name
            )
        
        raise RuntimeError("No evaluation results generated")
    
    async def _build_agent_for_eval(
        self,
        project: Project,
        eval_config: EvalConfig,
    ) -> BaseAgent:
        """Build an ADK agent from our project for evaluation."""
        # Use the RuntimeManager to build agents
        agents = self.runtime_manager._build_agents(project)
        
        if not agents:
            raise RuntimeError("No agents found in project")
        
        # Get the root agent (first one, or specified by target_agent in eval_config)
        target_agent_id = getattr(eval_config, 'target_agent', None)
        
        if target_agent_id:
            root_agent = agents.get(target_agent_id)
            if not root_agent:
                raise RuntimeError(f"Target agent '{target_agent_id}' not found")
        else:
            # Use the first agent (typically the root agent)
            root_agent = list(agents.values())[0]
        
        return root_agent

