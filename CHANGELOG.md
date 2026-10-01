# Changelog

All notable changes to toxindb are recorded here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> **No tagged release exists yet.** Everything below is unreleased work on
> `main`. The package version in `pyproject.toml` reads `1.0.0`, but no `1.0.0`
> has been published — do not install from a tag expecting this content. The
> first release will be cut once the open `deep-review:` findings with High
> severity are closed.

## [Unreleased]

### Added

- Analysis engine with 12 retrieval-time poisoning heuristics, `TX-001`–`TX-012`
  (demand concentration, recency anomaly, embedding clusters, canary resurgence,
  provenance mismatch, bulk-ingest pulses, query/doc mismatch, double retrieval,
  source cartels, drifted authority, new-namespace flash, quarantine).
- Trace model and deterministic generator, with three bundled example traces
  (`clean_trace.jsonl`, `poison_trace.jsonl`, `canary_trace.jsonl`).
- Canary lifecycle — plant and monitor retrieval-time canary claims, with
  deterministic seeding.
- Provenance attestation audit: signature coverage per source, owner/source
  consistency, multi-owner sources, and shared-signature clustering. Note that
  unsigned docs are only flagged when the same source *also* has signed
  documents — a wholly unsigned source is currently missed (#8).
- Report renderer producing Markdown and JSON, plus a JSONL alert stream.
- `toxindb` CLI: `monitor`, `canary`, `provenance`, `report`, `demo`.
- Test suite covering every heuristic (each with both a poison-trace test
  that fires and a clean-trace test that stays quiet), trace I/O, canaries,
  provenance, reports, and the CLI. 139 tests at the `1.0.0` baseline; 166 with
  the `canary --plant` regressions fixed above and their closing fences.
- GitHub Actions CI on `ubuntu-latest`, running the suite and the offline demo
  across Python 3.10–3.13, plus gates that make the documented promises
  checkable: a no-network `ast` scan, a determinism gate that diffs two demo
  runs, a gate that executes every runnable command in the README, and
  "teeth" suites that prove each of those gates can actually fail.
- Educational-use documentation set: `ETHICS.md`, `SCOPE.md`, `SECURITY.md`,
  `CODE_OF_CONDUCT.md`, `CONTRIBUTING.md`, `AUTHORS.md`, `NOTICE.md`.
- Bug and feature issue templates, a PR template, `CODEOWNERS`, and
  `dependabot.yml` covering the GitHub Actions the project actually depends on.

### Fixed

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

### Changed

- `--demo` is accepted as a global flag as well as a subcommand, so the
  documented and CI-invoked forms behave identically.
- CI installs `pytest` explicitly and invokes `python3 -m pytest` for
  interpreter-compatibility.

### Known issues

These are tracked as open issues and are **not** fixed in the current tree.
See the [v1.0 hardening milestone](https://github.com/5h4d0wn1k/toxindb/milestone/1) for
current status.

- **A wholly unsigned source is invisible to both the provenance audit and
  TX-010.** `provenance.py` only reports an unsigned doc when that source also
  has a signed peer, so a source with no signatures at all is never flagged.
  This is the primary supply-chain signal, and a unit test currently asserts
  the silence (#8).
- `SECURITY.md` directs vulnerability reports to a GitHub `users.noreply`
  address, which cannot receive mail (#15).
- `CONTRIBUTING.md` instructs `pip install -e ".[dev]"`, but `pyproject.toml`
  defines no `dev` extra.
- Several heuristics undercount or miscount under specific trace shapes
  (see `CRT` and `DAT` issues in the backlog).
- `package-data` glob in `pyproject.toml` does not match the bundled traces
  under a wheel build.
- `METRICS.md` and the README cite a test count that has drifted from the
  actual suite size.

