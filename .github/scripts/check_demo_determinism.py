#!/usr/bin/env python3
"""Assert that the bundled demo is deterministic.

Run-to-run variation in a security tool is a defect, not a cosmetic issue: it
means two analysts looking at the same evidence can reach different conclusions
and neither can tell why. The demo is the artifact this repository ships as
"here is what toxindb does", so it has to be byte-stable.

How output is compared
----------------------
Each output file is parsed and re-serialised into a canonical form, and the two
runs' canonical forms are compared. Parsing rather than line-matching matters:
an earlier version of this script dropped *whole lines* whose text contained the
substring ``generated_at``, so if the JSON report were ever rendered compactly
the whole report would collapse onto one line, that line would match, and the
report would silently leave the comparison while the gate stayed green.
Key-level normalisation cannot fail that way.

A file that does not decode as UTF-8 is compared as raw bytes rather than being
decoded with replacement characters, which would turn two different byte strings
into the same text.

What is normalised, and what is not
-----------------------------------
Two things, both scoped as narrowly as the code allows:

1. **Report metadata, and only report metadata.** The ``generated_at`` key is
   removed from the *top level* of a JSON report, and the ``**Generated:**``
   line is removed from the *header* of a Markdown report -- that is, only
   before the first heading. Both record when a report was written, and nothing
   else in this codebase produces either: ``generated_at`` appears exactly once
   in the whole package, at ``report.py:100``.

   The scoping is the point. An earlier version removed the key at any depth
   and dropped any line containing the marker, which meant a detector that grew
   its own ``generated_at`` field would have its genuinely per-call value
   absorbed, silently. Metadata is metadata because it is *not* detector
   output; if it moves, it should stop being normalised and this gate should
   start complaining.

2. **The ordering of ``doc_ids`` in TX-008 alerts only.** TX-008 builds this
   list from a set, so its order varies with the interpreter's hash seed. That
   is a real defect (issue #22), normalised only while it is open.

   It is deliberately *not* applied to other heuristics: sorting every
   detector's doc_ids would hide any future ordering bug anywhere in the
   package. In Markdown the sort is further confined to the ``### TX-008``
   section, and any heading at any level ends that section.

Everything else must match exactly: alert counts, heuristic ids, severities,
confidences, detail strings, alert ordering, doc_ids *content*, the set of files
produced, and the bytes of any file that is not a report.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# The one JSON key treated as report metadata, removed from the top level only.
REPORT_METADATA_KEY = "generated_at"
# The one heuristic whose doc_ids ordering is normalised, and why.
NORMALISED_HEURISTIC = "TX-008"

_BACKTICKED = re.compile(r"`([^`]*)`")
_ANY_HEADING = re.compile(r"^\s{0,3}#{1,6}\s")
_TX_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(TX-\d+)")
_GENERATED_LINE = re.compile(r"^\s*(?:[-*+]\s+)?\*\*Generated:\*\*")
_DOCUMENTS_LINE = re.compile(r"^(\s*-\s*\*\*Documents:\*\*\s*)(\S.*?)\s*$")
# A Documents tail that is *nothing but* a comma-separated list of doc ids.
# Anything else -- prose, a count, a trailing note -- is left untouched, because
# reordering part of a sentence would mean guessing where the list ends.
_ID_LIST = re.compile(r"^`[^`]*`(?:,\s*`[^`]*`)*$")


# --------------------------------------------------------------------------
# Normalisation
# --------------------------------------------------------------------------


def _sort_one_heuristic(value):
    """Sort one heuristic's doc_ids, wherever it appears. In place."""
    if isinstance(value, dict):
        if (
            value.get("heuristic_id") == NORMALISED_HEURISTIC
            and isinstance(value.get("doc_ids"), list)
        ):
            value["doc_ids"] = sorted(value["doc_ids"], key=str)
        for item in value.values():
            _sort_one_heuristic(item)
    elif isinstance(value, list):
        for item in value:
            _sort_one_heuristic(item)
    return value


def _canonical_json(text: str) -> str | None:
    """Canonicalise a whole JSON report document.

    Report metadata is removed from the top level only. Sorting doc_ids is
    applied throughout, because alerts are nested and every alert record
    carries its own ``heuristic_id``.
    """
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if isinstance(data, dict):
        data.pop(REPORT_METADATA_KEY, None)
    return json.dumps(_sort_one_heuristic(data), sort_keys=True, ensure_ascii=False)


def _canonical_jsonl(text: str) -> str | None:
    """Canonicalise JSON Lines, one record at a time.

    No metadata is removed here. These files hold raw alert records, so a
    ``generated_at`` key inside one would be detector output rather than report
    metadata, and absorbing it would hide real nondeterminism.
    """
    lines = []
    for raw in text.splitlines():
        if not raw.strip():
            lines.append(raw)
            continue
        try:
            record = json.loads(raw)
        except ValueError:
            return None
        lines.append(
            json.dumps(_sort_one_heuristic(record), sort_keys=True, ensure_ascii=False)
        )
    return "\n".join(lines)


def _canonical_markdown(text: str) -> str:
    out = []
    in_header = True
    section = None
    for line in text.splitlines(keepends=True):
        if in_header and _GENERATED_LINE.match(line):
            continue
        # Any heading at any level ends the header and closes the current
        # section. Matching only `### TX-\d+` would leave `section` latched onto
        # TX-008 for the rest of the document.
        if _ANY_HEADING.match(line):
            in_header = False
            heading = _TX_HEADING.match(line)
            section = heading.group(1) if heading else None
        if section == NORMALISED_HEURISTIC:
            line = _sort_markdown_documents(line)
        out.append(line)
    return "".join(out)


def _sort_markdown_documents(line: str) -> str:
    stripped = line.rstrip("\n")
    newline = line[len(stripped):]
    match = _DOCUMENTS_LINE.match(stripped)
    if not match:
        return line
    prefix, tail = match.group(1), match.group(2)
    if not _ID_LIST.match(tail):
        return line
    ids = _BACKTICKED.findall(tail)
    return f"{prefix}{', '.join(f'`{i}`' for i in sorted(ids))}{newline}"


def canonical_bytes(raw: bytes, suffix: str) -> bytes:
    """Return a canonical form of `raw`, or `raw` itself if it is not a report.

    Anything that is not a .json, .jsonl or .md file is returned untouched: a
    .txt or .csv sidecar is not Markdown, and running it through the Markdown
    normaliser would mean reordering text in a file whose format we do not know.
    """
    if suffix not in (".json", ".jsonl", ".md"):
        return raw
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        # Not text. Comparing the bytes is stricter than comparing a lossy
        # decode, which would report two different files as identical.
        return raw
    if suffix == ".json":
        canonical = _canonical_json(text)
    elif suffix == ".jsonl":
        canonical = _canonical_jsonl(text)
    else:
        canonical = _canonical_markdown(text)
    if canonical is None:
        # Not machine-readable after all. Comparing raw text is still a real
        # comparison, so this is a fallback rather than a skip.
        return raw
    return canonical.encode("utf-8")


def describe_policy() -> str:
    return (
        f"top-level '{REPORT_METADATA_KEY}' in JSON reports, the "
        f"'**Generated:**' header line in Markdown, and {NORMALISED_HEURISTIC} "
        f"doc_ids order"
    )


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------


def run_demo(dest: Path) -> None:
    """Run `python -m toxindb demo` once, into `dest`.

    `python -m` puts the working directory first on `sys.path`, so this
    deliberately measures the checkout: the demo job installs editable, and
    the gate teeth script injects its mutations into a copy of the tree that
    only takes effect if the copy is what gets imported. The cost is that
    `ensure_demo_traces()` rewrites the committed fixtures on every run, so the
    tree assertion in `main()` is what keeps that honest. Today the rewritten
    bytes match what is committed and the assertion passes; the day
    `trace_gen.py` changes they will not, and that is the point of asserting it
    rather than assuming it.
    """
    if dest.exists():
        shutil.rmtree(dest)
    completed = subprocess.run(
        [sys.executable, "-m", "toxindb", "demo", "--output", str(dest)],
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        sys.stderr.write(completed.stdout)
        sys.stderr.write(completed.stderr)
        raise SystemExit(
            f"the demo failed to run (rc={completed.returncode}); "
            "this is not a determinism result"
        )
    # The output directory is created here rather than relied upon from the
    # demo, so that a demo which writes no files produces an empty directory
    # instead of a missing one. Both mean "no output", but only one of them
    # reaches the comparison that reports it.
    dest.mkdir(parents=True, exist_ok=True)


def _files(root: Path) -> set[Path]:
    return {p.relative_to(root) for p in root.rglob("*") if p.is_file()}


def _fresh_dir(path: Path) -> None:
    """Make `path` exist and be empty, so a re-run into a fixed directory works."""
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)


def _read(path: Path) -> bytes:
    return path.read_bytes()


def _tree_state(root: Path) -> str | None:
    """A snapshot of the working tree, including gitignored paths.

    Returns None outside a git checkout, where the assertion is skipped with a
    printed note rather than assumed to have passed.
    """
    proc = subprocess.run(
        [
            "git",
            "status",
            "--porcelain",
            "--untracked-files=all",
            "--ignored=matching",
        ],
        cwd=root,
        capture_output=True,
        text=True,
    )
    return None if proc.returncode != 0 else proc.stdout


def _assert_tree_unchanged(before: str | None, after: str | None, root: Path) -> int:
    if before is None or after is None:
        print("  note   skipped the working-tree assertion (not a git checkout)")
        return 0
    if before == after:
        return 0
    # This is a real finding, and the same one the docs gate asserts. The demo
    # regenerates its fixtures through `trace_gen.ensure_demo_traces()`, which
    # writes relative to the *package* directory. Under the editable install the
    # demo job uses, that is the checkout, so the fixtures are rewritten on every
    # run. It is currently invisible because the regenerated bytes match what is
    # committed -- which is exactly what a changed `trace_gen.py` would break
    # first. Verified: mutating fixture generation leaves this script reporting
    # "deterministic" while the three committed traces are modified.
    print(
        f"::error::running the demo modified the working tree at {root}, so the "
        f"fixtures this comparison used are not the ones the repository ships",
        file=sys.stderr,
    )
    for entry in difflib.unified_diff(
        before.splitlines(), after.splitlines(),
        fromfile="tree before", tofile="tree after", lineterm="",
    ):
        if entry.startswith(("+", "-")) and not entry.startswith(("+++", "---")):
            print(f"  {entry}", file=sys.stderr)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "scratch",
        nargs="?",
        help="directory to work in (default: a fresh temporary directory)",
    )
    args = parser.parse_args()

    temporary = False
    if args.scratch:
        scratch = Path(args.scratch)
    else:
        scratch = Path(tempfile.mkdtemp(prefix="toxindb-determinism-"))
        temporary = True
    try:
        scratch.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"error: cannot use scratch directory {scratch}: {exc}", file=sys.stderr)
        return 2

    try:
        # Both runs write to the *same* directory, and the first run's output is
        # copied aside before the second overwrites it. That is deliberate:
        # reports embed the path they were written to (demo_summary.json lists
        # the report filenames), so running into two different directories
        # would compare those paths rather than the results.
        live = scratch / "live"
        first, second = scratch / "run1", scratch / "run2"
        _fresh_dir(first)
        _fresh_dir(second)

        repo_root = Path(__file__).resolve().parents[2]
        tree_before = _tree_state(repo_root)

        run_demo(live)
        shutil.copytree(live, first, dirs_exist_ok=True)
        run_demo(live)
        shutil.copytree(live, second, dirs_exist_ok=True)

        verdict = _compare(first, second)
        # Asserted regardless of the verdict. A run that reports
        # nondeterminism *and* dirtied the tree is still the more informative
        # failure, and a run that reports determinism while having overwritten
        # the fixtures is not a result at all.
        dirty = _assert_tree_unchanged(tree_before, _tree_state(repo_root), repo_root)
        return verdict or dirty
    except OSError as exc:
        # This script's whole thesis is that a crash is not a result. An
        # unwritable or full scratch directory must not escape as a traceback
        # whose exit code is indistinguishable from a determinism verdict.
        print(f"error: scratch directory {scratch} is unusable: {exc}", file=sys.stderr)
        return 2
    finally:
        if temporary:
            shutil.rmtree(scratch, ignore_errors=True)


def _compare(first: Path, second: Path) -> int:
    first_files = _files(first)
    second_files = _files(second)

    failures = 0
    for rel in sorted(first_files - second_files):
        print(f"::error::{rel} was produced by run 1 but not by run 2")
        failures += 1
    for rel in sorted(second_files - first_files):
        print(f"::error::{rel} was produced by run 2 but not by run 1")
        failures += 1

    common = first_files & second_files
    if not common:
        # Comparing nothing proves nothing. Reporting this as determinism would
        # be the single worst thing this script could do.
        print(
            "::error::the demo produced no output files in common, so determinism "
            "cannot be claimed"
        )
        return 1

    empty = []
    for rel in sorted(common):
        raw_a = _read(first / rel)
        raw_b = _read(second / rel)
        if not raw_a and not raw_b:
            empty.append(str(rel))
        a = canonical_bytes(raw_a, rel.suffix)
        b = canonical_bytes(raw_b, rel.suffix)
        if a == b:
            continue
        print(f"::error::{rel} differs between runs")
        diff = list(
            difflib.unified_diff(
                a.decode("utf-8", "replace").splitlines(),
                b.decode("utf-8", "replace").splitlines(),
                fromfile=f"run1/{rel}",
                tofile=f"run2/{rel}",
                lineterm="",
            )
        )
        for entry in diff[:40]:
            print(f"  {entry}")
        if len(diff) > 40:
            print(f"  ... and {len(diff) - 40} more diff line(s)")
        failures += 1

    # The zero-*files* case above is caught by `common` being empty. The
    # zero-*content* analogue is not: a demo that writes only empty or
    # unparseable files compares clean, and would be reported as deterministic
    # without this.
    if len(empty) == len(common):
        print(
            "::error::every compared file was empty, so there is nothing to "
            "compare and determinism cannot be claimed"
        )
        return 1

    if failures:
        print(
            f"::error::the demo is NOT deterministic "
            f"({failures} difference(s) across {len(common)} compared file(s))"
        )
        return 1

    print(
        f"Compared {len(common)} file(s) across two runs: the demo is "
        f"deterministic. Normalised: {describe_policy()}."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
