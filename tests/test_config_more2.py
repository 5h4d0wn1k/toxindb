"""More config coverage."""
from toxindb import Config


def test_config_from_empty():
    c = Config.from_dict({})
    assert isinstance(c, Config)
