# Completion Criterion 5 migration validation evidence

## Scope

This document records Product-owned validation evidence for GitHub Issue #1 and Completion Criterion 5: prove that Bubble Lab tests, validation, and tooling were not lost or broken because of the repository migration.

The validation deliberately does **not** restore Agent Control Plane assets such as `agent/`, `orchestra/`, `tasks/`, `.ai/`, queue files, or claim files. Historical checks that still depend on those assets are characterized separately rather than treated as Product migration gates.

## Compared repository boundaries

| Boundary | Commit | Meaning |
| --- | --- | --- |
| dedicated-main | `e72ed60ac3df6494f86bfe49d637b7e14ff11a72` | Dedicated Product repository after Agent Control Plane/process material was removed |
| pre-control-plane-removal | `be27cbe8e0c03f27f9cb019d04658e72968a74f1` | Immediately preceding repository snapshot; the migrated `bubblelab/` Product snapshot is equivalent while historical process/control-plane material is still present |

The comparison isolates repository-boundary effects from Product behavior changes.

## Validation harness and revisions

PR branch: `agent/criteria-5-validation`

Final validation-harness revision used for the authoritative runs:

`addf3ca891d238da7deb5e822a8d3ead9126f221`

The exhaustive harness inventories every discovered `bubblelab/**/test_*.py` file, runs Product-owned suites as the pass/fail migration gate, records the historically Control-Plane-coupled completion/final suites separately, validates canonical contract fixtures, compiles Product Python sources, characterizes the completion audit, and tests/builds the viewer.

A harness-only defect discovered during this Work was also fixed: job-summary text used the invalid Bash expression `${matrix.boundary}` instead of GitHub Actions interpolation `${{ matrix.boundary }}`. The correction was revalidated by the authoritative runs below. This was a validation-harness defect, not a migrated Product behavior regression.

## Authoritative runs

### Bounded smoke

GitHub Actions workflow: **Criteria 5 migration smoke**

- Run `36682100876` — **success**
- both `dedicated-main` and `pre-control-plane-removal` jobs succeeded

The smoke workflow covers representative contract, runtime, solver, validation, compile, and viewer behavior and remained green after the exhaustive harness changes.

### Exhaustive migration validation

GitHub Actions workflow: **Criteria 5 migration validation**

- Run `36682100918` — **success**
- dedicated-main job `109779595184` — **success**
- pre-control-plane-removal job `109779594961` — **success**
- environment: Ubuntu 24.04, Python 3.12, Node 22

Inventory reported on each boundary:

- 96 discovered Python test files total
- 83 Product-gate test files
- 6 legacy-coupled completion test files
- 7 legacy-coupled final-validation test files

All 83 Product-gate test files were exercised by directory-level `unittest discover` on both boundaries. Covered categories include:

- Python contract tests
- research/prototype tests
- runtime and runtime-server tests
- boundary/contact/equilibrium/event/gas-network/multiregion/plateau-border/precontact/rim-breakup/singular-breakup/thin-film/transient solver tests
- validation tests

Every Product-gate directory passed on both boundaries. No Product-owned test failure attributable to the dedicated repository boundary was observed.

## Product-owned tooling inventory and validation treatment

The migrated tree contains Product tooling under, among other paths:

- `bubblelab/python/tools/`
- `bubblelab/research/*/tools/`
- `bubblelab/runtime/tools/`
- `bubblelab/runtime/server/tools/`
- solver-family `tools/` directories under `bubblelab/solvers/`
- `bubblelab/validation/tools/`
- `bubblelab/validation/final/`
- viewer scripts under `bubblelab/viewer/`

Representative/canonical entry points include contract-fixture validation, runtime/session/replay tools, solver benchmarks/exporters, equilibrium/transient validation runners and report tools, final-validation entry points, and viewer build scripts.

The migration acceptance run does not invoke every benchmark/export/report command independently because many are scenario-specific producers rather than standalone migration gates. Their source presence was inventoried, the entire `bubblelab/` Python source tree was compiled successfully on both boundaries, associated behavior is covered by the exhaustive Product-owned test suites, and the canonical fixture/validation/viewer entry points below were executed directly.

Direct tooling/validation results on both boundaries:

| Validation/tooling entry point | dedicated-main | pre-control-plane-removal | Classification |
| --- | --- | --- | --- |
| Product-gate Python test inventory | all pass | all pass | equivalent |
| `python bubblelab/python/tools/validate_contract_fixtures.py` | 5/5 fixtures pass | 5/5 fixtures pass | equivalent |
| `python -m compileall -q bubblelab` | pass | pass | equivalent |
| viewer `npm test` | 75/75 pass | 75/75 pass | equivalent |
| viewer `npm run build` | pass (`dist/` built) | pass (`dist/` built) | equivalent |

## Legacy-coupled validation comparison

The completion/final validation suites were intentionally kept out of the Product pass/fail gate and executed separately so their repository-boundary dependency was explicit rather than silently skipped.

### `bubblelab/validation/completion/tests`

- dedicated-main: 47 test cases, 47 errors
- pre-control-plane-removal: 47/47 pass

The dedicated-main errors transitively enter the historical completion audit and fail because `orchestra/REQUIREMENTS.md` no longer exists in the Product repository.

### `bubblelab/validation/final/tests`

- dedicated-main: 31 test cases; 25 pass, 6 errors
- pre-control-plane-removal: 31/31 pass

The six dedicated-main errors are the final-validation assembly paths that transitively enter the same completion audit and require the same removed `orchestra/REQUIREMENTS.md` input. The remaining final-validation tests pass in the dedicated repository.

### `bubblelab/validation/completion/run_completion_audit.py --assert-honest`

- dedicated-main: nonzero exit because the historical audit reads removed Control Plane/process material, beginning with `orchestra/REQUIREMENTS.md`
- pre-control-plane-removal: exit 0; 39 requirements audited, 30 satisfied, 9 incomplete, `final_acceptance_ready=False`

Classification for all three differences above:

**legacy Control Plane coupling / expected repository-boundary effect — not a Product migration regression.**

Restoring `orchestra/`, `tasks/`, `agent/`, or other Control Plane state to make those historical checks green would violate the intended Product boundary and is therefore not an acceptable migration fix.

## Other observed failure/advisory classification

`npm ci` reports one high-severity dependency advisory on both compared boundaries. It does not fail dependency installation, viewer tests, or viewer build.

Classification:

**pre-existing / environment-independent dependency-maintenance gap — not a repository-migration regression.**

No confirmed migration regression was found, so no Product source defect required a migration-specific fix.

## Scope hygiene

The PR diff is limited to:

- `.github/workflows/criteria-5-smoke.yml`
- `.github/workflows/criteria-5-validation.yml`
- `docs/migration/criteria-5-validation-evidence.md`

No excluded Agent Control Plane directories/assets were added to the Product repository.

## Completion Criterion 5 conclusion

The evidence supports the following migration conclusion:

- the migrated Product test surface remains present and the exhaustive Product-gate suites pass at the dedicated repository boundary;
- contract-fixture tooling remains functional;
- Product Python sources compile at the dedicated boundary;
- viewer tests and build remain functional;
- repository-boundary-only failures in the historical completion/final validation stack are explained and reproduced as dependencies on intentionally removed Control Plane/process material;
- no Product migration regression was identified;
- no excluded Control Plane assets were reintroduced to manufacture a green result.

Therefore, the Worker evidence supports **Completion Criterion 5: Product tests / validation / tooling were not lost or broken because of the repository migration**.

Product-wide acceptance and Project completion remain a Product Leader decision under the role boundary; this document supplies the reproducible evidence for that decision.
