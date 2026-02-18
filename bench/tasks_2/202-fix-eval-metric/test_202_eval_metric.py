"""Acceptance tests for task 202 - evaluation metric aggregation fix."""
from __future__ import annotations

import sys
import time
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Add backend to path
backend_dir = Path(__file__).parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from models import (
    Project,
    AppConfig,
    LlmAgentConfig,
    ModelConfig,
    EvalSet,
    EvalCase,
    EvalInvocation,
    EvalSetResult,
    EvalCaseResult,
    InvocationResult,
    MetricResult,
    EvalConfig,
    EvalMetricConfig,
    EvalMetricType,
    EvalCriterion,
)


def _make_project() -> Project:
    return Project(
        id="eval_proj",
        name="Eval Project",
        app=AppConfig(
            id="app_eval",
            name="Eval App",
            root_agent_id="agent_1",
            session_service_uri="memory://",
            memory_service_uri="memory://",
            artifact_service_uri="memory://",
        ),
        agents=[
            LlmAgentConfig(
                id="agent_1",
                name="eval_agent",
                instruction="Test agent",
                model=ModelConfig(provider="gemini", model_name="gemini-2.0-flash"),
            ),
        ],
    )


def _make_eval_set(num_cases: int = 2, invocations_per_case: int = 2) -> EvalSet:
    """Create an eval set with multiple cases, each with multiple invocations."""
    cases = []
    for i in range(num_cases):
        invocations = []
        for j in range(invocations_per_case):
            invocations.append(
                EvalInvocation(
                    id=f"inv_{i}_{j}",
                    user_message=f"Test message {i}-{j}",
                    expected_response=f"Expected response {i}-{j}",
                )
            )
        cases.append(
            EvalCase(
                id=f"case_{i}",
                name=f"Test Case {i}",
                invocations=invocations,
            )
        )
    return EvalSet(
        id="evalset_1",
        name="Test Eval Set",
        eval_cases=cases,
        eval_config=EvalConfig(
            metrics=[
                EvalMetricConfig(
                    metric=EvalMetricType.RESPONSE_MATCH_SCORE,
                    enabled=True,
                    criterion=EvalCriterion(threshold=0.5),
                ),
            ],
        ),
    )


class TestEvalSetResultHasOverallScore:
    """Tests that EvalSetResult has and populates overall_score."""

    def test_overall_score_field_exists(self):
        """EvalSetResult must have an overall_score field."""
        result = EvalSetResult(
            id="test",
            eval_set_id="es1",
            eval_set_name="Test",
            project_id="p1",
        )
        assert hasattr(result, "overall_score"), (
            "EvalSetResult must have an overall_score field"
        )

    def test_overall_score_default_is_zero_or_none(self):
        """overall_score default should be 0.0 or None."""
        result = EvalSetResult(
            id="test",
            eval_set_id="es1",
            eval_set_name="Test",
            project_id="p1",
        )
        assert result.overall_score is None or result.overall_score == 0.0

    @pytest.mark.asyncio
    async def test_run_eval_set_populates_overall_score(self):
        """run_eval_set must compute and populate overall_score."""
        from evaluation_service import EvaluationService

        project = _make_project()
        eval_set = _make_eval_set(num_cases=3, invocations_per_case=2)

        # Mock the runtime_manager so no actual agent execution happens
        mock_runtime = MagicMock()

        service = EvaluationService(mock_runtime)

        # We mock run_eval_case to return controlled results with known scores
        case_results = []
        # Case 0: 2 invocations, scores 0.8 and 0.6 -> avg 0.7
        case_results.append(
            EvalCaseResult(
                eval_case_id="case_0",
                eval_case_name="Test Case 0",
                session_id="s0",
                passed=True,
                invocation_results=[
                    InvocationResult(invocation_id="inv_0_0", user_message="m", passed=True),
                    InvocationResult(invocation_id="inv_0_1", user_message="m", passed=True),
                ],
                metric_results=[
                    MetricResult(metric="response_match_score", score=0.7, threshold=0.5, passed=True),
                ],
            )
        )
        # Case 1: 2 invocations, scores 0.4 and 0.6 -> avg 0.5
        case_results.append(
            EvalCaseResult(
                eval_case_id="case_1",
                eval_case_name="Test Case 1",
                session_id="s1",
                passed=True,
                invocation_results=[
                    InvocationResult(invocation_id="inv_1_0", user_message="m", passed=True),
                    InvocationResult(invocation_id="inv_1_1", user_message="m", passed=True),
                ],
                metric_results=[
                    MetricResult(metric="response_match_score", score=0.5, threshold=0.5, passed=True),
                ],
            )
        )
        # Case 2: 2 invocations, scores 0.9 and 0.9 -> avg 0.9
        case_results.append(
            EvalCaseResult(
                eval_case_id="case_2",
                eval_case_name="Test Case 2",
                session_id="s2",
                passed=True,
                invocation_results=[
                    InvocationResult(invocation_id="inv_2_0", user_message="m", passed=True),
                    InvocationResult(invocation_id="inv_2_1", user_message="m", passed=True),
                ],
                metric_results=[
                    MetricResult(metric="response_match_score", score=0.9, threshold=0.5, passed=True),
                ],
            )
        )

        # Patch run_eval_case to return our controlled results sequentially
        call_count = 0

        async def mock_run_eval_case(**kwargs):
            nonlocal call_count
            result = case_results[call_count]
            call_count += 1
            return result

        service.run_eval_case = mock_run_eval_case

        result = await service.run_eval_set(project, eval_set)

        assert hasattr(result, "overall_score"), "Result must have overall_score"
        assert result.overall_score is not None, "overall_score must be populated"
        assert isinstance(result.overall_score, (int, float)), (
            f"overall_score must be numeric, got {type(result.overall_score)}"
        )
        # The overall_score should be some kind of average of the case scores
        # With weighted avg by invocations: (0.7*2 + 0.5*2 + 0.9*2) / 6 = 0.7
        # With simple avg: (0.7 + 0.5 + 0.9) / 3 = 0.7
        assert 0.0 < result.overall_score <= 1.0, (
            f"overall_score should be between 0 and 1, got {result.overall_score}"
        )

    @pytest.mark.asyncio
    async def test_overall_score_reflects_case_scores(self):
        """overall_score should reflect the actual case metric scores."""
        from evaluation_service import EvaluationService

        project = _make_project()
        eval_set = _make_eval_set(num_cases=2, invocations_per_case=1)

        mock_runtime = MagicMock()
        service = EvaluationService(mock_runtime)

        # All perfect scores
        case_results = [
            EvalCaseResult(
                eval_case_id="case_0",
                eval_case_name="Case 0",
                session_id="s0",
                passed=True,
                invocation_results=[
                    InvocationResult(invocation_id="inv_0_0", user_message="m", passed=True),
                ],
                metric_results=[
                    MetricResult(metric="response_match_score", score=1.0, threshold=0.5, passed=True),
                ],
            ),
            EvalCaseResult(
                eval_case_id="case_1",
                eval_case_name="Case 1",
                session_id="s1",
                passed=True,
                invocation_results=[
                    InvocationResult(invocation_id="inv_1_0", user_message="m", passed=True),
                ],
                metric_results=[
                    MetricResult(metric="response_match_score", score=1.0, threshold=0.5, passed=True),
                ],
            ),
        ]

        call_count = 0

        async def mock_run_eval_case(**kwargs):
            nonlocal call_count
            result = case_results[call_count]
            call_count += 1
            return result

        service.run_eval_case = mock_run_eval_case

        result = await service.run_eval_set(project, eval_set)
        assert result.overall_score == 1.0 or abs(result.overall_score - 1.0) < 0.01, (
            f"overall_score should be ~1.0 for perfect scores, got {result.overall_score}"
        )
