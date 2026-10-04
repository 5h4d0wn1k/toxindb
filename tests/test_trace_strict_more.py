"""More trace coverage."""
from toxindb import Trace
import tempfile
import os


def test_trace_from_jsonl_basic():
    t = Trace.from_jsonl('examples/traces/clean_trace.jsonl')
    assert len(t.ingests) > 0


def test_trace_strict_mode():
    t = Trace.from_jsonl('examples/traces/clean_trace.jsonl', strict=True)
    assert t is not None
