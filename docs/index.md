# toxindb

> **⚠️ EDUCATIONAL USE ONLY — AUTHORIZED TESTING ONLY.**

RAG retrieval-time poisoning detector. Monitors retrieval demand, detects coordinated document clusters, plants canary claims, and enforces provenance attestation. Fully offline, deterministic, and evidence-first.

## Key Features

- **12 detection heuristics** (TX-001–TX-012) for retrieval-time poisoning
- **Fully offline** - zero network access by design
- **Deterministic** - reproducible results
- **Evidence-first** - SARIF, JSON, and Markdown reports
- **Library API** - embed in your RAG pipelines
- **Configurable** - tune thresholds without code changes

## Quick Start

```bash
pip install -e .
toxindb demo
```

## Use Cases

- Security testing of RAG systems (with authorization)
- Research and education on AI security
- Defensive monitoring of retrieval patterns
- Forensics and incident response
