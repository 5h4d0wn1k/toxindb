"""Analysis engine — orchestrates heuristic detectors over a trace."""
from __future__ import annotations

import json
import os
from typing import List, Optional, Dict, Any

from .trace import Trace
from .heuristics import (
    Alert,
    DemandConcentrationDetector,
    RecencyAnomalyDetector,
    EmbeddingClusterDetector,
    CanaryResurgenceDetector,
    ProvenanceMismatchDetector,
    BulkIngestPulseDetector,
    QueryDocMismatchDetector,
    DoubleRetrievalDetector,
    SourceCartelDetector,
    DriftedAuthorityDetector,
    NewNamespaceFlashDetector,
    QuarantineDetector,
)


class Engine:
    def __init__(self, known_sources: Optional[Dict[str, str]] = None):
        self.detectors = [
            DemandConcentrationDetector(),
            RecencyAnomalyDetector(),
            EmbeddingClusterDetector(),
            CanaryResurgenceDetector(),
            ProvenanceMismatchDetector(known_sources=known_sources),
            BulkIngestPulseDetector(),
            QueryDocMismatchDetector(),
            DoubleRetrievalDetector(),
            SourceCartelDetector(),
            DriftedAuthorityDetector(),
            NewNamespaceFlashDetector(),
        ]
        self.quarantine_detector = QuarantineDetector()

    def analyze(self, trace: Trace) -> List[Alert]:
        all_alerts: List[Alert] = []
        for detector in self.detectors:
            all_alerts.extend(detector.detect(trace))
        quarantine_alerts = self.quarantine_detector.detect(trace, all_alerts)
        all_alerts.extend(quarantine_alerts)
        return all_alerts

    def analyze_to_jsonl(self, trace: Trace, output_path: str) -> List[Alert]:
        alerts = self.analyze(trace)
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w") as f:
            for alert in alerts:
                f.write(json.dumps(alert.to_dict()) + "\n")
        return alerts
