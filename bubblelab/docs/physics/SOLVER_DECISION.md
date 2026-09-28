# Bubble Lab Solver Decision

Status: implementation decision  
Task: bubble-physics-blueprint  
Requirements advanced: R1–R2, R6–R18, R20–R22, R29–R36, R38–R39

## 1. Decision summary

Bubble Lab will not force one numerical method to cover equilibrium foams, soap-film drainage, transient gas flow, microscopic rupture, and post-rupture droplets.

The staged solver stack is:

1. High Fidelity quasi-static equilibrium:
   custom triangulated surface-energy / film-network solver, Surface-Evolver-like in mathematics but integrated directly with the Bubble Lab canonical state contract.
2. Maximum Realism transient bubble-scale dynamics:
   explicit front-tracked soap-film sheet coupled to adaptive Eulerian incompressible flow for the bulk gases, with capillary traction, surface transport, and optional sheet inertia/rheology.
3. Drainage, surfactant, and gas diffusion:
   conservative lower-dimensional PDEs on the tracked film network, coupled by operator splitting initially and optionally monolithically for stiff cases.
4. Topology:
   explicit event/topology layer for contact-film creation, rupture, coalescence, burst, and later splitting; remeshing is not allowed to create topology changes implicitly.
5. Locally resolved liquid and topology-rich reference calculations:
   VOF with AMR, preferably a Basilisk-class backend, for benchmark/local subproblems where film/rim/Plateau-border thickness can actually be resolved.
6. OpenFOAM-class backend:
   supported as a secondary external CFD adapter when its broader finite-volume ecosystem, wall models, or deployment environment is advantageous, but it is not the default soap-film geometry engine.

The viewer remains solver-neutral and consumes only canonical result frames/checkpoints. [R2, R29, R34–R36]

## 2. Why there are two primary solver families

The core numerical conflict is scale and representation.

High Fidelity needs:
- accurate constrained area minimization;
- pressure as a volume multiplier;
- stable shared films;
- explicit triple lines;
- Plateau force balance;
- excellent curvature/pressure diagnostics;
- reproducible equilibrium independent of transient inertial timescales.

Maximum Realism needs:
- inertia and viscosity;
- ambient/internal flow;
- dynamic deformation;
- capillary waves;
- wind and buoyancy;
- surface transport;
- time-resolved topology events.

A transient CFD solver can eventually relax to equilibrium, but using it as the only equilibrium engine is wasteful and makes Plateau/junction geometry harder to control and validate. Conversely, gradient descent on a triangle mesh is not Navier–Stokes and must never be sold as physical transient dynamics. [R1, R6–R11, R33–R35]

## 3. Candidate-method comparison

### 3.1 Triangulated surface-energy minimization / Surface-Evolver-like

Representation:
- Explicit simplicial surface/film network.
- Region volumes and constraints are first-class.
- Triple lines and contact boundaries are explicit mesh entities.

Strengths:
- Directly minimizes the physical surface energy relevant to quasi-static soap films.
- Natural Lagrange-multiplier pressure interpretation.
- Excellent match to shared-film and Plateau-law benchmarks.
- Geometry, topology graph, and diagnostics map directly to the canonical contract.
- Deterministic execution is achievable with deterministic remeshing and solver ordering.
- No volumetric grid is required for empty gas space in equilibrium calculations.

Weaknesses:
- Not a physical inertial transient method.
- Mesh surgery is required for contact/coalescence/splitting.
- Curvature and force accuracy depend strongly on mesh quality and discrete differential-geometry choices.
- Finite-thickness Plateau borders are not resolved by a sheet mesh.

Decision:
- PRIMARY for High Fidelity equilibrium.
- Implement a Bubble Lab-native solver rather than make the viewer or state contract dependent on Surface Evolver file formats.
- Use Surface Evolver as an optional external comparison/oracle for selected equilibrium cases, not as the sole production dependency.

Surface Evolver itself is especially relevant because its documented model uses triangular simplicial surfaces with surface tension, volume constraints, boundary/contact-angle constraints, gravity, and arbitrary foam-like topology. Its public site states that it is available free of charge and provides source for Unix-like systems. Because the material checked does not present a modern standardized redistribution license in the same way as GPL/MIT-style projects, bundling or redistribution should be treated separately from merely using it as an external verification tool.

### 3.2 VOF with adaptive mesh refinement

Representation:
- Eulerian volume fraction for bulk phases.
- Interface reconstructed from cell fractions.
- AMR concentrates cells near interfaces.

Strengths:
- Strong volume conservation when implemented conservatively.
- Natural topology changes: breakup/merging do not require explicit mesh reconnection.
- Mature for droplets, jets, rims, and multiphase flows.
- Adaptive Cartesian implementations can resolve local capillary structures efficiently.
- Good reference method for post-rupture liquid fragments and resolved Plateau-border patches.

Weaknesses for soap bubbles:
- A real soap bubble is gas / extremely thin liquid / gas.
- A standard two-phase gas/liquid VOF bubble represents gas surrounded by bulk liquid, which is a different physical system.
- A three-phase/thin-shell VOF model must resolve film thickness in the normal direction; doing so over a centimeter-scale bubble while following sub-micrometre drainage is prohibitively multiscale.
- Curvature/spurious-current control is challenging at coarse resolution.
- Extracting clean persistent shared-film/triple-line geometry for the viewer requires reconstruction.

Decision:
- SECONDARY/reference and local resolved-liquid method.
- Do not designate an unresolved thickened-film VOF model as the Maximum Realism truth for a soap bubble in air.
- Prefer a Basilisk-class implementation for AMR reference cases because of its compact adaptive multiphase framework and suitability for convergence studies.

### 3.3 Level set

Representation:
- Signed-distance-like implicit interface field.

Strengths:
- Smooth normals and curvature are convenient.
- Topology change occurs naturally.
- Coupling to Eulerian Navier–Stokes is well established.
- Higher-order interface geometry is possible.

Weaknesses:
- Plain level set is not inherently mass conservative.
- Reinitialization can shift interfaces and change bubble volume.
- Shared films thinner than the Eulerian grid are still unresolved.
- Explicit identity/connectivity extraction is needed for Bubble Lab film/junction semantics.

Decision:
- NOT PRIMARY.
- May be used as an auxiliary geometry field or in a conservative coupled level-set/VOF method for local CFD backends.
- A pure level-set implementation must not be accepted without strict volume-drift benchmarking. [R7, R31–R32]

### 3.4 Front tracking

Representation:
- Explicit moving interface mesh coupled to an Eulerian bulk-fluid grid.

Strengths:
- Keeps bubble/film identity explicit.
- Direct access to surface tension, curvature, surfactant, and surface fields.
- Natural fit for a zero-thickness soap-film sheet separating gas regions of similar bulk properties.
- Clean canonical export of film and junction geometry.
- Supports surface transport without repeatedly reconstructing an implicit interface.

Weaknesses:
- Topology changes require explicit surgery/reconnection.
- Mesh tangling and remeshing need robust algorithms.
- Conservation depends on conservative coupling between Lagrangian front and Eulerian fluid.
- More custom implementation work than adopting a generic VOF solver.

Decision:
- PRIMARY representation for Maximum Realism bubble-scale soap-film dynamics.
- Couple to adaptive finite-volume gas flow.
- Use explicit topology events rather than relying on mesh self-intersection.

### 3.5 Phase field

Representation:
- Diffuse order parameter over finite interface thickness epsilon.

Strengths:
- Topology change is natural.
- Variational formulations can be thermodynamically consistent.
- Complex wetting and multicomponent coupling can be elegant.
- Convenient for some surfactant and contact-line models.

Weaknesses:
- Physical film thickness is not the numerical diffuse-interface width unless the simulation resolves the microscopic scale.
- Requires several cells across epsilon, increasing cost.
- Small bubbles and films suffer interface-thickness-dependent errors.
- Exact volume conservation requires care.
- Exporting a precise shared film/junction surface needs isosurface extraction.

Decision:
- RESEARCH/REFERENCE option, not default.
- Appropriate for specialized local studies of wetting/topological transitions if convergence with epsilon -> 0 is demonstrated.

### 3.6 OpenFOAM/Basilisk-class external solvers

Basilisk-class:
- Strong fit for adaptive Cartesian VOF, capillary-flow benchmarks, and localized resolved liquid structures.
- Current source distribution includes GNU GPL v3 license text.
- C99-based installation is compact enough for self-hosted Linux runners.
- Use behind a file/process adapter; do not link viewer semantics to Basilisk fields.

OpenFOAM-class:
- Mature general-purpose finite-volume CFD ecosystem, broad boundary-condition and multiphysics tooling, parallel execution, and established Linux deployment.
- The OpenFOAM Foundation distributes its current releases under GNU GPL v3.
- Heavier case/setup machinery than needed for the equilibrium solver and less natural for an explicit foam-sheet topology graph.
- Useful as a secondary CFD backend or cross-check where its models and infrastructure are advantageous.

Licensing/deployment rule:
- GPL backends may run as external executables/services with adapter-based data exchange.
- Any redistribution or derivative linking arrangement must be reviewed for the exact distribution model.
- Bubble Lab’s canonical contract and viewer must not require GPL-specific data structures or code linkage.
- Container images should pin backend source/version and record it in provenance. [R29, R31, R34–R36]

Official references checked for this decision:
- Surface Evolver overview: https://kenbrakke.com/evolver/html/intro.htm
- Surface Evolver home/download: https://www.kenbrakke.com/evolver/evolver.html
- Basilisk installation: https://basilisk.fr/src/INSTALL
- Basilisk GPL v3 text: https://basilisk.fr/src/COPYING
- OpenFOAM license: https://openfoam.org/licence/

## 4. Selected High Fidelity solver

### 4.1 Discretization

Use an oriented triangle complex with:
- vertex positions x_a;
- edge/facet connectivity;
- film-region ID per facet;
- ordered adjacent gas/exterior region IDs;
- explicit boundary/contact-line edges;
- explicit triple-line chains;
- per-film material/tension fields.

Region volumes are computed from oriented facets. Shared film facets contribute with opposite orientation to neighboring regions as required by the volume integral.

### 4.2 Objective

Minimize

E(x) = sum_f sigma_f A_f(x) + E_body(x) + E_wall(x) + E_optional(x)

subject to volume or gas constitutive constraints.

Default solution strategy:
1. Projected/nonlinear constrained optimization.
2. Exact or automatic-differentiated area/volume gradients where practical.
3. Augmented-Lagrangian or SQP/Newton correction for hard volume constraints.
4. Periodic quality-preserving remeshing.
5. Final Hessian/negative-mode check when claiming stable equilibrium.

Plain unconstrained gradient descent is allowed only as an initial relaxation stage, not as the sole production convergence criterion.

### 4.3 Discrete curvature and pressure

Do not infer physics from visually fitted spheres.

Compute curvature from the discrete first variation of area:
- the negative area gradient gives the discrete mean-curvature normal force;
- compare it directly against pressure-force contributions from volume constraints.

This makes the Young–Laplace residual consistent with the energy discretization.

Optional cotangent-Laplacian curvature may be exported as a diagnostic, but acceptance should use an energy-consistent force residual to avoid mismatched operators.

### 4.4 Mesh adaptation

Refine when any of these exceed configured thresholds:
- |kappa| h_mesh;
- curvature-gradient indicator;
- distance to contact/triple line;
- local force residual;
- thickness/surfactant gradient for coupled fields.

Coarsen only if:
- geometry error remains below target;
- no topology boundary is crossed;
- conservative field transfer passes mass checks.

Operations:
- edge split;
- edge collapse;
- edge flip;
- tangential vertex smoothing;
- junction-specific remeshing.

Each operation is deterministic under a stable ordering rule.

### 4.5 Convergence

Equilibrium is DELIVERABLE only when all active conditions are below tolerances:
- relative volume constraint residual;
- projected force residual;
- Young–Laplace residual;
- triple-line force residual;
- mesh-quality floor;
- energy decrease/stationarity;
- benchmark-specific geometry error.

Iteration count alone is never a convergence criterion.

## 5. Selected Maximum Realism solver

### 5.1 Global formulation

Use a hybrid front-tracking / adaptive Eulerian solver.

Lagrangian side:
- soap-film sheets;
- region identity;
- junction lines;
- thickness h;
- surfactant c_s;
- sheet material parameters;
- topology event locations.

Eulerian side:
- incompressible velocity u;
- pressure p;
- density/viscosity by gas/fluid region;
- optional temperature/species;
- adaptive finite-volume grid.

Coupling:
- interpolate Eulerian velocity to front;
- advect front in a conservative, geometry-aware manner;
- spread capillary and Marangoni traction to the Eulerian grid;
- enforce pressure/traction jumps;
- conservatively exchange any film/bulk species flux.

This is the default Maximum Realism architecture because it preserves the physically essential soap-film sheet while resolving bulk flow.

### 5.2 Adaptive grid

Use cell refinement around:
- film sheets and junctions;
- high curvature;
- vorticity/strain;
- topology events;
- local resolved liquid regions.

Far-field gas may be aggressively coarsened.

The interface and Eulerian refinement hierarchy are independent enough that the viewer is never tied to octree cells.

### 5.3 Pressure/velocity solve

Use a projection method or equivalent incompressible finite-volume formulation:
1. advect/update momentum;
2. apply body and interface forces;
3. solve pressure Poisson/projection;
4. correct velocity to satisfy divergence tolerance.

Pressure jump treatment must avoid smearing capillary pressure across too many cells. A ghost-fluid or sharp-interface treatment is preferred over a purely diffuse continuous-surface-force representation when pressure/curvature accuracy is the target.

A diffuse force form may be retained for early implementation only if the Young–Laplace and spurious-current benchmarks pass the resolution-dependent gates.

### 5.4 Surface transport

Surface fields h and c_s are solved on the front mesh after geometric advection and remeshing. Conservative remapping is mandatory.

The surface tension used by the traction calculation is updated from c_s and temperature before the next fluid coupling step.

### 5.5 Energy/conservation accounting

Report:
- bulk kinetic energy;
- sheet surface energy;
- gravitational potential;
- viscous dissipation estimate;
- work by external forcing;
- gas amount;
- liquid film mass in the reduced model;
- surfactant amount;
- topology-event jumps.

An event may change surface energy abruptly, but unexplained volume/gas creation is not acceptable.

## 6. Drainage, diffusion, and surfactant coupling

### 6.1 Default coupling

Initial production coupling is conservative operator splitting over macro-step Delta t:

1. Advance geometry/bulk flow over Delta t or subcycles.
2. Remap h and c_s conservatively onto the new surface.
3. Solve surfactant advection/diffusion/adsorption.
4. Update surface tension from the equation of state.
5. Solve film drainage with the new geometry/tension.
6. Solve gas permeation and update n_i.
7. Recompute gas pressure/volume closure.
8. Detect and localize topology events.
9. If an event occurs inside the step, roll back to the pre-event state and bisect/localize event time to the configured temporal tolerance.

For strongly coupled Marangoni/drainage cases, use Picard/Newton iteration inside the macro-step until h, c_s, sigma, and flow changes satisfy coupling tolerances.

### 6.2 Why not fully resolve film thickness globally

Suppose bubble radius is O(10^-2 m) while a drainage/rupture-relevant film may be O(10^-6 m) or below. A uniform 3D discretization would require O(10^4) cells across one radius merely to put one cell across the film, and several cells are actually needed. Three-dimensional cost is therefore prohibitive before accounting for time-step stiffness.

The sheet + lubrication + local-patch strategy explicitly acknowledges this scale separation. A simulation may only claim RESOLVED finite-thickness liquid where the local normal mesh actually resolves it.

## 7. Topology strategy

### 7.1 Event layer owns topology

Topology changes are discrete transactions:
- contact -> shared film;
- shared film -> rupture;
- rupture -> coalescence or opening to exterior;
- neck -> split;
- junction rearrangement (T1-like event) when enabled.

No remesher may silently change region adjacency.

### 7.2 Contact and shared-film creation

When two fronts approach:
1. detect minimum separation and relative normal speed;
2. create a contact candidate;
3. apply a model-specific contact/nucleation criterion;
4. construct a shared film patch with deterministic orientation/region ownership;
5. project/correct volume or gas state;
6. locally relax/regrid.

The trigger length must scale with physical/model parameters and mesh resolution. A contact event that moves materially under refinement fails convergence.

### 7.3 Coalescence/rupture

When a film ruptures:
- localize event time;
- remove film patch;
- merge or open gas regions;
- conserve species amount exactly in bookkeeping;
- conservatively transfer momentum/fields;
- remesh;
- continue from the non-equilibrium geometry.

### 7.4 Splitting

Splitting is enabled only after a neck-resolution criterion and refinement study demonstrate stable daughter volumes/event time. Until then it remains disabled rather than implemented as an arbitrary mesh cut. [R15–R16, R31–R33]

## 8. Determinism and reproducibility

High Fidelity target:
- same input, solver version, thread count, and platform -> bitwise-stable canonical scalar diagnostics and stable topology-event sequence where practical;
- deterministic mesh-operation ordering;
- fixed seed for stochastic rupture.

Maximum Realism target:
- deterministic mode fixes reduction ordering, partitioning, random seeds, adaptive-refinement tie breaks, and event ordering;
- performance mode may relax bitwise identity but must pass metric-level replay tolerances and preserve event sequence.

Every result records:
- git/backend version;
- compiler/container identifier;
- numerical method;
- mesh/timestep controls;
- nonlinear/linear tolerances;
- seed;
- thread/process count;
- feature-fidelity classification. [R31, R33]

## 9. CI and external-runner strategy

### 9.1 GitHub-hosted CI

Suitable for:
- document/schema checks;
- High Fidelity small equilibrium benchmarks;
- deterministic regression cases;
- small 2D/3D CFD smoke tests;
- mesh-convergence samples at modest resolution.

### 9.2 Self-hosted/external runner

Required for:
- high-resolution 3D transient runs;
- multi-level AMR studies;
- long drainage/coarsening runs;
- local resolved rupture/rim calculations;
- expensive convergence sweeps.

The test manifest, input scenario, container/backend version, and canonical result metrics must return to GitHub as reproducible artifacts even when computation occurs elsewhere. [R29–R32]

## 10. Canonical-contract export rules

A backend exports physical state, not native implementation objects.

Required mapping:
- native region IDs -> canonical BubbleState IDs;
- native front/VOF surface reconstruction -> SurfaceMesh;
- shared-film ownership -> FilmRegion adjacency;
- triple lines -> Junction entities;
- event graph -> TopologyGraph;
- scalar/field channels with units and location semantics;
- solver residuals/conservation -> SolverDiagnostics;
- backend/fidelity/version -> SimulationManifest provenance.

Prohibited:
- viewer depending on Surface Evolver .fe files;
- viewer requiring OpenFOAM mesh/case layout;
- viewer requiring Basilisk dump format;
- fake pressure/curvature fields generated solely for display. [R2, R22, R29, R33, R36]

## 11. Rejected shortcuts

The following may be useful only in the Interactive tier and may not be labeled High Fidelity or Maximum Realism:

- rigid-sphere collision as the authoritative contact model;
- spring networks without an energy/continuum derivation and convergence validation;
- screen-space deformation;
- metaball blending that changes appearance without physical state;
- forcing 120-degree-looking junctions in the renderer;
- post-hoc sphere fitting used as the only curvature/pressure computation;
- thickening a soap film in VOF without reporting that the thickness is numerical rather than physical. [R1–R2, R6–R9, R33, R39]

## 12. Staged implementation plan

### Stage A — equilibrium geometry core

Deliver:
- oriented triangle film network;
- volume constraints;
- surface-energy minimization;
- pressure multipliers;
- energy-consistent curvature residual;
- deterministic remeshing;
- sphere and zero-gravity benchmarks.

Exit condition:
- benchmark matrix geometry/Young–Laplace/convergence gates pass.

### Stage B — contact and foam network

Deliver:
- shared-film creation;
- unequal/equal pressure common films;
- triple junctions;
- contact angle;
- Plateau force residual;
- topology graph export.

Exit condition:
- two-bubble and 120-degree Plateau benchmarks pass under refinement.

### Stage C — reduced thin-film physics

Deliver:
- h field;
- lubrication drainage;
- gas permeation/coarsening;
- c_s field and tension equation of state;
- deterministic rupture/coalescence criteria.

Exit condition:
- conservative thickness/species transfer and event convergence tests pass.

### Stage D — transient front-tracked flow

Deliver:
- adaptive Eulerian gas flow;
- sharp capillary traction;
- front advection/remeshing;
- Marangoni coupling;
- gravity/wind;
- transient replay.

Exit condition:
- static bubble spurious-current, oscillation, volume, symmetry, and deterministic replay gates pass.

### Stage E — local resolved liquid / post-rupture physics

Deliver:
- VOF-AMR adapter;
- local Plateau-border/rim/droplet cases;
- coupling between resolved patches and sheet model where validated.

Exit condition:
- local refinement studies demonstrate independence from numerical interface thickness/cell size over the stated regime.

## 13. Decision matrix

| Criterion | Surface minimization | VOF + AMR | Level set | Front tracking | Phase field |
|---|---|---|---|---|---|
| Quasi-static film equilibrium | Excellent | Expensive | Good | Good | Good |
| Volume conservation | Excellent with constraints | Excellent | Weak unless corrected | Good with conservative coupling | Moderate/Good with constrained formulation |
| Pressure/curvature diagnostics | Excellent if energy-consistent | Good but sensitive to curvature reconstruction | Good geometry, pressure coupling varies | Excellent potential | Diffuse-interface dependent |
| Shared-film identity | Excellent | Difficult below grid scale | Difficult below grid scale | Excellent | Diffuse |
| Plateau triple lines | Explicit | Emergent only if resolved | Emergent/extracted | Explicit | Emergent/diffuse |
| Dynamic bulk flow | Not physical transient | Excellent | Excellent with CFD | Excellent | Excellent but diffuse |
| Natural topology change | Requires explicit surgery | Excellent | Excellent | Requires explicit surgery | Excellent |
| Thin real soap film at global scale | Excellent as sheet, thickness modeled separately | Prohibitively expensive to resolve | Same scale problem | Excellent as sheet | Requires artificial/diffuse width |
| Deterministic topology control | Excellent | Moderate | Moderate | Excellent | Moderate |
| Canonical geometry export | Direct | Reconstruction needed | Isosurface needed | Direct | Isosurface needed |
| Primary Bubble Lab role | High Fidelity | Local/reference CFD | Auxiliary | Maximum Realism global | Research option |

## 14. Final solver choices

High Fidelity quasi-static equilibrium:
- CHOSEN: Bubble Lab-native triangulated constrained surface-energy solver.
- OPTIONAL ORACLE: Surface Evolver for selected comparison cases.

Maximum Realism transient:
- CHOSEN: front-tracked effective soap-film sheet + adaptive Eulerian incompressible flow, with sharp surface-stress coupling.

Drainage/diffusion:
- CHOSEN: conservative surface lubrication + surfactant transport + permeability/gas-state modules on the film network.

Topology:
- CHOSEN: explicit event transactions and deterministic mesh surgery.
- SECONDARY: VOF-AMR for locally resolved liquid topology where normal film/rim thickness is actually resolved.

External backends:
- PREFERRED REFERENCE: Basilisk-class VOF/AMR for compact adaptive capillary benchmarks.
- SECONDARY GENERAL CFD: OpenFOAM-class adapter.

These choices preserve the core product promise: the highest-fidelity mode is constrained by physics and resolution, not by what happens to be easy to render in a browser. [R1, R33–R39]
