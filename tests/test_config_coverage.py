"""Extra config coverage."""
from toxindb import config


def test_config_from_yaml_and_toml_and_json(tmp_path):
    p = tmp_path / 'c.yaml'
    p.write_text('toxindb:\n  strict_schema: true\n')
    c = config.Config.from_yaml(str(p))
    assert c.strict_schema is True
    p = tmp_path / 'c.toml'
    p.write_text('[toxindb]\nstrict_schema = false\n')
    c = config.Config.from_toml(str(p))
    assert c.strict_schema is False
    p = tmp_path / 'c.json'
    p.write_text('{"strict_schema": true}')
    c = config.Config.from_file(str(p))
    assert c.strict_schema is True
