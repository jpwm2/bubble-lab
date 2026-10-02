"""Post-Wave-27 evidence overlay for the Bubble Lab completion catalog."""
from __future__ import annotations
from copy import deepcopy
from .wave25_catalog import CATALOG as WAVE25_CATALOG

CATALOG = deepcopy(WAVE25_CATALOG)

def _e(r,*paths):
    for p in paths:
        if p not in CATALOG[r]["evidence"]: CATALOG[r]["evidence"].append(p)
def _f(r,**features): CATALOG[r]["features"].update(features)

MULTI="bubblelab/validation/completion/evidence/historical-deliveries/bubble-multievent-topology-gas-network-foundation.json"
NECK="bubblelab/validation/completion/evidence/historical-deliveries/bubble-3d-multineck-breakup-foundation.json"
BORDER="bubblelab/validation/completion/evidence/historical-deliveries/bubble-liquid-border-global-cfd-foundation.json"
for r in ("R1","R9","R12","R13","R30","R31","R35","R38","R39"): _e(r,MULTI)
for r in ("R1","R10","R16","R30","R31","R32","R35","R38","R39"): _e(r,NECK)
for r in ("R1","R10","R11","R20","R30","R31","R32","R35","R38","R39"): _e(r,BORDER)
for r in ("R33",): _e(r,MULTI,NECK,BORDER)
for r in ("R1","R13","R35","R38","R39"): _f(r,bounded_multievent_topology_gas_network="MODELED")
for r in ("R1","R10","R16","R35","R38","R39"): _f(r,bounded_3d_interacting_multineck_breakup="MODELED")
for r in ("R1","R10","R11","R20","R35","R38","R39"): _f(r,bounded_field_coupled_liquid_border_global_cfd="MODELED")
_f("R12", multievent_stable_gas_identity="RESOLVED")
_f("R13", multievent_post_topology_transport_rebuild="RESOLVED")
_f("R16", conservative_3d_multineck_detachment_lineage="RESOLVED")
_f("R20", liquid_border_pressure_viscous_feedback="RESOLVED")
_f("R30", wave27_bounded_scenarios="RESOLVED")
_f("R31", wave27_deterministic_replay_and_identity="RESOLVED")
_f("R32", wave27_conservation_causality_refinement_validation="RESOLVED")
_f("R33", wave27_bounded_claim_boundaries_disclosed="RESOLVED")

CATALOG["R1"]["gap"]="Wave 27 adds a continuous ten-to-nine-region history with four causally dependent production T1 transactions plus topology-enabled rupture/coalescence, a genuinely non-coplanar interacting 3D multi-neck detachment class, and field-coupled 3D liquid-border redistribution with Eulerian pressure/viscous feedback and real T1 surgery. Arbitrary topology classes, unrestricted singular breakup/spray, universal multiphase/singular Plateau-border CFD, deforming walls, arbitrary coupled live surgery, and physical-device qualification remain outside accepted evidence."
CATALOG["R10"]["gap"]="Wave 27 strengthens bounded 3D interacting breakup and field-coupled liquid-border/T1 behavior, but the unrestricted maximum-realism runtime still lacks arbitrary forcing/contact/topology combinations, singular breakup/spray, universal multiphase CFD, deforming walls and arbitrary live surgery."
CATALOG["R11"]["gap"]="Wave 27 adds bounded 3D liquid-border redistribution on an Eulerian pressure/velocity field with pressure and viscous feedback plus real T1 surgery. Arbitrary fluids/scales/contact graphs, singular Plateau-border resolution and universal multiphase Navier-Stokes remain unsupported."
CATALOG["R20"]["gap"]="Wave 27 adds another qualified field-coupled high-end slice, but the canonical product still does not expose every requested high-end solver-control/runtime combination."
CATALOG["R30"]["gap"]="Wave 27 adds deterministic bounded multi-event topology/gas, 3D multi-neck and liquid-border/global-CFD evidence. Cross-version checkpoint portability, complete reusable many-bubble/network scenario breadth and arbitrary topology/event persistence remain unqualified."
CATALOG["R35"]["gap"]="Maximum Realism now includes materially stronger bounded topology/gas, non-coplanar multi-neck breakup and field-coupled liquid-border/T1 classes, but arbitrary topology/contact graphs, universal singular/multiphase CFD, unrestricted breakup/spray, deforming walls, arbitrary live surgery and physical-device qualification remain open."
CATALOG["R38"]["gap"]="Wave 27 strengthens integrated topology-changing gas transport, 3D breakup and field-coupled liquid-border/T1 evidence. Final integrated acceptance remains blocked by physical iPhone Safari/device-GPU/native-touch qualification and by explicitly unrestricted higher-fidelity physics classes."
CATALOG["R39"]["gap"]="The laboratory now carries stronger bounded multi-event topology/gas, non-coplanar interacting multi-neck breakup and field-coupled liquid-border/T1 behavior, but physical-device qualification and unrestricted topology/contact/singular-CFD/general-spray/deforming-wall/live-surgery classes remain open."
