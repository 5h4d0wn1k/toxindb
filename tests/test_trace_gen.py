"""Tests for the trace generator module."""
import os
import tempfile

from toxindb.trace_gen import (
    generate_clean_trace,
    generate_poison_trace,
    generate_canary_trace,
    trace_to_jsonl,
    ensure_demo_traces,
    get_traces_dir,
)


def test_generate_clean_trace():
    trace = generate_clean_trace()
    assert len(trace.ingests) > 0
    assert len(trace.queries) > 0
    assert len(trace.canaries) > 0


def test_generate_poison_trace():
    trace = generate_poison_trace()
    assert len(trace.ingests) > 0
    poison_docs = [i for i in trace.ingests if "attacker" in i.source]
    assert len(poison_docs) > 0


def test_generate_canary_trace():
    trace = generate_canary_trace()
    assert len(trace.canaries) == 3
    assert len(trace.ingests) > 0


def test_trace_to_jsonl():
    trace = generate_clean_trace()
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
        path = f.name
    try:
        result = trace_to_jsonl(trace, path)
        assert os.path.exists(path)
        assert result == path
        with open(path) as f:
            lines = [l.strip() for l in f if l.strip()]
        assert len(lines) > 0
    finally:
        os.unlink(path)


def test_get_traces_dir():
    d = get_traces_dir()
    assert d.endswith(os.path.join("examples", "traces"))


def test_clean_trace_deterministic():
    t1 = generate_clean_trace(seed=42)
    t2 = generate_clean_trace(seed=42)
    assert len(t1.ingests) == len(t2.ingests)
    assert t1.ingests[0].doc_id == t2.ingests[0].doc_id


def test_poison_trace_has_coordinated_docs():
    trace = generate_poison_trace()
    poison_sources = set(i.source for i in trace.ingests if "attacker" in i.source)
    assert len(poison_sources) == 1


def test_canary_trace_all_canaries_planted():
    trace = generate_canary_trace()
    canary_doc_ids = {c.planted_in_doc_id for c in trace.canaries}
    ingested_ids = {i.doc_id for i in trace.ingests}
    assert canary_doc_ids.issubset(ingested_ids)


def test_clean_trace_has_organic_sources():
    trace = generate_clean_trace()
    sources = set(i.source for i in trace.ingests if "canary" not in i.source)
    assert len(sources) >= 2


def test_poison_trace_has_post_attack_queries():
    trace = generate_poison_trace()
    post_queries = [q for q in trace.queries if q.query_id.startswith("post-")]
    assert len(post_queries) > 0
    for q in post_queries:
        poison_docs = [d for d in q.retrieved_doc_ids if "poison" in d]
        assert len(poison_docs) >= 1
