# Bubble Lab canonical contract v1

This directory is the solver-neutral interchange contract shared by solvers, saved scenarios, validation/replay tooling, and the Web viewer.

## Versioning and compatibility

contract_version is semantic and is currently 1.0.0. Consumers reject an unknown major version unless they have an explicit migration path. Minor revisions may add optional keys but must not change existing meanings or units. Patch revisions may tighten documentation or validation without changing serialized meaning.

All physical quantities use SI. Unit-bearing property names keep the unit in the name when ambiguity would be costly.

## Sparse physical truth

Optional physical fields stay absent when unavailable. Producers must not invent pressure, film thickness, curvature, temperature, gas amount, or other physics merely to satisfy a consumer. Consumers treat absence as unavailable, never as zero. Explicit null is used only where the schema permits it.

Feature disclosures use RESOLVED, MODELED, VISUAL_ONLY, or NOT_IMPLEMENTED. The viewer must expose these disclosures rather than infer fidelity from appearance.

## Binary sidecars

ArrayRef supports INLINE for tiny deterministic fixtures and SIDECAR for production mesh/field payloads. A sidecar records URI, dtype, shape, and optional byte-range/encoding metadata. The JSON contract therefore does not force production CFD arrays into text or bind the project to a specific CFD/storage library.

## Identity, topology, frame, and checkpoint

Bubble, film, mesh, junction, frame, and event IDs are stable identifiers. Topology changes are explicit time-stamped events with provenance. A disappearing ID should be explained by merge, rupture, split, or removal when that information exists.

Frame is time-indexed physical state. A CHECKPOINT is the same canonical state with checkpoint_state metadata/references sufficient for solver continuation when the backend can provide it. Missing continuation state is never fabricated.

## Requirement traceability

This task advances R2, R4, R6-R16, R18-R24, R26-R31, R33-R36, and R38 by separating authoritative physics from rendering, representing sparse physical state and topology, supporting deterministic persistence/replay, and allowing multiple solver families behind one contract.

The fixtures are contract examples only and do not claim that Young-Laplace behavior, Plateau equilibrium, drainage, coalescence, rupture, or any other physical phenomenon has been numerically solved. Physical validation remains the responsibility of solver/validation tasks under R32.
