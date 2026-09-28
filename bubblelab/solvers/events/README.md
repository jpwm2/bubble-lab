# Rupture and coalescence event layer

This package owns explicit topology-changing state transitions for R15, R16, R30, R31, R32, R33 and R38. It sits above accepted shared-film and thin-film state and does not modify the equilibrium, transient, or drainage solver cores.

## Rupture semantics

A film becomes rupture-eligible from its physical minimum-thickness trajectory. `RuptureTracker` supports a positive thickness threshold, an optional continuous dwell below that threshold, and deterministic user-triggered rupture. The event time is localized inside an accepted solver step by linear interpolation of the two bracketing minimum-thickness samples; the thinning trajectory itself is not replaced by that interpolation. Event provenance records the bracket, criterion, threshold, film ID, adjacent gas-region IDs, state digest, source, and seed.

Hooks exist for disjoining-pressure instability, strain/area-rate instability, and seeded stochastic nucleation. They are disabled by default. In particular, no random rupture occurs unless stochastic nucleation is explicitly enabled and a caller supplies a seeded hook.

## Two-bubble coalescence

Rupture and coalescence are separate ordered events. A failed shared film is removed from active topology and retained only in retired-film bookkeeping. If the film separates two live gas regions, the event engine then creates a deterministic child region, retires both parents as `MERGED`, and records exact parent lineage.

Gas amount and target volume are combined with `math.fsum`; the B10 gate is a relative gas-amount error of at most `1e-12`. When parent mass is available directly, or can be inferred from amount and a common molar mass, the child centroid and velocity are mass-weighted so center of mass and linear momentum are preserved. If mass is unavailable, the engine uses an explicitly disclosed volume-weighted fallback and does not claim a momentum conservation diagnostic. The failed shared-film surface energy is recorded as removed energy; full outer-surface energy change is explicitly left unresolved rather than forced to zero.

## Post-event geometry budget

The immediate child surface is a closed regular octahedron scaled to the merged target volume and centered at the preserved center. This is a conservative restart seed, not a claim of relaxed post-coalescence physics. Its default represented-volume error budget is `1e-12`. Full retracting-rim physics, spray/droplets, T1 rearrangements, large-deformation splitting, and post-event CFD relaxation remain outside this task.

## Determinism and replay

Child IDs and event IDs are SHA-256-derived from canonical event identity, never from wall-clock time or process randomness. With identical initial state, timestep sequence, enabled criteria, and seed, event times, event ordering, IDs, lineage, and post-event bookkeeping state are identical.

## Validation

`tools/run_benchmark.py` provides the B10 conservation case, physical thinning threshold localization, B16 timestep/pre-event-state convergence case, and exact replay case. `tools/export_demo.py` emits a contract-v1 frame whose topology history contains distinct `RUPTURE` and `COALESCENCE` events and whose live child carries restart geometry explicitly marked for later relaxation.
