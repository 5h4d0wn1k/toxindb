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
- Provenance attestation audit, including fully-unsigned source detection.
- Report renderer producing Markdown and JSON, plus a JSONL alert stream.
- `toxindb` CLI: `monitor`, `canary`, `provenance`, `report`, `demo`.
- 139-test suite covering every heuristic (each with both a poison-trace test
  that fires and a clean-trace test that stays quiet), trace I/O, canaries,
  provenance, reports, and the CLI.
- GitHub Actions CI on `ubuntu-latest`, running the suite and the offline demo.
- Educational-use documentation set: `ETHICS.md`, `SCOPE.md`, `SECURITY.md`,
  `CODE_OF_CONDUCT.md`, `CONTRIBUTING.md`, `AUTHORS.md`, `NOTICE.md`.
- Bug and feature issue templates, a PR template, `CODEOWNERS`, and
  `dependabot.yml` covering the GitHub Actions the project actually depends on.

### Changed

- `--demo` is accepted as a global flag as well as a subcommand, so the
  documented and CI-invoked forms behave identically.
- CI installs `pytest` explicitly and invokes `python3 -m pytest` for
  interpreter-compatibility.

### Known issues

These are tracked as open issues and are **not** fixed in the current tree.
See the [v1.0 hardening milestone](https://github.com/5h4d0wn1k/toxindb/milestone/1) for
current status.

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

