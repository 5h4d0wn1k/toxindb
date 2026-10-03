"""Configuration for toxindb (offline-first, deterministic defaults)."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Dict, Any, Optional
import os
import json


@dataclass
class Config:
    # Detection thresholds
    demand_concentration_threshold: float = 0.6
    demand_concentration_window_hours: float = 24.0
    recency_anomaly_threshold: float = 0.7
    recency_window_hours: float = 72.0
    embedding_cluster_threshold: float = 0.8
    embedding_cluster_min_size: int = 3
    canary_resurgence_threshold: float = 0.5
    bulk_ingest_pulse_threshold: float = 0.8
    bulk_ingest_window_hours: float = 1.0
    query_doc_mismatch_threshold: float = 0.6
    double_retrieval_threshold: float = 0.3
    source_cartel_threshold: float = 0.7
    source_cartel_min_sources: int = 2
    drifted_authority_threshold: float = 0.6
    new_namespace_flash_threshold: float = 0.8
    new_namespace_window_hours: float = 1.0
    quarantine_threshold: float = 0.5

    # General
    strict_schema: bool = False
    enable_jsonschema: bool = False
    max_trace_size_mb: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Config":
        return cls(**{k: v for k, v in d.items() if hasattr(cls, k)})

    @classmethod
    def from_toml(cls, path: str) -> "Config":
        try:
            import tomllib
        except Exception:
            try:
                import tomli as tomllib  # type: ignore
            except Exception:
                return cls()
        try:
            with open(path, "rb") as f:
                data = tomllib.load(f)
            return cls.from_dict(data.get("toxindb", data))
        except Exception:
            return cls()

    @classmethod
    def from_yaml(cls, path: str) -> "Config":
        try:
            import yaml
        except Exception:
            return cls()
        try:
            with open(path, "r") as f:
                data = yaml.safe_load(f) or {}
            return cls.from_dict(data.get("toxindb", data))
        except Exception:
            return cls()

    @classmethod
    def from_file(cls, path: str) -> "Config":
        if path.endswith((".toml", ".TOML")):
            return cls.from_toml(path)
        if path.endswith((".yaml", ".yml")):
            return cls.from_yaml(path)
        if path.endswith(".json"):
            try:
                with open(path) as f:
                    return cls.from_dict(json.load(f))
            except Exception:
                return cls()
        return cls()
