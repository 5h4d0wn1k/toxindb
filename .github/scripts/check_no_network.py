#!/usr/bin/env python3
"""Fail if the core imports anything that can open a network connection.

Why this exists
---------------
toxindb promises "zero network calls" in README.md and SCOPE.md. Nothing else in
the repository tests that promise: the test suite exercises the Python API and
the CLI in-process with no socket in the way, so a new dependency on the network
would not fail a single test. It would fail a user, silently, at the moment they
ran the tool on a trace that mattered.

This script is the one place the promise is checked rather than trusted.

Why it parses instead of grepping
---------------------------------
The first version of this check was a `grep -E`:

    grep -rnE '^\\s*(import|from)\\s+(socket|ssl|http|urllib|requests|...)\\b'

That is wrong in a way a reviewer has to be shown, because it *does* report
something for most inputs. It requires the network module to be the first name
in the statement, and grep has no multiline mode, so three ordinary spellings
slipped straight past it:

    import os, socket              # second name on the line
    import json, urllib.request   # second name, and a submodule
    from helper import (           # parenthesised, name is three lines down
        socket,
    )

All three were verified to produce no output and exit 0 -- a green check over a
module that imports `socket`. Parsing with `ast` collects every alias of every
`import` and `from` node regardless of formatting, so the shape of the source
stops mattering.

What it does not do
-------------------
It reads `import` statements. It does not follow them: `__import__("socket")`,
`importlib.import_module("socket")`, `os.system("curl ...")`,
`subprocess.run(["curl", ...])` and a base64-encoded payload all pass. That is a
real limit and worth stating, because this gate is the only thing backing the
offline promise. Catching those needs a different tool -- an import hook or a
sandbox with no network namespace -- not a bigger regex, and the honest move is
to say so rather than let a passing run imply more than it checked. A reader who
knows this project's code should also know that adding a network client is a
deletion-worthy change, because it will not be caught here.

`NETWORK_MODULES` is likewise a floor and not a ceiling; see
`REQUIRED_NETWORK_MODULES` for the part of it that is enforced.

Usage
-----
    python .github/scripts/check_no_network.py toxindb

Every run first checks the scanner against synthetic trees it builds itself --
several that must be rejected, several that must be accepted -- and then scans
the real tree. A gate whose own detector is never watched to reject anything is
the failure this repository has already made twice, so the teeth test lives in
the same file as the gate and runs in the same CI step. It is not a separate
script because a separate script is one more thing that can quietly stop running.

There is no flag to turn it off, and that is deliberate. An earlier version took
``--self-test`` and then ran the self-test unconditionally, so the flag did
nothing while its help text described it as "(default: on)" -- a reader would
reasonably conclude that omitting it skipped the check. A gate cannot defend
itself with a switch nobody needs, so the switch is gone.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

# Modules that can open a network connection, or that can be made to.
#
# `http` and `urllib` are packages rather than leaf modules, so importing
# `http.client` names `http` at the top level; that is what this set matches on.
# `asyncio` is here because `asyncio.open_connection` and the `*-connector`
# helpers reach a socket, even though the name alone promises nothing.
# Modules that can open a network connection, or that can be made to.
#
# `http` and `urllib` are packages rather than leaf modules, so importing
# `http.client` names `http` at the top level; that is what this set matches on.
# `asyncio` is here because `asyncio.open_connection` and the `*-connector`
# helpers reach a socket, even though the name alone promises nothing.
NETWORK_MODULES = frozenset(
    {
        "aiohttp",
        "asyncio",
        "boto3",
        "botocore",
        "ftplib",
        "grpc",
        "http",
        "httpx",
        "imaplib",
        "nntplib",
        "paramiko",
        "poplib",
        "requests",
        "smtplib",
        "socket",
        "socks",
        "ssl",
        "telnetlib",
        "urllib",
        "urllib3",
        "websockets",
        "xmlrpc",
    }
)

# The subset of `NETWORK_MODULES` that a well-known client library must be in.
#
# This exists because the previous list was never checked against anything. It
# omitted `httpx`, `aiohttp`, `paramiko` and `boto3` -- and `ci.yml` justifies
# this script as "the one place that promise could silently be broken by a
# *future dependency*". Those four are what a future dependency looks like, so
# the check missed exactly the case it was added for. Verified: with the old
# list, `import httpx`, `from aiohttp import ClientSession` and `import
# paramiko` all passed; only `import socket` was caught.
#
# An allowlist cannot be proven complete against an unbounded set of
# third-party packages. What *can* be enforced is that the packages this
# project would plausibly reach for are in it, and that nothing is added
# wrongly -- `SELF_TEST_CASES` covers the second direction, since every one of
# those must still be accepted. Stated as a floor, not a ceiling.
REQUIRED_NETWORK_MODULES = (
    "aiohttp",
    "boto3",
    "http",
    "httpx",
    "paramiko",
    "requests",
    "socket",
    "ssl",
    "urllib",
)


def offending_imports(source: str, filename: str) -> list[tuple[int, str]]:
    """Every network-capable import in `source`, as ``(line, name)``.

    Returns an empty list if the file does not parse. A file that does not
    compile cannot be imported either, so it is the test suite's problem to
    report, not this check's to guess at.
    """
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError:
        return []

    found: list[tuple[int, str]] = []

    def record(node: ast.AST, name: str) -> None:
        top = name.split(".", 1)[0]
        if top in NETWORK_MODULES:
            found.append((getattr(node, "lineno", 0), name))

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            # Every alias, not just the first: `import os, socket` is the
            # spelling the grep missed.
            for alias in node.names:
                record(node, alias.name)
        elif isinstance(node, ast.ImportFrom):
            # `level > 0` is a relative import, so `module` is a package-local
            # name that cannot be `socket` or `urllib`. Recorded anyway, because
            # a relative import of a name that shadows nothing is still not
            # something this check should have to reason about.
            if node.module:
                record(node, node.module)
            for alias in node.names:
                record(node, alias.name)
    return found


def scan(root: Path) -> list[tuple[Path, int, str]]:
    """Scan every `.py` file under `root`, returning the offending imports."""
    found: list[tuple[Path, int, str]] = []
    for path in sorted(root.rglob("*.py")):
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            found.append((path, 0, f"could not be read: {exc}"))
            continue
        for line, name in offending_imports(source, str(path)):
            found.append((path, line, name))
    return found


# Trees the self-test builds. Each is `(filename, source, expect_offender)`.
# A case with no expectation is the control: a scanner that rejects everything
# passes every "must fail" case and is caught here.
SELF_TEST_CASES: tuple[tuple[str, str, bool], ...] = (
    ("clean.py", "import ast\nimport os\nfrom pathlib import Path\n", False),
    # The three shapes the grep missed.
    ("comma_import.py", "import os, socket\n", True),
    ("comma_submodule.py", "import json, urllib.request\n", True),
    ("parenthesised.py", "from helper import (\n    ssl,\n)\n", True),
    # Shapes the grep did catch, kept so the rewrite cannot regress them.
    ("plain.py", "import socket\n", True),
    ("from_import.py", "from socket import socket\n", True),
    ("aliased.py", "import socket as s\n", True),
    ("dotted.py", "import urllib.parse\n", True),
    # Not a network module, however it is spelled.
    # The four real client libraries the previous list omitted. The CI comment
    # calls this script "the one place that promise could silently be broken by
    # a future dependency", and these are what a future dependency looks like.
    ("httpx_client.py", "import httpx\n", True),
    ("aiohttp_client.py", "from aiohttp import ClientSession\n", True),
    ("paramiko_ssh.py", "import paramiko\n", True),
    ("boto3_client.py", "import boto3\n", True),
    # Lookalikes, which must stay accepted or the list grows by accident.
    ("lookalike.py", "import socket_helpers\nfrom sockets import bind\n", False),
    ("comment.py", "# import socket\n'''import ssl'''\n", False),
    ("string.py", 'PATH = "socket/host.py"\n', False),
)


def missing_required_modules() -> list[str]:
    """Well-known network clients absent from `NETWORK_MODULES`.

    This is the one direction a tree of synthetic files cannot check, because
    every file it builds is written by this file -- widening the list wrongly is
    caught, but narrowing it is invisible unless the reader already knows which
    names matter. The names below are checked against the list directly instead.
    """
    return [name for name in REQUIRED_NETWORK_MODULES if name not in NETWORK_MODULES]


def self_test() -> int:
    """Prove the scanner both accepts and rejects, before scanning for real.

    Runs against synthetic trees rather than a copy of `toxindb/`, so a
    *legitimate* network import added to the core would show up as a real
    finding instead of quietly becoming the accepted baseline.
    """
    import tempfile

    problems: list[str] = []
    for name in missing_required_modules():
        problems.append(
            f"NETWORK_MODULES no longer contains {name!r}, a well-known "
            f"network client. Dropping a name is the silent direction: no "
            f"synthetic file in this self-test would ever import it."
        )
    with tempfile.TemporaryDirectory(prefix="toxindb-net-") as scratch:
        root = Path(scratch)
        for filename, source, _ in SELF_TEST_CASES:
            (root / filename).write_text(source, encoding="utf-8")
        offenders = scan(root)
        offending_files = {path.name for path, _, _ in offenders}

        for filename, _, expected in SELF_TEST_CASES:
            hit = filename in offending_files
            if hit != expected:
                problems.append(
                    f"{filename}: expected "
                    f"{'an offender' if expected else 'no offender'}, got "
                    f"{'one' if hit else 'none'}"
                )
        # Catches an offender in a file no case claims, which the per-file loop
        # above cannot see. Counted in *files*, not imports: one case imports
        # both `urllib` and `urllib.request` from a single line, and this check
        # first compared the two counts and failed on the difference -- which is
        # the self-test working, on the author.
        expected_files = {f for f, _, e in SELF_TEST_CASES if e}
        if offending_files != expected_files:
            problems.append(
                f"offending files {sorted(offending_files)} != expected "
                f"{sorted(expected_files)}"
            )

    if problems:
        print("::error::the no-network scanner does not work", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    rejected = sum(1 for _, _, expected in SELF_TEST_CASES if expected)
    print(
        f"the no-network scanner rejected {rejected} of {len(SELF_TEST_CASES)} "
        f"synthetic cases and accepted the other "
        f"{len(SELF_TEST_CASES) - rejected}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "root",
        type=Path,
        nargs="?",
        help="directory to scan (a package directory, not its parent)",
    )
    args = parser.parse_args()

    # The self-test runs unconditionally, before the root is even validated:
    # it is evidence that this script works, not an option for this
    # invocation. See the module docstring on why there is no flag for it.
    if self_test() != 0:
        return 1

    if args.root is None:
        parser.error("a directory to scan is required")
    if not args.root.is_dir():
        print(f"error: {args.root} is not a directory", file=sys.stderr)
        return 2

    offenders = scan(args.root)
    if offenders:
        print(
            f"::error::{args.root} imports {len(offenders)} network-capable "
            f"name(s). The core is documented as stdlib-only and fully offline.",
            file=sys.stderr,
        )
        for path, line, name in offenders:
            print(f"  - {path}:{line}: {name}", file=sys.stderr)
        return 1

    files = sum(1 for _ in args.root.rglob("*.py"))
    print(f"no network imports in {args.root} ({files} file(s) parsed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())