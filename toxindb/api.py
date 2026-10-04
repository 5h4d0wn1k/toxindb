"""Library API for toxindb (programmatic usage, offline)."""
from __future__ import annotations

from pathlib import Path
from typing import Union, Optional, List, Dict, Any

from .trace import Trace
from .engine import Engine
from .heuristics import Alert
from .models import Result
from .config import Config
from .report import generate_reports
from .sarif import alerts_to_sarif


def analyze_trace(
    trace_path: Union[str, Path],
    config: Optional[Config] = None,
    strict: bool = False,
) -> Result:
    """Analyze a JSONL trace file and return Result."""
    cfg = config or Config()
    trace = Trace.from_jsonl(str(trace_path), strict=strict or cfg.strict_schema)
    engine = Engine(
        demand_concentration_threshold=cfg.demand_concentration_threshold,
        demand_concentration_window_hours=cfg.demand_concentration_window_hours,
        recency_anomaly_threshold=cfg.recency_anomaly_threshold,
        recency_window_hours=cfg.recency_window_hours,
        embedding_cluster_threshold=cfg.embedding_cluster_threshold,
        embedding_cluster_min_size=cfg.embedding_cluster_min_size,
        canary_resurgence_threshold=cfg.canary_resurgence_threshold,
        bulk_ingest_pulse_threshold=cfg.bulk_ingest_pulse_threshold,
        bulk_ingest_window_hours=cfg.bulk_ingest_window_hours,
        query_doc_mismatch_threshold=cfg.query_doc_mismatch_threshold,
        double_retrieval_threshold=cfg.double_retrieval_threshold,
        source_cartel_threshold=cfg.source_cartel_threshold,
        source_cartel_min_sources=cfg.source_cartel_min_sources,
        drifted_authority_threshold=cfg.drifted_authority_threshold,
        new_namespace_flash_threshold=cfg.new_namespace_flash_threshold,
        new_namespace_window_hours=cfg.new_namespace_window_hours,
        quarantine_threshold=cfg.quarantine_threshold,
    )
    alerts = engine.analyze(trace)
    return Result(alerts=alerts)


def analyze_trace_obj(trace: Trace, config: Optional[Config] = None) -> Result:
    """Analyze an in-memory Trace object."""
    cfg = config or Config()
    engine = Engine(
        demand_concentration_threshold=cfg.demand_concentration_threshold,
        demand_concentration_window_hours=cfg.demand_concentration_window_hours,
        recency_anomaly_threshold=cfg.recency_anomaly_threshold,
        recency_window_hours=cfg.recency_window_hours,
        embedding_cluster_threshold=cfg.embedding_cluster_threshold,
        embedding_cluster_min_size=cfg.embedding_cluster_min_size,
        canary_resurgence_threshold=cfg.canary_resurgence_threshold,
        bulk_ingest_pulse_threshold=cfg.bulk_ingest_pulse_threshold,
        bulk_ingest_window_hours=cfg.bulk_ingest_window_hours,
        query_doc_mismatch_threshold=cfg.query_doc_mismatch_threshold,
        double_retrieval_threshold=cfg.double_retrieval_threshold,
        source_cartel_threshold=cfg.source_cartel_threshold,
        source_cartel_min_sources=cfg.source_cartel_min_sources,
        drifted_authority_threshold=cfg.drifted_authority_threshold,
        new_namespace_flash_threshold=cfg.new_namespace_flash_threshold,
        new_namespace_window_hours=cfg.new_namespace_window_hours,
        quarantine_threshold=cfg.quarantine_threshold,
    )
    alerts = engine.analyze(trace)
    return Result(alerts=alerts)


def generate_reports_from_result(result: Result, trace: Trace, out_dir: Union[str, Path]) -> Dict[str, str]:
    """Generate reports from Result and Trace."""
    return generate_reports(result, trace, str(out_dir))


def alerts_to_sarif_dict(alerts: List[Alert], **kwargs) -> Dict[str, Any]:
    """Export alerts as SARIF dict."""
    return alerts_to_sarif(alerts, **kwargs)
