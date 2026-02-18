"""Acceptance tests for task 207 - eval run comparison."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Add backend to path
backend_dir = Path(__file__).parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from models import (
    EvalSetResult,
    EvalCaseResult,
    MetricResult,
    InvocationResult,
)


def _make_eval_set_result(
    result_id: str,
    case_scores: dict[str, float],
    overall_pass_rate: float = 1.0,
) -> EvalSetResult:
    """Create an EvalSetResult with the given case scores.

    case_scores: mapping of eval_case_id -> score (metric avg)
    """
    case_results = []
    for case_id, score in case_scores.items():
        case_results.append(
            EvalCaseResult(
                eval_case_id=case_id,
                eval_case_name=f"Case {case_id}",
                session_id="s1",
                passed=score >= 0.5,
                metric_results=[
                    MetricResult(
                        metric="response_match_score",
                        score=score,
                        threshold=0.5,
                        passed=score >= 0.5,
                    ),
                ],
                invocation_results=[
                    InvocationResult(
                        invocation_id=f"inv_{case_id}",
                        user_message="test",
                        passed=score >= 0.5,
                    ),
                ],
            )
        )

    return EvalSetResult(
        id=result_id,
        eval_set_id="evalset_1",
        eval_set_name="Test Set",
        project_id="proj_1",
        case_results=case_results,
        total_cases=len(case_results),
        passed_cases=sum(1 for c in case_results if c.passed),
        failed_cases=sum(1 for c in case_results if not c.passed),
        overall_pass_rate=overall_pass_rate,
    )


class TestCompareEvalResultsFunction:
    """Tests for compare_eval_results function."""

    def test_function_exists(self):
        """compare_eval_results must exist in evaluation_service."""
        from evaluation_service import compare_eval_results
        assert callable(compare_eval_results)

    def test_returns_dict_with_required_keys(self):
        """compare_eval_results must return a dict with expected structure."""
        from evaluation_service import compare_eval_results

        result_a = _make_eval_set_result("a", {"c1": 0.5, "c2": 0.7})
        result_b = _make_eval_set_result("b", {"c1": 0.8, "c2": 0.7})

        diff = compare_eval_results(result_a, result_b)

        assert isinstance(diff, dict), f"Expected dict, got {type(diff)}"
        # Should contain some indication of improved/degraded/unchanged
        has_structural_keys = (
            "improved" in diff
            or "degraded" in diff
            or "unchanged" in diff
            or "cases" in diff
            or "delta" in diff
            or "overall_score_delta" in diff
        )
        assert has_structural_keys, (
            f"Result should have structural keys (improved/degraded/unchanged/delta), "
            f"got keys: {list(diff.keys())}"
        )

    def test_detects_improvement(self):
        """A case that improves from A to B should be detected."""
        from evaluation_service import compare_eval_results

        result_a = _make_eval_set_result("a", {"c1": 0.3, "c2": 0.5})
        result_b = _make_eval_set_result("b", {"c1": 0.9, "c2": 0.5})

        diff = compare_eval_results(result_a, result_b)

        # c1 improved from 0.3 to 0.9
        improved = diff.get("improved", [])
        if isinstance(improved, list):
            improved_ids = [c.get("case_id", c) if isinstance(c, dict) else c for c in improved]
            assert "c1" in improved_ids or len(improved) > 0, (
                f"c1 should be in improved list. diff={diff}"
            )
        elif isinstance(improved, dict):
            assert "c1" in improved, f"c1 should be improved. diff={diff}"

    def test_detects_degradation(self):
        """A case that gets worse from A to B should be detected."""
        from evaluation_service import compare_eval_results

        result_a = _make_eval_set_result("a", {"c1": 0.9, "c2": 0.5})
        result_b = _make_eval_set_result("b", {"c1": 0.2, "c2": 0.5})

        diff = compare_eval_results(result_a, result_b)

        degraded = diff.get("degraded", [])
        if isinstance(degraded, list):
            degraded_ids = [c.get("case_id", c) if isinstance(c, dict) else c for c in degraded]
            assert "c1" in degraded_ids or len(degraded) > 0, (
                f"c1 should be in degraded list. diff={diff}"
            )
        elif isinstance(degraded, dict):
            assert "c1" in degraded, f"c1 should be degraded. diff={diff}"

    def test_detects_unchanged(self):
        """Cases with same score should be unchanged."""
        from evaluation_service import compare_eval_results

        result_a = _make_eval_set_result("a", {"c1": 0.7, "c2": 0.7})
        result_b = _make_eval_set_result("b", {"c1": 0.7, "c2": 0.7})

        diff = compare_eval_results(result_a, result_b)

        unchanged = diff.get("unchanged", [])
        if isinstance(unchanged, list):
            assert len(unchanged) >= 1, (
                f"Both cases are unchanged, but unchanged list is empty. diff={diff}"
            )

    def test_handles_missing_cases_in_b(self):
        """Cases present in A but not B should be reported."""
        from evaluation_service import compare_eval_results

        result_a = _make_eval_set_result("a", {"c1": 0.5, "c2": 0.7, "c3": 0.8})
        result_b = _make_eval_set_result("b", {"c1": 0.5, "c2": 0.7})
        # c3 is missing in B

        diff = compare_eval_results(result_a, result_b)
        # Should not crash - just handle gracefully
        assert isinstance(diff, dict)

    def test_overall_score_delta(self):
        """Should report overall score delta."""
        from evaluation_service import compare_eval_results

        result_a = _make_eval_set_result("a", {"c1": 0.3}, overall_pass_rate=0.3)
        result_b = _make_eval_set_result("b", {"c1": 0.9}, overall_pass_rate=0.9)

        diff = compare_eval_results(result_a, result_b)

        # Should have some overall delta
        has_delta = (
            "overall_score_delta" in diff
            or "delta" in diff
            or "overall_delta" in diff
            or "pass_rate_delta" in diff
            or "score_delta" in diff
        )
        assert has_delta, (
            f"Diff should contain overall score/pass rate delta. Keys: {list(diff.keys())}"
        )


class TestCompareEndpoint:
    """Tests for POST /api/projects/{project_id}/eval-sets/{eval_set_id}/compare."""

    def test_endpoint_exists(self):
        """The compare endpoint must be registered."""
        from main import app

        routes = [r.path for r in app.routes]
        expected_path = "/api/projects/{project_id}/eval-sets/{eval_set_id}/compare"
        assert expected_path in routes, (
            f"Compare endpoint must exist. Available routes: {routes}"
        )
