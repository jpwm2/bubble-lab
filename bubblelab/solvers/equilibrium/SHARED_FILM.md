# Shared-film equilibrium extension

This extension adds the reduced B04/B05 scope to the existing isolated-bubble equilibrium core: two gas regions, two outer-film patches, and exactly one persistent shared-film patch.  It does not implement contact detection, topology change, Plateau triple-line mechanics, drainage, diffusion, rupture, coalescence, or transient CFD.

## Orientation and volume convention

Each FilmPatch stores an ordered pair adjacent=(region0, region1).  Triangle normals point from region0 toward region1.

For an oriented patch f with signed tetrahedral volume V_f:
- region0 receives +V_f;
- region1 receives -V_f;
- EXTERIOR is not a constrained gas region.

The shared A-B film is therefore represented once.  It contributes with opposite sign to the A and B gas volumes instead of being duplicated as coincident surfaces.

## Coupled constrained minimization

The network minimizes

E = sum_f sigma_f A_f

subject to one independent target volume for every GasRegion.  At each iterate, the solver forms every region-volume gradient and solves the coupled Gram system for one Lagrange multiplier p_i per gas region.  The projected force is

grad(E) - sum_i p_i grad(V_i).

Trial steps are retracted to all volume constraints simultaneously by a Newton correction in the span of all volume gradients.  Independent per-bubble uniform scaling is not used once a shared film exists.

The contact ring in the deterministic B04/B05 geometry is pinned.  This deliberately separates common-film mechanics from the later Plateau-junction worker; no 120-degree law is claimed here.

## Shared-film Young-Laplace sign

The shared patch is oriented bubble-a -> bubble-b.  With that normal convention,

p_A - p_B = sigma_shared * kappa_shared.

Positive curvature therefore bulges toward bubble-b when p_A > p_B.  The B05 benchmark measures curvature from the solved shared-film vertices; the fitted curvature is diagnostic-only and is never fed back into the optimizer.

## B04 and B05

The deterministic benchmark mesh uses a shared-film median edge ratio eta_s <= 0.03 relative to the film span.

B04 starts from a smoothly perturbed equal-pressure common film.  It measures:
- central-60-percent curvature times film span;
- central-60-percent best-plane RMS deviation divided by film span;
- pressure/curvature residual;
- both gas-volume residuals and projected-force residual.

B05 uses unequal bubble radii and a smoothly perturbed common film.  It measures:
- solved p_A-p_B;
- signed curvature from a sphere-of-revolution fit to solved numerical vertices;
- normalized curvature and pressure/curvature residuals;
- curvature-sign consistency;
- both gas-volume residuals and projected-force residual.

Run:

python3 bubblelab/solvers/equilibrium/tools/run_shared_benchmark.py b04 --assert
python3 bubblelab/solvers/equilibrium/tools/run_shared_benchmark.py b05 --assert

Export a canonical contract-v1 FRAME with:

python3 bubblelab/solvers/equilibrium/tools/export_shared_film_demo.py --output /tmp/shared-film.json

The export contains two BubbleState entries, both outer films, one SHARED FilmRegion with A-B adjacency, computed pressures, solved meshes, HIGH_FIDELITY provenance, and an empty junction list.  Plateau junctions remain NOT_IMPLEMENTED.
