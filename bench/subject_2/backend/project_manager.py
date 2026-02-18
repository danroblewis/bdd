"""Project management - save/load projects as YAML files."""

from __future__ import annotations

import asyncio
import gzip
import hashlib
import logging
import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from models import Project, AppConfig, AgentConfig, CustomToolDefinition, CustomCallbackDefinition

logger = logging.getLogger(__name__)


class ProjectManager:
    """Manages project persistence using YAML files."""
    
    def __init__(self, projects_dir: str = "./projects"):
        self.projects_dir = Path(projects_dir)
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        self._cache: Dict[str, Project] = {}
        
        # Backup tracking
        self._backup_dir = self.projects_dir / ".backups"
        self._backup_dir.mkdir(parents=True, exist_ok=True)
        self._last_backup_hashes: Dict[str, str] = {}  # project_id -> content hash
        self._backup_task: Optional[asyncio.Task] = None
        self._backup_running = False
        
        # Load existing backup hashes
        self._load_backup_hashes()
    
    def _project_path(self, project_id: str) -> Path:
        return self.projects_dir / f"{project_id}.yaml"
    
    def get_project_path(self, project_id: str) -> Optional[str]:
        """Get the path to a project's YAML file.
        
        Returns:
            The path as a string if the project exists, None otherwise.
        """
        path = self._project_path(project_id)
        if path.exists():
            return str(path)
        return None
    
    def _tools_dir(self, project_id: str) -> Path:
        tools_dir = self.projects_dir / project_id / "tools"
        tools_dir.mkdir(parents=True, exist_ok=True)
        return tools_dir
    
    def list_projects(self) -> List[Dict[str, str]]:
        """List all projects with basic info."""
        projects = []
        for path in self.projects_dir.glob("*.yaml"):
            try:
                with open(path) as f:
                    data = yaml.safe_load(f)
                    projects.append({
                        "id": data.get("id", path.stem),
                        "name": data.get("name", path.stem),
                        "description": data.get("description", ""),
                    })
            except Exception:
                continue
        return projects
    
    def get_project(self, project_id: str) -> Optional[Project]:
        """Load a project by ID."""
        if project_id in self._cache:
            return self._cache[project_id]
        
        path = self._project_path(project_id)
        if not path.exists():
            return None
        
        try:
            with open(path) as f:
                data = yaml.safe_load(f)
            project = Project.model_validate(data)
            self._cache[project_id] = project
            return project
        except Exception as e:
            print(f"Error loading project {project_id}: {e}")
            return None
    
    def save_project(self, project: Project) -> bool:
        """Save a project to disk."""
        try:
            path = self._project_path(project.id)
            data = project.model_dump(mode="json")
            with open(path, "w") as f:
                yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)
            self._cache[project.id] = project
            
            # Also save custom tools as separate Python files
            self._save_custom_tools(project)
            # Also save custom callbacks as separate Python files
            self._save_custom_callbacks(project)
            return True
        except Exception as e:
            print(f"Error saving project {project.id}: {e}")
            return False
    
    def create_project(self, name: str, description: str = "") -> Project:
        """Create a new project with defaults."""
        project_id = str(uuid.uuid4())[:8]
        
        app = AppConfig(
            id=f"app_{project_id}",
            name=name,
        )
        
        project = Project(
            id=project_id,
            name=name,
            description=description,
            app=app,
        )
        
        self.save_project(project)
        return project
    
    def delete_project(self, project_id: str) -> bool:
        """Delete a project."""
        try:
            path = self._project_path(project_id)
            if path.exists():
                path.unlink()
            
            # Remove tools directory
            tools_dir = self._tools_dir(project_id)
            if tools_dir.exists():
                import shutil
                shutil.rmtree(tools_dir.parent)
            
            if project_id in self._cache:
                del self._cache[project_id]
            
            return True
        except Exception as e:
            print(f"Error deleting project {project_id}: {e}")
            return False
    
    def _save_custom_tools(self, project: Project) -> None:
        """Save custom tools as Python files for execution."""
        tools_dir = self._tools_dir(project.id)
        
        # Group tools by module path
        modules: Dict[str, List[CustomToolDefinition]] = {}
        for tool in project.custom_tools:
            parts = tool.module_path.rsplit(".", 1)
            if len(parts) == 2:
                module_name = parts[0]
            else:
                module_name = "tools"
            
            if module_name not in modules:
                modules[module_name] = []
            modules[module_name].append(tool)
        
        # Create Python files for each module
        for module_name, tools in modules.items():
            # Convert dots to directory structure
            module_parts = module_name.split(".")
            module_dir = tools_dir
            for part in module_parts[:-1]:
                module_dir = module_dir / part
                module_dir.mkdir(parents=True, exist_ok=True)
                # Create __init__.py
                init_file = module_dir / "__init__.py"
                if not init_file.exists():
                    init_file.write_text("")
            
            # Write the module file
            file_name = f"{module_parts[-1]}.py" if module_parts else "tools.py"
            file_path = module_dir / file_name
            
            code_lines = [
                '"""Auto-generated custom tools module."""',
                "",
                "from google.adk.tools import ToolContext",
                "from typing import Any, Optional",
                "",
            ]
            
            for tool in tools:
                code_lines.append(f"# Tool: {tool.name}")
                code_lines.append(f'# Description: {tool.description}')
                code_lines.append(f"# State keys used: {', '.join(tool.state_keys_used)}")
                code_lines.append("")
                code_lines.append(tool.code)
                code_lines.append("")
            
            file_path.write_text("\n".join(code_lines))
    
    def get_project_yaml(self, project_id: str) -> Optional[str]:
        """Get project as YAML string."""
        project = self.get_project(project_id)
        if not project:
            return None
        
        # Convert project to dict for YAML serialization
        data = project.model_dump(mode="json")
        
        # Fix callback module_paths to include function names
        # ADK expects full paths like "module.path.function_name"
        for agent in data.get("agents", []):
            if agent.get("type") == "LlmAgent":
                callback_types = [
                    "before_agent_callbacks", "after_agent_callbacks",
                    "before_model_callbacks", "after_model_callbacks",
                    "before_tool_callbacks", "after_tool_callbacks"
                ]
                for callback_type in callback_types:
                    callbacks = agent.get(callback_type, [])
                    for callback in callbacks:
                        module_path = callback.get("module_path", "")
                        # Find the callback definition to get the function name
                        callback_def = None
                        for cb in project.custom_callbacks:
                            if cb.module_path == module_path:
                                callback_def = cb
                                break
                        if callback_def:
                            # Update module_path to include function name
                            callback["module_path"] = f"{module_path}.{callback_def.name}"
        
        return yaml.safe_dump(
            data,
            default_flow_style=False,
            sort_keys=False
        )
    
    def update_project_from_yaml(self, project_id: str, yaml_content: str) -> Optional[Project]:
        """Update a project from YAML content."""
        try:
            data = yaml.safe_load(yaml_content)
            data["id"] = project_id  # Preserve the ID
            
            # Parse callback module_paths that include function names
            # Convert "module.path.function_name" back to just "module.path" for internal storage
            for agent in data.get("agents", []):
                if agent.get("type") == "LlmAgent":
                    callback_types = [
                        "before_agent_callbacks", "after_agent_callbacks",
                        "before_model_callbacks", "after_model_callbacks",
                        "before_tool_callbacks", "after_tool_callbacks"
                    ]
                    for callback_type in callback_types:
                        callbacks = agent.get(callback_type, [])
                        for callback in callbacks:
                            full_path = callback.get("module_path", "")
                            # If it contains a dot, try to parse as module.function
                            if '.' in full_path:
                                parts = full_path.rsplit('.', 1)
                                if len(parts) == 2:
                                    # Check if the last part matches a callback function name
                                    possible_module_path, possible_func_name = parts
                                    # Try to find matching callback definition
                                    callback_found = False
                                    for cb_def in data.get("custom_callbacks", []):
                                        if (cb_def.get("module_path") == possible_module_path and 
                                            cb_def.get("name") == possible_func_name):
                                            # This is a full path, extract just the module part
                                            callback["module_path"] = possible_module_path
                                            callback_found = True
                                            break
                                    # If not found, keep as-is (might be a different format)
                                    if not callback_found:
                                        callback["module_path"] = full_path
            
            project = Project.model_validate(data)
            self.save_project(project)
            return project
        except Exception as e:
            print(f"Error updating project from YAML: {e}")
            return None


    def _save_custom_callbacks(self, project: Project) -> None:
        """Save custom callbacks as Python files for execution."""
        callbacks_dir = self.projects_dir / project.id / "callbacks"
        callbacks_dir.mkdir(parents=True, exist_ok=True)
        
        # Group callbacks by module path
        # The module_path format is: "module.path.function_name"
        # We need to extract the module path (everything except the function name)
        modules: Dict[str, List[CustomCallbackDefinition]] = {}
        for callback in project.custom_callbacks:
            # Split module_path to get module and function name
            # e.g., "callbacks.custom" -> module="callbacks", func="custom"
            # But we need to save it so the module can be imported correctly
            parts = callback.module_path.rsplit(".", 1)
            if len(parts) == 2:
                # If module_path is "callbacks.custom", we want to save as "callbacks/custom.py"
                # So the module name for grouping is the full path without the function
                # But actually, we need to save it so "callbacks.custom" can be imported
                # Let's use the first part as the directory and second part as filename
                module_prefix = parts[0]  # "callbacks"
                func_name = parts[1]  # "custom" (but this should match callback.name)
            else:
                # If no dot, assume it's just a function name in the default "callbacks" module
                module_prefix = "callbacks"
                func_name = callback.module_path
            
            # Group by the module prefix (directory)
            if module_prefix not in modules:
                modules[module_prefix] = []
            modules[module_prefix].append(callback)
        
        # Create Python files for each module
        for module_prefix, callbacks_list in modules.items():
            # Create directory structure
            # If module_prefix is "callbacks", files go directly in callbacks_dir
            # If module_prefix is "callbacks.submodule", create submodule directory
            module_parts = module_prefix.split(".")
            if module_parts == ["callbacks"]:
                # Special case: "callbacks" prefix means files go directly in callbacks_dir
                module_dir = callbacks_dir
            else:
                # Create subdirectories for nested modules
                module_dir = callbacks_dir
                for part in module_parts:
                    module_dir = module_dir / part
                    module_dir.mkdir(parents=True, exist_ok=True)
                    # Create __init__.py
                    init_file = module_dir / "__init__.py"
                    if not init_file.exists():
                        init_file.write_text("")
            
            # For each callback, determine the filename from the module_path
            # If module_path is "callbacks.custom", save as "callbacks/custom.py"
            callback_files: Dict[str, List[CustomCallbackDefinition]] = {}
            for callback in callbacks_list:
                parts = callback.module_path.rsplit(".", 1)
                if len(parts) == 2:
                    # Use the last part as the filename (e.g., "callbacks.custom" -> "custom.py")
                    file_key = parts[1]  # This will be the filename without .py
                else:
                    # Fallback to callback name
                    file_key = callback.name
                
                if file_key not in callback_files:
                    callback_files[file_key] = []
                callback_files[file_key].append(callback)
            
            # Create a file for each unique file_key
            for file_key, callbacks_in_file in callback_files.items():
                file_path = module_dir / f"{file_key}.py"
            
            code_lines = [
                '"""Auto-generated custom callbacks module."""',
                "",
                "from google.adk.agents.callback_context import CallbackContext",
                    "from google.adk.models.llm_response import LlmResponse",
                "from typing import Optional",
                "",
            ]
            
            for callback in callbacks_in_file:
                code_lines.append(f"# Callback: {callback.name}")
                # Handle multi-line descriptions properly - each line must be a comment
                if callback.description:
                    desc_lines = callback.description.split('\n')
                    for desc_line in desc_lines:
                        # Ensure each line is properly commented
                        code_lines.append(f'# Description: {desc_line}')
                else:
                    code_lines.append('# Description: (no description)')
                    code_lines.append(f"# State keys used: {', '.join(callback.state_keys_used) if callback.state_keys_used else 'none'}")
                code_lines.append("")
                code_lines.append(callback.code)
                code_lines.append("")
            
            file_path.write_text("\n".join(code_lines))

    # =========================================================================
    # Backup System
    # =========================================================================
    
    def _load_backup_hashes(self) -> None:
        """Load the hash of the last backup for each project."""
        for path in self.projects_dir.glob("*.yaml"):
            project_id = path.stem
            # Find the most recent backup and compute its hash
            backup_pattern = f"{project_id}_*.yaml.gz"
            backups = list(self._backup_dir.glob(backup_pattern))
            if backups:
                # Get the most recent backup
                latest = max(backups, key=lambda p: p.stat().st_mtime)
                try:
                    with gzip.open(latest, 'rt') as f:
                        content = f.read()
                    self._last_backup_hashes[project_id] = hashlib.md5(content.encode()).hexdigest()
                except Exception:
                    pass
    
    def _compute_file_hash(self, path: Path) -> Optional[str]:
        """Compute MD5 hash of a file's content."""
        if not path.exists():
            return None
        try:
            with open(path, 'r') as f:
                content = f.read()
            return hashlib.md5(content.encode()).hexdigest()
        except Exception:
            return None
    
    def _backup_project(self, project_id: str) -> bool:
        """Create a gzipped backup of a project if it has changed."""
        path = self._project_path(project_id)
        if not path.exists():
            return False
        
        current_hash = self._compute_file_hash(path)
        if not current_hash:
            return False
        
        # Check if changed since last backup
        last_hash = self._last_backup_hashes.get(project_id)
        if current_hash == last_hash:
            return False  # No change, no backup needed
        
        # Create backup with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"{project_id}_{timestamp}.yaml.gz"
        backup_path = self._backup_dir / backup_name
        
        try:
            # Read the original file
            with open(path, 'r') as f:
                content = f.read()
            
            # Write gzipped backup
            with gzip.open(backup_path, 'wt') as f:
                f.write(content)
            
            # Update hash
            self._last_backup_hashes[project_id] = current_hash
            
            logger.info(f"Backup created: {backup_name}")
            
            # Cleanup old backups (keep last 50 per project)
            self._cleanup_old_backups(project_id, keep=50)
            
            return True
        except Exception as e:
            logger.error(f"Failed to backup project {project_id}: {e}")
            return False
    
    def _cleanup_old_backups(self, project_id: str, keep: int = 50) -> None:
        """Remove old backups, keeping only the most recent N."""
        backup_pattern = f"{project_id}_*.yaml.gz"
        backups = list(self._backup_dir.glob(backup_pattern))
        
        if len(backups) <= keep:
            return
        
        # Sort by modification time (oldest first)
        backups.sort(key=lambda p: p.stat().st_mtime)
        
        # Remove oldest backups
        for backup in backups[:-keep]:
            try:
                backup.unlink()
                logger.debug(f"Removed old backup: {backup.name}")
            except Exception:
                pass
    
    async def _backup_loop(self) -> None:
        """Background task that checks for changes and backs up every minute."""
        while self._backup_running:
            try:
                # Check all projects
                for path in self.projects_dir.glob("*.yaml"):
                    project_id = path.stem
                    self._backup_project(project_id)
            except Exception as e:
                logger.error(f"Backup loop error: {e}")
            
            # Wait 60 seconds
            await asyncio.sleep(60)
    
    def start_backup_service(self) -> None:
        """Start the automatic backup service."""
        if self._backup_running:
            return
        
        self._backup_running = True
        try:
            loop = asyncio.get_running_loop()
            self._backup_task = loop.create_task(self._backup_loop())
            logger.info("Backup service started (checking every 60 seconds)")
        except RuntimeError:
            # No running loop - will be started later when there is one
            logger.debug("No event loop yet, backup service will start when loop is available")
    
    def stop_backup_service(self) -> None:
        """Stop the automatic backup service."""
        self._backup_running = False
        if self._backup_task:
            self._backup_task.cancel()
            self._backup_task = None
        logger.info("Backup service stopped")
    
    def list_backups(self, project_id: str) -> List[Dict[str, any]]:
        """List available backups for a project."""
        backup_pattern = f"{project_id}_*.yaml.gz"
        backups = []
        
        for path in self._backup_dir.glob(backup_pattern):
            try:
                # Parse timestamp from filename: project_id_YYYYMMDD_HHMMSS.yaml.gz
                name = path.stem.replace('.yaml', '')  # Remove .yaml from .yaml.gz
                parts = name.split('_')
                if len(parts) >= 3:
                    date_str = parts[-2]  # YYYYMMDD
                    time_str = parts[-1]  # HHMMSS
                    timestamp = datetime.strptime(f"{date_str}_{time_str}", "%Y%m%d_%H%M%S")
                else:
                    timestamp = datetime.fromtimestamp(path.stat().st_mtime)
                
                backups.append({
                    "filename": path.name,
                    "timestamp": timestamp.isoformat(),
                    "size": path.stat().st_size,
                })
            except Exception:
                continue
        
        # Sort by timestamp descending (newest first)
        backups.sort(key=lambda b: b["timestamp"], reverse=True)
        return backups
    
    def restore_backup(self, project_id: str, backup_filename: str) -> Optional[Project]:
        """Restore a project from a backup."""
        backup_path = self._backup_dir / backup_filename
        
        if not backup_path.exists():
            logger.error(f"Backup not found: {backup_filename}")
            return None
        
        try:
            # Read and decompress
            with gzip.open(backup_path, 'rt') as f:
                content = f.read()
            
            # Parse and validate
            data = yaml.safe_load(content)
            data["id"] = project_id  # Ensure ID matches
            project = Project.model_validate(data)
            
            # Save as current project (this will trigger a new backup)
            self.save_project(project)
            
            logger.info(f"Restored project {project_id} from {backup_filename}")
            return project
        except Exception as e:
            logger.error(f"Failed to restore backup {backup_filename}: {e}")
            return None


# Singleton instance - uses same default path logic as main.py
def _get_projects_dir() -> Path:
    """Get projects directory from environment or default."""
    env_dir = os.environ.get("ADK_PLAYGROUND_PROJECTS_DIR")
    if env_dir:
        return Path(env_dir)
    return Path.home() / ".adk-playground" / "projects"


# Module-level singleton for imports from other modules
project_manager = ProjectManager(str(_get_projects_dir()))
