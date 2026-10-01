#!/usr/bin/env python3
"""Prove that check_demo_determinism.py can actually fail.

A CI gate nobody has watched reject bad input is not a gate -- it is a green
light wired to nothing. This script injects known defects and asserts that the
determinism check notices each one.

Three rules make this a test rather than a demonstration
--------------------------------------------------------

1. **A crash is not a detection.** Every MUST_FAIL case must make the check
   report a *difference*, not merely exit non-zero. A mutation that breaks the
   program so badly the demo dies would otherwise score as a pass, which is
   theatre rather than evidence. An earlier version of this script made exactly
   that mistake on four of five cases: ``NameError``, ``AttributeError`` and
   ``IndentationError`` all produce rc=1, which the check counted as success.
   The CONTROL case keeps this distinction live.

2. **Only runnable mutations count.** Each mutation asserts its anchor still
   exists before editing, so a refactor that moves the anchor surfaces as a
   loud failure here rather than as a silent pass.

3. **The normalisations are proven narrow.** Each MUST_PASS case injects
   something the check is documented to absorb and requires it to stay green;
   each MUST_FAIL case injects something that *looks* similar but is not, and
   requires it to be caught. Without both directions, a normaliser that
   swallowed everything would satisfy every MUST_FAIL case vacuously.

Why some cases call the normaliser directly
--------------------------------------------
The check absorbs varying ``doc_ids`` order for TX-008. Proving that
end-to-end means making the order differ between two separate demo runs, and
any mechanism for doing that has a failure mode:

* ``list(set(...))`` -- the shipped defect -- agrees across two runs about half
  the time, because TX-008's overlap holds two elements and there are only two
  possible orders. End-to-end, that is a coin flip, and a coin flip in a CI
  self-test is a coin flip in CI.
* a random choice -- same problem, one bit of entropy per run.
* a counter file -- correct in principle, but the parity shift breaks if a run
  makes an even number of calls, because the second run's counter values are
  then congruent to the first run's.

So the *scope* of the doc_ids normalisation is verified directly, by calling
``normalise()`` on two records that differ only in that order. That is exact,
instant, and cannot flake. End-to-end evidence that varying doc order in a
*non*-normalised detector is caught comes from the TX-001 MUST_FAIL case, which
has three elements and is not normalised, so it is reliable.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHECK = HERE / "check_demo_determinism.py"
REPO = HERE.parent.parent

IGNORE = shutil.ignore_patterns(
    ".git",
    "__pycache__",
    "*.egg-info",
    ".venv",
    "venv",
    "env",
    "dist",
    "build",
    "reports",
    ".pytest_cache",
)

# Substrings the check prints only when it performed a real comparison and
# found a difference, as opposed to the demo failing to run.
DIFF_MARKERS = (
    "differs between runs",
    "was produced by run",
    "no output files in common",
)

# A random ordering, injected in place of a detector's doc_ids. Both branches
# hold the same ids in opposite orders, so the content is unaffected and only
# the ordering varies -- and it varies *per call*, which is what makes the
# check's two runs disagree.
RANDOM_ORDER = (
    "(list(reversed({var})) if __import__('random').random() < 0.5 "
    "else list({var}))"
)


class MutationFailed(Exception):
    """Raised when a mutation's anchor no longer exists in the source."""


def _replace(path: Path, old: str, new: str, count: int = 1) -> None:
    text = path.read_text(encoding="utf-8")
    if text.count(old) < count:
        raise MutationFailed(f"anchor not found in {path.name}: {old!r}")
    path.write_text(text.replace(old, new, count), encoding="utf-8")


def _fresh_repo() -> Path:
    root = Path(tempfile.mkdtemp(prefix="teeth-src-"))
    target = root / "repo"
    shutil.copytree(REPO, target, ignore=IGNORE)
    return target


# --------------------------------------------------------------------------
# MUST FAIL (end to end) -- each must be reported as a real difference.
# --------------------------------------------------------------------------


def m_random_value_in_alert_detail(repo: Path) -> None:
    """A per-call clock reading embedded in an alert's detail string.

    The most realistic shape of this bug: someone adds "generated at" or a
    duration to a message without realising it makes the report irreproducible.
    """
    _replace(
        repo / "toxindb" / "heuristics.py",
        'f"{recent_count}/{total} retrievals (',
        'f"n={__import__(\'time\').time_ns()} {recent_count}/{total} retrievals (',
    )


def m_random_tx001_doc_order(repo: Path) -> None:
    """TX-001 emits its doc_ids in a random order.

    This is the mirror image of the TX-008 normalisation and it must be CAUGHT.
    Sorting every detector's doc_ids would hide any future ordering bug in any
    heuristic, so the normalisation is scoped to TX-008 and this proves it.
    TX-001's overlap has three elements in the poison fixture, so the order
    really does differ between runs rather than coinciding half the time.
    """
    _replace(
        repo / "toxindb" / "heuristics.py",
        "doc_ids=recent_docs,",
        f"doc_ids={RANDOM_ORDER.format(var='recent_docs')},",
    )


def m_new_volatile_report_field(repo: Path) -> None:
    """A brand-new per-run field in the JSON report.

    The check drops the ``generated_at`` *key*; it must not be generalised into
    "drop anything that looks like a timestamp", or a genuinely volatile new
    field would be absorbed silently.
    """
    _replace(
        repo / "toxindb" / "report.py",
        '"generated_at": datetime.now(timezone.utc).isoformat(),',
        '"generated_at": datetime.now(timezone.utc).isoformat(),\n'
        '        "build_nonce": __import__("time").time_ns(),',
    )


def m_extra_output_file(repo: Path) -> None:
    """One run writes a file the other does not."""
    cli = repo / "toxindb" / "cli.py"
    helper = (
        "\ndef _teeth_emit(out_dir):\n"
        "    import os, secrets\n"
        "    name = os.path.join(out_dir, 'teeth-%s.txt' % secrets.token_hex(4))\n"
        "    with open(name, 'w') as fh:\n"
        "        fh.write('x')\n"
        "\n"
    )
    anchor = (
        "    output_dir = args.output\n"
        "    os.makedirs(output_dir, exist_ok=True)\n"
        "\n"
        "    results = {}\n"
    )
    text = cli.read_text(encoding="utf-8")
    for needle in ("def cmd_demo", anchor):
        if needle not in text:
            raise MutationFailed(f"anchor not found in cli.py: {needle!r}")
    text = text.replace("def cmd_demo", helper + "def cmd_demo", 1)
    text = text.replace(anchor, anchor + "\n    _teeth_emit(output_dir)\n", 1)
    cli.write_text(text, encoding="utf-8")


def m_demo_writes_nothing(repo: Path) -> None:
    """The demo runs, exits 0, and writes no files at all.

    Comparing zero files would otherwise be reported as determinism.
    """
    _replace(
        repo / "toxindb" / "cli.py",
        'def cmd_demo(args) -> int:\n    print("=== toxindb demo ===")',
        'def cmd_demo(args) -> int:\n'
        '    print("=== toxindb demo ===")\n'
        "    return 0",
    )


def m_volatile_suffix_on_documents_line(repo: Path) -> None:
    """A volatile suffix appended to a Markdown ``**Documents:**`` line.

    The normaliser reorders a *pure* id list and leaves anything else alone.
    If it sorted ids inside a line that also carries other text, it would be
    guessing where the list ends -- so this must be caught, not absorbed.
    """
    _replace(
        repo / "toxindb" / "report.py",
        "**Documents:**",
        "**Documents:** (nonce {__import__('time').time_ns()})",
    )


# --------------------------------------------------------------------------
# MUST PASS (end to end) -- documented as absorbed, so the check stays green.
# --------------------------------------------------------------------------


def m_microsecond_report_timestamp(repo: Path) -> None:
    """Report metadata raised to microsecond resolution.

    The shipped ``generated_at`` has second granularity, so two runs inside one
    second would be byte-identical anyway and the timestamp normalisation could
    pass *vacuously*. Raising it to microseconds makes the value vary on every
    single run, which proves the normalisation is load-bearing rather than
    decorative.
    """
    _replace(
        repo / "toxindb" / "report.py",
        '"generated_at": datetime.now(timezone.utc).isoformat(),',
        '"generated_at": datetime.now(timezone.utc)'
        '.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),',
    )


# --------------------------------------------------------------------------
# Scope of the normalisations, verified directly and deterministically.
# --------------------------------------------------------------------------


def _load_check_module():
    spec = importlib.util.spec_from_file_location("toxindb_determinism", CHECK)
    assert spec and spec.loader, "could not load the determinism check"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _alert(heuristic_id: str, doc_ids: list[str]) -> dict:
    return {
        "heuristic_id": heuristic_id,
        "heuristic_name": "x",
        "severity": "high",
        "query_id": None,
        "doc_ids": doc_ids,
        "detail": "d",
        "confidence": 1.0,
    }


NORMALISER_CASES: tuple[tuple[str, str, str, bool], ...] = (
    # (label, first, second, expect_identical)
    (
        "TX-008 doc_ids order is absorbed (issue #22)",
        json.dumps(_alert("TX-008", ["b", "a"])),
        json.dumps(_alert("TX-008", ["a", "b"])),
        True,
    ),
    (
        "TX-001 doc_ids order is NOT absorbed",
        json.dumps(_alert("TX-001", ["b", "a"])),
        json.dumps(_alert("TX-001", ["a", "b"])),
        False,
    ),
    (
        "generated_at is absorbed at any depth",
        json.dumps({"a": {"b": {"generated_at": "2024-01-01T00:00:00+00:00"}}}),
        json.dumps({"a": {"b": {"generated_at": "2025-09-09T09:09:09+00:00"}}}),
        True,
    ),
    (
        "a new volatile field is NOT absorbed",
        json.dumps({"build_nonce": 1}),
        json.dumps({"build_nonce": 2}),
        False,
    ),
    (
        "severity is not absorbed",
        json.dumps(_alert("TX-008", ["a"]) | {"severity": "high"}),
        json.dumps(_alert("TX-008", ["a"]) | {"severity": "low"}),
        False,
    ),
    (
        "confidence is not absorbed",
        json.dumps(_alert("TX-008", ["a"]) | {"confidence": 0.5}),
        json.dumps(_alert("TX-008", ["a"]) | {"confidence": 0.9}),
        False,
    ),
    (
        "doc_ids content is not absorbed by the ordering rule",
        json.dumps(_alert("TX-008", ["a", "b"])),
        json.dumps(_alert("TX-008", ["a", "b", "c"])),
        False,
    ),
    (
        "a compact JSON report is still compared, not skipped",
        json.dumps({"generated_at": "x", "alert_count": 2, "alerts": []}),
        json.dumps({"generated_at": "y", "alert_count": 3, "alerts": []}),
        False,
    ),
)


MD_CASES: tuple[tuple[str, str, str, bool], ...] = (
    (
        "TX-008 Documents order is absorbed",
        "### TX-008: LangChain\n\n- **Documents:** `b`, `a`\n",
        "### TX-008: LangChain\n\n- **Documents:** `a`, `b`\n",
        True,
    ),
    (
        "TX-001 Documents order is NOT absorbed",
        "### TX-001: Demand\n\n- **Documents:** `b`, `a`\n",
        "### TX-001: Demand\n\n- **Documents:** `a`, `b`\n",
        False,
    ),
    (
        "a non-id-list Documents line is left alone",
        "### TX-008: LangChain\n\n- **Documents:** `b`, `a` (2 of 9)\n",
        "### TX-008: LangChain\n\n- **Documents:** `b`, `a` (3 of 9)\n",
        False,
    ),
    (
        "the Generated metadata line is absorbed (as emitted)",
        "**Generated:** 2024-01-01T00:00:00Z\n\n- **Severity:** high\n",
        "**Generated:** 2025-09-09T09:09:09Z\n\n- **Severity:** high\n",
        True,
    ),
    (
        "the Generated metadata line is absorbed (as a list item)",
        "- **Generated:** 2024-01-01T00:00:00Z\n- **Severity:** high\n",
        "- **Generated:** 2025-09-09T09:09:09Z\n- **Severity:** high\n",
        True,
    ),
    (
        "the italic footer is NOT treated as metadata",
        "*Generated by toxindb - a detector*\n",
        "*Generated by toxindb - a scanner*\n",
        False,
    ),
    (
        "an unrelated Markdown value is NOT absorbed",
        "- **Severity:** high\n",
        "- **Severity:** critical\n",
        False,
    ),
)


def check_normaliser_scope() -> list[str]:
    """Verify the normaliser absorbs exactly what it documents."""
    module = _load_check_module()
    problems: list[str] = []

    def evaluate(label, first, second, expect_identical, suffix):
        path = Path("x" + suffix)
        a = module.normalise(path, first)
        b = module.normalise(path, second)
        identical = a == b
        if identical != expect_identical:
            problems.append(
                f"{label}: expected {'absorbed' if expect_identical else 'detected'}, "
                f"got {'absorbed' if identical else 'detected'}"
            )
            return False
        return True

    for label, first, second, expect in NORMALISER_CASES:
        ok = evaluate(label, first, second, expect, ".json")
        print(f"  {'ok    ' if ok else 'WRONG'} {label}")
    for label, first, second, expect in MD_CASES:
        ok = evaluate(label, first, second, expect, ".md")
        print(f"  {'ok    ' if ok else 'WRONG'} {label}")
    return problems


# --------------------------------------------------------------------------
# CONTROL -- a crash must not be mistaken for a detection.
# --------------------------------------------------------------------------


def m_deterministic_crash(repo: Path) -> None:
    """The demo dies immediately and identically, every run.

    If the check could not tell this apart from a detected difference, it could
    not tell whether any other case is a real detection either.
    """
    _replace(
        repo / "toxindb" / "cli.py",
        "def cmd_demo(args) -> int:",
        "def cmd_demo(args) -> int:\n    raise SystemExit(3)\n\n"
        "def _cmd_demo_unused(args) -> int:",
    )


MUST_FAIL = [
    ("per-call clock value inside an alert detail", m_random_value_in_alert_detail),
    (
        "TX-001 doc_ids in random order (not the known #22 defect)",
        m_random_tx001_doc_order,
    ),
    ("new volatile field in the JSON report", m_new_volatile_report_field),
    ("extra output file on one run only", m_extra_output_file),
    ("demo exits 0 but writes no files", m_demo_writes_nothing),
    ("volatile text on a Markdown Documents line", m_volatile_suffix_on_documents_line),
]

MUST_PASS = [
    ("report timestamp at microsecond resolution", m_microsecond_report_timestamp),
]

CONTROL = [
    ("deterministic crash, zero nondeterminism injected", m_deterministic_crash),
]


def run_check(repo: Path) -> tuple[int, str]:
    scratch = Path(tempfile.mkdtemp(prefix="teeth-scratch-"))
    try:
        proc = subprocess.run(
            [sys.executable, str(CHECK), str(scratch)],
            cwd=repo,
            capture_output=True,
            text=True,
        )
        return proc.returncode, proc.stdout + proc.stderr
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _reported_a_difference(output: str) -> bool:
    return any(marker in output for marker in DIFF_MARKERS)


def main() -> int:
    problems: list[str] = []
    created: list[Path] = []

    def evaluate(fn):
        repo = _fresh_repo()
        created.append(repo.parent)
        try:
            fn(repo)
        except MutationFailed as exc:
            problems.append(f"MUTATION DID NOT APPLY: {exc}")
            return None, ""
        except Exception as exc:  # noqa: BLE001 - a broken mutation is a failure
            problems.append(f"MUTATION RAISED {type(exc).__name__}: {exc}")
            return None, ""
        return run_check(repo)

    print("MUST FAIL (end to end) -- the check must reject each as a real difference:")
    for title, fn in MUST_FAIL:
        rc, output = evaluate(fn)
        if rc is None:
            print(f"  ERROR  {title}")
        elif rc == 0:
            problems.append(f"{title}: check returned 0 -> the check is BLIND")
            print(f"  BLIND  {title} -> rc=0, no difference reported")
        elif not _reported_a_difference(output):
            problems.append(
                f"{title}: check exited {rc} but reported no difference -> the mutation "
                "broke the demo instead of perturbing it"
            )
            print(f"  CRASH  {title} -> rc={rc}, no difference reported")
        else:
            print(f"  ok     {title} -> rc={rc} (difference reported)")

    print("\nMUST PASS (end to end) -- the check must absorb this, and nothing more:")
    for title, fn in MUST_PASS:
        rc, output = evaluate(fn)
        if rc is None:
            print(f"  ERROR  {title}")
        elif rc != 0:
            problems.append(
                f"{title}: check returned {rc}, expected 0 -> normalisation too narrow"
            )
            print(f"  NARROW {title} -> rc={rc}")
            for line in output.splitlines()[:10]:
                print(f"          {line}")
        else:
            print(f"  ok     {title} -> rc=0 (correctly absorbed)")

    print("\nCONTROL -- the check must not mistake a crash for a detection:")
    for title, fn in CONTROL:
        rc, output = evaluate(fn)
        if rc is None:
            print(f"  ERROR  {title}")
        elif rc == 0:
            problems.append(
                f"CONTROL {title}: check returned 0 on a broken demo -> it detects nothing"
            )
            print(f"  BLIND  {title} -> rc=0")
        elif _reported_a_difference(output):
            problems.append(
                f"CONTROL {title}: a deterministic crash was reported as a difference"
            )
            print(f"  CONFUSED {title} -> crash reported as a detection")
        else:
            print(f"  ok     {title} -> rc={rc}, reported as a failure to run")

    print("\nNormalisation scope -- what is absorbed and what must not be:")
    problems.extend(check_normaliser_scope())

    for path in created:
        shutil.rmtree(path, ignore_errors=True)

    print()
    if problems:
        print(f"::error::the determinism gate is not trustworthy ({len(problems)} problem(s)):")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print(
        f"The check rejected {len(MUST_FAIL)} injected defects as real differences, "
        f"absorbed {len(MUST_PASS)} documented normalisation end to end, verified "
        f"{len(NORMALISER_CASES) + len(MD_CASES)} normaliser scope properties directly, "
        "and did not confuse a crash with a detection."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
