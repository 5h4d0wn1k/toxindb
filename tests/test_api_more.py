"""API more coverage."""
from toxindb import api, Trace


def test_api_analyze_trace_obj():
    t = Trace.from_jsonl('examples/traces/poison_trace.jsonl')
    res = api.analyze_trace_obj(t)
    assert hasattr(res, 'alert_count')


def test_api_reports(tmp_path):
    t = Trace.from_jsonl('examples/traces/clean_trace.jsonl')
    res = api.analyze_trace_obj(t)
    paths = api.generate_reports_from_result(res, t, str(tmp_path))
    assert 'markdown' in paths
