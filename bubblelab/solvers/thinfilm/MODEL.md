# Reduced-order thin-film transport model

This package advances lower-dimensional fields on a triangulated soap-film surface.
It does not claim to resolve the film thickness as a 3D liquid volume mesh.

The face finite-volume conserved quantities are liquid proxy h dA and surfactant
amount Gamma dA. Internal edge fluxes are equal and opposite, so closed surfaces
and no-flux boundaries conserve both integrated quantities up to floating-point
roundoff.

For each internal edge, the drainage flux combines viscous lubrication resistance,
tangential gravity, a capillary/disjoining pressure gradient, a Marangoni term from
the surface-tension gradient, and an optional supplied surface-advection velocity.
The public API uses SI units.

The surfactant equation uses conservative edge advection plus Fickian surface
diffusion. Surface tension uses a linearized equation of state,

    sigma = max(sigma_min, sigma_clean - E * Gamma).

This is a declared local constitutive approximation. The Marangoni hook returns an
approximation of grad_s sigma pointing from lower toward higher surface tension.

Explicit updates use a deterministic donor-amount timestep bound. A step is split
before any face can export more than a fixed fraction of its available liquid or
surfactant. Negative values larger than roundoff raise an error; roundoff-only
corrections are counted in diagnostics rather than silently hidden.

Gas transfer is pairwise through a shared film. The molar conductance is
permeability * shared_area / film_thickness and the transfer rate is conductance
times the ideal-gas pressure difference. Each pair update subtracts and adds the
same molar transfer, so total gas amount is conservative. Geometry/topology merge,
rupture, and coalescence are intentionally absent.

During transient remeshing, h dA and Gamma dA are stored in the existing
ConservativeArealField representation. Reconstructing densities after remeshing
therefore preserves the integrated liquid proxy and surfactant amount while keeping
the FilmFront mesh/film identity.
