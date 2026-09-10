"""Provenance attestation audit of ingestion logs."""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional

from .trace import Trace, IngestEvent


@dataclass
class ProvenanceReport:
    total_docs: int
    signed_docs: int
    unsigned_docs: int
    unique_sources: int
    unique_owners: int
    source_owner_map: Dict[str, str]
    issues: List[Dict]

    def to_dict(self) -> dict:
        return asdict(self)


def audit_provenance(trace: Trace) -> ProvenanceReport:
    source_owners: Dict[str, set] = defaultdict(set)
    signed_count = 0
    unsigned_count = 0
    issues: List[Dict] = []

    for ingest in trace.ingests:
        source_owners[ingest.source].add(ingest.owner)
        if ingest.signature:
            signed_count += 1
        else:
            unsigned_count += 1

    for source, owners in source_owners.items():
        if len(owners) > 1:
            issues.append({
                "type": "multi_owner_source",
                "source": source,
                "owners": sorted(owners),
                "severity": "high",
                "detail": f"Source '{source}' has {len(owners)} different owners",
            })

    source_sigs: Dict[str, Counter] = defaultdict(Counter)
    for ingest in trace.ingests:
        if ingest.signature:
            source_sigs[ingest.source][ingest.signature] += 1

    for source, sig_counts in source_sigs.items():
        if len(sig_counts) >= 2:
            dominant_sig, dominant_count = sig_counts.most_common(1)[0]
            total_signed = sum(sig_counts.values())
            if dominant_count / total_signed > 0.5:
                for sig, count in sig_counts.items():
                    if sig != dominant_sig and count >= 2:
                        issues.append({
                            "type": "signature_mismatch",
                            "source": source,
                            "minority_signature": sig,
                            "count": count,
                            "severity": "high",
                            "detail": (
                                f"Source '{source}' has {count} docs with "
                                f"minority signature '{sig}' vs "
                                f"{dominant_count} with dominant '{dominant_sig}'"
                            ),
                        })

    for ingest in trace.ingests:
        if not ingest.signature:
            has_signed_peers = any(
                i.source == ingest.source and i.signature
                for i in trace.ingests
            )
            if has_signed_peers:
                issues.append({
                    "type": "unsigned_among_signed",
                    "doc_id": ingest.doc_id,
                    "source": ingest.source,
                    "severity": "medium",
                    "detail": f"Doc '{ingest.doc_id}' unsigned while source has signed docs",
                })

    source_summary = {}
    for source, owners in source_owners.items():
        source_summary[source] = sorted(owners)[0] if len(owners) == 1 else "MULTIPLE"

    return ProvenanceReport(
        total_docs=len(trace.ingests),
        signed_docs=signed_count,
        unsigned_docs=unsigned_count,
        unique_sources=len(source_owners),
        unique_owners=len(set(i.owner for i in trace.ingests)),
        source_owner_map=source_summary,
        issues=issues,
    )
