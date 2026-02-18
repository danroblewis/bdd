# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""A filesystem-based session service for ADK.

This session service stores sessions as JSON files in a directory structure:

    {base_dir}/
        {app_name}/
            _app_state.json              # App-level state
            {user_id}/
                _user_state.json         # User-level state
                {session_id}.json        # Session with events

Usage:
    from file_session_service import FileSessionService
    
    session_service = FileSessionService(base_dir="./sessions")
    
    # Or use with adk web via services.py:
    # session_service_uri = "file://./sessions"
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Optional
import uuid

from typing_extensions import override

from google.adk.sessions import _session_util
from google.adk.errors.already_exists_error import AlreadyExistsError
from google.adk.events.event import Event
from google.adk.sessions.base_session_service import BaseSessionService
from google.adk.sessions.base_session_service import GetSessionConfig
from google.adk.sessions.base_session_service import ListSessionsResponse
from google.adk.sessions.session import Session
from google.adk.sessions.state import State

logger = logging.getLogger('google_adk.' + __name__)


class FileSessionService(BaseSessionService):
    """A session service that stores sessions as JSON files on the filesystem.
    
    This is suitable for development, testing, and small-scale deployments.
    For production use with high concurrency, consider using a database-backed
    session service.
    
    Directory structure:
        {base_dir}/
            {app_name}/
                _app_state.json
                {user_id}/
                    _user_state.json
                    {session_id}.json
    """
    
    APP_STATE_FILENAME = "_app_state.json"
    USER_STATE_FILENAME = "_user_state.json"
    
    def __init__(self, base_dir: str = "./sessions"):
        """Initialize the file session service.
        
        Args:
            base_dir: The base directory for storing session files.
        """
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
    
    def _app_dir(self, app_name: str) -> Path:
        """Get the directory for an app."""
        return self.base_dir / self._safe_filename(app_name)
    
    def _user_dir(self, app_name: str, user_id: str) -> Path:
        """Get the directory for a user."""
        return self._app_dir(app_name) / self._safe_filename(user_id)
    
    def _session_path(self, app_name: str, user_id: str, session_id: str) -> Path:
        """Get the path for a session file."""
        return self._user_dir(app_name, user_id) / f"{self._safe_filename(session_id)}.json"
    
    def _app_state_path(self, app_name: str) -> Path:
        """Get the path for app state file."""
        return self._app_dir(app_name) / self.APP_STATE_FILENAME
    
    def _user_state_path(self, app_name: str, user_id: str) -> Path:
        """Get the path for user state file."""
        return self._user_dir(app_name, user_id) / self.USER_STATE_FILENAME
    
    @staticmethod
    def _safe_filename(name: str) -> str:
        """Convert a name to a safe filename."""
        # Replace problematic characters with underscores
        return "".join(c if c.isalnum() or c in "-_." else "_" for c in name)
    
    def _read_json(self, path: Path) -> Optional[dict]:
        """Read a JSON file."""
        if not path.exists():
            return None
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Failed to read {path}: {e}")
            return None
    
    def _write_json(self, path: Path, data: dict) -> None:
        """Write a JSON file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, default=str)
    
    def _load_app_state(self, app_name: str) -> dict[str, Any]:
        """Load app-level state."""
        data = self._read_json(self._app_state_path(app_name))
        return data or {}
    
    def _save_app_state(self, app_name: str, state: dict[str, Any]) -> None:
        """Save app-level state."""
        self._write_json(self._app_state_path(app_name), state)
    
    def _load_user_state(self, app_name: str, user_id: str) -> dict[str, Any]:
        """Load user-level state."""
        data = self._read_json(self._user_state_path(app_name, user_id))
        return data or {}
    
    def _save_user_state(self, app_name: str, user_id: str, state: dict[str, Any]) -> None:
        """Save user-level state."""
        self._write_json(self._user_state_path(app_name, user_id), state)
    
    def _load_session(self, app_name: str, user_id: str, session_id: str) -> tuple[Optional[Session], Optional[list]]:
        """Load a session from disk.
        
        Returns:
            Tuple of (Session, run_events) where run_events is a list of RunEvent dicts
            or None if not present
        """
        data = self._read_json(self._session_path(app_name, user_id, session_id))
        if data is None:
            return None, None
        
        # Extract RunEvents metadata before validation
        run_events = data.pop("_run_events", None)
        
        # Clean up event data to handle schema mismatches
        # Some fields like interactionId may be present but not allowed by the model
        if "events" in data and data["events"]:
            for event in data["events"]:
                # Remove fields that may cause validation errors
                event.pop("interactionId", None)
                event.pop("modelVersion", None)
                # Remove None values for optional fields that Pydantic doesn't like
                keys_to_remove = [k for k, v in event.items() if v is None]
                for k in keys_to_remove:
                    if k not in ["content", "author", "timestamp"]:  # Keep required fields even if None
                        event.pop(k, None)
        
        try:
            session = Session.model_validate(data)
            return session, run_events
        except Exception as e:
            logger.warning(f"Failed to parse session {session_id}: {e}")
            return None, None
    
    def _save_session(self, session: Session, run_events: Optional[list] = None) -> None:
        """Save a session to disk.
        
        Args:
            session: The ADK Session to save
            run_events: Optional list of RunEvent dicts to store as metadata
        """
        path = self._session_path(session.app_name, session.user_id, session.id)
        data = session.model_dump(mode='json', by_alias=True)
        
        # Store RunEvents as metadata if provided
        if run_events is not None:
            data["_run_events"] = run_events
        
        self._write_json(path, data)
    
    def _merge_state(self, app_name: str, user_id: str, session: Session) -> Session:
        """Merge app and user state into session state."""
        # Merge app state
        app_state = self._load_app_state(app_name)
        for key, value in app_state.items():
            session.state[State.APP_PREFIX + key] = value
        
        # Merge user state
        user_state = self._load_user_state(app_name, user_id)
        for key, value in user_state.items():
            session.state[State.USER_PREFIX + key] = value
        
        return session
    
    @override
    async def create_session(
        self,
        *,
        app_name: str,
        user_id: str,
        state: Optional[dict[str, Any]] = None,
        session_id: Optional[str] = None,
    ) -> Session:
        """Create a new session."""
        async with self._lock:
            # Check if session already exists
            session_id = (
                session_id.strip()
                if session_id and session_id.strip()
                else str(uuid.uuid4())
            )
            
            existing, _ = self._load_session(app_name, user_id, session_id)
            if existing:
                raise AlreadyExistsError(f'Session with id {session_id} already exists.')
            
            # Extract state deltas
            state_deltas = _session_util.extract_state_delta(state or {})
            app_state_delta = state_deltas['app']
            user_state_delta = state_deltas['user']
            session_state = state_deltas['session']
            
            # Update app state
            if app_state_delta:
                app_state = self._load_app_state(app_name)
                app_state.update(app_state_delta)
                self._save_app_state(app_name, app_state)
            
            # Update user state
            if user_state_delta:
                user_state = self._load_user_state(app_name, user_id)
                user_state.update(user_state_delta)
                self._save_user_state(app_name, user_id, user_state)
            
            # Create session
            session = Session(
                app_name=app_name,
                user_id=user_id,
                id=session_id,
                state=session_state or {},
                last_update_time=time.time(),
            )
            
            # Save to disk
            self._save_session(session)
            
            # Return with merged state
            return self._merge_state(app_name, user_id, copy.deepcopy(session))
    
    @override
    async def get_session(
        self,
        *,
        app_name: str,
        user_id: str,
        session_id: str,
        config: Optional[GetSessionConfig] = None,
    ) -> Optional[Session]:
        """Get a session."""
        session, _ = self._load_session(app_name, user_id, session_id)
        if session is None:
            return None
        
        # Apply config filters
        if config:
            if config.num_recent_events:
                session.events = session.events[-config.num_recent_events:]
            if config.after_timestamp:
                i = len(session.events) - 1
                while i >= 0:
                    if session.events[i].timestamp < config.after_timestamp:
                        break
                    i -= 1
                if i >= 0:
                    session.events = session.events[i + 1:]
        
        return self._merge_state(app_name, user_id, session)
    
    @override
    async def list_sessions(
        self, *, app_name: str, user_id: Optional[str] = None
    ) -> ListSessionsResponse:
        """List sessions for an app/user."""
        sessions = []
        
        app_dir = self._app_dir(app_name)
        if not app_dir.exists():
            return ListSessionsResponse(sessions=[])
        
        # Get list of user directories
        if user_id is not None:
            user_dirs = [self._user_dir(app_name, user_id)]
        else:
            user_dirs = [d for d in app_dir.iterdir() if d.is_dir()]
        
        for user_dir in user_dirs:
            if not user_dir.exists():
                continue
            
            # Find session files
            for session_file in user_dir.glob("*.json"):
                if session_file.name.startswith("_"):
                    continue  # Skip state files
                
                session_id = session_file.stem
                actual_user_id = user_dir.name
                
                session, _ = self._load_session(app_name, actual_user_id, session_id)
                if session:
                    # Clear events for list response
                    session.events = []
                    session = self._merge_state(app_name, actual_user_id, session)
                    sessions.append(session)
        
        return ListSessionsResponse(sessions=sessions)
    
    @override
    async def delete_session(
        self, *, app_name: str, user_id: str, session_id: str
    ) -> None:
        """Delete a session."""
        async with self._lock:
            path = self._session_path(app_name, user_id, session_id)
            if path.exists():
                path.unlink()
    
    @override
    async def append_event(self, session: Session, event: Event) -> Event:
        """Append an event to a session."""
        if event.partial:
            return event
        
        async with self._lock:
            app_name = session.app_name
            user_id = session.user_id
            session_id = session.id
            
            # Load current session from disk
            storage_session, run_events = self._load_session(app_name, user_id, session_id)
            if storage_session is None:
                logger.warning(f'Session {session_id} not found on disk')
                return event
            
            # Update the in-memory session
            await super().append_event(session=session, event=event)
            session.last_update_time = event.timestamp
            
            # Update storage session
            storage_session.events.append(event)
            storage_session.last_update_time = event.timestamp
            
            # Handle state deltas
            if event.actions and event.actions.state_delta:
                state_deltas = _session_util.extract_state_delta(
                    event.actions.state_delta
                )
                
                # Update app state
                if state_deltas['app']:
                    app_state = self._load_app_state(app_name)
                    app_state.update(state_deltas['app'])
                    self._save_app_state(app_name, app_state)
                
                # Update user state
                if state_deltas['user']:
                    user_state = self._load_user_state(app_name, user_id)
                    user_state.update(state_deltas['user'])
                    self._save_user_state(app_name, user_id, user_state)
                
                # Update session state
                if state_deltas['session']:
                    storage_session.state.update(state_deltas['session'])
            
            # Save updated session (preserve existing run_events if any)
            self._save_session(storage_session, run_events=run_events)
            
            return event
    
    def save_run_events(self, app_name: str, user_id: str, session_id: str, run_events: list[dict]) -> None:
        """Save RunEvents as metadata for a session.
        
        Args:
            app_name: The app name
            user_id: The user ID
            session_id: The session ID
            run_events: List of RunEvent dicts to save
        """
        session, existing_run_events = self._load_session(app_name, user_id, session_id)
        if session is None:
            logger.warning(f"Cannot save run_events: session {session_id} not found")
            return
        
        # Merge with existing run_events if any
        if existing_run_events:
            # Combine and sort by timestamp
            all_events = existing_run_events + run_events
            all_events.sort(key=lambda e: e.get("timestamp", 0))
            run_events = all_events
        
        self._save_session(session, run_events=run_events)
    
    def get_run_events(self, app_name: str, user_id: str, session_id: str) -> Optional[list[dict]]:
        """Get RunEvents metadata for a session.
        
        Args:
            app_name: The app name
            user_id: The user ID
            session_id: The session ID
            
        Returns:
            List of RunEvent dicts, or None if not found
        """
        _, run_events = self._load_session(app_name, user_id, session_id)
        return run_events


# Factory function for use with ADK services.py
def create_file_session_service(uri: str) -> FileSessionService:
    """Create a FileSessionService from a URI.
    
    URI format: file://{path}
    
    Example:
        file://./sessions
        file:///absolute/path/to/sessions
    """
    if uri.startswith("file://"):
        path = uri[7:]  # Remove "file://" prefix
    else:
        path = uri
    
    return FileSessionService(base_dir=path)

