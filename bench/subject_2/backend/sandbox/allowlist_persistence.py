"""Allowlist persistence for saving/loading from project YAML.

This module handles loading and saving the network allowlist to/from
the project's YAML configuration file.

Based on DOCKER_PLAN.md specification.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from .models import AllowlistPattern, NetworkAllowlist, PatternType, SandboxConfig

logger = logging.getLogger(__name__)


# Default sandbox configuration in YAML format
DEFAULT_SANDBOX_CONFIG = {
    "enabled": False,
    "allow_all_network": False,
    "network_allowlist": {
        "user": [],
    },
    "unknown_action": "ask",
    "approval_timeout": 120,
    "agent_memory_limit_mb": 512,
    "agent_cpu_limit": 1.0,
    "mcp_memory_limit_mb": 256,
    "mcp_cpu_limit": 0.5,
    "run_timeout": 300,
}


def load_allowlist_from_project(project_path: Path) -> NetworkAllowlist:
    """Load the network allowlist from a project's configuration.
    
    The allowlist is stored in the project's YAML file under:
    sandbox.network_allowlist.user
    
    Args:
        project_path: Path to the project directory or YAML file
    
    Returns:
        The NetworkAllowlist with user patterns loaded
    """
    # Find the config file
    if project_path.is_file():
        config_file = project_path
    else:
        # Try common config file names
        for name in ["app.yaml", "project.yaml", "sandbox.yaml"]:
            candidate = project_path / name
            if candidate.exists():
                config_file = candidate
                break
        else:
            logger.info(f"No sandbox config found in {project_path}")
            return NetworkAllowlist()
    
    try:
        with open(config_file) as f:
            data = yaml.safe_load(f) or {}
    except Exception as e:
        logger.warning(f"Failed to load config from {config_file}: {e}")
        return NetworkAllowlist()
    
    # Support both legacy top-level "sandbox.network_allowlist"
    # and newer "app.sandbox.allowlist" shapes.
    sandbox_config = data.get("sandbox", {}) or {}
    allowlist_config = sandbox_config.get("network_allowlist", {}) or {}

    app_sandbox_config = (data.get("app", {}) or {}).get("sandbox", {}) or {}
    app_allowlist_config = app_sandbox_config.get("allowlist", {}) or {}

    # Parse user patterns from both sources and merge.
    merged: list[AllowlistPattern] = []

    # Legacy format: sandbox.network_allowlist.user[*].{pattern,type,added,source}
    for p in allowlist_config.get("user", []) or []:
        try:
            merged.append(AllowlistPattern(
                id=p.get("id", ""),
                pattern=p.get("pattern", ""),
                pattern_type=PatternType(p.get("type", "exact")),
                added_at=datetime.fromisoformat(p["added"]) if p.get("added") else None,
                source=p.get("source", "user"),
            ))
        except Exception as e:
            logger.warning(f"Failed to parse allowlist pattern (sandbox.network_allowlist): {e}")

    # App format: app.sandbox.allowlist.user[*].{pattern,pattern_type,added_at,source}
    for p in app_allowlist_config.get("user", []) or []:
        try:
            merged.append(AllowlistPattern(
                id=p.get("id", ""),
                pattern=p.get("pattern", ""),
                pattern_type=PatternType(p.get("pattern_type", "exact")),
                added_at=datetime.fromisoformat(p["added_at"]) if p.get("added_at") else None,
                source=p.get("source", "user"),
            ))
        except Exception as e:
            logger.warning(f"Failed to parse allowlist pattern (app.sandbox.allowlist): {e}")

    # Deduplicate by (pattern, type) while preserving stable order.
    seen: set[tuple[str, str]] = set()
    user_patterns: list[AllowlistPattern] = []
    for p in merged:
        key = (p.pattern, p.pattern_type.value)
        if key in seen:
            continue
        seen.add(key)
        user_patterns.append(p)

    return NetworkAllowlist(user=user_patterns)


def save_allowlist_to_project(
    project_path: Path,
    allowlist: NetworkAllowlist,
) -> bool:
    """Save the network allowlist to a project's configuration.
    
    Only user-defined patterns are saved (auto patterns are regenerated).
    
    Args:
        project_path: Path to the project directory
        allowlist: The allowlist to save
    
    Returns:
        True if saved successfully
    """
    # Find the config file
    if project_path.is_file():
        config_file = project_path
    else:
        # Use app.yaml by default
        config_file = project_path / "app.yaml"
    
    # Load existing config or create new
    if config_file.exists():
        try:
            with open(config_file) as f:
                data = yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning(f"Failed to load existing config: {e}")
            data = {}
    else:
        data = {}
    
    # Ensure sandbox section exists
    if "sandbox" not in data:
        data["sandbox"] = dict(DEFAULT_SANDBOX_CONFIG)
    
    # Update allowlist
    data["sandbox"]["network_allowlist"] = allowlist.to_yaml_dict()
    
    # Save
    try:
        config_file.parent.mkdir(parents=True, exist_ok=True)
        with open(config_file, "w") as f:
            yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)
        logger.info(f"Saved allowlist to {config_file}")
        return True
    except Exception as e:
        logger.error(f"Failed to save config: {e}")
        return False


def load_sandbox_config_from_project(project_path: Path) -> SandboxConfig:
    """Load the complete sandbox configuration from a project.
    
    Args:
        project_path: Path to the project directory or YAML file
    
    Returns:
        The SandboxConfig
    """
    # Find the config file
    if project_path.is_file():
        config_file = project_path
    else:
        for name in ["app.yaml", "project.yaml", "sandbox.yaml"]:
            candidate = project_path / name
            if candidate.exists():
                config_file = candidate
                break
        else:
            return SandboxConfig()
    
    try:
        with open(config_file) as f:
            data = yaml.safe_load(f) or {}
    except Exception as e:
        logger.warning(f"Failed to load config: {e}")
        return SandboxConfig()
    
    sandbox_data = data.get("sandbox", {}) or {}
    app_sandbox_data = (data.get("app", {}) or {}).get("sandbox", {}) or {}
    
    # Load allowlist
    allowlist = load_allowlist_from_project(project_path)
    
    # Prefer app.sandbox values when present, but keep legacy top-level sandbox
    # as a fallback (and still merge allowlist patterns from both).
    return SandboxConfig(
        enabled=app_sandbox_data.get("enabled", sandbox_data.get("enabled", False)),
        allow_all_network=app_sandbox_data.get("allow_all_network", sandbox_data.get("allow_all_network", False)),
        allowlist=allowlist,
        unknown_action=app_sandbox_data.get("unknown_action", sandbox_data.get("unknown_action", "ask")),
        approval_timeout=app_sandbox_data.get("approval_timeout", sandbox_data.get("approval_timeout", 30)),
        agent_memory_limit_mb=app_sandbox_data.get("agent_memory_limit_mb", sandbox_data.get("agent_memory_limit_mb", 512)),
        agent_cpu_limit=app_sandbox_data.get("agent_cpu_limit", sandbox_data.get("agent_cpu_limit", 1.0)),
        mcp_memory_limit_mb=app_sandbox_data.get("mcp_memory_limit_mb", sandbox_data.get("mcp_memory_limit_mb", 256)),
        mcp_cpu_limit=app_sandbox_data.get("mcp_cpu_limit", sandbox_data.get("mcp_cpu_limit", 0.5)),
        run_timeout=app_sandbox_data.get("run_timeout", sandbox_data.get("run_timeout", 300)),
        volume_mounts=app_sandbox_data.get("volume_mounts", sandbox_data.get("volume_mounts", [])) or [],
    )


def save_sandbox_config_to_project(
    project_path: Path,
    config: SandboxConfig,
) -> bool:
    """Save the complete sandbox configuration to a project.
    
    Args:
        project_path: Path to the project directory
        config: The configuration to save
    
    Returns:
        True if saved successfully
    """
    # Find the config file
    if project_path.is_file():
        config_file = project_path
    else:
        config_file = project_path / "app.yaml"
    
    # Load existing config
    if config_file.exists():
        try:
            with open(config_file) as f:
                data = yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning(f"Failed to load existing config: {e}")
            data = {}
    else:
        data = {}
    
    # Build sandbox config dict
    sandbox_dict = {
        "enabled": config.enabled,
        "allow_all_network": getattr(config, "allow_all_network", False),
        "network_allowlist": config.allowlist.to_yaml_dict(),
        "unknown_action": config.unknown_action,
        "approval_timeout": config.approval_timeout,
        "agent_memory_limit_mb": config.agent_memory_limit_mb,
        "agent_cpu_limit": config.agent_cpu_limit,
        "mcp_memory_limit_mb": config.mcp_memory_limit_mb,
        "mcp_cpu_limit": config.mcp_cpu_limit,
        "run_timeout": config.run_timeout,
        "volume_mounts": [m.model_dump() for m in (config.volume_mounts or [])],
    }
    
    data["sandbox"] = sandbox_dict
    
    # Save
    try:
        config_file.parent.mkdir(parents=True, exist_ok=True)
        with open(config_file, "w") as f:
            yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)
        logger.info(f"Saved sandbox config to {config_file}")
        return True
    except Exception as e:
        logger.error(f"Failed to save config: {e}")
        return False


def add_pattern_to_project(
    project_path: Path,
    pattern: str,
    pattern_type: PatternType = PatternType.WILDCARD,
    source: str = "approved",
) -> Optional[AllowlistPattern]:
    """Add a pattern to the project's allowlist and save.
    
    Args:
        project_path: Path to the project directory
        pattern: The pattern string
        pattern_type: Type of pattern matching
        source: Source of the pattern (e.g., "approved", "user")
    
    Returns:
        The created AllowlistPattern or None if failed
    """
    # Load current allowlist
    allowlist = load_allowlist_from_project(project_path)
    
    # Check if pattern already exists
    for p in allowlist.user:
        if p.pattern == pattern and p.pattern_type == pattern_type:
            return p  # Already exists
    
    # Add new pattern
    new_pattern = allowlist.add_user_pattern(
        pattern=pattern,
        pattern_type=pattern_type,
        source=source,
    )
    
    # Save
    if save_allowlist_to_project(project_path, allowlist):
        return new_pattern
    return None


def remove_pattern_from_project(
    project_path: Path,
    pattern_id: str,
) -> bool:
    """Remove a pattern from the project's allowlist and save.
    
    Args:
        project_path: Path to the project directory
        pattern_id: ID of the pattern to remove
    
    Returns:
        True if removed and saved successfully
    """
    # Load current allowlist
    allowlist = load_allowlist_from_project(project_path)
    
    # Remove pattern
    if not allowlist.remove_user_pattern(pattern_id):
        return False
    
    # Save
    return save_allowlist_to_project(project_path, allowlist)

