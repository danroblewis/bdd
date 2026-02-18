"""Knowledge Service - Vector database for semantic search.

This service provides vector databases for storing and retrieving
knowledge entries using semantic similarity search.
Supports multiple named stores per project.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import aiohttp
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# Try to import google.genai for embeddings
try:
    from google.genai import Client
    from google.genai.types import EmbedContentConfig
    EMBEDDINGS_AVAILABLE = True
except ImportError:
    EMBEDDINGS_AVAILABLE = False
    logger.warning("google-genai not installed for embeddings")


@dataclass
class KnowledgeEntry:
    """A single entry in the knowledge base."""
    id: str
    text: str
    embedding: List[float] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    source_id: str = ""  # Reference to source config
    source_name: str = ""  # Display name
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "embedding": self.embedding,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "source_id": self.source_id,
            "source_name": self.source_name,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "KnowledgeEntry":
        return cls(
            id=data["id"],
            text=data["text"],
            embedding=data.get("embedding", []),
            metadata=data.get("metadata", {}),
            created_at=data.get("created_at", time.time()),
            source_id=data.get("source_id", ""),
            source_name=data.get("source_name", data.get("source", "")),
        )


@dataclass
class SearchResult:
    """A search result with similarity score."""
    entry: KnowledgeEntry
    score: float  # Cosine similarity, 0-1


class SkillSetStore:
    """A single vector store for a SkillSet.
    
    Each SkillSet has its own store with its own entries.
    """
    
    def __init__(
        self,
        project_id: str,
        skillset_id: str,
        storage_path: Path,
        model_name: str = "text-embedding-004",
        output_dimensionality: Optional[int] = None,
    ):
        self.project_id = project_id
        self.skillset_id = skillset_id
        self.storage_path = storage_path
        self.model_name = model_name
        self.output_dimensionality = output_dimensionality
        
        self._entries: Dict[str, KnowledgeEntry] = {}
        self._client: Optional[Client] = None
        self._embedding_dim: int = output_dimensionality or 768  # Default Gemini embedding size
        
        # Load existing entries
        self._load()
    
    def _get_client(self) -> Optional[Client]:
        """Lazy-load the Google GenAI client."""
        if not EMBEDDINGS_AVAILABLE:
            return None
        if self._client is None:
            logger.info(f"Initializing GenAI client for embeddings: {self.model_name}")
            self._client = Client()
        return self._client
    
    def _generate_id(self, text: str) -> str:
        """Generate a unique ID for text content."""
        return hashlib.sha256(text.encode()).hexdigest()[:16]
    
    def _embed(self, text: str) -> List[float]:
        """Generate embedding for text using LLM API."""
        client = self._get_client()
        if client is None:
            return []
        try:
            config = EmbedContentConfig()
            if self.output_dimensionality:
                config.output_dimensionality = self.output_dimensionality
            
            response = client.models.embed_content(
                model=self.model_name,
                contents=[text],
                config=config,
            )
            if response.embeddings:
                return list(response.embeddings[0].values)
            return []
        except Exception as e:
            logger.error(f"Embedding failed: {e}")
            return []
    
    def _embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for multiple texts using LLM API."""
        client = self._get_client()
        if client is None:
            return [[] for _ in texts]
        try:
            config = EmbedContentConfig()
            if self.output_dimensionality:
                config.output_dimensionality = self.output_dimensionality
            
            response = client.models.embed_content(
                model=self.model_name,
                contents=texts,
                config=config,
            )
            return [list(e.values) for e in response.embeddings]
        except Exception as e:
            logger.error(f"Batch embedding failed: {e}")
            return [[] for _ in texts]
    
    def _cosine_similarity(
        self, 
        query_embedding: List[float], 
        entry_embeddings: np.ndarray
    ) -> np.ndarray:
        """Compute cosine similarity between query and all entries."""
        if len(query_embedding) == 0 or len(entry_embeddings) == 0:
            return np.array([])
        
        query = np.array(query_embedding)
        query_norm = np.linalg.norm(query)
        if query_norm == 0:
            return np.zeros(len(entry_embeddings))
        
        query = query / query_norm
        norms = np.linalg.norm(entry_embeddings, axis=1, keepdims=True)
        norms[norms == 0] = 1
        normalized = entry_embeddings / norms
        similarities = np.dot(normalized, query)
        return similarities
    
    def _get_index_file(self) -> Path:
        """Get the index file path for this store."""
        return self.storage_path / f"{self.skillset_id}.json"
    
    def _load(self) -> None:
        """Load entries from disk."""
        index_file = self._get_index_file()
        if index_file.exists():
            try:
                with open(index_file, "r") as f:
                    data = json.load(f)
                    for entry_data in data.get("entries", []):
                        entry = KnowledgeEntry.from_dict(entry_data)
                        self._entries[entry.id] = entry
                logger.info(f"Loaded {len(self._entries)} entries for skillset {self.skillset_id}")
            except Exception as e:
                logger.error(f"Failed to load skillset index: {e}")
    
    def _save(self) -> None:
        """Save entries to disk."""
        self.storage_path.mkdir(parents=True, exist_ok=True)
        index_file = self._get_index_file()
        try:
            data = {
                "entries": [e.to_dict() for e in self._entries.values()],
                "model_name": self.model_name,
                "updated_at": time.time(),
            }
            with open(index_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save skillset index: {e}")
    
    def add(
        self,
        text: str,
        source_id: str = "",
        source_name: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        entry_id: Optional[str] = None,
    ) -> KnowledgeEntry:
        """Add a text entry."""
        if entry_id is None:
            entry_id = self._generate_id(text)
        
        embedding = self._embed(text)
        
        entry = KnowledgeEntry(
            id=entry_id,
            text=text,
            embedding=embedding,
            metadata=metadata or {},
            source_id=source_id,
            source_name=source_name,
        )
        
        self._entries[entry_id] = entry
        self._save()
        return entry
    
    def add_batch(
        self,
        texts: List[str],
        source_id: str = "",
        source_name: str = "",
    ) -> List[KnowledgeEntry]:
        """Add multiple text entries in batch."""
        if not texts:
            return []
        
        embeddings = self._embed_batch(texts)
        entries = []
        
        for text, embedding in zip(texts, embeddings):
            entry_id = self._generate_id(text)
            entry = KnowledgeEntry(
                id=entry_id,
                text=text,
                embedding=embedding,
                source_id=source_id,
                source_name=source_name,
            )
            self._entries[entry_id] = entry
            entries.append(entry)
        
        self._save()
        return entries
    
    def remove(self, entry_id: str) -> bool:
        """Remove an entry by ID."""
        if entry_id in self._entries:
            del self._entries[entry_id]
            self._save()
            return True
        return False
    
    def remove_by_source(self, source_id: str) -> int:
        """Remove all entries from a source."""
        to_remove = [e.id for e in self._entries.values() if e.source_id == source_id]
        for entry_id in to_remove:
            del self._entries[entry_id]
        if to_remove:
            self._save()
        return len(to_remove)
    
    def get(self, entry_id: str) -> Optional[KnowledgeEntry]:
        """Get an entry by ID."""
        return self._entries.get(entry_id)
    
    def list_all(self, limit: int = 100) -> List[KnowledgeEntry]:
        """List entries (limited)."""
        entries = sorted(self._entries.values(), key=lambda e: e.created_at, reverse=True)
        return entries[:limit]
    
    def search(
        self,
        query: str,
        top_k: int = 5,
        min_score: float = 0.0,
    ) -> List[SearchResult]:
        """Search for entries similar to the query."""
        if not self._entries:
            return []
        
        query_embedding = self._embed(query)
        if not query_embedding:
            return self._fallback_search(query, top_k)
        
        entry_list = list(self._entries.values())
        entry_embeddings = np.array([e.embedding for e in entry_list])
        
        valid_mask = np.array([len(e.embedding) > 0 for e in entry_list])
        if not np.any(valid_mask):
            return self._fallback_search(query, top_k)
        
        valid_entries = [e for e, valid in zip(entry_list, valid_mask) if valid]
        valid_embeddings = entry_embeddings[valid_mask]
        
        similarities = self._cosine_similarity(query_embedding, valid_embeddings)
        
        results = []
        for entry, score in zip(valid_entries, similarities):
            if score >= min_score:
                results.append(SearchResult(entry=entry, score=float(score)))
        
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top_k]
    
    def _fallback_search(self, query: str, top_k: int) -> List[SearchResult]:
        """Simple keyword-based fallback search."""
        query_words = set(query.lower().split())
        results = []
        
        for entry in self._entries.values():
            text_words = set(entry.text.lower().split())
            overlap = len(query_words & text_words)
            if overlap > 0:
                score = overlap / max(len(query_words), len(text_words))
                results.append(SearchResult(entry=entry, score=score))
        
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top_k]
    
    def clear(self) -> int:
        """Clear all entries."""
        count = len(self._entries)
        self._entries.clear()
        self._save()
        return count
    
    def stats(self) -> Dict[str, Any]:
        """Get statistics about the store."""
        entries = list(self._entries.values())
        sources = {}
        for e in entries:
            key = e.source_name or e.source_id or "unknown"
            sources[key] = sources.get(key, 0) + 1
        
        return {
            "entry_count": len(entries),
            "has_embeddings": EMBEDDINGS_AVAILABLE,
            "model_name": self.model_name,
            "sources": sources,
        }


class KnowledgeServiceManager:
    """Manages multiple SkillSet stores across projects."""
    
    def __init__(self, base_storage_path: str = "~/.adk-playground/skillsets"):
        self.base_path = Path(base_storage_path).expanduser()
        self.base_path.mkdir(parents=True, exist_ok=True)
        self._stores: Dict[str, SkillSetStore] = {}  # key: "{project_id}/{skillset_id}"
    
    def _store_key(self, project_id: str, skillset_id: str) -> str:
        return f"{project_id}/{skillset_id}"
    
    def get_store(
        self,
        project_id: str,
        skillset_id: str,
        model_name: str = "text-embedding-004",
    ) -> SkillSetStore:
        """Get or create a store for a skillset."""
        key = self._store_key(project_id, skillset_id)
        
        if key not in self._stores:
            storage_path = self.base_path / project_id
            self._stores[key] = SkillSetStore(
                project_id=project_id,
                skillset_id=skillset_id,
                storage_path=storage_path,
                model_name=model_name,
            )
        
        return self._stores[key]
    
    def delete_store(self, project_id: str, skillset_id: str) -> bool:
        """Delete a store and its data."""
        key = self._store_key(project_id, skillset_id)
        
        if key in self._stores:
            del self._stores[key]
        
        # Delete the index file
        index_file = self.base_path / project_id / f"{skillset_id}.json"
        if index_file.exists():
            index_file.unlink()
            return True
        return False
    
    def list_stores(self, project_id: str) -> List[str]:
        """List all skillset IDs for a project."""
        project_path = self.base_path / project_id
        if not project_path.exists():
            return []
        
        return [f.stem for f in project_path.glob("*.json")]
    
    @staticmethod
    def embeddings_available() -> bool:
        """Check if embeddings are available."""
        return EMBEDDINGS_AVAILABLE


# Singleton instance
_manager: Optional[KnowledgeServiceManager] = None


def get_knowledge_manager() -> KnowledgeServiceManager:
    """Get the singleton knowledge manager."""
    global _manager
    if _manager is None:
        _manager = KnowledgeServiceManager()
    return _manager


# Helper functions for fetching content

async def fetch_url_content(url: str, timeout: int = 30) -> str:
    """Fetch text content from a URL."""
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as response:
            response.raise_for_status()
            return await response.text()


def chunk_text(
    text: str,
    chunk_size: int = 500,
    chunk_overlap: int = 50,
) -> List[str]:
    """Split text into overlapping chunks."""
    if len(text) <= chunk_size:
        return [text]
    
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        
        # Try to break at sentence or paragraph boundary
        if end < len(text):
            # Look for paragraph break
            para_break = text.rfind('\n\n', start, end)
            if para_break > start + chunk_size // 2:
                end = para_break + 2
            else:
                # Look for sentence break
                for sep in ['. ', '! ', '? ', '\n']:
                    sent_break = text.rfind(sep, start, end)
                    if sent_break > start + chunk_size // 2:
                        end = sent_break + len(sep)
                        break
        
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        
        start = end - chunk_overlap
    
    return chunks
