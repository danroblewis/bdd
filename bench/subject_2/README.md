# ADK Playground

A web-based UI for building and testing Google ADK (Agent Development Kit) agents.

## Installation

### Prerequisites

- Python 3.10 or higher (Python 3.11+ recommended)
- Node.js 18+ and npm (for frontend)
- `uv` package manager (recommended) or `pip`

### Install with uvx

The easiest way to run ADK Playground is using `uvx`:

```bash
# Install and run directly from GitHub (production mode)
# Note: The built frontend is included in the repository
uvx --from git+https://github.com/danroblewis/adk-playground.git adk-playground
```

Or if you've cloned the repository:

```bash
# Clone the repository
git clone https://github.com/danroblewis/adk-playground.git
cd adk-playground

# Run with uvx (production mode - uses built frontend from repo)
ADK_PLAYGROUND_MODE=production uvx --from . adk-playground
```

### Install from Source

1. **Clone the repository:**
```bash
   git clone https://github.com/danroblewis/adk-playground.git
   cd adk-playground
```

2. **Install dependencies:**

   **Option A: Using `uv` (recommended)**
```bash
   uv sync
```

   **Option B: Using pip**
```bash
python3 -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -e .
   ```

3. **Install frontend dependencies:**
   ```bash
cd frontend
npm install
cd ..
```

4. **Build the frontend (for production mode):**
   ```bash
   ./build.sh
   ```

## Usage

### Running with uvx

**Production mode** (single server - recommended for uvx):
```bash
# The built frontend is included in the repository, so no build step needed
ADK_PLAYGROUND_MODE=production uvx --from git+https://github.com/danroblewis/adk-playground.git adk-playground
```

Then access the UI at `http://localhost:8080`

**Development mode** (if you've cloned the repo and want hot reload):
```bash
# Terminal 1: Start backend
uvx --from git+https://github.com/danroblewis/adk-playground.git adk-playground

# Terminal 2: Start frontend dev server (requires cloned repo)
cd frontend && npm run dev
```

Then access the UI at `http://localhost:3000`

### Running from Source

**Using `uv run`:**
```bash
# Development mode
uv run python -m backend

# Production mode
ADK_PLAYGROUND_MODE=production uv run python -m backend
```

**Using virtual environment:**
```bash
source .venv/bin/activate
cd backend
uvicorn main:app --port 8080 --host 0.0.0.0
```

### Configuration

**Environment Variables:**

**Environment Variables:**
- `ADK_PLAYGROUND_PORT` - Server port (default: `8080`)
- `ADK_PLAYGROUND_HOST` - Server host (default: `0.0.0.0`)
- `ADK_PLAYGROUND_MODE` - Run mode: `dev` or `production` (default: `production`)
- `ADK_PLAYGROUND_PROJECTS_DIR` - Projects directory (default: `~/.adk-playground/projects`)
- `ADK_PLAYGROUND_MCP_CONFIG` - MCP servers config file (default: `~/.adk-playground/mcp.json`)

**Command Line Arguments:**
- `--projects-dir PATH` - Directory for storing projects
- `--mcp-config PATH` - Path to MCP servers configuration file
- `--port PORT` - Server port
- `--host HOST` - Server host
- `--mode {dev,production}` - Run mode

**Example:**
```bash
ADK_PLAYGROUND_PORT=8081 ADK_PLAYGROUND_HOST=127.0.0.1 uvx --from git+https://github.com/danroblewis/adk-playground.git adk-playground
```

## Features

- Visual agent builder with YAML configuration
- Real-time agent execution and event monitoring
- Code generation from agent configurations
- MCP server support
- Custom tool creation
- Session management with filesystem storage
- Memory and artifact services

## Requirements

- `google-adk` package (install from [adk-python](https://github.com/google/adk-python) or PyPI if available)

## License

See LICENSE file for details.

## Repository

https://github.com/danroblewis/adk-playground
