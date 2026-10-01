"""Tests for the CLI module."""
import json
import os
import sys
import tempfile

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
# code of 0 is exactly what the broken version produced.


def _plant(path, tmp_path, capsys):
    rc = main(["canary", path, "--plant", "--output", str(tmp_path)])
    return rc, capsys.readouterr()


def test_cli_plant_does_not_overwrite_input_without_jsonl_suffix(tmp_path, capsys):
    path = tmp_path / "ingest_log"
    trace_to_jsonl(generate_clean_trace(), str(path))
    before = path.read_bytes()

    rc, _ = _plant(str(path), tmp_path, capsys)

    assert path.read_bytes() == before, "the input trace was modified in place"
    assert rc == 0


def test_cli_plant_writes_the_output_beside_a_suffixless_input(tmp_path, capsys):
    path = tmp_path / "ingest_log"
    trace_to_jsonl(generate_clean_trace(), str(path))

    rc, captured = _plant(str(path), tmp_path, capsys)

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

    rc, captured = _plant(str(path), tmp_path, capsys)

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

    rc, captured = _plant(str(directory), tmp_path, capsys)

    assert rc == 1
    assert "directory" in captured.err


def test_cli_plant_keeps_the_documented_jsonl_behaviour(tmp_path, capsys):
    """The control.

    A fix that always appended `_canary_planted` would pass the tests above
    while breaking the README's example, whose output path is published. For a
    correctly-suffixed input the output name must be unchanged.
    """
    path = tmp_path / "ok.jsonl"
    trace_to_jsonl(generate_clean_trace(), str(path))
    before = path.read_bytes()

    rc, captured = _plant(str(path), tmp_path, capsys)

    assert rc == 0
    assert path.read_bytes() == before
    assert (tmp_path / "ok_canary_planted.jsonl").exists(), captured.out


# --- `canary --plant` must plant at a time the trace can see ----------------
#
# The plant timestamp was hardcoded to `999999.0` (1970-01-12). Every recency
# window in the tool is measured as `event.timestamp - doc.timestamp`, so on any
# trace with real epoch timestamps the planted document is not merely old, it
# is outside every window by decades: TX-001 counted 0 of the retrieved canary
# docs as recent, and TX-004 canary resurgence never fires. A plant is the
# documented way to prove detection works, and it could not be detected.
#
# The bundled fixtures hide this: `trace_gen` bases its timestamps near
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
    rc, captured = _plant(str(path), tmp_path, capsys)
    assert rc == 0

    planted = tmp_path / "epoch_canary_planted.jsonl"
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
    rc, _ = _plant(str(path), tmp_path, capsys)
    assert rc == 0

    planted = tmp_path / "epoch_canary_planted.jsonl"
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
        "canary", str(path), "--plant", "--output", str(tmp_path),
        "--at", "1234567890.0",
    ])
    capsys.readouterr()
    assert rc == 0

    planted = tmp_path / "epoch_canary_planted.jsonl"
    rows = [json.loads(line) for line in planted.read_text(encoding="utf-8").splitlines()]
    claims = [r["planted_at"] for r in rows if r["type"] == "canary"]
    assert 1234567890.0 in claims


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
