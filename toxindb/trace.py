"""Trace data models for toxindb."""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import List, Optional


@dataclass
class IngestEvent:
    doc_id: str
    source: str
    owner: str
    namespace: str
    timestamp: float
    content: str
    signature: Optional[str] = None
    user_agent: str = "default-agent"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class QueryEvent:
    query_id: str
    query_text: str
    timestamp: float
    retrieved_doc_ids: List[str] = field(default_factory=list)
    output_text: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CanaryClaim:
    claim_id: str
    text: str
    planted_in_doc_id: str
    planted_at: float
    detected: bool = False
    detected_at: Optional[float] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Trace:
    ingests: List[IngestEvent] = field(default_factory=list)
    queries: List[QueryEvent] = field(default_factory=list)
    canaries: List[CanaryClaim] = field(default_factory=list)

    @classmethod
    def from_jsonl(cls, path: str, strict: bool = False) -> "Trace":
        trace = cls()
        try:
            with open(path, "r") as f:
                for lineno, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError as e:
                        raise ValueError(f"{path}:{lineno}: invalid JSON") from e
                    if not isinstance(record, dict):
                        continue
                    rtype = record.get("type")
                    if rtype == "ingest":
                        try:
                            trace.ingests.append(IngestEvent(
                                doc_id=record["doc_id"],
                                source=record["source"],
                                owner=record["owner"],
                                namespace=record["namespace"],
                                timestamp=record["timestamp"],
                                content=record["content"],
                                signature=record.get("signature"),
                                user_agent=record.get("user_agent", "default-agent"),
                            ))
                        except (KeyError, TypeError) as e:
                            raise ValueError(f"{path}:{lineno}: missing required ingest field") from e
                    elif rtype == "query":
                        try:
                            retrieved = record.get("retrieved_doc_ids")
                            if retrieved is None or isinstance(retrieved, str) or not isinstance(retrieved, list):
                                retrieved = []
                            else:
                                retrieved = list(dict.fromkeys(str(d) for d in retrieved if d is not None))
                            trace.queries.append(QueryEvent(
                                query_id=record["query_id"],
                                query_text=record["query_text"],
                                timestamp=record["timestamp"],
                                retrieved_doc_ids=retrieved,
                                output_text=record.get("output_text", ""),
                            ))
                        except (KeyError, TypeError) as e:
                            raise ValueError(f"{path}:{lineno}: missing required query field") from e
                    elif rtype == "canary":
                        try:
                            trace.canaries.append(CanaryClaim(
                                claim_id=record["claim_id"],
                                text=record["text"],
                                planted_in_doc_id=record["planted_in_doc_id"],
                                planted_at=record["planted_at"],
                                detected=record.get("detected", False),
                                detected_at=record.get("detected_at"),
                            ))
                        except (KeyError, TypeError) as e:
                            raise ValueError(f"{path}:{lineno}: missing required canary field") from e
        except (OSError, IOError) as e:
            raise
        return trace

    def to_jsonl(self, path: str) -> None:
        with open(path, "w") as f:
            for ingest in self.ingests:
                f.write(json.dumps({"type": "ingest", **ingest.to_dict()}) + "\n")
            for query in self.queries:
                f.write(json.dumps({"type": "query", **query.to_dict()}) + "\n")
            for canary in self.canaries:
                f.write(json.dumps({"type": "canary", **canary.to_dict()}) + "\n")

