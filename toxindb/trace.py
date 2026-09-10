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
    def from_jsonl(cls, path: str) -> "Trace":
        trace = cls()
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                rtype = record.get("type")
                if rtype == "ingest":
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
                elif rtype == "query":
                    trace.queries.append(QueryEvent(
                        query_id=record["query_id"],
                        query_text=record["query_text"],
                        timestamp=record["timestamp"],
                        retrieved_doc_ids=record.get("retrieved_doc_ids", []),
                        output_text=record.get("output_text", ""),
                    ))
                elif rtype == "canary":
                    trace.canaries.append(CanaryClaim(
                        claim_id=record["claim_id"],
                        text=record["text"],
                        planted_in_doc_id=record["planted_in_doc_id"],
                        planted_at=record["planted_at"],
                        detected=record.get("detected", False),
                        detected_at=record.get("detected_at"),
                    ))
        return trace

    def to_jsonl(self, path: str) -> None:
        with open(path, "w") as f:
            for ingest in self.ingests:
                f.write(json.dumps({"type": "ingest", **ingest.to_dict()}) + "\n")
            for query in self.queries:
                f.write(json.dumps({"type": "query", **query.to_dict()}) + "\n")
            for canary in self.canaries:
                f.write(json.dumps({"type": "canary", **canary.to_dict()}) + "\n")
