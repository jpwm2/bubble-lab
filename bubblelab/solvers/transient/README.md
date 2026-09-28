# Bubble Lab transient sharp-interface reference backend

This directory contains the uniform-grid reference implementation of Bubble Lab's Maximum Realism transient architecture: an explicit, zero-thickness front-tracked soap-film sheet coupled to incompressible Eulerian gas flow. This slice advances the accepted foundation with region identity, region-specific bulk properties, a jump-aware capillary pressure treatment, and density-contrast buoyancy. It remains a compact CI implementation rather than a production AMR solver.

Requirements advanced: R6, R7, R10, R11, R18, R20, R22, R24, R31, R32, R33, R34, R35, R38.

## Film and region representation

Each closed bubble is an outward-oriented triangle mesh. The film remains a mathematical sheet with effective sheet tension `sigma_f`; no finite liquid thickness is created.

Eulerian cell centers are classified as `EXTERIOR` or a bubble region using the oriented solid angle of the tracked closed surface. An axis-aligned front bound is used only as a deterministic acceleration structure before the solid-angle test. The current task targets isolated closed bubbles; overlapping/nested ownership and shared-film topology are outside this implementation.

Each region can carry its own:
- density `rho`;
- dynamic viscosity `mu`.

If a bubble has no explicit override, it inherits exterior properties for backward compatibility.

## Variable-property bulk flow

The velocity update retains deterministic semi-Lagrangian advection. Viscous diffusion evaluates a variable-coefficient `div(mu grad u)/rho` term. Dynamic viscosity on a cell-to-cell face uses a harmonic mean.

The incompressible pressure projection is

`div((1/rho) grad p) = div(u*) / dt`.

Face mobility `1/rho_face` is the arithmetic mean of neighboring inverse densities, equivalent to a harmonic interpolation of density. The same face mobility, forward pressure gradient, and backward divergence are used in both the capillary pressure treatment and projection. This pairing is important for static-bubble balance.

The reference domain is still periodic and uniform. AMR and production far-field boundary conditions are separate later tasks.

## Sharp/jump-aware capillarity

The old cloud-in-cell capillary force path is retained only for explicit diffuse comparisons when `sharp_pressure_jump=False`. The default sharp path does not spread the area-gradient force through the gas volume.

For each tracked front, curvature is derived from the discrete surface-area first variation already used by the film geometry. For the isolated closed-front slice implemented here, an area-weighted discrete curvature magnitude is converted to a region pressure potential

`Delta p_h = sigma_f * kappa_h`.

The potential is discontinuous at the cell region boundary. Its face gradient is applied using the same mobility operator that the variable-density pressure projection uses. In a static sphere, projection therefore represents the capillary jump in pressure instead of leaving a smeared force that drives persistent currents.

The analytical sphere value `2 sigma_f/R` appears only in benchmarks. It is not used by the numerical solve.

This uniform cell-label method resolves the jump over the discrete interface crossing rather than through a multi-cell continuous-surface-force kernel. It is disclosed as **MODELED** in the canonical manifest because subcell cut geometry and fully local signed curvature transfer are not yet present.

## Density contrast and buoyancy

When density differs across the film, the periodic reference solver uses an exterior-density hydrostatic split. The declared physical pressure includes the reference hydrostatic component, while the perturbation momentum equation advances the residual acceleration

`g * (1 - rho_ref/rho)`.

With `rho_ref = rho_exterior`, exterior hydrostatic balance is removed from the dynamic solve and a lighter internal gas receives the correct upward buoyant response relative to the exterior. This is a periodic-box physics check, not a terminal-rise or nonperiodic far-field model.

With no density contrast, gravity retains the foundation behavior of a uniform body acceleration.

## Volume and conservation

Front advection is still midpoint interpolation of Eulerian velocity. The uniform reference grid does not yet implement conservative cut-cell interface transport, so a deterministic global closed-volume projection restores each initial target volume after advection. Pre-projection error is retained in diagnostics. This remains **MODELED** and is not presented as resolved local conservation.

## Diagnostics

Each step records:
- timestep;
- projection iterations and residual;
- post-projection divergence;
- maximum gas velocity;
- pre/post global volume-projection error;
- sheet surface energy;
- bulk kinetic energy using local density;
- integrated discrete capillary-force diagnostics;
- numerical pressure-jump error against the geometry-derived target.

The canonical export additionally records region cell counts, region material properties, grid spacing, interpolation choices, and mesh quality.

## Feature disclosures

Advanced in this task:
- pressure jump: **MODELED** sharp region pressure potential;
- region-specific bulk density/viscosity: **RESOLVED** on the uniform Eulerian grid;
- density-contrast buoyancy: **MODELED** exterior-hydrostatic reference formulation.

Still **NOT_IMPLEMENTED**:
- adaptive mesh refinement;
- finite film thickness or liquid-film mass;
- drainage/disjoining pressure;
- surfactant/Marangoni transport;
- shared-film/contact/Plateau topology;
- topology changes;
- rupture, coalescence, burst, and splitting;
- local resolved-liquid VOF patches;
- nonperiodic production far-field boundaries.

## Validation commands

Unit/regression suite:

`python3 -m unittest discover -s bubblelab/solvers/transient/tests -v`

Sharp static sphere:

`python3 bubblelab/solvers/transient/tools/run_benchmark.py sharp-static-sphere --assert`

This reports volume/area/centroid drift, pressure-jump error, divergence, and `max|u|/U_sigma` at two uniform-grid resolutions. The CI grids are intentionally much coarser than the Benchmark Matrix final B12 requirement `eta_b <= 0.02`, so the command enforces a coarse-to-finer trend and static-balance gates without claiming final B12 release qualification.

Young-Laplace jump:

`python3 bubblelab/solvers/transient/tools/run_benchmark.py pressure-jump --assert`

The benchmark compares numerical inside/outside mean pressure with both the discrete tracked-mesh jump and the analytical sphere reference. The tracked surface is refined between levels and the analytical error must improve.

Density contrast:

`python3 bubblelab/solvers/transient/tools/run_benchmark.py density-contrast --assert`

A lighter internal gas under downward gravity must move upward, installed cell densities must match the two regions, the declared exterior hydrostatic reference must have the correct gradient, and the projected field must remain divergence controlled.

Deterministic replay:

`python3 bubblelab/solvers/transient/tools/run_benchmark.py replay --assert`

Replay hashing includes geometry, scalar diagnostics, region labels, and pressure-jump targets.

Canonical export:

`python3 bubblelab/solvers/transient/tools/export_demo.py --output /tmp/bubble-transient-sharp-frame.json`

## Numerical limitations and next steps

The sharp path is intentionally a stepping stone between the accepted diffuse foundation and the architecture's final adaptive finite-volume target. The main remaining numerical limitations are uniform spatial resolution, cell-center rather than subcell cut geometry, one scalar curvature target per isolated closed front, global rather than locally conservative volume correction, periodic boundaries, and no topology surgery.

A later AMR task can replace the uniform Eulerian implementation while preserving the front, region-property, pressure-jump, canonical-export, and benchmark interfaces introduced here.
