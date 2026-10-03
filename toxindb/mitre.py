"""MITRE ATLAS mapping helpers (offline)."""
from __future__ import annotations

from typing import Dict, List


ATLAS_MAPPINGS = {
    "TX-001": {"technique": "AML.T0015", "name": "Poison Training Data"},
    "TX-002": {"technique": "AML.T0048", "name": "Exfiltration via ML Inference API"},
    "TX-003": {"technique": "AML.T0015", "name": "Poison Training Data"},
    "TX-004": {"technique": "AML.T0020", "name": "Backdoor ML Model"},
    "TX-005": {"technique": "AML.T0040", "name": "ML Model Attribution"},
    "TX-006": {"technique": "AML.T0019", "name": "Publish Poisoned Datasets"},
    "TX-007": {"technique": "AML.T0015", "name": "Poison Training Data"},
    "TX-008": {"technique": "AML.T0015", "name": "Poison Training Data"},
    "TX-009": {"technique": "AML.T0019", "name": "Publish Poisoned Datasets"},
    "TX-010": {"technique": "AML.T0040", "name": "ML Model Attribution"},
    "TX-011": {"technique": "AML.T0015", "name": "Poison Training Data"},
    "TX-012": {"technique": "AML.T0018", "name": "Query System"},
}


def map_to_atlas(heuristic_id: str) -> Dict[str, str]:
    return ATLAS_MAPPINGS.get(heuristic_id, {"technique": "AML.UNKNOWN", "name": "Unknown"})
