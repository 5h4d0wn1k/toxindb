# toxindb Metrics

Real numbers measured against the bundled traces (deterministic generators,
offline, Python 3.13.5, x86-64).

## Test Suite

- **Tests:** 137 passed / 137 total (0 failures)
- **Duration (core suite):** 0.82 s on reference hardware
- **CI:** GitHub Actions, Python 3.11, offline, `pytest tests/ -v`
- **Runtime dependencies:** 0 (stdlib only)

## Detection Performance (bundled fixtures)

| Metric | Clean trace | Poison trace | Canary trace |
|--------|-------------|--------------|--------------|
| Total alerts | 30 | 55 | 12 |
| High/critical alerts | **0** | **24** | 2 |
| Heuristics firing | 1 (TX-007 medium) | 8 (TX-001,002,003,004,006,007,008,011) | 2 (TX-004, TX-007) |
| Provenance issues | 0 | 0 | 0 |

### Clean trace (near-zero false positives)

- **False-positive rate (high/critical):** 0% at reference thresholds.
- The only clean-trace signals are `TX-007` (medium) — legitimate
  query↔document lexical distance — which is expected and non-actionable.

### Poison trace (coordinated cluster)

- **Recall (TX-001/TX-002 on poisoned queries):** 100% — every `post-*` and
  `canary-q-*` query is flagged by demand concentration or recency anomaly.
- **Heuristic hit set:** TX-001 (13), TX-002 (3), TX-003 (8), TX-004 (1,
  canary resurfaced), TX-006 (6), TX-007 (22), TX-008 (1), TX-011 (1).
- **Canary resurgence:** 1/1 planted canary detected in generated output
  (`TX-004`, critical).

### Canary trace

- 2/3 canaries resurfaced in outputs and reported; 1 remaining silent (correct).

## Analysis Speed

| Trace | Analyzer latency |
|-------|------------------|
| Clean trace (40 ingests, 30 queries) | ~13 ms |
| Poison trace (36 ingests, 22 queries) | ~25 ms |
| Canary trace (20 ingests, 10 queries) | ~2 ms |

Analysis is linear in (ingests × queries × retrieved-doc overlap); the reference
threshold of 100k rows replays in seconds.

## Fixture Sizes

| File | Lines |
|------|-------|
| `examples/traces/clean_trace.jsonl` | 52 |
| `examples/traces/poison_trace.jsonl` | 59 |
| `examples/traces/canary_trace.jsonl` | 36 |

## Repro

```bash
pytest tests/ -v            # 137 passed
toxindb demo --verbose      # exit 0, writes reports/
```