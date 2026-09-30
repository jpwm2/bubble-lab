# Bubble Lab Product Completion Boundary

Decision date: 2026-10-01

Requirement source: [`PRODUCT_REQUIREMENTS.md`](PRODUCT_REQUIREMENTS.md)
Current completion projection: [`PRODUCT_COMPLETION_STATUS.md`](PRODUCT_COMPLETION_STATUS.md)
Physics model: [`physics/PHYSICS_MODEL.md`](physics/PHYSICS_MODEL.md)
Accepted evidence overlay: [`../validation/completion/wave27_catalog.py`](../validation/completion/wave27_catalog.py)
Accepted honesty gate: [`../validation/completion/wave27_audit.py`](../validation/completion/wave27_audit.py)

## Decision

Bubble Lab Product completion is evaluated against the original R1-R39 wording, not against an inferred requirement that Maximum Realism be a universal solver for every physically possible topology, contact graph, fluid regime, singularity, wall motion, or live surgery combination.

`High-fidelity/maximum-realism mode is the design reference` in R1 and the multifidelity rules in R35 require the highest-fidelity Product path to remain physically grounded, independently extensible, and honestly classified. They do **not** turn every later, optional, local, staged, or unbounded extension into a prerequisite for Product completion.

Bounded MODELED/RESOLVED evidence remains bounded. This decision narrows completion semantics; it does not widen evidence.

## Completion classification

| Remaining class | Completion classification | Requirement basis | Boundary |
| --- | --- | --- | --- |
| Arbitrary topology/contact graphs beyond accepted qualified classes | **accepted bounded + later extension** | R1, R10, R35, R38 | Product completion requires the R38 integrated interactions and the explicitly required add/delete/contact/common-film/coalescence/rupture paths to work in supported declared regimes. Universal graph/topology generality is not stated. |
| Universal multiphase Navier-Stokes for arbitrary fluids/scales | **already covered by original optional wording** | R11, R34 | R11 says high-end mode **may** solve multiphase Navier-Stokes. Multiple solver families may coexist and one solver need not solve every regime. |
| Singular fully resolved Plateau-border CFD everywhere | **accepted bounded + later extension** | R9, R11, R14, R35 | The physics model explicitly permits GEOMETRIC, REDUCED_ORDER, and RESOLVED_LOCAL Plateau-border states. Universal singular-border resolution is not a completion prerequisite. |
| General singular breakup, rim retraction, droplets, spray, secondary breakup | **already covered by original optional/later wording** | R16 | R16 explicitly calls rim retraction/droplet generation a later Maximum Realism target and permits splitting to be staged later. Existing bounded breakup evidence must remain scoped. |
| Deforming/moving-wall CFD beyond required static/arbitrary solid obstacles and contact behavior | **accepted bounded + later extension** | R17, R10 | R17 requires floor, walls, arbitrary solid obstacles and extensible wettability/contact-angle behavior; it does not require general deforming-wall CFD. |
| Arbitrary coupled live topology surgery beyond specified Product actions | **accepted bounded + later extension** | R4, R5, R15-R16, R27, R38 | Add at arbitrary time, delete, burst, move, resize, inspect and the required physical topology events remain mandatory where specified. Unbounded arbitrary live surgery is not. |
| Every possible high-end solver-control/runtime combination | **accepted bounded + later extension** | R20, R33 | R20 requires user-facing fidelity modes and controls `as appropriate`. Every control actually exposed must map to a runnable capability and be disclosed truthfully; unsupported combinations need not be exposed. |
| Physical iPhone Safari/device GPU/native multi-touch qualification | **required-before-completion** | R3, R28, R38 | iPhone is a first-class client and R38 explicitly requires desktop and iPhone use. Emulation alone is insufficient evidence. |
| Cross-version checkpoint portability | **accepted bounded + later extension** | R30 | R30 requires save/restart including solver state `when possible`; it does not state cross-version portability. |
| Reusable initial scenario set named by R30 | **required-before-completion** | R30 | The initial scenario set should include two-bubble contact, three-bubble Plateau, many-bubble foam, zero gravity, strong wind, unequal sizes, coalescence and rupture. Product completion must either provide these reusable scenarios or retain an explicit unresolved R30 gap. |
| Product-owned repeatable final audit and evidence path | **required-before-completion** | R32, R33, R38-R39 plus Project completion criteria | Final acceptance must be reproducible from the dedicated Product repository without restoring Control Plane assets and without weakening bounded-claim honesty. |

## Minimum sufficient R38 / R39 completion boundary

R38 is accepted only when one Product-owned integrated path demonstrates, with truthful fidelity declarations:

1. 3D observation;
2. arbitrary add/delete within the supported Product interaction model;
3. physically driven interaction/deformation;
4. common films;
5. pressure/surface-tension response;
6. Plateau-law handling;
7. coalescence;
8. rupture;
9. configurable gravity/buoyancy/flow;
10. time control;
11. parameter/state inspection;
12. desktop and physical iPhone Safari use;
13. high-fidelity result/view separation; and
14. automated physical validation.

R39 adds no separate requirement for universal physics breadth. It is accepted when the integrated Product above behaves as a laboratory for the supported physical system rather than a visual imitation, and all unsupported higher-fidelity classes remain explicitly disclosed instead of being visually or textually implied as solved.

## Requirement-specific consequences

### R1

`Maximum Realism` remains the design reference. Completion requires a physically grounded highest-fidelity path and continued extensibility; it does not require universal topology/CFD/breakup/wall/live-surgery coverage.

### R10

The listed forcing/deformation causes remain mandatory in the supported Product regimes. Universal simultaneous combinations across every contact graph and topology class are later extensions unless a specific R38 integrated path depends on them.

### R11

Configurable ambient-fluid properties and physically modeled ambient-flow effects remain mandatory where the Product exposes them. Universal multiphase Navier-Stokes is optional by the word `may`.

### R20

The completion blocker is **capability truthfulness**, not the absence of every conceivable control combination. Every exposed Fast/Balanced/High/Maximum Realism control path must be runnable and must report the actual fidelity used. Controls that cannot execute must be hidden, disabled, or explicitly declared unavailable.

### R30

Reusable scenarios and restart/persistence remain required to the breadth stated by R30. Cross-version portability and arbitrary-event persistence are not new mandatory semantics. The named initial scenario family is the concrete completion target.

### R35

Approximate modes may not constrain the highest-fidelity architecture. Bounded Maximum Realism classes are acceptable for Product completion when their supported regimes are explicit and the design keeps higher-fidelity extensions replaceable/additive.

### R38 / R39

Final acceptance is blocked by any missing item in the explicit R38 list, physical iPhone qualification, dishonest fidelity disclosure, or a Product-owned final audit that cannot run at the dedicated repository boundary. It is not blocked solely because the Product does not solve unrestricted physics classes that the original requirements never made mandatory.

## Work routing consequences

- **W2 remains required:** rebuild the completion/final audit as Product-owned and self-contained.
- **W3 remains required and externally blocked:** physical iPhone Safari qualification.
- **W4 narrows to required Product breadth:** make exposed R20 controls executable/truthful and close the R30 named reusable-scenario/persistence breadth needed by the original wording. Cross-version portability is not a completion prerequisite.
- **W5 has no mandatory universal-physics implementation class solely from the previously listed unrestricted gaps.** Create Worker work only if validation of the explicit R10/R11/R38 capabilities finds a concrete missing required behavior. Do not create work merely to universalize already bounded physics.
- **W6 remains blocked** until W2-W4, W3 device evidence, and any concrete required behavior discovered by validation are closed.

## No Project-level barrier

This decision does not change Project intent or the original R1-R39 requirements. It resolves an over-broad interpretation of open Maximum Realism limits while preserving the requirement that bounded evidence remain bounded. No Project Leader escalation is required for this boundary decision.
