# Bubble Lab Python contract reference

This package is standard-library-only. It provides typed dataclasses, semantic validation, deterministic JSON serialization, and fixture tooling for the canonical Bubble Lab contract.

Run from repository root:

    python3 -m unittest discover -s bubblelab/python/tests -v
    python3 bubblelab/python/tools/validate_contract_fixtures.py

The semantic validator complements JSON Schema with cross-object checks such as stable/unique bubble IDs, film references, event-time ordering, and INLINE versus SIDECAR invariants.
