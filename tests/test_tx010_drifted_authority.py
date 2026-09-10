"""Tests for TX-010 Drifted Authorities detector."""
from toxindb.trace import Trace, IngestEvent
from toxindb.heuristics import DriftedAuthorityDetector


def test_tx010_fires_on_drifted_authority():
    trace = Trace()
    base = 1000000.0
    trace.ingests.append(IngestEvent(
        doc_id="old-signed", source="trusted", owner="owner",
        namespace="ns", timestamp=base - 1000 * 3600,
        content="Old signed doc", signature="old-sig", user_agent="ua",
    ))
    for i in range(5):
        trace.ingests.append(IngestEvent(
            doc_id=f"new-unsigned-{i}", source="trusted", owner="owner",
            namespace="ns", timestamp=base + i * 3600,
            content=f"New unsigned doc {i}", signature=None, user_agent="ua",
        ))
    det = DriftedAuthorityDetector(max_age_hours=720)
    alerts = det.detect(trace)
    assert any(a.heuristic_id == "TX-010" for a in alerts)


def test_tx010_quiet_recent_signed():
    trace = Trace()
    base = 1000000.0
    trace.ingests.append(IngestEvent(
        doc_id="recent-signed", source="trusted", owner="owner",
        namespace="ns", timestamp=base - 100,
        content="Recent signed", signature="recent-sig", user_agent="ua",
    ))
    trace.ingests.append(IngestEvent(
        doc_id="new-doc", source="trusted", owner="owner",
        namespace="ns", timestamp=base,
        content="New doc", signature=None, user_agent="ua",
    ))
    det = DriftedAuthorityDetector(max_age_hours=720)
    alerts = det.detect(trace)
    assert not any(a.heuristic_id == "TX-010" for a in alerts)


def test_tx010_quiet_all_unsigned():
    trace = Trace()
    base = 1000000.0
    for i in range(3):
        trace.ingests.append(IngestEvent(
            doc_id=f"u-{i}", source="src", owner="o",
            namespace="ns", timestamp=base + i,
            content=f"Doc {i}", signature=None, user_agent="ua",
        ))
    det = DriftedAuthorityDetector()
    alerts = det.detect(trace)
    assert not any(a.heuristic_id == "TX-010" for a in alerts)
