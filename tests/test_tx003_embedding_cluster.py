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


def _reference_tx003(trace, similarity_threshold, min_cluster_size):
    """The pre-#43 per-pair tokenisation implementation, for output equivalence."""
    from collections import defaultdict
    from toxindb.heuristics import _cosine_bow
    alerts = []
    doc_map = {d.doc_id: d for d in trace.ingests}
    query_groups = defaultdict(list)
    for query in trace.queries:
        for doc_id in dict.fromkeys(query.retrieved_doc_ids):
            if doc_id in doc_map:
                query_groups[query.query_id].append(doc_id)
    for query_id, doc_ids in query_groups.items():
        if len(doc_ids) < min_cluster_size:
            continue
        docs = [doc_map[did] for did in doc_ids]
        similar_pairs = 0
        total_pairs = 0
        for i in range(len(docs)):
            for j in range(i + 1, len(docs)):
                total_pairs += 1
                sim = _cosine_bow(docs[i].content, docs[j].content)
                if sim >= similarity_threshold:
                    similar_pairs += 1
        if total_pairs > 0:
            density = similar_pairs / total_pairs
            if density > 0.5 and similar_pairs >= 3:
                alerts.append((query_id, tuple(doc_ids), similar_pairs, total_pairs, density))
    return alerts


def test_tx003_output_equivalent_to_per_pair_tokens():
    """#43: tokenisation memoisation must be behaviour-identical (#43)."""
    import random
    rng = random.Random(99)
    trace = Trace()
    base = 10000.0
    vocab = [f"w{i}" for i in range(200)]
    for i in range(80):
        if i < 40:
            # near-identical cluster members: 5 shared template tokens + 2 unique
            content = "shared core template words " + " ".join(
                rng.choice(vocab) for _ in range(2))
        else:
            content = " ".join(rng.choice(vocab) for _ in range(8))
        trace.ingests.append(IngestEvent(
            doc_id=f"d-{i}", source="org", owner="org", namespace="ns",
            timestamp=base + i, content=content, user_agent="org-agent",
        ))
    for q in range(20):
        if q < 10:
            retrieved = [f"d-{rng.randrange(40)}" for _ in range(5)]
        else:
            retrieved = [f"d-{40 + rng.randrange(40)}" for _ in range(5)]
        trace.queries.append(QueryEvent(
            query_id=f"q-{q}", query_text="q", timestamp=base + 500 + q,
            retrieved_doc_ids=list(dict.fromkeys(retrieved)),
        ))
    det = EmbeddingClusterDetector(similarity_threshold=0.5, min_cluster_size=4)
    expected = _reference_tx003(trace, 0.5, 4)
    actual = [(a.query_id, tuple(a.doc_ids), int(a.detail.split("/")[0]),
               int(a.detail.split("/")[1].split(" ")[0]), a.confidence)
              for a in det.detect(trace)]
    assert actual == expected
    assert expected, "reference found no alerts; equivalence test is vacuous"
