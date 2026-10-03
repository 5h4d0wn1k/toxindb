"""Additional streaming coverage."""
import json
import tempfile
import os

from toxindb import streaming


def test_streaming_with_empty_lines():
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
        f.write("\n\n")
        f.write(json.dumps({"key": "value"}) + "\n")
        f.write("\n")
        path = f.name
    try:
        items = list(streaming.iter_jsonl(path))
        assert len(items) == 1
        assert items[0]["key"] == "value"
    finally:
        os.unlink(path)


def test_streaming_with_bad_json():
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
        f.write(json.dumps({"good": 1}) + "\n")
        f.write("not valid json\n")
        f.write(json.dumps({"good": 2}) + "\n")
        path = f.name
    try:
        items = list(streaming.iter_jsonl(path))
        assert len(items) == 2
    finally:
        os.unlink(path)
