"""Tests for TX-003 Embedding-Space Cluster detector."""
from toxindb.trace import Trace, IngestEvent, QueryEvent
from toxindb.heuristics import EmbeddingClusterDetector


def test_tx003_fires_on_similar_cluster():
    trace = Trace()
    base = 1000.0
    for i in range(5):
        trace.ingests.append(IngestEvent(
            doc_id=f"similar-{i}", source="s", owner="o",
            namespace="ns", timestamp=base + i,
            content="quantum computing quantum supremacy quantum advantage "
                    "quantum computing quantum supremacy quantum advantage",
            user_agent="ua",
        ))
    trace.queries.append(QueryEvent(
        query_id="q1", query_text="quantum", timestamp=base + 10,
        retrieved_doc_ids=[f"similar-{i}" for i in range(5)],
    ))
    det = EmbeddingClusterDetector(similarity_threshold=0.3, min_cluster_size=3)
    alerts = det.detect(trace)
    assert any(a.heuristic_id == "TX-003" for a in alerts)


def test_tx003_quiet_on_diverse_docs():
    trace = Trace()
    base = 1000.0
    contents = [
        "cats are furry animals that purr",
        "the stock market rises and falls daily",
        "python programming language tutorials",
        "ocean waves crash on rocky shores",
        "mountain climbing requires proper equipment",
    ]
    for i, content in enumerate(contents):
        trace.ingests.append(IngestEvent(
            doc_id=f"diverse-{i}", source="s", owner="o",
            namespace="ns", timestamp=base + i,
            content=content, user_agent="ua",
        ))
    trace.queries.append(QueryEvent(
        query_id="q1", query_text="general", timestamp=base + 10,
        retrieved_doc_ids=[f"diverse-{i}" for i in range(5)],
    ))
    det = EmbeddingClusterDetector(similarity_threshold=0.4, min_cluster_size=3)
    alerts = det.detect(trace)
    assert not any(a.heuristic_id == "TX-003" for a in alerts)


def test_tx003_quiet_small_cluster():
    trace = Trace()
    base = 1000.0
    for i in range(2):
        trace.ingests.append(IngestEvent(
            doc_id=f"small-{i}", source="s", owner="o",
            namespace="ns", timestamp=base + i,
            content="identical content here", user_agent="ua",
        ))
    trace.queries.append(QueryEvent(
        query_id="q1", query_text="q", timestamp=base + 10,
        retrieved_doc_ids=[f"small-{i}" for i in range(2)],
    ))
    det = EmbeddingClusterDetector(min_cluster_size=3)
    alerts = det.detect(trace)
    assert not any(a.heuristic_id == "TX-003" for a in alerts)
