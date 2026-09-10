"""Tests for TX-001 Demand Concentration detector."""
from toxindb.trace import Trace, IngestEvent, QueryEvent
from toxindb.heuristics import DemandConcentrationDetector


def test_tx001_fires_on_concentrated_demand():
    trace = Trace()
    base = 1000.0
    for i in range(10):
        trace.ingests.append(IngestEvent(
            doc_id=f"fresh-{i}", source="attacker", owner="attacker",
            namespace="ns", timestamp=base + i,
            content=f"Poison doc {i}", user_agent="attacker-agent",
        ))
    trace.queries.append(QueryEvent(
        query_id="q1", query_text="test query", timestamp=base + 5,
        retrieved_doc_ids=[f"fresh-{i}" for i in range(8)],
    ))
    det = DemandConcentrationDetector(threshold=0.5, window_hours=1.0)
    alerts = det.detect(trace)
    assert len(alerts) >= 1
    assert alerts[0].heuristic_id == "TX-001"
    assert alerts[0].severity == "high"


def test_tx001_quiet_on_old_docs():
    trace = Trace()
    base = 1000.0
    for i in range(10):
        trace.ingests.append(IngestEvent(
            doc_id=f"old-{i}", source="wiki", owner="wiki",
            namespace="ns", timestamp=base - 100000 + i,
            content=f"Old doc {i}", user_agent="wiki-agent",
        ))
    trace.queries.append(QueryEvent(
        query_id="q1", query_text="test query", timestamp=base + 5,
        retrieved_doc_ids=[f"old-{i}" for i in range(8)],
    ))
    det = DemandConcentrationDetector(threshold=0.5, window_hours=1.0)
    alerts = det.detect(trace)
    assert len(alerts) == 0


def test_tx001_threshold_boundary():
    trace = Trace()
    base = 1000.0
    for i in range(10):
        trace.ingests.append(IngestEvent(
            doc_id=f"d-{i}", source="s", owner="o",
            namespace="ns", timestamp=base if i < 5 else base - 200000,
            content=f"Doc {i}", user_agent="ua",
        ))
    trace.queries.append(QueryEvent(
        query_id="q1", query_text="q", timestamp=base,
        retrieved_doc_ids=[f"d-{i}" for i in range(10)],
    ))
    det = DemandConcentrationDetector(threshold=0.4, window_hours=1.0)
    alerts = det.detect(trace)
    assert len(alerts) >= 1


def test_tx001_empty_retrievals():
    trace = Trace()
    trace.queries.append(QueryEvent(
        query_id="q1", query_text="q", timestamp=1000,
        retrieved_doc_ids=[],
    ))
    det = DemandConcentrationDetector()
    alerts = det.detect(trace)
    assert len(alerts) == 0


def test_tx001_no_ingests():
    trace = Trace()
    trace.queries.append(QueryEvent(
        query_id="q1", query_text="q", timestamp=1000,
        retrieved_doc_ids=["missing-1", "missing-2"],
    ))
    det = DemandConcentrationDetector()
    alerts = det.detect(trace)
    assert len(alerts) == 0
