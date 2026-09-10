"""Tests for the analysis engine."""
import json
import os
import tempfile

from toxindb.trace import Trace, IngestEvent, QueryEvent
from toxindb.engine import Engine


def test_engine_analyze_clean_trace():
    trace = Trace()
    base = 1000.0
    for i in range(10):
        trace.ingests.append(IngestEvent(
            doc_id=f"d-{i}", source="wiki", owner="wiki",
            namespace="ns", timestamp=base - 100000 + i,
            content=f"Legit doc {i} about science", user_agent="wiki-agent",
        ))
    for i in range(5):
        trace.queries.append(QueryEvent(
            query_id=f"q-{i}", query_text=f"science topic {i}",
            timestamp=base + i * 100,
            retrieved_doc_ids=[f"d-{i}", f"d-{(i+1)%10}"],
        ))
    engine = Engine()
    alerts = engine.analyze(trace)
    critical_high = [a for a in alerts if a.severity in ("critical", "high")]
    assert len(critical_high) <= 2


def test_engine_analyze_poison_trace():
    trace = Trace()
    base = 1000.0
    for i in range(30):
        trace.ingests.append(IngestEvent(
            doc_id=f"poison-{i}", source="attacker", owner="attacker",
            namespace="ns", timestamp=base + i * 10,
            content="quantum computing quantum supremacy quantum advantage "
                    "quantum computing quantum supremacy quantum advantage",
            user_agent="attacker-agent",
        ))
    for i in range(10):
        trace.queries.append(QueryEvent(
            query_id=f"q-{i}", query_text="quantum computing",
            timestamp=base + 500 + i * 10,
            retrieved_doc_ids=[f"poison-{j}" for j in range(i*3, i*3+5)],
        ))
    engine = Engine()
    alerts = engine.analyze(trace)
    assert len(alerts) > 0


def test_engine_analyze_to_jsonl():
    trace = Trace()
    base = 1000.0
    for i in range(5):
        trace.ingests.append(IngestEvent(
            doc_id=f"d-{i}", source="s", owner="o",
            namespace="ns", timestamp=base + i,
            content=f"Doc {i}", user_agent="ua",
        ))
    trace.queries.append(QueryEvent(
        query_id="q1", query_text="q", timestamp=base + 10,
        retrieved_doc_ids=[f"d-{i}" for i in range(5)],
    ))
    engine = Engine()

    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
        out_path = f.name

    try:
        alerts = engine.analyze_to_jsonl(trace, out_path)
        assert os.path.exists(out_path)
        with open(out_path) as f:
            lines = [l.strip() for l in f if l.strip()]
        assert len(lines) == len(alerts)
        first = json.loads(lines[0])
        assert "heuristic_id" in first
    finally:
        os.unlink(out_path)


def test_engine_empty_trace():
    trace = Trace()
    engine = Engine()
    alerts = engine.analyze(trace)
    assert len(alerts) == 0


def test_engine_with_known_sources():
    trace = Trace()
    trace.ingests.append(IngestEvent(
        doc_id="d1", source="trusted", owner="impersonator",
        namespace="ns", timestamp=100.0, content="c",
        signature="fake-sig", user_agent="ua",
    ))
    engine = Engine(known_sources={"trusted": "real-owner"})
    alerts = engine.analyze(trace)
    provenance_alerts = [a for a in alerts if a.heuristic_id == "TX-005"]
    assert len(provenance_alerts) >= 1
