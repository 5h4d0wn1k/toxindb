"""SARIF (Static Analysis Results Interchange Format) export for toxindb alerts."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import List, Dict, Any
from .models import Alert


def _alert_level(severity: str) -> str:
    s = severity.lower()
    if s == "critical":
        return "error"
    if s == "high":
        return "error"
    if s == "medium":
        return "warning"
    return "note"


def alerts_to_sarif(alerts: List[Alert], tool_name: str = "toxindb", tool_version: str = "1.0.0") -> Dict[str, Any]:
    """Convert alerts to SARIF v2.1.0 format."""
    results = []
    for i, a in enumerate(alerts):
        results.append({
            "ruleId": a.heuristic_id or f"rule{i}",
            "level": _alert_level(a.severity),
            "message": {"text": a.detail or a.heuristic_name},
            "locations": [{
                "physicalLocation": {
                    "artifactLocation": {"uri": "trace.jsonl"},
                    "region": {"startLine": 1}
                }
            }],
            "properties": {
                "heuristic_name": a.heuristic_name,
                "severity": a.severity,
                "query_id": a.query_id,
                "doc_ids": a.doc_ids,
                "confidence": a.confidence,
            }
        })

    return {
        "version": "2.1.0",
        "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
        "runs": [{
            "tool": {
                "driver": {
                    "name": tool_name,
                    "informationUri": "https://github.com/5h4d0wn1k/toxindb",
                    "version": tool_version,
                    "rules": []
                }
            },
            "results": results,
            "properties": {
                "generated_at": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
            }
        }]
    }
