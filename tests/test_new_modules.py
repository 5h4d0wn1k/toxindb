"""Tests for new modules (api, config, sarif, schema, etc.)."""
from toxindb import api, Config, Trace, alerts_to_sarif
from toxindb import models


def test_api_analyze_trace():
    res = api.analyze_trace('examples/traces/clean_trace.jsonl')
    assert hasattr(res, 'alert_count')


def test_config_from_dict():
    c = Config.from_dict({'strict_schema': True})
    assert c.strict_schema is True


def test_config_to_dict():
    c = Config()
    d = c.to_dict()
    assert 'demand_concentration_threshold' in d


def test_sarif_export():
    res = api.analyze_trace('examples/traces/clean_trace.jsonl')
    sarif = alerts_to_sarif(res.alerts)
    assert sarif['version'] == '2.1.0'


def test_trace_strict():
    Trace.from_jsonl('examples/traces/clean_trace.jsonl', strict=False)


def test_otel_helpers():
    from toxindb import otel
    trace = otel.langfuse_events_to_trace([])
    assert len(trace.ingests) == 0


def test_benchmarks():
    from toxindb import benchmarks
    b = benchmarks.BenchmarkResult(name='test')
    assert b.to_dict()['name'] == 'test'


def test_mitre():
    from toxindb import mitre
    m = mitre.map_to_atlas('TX-001')
    assert 'technique' in m
