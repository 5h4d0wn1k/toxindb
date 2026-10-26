"""Trace data models for toxindb."""
from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass, field, asdict
from typing import List, Optional


def _canonical_doc_id(value) -> str:
    """Canonical comparison key for ingest ``doc_id`` uniqueness.

    Stringified, NFC-normalized, stripped and casefolded, so variants that
    denote the same document collide instead of slipping past a raw-key
    duplicate check: ``"D1"`` vs ``"d1"``, trailing whitespace, NFC vs NFD
    forms, and ``1`` vs ``"1"``. ``doc_id`` is nominally a ``str``, but this
    also tolerates a JSON file that carried the id as another scalar type.
    """
    return unicodedata.normalize("NFC", str(value)).strip().casefold()


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

    def __post_init__(self) -> None:
        self._reject_duplicate_ingest_doc_ids(self.ingests)

    @staticmethod
    def _reject_duplicate_ingest_doc_ids(ingests: List[IngestEvent]) -> None:
        """Enforce the ingest doc_id uniqueness invariant at the model level.

        Runs from ``__post_init__`` so a trace built as
        ``Trace(ingests=[...])`` (or deserialized by ``api.analyze_trace_obj``
        callers and other in-memory paths) is rejected exactly like one read
        by ``from_jsonl``; it cannot reach the last-write-wins doc_id maps in
        ``heuristics.py``.
        """
        seen: dict = {}
        for index, ingest in enumerate(ingests):
            key = _canonical_doc_id(ingest.doc_id)
            first_index = seen.get(key)
            if first_index is not None:
                raise ValueError(
                    f"duplicate ingest doc_id {ingest.doc_id!r} (ingest index "
                    f"{first_index} already used it) - re-ingesting a document "
                    "under an existing doc_id silently discards the earlier "
                    "record's provenance; assign a distinct doc_id per revision"
                )
            seen[key] = index

    @classmethod
    def from_jsonl(cls, path: str, strict: bool = False) -> "Trace":
        trace = cls()
        ingest_doc_lines: dict = {}
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
                            doc_id = record["doc_id"]
                            doc_key = _canonical_doc_id(doc_id)
                            first_line = ingest_doc_lines.get(doc_key)
                            if first_line is not None:
                                raise ValueError(
                                    f"{path}:{lineno}: duplicate ingest doc_id {doc_id!r} "
                                    f"(first ingested on line {first_line}) - re-ingesting a "
                                    "document under an existing doc_id silently discards the "
                                    "earlier record's provenance; assign a distinct doc_id "
                                    "per revision"
                                )
                            ingest_doc_lines[doc_key] = lineno
                            trace.ingests.append(IngestEvent(
                                doc_id=doc_id,
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

