"""Tests for TX-002 Recency Anomaly detector."""
from toxindb.trace import Trace, IngestEvent, QueryEvent
from toxindb.heuristics import RecencyAnomalyDetector


def test_tx002_fires_on_fresh_cluster_no_prior():
    trace = Trace()
    base = 10000.0
    for i in range(5):
        trace.ingests.append(IngestEvent(
            doc_id=f"f-{i}", source="attacker", owner="attacker",
            namespace="ns", timestamp=base + i,
            content=f"Fresh doc {i}", user_agent="attacker",
        ))
    trace.queries.append(QueryEvent(
        query_id="q1", query_text="q", timestamp=base + 10,
        retrieved_doc_ids=[f"f-{i}" for i in range(4)],
    ))
    det = RecencyAnomalyDetector(window_hours=1.0, prior_window_hours=24.0)
    alerts = det.detect(trace)
    assert any(a.heuristic_id == "TX-002" for a in alerts)


def test_tx002_quiet_when_prior_demand_exists():
    trace = Trace()
    base = 10000.0
    target_docs = [f"d-{i}" for i in range(5)]
    old_docs = [f"old-{i}" for i in range(5)]
    for i in range(5):
        trace.ingests.append(IngestEvent(
            doc_id=f"d-{i}", source="org", owner="org",
            namespace="ns", timestamp=base + i,
            content=f"Doc {i}", user_agent="org-agent",
        ))
    for i in range(5):
        trace.ingests.append(IngestEvent(
            doc_id=f"old-{i}", source="org", owner="org",
            namespace="ns", timestamp=base - 86400 + i,
            content=f"Old doc {i}", user_agent="org-agent",
        ))
    for i in range(10):
        trace.queries.append(QueryEvent(
            query_id=f"pq-{i}", query_text="q",
            timestamp=base + 100 + i * 10,
            retrieved_doc_ids=target_docs,
        ))
    trace.queries.append(QueryEvent(
        query_id="q1", query_text="q", timestamp=base + 200,
        retrieved_doc_ids=target_docs,
    ))
    det = RecencyAnomalyDetector(window_hours=1.0, prior_window_hours=24.0)
    alerts = det.detect(trace)
    q1_alerts = [a for a in alerts if a.query_id == "q1"]
    assert len(q1_alerts) == 0


def test_tx002_quiet_single_doc():
    trace = Trace()
    base = 10000.0
    trace.ingests.append(IngestEvent(
        doc_id="single", source="s", owner="o", namespace="ns",
        timestamp=base, content="One doc", user_agent="ua",
    ))
    trace.queries.append(QueryEvent(
        query_id="q1", query_text="q", timestamp=base + 10,
        retrieved_doc_ids=["single"],
    ))
    det = RecencyAnomalyDetector()
    alerts = det.detect(trace)
    assert not any(a.heuristic_id == "TX-002" for a in alerts)
