"""Sigstore/DSSE provenance helpers (offline-first; optional dependencies)."""
from __future__ import annotations

import json
from typing import Dict, Any, Optional


def create_dsee_envelope(payload: Dict[str, Any], payload_type: str = "application/vnd.toxindb.provenance+json") -> Dict[str, Any]:
    """Create a minimal DSSE envelope structure (offline)."""
    return {
        "payload": payload,
        "payloadType": payload_type,
        "signatures": [],
    }


def attest_provenance(doc_id: str, owner: str, source: str, digest: Optional[str] = None) -> Dict[str, Any]:
    return {
        "doc_id": doc_id,
        "owner": owner,
        "source": source,
        "digest": digest,
    }
