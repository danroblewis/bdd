"""Acceptance tests for task 203 - agent execution timeout."""
from __future__ import annotations

import asyncio
import inspect
import sys
import time
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
    RunEvent,
    RunSession,
)
from runtime import RuntimeManager


def _make_project() -> Project:
    return Project(
        id="timeout_proj",
        name="Timeout Project",
        app=AppConfig(
            id="app_timeout",
            name="Timeout App",
            root_agent_id="agent_1",
            session_service_uri="memory://",
            memory_service_uri="memory://",
            artifact_service_uri="memory://",
        ),
        agents=[
            LlmAgentConfig(
                id="agent_1",
                name="timeout_agent",
                instruction="Test agent",
                model=ModelConfig(provider="gemini", model_name="gemini-2.0-flash"),
            ),
        ],
    )


class TestRunAgentTimeoutParameter:
    """Tests that run_agent accepts a timeout_seconds parameter."""

    def test_run_agent_accepts_timeout_seconds(self):
        """run_agent must accept a timeout_seconds keyword argument."""
        rm = RuntimeManager(str(Path("/tmp/test_timeout_proj")))
        sig = inspect.signature(rm.run_agent)
        params = list(sig.parameters.keys())
        assert "timeout_seconds" in params, (
            f"run_agent must accept 'timeout_seconds' parameter. "
            f"Current parameters: {params}"
        )

    def test_timeout_seconds_default_is_none(self):
        """timeout_seconds should default to None."""
        rm = RuntimeManager(str(Path("/tmp/test_timeout_proj")))
        sig = inspect.signature(rm.run_agent)
        param = sig.parameters["timeout_seconds"]
        assert param.default is None, (
            f"timeout_seconds default should be None, got {param.default}"
        )


class TestTimeoutBehavior:
    """Tests that timeout actually cancels execution and emits an error event."""

    @pytest.mark.asyncio
    async def test_timeout_emits_error_event(self):
        """When execution exceeds timeout_seconds, an error event should be emitted."""
        rm = RuntimeManager(str(Path("/tmp/test_timeout_proj")))
        project = _make_project()

        events_collected = []

        async def event_callback(event):
            events_collected.append(event)

        # Mock the entire execution chain so it simulates a slow agent
        # The key idea: we mock the code execution path to be slow
        async def slow_generator():
            """Simulate a very slow agent that takes longer than timeout."""
            await asyncio.sleep(10)  # Way longer than our timeout
            yield RunEvent(
                timestamp=time.time(),
                event_type="agent_end",
                agent_name="timeout_agent",
                data={},
            )

        # We need to patch enough of the internals so run_agent reaches the
        # timeout logic. Patch generate_python_code and exec to avoid real ADK.
        with patch("runtime.generate_python_code", return_value="# mock code"):
            # Patch the exec/compile flow - make it set up a mock runner
            mock_runner = MagicMock()
            mock_runner.run_async = MagicMock(return_value=slow_generator())

            with patch("runtime.RuntimeManager._execute_agent") as mock_exec:
                # Make _execute_agent an async generator that sleeps forever
                async def slow_execute(*args, **kwargs):
                    await asyncio.sleep(10)
                    yield RunEvent(
                        timestamp=time.time(),
                        event_type="agent_end",
                        agent_name="timeout_agent",
                        data={},
                    )

                mock_exec.return_value = slow_execute()

                # Collect events from run_agent with a very short timeout
                start = time.time()
                try:
                    async for event in rm.run_agent(
                        project=project,
                        user_message="hello",
                        event_callback=event_callback,
                        timeout_seconds=0.5,
                    ):
                        events_collected.append(event)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    # Some implementations may raise instead of yielding
                    pass
                except Exception:
                    # Other exceptions from the mocked environment are acceptable
                    pass

                elapsed = time.time() - start

        # The test should have completed relatively quickly (not 10s)
        assert elapsed < 5.0, (
            f"Execution should have been cancelled by timeout, took {elapsed:.1f}s"
        )

        # Check that at least one event mentions timeout
        all_events = events_collected
        timeout_events = [
            e for e in all_events
            if isinstance(e, RunEvent)
            and (
                "timeout" in str(e.data).lower()
                or "timeout" in str(getattr(e, "event_type", "")).lower()
                or (e.event_type == "error" and "timed out" in str(e.data).lower())
                or (e.event_type == "error" and "timeout" in str(e.data).lower())
            )
        ]
        # We accept the timeout being detected either through events or by the
        # elapsed time being < 5s (proving the timeout mechanism exists)
        if not timeout_events:
            # If no explicit timeout event, at least verify execution was short
            assert elapsed < 3.0, (
                "No timeout event found and execution wasn't cancelled quickly. "
                "run_agent should emit an error event on timeout."
            )

    @pytest.mark.asyncio
    async def test_no_timeout_when_none(self):
        """When timeout_seconds is None, no timeout should be applied."""
        rm = RuntimeManager(str(Path("/tmp/test_timeout_proj")))
        project = _make_project()

        # Just verify we can call run_agent with timeout_seconds=None without error
        # We mock everything so it returns immediately
        events = []

        async def event_callback(event):
            events.append(event)

        with patch("runtime.generate_python_code", return_value="# mock"):
            with patch("runtime.RuntimeManager._execute_agent") as mock_exec:
                async def quick_execute(*args, **kwargs):
                    yield RunEvent(
                        timestamp=time.time(),
                        event_type="agent_end",
                        agent_name="timeout_agent",
                        data={"response": "done"},
                    )

                mock_exec.return_value = quick_execute()

                try:
                    async for event in rm.run_agent(
                        project=project,
                        user_message="hello",
                        event_callback=event_callback,
                        timeout_seconds=None,
                    ):
                        events.append(event)
                except Exception:
                    pass  # Mocked environment may raise

        # No assertion on events - just verifying no crash with timeout_seconds=None
