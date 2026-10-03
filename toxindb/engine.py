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
    def __init__(self, known_sources: Optional[Dict[str, str]] = None, **kwargs):
        self.detectors = [
            DemandConcentrationDetector(
                threshold=kwargs.get('demand_concentration_threshold', 0.6),
                window_hours=kwargs.get('demand_concentration_window_hours', 24.0),
            ),
            RecencyAnomalyDetector(
                threshold=kwargs.get('recency_anomaly_threshold', 0.7),
                window_hours=kwargs.get('recency_window_hours', 72.0),
            ),
            EmbeddingClusterDetector(
                threshold=kwargs.get('embedding_cluster_threshold', 0.8),
                min_size=kwargs.get('embedding_cluster_min_size', 3),
            ),
            CanaryResurgenceDetector(
                threshold=kwargs.get('canary_resurgence_threshold', 0.5),
            ),
            ProvenanceMismatchDetector(known_sources=known_sources),
            BulkIngestPulseDetector(
                threshold=kwargs.get('bulk_ingest_pulse_threshold', 0.8),
                window_hours=kwargs.get('bulk_ingest_window_hours', 1.0),
            ),
            QueryDocMismatchDetector(
                threshold=kwargs.get('query_doc_mismatch_threshold', 0.6),
            ),
            DoubleRetrievalDetector(
                threshold=kwargs.get('double_retrieval_threshold', 0.3),
            ),
            SourceCartelDetector(
                threshold=kwargs.get('source_cartel_threshold', 0.7),
                min_sources=kwargs.get('source_cartel_min_sources', 2),
            ),
            DriftedAuthorityDetector(
                threshold=kwargs.get('drifted_authority_threshold', 0.6),
            ),
            NewNamespaceFlashDetector(
                threshold=kwargs.get('new_namespace_flash_threshold', 0.8),
                window_hours=kwargs.get('new_namespace_window_hours', kwargs.get('new_namespace_flash_window_hours', 1.0)),
            ),
        ]
        self.quarantine_detector = QuarantineDetector(
            threshold=kwargs.get('quarantine_threshold', 0.5),
        )

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
