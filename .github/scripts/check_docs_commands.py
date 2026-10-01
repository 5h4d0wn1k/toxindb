#!/usr/bin/env python3
"""Execute every runnable command in README.md and fail if any of them fail.

Why this exists
---------------
toxindb's README is its primary interface. A command that is documented but no
longer runs is worse than no command at all, because it costs a reader their
time and their trust in every other line of the file. Nothing else in this
repository would notice that: the test suite exercises the Python API and the
CLI in-process, but it does not read README.md, so doc rot is invisible to it.

This script closes that gap. It parses the fenced ```bash blocks out of the
README, runs the ones that are safe to run, and exits non-zero if any of them
fails. It runs in CI on every push and pull request.

Design constraints
------------------
1. **No network.** Every command that is run is fully offline, which is the
   project's core promise. Commands that would need the network are skipped,
   and the skip is reported rather than hidden.
2. **No environment mutation.** Commands that create a venv or install packages
   are skipped. The CI job has already installed the package before this runs --
   as a *non-editable* install, which this script checks rather than assumes,
   because `toxindb demo` regenerates fixtures relative to the package
   directory and an editable install would send that into the checkout.
3. **Honest skips.** A skipped command is printed as SKIPPED with its reason.
   A gate that quietly ignores half the file is not a gate. For the same
   reason, a leading `cd` or `mkdir` does not make a command skippable: only
   the steps that actually assert something about toxindb are judged.
4. **No test-suite duplication.** The README's test block is skipped because the
   suite job runs it directly, which is a stronger check than shelling out.
5. **The checkout is not an output directory.** After running, the working tree
   is compared against its prior state and a change fails the job.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# A command is split into its chained steps and each step judged separately.
# Only steps that are not shell setup can make the command skippable.
#
# This distinction is the whole reason the split exists. `cd . && toxindb
# monitor <broken path>` used to be skipped, because the skip rules matched
# the whole line and `cd` matched "directory navigation". The documented
# command then rotted in plain sight and the job stayed green. Setup decides
# where a command runs; the payload decides whether the job can check it.
SETUP_STEPS: re.Pattern[str] = re.compile(
    r"^\s*(?:"
    r"(?:cd|pushd)\b"              # change directory
    r"|mkdir\b"                    # create a scratch output directory
    r"|export\b|set\b"             # set an environment variable
    r"|source\b|\.\s+\S*activate"  # activate a virtualenv
    r")",
    re.VERBOSE,
)

# A payload step matching any of these must not be run here. The reason is
# printed so a reviewer can judge whether the skip is sound.
UNSAFE_STEPS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^\s*git\s+clone\b"), "clones the network"),
    (re.compile(r"^\s*git\s+(remote|fetch|pull|push|submodule)\b"), "network"),
    (re.compile(r"^\s*(?:python3?|\S*tox)?\s*-m\s+pip\b|pip\s+install\b"), "mutates the environment"),
    (re.compile(r"^\s*python3?\s+-m\s+venv\b"), "mutates the environment"),
    (re.compile(r"^\s*(?:python3?|tox)\s+-m\s+pytest\b|^\s*pytest\b"), "already run by the suite job"),
    (re.compile(r"^\s*(?:source\b|\.\s+\S*activate)"), "mutates the shell environment"),
    (re.compile(r"^\s*(?:rm|mv|cp)\b"), "destructive filesystem operation"),
    (re.compile(r"^\s*(?:touch|chmod|chown)\b"), "filesystem mutation"),
)

# Shell metacharacters that chain steps together on one line.
_CHAIN = re.compile(r"\s*(?:&&|\|\||;|\|)\s*")

TIMEOUT_SECONDS = 300


def strip_inline_comment(line: str) -> str:
    """Remove a trailing `# ...` comment, respecting quotes."""
    out: list[str] = []
    quote: str | None = None
    i = 0
    while i < len(line):
        ch = line[i]
        if quote:
            out.append(ch)
            if ch == "\\" and i + 1 < len(line):
                out.append(line[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
            out.append(ch)
        elif ch == "#" and (not out or out[-1] in " \t"):
            break
        else:
            out.append(ch)
        i += 1
    return "".join(out).strip()


def split_steps(command: str) -> list[str]:
    """Split a command on shell chaining, respecting simple quoting."""
    steps: list[str] = []
    current: list[str] = []
    quote: str | None = None
    i = 0
    while i < len(command):
        ch = command[i]
        if quote:
            current.append(ch)
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in "'\"":
            quote = ch
            current.append(ch)
            i += 1
            continue
        pair = command[i:i + 2]
        if pair in ("&&", "||", ";", "|"):
            steps.append("".join(current).strip())
            current = []
            i += 2
            continue
        current.append(ch)
        i += 1
    steps.append("".join(current).strip())
    return [step for step in steps if step]


def skip_reason(command: str) -> str | None:
    """Why this command must not be run, or None if it is safe to run.

    Only payload steps can trigger a skip. A line such as
    ``mkdir -p reports && toxindb provenance examples/traces/clean.jsonl`` sets
    up an output directory and then asserts something about toxindb; skipping it
    because of the ``mkdir`` would leave the documented command unchecked.
    """
    steps = split_steps(command)
    if not steps:
        return "blank"
    if all(step.startswith("#") for step in steps):
        return "comment only"

    payload = [step for step in steps if not SETUP_STEPS.match(step)]
    if not payload:
        return "shell setup only, nothing to check"

    for step in payload:
        for pattern, reason in UNSAFE_STEPS:
            if pattern.search(step):
                return reason
    return None


def _diff_lines(before: str, after: str) -> list[str]:
    import difflib

    return [
        line
        for line in difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile="tree before",
            tofile="tree after",
            lineterm="",
        )
    ]


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _tree_state(root: Path) -> str | None:
    """A snapshot of the tracked/untracked file list under `root`.

    Returns None outside a git checkout, where the assertion is skipped with a
    printed note rather than silently assumed to have passed.
    """
    proc = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout


def extract_bash_blocks(markdown: str) -> list[tuple[int, list[str]]]:
    """Return (line_number, lines) for each fenced ```bash block."""
    blocks: list[tuple[int, list[str]]] = []
    lines = markdown.splitlines()
    in_block = False
    start = 0
    body: list[str] = []
    for number, line in enumerate(lines, 1):
        if not in_block and line.strip() == "```bash":
            in_block, start, body = True, number, []
            continue
        if in_block and line.strip() == "```":
            blocks.append((start, body))
            in_block = False
            continue
        if in_block:
            body.append(line)
    return blocks


def logical_commands(lines: list[str]) -> list[str]:
    """Join backslash continuations, strip comments, drop blanks."""
    joined: list[str] = []
    buffer = ""
    for raw in lines:
        line = raw.rstrip()
        if line.endswith("\\"):
            buffer += line[:-1] + " "
            continue
        buffer += line
        stripped = strip_inline_comment(buffer)
        if stripped:
            joined.append(stripped)
        buffer = ""
    if buffer:
        stripped = strip_inline_comment(buffer)
        if stripped:
            joined.append(stripped)
    return joined


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--readme",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "README.md",
        help="path to the README to check (default: the repository README)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="print what would be run without running anything",
    )
    args = parser.parse_args()

    if not args.readme.is_file():
        print(f"error: README not found at {args.readme}", file=sys.stderr)
        return 2

    markdown = args.readme.read_text(encoding="utf-8")
    blocks = extract_bash_blocks(markdown)
    if not blocks:
        print(f"error: no ```bash blocks found in {args.readme}", file=sys.stderr)
        print("If the README lost its shell examples, delete this job instead of", file=sys.stderr)
        print("letting it pass vacuously.", file=sys.stderr)
        return 2

    planned: list[tuple[int, str, str | None]] = []
    for start, body in blocks:
        for command in logical_commands(body):
            planned.append((start, command, skip_reason(command)))

    if args.list:
        for line_no, command, reason in planned:
            state = f"SKIP ({reason})" if reason else "RUN"
            print(f"{state:28} README.md:{line_no}  {command}")
        return 0

    print(f"Checking {len(planned)} command(s) from {args.readme.name}\n")
    failures: list[tuple[int, str, int, str]] = []
    ran = skipped = 0
    repo_root = Path(__file__).resolve().parents[2]
    tree_before = _tree_state(repo_root)

    with tempfile.TemporaryDirectory(prefix="toxindb-docs-") as tmp:
        workdir = Path(tmp)
        # Run hermetically: copy the fixture data into a scratch directory and
        # execute there. Several documented commands write files (the demo
        # writes reports/, `canary --plant` writes a new trace), and running
        # them in the checkout would leave the working tree dirty on every CI
        # run. A gate that mutates the tree it guards is a bad gate.
        #
        # Copying examples/ is necessary but NOT sufficient. `toxindb demo`
        # regenerates its fixtures via `trace_gen.get_traces_dir()`, which
        # resolves relative to the *package* directory rather than the working
        # directory. With an editable install that is the checkout, so the demo
        # writes into the real tree no matter where it is invoked from. The
        # precondition below refuses to run in that configuration, and the
        # post-run assertion below catches any future leak that slips past it.
        examples = Path.cwd() / "examples"
        if examples.is_dir():
            shutil.copytree(examples, workdir / "examples")
        else:
            print(
                "warning: no examples/ directory found; commands that reference "
                "bundled fixtures will fail",
                file=sys.stderr,
            )

        # NOT .resolve(): on a venv created by `python -m venv`, sys.executable is
        # a symlink to the base interpreter, and resolving it would walk out of
        # the venv and point at the wrong bin directory entirely.
        bindir = Path(sys.executable).parent
        env = dict(os.environ)
        env["PATH"] = f"{bindir}{os.pathsep}{env.get('PATH', '')}"

        # Guard 1: if the console script that the README invokes does not belong
        # to this interpreter, we would be validating a *different* toxindb than
        # the one CI just built, and every result below would be meaningless.
        # Fail loudly rather than report a green gate that tested the wrong code.
        for name in ("toxindb",):
            resolved = shutil.which(name, path=env["PATH"])
            expected = bindir / name
            if resolved is None:
                print(
                    f"error: `{name}` is not on PATH after prepending {bindir}. "
                    f"Install the package before running this check "
                    f"(pip install .).",
                    file=sys.stderr,
                )
                return 2
            if Path(resolved).resolve() != expected.resolve():
                print(
                    f"error: `{name}` resolves to {resolved}, which is not the "
                    f"console script for {sys.executable} (expected {expected}).\n"
                    f"Refusing to report a green docs gate that tested a different "
                    f"installation.",
                    file=sys.stderr,
                )
                return 2

        # Guard 2: refuse to run against an editable install of this checkout.
        # See the comment above -- `toxindb demo` would regenerate fixtures
        # inside the repository, and it would do so silently.
        try:
            import toxindb as _pkg
        except ImportError:
            print("error: toxindb is not importable by this interpreter", file=sys.stderr)
            return 2
        pkg_dir = Path(_pkg.__file__).resolve().parent
        if _is_within(pkg_dir, repo_root):
            print(
                f"error: toxindb is loaded from {pkg_dir}, which is inside the "
                f"repository at {repo_root}.\n"
                f"`toxindb demo` regenerates its fixtures relative to the package "
                f"directory, so running the documented commands would write into "
                f"the checkout.\n"
                f"Re-run this check against a non-editable install: "
                f"`pip install .` (not `pip install -e .`).",
                file=sys.stderr,
            )
            return 2
        print(
            f"  note   toxindb loaded from {pkg_dir} (outside the checkout, so "
            f"fixture regeneration cannot dirty the tree)"
        )

        for line_no, command, reason in planned:
            if reason:
                skipped += 1
                print(f"  SKIP  README.md:{line_no:<5} ({reason})")
                continue
            ran += 1
            try:
                completed = subprocess.run(
                    command,
                    shell=True,
                    cwd=workdir,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=TIMEOUT_SECONDS,
                )
                rc, output = completed.returncode, completed.stdout + completed.stderr
            except subprocess.TimeoutExpired:
                rc, output = 124, f"timed out after {TIMEOUT_SECONDS}s"

            if rc == 0:
                print(f"  PASS  README.md:{line_no:<5} {command}")
            else:
                print(f"  FAIL  README.md:{line_no:<5} {command}  (exit {rc})")
                tail = [ln for ln in output.strip().splitlines() if ln.strip()][-5:]
                for line in tail:
                    print(f"        | {line}")
                failures.append((line_no, command, rc, output))

    print(f"\n{ran} command(s) executed, {skipped} skipped, {len(failures)} failed")

    tree_after = _tree_state(repo_root)
    if tree_before is None or tree_after is None:
        print("  note   skipped the working-tree assertion (not a git checkout)")
    elif tree_before != tree_after:
        # This is the assertion that makes the "runs hermetically" claim above
        # verifiable. Guards 1 and 2 remove the two known ways the demo can
        # write into the checkout; this catches the ones nobody has thought of.
        print(
            "::error::running the documented commands modified the working tree",
            file=sys.stderr,
        )
        for line in _diff_lines(tree_before, tree_after):
            print(f"  {line}", file=sys.stderr)
        return 1

    if failures:
        print(
            "\nThe README documents commands that do not run. Either fix the "
            "documented\ncommand, or if the example needs a real input file, "
            "point it at one that\nships in the repository.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
