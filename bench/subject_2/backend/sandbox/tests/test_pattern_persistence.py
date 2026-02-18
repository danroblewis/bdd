#!/usr/bin/env python3
"""
Integration test for allowlist pattern persistence.

This test verifies that once a pattern is approved, subsequent requests
to the same domain don't require re-approval.

Test flow:
1. Start sandbox with an agent that has before_agent and after_agent callbacks
   both making requests to the same external URL
2. Wait for approval_required for the first request (before_agent)
3. Approve with a pattern
4. Verify the second request (after_agent) is auto-allowed without prompting

Run: python backend/sandbox/tests/test_pattern_persistence.py
"""
import asyncio
import json
import subprocess
import sys
import time
from typing import Optional

try:
    import websockets
    import aiohttp
except ImportError:
    print("Install: pip install websockets aiohttp")
    sys.exit(1)


# Configuration
BACKEND_URL = "http://localhost:8080"
WS_URL = "ws://localhost:8080"
PROJECT_ID = "cff7f9dc"  # Update to match your test project
APP_ID = "app_cff7f9dc"
TEST_DOMAIN = "bodygen.re"


async def cleanup_containers():
    """Remove existing sandbox containers to start fresh."""
    subprocess.run(
        f"docker rm -f sandbox-agent-{APP_ID} sandbox-gateway-{APP_ID} 2>/dev/null",
        shell=True, capture_output=True
    )
    subprocess.run(
        f"docker network rm adk-sandbox-net-{APP_ID}-internal 2>/dev/null",
        shell=True, capture_output=True
    )
    print("🧹 Cleaned up existing containers")


async def get_gateway_port() -> Optional[str]:
    """Get the gateway control API port."""
    result = subprocess.run(
        f"docker port sandbox-gateway-{APP_ID} 8081 2>/dev/null | cut -d: -f2",
        shell=True, capture_output=True, text=True
    )
    port = result.stdout.strip()
    return port if port else None


async def check_gateway_pending():
    """Check the gateway's pending requests directly."""
    port = await get_gateway_port()
    if not port:
        return {"error": "Gateway not found", "count": 0, "pending": []}
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://localhost:{port}/pending") as resp:
                return await resp.json()
    except Exception as e:
        return {"error": str(e), "count": 0, "pending": []}


async def check_gateway_allowlist():
    """Check the gateway's current allowlist."""
    port = await get_gateway_port()
    if not port:
        return {"error": "Gateway not found"}
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://localhost:{port}/allowlist") as resp:
                return await resp.json()
    except Exception as e:
        return {"error": str(e)}


async def approve_request(request_id: str, pattern: str, persist: bool = False):
    """Call the approval API."""
    url = f"{BACKEND_URL}/api/sandbox/{APP_ID}/approval"
    if persist:
        url += f"?project_id={PROJECT_ID}"
    
    async with aiohttp.ClientSession() as session:
        async with session.post(
            url,
            json={
                'request_id': request_id,
                'action': 'allow_pattern',
                'pattern': pattern,
                'pattern_type': 'exact',
                'persist': persist,
            },
        ) as resp:
            body = await resp.text()
            return resp.status, body


async def test_pattern_persistence():
    """
    Test that approved patterns are remembered for subsequent requests.
    
    This simulates:
    1. before_agent_callback makes request to bodygen.re
    2. User approves bodygen.re pattern
    3. after_agent_callback makes request to bodygen.re
    4. Second request should be auto-allowed (no approval needed)
    """
    print("\n" + "="*70)
    print("Testing Pattern Persistence (same domain, no re-approval)")
    print("="*70 + "\n")
    
    # Step 1: Clean up
    await cleanup_containers()
    await asyncio.sleep(1)
    
    # Step 2: Connect to WebSocket and start run
    print("1️⃣ Connecting to WebSocket...")
    uri = f"{WS_URL}/ws/run/{PROJECT_ID}"
    
    async with websockets.connect(uri) as ws:
        print("   Connected!")
        
        print("\n2️⃣ Sending message to trigger agent...")
        await ws.send(json.dumps({
            'message': 'Hello, make two requests to bodygen.re',
            'sandbox_mode': True
        }))
        
        # Track events
        first_approval_done = False
        first_request_id = None
        approved_request_ids = set()  # Track IDs we've approved
        second_approval_required = False
        all_events = []
        network_events = []
        
        print("\n3️⃣ Processing events...")
        start = time.time()
        timeout = 120  # 2 minutes max
        
        while time.time() - start < timeout:
            try:
                response = await asyncio.wait_for(ws.recv(), timeout=3)
                data = json.loads(response)
                all_events.append(data)
                
                event_type = data.get('event_type') or data.get('type')
                
                # Handle network events
                if event_type in ('network_request', 'approval_required'):
                    # Extract from nested data if needed
                    net_data = data.get('data', data)
                    host = net_data.get('host', '?')
                    status = net_data.get('status', '?')
                    request_id = net_data.get('id', '?')
                    
                    # Filter to our test domain
                    if TEST_DOMAIN in host or TEST_DOMAIN in str(net_data.get('url', '')):
                        network_events.append({
                            'id': request_id,
                            'host': host,
                            'status': status,
                            'event_type': event_type,
                        })
                        
                        print(f"   📡 Network [{TEST_DOMAIN}]: status={status}, id={request_id[:8] if len(request_id) > 8 else request_id}")
                        
                        if status == 'pending' and request_id not in approved_request_ids:
                            if not first_approval_done:
                                # First pending request - approve it
                                first_request_id = request_id
                                print(f"\n4️⃣ Approving first request: {request_id}")
                                
                                # Check allowlist before approval
                                allowlist = await check_gateway_allowlist()
                                print(f"   Allowlist before: {allowlist}")
                                
                                status_code, body = await approve_request(
                                    request_id, 
                                    pattern=TEST_DOMAIN,
                                    persist=True
                                )
                                print(f"   Approval response: {status_code} - {body}")
                                
                                if status_code == 200:
                                    first_approval_done = True
                                    approved_request_ids.add(request_id)
                                    print("   ✅ First request approved!")
                                    
                                    # Check allowlist after approval
                                    await asyncio.sleep(0.5)
                                    allowlist = await check_gateway_allowlist()
                                    print(f"   Allowlist after: {allowlist}")
                                else:
                                    print(f"   ❌ Approval failed!")
                                    return False
                            else:
                                # A NEW pending request after we already approved one
                                # This means the pattern was NOT remembered!
                                print(f"\n   ❌ SECOND APPROVAL REQUIRED: {request_id}")
                                print(f"   Already approved: {approved_request_ids}")
                                print(f"   This means the pattern was NOT added to the allowlist!")
                                second_approval_required = True
                
                elif event_type == 'completed':
                    print(f"\n   ✅ Run completed")
                    break
                    
                elif event_type == 'error':
                    error = data.get('error') or data.get('data', {}).get('error', '?')
                    print(f"   ❌ Error: {error}")
                    # Continue processing, might still get useful info
                    
                elif event_type in ('agent_start', 'agent_end', 'callback_start', 'callback_end'):
                    name = data.get('agent_name') or data.get('callback_name') or data.get('data', {}).get('agent_name', '?')
                    print(f"   🔄 {event_type}: {name}")
                    
                else:
                    # Log other events
                    print(f"   📨 {event_type}")
                    
            except asyncio.TimeoutError:
                # Check gateway pending directly
                pending = await check_gateway_pending()
                if pending.get('count', 0) > 0:
                    print(f"   🔍 Gateway has {pending['count']} pending: {pending.get('pending', [])}")
                    
                    # If first approval not done, handle it
                    if not first_approval_done and pending.get('pending'):
                        first_request_id = pending['pending'][0]
                        if first_request_id not in approved_request_ids:
                            print(f"\n4️⃣ Approving first request from gateway: {first_request_id}")
                            status_code, body = await approve_request(
                                first_request_id, 
                                pattern=TEST_DOMAIN,
                                persist=True
                            )
                            print(f"   Approval response: {status_code} - {body}")
                            if status_code == 200:
                                first_approval_done = True
                                approved_request_ids.add(first_request_id)
                            else:
                                print(f"   ❌ Approval failed!")
                
                elapsed = int(time.time() - start)
                if elapsed % 10 == 0:
                    print(f"   ⏳ Waiting... ({elapsed}s)")
        
        # Summary
        print("\n" + "="*70)
        print("TEST SUMMARY")
        print("="*70)
        print(f"\nTotal events received: {len(all_events)}")
        print(f"Network events for {TEST_DOMAIN}: {len(network_events)}")
        for e in network_events:
            print(f"  - {e['status']}: {e['host']} ({e['id'][:8]}...)")
        
        print(f"\nFirst approval done: {first_approval_done}")
        print(f"Second approval required: {second_approval_required}")
        
        if first_approval_done and not second_approval_required:
            print("\n✅ TEST PASSED: Pattern was remembered!")
            return True
        elif second_approval_required:
            print("\n❌ TEST FAILED: Pattern was NOT remembered - second approval was required!")
            return False
        elif not first_approval_done:
            print("\n❌ TEST FAILED: No approval request was received")
            print("   Make sure your project has callbacks that make requests to bodygen.re")
            return False
        else:
            print("\n⚠️ TEST INCONCLUSIVE")
            return False


async def main():
    try:
        success = await test_pattern_persistence()
        return success
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)

