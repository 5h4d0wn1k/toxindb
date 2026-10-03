"""Tests for webhooks and metrics."""
from toxindb import webhooks, metrics, api


def test_webhooks():
    res = api.analyze_trace('examples/traces/clean_trace.jsonl')
    p = webhooks.alerts_to_webhook_payload(res.alerts)
    assert 'alert_count' in p
    s = webhooks.alerts_to_splunk_payload(res.alerts)
    assert isinstance(s, list)
    e = webhooks.alerts_to_elastic_payload(res.alerts)
    assert isinstance(e, list)


def test_metrics():
    tpr, fpr, prec, rec, f1 = metrics.compute_metrics(10, 2, 88, 0)
    assert isinstance(tpr, float)
