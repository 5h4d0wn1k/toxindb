"""Tests for TX-009 Source Cartel detector."""
from toxindb.trace import Trace, IngestEvent
from toxindb.heuristics import SourceCartelDetector


def test_tx009_fires_on_cartel():
    trace = Trace()
    base = 1000.0
    ua = "shared-ua"
    sources = ["src-a", "src-b", "src-c"]
    ts = base
    for si, src in enumerate(sources):
        for i in range(4):
            trace.ingests.append(IngestEvent(
                doc_id=f"cartel-{si}-{i}", source=src, owner=src,
                namespace="ns", timestamp=ts,
                content=f"Cartel doc {si}-{i}", user_agent=ua,
            ))
            ts += 1
    det = SourceCartelDetector()
    alerts = det.detect(trace)
    assert any(a.heuristic_id == "TX-009" for a in alerts)


def test_tx009_quiet_distinct_agents():
    trace = Trace()
    base = 1000.0
    for i in range(5):
        trace.ingests.append(IngestEvent(
            doc_id=f"distinct-{i}", source=f"src-{i}", owner=f"owner-{i}",
            namespace="ns", timestamp=base + i,
            content=f"Doc {i}", user_agent=f"agent-{i}",
        ))
    det = SourceCartelDetector()
    alerts = det.detect(trace)
    assert not any(a.heuristic_id == "TX-009" for a in alerts)


def test_tx009_quiet_few_sources():
    trace = Trace()
    base = 1000.0
    for i in range(5):
        trace.ingests.append(IngestEvent(
            doc_id=f"few-{i}", source=f"src-{i % 2}", owner="o",
            namespace="ns", timestamp=base + i,
            content=f"Doc {i}", user_agent="shared-ua",
        ))
    det = SourceCartelDetector()
    alerts = det.detect(trace)
    assert not any(a.heuristic_id == "TX-009" for a in alerts)
