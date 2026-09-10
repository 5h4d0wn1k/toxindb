"""Tests for TX-011 New-Namespace Flash detector."""
from toxindb.trace import Trace, IngestEvent, QueryEvent
from toxindb.heuristics import NewNamespaceFlashDetector


def test_tx011_fires_on_new_namespace_high_share():
    trace = Trace()
    base = 1000000.0
    for i in range(5):
        trace.ingests.append(IngestEvent(
            doc_id=f"new-{i}", source="attacker", owner="attacker",
            namespace="flash-ns", timestamp=base + i,
            content=f"Flash doc {i}", user_agent="ua",
        ))
    trace.queries.append(QueryEvent(
        query_id="q1", query_text="q", timestamp=base + 10,
        retrieved_doc_ids=[f"new-{i}" for i in range(5)],
    ))
    det = NewNamespaceFlashDetector(age_threshold_hours=2.0, retrieval_share=0.1)
    alerts = det.detect(trace)
    assert any(a.heuristic_id == "TX-011" for a in alerts)


def test_tx011_quiet_on_old_namespace():
    trace = Trace()
    base = 1000000.0
    for i in range(5):
        trace.ingests.append(IngestEvent(
            doc_id=f"old-{i}", source="s", owner="o",
            namespace="old-ns", timestamp=base - 86400 + i * 8640,
            content=f"Old doc {i}", user_agent="ua",
        ))
    trace.queries.append(QueryEvent(
        query_id="q1", query_text="q", timestamp=base,
        retrieved_doc_ids=[f"old-{i}" for i in range(3)],
    ))
    det = NewNamespaceFlashDetector(age_threshold_hours=2.0, retrieval_share=0.1)
    alerts = det.detect(trace)
    assert not any(a.heuristic_id == "TX-011" for a in alerts)


def test_tx011_quiet_low_retrieval_share():
    trace = Trace()
    base = 1000000.0
    for i in range(3):
        trace.ingests.append(IngestEvent(
            doc_id=f"flash-{i}", source="s", owner="o",
            namespace="flash", timestamp=base + i,
            content=f"Flash {i}", user_agent="ua",
        ))
    for i in range(20):
        trace.ingests.append(IngestEvent(
            doc_id=f"old-{i}", source="s", owner="o",
            namespace="old", timestamp=base - 100000 + i,
            content=f"Old {i}", user_agent="ua",
        ))
    trace.queries.append(QueryEvent(
        query_id="q1", query_text="q", timestamp=base + 10,
        retrieved_doc_ids=[f"old-{i}" for i in range(10)] + [f"flash-0"],
    ))
    det = NewNamespaceFlashDetector(age_threshold_hours=2.0, retrieval_share=0.3)
    alerts = det.detect(trace)
    assert not any(a.heuristic_id == "TX-011" for a in alerts)


def test_tx011_quiet_equal_share_two_namespaces():
    trace = Trace()
    base = 1000000.0
    for i in range(5):
        trace.ingests.append(IngestEvent(
            doc_id=f"a-{i}", source="s", owner="o",
            namespace="ns-a", timestamp=base + i,
            content=f"Doc A {i}", user_agent="ua",
        ))
        trace.ingests.append(IngestEvent(
            doc_id=f"b-{i}", source="s", owner="o",
            namespace="ns-b", timestamp=base + i + 0.5,
            content=f"Doc B {i}", user_agent="ua",
        ))
    trace.queries.append(QueryEvent(
        query_id="q1", query_text="q", timestamp=base + 10,
        retrieved_doc_ids=[f"a-{i}" for i in range(5)] + [f"b-{i}" for i in range(5)],
    ))
    det = NewNamespaceFlashDetector(age_threshold_hours=2.0, retrieval_share=0.6)
    alerts = det.detect(trace)
    assert not any(a.heuristic_id == "TX-011" for a in alerts)
