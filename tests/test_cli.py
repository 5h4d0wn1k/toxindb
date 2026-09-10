"""Tests for the CLI module."""
import json
import os
import sys
import tempfile

from toxindb.cli import main, _build_parser
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
