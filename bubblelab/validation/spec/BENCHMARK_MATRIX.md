# Bubble Lab Benchmark Matrix

Status: validation specification  
Task: bubble-physics-blueprint  
Requirements advanced: R6–R9, R15, R18, R20–R24, R31–R35, R38

## 1. Validation philosophy

Bubble Lab physics is accepted by analytical identities, conservation, symmetry, and convergence, not by visual similarity.

Every benchmark result must record:
- backend and version;
- fidelity tier and active feature classifications;
- geometry resolution h;
- bulk-grid resolution dx where applicable;
- timestep dt;
- nonlinear/linear tolerances;
- remeshing/adaptivity settings;
- seed;
- thread/process count;
- measured errors and residuals;
- whether the run is in the asymptotic convergence regime.

A fixed tolerance is never sufficient by itself. The acceptance rule combines:
1. an absolute or relative fine-resolution target;
2. a resolution-scaled bound;
3. an observed convergence-order check where a smooth analytical solution exists.

## 2. Common notation

For a characteristic bubble radius R:
- eta_s = h/R, where h is the RMS or median local surface-edge length and h_max/R is also reported.
- eta_b = dx/R for Eulerian bulk grids.
- eta_t = dt/tau, with tau chosen from the dominant physical timescale.

For capillary dynamics use the capillary time

tau_sigma = sqrt(rho R^3 / sigma_f)

with the density appropriate to the dominant inertial phase and effective sheet tension sigma_f.

For a measured scalar q with exact/reference q*,

e_rel(q) = |q - q*| / max(|q*|, q_scale_floor).

For a field residual r(s),

e_L2(r) = sqrt( ∫ r^2 dA / ∫ dA ) / r_scale.

For three resolutions h1 > h2 > h3 with refinement ratio approximately r = h1/h2 = h2/h3, observed order is

p_obs = ln(e1/e2) / ln(r)

and independently ln(e2/e3)/ln(r). When the finest error reaches nonlinear/roundoff/model floors, order checks may use the two coarser asymptotic levels and must report the floor.

## 3. Standard resolution ladder

Unless a benchmark defines a more appropriate scale, use:

- Coarse: eta_s <= 0.12
- Medium: eta_s <= 0.06
- Fine: eta_s <= 0.03
- Verification: eta_s <= 0.015 where cost permits

For bulk AMR:
- Coarse interface-region eta_b <= 0.08
- Medium eta_b <= 0.04
- Fine eta_b <= 0.02

The actual element distribution and h_max must be reported; a tiny average h cannot hide a coarse high-curvature patch.

Time refinement uses at least:
- dt
- dt/2
- dt/4

at fixed spatial resolution when measuring temporal order or event-time convergence.

These are default benchmark scales, not user-facing production presets.

## 4. Tolerance scaling policy

For a quantity expected to converge with order p,

tol(h,dt) = C_h (h/R)^p + C_t (dt/tau)^q + tol_solver + tol_floor.

The benchmark defines C_h, C_t, p, q, and the fine-resolution cap.

A run fails if:
- error exceeds tol;
- refinement does not reduce error in the expected asymptotic trend;
- a tighter nonlinear tolerance materially changes the result, meaning discretization error was not isolated;
- conservation error spikes at remesh/topology events without an accounted physical source.

The constants below are intentionally small enough to demand convergence, but they are not machine-epsilon fantasies for piecewise-linear curvature.

## 5. Benchmark summary matrix

| ID | Benchmark | Primary metric | Fine target | Convergence target | Requirements |
|---|---|---|---|---|---|
| B01 | Sphere area/volume geometry | e_A, e_V | each <= 2e-3 at eta_s <= 0.03 | p_obs >= 1.7 | R7, R32 |
| B02 | Young–Laplace sphere pressure | e_LP | <= 5e-3 at eta_s <= 0.03 | p_obs >= 1.5 | R6, R32 |
| B03 | Static volume drift | max_t e_V(t) | <= 1e-5 HF; <= 5e-4 transient fine | decreases with h/dt; no event spikes | R7, R31–R32 |
| B04 | Equal-pressure common-film flatness | kappa_rms L and plane deviation | <= 3e-3 | p_obs >= 1.5 | R8, R32 |
| B05 | Unequal-pressure film curvature | e_kappa and pressure residual | <= 1e-2 | p_obs >= 1.3 | R8, R32 |
| B06 | Equal-tension Plateau junction | angle and force residual | RMS angle <= 1.0 deg; r_J <= 5e-3 | angle error decreases at least first order | R9, R22, R32 |
| B07 | Static equilibrium stability | drift, force, energy | no secular drift; normalized force <= solver gate | invariant under smaller step/tolerance | R7, R32 |
| B08 | Zero-gravity symmetry | symmetry norm, centroid drift | <= 2e-3 geometry; centroid <= 1e-4 R | p_obs >= 1.5 where applicable | R18, R32 |
| B09 | Mesh-refinement convergence | Richardson/order metrics | method-specific | smooth geometry >= 1.7; curvature >= 1.3 | R20, R32 |
| B10 | Coalescence conservation | gas/volume, momentum as applicable | bookkeeping <= 1e-12; geometric/transient <= solver budget | event result converges with h/dt | R15, R31–R32 |
| B11 | Deterministic replay | hashes/event sequence/metric norms | exact in deterministic same-platform mode | no divergence with rerun | R31 |
| B12 | Spurious-current static bubble | max velocity / capillary scale | <= 1e-3 fine | decreases under dx refinement | R6, R11, R32 |
| B13 | Surface-energy monotonic relaxation | energy increase count/magnitude | no unexplained increase above 1e-10 relative per accepted step | stable under refinement | R6–R7 |
| B14 | Conservative remeshing | volume, h-mass, surfactant mass | scalar loss <= 1e-10 where exact transfer promised | independent of remesh frequency | R7, R14, R31 |
| B15 | Diffusion pair conservation | total gas amount | <= 1e-10 relative internal-transfer drift | temporal order >= 1.0 | R13, R31 |
| B16 | Rupture/event-time convergence | event time and pre-event state | relative time shift <= 2% fine-vs-finer | decreases with dt and h | R15–R16, R31 |

B01–B11 are the minimum matrix required by the assignment. B12–B16 are mandatory before the corresponding transient/thin-film features can claim validation.

## 6. B01 — Sphere area and volume

### Setup

Single isolated spherical film, zero gravity, uniform sigma_f, no external flow. Prescribe radius R through target volume

V* = 4 pi R^3 / 3.

Analytical area:

A* = 4 pi R^2.

Initialize with an icosphere or another triangulation that does not hard-code exact area/volume.

### Metrics

e_A = |A_num - A*| / A*

e_V = |V_num - V*| / V*

sphericity error may additionally use radial RMS deviation after removing centroid:

e_r = sqrt(mean((|x_a-x_c|-R)^2))/R.

### Acceptance

At eta_s <= 0.03:
- e_A <= 2e-3;
- e_V <= 2e-3 before hard constraint correction is credited;
- after constrained solve, final volume residual must also satisfy the solver constraint gate, normally <= 1e-8 for High Fidelity.

For piecewise-linear triangles on a smooth sphere:
- area and volume geometric errors should approach second order under regular refinement;
- require p_obs >= 1.7 across an asymptotic pair.

A hard volume constraint can make e_V tiny even on a poor mesh, so e_A and e_r remain necessary.

## 7. B02 — Young–Laplace spherical pressure

### Setup

Same geometry as B01.

Sheet convention:
- exact Delta p* = 2 sigma_f / R.

If the material input is single-interface soap-film tension gamma_s:
- sigma_f = 2 gamma_s;
- exact Delta p* = 4 gamma_s / R.

The benchmark manifest must record which convention is used.

### Metrics

e_LP = |Delta p_num - Delta p*| / |Delta p*|.

Energy-consistent residual:

r_LP = RMS[ (Delta p_num - sigma_f kappa_discrete) ] / (sigma_f/R).

### Acceptance

At eta_s <= 0.03:
- e_LP <= 5e-3;
- r_LP <= 1e-2;
- p_obs >= 1.5 for pressure/curvature error.

If an energy-minimizing solver reports an accurate Lagrange-multiplier pressure but a separate visualization curvature estimator does not converge, the physical solve may pass while the exported curvature channel fails its own diagnostic acceptance. The two errors must not be conflated.

## 8. B03 — Volume conservation/drift

### Setup A: High Fidelity equilibrium

Relax a perturbed sphere and a two-bubble configuration with fixed target volumes.

Metric:

e_V,max = max_i |V_i - V_i,target| / V_i,target.

Acceptance:
- final e_V,max <= max(1e-8, 10 * nonlinear_constraint_tolerance);
- no remesh operation may increase a previously converged volume error by more than 5 times the local solver tolerance without immediate corrective projection.

### Setup B: transient no-diffusion

Advect/deform a bubble for at least 10 characteristic times with diffusion and topology events disabled.

Metric:

e_V,drift(t) = |V(t)-V(0)|/V(0).

Fine target:
- <= 5e-4 at eta_b <= 0.02 and temporally converged settings.

Acceptance also requires:
- drift decreases under spatial/time refinement;
- no monotonic secular trend larger than the fitted discretization error budget.

A transient method that visually preserves shape but loses volume fails R7.

## 9. B04 — Equal-pressure common-film flatness

### Setup

Two bubbles with equal pressure and equal film tension, zero gravity. Construct a stable shared film bounded by a symmetric junction/contact ring.

Analytical target for the common film away from the boundary layer:

kappa* = 0.

Fit the best plane to vertices/facets in the central 60% of the film by geodesic distance from the boundary.

### Metrics

Dimensionless RMS curvature:

e_k0 = kappa_rms L_f.

Normalized plane deviation:

e_plane = RMS(distance_to_best_plane) / L_f.

Pressure/curvature residual:

r_p = RMS(Delta p - sigma_f kappa)/(sigma_f/L_f).

### Acceptance

At eta_s <= 0.03 relative to film span:
- e_k0 <= 3e-3;
- e_plane <= 3e-3;
- r_p <= 1e-2;
- p_obs >= 1.5 for e_plane or e_k0.

The outer boundary/junction layer is excluded only by the declared central-region rule; manual point selection is prohibited.

## 10. B05 — Unequal-pressure common-film curvature

### Setup

Two bubbles sharing a film with known pressure difference Delta p and uniform sigma_f. Choose geometry where the central common film is expected to have approximately constant mean curvature and remains away from a wall.

Target:

kappa* = Delta p / sigma_f.

### Metrics

Area-weighted curvature error:

e_kappa = sqrt(∫(kappa-kappa*)^2 dA / A) / max(|kappa*|,1/L_f).

Mean relation error:

e_mean = |mean(kappa)-kappa*| / |kappa*|.

### Acceptance

At eta_s <= 0.03:
- e_mean <= 1e-2;
- e_kappa <= 2e-2;
- p_obs >= 1.3.

The sign of curvature must reverse when the pressure ordering is reversed. A correct magnitude with wrong orientation fails.

## 11. B06 — Three-film 120-degree Plateau junction

### Setup

Three films of equal effective tension meeting along a junction in zero gravity with symmetric far-field constraints.

Analytical target:
- pairwise angles in the normal plane are 120 degrees;
- vector force sum is zero.

### Metrics

For samples along the central 60% of the triple line:

e_theta,rms = sqrt(mean((theta_k - 120 deg)^2)).

e_theta,max = max |theta_k - 120 deg|.

Force residual:

r_J = |sum_f sigma_f m_f| / sum_f sigma_f.

### Acceptance

At eta_s <= 0.03:
- e_theta,rms <= 1.0 degree;
- e_theta,max <= 2.0 degrees;
- r_J <= 5e-3.

Refinement:
- RMS angle error must decrease approximately first order or better;
- require p_obs >= 0.9 unless the fine run is demonstrably at the nonlinear tolerance floor.

### Unequal-tension extension

For sigma_1, sigma_2, sigma_3 satisfying triangle inequality, compare against the Neumann force triangle, not 120 degrees. Require r_J <= 5e-3 and angle errors <= 1.5 degrees fine.

## 12. B07 — Static equilibrium stability

### Setup

Take converged B01, B04, and B06 states and continue simulation/relaxation for:
- 100 accepted equilibrium iterations with no intended geometry change; or
- at least 5 capillary times in a transient backend initialized from static equilibrium.

### Metrics

- centroid drift / R;
- area drift;
- volume drift;
- maximum vertex normal displacement per accepted equilibrium iteration / R;
- projected force residual;
- transient max velocity normalized by capillary speed U_sigma = sqrt(sigma_f/(rho R));
- energy change.

### Acceptance — High Fidelity

After convergence:
- normalized projected force <= max(1e-8, 10 * configured gradient tolerance);
- centroid drift <= 1e-8 R absent remeshing;
- relative energy change over the hold period <= 1e-10 except conservative remesh roundoff.

### Acceptance — transient

Fine configuration:
- max |u|/U_sigma <= 1e-3 for a nominally static case after startup projection;
- no growing oscillatory mode;
- pressure and geometry remain within the B01/B02 spatial error budgets.

## 13. B08 — Zero-gravity symmetry

### Setup

Run a symmetric initial condition with g=0:
- isolated perturbed sphere with symmetric perturbation;
- equal two-bubble pair;
- symmetric three-bubble junction.

Repeat with the entire input rotated by an arbitrary non-grid-aligned rotation.

### Metrics

Map the rotated result back and compare invariant quantities.

- centroid difference / R;
- volume/area difference;
- radial or surface-distance L2 norm after registration;
- pressure difference;
- topology/event sequence.

### Acceptance

High Fidelity fine:
- centroid discrepancy <= 1e-4 R;
- registered geometry L2 discrepancy <= 2e-3 R;
- scalar invariant relative errors <= 2e-4.

Transient fine:
- registered geometry difference <= 5e-3 R over one capillary time;
- differences decrease with grid refinement.

This benchmark detects hidden axis bias, gravity leakage, and AMR orientation artifacts.

## 14. B09 — Mesh-refinement convergence

### Purpose

No physical feature may be declared validated solely at one resolution.

### Required sequence

For each smooth benchmark, run at least three resolution levels with approximately constant refinement ratio.

Report:
- e(h);
- p_obs for each adjacent pair;
- Richardson-extrapolated q_ext where meaningful;
- estimated Grid Convergence Index or equivalent uncertainty estimate.

### Acceptance targets

For the triangulated equilibrium solver:
- area/volume on smooth surfaces: p_obs >= 1.7;
- energy-consistent curvature/pressure: p_obs >= 1.3;
- Plateau angle: p_obs >= 0.9 due to junction singularity/discrete-line effects.

For transient finite-volume/interface coupling:
- smooth advection/velocity quantities: demonstrate at least first-order global convergence;
- a claimed second-order scheme must measure p_obs >= 1.7 on a benchmark designed to exercise its second-order regime;
- topology-event times are validated separately because discontinuous events need not exhibit smooth second-order convergence.

If p_obs is lower, the backend must report the measured order and use it in tolerance scaling rather than assume design order.

## 15. B10 — Coalescence conservation

### Setup

Two closed gas bubbles form a shared film and are forced to coalesce at a controlled event time. Run both:
- prescribed-volume equilibrium event;
- ideal-gas/species transient event where supported.

### Exact bookkeeping checks

Before event:
N_before,k = n_i,k + n_j,k.

After event:
N_after,k = n_new,k.

Acceptance:
- |N_after,k-N_before,k| / max(N_before,k,N_floor) <= 1e-12 for internal bookkeeping in double precision.

For prescribed-volume mode:
- target V_new must be assigned as V_i + V_j with relative arithmetic discrepancy <= 1e-14.

### Geometric/transient checks

After topology surgery/projection:
- actual volume error obeys the B03 solver budget;
- no unaccounted bubble disappears;
- surface energy change is reported, not artificially forced to zero.

When momentum is an active resolved variable:
- linear momentum change across the instantaneous bookkeeping event must be <= 1e-8 relative before subsequent capillary/body-force evolution, unless an explicit impulse model is active and logged.

### Event convergence

Repeat with h, h/2 and dt, dt/2:
- post-event total conserved quantities must remain within their conservation gates;
- event time and immediate post-event coarse observables must converge;
- fine-vs-finer event-time shift <= 2% of the characteristic contact/drainage time.

## 16. B11 — Deterministic replay

### Same-build deterministic mode

Run identical scenario twice with identical:
- solver build;
- platform/container;
- thread/process count;
- seed;
- adaptive thresholds.

Require:
- identical topology event sequence;
- identical IDs;
- identical mesh-operation counts;
- identical canonical scalar diagnostics bit-for-bit where deterministic mode promises bitwise reproducibility;
- canonical frame hash equality after normalization of intentionally nonsemantic metadata such as wall-clock runtime.

### Cross-platform metric replay

Bitwise identity across compilers/architectures is not universally required. Instead require:
- same topology event sequence;
- event-time difference <= max(2 dt_fine, 1e-6 tau_characteristic) for non-chaotic benchmark cases;
- scalar relative difference <= 10 * solver tolerance or the spatial/temporal discretization uncertainty, whichever is larger;
- geometry registered L2 difference remains within the benchmark’s fine-resolution tolerance.

A backend that is intrinsically chaotic/turbulent must validate statistical reproducibility separately and may not use that exception for the deterministic baseline scenarios. [R31]

## 17. B12 — Spurious-current static bubble

Required before Maximum Realism capillary flow is accepted.

### Setup

Static spherical bubble/film with no gravity, no imposed flow.

### Metric

Capillary speed:

U_sigma = sqrt(sigma_f/(rho R)).

Spurious-current ratio:

e_u = max |u| / U_sigma.

### Acceptance

At eta_b <= 0.02:
- e_u <= 1e-3 after initial pressure projection;
- pressure error also passes B02-equivalent target;
- e_u decreases under dx refinement.

Persistent non-decaying vortices at a nominally static interface fail even if volume is conserved.

## 18. B13 — Surface-energy relaxation

### Setup

Perturb a volume-constrained sphere and a two-bubble film network away from equilibrium.

### Metrics

E_n per accepted relaxation step and volume residual.

### Acceptance

For a line-search/trust-region step accepted as energy descent:
- E_(n+1) <= E_n + 1e-10 |E_n|.

Temporary energy increases are allowed only for a documented Newton/trust-region globalization step that subsequently lowers the merit function; the raw and merit energies must both be logged.

Final state must pass B01/B02 or B04/B05 as applicable.

## 19. B14 — Conservative remeshing

### Setup

Repeatedly refine/coarsen/flip/smooth a static film without physical evolution.

Tracked invariants:
- gas volume;
- gas amount;
- integrated film liquid volume ∫ h dA when h exists;
- integrated surfactant amount ∫ c_s dA.

### Acceptance

If the transfer algorithm claims exact conservative remapping:
- relative invariant change per remesh <= 1e-10;
- after 100 remesh cycles cumulative drift <= 1e-8.

If a quantity is only approximately conservative:
- its remesh error must scale at least second order with h on smooth fields;
- cumulative error must remain below one tenth of the physical benchmark tolerance so remeshing is not the dominant error source.

## 20. B15 — Gas diffusion pair conservation

### Setup

Two bubbles connected by a shared film, diffusion enabled, exterior flux disabled. Use unequal pressures to drive transfer.

### Metric

N_total,k(t) = n_1,k + n_2,k.

### Acceptance

- relative drift in N_total,k <= 1e-10;
- individual fluxes are equal and opposite to integration tolerance;
- dt refinement demonstrates temporal order >= 1.0;
- small bubble shrinks and large bubble grows when the constitutive law predicts that direction.

This validates conservation, not the empirical permeability coefficient itself.

## 21. B16 — Rupture and event-time convergence

### Setup

Use a drainage case where h_min crosses h_crit smoothly.

Reference event time is obtained by temporal refinement.

### Metrics

- rupture time t_r;
- h_min just before event;
- gas volumes/amounts immediately before and after;
- event location.

### Acceptance

Between fine and verification runs:
- |t_r,fine - t_r,verify| / tau_case <= 0.02;
- pre-event h_min differs by <= 2% of h_crit;
- conserved quantities satisfy B10;
- event location differs by <= 2 h_fine along the film.

A rupture criterion that triggers at a fixed mesh index or visual overlap rather than physical h/stress state fails.

## 22. Solver-tolerance isolation

Before claiming spatial convergence, repeat the fine run with:
- nonlinear tolerance reduced by 10x;
- pressure/linear tolerance reduced by 10x where applicable.

The target observable must change by less than 20% of the measured fine-grid discretization error.

If it changes more, the run is solver-tolerance limited and cannot be used to estimate spatial order.

## 23. Adaptive-mesh reporting

For AMR runs, a single nominal dx is insufficient. Report:
- minimum dx;
- area fraction of interface at each refinement level;
- curvature-weighted mean dx;
- maximum dx on any interface cell;
- refinement thresholds.

Convergence comparisons should use the interface-region effective resolution and should include a uniform-grid or tightly controlled AMR reference for at least one case to ensure threshold changes are not masquerading as grid convergence.

## 24. Topology and discontinuity reporting

Smooth convergence expectations do not apply across a topology discontinuity in the same way as static geometry. For event problems validate separately:

1. pre-event smooth-state convergence;
2. event-time convergence;
3. conservation across the transaction;
4. post-event observable convergence after a fixed physical time offset.

This avoids declaring failure merely because two discretizations rupture on adjacent timesteps while still requiring the rupture time to converge.

## 25. Pass levels by fidelity tier

### Interactive

Interactive mode is not allowed to inherit High Fidelity validation claims. It must:
- pass deterministic state bookkeeping;
- preserve declared conserved quantities within its own documented tolerance;
- report MODELED/VISUAL_ONLY classifications;
- never use a renderer-only result to satisfy B01–B16.

### High Fidelity

Before the equilibrium backend is release-qualified it must pass:
- B01, B02, B03A, B04, B05, B06, B07 HF, B08 HF, B09, B11, B13;
- B14 when remeshing transports physical fields;
- B10/B15/B16 when those modules are enabled.

### Maximum Realism

Before the transient backend is release-qualified it must pass:
- B01/B02-equivalent static geometry/pressure checks;
- B03B;
- B07 transient;
- B08 transient;
- B09;
- B11;
- B12;
- B14;
- plus B10/B15/B16 for enabled event/diffusion/rupture modules.

## 26. Regression policy

Each validated benchmark stores:
- input scenario;
- exact backend/version;
- scalar metric JSON;
- convergence table;
- optional canonical geometry/frame artifact.

A pull request fails physics regression if:
- a required fine target is exceeded;
- observed order falls below its gate without an explained numerical-floor condition;
- conservation worsens by more than 2x while remaining nominally below a fixed threshold;
- topology/event sequence changes in a deterministic benchmark without an intentional model change;
- feature classification is upgraded without adding the corresponding benchmark.

Numerical improvements may change golden geometry. Golden files are updated only with a metric/convergence justification, never because the picture “looks better.”

## 27. Requirement traceability

- R6: B02 and B12 validate pressure/capillary behavior.
- R7: B01, B03, B13, B14 validate area/volume/energy behavior.
- R8: B04 and B05 validate common-film mechanics.
- R9: B06 validates Plateau force/angle equilibrium.
- R13–R14: B14–B16 validate conservative thin-film/diffusion/event coupling.
- R15–R16: B10 and B16 validate topology-event conservation and convergence.
- R18: B08 validates zero-gravity symmetry.
- R20–R24: every run reports resolution, residuals, and physical diagnostics.
- R31: B11 plus conservation/event metadata validate replay.
- R32: B01–B11 directly implement the required numerical validation set.
- R33–R35: pass levels are fidelity-specific and do not permit approximate tiers to inherit stronger claims.
- R38: the matrix provides objective integration gates for the physical behaviors required by final acceptance.
