"""OTel/Langfuse-compatible trace ingestion helpers (offline-first, optional)."""
from __future__ import annotations

from typing import Dict, Any, List
from .trace import Trace, IngestEvent, QueryEvent


def langfuse_events_to_trace(events: List[Dict[str, Any]]) -> Trace:
    """Convert generic event list to Trace (best-effort, deterministic)."""
    trace = Trace()
    for ev in events:
        t = ev.get("type") or ev.get("event")
        if t == "ingest" or t == "document":
            trace.ingests.append(IngestEvent(
                doc_id=str(ev.get("doc_id") or ev.get("id")),
                source=str(ev.get("source", "")),
                owner=str(ev.get("owner", "")),
                namespace=str(ev.get("namespace", "")),
                timestamp=float(ev.get("timestamp", 0)),
                content=str(ev.get("content", "")),
                signature=ev.get("signature"),
                user_agent=str(ev.get("user_agent", "default-agent")),
            ))
        elif t == "query" or t == "retrieval":
            retrieved = ev.get("retrieved_doc_ids") or ev.get("documents") or []
            if isinstance(retrieved, list):
                result = []
                seen = set()
                for d in retrieved:
                    if d is None:
                        continue
                    if isinstance(d, dict):
                        key = str(d.get("doc_id") or d.get("id") or d)
                    else:
                        key = str(d)
                    if key not in seen:
                        seen.add(key)
                        result.append(key)
                retrieved = result
            trace.queries.append(QueryEvent(
                query_id=str(ev.get("query_id") or ev.get("id")),
                query_text=str(ev.get("query_text") or ev.get("input", "")),
                timestamp=float(ev.get("timestamp", 0)),
                retrieved_doc_ids=retrieved if isinstance(retrieved, list) else [],
                output_text=str(ev.get("output_text", "")),
            ))
    return trace
