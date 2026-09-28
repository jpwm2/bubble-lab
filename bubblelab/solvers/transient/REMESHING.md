# Deterministic tracked-front remeshing

The transient backend can optionally maintain the triangle quality of each closed tracked soap-film front. Remeshing is geometry maintenance only: it does not create/delete bubble regions, change genus, merge bubbles, rupture films, or perform any other physical topology event.

## Configuration

TransientConfig.remeshing accepts RemeshConfig.

| setting | default | meaning |
| --- | ---: | --- |
| mode | disabled | disabled, interval, or quality |
| interval_steps | 1 | interval cadence in interval mode |
| target_edge_length_m | None | explicit target; otherwise current mean edge length |
| min_edge_factor | 0.45 | collapse candidates below target times this factor |
| max_edge_factor | 1.60 | split candidates above target times this factor |
| min_angle_deg | 20 | quality trigger/floor target |
| max_aspect_ratio | 3.0 | quality trigger |
| max_passes | 2 | deterministic remeshing passes |
| max_operations_per_pass | 64 | operation budget per pass |
| smoothing_relaxation | 0.25 | tangential Laplacian move fraction |
| max_geometry_relative_error | 2e-3 | per-operation volume/area/centroid geometry guard |
| amr_cell_size_factor | 1.0 | caps target size by local Eulerian cell size |

Quality mode runs only when an edge-length or triangle-quality gate is violated. Interval mode attempts maintenance every configured number of solver steps. The default is deliberately disabled, so enabling this module does not alter accepted sharp-interface or AMR regressions.

The target-size interface is independent of the Eulerian grid. The solver may supply the finest local AMR cell size as an additional cap, but front connectivity and Eulerian AMR hierarchy remain separate meshes. This interface can later accept curvature, shared-film/junction, thickness-gradient, surfactant-gradient, or rupture-neighborhood target policies.

## Operations and deterministic ordering

A pass considers, in order:

1. shortest edges for collapse;
2. longest edges for split;
3. lexicographically ordered edges for quality-improving flips;
4. increasing vertex indices for tangential smoothing.

Length ties use stable vertex-index ordering. No random decisions are made.

Every accepted operation must leave a closed connected two-manifold with the same Euler characteristic and positive outward signed volume. Degenerate or duplicate faces, nonmanifold edges, invalid collapse link conditions, nonconvex flip neighborhoods, orientation failure, and configured geometry error violations are rejected. Bubble, mesh, and film identifiers are retained.

The current collapse keeps the lower-index endpoint. Split inserts the new vertex on the selected edge. Smoothing removes the local normal component from a Laplacian displacement so it is tangential to first order.

## Conservative surface-field transfer

ConservativeArealField is generic infrastructure for future film-liquid mass and surfactant fields. It stores a face-integrated amount rather than a pointwise concentration. After a connectivity-changing or smoothing operation, the old areal density is deterministically sampled by nearest face centroid on the new mesh, then a global conservative correction preserves the integrated amount. The final floating-point residual is applied to one deterministic face.

This task does not implement drainage, surfactant transport, Marangoni stress, or finite film thickness. The field is only a conservative remapping abstraction. The B14-style CI gate for its integrated amount is relative error <= 1e-10.

## Solver ordering and diagnostics

Within a transient step the order is:

    Eulerian advance -> tracked-front advection -> optional remeshing -> existing closed-volume projection -> region/AMR refresh

This is intentional. Remesh-induced volume error is measured before the existing global volume projection, so the projection cannot hide remeshing error.

Per-step diagnostics expose operation counts and logs, vertices/faces before and after, minimum angle and worst aspect ratio before/after, target edge length, remesh-induced volume/area/centroid change, field-conservation error, and region-identity preservation. Canonical FRAME export includes those diagnostics when remeshing is enabled.

After remeshing, the authoritative front is immediately reused for cell-region classification, sharp pressure-jump curvature, AMR hierarchy rebuild, and canonical mesh export.

## Validation

Run:

    python3 -m unittest discover -s bubblelab/solvers/transient/tests -v
    python3 bubblelab/solvers/transient/tools/run_benchmark.py remesh-quality --assert
    python3 bubblelab/solvers/transient/tools/run_benchmark.py remesh-conservation --assert
    python3 bubblelab/solvers/transient/tools/run_benchmark.py remesh-replay --assert
    python3 bubblelab/solvers/transient/tools/run_benchmark.py amr-replay --assert
    python3 bubblelab/solvers/transient/tools/run_benchmark.py pressure-jump --assert

remesh-quality repairs a deliberately poor but valid sphere triangulation. remesh-conservation executes split, collapse, flip, and tangential smoothing while checking generic areal mass, gas volume, area, centroid, and region identity. remesh-replay hashes connectivity, vertices, field data, and the operation report from two identical runs.
