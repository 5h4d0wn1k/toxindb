"""Session/agent-aware tracking utilities."""
from __future__ import annotations

from typing import Dict, List, Optional
from dataclasses import dataclass, field


@dataclass
class Session:
    session_id: str
    agent_id: Optional[str] = None
    turns: List[Dict[str, str]] = field(default_factory=list)
    metadata: Dict[str, str] = field(default_factory=dict)


class SessionTracker:
    def __init__(self) -> None:
        self.sessions: Dict[str, Session] = {}

    def get_or_create(self, session_id: str, agent_id: Optional[str] = None) -> Session:
        if session_id not in self.sessions:
            self.sessions[session_id] = Session(session_id=session_id, agent_id=agent_id)
        return self.sessions[session_id]

    def record_turn(self, session_id: str, query: str, retrieved: List[str]) -> None:
        sess = self.get_or_create(session_id)
        sess.turns.append({"query": query, "retrieved": ",".join(retrieved)})
