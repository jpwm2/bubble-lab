#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from benchmarks import all_benchmarks


def _fmt(value: object) -> str:
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def render() -> str:
    data = all_benchmarks(assert_result=True)
    neck = data["neck_detection"]
    split = data["split_bookkeeping"]
    resolution = data["neck_resolution"]
    rows = resolution["levels"]
    lines = [
        "# Fragmentation / pinch-off research report",
        "",
        "Status: research prototype only; production fragmentation remains NOT_IMPLEMENTED.",
        "Requirements advanced: R16, R31, R32, R33, R34, R35, R38.",
        "",
        "## Executable evidence",
        "",
        f"The mesh-based cross-sectional diagnostic detects the necked benchmark ({neck['necked_detected']}) and rejects the elongated ellipsoid ({neck['ellipsoid_detected']}). The candidate cut is topologically separating ({neck['topologically_separable']}).",
        f"Rotation sensitivity is bounded in the benchmark: neck-radius relative error={_fmt(neck['rotation_radius_relative_error'])}, child-fraction max error={_fmt(neck['rotation_child_fraction_max_error'])}.",
        "",
        "The split-bookkeeping prototype conserves quantities without assigning a fictitious surface-energy jump:",
        "",
        "```json",
        json.dumps(split["conservation"], indent=2, sort_keys=True),
        "```",
        "",
        "Child restart geometry is explicitly labeled `PROTOTYPE_SPLIT_REQUIRES_PHYSICAL_RELAXATION`; the singular pinch event is not treated as an energy-conserving mesh edit.",
        "",
        "## Resolution / orientation study",
        "",
        "| level | h | neck radius | |cut| | child fractions | orientation radius error | orientation fraction error |",
        "|---|---:|---:|---:|---|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['level']} | {_fmt(row['mesh_spacing'])} | {_fmt(row['neck_radius'])} | {_fmt(row['cut_abs'])} | {tuple(round(x, 6) for x in row['child_volume_fractions'])} | {_fmt(row['orientation_radius_error'])} | {_fmt(row['orientation_fraction_error'])} |"
        )
    lines.extend([
        "",
        "The acceptance gate requires stable neck location, child volume fractions, and rotation response across three surface resolutions. A thin-looking neck on one coarse mesh is therefore insufficient evidence for a split.",
        "",
        "## Dynamic production trigger",
        "",
        "A production SPLIT candidate should require all of the following: geometric neck prominence and a separating loop; a refinement history showing stable neck position and daughter-volume fractions; local front and Eulerian refinement around the neck; monotone neck collapse over time; a capillary-timescale-consistent collapse rate or extensional/strain evidence; curvature growth consistent with collapse; and compatible thin-film state when that field is active. If the neck is only small relative to a coarse local mesh, the action is refine, not split.",
        "",
        "At the maximum permitted local refinement, an Eulerian topology handoff becomes eligible only after adjacent refinement levels agree within declared tolerances. Event time must then be localized by the event layer rather than by remeshing side effects.",
        "",
        "## Production-method comparison",
        "",
        "| family | topology robustness | conservation | singular neck dynamics | AMR fit | deterministic restart | conclusion |",
        "|---|---|---|---|---|---|---|",
        "| Explicit front surgery | deterministic connectivity is strong, as this prototype shows | exact scalar bookkeeping is straightforward | weak unless a physical singular model is added | good on tracked front | strong | keep for diagnostics/reconstruction, not as the sole pinch solver |",
        "| Temporary level-set/VOF patch | natural topology change | VOF can be strongly conservative; level set alone needs correction | strong when the local liquid/gas structure is actually resolved | strong | moderate; extraction/reinitialization must be canonicalized | viable local transition representation |",
        "| Local phase field | natural topology change | conservative formulations exist | regularizes the singularity through numerical interface width | expensive because epsilon must be resolved | moderate | useful reference path, not the default handoff |",
        "| Hybrid front tracking + Eulerian handoff | preserves explicit film identity away from pinch and delegates topology to a local Eulerian patch | combines tracked-state bookkeeping with conservative local CFD | strongest architectural fit | strong | strong if patch inputs/outputs and reconstruction are recorded | recommended |",
        "",
        "## Recommended production path",
        "",
        "Use hybrid front tracking with a temporary local conservative VOF (optionally coupled to a signed-distance field for geometry) patch through pinch-off. The tracked front remains authoritative before the handoff. AMR refines the neck until the maximum local level and convergence gates are met; then the event layer snapshots the pre-event state and creates a deterministic patch input containing local geometry, bulk fields, sheet state, seed, and trigger diagnostics. The Eulerian patch resolves the topology change, conserves phase volume/gas bookkeeping to its numerical budget, and returns two separated interfaces. Those interfaces are reconstructed as child tracked fronts with stable IDs and parent lineage, then relaxed/remeshed under the normal front-tracking solver.",
        "",
        "The event record should contain: parent ID; ordered child IDs; localized event time; trigger provenance including neck metric, local h/dx and refinement history; gas/target-volume/momentum diagnostics; Eulerian patch version and deterministic seed; reconstruction residuals; and restart-geometry status. Canonical contracts are not changed by this research task.",
        "",
        "## Graduation criteria before MODELED / RESOLVED claims",
        "",
        "Fragmentation remains research-only until all of these are demonstrated: at least three spatial resolutions and three time resolutions; split time converges with fine-vs-finer relative shift <=2%; daughter volume fractions converge and orientation sensitivity remains within a declared error budget; gas/target-volume bookkeeping <=1e-12 where algebraic allocation is claimed and full CFD conservation meets its solver budget; deterministic same-platform replay reproduces event IDs, event ordering, patch inputs, and child reconstruction; coarse-mesh-only triggers are rejected; restart fronts are closed, valid, identity-stable, and relax without unexplained conserved-quantity jumps; and benchmark cases include symmetric and asymmetric dumbbells, rotated geometry, non-pinching elongated shapes, strong extensional forcing, and cases where film-thickness physics suppresses or delays splitting.",
        "",
        "Surface energy across the singular pinch remains an observed diagnostic, not an algebraically conserved quantity. A production implementation must report the jump and dissipation/work accounting rather than forcing it to zero.",
    ])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    Path(args.output).write_text(render(), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
