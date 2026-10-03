"""More schema/config coverage."""
from toxindb import schema, Config


def test_schema_import():
    assert schema.TRACE_INGEST_SCHEMA is not None


def test_config_from_files(tmp_path):
    p = tmp_path / 'c.toml'
    p.write_text('[toxindb]\nstrict_schema = true\n')
    c = Config.from_file(str(p))
    assert c.strict_schema is True

    p2 = tmp_path / 'c.json'
    p2.write_text('{"strict_schema": false}')
    c2 = Config.from_file(str(p2))
    assert c2.strict_schema is False

    p3 = tmp_path / 'c.yaml'
    p3.write_text('toxindb:\n  strict_schema: true\n')
    c3 = Config.from_file(str(p3))
    assert c3.strict_schema is True

    c4 = Config.from_file('/nonexist.xyz')
    assert isinstance(c4, Config)
