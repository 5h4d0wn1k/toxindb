"""Tests for TX-007 Query-Doc Mismatch detector."""
from toxindb.trace import Trace, IngestEvent, QueryEvent
from toxindb.heuristics import QueryDocMismatchDetector


def test_tx007_fires_on_unrelated_docs():
    trace = Trace()
    trace.ingests.append(IngestEvent(
        doc_id="stuffed", source="s", owner="o",
        namespace="ns", timestamp=100.0,
        content="completely unrelated content about cooking recipes pasta sauce",
        user_agent="ua",
    ))
    trace.queries.append(QueryEvent(
        query_id="q1", query_text="quantum computing hardware security",
        timestamp=200.0, retrieved_doc_ids=["stuffed"],
    ))
    det = QueryDocMismatchDetector(distance_threshold=0.6)
    alerts = det.detect(trace)
    assert any(a.heuristic_id == "TX-007" for a in alerts)


def test_tx007_quiet_on_relevant_docs():
    trace = Trace()
    trace.ingests.append(IngestEvent(
        doc_id="related", source="s", owner="o",
        namespace="ns", timestamp=100.0,
        content="quantum computing hardware security analysis",
        user_agent="ua",
    ))
    trace.queries.append(QueryEvent(
        query_id="q1", query_text="quantum computing security",
        timestamp=200.0, retrieved_doc_ids=["related"],
    ))
    det = QueryDocMismatchDetector(distance_threshold=0.6)
    alerts = det.detect(trace)
    assert not any(a.heuristic_id == "TX-007" for a in alerts)


def test_tx007_quiet_no_retrievals():
    trace = Trace()
    trace.queries.append(QueryEvent(
        query_id="q1", query_text="q", timestamp=200.0,
        retrieved_doc_ids=[],
    ))
    det = QueryDocMismatchDetector()
    alerts = det.detect(trace)
    assert len(alerts) == 0
