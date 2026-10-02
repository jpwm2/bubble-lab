"""Post-Wave-23 evidence overlay for the Bubble Lab completion catalog."""
from __future__ import annotations

from copy import deepcopy

from .wave21_catalog import CATALOG as WAVE21_CATALOG


CATALOG = deepcopy(WAVE21_CATALOG)


def _extend_evidence(requirement_id: str, *paths: str) -> None:
    evidence = CATALOG[requirement_id]["evidence"]
    assert isinstance(evidence, list)
    for path in paths:
        if path not in evidence:
            evidence.append(path)


def _set_features(requirement_id: str, **features: str) -> None:
    current = CATALOG[requirement_id]["features"]
    assert isinstance(current, dict)
    current.update(features)


ASYMMETRIC_RIM = "bubblelab/validation/completion/evidence/historical-deliveries/bubble-asymmetric-multimode-rim-breakup-foundation.json"
PLATEAU_BORDER = "bubblelab/validation/completion/evidence/historical-deliveries/bubble-plateau-border-hydrodynamics-foundation.json"
STRONG_T1_CFD = "bubblelab/validation/completion/evidence/historical-deliveries/bubble-strongly-coupled-t1-global-cfd-foundation.json"

for requirement_id in ("R1", "R16", "R35", "R38", "R39"):
    _extend_evidence(requirement_id, ASYMMETRIC_RIM)
for requirement_id in ("R1", "R9", "R10", "R11", "R35", "R38", "R39"):
    _extend_evidence(requirement_id, PLATEAU_BORDER)
for requirement_id in ("R1", "R10", "R11", "R20", "R35", "R38", "R39"):
    _extend_evidence(requirement_id, STRONG_T1_CFD)
for requirement_id in ("R31", "R32", "R33"):
    _extend_evidence(requirement_id, ASYMMETRIC_RIM, PLATEAU_BORDER, STRONG_T1_CFD)

_set_features(
    "R1",
    bounded_asymmetric_multimode_rim_breakup="MODELED",
    bounded_dynamic_plateau_border_hydrodynamics="MODELED",
    bounded_strongly_coupled_t1_global_cfd="MODELED",
)
CATALOG["R1"]["gap"] = (
    "Wave 23 adds three stronger bounded foundations: one asymmetric single-hole reduced rim with simultaneous "
    "modes and state-derived droplet partition, one dynamic reduced-order Plateau-border/liquid-border model "
    "feeding a real four-region T1, and one strongly field-coupled four-region T1 whose resolved Eulerian "
    "traction changes production event timing by more than 5% in the declared high-viscosity regime. The "
    "ultimate maximum-realism laboratory is still incomplete because unrestricted repeated topology-changing "
    "gas-film coupling, arbitrary-contact universal multiphase Navier-Stokes and singular liquid-border CFD, "
    "unrestricted continuum/singular 3D T1, arbitrary 3D multi-hole/multi-neck breakup and broad spray physics, "
    "deforming-wall CFD, arbitrary coupled live surgery, and physical-device qualification remain outside "
    "accepted evidence."
)
CATALOG["R1"]["closure"] = (
    "Preserve every accepted supported class and close only the remaining unrestricted/device classes with "
    "independent measured evidence; Wave-23 bounded foundations must not be widened into universal claims."
)

_set_features(
    "R9",
    bounded_dynamic_plateau_border_hydrodynamics="MODELED",
)
CATALOG["R9"]["gap"] = (
    "No baseline R9 gap remains. Wave 23 additionally qualifies dynamic liquid-border feedback for one isolated "
    "four-region curvilinear 3D T1 using two conserved liquid control volumes, Young-Laplace pressure, "
    "Poiseuille redistribution, state-dependent capillarity and viscous resistance before the accepted topology "
    "switch. This remains a reduced-order local model rather than singular Plateau-border Navier-Stokes CFD."
)
CATALOG["R9"]["closure"] = (
    "Retain the accepted four-region reduced-order boundary. Unrestricted curved/singular liquid-border "
    "continuum hydrodynamics remains a higher-fidelity extension rather than an R9 blocker."
)

_set_features(
    "R10",
    bounded_dynamic_plateau_border_hydrodynamics="MODELED",
    bounded_strongly_coupled_t1_global_cfd="MODELED",
)
CATALOG["R10"]["gap"] = (
    "Accepted runtime slices now include dynamic reduced liquid-border feedback and one isolated four-region "
    "strongly coupled T1 carried through a single authoritative Eulerian field with materially causal resolved "
    "traction. A single unrestricted maximum-realism runtime still does not combine every forcing/contact graph "
    "with arbitrary-contact multiphase CFD, singular liquid-border dynamics, deforming walls and arbitrary live "
    "topology surgery."
)
CATALOG["R10"]["closure"] = (
    "Qualify only the remaining general forcing/contact/wall/CFD combinations required by the maximum-realism "
    "claim while retaining the bounded Wave-23 strong-coupling and reduced liquid-border classes."
)

_set_features(
    "R11",
    bounded_dynamic_plateau_border_hydrodynamics="MODELED",
    bounded_strongly_coupled_t1_global_cfd="MODELED",
    bounded_causal_cfd_t1_timing_feedback="MODELED",
)
CATALOG["R11"]["gap"] = (
    "Wave 23 materially strengthens the bounded global-flow evidence: two non-equivalent non-coplanar "
    "four-region fixtures use one authoritative Eulerian field, overlapping closed supports, resolved "
    "pressure/viscous traction and same-field continuation, and the accepted production event time shifts by "
    "about 5.48% and 5.82% versus feedback-disabled runs in the declared 50 Pa s exterior-liquid regime. A "
    "separate bounded reduced-order liquid-border model also evolves local conserved liquid state into T1 timing. "
    "Arbitrary contact graphs, unrestricted many-bubble topology-through-CFD, singular Plateau-border/liquid-border "
    "Navier-Stokes, turbulence, compressibility, thermal/rarefied flow and universal sharp moving-interface "
    "multiphase CFD remain unsupported."
)
CATALOG["R11"]["closure"] = (
    "Extend beyond the accepted isolated four-region/high-viscosity and reduced local-border classes only with "
    "independent field, conservation, refinement, topology-continuation and constitutive-response evidence for "
    "each broader flow regime."
)

_set_features(
    "R16",
    bounded_asymmetric_multimode_rim_breakup="MODELED",
    state_derived_multimode_droplet_handoff="RESOLVED",
)
CATALOG["R16"]["gap"] = (
    "No baseline R16 gap remains. Wave 23 additionally qualifies one polar-asymmetric thin-film hole whose "
    "single conservative reduced rim carries simultaneous azimuthal modes 7 and 10; evolved local neck minima "
    "rather than a seeded mode count determine conservative detachment, producing 11 droplets in the default "
    "case with deterministic runtime handoff."
)
CATALOG["R16"]["closure"] = (
    "Retain the accepted single-hole reduced-rim/multimode boundary. Arbitrary 3D multi-hole interaction, "
    "grid-resolved singular ligament pinch-off, broadband turbulent atomization, broad spray statistics, "
    "secondary aerodynamic breakup and deforming post-detachment droplet CFD remain higher-fidelity extensions."
)

_set_features(
    "R20",
    bounded_strongly_coupled_t1_global_cfd="MODELED",
)
CATALOG["R20"]["gap"] = (
    "Wave 23 adds another qualified high-end runtime combination: one bounded strongly coupled four-region "
    "T1/global-CFD path with conservation, refinement, symmetry and runtime continuation gates. The canonical "
    "product still does not expose every high-end solver-control/runtime combination requested by R20."
)
CATALOG["R20"]["closure"] = (
    "Map only runnable high-end controls and scenarios into the authoritative product path and retain explicit "
    "capability declarations for combinations that remain unavailable."
)

_set_features(
    "R31",
    wave23_deterministic_replay_evidence="RESOLVED",
)
_set_features(
    "R32",
    wave23_foundation_validation="RESOLVED",
)
_set_features(
    "R33",
    wave23_claim_boundaries_disclosed="RESOLVED",
)

_set_features(
    "R35",
    bounded_asymmetric_multimode_rim_breakup="MODELED",
    bounded_dynamic_plateau_border_hydrodynamics="MODELED",
    bounded_strongly_coupled_t1_global_cfd="MODELED",
)
CATALOG["R35"]["gap"] = (
    "Maximum Realism now includes the prior bounded topology-changing gas transport and T1-through-global-CFD "
    "classes plus Wave-23 asymmetric multimode reduced-rim breakup, dynamic reduced liquid-border feedback, and "
    "strong causal Eulerian-field T1 timing feedback. It is still not one unrestricted path because arbitrary "
    "contact/topology multiphase CFD, singular continuum liquid-border dynamics, unrestricted 3D T1, deforming "
    "walls, arbitrary multi-hole/multi-neck breakup and broad spray physics, arbitrary live surgery and direct "
    "physical-device qualification remain unavailable."
)
CATALOG["R35"]["closure"] = (
    "Keep every supported-class mode explicit and qualify each remaining unrestricted maximum-realism extension "
    "independently before presenting the integrated path as general."
)

_set_features(
    "R38",
    bounded_asymmetric_multimode_rim_breakup="MODELED",
    bounded_dynamic_plateau_border_hydrodynamics="MODELED",
    bounded_strongly_coupled_t1_global_cfd="MODELED",
    bounded_causal_cfd_t1_timing_feedback="MODELED",
)
CATALOG["R38"]["gap"] = (
    "Wave 23 integrates stronger bounded breakup, liquid-border and field-coupled T1 evidence into the accepted "
    "stack. Final integrated acceptance remains directly blocked by missing physical iPhone Safari/device-GPU/"
    "native-touch qualification. Unrestricted repeated topology-changing gas transport, arbitrary-contact "
    "multiphase and singular-border CFD, unrestricted continuum/singular 3D T1, arbitrary 3D multi-hole/multi-neck "
    "breakup and broad spray physics, deforming-wall CFD and arbitrary coupled live surgery remain explicit "
    "higher-fidelity scope limits."
)
CATALOG["R38"]["closure"] = (
    "Archive physical iPhone Safari/native-hardware evidence for the direct R38 device requirement and preserve "
    "every unrestricted higher-fidelity boundary until independently implemented and qualified."
)

_set_features(
    "R39",
    bounded_asymmetric_multimode_rim_breakup="MODELED",
    bounded_dynamic_plateau_border_hydrodynamics="MODELED",
    bounded_strongly_coupled_t1_global_cfd="MODELED",
)
CATALOG["R39"]["gap"] = (
    "Bubble Lab now combines its prior integrated physics with Wave-23 asymmetric multimode reduced-rim breakup, "
    "dynamic conserved liquid-border feedback and a bounded strongly coupled T1/global-CFD path with material "
    "resolved-traction timing feedback. The ultimate laboratory statement remains incomplete while physical-device "
    "qualification and declared unrestricted topology-changing, arbitrary-contact/singular CFD, general 3D T1, "
    "arbitrary breakup/spray, deforming-wall and coupled live-surgery classes remain open."
)
CATALOG["R39"]["closure"] = (
    "Preserve every supported-class boundary and close the remaining physical-validity/device gaps with measured "
    "evidence rather than treating breadth of bounded modes as unrestricted maximum-realism completion."
)
