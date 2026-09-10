"""CLI entry point for toxindb."""
from __future__ import annotations

import argparse
import json
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


def cmd_canary(args) -> int:
    trace_path = _resolve_trace(args)
    if not trace_path:
        print("Error: no trace file specified.", file=sys.stderr)
        return 1
    trace = Trace.from_jsonl(trace_path)

    if getattr(args, "plant", False):
        canary = generate_canary(args.seed)
        plant_canary_in_trace(trace, canary, timestamp=999999.0)
        out_path = trace_path.replace(".jsonl", "_canary_planted.jsonl")
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
