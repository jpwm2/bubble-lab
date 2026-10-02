# Accepted Historical Validation Evidence

This directory is Product-owned validation evidence used by the Bubble Lab completion and final-validation assemblies.

## Provenance

- Historical Product snapshot: `be27cbe8e0c03f27f9cb019d04658e72968a74f1`
- Control Plane removal commit: `e72ed60ac3df6494f86bfe49d637b7e14ff11a72`
- The JSON records in `historical-deliveries/` are exact copies of the already-sanitized public validation records that existed immediately before Control Plane removal.
- Their embedded `source_path` and `source_sha256` fields are provenance metadata only. Runtime validation reads the Product-owned files in this directory.

## Boundary

These records contain accepted Product validation outcomes only. They do **not** restore task queues, claims, prompts, worker instructions, private logs, branch ownership, or any other Agent Control Plane state.

R37 traceability is preserved by the Product requirement baseline plus this immutable historical provenance. Product execution remains independent of the removed `agent/`, `orchestra/`, and `tasks/` runtime paths.
