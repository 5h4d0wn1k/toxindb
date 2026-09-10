"""Tests for TX-012 Quarantine Suggestion detector."""
from toxindb.trace import Trace, IngestEvent, QueryEvent
from toxindb.heuristics import (
    QuarantineDetector,
    Alert,
)


def test_tx012_fires_when_flagged_docs_have_high_share():
    trace = Trace()
    base = 1000.0
    flagged = ["flagged-1", "flagged-2"]
    for fd in flagged:
        trace.ingests.append(IngestEvent(
            doc_id=fd, source="s", owner="o",
            namespace="ns", timestamp=base,
            content="content", user_agent="ua",
        ))
    for qi in range(10):
        trace.queries.append(QueryEvent(
            query_id=f"q-{qi}", query_text="q", timestamp=base + qi,
            retrieved_doc_ids=[flagged[0], flagged[1]],
        ))
    existing = [
        Alert("TX-001", "test", "high", "q-0", flagged, "test detail"),
    ]
    det = QuarantineDetector(demand_threshold=0.3)
    alerts = det.detect(trace, existing)
    assert any(a.heuristic_id == "TX-012" for a in alerts)


def test_tx012_quiet_no_high_severity():
    trace = Trace()
    trace.ingests.append(IngestEvent(
        doc_id="d1", source="s", owner="o",
        namespace="ns", timestamp=100.0,
        content="c", user_agent="ua",
    ))
    trace.queries.append(QueryEvent(
        query_id="q1", query_text="q", timestamp=200.0,
        retrieved_doc_ids=["d1"],
    ))
    existing = [
        Alert("TX-001", "test", "low", "q-0", ["d1"], "minor"),
    ]
    det = QuarantineDetector()
    alerts = det.detect(trace, existing)
    assert not any(a.heuristic_id == "TX-012" for a in alerts)


def test_tx012_quiet_low_retrieval_share():
    trace = Trace()
    trace.ingests.append(IngestEvent(
        doc_id="flagged", source="s", owner="o",
        namespace="ns", timestamp=100.0,
        content="c", user_agent="ua",
    ))
    base = 100.0
    for qi in range(10):
        trace.queries.append(QueryEvent(
            query_id=f"q-{qi}", query_text="q", timestamp=base + qi,
            retrieved_doc_ids=["unrelated"],
        ))
    existing = [
        Alert("TX-001", "test", "high", "q-0", ["flagged"], "detail"),
    ]
    det = QuarantineDetector(demand_threshold=0.5)
    alerts = det.detect(trace, existing)
    assert not any(a.heuristic_id == "TX-012" for a in alerts)
