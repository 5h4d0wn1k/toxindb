"""Benchmark helpers (PoisonedRAG/BEIR-aligned scaffolding, offline)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Dict, Any


@dataclass
class BenchmarkResult:
    name: str
    tpr: float = 0.0
    fpr: float = 0.0
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0
    alerts_total: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "tpr": self.tpr,
            "fpr": self.fpr,
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
            "alerts_total": self.alerts_total,
        }
