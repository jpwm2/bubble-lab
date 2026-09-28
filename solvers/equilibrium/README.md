# Bubble Lab High-Fidelity Equilibrium Core

This directory implements the executable quasi-static soap-bubble solver for Bubble Lab. It covers isolated prescribed-volume bubbles and a reduced two-region shared-film equilibrium model. Dynamic contact creation, Plateau triple-line mechanics, coalescence, rupture, transient flow, drainage and diffusion remain `NOT_IMPLEMENTED` here and belong to downstream components.

## Physical model

For a closed film with effective collapsed-sheet tension `sigma_f`, the solver minimizes

`E(x) = sigma_f A(x)`

subject to

`V(x) = V_target`.

The tension convention is the project convention from `PHYSICS_MODEL.md`: `sigma_f` is the effective tension of the collapsed soap-film sheet. For a sphere,

`Delta p = 2 sigma_f / R`.

The pressure jump reported by this solver is not obtained by fitting a sphere. It is the discrete volume-constraint multiplier that minimizes the stationarity residual

`grad(E) - Delta p grad(V)`.

## Discretization

`SurfaceMesh` is an explicitly oriented triangle complex with deterministic vertex/face ordering. It provides:

- total triangle area;
- signed enclosed volume from oriented tetrahedra;
- face normals;
- closed-manifold/orientation validation;
- deterministic unique edges and mesh-quality diagnostics.

Area and volume gradients are exact first derivatives of those same discrete formulas. The Young-Laplace force diagnostic therefore compares energy and pressure using one internally consistent discretization.

## Optimizer

`solve_prescribed_volume` uses a constrained projected-gradient method:

1. compute exact discrete `grad(E)` and `grad(V)`;
2. compute the least-squares pressure multiplier `p` in `grad(E) = p grad(V)`;
3. remove the constraint-normal component from the energy gradient;
4. take a bounded descent step along the projected gradient;
5. retract the trial surface exactly to `V_target` by uniform scaling about the vertex centroid;
6. accept only a non-increasing physical surface-energy step using deterministic backtracking.

This is a genuine constrained surface-energy method rather than a spring relaxation. The exact volume retraction is appropriate for the current single closed region and is intentionally isolated so a later multi-region/shared-film solver can replace it with a coupled constraint projection without replacing mesh, energy or diagnostic primitives.

Default stopping gates are:

- relative volume error `<= 1e-10`;
- normalized projected-force residual `<= 1e-3`;
- maximum 200 nonlinear iterations.

Iteration count by itself never signals convergence.

## Benchmarks

`tools/run_benchmark.py sphere --assert` runs the fine single-sphere checks. It uses an icosphere with `eta_s <= 0.03` and enforces the accepted matrix gates relevant to this isolated solver:

- B01 raw area error `<= 2e-3`;
- B01 raw volume error `<= 2e-3` before constraint correction;
- B03A final relative volume error `<= 1e-8`;
- B02 Young-Laplace pressure error `<= 5e-3`;
- B02 energy-consistent normalized force residual `<= 1e-2`;
- B11 deterministic repeatability.

`tools/run_benchmark.py sphere-convergence --assert` uses three deterministic refinement levels and enforces B09 observed-order gates:

- area and volume order `>= 1.7`;
- pressure/multiplier order `>= 1.3`.

The convergence command is a compact CI ladder; the separate `sphere` command supplies the matrix's fine-resolution absolute target.

## Canonical export

`tools/export_demo.py` writes a contract-v1 `FRAME` with:

- one `BubbleState`;
- one `OUTER_FILM` mesh and film region;
- computed pressure, area, energy, volume and solver diagnostics;
- HIGH_FIDELITY provenance and effective-sheet-tension convention;
- explicit `NOT_IMPLEMENTED` disclosures for unavailable physics.

It does not fabricate film thickness, CFD velocity, shared-film, junction or Plateau data.

## Numerical limitations

- The optimizer currently handles one closed prescribed-volume region. Coupled multi-region constraints require the downstream shared-film topology task.
- Refinement is deterministic icosphere generation for convergence studies; adaptive split/collapse/flip remeshing is not yet part of this task.
- The piecewise-linear surface has discretization error in area and pressure. The benchmark reports and tests that error rather than hiding it with an analytical sphere fit.
- No Hessian/negative-mode stability test is claimed in this first core. Energy monotonicity and first-order stationarity are the implemented stability evidence.
- Pressure is a pressure **jump** relative to exterior in solver diagnostics. Canonical bubble pressure adds the declared ambient reference pressure.

## Requirement traceability

This task advances R6, R7, R8 (core abstractions only, not contact), R9 (core force machinery only, not junction topology), R10 (geometry foundation), R17 (future boundary extension point), R32 and R35. Directly exercised here are R6, R7, R31/R32 deterministic/convergence behavior, and R33 physical-transparency disclosure.
