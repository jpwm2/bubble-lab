# Dynamic Plateau-border foundation

This package implements a **bounded reduced-order liquid-border model** for the
qualified isolated four-gas curvilinear T1 neighborhood. It is not resolved
Navier-Stokes, not singular Plateau-border CFD, and not a universal 3D foam
model.

## State and conservation

The generalized T1 coordinate is the measured separation `ell` of the two
resolved Plateau curves. The liquid phase is represented by two connected
control volumes: the local collapsing border core and a finite reservoir. Their
volumes obey

`V_core + V_reservoir = V_liquid = constant`.

The core control-volume length scales with `ell`; equivalent circular radii are
computed from the evolved volumes and lengths. The update transfers equal and
opposite volume between the two control volumes, so the discrete total liquid
volume is conserved to roundoff.

## Pressure, viscous and capillary terms

The surrounding-film contribution is the surface-tension co-normal traction
integrated on the actual resolved 3D Plateau boundaries. It is a measured
boundary load, not a prescribed event-time curve.

Liquid pressures use the Young-Laplace reduced closure

`p_i - p_g = -gamma / r_i`.

Liquid redistribution uses a Poiseuille throat,

`Q = (p_core - p_reservoir) / R_h`,

`R_h = 8 mu L_h / (pi r_h^4)`.

The collapsing generalized coordinate satisfies the overdamped momentum balance

`0 = F_sheet + F_border_capillary - F_pressure - F_viscous`,

with `F_viscous = zeta(state) * |d ell / dt|`. Both Young-Laplace pressure and
viscous resistance are recomputed from the evolving conserved liquid state on
every integration step. Increasing viscosity therefore slows the event, while
increasing surface tension strengthens capillary drive.

## Event and topology

The event is not assigned a hardcoded time. Integration continues until
`ell = 2 r_core_declared`. Only then is the existing qualified direct-3D
adjacency/incidence surgery applied at that reached geometry. Stable gas IDs are
preserved and gas-volume conservation is checked independently of liquid-volume
conservation.

## Claim boundary

The supported class is
`isolated-four-region-curvilinear-3d-dynamic-liquid-border-reduced-order`.
The model resolves the time evolution of declared liquid control-volume state
and its constitutive force/resistance feedback, but it does not resolve the full
3D velocity/pressure field inside a singular Plateau border. The external
surrounding-film traction is measured on the initial resolved local mesh; its
subsequent variation is not claimed. Event timing is nevertheless not the
legacy frozen-traction predictor because the pressure, curvature, liquid
redistribution and viscous mobility that determine the collapse rate evolve
from the conserved liquid state.
