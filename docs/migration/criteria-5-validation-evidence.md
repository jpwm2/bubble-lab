# Completion Criterion 5 migration validation evidence

## Scope

This document records Product-owned validation evidence for GitHub Issue #1. It is intentionally scoped to proving that representative Product tests, validation, contract tooling, and viewer build/test behavior survive the repository migration without reintroducing Agent Control Plane assets.

The exhaustive Product-owned Python suite remains available through `.github/workflows/criteria-5-validation.yml`; the bounded acceptance slice is `.github/workflows/criteria-5-smoke.yml`.

## Compared repository boundaries

| Boundary | Commit | Meaning |
| --- | --- | --- |
| dedicated-main | `e72ed60ac3df6494f86bfe49d637b7e14ff11a72` | Current dedicated Product repository after Agent Control Plane artifacts were removed |
| pre-control-plane-removal | `be27cbe8e0c03f27f9cb019d04658e72968a74f1` | Immediately preceding repository snapshot; `bubblelab/` is the same migrated Product snapshot, with historical/process stubs still present |

The comparison is therefore useful for distinguishing a Product migration regression from behavior caused only by removal of legacy process/control-plane material.

## Executed evidence

GitHub Actions workflow: **Criteria 5 migration smoke**

- Run: `36671854451`
- dedicated-main job: `109748354455` — **success**
- pre-control-plane-removal job: `109748354698` — **success**
- Runtime: Ubuntu 24.04, Python 3.12, Node 22

Both boundaries executed the same validation sequence.

| Validation | dedicated-main | pre-control-plane-removal | Result |
| --- | --- | --- | --- |
| Python contract reference tests | 6/6 pass | 6/6 pass | equivalent |
| Canonical contract fixture validator | 5 fixtures pass | 5 fixtures pass | equivalent |
| Runtime representative tests | 5/5 pass | 5/5 pass | equivalent |
| Equilibrium solver representative tests | 5/5 pass | 5/5 pass | equivalent |
| Equilibrium validation representative tests | 6/6 pass | 6/6 pass | equivalent |
| Python source compile | pass | pass | equivalent |
| Viewer `npm test` | 75/75 pass | 75/75 pass | equivalent |
| Viewer `npm run build` | pass (`dist/` built) | pass (`dist/` built) | equivalent |

No Product-owned migration regression was observed in this bounded slice.

## Legacy completion-audit classification

The legacy completion audit was executed separately from the Product-owned pass/fail gate so its dependency could be characterized rather than silently ignored.

### dedicated-main

`bubblelab/validation/completion/run_completion_audit.py --assert-honest` exits **1** because `bubblelab/validation/completion/audit.py` tries to read:

`orchestra/REQUIREMENTS.md`

That file is intentionally absent from the dedicated Product repository after the Control Plane/process-material removal commit.

### pre-control-plane-removal

The same audit exits **0** and reports:

- 39 requirements audited
- 30 satisfied
- 9 incomplete
- `final_acceptance_ready=False`

### Classification

**legacy Control Plane coupling / expected repository-boundary effect — not a Product migration regression.**

The Product-owned validation slice is equivalent across the two boundaries, while the completion audit alone changes behavior because it reads files deliberately removed from the Product repository. Restoring `orchestra/`, `tasks/`, `agent/`, or other Control Plane assets would violate the migration boundary and is not an acceptable fix.

## Additional observation

`npm ci` reported one high-severity dependency advisory on both compared boundaries. It did not fail install, tests, or build and is not specific to the repository migration. Treat it as a pre-existing/non-migration dependency-maintenance gap rather than evidence against Completion Criterion 5.

## Current conclusion

This evidence establishes a meaningful validated slice of Completion Criterion 5:

- contract behavior survives migration;
- canonical fixture tooling survives migration;
- representative runtime, solver, and validation behavior survives migration;
- viewer tests and build survive migration;
- the known completion-audit failure is explained by intentional legacy Control Plane removal rather than a Product regression.

The exhaustive workflow is retained to extend the evidence over all discovered Product-owned Python test directories. Until that broader run is accepted, this document does **not** claim that every Product-owned test/tool entry point has been exhaustively validated.
