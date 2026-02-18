"""
Webhook handler for receiving network events from the Docker sandbox gateway.

The mitmproxy gateway sends events here, and we store them and broadcast
to connected WebSocket clients.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional

from .models import NetworkRequest

logger = logging.getLogger(__name__)


@dataclass
class SandboxEvents:
    """Stores events for a sandbox instance."""
    
    app_id: str
    network_requests: dict[str, NetworkRequest] = field(default_factory=dict)
    pending_approvals: list[str] = field(default_factory=list)
    subscribers: list[Callable] = field(default_factory=list)
    
    def add_request(self, data: dict):
        """Add or update a network request."""
        request_id = data.get("id")
        if not request_id:
            return
        
        # Check if updating existing request
        existing = self.network_requests.get(request_id)
        
        if existing:
            # Update existing request
            if data.get("status"):
                existing.status = data["status"]
            if data.get("response_status"):
                existing.response_status = data["response_status"]
            if data.get("response_time_ms"):
                existing.response_time_ms = data["response_time_ms"]
            if data.get("response_size"):
                existing.response_size = data["response_size"]
            if data.get("matched_pattern"):
                existing.matched_pattern = data["matched_pattern"]
        else:
            # Create new request
            request = NetworkRequest(
                id=request_id,
                timestamp=datetime.now().isoformat(),
                method=data.get("method", "GET"),
                url=data.get("url", ""),
                host=data.get("host", ""),
                status=data.get("status", "pending"),
                source=data.get("source", "agent"),
                matched_pattern=data.get("matched_pattern"),
                is_llm_provider=data.get("is_llm_provider", False),
                headers=data.get("headers") or {},  # Handle None
            )
            self.network_requests[request_id] = request
            existing = request
        
        # Track pending approvals
        if existing.status == "pending":
            if request_id not in self.pending_approvals:
                self.pending_approvals.append(request_id)
        else:
            if request_id in self.pending_approvals:
                self.pending_approvals.remove(request_id)
        
        # Notify subscribers (convert to dict for JSON serialization)
        # Use mode='json' to ensure datetime objects are converted to strings
        self._notify({"type": "network_request", "data": existing.model_dump(mode='json')})
    
    def _notify(self, event: dict):
        """Notify all subscribers of an event."""
        for subscriber in self.subscribers:
            try:
                subscriber(event)
            except Exception as e:
                logger.warning(f"Failed to notify subscriber: {e}")
    
    def subscribe(self, callback: Callable):
        """Add a subscriber."""
        self.subscribers.append(callback)
    
    def unsubscribe(self, callback: Callable):
        """Remove a subscriber."""
        if callback in self.subscribers:
            self.subscribers.remove(callback)
    
    def get_pending_approvals(self) -> list[NetworkRequest]:
        """Get list of pending approval requests."""
        return [
            self.network_requests[rid] 
            for rid in self.pending_approvals 
            if rid in self.network_requests
        ]
    
    def get_all_requests(self) -> list[NetworkRequest]:
        """Get all network requests."""
        return list(self.network_requests.values())


class WebhookHandler:
    """Handles webhook events from sandbox gateways."""
    
    def __init__(self):
        self.sandboxes: dict[str, SandboxEvents] = {}
        self._lock = asyncio.Lock()
    
    async def get_or_create(self, app_id: str) -> SandboxEvents:
        """Get or create events storage for an app."""
        async with self._lock:
            if app_id not in self.sandboxes:
                self.sandboxes[app_id] = SandboxEvents(app_id=app_id)
            return self.sandboxes[app_id]
    
    async def clear(self, app_id: str):
        """Clear all events for an app (call when starting a new sandbox)."""
        async with self._lock:
            if app_id in self.sandboxes:
                old_events = len(self.sandboxes[app_id].network_requests)
                old_pending = len(self.sandboxes[app_id].pending_approvals)
                self.sandboxes[app_id] = SandboxEvents(app_id=app_id)
                logger.info(f"Cleared cached events for {app_id}: had {old_events} requests, {old_pending} pending")
    
    async def handle_event(self, event_type: str, app_id: str, data: dict):
        """Handle an incoming webhook event."""
        events = await self.get_or_create(app_id)
        
        if event_type == "network_request":
            events.add_request(data)
        elif event_type == "network_response":
            events.add_request(data)
        else:
            logger.debug(f"Unknown event type: {event_type}")
    
    async def cleanup(self, app_id: str):
        """Clean up events storage for an app."""
        async with self._lock:
            if app_id in self.sandboxes:
                del self.sandboxes[app_id]


# Global handler instance
webhook_handler = WebhookHandler()

