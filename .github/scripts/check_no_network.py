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

Usage
-----
    python .github/scripts/check_no_network.py toxindb
    python .github/scripts/check_no_network.py --self-test toxindb

`--self-test` runs the scanner over synthetic trees it builds itself -- one
clean, several of which must be rejected -- and then scans the real tree. A gate
whose own detector is never watched to reject anything is the failure this
repository has already made twice, so the teeth test lives in the same file as
the gate and runs in the same CI step. It is not a separate script because a
separate script is one more thing that can quietly stop running.
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
NETWORK_MODULES = frozenset(
    {
        "asyncio",
        "ftplib",
        "http",
        "imaplib",
        "nntplib",
        "poplib",
        "requests",
        "smtplib",
        "socket",
        "ssl",
        "telnetlib",
        "urllib",
        "urllib3",
        "websockets",
        "xmlrpc",
    }
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
    ("lookalike.py", "import socket_helpers\nfrom sockets import bind\n", False),
    ("comment.py", "# import socket\n'''import ssl'''\n", False),
    ("string.py", 'PATH = "socket/host.py"\n', False),
)


def self_test() -> int:
    """Prove the scanner both accepts and rejects, before scanning for real.

    Runs against synthetic trees rather than a copy of `toxindb/`, so a
    *legitimate* network import added to the core would show up as a real
    finding instead of quietly becoming the accepted baseline.
    """
    import tempfile

    problems: list[str] = []
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
        help="directory to scan (a package directory, not its parent)",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="prove the scanner can reject before scanning (default: on)",
    )
    args = parser.parse_args()

    if not args.root.is_dir():
        print(f"error: {args.root} is not a directory", file=sys.stderr)
        return 2

    if self_test() != 0:
        return 1

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