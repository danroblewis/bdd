#!/usr/bin/env python3
"""
Integration test for the network approval flow.

This test verifies the full approval workflow:
1. Start sandbox and trigger agent
2. Wait for approval_required event
3. Call approval API
4. Verify request is approved

Run: python backend/sandbox/tests/test_approval_flow.py
"""
import asyncio
import json
import sys
import time

try:
    import websockets
    import aiohttp
except ImportError:
    print("Install: pip install websockets aiohttp")
    sys.exit(1)


# Configuration
BACKEND_URL = "http://localhost:8080"
WS_URL = "ws://localhost:8080"
PROJECT_ID = "cff7f9dc"
APP_ID = "app_cff7f9dc"


async def cleanup_containers():
    """Remove existing sandbox containers to start fresh."""
    import subprocess
    subprocess.run(
        "docker rm -f sandbox-agent-app_cff7f9dc sandbox-gateway-app_cff7f9dc 2>/dev/null",
        shell=True, capture_output=True
    )
    subprocess.run(
        "docker network rm adk-sandbox-net-app_cff7f9dc-internal 2>/dev/null",
        shell=True, capture_output=True
    )
    print("🧹 Cleaned up existing containers")


async def check_gateway_pending():
    """Check the gateway's pending requests directly."""
    import subprocess
    result = subprocess.run(
        "docker port sandbox-gateway-app_cff7f9dc 8081 2>/dev/null | cut -d: -f2",
        shell=True, capture_output=True, text=True
    )
    port = result.stdout.strip()
    if not port:
        return {"error": "Gateway not found"}
    
    async with aiohttp.ClientSession() as session:
        async with session.get(f"http://localhost:{port}/pending") as resp:
            return await resp.json()


async def test_approval_flow():
    """Test the complete approval flow."""
    print("\n" + "="*60)
    print("Testing Network Approval Flow")
    print("="*60 + "\n")
    
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
            'message': 'Hello',
            'sandbox_mode': True
        }))
        
        # Step 3: Wait for approval_required event
        print("\n3️⃣ Waiting for events...")
        approval_request = None
        start = time.time()
        timeout = 60
        
        while time.time() - start < timeout:
            try:
                response = await asyncio.wait_for(ws.recv(), timeout=2)
                data = json.loads(response)
                event_type = data.get('event_type') or data.get('type')
                
                # Log all events
                if event_type == 'network_request':
                    host = data.get('host') or data.get('data', {}).get('host', '?')
                    status = data.get('status') or data.get('data', {}).get('status', '?')
                    print(f"   📡 Network: {host} ({status})")
                    
                    if status == 'pending':
                        approval_request = data
                        print(f"   🚨 FOUND PENDING REQUEST!")
                        break
                elif event_type == 'approval_required':
                    approval_request = data
                    print(f"   🚨 APPROVAL REQUIRED: {data.get('host')}")
                    break
                elif event_type == 'agent_start':
                    agent = data.get('agent_name') or data.get('data', {}).get('agent_name', '?')
                    print(f"   🤖 Agent start: {agent}")
                else:
                    print(f"   📨 {event_type}")
                    
            except asyncio.TimeoutError:
                # Check gateway directly
                pending = await check_gateway_pending()
                if pending.get('count', 0) > 0:
                    print(f"   🔍 Gateway has {pending['count']} pending requests!")
                    approval_request = {"id": pending['pending'][0]}
                    break
                print(f"   ⏳ Waiting... ({int(time.time() - start)}s)")
        
        if not approval_request:
            print("\n❌ FAILED: No approval request received")
            print("   Check if the project has a callback that makes external requests")
            return False
        
        request_id = approval_request.get('id') or approval_request.get('request_id')
        print(f"\n4️⃣ Got approval request: {request_id}")
        
        # Step 4: Check gateway pending before approval
        print("\n5️⃣ Checking gateway pending requests...")
        pending = await check_gateway_pending()
        print(f"   Gateway pending: {pending}")
        
        # Step 5: Call approval API
        print(f"\n6️⃣ Calling approval API...")
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{BACKEND_URL}/api/sandbox/{APP_ID}/approval",
                json={
                    'request_id': request_id,
                    'action': 'allow_pattern',
                    'pattern': 'bodygen.re',
                    'pattern_type': 'exact',
                },
            ) as resp:
                body = await resp.text()
                print(f"   Status: {resp.status}")
                print(f"   Response: {body}")
                
                if resp.status == 200:
                    print("\n✅ SUCCESS: Approval accepted!")
                    return True
                else:
                    print("\n❌ FAILED: Approval rejected")
                    
                    # Debug: check gateway pending after failure
                    pending_after = await check_gateway_pending()
                    print(f"   Gateway pending after: {pending_after}")
                    return False


async def main():
    try:
        success = await test_approval_flow()
        print("\n" + "="*60)
        if success:
            print("✅ TEST PASSED")
        else:
            print("❌ TEST FAILED")
        print("="*60 + "\n")
        return success
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)


