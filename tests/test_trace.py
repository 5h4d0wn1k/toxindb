"""Tests for the trace data model."""
import json
import os
import tempfile

from toxindb.trace import Trace, IngestEvent, QueryEvent, CanaryClaim


def test_ingest_event_to_dict():
    e = IngestEvent(doc_id="d1", source="s", owner="o", namespace="ns",
                    timestamp=1.0, content="c")
    d = e.to_dict()
    assert d["doc_id"] == "d1"
    assert d["source"] == "s"
    assert d["signature"] is None


def test_query_event_to_dict():
    e = QueryEvent(query_id="q1", query_text="text", timestamp=1.0,
                   retrieved_doc_ids=["d1"], output_text="out")
    d = e.to_dict()
    assert d["query_id"] == "q1"
    assert d["retrieved_doc_ids"] == ["d1"]


def test_canary_claim_to_dict():
    c = CanaryClaim(claim_id="c1", text="t", planted_in_doc_id="d",
                    planted_at=1.0)
    d = c.to_dict()
    assert d["claim_id"] == "c1"
    assert d["detected"] is False


def test_trace_roundtrip_jsonl():
    trace = Trace()
    trace.ingests.append(IngestEvent(
        doc_id="d1", source="s", owner="o", namespace="ns",
        timestamp=1.0, content="hello world",
    ))
    trace.queries.append(QueryEvent(
        query_id="q1", query_text="q", timestamp=2.0,
        retrieved_doc_ids=["d1"], output_text="answer",
    ))
    trace.canaries.append(CanaryClaim(
        claim_id="c1", text="canary", planted_in_doc_id="d1",
        planted_at=1.0,
    ))

    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
        path = f.name

    try:
        trace.to_jsonl(path)
        loaded = Trace.from_jsonl(path)
        assert len(loaded.ingests) == 1
        assert len(loaded.queries) == 1
        assert len(loaded.canaries) == 1
        assert loaded.ingests[0].doc_id == "d1"
        assert loaded.queries[0].query_id == "q1"
        assert loaded.canaries[0].claim_id == "c1"
    finally:
        os.unlink(path)


def test_trace_empty_jsonl():
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
        path = f.name
    try:
        trace = Trace.from_jsonl(path)
        assert len(trace.ingests) == 0
        assert len(trace.queries) == 0
    finally:
        os.unlink(path)


def test_trace_blank_lines():
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
        f.write("\n\n\n")
        path = f.name
    try:
        trace = Trace.from_jsonl(path)
        assert len(trace.ingests) == 0
    finally:
        os.unlink(path)


def test_trace_unknown_type():
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
        f.write(json.dumps({"type": "unknown_field"}) + "\n")
        path = f.name
    try:
        trace = Trace.from_jsonl(path)
        assert len(trace.ingests) == 0
    finally:
        os.unlink(path)


def test_trace_optional_fields():
    e = IngestEvent(doc_id="d1", source="s", owner="o", namespace="ns",
                    timestamp=1.0, content="c")
    assert e.signature is None
    assert e.user_agent == "default-agent"


def test_trace_ingest_defaults():
    e = IngestEvent(doc_id="d1", source="s", owner="o", namespace="ns",
                    timestamp=1.0, content="c", user_agent="custom-agent")
    assert e.user_agent == "custom-agent"


def test_trace_query_defaults():
    q = QueryEvent(query_id="q1", query_text="q", timestamp=1.0)
    assert q.retrieved_doc_ids == []
    assert q.output_text == ""


def test_from_jsonl_rejects_duplicate_ingest_doc_id():
    """Duplicate ingest doc_id must not silently discard provenance (#31)."""
    line1 = json.dumps({
        "type": "ingest", "doc_id": "d1", "source": "legit-src", "owner": "alice",
        "namespace": "ns", "timestamp": 1000.0, "content": "original", "signature": "sig:good",
    })
    line2 = json.dumps({
        "type": "ingest", "doc_id": "d1", "source": "evil-src", "owner": "mallory",
        "namespace": "ns", "timestamp": 1001.0, "content": "poisoned",
    })
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
        f.write(line1 + "\n" + line2 + "\n")
        path = f.name
    try:
        try:
            Trace.from_jsonl(path)
            raise AssertionError("expected ValueError for duplicate ingest doc_id")
        except ValueError as e:
            assert "duplicate ingest doc_id 'd1'" in str(e)
            assert "line 1" in str(e)
            assert ":2:" in str(e)
    finally:
        os.unlink(path)


def test_from_jsonl_accepts_reingest_under_distinct_doc_id():
    """A revised document is fine as long as each revision keeps its own doc_id."""
    line1 = json.dumps({
        "type": "ingest", "doc_id": "d1", "source": "legit-src", "owner": "alice",
        "namespace": "ns", "timestamp": 1000.0, "content": "original",
    })
    line2 = json.dumps({
        "type": "ingest", "doc_id": "d1-rev2", "source": "legit-src", "owner": "alice",
        "namespace": "ns", "timestamp": 1001.0, "content": "revised",
    })
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
        f.write(line1 + "\n" + line2 + "\n")
        path = f.name
    try:
        trace = Trace.from_jsonl(path)
        assert [i.doc_id for i in trace.ingests] == ["d1", "d1-rev2"]
        assert trace.ingests[0].content == "original"
        assert trace.ingests[1].content == "revised"
    finally:
        os.unlink(path)
