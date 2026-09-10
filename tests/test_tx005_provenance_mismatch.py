"""Tests for TX-005 Provenance Mismatch detector."""
from toxindb.trace import Trace, IngestEvent
from toxindb.heuristics import ProvenanceMismatchDetector


def test_tx005_fires_on_mismatch():
    trace = Trace()
    trace.ingests.append(IngestEvent(
        doc_id="d1", source="trusted-repo", owner="impersonator",
        namespace="ns", timestamp=100.0, content="content",
        signature="fake-sig", user_agent="ua",
    ))
    det = ProvenanceMismatchDetector(known_sources={"trusted-repo": "real-owner"})
    alerts = det.detect(trace)
    assert len(alerts) == 1
    assert alerts[0].heuristic_id == "TX-005"


def test_tx005_quiet_on_match():
    trace = Trace()
    trace.ingests.append(IngestEvent(
        doc_id="d1", source="trusted-repo", owner="real-owner",
        namespace="ns", timestamp=100.0, content="content",
        signature="real-sig", user_agent="ua",
    ))
    det = ProvenanceMismatchDetector(known_sources={"trusted-repo": "real-owner"})
    alerts = det.detect(trace)
    assert len(alerts) == 0


def test_tx005_quiet_without_signature():
    trace = Trace()
    trace.ingests.append(IngestEvent(
        doc_id="d1", source="trusted-repo", owner="anyone",
        namespace="ns", timestamp=100.0, content="content",
        signature=None, user_agent="ua",
    ))
    det = ProvenanceMismatchDetector(known_sources={"trusted-repo": "real-owner"})
    alerts = det.detect(trace)
    assert len(alerts) == 0


def test_tx005_quiet_unknown_source():
    trace = Trace()
    trace.ingests.append(IngestEvent(
        doc_id="d1", source="unknown", owner="x",
        namespace="ns", timestamp=100.0, content="c",
        signature="s", user_agent="ua",
    ))
    det = ProvenanceMismatchDetector(known_sources={"trusted-repo": "real-owner"})
    alerts = det.detect(trace)
    assert len(alerts) == 0
