"""ADK Playground package."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Add parent directory to path so we can import backend
_package_dir = Path(__file__).parent
_parent_dir = _package_dir.parent
# Add both parent and backend directory to path
if str(_parent_dir) not in sys.path:
    sys.path.insert(0, str(_parent_dir))
_backend_dir = _parent_dir / "backend"
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))


def main():
    """Main entry point for adk-playground."""
    import uvicorn
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="ADK Playground - Web UI for building and testing Google ADK agents")
    parser.add_argument(
        "--projects-dir",
        type=str,
        help="Directory for storing projects (default: ~/.adk-playground/projects)",
        default=None,
    )
    parser.add_argument(
        "--mcp-config",
        type=str,
        help="Path to MCP servers configuration file (default: ~/.adk-playground/mcp.json)",
        default=None,
    )
    parser.add_argument(
        "--port",
        type=int,
        help="Server port (default: 8080, or ADK_PLAYGROUND_PORT env var)",
        default=None,
    )
    parser.add_argument(
        "--host",
        type=str,
        help="Server host (default: 0.0.0.0, or ADK_PLAYGROUND_HOST env var)",
        default=None,
    )
    parser.add_argument(
        "--mode",
        type=str,
        choices=["dev", "production"],
        help="Run mode: dev (separate frontend server) or production (serves built frontend, default)",
        default=None,
    )
    
    args = parser.parse_args()
    
    # Set environment variables from command line arguments (if provided)
    # These will be picked up by backend/main.py
    if args.projects_dir:
        os.environ["ADK_PLAYGROUND_PROJECTS_DIR"] = args.projects_dir
    if args.mcp_config:
        os.environ["ADK_PLAYGROUND_MCP_CONFIG"] = args.mcp_config
    if args.port:
        os.environ["ADK_PLAYGROUND_PORT"] = str(args.port)
    if args.host:
        os.environ["ADK_PLAYGROUND_HOST"] = args.host
    if args.mode:
        os.environ["ADK_PLAYGROUND_MODE"] = args.mode
    
    # Import after path setup and environment variables are set
    from backend.main import app
    
    # Get port from environment or default to 8080
    port = int(os.environ.get("ADK_PLAYGROUND_PORT", "8080"))
    host = os.environ.get("ADK_PLAYGROUND_HOST", "0.0.0.0")
    
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()

