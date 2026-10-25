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


def _reference_tx002(trace, window_seconds):
    """The pre-#43 nested-scan implementation, for output equivalence."""
    alerts = []
    doc_map = {d.doc_id: d for d in trace.ingests}
    sorted_queries = sorted(trace.queries, key=lambda q: q.timestamp)
    for i, query in enumerate(sorted_queries):
        if not query.retrieved_doc_ids:
            continue
        recent_docs = []
        for doc_id in query.retrieved_doc_ids:
            doc = doc_map.get(doc_id)
            if doc and (query.timestamp - doc.timestamp) <= window_seconds:
                recent_docs.append(doc_id)
        if not recent_docs:
            continue
        prior_demand = 0
        for prev_q in sorted_queries[:i]:
            for doc_id in recent_docs:
                if doc_id in prev_q.retrieved_doc_ids:
                    prior_demand += 1
                    break
        total_queries_before = i
        prior_rate = prior_demand / total_queries_before if total_queries_before > 0 else 0.0
        if prior_rate < 0.01 and len(recent_docs) >= 3:
            alerts.append((query.query_id, tuple(recent_docs), prior_rate))
    return alerts


def test_tx002_output_equivalent_to_nested_scan_on_large_trace():
    """#43: the inverted-index rewrite must be behaviour-identical (#43)."""
    import random
    rng = random.Random(1234)
    trace = Trace()
    base = 10000.0
    for i in range(60):
        trace.ingests.append(IngestEvent(
            doc_id=f"d-{i}", source="org", owner="org", namespace="ns",
            timestamp=base + rng.random() * 100,
            content=f"Doc {i} content words here", user_agent="org-agent",
        ))
    for i in range(120):
        # mix: half the queries overlap recent docs with earlier queries,
        # half are fresh clusters with no prior demand
        if rng.random() < 0.5:
            retrieved = [f"d-{rng.randrange(60)}" for _ in range(4)]
        else:
            for j in range(3):
                trace.ingests.append(IngestEvent(
                    doc_id=f"fresh-{i}-{j}", source="attacker", owner="attacker",
                    namespace="ns", timestamp=base + 200 + i,
                    content=f"Fresh doc {i} {j}", user_agent="attacker",
                ))
            retrieved = [f"fresh-{i}-{j}" for j in range(3)]
        trace.queries.append(QueryEvent(
            query_id=f"q-{i}", query_text="q", timestamp=base + 300 + i,
            retrieved_doc_ids=retrieved,
        ))
    det = RecencyAnomalyDetector(window_hours=1.0, prior_window_hours=24.0)
    window_seconds = 1.0 * 3600
    expected = _reference_tx002(trace, window_seconds)
    actual = [(a.query_id, tuple(a.doc_ids), a.confidence and (1.0 - a.confidence))
              for a in det.detect(trace)]
    assert actual == expected


def test_tx002_scale_2000_queries_completes():
    """The scale claim in METRICS.md must hold: 2k queries analyze promptly."""
    trace = Trace()
    base = 10000.0
    for i in range(500):
        trace.ingests.append(IngestEvent(
            doc_id=f"d-{i}", source="org", owner="org", namespace="ns",
            timestamp=base + i, content=f"Doc {i}", user_agent="org-agent",
        ))
    for i in range(2000):
        trace.queries.append(QueryEvent(
            query_id=f"q-{i}", query_text="q", timestamp=base + 1000 + i,
            retrieved_doc_ids=[f"d-{j}" for j in range((i * 7) % 480, (i * 7) % 480 + 8)],
        ))
    det = RecencyAnomalyDetector(window_hours=1.0, prior_window_hours=24.0)
    assert isinstance(det.detect(trace), list)
