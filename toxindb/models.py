"""Data models."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any


@dataclass
class Alert:
    heuristic_id: str
    heuristic_name: str
    severity: str
    query_id: Optional[str]
    doc_ids: List[str]
    detail: str
    confidence: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "heuristic_id": self.heuristic_id,
            "heuristic_name": self.heuristic_name,
            "severity": self.severity,
            "query_id": self.query_id,
            "doc_ids": self.doc_ids,
            "detail": self.detail,
            "confidence": self.confidence,
        }


@dataclass
class Result:
    alerts: List[Alert] = field(default_factory=list)
    provenance_issues: List[Dict[str, Any]] = field(default_factory=list)
    canary_results: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def alert_count(self) -> int:
        return len(self.alerts)

    @property
    def high_severity_alerts(self) -> List[Alert]:
        return [a for a in self.alerts if a.severity.lower() in ("high", "critical")]
