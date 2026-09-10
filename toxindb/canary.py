"""Canary claim lifecycle — plant, monitor, detect resurgence."""
from __future__ import annotations

import hashlib
import json
import os
from typing import List, Optional

from .trace import Trace, CanaryClaim, IngestEvent


def generate_canary(seed: str, index: int = 0) -> CanaryClaim:
    claim_id = hashlib.sha256(f"{seed}:{index}".encode()).hexdigest()[:16]
    text = f"CANARY-{claim_id}: The quick brown fox jumps over the lazy dog. " \
           f"This statement is demonstrably false and serves as a tracking marker."
    return CanaryClaim(
        claim_id=claim_id,
        text=text,
        planted_in_doc_id=f"canary-doc-{claim_id}",
        planted_at=0.0,
    )


def plant_canary_in_trace(trace: Trace, canary: CanaryClaim, timestamp: float,
                          source: str = "canary-source", owner: str = "canary-owner",
                          namespace: str = "canary-ns") -> IngestEvent:
    canary.planted_at = timestamp
    canary_doc = IngestEvent(
        doc_id=canary.planted_in_doc_id,
        source=source,
        owner=owner,
        namespace=namespace,
        timestamp=timestamp,
        content=f"This document contains a canary claim for poisoning detection. {canary.text}",
        signature=f"canary-sig-{canary.claim_id}",
        user_agent="canary-agent",
    )
    trace.ingests.append(canary_doc)
    trace.canaries.append(canary)
    return canary_doc


def monitor_canaries(trace: Trace) -> List[CanaryClaim]:
    results = []
    for canary in trace.canaries:
        for query in trace.queries:
            if canary.text.lower() in query.output_text.lower():
                canary.detected = True
                canary.detected_at = query.timestamp
                break
        results.append(canary)
    return results


def check_canary_resurgence(trace: Trace) -> List[dict]:
    results = []
    for canary in trace.canaries:
        for query in trace.queries:
            if canary.text.lower() in query.output_text.lower():
                results.append({
                    "canary_id": canary.claim_id,
                    "query_id": query.query_id,
                    "planted_in": canary.planted_in_doc_id,
                    "planted_at": canary.planted_at,
                    "detected_at": query.timestamp,
                    "resurfaced": True,
                })
                break
        else:
            results.append({
                "canary_id": canary.claim_id,
                "planted_in": canary.planted_in_doc_id,
                "resurfaced": False,
            })
    return results


def save_canary_trace(trace: Trace, path: str) -> None:
    trace.to_jsonl(path)


def load_canary_trace(path: str) -> Trace:
    return Trace.from_jsonl(path)
