#!/usr/bin/env python3
"""Prove that check_docs_commands.py can actually fail.

The companion to check_gate_teeth.py, and it exists for the same reason. That
script proves the *determinism* gate rejects what it is supposed to reject. The
*docs* gate was shipped with no equivalent, and it is the gate that had four
holes found by inspection rather than by a failing test:

* ``subprocess.run(..., shell=True)`` returns the **shell's** exit status, so
  ``toxindb nosuchsubcommand &`` printed PASS and the job exited 0.
* ``$(...)`` and backticks were passed straight to the shell, so command
  substitution ran -- which breaks the gate's own "no network" promise, since
  nothing about the substitution was inspected.
* a fence that was never closed printed ``::error::`` and still exited 0, so
  every command after it silently went uncompared.
* ``RUNNABLE_STEPS`` was anchored at the start of the string, so
  ``env toxindb ...``, ``nohup toxindb ...``, ``timeout 5 toxindb ...`` and
  ``FOO=bar toxindb ...`` were all reported as "not a toxindb command" and
  skipped. The job exited 0 with two nonexistent subcommands unverified.

Each of those is a MUST_FAIL case here, and each one is a *regression* test: a
future change that reintroduces ``shell=True`` turns the substitution case green
again in exactly the way it was before.

Two rules, same as the determinism gate's:

1. **A crash is not a detection.** Every MUST_FAIL case must make the gate
   report a *verdict* -- a FAIL line for the command, or a named error -- not
   merely exit non-zero. A mutation that broke the gate so badly it crashed
   would otherwise score as a pass.
2. **A gate that always fails is not a gate.** MUST_PASS runs a README the gate
   should accept and requires exit 0.

Nothing here mutates the repository. Each case writes a small synthetic README
to a temporary file and passes it with ``--readme``; the gate resolves its own
repository root from ``__file__``, so the real checkout is still what the tree
assertion watches, and a case that dirtied it would be caught.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHECK = HERE / "check_docs_commands.py"

# Substrings the gate prints when it reached a verdict, as opposed to crashing.
# A verdict is either a failing documented command or a named structural
# complaint about the document.
VERDICT_MARKERS = (
    "FAIL  ",
    "command(s) executed",
    "code fence",
    "no ```bash blocks found",
    "unlabelled code fence",
    "SKIP  ",
    "error:",
    "::error::",
    "Traceback",
)


def readme(body: str) -> str:
    """A synthetic README whose commands all sit on line 4.

    `# Synthetic README` on line 1, a blank line 2, the opening fence on line 3,
    and the first body line on line 4. Every case below uses this single-command
    shape where possible, so the expected line number is the same in all of them.
    """
    return f"# Synthetic README\n\n```bash\n{body}\n```\n"


# The line the first command of a `readme()` body lands on. Asserted rather than
# assumed, because a wrong expectation here reads as a gate failure and costs
# more time than the constant is worth.
COMMAND_LINE = 4

# An absolute path outside the gate's own scratch directory, used to detect
# whether a documented command substitution actually ran.
#
# The first version of this check used a bare relative filename, and it could
# never fire. The gate runs documented commands in a `TemporaryDirectory` that
# it removes before returning, so any file a substitution created was deleted
# before the check looked for it -- an assertion that was incapable of failing
# and therefore proved nothing. Verified: reintroducing the argv-to-shell-string
# regression below creates this marker and the check catches it, where the
# relative version stayed green.
NO_SIDE_EFFECT = "TEETH_SIDE_EFFECT_MARKER"


class Case:
    __slots__ = ("title", "markdown", "expect_rc", "expect", "marker")

    def __init__(
        self,
        title: str,
        markdown: str,
        expect_rc: int,
        expect: str | None = None,
        marker: str | None = None,
    ):
        self.title = title
        self.markdown = markdown
        self.expect_rc = expect_rc
        self.expect = expect
        # Substituted in for `{marker}` when the markdown is written, so a
        # substitution case can name a path that outlives the gate's scratch
        # directory.
        self.marker = marker


# --------------------------------------------------------------------------
# MUST FAIL -- the gate must reject each of these, and say why.
# --------------------------------------------------------------------------

MUST_FAIL = [
    Case(
        "a documented command that exits non-zero",
        readme("toxindb nosuchsubcommand"),
        1,
        expect=f"FAIL  README.md:{COMMAND_LINE}",
    ),
    # Finding: shell=True returned the shell's status, so the trailing `&`
    # backgrounded a failing command and the gate reported PASS with rc 0.
    Case(
        "a failing command backgrounded with a trailing &",
        readme("toxindb nosuchsubcommand &"),
        1,
        expect="background operator",
    ),
    # Finding: `$(...)` reached /bin/sh and ran. The gate used to execute it,
    # which breaks its own "no network" promise: nothing inspects the inside of
    # a substitution. Refusing it leaves nothing to run, so the documented
    # command is skipped -- and a README whose only command is skipped must then
    # fail the "ran == 0" floor rather than pass. This case is the one that
    # proves the substitution did not run: the marker path is absolute, because
    # a relative one would be created inside the gate's scratch directory and
    # deleted before anything could look for it.
    Case(
        "a README whose only command is command substitution fails",
        readme("toxindb demo $(touch {marker})"),
        1,
        expect="command substitution",
        marker="substitution",
    ),
    Case(
        "backtick command substitution is refused, not executed",
        readme("toxindb demo `touch {marker}`"),
        1,
        expect="backtick command substitution",
        marker="backtick",
    ),
    Case(
        "a failing command piped into a head is refused",
        readme("toxindb nosuchsubcommand | head -1"),
        1,
        expect="not a toxindb command",
    ),
    Case(
        "a failing command with a redirect is refused",
        readme("toxindb nosuchsubcommand > /dev/null"),
        1,
        expect="redirection",
    ),
    Case(
        "an unquoted wildcard is refused",
        readme("toxindb nosuchsubcommand *.jsonl"),
        1,
        expect="glob",
    ),
    Case(
        "variable expansion is refused",
        readme("toxindb monitor $TRACE"),
        1,
        expect="variable expansion",
    ),
    # Finding: RUNNABLE_STEPS was anchored at the start of the string, so each
    # of these was silently skipped and the job exited 0 with a nonexistent
    # subcommand unverified. The correct behaviour is to RUN them, and then
    # fail -- which is what these cases assert.
    Case(
        "env-wrapped invocation is run, not skipped",
        readme("env toxindb nosuchsubcommand"),
        1,
        expect=f"FAIL  README.md:{COMMAND_LINE}",
    ),
    Case(
        "nohup-wrapped invocation is run, not skipped",
        readme("nohup toxindb nosuchsubcommand"),
        1,
        expect=f"FAIL  README.md:{COMMAND_LINE}",
    ),
    Case(
        "timeout-wrapped invocation is run, not skipped",
        readme("timeout 5 toxindb nosuchsubcommand"),
        1,
        expect=f"FAIL  README.md:{COMMAND_LINE}",
    ),
    Case(
        "invocation with a leading variable assignment is run, not skipped",
        readme("PYTHONHASHSEED=0 toxindb nosuchsubcommand"),
        1,
        expect=f"FAIL  README.md:{COMMAND_LINE}",
    ),
    Case(
        "sudo is refused rather than run",
        readme("sudo toxindb nosuchsubcommand"),
        1,
        expect="would change privileges",
    ),
    Case(
        "every documented command skipped is a failure, not a pass",
        readme("git clone https://github.com/5h4d0wn1k/toxindb.git"),
        1,
        expect="no documented command was executed",
    ),
]

# Structural complaints. These are the document's fault, not a command's, and
# the gate reports them before it runs anything.
STRUCTURAL = [
    Case(
        "an unterminated code fence is a failure",
        "# Synthetic\n\n```bash\ntoxindb --version\n",
        1,
        expect="never closed",
    ),
    # The closing fence of a non-shell block used to be read as the *opening* of
    # a new unlabelled block, which was then reported as never closed -- so a
    # perfectly ordinary document containing one `python` example failed the
    # gate. This README has no shell blocks at all, which is a different failure
    # and its own case.
    Case(
        "a README with only a non-shell block is a failure",
        "# Synthetic\n\n```python\nprint(1)\n```\n\nAfterwards.\n",
        2,
        expect="no ```bash blocks found",
    ),
    Case(
        "a non-shell block does not poison the shell block after it",
        readme("toxindb --version"),
        0,
    ),
    # A non-shell block left open is a failure too, and it is the other half of
    # the defect above. Its error line was reported as `0` for a while, because
    # the report reused the shell-block's start offset -- and an error naming
    # line 0 is worse than no error, since it points nowhere. This one lives
    # away from line 1 so that a regression to `start` would be visible.
    Case(
        "an unterminated non-shell fence is a failure, at the right line",
        "# Synthetic\n\nProse.\n\n```python\nprint(1)\n",
        1,
        expect="::error::5: non-shell code fence opened here is never closed",
    ),
    # Tilde fences are CommonMark-valid and must be honoured, or a documented
    # `~~~bash` block would go unchecked with no error.
    Case(
        "a tilde-fenced bash block is executed",
        "# Synthetic\n\n~~~bash\ntoxindb nosuchsubcommand\n~~~\n",
        1,
        expect=f"FAIL  README.md:{COMMAND_LINE}",
    ),
    Case(
        "a tilde-fenced non-shell block is consumed, not read as unlabelled",
        "# Synthetic\n\n~~~python\nprint(1)\n~~~\n\n```bash\ntoxindb --version\n```\n",
        0,
    ),
]

# --------------------------------------------------------------------------
# MUST PASS -- a gate that rejects everything is not a gate.
# --------------------------------------------------------------------------

MUST_PASS = [
    Case(
        "a README whose only command runs",
        readme("toxindb --version"),
        0,
    ),
    # A refused command next to a good one is not itself a failure: refusing it
    # loudly *is* the correct behaviour, and the job still has a real result to
    # report. This is the case that would fail if "refuse" were ever turned into
    # "fail" -- which would make the gate reject a README for having a
    # `$(...)` in it rather than for anything being wrong with toxindb.
    Case(
        "a passing command alongside a refused one still passes",
        readme("toxindb demo $(touch {marker})\n"
               "toxindb --version"),
        0,
        expect="command substitution",
        marker="alongside",
    ),
    Case(
        "a quoted metacharacter is a plain argument, not shell syntax",
        readme("toxindb monitor 'examples/traces/poison_trace.jsonl'"),
        0,
    ),
]

# The substitution cases must not have produced their side effect. The marker
# is named in a temporary directory beside the synthetic README, because the
# gate runs documented commands inside a scratch directory that it deletes
# before returning -- see NO_SIDE_EFFECT above.


def run_gate(markdown: str, workdir: Path) -> tuple[int, str]:
    """Run the gate under test against `markdown`, with `workdir` as its CWD."""
    readme_path = workdir / "README.md"
    readme_path.write_text(markdown, encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(CHECK), "--readme", str(readme_path)],
        cwd=workdir,
        capture_output=True,
        text=True,
        timeout=900,
    )
    return proc.returncode, proc.stdout + proc.stderr


def _temp_leftovers(root: Path) -> list[str]:
    return [str(p.relative_to(root)) for p in root.rglob(NO_SIDE_EFFECT)]


def run_case(case: Case) -> str | None:
    """Run one case; return a problem string, or None if it behaved."""
    with tempfile.TemporaryDirectory(prefix="docs-teeth-") as tmp:
        workdir = Path(tmp)
        marker = workdir / NO_SIDE_EFFECT
        if case.marker and "{marker}" not in case.markdown:
            return "the case declared a marker but its README does not use one"
        markdown = (
            case.markdown.replace("{marker}", str(marker))
            if case.marker
            else case.markdown
        )
        rc, output = run_gate(markdown, workdir)
        problems: list[str] = []
        if "Traceback (most recent call last)" in output:
            # Rule 1. A crash must never be allowed to score as a detection.
            problems.append("the gate crashed instead of reaching a verdict")
        elif not any(marker_text in output for marker_text in VERDICT_MARKERS):
            problems.append("the gate produced no recognisable verdict")
        if rc != case.expect_rc:
            problems.append(f"expected exit {case.expect_rc}, got {rc}")
        if case.expect and case.expect not in output:
            problems.append(f"expected {case.expect!r} in the output")
        # The marker lives beside the synthetic README, not inside the gate's
        # own scratch directory, so if a substitution ran, the file is still here.
        leftovers = [str(p.relative_to(workdir)) for p in workdir.rglob(NO_SIDE_EFFECT)]
        if leftovers:
            problems.append(
                f"command substitution ran anyway and created {leftovers}"
            )
        return "; ".join(problems) or None


def main() -> int:
    if not CHECK.is_file():
        print(f"error: {CHECK} not found", file=sys.stderr)
        return 2

    # No preflight check on how toxindb was installed. An earlier version
    # printed a note when an environment variable was unset, which read as
    # though the variable controlled something; it controlled nothing. The
    # situation is covered without one: the gate under test refuses to run
    # against an editable install of the checkout and exits 2, so every case
    # that expects 1 or 0 fails with "expected exit N, got 2" and names the
    # configuration. That is a louder and more accurate outcome than a note.

    problems: list[str] = []
    total = 0

    for heading, cases in (
        ("MUST FAIL (documented commands)", MUST_FAIL),
        ("MUST FAIL (document structure)", STRUCTURAL),
        ("MUST PASS (the gate must accept a good README)", MUST_PASS),
    ):
        print(f"\n{heading}:")
        for case in cases:
            total += 1
            problem = run_case(case)
            if problem is None:
                print(f"  ok     {case.title}")
            else:
                problems.append(f"{case.title}: {problem}")
                print(f"  WRONG  {case.title} -> {problem}")

    print()
    if problems:
        print(
            f"::error::the docs gate is not trustworthy ({len(problems)} problem(s)):"
        )
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print(
        f"The docs gate rejected {len(MUST_FAIL) + len(STRUCTURAL)} injected "
        f"document defects, accepted {len(MUST_PASS)} good README(s), executed "
        f"no command substitution, and did not confuse a crash with a verdict."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
