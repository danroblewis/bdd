"""Docker container lifecycle manager for the sandbox.

This module manages the Docker containers for the App-scoped sandbox:
- Gateway container (mitmproxy)
- Agent runner container
- MCP server containers (for SSE transport)

Based on DOCKER_PLAN.md specification.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import (
    MCPContainerStatus,
    MCPServerSandboxConfig,
    NetworkAllowlist,
    VolumeMount,
    SandboxConfig,
    SandboxInstance,
    SandboxStatus,
)
from .mcp_manager import MCPContainerManager

# Import code generator for creating executable Python code
from backend.code_generator import generate_python_code
from backend.models import Project

logger = logging.getLogger(__name__)


def extract_storage_paths_from_project(project_config: Dict[str, Any]) -> List[VolumeMount]:
    """Extract filesystem paths from storage service URIs and create volume mounts.
    
    Checks session_service_uri, memory_service_uri, and artifact_service_uri for
    file:// and sqlite:// schemes and creates appropriate volume mounts.
    
    Args:
        project_config: Full project configuration dict
        
    Returns:
        List of VolumeMount objects for storage paths
    """
    mounts = []
    app = project_config.get("app", {})
    
    def expand_path(path_str: str) -> Optional[Path]:
        """Expand ~ and resolve path, return None if invalid."""
        if not path_str:
            return None
        try:
            path = Path(path_str).expanduser().resolve()
            return path
        except Exception:
            return None
    
    def add_mount_for_path(path: Path, is_file: bool = False):
        """Add a mount for a path (file or directory)."""
        # For files, mount the parent directory
        mount_path = path.parent if is_file else path
        
        # Ensure the directory exists on host
        mount_path.mkdir(parents=True, exist_ok=True)
        
        # Check if we already have this mount
        for existing in mounts:
            if Path(existing.host_path).resolve() == mount_path:
                return
        
        mounts.append(VolumeMount(
            host_path=str(mount_path),
            container_path=str(mount_path),  # Use same path in container
            mode="rw"
        ))
    
    # Session service
    session_uri = app.get("session_service_uri", "")
    if session_uri.startswith("sqlite://"):
        db_path = expand_path(session_uri[9:])
        if db_path:
            add_mount_for_path(db_path, is_file=True)
    elif session_uri.startswith("file://"):
        dir_path = expand_path(session_uri[7:])
        if dir_path:
            add_mount_for_path(dir_path, is_file=False)
    
    # Memory service
    memory_uri = app.get("memory_service_uri", "")
    if memory_uri.startswith("file://"):
        dir_path = expand_path(memory_uri[7:])
        if dir_path:
            add_mount_for_path(dir_path, is_file=False)
    
    # Artifact service
    artifact_uri = app.get("artifact_service_uri", "")
    if artifact_uri.startswith("file://"):
        dir_path = expand_path(artifact_uri[7:])
        if dir_path:
            add_mount_for_path(dir_path, is_file=False)
    
    if mounts:
        logger.info(f"Auto-mounting storage paths: {[m.host_path for m in mounts]}")
    
    return mounts


# Check if docker is available
try:
    import docker
    from docker.errors import DockerException, NotFound, APIError
    DOCKER_AVAILABLE = True
except ImportError:
    DOCKER_AVAILABLE = False
    docker = None
    DockerException = Exception
    NotFound = Exception
    APIError = Exception


class SandboxManager:
    """Manages Docker sandbox lifecycle for ADK apps.
    
    The sandbox is App-scoped: one sandbox instance per App, shared by all
    Agents in the App.
    
    Uses base images from Docker Hub directly (no build step required):
    - python:3.11-slim for agent containers
    - mitmproxy/mitmproxy:latest for gateway containers
    
    Scripts are mounted at runtime, eliminating the need to build custom images.
    """
    
    # Base images from Docker Hub (no build required)
    GATEWAY_BASE_IMAGE = "mitmproxy/mitmproxy:latest"
    AGENT_BASE_IMAGE = "python:3.11-slim"
    
    # Legacy custom image names (used if pre-built images exist)
    GATEWAY_IMAGE = "adk-sandbox-gateway"
    AGENT_IMAGE = "adk-sandbox-agent"
    MCP_IMAGE = "adk-sandbox-mcp"
    
    # Network name prefix
    NETWORK_PREFIX = "adk-sandbox-net"
    
    def __init__(self, docker_dir: Optional[Path] = None):
        """Initialize the sandbox manager.
        
        Args:
            docker_dir: Directory containing scripts. Defaults to
                        the docker/ subdirectory of this module.
        """
        self.docker_dir = docker_dir or Path(__file__).parent / "docker"
        self.client: Optional[docker.DockerClient] = None
        self.instances: Dict[str, SandboxInstance] = {}  # app_id -> instance
        self.mcp_managers: Dict[str, MCPContainerManager] = {}  # app_id -> manager
        self._initialized = False
        self._use_base_images = True  # Use base images by default (no build)
    
    async def initialize(self) -> bool:
        """Initialize Docker client and build images if needed.
        
        Returns:
            True if initialization succeeded
        """
        if not DOCKER_AVAILABLE:
            logger.error("Docker Python SDK not installed. Run: pip install docker")
            return False
        
        try:
            self.client = docker.from_env()
            # Test connection
            self.client.ping()
            logger.info("Docker client connected")
        except DockerException as e:
            logger.error(f"Failed to connect to Docker: {e}")
            return False
        
        # Ensure images are available (pull base images if needed)
        try:
            await self._ensure_images_available()
        except Exception as e:
            logger.error(f"Failed to prepare Docker images: {e}")
            return False
        
        self._initialized = True
        return True
    
    # Dependencies to install in agent container (matches pyproject.toml + runtime needs)
    AGENT_DEPENDENCIES = [
        "google-adk",
        "litellm",
        "aiohttp",
        "httpx",
        "pyyaml",
        "mcp",
        "numpy",
    ]
    
    async def _ensure_images_available(self):
        """Ensure Docker images are available.
        
        Strategy:
        1. Check if cached custom images exist (fast path)
        2. If not, pull base images and build cached images with deps pre-installed
        3. Cache the images so subsequent starts are instant
        """
        if not self.client:
            return
        
        # Check if we have cached images with dependencies pre-installed
        agent_cached = False
        gateway_cached = False
        
        try:
            self.client.images.get(self.AGENT_IMAGE)
            agent_cached = True
            logger.info(f"Using cached agent image: {self.AGENT_IMAGE}")
        except NotFound:
            pass
        
        try:
            self.client.images.get(self.GATEWAY_IMAGE)
            gateway_cached = True
            logger.info(f"Using cached gateway image: {self.GATEWAY_IMAGE}")
        except NotFound:
            pass
        
        if agent_cached and gateway_cached:
            self._use_base_images = False
            return
        
        # Need to build cached images - first pull base images
        logger.info("Building cached images with dependencies (one-time setup)...")
        
        for image in [self.AGENT_BASE_IMAGE, self.GATEWAY_BASE_IMAGE]:
            try:
                self.client.images.get(image)
                logger.info(f"Base image {image} already available")
            except NotFound:
                logger.info(f"Pulling base image {image}...")
                self.client.images.pull(image)
                logger.info(f"Pulled {image}")
        
        # Build agent image with dependencies pre-installed
        if not agent_cached:
            await self._build_cached_agent_image()
        
        # Build gateway image with dependencies pre-installed
        if not gateway_cached:
            await self._build_cached_gateway_image()
        
        self._use_base_images = False
        logger.info("Cached images ready - future starts will be fast!")
    
    async def _build_cached_agent_image(self):
        """Build a cached agent image with all dependencies pre-installed.
        
        Includes:
        - Python packages (google-adk, litellm, etc.)
        - uv/uvx for Python MCP servers
        - Node.js/npm/npx for Node MCP servers
        - tsx for TypeScript MCP servers
        """
        if not self.client:
            return
        
        deps = " ".join(self.AGENT_DEPENDENCIES)
        logger.info(f"Building cached agent image with: {deps} + uv + node/npm + chromium")
        
        # Build command that installs everything
        # 1. Install curl and ca-certificates for downloading
        # 2. Install uv (provides uvx)
        # 3. Install Node.js (provides npm/npx)
        # 4. Install tsx globally
        # 5. Install Python packages
        build_command = """sh -c '
            apt-get update && apt-get install -y --no-install-recommends \
              curl ca-certificates git \
              chromium chromium-driver \
              xvfb xauth \
              fonts-liberation fonts-noto-color-emoji \
              && \
            # Compatibility paths expected by some automation SDKs ("Chrome stable")
            mkdir -p /opt/google/chrome && \
            ln -sf /usr/bin/chromium /opt/google/chrome/chrome && \
            ln -sf /usr/bin/chromium /usr/bin/google-chrome && \
            ln -sf /usr/bin/chromium /usr/bin/google-chrome-stable && \
            curl -LsSf https://astral.sh/uv/install.sh | sh && \
            export PATH="/root/.local/bin:$PATH" && \
            curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
            apt-get install -y nodejs && \
            npm install -g tsx && \
            pip install --no-cache-dir """ + deps + """ && \
            rm -rf /var/lib/apt/lists/*
        '"""
        
        # Create a temporary container, install deps, commit as new image
        container = self.client.containers.run(
            self.AGENT_BASE_IMAGE,
            command=build_command,
            detach=True,
            remove=False,
        )
        
        # Wait for pip install to complete
        result = container.wait()
        exit_code = result.get("StatusCode", 1)
        
        if exit_code != 0:
            logs = container.logs().decode()
            container.remove()
            raise RuntimeError(f"Failed to install dependencies: {logs}")
        
        # Commit the container as a new image
        container.commit(repository=self.AGENT_IMAGE, tag="latest")
        container.remove()
        logger.info(f"Built cached agent image: {self.AGENT_IMAGE}")
    
    async def _build_cached_gateway_image(self):
        """Build a cached gateway image with dependencies pre-installed."""
        if not self.client:
            return
        
        logger.info("Building cached gateway image with aiohttp")
        
        # Create a temporary container, install deps, commit as new image
        container = self.client.containers.run(
            self.GATEWAY_BASE_IMAGE,
            command="pip install --no-cache-dir aiohttp",
            detach=True,
            remove=False,
        )
        
        # Wait for pip install to complete
        result = container.wait()
        exit_code = result.get("StatusCode", 1)
        
        if exit_code != 0:
            logs = container.logs().decode()
            container.remove()
            raise RuntimeError(f"Failed to install dependencies: {logs}")
        
        # Commit the container as a new image
        container.commit(repository=self.GATEWAY_IMAGE, tag="latest")
        container.remove()
        logger.info(f"Built cached gateway image: {self.GATEWAY_IMAGE}")
    
    async def start_sandbox(
        self,
        app_id: str,
        config: SandboxConfig,
        project_config: Dict[str, Any],
        workspace_path: Path,
    ) -> SandboxInstance:
        """Start a sandbox for an App.
        
        Args:
            app_id: The App ID (used for container naming)
            config: Sandbox configuration
            project_config: Full project configuration dict
            workspace_path: Path to the project workspace
        
        Returns:
            The SandboxInstance with container info
        """
        if not self._initialized:
            if not await self.initialize():
                raise RuntimeError("Docker not available")
        
        # Check if already running in memory
        if app_id in self.instances:
            existing = self.instances[app_id]
            if existing.status == SandboxStatus.RUNNING:
                # Verify container is still running
                if await self._verify_container_running(existing.agent_container_id):
                    logger.info(f"Reusing existing sandbox for {app_id}")
                    # Load project config into existing container
                    await self._load_project_into_container(existing, project_config)
                    return existing
                else:
                    # Container died, clean up
                    logger.info(f"Container for {app_id} died, cleaning up")
                    await self._cleanup_existing_containers(app_id)
        else:
            # Check for orphaned Docker containers (e.g. after server restart)
            existing_container = await self._find_existing_container(app_id)
            if existing_container:
                logger.info(f"Found orphaned container for {app_id}, reusing")
                instance = await self._adopt_existing_container(app_id, existing_container, config)
                if instance:
                    await self._load_project_into_container(instance, project_config)
                    return instance
                # Failed to adopt, clean up
                await self._cleanup_existing_containers(app_id)
        
        # Auto-mount storage paths from service URIs
        storage_mounts = extract_storage_paths_from_project(project_config)
        if storage_mounts:
            # Combine with existing volume_mounts (if any)
            existing_paths = {m.host_path for m in config.volume_mounts}
            for mount in storage_mounts:
                if mount.host_path not in existing_paths:
                    config.volume_mounts.append(mount)
        
        # Create instance
        instance = SandboxInstance(
            app_id=app_id,
            status=SandboxStatus.STARTING,
            started_at=datetime.now(),
            config=config,
        )
        self.instances[app_id] = instance
        
        try:
            # Create network
            network_name = f"{self.NETWORK_PREFIX}-{app_id}"
            network = await self._create_network(network_name)
            
            # Create MCP manager and parse MCP configs
            mcp_manager = MCPContainerManager(client=self.client)
            self.mcp_managers[app_id] = mcp_manager
            mcp_configs = mcp_manager.parse_mcp_configs_from_project(project_config)
            
            # Get MCP-required domains and add to allowlist
            mcp_domains = mcp_manager.get_allowed_domains_for_mcp(mcp_configs)
            
            # Prepare allowlist with defaults and MCP domains
            allowlist = config.allowlist.with_defaults()
            allowlist.auto.extend(mcp_domains)
            allowlist.auto = list(set(allowlist.auto))  # Deduplicate

            # Optionally allow all outbound network connections (still via gateway proxy)
            if config.allow_all_network:
                # A single wildcard matches any host/url in the gateway addon.
                allowlist.auto = list(set(allowlist.auto + ["*"]))
            
            # Write project config to temp file
            config_file = await self._write_config_file(project_config)
            
            # Start gateway container
            gateway_unknown_action = "allow" if config.allow_all_network else config.unknown_action
            gateway_id = await self._start_gateway(
                app_id=app_id,
                network_name=network_name,
                allowlist=allowlist,
                unknown_action=gateway_unknown_action,
                approval_timeout=config.approval_timeout,
                allow_all_network=config.allow_all_network,
            )
            instance.gateway_container_id = gateway_id
            
            # Get app environment variables from project config
            app_env_vars = {}
            if project_config.get("app") and project_config["app"].get("env_vars"):
                app_env_vars = project_config["app"]["env_vars"]
            
            # Start agent container
            agent_id = await self._start_agent(
                app_id=app_id,
                network_name=network_name,
                workspace_path=workspace_path,
                config_file=config_file,
                memory_limit=config.agent_memory_limit_mb,
                cpu_limit=config.agent_cpu_limit,
                mcp_configs=mcp_configs,
                app_env_vars=app_env_vars,
                volume_mounts=config.volume_mounts,
            )
            instance.agent_container_id = agent_id
            
            # Start SSE MCP server containers
            for mcp_config in mcp_configs:
                if mcp_config.transport == "sse":
                    mcp_status = await mcp_manager.start_sse_container(
                        config=mcp_config,
                        network_name=network_name,
                        session_id=instance.id,
                    )
                    instance.mcp_containers.append(mcp_status)
            
            instance.status = SandboxStatus.RUNNING
            logger.info(f"Sandbox started for {app_id}")
            
        except Exception as e:
            instance.status = SandboxStatus.ERROR
            instance.error = str(e)
            logger.error(f"Failed to start sandbox for {app_id}: {e}")
            # Cleanup any partially created containers
            await self.stop_sandbox(app_id)
            raise
        
        return instance
    
    async def _create_network(self, network_name: str):
        """Create an isolated internal Docker network.
        
        This network is internal=True, meaning containers on it cannot
        directly access the internet. The gateway container will be on
        both this network AND the default bridge network to route traffic.
        
        Note: The MCP library only inherits a limited set of env vars to
        subprocesses (PATH, HOME, etc.) but NOT proxy variables. We handle
        this by injecting proxy env vars directly into the MCP server's
        StdioServerParameters.env in the code generator.
        """
        if not self.client:
            raise RuntimeError("Docker client not initialized")
        
        try:
            # Check if network exists
            network = self.client.networks.get(network_name)
            logger.info(f"Network {network_name} already exists")
            return network
        except NotFound:
            pass
        
        # Create INTERNAL network - no direct internet access from this network
        network = self.client.networks.create(
            network_name,
            driver="bridge",
            internal=True,  # No direct internet access
        )
        logger.info(f"Created internal network {network_name}")
        return network
    
    async def _find_gateway_container(self, app_id: str) -> Optional[str]:
        """Find an orphaned gateway container by app_id.
        
        This is used to recover from server restarts when Docker containers
        are still running but not tracked in memory.
        """
        if not self.client:
            return None
        
        gateway_name = f"sandbox-gateway-{app_id}"
        try:
            container = self.client.containers.get(gateway_name)
            if container.status == "running":
                logger.info(f"Found running gateway container: {gateway_name}")
                return container.id
        except Exception:
            pass
        return None
    
    async def _cleanup_existing_containers(self, app_id: str):
        """Clean up any existing containers and networks for an app.
        
        This handles the case where the server restarts but containers are still running.
        """
        if not self.client:
            return
        
        # Clean up agent container
        agent_name = f"sandbox-agent-{app_id}"
        try:
            container = self.client.containers.get(agent_name)
            logger.info(f"Found existing container {agent_name}, stopping...")
            container.stop(timeout=5)
            container.remove(force=True)
            logger.info(f"Removed container {agent_name}")
        except Exception:
            pass  # Container doesn't exist
        
        # Clean up gateway container
        gateway_name = f"sandbox-gateway-{app_id}"
        try:
            container = self.client.containers.get(gateway_name)
            logger.info(f"Found existing container {gateway_name}, stopping...")
            container.stop(timeout=5)
            container.remove(force=True)
            logger.info(f"Removed container {gateway_name}")
        except Exception:
            pass  # Container doesn't exist
        
        # Clean up network
        network_name = f"{self.NETWORK_PREFIX}-{app_id}"
        try:
            network = self.client.networks.get(network_name)
            logger.info(f"Found existing network {network_name}, removing...")
            network.remove()
            logger.info(f"Removed network {network_name}")
        except Exception:
            pass  # Network doesn't exist
    
    async def _verify_container_running(self, container_id: Optional[str]) -> bool:
        """Check if a container is still running and healthy."""
        if not container_id or not self.client:
            return False
        try:
            container = self.client.containers.get(container_id)
            return container.status == "running"
        except Exception:
            return False
    
    async def _find_existing_container(self, app_id: str) -> Optional[Any]:
        """Find an existing container for an app."""
        if not self.client:
            return None
        agent_name = f"sandbox-agent-{app_id}"
        try:
            container = self.client.containers.get(agent_name)
            if container.status == "running":
                return container
        except Exception:
            pass
        return None
    
    async def _adopt_existing_container(
        self,
        app_id: str,
        container: Any,
        config: SandboxConfig,
    ) -> Optional[SandboxInstance]:
        """Adopt an existing container into our instance tracking."""
        try:
            # Get container port
            ports = container.ports.get("5000/tcp")
            if not ports:
                return None
            
            # Create instance
            instance = SandboxInstance(
                app_id=app_id,
                status=SandboxStatus.RUNNING,
                started_at=datetime.now(),
                config=config,
            )
            instance.agent_container_id = container.id
            
            # Try to find gateway container
            gateway_name = f"sandbox-gateway-{app_id}"
            try:
                gateway = self.client.containers.get(gateway_name)
                instance.gateway_container_id = gateway.id
            except Exception:
                pass
            
            self.instances[app_id] = instance
            logger.info(f"Adopted existing container for {app_id}")
            return instance
        except Exception as e:
            logger.error(f"Failed to adopt container: {e}")
            return None
    
    async def _load_project_into_container(
        self,
        instance: SandboxInstance,
        project_config: Dict[str, Any],
    ):
        """Load project configuration into an existing container.
        
        Generates Python code from the project config and sends it to the container.
        The container then execs the code to create the app.
        """
        if not instance.agent_container_id or not self.client:
            return
        
        try:
            container = self.client.containers.get(instance.agent_container_id)
            ports = container.ports.get("5000/tcp")
            if not ports:
                return
            host_port = ports[0]["HostPort"]
            
            # Generate Python code from project config
            project = Project.model_validate(project_config)
            generated_code = generate_python_code(project)
            
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"http://localhost:{host_port}/project",
                    json={"code": generated_code, "project_name": project.name, "app_id": instance.app_id},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 200:
                        logger.info(f"Loaded project into container for {instance.app_id}")
                    else:
                        logger.warning(f"Failed to load project: {resp.status}")
        except Exception as e:
            logger.error(f"Failed to load project into container: {e}")
    
    async def _write_config_file(self, project_config: Dict[str, Any]) -> Path:
        """Write project config to a temp file.
        
        Expands ~ in service URIs so paths work correctly in the container.
        """
        # Deep copy to avoid modifying original
        config = json.loads(json.dumps(project_config))
        
        # Expand paths in service URIs
        if "app" in config:
            app = config["app"]
            for uri_key in ["session_service_uri", "memory_service_uri", "artifact_service_uri"]:
                uri = app.get(uri_key, "")
                if uri.startswith("sqlite://") or uri.startswith("file://"):
                    # Extract path portion and expand ~
                    prefix = uri.split("://")[0] + "://"
                    path_part = uri[len(prefix):]
                    expanded = str(Path(path_part).expanduser().resolve())
                    app[uri_key] = prefix + expanded
                    logger.debug(f"Expanded {uri_key}: {uri} -> {app[uri_key]}")
        
        fd, path = tempfile.mkstemp(suffix=".json", prefix="sandbox_config_")
        with os.fdopen(fd, "w") as f:
            json.dump(config, f)
        return Path(path)
    
    async def _start_gateway(
        self,
        app_id: str,
        network_name: str,
        allowlist: NetworkAllowlist,
        unknown_action: str,
        approval_timeout: int,
        allow_all_network: bool = False,
    ) -> str:
        """Start the gateway container."""
        if not self.client:
            raise RuntimeError("Docker client not initialized")
        
        # Prepare allowlist patterns for gateway
        patterns = []
        for p in allowlist.all_patterns():
            patterns.append({
                "pattern": p.pattern,
                "pattern_type": p.pattern_type.value,  # Gateway expects "pattern_type"
            })
        
        # Mount the addon script (always needed)
        addon_script = self.docker_dir / "gateway_addon.py"
        volumes = {
            str(addon_script): {"bind": "/app/gateway_addon.py", "mode": "ro"},
        }
        
        # Use cached image (deps pre-installed) - no pip install needed at runtime
        image = self.GATEWAY_IMAGE
        command = ["mitmdump", "--mode", "regular", "--set", "block_global=false", "-s", "/app/gateway_addon.py"]
        
        # Create container without any network initially
        container = self.client.containers.create(
            image=image,
            name=f"sandbox-gateway-{app_id}",
            detach=True,
            network_mode="bridge",  # Start with default bridge for internet access
            environment={
                "ALLOWLIST": json.dumps(patterns),
                "UNKNOWN_ACTION": unknown_action,
                "APPROVAL_TIMEOUT": str(approval_timeout),
                "ALLOW_ALL_NETWORK": "true" if allow_all_network else "false",
                "WEBHOOK_URL": f"http://host.docker.internal:8080/api/sandbox/webhook/{app_id}",
                "APP_ID": app_id,
                "CONTROL_PORT": "8081",
            },
            volumes=volumes if volumes else None,
            command=command,
            ports={
                "8080/tcp": None,  # Proxy port
                "8081/tcp": None,  # Control API
            },
            extra_hosts={
                "host.docker.internal": "host-gateway",
            },
        )
        
        # Also connect to internal network with "gateway" alias
        # This gives gateway dual-homed access: internet + internal network
        internal_network = self.client.networks.get(network_name)
        internal_network.connect(container, aliases=["gateway"])
        container.start()
        
        logger.info(f"Started gateway container: {container.id[:12]} (dual-homed)")
        return container.id
    
    async def _start_agent(
        self,
        app_id: str,
        network_name: str,
        workspace_path: Path,
        config_file: Path,
        memory_limit: int,
        cpu_limit: float,
        mcp_configs: Optional[List[MCPServerSandboxConfig]] = None,
        app_env_vars: Optional[Dict[str, str]] = None,
        volume_mounts: Optional[List[VolumeMount]] = None,
    ) -> str:
        """Start the agent runner container.
        
        Args:
            app_id: App ID for naming
            network_name: Docker network to join
            workspace_path: Path to project workspace
            config_file: Path to project config file
            memory_limit: Memory limit in MB
            cpu_limit: CPU limit (1.0 = 1 core)
            mcp_configs: MCP server configurations (stdio servers will be spawned in container)
            app_env_vars: Environment variables configured for the app
        """
        if not self.client:
            raise RuntimeError("Docker client not initialized")
        
        # Memory limit in bytes
        mem_limit = f"{memory_limit}m"
        
        # Prepare MCP configuration for stdio servers
        mcp_manager = self.mcp_managers.get(app_id)
        stdio_mcp_config = {}
        if mcp_manager and mcp_configs:
            stdio_mcp_config = mcp_manager.get_stdio_config_for_agent(mcp_configs)
        
        # Create container with proxy configuration for network monitoring
        # All HTTP/HTTPS traffic goes through the mitmproxy gateway
        # Agent is on internal network and can ONLY reach the gateway
        env_vars = {
            # Standard proxy environment variables
            "HTTP_PROXY": "http://gateway:8080",
            "HTTPS_PROXY": "http://gateway:8080",
            "http_proxy": "http://gateway:8080",  # Some tools check lowercase
            "https_proxy": "http://gateway:8080",
            # uv/uvx specific proxy variables
            "UV_HTTP_PROXY": "http://gateway:8080",
            "UV_HTTPS_PROXY": "http://gateway:8080",
            # npm proxy configuration
            "npm_config_proxy": "http://gateway:8080",
            "npm_config_https_proxy": "http://gateway:8080",
            # No proxy for local and gateway
            "NO_PROXY": "localhost,127.0.0.1,gateway",
            "no_proxy": "localhost,127.0.0.1,gateway",
            # Paths and config
            "WORKSPACE_PATH": "/workspace",
            "PROJECT_CONFIG_PATH": "/config/project.json",
            # Host URL goes through proxy - gateway will forward to host
            "HOST_URL": "http://host.docker.internal:8080",
            # MCP server configuration for stdio servers
            "MCP_SERVERS_CONFIG": json.dumps(stdio_mcp_config),
            # PATH includes uvx location
            "PATH": "/root/.local/bin:/usr/local/bin:/usr/bin:/bin",

            # Browser automation defaults (Chromium is installed in cached agent image)
            "CHROME_BIN": "/usr/bin/chromium",
            "CHROMIUM_BIN": "/usr/bin/chromium",
            "CHROMEDRIVER_BIN": "/usr/bin/chromedriver",
            "GOOGLE_CHROME_BIN": "/opt/google/chrome/chrome",
            # Puppeteer-based MCP servers: use system Chromium (avoid downloading at runtime)
            "PUPPETEER_SKIP_DOWNLOAD": "true",
            "PUPPETEER_EXECUTABLE_PATH": "/usr/bin/chromium",
            # Docker-friendly Chrome launch args (required for running in container)
            # These flags are needed because:
            # - --no-sandbox: Chrome sandbox doesn't work as root in Docker
            # - --disable-dev-shm-usage: /dev/shm is too small in Docker by default
            # - --disable-gpu: No GPU available in container
            # - --headless=new: Run headless (no display needed)
            # - --ignore-certificate-errors: Gateway proxy intercepts HTTPS, causing cert errors
            "PUPPETEER_ARGS": "--no-sandbox --disable-dev-shm-usage --disable-gpu --headless=new --ignore-certificate-errors",
            "CHROME_ARGS": "--no-sandbox --disable-dev-shm-usage --disable-gpu --headless=new --ignore-certificate-errors",
            # Optional virtual display fallback (some automations require a DISPLAY)
            # Set ENABLE_XVFB=1 at app-level env_vars to enable.
            "ENABLE_XVFB": "0",
        }
        
        # Pass through app-configured environment variables (API keys, etc.)
        if app_env_vars:
            env_vars.update(app_env_vars)
        
        # Also pass through common API credentials from host environment if not already set
        for key in [
            "GOOGLE_API_KEY",
            "GOOGLE_APPLICATION_CREDENTIALS",
            "GOOGLE_CLOUD_PROJECT",
            "GOOGLE_CLOUD_LOCATION",
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
        ]:
            if key not in env_vars and os.environ.get(key):
                env_vars[key] = os.environ[key]
        
        # Create agent on the sandbox network
        # All HTTP/HTTPS traffic is routed through the gateway proxy via env vars
        
        # Build volumes dict with workspace, config, and user-specified mounts
        volumes = {
            str(workspace_path): {"bind": "/workspace", "mode": "ro"},
            str(config_file): {"bind": "/config/project.json", "mode": "ro"},
        }
        
        # Add user-specified volume mounts (for MCP filesystem access, etc.)
        if volume_mounts:
            for mount in volume_mounts:
                # Expand ~ to home directory and resolve to absolute path
                host_path = os.path.expanduser(mount.host_path)
                host_path = os.path.abspath(host_path)
                if os.path.exists(host_path):
                    volumes[host_path] = {
                        "bind": mount.container_path,
                        "mode": mount.mode,
                    }
                    logger.info(f"Mounting {host_path} -> {mount.container_path} ({mount.mode})")
                else:
                    logger.warning(f"Volume mount path does not exist: {host_path}")
        
        # Mount the agent scripts (always needed)
        agent_script = self.docker_dir / "agent_runner.py"
        mcp_script = self.docker_dir / "mcp_spawner.py"
        volumes[str(agent_script)] = {"bind": "/app/agent_runner.py", "mode": "ro"}
        volumes[str(mcp_script)] = {"bind": "/app/mcp_spawner.py", "mode": "ro"}
        
        # Mount custom service implementations (file_session_service, file_memory_service)
        # These are in the adk-playground root directory
        repo_root = self.docker_dir.parent.parent.parent  # sandbox/docker -> sandbox -> backend -> root
        for service_file in ["file_session_service.py", "file_memory_service.py"]:
            service_path = repo_root / service_file
            if service_path.exists():
                volumes[str(service_path)] = {"bind": f"/app/{service_file}", "mode": "ro"}
                logger.info(f"Mounting custom service: {service_file}")
        
        # Use cached image (deps pre-installed) - no pip install needed at runtime
        image = self.AGENT_IMAGE
        # Optional Xvfb display for non-headless browser automation.
        # Default is headless (ENABLE_XVFB=0). If enabled, we start a minimal virtual X server.
        command = [
            "sh",
            "-c",
            'if [ "${ENABLE_XVFB:-0}" = "1" ]; then '
            '  Xvfb :99 -screen 0 1280x720x24 -nolisten tcp >/tmp/xvfb.log 2>&1 & '
            '  export DISPLAY=:99; '
            "fi; "
            "exec python -u /app/agent_runner.py",
        ]
        
        # Run as current user to match host filesystem permissions for mounted volumes
        # This allows the container to write to mounted storage directories
        import platform
        user_spec = None
        if platform.system() != "Darwin":  # On Linux, need to match UID/GID
            user_spec = f"{os.getuid()}:{os.getgid()}"
        
        container = self.client.containers.create(
            image=image,
            name=f"sandbox-agent-{app_id}",
            detach=True,
            network=network_name,  # Internal network only - isolated from internet
            environment=env_vars,
            volumes=volumes,
            command=command,
            # No ports exposed - host communicates via gateway proxy
            mem_limit=mem_limit,
            cpu_period=100000,
            cpu_quota=int(cpu_limit * 100000),
            user=user_spec,  # Match host user for volume write permissions
            # No extra_hosts - all traffic goes through gateway proxy
        )
        
        container.start()
        logger.info(f"Started agent container: {container.id[:12]} (isolated)")
        return container.id
    
    async def stop_sandbox(self, app_id: str) -> bool:
        """Stop a sandbox and cleanup containers.
        
        Args:
            app_id: The App ID
        
        Returns:
            True if stopped successfully
        """
        if app_id not in self.instances:
            return False
        
        instance = self.instances[app_id]
        instance.status = SandboxStatus.STOPPING
        
        if not self.client:
            return False
        
        # Stop containers
        for container_id in [
            instance.agent_container_id,
            instance.gateway_container_id,
        ]:
            if container_id:
                try:
                    container = self.client.containers.get(container_id)
                    container.stop(timeout=5)
                    container.remove()
                    logger.info(f"Stopped container {container_id[:12]}")
                except NotFound:
                    pass
                except Exception as e:
                    logger.error(f"Error stopping container {container_id[:12]}: {e}")
        
        # Stop MCP containers
        for mcp in instance.mcp_containers:
            if mcp.container_id:
                try:
                    container = self.client.containers.get(mcp.container_id)
                    container.stop(timeout=5)
                    container.remove()
                except NotFound:
                    pass
                except Exception as e:
                    logger.error(f"Error stopping MCP container {mcp.name}: {e}")
        
        # Remove network
        network_name = f"{self.NETWORK_PREFIX}-{app_id}"
        try:
            network = self.client.networks.get(network_name)
            network.remove()
            logger.info(f"Removed network {network_name}")
        except NotFound:
            pass
        except Exception as e:
            logger.error(f"Error removing network: {e}")
        
        # Cleanup MCP manager
        if app_id in self.mcp_managers:
            await self.mcp_managers[app_id].stop_all()
            del self.mcp_managers[app_id]
        
        instance.status = SandboxStatus.STOPPED
        del self.instances[app_id]
        
        return True
    
    async def get_sandbox_status(self, app_id: str) -> Optional[SandboxInstance]:
        """Get the status of a sandbox.
        
        Args:
            app_id: The App ID
        
        Returns:
            The SandboxInstance or None if not found
        """
        return self.instances.get(app_id)
    
    async def list_sandboxes(self) -> List[SandboxInstance]:
        """List all sandbox instances."""
        return list(self.instances.values())
    
    def _get_agent_urls(self, instance: SandboxInstance) -> tuple:
        """Get the agent URL and proxy URL for a sandbox instance.
        
        Returns:
            Tuple of (agent_url, proxy_url) or (None, None) if not available
        """
        if not instance.gateway_container_id:
            return None, None
        
        try:
            gateway = self.client.containers.get(instance.gateway_container_id)
            gateway_ports = gateway.attrs.get("NetworkSettings", {}).get("Ports", {}).get("8080/tcp")
            if not gateway_ports:
                return None, None
            proxy_port = gateway_ports[0]["HostPort"]
            
            agent_container_name = f"sandbox-agent-{instance.app_id}"
            agent_url = f"http://{agent_container_name}:5000"
            proxy_url = f"http://localhost:{proxy_port}"
            
            return agent_url, proxy_url
        except Exception as e:
            logger.warning(f"Failed to get agent URLs: {e}")
            return None, None
    
    async def send_message_to_agent(
        self,
        app_id: str,
        message: str,
        session_id: Optional[str] = None,
    ) -> Optional[str]:
        """Send a message to the agent in the sandbox.
        
        Args:
            app_id: The App ID
            message: The user message
            session_id: Optional session ID to continue
        
        Returns:
            The session ID if started successfully
        """
        instance = self.instances.get(app_id)
        if not instance or instance.status != SandboxStatus.RUNNING:
            return None
        
        if not instance.agent_container_id or not self.client:
            return None
        
        # Get agent container port
        try:
            container = self.client.containers.get(instance.agent_container_id)
            ports = container.ports.get("5000/tcp")
            if not ports:
                return None
            host_port = ports[0]["HostPort"]
            
            # Send message to agent
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"http://localhost:{host_port}/run",
                    json={"message": message, "session_id": session_id},
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("session_id")
        except Exception as e:
            logger.error(f"Failed to send message to agent: {e}")
        
        return None
    
    async def approve_request(
        self,
        app_id: str,
        request_id: str,
        pattern: Optional[str] = None,
    ) -> bool:
        """Approve a pending network request.
        
        Args:
            app_id: The App ID
            request_id: The request ID to approve
            pattern: Optional pattern to add to allowlist
        
        Returns:
            True if approved successfully
        """
        logger.info(f"🔓 approve_request called: app_id={app_id}, request_id={request_id}")
        logger.info(f"   Manager id={id(self)}, instances={list(self.instances.keys())}")
        
        instance = self.instances.get(app_id)
        if not instance:
            # Try to find orphaned containers (e.g., after server restart)
            logger.info(f"   Instance not in memory, checking for Docker containers...")
            gateway_container_id = await self._find_gateway_container(app_id)
            if gateway_container_id:
                logger.info(f"   Found orphaned gateway container: {gateway_container_id[:12]}")
                # Create a temporary instance just for this approval
                instance = SandboxInstance(
                    app_id=app_id,
                    status=SandboxStatus.RUNNING,
                    started_at=datetime.now(),
                    config=SandboxConfig(enabled=True),
                    gateway_container_id=gateway_container_id,
                )
                self.instances[app_id] = instance
            else:
                logger.warning(f"   ❌ No instance or container found for app_id={app_id}")
                return False
        if instance.status != SandboxStatus.RUNNING:
            logger.warning(f"   ❌ Instance status={instance.status}, not RUNNING")
            return False
        
        if not instance.gateway_container_id or not self.client:
            logger.warning(f"   ❌ No gateway or client")
            return False
        
        try:
            container = self.client.containers.get(instance.gateway_container_id)
            ports = container.ports.get("8081/tcp")
            if not ports:
                logger.warning(f"   ❌ No 8081/tcp port exposed")
                return False
            host_port = ports[0]["HostPort"]
            
            logger.info(f"   Calling gateway at http://localhost:{host_port}/approve")
            
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"http://localhost:{host_port}/approve",
                    json={"request_id": request_id, "pattern": pattern},
                ) as resp:
                    logger.info(f"   Gateway response: {resp.status}")
                    if resp.status != 200:
                        body = await resp.text()
                        logger.warning(f"   Gateway error: {body}")
                    return resp.status == 200
        except Exception as e:
            logger.error(f"Failed to approve request: {e}")
        
        return False
    
    async def deny_request(self, app_id: str, request_id: str) -> bool:
        """Deny a pending network request."""
        instance = self.instances.get(app_id)
        if not instance or instance.status != SandboxStatus.RUNNING:
            return False
        
        if not instance.gateway_container_id or not self.client:
            return False
        
        try:
            container = self.client.containers.get(instance.gateway_container_id)
            ports = container.ports.get("8081/tcp")
            if not ports:
                return False
            host_port = ports[0]["HostPort"]
            
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"http://localhost:{host_port}/deny",
                    json={"request_id": request_id},
                ) as resp:
                    return resp.status == 200
        except Exception as e:
            logger.error(f"Failed to deny request: {e}")
        
        return False
    
    async def add_pattern_to_gateway(
        self,
        app_id: str,
        pattern: str,
        pattern_type: str = "exact",
    ) -> bool:
        """Add a pattern to the running gateway's allowlist.
        
        Args:
            app_id: The App ID
            pattern: The pattern to add
            pattern_type: Type of pattern (exact, wildcard, regex)
        
        Returns:
            True if added successfully
        """
        instance = self.instances.get(app_id)
        if not instance or instance.status != SandboxStatus.RUNNING:
            logger.info(f"No running sandbox for {app_id}")
            return False
        
        if not instance.gateway_container_id or not self.client:
            return False
        
        try:
            container = self.client.containers.get(instance.gateway_container_id)
            ports = container.ports.get("8081/tcp")
            if not ports:
                return False
            host_port = ports[0]["HostPort"]
            
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"http://localhost:{host_port}/add_pattern",
                    json={"pattern": pattern, "pattern_type": pattern_type},
                ) as resp:
                    if resp.status == 200:
                        logger.info(f"Added pattern {pattern} to gateway for {app_id}")
                        return True
                    else:
                        body = await resp.text()
                        logger.warning(f"Failed to add pattern: {body}")
        except Exception as e:
            logger.error(f"Failed to add pattern to gateway: {e}")
        
        return False
    
    async def sync_allowlist_to_gateway(
        self,
        app_id: str,
        patterns: List[Dict[str, Any]],
    ) -> int:
        """Sync multiple patterns to the running gateway's allowlist.
        
        Args:
            app_id: The App ID
            patterns: List of pattern dicts with 'pattern' and 'pattern_type'
        
        Returns:
            Number of patterns successfully added
        """
        count = 0
        for p in patterns:
            pattern = p.get("pattern", "")
            pattern_type = p.get("pattern_type", "exact")
            if pattern:
                success = await self.add_pattern_to_gateway(app_id, pattern, pattern_type)
                if success:
                    count += 1
        return count
    
    async def send_message(
        self,
        app_id: str,
        message: str,
        session_id: Optional[str] = None,
        project_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Send a message to the agent running in the sandbox.
        
        Args:
            app_id: The App ID
            message: The user message
            session_id: Optional session ID to reuse
            project_config: Optional project config to load before running
        
        Returns:
            Response from the agent
        """
        instance = self.instances.get(app_id)
        if not instance or instance.status != SandboxStatus.RUNNING:
            return {"error": "Sandbox not running"}
        
        if not instance.agent_container_id or not self.client:
            return {"error": "Agent container not available"}
        
        try:
            # Get gateway proxy port - all communication goes through the gateway
            gateway = self.client.containers.get(instance.gateway_container_id)
            gateway_ports = gateway.ports.get("8080/tcp")
            if not gateway_ports:
                return {"error": "Gateway proxy port not exposed"}
            proxy_port = gateway_ports[0]["HostPort"]
            
            # Agent container name for internal routing
            agent_container_name = f"sandbox-agent-{app_id}"
            agent_url = f"http://{agent_container_name}:5000"
            
            import aiohttp
            
            # Create a session that uses the gateway as a proxy
            proxy_url = f"http://localhost:{proxy_port}"
            
            # Wait for agent to be healthy (through the proxy)
            max_retries = 15
            for attempt in range(max_retries):
                try:
                    # Use the proxy to reach the agent
                    connector = aiohttp.TCPConnector()
                    async with aiohttp.ClientSession(connector=connector) as session:
                        async with session.get(
                            f"{agent_url}/health",
                            proxy=proxy_url,
                            timeout=aiohttp.ClientTimeout(total=5),
                        ) as health_resp:
                            if health_resp.status == 200:
                                logger.info(f"Agent is healthy (via proxy)")
                                break
                except Exception as e:
                    logger.debug(f"Health check attempt {attempt + 1} failed: {e}")
                
                if attempt < max_retries - 1:
                    logger.info(f"Waiting for agent container to be ready (attempt {attempt + 1}/{max_retries})")
                    await asyncio.sleep(1)
            else:
                return {"error": "Agent container not ready after retries"}
            
            # Load project config if provided (through proxy)
            if project_config:
                try:
                    project = Project.model_validate(project_config)
                    generated_code = generate_python_code(project)
                    async with aiohttp.ClientSession() as session:
                        async with session.post(
                            f"{agent_url}/project",
                            proxy=proxy_url,
                            json={"code": generated_code, "project_name": project.name, "app_id": app_id},
                            timeout=aiohttp.ClientTimeout(total=10),
                        ) as resp:
                            if resp.status != 200:
                                logger.warning(f"Failed to load project config: {resp.status}")
                except Exception as e:
                    logger.warning(f"Failed to load project config: {e}")
            
            # Send the run request (through proxy) with retry logic
            # Use run_timeout from config, default to 3600 (1 hour)
            run_timeout = instance.config.run_timeout if instance.config else 3600
            max_retries = 3
            last_error = None
            
            for attempt in range(max_retries):
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.post(
                            f"{agent_url}/run",
                            proxy=proxy_url,
                            json={
                                "message": message,
                                "session_id": session_id,
                            },
                            timeout=aiohttp.ClientTimeout(total=run_timeout),
                        ) as resp:
                            if resp.status == 200:
                                return await resp.json()
                            else:
                                text = await resp.text()
                                error_msg = f"Agent returned {resp.status}: {text}"
                                # Retry on 5xx errors
                                if resp.status >= 500 and attempt < max_retries - 1:
                                    logger.warning(f"Agent request failed (attempt {attempt + 1}/{max_retries}): {error_msg}")
                                    await asyncio.sleep(2 ** attempt)  # Exponential backoff
                                    continue
                                return {"error": error_msg}
                except asyncio.TimeoutError:
                    last_error = "Agent request timed out"
                    if attempt < max_retries - 1:
                        logger.warning(f"Agent request timed out (attempt {attempt + 1}/{max_retries}), retrying...")
                        await asyncio.sleep(2 ** attempt)  # Exponential backoff: 1s, 2s, 4s
                        continue
                    return {"error": f"Agent request timed out after {max_retries} attempts"}
                except (aiohttp.ClientError, ConnectionError) as e:
                    last_error = str(e)
                    if attempt < max_retries - 1:
                        logger.warning(f"Agent request failed (attempt {attempt + 1}/{max_retries}): {e}")
                        await asyncio.sleep(2 ** attempt)
                        continue
                    return {"error": f"Connection error after {max_retries} attempts: {e}"}
                except Exception as e:
                    logger.error(f"Failed to send message to agent: {e}")
                    return {"error": str(e)}
            
            return {"error": last_error or "Unknown error after retries"}
        except Exception as e:
            logger.error(f"Failed to send message to agent: {e}")
            return {"error": str(e)}
    
    async def mcp_list_servers(self, app_id: str) -> Dict[str, Any]:
        """List MCP servers available in the sandbox."""
        instance = self.instances.get(app_id)
        if not instance:
            return {"error": "Sandbox not found"}
        
        agent_url, proxy_url = self._get_agent_urls(instance)
        if not agent_url:
            return {"error": "Agent not running"}
        
        import aiohttp
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{agent_url}/mcp/servers",
                    proxy=proxy_url,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    else:
                        text = await resp.text()
                        return {"error": f"Agent returned {resp.status}: {text}"}
        except Exception as e:
            logger.error(f"Failed to list MCP servers: {e}")
            return {"error": str(e)}
    
    async def mcp_list_tools(self, app_id: str, server_name: str) -> Dict[str, Any]:
        """List tools from an MCP server in the sandbox."""
        instance = self.instances.get(app_id)
        if not instance:
            return {"error": "Sandbox not found"}
        
        agent_url, proxy_url = self._get_agent_urls(instance)
        if not agent_url:
            return {"error": "Agent not running"}
        
        import aiohttp
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{agent_url}/mcp/tools",
                    proxy=proxy_url,
                    json={"server": server_name},
                    timeout=aiohttp.ClientTimeout(total=60),
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    else:
                        text = await resp.text()
                        return {"error": f"Agent returned {resp.status}: {text}"}
        except Exception as e:
            logger.error(f"Failed to list MCP tools: {e}")
            return {"error": str(e)}
    
    async def mcp_call_tool(
        self, 
        app_id: str, 
        server_name: str, 
        tool_name: str, 
        args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Call an MCP tool in the sandbox.
        
        This allows Tool Watches and debugging to execute MCP tools
        from the perspective of the agent runner inside the container.
        """
        instance = self.instances.get(app_id)
        if not instance:
            return {"error": "Sandbox not found"}
        
        agent_url, proxy_url = self._get_agent_urls(instance)
        if not agent_url:
            return {"error": "Agent not running"}
        
        import aiohttp
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{agent_url}/mcp/call",
                    proxy=proxy_url,
                    json={
                        "server": server_name,
                        "tool": tool_name,
                        "args": args,
                    },
                    timeout=aiohttp.ClientTimeout(total=120),  # Tools can take a while
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    else:
                        text = await resp.text()
                        return {"error": f"Agent returned {resp.status}: {text}"}
        except Exception as e:
            logger.error(f"Failed to call MCP tool: {e}")
            return {"error": str(e)}
    
    async def mcp_disconnect(self, app_id: str, server_name: Optional[str] = None) -> Dict[str, Any]:
        """Disconnect from MCP servers in the sandbox."""
        instance = self.instances.get(app_id)
        if not instance:
            return {"error": "Sandbox not found"}
        
        agent_url, proxy_url = self._get_agent_urls(instance)
        if not agent_url:
            return {"error": "Agent not running"}
        
        import aiohttp
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{agent_url}/mcp/disconnect",
                    proxy=proxy_url,
                    json={"server": server_name} if server_name else {},
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    else:
                        text = await resp.text()
                        return {"error": f"Agent returned {resp.status}: {text}"}
        except Exception as e:
            logger.error(f"Failed to disconnect MCP: {e}")
            return {"error": str(e)}
    
    async def get_container_logs(
        self, 
        app_id: str, 
        container_type: str = "agent",  # "agent" or "gateway"
        tail: int = 500,
        since: Optional[int] = None,  # Unix timestamp
    ) -> Dict[str, Any]:
        """Get logs from a sandbox container.
        
        Args:
            app_id: The App ID
            container_type: "agent" or "gateway"
            tail: Number of lines to return from the end
            since: Only return logs since this Unix timestamp
        
        Returns:
            Dict with "logs" key containing the log text, or "error" key
        """
        instance = self.instances.get(app_id)
        if not instance:
            return {"error": "Sandbox not found"}
        
        try:
            if container_type == "agent" and instance.agent_container_id:
                container = self.client.containers.get(instance.agent_container_id)
            elif container_type == "gateway" and instance.gateway_container_id:
                container = self.client.containers.get(instance.gateway_container_id)
            else:
                return {"error": f"Container type '{container_type}' not found"}
            
            # Get logs
            logs = container.logs(
                tail=tail,
                since=since,
                timestamps=True,
            )
            
            # Decode bytes to string
            if isinstance(logs, bytes):
                logs = logs.decode("utf-8", errors="replace")
            
            return {
                "logs": logs,
                "container_id": container.id[:12],
                "container_type": container_type,
                "status": container.status,
            }
            
        except Exception as e:
            logger.error(f"Failed to get container logs: {e}")
            return {"error": str(e)}
    
    async def cleanup(self):
        """Cleanup all sandboxes on shutdown."""
        for app_id in list(self.instances.keys()):
            await self.stop_sandbox(app_id)


# Global sandbox manager instance
_manager: Optional[SandboxManager] = None


def get_sandbox_manager() -> SandboxManager:
    """Get the global sandbox manager instance."""
    global _manager
    if _manager is None:
        _manager = SandboxManager()
    return _manager

