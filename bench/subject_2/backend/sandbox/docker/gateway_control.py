"""
Control API for the mitmproxy gateway.

Runs alongside mitmproxy and provides HTTP endpoints for:
1. Adding patterns to the allowlist
2. Approving/denying pending requests
3. Health checks
4. Getting gateway status
"""

from __future__ import annotations

import json
import logging
import os
from http.server import HTTPServer, BaseHTTPRequestHandler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gateway_control")


class ControlHandler(BaseHTTPRequestHandler):
    """HTTP handler for gateway control commands."""
    
    def log_message(self, format, *args):
        """Override to use logger."""
        logger.debug(f"{self.address_string()} - {format % args}")
    
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
            self._handle_status()
        elif self.path == "/pending":
            self._handle_pending()
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
            self._handle_add_pattern(data)
        elif self.path == "/approve":
            self._handle_approve(data)
        elif self.path == "/deny":
            self._handle_deny(data)
        else:
            self._send_json({"error": "Not found"}, 404)
    
    def _handle_status(self):
        """Get gateway status."""
        try:
            from gateway_addon import gateway
            
            self._send_json({
                "status": "ok",
                "exact_patterns": len(gateway.exact_patterns),
                "wildcard_patterns": len(gateway.wildcard_patterns),
                "regex_patterns": len(gateway.regex_patterns),
                "pending_requests": len(gateway.pending_approvals),
                "app_id": gateway.app_id,
                "unknown_action": gateway.unknown_action,
            })
        except Exception as e:
            self._send_json({"error": str(e)}, 500)
    
    def _handle_pending(self):
        """Get list of pending requests."""
        try:
            from gateway_addon import gateway
            
            pending_ids = gateway.get_pending_requests()
            self._send_json({
                "pending": pending_ids,
                "count": len(pending_ids),
            })
        except Exception as e:
            self._send_json({"error": str(e)}, 500)
    
    def _handle_add_pattern(self, data: dict):
        """Add a pattern to the allowlist."""
        pattern = data.get("pattern")
        pattern_type = data.get("pattern_type", "exact")
        
        if not pattern:
            self._send_json({"error": "pattern required"}, 400)
            return
        
        try:
            from gateway_addon import gateway
            
            success = gateway.add_pattern(pattern, pattern_type)
            if success:
                self._send_json({"status": "ok", "pattern": pattern})
            else:
                self._send_json({"error": "Failed to add pattern"}, 500)
        except Exception as e:
            self._send_json({"error": str(e)}, 500)
    
    def _handle_approve(self, data: dict):
        """Approve a pending request."""
        request_id = data.get("request_id")
        pattern = data.get("pattern")
        pattern_type = data.get("pattern_type", "exact")
        
        if not request_id:
            self._send_json({"error": "request_id required"}, 400)
            return
        
        try:
            from gateway_addon import gateway
            
            success = gateway.approve_request(request_id, pattern, pattern_type)
            if success:
                logger.info(f"Approved request {request_id}")
                self._send_json({"status": "ok"})
            else:
                self._send_json({"error": "Request not found or already processed"}, 404)
        except Exception as e:
            self._send_json({"error": str(e)}, 500)
    
    def _handle_deny(self, data: dict):
        """Deny a pending request."""
        request_id = data.get("request_id")
        
        if not request_id:
            self._send_json({"error": "request_id required"}, 400)
            return
        
        try:
            from gateway_addon import gateway
            
            success = gateway.deny_request(request_id)
            if success:
                logger.info(f"Denied request {request_id}")
                self._send_json({"status": "ok"})
            else:
                self._send_json({"error": "Request not found or already processed"}, 404)
        except Exception as e:
            self._send_json({"error": str(e)}, 500)


def main():
    """Run the control API server."""
    port = int(os.environ.get("CONTROL_PORT", "8081"))
    
    server = HTTPServer(("0.0.0.0", port), ControlHandler)
    logger.info(f"Gateway control API listening on port {port}")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
