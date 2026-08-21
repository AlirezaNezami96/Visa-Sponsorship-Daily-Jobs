"""
In-memory session store with TTL expiry.

Each session holds:
  - The raw Master Resume text (fetched from Google Docs)
  - A timestamp for TTL enforcement
  - Optionally, a cache of generated doc_ids for this session
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class Session:
    session_id: str
    resume_text: str
    google_doc_id: str = ""
    created_at: float = field(default_factory=time.time)
    doc_ids: List[str] = field(default_factory=list)

    def is_expired(self, ttl_seconds: int) -> bool:
        return (time.time() - self.created_at) > ttl_seconds


class SessionStore:
    """Thread-safe in-memory session store with automatic TTL cleanup."""

    def __init__(self, ttl_seconds: int = 7200) -> None:
        self._store: Dict[str, Session] = {}
        self._ttl = ttl_seconds

    def create(self, resume_text: str, google_doc_id: str = "") -> str:
        """Create a new session and return its ID."""
        self._evict_expired()
        session_id = str(uuid.uuid4())
        self._store[session_id] = Session(
            session_id=session_id,
            resume_text=resume_text,
            google_doc_id=google_doc_id,
        )
        return session_id

    def get(self, session_id: str) -> Optional[Session]:
        """Return a session if it exists and hasn't expired."""
        session = self._store.get(session_id)
        if session is None:
            return None
        if session.is_expired(self._ttl):
            del self._store[session_id]
            return None
        return session

    def add_doc(self, session_id: str, doc_id: str) -> None:
        """Record a generated document ID against a session."""
        session = self.get(session_id)
        if session:
            session.doc_ids.append(doc_id)

    def _evict_expired(self) -> None:
        expired = [sid for sid, s in self._store.items() if s.is_expired(self._ttl)]
        for sid in expired:
            del self._store[sid]

    def count(self) -> int:
        self._evict_expired()
        return len(self._store)


# Global singleton — shared across the process lifetime
_store: Optional[SessionStore] = None


def get_session_store() -> SessionStore:
    global _store
    if _store is None:
        from .config import get_settings
        _store = SessionStore(ttl_seconds=get_settings().session_ttl_seconds)
    return _store
