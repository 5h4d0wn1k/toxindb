"""Tests for streaming, detections-as-code, provenance_sigstore."""
from toxindb import streaming, detections_as_code, provenance_sigstore


def test_streaming():
    # iterate over a file
    for item in streaming.iter_jsonl('examples/traces/clean_trace.jsonl'):
        assert isinstance(item, dict)
        break


def test_dac():
    rules = detections_as_code.load_rules('/tmp/nonexistent.yaml')
    assert rules == []


def test_prov():
    env = provenance_sigstore.create_dsee_envelope({'test': 1})
    assert 'payload' in env
