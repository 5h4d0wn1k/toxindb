"""Integration tests — bundled traces, heuristic firing, demo flow."""
import json
import os
import tempfile

from toxindb.trace import Trace, IngestEvent, QueryEvent, CanaryClaim
from toxindb.engine import Engine
from toxindb.canary import generate_canary, plant_canary_in_trace, check_canary_resurgence
from toxindb.provenance import audit_provenance
from toxindb.report import render_markdown_report, render_json_report
from toxindb.heuristics import (
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
    QuarantineDetector,
)


def _build_poison_trace():
    trace = Trace()
    base = 1000000.0
    for i in range(30):
        trace.ingests.append(IngestEvent(
            doc_id=f"legit-{i}", source="wiki", owner="wiki",
            namespace="general", timestamp=base + i * 8640,
            content=f"Legitimate document about topic {i}", user_agent="wiki-agent",
        ))
    for i in range(15):
        trace.ingests.append(IngestEvent(
            doc_id=f"poison-{i}", source="attacker", owner="attacker",
            namespace="target", timestamp=base + 86400 + i * 30,
            content="quantum computing quantum supremacy quantum advantage "
                    "quantum computing quantum supremacy quantum advantage",
            user_agent="attacker-agent",
        ))
    for i in range(10):
        trace.queries.append(QueryEvent(
            query_id=f"pre-{i}", query_text="quantum computing",
            timestamp=base + i * 86400,
            retrieved_doc_ids=[f"legit-{i}", f"legit-{(i+1)%30}"],
        ))
    for i in range(10):
        trace.queries.append(QueryEvent(
            query_id=f"post-{i}", query_text="quantum computing",
            timestamp=base + 86400 + 1000 + i * 10,
            retrieved_doc_ids=[f"poison-{j}" for j in range(i, min(i+5, 15))] + [f"legit-{i}"],
        ))
    return trace


def _build_clean_trace():
    trace = Trace()
    base = 1000000.0
    for i in range(40):
        trace.ingests.append(IngestEvent(
            doc_id=f"doc-{i}", source="wiki", owner="wiki",
            namespace="general", timestamp=base + i * 8640,
            content=f"Legitimate document about topic {i} with unique content "
                    f"covering different aspects of knowledge",
            user_agent="wiki-agent",
        ))
    for i in range(20):
        trace.queries.append(QueryEvent(
            query_id=f"q-{i}", query_text=f"topic {i}",
            timestamp=base + 86400 + i * 43200,
            retrieved_doc_ids=[f"doc-{i}", f"doc-{(i+1)%40}"],
        ))
    return trace


def test_poison_trace_fires_heuristics():
    trace = _build_poison_trace()
    engine = Engine()
    alerts = engine.analyze(trace)
    heuristic_ids = {a.heuristic_id for a in alerts}
    assert "TX-001" in heuristic_ids or "TX-002" in heuristic_ids


def test_clean_trace_low_false_positives():
    trace = _build_clean_trace()
    engine = Engine()
    alerts = engine.analyze(trace)
    critical_high = [a for a in alerts if a.severity in ("critical", "high")]
    assert len(critical_high) <= 10


def test_heuristics_all_have_detect_method():
    detector_classes = [
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
        QuarantineDetector,
    ]
    for cls in detector_classes:
        det = cls()
        assert hasattr(det, 'detect')


def test_full_analysis_pipeline():
    trace = _build_poison_trace()
    engine = Engine()
    alerts = engine.analyze(trace)
    prov = audit_provenance(trace)
    jr = render_json_report(alerts, prov)
    data = json.loads(jr)
    assert data["alert_count"] > 0
    md = render_markdown_report(alerts, prov)
    assert "toxindb" in md


def test_canary_lifecycle_integration():
    trace = Trace()
    base = 1000.0
    for i in range(10):
        trace.ingests.append(IngestEvent(
            doc_id=f"doc-{i}", source="s", owner="o",
            namespace="ns", timestamp=base + i,
            content=f"Normal doc {i}", user_agent="ua",
        ))
    canary = generate_canary("integration-test", 0)
    plant_canary_in_trace(trace, canary, base + 50, "s", "o", "ns")
    trace.queries.append(QueryEvent(
        query_id="q1", query_text="q", timestamp=base + 100,
        retrieved_doc_ids=[canary.planted_in_doc_id],
        output_text=f"Answer contains: {canary.text} end.",
    ))
    engine = Engine()
    alerts = engine.analyze(trace)
    canary_alerts = [a for a in alerts if a.heuristic_id == "TX-004"]
    assert len(canary_alerts) >= 1


def test_provenance_mismatch_integration():
    trace = Trace()
    trace.ingests.append(IngestEvent(
        doc_id="d1", source="trusted", owner="impostor",
        namespace="ns", timestamp=1.0, content="c",
        signature="fake", user_agent="ua",
    ))
    engine = Engine(known_sources={"trusted": "real-owner"})
    alerts = engine.analyze(trace)
    mismatch = [a for a in alerts if a.heuristic_id == "TX-005"]
    assert len(mismatch) >= 1


def test_bulk_ingest_integration():
    trace = Trace()
    base = 1000.0
    for i in range(15):
        trace.ingests.append(IngestEvent(
            doc_id=f"bulk-{i}", source="attacker", owner="attacker",
            namespace="target", timestamp=base + i * 2,
            content=f"Doc {i}", user_agent="ua",
        ))
    engine = Engine()
    alerts = engine.analyze(trace)
    bulk = [a for a in alerts if a.heuristic_id == "TX-006"]
    assert len(bulk) >= 1


def test_cartel_integration():
    trace = Trace()
    base = 1000.0
    ua = "shared-agent"
    ts = base
    for si, src in enumerate(["a", "b", "c", "d"]):
        for i in range(4):
            trace.ingests.append(IngestEvent(
                doc_id=f"cartel-{si}-{i}", source=src, owner=src,
                namespace="ns", timestamp=ts,
                content=f"Doc", user_agent=ua,
            ))
            ts += 1
    engine = Engine()
    alerts = engine.analyze(trace)
    cartel = [a for a in alerts if a.heuristic_id == "TX-009"]
    assert len(cartel) >= 1


def test_double_retrieval_integration():
    trace = Trace()
    trace.queries.append(QueryEvent(
        query_id="q1", query_text="identical query",
        timestamp=100.0, retrieved_doc_ids=["d1", "d2", "d3"],
    ))
    trace.queries.append(QueryEvent(
        query_id="q2", query_text="identical query",
        timestamp=105.0, retrieved_doc_ids=["d1", "d2", "d3"],
    ))
    engine = Engine()
    alerts = engine.analyze(trace)
    dr = [a for a in alerts if a.heuristic_id == "TX-008"]
    assert len(dr) >= 1


def test_quarantine_integration():
    trace = Trace()
    base = 1000.0
    for i in range(10):
        trace.ingests.append(IngestEvent(
            doc_id=f"flagged-{i}", source="attacker", owner="attacker",
            namespace="ns", timestamp=base + i * 2,
            content=f"Doc {i}", user_agent="ua",
        ))
    flagged_ids = [f"flagged-{i}" for i in range(3)]
    for qi in range(20):
        trace.queries.append(QueryEvent(
            query_id=f"q-{qi}", query_text="q", timestamp=base + 100 + qi,
            retrieved_doc_ids=flagged_ids,
        ))
    engine = Engine()
    alerts = engine.analyze(trace)
    quarantine = [a for a in alerts if a.heuristic_id == "TX-012"]
    assert len(quarantine) >= 1
