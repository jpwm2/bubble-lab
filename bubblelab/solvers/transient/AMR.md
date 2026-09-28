# Transient adaptive Eulerian refinement

This backend provides deterministic block-structured adaptive mesh refinement
beneath the tracked soap-film solver. The coarse level covers the full periodic
reference domain. Nested Cartesian patches are created around the film and use
the same variable-density, variable-viscosity, jump-balanced pressure operator
as the uniform solver.

## Refinement rule

For each parent cell, the hierarchy measures Euclidean distance from the cell
center to the tracked surface triangles. Cells inside a configured distance band
are marked. The marked set is converted into an axis-aligned patch whose bounds
are snapped to parent-cell boundaries, and the child uses an integer refinement
ratio. Repeating the procedure creates deeper nested levels.

The rule is deterministic: it uses only tracked geometry, integer cell indices,
and AMR configuration. The current implemented indicator is front distance. The
AMR configuration and diagnostics are intentionally structured so curvature,
vorticity/strain, pressure-jump, and topology-event indicators can be added
without changing the hierarchy contract.

## Parent/child transfer

Velocity and pressure use trilinear prolongation when a child patch is created.
Covered parent cells receive volume-averaged child velocity and pressure after
the level advances. A constant field is therefore preserved to floating-point
roundoff. With constant density, the same restriction preserves the integrated
momentum proxy over a refine/restrict cycle.

Density, viscosity, region identity, and capillary pressure potential are not
interpolated between levels. They are recomputed independently on every level
from the authoritative tracked geometry and region material configuration. This
avoids smearing the sharp material jump through transfer operators.

## Pressure projection and coarse/fine interface

Every level executes the accepted paired backward-divergence/forward-gradient
variable-density projection. Before a fine-level advance, a one-cell shell is
filled from its parent. After the advance, the fine correction is restricted
back into the covered parent cells. Composite diagnostics exclude parent cells
covered by a child, so cell counts, pressure means, volume estimates, and kinetic
energy use leaf cells rather than double-counting the hierarchy.

This reference implementation is a nested-grid correction scheme rather than a
single global composite finite-volume matrix. The coarse/fine shell treatment
is explicit in exported metadata so the current numerical fidelity is not
overstated.

## Diagnostics

AMR runs export:

- active leaf cells by level and total active-cell count;
- maximum refinement level and refinement ratio;
- base and finest cell size;
- geometric refinement criterion and band width;
- transfer policy and coarse/fine interface policy;
- ordinary pressure residual, divergence, and volume-error diagnostics.

Deterministic replay includes hierarchy geometry and per-level Eulerian state.

## Validation

The AMR validation ladder contains:

- `amr-topology`: hierarchy determinism, coarse far field, fine film region,
  and prolong/restrict conservation;
- `amr-static-sphere`: static sharp bubble compared with a uniform peer under a
  comparable active-cell budget;
- `amr-pressure-jump`: three refinement settings with Young-Laplace
  convergence, discrete-jump residual, active-cell count, and finest `eta_b`;
- `amr-replay`: exact hierarchy and replay signature equality.

The CI ladder reports its actual finest nondimensional bulk resolution. It is a
foundation/convergence qualification unless the final B12 requirement
`eta_b <= 0.02` is actually reached.
