# Second static/modal verification batch

This batch adds **150 new shared `.mf` models**, IDs **101–250**, in 30 families
with five variants each. Each model has a `STATIC` and a `MODAL` analysis: 150
static verifications and 150 modal verifications. The first 100-model suite
remains in `../linear_modal/` with its own results.

Run from `E:\MetuFire\OpenCivil` using the existing environment:

```powershell
.\.venv-build\Scripts\python.exe -m validation.linear_modal_150.runner
.\.venv-build\Scripts\python.exe -m unittest validation.linear_modal_150.test_verification
```

The runner generates inputs and independent solutions, verifies every supplied
analytical formula against that independent solution, runs the production
static/modal file pipelines, and saves comparisons. The unittest command
replays **300 named numerical assertions** against freshly calculated
references. Model/solver hashes reject stale outputs. A real failed comparison
returns a nonzero exit status and remains visible.

Useful options: `--generate-only`, `--case <full_case_id>`, `--jobs 2`,
`--timeout 90`, `--output <directory>`, and `--compare-only`.
Single-case runs produce a selected-case report; a full run restores the
150-model report. `--compare-only` recalculates comparisons without rerunning
production solvers, and regenerates the deterministic input files first.

The batch expands mixed 3D forces/moments, interior point forces and moments,
triangular/patch/projected loads, self-weight, property modifiers, multiple
load patterns, rigid end portions, nonstandard mass sources, added masses,
rotary inertia, springs, asymmetric multi-bay/storey frames, bracing and varied
3D frame geometry. Sparse/shuffled node IDs exercise the previous node-order fix.
Exact case definitions and assumptions are in `manifest.json` and each
`expected.json`.

The independent reference is the same audited force-flexibility, virtual-work
load assembly and dense symmetric eigenanalysis used by the first batch.
See `../linear_modal/reference_audit.md` for analytical/CALFEM audit evidence.
General frames use independent assembled solutions; cases with applicable
closed forms also check those directly. Continuum formulas and discrete mass
formulas are labelled separately. All comparison thresholds match the first
batch: displacement/reaction relative tolerance `2e-6`, frequency/eigen residual
`2e-5`, and modal subspace mismatch `2e-4`, with the same absolute floors.
Reference and model preparation errors must be resolved before production
success rates are measured.

Each `cases/<id>/` contains the model, expected values, static/modal output,
matrix export, solver logs, execution provenance and `comparison.json`.
Passing-case logs and optional scratch/cache copies are compressed in
`archives/case_logs_*.zip` and `archives/scratch_*.zip`. Each ZIP includes original
suite-relative paths and a SHA-256 manifest; extract into this suite to restore
it. Native matrices remain beside their model for app result viewing. The runners
and audits regenerate logs and scratch files. See `../README.md` for cleanup.
Root outputs include `reference_integrity.json`, `summary.json`, `summary.csv`,
`report.html`, `report.md`, and the 300-assertion replay log. `work/` is scratch
space excluded from deliverables.

The new batch has **735 static and 95 modal analytical scalar checks** (830
total), all verified against independent solutions before running production.
All 150 projects also passed GUI-model serialization/deserialization without
launching an application window. Reproduce that schema audit with:

```powershell
.\.venv-build\Scripts\python.exe -m validation.linear_modal_150.audit_schema
```

See `audit_mass_support.md`, `audit_new_batch.md`, and `schema_roundtrip.json`
for the supporting audit details.

This is linear elastic frame/spring/mass verification. It does not extend the
reference to nonlinear/plastic hinges, shells, solids, cables or diaphragms.

## Measured result

The full new batch passed **150/150 static checks (100%)** and **150/150 modal
checks (100%)**, with **150/150 models passing both**. All **300 named numerical
assertions** passed. No solver subprocess failed and no production solver code
was changed during this batch. The comparisons use the same tolerances as the
first batch. The production run took approximately 238 seconds with two workers.
