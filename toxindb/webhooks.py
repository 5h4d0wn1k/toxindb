"""Webhook/SIEM outputs (offline-first; sending is opt-in)."""
from __future__ import annotations

import json
from typing import List, Dict, Any
from .heuristics import Alert


def alerts_to_webhook_payload(alerts: List[Alert]) -> Dict[str, Any]:
    return {
        "alert_count": len(alerts),
        "alerts": [a.to_dict() for a in alerts],
    }


def alerts_to_splunk_payload(alerts: List[Alert]) -> List[Dict[str, Any]]:
    events = []
    for a in alerts:
        events.append({
            "event": "toxindb_alert",
            "sourcetype": "toxindb",
            "fields": a.to_dict(),
        })
    return events


def alerts_to_elastic_payload(alerts: List[Alert]) -> List[Dict[str, Any]]:
    docs = []
    for a in alerts:
        docs.append({"index": {}, "_source": a.to_dict()})
    return docs
