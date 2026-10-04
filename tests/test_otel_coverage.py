"""Additional coverage for otel module."""
from toxindb import otel


def test_langfuse_events_to_trace_empty():
    trace = otel.langfuse_events_to_trace([])
    assert len(trace.ingests) == 0
    assert len(trace.queries) == 0


def test_langfuse_events_ingest_variants():
    events = [
        {"type": "ingest", "doc_id": "d1", "source": "s", "owner": "o", "namespace": "ns", "timestamp": 1.0, "content": "c"},
        {"event": "document", "id": "d2", "timestamp": 2.0},  # minimal fields
    ]
    trace = otel.langfuse_events_to_trace(events)
    assert len(trace.ingests) == 2


def test_langfuse_events_query_variants():
    events = [
        {"type": "query", "query_id": "q1", "query_text": "t", "timestamp": 1.0},
        {"event": "retrieval", "id": "q2", "input": "search", "timestamp": 2.0},
    ]
    trace = otel.langfuse_events_to_trace(events)
    assert len(trace.queries) == 2


def test_langfuse_events_query_with_documents():
    events = [
        {
            "type": "query",
            "query_id": "q1",
            "query_text": "t",
            "timestamp": 1.0,
            "documents": [{"doc_id": "d1"}, "d2", None],
        }
    ]
    trace = otel.langfuse_events_to_trace(events)
    assert len(trace.queries) == 1
    assert len(trace.queries[0].retrieved_doc_ids) == 2


def test_langfuse_events_query_with_retrieved_doc_ids():
    events = [
        {
            "type": "query",
            "query_id": "q1",
            "query_text": "t",
            "timestamp": 1.0,
            "retrieved_doc_ids": ["d1", "d2"],
        }
    ]
    trace = otel.langfuse_events_to_trace(events)
    assert len(trace.queries) == 1


def test_langfuse_events_mixed():
    events = [
        {"type": "other", "data": 123},
        {"type": "ingest", "doc_id": "d1", "source": "s", "owner": "o", "namespace": "ns", "timestamp": 1.0, "content": "c"},
    ]
    trace = otel.langfuse_events_to_trace(events)
    assert len(trace.ingests) == 1
    assert len(trace.queries) == 0
