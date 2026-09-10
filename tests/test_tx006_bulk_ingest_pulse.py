"""Tests for TX-006 Bulk-Ingest Pulse detector."""
from toxindb.trace import Trace, IngestEvent
from toxindb.heuristics import BulkIngestPulseDetector


def test_tx006_fires_on_bulk_pulse():
    trace = Trace()
    base = 1000.0
    for i in range(12):
        trace.ingests.append(IngestEvent(
            doc_id=f"bulk-{i}", source="attacker", owner="attacker",
            namespace="target", timestamp=base + i * 10,
            content=f"Bulk doc {i}", user_agent="ua",
        ))
    det = BulkIngestPulseDetector(threshold=10, window_hours=1.0)
    alerts = det.detect(trace)
    assert any(a.heuristic_id == "TX-006" for a in alerts)


def test_tx006_quiet_on_spread_ingests():
    trace = Trace()
    base = 1000.0
    for i in range(12):
        trace.ingests.append(IngestEvent(
            doc_id=f"spread-{i}", source="legit", owner="legit",
            namespace="ns", timestamp=base + i * 4000,
            content=f"Spread doc {i}", user_agent="ua",
        ))
    det = BulkIngestPulseDetector(threshold=10, window_hours=1.0)
    alerts = det.detect(trace)
    assert not any(a.heuristic_id == "TX-006" for a in alerts)


def test_tx006_quiet_below_threshold():
    trace = Trace()
    base = 1000.0
    for i in range(5):
        trace.ingests.append(IngestEvent(
            doc_id=f"few-{i}", source="s", owner="o",
            namespace="ns", timestamp=base + i,
            content=f"Doc {i}", user_agent="ua",
        ))
    det = BulkIngestPulseDetector(threshold=10, window_hours=1.0)
    alerts = det.detect(trace)
    assert not any(a.heuristic_id == "TX-006" for a in alerts)
