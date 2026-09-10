"""Heuristic detectors for RAG retrieval-time poisoning."""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional, Set

from .trace import Trace, IngestEvent, QueryEvent


@dataclass
class Alert:
    heuristic_id: str
    heuristic_name: str
    severity: str
    query_id: Optional[str]
    doc_ids: List[str]
    detail: str
    confidence: float = 1.0

    def to_dict(self) -> dict:
        return {
            "heuristic_id": self.heuristic_id,
            "heuristic_name": self.heuristic_name,
            "severity": self.severity,
            "query_id": self.query_id,
            "doc_ids": self.doc_ids,
            "detail": self.detail,
            "confidence": self.confidence,
        }


def _tokens(text: str) -> List[str]:
    return [w.lower() for w in text.split() if len(w) > 1]


def _token_set(text: str) -> Set[str]:
    return set(_tokens(text))


def _jaccard(a: Set[str], b: Set[str]) -> float:
    if not a and not b:
        return 0.0
    inter = a & b
    union = a | b
    return len(inter) / len(union) if union else 0.0


def _cosine_bow(text_a: str, text_b: str) -> float:
    tokens_a = _tokens(text_a)
    tokens_b = _tokens(text_b)
    if not tokens_a or not tokens_b:
        return 0.0
    counter_a = Counter(tokens_a)
    counter_b = Counter(tokens_b)
    all_keys = set(counter_a) | set(counter_b)
    dot = sum(counter_a.get(k, 0) * counter_b.get(k, 0) for k in all_keys)
    mag_a = math.sqrt(sum(v * v for v in counter_a.values()))
    mag_b = math.sqrt(sum(v * v for v in counter_b.values()))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


def _lexical_distance(a: str, b: str) -> float:
    tokens_a = set(_tokens(a))
    tokens_b = set(_tokens(b))
    if not tokens_a:
        return 1.0
    overlap = len(tokens_a & tokens_b) / len(tokens_a)
    return 1.0 - overlap


class DemandConcentrationDetector:
    def __init__(self, threshold: float = 0.6, window_hours: float = 24.0):
        self.threshold = threshold
        self.window_seconds = window_hours * 3600

    def detect(self, trace: Trace) -> List[Alert]:
        alerts = []
        doc_map = {d.doc_id: d for d in trace.ingests}
        for query in trace.queries:
            if not query.retrieved_doc_ids:
                continue
            recent_count = 0
            recent_docs = []
            for doc_id in query.retrieved_doc_ids:
                doc = doc_map.get(doc_id)
                if doc and (query.timestamp - doc.timestamp) <= self.window_seconds:
                    recent_count += 1
                    recent_docs.append(doc_id)
            total = len(query.retrieved_doc_ids)
            if total > 0:
                fraction = recent_count / total
                if fraction > self.threshold:
                    alerts.append(Alert(
                        heuristic_id="TX-001",
                        heuristic_name="Demand Concentration",
                        severity="high",
                        query_id=query.query_id,
                        doc_ids=recent_docs,
                        detail=(
                            f"{recent_count}/{total} retrievals ({fraction:.0%}) "
                            f"from docs ingested within {self.window_seconds/3600:.0f}h "
                            f"threshold={self.threshold:.0%}"
                        ),
                        confidence=fraction,
                    ))
        return alerts


class RecencyAnomalyDetector:
    def __init__(self, window_hours: float = 24.0, prior_window_hours: float = 168.0):
        self.window_seconds = window_hours * 3600
        self.prior_window_seconds = prior_window_hours * 3600

    def detect(self, trace: Trace) -> List[Alert]:
        alerts = []
        doc_map = {d.doc_id: d for d in trace.ingests}
        sorted_queries = sorted(trace.queries, key=lambda q: q.timestamp)
        for i, query in enumerate(sorted_queries):
            if not query.retrieved_doc_ids:
                continue
            recent_docs = []
            for doc_id in query.retrieved_doc_ids:
                doc = doc_map.get(doc_id)
                if doc and (query.timestamp - doc.timestamp) <= self.window_seconds:
                    recent_docs.append(doc_id)
            if not recent_docs:
                continue
            prior_demand = 0
            for prev_q in sorted_queries[:i]:
                for doc_id in recent_docs:
                    if doc_id in prev_q.retrieved_doc_ids:
                        prior_demand += 1
                        break
            total_queries_before = i
            if total_queries_before > 0:
                prior_rate = prior_demand / total_queries_before
            else:
                prior_rate = 0.0
            if prior_rate < 0.05 and len(recent_docs) >= 2:
                alerts.append(Alert(
                    heuristic_id="TX-002",
                    heuristic_name="Recency Anomaly",
                    severity="high",
                    query_id=query.query_id,
                    doc_ids=recent_docs,
                    detail=(
                        f"{len(recent_docs)} fresh docs dominate retrieval with "
                        f"prior organic demand rate {prior_rate:.2%}"
                    ),
                    confidence=1.0 - prior_rate,
                ))
        return alerts


class EmbeddingClusterDetector:
    def __init__(self, similarity_threshold: float = 0.4, min_cluster_size: int = 3):
        self.similarity_threshold = similarity_threshold
        self.min_cluster_size = min_cluster_size

    def detect(self, trace: Trace) -> List[Alert]:
        alerts = []
        doc_map = {d.doc_id: d for d in trace.ingests}
        query_groups: Dict[str, List[str]] = defaultdict(list)
        for query in trace.queries:
            for doc_id in query.retrieved_doc_ids:
                if doc_id in doc_map:
                    query_groups[query.query_id].append(doc_id)
        for query_id, doc_ids in query_groups.items():
            if len(doc_ids) < self.min_cluster_size:
                continue
            docs = [doc_map[did] for did in doc_ids]
            similar_pairs = 0
            total_pairs = 0
            for i in range(len(docs)):
                for j in range(i + 1, len(docs)):
                    total_pairs += 1
                    sim = _cosine_bow(docs[i].content, docs[j].content)
                    if sim >= self.similarity_threshold:
                        similar_pairs += 1
            if total_pairs > 0:
                cluster_density = similar_pairs / total_pairs
                if cluster_density > 0.5 and similar_pairs >= 3:
                    alerts.append(Alert(
                        heuristic_id="TX-003",
                        heuristic_name="Embedding-Space Cluster",
                        severity="medium",
                        query_id=query_id,
                        doc_ids=doc_ids,
                        detail=(
                            f"{similar_pairs}/{total_pairs} pairs above "
                            f"similarity {self.similarity_threshold} "
                            f"(density={cluster_density:.2f})"
                        ),
                        confidence=cluster_density,
                    ))
        return alerts


class CanaryResurgenceDetector:
    def detect(self, trace: Trace) -> List[Alert]:
        alerts = []
        canary_texts = {c.planted_in_doc_id: c for c in trace.canaries}
        for query in trace.queries:
            if not query.output_text:
                continue
            output_lower = query.output_text.lower()
            for canary in trace.canaries:
                canary_lower = canary.text.lower()
                if canary_lower in output_lower:
                    alerts.append(Alert(
                        heuristic_id="TX-004",
                        heuristic_name="Canary Resurgence",
                        severity="critical",
                        query_id=query.query_id,
                        doc_ids=[canary.planted_in_doc_id],
                        detail=(
                            f"Canary claim '{canary.claim_id}' surfaced in "
                            f"query output"
                        ),
                        confidence=1.0,
                    ))
        return alerts


class ProvenanceMismatchDetector:
    def __init__(self, known_sources: Optional[Dict[str, str]] = None):
        self.known_sources = known_sources or {}

    def detect(self, trace: Trace) -> List[Alert]:
        alerts = []
        for ingest in trace.ingests:
            if ingest.signature and ingest.source in self.known_sources:
                expected_owner = self.known_sources[ingest.source]
                if ingest.owner != expected_owner:
                    alerts.append(Alert(
                        heuristic_id="TX-005",
                        heuristic_name="Provenance Mismatch",
                        severity="high",
                        query_id=None,
                        doc_ids=[ingest.doc_id],
                        detail=(
                            f"Source '{ingest.source}' owner '{ingest.owner}' "
                            f"does not match expected '{expected_owner}'"
                        ),
                        confidence=1.0,
                    ))
        return alerts


class BulkIngestPulseDetector:
    def __init__(self, threshold: int = 10, window_hours: float = 1.0):
        self.threshold = threshold
        self.window_seconds = window_hours * 3600

    def detect(self, trace: Trace) -> List[Alert]:
        alerts = []
        sorted_ingests = sorted(trace.ingests, key=lambda i: i.timestamp)
        for i, ingest in enumerate(sorted_ingests):
            batch = [ingest]
            for j in range(i + 1, len(sorted_ingests)):
                next_ingest = sorted_ingests[j]
                if next_ingest.source == ingest.source and \
                   next_ingest.namespace == ingest.namespace and \
                   (next_ingest.timestamp - ingest.timestamp) <= self.window_seconds:
                    batch.append(next_ingest)
                else:
                    break
            if len(batch) >= self.threshold:
                alerts.append(Alert(
                    heuristic_id="TX-006",
                    heuristic_name="Bulk-Ingest Pulse",
                    severity="high",
                    query_id=None,
                    doc_ids=[d.doc_id for d in batch],
                    detail=(
                        f"{len(batch)} docs from '{ingest.source}' into "
                        f"'{ingest.namespace}' within "
                        f"{self.window_seconds/3600:.1f}h"
                    ),
                    confidence=min(1.0, len(batch) / self.threshold),
                ))
        return alerts


class QueryDocMismatchDetector:
    def __init__(self, distance_threshold: float = 0.8):
        self.distance_threshold = distance_threshold

    def detect(self, trace: Trace) -> List[Alert]:
        alerts = []
        doc_map = {d.doc_id: d for d in trace.ingests}
        for query in trace.queries:
            mismatched = []
            for doc_id in query.retrieved_doc_ids:
                doc = doc_map.get(doc_id)
                if doc:
                    dist = _lexical_distance(query.query_text, doc.content)
                    if dist >= self.distance_threshold:
                        mismatched.append(doc_id)
            if mismatched:
                alerts.append(Alert(
                    heuristic_id="TX-007",
                    heuristic_name="Query-Doc Mismatch",
                    severity="medium",
                    query_id=query.query_id,
                    doc_ids=mismatched,
                    detail=(
                        f"{len(mismatched)} retrieved docs have lexical distance "
                        f">= {self.distance_threshold} from query"
                    ),
                    confidence=max(0.5, len(mismatched) / max(1, len(query.retrieved_doc_ids))),
                ))
        return alerts


class DoubleRetrievalDetector:
    def __init__(self, window_seconds: float = 60.0):
        self.window_seconds = window_seconds

    def detect(self, trace: Trace) -> List[Alert]:
        alerts = []
        sorted_queries = sorted(trace.queries, key=lambda q: q.timestamp)
        for i in range(len(sorted_queries) - 1):
            q1 = sorted_queries[i]
            q2 = sorted_queries[i + 1]
            dt = q2.timestamp - q1.timestamp
            if dt <= self.window_seconds and dt > 0:
                overlap = set(q1.retrieved_doc_ids) & set(q2.retrieved_doc_ids)
                if len(overlap) >= 2 and q1.query_text == q2.query_text:
                    alerts.append(Alert(
                        heuristic_id="TX-008",
                        heuristic_name="LangChain Double-Retrieval",
                        severity="medium",
                        query_id=q2.query_id,
                        doc_ids=list(overlap),
                        detail=(
                            f"Same query repeated with {len(overlap)} shared docs "
                            f"within {dt:.1f}s (attacker context reuse pattern)"
                        ),
                        confidence=min(1.0, len(overlap) / 3),
                    ))
        return alerts


class SourceCartelDetector:
    def detect(self, trace: Trace) -> List[Alert]:
        alerts = []
        ua_sources: Dict[str, Dict[str, List[float]]] = defaultdict(lambda: defaultdict(list))
        for ingest in trace.ingests:
            ua_sources[ingest.user_agent][ingest.source].append(ingest.timestamp)
        for ua, sources in ua_sources.items():
            if len(sources) >= 3:
                all_timestamps = []
                for src, ts_list in sources.items():
                    all_timestamps.extend([(t, src) for t in ts_list])
                all_timestamps.sort()
                burst_count = 1
                for k in range(1, len(all_timestamps)):
                    if all_timestamps[k][0] - all_timestamps[k - 1][0] <= 5.0:
                        burst_count += 1
                    else:
                        burst_count = 1
                if burst_count >= 5:
                    alerts.append(Alert(
                        heuristic_id="TX-009",
                        heuristic_name="Source Cartel",
                        severity="high",
                        query_id=None,
                        doc_ids=[],
                        detail=(
                            f"UA '{ua}' used by {len(sources)} sources with "
                            f"{burst_count} rapid-fire ingests"
                        ),
                        confidence=min(1.0, len(sources) / 3),
                    ))
        return alerts


class DriftedAuthorityDetector:
    def __init__(self, max_age_hours: float = 720.0):
        self.max_age_seconds = max_age_hours * 3600

    def detect(self, trace: Trace) -> List[Alert]:
        alerts = []
        latest_signed: Dict[str, float] = {}
        for ingest in trace.ingests:
            if ingest.signature:
                current = latest_signed.get(ingest.source, float("-inf"))
                if ingest.timestamp > current:
                    latest_signed[ingest.source] = ingest.timestamp
        latest_ts = max((i.timestamp for i in trace.ingests), default=0)
        for source, last_signed in latest_signed.items():
            if (latest_ts - last_signed) > self.max_age_seconds:
                unsigned_count = sum(
                    1 for i in trace.ingests
                    if i.source == source and not i.signature
                )
                if unsigned_count > 0:
                    alerts.append(Alert(
                        heuristic_id="TX-010",
                        heuristic_name="Drifted Authorities",
                        severity="medium",
                        query_id=None,
                        doc_ids=[i.doc_id for i in trace.ingests if i.source == source and not i.signature],
                        detail=(
                            f"Source '{source}' last signed attestation "
                            f"{((latest_ts - last_signed)/3600):.0f}h ago, "
                            f"{unsigned_count} unsigned ingests since"
                        ),
                        confidence=min(1.0, unsigned_count / 5),
                    ))
        return alerts


class NewNamespaceFlashDetector:
    def __init__(self, age_threshold_hours: float = 2.0, retrieval_share: float = 0.15):
        self.age_threshold_seconds = age_threshold_hours * 3600
        self.retrieval_share = retrieval_share

    def detect(self, trace: Trace) -> List[Alert]:
        alerts = []
        ns_first_ingest: Dict[str, float] = {}
        for ingest in trace.ingests:
            if ingest.namespace not in ns_first_ingest or \
               ingest.timestamp < ns_first_ingest[ingest.namespace]:
                ns_first_ingest[ingest.namespace] = ingest.timestamp
        doc_map = {d.doc_id: d for d in trace.ingests}
        total_retrievals = sum(len(q.retrieved_doc_ids) for q in trace.queries)
        if total_retrievals == 0:
            return alerts
        ns_retrievals: Dict[str, int] = Counter()
        for query in trace.queries:
            for doc_id in query.retrieved_doc_ids:
                doc = doc_map.get(doc_id)
                if doc:
                    ns_retrievals[doc.namespace] += 1
        latest_ts = max((i.timestamp for i in trace.ingests), default=0)
        for ns, first_ts in ns_first_ingest.items():
            age = latest_ts - first_ts
            if age <= self.age_threshold_seconds:
                share = ns_retrievals.get(ns, 0) / total_retrievals
                if share >= self.retrieval_share:
                    alerts.append(Alert(
                        heuristic_id="TX-011",
                        heuristic_name="New-Namespace Flash",
                        severity="high",
                        query_id=None,
                        doc_ids=[i.doc_id for i in trace.ingests if i.namespace == ns],
                        detail=(
                            f"Namespace '{ns}' is {age/3600:.1f}h old but has "
                            f"{share:.0%} of all retrievals"
                        ),
                        confidence=share,
                    ))
        return alerts


class QuarantineDetector:
    def __init__(self, demand_threshold: float = 0.5):
        self.demand_threshold = demand_threshold

    def detect(self, trace: Trace, existing_alerts: List[Alert]) -> List[Alert]:
        alerts = []
        flagged_docs: Set[str] = set()
        for alert in existing_alerts:
            if alert.severity in ("high", "critical"):
                flagged_docs.update(alert.doc_ids)
        if not flagged_docs:
            return alerts
        doc_retrieval_count: Counter = Counter()
        for query in trace.queries:
            for doc_id in query.retrieved_doc_ids:
                if doc_id in flagged_docs:
                    doc_retrieval_count[doc_id] += 1
        total_queries = len(trace.queries)
        if total_queries == 0:
            return alerts
        quarantine_candidates = []
        for doc_id, count in doc_retrieval_count.items():
            share = count / total_queries
            if share >= self.demand_threshold:
                quarantine_candidates.append((doc_id, share))
        quarantine_candidates.sort(key=lambda x: -x[1])
        if quarantine_candidates:
            alerts.append(Alert(
                heuristic_id="TX-012",
                heuristic_name="Quarantine Suggestion",
                severity="high",
                query_id=None,
                doc_ids=[doc_id for doc_id, _ in quarantine_candidates],
                detail=(
                    f"{len(quarantine_candidates)} docs flagged by other "
                    f"heuristics have high retrieval share; suggest quarantine"
                ),
                confidence=1.0,
            ))
        return alerts


ALL_DETECTORS = [
    DemandConcentrationDetector,
    RecencyAnomalyDetector,
    EmbeddingClusterDetector,
    CanaryResurgenceDetector,
    ProvenanceMismatchDetector,
    BulkIngestPulseDetector,
    QueryDocMismatchDetector,
    DoubleRetrievalDetector,
    SourceCartelDetector,
    DriftedAuthorityDetector,
    NewNamespaceFlashDetector,
]
