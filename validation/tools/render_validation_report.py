#!/usr/bin/env python3
"""Render deterministic equilibrium validation JSON as a Markdown report."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _fmt(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:.8g}"
    if value is None:
        return "n/a"
    if isinstance(value, (list, dict)):
        return json.dumps(value, sort_keys=True, ensure_ascii=True)
    return str(value)


def render_report(result: dict[str, Any]) -> str:
    tick = chr(96)
    lines: list[str] = []
    status = "PASS" if result["summary"]["passed"] else "FAIL"
    lines.extend([
        "# Equilibrium Physics Validation Report",
        "",
        f"Overall status: **{status}**",
        "",
        "**Scope:** This report validates equilibrium physics only. It does not validate transient multiphase flow, film drainage, gas diffusion, coalescence, rupture, or rendering.",
        "",
        f"Replay payload SHA-256: {tick}{result['replay_payload_sha256']}{tick}",
        "",
        "## Solver provenance",
        "",
        "| Field | Value |",
        "|---|---|",
    ])
    provenance = result["provenance"]
    lines.append(f"| Backend | {_fmt(provenance['backend'])} |")
    lines.append(f"| Fidelity tier | {_fmt(provenance['fidelity_tier'])} |")
    lines.append(f"| Active features | {_fmt(provenance['active_feature_classification'])} |")
    lines.append(f"| Adapter source hashes | {_fmt(provenance['adapter_source_sha256'])} |")
    lines.append(f"| Seed | {_fmt(provenance['seed'])} |")
    lines.append(f"| Thread/process count | {_fmt(provenance['thread_process_count'])} |")
    lines.append(f"| Bulk-grid resolution | {_fmt(provenance['bulk_grid_resolution'])} |")
    lines.append(f"| Timestep | {_fmt(provenance['timestep'])} |")
    lines.append("")

    lines.extend([
        "## Benchmark summary",
        "",
        "| ID | Benchmark | Result |",
        "|---|---|---|",
    ])
    for record in result["benchmarks"]:
        lines.append(f"| {record['id']} | {record['title']} | {'PASS' if record['passed'] else 'FAIL'} |")
    lines.append("")

    for record in result["benchmarks"]:
        lines.extend([
            f"## {record['id']} — {record['title']}",
            "",
            f"Requirements: {', '.join(record['requirements'])}",
            "",
            f"Setup: {_fmt(record['setup'])}",
            "",
            f"Resolution: {_fmt(record['resolution'])}",
            "",
            "### Measured metrics",
            "",
            "| Metric | Value |",
            "|---|---:|",
        ])
        for key, value in record["metrics"].items():
            lines.append(f"| {key} | {_fmt(value)} |")
        lines.extend([
            "",
            "### Gates",
            "",
            "| Metric | Measured | Required | Source | Result |",
            "|---|---:|---:|---|---|",
        ])
        for gate in record["gates"]:
            required = f"{gate['relation']} {_fmt(gate['threshold'])}"
            lines.append(
                f"| {gate['metric']} | {_fmt(gate['value'])} | {required} | {gate['source']} | "
                f"{'PASS' if gate['passed'] else 'FAIL'} |"
            )
        if record.get("termination"):
            lines.extend(["", f"Termination: {_fmt(record['termination'])}"])
        if record.get("convergence"):
            lines.extend(["", "### Convergence evidence", "", _fmt(record["convergence"])])
        if record.get("limitations"):
            lines.extend(["", "### Limitations", ""])
            for limitation in record["limitations"]:
                lines.append(f"- {limitation}")
        lines.append("")

    lines.extend(["## Suite limitations", ""])
    for limitation in result["limitations"]:
        lines.append(f"- {limitation}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    result = json.loads(Path(args.input).read_text(encoding="utf-8"))
    report = render_report(result)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")
    print(f"report: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
