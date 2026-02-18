"""Root-level entry point for ADK Playground."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Add backend directory to path so relative imports in main.py work
_backend_dir = Path(__file__).parent / "backend"
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))


def main():
    """Main entry point for adk-playground."""
    import uvicorn
    # Import after path setup - use relative import since we're in backend/
    from main import app
    
    # Get port from environment or default to 8080
    port = int(os.environ.get("ADK_PLAYGROUND_PORT", "8080"))
    host = os.environ.get("ADK_PLAYGROUND_HOST", "0.0.0.0")
    
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()

