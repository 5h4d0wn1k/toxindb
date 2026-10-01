"""CLI entry point for toxindb."""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from typing import List, Optional

from . import __version__
from .trace import Trace
from .engine import Engine
from .canary import (
    generate_canary,
    plant_canary_in_trace,
    monitor_canaries,
    check_canary_resurgence,
)
from .provenance import audit_provenance
from .report import render_markdown_report, render_json_report, write_report
from .trace_gen import ensure_demo_traces, generate_clean_trace, generate_poison_trace


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="toxindb",
        description="RAG retrieval-time poisoning detector",
    )
    parser.add_argument("--version", action="version", version=f"toxindb {__version__}")
    parser.add_argument("--demo", action="store_true",
                        help="Run the offline demo (alias for the 'demo' subcommand)")

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--output", type=str, default="./reports")
    common.add_argument("--verbose", action="store_true")

    sub = parser.add_subparsers(dest="command")

    monitor_p = sub.add_parser("monitor", parents=[common],
                                help="Process a trace and emit JSONL alerts")
    monitor_p.add_argument("trace", nargs="?", help="Path to trace JSONL file")
    monitor_p.add_argument("--target", type=str, default=None)

    canary_p = sub.add_parser("canary", parents=[common],
                               help="Plant/monitor canary claims")
    canary_p.add_argument("trace", nargs="?", help="Path to trace JSONL file")
    canary_p.add_argument("--target", type=str, default=None)
    canary_p.add_argument("--seed", type=str, default="demo")
    canary_p.add_argument("--plant", action="store_true")
    canary_p.add_argument(
        "--at",
        type=float,
        default=None,
        metavar="TIMESTAMP",
        help="Timestamp for the planted canary (default: the trace's own "
             "latest event, so the plant lands inside the recency windows)",
    )
    canary_p.add_argument("--monitor", action="store_true")

    prov_p = sub.add_parser("provenance", parents=[common],
                             help="Audit ingestion log provenance")
    prov_p.add_argument("trace", nargs="?", help="Path to trace JSONL file")
    prov_p.add_argument("--target", type=str, default=None)

    report_p = sub.add_parser("report", parents=[common],
                               help="Render analysis report (MD/JSON)")
    report_p.add_argument("trace", nargs="?", help="Path to trace JSONL file")
    report_p.add_argument("--target", type=str, default=None)
    report_p.add_argument("--format", choices=["md", "json"], default="md")

    demo_p = sub.add_parser("demo", parents=[common],
                             help="Run offline demo")

    return parser


def _resolve_trace(args) -> Optional[str]:
    path = getattr(args, "trace", None) or getattr(args, "target", None)
    if path and os.path.exists(path):
        return path
    return None


def cmd_monitor(args) -> int:
    trace_path = _resolve_trace(args)
    if not trace_path:
        print("Error: no trace file specified. Use --target or positional arg.", file=sys.stderr)
        return 1
    trace = Trace.from_jsonl(trace_path)
    engine = Engine()
    output_path = os.path.join(args.output, "alerts.jsonl")
    alerts = engine.analyze_to_jsonl(trace, output_path)
    if args.verbose:
        for alert in alerts:
            print(json.dumps(alert.to_dict()))
    print(f"Emitted {len(alerts)} alerts to {output_path}")
    return 0


def _plant_timestamp(trace: Trace) -> float:
    """When to stamp a planted canary, in the trace's own time.

    This used to be hardcoded to `999999.0` (1970-01-12). Every recency window
    in the tool is measured as `event.timestamp - doc.timestamp`, so on any
    trace carrying real epoch timestamps the planted document sat outside every
    window by decades: a query retrieving it counted 0 of its documents as
    recent and so raised no TX-001. Verified on a trace at 1.75e9 -- the plant
    was 55.4 years older than the trace it joined. Since `--plant` is the
    documented way to prove detection works, a plant that no demand-and-recency
    detector can see defeats the command's entire purpose.

    TX-004 is deliberately *not* named above. It substring-matches canary text
    in `query.output_text` and does no timestamp arithmetic at all, so it fires
    on a 1970-stamped plant exactly as it would on any other. An earlier
    version of this docstring said it "never fired", which was wrong: the
    timestamp defect was never about resurgence, only about the TX-001/TX-002
    family.

    The latest timestamp already in the trace, rather than wall-clock, for
    three reasons. It keeps the tool deterministic, which is a hard invariant
    and the reason the demo is byte-comparable across runs. It needs no clock,
    which is the same reason every timestamp here is read from the trace. And it
    cannot land in the future relative to the queries that would retrieve it,
    which several windows would read as a negative age.

    Timestamps that are not finite numbers are skipped rather than compared.
    `Trace.from_jsonl` performs no validation, so a record carrying
    `"timestamp": null` reaches here intact, and `max()` over it raised an
    uncaught `TypeError` -- turning a malformed trace into a traceback on a
    command that previously succeeded. Skipping means a trace with one bad
    timestamp plants at the best of its good ones instead of crashing, and a
    trace with no usable timestamp falls back rather than guessing.

    Falls back to `999999.0` for an empty trace, so the old constant survives
    only where it is the only answer available. `trace_gen` bases its fixtures
    near `1_000_000.0`, which is why the hardcoded value looked plausible: the
    bundled demo hid the defect rather than disproving it.
    """
    stamps = [
        e.timestamp
        for e in (*trace.ingests, *trace.queries)
        if isinstance(e.timestamp, (int, float)) and math.isfinite(e.timestamp)
    ]
    return max(stamps) if stamps else 999999.0


def _plant_output_path(trace_path: str) -> str:
    """Where a planted trace goes, derived from the input's final extension.

    Never by substring replacement. `str.replace` takes no occurrence count, so
    the old `trace_path.replace(".jsonl", "_canary_planted.jsonl")` was a no-op
    whenever the path contained no `.jsonl` -- `out_path` silently fell back to
    the input path, and `canary --plant` appended two canary records to the
    operator's own evidence file, printed the input path as the destination,
    and exited 0. With no occurrence count it also rewrote every occurrence, so
    `a.jsonl.b.jsonl` came out as `a_canary_planted.jsonl.b_canary_planted.jsonl`.

    `os.path.splitext` splits the last extension only, which is what a suffix
    means, and returns the stem unchanged when there is no extension at all.
    """
    base, _ext = os.path.splitext(trace_path)
    return f"{base}_canary_planted.jsonl"


def _same_file(left: str, right: str) -> bool:
    """Whether two paths name the same file, following links.

    Not `abspath` equality. That compares *names*, and an output path already
    present as a symlink or hardlink to the input has a different name while
    being the same file -- so the string test passed and `open(out, "w")`
    clobbered the input with exit 0. Verified with a symlink named exactly as
    the computed output.

    `os.path.samefile` is the correct test but it raises if either path is
    missing, which is the normal case here: the output is a file about to be
    created. So the plain paths are compared first as a cheap answer, and the
    inode comparison is only attempted for a path that exists.
    """
    if os.path.abspath(left) == os.path.abspath(right):
        return True
    try:
        return os.path.samefile(left, right)
    except OSError:
        # Neither present, or unreadable: they cannot be the same file.
        return False


def cmd_canary(args) -> int:
    trace_path = _resolve_trace(args)
    if not trace_path:
        print("Error: no trace file specified.", file=sys.stderr)
        return 1
    if os.path.isdir(trace_path):
        # Checked before reading, because `Trace.from_jsonl` raises
        # `IsADirectoryError` naming a path the operator never asked for. A
        # directory ending in `.jsonl` is a plausible mount layout, so this is
        # reachable rather than theoretical.
        print(
            f"Error: {trace_path} is a directory, not a trace file.",
            file=sys.stderr,
        )
        return 1
    trace = Trace.from_jsonl(trace_path)

    if getattr(args, "plant", False):
        canary = generate_canary(args.seed)
        requested = getattr(args, "at", None)
        if requested is not None:
            if not math.isfinite(requested):
                # `type=float` accepts `nan`, `inf` and `1e400`, and `json.dumps`
                # writes those as the bare tokens `NaN` and `Infinity`, which
                # RFC 8259 does not allow. Python's own `json.loads` accepts
                # them, so toxindb round-trips its own output and never notices
                # -- the break lands on every external consumer of a planted
                # trace, and the exit code is 0. Refused rather than sanitised,
                # because silently planting a timestamp the operator did not ask
                # for is worse than declining to plant.
                print(
                    f"Error: --at must be a finite number, got {requested!r}.",
                    file=sys.stderr,
                )
                return 1
            timestamp = requested
        else:
            timestamp = _plant_timestamp(trace)
        plant_canary_in_trace(trace, canary, timestamp=timestamp)
        out_path = _plant_output_path(trace_path)
        if _same_file(out_path, trace_path):
            # A standing guard on the one failure here that destroys data rather
            # than reporting it.
            #
            # The path-equality half is unreachable via `_plant_output_path` as
            # written -- it always appends a suffix -- and brute-forcing 22,629
            # generated path shapes found no input for which the output equals
            # the input. Kept because it costs one string comparison and the
            # failure it guards is irreversible. The inode half is *not*
            # unreachable: see `_same_file`.
            print("Error: refusing to overwrite the input trace.", file=sys.stderr)
            return 1
        trace.to_jsonl(out_path)
        print(f"Planted canary {canary.claim_id} -> {out_path}")
        return 0

    if getattr(args, "monitor", False):
        results = check_canary_resurgence(trace)
        output_path = os.path.join(args.output, "canary_report.json")
        os.makedirs(args.output, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(results, f, indent=2)
        surfaced = sum(1 for r in results if r.get("resurfaced"))
        print(f"Canary check: {surfaced}/{len(results)} resurfaced -> {output_path}")
        return 0

    results = check_canary_resurgence(trace)
    for r in results:
        status = "RESURFACED" if r.get("resurfaced") else "SAFE"
        print(f"Canary {r['canary_id']}: {status}")
    return 0


def cmd_provenance(args) -> int:
    trace_path = _resolve_trace(args)
    if not trace_path:
        print("Error: no trace file specified.", file=sys.stderr)
        return 1
    trace = Trace.from_jsonl(trace_path)
    report = audit_provenance(trace)
    output_path = os.path.join(args.output, "provenance.json")
    os.makedirs(args.output, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(report.to_dict(), f, indent=2)
    print(f"Provenance audit: {report.total_docs} docs, "
          f"{report.signed_docs} signed, {len(report.issues)} issues")
    if args.verbose:
        for issue in report.issues:
            print(f"  [{issue['severity']}] {issue['detail']}")
    return 0


def cmd_report(args) -> int:
    trace_path = _resolve_trace(args)
    if not trace_path:
        print("Error: no trace file specified.", file=sys.stderr)
        return 1
    trace = Trace.from_jsonl(trace_path)
    engine = Engine()
    alerts = engine.analyze(trace)
    prov_report = audit_provenance(trace)
    canary_results = check_canary_resurgence(trace) if trace.canaries else None

    if getattr(args, "format", "md") == "json":
        content = render_json_report(alerts, prov_report, canary_results)
        filename = "report.json"
    else:
        content = render_markdown_report(alerts, prov_report, canary_results,
                                         trace_path=trace_path)
        filename = "report.md"

    path = write_report(content, args.output, filename)
    print(f"Report written to {path}")
    return 0


def cmd_demo(args) -> int:
    print("=== toxindb demo ===")
    traces = ensure_demo_traces()
    print(f"Generated traces: {', '.join(traces.keys())}")

    output_dir = args.output
    os.makedirs(output_dir, exist_ok=True)

    results = {}

    for name, path in traces.items():
        print(f"\n--- Analyzing {name} trace ---")
        trace = Trace.from_jsonl(path)
        engine = Engine()
        alerts = engine.analyze(trace)
        prov = audit_provenance(trace)
        canary_res = check_canary_resurgence(trace) if trace.canaries else None

        md_content = render_markdown_report(
            alerts, prov, canary_res,
            title=f"toxindb Demo Report — {name.title()} Trace",
            trace_path=path,
        )
        json_content = render_json_report(alerts, prov, canary_res)

        md_path = write_report(md_content, output_dir, f"demo_{name}_report.md")
        json_path = write_report(json_content, output_dir, f"demo_{name}_report.json")

        alerts_path = os.path.join(output_dir, f"demo_{name}_alerts.jsonl")
        with open(alerts_path, "w") as f:
            for alert in alerts:
                f.write(json.dumps(alert.to_dict()) + "\n")

        results[name] = {
            "alerts": len(alerts),
            "md_report": md_path,
            "json_report": json_path,
            "alerts_file": alerts_path,
            "provenance_issues": len(prov.issues),
            "canary_results": canary_res,
        }

        print(f"  Alerts: {len(alerts)}")
        print(f"  Provenance issues: {len(prov.issues)}")
        if canary_res:
            surfaced = sum(1 for r in canary_res if r.get("resurfaced"))
            print(f"  Canaries: {surfaced}/{len(canary_res)} resurfaced")

        if args.verbose:
            for alert in alerts:
                print(f"    [{alert.severity}] {alert.heuristic_id}: {alert.detail}")

    summary_path = os.path.join(output_dir, "demo_summary.json")
    with open(summary_path, "w") as f:
        json.dump(results, f, indent=2, default=str)

    print(f"\n=== Demo complete ===")
    print(f"Reports in: {output_dir}")
    print(f"Summary: {summary_path}")

    clean_alerts = results.get("clean", {}).get("alerts", 0)
    poison_alerts = results.get("poison", {}).get("alerts", 0)
    print(f"Clean trace alerts: {clean_alerts}")
    print(f"Poison trace alerts: {poison_alerts}")
    print(f"Poison/Clean ratio: {poison_alerts / max(clean_alerts, 1):.1f}x")

    return 0


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--demo" in argv:
        argv.remove("--demo")
        argv.insert(0, "demo")
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "demo":
        return cmd_demo(args)
    elif args.command == "monitor":
        return cmd_monitor(args)
    elif args.command == "canary":
        return cmd_canary(args)
    elif args.command == "provenance":
        return cmd_provenance(args)
    elif args.command == "report":
        return cmd_report(args)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
