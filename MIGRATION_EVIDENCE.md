# Bubble Lab migration evidence boundary

- `bubblelab/` is the exact migrated Product snapshot.
- `orchestra/REQUIREMENTS.md` is the accepted Bubble Lab product requirements baseline.
- `tasks/*/deliverable.json` contains only sanitized historical validation outcomes needed by the legacy completion audit.
- `agent/WORKER_PROTOCOL.md`, `orchestra/ARCHITECTURE.md`, and `orchestra/TASK_INDEX.json` are non-operational digest stubs; the private Agent Control Plane was not migrated.
- No private task logs, prompts, queue/claim state, worker instructions, or branch metadata are intentionally published.
