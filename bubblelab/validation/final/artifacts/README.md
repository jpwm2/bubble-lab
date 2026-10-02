# Generated final-validation artifacts

The canonical final-validation runner writes machine-readable JSON and human-readable Markdown here by default.

- Static assembly: `python bubblelab/validation/final/run_final_validation.py --assert-honest --no-execute`
- Full executable validation: omit `--no-execute`.
- CI uploads generated files as workflow artifacts.

A static assembly is not final Product acceptance and reports `NOT_RUN` for current executable probes.
