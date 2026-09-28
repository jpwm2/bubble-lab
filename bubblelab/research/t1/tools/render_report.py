#!/usr/bin/env python3
"""Render executable T1 research evidence and production-path recommendation."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bubblelab.research.t1.benchmarks import eligibility_benchmark, neighbor_switch_benchmark, refinement_benchmark


def _fmt(value: float) -> str:
    return f"{value:.6g}"


def render() -> str:
    eligibility = eligibility_benchmark()
    switch = neighbor_switch_benchmark()
    refinement = refinement_benchmark()
    rows = refinement["rows"]
    order = refinement["observed_volume_error_orders"]
    lines = [
        "# T1 foam-neighbor-switch topology research",
        "",
        "## Claim boundary",
        "",
        "This is executable research evidence for one deterministic quasi-2D extruded four-gas-region T1 class. It does not promote production T1 capability, resolve singular liquid-rim dynamics, or claim general 3D Plateau-line rearrangement. The immediate post-event geometry is an unrelaxed seed.",
        "",
        "## Geometry and topology represented",
        "",
        "Each physical film is an actual triangulated rectangular sheet extruded through finite depth and stored once with two gas-region IDs. Each Plateau line contains coincident mesh-vertex samples on exactly three incident films. Closed cross-section gas polygons make geometric volumes measurable. Validation additionally requires every film spine to be a literal common edge of both adjacent gas cells, so a graph-only edge flip cannot satisfy the benchmark.",
        "",
        "The pre-event supported class contains gas regions A/B/C/D and films AB, AC, BC, AD, BD. The shrinking AB sheet is bounded by two Plateau lines. The switch retires AB and those two lines, creates CD and two replacement lines, preserves all gas-region IDs and four outer-film IDs, and generates finite triangulated CD seed geometry.",
        "",
        "## Executable results",
        "",
        f"- eligibility benchmark: {'PASS' if eligibility['pass'] else 'FAIL'}",
        f"- neighbor-switch benchmark: {'PASS' if switch['pass'] else 'FAIL'}",
        f"- refinement benchmark: {'PASS' if refinement['pass'] else 'FAIL'}",
        f"- raw post-seed max relative volume error at nominal h=0.12 m: {_fmt(float(switch['max_volume_error_after']))}",
        f"- surface-energy change at nominal h=0.12 m: {_fmt(float(switch['surface_energy_delta_j']))} J (singular-event energy is not physically resolved)",
        f"- normalized Plateau force residual before/after seed: {_fmt(float(switch['junction_force_residual_before']))} / {_fmt(float(switch['junction_force_residual_after']))}",
        f"- minimum post-seed triangle quality: {_fmt(float(switch['minimum_triangle_quality_after']))}",
        "",
        "## Refinement ladder",
        "",
        "| nominal h (m) | measured h (m) | collapse/threshold | max volume error | energy delta (J) |",
        "|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            "| " + " | ".join((
                _fmt(float(row["nominal_resolution_m"])),
                _fmt(float(row["measured_resolution_m"])),
                _fmt(float(row["collapse_threshold_ratio"])),
                _fmt(float(row["max_relative_volume_error"])),
                _fmt(float(row["surface_energy_delta_j"])),
            )) + " |"
        )
    lines.extend([
        "",
        "Observed raw-seed volume-error convergence orders: " + ", ".join(_fmt(float(value)) for value in order) + ". Eligibility remains stable and the post-switch gas adjacency is identical across all tested resolutions. The raw seed is intentionally not volume-projected; its volume residual converges with refinement and exposes the conservative correction that production integration must perform.",
        "",
        "## Eligibility boundary",
        "",
        "The detector uses actual film span, triangulated area, outer-film mesh resolution, Plateau incidence, and region adjacency. It rejects no-threshold-crossing cases, more than one simultaneous collapsing two-junction film, duplicate future adjacency, non-four-region local incidence, non-manifold/coincident-line failures, coarse outer-film grids, insufficient depth sampling, and low-quality triangles.",
        "",
        "## Production architecture comparison",
        "",
        "| Approach | Strength for T1 | Main gap/risk | Research recommendation |",
        "|---|---|---|---|",
        "| Direct tracked-front local surgery | Preserves stable film/region identity and matches the current shared-film representation | Needs robust arbitrary 3D patch cutting, remeshing, conservative volume projection, event ordering, and post-event relaxation | Best near-term path for narrowly certified local classes; generalization needs explicit mutable topology support |",
        "| Localized level-set/VOF handoff | Topology change occurs naturally without explicit combinatorial surgery | Recovering exact gas-region/film lineage and a clean Plateau network is difficult; handoff can diffuse volume/interface geometry | Useful fallback for geometrically ambiguous events if conservative multi-label reconstruction is added |",
        "| Phase-field/local diffuse-interface handoff | Naturally regularizes singular topology and can represent short transient scales | Interface thickness and mobility introduce model parameters; extracting sharp stable IDs and quantitative films requires convergence studies | Valuable physics-research route, not a drop-in production replacement for the tracked network |",
        "| Hybrid tracked-network to Eulerian event and back | Keeps efficient tracked geometry away from the event while delegating singularity crossing | Highest implementation complexity: bidirectional conservative transfer, lineage matching, and acceptance criteria are all required | Strong long-term architecture when general 3D T1/T2 events exceed certifiable local surgery classes |",
        "",
        "## Minimum production changes",
        "",
        "1. Add an explicit mutable topology transaction object that atomically retires/creates film and Plateau-junction IDs and records lineage.",
        "2. Rebuild the transient shared-DOF topology after a transaction instead of treating FilmNetwork/template topology as immutable for the full run.",
        "3. Add robust 3D local patch extraction/cutting and mesh-quality-controlled seed generation; the present research class is an extrusion, not a general Plateau-border configuration.",
        "4. Run coupled multi-region volume projection and physical capillary relaxation immediately after the raw seed, with rollback if conservation, manifoldness, or mesh-quality limits fail.",
        "5. Introduce deterministic event arbitration for simultaneous/nearby topology candidates and a handoff path for cases outside the direct-surgery support envelope.",
        "6. Extend validation with lineage, topology-signature, refinement, volume, energy, and junction-force diagnostics across accepted topology-event classes.",
        "",
        "## Interpretation",
        "",
        "The experiment demonstrates that the existing shared-film/Plateau semantics can represent both sides of one T1 event and that deterministic geometry-bearing surgery is feasible for a tightly constrained extruded class. It also demonstrates why production support is not yet justified: the accepted transient topology is immutable during a run, the raw geometric seed is not exactly conservative, and general 3D Plateau-line surgery/remeshing is absent. Production should therefore retain T1 topology surgery as not implemented until those architectural gaps and broader validation are closed.",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output)
    output.write_text(render(), encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
