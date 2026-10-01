#!/usr/bin/env python3
"""Prove that check_demo_determinism.py can actually fail.

A CI gate is only worth its runtime if you have watched it reject bad input. A
green gate that would stay green under any mutation is worse than no gate,
because it is trusted. This script therefore deliberately introduces
nondeterminism into a throwaway copy of the tree and asserts that the
determinism check notices.

It operates on a copy, never on the working tree, and it restores nothing
because it restores nothing it changed.

Cases
-----
MUST FAIL (the gate has teeth):
  1. A detector emits the current wall clock into an alert detail.
  2. A detector iterates a set, so doc order depends on PYTHONHASHSEED.
  3. An extra output file appears on only one of the two runs.
  4. A detector's threshold is perturbed by the run index (non-idempotent).

MUST PASS (the gate is not merely failing on everything):
  5. Report metadata gains a wall-clock timestamp -- this is what normalisation
     (1) exists to absorb, so the check must stay green.
  6. An alert's doc_ids comes back unsorted -- this is what normalisation (2)
     exists to absorb while #22 is open.

If a MUST FAIL case passes, the gate is blind and this script exits non-zero.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHECK = HERE / "check_demo_determinism.py"


def _mutate_alert_detail(src: Path, marker: str, replacement: str) -> bool:
    """Insert `replacement` as the first statement of DemandConcentrationDetector.detect."""
    text = (src / "toxindb" / "heuristics.py").read_text(encoding="utf-8")
    # Anchor on the first detector class, whose detect() body opens with
    # `alerts = []`. Inject immediately after that assignment.
    needle = "class DemandConcentrationDetector:"
    if needle not in text:
        return False
    idx = text.index(needle)
    body = text.index("alerts = []", idx) + len("alerts = []")
    text = text[:body] + "\n        " + replacement + text[body:]
    (src / "toxindb" / "heuristics.py").write_text(text, encoding="utf-8")
    return True


def _mutate_cli(src: Path, old: str, new: str) -> bool:
    p = src / "toxindb" / "cli.py"
    text = p.read_text(encoding="utf-8")
    if old not in text:
        return False
    p.write_text(text.replace(old, new, 1), encoding="utf-8")
    return True


def case_wallclock_in_alert(src: Path) -> None:
    import datetime

    assert _mutate_alert_detail(
        src,
        "ts",
        f"alerts.append(__import__('datetime').datetime.now(timezone.utc).isoformat())",
    )
    del datetime


def case_set_iteration(src: Path) -> None:
    # TX-008 builds doc_ids from a set; widen it to a set of every doc id in
    # the trace so the alert's contents depend on set iteration order.
    assert _mutate_alert_detail(
        src,
        "set",
        "alerts.append(' '.join(sorted({d.doc_id for d in trace.ingests})))",
    )


def case_run_index(src: Path) -> None:
    # A per-process nonce necessarily differs between the two runs.
    assert _mutate_alert_detail(src, "nonce", "alerts.append(str(id(trace)))")


def case_extra_output_file(src: Path) -> None:
    # A detector-side artefact whose name embeds a fresh random token each run,
    # so the two runs produce different file sets.
    p = src / "toxindb" / "cli.py"
    text = p.read_text(encoding="utf-8")
    needle = "def cmd_demo"
    assert needle in text
    inject = (
        "\ndef _teeth_extra_artifact(out_dir):\n"
        "    import os, secrets\n"
        "    with open(os.path.join(out_dir, 'teeth-%s.txt' % secrets.token_hex(4)), 'w') as fh:\n"
        "        fh.write('x')\n\n"
    )
    text = text.replace(needle, inject + needle, 1)
    p.write_text(text, encoding="utf-8")
    # call it from cmd_demo so the artefact actually lands in the output dir
    text = p.read_text(encoding="utf-8")
    marker = 'traces = ensure_demo_traces()'
    if marker in text:
        text = text.replace(marker, marker + "\n        _teeth_extra_artifact(args.output)", 1)
        p.write_text(text, encoding="utf-8")


def case_new_wallclock_field(src: Path) -> None:
    """Must FAIL: a genuinely new volatile field is a real determinism regression.

    The normaliser drops the *known* metadata keys. It must not silently absorb
    an arbitrary new one, or the gate would rot into "ignore anything that looks
    like a timestamp". This case is what keeps normalisation (1) honest.
    """
    p = src / "toxindb" / "report.py"
    text = p.read_text(encoding="utf-8")
    old = '"generated_at": datetime.now(timezone.utc).isoformat(),'
    assert old in text, "report.py: generated_at field not found; update this mutation"
    text = text.replace(old, old + '\n        "build_elapsed_ns": time.time_ns(),', 1)
    text = text.replace("import json", "import json\nimport time", 1)
    p.write_text(text, encoding="utf-8")


def case_finer_timestamp(src: Path) -> None:
    """Must PASS: normalisation (1) exists precisely for report metadata.

    The shipped `generated_at` is second-granularity, so it is possible for two
    runs inside one second to be byte-identical and for the normaliser to be
    only vacuously satisfied. Raising the existing key to microsecond
    resolution makes it vary on *every* run, which proves the drop is load-
    bearing rather than decorative.
    """
    p = src / "toxindb" / "report.py"
    text = p.read_text(encoding="utf-8")
    old = '"generated_at": datetime.now(timezone.utc).isoformat(),'
    assert old in text, "report.py: generated_at field not found; update this mutation"
    text = text.replace(
        old,
        '"generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),',
        1,
    )
    # And the Markdown header, so both normalisations (1) are exercised.
    text = text.replace(
        "strftime('%Y-%m-%dT%H:%M:%SZ')",
        "strftime('%Y-%m-%dT%H:%M:%S.%fZ')",
        1,
    )
    p.write_text(text, encoding="utf-8")


def case_unsorted_doc_ids(src: Path) -> None:
    """Must stay green: normalisation (2) exists precisely for issue #22."""
    p = src / "toxindb" / "heuristics.py"
    text = p.read_text(encoding="utf-8")
    old = "doc_ids=list(overlap),"
    assert old in text, "heuristics.py: TX-008 doc_ids=list(overlap) not found; update this mutation"
    # Reverse the order rather than randomise: the point is that the ORDER
    # changes while the CONTENT does not, which normalisation (2) must absorb.
    text = text.replace(old, "doc_ids=list(reversed(list(overlap))),", 1)
    p.write_text(text, encoding="utf-8")


MUST_FAIL = [
    ("wall-clock leaked into an alert detail", case_wallclock_in_alert),
    ("detector result depends on set iteration order", case_set_iteration),
    ("detector result differs per process", case_run_index),
    ("a new volatile field appears in the report", case_new_wallclock_field),
    ("an extra output file appears on one run only", case_extra_output_file),
]
MUST_PASS = [
    ("report timestamp raised to microsecond resolution", case_finer_timestamp),
    ("alert doc_ids come back unsorted", case_unsorted_doc_ids),
]


def run_check(src: Path) -> tuple[int, str]:
    scratch = Path(tempfile.mkdtemp(prefix="teeth-"))
    try:
        proc = subprocess.run(
            [sys.executable, str(CHECK), str(scratch)],
            cwd=src,
            capture_output=True,
            text=True,
        )
        return proc.returncode, (proc.stdout + proc.stderr)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def main() -> int:
    failures: list[str] = []

    for title, mutate in MUST_FAIL:
        src = Path(tempfile.mkdtemp(prefix="teeth-src-"))
        try:
            shutil.copytree(HERE.parent.parent, src / "toxindb-repo",
                            ignore=shutil.ignore_patterns(".git", "__pycache__", "*.egg-info", ".venv"))
            repo = src / "toxindb-repo"
            try:
                mutate(repo)
            except AssertionError:
                failures.append(f"{title}: MUTATION DID NOT APPLY (source moved; update this script)")
                print(f"  SKIP  {title} - mutation no longer applies")
                continue
            rc, output = run_check(repo)
            if rc == 0:
                failures.append(f"{title}: check returned 0 but should have failed -> gate is BLIND")
                print(f"  BLIND {title} -> rc=0")
            else:
                print(f"  ok    {title} -> rc={rc} (rejected)")
        finally:
            shutil.rmtree(src, ignore_errors=True)

    for title, mutate in MUST_PASS:
        src = Path(tempfile.mkdtemp(prefix="teeth-src-"))
        try:
            shutil.copytree(HERE.parent.parent, src / "toxindb-repo",
                            ignore=shutil.ignore_patterns(".git", "__pycache__", "*.egg-info", ".venv"))
            repo = src / "toxindb-repo"
            try:
                mutate(repo)
            except AssertionError:
                failures.append(f"{title}: MUTATION DID NOT APPLY (source moved; update this script)")
                print(f"  SKIP  {title} - mutation no longer applies")
                continue
            rc, output = run_check(repo)
            if rc != 0:
                failures.append(f"{title}: check returned {rc} but should have passed -> normalisation is TOO NARROW")
                print(f"  BROKEN {title} -> rc={rc}")
                for line in output.splitlines()[:6]:
                    print(f"          {line}")
            else:
                print(f"  ok    {title} -> rc=0 (correctly absorbed)")
        finally:
            shutil.rmtree(src, ignore_errors=True)

    print()
    if failures:
        print(f"::error::the determinism gate is not trustworthy ({len(failures)} problem(s)):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("The determinism gate rejects injected nondeterminism and absorbs only its two documented normalisations.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
