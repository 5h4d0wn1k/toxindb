"""Additional coverage tests for trace module."""
import json
import os
import tempfile

from toxindb.trace import Trace, IngestEvent, QueryEvent, CanaryClaim


def test_trace_non_dict_record():
    """Test that non-dict records are skipped."""
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
        f.write('["not", "a", "dict"]\n')
        f.write(json.dumps({"type": "ingest", "doc_id": "d1", "source": "s", 
                            "owner": "o", "namespace": "ns", "timestamp": 1.0, 
                            "content": "c"}) + "\n")
        path = f.name
    try:
        trace = Trace.from_jsonl(path)
        assert len(trace.ingests) == 1
    finally:
        os.unlink(path)


def test_trace_ingest_missing_field():
    """Test ingest with missing required field raises ValueError."""
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
        f.write(json.dumps({"type": "ingest", "doc_id": "d1"}) + "\n")  # missing fields
        path = f.name
    try:
        Trace.from_jsonl(path)
        assert False, "Should have raised"
    except ValueError as e:
        assert "missing required ingest field" in str(e)


def test_trace_query_missing_field():
    """Test query with missing required field raises ValueError."""
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
        f.write(json.dumps({"type": "query", "query_text": "t"}) + "\n")  # missing query_id, timestamp
        path = f.name
    try:
        Trace.from_jsonl(path)
        assert False, "Should have raised"
    except ValueError as e:
        assert "missing required query field" in str(e)


def test_trace_canary_missing_field():
    """Test canary with missing required field raises ValueError."""
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
        f.write(json.dumps({"type": "canary", "claim_id": "c1"}) + "\n")  # missing fields
        path = f.name
    try:
        Trace.from_jsonl(path)
        assert False, "Should have raised"
    except ValueError as e:
        assert "missing required canary field" in str(e)


def test_trace_query_retrieved_none():
    """Test query with retrieved_doc_ids as None."""
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
        f.write(json.dumps({"type": "query", "query_id": "q1", "query_text": "t", 
                            "timestamp": 1.0, "retrieved_doc_ids": None}) + "\n")
        path = f.name
    try:
        trace = Trace.from_jsonl(path)
        assert len(trace.queries) == 1
        assert trace.queries[0].retrieved_doc_ids == []
    finally:
        os.unlink(path)


def test_trace_query_retrieved_string():
    """Test query with retrieved_doc_ids as string."""
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
        f.write(json.dumps({"type": "query", "query_id": "q1", "query_text": "t", 
                            "timestamp": 1.0, "retrieved_doc_ids": "not_a_list"}) + "\n")
        path = f.name
    try:
        trace = Trace.from_jsonl(path)
        assert len(trace.queries) == 1
        assert trace.queries[0].retrieved_doc_ids == []
    finally:
        os.unlink(path)


def test_trace_query_retrieved_invalid_type():
    """Test query with retrieved_doc_ids as int."""
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
        f.write(json.dumps({"type": "query", "query_id": "q1", "query_text": "t", 
                            "timestamp": 1.0, "retrieved_doc_ids": 123}) + "\n")
        path = f.name
    try:
        trace = Trace.from_jsonl(path)
        assert len(trace.queries) == 1
        assert trace.queries[0].retrieved_doc_ids == []
    finally:
        os.unlink(path)


def test_trace_query_retrieved_with_dupes_and_nones():
    """Test query retrieved_doc_ids deduplication and None filtering."""
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
        f.write(json.dumps({"type": "query", "query_id": "q1", "query_text": "t", 
                            "timestamp": 1.0, "retrieved_doc_ids": ["d1", "d1", None, "d2"]}) + "\n")
        path = f.name
    try:
        trace = Trace.from_jsonl(path)
        assert len(trace.queries) == 1
        assert trace.queries[0].retrieved_doc_ids == ["d1", "d2"]
    finally:
        os.unlink(path)


def test_trace_bad_json_raises_valueerror():
    """Test that bad JSON raises ValueError with proper message."""
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
        f.write('{"type": "ingest", bad json}\n')
        path = f.name
    try:
        Trace.from_jsonl(path)
        assert False, "Should have raised"
    except ValueError as e:
        assert "invalid JSON" in str(e)
    finally:
        os.unlink(path)


def test_trace_file_not_found():
    """Test that missing file raises appropriate error."""
    try:
        Trace.from_jsonl("/non/existent/file.jsonl")
        assert False, "Should have raised"
    except (OSError, IOError):
        pass  # Expected
