"""Tests for sliding windows and HTML report."""
from toxindb import sliding, html_report, Trace, api


def test_sliding_windows():
    wins = sliding.sliding_window([1, 2, 3], 2)
    assert len(wins) > 0


def test_sliding_empty():
    assert sliding.sliding_window([], 5) == []


def test_html_report():
    t = Trace.from_jsonl('examples/traces/clean_trace.jsonl')
    res = api.analyze_trace_obj(t)
    html = html_report.render_html_report(res.alerts)
    assert '<html>' in html
