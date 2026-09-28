# Bubble Lab Physics Model

Status: implementation blueprint  
Task: bubble-physics-blueprint  
Requirements advanced: R1, R2, R4, R6–R18, R20–R24, R29–R36, R38–R39

## 1. Scope and conventions

Bubble Lab models soap bubbles, soap films, and foams rather than generic droplets. The important distinction is that a soap film has two gas–liquid interfaces separated by a thin liquid layer. A centimeter-scale bubble can therefore have a film thickness many orders of magnitude smaller than its radius. Resolving both interfaces and the liquid thickness everywhere in a full 3D domain is prohibitively multiscale for routine simulation.

The architecture therefore uses two mathematically compatible descriptions:

1. A zero-thickness film sheet for bubble-scale geometry and force balance.
2. A finite-thickness thin-film state on that sheet for drainage, surfactant, diffusion, and rupture physics.

Local fully resolved multiphase calculations may replace the sheet model in restricted patches or benchmark cases, but the global solver must not pretend that an unresolved micrometre/nanometre film is volumetrically resolved.

### 1.1 Surface-tension convention

Let gamma_s [N/m] be the surface tension of one gas–liquid interface. Let sigma_f [N/m] be the effective tension of a collapsed soap-film sheet. For a symmetric free soap film with two equivalent interfaces,

sigma_f = gamma_s,in + gamma_s,out ≈ 2 gamma_s.

All sheet equations below use sigma_f. With mean-curvature convention

kappa = 1/R1 + 1/R2,

the pressure jump across a sheet is

Delta p = sigma_f kappa.

For a spherical sheet of radius R,

Delta p = 2 sigma_f / R.

If a material model stores single-interface tension gamma_s instead, this becomes Delta p = 4 gamma_s / R for a symmetric soap bubble. This convention reconciles the R6 Young–Laplace form with the physically distinct two-interface soap-film interpretation. The canonical contract must state whether a tension field is single-interface gamma_s or effective sheet tension sigma_f; adapters may not silently convert between them. [R6, R12, R33]

### 1.2 Sign convention

Each oriented film sheet f has unit normal n_f pointing from region j to region i. Positive curvature is defined by kappa_f = div_s n_f. The traction jump condition is written

(p_i - p_j) - n_f · (tau_i - tau_j) · n_f = sigma_f kappa_f

for constant tension, with tangential Marangoni traction included separately when sigma_f varies.

The implementation may choose the opposite normal convention, but it must export the convention and use it consistently in pressure, curvature, and validation diagnostics.

## 2. Authoritative physical state

The physical state is independent of rendering. The minimum state needed by the solver family is:

- Region/bubble identity i and adjacency graph.
- Film-sheet geometry: vertices x_a, facets, oriented region ownership, boundary/contact-line edges, and triple-line/junction connectivity.
- Bubble gas volume V_i and either pressure p_i or gas amount n_i plus temperature T_i and constitutive law.
- Effective film tension sigma_f; optional per-side single-interface tensions gamma_s.
- Optional finite film thickness h_f(s,t) on each film region.
- Optional surfactant surface concentration c_s,f(s,t), surface equation-of-state parameters, and adsorption state.
- Optional film areal mass m_A = rho_l h and surface viscosity parameters.
- Region velocities and pressure fields for transient CFD.
- External-fluid properties rho, mu, temperature, species, imposed wind/flow, and turbulence parameters when enabled.
- Solid-boundary geometry, velocity, wettability/contact-angle data.
- Topology/event state: contact, shared film, junctions, rupture, coalescence, burst, split.
- Numerical provenance: mesh scale, timestep, tolerances, iteration counts, random seed, and model-fidelity disclosures. [R2, R11–R12, R17–R24, R29–R36]

A field absent from a lower-fidelity backend is absent, not fabricated.

## 3. Quasi-static governing model

### 3.1 Energy and constraints

For a film network with film regions f and gas regions i, the High Fidelity equilibrium backend minimizes

E = sum_f ∫_(S_f) sigma_f dA + E_body + E_wall + E_optional

subject to region constraints C_i = V_i - V_i,target = 0 when volume is prescribed.

For constant sigma_f this reduces to sum_f sigma_f A_f plus body/wall terms. The Lagrange multipliers lambda_i associated with volume constraints have pressure units and are interpreted as region pressures up to the chosen reference pressure.

The first variation gives the Young–Laplace relation on each smooth film:

(lambda_i - lambda_j) = sigma_f kappa_f

when body forces and surface-tension gradients are absent.

The discrete solver must therefore minimize energy and satisfy both volume residuals and force/curvature residuals; a low energy alone is not sufficient acceptance. [R6–R9, R32]

### 3.2 Gas constitutive modes

Bubble Lab supports two gas modes.

Prescribed-volume mode:
- V_i is constrained.
- p_i emerges as a Lagrange multiplier.
- This is the default for equilibrium geometry benchmarks.

Ideal-gas mode:
- p_i V_i = n_i R_g T_i for each gas species mixture under the ideal-gas approximation.
- n_i and T_i are state variables.
- Equilibrium minimizes the appropriate thermodynamic potential rather than enforcing V_i exactly; numerically, the pressure constitutive law replaces the hard volume constraint.

A practical isothermal free-energy term for an ideal gas is chosen so that -dF_gas/dV = p = nRT/V. One convenient form is

F_gas(V) = - n R_g T ln(V/V_ref) + constant.

Other equations of state may replace this without changing the geometry interface. [R7, R12, R34–R36]

### 3.3 Shared films

A contact between bubbles i and j creates a persistent film region only through a topology event; rigid collision response is not sufficient.

For a shared film,

p_i - p_j = sigma_ij kappa_ij

in static equilibrium, using effective sheet tension sigma_ij.

Consequences used as required diagnostics:

- Equal pressures p_i = p_j imply kappa_ij -> 0, so the common film approaches a plane away from junction/boundary layers.
- Unequal pressure gives signed constant mean curvature kappa* = (p_i - p_j)/sigma_ij when sigma is uniform.
- Film force balance must be compatible with the neighboring external films and the triple-line geometry. [R8, R32]

### 3.4 Plateau junction law

At a triple line with tangent t and three incident films, define m_f as the unit co-normal of film f: tangent to the film, normal to the triple line, and directed away from the line. Static force balance is

sum_(f=1..3) sigma_f m_f = 0.

For sigma_1 = sigma_2 = sigma_3 this implies 120 degree pairwise dihedral angles in the plane normal to the triple line.

The solver must measure both:
- force-balance residual r_J = |sum sigma_f m_f| / sum sigma_f;
- geometric angle error relative to the tension-weighted Neumann triangle.

For unequal tensions, 120 degrees is not the target; the vector balance above is authoritative. [R9, R22, R32]

### 3.5 Body forces and gravity

For resolved bulk phases, gravity enters the momentum equation as rho g.

For quasi-static zero-thickness geometry, hydrostatic pressure variation is included through

grad p_q = rho_q g

inside each region. Hence the local jump includes the density difference:

Delta p(x) = Delta p(x_ref) + (rho_i - rho_j) g · (x - x_ref).

Equivalently, the energy may include bulk gravitational potential

E_g,bulk = sum_q ∫_(Omega_q) rho_q (-g · x) dV.

When finite film mass is modeled, add

E_g,film = ∫_S rho_l h (-g · x) dA.

This distinguishes buoyancy from film drainage. For a very thin soap bubble in air, gravitational reshaping due to film mass can be smaller than drainage-induced thickness variation; the model must not attribute all visible asymmetry to buoyancy. [R10–R11, R14, R18]

### 3.6 Dimensionless regime selectors

For characteristic length L, speed U, density rho, viscosity mu, and effective sheet tension sigma_f, use:

- Bond number: Bo = |Delta rho| g L^2 / sigma_f.
- Capillary number: Ca = mu U / sigma_f.
- Weber number: We = rho U^2 L / sigma_f.
- Reynolds number: Re = rho U L / mu.
- Ohnesorge number: Oh = mu / sqrt(rho sigma_f L).
- Peclet number for surface surfactant: Pe_s = U L / D_s.
- Film slenderness: epsilon_h = h/L.

For a conventional one-interface droplet, sigma_f is replaced by that interface tension. For a collapsed symmetric soap film, sigma_f is the two-interface effective tension. These groups guide solver selection and timestep/refinement policy, not merely UI labels. [R10–R11, R14, R20, R33]

## 4. Transient bulk-fluid model

When transient ambient/internal flow is enabled, each resolved bulk phase obeys incompressible Navier–Stokes:

div u = 0

rho (du/dt + u · grad u) =
  - grad p
  + div[mu (grad u + grad u^T)]
  + rho g
  + f_interface
  + f_external.

At a tracked film sheet, normal and tangential traction jumps satisfy the surface-stress balance. For constant isotropic tension this reduces to capillary normal force sigma_f kappa n. With variable tension,

jump(T) n = sigma_f kappa n + grad_s sigma_f + additional surface-rheology terms.

The film moves with the local normal velocity consistent with the coupled fluid/sheet kinematics, except where a documented permeation model permits relative normal flux.

### 4.1 Why the global model is not a naïve two-phase VOF bubble

A real soap bubble is gas / thin liquid film / gas, not a gas region surrounded by a semi-infinite liquid. A standard gas–liquid two-phase VOF model would instead represent a gas bubble in liquid and would give wrong inertia, drainage, and film-volume physics for a soap bubble in air.

The default Maximum Realism global formulation is therefore:
- gas-domain Navier–Stokes on both sides of a front-tracked soap-film sheet;
- sheet capillary traction using sigma_f;
- optional sheet inertia and surface viscosity;
- thin-film drainage/surfactant fields on the sheet;
- local resolved liquid subdomains only where Plateau-border/rim/droplet physics is intentionally refined.

VOF-AMR remains valuable as a local/reference backend for cases where liquid thickness is intentionally resolvable, for droplets, and for post-rupture liquid structures. [R1, R11, R14–R16, R33–R35]

### 4.2 Surface inertia and rheology

At leading order, a very thin film may be treated as massless for bubble-scale equilibrium. When sheet inertia matters, areal mass is m_A = rho_l h and the surface momentum balance includes m_A D_s u_s/Dt.

Optional Boussinesq–Scriven surface rheology adds surface shear and dilatational viscosities mu_s and kappa_s through a surface viscous stress tensor. This is a Maximum Realism extension; lower tiers may omit it explicitly. [R10–R11, R14, R33]

## 5. Solid contact and contact angle

For a film meeting a solid boundary, the equilibrium contact-line condition follows variation of film plus solid surface energies. In scalar Young form,

gamma_SG - gamma_SL = gamma_s cos(theta_e)

for a single gas–liquid interface with equilibrium contact angle theta_e. For a collapsed soap film, each side must be accounted for; the effective geometric boundary condition is derived from the relevant per-side solid surface energies rather than blindly substituting sigma_f into the single-interface equation.

Implementation policy:
- The scenario stores a prescribed equilibrium contact angle or the underlying wall-energy parameters.
- High Fidelity imposes the geometric contact-angle constraint and allows contact-line motion toward equilibrium.
- Contact-angle hysteresis may be MODELED with advancing/receding bounds.
- Maximum Realism may add dynamic contact-angle and contact-line friction laws.
- Pinned contact lines are explicit boundary constraints, not numerical accidents. [R17, R33]

## 6. Thin-film drainage

Film thickness h(s,t) is not represented by geometric separation of two global meshes in the normal High Fidelity path. It is a field on the collapsed film mid-surface.

The thickness equation is conservative:

partial_t h + div_s(h u_s + q_drain) = S_h.

For a locally planar film with immobile interfaces, a baseline lubrication flux is

q_drain = - h^3/(12 mu_l) grad_s p_l
          + h^2/(2 mu_l) grad_s gamma_eff
          + q_body,

with coefficients changed when interface mobility/slip differs. The pressure in the film uses

p_l = p_capillary + Pi(h,c_s,chemistry) + p_hydrostatic,

where Pi is a disjoining-pressure model.

A practical disjoining-pressure closure may combine attractive van der Waals and stabilizing electrostatic/steric terms. A pure Hamaker attraction scales as |Pi_vdW| proportional to A_H / h^3; the exact sign convention and coefficients must be declared by the chosen material model.

Drainage is multiscale: the global film geometry can be millimetres/centimetres while h can approach micrometres or less. Therefore:

- Interactive: no PDE solve; optional empirical contact-age thickness law.
- High Fidelity: surface lubrication PDE on each film, coupled to geometry through capillary pressure and to events through h.
- Maximum Realism: same sheet PDE globally, with local resolved liquid patches only when needed.

This is a physically defensible reduced-order coupling, not VISUAL_ONLY thickness animation. [R14, R16, R22, R33]

## 7. Surfactant and Marangoni model

Let c_s be surface surfactant concentration on a film interface. The transport equation is

partial_t c_s + div_s(c_s u_s) =
  D_s Laplace_s c_s + J_ads/des.

Surface tension is a constitutive function gamma_s(c_s,T). A default elastic form suitable for small/moderate concentration changes is expressed through Gibbs elasticity E_G:

d gamma_s / d ln(c_s) = -E_G.

Thus a local increase in surfactant concentration lowers tension for E_G > 0, and the tangential stress balance includes

t · jump(T) n = grad_s gamma_s · t.

For a collapsed two-sided film, sigma_f = gamma_s,+ + gamma_s,- and its surface gradient is the sum of the per-side gradients.

The model must expose:
- c_s;
- the equation of state;
- diffusivity D_s;
- adsorption/desorption law if bulk exchange is enabled;
- whether the two film sides share one concentration or are tracked independently.

High Fidelity may use a single effective c_s field per film and quasi-static geometry coupling. Maximum Realism should transport c_s with the transient surface flow and apply Marangoni traction directly. [R14, R22, R33]

## 8. Gas diffusion and coarsening

Gas amount, not geometric volume, is the conserved quantity when diffusion is enabled.

For gas species k crossing a shared film between regions i and j, use the reduced permeation law

J_ij,k = P_k(c_s,T) / h_ij * (p_i,k - p_j,k)

with J in mol/(m^2 s) and permeability P_k chosen with consistent units.

Then

d n_i,k / dt = - sum_j ∫_(S_ij) J_ij,k dA - exterior_flux_i,k.

The gas constitutive law updates p_i from n_i, V_i, and T_i. This naturally drives pressure-mediated coarsening: for comparable tension, smaller cells have higher Laplace pressure and tend to lose gas.

Requirements:
- Disable means n_i is fixed except for topology events.
- Conservation across internal films must hold pairwise to roundoff/integration tolerance: flux lost by i is gained by j.
- Exterior dissolution/leakage, if enabled, is separately accounted.
- High Fidelity and Maximum Realism use the same species/flux abstraction, while their geometry/flow coupling differs. [R7, R12–R13, R31–R33]

## 9. Rupture, coalescence, burst, and splitting

Topology change is event-driven physical state transition, never a renderer action.

### 9.1 Rupture criterion

A shared film becomes eligible to rupture when all enabled material rules are satisfied. The baseline deterministic criterion is:

1. h_min <= h_crit;
2. the film has remained below h_crit for at least tau_nucleation, unless an instantaneous mechanical failure rule triggers;
3. optional local instability criterion based on disjoining-pressure slope, stress, or curvature is satisfied.

Stochastic nucleation may instead use hazard rate lambda(h,stress,c_s,T) with stored random seed. User-triggered burst bypasses the spontaneous nucleation test but still produces an explicit event record. [R15–R16, R31]

The microscopic rupture threshold is a constitutive/model parameter, so the trigger is MODELED even when h is numerically resolved by a lubrication equation.

### 9.2 Coalescence

Rupture of a film between gas regions i and j creates a topology transaction:

- remove the shared film;
- merge gas-region identity according to deterministic ID policy;
- conserve total gas amount species-by-species;
- conserve energy/momentum to the degree supported by the active transient model;
- create a non-equilibrium merged geometry;
- relax/evolve physically rather than snapping to a sphere.

For a prescribed-volume equilibrium benchmark, the merged target volume is V_new = V_i + V_j to numerical precision. For ideal gas, n_new = n_i + n_j and energy/temperature handling follows the thermodynamic closure. [R15, R32]

### 9.3 Burst to exterior

Bursting an external film opens a gas region to the exterior. The event must identify the removed film region and the changed region connectivity. Maximum Realism may later resolve rim retraction and droplets in local liquid domains; until then these products are explicitly NOT_IMPLEMENTED rather than drawn as if simulated. [R16, R33]

### 9.4 Splitting

Splitting is permitted only when the solver has an explicit neck-detection and topology-reconnection rule. A candidate geometric trigger is a neck radius falling below both:
- a resolution-aware threshold c_h h_mesh;
- a physical instability scale derived from the active capillary/inertial regime.

The event must conserve gas amount and assign daughter identities deterministically. Early High Fidelity may mark splitting NOT_IMPLEMENTED. Maximum Realism may enable it only after convergence tests show event time and daughter volumes stabilize with refinement. [R16, R31–R34]

## 10. Plateau borders and the zero-thickness limit

A zero-thickness film network can represent:
- film area and curvature;
- pressure jumps;
- triple-line force balance;
- topological adjacency;
- a geometric approximation to Plateau junctions.

It cannot by itself resolve:
- finite liquid cross-section of Plateau borders;
- liquid drainage through those channels;
- border capillary pressure from channel shape;
- vertex liquid reservoirs;
- microscopic disjoining forces across film thickness;
- rim formation after rupture;
- droplets generated by retracting films.

Therefore the global model treats Plateau borders as one of three explicit states:

1. GEOMETRIC: line junction only; appropriate for High Fidelity equilibrium geometry.
2. REDUCED_ORDER: line/1D channel stores cross-sectional area A_PB and solves mass transport with constitutive hydraulic resistance.
3. RESOLVED_LOCAL: a local 3D multiphase patch resolves the liquid channel and couples flux/traction back to the sheet network.

No fidelity label may call GEOMETRIC borders “resolved liquid channels.” [R9, R14, R16, R33]

## 11. Fidelity classification

The labels below are target behavior of each tier, not claims that code already exists.

| Phenomenon | Interactive | High Fidelity | Maximum Realism |
|---|---|---|---|
| Surface-energy relaxation | MODELED | RESOLVED | RESOLVED |
| Young–Laplace pressure/curvature | MODELED | RESOLVED | RESOLVED |
| Gas volume constraint | MODELED | RESOLVED | RESOLVED |
| Ideal-gas pressure state | MODELED | RESOLVED | RESOLVED |
| Shared-film geometry | MODELED | RESOLVED | RESOLVED |
| Triple-film force balance | MODELED | RESOLVED | RESOLVED |
| Finite Plateau-border liquid channel | NOT_IMPLEMENTED | MODELED | MODELED globally / RESOLVED_LOCAL when enabled |
| Gravity/hydrostatic equilibrium | MODELED | RESOLVED | RESOLVED |
| Ambient/internal flow | MODELED prescribed forcing | MODELED prescribed traction/pressure | RESOLVED bulk flow |
| Turbulence | NOT_IMPLEMENTED | NOT_IMPLEMENTED | MODELED unless DNS is explicitly selected |
| Wall/contact angle | MODELED | RESOLVED equilibrium BC | RESOLVED BC with optional MODELED dynamics |
| Gas diffusion/coarsening | NOT_IMPLEMENTED by default | MODELED permeation | MODELED permeation coupled to resolved flow |
| Film drainage | MODELED empirical law | MODELED lubrication PDE | MODELED global lubrication / RESOLVED_LOCAL patches |
| Surfactant concentration | NOT_IMPLEMENTED | MODELED effective surface field | RESOLVED surface transport with constitutive EOS |
| Marangoni traction | NOT_IMPLEMENTED | MODELED quasi-static | RESOLVED from transported surface tension field |
| Contact-to-film formation | MODELED | RESOLVED topology event with modeled nucleation length/time | RESOLVED topology event with modeled microscopic closure |
| Rupture trigger | MODELED | MODELED | MODELED unless microscopic film instability is locally resolved |
| Coalescence topology | MODELED | RESOLVED | RESOLVED |
| Post-coalescence oscillation | MODELED/damped | MODELED relaxation | RESOLVED by transient flow |
| Burst rim/droplets | VISUAL_ONLY only if clearly labeled, otherwise absent | NOT_IMPLEMENTED | MODELED or RESOLVED_LOCAL in later stage |
| Splitting | NOT_IMPLEMENTED | NOT_IMPLEMENTED initially | MODELED/RESOLVED topology after convergence qualification |

A feature may be downgraded at runtime if the selected backend cannot satisfy the target classification. The result contract must report the actual classification used. [R33–R35]

## 12. Numerical invariants and diagnostics

Every backend must provide diagnostics appropriate to its fidelity.

Mandatory geometry/thermodynamics diagnostics:
- V_i and relative volume error;
- A_f and total area;
- p_i;
- signed mean curvature statistics per film;
- Young–Laplace residual;
- junction force residual and angles;
- total gas amount by species when diffusion is enabled;
- topology event sequence and timestamps.

Equilibrium solver diagnostics:
- energy E;
- constraint residual norm;
- projected force/gradient norm;
- mesh quality;
- refinement level;
- remesh count.

Transient solver diagnostics:
- timestep dt and CFL;
- capillary timestep restriction indicator;
- mass/volume conservation;
- linear/nonlinear residuals;
- kinetic, surface, and gravitational energy budget;
- maximum divergence error;
- interface advection error;
- event localization error.

Thin-film diagnostics:
- h_min, h_mean, h_max;
- thickness mass balance;
- surfactant total amount;
- diffusive gas flux balance.

These diagnostics are validation inputs, not optional debug cosmetics. [R20–R24, R31–R33]

## 13. Resolution and timestep policy

Let h_mesh be a representative local surface/bulk cell size.

For geometry:
- curvature-dependent acceptance must be reported against h_mesh/R;
- local refinement is required where |kappa| h_mesh is large, near contacts/junctions, or where curvature gradients exceed a configured threshold.

For transient capillary flow:
- timestep must obey both advective CFL and capillary-wave stability restrictions appropriate to the discretization;
- event detection for rupture/coalescence must localize event time to O(dt) and demonstrate convergence under dt refinement.

For thin-film drainage:
- surface mesh spacing must resolve thickness-gradient length scales even though it does not resolve h in the normal direction;
- implicit/stiff integration is allowed where disjoining pressure creates severe timescale separation.

The solver may remesh, but conservative transfer of volume, gas amount, h-weighted liquid mass, and surfactant must be measured after each transfer. [R20, R31–R32]

## 14. Requirement traceability

- R1, R39: bubble/foam physics is authoritative; no rigid-sphere or graphics substitute.
- R2, R33: rendering is separate and every feature has a declared physical fidelity.
- R4, R12: state supports radius/volume, velocity, gas pressure, temperature, species, and film properties.
- R6–R9: surface energy, Young–Laplace, shared films, and Plateau force balance define equilibrium.
- R10–R11, R18: gravity, buoyancy, fluid motion, and external forcing are explicit.
- R13–R14: gas transfer, drainage, surfactant, and Marangoni are reduced-order physical modules where full resolution is multiscale-prohibitive.
- R15–R16: coalescence, rupture, burst, and later splitting are explicit topology events.
- R17: solid contact and wettability are boundary physics.
- R20–R24: resolution controls and physical diagnostics are solver outputs.
- R29–R31, R34–R36: backend-neutral state, replay, and reproducibility remain mandatory.
- R32: analytical and convergence benchmarks are merge gates.
- R38: the combined model covers the physics needed by the integrated laboratory.

## 15. Implementation handoff

The first High Fidelity solver Worker should implement the following subset without inventing new physics:

1. Oriented triangulated film network with region ownership.
2. Effective sheet tension sigma_f and constrained region volumes.
3. Surface-energy minimization with adaptive remeshing.
4. Pressure as volume-constraint multiplier.
5. Young–Laplace residual from discrete curvature.
6. Shared-film topology and equal/unequal-pressure equilibrium.
7. Triple-line force balance and 120-degree equal-tension benchmark.
8. Hydrostatic/body-energy terms and contact-angle boundary condition.
9. Deterministic output of all diagnostics needed by the benchmark matrix.

Drainage, diffusion, surfactant transport, microscopic rupture, bulk transient CFD, and split events should be implemented as separate modules after the geometry/pressure core passes convergence benchmarks.
