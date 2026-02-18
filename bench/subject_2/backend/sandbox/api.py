"""API routes for the Docker sandbox.

These routes are added to the main FastAPI app.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from .docker_manager import get_sandbox_manager
from .models import (
    ApprovalDecision,
    NetworkAllowlist,
    NetworkRequest,
    PatternType,
    SandboxConfig,
    SandboxInstance,
    SandboxStatus,
)
from .allowlist_persistence import (
    add_pattern_to_project,
    remove_pattern_from_project,
    load_sandbox_config_from_project,
    save_sandbox_config_to_project,
)

logger = logging.getLogger(__name__)

# Create router with prefix
router = APIRouter(prefix="/api/sandbox", tags=["sandbox"])


# =============================================================================
# Request/Response Models
# =============================================================================

class StartSandboxRequest(BaseModel):
    """Request to start a sandbox."""
    app_id: str
    project_id: str
    config: Optional[SandboxConfig] = None


class StartSandboxResponse(BaseModel):
    """Response from starting a sandbox."""
    status: str
    instance: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class SendMessageRequest(BaseModel):
    """Request to send a message to the agent."""
    message: str
    session_id: Optional[str] = None


class ApprovalRequest(BaseModel):
    """Request to approve/deny a network request."""
    request_id: str
    action: str  # "allow_once", "allow_pattern", "deny"
    pattern: Optional[str] = None
    pattern_type: str = "exact"
    persist: bool = False


class AddPatternRequest(BaseModel):
    """Request to add a pattern to the allowlist."""
    pattern: str
    pattern_type: str = "exact"
    persist: bool = False  # Save to project YAML
    project_id: Optional[str] = None


class SandboxStatusResponse(BaseModel):
    """Response with sandbox status."""
    status: str
    instance: Optional[Dict[str, Any]] = None


class AllowlistResponse(BaseModel):
    """Response with allowlist patterns."""
    auto: List[str]
    user: List[Dict[str, Any]]


class NetworkActivityResponse(BaseModel):
    """Response with network activity."""
    requests: List[Dict[str, Any]]


# =============================================================================
# API Routes
# =============================================================================

@router.post("/start", response_model=StartSandboxResponse)
async def start_sandbox(request: StartSandboxRequest):
    """Start a sandbox for an App.
    
    The sandbox is App-scoped: all agents in the App share the same sandbox.
    """
    manager = get_sandbox_manager()
    
    # Load project config
    from project_manager import project_manager
    project = project_manager.get_project(request.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Get workspace path
    project_path = project_manager.get_project_path(request.project_id)
    if not project_path:
        raise HTTPException(status_code=404, detail="Project path not found")
    
    workspace_path = Path(project_path).parent  # For Docker mounts, we need the directory
    
    # Use provided config or create default
    config = request.config or SandboxConfig(enabled=True)
    
    try:
        instance = await manager.start_sandbox(
            app_id=request.app_id,
            config=config,
            project_config=project.model_dump(),
            workspace_path=workspace_path,
        )
        
        return StartSandboxResponse(
            status="started",
            instance=instance.model_dump(),
        )
    except Exception as e:
        logger.error(f"Failed to start sandbox: {e}", exc_info=True)
        return StartSandboxResponse(
            status="error",
            error=str(e),
        )


@router.post("/{app_id}/stop")
async def stop_sandbox(app_id: str):
    """Stop a sandbox."""
    manager = get_sandbox_manager()
    
    success = await manager.stop_sandbox(app_id)
    if not success:
        raise HTTPException(status_code=404, detail="Sandbox not found")
    
    return {"status": "stopped"}


@router.get("/{app_id}/status", response_model=SandboxStatusResponse)
async def get_sandbox_status(app_id: str):
    """Get sandbox status."""
    manager = get_sandbox_manager()
    
    instance = await manager.get_sandbox_status(app_id)
    if not instance:
        return SandboxStatusResponse(status="not_found")
    
    return SandboxStatusResponse(
        status=instance.status.value,
        instance=instance.model_dump(),
    )


@router.get("/list")
async def list_sandboxes():
    """List all sandboxes."""
    manager = get_sandbox_manager()
    
    instances = await manager.list_sandboxes()
    return {
        "sandboxes": [i.model_dump() for i in instances],
    }


@router.post("/{app_id}/message")
async def send_message(app_id: str, request: SendMessageRequest):
    """Send a message to the agent in the sandbox."""
    manager = get_sandbox_manager()
    
    session_id = await manager.send_message_to_agent(
        app_id=app_id,
        message=request.message,
        session_id=request.session_id,
    )
    
    if not session_id:
        raise HTTPException(status_code=404, detail="Sandbox not running")
    
    return {"status": "sent", "session_id": session_id}


@router.post("/{app_id}/approval")
async def handle_approval(app_id: str, request: ApprovalRequest, project_id: Optional[str] = None):
    """Handle approval/denial of a network request.
    
    If persist=True and project_id is provided, the pattern is saved to the
    project's YAML configuration.
    """
    manager = get_sandbox_manager()
    
    # Debug logging
    logger.info(f"🔐 Approval request: app_id={app_id}, request_id={request.request_id}, action={request.action}")
    logger.info(f"   Manager id={id(manager)}, instances: {list(manager.instances.keys())}")
    
    instance = manager.instances.get(app_id)
    if instance:
        logger.info(f"   Instance found: status={instance.status}, gateway={instance.gateway_container_id[:12] if instance.gateway_container_id else None}")
    else:
        logger.info(f"   ❌ No instance found for app_id={app_id}")
    
    if request.action == "deny":
        success = await manager.deny_request(app_id, request.request_id)
    else:
        # allow_once or allow_pattern
        pattern = request.pattern if request.action == "allow_pattern" else None
        success = await manager.approve_request(app_id, request.request_id, pattern)
    
    logger.info(f"   Approval result: success={success}")
    
    if not success:
        raise HTTPException(status_code=404, detail="Request or sandbox not found")
    
    # Persist pattern to project YAML if requested
    persisted = False
    if request.persist and request.pattern and project_id:
        from project_manager import project_manager
        project_path = project_manager.get_project_path(project_id)
        if project_path:
            pattern_type = PatternType(request.pattern_type)
            # Pass the actual project file path (not parent directory)
            result = add_pattern_to_project(
                project_path=Path(project_path),
                pattern=request.pattern,
                pattern_type=pattern_type,
                source="approved",
            )
            persisted = result is not None
            logger.info(f"Persisted pattern '{request.pattern}' to {project_path}: {persisted}")
    
    return {
        "status": "processed",
        "action": request.action,
        "persisted": persisted,
    }


@router.get("/{app_id}/network", response_model=NetworkActivityResponse)
async def get_network_activity(app_id: str, limit: int = 100):
    """Get network activity for the sandbox."""
    manager = get_sandbox_manager()
    
    instance = await manager.get_sandbox_status(app_id)
    if not instance:
        raise HTTPException(status_code=404, detail="Sandbox not found")
    
    # Get requests from the instance
    requests = [r.model_dump() for r in instance.network_requests[-limit:]]
    
    return NetworkActivityResponse(requests=requests)


@router.get("/{app_id}/allowlist", response_model=AllowlistResponse)
async def get_allowlist(app_id: str):
    """Get the current allowlist for the sandbox."""
    manager = get_sandbox_manager()
    
    instance = await manager.get_sandbox_status(app_id)
    if not instance or not instance.config:
        raise HTTPException(status_code=404, detail="Sandbox not found")
    
    allowlist = instance.config.allowlist.with_defaults()
    
    return AllowlistResponse(
        auto=allowlist.auto,
        user=[p.to_dict() for p in allowlist.user],
    )


@router.post("/{app_id}/allowlist")
async def add_allowlist_pattern(app_id: str, request: AddPatternRequest):
    """Add a pattern to the allowlist.
    
    If persist=True and project_id is provided, the pattern is saved to the
    project's YAML configuration.
    """
    manager = get_sandbox_manager()
    
    instance = await manager.get_sandbox_status(app_id)
    if not instance or not instance.config:
        raise HTTPException(status_code=404, detail="Sandbox not found")
    
    # Add pattern to runtime config
    pattern_type = PatternType(request.pattern_type)
    new_pattern = instance.config.allowlist.add_user_pattern(
        pattern=request.pattern,
        pattern_type=pattern_type,
        source="user",
    )
    
    # Notify gateway container about the new pattern
    try:
        await manager.approve_request(app_id, "", request.pattern)
    except Exception:
        pass  # Non-critical
    
    # Persist to project YAML if requested
    persisted = False
    if request.persist and request.project_id:
        from project_manager import project_manager
        project_path = project_manager.get_project_path(request.project_id)
        if project_path:
            result = add_pattern_to_project(
                project_path=Path(project_path),  # Use actual file path
                pattern=request.pattern,
                pattern_type=pattern_type,
                source="user",
            )
            persisted = result is not None
    
    return {
        "status": "added",
        "pattern": new_pattern.to_dict(),
        "persisted": persisted,
    }


@router.delete("/{app_id}/allowlist/{pattern_id}")
async def remove_allowlist_pattern(app_id: str, pattern_id: str):
    """Remove a pattern from the allowlist."""
    manager = get_sandbox_manager()
    
    instance = await manager.get_sandbox_status(app_id)
    if not instance or not instance.config:
        raise HTTPException(status_code=404, detail="Sandbox not found")
    
    success = instance.config.allowlist.remove_user_pattern(pattern_id)
    if not success:
        raise HTTPException(status_code=404, detail="Pattern not found")
    
    return {"status": "removed"}


@router.get("/{app_id}/mcp-status")
async def get_mcp_status(app_id: str):
    """Get status of MCP server containers."""
    manager = get_sandbox_manager()
    
    instance = await manager.get_sandbox_status(app_id)
    if not instance:
        raise HTTPException(status_code=404, detail="Sandbox not found")
    
    return {
        "mcp_containers": [c.model_dump() for c in instance.mcp_containers],
    }


@router.get("/{app_id}/logs")
async def get_container_logs(
    app_id: str, 
    container: str = "agent",  # "agent" or "gateway"
    tail: int = 500,
    since: Optional[int] = None,
):
    """Get logs from a sandbox container.
    
    Args:
        app_id: The App ID
        container: Which container to get logs from ("agent" or "gateway")
        tail: Number of lines to return from the end (default 500)
        since: Only return logs since this Unix timestamp
    
    Returns:
        Container logs as text
    """
    manager = get_sandbox_manager()
    
    result = await manager.get_container_logs(
        app_id=app_id,
        container_type=container,
        tail=tail,
        since=since,
    )
    
    if "error" in result:
        raise HTTPException(
            status_code=404 if "not found" in result["error"].lower() else 500,
            detail=result["error"]
        )
    
    return result


# =============================================================================
# MCP Tool Execution - for Tool Watches and debugging
# =============================================================================

@router.get("/{app_id}/mcp/servers")
async def mcp_list_servers(app_id: str):
    """List available MCP servers in the sandbox.
    
    Returns servers configured in the project that can be connected to.
    """
    manager = get_sandbox_manager()
    result = await manager.mcp_list_servers(app_id)
    
    if "error" in result:
        raise HTTPException(status_code=404 if "not found" in result["error"].lower() else 500, 
                          detail=result["error"])
    
    return result


class MCPListToolsRequest(BaseModel):
    """Request to list tools from an MCP server."""
    server: str


@router.post("/{app_id}/mcp/tools")
async def mcp_list_tools(app_id: str, request: MCPListToolsRequest):
    """List tools available from an MCP server in the sandbox.
    
    This connects to the MCP server if not already connected.
    """
    manager = get_sandbox_manager()
    result = await manager.mcp_list_tools(app_id, request.server)
    
    if "error" in result:
        raise HTTPException(status_code=404 if "not found" in result["error"].lower() else 500, 
                          detail=result["error"])
    
    return result


class MCPCallToolRequest(BaseModel):
    """Request to call an MCP tool."""
    server: str
    tool: str
    args: Dict[str, Any] = Field(default_factory=dict)


@router.post("/{app_id}/mcp/call")
async def mcp_call_tool(app_id: str, request: MCPCallToolRequest):
    """Call an MCP tool in the sandbox.
    
    This executes the tool from the perspective of the agent runner,
    useful for Tool Watches and debugging to inspect the container's state.
    
    Example:
        POST /api/sandbox/{app_id}/mcp/call
        {
            "server": "filesystem",
            "tool": "list_directory",
            "args": {"path": "/tmp"}
        }
    """
    manager = get_sandbox_manager()
    result = await manager.mcp_call_tool(
        app_id=app_id,
        server_name=request.server,
        tool_name=request.tool,
        args=request.args,
    )
    
    if "error" in result:
        raise HTTPException(status_code=404 if "not found" in result["error"].lower() else 500, 
                          detail=result["error"])
    
    return result


class MCPDisconnectRequest(BaseModel):
    """Request to disconnect from MCP servers."""
    server: Optional[str] = None  # If None, disconnect from all


@router.post("/{app_id}/mcp/disconnect")
async def mcp_disconnect(app_id: str, request: MCPDisconnectRequest):
    """Disconnect from MCP servers in the sandbox.
    
    Useful for cleaning up connections or forcing a reconnect.
    """
    manager = get_sandbox_manager()
    result = await manager.mcp_disconnect(app_id, request.server)
    
    if "error" in result:
        raise HTTPException(status_code=404 if "not found" in result["error"].lower() else 500, 
                          detail=result["error"])
    
    return result


class SyncAllowlistRequest(BaseModel):
    """Request to sync allowlist patterns to a running gateway."""
    patterns: List[Dict[str, Any]]


@router.post("/{app_id}/allowlist/sync")
async def sync_allowlist_to_gateway(app_id: str, request: SyncAllowlistRequest):
    """Sync allowlist patterns to a running gateway.
    
    This pushes patterns to the mitmproxy gateway without restarting it.
    Called when the allowlist is updated in the App configurator.
    """
    manager = get_sandbox_manager()
    
    count = await manager.sync_allowlist_to_gateway(app_id, request.patterns)
    
    return {
        "status": "synced",
        "patterns_added": count,
    }


@router.post("/{app_id}/allowlist/persist")
async def persist_allowlist(app_id: str, project_id: str):
    """Persist the entire allowlist to project YAML.
    
    Saves all user-defined patterns to the project's configuration file.
    """
    manager = get_sandbox_manager()
    
    instance = await manager.get_sandbox_status(app_id)
    if not instance or not instance.config:
        raise HTTPException(status_code=404, detail="Sandbox not found")
    
    from project_manager import project_manager
    from .allowlist_persistence import save_allowlist_to_project
    
    project_path = project_manager.get_project_path(project_id)
    if not project_path:
        raise HTTPException(status_code=404, detail="Project not found")
    
    success = save_allowlist_to_project(
        project_path=Path(project_path),  # Use actual file path
        allowlist=instance.config.allowlist,
    )
    
    if not success:
        raise HTTPException(status_code=500, detail="Failed to save allowlist")
    
    return {"status": "persisted", "pattern_count": len(instance.config.allowlist.user)}


# =============================================================================
# Project-level sandbox config endpoints
# =============================================================================

@router.get("/config/{project_id}")
async def get_sandbox_config(project_id: str):
    """Get sandbox configuration for a project."""
    from project_manager import project_manager
    
    project_path = project_manager.get_project_path(project_id)
    if not project_path:
        raise HTTPException(status_code=404, detail="Project not found")
    
    config = load_sandbox_config_from_project(Path(project_path))  # Use actual file path
    
    return {
        "config": config.model_dump(),
        "allowlist": {
            "auto": config.allowlist.with_defaults().auto,
            "user": [p.to_dict() for p in config.allowlist.user],
        },
    }


@router.put("/config/{project_id}")
async def update_sandbox_config(project_id: str, config: SandboxConfig):
    """Update sandbox configuration for a project."""
    from project_manager import project_manager
    
    project_path = project_manager.get_project_path(project_id)
    if not project_path:
        raise HTTPException(status_code=404, detail="Project not found")
    
    success = save_sandbox_config_to_project(
        project_path=Path(project_path),  # Use actual file path
        config=config,
    )
    
    if not success:
        raise HTTPException(status_code=500, detail="Failed to save config")
    
    return {"status": "updated"}


# =============================================================================
# WebSocket for streaming events
# =============================================================================

@router.websocket("/{app_id}/events")
async def sandbox_events_ws(websocket: WebSocket, app_id: str):
    """WebSocket for streaming sandbox events."""
    await websocket.accept()
    
    manager = get_sandbox_manager()
    instance = await manager.get_sandbox_status(app_id)
    
    if not instance:
        await websocket.close(code=4004, reason="Sandbox not found")
        return
    
    try:
        # TODO: Implement proper event streaming from sandbox
        # For now, just keep connection alive
        while True:
            try:
                # Wait for messages from client (ping/pong)
                data = await websocket.receive_text()
                if data == "ping":
                    await websocket.send_text("pong")
            except WebSocketDisconnect:
                break
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


# =============================================================================
# Webhook endpoint for sandbox containers
# =============================================================================

from .webhook_handler import webhook_handler


class WebhookPayload(BaseModel):
    """Payload from sandbox containers."""
    event_type: str
    app_id: str
    timestamp: float
    data: Dict[str, Any]


@router.post("/webhook/{app_id}")
async def sandbox_webhook_with_app_id(app_id: str, payload: Dict[str, Any]):
    """Receive events from sandbox containers (app_id in path).
    
    This endpoint is called by the gateway container to:
    - Notify about network requests
    - Request approval for blocked requests
    - Report errors
    """
    event_type = payload.get("event_type", "unknown")
    data = payload.get("data", {})
    
    # Debug: log the request ID for pending requests
    if data.get("status") == "pending" or event_type == "approval_required":
        logger.info(f"🔑 Pending request ID received: {data.get('id')} for host {data.get('host')}")
    
    logger.info(f"📡 Webhook received: {event_type} for {app_id}")
    
    await webhook_handler.handle_event(
        event_type=event_type,
        app_id=app_id,
        data=data,
    )
    
    # Forward as agent_event for WebSocket streaming
    events = await webhook_handler.get_or_create(app_id)
    events._notify({"type": "network_request", "data": {"event_type": event_type, **data}})
    
    return {"status": "received"}


@router.post("/webhook")
async def sandbox_webhook(payload: WebhookPayload):
    """Receive events from sandbox containers (app_id in payload).
    
    This endpoint is called by the gateway container to:
    - Notify about network requests
    - Request approval for blocked requests
    - Report errors
    """
    logger.info(f"📡 Webhook received: {payload.event_type} for {payload.app_id}")
    
    await webhook_handler.handle_event(
        event_type=payload.event_type,
        app_id=payload.app_id,
        data=payload.data,
    )
    
    # Also update the sandbox instance if we have one
    manager = get_sandbox_manager()
    if payload.app_id in manager.sandboxes:
        instance = manager.sandboxes[payload.app_id]
        
        # Handle network request events
        if payload.event_type in ("network_request", "network_response"):
            request_data = payload.data
            request_id = request_data.get("id")
            
            if request_id:
                # Check if request exists
                existing = next(
                    (r for r in instance.network_requests if r.id == request_id),
                    None
                )
                
                if existing:
                    # Update existing request
                    if request_data.get("status"):
                        existing.status = request_data["status"]
                    if request_data.get("response_status"):
                        existing.response_status = request_data["response_status"]
                    if request_data.get("response_time_ms"):
                        existing.response_time_ms = request_data["response_time_ms"]
                    if request_data.get("response_size"):
                        existing.response_size = request_data["response_size"]
                else:
                    # Create new request
                    from datetime import datetime
                    
                    request = NetworkRequest(
                        id=request_id,
                        timestamp=datetime.now().isoformat(),
                        method=request_data.get("method", "GET"),
                        url=request_data.get("url", ""),
                        host=request_data.get("host", ""),
                        status=request_data.get("status", "pending"),
                        source=request_data.get("source", "agent"),
                        matched_pattern=request_data.get("matched_pattern"),
                        is_llm_provider=request_data.get("is_llm_provider", False),
                        headers=request_data.get("headers"),
                    )
                    instance.network_requests.append(request)
                    
                    # Track pending approvals
                    if request.status == "pending":
                        instance.pending_approvals.append(request_id)
    
    return {"status": "received"}


@router.post("/event")
async def sandbox_event(data: Dict[str, Any]):
    """Receive events from agent container.
    
    This endpoint is called by the agent runner to stream events.
    """
    event_type = data.get("event_type") or data.get("type")
    app_id = data.get("app_id")
    
    logger.info(f"📨 Sandbox event: {event_type} for app_id='{app_id}' (type={type(app_id).__name__})")
    
    # Forward to webhook handler for broadcasting
    if app_id and app_id != "None":  # Check for string "None" too
        events = await webhook_handler.get_or_create(app_id)
        logger.info(f"📢 Broadcasting to {len(events.subscribers)} subscribers for {app_id}")
        events._notify({"type": "agent_event", "data": data})
    else:
        logger.warning(f"⚠️ No valid app_id in event: app_id={repr(app_id)}, keys={list(data.keys())}")
    
    return {"status": "received"}

