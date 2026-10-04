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
   line is removed from the *preamble* of a Markdown report -- the lines before
   the first section heading. A leading ``# title`` is a title rather than a
   section and does not end the preamble, because this project's own reports are
   shaped that way. Both record when a report was written, and nothing else in
   this codebase produces either: ``generated_at`` appears exactly once in the
   whole package, at ``report.py:100``.

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
import os
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
# ATX headings, with or without a space after the hashes: CommonMark accepts
# `#Heading` as well as `# Heading`. `(?!#)` is what stops seven hashes from
# being read as a six-hash heading. Recognising only the spaced form left the
# TX-008 section open for the other spelling.
_ATX_HEADING = re.compile(r"^\s{0,3}(#{1,6})(?!#)")
# Setext underlines, where `=====` underlines an H1 and `-----` an H2. A setext
# heading is only a heading when the line above it is non-blank, so this is
# resolved with lookahead in `_heading_levels` rather than by matching a line in
# isolation -- a `---` thematic break must not be mistaken for one.
_SETEXT_HEADING = re.compile(r"^\s{0,3}(=+|-{2,})\s*$")
# A fenced code block, opened or closed. Only the line shape matters here:
# `_heading_levels` needs to know which lines are *not* headings, and a
# fence is the one construct that reliably hides them. Deliberately the
# same permissive shape as the docs gate's `_FENCE`, so a report that
# documents a command and a gate that reads a report agree on where the
# fences are.
_FENCE = re.compile(r"^\s*(?P<ticks>`{3,}|~{3,})\s*(?P<info>.*?)\s*$")
_TX_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*(TX-\d+)")
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
    # `splitlines()` then `"\n".join()` is what makes a CRLF file and an LF file
    # compare equal, and what drops a trailing newline. Both are documented in
    # `describe_policy` rather than fixed, because a JSON *record's* content is
    # what this comparison is for and neither is part of it. Verified: CRLF-vs-LF
    # and trailing-newline-vs-none both compare equal.
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


def _heading_levels(lines: list[str]) -> dict[int, int]:
    """Map line index -> heading level, for ATX and setext headings.

    Setext needs lookahead, so this cannot be a per-line regex: the underline
    arrives *after* the text it underlines.

    Two exclusions, both because a line that looks like a heading is not one:

    - A line inside a fenced code block is not a heading. A report quoting
      `## Usage` inside a fence would otherwise close its own preamble there, and
      `_header_end` would then miss every real section after it.
    - A setext underline cannot follow another heading, because a heading is
      already a complete block and a `---` on the next line is a thematic break.
      CommonMark says exactly this. The previous version did not: `# Title` on
      line 1 made the `---` on line 2 a level-2 heading, so `_header_end`
      returned 1 and the report's own `**Generated:**` line was compared
      literally -- a spurious red, since the two runs really do differ by a
      second. The `_SETEXT_HEADING` comment above already claimed "a `---`
      thematic break must not be mistaken for one"; this is where that is true.

    `previous_was_heading` rather than "is the previous line an ATX heading",
    because a setext heading's *last* line is its underline and that counts too.
    Checking only ATX left `Title` / `=====` / `---` misparsed the same way.
    """
    levels: dict[int, int] = {}
    in_fence = False
    previous_was_heading = False
    for index, line in enumerate(lines):
        if _FENCE.match(line):
            in_fence = not in_fence
            previous_was_heading = False
            continue
        if in_fence:
            previous_was_heading = False
            continue
        atx = _ATX_HEADING.match(line)
        if atx:
            levels[index] = len(atx.group(1))
            previous_was_heading = True
            continue
        previous = lines[index - 1] if index else ""
        if previous.strip() and not previous_was_heading:
            setext = _SETEXT_HEADING.match(line)
            if setext:
                levels[index] = 1 if setext.group(1).startswith("=") else 2
                previous_was_heading = True
                continue
        previous_was_heading = False
    return levels


def _span_start(lines: list[str], index: int) -> int:
    """First line of the heading block whose marker is at `index`.

    A setext heading is underlined, so its text is on the line *above* the
    marker; an ATX heading is a single line. Needed so that a setext H1 title is
    recognised as a title rather than as a section.
    """
    return index - 1 if _SETEXT_HEADING.match(lines[index]) else index


def _header_end(lines: list[str], levels: dict[int, int]) -> int:
    """Index of the first line that ends a report's metadata preamble.

    A level-1 heading at the very top is the document *title*, not a section,
    so it does not end the preamble; the block ends at the next heading. This
    is the fix for a real defect: the previous rule ended the header at the
    first heading of any level, and this project's own reports start with
    ``# <title>`` on line 1 and put ``**Generated:**`` on line 3. So the
    timestamp was never normalised in the reports the gate actually compares,
    and the gate passed only because two consecutive runs usually land in the
    same second -- a spurious failure roughly one run in ten.

    When there is no section heading at all -- the document's only heading is
    its title, or it has no headings -- there is no preamble and the index is 0.
    Returning ``len(lines)`` instead, as this used to, made the whole document
    its own header, so a ``**Generated:**`` line anywhere in the body was
    absorbed. For a report that means a per-run timestamp silently normalised
    away: a gate that reports two differing runs as identical is the one
    failure mode a determinism check must not have. None of this project's
    reports are shaped that way -- each has a ``## Summary`` -- so the stricter
    rule costs nothing and errs towards reporting a difference rather than
    hiding one.
    """
    ordered = sorted(levels)
    if ordered:
        first = ordered[0]
        if levels[first] == 1 and not any(
            line.strip() for line in lines[: _span_start(lines, first)]
        ):
            ordered = ordered[1:]
    return ordered[0] if ordered else 0


def _canonical_markdown(text: str) -> str:
    lines = text.splitlines(keepends=True)
    levels = _heading_levels(lines)
    header_end = _header_end(lines, levels)
    out = []
    section = None
    for index, line in enumerate(lines):
        if index < header_end and _GENERATED_LINE.match(line):
            continue
        # Any heading at any level ends the TX-008 section. Matching only
        # `### TX-\d+` would leave `section` latched onto TX-008 for the rest of
        # the document.
        if index in levels:
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


def canonicalise(raw: bytes, suffix: str) -> bytes | None:
    """Canonical form of `raw`, or None if it is not a machine-readable report.

    None means "not parsed", which the caller must know: a run whose every file
    fails to parse must not be reported as deterministic. "Could not compare"
    and "compared equal" are different answers, and conflating them is how a
    gate passes vacuously.
    """
    if suffix not in (".json", ".jsonl", ".md"):
        return None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        # Not text. Comparing the bytes is stricter than comparing a lossy
        # decode, which would report two different files as identical.
        return None
    if suffix == ".json":
        canonical = _canonical_json(text)
    elif suffix == ".jsonl":
        canonical = _canonical_jsonl(text)
    else:
        canonical = _canonical_markdown(text)
    return None if canonical is None else canonical.encode("utf-8")


def canonical_bytes(raw: bytes, suffix: str) -> bytes:
    """Canonical form of `raw`, falling back to the raw bytes.

    Anything that is not a parsed report is returned untouched: a .txt or .csv
    sidecar is not Markdown, and running it through the Markdown normaliser
    would mean reordering text in a file whose format we do not know.
    """
    canonical = canonicalise(raw, suffix)
    return raw if canonical is None else canonical


def describe_policy() -> str:
    """What the comparison permits, stated in full.

    JSON is re-serialised, which also absorbs key order, indentation, escape
    form and number form. Those are properties of *formatting* rather than
    results, but they are still things the comparison lets through, and the
    previous wording named three allowances while relying on several more.

    The list below names two more that fall out of the same re-serialisation and
    were previously left for a reader to discover. JSON Lines records are split
    and rejoined with ``"\\n"``, so a CRLF file and an LF file compare equal, and
    a file with a trailing newline and one without compare equal. Both were
    verified. Neither is new information to the gate -- the JSON re-serialisation
    allowance already covers whitespace, of which a line ending is a kind, and
    the previous wording said "whitespace" too -- but a reader auditing what this
    gate lets through should not have to derive it. The risk is bounded and
    stated here: a `.gitattributes` change or a `core.autocrlf` setting would
    not be detected, and neither would a report that stopped ending in a
    newline. Neither alters the *content* of an alert record, which is what this
    gate exists to compare.
    """
    return (
        f"Permitted variation: JSON re-serialisation (key order, whitespace, "
        f"line endings, escape form, number form, trailing newline), the "
        f"top-level '{REPORT_METADATA_KEY}' key in JSON reports, the "
        f"'**Generated:**' header line in Markdown, and {NORMALISED_HEURISTIC} "
        f"doc_ids order."
    )


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------


def run_demo(dest: Path, run_number: int) -> None:
    """Run `python -m toxindb demo` once, into `dest`.

    `python -m` puts the working directory first on `sys.path`, so this
    deliberately measures the checkout: the demo job installs editable, and the
    gate teeth script injects its mutations into a copy of the tree that only
    takes effect if the copy is what gets imported. Running the demo this way
    also means `trace_gen.get_traces_dir()` resolves to the checkout, so the
    demo *could* write into the tree being guarded, and `main()` asserts that it
    does not. In practice `ensure_demo_traces()` skips every fixture that
    already exists, so nothing is written -- which is why that assertion is a
    net rather than a tripwire.

    `run_number` is exported as `TOXINDB_DETERMINISM_RUN`. Nothing in toxindb
    reads it; the teeth script's mutations do. A test for "this output differs
    between runs" needs the two runs to actually differ, and the only way to
    arrange that without a coin flip is to tell the run which run it is. Doing
    so makes those cases deterministic: previously they rolled the dice, and on
    the rare occasion every roll matched, the gate concluded the check was blind
    and failed. The variable is the difference between "can fail" and "will".
    """
    if dest.exists():
        shutil.rmtree(dest)
    env = dict(os.environ, TOXINDB_DETERMINISM_RUN=str(run_number))
    completed = subprocess.run(
        [sys.executable, "-m", "toxindb", "demo", "--output", str(dest)],
        capture_output=True,
        text=True,
        env=env,
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


class GitUnavailable(RuntimeError):
    """`git` could not be executed at all.

    Deliberately distinct from "not a repository": the latter is a legitimate
    reason to skip the assertion with a note, but a missing git binary means
    the safety net silently vanishes, which must be a hard failure.
    """


class GitRefused(RuntimeError):
    """`git` ran, in a real checkout, and failed anyway.

    Separate from `GitUnavailable` because it used to be invisible. `_tree_state`
    returned None for *every* non-zero exit from `git status`, and None is the
    documented "outside a git checkout" answer -- so a corrupt index, or git's
    own `safe.directory` refusal on a checkout owned by another uid, produced
    `note skipped the working-tree assertion (not a git checkout)` and exited 0.

    That note was the opposite of the truth, and the assertion it described is
    the only evidence that `toxindb demo` did not overwrite the committed
    fixtures. Verified: the same tree-write mutation that exits 1 against a
    healthy index exits 0 against a truncated one.
    """


def _inside_a_checkout(root: Path) -> bool:
    """Is there a `.git` in `root` or any parent, the way git itself looks?

    Deliberately not a message match on git's stderr. `fatal: not a git
    repository` is one of several phrases git varies between versions and
    locales; the presence of a `.git` entry is the property that actually
    decides the question. It may be a *file* rather than a directory, which is
    what a linked worktree and a submodule submodule both use, so this tests
    `exists()` and not `is_dir()`.
    """
    for candidate in (root, *root.parents):
        if (candidate / ".git").exists():
            return True
    return False


def _tree_state(root: Path) -> str | None:
    """A snapshot of the working tree, including gitignored paths.

    Returns None outside a git checkout, where the assertion is skipped with a
    printed note rather than assumed to have passed.

    `--ignored=traditional` rather than `--ignored=matching`. `matching`
    collapses an ignored *directory* to a single `!! reports/` line, so nothing
    inside it can ever change the snapshot -- verified: writing
    `reports/LEAKED_SECRET.json` into an already-ignored `reports/` left the
    snapshot byte-identical. `traditional` lists the files, so a new one shows
    up. (A content change to an already-ignored file remains invisible, because
    git does not track such files at all; only the file *list* is compared.)

    Byte-code caches are filtered out. They are created by *importing* the
    package, so they appear during any run that imports toxindb and say nothing
    about whether the run wrote to the tree. They are also the one ignored path
    guaranteed to be new on a fresh CI checkout, which is exactly what happened:
    the first version of this assertion failed on `!! toxindb/__pycache__/` and
    nothing else. The filter is narrow -- `__pycache__` paths and `.pyc` files --
    because everything else, including ignored data files, is a real signal.
    """
    try:
        proc = subprocess.run(
            [
                "git",
                "status",
                "--porcelain",
                "--untracked-files=all",
                "--ignored=traditional",
            ],
            cwd=root,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise GitUnavailable(str(exc)) from exc
    if proc.returncode != 0:
        # Distinguish "this is not a checkout" from "git is here and failed".
        # Conflating them is how a corrupt index or a `safe.directory` refusal
        # used to turn this assertion off and print a note asserting the
        # opposite. Only the first is a legitimate skip, and it is decided by
        # the absence of a `.git`, not by anything git says.
        if not _inside_a_checkout(root):
            return None
        raise GitRefused(
            f"`git status` exited {proc.returncode} in a checkout: "
            f"{proc.stderr.strip() or proc.stdout.strip() or 'no output'}"
        )
    # Narrow on path *components*, not on the substring `"__pycache__" in line`.
    # The substring also matched any path carrying that text anywhere in its
    # name -- `toxindb/report_cache.py`, a fixture called
    # `__pycache__notes.jsonl` -- and dropped it from the comparison without
    # saying so, which is the failure this assertion exists to produce. See the
    # same filter in check_docs_commands.py.
    return "".join(
        line for line in proc.stdout.splitlines(keepends=True)
        if not _is_byte_code_cache(line)
    )


def _is_byte_code_cache(line: str) -> bool:
    """Is this `git status --porcelain` line a byte-code cache entry?

    `XY PATH`, so the path starts at offset 3. A rename reads `old -> new` and
    the new name is the one on disk.
    """
    entry = line[3:] if len(line) > 3 else ""
    path = entry.split(" -> ")[-1].strip().strip('"')
    return "__pycache__" in path.split("/") or path.endswith(".pyc")


def _assert_tree_unchanged(before: str | None, after: str | None, root: Path) -> int:
    if before is None or after is None:
        print("  note   skipped the working-tree assertion (not a git checkout)")
        return 0
    if before == after:
        return 0
    # A real finding, and the same one the docs gate asserts. The demo resolves
    # its fixture directory through `trace_gen.get_traces_dir()`, which is
    # relative to the *package* directory rather than to the working directory.
    # Under the editable install the demo job uses, that is the checkout.
    #
    # `ensure_demo_traces()` guards every write with `if not os.path.exists(...)`,
    # so on a normal run the committed fixtures are left untouched and this
    # assertion stays quiet. That is precisely what makes it worth having: it is
    # a safety net for the change that removes that guard, or adds a write
    # somewhere else. Verified by injecting an unconditional write into the
    # installed package: the demo still reported "deterministic", and this
    # assertion is what caught it.
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

        run_demo(live, 1)
        shutil.copytree(live, first, dirs_exist_ok=True)
        run_demo(live, 2)
        shutil.copytree(live, second, dirs_exist_ok=True)

        verdict = _compare(first, second)
        # Asserted regardless of the verdict. A run that reports
        # nondeterminism *and* dirtied the tree is still the more informative
        # failure, and a run that reports determinism while having overwritten
        # the fixtures is not a result at all.
        dirty = _assert_tree_unchanged(tree_before, _tree_state(repo_root), repo_root)
        return verdict or dirty
    except GitUnavailable as exc:
        print(
            f"error: `git` could not be run ({exc}), so this script cannot show "
            f"that the demo left the working tree alone. Install git, or delete "
            f"this job -- silently dropping the check would be worse than the "
            f"crash.",
            file=sys.stderr,
        )
        return 2
    except GitRefused as exc:
        print(
            f"error: {exc}. This script cannot show that the demo left the "
            f"working tree alone, and reporting the run as deterministic without "
            f"that evidence would be claiming more than it checked. Repair the "
            f"checkout (`git status` in it should work) and re-run.",
            file=sys.stderr,
        )
        return 2
    except OSError as exc:
        # This script's whole thesis is that a crash is not a result. An
        # unwritable or full scratch directory must not escape as a traceback
        # whose exit code is indistinguishable from a determinism verdict.
        #
        # `shutil.copytree` reports per-file failures as a list inside the
        # exception, and a dangling symlink in the demo's output is one of them.
        # Blaming the scratch *directory* for a single broken file points the
        # reader at the wrong place, so the individual reasons are printed too.
        detail = ""
        args = getattr(exc, "args", ())
        if args and isinstance(args[0], list):
            detail = "\n" + "\n".join(
                f"  {item[0]}: {item[2]}" for item in args[0] if len(item) >= 3
            )
        print(
            f"error: the scratch area {scratch} could not be used: {exc}{detail}",
            file=sys.stderr,
        )
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

    readable = 0
    for rel in sorted(common):
        raw_a = _read(first / rel)
        raw_b = _read(second / rel)
        canon_a = canonicalise(raw_a, rel.suffix)
        canon_b = canonicalise(raw_b, rel.suffix)
        if canon_a is not None and canon_b is not None and canon_a and canon_b:
            # Parsed, and there is content in it. This is the only kind of
            # file that can support a determinism claim.
            readable += 1
        # Not machine-readable: fall back to comparing the bytes. That is still
        # a real comparison -- it is what catches two different non-UTF-8
        # sidecars -- but it does not count towards `readable` below.
        a = raw_a if canon_a is None else canon_a
        b = raw_b if canon_b is None else canon_b
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

    # Comparing nothing proves nothing. The zero-*files* case is caught by
    # `common` being empty above. The zero-*content* case is not, and it has two
    # shapes: a demo that writes only empty files, and a demo that writes only
    # files this script cannot parse. Both compare clean and would be reported
    # as deterministic. The earlier guard counted 0-byte files only, so a demo
    # that wrote `{not json` twice passed while proving nothing.
    if readable == 0:
        print(
            "::error::no compared file was non-empty and machine-readable, so "
            "there is nothing to compare and determinism cannot be claimed"
        )
        return 1

    if failures:
        print(
            f"::error::the demo is NOT deterministic "
            f"({failures} difference(s) across {len(common)} compared file(s))"
        )
        return 1

    print(
        f"Compared {len(common)} file(s) across two runs "
        f"({readable} machine-readable): the demo is deterministic. "
        f"{describe_policy()}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
