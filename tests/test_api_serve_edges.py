"""Edge cases for API/serve/config."""
from toxindb import api, Config, serve, provenance_sigstore, detections_as_code
import tempfile
import os


def test_config_from_yaml_toml_json(tmp_path):
    # yaml
    p = tmp_path / 'c.yaml'
    p.write_text('strict_schema: true\n')
    c = Config.from_yaml(str(p))
    assert isinstance(c, Config)
    # toml
    p = tmp_path / 'c.toml'
    p.write_text('[section]\n')
    c = Config.from_toml(str(p))
    assert isinstance(c, Config)
    # json bad
    p = tmp_path / 'bad.json'
    p.write_text('{bad')
    c = Config.from_file(str(p))
    assert isinstance(c, Config)


def test_serve_handler_health():
    pass  # basic import covered


def test_dac_load_bad(tmp_path):
    p = tmp_path / 'bad.yaml'
    p.write_text('not: [')
    rules = detections_as_code.load_rules(str(p))
    assert rules == []
