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
* the runnable-command patterns were anchored at the start of the string, so
  ``env toxindb ...``, ``nohup toxindb ...``, ``timeout 5 toxindb ...`` and
  ``FOO=bar toxindb ...`` were all reported as "not a toxindb command" and
  skipped. The job exited 0 with two nonexistent subcommands unverified.

Each of those is a MUST_FAIL case here. One claim about them was wrong, and the
correction matters more than the fix did.

This docstring used to say each case was a *regression* test, and that "a future
change that reintroduces ``shell=True`` turns the substitution case green again
in exactly the way it was before." It does not. Verified: restoring
``shell=True`` with a joined string leaves every case green but one. All of the
rest is carried by ``shell_syntax_reason``, which refuses the metacharacter
before ``subprocess.run`` is ever reached; deleting only that guard turns seven
cases red while ``shell=False`` itself is asserted by nothing. A docstring that
tells a reviewer a hole is closed when no test covers it is worse than the hole,
because the reader stops looking.

So ``shell=False`` now has its own case, and it works by finding the one shape
the syntax guard cannot cover. The guard sees the raw command text, where a
*quoted* metacharacter is an ordinary argument; ``shlex`` then strips the quotes
and the argv vector holds a bare ``&``. A shell would treat that as an operator.
``toxindb monitor '&'`` exits 1 with argv execution and 0 with
``shell=True`` plus a joined string, because the second backgrounds the command
and reports the shell's status -- the original defect, one token further along.

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


class MutationFailed(Exception):
    """The setup for a check could not be built, so the check cannot run.

    Deliberately its own type rather than an `AssertionError`. A check that
    cannot run and a check that failed look the same in the output, and only one
    of them means the gate is broken; `main` reports the two differently.
    """

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

# Line numbers for the multi-block documents below, and the gate's own
# `f"{line_no:<5}"` padding reproduced literally -- `README.md:14` is followed by
# four spaces, `README.md:8` by five. Spelled out rather than computed, because a
# computed expectation that is wrong moves with the document and can never be
# wrong in an obvious way. Both were counted by hand from the markdown in the
# case and then confirmed against the gate's output, which is how the padding was
# found: three of these cases failed on it the first time.
#
# The hidden-block document, numbered:
#     1 # Synthetic   2 (blank)   3 Prose.   4 (blank)   5 ```bash
#     6 toxindb --version          7 ```      8 (blank)  9 (blank)
#    10 ```python  11 x = 1  12 (blank)     13 ```bash
#    14 toxindb nosuchsubcommand   15 ```
HIDDEN_FENCE_LINE = 10        # the ```python that is never closed
HIDDEN_COMMAND_LINE = 14       # the command it was hiding
QUOTED_COMMAND_LINE = 8        # the first command inside `> ```bash`

# An absolute path outside the gate's own scratch directory, used to detect
# whether a documented command substitution actually ran.
#
# The first version of this check used a bare relative filename, and it could
# never fire. The gate runs documented commands in a `TemporaryDirectory` that
# it removes before returning, so any file a substitution created was deleted
# before the check looked for it -- an assertion that was incapable of failing
# and therefore proved nothing.
#
# The marker is at an absolute path in the *teeth* script's own directory rather
# than in the gate's, so a substitution that runs leaves evidence behind. It is a
# belt-and-braces check on top of the syntax guard, and the two layers were
# verified independently rather than assumed:
#
#   * removing the substitution rules from `_SHELL_SYNTAX` *and* restoring
#     `shell=True` with a joined argv makes the marker fire, and the suite goes
#     red naming the file it created;
#   * restoring `shell=True` alone does NOT fire it, because `shell_syntax_reason`
#     still refuses the line before `subprocess.run` is reached. The previous
#     version of this comment credited the marker with catching the
#     shell-regression alone, which is not what happens.
#
# So it is a real assertion -- `run_case` fails the case if the file exists
# afterwards -- but it is reachable only when *both* layers are gone.
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
    # The ONLY case that pins `shell=False`. Every other metacharacter case is
    # carried by the syntax guard, so with `shell=True` restored they all stay
    # green -- which is what the module docstring used to (wrongly) claim they
    # would catch. This one cannot be carried by the guard: `&` is quoted, so the
    # guard sees an ordinary argument, and it is `shlex` that then strips the
    # quotes and leaves a bare `&` in the argv vector. A shell reintroduced at
    # the subprocess call reads that as the background operator, backgrounds the
    # command, and reports 0 -- so the gate prints PASS for a documented command
    # that never ran. Verified in both directions: rc=1 with argv execution,
    # rc=0 with `shell=True` and `" ".join(argv)`.
    Case(
        "a quoted operator is an argument, and argv execution says so",
        readme("toxindb monitor '&'"),
        1,
        expect=f"FAIL  README.md:{COMMAND_LINE}",
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
    # An unterminated non-shell fence used to swallow every ```bash block after
    # it, because the `bash` line was accepted as its closer. Nothing was
    # printed, nothing was skipped, and the job was green with a documented
    # `nosuchsubcommand` unverified -- the exact shape of hole this script
    # exists to close. Two assertions, because the two halves fail separately:
    # the structural error names the *python* fence, and the command inside the
    # block the python fence was hiding is actually run and reported.
    Case(
        "an unterminated non-shell fence does not hide a later bash block",
        "# Synthetic\n\nProse.\n\n```bash\ntoxindb --version\n```\n\n\n"
        "```python\nx = 1\n\n```bash\ntoxindb nosuchsubcommand\n```\n",
        1,
        expect=f"FAIL  README.md:{HIDDEN_COMMAND_LINE}    toxindb nosuchsubcommand",
    ),
    Case(
        "that hidden block is also reported as an unclosed fence",
        "# Synthetic\n\nProse.\n\n```bash\ntoxindb --version\n```\n\n\n"
        "```python\nx = 1\n\n```bash\ntoxindb nosuchsubcommand\n```\n",
        1,
        expect=(
            f"::error::{HIDDEN_FENCE_LINE}: non-shell code fence "
            f"opened here is never closed"
        ),
    ),
    # `||` runs its right-hand side precisely because the left-hand side failed,
    # so the line succeeds. Treating it as `&&` reported a correct documented
    # command as broken, which is how a maintainer learns to ignore a red job.
    Case(
        "a || chain succeeds when the second command succeeds",
        readme("toxindb nosuchsubcommand || toxindb --version"),
        0,
        expect=f"PASS  README.md:{COMMAND_LINE}",
    ),
    Case(
        "a || chain fails when both commands fail",
        readme("toxindb nosuchsubcommand || toxindb alsonosuchsubcommand"),
        1,
        expect=f"FAIL  README.md:{COMMAND_LINE}",
    ),
    Case(
        "a && chain still stops at the first failure",
        readme("toxindb nosuchsubcommand && toxindb --version"),
        1,
        expect=f"FAIL  README.md:{COMMAND_LINE}",
    ),
    # A fenced block inside a block quote is a block a reader will copy. The
    # fence pattern was anchored at column 0, so `> ```bash` never matched and
    # the block was invisible -- with no skip reason, and with the
    # "no documented command was executed" floor satisfied by whatever other
    # block the document had.
    Case(
        "a block-quoted bash fence is executed",
        "# Synthetic\n\n```bash\ntoxindb --version\n```\n\n"
        "> ```bash\n> toxindb nosuchsubcommand\n> ```\n",
        1,
        expect=f"FAIL  README.md:{QUOTED_COMMAND_LINE}     toxindb nosuchsubcommand",
    ),
    # The mirror image: an *unquoted* `#` inside a filename is a legal token in a
    # shell too, and refusing it silently cost a real command its check.
    Case(
        "a hash inside a filename is not a comment",
        readme("toxindb monitor 'examples/traces/poison_trace.jsonl' --output r#1/"),
        0,
        expect=f"PASS  README.md:{COMMAND_LINE}",
    ),
    # A closing fence must be at least as long as the opener. Comparing only the
    # fence *character* let a 3-backtick line close a 4-backtick ```bash block,
    # so everything after it was read as document text -- no skip reason, no
    # structural error, exit 0, and a documented `nosuchsubcommand` never run.
    # Counted by hand from the markdown: 1 `# T`, 2 blank, 3 ````bash opener,
    # 4 the good command, 5 the short closer, 6 the hidden bad command.
    Case(
        "a short closer does not close a longer opener",
        "# Synthetic\n\n````bash\ntoxindb --version\n```\n"
        "toxindb nosuchsubcommand\n`````\n",
        1,
        expect=f"FAIL  README.md:6     toxindb nosuchsubcommand",
    ),
    # The other half, and the reason it needed two cases: with no real closer at
    # all the block *looked* closed, so no unclosed-fence error was printed
    # either. A structure the parser rejects should say so, not just fail.
    Case(
        "a short closer is also reported as an unclosed fence",
        "# Synthetic\n\n````bash\ntoxindb --version\n```\n",
        1,
        expect="::error::3: code fence opened here is never closed",
    ),
    # The control, so the fix is not simply "always require four backticks": a
    # longer closer than the opener is legal and must still close the block.
    Case(
        "a longer closer than the opener still closes it",
        "# Synthetic\n\n```bash\ntoxindb --version\n`````\n",
        0,
        expect=f"PASS  README.md:4     toxindb --version",
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


# --------------------------------------------------------------------------
# The working-tree safety net
# --------------------------------------------------------------------------
#
# `_tree_state` is the only evidence that running the documented commands did
# not rewrite the repository's own fixtures, and nothing above exercises it:
# `run_case` hands the gate a scratch directory with no `.git`, so the
# assertion is legitimately skipped in all 29 cases. Neutralising the function
# entirely left this script green, which is how a docstring came to claim a
# verification nobody had run.
#
# Called directly against real checkouts rather than through `run_gate`, because
# the property is about `git status` and about which failures are silent -- and
# a scratch directory cannot express either.

_GATE: object | None = None


def _gate() -> object:
    """Import check_docs_commands.py so its internals can be called directly."""
    global _GATE
    if _GATE is None:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "docs_gate_under_test", HERE / "check_docs_commands.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _GATE = module
    return _GATE


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise MutationFailed(f"`git` is not on PATH ({exc}); this check cannot run") from exc


def check_tree_state() -> list[str]:
    """Prove `_tree_state` reports a change, and stays quiet about a non-checkout.

    Five properties. The two that matter most are the first and the third: a
    gate that cannot see a write, and a gate that reports one it cannot see.
    """
    problems: list[str] = []
    gate = _gate()
    results: list[tuple[str, bool, str]] = []

    with tempfile.TemporaryDirectory(prefix="docs-tree-") as tmp:
        outside = Path(tmp)
        checkout = outside / "checkout"
        checkout.mkdir()
        init = _git(["git", "init", "-q"], checkout)
        if init.returncode != 0:
            raise MutationFailed(f"`git init` failed: {init.stderr.strip()}")

        before = gate._tree_state(checkout)
        # A file git already tracks, plus a new untracked one: both must show.
        (checkout / "TREE_PROBE.txt").write_text("x", encoding="utf-8")
        after_new_file = gate._tree_state(checkout)
        same = gate._tree_state(checkout)
        (checkout / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
        (checkout / "ignored.txt").write_text("secret", encoding="utf-8")
        after_ignored = gate._tree_state(checkout)

        results.append(("a new untracked file changes the snapshot",
                        before != after_new_file, "expected a difference"))
        results.append(("an unchanged tree yields an identical snapshot",
                        after_new_file == same, "expected no difference"))
        results.append(("a file inside an ignored directory is still listed",
                        after_ignored != same, "expected a difference"))

        # Not a checkout: skipped with a note, never silently assumed to have
        # passed. `_tree_state` returns None for this and for nothing else.
        plain = outside / "plain"
        plain.mkdir()
        results.append(("a directory with no .git anywhere is skipped",
                        gate._tree_state(plain) is None, "expected None"))

        # Git present, in a real checkout, and failing. This used to be reported
        # as the "not a git checkout" skip, which is the opposite of the truth
        # and left the only tree assertion in the gate switched off.
        corrupt = outside / "corrupt"
        corrupt.mkdir()
        _git(["git", "init", "-q"], corrupt)
        (corrupt / ".git" / "index").write_bytes(b"DIRC\0\0\0\0garbage")
        try:
            gate._tree_state(corrupt)
            refused = False
        except gate.GitRefused:
            refused = True
        except Exception as exc:  # noqa: BLE001 - wrong exception type is a failure
            problems.append(
                f"a corrupt index raised {type(exc).__name__} rather than "
                f"GitRefused: the error type is what main() dispatches on"
            )
            refused = True
        results.append(("a corrupt index in a checkout is refused, not skipped",
                        refused, "expected GitRefused"))

    for label, ok, why in results:
        if not ok:
            problems.append(f"{label}: {why}")
        print(f"  {'ok' if ok else 'WRONG':>5}  {label}")
    return problems


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

    print(
        "\nWorking-tree assertion -- called directly, because `run_case` hands "
        "the gate a scratch directory with no `.git`, so all "
        f"{total} cases above run with this assertion legitimately skipped:"
    )
    try:
        problems.extend(check_tree_state())
    except MutationFailed as exc:
        problems.append(f"the working-tree assertion could not be checked: {exc}")

    print()
    if problems:
        print(
            f"::error::the docs gate is not trustworthy ({len(problems)} problem(s)):"
        )
        for problem in problems:
            print(f"  - {problem}")
        return 1
    # Counted, not assumed. The previous version printed
    # `len(MUST_FAIL) + len(STRUCTURAL)` under the words "rejected", which
    # overstated the result by 17%: four of the STRUCTURAL cases expect exit 0,
    # because the gate is *supposed* to accept those documents. They are real
    # cases and worth running -- a rule that rejects a well-formed document is
    # just as broken as one that misses a defect -- but calling them "rejected"
    # claims evidence that does not exist, in the one line a reader is most
    # likely to quote when auditing what this gate proved.
    rejected = sum(1 for case in (*MUST_FAIL, *STRUCTURAL) if case.expect_rc != 0)
    accepted_defects = len(MUST_FAIL) + len(STRUCTURAL) - rejected
    print(
        f"The docs gate rejected {rejected} injected document defects, "
        f"correctly accepted {accepted_defects} well-formed document(s) it must "
        f"not reject, accepted {len(MUST_PASS)} good README(s), executed no "
        f"command substitution, saw a real tree change and refused a broken git "
        f"instead of skipping on it, and did not confuse a crash with a verdict."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
