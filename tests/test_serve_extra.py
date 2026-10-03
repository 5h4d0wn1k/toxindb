"""Extra serve coverage."""
from toxindb import serve
from unittest.mock import patch, MagicMock


def test_serve_function():
    """Test serve function."""
    with patch('toxindb.serve.HTTPServer') as mock_server:
        mock_instance = MagicMock()
        mock_server.return_value = mock_instance
        serve.serve(host='0.0.0.0', port=8080)
        mock_server.assert_called_once()
        args, kwargs = mock_server.call_args
        assert args[0] == ('0.0.0.0', 8080)
        mock_instance.serve_forever.assert_called_once()
