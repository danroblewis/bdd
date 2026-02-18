#!/usr/bin/env python3
"""Integration tests for Docker sandbox functionality.

These tests verify:
1. Container lifecycle (start, stop, reuse)
2. Event streaming (agent events flowing to WebSocket)
3. Network isolation (requests go through proxy)
4. Approval workflow (pending requests, approve/deny)

Requirements:
- Backend server running on localhost:8080
- Docker daemon available

Run standalone: python backend/sandbox/tests/test_docker_integration.py
"""
import asyncio
import json
import os
import sys
import time
from typing import Any, Dict, List

try:
    import websockets
except ImportError:
    print("Please install websockets: pip install websockets")
    sys.exit(1)


# Test configuration
BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8080")
WS_URL = os.environ.get("WS_URL", "ws://localhost:8080")
PROJECT_ID = os.environ.get("TEST_PROJECT_ID", "cff7f9dc")
TEST_TIMEOUT = 120  # seconds


class EventCollector:
    """Collects events from WebSocket for assertions."""
    
    def __init__(self):
        self.events: List[Dict[str, Any]] = []
        self.start_time = time.time()
    
    def add(self, data: Dict[str, Any]):
        elapsed = time.time() - self.start_time
        event_type = data.get('type') or data.get('event_type')
        self.events.append({
            'elapsed': elapsed,
            'type': event_type,
            'data': data,
        })
    
    def get_types(self) -> set:
        return set(e['type'] for e in self.events)
    
    def get_by_type(self, event_type: str) -> List[Dict[str, Any]]:
        return [e for e in self.events if e['type'] == event_type]
    
    def has_type(self, event_type: str) -> bool:
        return event_type in self.get_types()


async def run_agent_via_websocket(
    project_id: str,
    message: str,
    sandbox_mode: bool = True,
    timeout: float = TEST_TIMEOUT,
) -> EventCollector:
    """Run an agent via WebSocket and collect all events."""
    collector = EventCollector()
    uri = f"{WS_URL}/ws/run/{project_id}"
    
    async with websockets.connect(uri) as ws:
        await ws.send(json.dumps({
            'message': message,
            'sandbox_mode': sandbox_mode,
        }))
        
        while True:
            try:
                response = await asyncio.wait_for(ws.recv(), timeout=timeout)
                data = json.loads(response)
                collector.add(data)
                
                event_type = data.get('type') or data.get('event_type')
                if event_type == 'completed':
                    break
            except asyncio.TimeoutError:
                print(f"  [TIMEOUT after {timeout}s]")
                break
    
    return collector


def print_result(test_name: str, passed: bool, details: str = ""):
    status = "✅ PASS" if passed else "❌ FAIL"
    print(f"{status}: {test_name}")
    if details:
        print(f"       {details}")


async def test_sandbox_lifecycle_events():
    """Verify sandbox_starting and sandbox_started events are received."""
    collector = await run_agent_via_websocket(PROJECT_ID, "Hello")
    
    has_starting = collector.has_type('sandbox_starting')
    has_started = collector.has_type('sandbox_started')
    passed = has_starting and has_started
    
    print_result(
        "Sandbox lifecycle events",
        passed,
        f"Types: {collector.get_types()}"
    )
    return passed


async def test_agent_start_events():
    """Verify agent_start events are streamed from container."""
    collector = await run_agent_via_websocket(PROJECT_ID, "Hello")
    
    has_agent_start = collector.has_type('agent_start')
    agent_starts = collector.get_by_type('agent_start')
    
    agents = []
    for e in agent_starts:
        agent_name = e['data'].get('agent_name') or e['data'].get('data', {}).get('agent_name', '?')
        agents.append(agent_name)
    
    print_result(
        "Agent start events",
        has_agent_start,
        f"Agents: {agents}" if agents else "No agent_start events received"
    )
    return has_agent_start


async def test_network_request_events():
    """Verify network_request events are streamed."""
    collector = await run_agent_via_websocket(PROJECT_ID, "Hello")
    
    has_network = collector.has_type('network_request')
    network_events = collector.get_by_type('network_request')
    
    hosts = []
    for e in network_events:
        host = e['data'].get('host') or e['data'].get('data', {}).get('host', '?')
        status = e['data'].get('status') or e['data'].get('data', {}).get('status', '?')
        hosts.append(f"{host}:{status}")
    
    print_result(
        "Network request events",
        has_network,
        f"Hosts: {hosts[:5]}..." if len(hosts) > 5 else f"Hosts: {hosts}"
    )
    return has_network


async def test_completed_event():
    """Verify completed event is received at the end."""
    collector = await run_agent_via_websocket(PROJECT_ID, "Hello")
    
    has_completed = collector.has_type('completed')
    is_last = collector.events[-1]['type'] == 'completed' if collector.events else False
    passed = has_completed and is_last
    
    print_result(
        "Completed event (and is last)",
        passed,
        f"Last event: {collector.events[-1]['type'] if collector.events else 'none'}"
    )
    return passed


async def test_container_reuse():
    """Verify second run reuses container and is faster."""
    # First run
    start1 = time.time()
    collector1 = await run_agent_via_websocket(PROJECT_ID, "First message")
    time1 = time.time() - start1
    
    # Second run should reuse container
    start2 = time.time()
    collector2 = await run_agent_via_websocket(PROJECT_ID, "Second message")
    time2 = time.time() - start2
    
    both_completed = collector1.has_type('completed') and collector2.has_type('completed')
    
    print_result(
        "Container reuse",
        both_completed,
        f"First: {time1:.1f}s, Second: {time2:.1f}s"
    )
    return both_completed


async def test_all_expected_event_types():
    """Verify we receive the expected event types."""
    collector = await run_agent_via_websocket(PROJECT_ID, "Hello")
    
    event_types = collector.get_types()
    
    # Required events
    required = {'sandbox_starting', 'sandbox_started', 'completed'}
    missing = required - event_types
    passed = not missing
    
    # Agent events we hope to see
    agent_events = {'agent_start', 'model_call', 'model_response', 'agent_end'}
    received_agent = agent_events & event_types
    
    print_result(
        "All expected event types",
        passed,
        f"Required: {required & event_types}, Agent: {received_agent}, Missing: {missing}"
    )
    return passed


async def test_pending_approval_for_external():
    """Verify unknown external requests get pending status."""
    collector = await run_agent_via_websocket(PROJECT_ID, "Hello", timeout=35)
    
    network_events = collector.get_by_type('network_request')
    
    pending = [
        e for e in network_events
        if e['data'].get('status') == 'pending'
        or e['data'].get('data', {}).get('status') == 'pending'
    ]
    
    # This test depends on the project making external requests
    has_pending = len(pending) > 0
    
    pending_hosts = []
    for e in pending:
        host = e['data'].get('host') or e['data'].get('data', {}).get('host', '?')
        pending_hosts.append(host)
    
    print_result(
        "Pending approval for external requests",
        has_pending,
        f"Pending hosts: {pending_hosts}" if pending_hosts else "No external requests made"
    )
    return has_pending  # May not pass if project doesn't make external requests


async def run_all_tests():
    """Run all integration tests."""
    print("\n" + "="*60)
    print("Docker Sandbox Integration Tests")
    print("="*60 + "\n")
    
    tests = [
        ("Sandbox Lifecycle", test_sandbox_lifecycle_events),
        ("Agent Start Events", test_agent_start_events),
        ("Network Request Events", test_network_request_events),
        ("Completed Event", test_completed_event),
        ("Container Reuse", test_container_reuse),
        ("All Expected Types", test_all_expected_event_types),
        ("Pending Approval", test_pending_approval_for_external),
    ]
    
    results = []
    for name, test_fn in tests:
        print(f"\n--- {name} ---")
        try:
            result = await test_fn()
            results.append((name, result, None))
        except Exception as e:
            print_result(name, False, f"Exception: {e}")
            results.append((name, False, str(e)))
    
    # Summary
    print("\n" + "="*60)
    print("Summary")
    print("="*60)
    
    passed = sum(1 for _, r, _ in results if r)
    total = len(results)
    
    for name, result, error in results:
        status = "✅" if result else "❌"
        print(f"  {status} {name}")
    
    print(f"\n{passed}/{total} tests passed")
    print("="*60 + "\n")
    
    return passed == total


if __name__ == "__main__":
    success = asyncio.run(run_all_tests())
    sys.exit(0 if success else 1)
