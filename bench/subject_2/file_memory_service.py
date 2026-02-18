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

"""A filesystem-based memory service for ADK.

Stores session memories as JSON files organized by app_name/user_id.
Uses keyword matching for search (like InMemoryMemoryService).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from google.genai import types
from typing_extensions import override

from google.adk.memory.base_memory_service import BaseMemoryService
from google.adk.memory.base_memory_service import SearchMemoryResponse
from google.adk.memory.memory_entry import MemoryEntry

if TYPE_CHECKING:
    from google.adk.events.event import Event
    from google.adk.sessions.session import Session

logger = logging.getLogger('google_adk.' + __name__)


def _format_timestamp(timestamp: float) -> str:
    """Formats the timestamp of the memory entry."""
    return datetime.fromtimestamp(timestamp).isoformat()


def _extract_words_lower(text: str) -> set[str]:
    """Extracts words from a string and converts them to lowercase."""
    return set([word.lower() for word in re.findall(r'[A-Za-z]+', text)])


def _user_key(app_name: str, user_id: str) -> str:
    """Creates a key for the user's memory storage."""
    return f'{app_name}/{user_id}'


class FileMemoryService(BaseMemoryService):
    """A filesystem-based memory service.

    Stores session memories as JSON files organized by:
        {base_dir}/
            {app_name}/
                {user_id}/
                    {session_id}.json

    Each session file contains a list of event data with content parts.
    Uses keyword matching for search (like InMemoryMemoryService).
    """

    def __init__(self, base_dir: str = "./adk_memory"):
        """Initializes the file-based memory service.

        Args:
            base_dir: The directory that will contain memory data.
        """
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()

    def _get_user_dir(self, app_name: str, user_id: str) -> Path:
        """Returns the directory for a user's memories."""
        return self.base_dir / app_name / user_id

    def _get_session_file(self, app_name: str, user_id: str, session_id: str) -> Path:
        """Returns the path to a session's memory file."""
        return self._get_user_dir(app_name, user_id) / f"{session_id}.json"

    def _read_json_file(self, path: Path) -> list[dict[str, Any]]:
        """Reads a JSON file and returns its contents."""
        if path.exists():
            try:
                return json.loads(path.read_text())
            except json.JSONDecodeError as e:
                logger.error(f"Error decoding JSON from {path}: {e}")
                return []
        return []

    def _write_json_file(self, path: Path, data: list[dict[str, Any]]):
        """Writes data to a JSON file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2))

    def _serialize_content(self, content: types.Content) -> dict[str, Any]:
        """Serializes a Content object to a dict."""
        parts_data = []
        for part in (content.parts or []):
            part_data = {}
            if part.text is not None:
                part_data['text'] = part.text
            if part.inline_data:
                # Skip binary data in memory storage - just store text
                pass
            if part_data:
                parts_data.append(part_data)
        
        return {
            'role': content.role,
            'parts': parts_data
        }

    def _deserialize_content(self, data: dict[str, Any]) -> types.Content:
        """Deserializes a dict to a Content object."""
        parts = []
        for part_data in data.get('parts', []):
            if 'text' in part_data:
                parts.append(types.Part.from_text(text=part_data['text']))
        
        return types.Content(
            role=data.get('role', 'user'),
            parts=parts
        )

    @override
    async def add_session_to_memory(self, session: "Session"):
        """Adds a session to the memory service.

        Extracts events with content and stores them to disk.

        Args:
            session: The session to add.
        """
        events_data = []
        for event in session.events:
            if event.content and event.content.parts:
                # Only store events that have text content
                has_text = any(
                    part.text for part in event.content.parts if part.text
                )
                if not has_text:
                    continue
                
                events_data.append({
                    'author': event.author,
                    'timestamp': event.timestamp,
                    'content': self._serialize_content(event.content)
                })

        if events_data:
            session_file = self._get_session_file(
                session.app_name, session.user_id, session.id
            )
            async with self._lock:
                self._write_json_file(session_file, events_data)
                logger.debug(
                    f"Saved {len(events_data)} memory events to {session_file}"
                )

    @override
    async def search_memory(
        self, *, app_name: str, user_id: str, query: str
    ) -> SearchMemoryResponse:
        """Searches for memories that match the query.

        Uses keyword matching (same algorithm as InMemoryMemoryService).

        Args:
            app_name: The name of the application.
            user_id: The id of the user.
            query: The query to search for.

        Returns:
            A SearchMemoryResponse containing the matching memories.
        """
        user_dir = self._get_user_dir(app_name, user_id)
        words_in_query = _extract_words_lower(query)
        response = SearchMemoryResponse()

        if not user_dir.exists():
            return response

        async with self._lock:
            # Iterate through all session files for this user
            for session_file in user_dir.glob("*.json"):
                events_data = self._read_json_file(session_file)
                
                for event_data in events_data:
                    content_data = event_data.get('content', {})
                    parts = content_data.get('parts', [])
                    
                    # Extract text from all parts
                    text_content = ' '.join([
                        part.get('text', '') 
                        for part in parts 
                        if part.get('text')
                    ])
                    
                    if not text_content:
                        continue
                    
                    words_in_event = _extract_words_lower(text_content)
                    
                    # Check if any query word matches
                    if any(query_word in words_in_event for query_word in words_in_query):
                        content = self._deserialize_content(content_data)
                        timestamp = event_data.get('timestamp', 0)
                        
                        response.memories.append(
                            MemoryEntry(
                                content=content,
                                author=event_data.get('author'),
                                timestamp=_format_timestamp(timestamp) if timestamp else None,
                            )
                        )

        return response


def create_file_memory_service(uri: str) -> FileMemoryService:
    """Factory function to create a FileMemoryService from a URI.

    Args:
        uri: A file:// URI specifying the storage directory.
             Example: file://./memory or file:///absolute/path

    Returns:
        A configured FileMemoryService instance.
    """
    if uri.startswith("file://"):
        path = uri[7:]  # Remove "file://" prefix
    else:
        path = uri
    
    return FileMemoryService(base_dir=path)

