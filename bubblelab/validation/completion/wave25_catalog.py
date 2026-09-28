"""Post-Wave-25 evidence overlay for the Bubble Lab completion catalog."""
from __future__ import annotations

from copy import deepcopy

from .wave23_catalog import CATALOG as WAVE23_CATALOG


CATALOG = deepcopy(WAVE23_CATALOG)


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


REPEATED_T1_GAS = "tasks/bubble-repeated-t1-gas-transport-foundation/deliverable.json"
INTERACTING_MULTIHOLE = "tasks/bubble-interacting-multihole-breakup-foundation/deliverable.json"
MANYCONTACT_T1_CFD = "tasks/bubble-manycontact-t1-global-cfd-foundation/deliverable.json"

for requirement_id in ("R1", "R9", "R12", "R13", "R30", "R31", "R35", "R38", "R39"):
    _extend_evidence(requirement_id, REPEATED_T1_GAS)
for requirement_id in ("R1", "R10", "R16", "R30", "R31", "R32", "R35", "R38", "R39"):
    _extend_evidence(requirement_id, INTERACTING_MULTIHOLE)
for requirement_id in ("R1", "R9", "R10", "R11", "R20", "R30", "R31", "R32", "R35", "R38", "R39"):
    _extend_evidence(requirement_id, MANYCONTACT_T1_CFD)
for requirement_id in ("R33",):
    _extend_evidence(requirement_id, REPEATED_T1_GAS, INTERACTING_MULTIHOLE, MANYCONTACT_T1_CFD)

_set_features(
    "R1",
    bounded_repeated_t1_gas_transport="MODELED",
    bounded_interacting_multihole_breakup="MODELED",
    bounded_manycontact_t1_global_cfd="MODELED",
)
CATALOG["R1"]["gap"] = (
    "Wave 25 materially extends three bounded physical classes: one continuous six-region gas/network history through "
    "two dependent production T1 transactions, two interacting thin-film holes evolving in one conservative reduced "
    "film/rim state, and a five-region many-contact T1 path in which an additional non-event contact causally changes "
    "resolved resistance on one authoritative Eulerian field. The ultimate maximum-realism laboratory is still "
    "incomplete because arbitrary repeated topology surgery and topology types, unrestricted 3D multi-hole/singular "
    "breakup and broad spray, arbitrary contact graphs and fluids/scales, singular Plateau-border CFD, deforming-wall "
    "CFD, arbitrary coupled live surgery, and physical-device qualification remain outside accepted evidence."
)
CATALOG["R1"]["closure"] = (
    "Preserve the accepted Wave-25 bounded classes and qualify each remaining unrestricted physical/device class "
    "independently; do not infer universal maximum-realism completion from the stronger bounded evidence."
)

_set_features(
    "R9",
    bounded_repeated_t1_topology_history="MODELED",
    bounded_manycontact_non_coplanar_t1="MODELED",
)

_set_features(
    "R10",
    bounded_interacting_multihole_breakup="MODELED",
    bounded_manycontact_t1_global_cfd="MODELED",
)
CATALOG["R10"]["gap"] = (
    "Wave 25 adds interacting two-hole rupture dynamics and a five-region shared-field contact/T1 case with measured "
    "non-event-contact influence. A single unrestricted maximum-realism runtime still does not combine arbitrary "
    "forcing/contact graphs with universal multiphase CFD, singular liquid-border dynamics, arbitrary 3D breakup, "
    "deforming walls and arbitrary live topology surgery."
)
CATALOG["R10"]["closure"] = (
    "Qualify the remaining general forcing/contact/wall/topology combinations with the same causality, conservation, "
    "refinement and runtime gates before widening the current bounded classes."
)

_set_features(
    "R11",
    bounded_manycontact_t1_global_cfd="MODELED",
    bounded_non_event_contact_causality="MODELED",
)
CATALOG["R11"]["gap"] = (
    "The accepted many-contact extension now demonstrates five support regions and two simultaneously active contacts "
    "on one authoritative partitioned Eulerian pressure/velocity field. Disabling only the non-event relative motion "
    "changes resolved T1 resistance by about 18.95%, while every 8/10/12-cell level retains the >=5% strong-feedback "
    "gate. This remains the declared 50 Pa s / 970 kg/m^3 exterior-liquid class; arbitrary contact graphs, fluids, "
    "scales, turbulence, compressibility, thermal/rarefied effects, singular Plateau-border CFD and universal sharp-"
    "interface multiphase Navier-Stokes remain unsupported."
)
CATALOG["R11"]["closure"] = (
    "Extend beyond the accepted many-contact/high-viscosity class only with independent field, causality, conservation, "
    "traction, refinement, symmetry and topology-continuation evidence for each broader flow regime."
)

_set_features(
    "R12",
    repeated_t1_stable_gas_identity="RESOLVED",
)
_set_features(
    "R13",
    bounded_repeated_t1_gas_transport="MODELED",
    repeated_post_topology_transport_rebuild="RESOLVED",
)

_set_features(
    "R16",
    bounded_interacting_multihole_breakup="MODELED",
    state_derived_interacting_multihole_fragments="RESOLVED",
)
CATALOG["R16"]["gap"] = (
    "No baseline R16 gap remains. Wave 25 additionally qualifies two simultaneously evolving thin-film holes in one "
    "conservative reduced film/rim state: shared-web interaction shifts detachment by about 17.16%, alters the "
    "pre-detachment neck trajectory, and the evolved neck counts [8,10] determine 18 conservative fragments."
)
CATALOG["R16"]["closure"] = (
    "Retain the accepted interacting-two-hole reduced-rim boundary. Unrestricted 3D multi-hole hydrodynamics, "
    "grid-resolved singular ligament pinch-off, turbulent atomization, secondary aerodynamic breakup and universal "
    "spray/droplet CFD remain higher-fidelity extensions rather than baseline R16 blockers."
)

_set_features(
    "R20",
    bounded_manycontact_t1_global_cfd="MODELED",
    manycontact_refinement_feedback_gates="RESOLVED",
)
CATALOG["R20"]["gap"] = (
    "Wave 25 adds a qualified many-contact high-end runtime slice with 8/10/12-cell feedback/refinement gates. The "
    "canonical product still does not expose every requested high-end solver-control/runtime combination, so R20 "
    "remains PARTIAL."
)
CATALOG["R20"]["closure"] = (
    "Expose only runnable high-end control combinations through the authoritative product path and retain explicit "
    "capability declarations for combinations that remain unavailable."
)

_set_features(
    "R30",
    repeated_t1_gas_scenario="RESOLVED",
    interacting_multihole_breakup_scenario="RESOLVED",
    manycontact_t1_cfd_scenario="RESOLVED",
)
CATALOG["R30"]["gap"] = (
    "Wave 25 contributes deterministic reusable scenarios for repeated dependent T1 gas transport, interacting "
    "two-hole breakup and many-contact T1/global-CFD. R30 remains PARTIAL because cross-version checkpoint portability, "
    "the complete reusable many-bubble/network scenario family, and arbitrary topology/event surgery persistence are "
    "not yet qualified."
)
CATALOG["R30"]["closure"] = (
    "Complete the missing reusable scenario/state breadth and demonstrate deterministic save/restart across the "
    "remaining coupled topology/event classes without weakening stable identity or conservation."
)

_set_features("R31", wave25_deterministic_replay_and_identity="RESOLVED")
_set_features("R32", wave25_causality_conservation_refinement_validation="RESOLVED")
_set_features("R33", wave25_bounded_claim_boundaries_disclosed="RESOLVED")

_set_features(
    "R35",
    bounded_repeated_t1_gas_transport="MODELED",
    bounded_interacting_multihole_breakup="MODELED",
    bounded_manycontact_t1_global_cfd="MODELED",
)
CATALOG["R35"]["gap"] = (
    "Maximum Realism now includes bounded two-dependent-T1 gas transport, interacting two-hole reduced-rim breakup, "
    "and a five-region many-contact shared-field T1 with demonstrated non-event-contact causality. It is still not one "
    "unrestricted path: arbitrary topology/contact graphs, universal multiphase and singular-border CFD, unrestricted "
    "3D breakup/spray, deforming walls, arbitrary live surgery and direct physical-device qualification remain open."
)
CATALOG["R35"]["closure"] = (
    "Keep supported-class modes explicit and qualify the remaining unrestricted maximum-realism extensions one class "
    "at a time before presenting the integrated path as general."
)

_set_features(
    "R38",
    bounded_repeated_t1_gas_transport="MODELED",
    bounded_interacting_multihole_breakup="MODELED",
    bounded_manycontact_t1_global_cfd="MODELED",
    bounded_non_event_contact_causality="MODELED",
)
CATALOG["R38"]["gap"] = (
    "Wave 25 strengthens integrated topology-changing gas transport, breakup and many-contact shared-field T1 evidence. "
    "Final integrated acceptance remains directly blocked by missing physical iPhone Safari/device-GPU/native-touch "
    "qualification. Arbitrary repeated topology classes, unrestricted 3D multi-hole/singular breakup and spray, "
    "arbitrary-contact/universal multiphase and singular-border CFD, deforming walls and arbitrary coupled live surgery "
    "also remain explicit higher-fidelity limits."
)
CATALOG["R38"]["closure"] = (
    "Archive physical iPhone Safari/native-hardware evidence for the direct device requirement and preserve every "
    "unrestricted higher-fidelity boundary until independently implemented and qualified."
)

_set_features(
    "R39",
    bounded_repeated_t1_gas_transport="MODELED",
    bounded_interacting_multihole_breakup="MODELED",
    bounded_manycontact_t1_global_cfd="MODELED",
)
CATALOG["R39"]["gap"] = (
    "Bubble Lab now carries a continuous gas history through two dependent real T1 events, interacting two-hole "
    "state-derived breakup, and a causally coupled five-region T1/global-CFD case. The ultimate laboratory statement "
    "remains incomplete while physical-device qualification and declared unrestricted topology/contact/singular-CFD, "
    "general breakup/spray, deforming-wall and coupled-live-surgery classes remain open."
)
CATALOG["R39"]["closure"] = (
    "Preserve every supported-class boundary and close the remaining physical-validity/device gaps with measured "
    "evidence rather than treating breadth of bounded modes as unrestricted maximum-realism completion."
)
