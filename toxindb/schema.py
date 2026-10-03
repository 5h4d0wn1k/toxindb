"""JSONL schema validation for toxindb traces (optional, offline)."""
from __future__ import annotations

import json
from typing import Any, Dict

TRACE_INGEST_SCHEMA = {
    "type": "object",
    "required": ["type", "doc_id", "source", "owner", "namespace", "timestamp", "content"],
    "additionalProperties": True,
    "properties": {
        "type": {"type": "string", "enum": ["ingest"]},
        "doc_id": {"type": "string"},
        "source": {"type": "string"},
        "owner": {"type": "string"},
        "namespace": {"type": "string"},
        "timestamp": {"type": "number"},
        "content": {"type": "string"},
        "signature": {"type": ["string", "null"]},
        "user_agent": {"type": "string"},
    },
}

TRACE_QUERY_SCHEMA = {
    "type": "object",
    "required": ["type", "query_id", "query_text", "timestamp"],
    "additionalProperties": True,
    "properties": {
        "type": {"type": "string", "enum": ["query"]},
        "query_id": {"type": "string"},
        "query_text": {"type": "string"},
        "timestamp": {"type": "number"},
        "retrieved_doc_ids": {"type": ["array", "null"]},
        "output_text": {"type": "string"},
    },
}

TRACE_CANARY_SCHEMA = {
    "type": "object",
    "required": ["type", "claim_id", "text", "planted_in_doc_id", "planted_at"],
    "additionalProperties": True,
    "properties": {
        "type": {"type": "string", "enum": ["canary"]},
        "claim_id": {"type": "string"},
        "text": {"type": "string"},
        "planted_in_doc_id": {"type": "string"},
        "planted_at": {"type": "number"},
        "detected": {"type": "boolean"},
        "detected_at": {"type": ["number", "null"]},
    },
}
