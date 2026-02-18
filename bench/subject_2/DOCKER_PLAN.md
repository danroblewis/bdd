# Docker Sandbox Plan

This document outlines the plan for running ADK agents in isolated Docker containers with network monitoring and interactive approval.

## Overview

Run agents in a sandboxed Docker environment where:
- The sandbox is **App-scoped**: one sandbox per App, shared by all Agents in the App
- Agent code runs in an isolated container with **no direct internet access**
- **MCP servers run inside the sandbox** alongside the agent (not on host)
- All network traffic is routed through a **mitmproxy gateway**
- Users can **monitor all network requests** in real-time
- Unknown domains trigger an **interactive approval dialog** with sound notification
- Approved domains support **wildcard and regex patterns** for flexible matching
- Allowlist is **persisted in project config** and loaded when project opens

### Why MCP Servers Must Run in the Sandbox

MCP (Model Context Protocol) servers are external tools that agents can invoke. If MCP servers ran on the host machine while the agent runs in a sandbox:

1. **Security bypass**: A malicious agent could instruct an MCP server to make network requests on its behalf, completely bypassing the proxy and allowlist
2. **Data exfiltration**: MCP servers could leak sensitive workspace data to arbitrary endpoints
3. **Host access**: MCP servers running on host have access to host filesystem, environment variables, and credentials

By running MCP servers inside the same sandboxed Docker network, all their network traffic is also routed through mitmproxy, ensuring complete network visibility and control.

### App-Scoped Sandbox

The Docker sandbox is scoped at the **App level**, not the Agent level:

- **One sandbox per App**: All Agents defined in the App share the same sandbox environment
- **Shared allowlist**: Network allowlist applies to all Agents and MCP servers in the App
- **Shared MCP servers**: MCP servers are started once and available to all Agents
- **Consistent security**: No Agent can bypass the sandbox by delegating to another Agent

This matches the ADK App model where an App contains a `root_agent` (which may have sub-agents) and shared configuration like plugins and MCP servers.

### Allowlist Persistence

The network allowlist is persisted in the project configuration and loaded when the sandbox starts:

**Storage location:** Project YAML file (e.g., `app.yaml` or `sandbox.yaml`)

```yaml
# In project config (app.yaml)
sandbox:
  enabled: true
  network_allowlist:
    # Auto-populated (read-only in config, managed by system)
    auto:
      - generativelanguage.googleapis.com  # Gemini API
      - api.anthropic.com                  # Anthropic API
      - api.openai.com                     # OpenAI API
      - api.github.com                     # From MCP: github
    
    # User-defined patterns (editable)
    user:
      - pattern: "*.example.com/*"
        added: "2025-01-15T10:30:00Z"
        source: "approved during run"
      - pattern: "api.weather.com"
        added: "2025-01-14T08:00:00Z"
        source: "manually added"
      - pattern: "regex:.*\\.internal\\.company\\.com"
        added: "2025-01-13T14:00:00Z"
        source: "manually added"
    
    # Session-only approvals (not persisted, for reference)
    # These are shown in UI but not saved unless user checks "Save to project"
```

**Persistence flow:**

1. **Project load**: Backend reads `sandbox.network_allowlist` from project YAML
2. **Sandbox start**: Allowlist is sent to gateway container via environment or config file
3. **Runtime approval**: User approves a domain with pattern
4. **Save decision**: If "Save to project" checked, pattern is appended to `user` list in YAML
5. **Project save**: Updated allowlist is written back to project YAML

**Sending allowlist to container:**

```python
# backend/sandbox/docker_manager.py

async def start_sandbox(app_config: AppConfig) -> SandboxInstance:
    """Start the App-scoped sandbox with persisted allowlist."""
    
    # Load allowlist from project config
    allowlist = load_allowlist_from_project(app_config.project_path)
    
    # Combine auto + user patterns
    all_patterns = allowlist.auto + [p.pattern for p in allowlist.user]
    
    # Start gateway with allowlist
    gateway = await docker.containers.run(
        image="sandbox-gateway",
        environment={
            "ALLOWLIST_PATTERNS": json.dumps(all_patterns),
        },
        # Or mount as config file:
        volumes={
            allowlist_file: {"bind": "/etc/allowlist.json", "mode": "ro"},
        },
        ...
    )
```

## Architecture

```
┌───────────────────────────────────────────────────────────────────────────────────────┐
│  HOST MACHINE                                                                         │
│                                                                                       │
│  ┌─────────────────────────────────────────────────────────────────────────────┐     │
│  │  ADK Playground Backend (FastAPI)                            :8080          │     │
│  │  - POST /api/run-sandboxed - Start sandboxed run                            │     │
│  │  - WebSocket /ws/sandbox/{session} - Stream events                          │     │
│  │  - POST /api/sandbox/{session}/approval - Forward user decisions            │     │
│  └─────────────────────────────────────────────────────────────────────────────┘     │
│                                       │                                               │
│                            Docker API │ (docker-py)                                   │
│                                       ▼                                               │
│  ┌─────────────────────────────────────────────────────────────────────────────────┐ │
│  │  DOCKER                                                                         │ │
│  │                                                                                 │ │
│  │  ┌─── sandbox-network (internal, no internet) ───────────────────────────────┐ │ │
│  │  │                                                                            │ │ │
│  │  │  ┌────────────────────────┐  ┌────────────────────────┐                   │ │ │
│  │  │  │  agent-runner          │  │  mcp-server-1          │                   │ │ │
│  │  │  │                        │  │  (e.g., filesystem)    │                   │ │ │
│  │  │  │  - Runs ADK agent      │  │                        │                   │ │ │
│  │  │  │  - HTTP API :5000      │  │  - stdio/SSE transport │                   │ │ │
│  │  │  │  - WebSocket streaming │  │  - HTTP_PROXY enforced │                   │ │ │
│  │  │  │  - No direct internet  │  │  - /workspace mounted  │                   │ │ │
│  │  │  │                        │  │                        │                   │ │ │
│  │  │  │  HTTP_PROXY=gateway    │  └────────────────────────┘                   │ │ │
│  │  │  │                        │                                               │ │ │
│  │  │  │  Connects to MCP       │  ┌────────────────────────┐                   │ │ │
│  │  │  │  servers via stdio ────┼─▶│  mcp-server-2          │                   │ │ │
│  │  │  │  or localhost SSE      │  │  (e.g., github)        │                   │ │ │
│  │  │  │                        │  │                        │                   │ │ │
│  │  │  └────────────────────────┘  │  - HTTP_PROXY enforced │                   │ │ │
│  │  │           │                  │  - All API calls go    │                   │ │ │
│  │  │           │                  │    through gateway     │                   │ │ │
│  │  │           ▼                  └────────────────────────┘                   │ │ │
│  │  │  ┌─────────────────────────────────────────────────────────────────────┐  │ │ │
│  │  │  │  mitmproxy-gateway                                                  │  │ │ │
│  │  │  │                                                                     │  │ │ │
│  │  │  │  - mitmproxy with addon           - Allowlist checking              │  │ │ │
│  │  │  │  - Request interception           - Webhooks to host                │  │ │ │
│  │  │  │  - :8080 (proxy)                  - :8081 (control API)             │──┼─┼──▶ Internet
│  │  │  │                                                                     │  │ │ │
│  │  │  │  ALL containers in sandbox-network route through this gateway       │  │ │ │
│  │  │  └─────────────────────────────────────────────────────────────────────┘  │ │ │
│  │  └───────────────────────────────────────────────────────────────────────────┘ │ │
│  └─────────────────────────────────────────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────────────────────────────────────────┘
```

**Key points:**
- Agent and all MCP servers share the same isolated `sandbox-network`
- Agent communicates with MCP servers via stdio (subprocess) or localhost SSE
- All containers have `HTTP_PROXY` set to route through the gateway
- MCP servers' network requests (e.g., GitHub API calls) go through mitmproxy
- User sees and approves ALL network traffic, including from MCP servers

## Components

### 1. Gateway Container (mitmproxy)

**Dockerfile.gateway**
```dockerfile
FROM mitmproxy/mitmproxy:latest

COPY gateway_addon.py /app/
COPY gateway_control.py /app/

# Run mitmproxy with our addon + control API
CMD ["sh", "-c", "mitmdump -s /app/gateway_addon.py & python /app/gateway_control.py"]

EXPOSE 8080 8081
```

**Features:**
- Intercepts all HTTP/HTTPS traffic from agent container
- Checks requests against allowlist
- Pauses unknown requests and notifies host for approval
- Streams all network activity to host via webhooks
- Control API for receiving approval decisions

**Allowlist sources (auto-populated):**
- LLM providers: `generativelanguage.googleapis.com`, `api.anthropic.com`, `api.openai.com`, `api.groq.com`
- Project config: `app.model.api_base`, LiteLLM config URLs
- MCP server APIs: Known endpoints for configured MCP servers (e.g., `api.github.com` for GitHub MCP)
- User-added: Manually configured domains/patterns (persisted in project YAML)
- Session-approved: Domains approved during current run (optionally persisted)

**Pattern matching support:**
The allowlist supports wildcard and regex patterns for flexible domain matching:

| Pattern Type | Syntax | Example | Matches |
|--------------|--------|---------|---------|
| Exact domain | `domain.com` | `api.github.com` | Only `api.github.com` |
| Wildcard subdomain | `*.domain.com` | `*.googleapis.com` | `storage.googleapis.com`, `vision.googleapis.com` |
| Wildcard path | `domain.com/*` | `api.example.com/v1/*` | Any path under `/v1/` |
| Full wildcard | `*.domain.com/*` | `*.example.com/*` | Any subdomain, any path |
| Regex (advanced) | `regex:pattern` | `regex:.*\.example\.(com\|org)` | `api.example.com`, `cdn.example.org` |

**Note on MCP servers:**
MCP servers run inside the sandbox, so their network requests are also subject to the allowlist. For example:
- `mcp-server-github` → auto-allows `api.github.com`
- `mcp-server-fetch` → NO auto-allow (user must approve each domain)
- `mcp-server-filesystem` → No network access needed
- Custom MCP servers → User must configure allowed domains

### 2. MCP Server Containers

MCP servers must run inside the sandbox to prevent them from bypassing network controls. There are two approaches based on MCP transport type:

#### Approach A: Sidecar Containers (for HTTP/SSE MCP servers)

Each MCP server runs as a separate container in the sandbox network.

**Dockerfile.mcp-base**
```dockerfile
FROM python:3.11-slim

# Install common MCP dependencies
RUN pip install mcp httpx aiohttp

# Enforce proxy for all network requests
ENV HTTP_PROXY=http://gateway:8080
ENV HTTPS_PROXY=http://gateway:8080
ENV NO_PROXY=localhost,127.0.0.1,agent-runner

WORKDIR /app
```

**Dynamic container creation:**
```python
# backend/sandbox/mcp_manager.py

async def create_mcp_container(mcp_config: MCPServerConfig) -> Container:
    """Create a container for an MCP server based on its config."""
    
    if mcp_config.transport == "sse":
        # SSE servers expose an HTTP endpoint
        return await docker.containers.run(
            image="mcp-base",
            command=mcp_config.command,
            environment={
                "HTTP_PROXY": "http://gateway:8080",
                "HTTPS_PROXY": "http://gateway:8080",
                **mcp_config.env,
            },
            network="sandbox-network",
            volumes={workspace_path: {"bind": "/workspace", "mode": "ro"}},
            name=f"mcp-{mcp_config.name}-{session_id}",
        )
    
    elif mcp_config.transport == "stdio":
        # stdio servers are spawned by agent-runner (see below)
        return None
```

#### Approach B: Embedded in Agent Container (for stdio MCP servers)

Stdio-based MCP servers are spawned as subprocesses within the agent-runner container. The agent container image includes common MCP server packages.

**Agent container with MCP support:**
```dockerfile
FROM python:3.11-slim

# ADK and core dependencies
RUN pip install google-adk aiohttp

# Common MCP servers (pre-installed for convenience)
RUN pip install \
    mcp-server-filesystem \
    mcp-server-fetch \
    mcp-server-time \
    mcp-server-sqlite

# For custom MCP servers, they're installed at runtime from project requirements
COPY agent_runner.py /app/
COPY mcp_spawner.py /app/

WORKDIR /app
EXPOSE 5000

# Enforce proxy for ALL processes (including MCP subprocesses)
ENV HTTP_PROXY=http://gateway:8080
ENV HTTPS_PROXY=http://gateway:8080
ENV NO_PROXY=localhost,127.0.0.1

CMD ["python", "agent_runner.py"]
```

**MCP spawner within agent container:**
```python
# mcp_spawner.py - Runs inside agent container

import subprocess
import os

def spawn_mcp_server(command: list[str], env: dict) -> subprocess.Popen:
    """Spawn an MCP server as a subprocess with proxy enforced."""
    
    # Merge proxy settings into environment
    full_env = {
        **os.environ,  # Inherits HTTP_PROXY, HTTPS_PROXY from container
        **env,
    }
    
    return subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=full_env,
    )
```

#### MCP Server Network Traffic Visibility

All MCP server network requests appear in the Network Monitor, tagged with the MCP server name:

```
│  ✓ GET  api.github.com/repos/...    200   120ms   [mcp:github]     │
│  ✓ POST api.openai.com/v1/...       200   450ms   [mcp:openai]     │
│  ⏳ GET  unknown-api.com/data       PENDING       [mcp:custom]     │
```

### 3. Agent Runner Container

**Dockerfile.agent**
```dockerfile
FROM python:3.11-slim

RUN pip install google-adk aiohttp

# Common MCP servers (for stdio transport)
RUN pip install \
    mcp-server-filesystem \
    mcp-server-fetch \
    mcp-server-time \
    mcp-server-sqlite

COPY agent_runner.py /app/
COPY mcp_spawner.py /app/

WORKDIR /app
EXPOSE 5000

# Enforce proxy for all processes
ENV HTTP_PROXY=http://gateway:8080
ENV HTTPS_PROXY=http://gateway:8080
ENV NO_PROXY=localhost,127.0.0.1

CMD ["python", "agent_runner.py"]
```

**Features:**
- Loads project code from mounted `/workspace` volume
- Runs ADK agent with Runner
- Spawns stdio MCP servers as subprocesses (with proxy enforced)
- Connects to SSE MCP servers via sandbox network
- Exposes WebSocket API for control and event streaming
- All network traffic goes through HTTP_PROXY (gateway)

### 4. Backend Integration

**New files:**
- `backend/sandbox/docker_manager.py` - App-scoped Docker container lifecycle
- `backend/sandbox/mcp_manager.py` - MCP server container orchestration
- `backend/sandbox/network_monitor.py` - Track and stream network events with source attribution
- `backend/sandbox/models.py` - Data models for sandbox configuration and allowlist
- `backend/sandbox/allowlist.py` - Pattern matching engine (wildcard, regex)
- `backend/sandbox/allowlist_persistence.py` - Load/save allowlist from project YAML
- `backend/sandbox/known_mcp_servers.py` - Registry of MCP servers and their network requirements

**New endpoints:**
- `POST /api/run-sandboxed` - Start App sandbox (shared by all agents)
- `POST /api/sandbox/{app_id}/approval` - Forward approval decision with pattern
- `GET /api/sandbox/{app_id}/network` - Get network activity history with source info
- `GET /api/sandbox/{app_id}/mcp-status` - Get status of MCP server containers
- `GET /api/sandbox/{app_id}/allowlist` - Get current allowlist (auto + user patterns)
- `POST /api/sandbox/{app_id}/allowlist` - Add pattern to allowlist
- `DELETE /api/sandbox/{app_id}/allowlist/{pattern_id}` - Remove user pattern
- `POST /api/sandbox/{app_id}/allowlist/persist` - Save allowlist to project YAML
- WebSocket `/ws/sandbox/{app_id}` - Stream agent + MCP + network events

### 5. Frontend Components

**New components:**
- `NetworkMonitor.tsx` - Real-time network activity display with source column
- `NetworkApprovalDialog.tsx` - Interactive approval popup with pattern editor
- `PatternSelector.tsx` - Dropdown with pattern suggestions + custom option
- `PatternEditor.tsx` - Custom pattern input with wildcard/regex toggle and test preview
- `AllowlistManager.tsx` - View/edit/delete allowlist patterns
- `SandboxSettings.tsx` - Configuration UI for App-scoped sandbox

**Features:**
- Real-time network request list (source, method, URL, matched pattern, status, timing)
- Filter: show/hide LLM API calls, filter by source
- Approval dialog with pattern selector and suggestions
- Pattern editor with live test/preview against sample URLs
- "Save to project" checkbox for persisting patterns
- Options: Deny, Allow Once, Allow Pattern (with editor)
- 30-second timeout with visual countdown
- Allowlist manager showing pattern type, source, and date added

## User Flow

1. User enables "Docker Sandbox" in App settings
2. User configures allowlist (or uses defaults)
3. User reviews MCP servers that will run in sandbox (UI shows network requirements)
4. User clicks "Run" 
5. Backend creates Docker containers:
   - Gateway container (mitmproxy)
   - Agent runner container
   - MCP server containers (one per SSE server, stdio servers spawn in agent container)
6. Agent runs, events stream to frontend
7. When agent or MCP server makes network request:
   - Request goes through mitmproxy gateway
   - Source (agent or mcp:<name>) is logged
   - If domain in allowlist → forward immediately, show in monitor
   - If domain not in allowlist → pause, show approval dialog with source info
8. User approves/denies (sees which component is making the request)
9. Request continues or is blocked
10. Run completes, all containers cleaned up

## Configuration UI

```
┌───────────────────────────────────────────────────────────────────────┐
│  🐳 Docker Sandbox Settings                                           │
├───────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  [✓] Enable Docker sandbox for agent runs                             │
│                                                                       │
│  ─────────────────────────────────────────────────────────────────    │
│  📦 MCP Servers                                                       │
│  ─────────────────────────────────────────────────────────────────    │
│                                                                       │
│  MCP servers will run INSIDE the sandbox. Their network requests      │
│  are subject to the same allowlist as the agent.                      │
│                                                                       │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │  ✓ filesystem (stdio)     Local only, no network access         │ │
│  │  ✓ time (stdio)           Local only, no network access         │ │
│  │  ✓ github (stdio)         → auto-allows: api.github.com         │ │
│  │  ⚠️ fetch (stdio)          → CAN ACCESS ANY URL (needs approval) │ │
│  │  ✓ custom-api (sse)       → auto-allows: api.example.com        │ │
│  └─────────────────────────────────────────────────────────────────┘ │
│                                                                       │
│  ─────────────────────────────────────────────────────────────────    │
│  🌐 Network Allowlist (persisted in project)                          │
│  ─────────────────────────────────────────────────────────────────    │
│                                                                       │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │  Auto-populated (read-only):                                    │ │
│  │  ✓ generativelanguage.googleapis.com    [exact]    LLM          │ │
│  │  ✓ api.anthropic.com                    [exact]    LLM          │ │
│  │  ✓ api.openai.com                       [exact]    LLM          │ │
│  │  ✓ api.groq.com                         [exact]    LLM          │ │
│  │  ✓ api.github.com                       [exact]    mcp:github   │ │
│  │  ✓ localhost:11434                      [exact]    LiteLLM      │ │
│  │  ─────────────────────────────────────────────────────────────  │ │
│  │  User-defined (editable, saved to project):                     │ │
│  │  ✓ api.custom-service.com               [exact]    [✏️] [🗑️]    │ │
│  │  ✓ *.example.com/*                      [wildcard] [✏️] [🗑️]    │ │
│  │  ✓ regex:.*\.internal\.corp\.com        [regex]    [✏️] [🗑️]    │ │
│  │                                                                 │ │
│  │    [+ Add pattern...]                                           │ │
│  └─────────────────────────────────────────────────────────────────┘ │
│                                                                       │
│  Pattern syntax:                                                      │
│  • Exact: api.example.com (matches only that domain)                  │
│  • Wildcard: *.example.com/* (matches subdomains and paths)           │
│  • Regex: regex:pattern (for advanced matching)                       │
│                                                                       │
│  When unknown domain requested:                                       │
│  (•) Ask for approval (with sound notification)                       │
│  ( ) Auto-deny all unknown                                            │
│  ( ) Auto-allow all (⚠️ defeats sandbox purpose)                      │
│                                                                       │
│  Timeout for approval: [30] seconds                                   │
│                                                                       │
│  ─────────────────────────────────────────────────────────────────    │
│  ⚙️ Resource Limits                                                    │
│  ─────────────────────────────────────────────────────────────────    │
│                                                                       │
│  Agent container:    Memory: [512] MB   CPU: [1.0] cores             │
│  Per MCP container:  Memory: [256] MB   CPU: [0.5] cores             │
│  Total run timeout:  [300] seconds                                    │
│                                                                       │
└───────────────────────────────────────────────────────────────────────┘
```

## Network Monitor UI

```
┌───────────────────────────────────────────────────────────────────────────┐
│  🌐 Network Activity                                    [Filter: All ▾]   │
├───────────────────────────────────────────────────────────────────────────┤
│  Source        Method  URL                          Status  Time   Size  │
│  ─────────────────────────────────────────────────────────────────────── │
│  mcp:github    POST    api.github.com/graphql       200     45ms   1.2KB │
│  mcp:fetch     GET     api.weather.com/v1/forecast  200     120ms  3.4KB │
│  mcp:custom    GET     api.unknown.com/data         ⏳ PENDING (asking)  │
│  agent         GET     malicious-site.com/exfil     🚫 DENIED            │
│  ─────────────────────────────────────────────────────────────────────── │
│  agent         POST    generativelanguage.google... 200     890ms  12KB  │
├───────────────────────────────────────────────────────────────────────────┤
│  [ ] Show LLM API calls    [ ] Show by source    [Export HAR]            │
│  Requests: 5 | Allowed: 3 | Denied: 1 | Pending: 1                       │
│  Sources: agent (2) | mcp:github (1) | mcp:fetch (1) | mcp:custom (1)    │
└───────────────────────────────────────────────────────────────────────────┘
```

**Source attribution:**
- `agent` - Direct requests from the agent code
- `mcp:<name>` - Requests from a specific MCP server
- Attribution is tracked via X-Sandbox-Source header injected by the proxy

## Approval Dialog

```
┌───────────────────────────────────────────────────────────────────────┐
│  🔔 Network Request Approval                                          │
├───────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  MCP server "fetch" wants to connect to:                              │
│  (requested by agent "data_fetcher")                                  │
│                                                                       │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │  GET https://api.unknown.com/v1/data?query=test                 │ │
│  │  Headers: Authorization: Bearer ***                              │ │
│  └─────────────────────────────────────────────────────────────────┘ │
│                                                                       │
│  Allow pattern: [api.unknown.com                              ▾]     │
│                 ┌─────────────────────────────────────────────┐      │
│                 │  api.unknown.com          (exact domain)    │      │
│                 │  api.unknown.com/*        (domain + paths)  │      │
│                 │  *.unknown.com            (all subdomains)  │      │
│                 │  *.unknown.com/*          (full wildcard)   │      │
│                 │  [Custom pattern...]                        │      │
│                 └─────────────────────────────────────────────┘      │
│                                                                       │
│  [ ] Save to project (persists across sessions)                       │
│                                                                       │
│  [🚫 Deny]  [✓ Allow Once]  [✓ Allow Pattern]                        │
│                                                                       │
│  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━░░░░░░░░░  25s              │
└───────────────────────────────────────────────────────────────────────┘
```

**Custom pattern dialog (when "Custom pattern..." selected):**
```
┌───────────────────────────────────────────────────────────────────────┐
│  Custom Allow Pattern                                                 │
├───────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  Pattern: [*.unknown.com/api/v*                               ]      │
│                                                                       │
│  Pattern type:                                                        │
│  (•) Wildcard (* matches any characters)                              │
│  ( ) Regex (advanced)                                                 │
│                                                                       │
│  Test matches:                                                        │
│  ✓ api.unknown.com/api/v1/data     MATCHES                           │
│  ✓ cdn.unknown.com/api/v2/files    MATCHES                           │
│  ✗ api.unknown.com/other/path      NO MATCH                          │
│                                                                       │
│  [Cancel]  [Apply Pattern]                                            │
└───────────────────────────────────────────────────────────────────────┘
```

The dialog shows:
- **Source**: Which component made the request (agent or specific MCP server)
- **Context**: Which agent triggered the MCP tool call (for MCP requests)
- **Request details**: Method, URL, and sanitized headers
- **Pattern selector**: Dropdown with common patterns + custom option
- **Persistence checkbox**: Option to save the pattern to project config

## Implementation Phases

### Phase 1: Basic Docker Integration (App-Scoped Sandbox)
- [ ] Create Dockerfile.gateway with basic mitmproxy
- [ ] Create Dockerfile.agent with agent runner and MCP support
- [ ] Create Dockerfile.mcp-base for SSE MCP server containers
- [ ] Implement `SandboxManager` with App-scoped lifecycle
- [ ] Add `/api/run-sandboxed` endpoint (takes App ID, not Agent ID)
- [ ] Basic event streaming (no network monitoring yet)
- [ ] Ensure sandbox is shared across all Agents in App

### Phase 2: MCP Server Integration
- [ ] Implement `MCPContainerManager` for SSE-based MCP servers
- [ ] Implement `mcp_spawner.py` for stdio MCP servers in agent container
- [ ] Parse project's MCP config to determine which servers to start
- [ ] Configure MCP servers with HTTP_PROXY environment
- [ ] Test stdio and SSE transport modes work through proxy

### Phase 3: Allowlist Persistence & Pattern Matching
- [ ] Define YAML schema for `sandbox.network_allowlist` in project config
- [ ] Implement `NetworkAllowlist` and `AllowlistPattern` models
- [ ] Implement pattern matching: exact, wildcard, regex
- [ ] Load allowlist from project YAML on sandbox start
- [ ] Send allowlist to gateway container (env var or mounted file)
- [ ] Implement pattern matching in mitmproxy addon
- [ ] Add API endpoint to persist new patterns to project YAML

### Phase 4: Network Monitoring
- [ ] Implement mitmproxy addon for traffic capture
- [ ] Add source attribution (agent vs mcp:<name>) to requests
- [ ] Log which pattern matched each allowed request
- [ ] Add webhook to stream network events to host
- [ ] Create `NetworkMonitor.tsx` component with source column
- [ ] Display real-time network activity in Run panel

### Phase 5: Interactive Approval with Pattern Editor
- [ ] Implement request interception in mitmproxy addon
- [ ] Add approval webhook flow (gateway → host → frontend → host → gateway)
- [ ] Create `NetworkApprovalDialog.tsx` with pattern selector dropdown
- [ ] Add pattern suggestions (exact, *.domain, domain/*, full wildcard)
- [ ] Add custom pattern editor with wildcard/regex toggle
- [ ] Add pattern test/preview functionality
- [ ] Add "Save to project" checkbox for persistence
- [ ] Show MCP server name and triggering agent in approval dialog
- [ ] Add timeout handling

### Phase 6: Configuration UI
- [ ] Create `SandboxSettings.tsx` component
- [ ] Add MCP server sandbox status display
- [ ] Add allowlist management UI with pattern editor
- [ ] Show pattern type (exact/wildcard/regex) and source
- [ ] Allow editing/deleting user-defined patterns
- [ ] Auto-populate from project config (API bases, MCP server known domains)
- [ ] Warn about high-risk MCP servers (e.g., fetch) that can access any URL
- [ ] Persist all settings to project YAML on save

### Phase 7: Polish
- [ ] Export network log as HAR file with source attribution
- [ ] Resource limits (memory, CPU, timeout) per container type
- [ ] Handle MCP server container crashes gracefully
- [ ] Error handling and recovery
- [ ] Add pattern import/export functionality
- [ ] Documentation for MCP sandbox behavior and pattern syntax

## Data Models

```python
# backend/sandbox/models.py

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from enum import Enum
import re


class PatternType(Enum):
    EXACT = "exact"           # Exact domain match
    WILDCARD = "wildcard"     # Glob-style wildcards (* matches anything)
    REGEX = "regex"           # Full regex pattern


@dataclass
class AllowlistPattern:
    """A single pattern in the network allowlist."""
    pattern: str
    pattern_type: PatternType = PatternType.WILDCARD
    added_at: Optional[datetime] = None
    source: str = "user"  # "auto", "user", "mcp:<name>", "approved"
    
    def matches(self, url: str) -> bool:
        """Check if this pattern matches the given URL."""
        if self.pattern_type == PatternType.EXACT:
            return url == self.pattern or url.startswith(self.pattern + "/")
        
        elif self.pattern_type == PatternType.WILDCARD:
            # Convert glob pattern to regex
            regex = self.pattern.replace(".", r"\.")
            regex = regex.replace("*", ".*")
            return bool(re.match(f"^{regex}$", url))
        
        elif self.pattern_type == PatternType.REGEX:
            return bool(re.match(self.pattern, url))
        
        return False


@dataclass
class NetworkAllowlist:
    """Complete allowlist with auto and user-defined patterns."""
    auto: list[str] = field(default_factory=list)  # Auto-populated, not persisted
    user: list[AllowlistPattern] = field(default_factory=list)  # User-defined, persisted
    
    def all_patterns(self) -> list[AllowlistPattern]:
        """Get all patterns (auto converted to AllowlistPattern + user)."""
        auto_patterns = [
            AllowlistPattern(p, PatternType.EXACT, source="auto") 
            for p in self.auto
        ]
        return auto_patterns + self.user
    
    def matches(self, url: str) -> bool:
        """Check if any pattern matches the URL."""
        return any(p.matches(url) for p in self.all_patterns())
    
    def to_yaml_dict(self) -> dict:
        """Serialize user patterns for YAML storage."""
        return {
            "user": [
                {
                    "pattern": p.pattern,
                    "type": p.pattern_type.value,
                    "added": p.added_at.isoformat() if p.added_at else None,
                    "source": p.source,
                }
                for p in self.user
            ]
        }
    
    @classmethod
    def from_yaml_dict(cls, data: dict) -> "NetworkAllowlist":
        """Load from YAML dict."""
        user_patterns = []
        for p in data.get("user", []):
            user_patterns.append(AllowlistPattern(
                pattern=p["pattern"],
                pattern_type=PatternType(p.get("type", "wildcard")),
                added_at=datetime.fromisoformat(p["added"]) if p.get("added") else None,
                source=p.get("source", "user"),
            ))
        return cls(user=user_patterns)


@dataclass
class MCPServerSandboxConfig:
    """Configuration for an MCP server in the sandbox."""
    name: str
    transport: str  # "stdio" or "sse"
    command: list[str]
    env: dict[str, str] = field(default_factory=dict)
    allowed_domains: list[str] = field(default_factory=list)  # Known domains this MCP uses
    memory_limit_mb: int = 256
    cpu_limit: float = 0.5


@dataclass
class SandboxConfig:
    """App-scoped sandbox configuration (persisted in project YAML)."""
    enabled: bool = False
    allowlist: NetworkAllowlist = field(default_factory=NetworkAllowlist)
    unknown_action: str = "ask"  # ask, deny, allow
    approval_timeout: int = 30
    agent_memory_limit_mb: int = 512
    agent_cpu_limit: float = 1.0
    mcp_memory_limit_mb: int = 256  # Per MCP container
    mcp_cpu_limit: float = 0.5  # Per MCP container
    run_timeout: int = 300
    mcp_servers: list[MCPServerSandboxConfig] = field(default_factory=list)


@dataclass
class NetworkRequest:
    id: str
    timestamp: datetime
    method: str
    url: str
    host: str
    status: str  # pending, allowed, denied, completed, error
    source: str  # "agent" or "mcp:<server_name>"
    matched_pattern: Optional[str] = None  # Which pattern allowed this request
    source_agent: Optional[str] = None  # Which agent triggered the MCP call
    response_status: Optional[int] = None
    response_time_ms: Optional[float] = None
    response_size: Optional[int] = None
    is_llm_provider: bool = False


@dataclass
class MCPContainerStatus:
    """Runtime status of an MCP server container."""
    name: str
    container_id: str
    status: str  # "starting", "running", "stopped", "error"
    transport: str
    endpoint: Optional[str] = None  # For SSE: "http://mcp-github:8080"
    error: Optional[str] = None


@dataclass 
class ApprovalDecision:
    """User's decision when approving a network request."""
    request_id: str
    action: str  # "deny", "allow_once", "allow_pattern"
    pattern: Optional[str] = None  # The pattern to allow (if allow_pattern)
    pattern_type: PatternType = PatternType.WILDCARD
    persist: bool = False  # Save to project config
```

## Security Considerations

### Core Sandbox Security

1. **Container Isolation**: Agent and MCP containers have no direct internet access
2. **Proxy Enforcement**: All traffic from all containers goes through gateway (HTTP_PROXY)
3. **Allowlist Default**: Only LLM providers allowed by default
4. **User Consent**: Unknown domains require explicit approval
5. **Timeout**: Unapproved requests timeout after 30 seconds
6. **Resource Limits**: Memory, CPU, and time limits prevent abuse
7. **Read-only Code**: Project code mounted read-only
8. **No Host Access**: Containers cannot access host filesystem (except workspace)

### MCP-Specific Security

9. **MCP Sandboxing**: MCP servers run inside sandbox, not on host machine
10. **No Bypass via MCP**: MCP servers cannot be used to bypass network controls
11. **Source Attribution**: All network requests are tagged with their source (agent or mcp:<name>)
12. **Per-MCP Allowlists**: Each MCP server can have known domains pre-approved
13. **Dangerous MCP Warning**: UI warns about MCP servers like `fetch` that can access arbitrary URLs
14. **MCP Container Isolation**: Each SSE MCP server runs in its own container with separate resource limits
15. **Stdio Proxy Inheritance**: Stdio MCP servers inherit HTTP_PROXY from agent container

### Allowlist & Pattern Security

16. **Pattern Validation**: Regex patterns are validated before use to prevent ReDoS attacks
17. **Overly Broad Warning**: UI warns when patterns like `*` or `*.*` would allow all traffic
18. **Persistence Audit**: All user-defined patterns include timestamp and source for auditing
19. **Project-Scoped**: Allowlist is scoped to project, not global (each project has its own)
20. **Version Control**: Allowlist in YAML can be tracked in git for team review

### Attack Vectors Mitigated

| Attack | Mitigation |
|--------|------------|
| Agent exfiltrates data via HTTP | All requests go through proxy, unknown domains blocked |
| Agent uses MCP server to bypass proxy | MCP servers also run in sandbox with same proxy |
| MCP server reads host secrets | MCP runs in container, no host access |
| Agent spawns subprocess to bypass proxy | HTTP_PROXY env is inherited by all child processes |
| Agent uses DNS exfiltration | (Future) Consider DNS monitoring/blocking |
| Overly permissive patterns | UI warns about broad patterns, shows match count |
| Malicious regex patterns | Patterns validated, timeout on regex matching |

## Dependencies

- `docker` (Python SDK for Docker)
- `mitmproxy` (HTTP/HTTPS proxy)
- `aiohttp` (Async HTTP for control APIs)
- Docker Engine on host machine

## Known MCP Servers and Network Requirements

This table documents common MCP servers and their network access patterns for auto-allowlist configuration:

| MCP Server | Transport | Network Access | Auto-Allow Domains | Risk Level |
|------------|-----------|----------------|-------------------|------------|
| `filesystem` | stdio | None | (none) | Low |
| `time` | stdio | None | (none) | Low |
| `sqlite` | stdio | None | (none) | Low |
| `memory` | stdio | None | (none) | Low |
| `github` | stdio | GitHub API | `api.github.com`, `github.com` | Medium |
| `gitlab` | stdio | GitLab API | `gitlab.com` | Medium |
| `slack` | stdio | Slack API | `slack.com`, `api.slack.com` | Medium |
| `google-drive` | stdio | Google APIs | `*.googleapis.com` | Medium |
| `brave-search` | stdio | Brave API | `api.search.brave.com` | Medium |
| `fetch` | stdio | **Any URL** | (user approval required) | **High** |
| `puppeteer` | stdio | **Any URL** | (user approval required) | **High** |
| `browserbase` | stdio | **Any URL** | (user approval required) | **High** |

### Risk Levels

- **Low**: No network access, only local operations
- **Medium**: Accesses specific, known APIs that can be auto-allowed
- **High**: Can access arbitrary URLs, requires per-request approval

### Handling High-Risk MCP Servers

MCP servers like `fetch`, `puppeteer`, and `browserbase` are designed to access arbitrary URLs. For these:

1. **Cannot auto-allow**: No predefined allowlist makes sense
2. **Per-request approval**: Each URL access triggers approval dialog
3. **User warning**: Configuration UI shows warning about these servers
4. **Consider alternatives**: Suggest using more specific MCP servers when possible

## Notes

- This is a significant feature that adds complexity
- Requires Docker to be installed and running
- May not work on all platforms (especially Windows without WSL2)
- Consider making this opt-in and clearly marked as experimental
- Could be useful for enterprise deployments with security requirements
- MCP servers add container orchestration complexity but are essential for complete sandboxing
- Some MCP servers may need specific base images (e.g., Node.js for JS-based servers)

