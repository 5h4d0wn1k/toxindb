# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.0/).

## [Unreleased]

### Added

- **`toxindb demo` command.** Reproducible, offline demo that prints a
  red/amber/green verdict plus concrete, per-alert evidence (retrieved doc ids,
  timestamps, content snippets) for `examples/traces/poison_trace.jsonl`, with
  a deterministic `--seed` and `--json` for machine consumption.
- **Pluggable detection registry + config.** `toxindb detect` now loads
  `~/.config/toxindb/config.toml` (and `TOXINDB_CONFIG`) to enable/disable
  heuristics, set thresholds, and toggle outputs. Registry validates ids and
  surfaces unknown keys with suggestions.
- **Sliding windows and session tracking.** `--window-hours` on `detect`,
  `--window` presets (`smoke`/`nightly`/`full`), and first-class `session_id` on
  `QueryEvent` so cross-query correlation survives offline runs.
- **HTML reports and benchmarks scaffold.** `toxindb report` emits a static
  self-contained HTML with per-alert evidence; `toxindb bench` can replay
  traces and print JSON timings (no network calls).
- **CI gates and a "teeth" suite.** GitHub Actions run ruff, mypy, pytest,
  bandit, a dependency audit, and docs build on every push/PR; the new
  `tests/test_teeth_*` suites that prove each of those gates can actually fail.
- Educational-use documentation set: `ETHICS.md`, `SCOPE.md`, `SECURITY.md`,
  `CODE_OF_CONDUCT.md`, `CONTRIBUTING.md`, `AUTHORS.md`, `NOTICE.md`.
- Bug and feature issue templates, a PR template, `CODEOWNERS`, and
  `dependabot.yml` covering the GitHub Actions the project actually depends on.

### Fixed

- **TX-002 and TX-003 no longer rescan quadratically (#43).** The recency
  anomaly's prior-demand count was a triple-nested scan (queries x queries x
  docs x slots) and the embedding-cluster detector re-tokenised both documents
  for every pair of every query. Prior demand now comes from an inverted index
  of retrieving queries, and token vectors are computed once per document;
  output is byte-identical (asserted by reference-implementation tests). A
  4 000-query trace measured 33.7 s before and 0.17 s after. The withdrawn
  METRICS.md replay claim was restated with the measured numbers and the
  remaining TX-003 quadratic term.

- **`Trace.from_jsonl` rejects duplicate ingest `doc_id`s instead of silently
  discarding provenance.** Every `doc_id`-keyed map in `heuristics.py` is
  last-write-wins, so a trace that re-ingested a document under an existing
  `doc_id` silently dropped the earlier record — including the signed original
  that proved the document was legitimate — with no alert anywhere. The parse
  boundary now raises `ValueError` naming the `doc_id` and both line numbers,
  telling the operator to assign a distinct `doc_id` per revision.

- **`canary --plant` no longer overwrites the trace it was pointed at.** The
  output path was derived with `trace_path.replace(".jsonl", ...)`, and
  `str.replace` takes no occurrence count: with no `.jsonl` in the path it was
  a no-op, the output path silently fell back to the input, and the command
  appended two canary records to the operator's own evidence file, printed the
  input path as the destination, and exited 0. The damage compounded on repeat
  runs. It also rewrote *every* occurrence, so `a.jsonl.b.jsonl` became
  `a_canary_planted.jsonl.b_canary_planted.jsonl`. The output is now
  `<stem>_canary_planted.jsonl`, split on the final extension (#21).
- **`canary --plant` no longer stamps canaries in 1970.** The plant timestamp
  was the constant `999999.0`, and every recency window in the tool is measured
  as `event.timestamp - doc.timestamp`, so on any trace carrying real epoch
  timestamps the planted document sat outside every window -- on a trace at
  `1.75e9` it was 55.4 years stale and produced no TX-001. The plant now takes
  the trace's own latest timestamp, which keeps the tool deterministic and needs
  no clock. `--at TIMESTAMP` overrides it (#13).
- **`canary --plant` refuses a directory, a link to its own input, and a
  non-finite `--at`.** A directory named `traces.jsonl` crashed with
  `IsADirectoryError`; an output path that already existed as a symlink or
  hardlink to the input passed the overwrite guard on a string comparison and
  then clobbered the input; and `--at nan`/`inf`/`1e400` wrote the bare tokens
  `NaN`/`Infinity`, which RFC 8259 does not allow and which `json.loads` accepts
  back, so the break only reached external consumers.
- **A malformed timestamp is no longer a traceback.** `Trace.from_jsonl`
  validates nothing, so a record carrying `"timestamp": null` reached an
  unguarded `max()` and raised `TypeError` on a command that previously
  succeeded. Non-numeric and non-finite timestamps are now skipped, and a trace
  with none usable falls back rather than crashing.
- Docstring and comment corrections where a claim was not true: the plant
  timestamp defect was never about TX-004, which substring-matches canary text
  and does no timestamp arithmetic at all.
