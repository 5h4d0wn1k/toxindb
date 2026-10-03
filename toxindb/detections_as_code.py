"""Detections-as-code: YAML/JSON rule definitions (offline, deterministic)."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Dict, Any, List, Optional


@dataclass
class DetectionRule:
    id: str
    name: str
    description: str
    heuristic: str
    severity: str = "medium"
    enabled: bool = True
    parameters: Dict[str, Any] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        if d["parameters"] is None:
            d["parameters"] = {}
        return d


def load_rules(path: str) -> List[DetectionRule]:
    try:
        import yaml
    except Exception:
        return []
    try:
        with open(path, "r") as f:
            data = yaml.safe_load(f) or {}
        rules = []
        for r in data.get("rules", []):
            rules.append(DetectionRule(
                id=r["id"],
                name=r.get("name", r["id"]),
                description=r.get("description", ""),
                heuristic=r.get("heuristic", ""),
                severity=r.get("severity", "medium"),
                enabled=r.get("enabled", True),
                parameters=r.get("parameters") or {},
            ))
        return rules
    except Exception:
        return []
