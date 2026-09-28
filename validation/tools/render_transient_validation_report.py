#!/usr/bin/env python3
"""Render integrated transient validation JSON as deterministic Markdown."""
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
    status = "PASS" if result["summary"]["passed"] else "FAIL"
    lines = [
        "# Integrated Transient Physics Validation Report",
        "",
        f"Overall status: **{status}**",
        "",
        "This report preserves the fidelity qualification of each accepted producer. A passing integration gate does not promote MODELED/foundation evidence to final fine-grid or long-time qualification.",
        "",
        f"Replay payload SHA-256: {tick}{result['replay_payload_sha256']}{tick}",
        "",
        "## Capability classification",
        "",
        "| Capability | Classification |",
        "|---|---|",
    ]
    for capability, classification in sorted(result["capability_classification"].items()):
        lines.append(f"| {capability} | {classification} |")
    lines.extend([
        "",
        "## Gate summary",
        "",
        "| Gate | Matrix mapping | Classification | Result |",
        "|---|---|---|---|",
    ])
    for record in result["records"]:
        mapping = ", ".join(record["matrix_mapping"]) or "integration-only"
        lines.append(
            f"| {record['gate_id']} | {mapping} | {record['classification']} | "
            f"{'PASS' if record['passed'] else 'FAIL'} |"
        )
    lines.append("")

    for record in result["records"]:
        lines.extend([
            f"## {record['gate_id']} — {record['title']}",
            "",
            f"Classification: **{record['classification']}**",
            "",
            f"Matrix mapping: {', '.join(record['matrix_mapping']) or 'integration-only'}",
            "",
            "### Setup / represented population",
            "",
            f"{tick}{tick}{tick}json",
            json.dumps(record["setup"], indent=2, sort_keys=True, ensure_ascii=True),
            f"{tick}{tick}{tick}",
            "",
            "### Measured evidence",
            "",
            f"{tick}{tick}{tick}json",
            json.dumps(record["evidence"], indent=2, sort_keys=True, ensure_ascii=True),
            f"{tick}{tick}{tick}",
            "",
            "### Thresholds / gates",
            "",
            f"{tick}{tick}{tick}json",
            json.dumps(record["thresholds"], indent=2, sort_keys=True, ensure_ascii=True),
            f"{tick}{tick}{tick}",
            "",
            "### Provenance",
            "",
        ])
        for item in record["provenance"]:
            lines.append(f"- {item}")
        lines.extend(["", "### Limitations", ""])
        for item in record["limitations"]:
            lines.append(f"- {item}")
        lines.extend(["", f"Gate result: **{'PASS' if record['passed'] else 'FAIL'}**", ""])

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
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_report(result), encoding="utf-8")
    print(f"report: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
