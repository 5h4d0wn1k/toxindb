"""Trace edge cases for coverage."""
from toxindb import Trace
import tempfile
import os


def test_trace_from_bad_json(tmp_path):
    p = tmp_path / 'bad.jsonl'
    p.write_text('not json\n')
    try:
        Trace.from_jsonl(str(p))
    except ValueError:
        pass


def test_trace_with_none_retrieved(tmp_path):
    p = tmp_path / 't.jsonl'
    p.write_text('{"type":"query","query_id":"q","query_text":"t","timestamp":1,"retrieved_doc_ids":null}\n')
    t = Trace.from_jsonl(str(p))
    assert len(t.queries) == 1


def test_trace_with_str_retrieved(tmp_path):
    p = tmp_path / 't2.jsonl'
    p.write_text('{"type":"query","query_id":"q","query_text":"t","timestamp":1,"retrieved_doc_ids":"bad"}\n')
    t = Trace.from_jsonl(str(p))
    assert len(t.queries) == 1
