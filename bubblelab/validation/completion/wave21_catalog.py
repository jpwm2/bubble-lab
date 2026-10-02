"""Post-Wave-21 evidence overlay for the Bubble Lab completion catalog."""
from __future__ import annotations

from copy import deepcopy

from .wave19_catalog import CATALOG as WAVE19_CATALOG


CATALOG = deepcopy(WAVE19_CATALOG)


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


TOPOLOGY_GAS = "bubblelab/validation/completion/evidence/historical-deliveries/bubble-topology-changing-gas-transport.json"
T1_GLOBAL_CFD = "bubblelab/validation/completion/evidence/historical-deliveries/bubble-t1-through-global-cfd-foundation.json"
RIM_BREAKUP = "bubblelab/validation/completion/evidence/historical-deliveries/bubble-retracting-rim-ligament-droplet-foundation.json"

for requirement_id in ("R1", "R13", "R35", "R38", "R39"):
    _extend_evidence(requirement_id, TOPOLOGY_GAS)
for requirement_id in ("R1", "R10", "R11", "R35", "R38", "R39"):
    _extend_evidence(requirement_id, T1_GLOBAL_CFD)
for requirement_id in ("R1", "R16", "R35", "R38", "R39"):
    _extend_evidence(requirement_id, RIM_BREAKUP)

_set_features(
    "R1",
    bounded_topology_changing_gas_transport="MODELED",
    bounded_t1_through_global_cfd="MODELED",
    bounded_retracting_rim_ligament_droplet_detachment="MODELED",
)
CATALOG["R1"]["gap"] = (
    "Wave 21 adds conservative gas transport through one supported four-region T1, one bounded "
    "four-region T1-through-global-CFD path with measured overlap treatment, and one circular-hole "
    "retracting-rim/ligament/droplet-detachment path. The ultimate maximum-realism laboratory still "
    "lacks unrestricted repeated/arbitrary topology-changing gas-film coupling, arbitrary-contact "
    "multiphase Navier-Stokes and singular Plateau-border CFD, unrestricted continuous/singular 3D "
    "T1 liquid-border hydrodynamics, arbitrary 3D multi-hole/multi-neck breakup and broad spray/secondary "
    "breakup, deforming-wall CFD, arbitrary coupled live surgery, and physical-device qualification."
)
CATALOG["R1"]["closure"] = (
    "Preserve every accepted supported class and close only the remaining unrestricted/device classes "
    "with independent measured evidence; bounded Wave-21 subclasses must not be widened by prose."
)

_set_features("R10", bounded_t1_through_global_cfd="MODELED")
CATALOG["R10"]["gap"] = (
    "Accepted runtime slices now include one isolated four-region T1 carried through a shared Eulerian "
    "field with field-derived event resistance and post-event continuation. A single unrestricted "
    "maximum-realism runtime still does not combine every forcing/contact graph with arbitrary-contact "
    "multiphase CFD, singular liquid-border dynamics and deforming walls."
)
CATALOG["R10"]["closure"] = (
    "Qualify only the remaining general forcing/contact/wall/CFD combinations required by the "
    "maximum-realism claim while retaining the bounded four-region T1-through-CFD support class."
)

_set_features(
    "R11",
    bounded_t1_through_global_cfd="MODELED",
    bounded_overlapping_immersed_supports="MODELED",
)
CATALOG["R11"]["gap"] = (
    "Wave 21 advances the global Eulerian path to one isolated genuinely non-coplanar four-region T1, "
    "including measured partition-of-unity treatment of overlapping immersed supports, field-derived "
    "traction in event timing, real adjacency/incidence surgery and post-event continuation. Arbitrary "
    "contact graphs, unrestricted many-bubble T1-through-CFD, singular Plateau-border/liquid-border CFD, "
    "universal sharp moving-interface multiphase Navier-Stokes, turbulence, compressibility, thermal and "
    "rarefied regimes remain unsupported."
)
CATALOG["R11"]["closure"] = (
    "Extend beyond the accepted isolated four-region class only with independent field, conservation, "
    "refinement, topology-continuation and runtime evidence for each broader flow regime."
)

_set_features(
    "R13",
    bounded_topology_changing_gas_transport="MODELED",
    t1_gas_state_preservation="RESOLVED",
)
CATALOG["R13"]["gap"] = (
    "No baseline R13 gap remains. In addition to the fixed-topology many-bubble network, Wave 21 qualifies "
    "one real four-region T1 where the canonical FilmNetwork retires AB, creates CD, preserves stable gas "
    "identities and amount/pressure/volume at surgery, rebuilds transport edges from the post-event network, "
    "and continues simultaneous conservative pressure-driven transfer with exact replay and disable semantics."
)
CATALOG["R13"]["closure"] = (
    "Retain exact conservation, stable gas identities and the declared isolated four-region T1 boundary. "
    "Rupture/coalescence/vanishing-region remap, unrestricted repeated topology surgery and continuously "
    "deforming fully coupled 3D gas-film transport remain higher-fidelity extensions rather than R13 blockers."
)

_set_features(
    "R16",
    bounded_retracting_rim_ligament_droplet_detachment="MODELED",
    deterministic_rim_breakup_runtime_handoff="RESOLVED",
)
CATALOG["R16"]["gap"] = (
    "No baseline R16 gap remains. Wave 21 additionally qualifies one circular thin-film hole with a "
    "dynamically evolved toroidal rim, one resolved azimuthal instability mode, ligament onset from evolved "
    "state and conservative deterministic droplet detachment/runtime handoff."
)
CATALOG["R16"]["closure"] = (
    "Retain the accepted circular-hole/single-mode reduced-rim boundary. Arbitrary 3D multi-hole rupture, "
    "fully resolved singular ligament pinch-off, broad spray distributions, turbulent atomization, secondary "
    "aerodynamic breakup and general post-detachment droplet CFD remain later maximum-realism extensions."
)

_set_features(
    "R35",
    bounded_topology_changing_gas_transport="MODELED",
    bounded_t1_through_global_cfd="MODELED",
    bounded_retracting_rim_ligament_droplet_detachment="MODELED",
)
CATALOG["R35"]["gap"] = (
    "Maximum Realism now includes bounded topology-changing gas transport, bounded T1-through-one-global-field "
    "CFD with measured overlap support, and bounded retracting-rim/ligament/droplet detachment. It is still not "
    "one unrestricted path because repeated/arbitrary topology-changing gas-film coupling, arbitrary-contact "
    "multiphase/singular-border CFD, unrestricted continuous/singular 3D T1, deforming-wall CFD, arbitrary "
    "multi-hole/multi-neck 3D breakup, broad spray physics and coupled live-state surgery remain unavailable."
)
CATALOG["R35"]["closure"] = (
    "Keep every lower-fidelity and supported-class mode explicit and qualify each remaining unrestricted "
    "maximum-realism extension independently before presenting it as general."
)

_set_features(
    "R38",
    bounded_topology_changing_gas_transport="MODELED",
    bounded_t1_through_global_cfd="MODELED",
    bounded_overlapping_immersed_supports="MODELED",
    bounded_retracting_rim_ligament_droplet_detachment="MODELED",
)
CATALOG["R38"]["gap"] = (
    "Wave 21 integrates bounded T1-through-gas-network transport, one four-region T1 through a shared Eulerian "
    "field with measured overlap support, and one circular-hole rim/ligament/droplet-detachment path. Final "
    "integrated acceptance remains directly blocked by missing physical iPhone Safari/device-GPU/native-touch "
    "qualification. Unrestricted repeated topology-changing gas transport, arbitrary-contact multiphase and "
    "singular-border CFD, unrestricted arbitrary/continuum/singular 3D T1, arbitrary 3D multi-hole/multi-neck "
    "breakup and broad spray physics, deforming-wall CFD and arbitrary coupled live surgery remain explicit "
    "higher-fidelity scope limits."
)
CATALOG["R38"]["closure"] = (
    "Archive physical iPhone Safari/native-hardware evidence for the direct R38 device requirement and preserve "
    "every unrestricted higher-fidelity scope limit until independently implemented and qualified."
)

_set_features(
    "R39",
    bounded_topology_changing_gas_transport="MODELED",
    bounded_t1_through_global_cfd="MODELED",
    bounded_retracting_rim_ligament_droplet_detachment="MODELED",
)
CATALOG["R39"]["gap"] = (
    "Bubble Lab now combines its prior integrated physics with bounded conservative gas transport through a real "
    "T1, bounded four-region T1-through-global-CFD continuation, and bounded circular-hole rim/ligament/droplet "
    "detachment. The ultimate laboratory statement remains incomplete while physical-device qualification and "
    "declared unrestricted topology-changing, arbitrary-contact CFD, general/singular T1, arbitrary 3D breakup/"
    "spray, deforming-wall and coupled live-surgery classes remain open."
)
CATALOG["R39"]["closure"] = (
    "Preserve every supported-class boundary and close the remaining physical-validity/device gaps with measured "
    "evidence rather than treating breadth of bounded modes as unrestricted maximum-realism completion."
)
