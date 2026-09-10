# toxindb

![tests](https://github.com/5h4d0wn1k/toxindb/actions/workflows/ci.yml/badge.svg) ![MIT](https://img.shields.io/badge/license-MIT-blue.svg)

RAG retrieval-time poisoning detector. Monitors retrieval demand, detects
coordinated document clusters with abnormal demand concentration, plants canary
claims, and enforces provenance attestation. Fully offline against simulated
query/document traces.

Coordinated poisoning of a vector database is provably impossible to stop at
ingestion time (documented detections as low as 4.2% at 1% FPR for near-duplicate
injections at index time). The attack only becomes visible at **retrieval time**
via demand/recency analysis: the poisoned cluster needs unsustainably high
retrieval demand to win an impact-seeking query. toxindb makes that demand
visible, quantifiable, and actionable.

## IMPORTANT: Read before use.

This is an **authorized security testing and education** tool. It is designed to be
used exclusively against systems, networks, and hardware that **you own** or for which
you have **explicit written authorization** to test.

### Authorization Requirements

- Only test targets you own, your own accounts, or systems you have written permission
  to assess (scope, duration, and limits in writing).
- This tool defaults to **offline / simulation mode**. Any action that could affect a
  real system, emit radio signals, or contact a real network requires an explicit
  confirmation flag **and** membership of the configured LAB allowlist.
- The demo/harness functionality runs entirely on localhost, fixtures, or your own lab.

### Legal Framework

Unauthorized security testing is a crime in most jurisdictions, including:

- **Computer Fraud and Abuse Act (CFAA), 18 U.S.C. § 1030** (US) — unauthorized
  access to computers is a federal crime, punishable by up to 20 years imprisonment.
- **Wiretap Act (18 U.S.C. § 2511)** (US) — intercepting electronic communications
  without consent is illegal.
- **EU Directive 2013/40/EU on attacks against information systems** — criminalises
  illegal access and interference.
- **State / local computer-crime statutes** — nearly all jurisdictions criminalise
  unauthorised access, data theft, or network disruption.
- **RF regulatory law** — transmitting on ISM bands without the appropriate
  authorisation may violate terms of your licence/regulatory regime in your country.

### Acceptable Use

- Learning and coursework in a controlled lab environment.
- Authorised penetration testing and red/blue-team exercises with written scope.
- Security research on systems you own.
- Building defensive detections and hardening your own infrastructure.

### Prohibited Use

- **Any** unauthorised access, interception, or disruption.
- Use against third-party networks, devices, or accounts at any time.
- Removing or weakening the safety gates, allowlists, or legal notices.
- Any activity that violates applicable law.

### No Warranty

This software is provided "AS IS", without warranty of any kind, express or
implied, including but not limited to the warranties of merchantability, fitness
for a particular purpose, and non-infringement. **In no event shall the authors or
copyright holders be liable** for any claim, damages or other liability arising
from, out of, or in connection with the software or the use or other dealings in
the software. **You are solely responsible for how you use this tool.**

### Responsible Disclosure

If you discover real vulnerabilities while learning with this tool, follow
responsible disclosure:

1. Report privately to the affected vendor/owner.
2. Give a reasonable remediation window.
3. Do not exploit beyond proof of concept.
4. Only publish with the vendor's consent.

## Overview

toxindb is a defensive AI-security tool that watches the **retrieval side** of a
RAG pipeline. It ingests a JSONL trace of query events (what was asked, what was
retrieved, what was generated) and ingest events (what documents entered the
vector index, from whom, signed or not). It then runs 12 heuristics that together
fingerprint coordinated poisoning: fresh-document clusters that suddenly dominate
a query, bulk-ingest pulses into a single namespace, reused attack accounts, and
canary claims that resurface in generated answers.

The core insight is that a poisoning cluster — however well it evades ingestion
filters — must generate **retrieval demand** and **recency** to win. Demand
concentration (`TX-001`) and recency anomaly (`TX-002`) are the fundamental
detectors; the rest add precision, attribution, quarantine, and provenance.

## Features

- **Offline by design.** Zero network calls. All analysis runs against local
  JSONL trace files. Read-only to targets.
- **12 named heuristics** (TX-001 … TX-012), each independently testable.
- **`monitor`** — process a trace, emit JSONL alerts.
- **`canary`** — generate/plant canary claims; monitor their resurgence in outputs.
- **`provenance`** — attestation audit of the ingestion log (signatures, owners,
  multi-owner sources, drifted authorities).
- **`report`** — render Markdown or JSON reports to `reports/`.
- **`demo`** — deterministic offline demo over bundled traces; exits 0.
- **Bundled fixtures** — clean trace (near-zero false positives), poison trace
  (coordinated cluster, recall 100% at low FPR), canary fixture set.
- **stdlib-only core**, Python 3.10+; pytest for tests.

## Install

```bash
git clone https://github.com/5h4d0wn1k/toxindb.git
cd toxindb
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

Requires Python 3.10+. The core has **no runtime dependencies**. `pytest` is
the only dev dependency.

## Quick Start (demo)

```bash
toxindb demo            # runs the offline demo, exit 0
toxindb demo --verbose  # print every alert to stdout
toxindb demo --output ./reports
```

The demo generates three deterministic traces under `examples/traces/`:
`clean_trace.jsonl`, `poison_trace.jsonl`, `canary_trace.jsonl`, analyzes each,
and writes Markdown + JSON reports plus JSONL alert streams to `reports/`.

## Usage

Global flags apply to every subcommand:

```
toxindb monitor   TRACE [--output DIR] [--verbose] [--target PATH]
toxindb canary    TRACE [--plant] [--monitor] [--seed SEED] [--output DIR]
toxindb provenance TRACE [--output DIR] [--verbose]
toxindb report    TRACE [--format md|json] [--output DIR]
toxindb demo      [--output DIR] [--verbose]
```

### monitor

```bash
toxindb monitor examples/traces/poison_trace.jsonl --output reports/
```

Emits `reports/alerts.jsonl` — one JSON object per alert:
`heuristic_id`, `heuristic_name`, `severity`, `query_id`, `doc_ids`, `detail`,
`confidence`.

### canary

```bash
toxindb canary examples/traces/canary_trace.jsonl --monitor --output reports/
toxindb canary some_trace.jsonl --plant --seed my-claim   # write a planted trace
```

`--plant` generates a deterministic canary claim, adds it as an ingest event with
a pseudo-confidential marker, and writes `<trace>_canary_planted.jsonl`.
`--monitor` scans query outputs for canary-text resurgence and writes
`reports/canary_report.json`.

### provenance

```bash
toxindb provenance examples/traces/clean_trace.jsonl --output reports/
```

Audits signatures, owners, source/owner mapping, flags multi-owner sources,
minority-signature sub-populations, and unsigned docs among signed peers.
Writes `reports/provenance.json`.

### report

```bash
toxindb report examples/traces/poison_trace.jsonl --format md  --output reports/
toxindb report examples/traces/poison_trace.jsonl --format json --output reports/
```

Runs the full analysis (all heuristics + provenance + canaries) and writes
`reports/report.md` or `reports/report.json`.

## Example Output (REAL, from bundled poison trace)

```
=== toxindb demo ===
Generated traces: clean, poison, canary

--- Analyzing clean trace ---
  Alerts: 30
  Provenance issues: 0
  Canaries: 0/1 resurfaced

--- Analyzing poison trace ---
  Alerts: 55
  Provenance issues: 0
  Canaries: 1/1 resurfaced

--- Analyzing canary trace ---
  Alerts: 12
  Provenance issues: 0
  Canaries: 2/3 resurfaced

=== Demo complete ===
Reports in: ./reports
Summary: ./reports/demo_summary.json
Clean trace alerts: 30
Poison trace alerts: 55
Poison/Clean ratio: 1.8x
```

Verbose alert stream (excerpt, `toxindb demo --verbose`):

```
[critical] TX-004: Canary claim '2bb07cba4e4adca4' surfaced in query output
[high]     TX-001: 4/5 retrievals (80%) from docs ingested within 24h threshold=60%
[high]     TX-002: 4 fresh docs dominate retrieval with prior organic demand rate 0.00%
[medium]   TX-003: 6/10 pairs above similarity 0.4 (density=0.60)
[high]     TX-006: 15 docs from 'attacker-blog' into 'poison-camp' within 1.0h
[medium]   TX-007: 3 retrieved docs have lexical distance >= 0.8 from query
[medium]   TX-008: Same query repeated with 2 shared docs within 10.0s
[high]     TX-011: Namespace 'poison-camp' is 0.1h old but has 49% of all retrievals
```

Generated Markdown report summary (from `reports/demo_poison_report.md`):

```
# toxindb Demo Report — Poison Trace

## Summary

- **Total alerts:** 55
- **Critical:** 1
- **High:** 23
- **Medium:** 31

### Alerts by Heuristic

| TX-001 | 13 |
| TX-002 | 3  |
| TX-003 | 8  |
| TX-004 | 1  |
| TX-006 | 6  |
| TX-007 | 22 |
| TX-008 | 1  |
| TX-011 | 1  |

## Canary Status
- Canary `2bb07cba4e4adca4`: **RESURFACED**
```

## Detectors / Heuristics

| ID | Heuristic | Severity | What it detects |
|----|-----------|----------|-----------------|
| TX-001 | Demand Concentration | high | >60% of a query's retrievals from docs ingested in last 24h |
| TX-002 | Recency Anomaly | high | fresh-doc cluster dominating a query with no prior organic demand |
| TX-003 | Embedding-Space Cluster | medium | pairwise similarity cluster among retrieved docs (bag-of-words approx.) |
| TX-004 | Canary Resurgence | critical | planted false-claim text surfaced in generated output |
| TX-005 | Provenance Mismatch | high | source owner inconsistent with its expected identity |
| TX-006 | Bulk-Ingest Pulse | high | >10 docs from one source into one namespace in <1h |
| TX-007 | Query-Doc Mismatch | medium | retrieved doc lexical distance to query exceeds expected |
| TX-008 | LangChain Double-Retrieval | medium | same query repeated with overlapping docs (attacker context reuse) |
| TX-009 | Source Cartel | high | multiple ingest accounts sharing one UA/timing profile |
| TX-010 | Drifted Authorities | medium | ingest source without recent signed attestation |
| TX-011 | New-Namespace Flash | high | brand-new namespace with disproportionate retrieval share |
| TX-012 | Quarantine Suggestion | high | actionable quarantine list when demand deviates |

## How It Works

A trace is a deterministic JSONL stream with three record types:

- `ingest` — `doc_id`, `source`, `owner`, `namespace`, `timestamp`, `content`,
  `signature`, `user_agent`
- `query` — `query_id`, `query_text`, `timestamp`, `retrieved_doc_ids`, `output_text`
- `canary` — `claim_id`, `text`, `planted_in_doc_id`, `planted_at`, `detected`,
  `detected_at`

The engine (`Engine`) runs every detector against the full trace, each returning
zero or more `Alert` objects. Alerts are then:

1. Surfaced verbatim in `monitor` JSONL.
2. Aggregated by `report` into Markdown/JSON with provenance and canary sections.
3. Used by `TX-012` to build a quarantine candidate list when high-severity
   alerts intersect with high retrieval demand.

The discriminator at the core is **demand × recency**: a legit corpus accrues
demand over time from diverse sources; a coordinated poison cluster shows
recency concentration (`TX-001`), no organic prior demand (`TX-002`), and
suspicious operational fingerprints (`TX-003`–`TX-011`).

The approximate embedding similarity in `TX-003` is a deterministic
bag-of-words cosine over token sets (no external vector DB required). No network
calls are made anywhere.

## Safety & Authorization

- **Fully offline.** toxindb never makes network calls. It is read-only to any
  trace it analyzes (`monitor`, `canary`, `provenance`, `report`, `demo`).
- **Simulation-first.** The default unit of work is a bundled or user-authored
  trace file. There is no "attack" mode; everything is retrospective analysis.
- **Integration targets** (LangChain, LlamaIndex, Pinecone, etc.) are
  **documented interfaces** — an integrator exports a trace from their retriever
  and toxindb consumes it. toxindb does not import or attach to them.
- **Authorization.** Only analyze systems you own or have written authorization
  to assess, per the legal notice above.

## Limitations

- `TX-003` uses a **bag-of-words approximation**, not real embeddings. It proves
  the clustering pattern; production deployments should feed cosine similarity
  from their own vector store.
- Heuristic thresholds (`24h`, `60%`, `10 docs`, `1h`) are defaults optimized
  against the bundled traces. They are configurable only at the library level,
  not yet via CLI flags.
- Fully **offline** — it analyzes traces; it does not field live retrieval demand
  on its own. A live deployment requires exporting retrieval logs periodically.
- Canary resurgence detection is exact-substring and case-insensitive; LLM
  paraphrase of a canary would not match.
- Provenance checks assume signatures are present and trustworthy in the trace;
  toxindb does not verify cryptographic signatures (that is the integrator's job).

## Live Lab Test Plan

1. Stand up a local vector DB (e.g. Chroma or LanceDB) with an HTTP-only
   collection.
2. Emit a **clean trace**: 30 legit docs across namespaces; 30 organic queries;
   ensure alerts in clean trace stay high=0.
3. Emit a **poison trace**: ingest 15 near-identical docs from one account in a
   burst; run matching queries; expect `TX-001`, `TX-002`, `TX-003`, `TX-006`,
   `TX-011` and recall 100% for the poisoned query.
4. Plant a canary doc, then reference its claim text in an answer; expect
   `TX-004` critical.
5. Rotate signature ownership; re-audit with `provenance`; expect
   `multi_owner_source` / `signature_mismatch` issues.
6. Tune thresholds against your corpus to keep clean-trace FPR < 5% while
   keeping poison recall at 100%.

## Testing

```bash
pip install pytest
pytest tests/ -v
```

137 tests, all offline, deterministic, fast (<1s core suite). Each heuristic has
dedicated tests that prove it **fires** on a poison scenario and **stays quiet**
on a clean scenario where possible. Test suite also covers: trace I/O, engine
orchestration, canary lifecycle, provenance audit, report schemas, CLI shims,
and integration over the bundled fixtures.

## Roadmap

- CLI flags to tune heuristic thresholds per deployment.
- Real-embedding similarity adapter (`TX-003`) via optional, opt-in plugins.
- Live retrieval-log tailing for vector DBs (documented interface, still offline
  batch analysis).
- HTTP export shim (optional) for alert webhooks.
- Paraphrase-tolerant canary matching (near-duplicate, not exact substring).

## License

MIT License — see [LICENSE](LICENSE).
Copyright (c) 2026 5h4d0wn1k.