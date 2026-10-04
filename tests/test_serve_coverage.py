"""Comprehensive tests for serve module."""
import json
import tempfile
import threading
import time
from http.client import HTTPConnection
from io import BytesIO
from unittest.mock import patch, MagicMock

from toxindb import serve


def test_handler_log_message():
    """Test that log_message suppresses logging."""
    handler = serve._Handler.__new__(serve._Handler)
    # Should not raise
    result = handler.log_message("test %s", "msg")
    assert result is None


def test_handler_set_headers():
    """Test _set_headers."""
    handler = serve._Handler.__new__(serve._Handler)
    handler.send_response = MagicMock()
    handler.send_header = MagicMock()
    handler.end_headers = MagicMock()
    
    handler._set_headers(201, "text/plain")
    handler.send_response.assert_called_with(201)
    handler.send_header.assert_called_with("Content-type", "text/plain")
    handler.end_headers.assert_called_once()


def test_handler_do_get_health():
    """Test GET /health."""
    handler = serve._Handler.__new__(serve._Handler)
    handler.path = "/health"
    handler._set_headers = MagicMock()
    handler.wfile = BytesIO()
    
    handler.do_GET()
    handler._set_headers.assert_called_with(200)
    handler.wfile.seek(0)
    data = json.loads(handler.wfile.read())
    assert data["status"] == "ok"


def test_handler_do_get_not_found():
    """Test GET other paths return 404."""
    handler = serve._Handler.__new__(serve._Handler)
    handler.path = "/other"
    handler._set_headers = MagicMock()
    handler.wfile = BytesIO()
    
    handler.do_GET()
    handler._set_headers.assert_called_with(404)
    handler.wfile.seek(0)
    data = json.loads(handler.wfile.read())
    assert data["error"] == "not found"


def test_handler_do_post_not_found():
    """Test POST to wrong path."""
    handler = serve._Handler.__new__(serve._Handler)
    handler.path = "/wrong"
    handler.headers = {}
    handler._set_headers = MagicMock()
    handler.wfile = BytesIO()
    
    handler.do_POST()
    handler._set_headers.assert_called_with(404)


def test_handler_do_post_invalid_json():
    """Test POST /analyze with invalid JSON."""
    handler = serve._Handler.__new__(serve._Handler)
    handler.path = "/analyze"
    handler.headers = {"Content-Length": "10"}
    handler.rfile = BytesIO(b"not json!!")
    handler._set_headers = MagicMock()
    handler.wfile = BytesIO()
    
    handler.do_POST()
    handler._set_headers.assert_called_with(400)
    handler.wfile.seek(0)
    data = json.loads(handler.wfile.read())
    assert "invalid json" in data["error"]


def test_handler_do_post_analyze_no_trace_path():
    """Test POST /analyze without trace_path."""
    handler = serve._Handler.__new__(serve._Handler)
    handler.path = "/analyze"
    handler.headers = {"Content-Length": "2"}
    handler.rfile = BytesIO(b"{}")
    handler._set_headers = MagicMock()
    handler.wfile = BytesIO()
    
    handler.do_POST()
    handler._set_headers.assert_called_with(400)
    handler.wfile.seek(0)
    data = json.loads(handler.wfile.read())
    assert "provide trace_path" in data["error"]


def test_handler_do_post_analyze_success(tmp_path):
    """Test successful analyze POST."""
    # Create a simple trace file
    trace_file = tmp_path / "test.jsonl"
    trace_file.write_text('{"type":"ingest","doc_id":"d1","source":"s","owner":"o","namespace":"ns","timestamp":1.0,"content":"c"}\n')
    
    handler = serve._Handler.__new__(serve._Handler)
    handler.path = "/analyze"
    handler.headers = {"Content-Length": str(len(json.dumps({"trace_path": str(trace_file)})))}
    handler.rfile = BytesIO(json.dumps({"trace_path": str(trace_file)}).encode())
    handler._set_headers = MagicMock()
    handler.wfile = BytesIO()
    
    handler.do_POST()
    handler._set_headers.assert_called_with(200)
    handler.wfile.seek(0)
    data = json.loads(handler.wfile.read())
    assert "alert_count" in data
    assert "alerts" in data


def test_handler_do_post_analyze_error(tmp_path):
    """Test analyze POST with error."""
    trace_file = tmp_path / "bad.jsonl"
    trace_file.write_text('bad json\n')
    
    handler = serve._Handler.__new__(serve._Handler)
    handler.path = "/analyze"
    handler.headers = {"Content-Length": str(len(json.dumps({"trace_path": str(trace_file)})))}
    handler.rfile = BytesIO(json.dumps({"trace_path": str(trace_file)}).encode())
    handler._set_headers = MagicMock()
    handler.wfile = BytesIO()
    
    handler.do_POST()
    handler._set_headers.assert_called_with(500)
    handler.wfile.seek(0)
    data = json.loads(handler.wfile.read())
    assert "error" in data


def test_handler_do_post_empty_body():
    """Test POST with empty body."""
    handler = serve._Handler.__new__(serve._Handler)
    handler.path = "/analyze"
    handler.headers = {}  # No Content-Length
    handler.rfile = BytesIO(b"")
    handler._set_headers = MagicMock()
    handler.wfile = BytesIO()
    
    handler.do_POST()
    handler._set_headers.assert_called_with(400)
    handler.wfile.seek(0)
    data = json.loads(handler.wfile.read())
    assert "provide trace_path" in data["error"]
