"""Tests for the CLI module."""
import json
import os
import sys
import tempfile

import pytest

from toxindb.cli import main, _build_parser
from toxindb.engine import Engine
from toxindb.trace import QueryEvent, Trace
from toxindb.trace_gen import generate_clean_trace, generate_poison_trace, trace_to_jsonl


def _make_trace_file(trace, suffix=".jsonl"):
    f = tempfile.NamedTemporaryFile(suffix=suffix, delete=False, mode="w")
    trace_to_jsonl(trace, f.name)
    f.close()
    return f.name


def test_cli_help():
    try:
        main(["--help"])
    except SystemExit as e:
        assert e.code == 0


def test_cli_version():
    try:
        main(["--version"])
    except SystemExit as e:
        assert e.code == 0


def test_cli_demo(tmp_path):
    rc = main(["demo", "--output", str(tmp_path)])
    assert rc == 0
    assert (tmp_path / "demo_summary.json").exists()


def test_cli_demo_global_includes_demo_subcommand():
    assert "--demo" in _build_parser().format_help()


def test_cli_demo_global_flag(tmp_path):
    rc = main(["--demo", "--output", str(tmp_path)])
    assert rc == 0
    assert (tmp_path / "demo_summary.json").exists()


def test_cli_monitor(tmp_path):
    path = _make_trace_file(generate_clean_trace())
    alerts_dir = tmp_path / "alerts"
    alerts_dir.mkdir()
    rc = main(["monitor", path, "--output", str(alerts_dir)])
    assert rc == 0
    assert (alerts_dir / "alerts.jsonl").exists()
    os.unlink(path)


def test_cli_canary(tmp_path):
    path = _make_trace_file(generate_clean_trace())
    rc = main(["canary", path, "--monitor", "--output", str(tmp_path)])
    assert rc == 0
    assert (tmp_path / "canary_report.json").exists()
    os.unlink(path)


def test_cli_canary_plant(tmp_path):
    path = _make_trace_file(generate_clean_trace())
    rc = main(["canary", path, "--plant", "--output", str(tmp_path)])
    assert rc == 0
    os.unlink(path)


# --- `canary --plant` must never write over its own input -----------------
#
# The output path used to be derived with `trace_path.replace(".jsonl", ...)`.
# `str.replace` takes no occurrence count, so with no `.jsonl` in the path it is
# a no-op, `out_path` silently falls back to the input path, and the command
# appended two canary records to the operator's evidence file, reported the
# input path as the destination, and exited 0. The damage is cumulative: a
# second `--plant` appends two more.
#
# Every test below asserts the input's bytes are unchanged, because a return
# code of 0 is exactly what the broken version produced. The byte assertion
# comes first in each one, because that is the failure that destroys the
# operator's evidence; the exit code is the secondary signal.


def _plant(path, capsys):
    """`canary --plant` with no `--output`.

    `--output` is deliberately absent. `--plant` ignores it -- the trace is
    written beside its input, since the command's whole subject is that input --
    and passing it here would have masked that: `tmp_path` is the input's
    parent, so the tests passed whether or not the flag was honoured. The three
    subcommands that *do* honour it are covered by the tests around them.
    """
    rc = main(["canary", path, "--plant"])
    return rc, capsys.readouterr()


def _planted(tmp_path, source_name):
    """The file `--plant` wrote: the one entry in `tmp_path` that is not the input.

    Derived by looking at the directory rather than by naming the output, so a
    change to the output *filename* cannot make a timestamp test fail for a
    reason that has nothing to do with timestamps. The three filename tests
    above are the ones that pin the name, and they name it deliberately.
    """
    others = [
        p for p in tmp_path.iterdir()
        if p.name != source_name and p.is_file()
    ]
    assert len(others) == 1, f"expected exactly one planted trace, found {others}"
    return others[0]


def _planted_or_none(tmp_path, source_name):
    """As `_planted`, but for tests asserting that *nothing* was written."""
    others = [
        p for p in tmp_path.iterdir()
        if p.name != source_name and p.is_file()
    ]
    return others[0] if len(others) == 1 else None


def test_cli_plant_does_not_overwrite_input_without_jsonl_suffix(tmp_path, capsys):
    path = tmp_path / "ingest_log"
    trace_to_jsonl(generate_clean_trace(), str(path))
    before = path.read_bytes()

    rc, _ = _plant(str(path), capsys)

    assert path.read_bytes() == before, "the input trace was modified in place"
    assert rc == 0


def test_cli_plant_writes_the_output_beside_a_suffixless_input(tmp_path, capsys):
    path = tmp_path / "ingest_log"
    trace_to_jsonl(generate_clean_trace(), str(path))

    rc, captured = _plant(str(path), capsys)

    assert rc == 0
    written = tmp_path / "ingest_log_canary_planted.jsonl"
    assert written.exists(), captured.out
    assert str(written) in captured.out
    # A second plant must not compound on the first.
    assert len(written.read_text().splitlines()) == \
        len(path.read_text().splitlines()) + 2


def test_cli_plant_rewrites_only_the_final_extension(tmp_path, capsys):
    """`a.jsonl.b.jsonl` must not become `a_canary_planted.jsonl.b_canary_planted.jsonl`.

    `str.replace` has no occurrence count and rewrites every occurrence, so the
    middle of the name was mangled too. The suffix is the last one, and only
    the last one.
    """
    path = tmp_path / "a.jsonl.b.jsonl"
    trace_to_jsonl(generate_clean_trace(), str(path))
    before = path.read_bytes()

    rc, captured = _plant(str(path), capsys)

    assert path.read_bytes() == before
    written = tmp_path / "a.jsonl.b_canary_planted.jsonl"
    assert written.exists(), captured.out
    assert rc == 0


def test_cli_plant_refuses_a_directory(tmp_path, capsys):
    """A directory named `traces.jsonl` is a common mount layout.

    The old code crashed with `IsADirectoryError` naming a path the operator
    never asked for. It should refuse, and say why.
    """
    directory = tmp_path / "traces.jsonl"
    directory.mkdir()
    (directory / "trace.jsonl").write_text(
        '{"type": "ingest", "doc_id": "d", "source": "s", "owner": "o", '
        '"namespace": "n", "timestamp": 1.0, "content": "c"}\n',
        encoding="utf-8",
    )

    rc, captured = _plant(str(directory), capsys)

    assert rc == 1
    assert "directory" in captured.err


def test_cli_plant_keeps_the_documented_jsonl_behaviour(tmp_path, capsys):
    """The control.

    Pins the output name for the one input shape the README documents, whose
    destination path is published. A fix that rewrote the name even here --
    always appending, or taking the *first* extension rather than the last --
    would corrupt a path the docs promise. `test_cli_plant_rewrites_only_the_
    final_extension` is what catches an unconditional append; this catches the
    case where the correctly-suffixed path itself changes.
    """
    path = tmp_path / "ok.jsonl"
    trace_to_jsonl(generate_clean_trace(), str(path))
    before = path.read_bytes()

    rc, captured = _plant(str(path), capsys)

    assert rc == 0
    assert path.read_bytes() == before
    assert (tmp_path / "ok_canary_planted.jsonl").exists(), captured.out


# --- `canary --plant` must plant at a time the trace can see ----------------
#
# The plant timestamp was hardcoded to `999999.0` (1970-01-12). Every recency
# window in the tool is measured as `event.timestamp - doc.timestamp`, so on any
# trace with real epoch timestamps the planted document is not merely old, it
# is outside every window by decades: TX-001 counted 0 of the retrieved canary
# docs as recent and so raised nothing. A plant is the documented way to prove
# detection works, and the demand-and-recency detectors could not see it.
#
# TX-004 is not the case here and is not claimed to be: it substring-matches
# canary text in `query.output_text` and does no timestamp arithmetic, so it
# fired on a 1970-stamped plant exactly as it would on any other. The tests
# below therefore assert on TX-001, which is the detector the timestamp
# actually decides.
#
# The bundled fixtures hide the defect: `trace_gen` bases its timestamps near
# 1,000,000.0, so 999999.0 sits plausibly among them. That is a fixture
# artifact, not a design decision, so the tests below use a real epoch.

REAL_EPOCH = 1_750_000_000.0  # 2025-07, a plausible production trace


def _epoch_trace(tmp_path, name="epoch.jsonl", count=40):
    """A trace whose timestamps are real epoch seconds, not 1970 fixtures."""
    path = tmp_path / name
    rows = [
        {
            "type": "ingest", "doc_id": f"d{i}", "source": f"src{i % 7}",
            "owner": f"own{i % 5}", "namespace": f"ns{i % 4}",
            "timestamp": REAL_EPOCH, "content": f"document {i}", "signature": f"sig{i}",
        }
        for i in range(count)
    ]
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


def test_cli_plant_stamps_at_the_trace_not_1970(tmp_path, capsys):
    path = _epoch_trace(tmp_path)
    rc, captured = _plant(str(path), capsys)
    assert rc == 0

    planted = _planted(tmp_path, path.name)
    rows = [json.loads(line) for line in planted.read_text(encoding="utf-8").splitlines()]
    # `ingest` rows carry `timestamp`; the canary record carries `planted_at`.
    ingests = [r["timestamp"] for r in rows if r["type"] == "ingest"]
    claims = [r["planted_at"] for r in rows if r["type"] == "canary"]
    assert claims, "no canary record was written"
    drift = abs(max(ingests) - claims[0])
    assert drift < 1.0, (
        f"the planted canary is stamped {drift:.0f}s away from the trace it "
        f"joins, so every recency window excludes it"
    )


def test_cli_plant_lands_inside_the_default_recency_window(tmp_path, capsys):
    """The behavioural half.

    Timestamp arithmetic is the proxy; this is what the tool actually does with
    the result. A query retrieving the planted doc at the trace's own time must
    count it as recent, or the plant is invisible to TX-001.
    """
    path = _epoch_trace(tmp_path)
    rc, _ = _plant(str(path), capsys)
    assert rc == 0

    planted = _planted(tmp_path, path.name)
    rows = [json.loads(line) for line in planted.read_text(encoding="utf-8").splitlines()]
    canary_doc = [r["doc_id"] for r in rows if r["type"] == "ingest"][-1]

    trace = Trace.from_jsonl(str(planted))
    trace.queries.append(QueryEvent(
        query_id="q1", query_text="find things", timestamp=REAL_EPOCH,
        retrieved_doc_ids=[canary_doc], output_text="unrelated",
    ))
    alerts = Engine().analyze(trace)
    tx001 = [a for a in alerts if a.heuristic_id == "TX-001"]
    assert tx001, (
        "a query retrieving the freshly planted canary produced no TX-001 "
        "alert, so the plant is still invisible to the demand x recency "
        "analysis the tool is built around"
    )


def test_cli_plant_at_override_wins(tmp_path, capsys):
    """The control for the fix.

    A change that simply stamps every plant "now" would pass the two tests
    above while making the plant impossible to place in a trace deliberately.
    An explicit `--at` must still be honoured exactly.
    """
    path = _epoch_trace(tmp_path)
    rc = main([
        "canary", str(path), "--plant", "--at", "1234567890.0",
    ])
    capsys.readouterr()
    assert rc == 0

    planted = _planted(tmp_path, path.name)
    rows = [json.loads(line) for line in planted.read_text(encoding="utf-8").splitlines()]
    claims = [r["planted_at"] for r in rows if r["type"] == "canary"]
    assert 1234567890.0 in claims


# --- `--at` must produce a file a strict JSON reader can read ---------------
#
# `type=float` accepts `nan`, `inf` and `1e400`, and `json.dumps` writes those
# as the bare tokens `NaN` and `Infinity`, which RFC 8259 does not allow.
# Python's own `json.loads` accepts them back, so toxindb round-trips its own
# output and never notices: the exit code is 0 and the planted file is only
# broken for anyone *else* reading it. Verified before the fix -- `--at 1e400`
# wrote `"planted_at": Infinity` and a strict parse raised.
#
# Adding `--at` created the first user-controlled path to a non-finite
# timestamp; the value was the constant `999999.0` before it.


@pytest.mark.parametrize("literal", ["nan", "inf", "-inf", "1e400", "-1e400"])
def test_cli_plant_rejects_a_non_finite_at(tmp_path, capsys, literal):
    path = _epoch_trace(tmp_path)

    # The `=` form, because argparse reads a bare `-inf` as an option and exits
    # 2 with "expected one argument" -- which would make this test pass for the
    # wrong reason on every negative literal.
    rc = main(["canary", str(path), "--plant", f"--at={literal}"])
    captured = capsys.readouterr()

    assert rc == 1
    assert "finite" in captured.err
    assert _planted_or_none(tmp_path, path.name) is None, (
        "a trace was written for a timestamp the command had just refused"
    )


@pytest.mark.parametrize("literal", ["1750000000.0", "0", "-1", "1e308"])
def test_cli_plant_accepts_a_finite_at(tmp_path, capsys, literal):
    """The other direction, so the guard is not simply refusing everything.

    `--at` is how an operator places a plant deliberately, and the fix must not
    narrow it to "some floats". `1e308` is finite and is about 5.8 billion
    years, so it is absurd as a timestamp and still legal JSON -- which is the
    distinction the guard is drawing: the *format*, not a range opinion.
    """
    path = _epoch_trace(tmp_path)

    rc = main(["canary", str(path), "--plant", f"--at={literal}"])
    capsys.readouterr()

    assert rc == 0
    planted = _planted(tmp_path, path.name)
    rows = [json.loads(line) for line in planted.read_text(encoding="utf-8").splitlines()]
    claims = [r["planted_at"] for r in rows if r["type"] == "canary"]
    assert float(literal) in claims


def test_cli_planted_trace_is_strict_json(tmp_path, capsys):
    """The property, checked on the file itself rather than via the CLI.

    `json.loads` is lenient by default, so a lenient reader cannot detect this
    class of defect -- which is exactly why it survived the fix's own testing.
    `parse_constant` fires only for `NaN`/`Infinity`/`-Infinity`, so this
    accepts every legal JSON number and rejects exactly the three illegal
    tokens.
    """
    path = _epoch_trace(tmp_path)
    rc, _ = _plant(str(path), capsys)
    assert rc == 0

    planted = _planted(tmp_path, path.name)

    def reject(token):
        raise AssertionError(f"planted trace contains the non-RFC-8259 token {token!r}")

    for line in planted.read_text(encoding="utf-8").splitlines():
        json.loads(line, parse_constant=reject)


# --- `--plant` must not clobber the input through a link -------------------
#
# The guard compared `os.path.abspath` *strings*. Those differ when the output
# path already exists as a symlink or hardlink to the input, so the guard passed
# and `open(out, "w")` overwrote the input with exit 0 -- the same data loss
# the guard was written to stop, reachable whenever something else in the
# workspace happens to be named as the output. Verified before the fix: a
# symlink named `ev_canary_planted.jsonl` pointing at `ev.jsonl`.


def test_cli_plant_refuses_to_overwrite_a_symlinked_output(tmp_path, capsys):
    source = tmp_path / "evidence.jsonl"
    trace_to_jsonl(generate_clean_trace(), str(source))
    before = source.read_bytes()
    (tmp_path / "evidence_canary_planted.jsonl").symlink_to(source)

    rc, captured = _plant(str(source), capsys)

    assert source.read_bytes() == before, "the input trace was modified in place"
    assert rc == 1
    assert "refusing to overwrite" in captured.err


def test_cli_plant_refuses_to_overwrite_a_hardlinked_output(tmp_path, capsys):
    """Same, through a hard link -- so the fix is not a symlink special case.

    `os.path.samefile` compares `(st_dev, st_ino)`, so it catches both. A fix
    written as `os.path.islink` would pass the test above and fail this one.
    """
    source = tmp_path / "evidence.jsonl"
    trace_to_jsonl(generate_clean_trace(), str(source))
    before = source.read_bytes()
    os.link(source, tmp_path / "evidence_canary_planted.jsonl")

    rc, captured = _plant(str(source), capsys)

    assert source.read_bytes() == before, "the input trace was modified in place"
    assert rc == 1
    assert "refusing to overwrite" in captured.err


def test_cli_plant_overwrites_its_own_previous_output(tmp_path, capsys):
    """The control, because refusing too much is also a defect.

    Plant twice: the second run must succeed and the planted file must hold one
    plant, not two. A guard that refused whenever the output already existed
    would pass both link tests above and make `--plant` unusable for iterating.
    """
    source = tmp_path / "iter.jsonl"
    trace_to_jsonl(generate_clean_trace(), str(source))
    before = source.read_bytes()

    assert _plant(str(source), capsys)[0] == 0
    planted = _planted(tmp_path, source.name)
    first = planted.read_text(encoding="utf-8")

    assert _plant(str(source), capsys)[0] == 0

    assert source.read_bytes() == before
    # Compared against the first run's output rather than an absolute count:
    # `generate_clean_trace` already carries canary records of its own, so
    # asserting a literal number would be a statement about the fixture, not
    # about whether the second plant compounded.
    assert _planted(tmp_path, source.name).read_text(encoding="utf-8") == first, (
        "the second plant compounded on the first"
    )


# --- a malformed timestamp must not become a traceback ----------------------
#
# `Trace.from_jsonl` validates nothing, so `"timestamp": null` arrives intact.
# Comparing it raised `TypeError: '>' not supported between 'float' and
# 'NoneType'`, turning a trace toxindb would previously have accepted into a
# crash. A tool whose purpose is to read other people's logs has to survive
# their logs.


@pytest.mark.parametrize(
    "bad", [None, "1750000000.0", True, {"a": 1}, [1.0]]
)
def test_cli_plant_skips_a_non_numeric_timestamp(tmp_path, capsys, bad):
    path = tmp_path / "mixed.jsonl"
    rows = [
        {
            "type": "ingest", "doc_id": f"d{i}", "source": "s", "owner": "o",
            "namespace": "n", "timestamp": REAL_EPOCH, "content": f"doc {i}",
        }
        for i in range(3)
    ]
    rows.insert(1, {
        "type": "ingest", "doc_id": "bad", "source": "s", "owner": "o",
        "namespace": "n", "timestamp": bad, "content": "malformed",
    })
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")

    rc, _ = _plant(str(path), capsys)

    assert rc == 0, "one bad timestamp crashed the command"
    planted = _planted(tmp_path, path.name)
    claims = [
        json.loads(line)["planted_at"]
        for line in planted.read_text(encoding="utf-8").splitlines()
        if json.loads(line)["type"] == "canary"
    ]
    assert claims == [REAL_EPOCH], (
        f"planted at {claims} rather than at the one good timestamp in the trace"
    )


def test_cli_plant_falls_back_when_no_timestamp_is_usable(tmp_path, capsys):
    """All-bad rather than one-bad, so the fallback is pinned too.

    Prevents a `max()` over an empty filtered list from becoming the new crash.
    """
    path = tmp_path / "allbad.jsonl"
    path.write_text(
        '{"type": "ingest", "doc_id": "d", "source": "s", "owner": "o", '
        '"namespace": "n", "timestamp": null, "content": "c"}\n',
        encoding="utf-8",
    )

    rc, _ = _plant(str(path), capsys)

    assert rc == 0
    planted = _planted(tmp_path, path.name)
    claims = [
        json.loads(line)["planted_at"]
        for line in planted.read_text(encoding="utf-8").splitlines()
        if json.loads(line)["type"] == "canary"
    ]
    assert claims == [999999.0], (
        "a trace with no usable timestamp must fall back to the documented "
        "constant rather than guess or crash"
    )


def test_cli_provenance(tmp_path):
    path = _make_trace_file(generate_clean_trace())
    rc = main(["provenance", path, "--output", str(tmp_path)])
    assert rc == 0
    assert (tmp_path / "provenance.json").exists()
    os.unlink(path)


def test_cli_report(tmp_path):
    path = _make_trace_file(generate_poison_trace())
    rc = main(["report", path, "--format", "md", "--output", str(tmp_path)])
    assert rc == 0
    assert (tmp_path / "report.md").exists()
    os.unlink(path)


def test_cli_report_json(tmp_path):
    path = _make_trace_file(generate_poison_trace())
    rc = main(["report", path, "--format", "json", "--output", str(tmp_path)])
    assert rc == 0
    assert (tmp_path / "report.json").exists()
    os.unlink(path)


def test_cli_no_command():
    rc = main([])
    assert rc == 0


def test_cli_monitor_no_trace():
    rc = main(["monitor", "--output", "/tmp"])
    assert rc == 1


def test_cli_canary_no_trace():
    rc = main(["canary", "--output", "/tmp"])
    assert rc == 1


def test_cli_provenance_no_trace():
    rc = main(["provenance", "--output", "/tmp"])
    assert rc == 1


def test_cli_report_no_trace():
    rc = main(["report", "--output", "/tmp"])
    assert rc == 1


def test_cli_monitor_verbose(tmp_path):
    path = _make_trace_file(generate_clean_trace())
    rc = main(["monitor", path, "--verbose", "--output", str(tmp_path)])
    assert rc == 0
    os.unlink(path)


def test_cli_provenance_verbose(tmp_path):
    path = _make_trace_file(generate_clean_trace())
    rc = main(["provenance", path, "--verbose", "--output", str(tmp_path)])
    assert rc == 0
    os.unlink(path)
