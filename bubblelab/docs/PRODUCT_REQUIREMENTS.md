# Bubble Lab Product Requirements Baseline

Product-owned source: `bubblelab/docs/PRODUCT_REQUIREMENTS.md`

Restored: 2026-10-01
Original acceptance: 2026-09-18
Historical source: commit `be27cbe8e0c03f27f9cb019d04658e72968a74f1`, `orchestra/REQUIREMENTS.md`

This file restores the accepted R1-R39 Bubble Lab Product requirements into the Product-owned repository boundary. It preserves the original requirement intent while deliberately **not** restoring Agent Control Plane assets such as `orchestra/`, `agent/`, `tasks/`, queue/claim state, or worker instructions.

R37 records the accepted ability to decompose work across specialized workers. It does not require Control Plane implementation or state to live in this Product repository.

## R1. Product intent and priorities
- Build a 3D experimental environment for real soap-bubble/foam physics.
- Priority order: physical validity, numerical stability, phenomenon consistency, observability/control, visuals, speed.
- Do not replace the physical model with rigid spheres or appearance-only deformation.
- High-fidelity/maximum-realism mode is the design reference.

## R2. Physics/rendering separation
- Solver state and render state are separate.
- Visual interpolation, shaders and thin-film optics may improve appearance but must not alter physical results.

## R3. 3D navigation and input
- Full 3D scene.
- Rotate, zoom, pan, change focus, focus selected bubble, fit all.
- Mouse/desktop and touch/iPhone support.

## R4. Bubble creation
- Add bubbles at arbitrary time.
- Required inputs: X/Y/Z position, radius or volume, X/Y/Z initial velocity.
- Extensible inputs: gas, pressure, temperature, film thickness, surface tension, viscosity, density, initial shape/deformation, explicit ID.
- Click/tap placement mode.

## R5. Bubble deletion and selection
- Select in 3D, individual delete, delete all, highlighted selection.
- Multiple selection desirable.

## R6. Surface tension and Young-Laplace
- Surface energy drives shape relaxation.
- Young-Laplace relation is a governing validation principle:
  deltaP = gamma(1/R1 + 1/R2), and deltaP = 2 gamma / R for a sphere.
- Smaller bubbles must exhibit higher pressure for equal tension under comparable conditions.
- Do not substitute a generic spring-only model as the physical truth.

## R7. Volume and surface-energy behavior
- Normal operation conserves gas volume unless an enabled process changes it.
- Quantify numerical volume drift.
- Under volume constraints, surfaces relax toward lower area/energy and physically valid equilibrium.

## R8. Bubble contact and shared films
- Contacts deform surfaces instead of only applying rigid collision impulses.
- Persistent common films are representable.
- Common-film curvature follows pressure difference; equal-pressure two-bubble film approaches flatness.

## R9. Plateau laws
- Three-film equilibrium targets approximately 120 degrees for equal film tensions.
- 3D Plateau-border/multi-bubble geometry is a target.
- Plateau angle measurement/diagnostics should be supported.

## R10. Free deformation and forcing
- Shape responds to bubble contacts, gravity, buoyancy, airflow, acceleration, walls, external pressure, surface tension and neighbor pressure.
- Large-bubble flattening under gravity is in scope.

## R11. Dynamics and ambient fluid
- Consider gravity, buoyancy, drag, inertia, fluid viscosity, airflow, turbulence, surface tension, pressure and film motion.
- High-end mode may solve multiphase Navier-Stokes.
- Ambient air is not universally ignored.
- Configurable air density, viscosity, wind speed/direction, turbulence intensity and gravity.

## R12. Internal gas
- Architecture can represent density, pressure, temperature, amount of substance and gas species.
- Ideal-gas or other documented constitutive models are allowed.

## R13. Gas diffusion/coarsening
- High-fidelity extension: pressure-driven gas transfer between neighbors, causing small bubbles to shrink and larger bubbles to grow.
- User may enable/disable.

## R14. Thin-film drainage and surfactant effects
- Contact-film thickness evolves in time where enabled.
- Candidate effects: gravitational drainage, capillary pressure, viscosity, Marangoni response, surfactant state.

## R15. Coalescence
- Contact does not imply immediate merge.
- Shared film precedes coalescence.
- Rupture criterion may depend on thickness, contact time, pressure and collision speed.
- Merge aims to conserve gas volume/amount and momentum as applicable.
- Post-merge non-spherical relaxation/oscillation is a target.

## R16. Rupture and splitting
- Individual bubbles may burst from thickness, curvature, stress, disturbance, user action or stochastic rupture.
- User-triggered burst is required.
- Rim retraction/droplet generation is a later maximum-realism target.
- Splitting due to strong deformation is allowed by architecture and may be staged later.

## R17. Walls and boundaries
- Floor, walls and arbitrary solid obstacles.
- Extensible wettability/contact-angle behavior.

## R18. Gravity environments
- Arbitrary gravity magnitude and direction.
- Presets may include Earth, Moon, Mars, microgravity and zero gravity.

## R19. Time controls
- Start, pause, resume, single-step, reset, time scale.
- Slow playback, fast compute and compute-to-time are desirable.

## R20. Accuracy controls
- User-facing modes such as Fast, Balanced, High and Maximum Realism.
- Expose or map controls for timestep, mesh resolution, AMR level, nonlinear iterations, tolerance, pressure-solver tolerance and curvature quality as appropriate.

## R21. Mesh/debug visualization
- Mesh display mode when a mesh solver is used.
- Show triangles, nodes, normals, contact boundaries and Plateau borders where available.
- AMR refinement visualization desirable.

## R22. Physics diagnostics
- Visualizable channels may include pressure, curvature, film thickness, velocity, stress, surface tension, mesh quality, air velocity/pressure, volume error, Plateau angle and contact state.
- Heatmaps are allowed.

## R23. Per-bubble panel
Required:
- ID, volume, equivalent radius, position, velocity, internal pressure, surface area.
Advanced:
- mean/min/max curvature, film thickness, contacts, energy, mesh vertex count.

## R24. System panel
- Bubble count, total volume, total area, simulation time, compute time, timestep, FPS, solver iterations, max volume error.

## R25. Rendering
Required baseline:
- transparent film, reflection, refraction, Fresnel response.
Desired:
- thin-film interference, thickness-dependent color, HDR environment reflection, high-quality lighting/environment.
- Rendering load is isolated from the solver.

## R26. Common-film display
- External films and shared films are distinguishable.
- Modes may include shared-only, outer-only, transparent and wireframe.

## R27. Direct manipulation
- 3D selection and actions: select, add, delete, burst, move, set initial velocity, resize, inspect.
- Editing mode and running-simulation mode are clearly distinct.

## R28. Mobile
- iPhone Safari is a first-class observation/control client.
- One-finger rotate, pinch zoom, tap selection, touch add, responsive UI.
- Heavy compute may run on server/Actions/other machine.

## R29. Backend/viewer separation
- A valid architecture is Simulation backend -> result files/stream -> Web viewer.
- Time-indexed meshes may be precomputed and replayed.

## R30. Persistence and scenarios
- Save/restart state including bubbles, meshes, parameters, time and solver state when possible.
- Prefer metadata JSON plus binary-friendly mesh/field payloads.
- Save reusable scenarios.
- Initial scenario set should include: two-bubble contact, three-bubble Plateau, many-bubble foam, zero gravity, strong wind, unequal sizes, coalescence and rupture.

## R31. Reproducibility
- Same initial conditions, parameters and seed should reproduce results as far as the numerical method permits.
- Store seed for stochastic rupture/turbulence.

## R32. Numerical validation
Automated validation should cover at least:
- single sphere Young-Laplace pressure;
- volume conservation;
- surface area;
- two-bubble equilibrium;
- Plateau angle near 120 degrees;
- stationary stability;
- coalescence volume conservation;
- zero-gravity symmetry;
- mesh convergence.

## R33. Physical transparency
- UI/docs must disclose which phenomena are implemented, approximated or absent.
- Never present visual realism as proof that a physical phenomenon was solved.

## R34. Solver flexibility
- Orchestra/Workers may choose Surface Evolver, Basilisk, OpenFOAM, VOF, Level Set, Front Tracking, Phase Field, FEM, BEM or custom methods.
- Multiple solver families may coexist; one solver need not solve every regime.

## R35. Multifidelity
- Interactive, High Fidelity and Maximum Realism modes are acceptable.
- Approximate modes must not dictate the limitations of the highest-fidelity design.

## R36. Modular architecture
- Separate physics solver, state management, renderer, UI and file I/O.
- Solver replacement must not require a viewer rewrite.
- Use a common state/result format.

## R37. Worker decomposition
- Orchestra may split physics, CFD, state/API, rendering, UX, mobile, validation, performance and integration among Workers.
- Minimize overlapping edit ownership.

## R38. Integrated completion
Final acceptance is not "the page renders". The integrated system must support:
- 3D observation;
- arbitrary add/delete;
- physically driven interaction/deformation;
- common films;
- pressure/surface-tension response;
- Plateau-law handling;
- coalescence;
- rupture;
- configurable gravity/buoyancy/flow;
- time control;
- parameter/state inspection;
- desktop and iPhone use;
- high-fidelity result/view separation;
- automated physical validation.

## R39. Ultimate product statement

The target is a laboratory for constructing, destroying, contacting and observing the physical system of soap bubbles itself, not a visual imitation of bubbles.

## Traceability rule

Every implementation task and final acceptance report must reference the requirement IDs above that it advances. Missing or deferred requirements must be explicitly listed as such.
