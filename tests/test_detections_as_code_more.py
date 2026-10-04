"""DAC more tests."""
from toxindb import detections_as_code
import tempfile
import os


def test_dac_load_valid(tmp_path):
    p = tmp_path / 'r.yaml'
    p.write_text('rules:\n  - id: R1\n    name: r\n    description: d\n    heuristic: TX-001\n')
    rules = detections_as_code.load_rules(str(p))
    assert len(rules) == 1
    assert rules[0].to_dict()['id'] == 'R1'
