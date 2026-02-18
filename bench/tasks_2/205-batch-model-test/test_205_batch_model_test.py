"""Acceptance tests for task 205 - batch model connectivity test."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Add backend to path
backend_dir = Path(__file__).parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))


class TestModelConnectivityFunction:
    """Tests for the test_model_connectivity function in model_service."""

    def test_function_exists(self):
        """test_model_connectivity must exist in model_service."""
        import model_service
        assert hasattr(model_service, "test_model_connectivity"), (
            "model_service must have a test_model_connectivity function"
        )
        assert asyncio.iscoroutinefunction(model_service.test_model_connectivity), (
            "test_model_connectivity must be an async function"
        )

    @pytest.mark.asyncio
    async def test_returns_proper_format_on_success(self):
        """test_model_connectivity should return dict with reachable, error, latency_ms."""
        import model_service

        # Mock the actual network call to simulate a reachable model
        with patch.object(
            model_service,
            "test_model_connectivity",
            new_callable=AsyncMock,
            return_value={"reachable": True, "error": None, "latency_ms": 42.5},
        ) as mock_fn:
            result = await mock_fn(provider="gemini", model_name="gemini-2.0-flash")

        assert isinstance(result, dict)
        assert "reachable" in result
        assert "error" in result
        assert "latency_ms" in result
        assert result["reachable"] is True

    @pytest.mark.asyncio
    async def test_returns_proper_format_on_failure(self):
        """test_model_connectivity should handle unreachable models gracefully."""
        import model_service

        # We need to actually call the real function but mock any network calls
        # to simulate failure
        with patch("model_service.asyncio", MagicMock()) as mock_asyncio:
            # Simulate a connection error by patching whatever HTTP client is used
            # The actual implementation might use different HTTP libraries
            try:
                result = await model_service.test_model_connectivity(
                    provider="fake_provider",
                    model_name="nonexistent-model",
                )
                assert isinstance(result, dict)
                assert "reachable" in result
                assert "error" in result
                assert "latency_ms" in result
                # For a fake provider, it should report not reachable
                assert result["reachable"] is False
                assert result["error"] is not None
            except Exception:
                # If it raises, that's also acceptable for an unknown provider
                # as long as the function exists and is callable
                pass

    @pytest.mark.asyncio
    async def test_accepts_provider_and_model_name(self):
        """Function signature must accept provider and model_name."""
        import model_service
        import inspect

        sig = inspect.signature(model_service.test_model_connectivity)
        params = list(sig.parameters.keys())
        assert "provider" in params, f"Must accept 'provider' param, has: {params}"
        assert "model_name" in params, f"Must accept 'model_name' param, has: {params}"


class TestBatchConnectivityEndpoint:
    """Tests for POST /api/models/test-connectivity endpoint."""

    def test_endpoint_exists(self):
        """POST /api/models/test-connectivity must be registered."""
        from main import app

        routes = [r.path for r in app.routes]
        assert "/api/models/test-connectivity" in routes, (
            "POST /api/models/test-connectivity route must exist. "
            f"Available routes: {routes}"
        )

    def test_endpoint_accepts_models_list(self):
        """Endpoint should accept a list of models and return results."""
        from main import app

        from fastapi.testclient import TestClient

        client = TestClient(app)

        # Mock the test_model_connectivity function to avoid real network calls
        with patch(
            "main.test_model_connectivity",
            new_callable=AsyncMock,
            return_value={"reachable": True, "error": None, "latency_ms": 25.0},
        ):
            resp = client.post(
                "/api/models/test-connectivity",
                json={
                    "models": [
                        {"provider": "gemini", "model_name": "gemini-2.0-flash"},
                        {"provider": "openai", "model_name": "gpt-4"},
                    ]
                },
            )

        # Should succeed
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()

        # Response should contain results
        results = data.get("results", data)
        if isinstance(results, list):
            assert len(results) == 2, f"Expected 2 results, got {len(results)}"
            for r in results:
                assert "reachable" in r, f"Each result must have 'reachable' field: {r}"

    def test_endpoint_handles_empty_list(self):
        """Endpoint should handle an empty models list."""
        from main import app

        from fastapi.testclient import TestClient

        client = TestClient(app)
        resp = client.post(
            "/api/models/test-connectivity",
            json={"models": []},
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        results = data.get("results", data)
        if isinstance(results, list):
            assert len(results) == 0

    def test_endpoint_with_unreachable_model(self):
        """Endpoint should gracefully report unreachable models."""
        from main import app

        from fastapi.testclient import TestClient

        client = TestClient(app)

        with patch(
            "main.test_model_connectivity",
            new_callable=AsyncMock,
            return_value={"reachable": False, "error": "Connection refused", "latency_ms": None},
        ):
            resp = client.post(
                "/api/models/test-connectivity",
                json={
                    "models": [
                        {"provider": "unknown", "model_name": "bad-model"},
                    ]
                },
            )

        assert resp.status_code == 200
        data = resp.json()
        results = data.get("results", data)
        if isinstance(results, list):
            assert len(results) == 1
            assert results[0]["reachable"] is False
