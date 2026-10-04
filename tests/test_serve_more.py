"""More serve tests."""
from toxindb import serve


def test_serve_module():
    assert hasattr(serve, 'serve')
