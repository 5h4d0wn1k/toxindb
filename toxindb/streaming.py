"""Streaming utilities for large traces (offline, deterministic)."""
from __future__ import annotations

from typing import Iterator, Dict, Any


def iter_jsonl(path: str) -> Iterator[Dict[str, Any]]:
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception:
                continue


import json
