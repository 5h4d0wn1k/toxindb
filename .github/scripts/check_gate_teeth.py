#!/usr/bin/env python3
"""Prove that check_demo_determinism.py can actually fail.

A CI gate nobody has watched reject bad input is not a gate -- it is a green
light wired to nothing. This script injects known defects and asserts that the
determinism check notices each one.

Four rules make this a test rather than a demonstration
--------------------------------------------------------

1. **A crash is not a detection.** Every MUST_FAIL case must make the check
   report a *difference*, not merely exit non-zero. A mutation that breaks the
   program so badly the demo dies would otherwise score as a pass, which is
   theatre rather than evidence. An earlier version of this script made exactly
   that mistake on four of five cases: ``NameError``, ``AttributeError`` and
   ``IndentationError`` all produce rc=1, which the check counted as success.
   The CONTROL case keeps this distinction live.

2. **Every anchor is unambiguous.** Each mutation not only asserts its anchor
   exists but asserts the anchor is *unique within the detector it names*.
   ``doc_ids=recent_docs,`` occurs twice in ``heuristics.py`` -- once in TX-001
   and once in TX-002 -- so a plain first-match replacement would silently
   retarget the case at whichever detector came first in the file. Reordering two
   unrelated classes is a purely cosmetic change, and it would have turned the
   TX-001 case into a TX-002 case that still printed "TX-001".

3. **A case must fail for the stated reason.** Each MUST_FAIL case names the
   output file whose contents must change. Without that, a case can be carried
   entirely by one renderer while the thing it is actually about changes
   silently -- demonstrated against an earlier version of this script, where the
   TX-001 case still passed when the normaliser was widened to sort every
   heuristic's doc_ids, because only the Markdown differed.

4. **The normalisations are proven narrow.** Each MUST_PASS case injects
   something the check is documented to absorb and requires it to stay green;
   each MUST_FAIL case injects something that *looks* similar but is not, and
   requires it to be caught. Without both directions, a normaliser that
   swallowed everything would satisfy every MUST_FAIL case vacuously.

Why some cases call the normaliser directly
--------------------------------------------
The check absorbs varying ``doc_ids`` order for TX-008. Proving that end-to-end
means making the order differ between two separate demo runs, and any mechanism
for doing that has a failure mode:

* ``list(set(...))`` -- the shipped defect -- agrees across two runs about half
  the time, because TX-008's overlap holds two elements and there are only two
  possible orders.
* a random choice -- same problem, one bit of entropy per run.
* a counter file -- correct in principle, but the parity shift breaks if a run
  makes an even number of calls.

So the *scope* of the doc_ids normalisation is verified directly, by calling
``canonical_bytes()`` on two records that differ only in that order. That is
exact, instant, and cannot flake. End-to-end evidence that varying doc order in
a *non*-normalised detector is caught comes from the TX-001 case, which has
three elements in the poison fixture and is therefore reliable.
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

# Broad enough to skip every conventional virtualenv name. Matching only the
# exact strings `.venv`, `venv` and `env` means a contributor who names theirs
# `.venv311` pays for eight full copies of a 30 MB directory on every run.
IGNORE = shutil.ignore_patterns(
    ".git",
    "__pycache__",
    "*.egg-info",
    "*.pyc",
    ".venv*",
    "venv*",
    "env*",
    ".tox",
    "dist",
    "build",
    "reports",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".coverage",
    "htmlcov",
    "*.log",
)

# Substrings the check prints only when it performed a real comparison and
# found a difference, as opposed to the demo failing to run.
DIFF_MARKERS = (
    "differs between runs",
    "was produced by run",
    "no output files in common",
    "every compared file was empty",
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
    """Raised when a mutation's anchor is missing or ambiguous."""


def _replace(path: Path, old: str, new: str, count: int = 1) -> None:
    text = path.read_text(encoding="utf-8")
    if text.count(old) < count:
        raise MutationFailed(f"anchor not found in {path.name}: {old!r}")
    path.write_text(text.replace(old, new, count), encoding="utf-8")


def _class_slice(text: str, class_name: str) -> tuple[int, int]:
    """Return the [start, end) offsets of a top-level class body."""
    marker = f"\nclass {class_name}"
    start = text.find(marker)
    if start == -1:
        raise MutationFailed(f"class not found: {class_name}")
    start += 1  # keep the leading newline
    following = text.find("\nclass ", start + 1)
    end = len(text) if following == -1 else following
    return start, end


def _replace_in_class(
    path: Path, class_name: str, old: str, new: str, expect: int = 1
) -> None:
    """Replace `old` only inside `class_name`, asserting it is unambiguous there.

    Without the uniqueness assertion, reordering two classes in the file would
    silently move a mutation from one detector to another and the case would
    keep reporting the name it was written with.
    """
    text = path.read_text(encoding="utf-8")
    start, end = _class_slice(text, class_name)
    body = text[start:end]
    found = body.count(old)
    if found != expect:
        raise MutationFailed(
            f"anchor {old!r} occurs {found} time(s) inside {class_name}, "
            f"expected exactly {expect}"
        )
    text = text[:start] + body.replace(old, new, expect) + text[end:]
    path.write_text(text, encoding="utf-8")


def _fresh_repo() -> Path:
    root = Path(tempfile.mkdtemp(prefix="teeth-src-"))
    target = root / "repo"
    shutil.copytree(REPO, target, ignore=IGNORE)
    return target


# --------------------------------------------------------------------------
# MUST FAIL (end to end) -- each must be reported as a real difference.
# --------------------------------------------------------------------------

_HEURISTICS = ("toxindb", "heuristics.py")


def m_random_value_in_alert_detail(repo: Path) -> None:
    """A per-call clock reading embedded in an alert's detail string.

    The most realistic shape of this bug: someone adds "generated at" or a
    duration to a message without realising it makes the report irreproducible.
    """
    _replace_in_class(
        repo.joinpath(*_HEURISTICS),
        "DemandConcentrationDetector",
        'f"{recent_count}/{total} retrievals (',
        'f"n={__import__(\'time\').time_ns()} {recent_count}/{total} retrievals (',
    )


def m_random_tx001_doc_order(repo: Path) -> None:
    """TX-001 emits its doc_ids in a random order.

    The mirror image of the TX-008 normalisation, and it must be CAUGHT.
    Sorting every detector's doc_ids would hide any future ordering bug in any
    heuristic, so the normalisation is scoped to TX-008 and this proves it.
    TX-001's overlap holds three ids in the poison fixture, so the order really
    does differ between runs rather than coinciding half the time.

    The anchor `doc_ids=recent_docs,` also appears in TX-002, so the
    replacement is scoped to the class and asserted unique within it.
    """
    _replace_in_class(
        repo.joinpath(*_HEURISTICS),
        "DemandConcentrationDetector",
        "doc_ids=recent_docs,",
        f"doc_ids={RANDOM_ORDER.format(var='recent_docs')},",
    )


def m_new_volatile_report_field(repo: Path) -> None:
    """A brand-new per-run field in the JSON report.

    The check removes exactly one key, by name, from the top level. It must not
    be generalised into "drop anything that looks like a timestamp", or a
    genuinely volatile new field would be absorbed silently.
    """
    _replace(
        repo / "toxindb" / "report.py",
        '"generated_at": datetime.now(timezone.utc).isoformat(),',
        '"generated_at": datetime.now(timezone.utc).isoformat(),\n'
        '        "build_nonce": __import__("time").time_ns(),',
    )


def m_generated_at_inside_an_alert(repo: Path) -> None:
    """A detector grows its own `generated_at` field.

    The key is report metadata only because it is not detector output. Once a
    detector emits it, the value is per-call and must be compared. The check
    removes the key from the top level of a report document, not at any depth,
    so this must be caught in both the JSON report and the alerts JSONL.
    """
    _replace_in_class(
        repo.joinpath(*_HEURISTICS),
        "Alert",
        '"severity": self.severity,',
        '"severity": self.severity,\n'
        '            "generated_at": __import__("time").time_ns(),',
    )


def m_generated_line_after_a_heading(repo: Path) -> None:
    """A `**Generated:**` line emitted as *detection data*, below the header.

    The check drops that line only from a report's header -- before the first
    heading. Anywhere else it is content, and dropping it would hide a real
    per-run value.
    """
    _replace(
        repo / "toxindb" / "report.py",
        "lines.append(\"\")\n    return \"\\n\".join(lines)",
        "lines.append(\"\")\n"
        "    lines.append(\"- **Generated:** \" + str(__import__('time').time_ns()))\n"
        "    return \"\\n\".join(lines)",
    )


def m_appendix_after_tx008(repo: Path) -> None:
    """Random document ordering in a section that merely *follows* TX-008.

    The Markdown normalisation is scoped to the `### TX-008` section and any
    heading closes it. Without that, `section` latches onto TX-008 for the rest
    of the document and every later `**Documents:**` line gets silently sorted.
    """
    _replace(
        repo / "toxindb" / "report.py",
        "lines.append(\"\")\n    return \"\\n\".join(lines)",
        "lines.append(\"\")\n"
        "    lines.append(\"## Appendix\")\n"
        "    lines.append(\"- **Documents:** `\" + "
        "','.join(__import__('random').sample(['zz-9','zz-8','zz-7'], 3)) + \"`\")\n"
        "    return \"\\n\".join(lines)",
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


def m_demo_writes_only_empty_files(repo: Path) -> None:
    """The demo writes one file per run and it is always empty.

    The zero-*files* case is caught by "no output files in common". This is the
    zero-*content* analogue: one file exists, so the comparison runs, and two
    empty files compare equal. Mutated at the point where the output directory
    is created, so the demo still exits 0 -- the rest of the body becomes
    unreachable rather than undefined.
    """
    cli = repo / "toxindb" / "cli.py"
    _replace(
        cli,
        "    output_dir = args.output\n"
        "    os.makedirs(output_dir, exist_ok=True)\n"
        "\n"
        "    results = {}\n",
        "    output_dir = args.output\n"
        "    os.makedirs(output_dir, exist_ok=True)\n"
        "    open(os.path.join(output_dir, 'teeth-empty.txt'), 'w').close()\n"
        "    return 0\n"
        "\n"
        "    results = {}\n",
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


def _alert(heuristic_id: str, doc_ids: list[str], **extra) -> dict:
    payload = {
        "heuristic_id": heuristic_id,
        "heuristic_name": "x",
        "severity": "high",
        "query_id": None,
        "doc_ids": doc_ids,
        "detail": "d",
        "confidence": 1.0,
    }
    payload.update(extra)
    return payload


def _j(obj) -> bytes:
    return json.dumps(obj).encode("utf-8")


# Names a future contributor might plausibly add to a "drop the volatile stuff"
# allowlist. Only `generated_at` may be absorbed; every one of these is a real
# detection result and must be compared. Parameterising the list matters: a
# single hard-coded probe name leaves the teeth gate fully green when the
# allowlist is quietly widened, which is the exact failure the case exists for.
VOLATILE_LOOKING_NAMES = (
    "timestamp",
    "created_at",
    "run_id",
    "started_at",
    "executed_at",
    "build_nonce",
    "ts",
    "as_of",
)


def scope_cases() -> list[tuple[str, bytes, bytes, str, bool]]:
    cases: list[tuple[str, bytes, bytes, str, bool]] = [
        # -- metadata: absorbed only at the top level of a JSON report --------
        (
            "top-level generated_at is absorbed",
            _j({"generated_at": "2024-01-01T00:00:00+00:00", "alert_count": 1}),
            _j({"generated_at": "2025-09-09T09:09:09+00:00", "alert_count": 1}),
            ".json",
            True,
        ),
        (
            "generated_at nested in a report is NOT absorbed",
            _j({"a": {"b": {"generated_at": "x"}}}),
            _j({"a": {"b": {"generated_at": "y"}}}),
            ".json",
            False,
        ),
        (
            "generated_at inside an alert record is NOT absorbed",
            _j(_alert("TX-001", ["a"], generated_at="x")),
            _j(_alert("TX-001", ["a"], generated_at="y")),
            ".jsonl",
            False,
        ),
        # -- metadata: absorbed only from a Markdown header -------------------
        (
            "the Generated header line is absorbed",
            b"**Generated:** 2024-01-01T00:00:00Z\n\n- **Severity:** high\n",
            b"**Generated:** 2025-09-09T09:09:09Z\n\n- **Severity:** high\n",
            ".md",
            True,
        ),
        (
            "the Generated header line is absorbed as a list item",
            b"- **Generated:** 2024-01-01T00:00:00Z\n- **Severity:** high\n",
            b"- **Generated:** 2025-09-09T09:09:09Z\n- **Severity:** high\n",
            ".md",
            True,
        ),
        (
            "a Generated line BELOW a heading is NOT absorbed",
            b"## Alerts\n\n- **Generated:** 2024\n",
            b"## Alerts\n\n- **Generated:** 2025\n",
            ".md",
            False,
        ),
        (
            "the italic footer is NOT treated as metadata",
            b"*Generated by toxindb - detector*\n",
            b"*Generated by toxindb - scanner*\n",
            ".md",
            False,
        ),
        # -- doc_ids ordering: TX-008 only ------------------------------------
        (
            "TX-008 doc_ids order is absorbed (issue #22)",
            _j(_alert("TX-008", ["b", "a"])),
            _j(_alert("TX-008", ["a", "b"])),
            ".jsonl",
            True,
        ),
        (
            "TX-001 doc_ids order is NOT absorbed",
            _j(_alert("TX-001", ["b", "a"])),
            _j(_alert("TX-001", ["a", "b"])),
            ".jsonl",
            False,
        ),
        (
            "lowercase tx-008 is NOT treated as TX-008",
            _j(_alert("tx-008", ["b", "a"])),
            _j(_alert("tx-008", ["a", "b"])),
            ".jsonl",
            False,
        ),
        (
            "'TX-008 ' with a trailing space is NOT treated as TX-008",
            _j(_alert("TX-008 ", ["b", "a"])),
            _j(_alert("TX-008 ", ["a", "b"])),
            ".jsonl",
            False,
        ),
        (
            "a different doc_ids multiset is NOT absorbed",
            _j(_alert("TX-008", ["a", "b"])),
            _j(_alert("TX-008", ["b", "b", "a"])),
            ".jsonl",
            False,
        ),
        # -- Markdown section scoping -----------------------------------------
        (
            "TX-008 Documents order is absorbed",
            b"### TX-008: LangChain\n\n- **Documents:** `b`, `a`\n",
            b"### TX-008: LangChain\n\n- **Documents:** `a`, `b`\n",
            ".md",
            True,
        ),
        (
            "TX-001 Documents order is NOT absorbed",
            b"### TX-001: Demand\n\n- **Documents:** `b`, `a`\n",
            b"### TX-001: Demand\n\n- **Documents:** `a`, `b`\n",
            ".md",
            False,
        ),
        (
            "any heading closes the TX-008 section",
            b"### TX-008: L\n\n## Appendix\n\n- **Documents:** `b`, `a`\n",
            b"### TX-008: L\n\n## Appendix\n\n- **Documents:** `a`, `b`\n",
            ".md",
            False,
        ),
        (
            "a non-id-list Documents line is left alone",
            b"### TX-008: L\n\n- **Documents:** `b`, `a` (2 of 9)\n",
            b"### TX-008: L\n\n- **Documents:** `b`, `a` (3 of 9)\n",
            ".md",
            False,
        ),
        # -- everything else ---------------------------------------------------
        (
            "severity is not absorbed",
            _j(_alert("TX-008", ["a"]) | {"severity": "high"}),
            _j(_alert("TX-008", ["a"]) | {"severity": "low"}),
            ".json",
            False,
        ),
        (
            "confidence is not absorbed",
            _j(_alert("TX-008", ["a"]) | {"confidence": 0.5}),
            _j(_alert("TX-008", ["a"]) | {"confidence": 0.9}),
            ".json",
            False,
        ),
        (
            "a compact JSON report is compared, not skipped",
            _j({"generated_at": "x", "alert_count": 2, "alerts": []}),
            _j({"generated_at": "y", "alert_count": 3, "alerts": []}),
            ".json",
            False,
        ),
        (
            "a .txt sidecar is never markdown-normalised",
            b"### TX-008: L\n\n- **Documents:** `b`, `a`\n",
            b"### TX-008: L\n\n- **Documents:** `a`, `b`\n",
            ".txt",
            False,
        ),
        (
            "differing non-UTF-8 bytes are detected, not lossy-decoded",
            b"id\xff payload",
            b"id\xfe payload",
            ".txt",
            False,
        ),
        (
            "identical non-UTF-8 bytes compare equal",
            b"id\xff payload",
            b"id\xff payload",
            ".txt",
            True,
        ),
        (
            "unparseable JSON falls back to a raw comparison",
            b"{not json",
            b"{also not json",
            ".json",
            False,
        ),
    ]
    for name in VOLATILE_LOOKING_NAMES:
        cases.append(
            (
                f"volatile-looking key {name!r} is NOT absorbed",
                _j({"alert_count": 1, name: "x"}),
                _j({"alert_count": 1, name: "y"}),
                ".json",
                False,
            )
        )
    return cases


def check_normaliser_scope() -> list[str]:
    """Verify the normaliser absorbs exactly what it documents."""
    module = _load_check_module()
    problems: list[str] = []
    for label, first, second, suffix, expect_identical in scope_cases():
        identical = (
            module.canonical_bytes(first, suffix) == module.canonical_bytes(second, suffix)
        )
        if identical == expect_identical:
            print(f"  ok     {label}")
            continue
        problems.append(
            f"{label}: expected {'absorbed' if expect_identical else 'detected'}, "
            f"got {'absorbed' if identical else 'detected'}"
        )
        print(f"  WRONG  {label}")
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


class Case:
    __slots__ = ("title", "fn", "expect")

    def __init__(self, title: str, fn, expect: str | None = None):
        self.title = title
        self.fn = fn
        self.expect = expect


MUST_FAIL = [
    Case(
        "per-call clock value inside an alert detail",
        m_random_value_in_alert_detail,
        "demo_poison_alerts.jsonl differs",
    ),
    Case(
        "TX-001 doc_ids in random order (not the known #22 defect)",
        m_random_tx001_doc_order,
        "demo_poison_alerts.jsonl differs",
    ),
    Case("new volatile field in the JSON report", m_new_volatile_report_field),
    Case("generated_at grown by a detector", m_generated_at_inside_an_alert),
    Case("a Generated line emitted below the report header", m_generated_line_after_a_heading),
    Case("volatile document ordering after the TX-008 section", m_appendix_after_tx008),
    Case("extra output file on one run only", m_extra_output_file),
    Case("demo exits 0 but writes no files", m_demo_writes_nothing),
    Case("demo writes only an empty file", m_demo_writes_only_empty_files),
    Case("volatile text on a Markdown Documents line", m_volatile_suffix_on_documents_line),
]

MUST_PASS = [
    Case("report timestamp at microsecond resolution", m_microsecond_report_timestamp),
]

CONTROL = [
    Case("deterministic crash, zero nondeterminism injected", m_deterministic_crash),
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

    def evaluate(case: Case):
        repo = _fresh_repo()
        created.append(repo.parent)
        try:
            case.fn(repo)
        except MutationFailed as exc:
            problems.append(f"MUTATION DID NOT APPLY: {exc}")
            return None, ""
        except Exception as exc:  # noqa: BLE001 - a broken mutation is a failure
            problems.append(f"MUTATION RAISED {type(exc).__name__}: {exc}")
            return None, ""
        return run_check(repo)

    print(
        f"MUST FAIL (end to end) -- the check must reject each of these "
        f"({len(MUST_FAIL)} cases):"
    )
    for case in MUST_FAIL:
        rc, output = evaluate(case)
        if rc is None:
            print(f"  ERROR  {case.title}")
        elif rc == 0:
            problems.append(f"{case.title}: check returned 0 -> the check is BLIND")
            print(f"  BLIND  {case.title} -> rc=0, no difference reported")
        elif not _reported_a_difference(output):
            problems.append(
                f"{case.title}: check exited {rc} but reported no difference -> the "
                "mutation broke the demo instead of perturbing it"
            )
            print(f"  CRASH  {case.title} -> rc={rc}, no difference reported")
        elif case.expect and case.expect not in output:
            problems.append(
                f"{case.title}: a difference was reported but not in the expected "
                f"place; expected {case.expect!r} in the output"
            )
            print(f"  WRONG  {case.title} -> rc={rc}, wrong file reported")
        else:
            note = f" (in {case.expect})" if case.expect else ""
            print(f"  ok     {case.title} -> rc={rc}{note}")

    print("\nMUST PASS (end to end) -- the check must absorb this, and nothing more:")
    for case in MUST_PASS:
        rc, output = evaluate(case)
        if rc is None:
            print(f"  ERROR  {case.title}")
        elif rc != 0:
            problems.append(
                f"{case.title}: check returned {rc}, expected 0 -> normalisation too narrow"
            )
            print(f"  NARROW {case.title} -> rc={rc}")
            for line in output.splitlines()[:10]:
                print(f"          {line}")
        else:
            print(f"  ok     {case.title} -> rc=0 (correctly absorbed)")

    print("\nCONTROL -- the check must not mistake a crash for a detection:")
    for case in CONTROL:
        rc, output = evaluate(case)
        if rc is None:
            print(f"  ERROR  {case.title}")
        elif rc == 0:
            problems.append(
                f"CONTROL {case.title}: check returned 0 on a broken demo -> it detects nothing"
            )
            print(f"  BLIND  {case.title} -> rc=0")
        elif _reported_a_difference(output):
            problems.append(
                f"CONTROL {case.title}: a deterministic crash was reported as a difference"
            )
            print(f"  CONFUSED {case.title} -> crash reported as a detection")
        else:
            print(f"  ok     {case.title} -> rc={rc}, reported as a failure to run")

    print(f"\nNormalisation scope -- {len(scope_cases())} properties, called directly:")
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
        f"{len(scope_cases())} normaliser scope properties directly, and did not "
        "confuse a crash with a detection."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
