#!/usr/bin/env python3
"""Assert that the bundled demo is deterministic.

Why this exists
---------------
The README and SCOPE.md promise deterministic offline analysis over the bundled
fixtures. That promise is easy to break accidentally: a heuristic that starts
iterating a set, a dict whose key order depends on insertion, or a wall-clock
derived threshold would all make the demo's output drift between runs while
every test still passed -- because the suite never compares two runs against each
other. It only checks each run against fixed expectations.

Running this check is how the nondeterministic ``doc_ids`` ordering in TX-008
(issue #22) was found in the first place.

What is and is not normalised
-----------------------------
A determinism gate is only worth having if its blind spots are written down and
narrow, so there are exactly three, each commented where it is defined:

1. Report metadata -- ``generated_at`` and the Markdown ``**Generated:**``
   header. These record *when* a report was written, not a detection result.
   A report that omitted when it was produced would be worse, so this is a
   genuine value, not a defect.
2. The ordering of ``doc_ids`` within a single alert, which is currently
   nondeterministic because TX-008 builds it from a set (issue #22). This is a
   real defect, so it is normalised only to keep this gate green while the
   defect is open. When #22 is fixed, delete ``_canonicalise_doc_ids`` and this
   check starts enforcing ordering as well.
3. The line layout of a ``doc_ids`` array. The JSONL alerts are written one
   record per line while the JSON reports are pretty-printed, so the same value
   appears as ``"doc_ids": ["a", "b"]`` in one and as a four-line block in the
   other. Both are normalised to one canonical single-line sorted form so the
   two runs are comparable. This erases formatting only; it cannot hide a
   changed value.

Everything else -- counts, heuristic ids, severities, confidences, alert
ordering, the summary -- must match byte for byte.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# (1) Report metadata, not results.
_DROP_LINE = re.compile(r'"generated_at"|\*\*Generated:\*\*')

# (2) and (3) The known-open nondeterministic doc_ids ordering, and the
# difference between single-line and pretty-printed JSON. DOTALL is required
# because in the pretty-printed reports the array spans several lines; the
# match is bounded by the first ``]`` so it cannot run away.
_DOC_IDS_ARRAY = re.compile(r'"doc_ids"\s*:\s*\[(.*?)\]', re.DOTALL)
_QUOTED = re.compile(r'"([^"]*)"')

# The Markdown report renders the same list on one line, backticked.
_MD_DOCS = re.compile(r"^(\s*-?\s*\*\*Documents:\*\*\s*)(.*)$")
_BACKTICKED = re.compile(r"`([^`]*)`")


def _canonicalise_doc_ids(text: str) -> str:
    """Sort every ``doc_ids`` array into one canonical single-line form."""

    def repl(match: re.Match[str]) -> str:
        ids = _QUOTED.findall(match.group(1))
        # Preserve the original separator style so the JSONL alerts (which use
        # ", ") and the reports (which use ",\n") both stay valid-looking.
        return '"doc_ids": [' + ", ".join(f'"{i}"' for i in sorted(ids)) + "]"

    return _DOC_IDS_ARRAY.sub(repl, text)


def _sort_md_ids(match: re.Match[str]) -> str:
    ids = _BACKTICKED.findall(match.group(2))
    if not ids:
        return match.group(0)
    return f"{match.group(1)}" + ", ".join(f"`{i}`" for i in sorted(ids))


def normalise(text: str) -> str:
    kept: list[str] = []
    for line in text.splitlines(keepends=True):
        if _DROP_LINE.search(line):
            continue
        stripped = line.rstrip("\n")
        newline = line[len(stripped) :]
        line = _sort_md_ids_regex(stripped) + newline
        kept.append(line)
    return _canonicalise_doc_ids("".join(kept))


def _sort_md_ids_regex(line: str) -> str:
    return _MD_DOCS.sub(_sort_md_ids, line)


def read_normalised(path: Path) -> str:
    return normalise(path.read_text(encoding="utf-8", errors="replace"))


def run_demo(dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    # Invoke the package through the *current* interpreter rather than whatever
    # `toxindb` happens to be first on PATH. Using the console script would
    # silently test a different install than the one under test.
    completed = subprocess.run(
        [sys.executable, "-m", "toxindb", "demo", "--output", str(dest)],
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        sys.stderr.write(completed.stdout + completed.stderr)
        raise SystemExit(f"error: `toxindb demo --output {dest}` failed (rc={completed.returncode})")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scratch", nargs="?", help="scratch directory (default: a temp dir)")
    args = parser.parse_args()

    scratch = Path(args.scratch) if args.scratch else Path(tempfile.mkdtemp(prefix="toxindb-det-"))
    scratch.mkdir(parents=True, exist_ok=True)
    out = scratch / "out"
    snapshot = scratch / "snapshot"

    print("Running the demo twice and comparing the results...")
    run_demo(out)
    if snapshot.exists():
        shutil.rmtree(snapshot)
    shutil.copytree(out, snapshot)
    run_demo(out)

    first_files = {p.relative_to(snapshot) for p in snapshot.rglob("*") if p.is_file()}
    second_files = {p.relative_to(out) for p in out.rglob("*") if p.is_file()}

    failures = 0
    for rel in sorted(first_files - second_files):
        print(f"::error::{rel} was produced by run 1 but not by run 2")
        failures += 1
    for rel in sorted(second_files - first_files):
        print(f"::error::{rel} was produced by run 2 but not by run 1")
        failures += 1

    for rel in sorted(first_files & second_files):
        a = read_normalised(snapshot / rel)
        b = read_normalised(out / rel)
        if a != b:
            print(f"::error::{rel} differs between runs (ignoring timestamps, #22 doc_ids order, array layout)")
            import difflib

            for line in list(
                difflib.unified_diff(
                    a.splitlines(), b.splitlines(), fromfile=f"run1/{rel}", tofile=f"run2/{rel}", lineterm=""
                )
            )[:40]:
                print(f"  {line}")
            failures += 1

    if failures:
        print(f"::error::the demo is NOT deterministic ({failures} difference(s))")
        return 1

    print(
        f"Compared {len(first_files & second_files)} file(s) across two runs: the demo is "
        "deterministic (ignoring report timestamps, #22 doc_ids order, and array layout)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
