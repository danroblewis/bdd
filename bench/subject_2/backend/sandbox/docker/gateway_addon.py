"""
Mitmproxy addon for the ADK Playground Docker sandbox.

This addon intercepts all HTTP/HTTPS traffic from the sandbox and:
1. Checks if the destination is in the allowlist
2. Blocks requests to unknown hosts (or asks for approval)
3. Reports all network activity to the host via webhook
4. Attributes traffic to its source (agent or MCP server)
"""

from __future__ import annotations

import asyncio
import fnmatch
import json
import logging
import os
import re
import threading
import time
from typing import Optional

from mitmproxy import ctx, http

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gateway_addon")


class PendingApproval:
    """Represents a request waiting for approval."""
    
    def __init__(self, request_id: str, flow: http.HTTPFlow, timeout: int):
        self.request_id = request_id
        self.flow = flow
        self.timeout = timeout
        self.created_at = time.time()
        self.approved: Optional[bool] = None
        self.pattern: Optional[str] = None
        self.pattern_type: str = "exact"
        self.event = threading.Event()
    
    def is_expired(self) -> bool:
        return time.time() - self.created_at > self.timeout
    
    def approve(self, pattern: Optional[str] = None, pattern_type: str = "exact"):
        self.approved = True
        self.pattern = pattern
        self.pattern_type = pattern_type
        self.event.set()
    
    def deny(self):
        self.approved = False
        self.event.set()
    
    def wait(self) -> bool:
        """Wait for approval decision or timeout. Returns True if approved."""
        remaining = self.timeout - (time.time() - self.created_at)
        if remaining <= 0:
            return False
        
        self.event.wait(timeout=remaining)
        return self.approved is True


class AllowlistGateway:
    """Mitmproxy addon that enforces network allowlist."""

    def __init__(self):
        # Load configuration from environment
        self.webhook_url = os.environ.get(
            "WEBHOOK_URL", "http://host.docker.internal:8765/api/sandbox/webhook"
        )
        self.app_id = os.environ.get("APP_ID", "unknown")
        self.unknown_action = os.environ.get("UNKNOWN_ACTION", "ask")  # ask, deny, allow
        self.approval_timeout = int(os.environ.get("APPROVAL_TIMEOUT", "30"))
        self.allow_all_network = os.environ.get("ALLOW_ALL_NETWORK", "false").lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        
        # Parse allowlist from environment (JSON)
        self.exact_patterns: list[str] = []
        self.wildcard_patterns: list[str] = []
        self.regex_patterns: list[re.Pattern] = []
        self._load_allowlist()
        
        # Pending approvals: request_id -> PendingApproval
        self.pending_approvals: dict[str, PendingApproval] = {}
        self._pending_lock = threading.Lock()
        
        # Known LLM provider domains (always allowed for model calls)
        self.llm_providers = {
            "generativelanguage.googleapis.com",
            "aiplatform.googleapis.com",
            "api.anthropic.com",
            "api.openai.com",
            "openai.azure.com",  # Azure OpenAI (e.g., companyname.openai.azure.com)
            "api.together.xyz",
            "api.mistral.ai",
            "api.cohere.ai",
            "api.groq.com",
            "api.deepseek.com",
            "api.fireworks.ai",
        }

    def _load_allowlist(self):
        """Load allowlist patterns from environment."""
        try:
            allowlist_json = os.environ.get("ALLOWLIST", "[]")
            patterns = json.loads(allowlist_json)
            
            for p in patterns:
                pattern = p.get("pattern", "")
                pattern_type = p.get("pattern_type", "exact")
                
                if pattern_type == "exact":
                    self.exact_patterns.append(pattern.lower())
                elif pattern_type == "wildcard":
                    self.wildcard_patterns.append(pattern.lower())
                elif pattern_type == "regex":
                    try:
                        self.regex_patterns.append(re.compile(pattern, re.IGNORECASE))
                    except re.error as e:
                        logger.warning(f"Invalid regex pattern '{pattern}': {e}")
            
            logger.info(f"Loaded {len(self.exact_patterns)} exact, "
                       f"{len(self.wildcard_patterns)} wildcard, "
                       f"{len(self.regex_patterns)} regex patterns")
        except Exception as e:
            logger.error(f"Failed to load allowlist: {e}")

    def _match_pattern(self, host: str, url: str) -> Optional[str]:
        """Check if host/url matches any allowlist pattern."""
        host_lower = host.lower()
        url_lower = url.lower()
        
        # Extract host:port from URL for more accurate matching
        # URL format: http://host:port/path or https://host:port/path
        url_host = ""
        try:
            if "://" in url_lower:
                after_scheme = url_lower.split("://", 1)[1]
                url_host = after_scheme.split("/", 1)[0]  # host:port part
        except Exception:
            pass
        
        # Check exact patterns
        for pattern in self.exact_patterns:
            # Match against host, host:port from URL, or check if URL contains pattern
            if (host_lower == pattern or 
                url_host == pattern or
                pattern in url_lower or
                # Also match host without port against pattern without port
                host_lower == pattern.split(":")[0]):
                return pattern
        
        # Check wildcard patterns
        for pattern in self.wildcard_patterns:
            # Convert wildcard to regex-like matching
            if "*" in pattern:
                if (fnmatch.fnmatch(host_lower, pattern) or 
                    fnmatch.fnmatch(url_lower, pattern) or
                    fnmatch.fnmatch(url_host, pattern)):
                    return pattern
            elif host_lower == pattern or url_host == pattern:
                return pattern
        
        # Check regex patterns
        for regex in self.regex_patterns:
            if regex.search(url_lower) or regex.search(host_lower):
                return regex.pattern
        
        return None

    def _is_llm_provider(self, host: str) -> bool:
        """Check if host is a known LLM API provider."""
        host_lower = host.lower()
        for provider in self.llm_providers:
            if host_lower == provider or host_lower.endswith("." + provider):
                return True
        return False

    def _get_source(self, flow: http.HTTPFlow) -> str:
        """Determine the source of the request (agent or MCP server)."""
        # Check X-Sandbox-Source header
        source_header = flow.request.headers.get("X-Sandbox-Source", "")
        if source_header:
            # Remove the header so it doesn't leak to destination
            del flow.request.headers["X-Sandbox-Source"]
            return source_header
        
        # Default to agent
        return "agent"

    def _send_webhook(self, event_type: str, data: dict):
        """Send event to host via webhook."""
        try:
            import urllib.request
            import urllib.error
            
            payload = {
                "event_type": event_type,
                "app_id": self.app_id,
                "timestamp": time.time(),
                "data": data,
            }
            
            req = urllib.request.Request(
                self.webhook_url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            
            with urllib.request.urlopen(req, timeout=5) as resp:
                pass  # Fire and forget
        except Exception as e:
            logger.debug(f"Webhook failed: {e}")

    def _request_approval(self, flow: http.HTTPFlow, request_id: str, host: str, 
                          url: str, method: str, source: str) -> bool:
        """Request approval for a blocked request and wait for decision."""
        # Create pending approval
        pending = PendingApproval(request_id, flow, self.approval_timeout)
        
        with self._pending_lock:
            self.pending_approvals[request_id] = pending
        
        # Send approval request to host
        self._send_webhook("approval_required", {
            "id": request_id,
            "method": method,
            "url": url,
            "host": host,
            "source": source,
            "is_llm_provider": False,
            "timeout": self.approval_timeout,
            "headers": {k: v for k, v in flow.request.headers.items() 
                       if k.lower() not in ("authorization", "cookie", "x-api-key")},
        })
        
        logger.info(f"Waiting for approval: {request_id} ({host})")
        
        # Wait for approval (blocking)
        approved = pending.wait()
        
        # Cleanup
        with self._pending_lock:
            if request_id in self.pending_approvals:
                del self.pending_approvals[request_id]
        
        # If approved with a pattern, add it to allowlist
        if approved and pending.pattern:
            self.add_pattern(pending.pattern, pending.pattern_type)
        
        return approved

    def tls_clienthello(self, data):
        """Handle TLS client hello - passthrough for LLM providers.
        
        This avoids MITM'ing HTTPS connections to LLM APIs, which would
        cause SSL certificate verification failures in the agent.
        """
        # Get the Server Name Indication (SNI) from the client hello
        sni = data.context.client.sni
        if sni:
            # In allow-all mode, avoid MITM for arbitrary TLS targets.
            # The agent container typically does not trust the mitmproxy CA, so
            # passthrough ensures HTTPS connectivity while still routing through
            # the gateway (as the network chokepoint).
            if self.allow_all_network:
                sni_lower = sni.lower()
                data.ignore_connection = True

                # Emit a lightweight network event (we won't see the decrypted HTTP request).
                try:
                    request_id = f"tls_{int(time.time() * 1000)}_{threading.get_ident()}"
                    self._send_webhook("network_request", {
                        "id": request_id,
                        "method": "TLS",
                        "url": f"tls://{sni}",
                        "host": sni,
                        "status": "allowed",
                        "source": "agent",
                        "is_llm_provider": self._is_llm_provider(sni_lower),
                        "matched_pattern": "*",
                    })
                except Exception:
                    pass
                return

            # Check if this is an LLM provider domain
            sni_lower = sni.lower()
            if self._is_llm_provider(sni_lower):
                logger.info(f"[PASSTHROUGH] TLS to LLM provider: {sni}")
                # Tell mitmproxy to ignore this connection (passthrough)
                data.ignore_connection = True
                return
            
            # Also passthrough for Google OAuth/auth domains
            if any(domain in sni_lower for domain in [
                "accounts.google.com",
                "oauth2.googleapis.com",
                "www.googleapis.com",
                "storage.googleapis.com",
            ]):
                logger.info(f"[PASSTHROUGH] TLS to Google service: {sni}")
                data.ignore_connection = True
                return
            
            # Passthrough for PyPI (package installation in containers)
            if any(domain in sni_lower for domain in [
                "pypi.org",
                "files.pythonhosted.org",
                "pythonhosted.org",
            ]):
                logger.info(f"[PASSTHROUGH] TLS to PyPI: {sni}")
                data.ignore_connection = True
                return
            
            # Passthrough for npm registry (Node.js package installation)
            if any(domain in sni_lower for domain in [
                "registry.npmjs.org",
                "npmjs.org",
            ]):
                logger.info(f"[PASSTHROUGH] TLS to npm: {sni}")
                data.ignore_connection = True
                return
            
            # Passthrough for GitHub (package downloads)
            if any(domain in sni_lower for domain in [
                "github.com",
                "githubusercontent.com",
                "github.io",
            ]):
                logger.info(f"[PASSTHROUGH] TLS to GitHub: {sni}")
                data.ignore_connection = True
                return

    def request(self, flow: http.HTTPFlow):
        """Handle incoming request."""
        host = flow.request.host
        url = flow.request.pretty_url
        method = flow.request.method
        source = self._get_source(flow)
        is_llm = self._is_llm_provider(host)
        
        # Generate request ID
        request_id = f"{int(time.time() * 1000)}_{id(flow)}"
        flow.metadata["request_id"] = request_id
        flow.metadata["source"] = source
        flow.metadata["is_llm_provider"] = is_llm
        flow.metadata["start_time"] = time.time()
        
        # Check allowlist
        matched_pattern = self._match_pattern(host, url)
        
        # Determine action
        if matched_pattern or is_llm:
            # Allowed
            action = "allowed"
            flow.metadata["matched_pattern"] = matched_pattern or "llm_provider"
            
            # Report to webhook
            self._send_webhook("network_request", {
                "id": request_id,
                "method": method,
                "url": url,
                "host": host,
                "status": action,
                "source": source,
                "is_llm_provider": is_llm,
                "matched_pattern": matched_pattern,
            })
            
        elif self.unknown_action == "allow":
            action = "allowed"
            
            self._send_webhook("network_request", {
                "id": request_id,
                "method": method,
                "url": url,
                "host": host,
                "status": action,
                "source": source,
                "is_llm_provider": is_llm,
                "matched_pattern": None,
            })
            
        elif self.unknown_action == "deny":
            action = "denied"
            
            self._send_webhook("network_request", {
                "id": request_id,
                "method": method,
                "url": url,
                "host": host,
                "status": action,
                "source": source,
                "is_llm_provider": is_llm,
                "matched_pattern": None,
            })
            
            flow.response = http.Response.make(
                403,
                f"Blocked by sandbox: {host} is not in allowlist",
                {"Content-Type": "text/plain"},
            )
            
        else:
            # Ask mode - notify and wait for approval
            self._send_webhook("network_request", {
                "id": request_id,
                "method": method,
                "url": url,
                "host": host,
                "status": "pending",
                "source": source,
                "is_llm_provider": is_llm,
                "matched_pattern": None,
                "headers": {k: v for k, v in flow.request.headers.items() 
                           if k.lower() not in ("authorization", "cookie", "x-api-key")},
            })
            
            approved = self._request_approval(flow, request_id, host, url, method, source)
            
            if approved:
                action = "allowed"
                self._send_webhook("network_request", {
                    "id": request_id,
                    "status": "allowed",
                })
            else:
                action = "denied"
                self._send_webhook("network_request", {
                    "id": request_id,
                    "status": "denied",
                })
                
                flow.response = http.Response.make(
                    403,
                    f"Request denied: {host}",
                    {"Content-Type": "text/plain"},
                )
        
        logger.info(f"[{action.upper()}] {source}: {method} {url}")

    def response(self, flow: http.HTTPFlow):
        """Handle response (for timing and size)."""
        request_id = flow.metadata.get("request_id")
        if not request_id:
            return
        
        start_time = flow.metadata.get("start_time", time.time())
        response_time_ms = (time.time() - start_time) * 1000
        response_size = len(flow.response.content) if flow.response.content else 0
        
        self._send_webhook("network_response", {
            "id": request_id,
            "status": "completed",
            "response_status": flow.response.status_code,
            "response_time_ms": response_time_ms,
            "response_size": response_size,
        })

    def add_pattern(self, pattern: str, pattern_type: str) -> bool:
        """Add a pattern to the allowlist (called via control API)."""
        if pattern_type == "exact":
            self.exact_patterns.append(pattern.lower())
        elif pattern_type == "wildcard":
            self.wildcard_patterns.append(pattern.lower())
        elif pattern_type == "regex":
            try:
                self.regex_patterns.append(re.compile(pattern, re.IGNORECASE))
            except re.error as e:
                logger.warning(f"Invalid regex pattern '{pattern}': {e}")
                return False
        
        logger.info(f"Added {pattern_type} pattern: {pattern}")
        return True
    
    def approve_request(self, request_id: str, pattern: Optional[str] = None, 
                       pattern_type: str = "exact"):
        """Approve a pending request."""
        with self._pending_lock:
            pending = self.pending_approvals.get(request_id)
            if pending:
                pending.approve(pattern, pattern_type)
                return True
        return False
    
    def deny_request(self, request_id: str):
        """Deny a pending request."""
        with self._pending_lock:
            pending = self.pending_approvals.get(request_id)
            if pending:
                pending.deny()
                return True
        return False
    
    def get_pending_requests(self) -> list[str]:
        """Get list of pending request IDs."""
        with self._pending_lock:
            return list(self.pending_approvals.keys())


# Global addon instance
gateway = AllowlistGateway()


# =============================================================================
# Embedded Control API
# Runs in the SAME process as mitmproxy to share state
# =============================================================================

from http.server import HTTPServer, BaseHTTPRequestHandler
import threading


class ControlHandler(BaseHTTPRequestHandler):
    """HTTP handler for gateway control commands."""
    
    def log_message(self, format, *args):
        """Suppress logging."""
        pass
    
    def _send_json(self, data: dict, status: int = 200):
        """Send JSON response."""
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))
    
    def do_OPTIONS(self):
        """Handle CORS preflight."""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
    
    def do_GET(self):
        """Handle GET requests."""
        if self.path == "/health":
            self._send_json({"status": "ok"})
        elif self.path == "/status":
            self._send_json({
                "status": "ok",
                "exact_patterns": len(gateway.exact_patterns),
                "wildcard_patterns": len(gateway.wildcard_patterns),
                "regex_patterns": len(gateway.regex_patterns),
                "pending_requests": len(gateway.pending_approvals),
                "app_id": gateway.app_id,
                "unknown_action": gateway.unknown_action,
            })
        elif self.path == "/pending":
            pending_ids = gateway.get_pending_requests()
            self._send_json({
                "pending": pending_ids,
                "count": len(pending_ids),
            })
        elif self.path == "/allowlist":
            self._send_json({
                "exact": gateway.exact_patterns,
                "wildcard": gateway.wildcard_patterns,
                "regex_count": len(gateway.regex_patterns),
            })
        else:
            self._send_json({"error": "Not found"}, 404)
    
    def do_POST(self):
        """Handle POST requests."""
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8")
        
        try:
            data = json.loads(body) if body else {}
        except json.JSONDecodeError:
            self._send_json({"error": "Invalid JSON"}, 400)
            return
        
        if self.path == "/add_pattern":
            pattern = data.get("pattern")
            pattern_type = data.get("pattern_type", "exact")
            if not pattern:
                self._send_json({"error": "pattern required"}, 400)
                return
            success = gateway.add_pattern(pattern, pattern_type)
            if success:
                self._send_json({"status": "ok", "pattern": pattern})
            else:
                self._send_json({"error": "Failed to add pattern"}, 500)
        elif self.path == "/approve":
            request_id = data.get("request_id")
            pattern = data.get("pattern")
            pattern_type = data.get("pattern_type", "exact")
            if not request_id:
                self._send_json({"error": "request_id required"}, 400)
                return
            success = gateway.approve_request(request_id, pattern, pattern_type)
            if success:
                logger.info(f"Approved request {request_id}")
                self._send_json({"status": "ok"})
            else:
                self._send_json({"error": "Request not found or already processed"}, 404)
        elif self.path == "/deny":
            request_id = data.get("request_id")
            if not request_id:
                self._send_json({"error": "request_id required"}, 400)
                return
            success = gateway.deny_request(request_id)
            if success:
                logger.info(f"Denied request {request_id}")
                self._send_json({"status": "ok"})
            else:
                self._send_json({"error": "Request not found or already processed"}, 404)
        else:
            self._send_json({"error": "Not found"}, 404)


def start_control_server(port: int = 8081):
    """Start the control API server in a background thread."""
    server = HTTPServer(("0.0.0.0", port), ControlHandler)
    logger.info(f"Control API listening on port {port}")
    server.serve_forever()


# Start control server when mitmproxy loads the addon
control_thread = threading.Thread(target=start_control_server, daemon=True)
control_thread.start()


addons = [gateway]
