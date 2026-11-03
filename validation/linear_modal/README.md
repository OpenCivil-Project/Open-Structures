# Linear static and modal verification

This suite creates **100 shared OpenCivil `.mf` projects**, each containing a
`STATIC` linear-static case and a `MODAL` case. A full run performs **100 static
and 100 modal verifications** through the application's production file-analysis
entry points. It does not need to open the graphical application.

Every case has its own model, independently calculated expected solution,
actual solver results, logs, and comparison. Failed checks are retained and make
the command return a nonzero exit code. The runner does not modify solver code
or accept a failed comparison as a pass.

## Run

From `E:\MetuFire\OpenCivil`, using the existing build environment:

```powershell
.\.venv-build\Scripts\python.exe -m validation.linear_modal.runner
```

Useful options:

```powershell
# Generate all 100 models and their independent solutions without solving.
.\.venv-build\Scripts\python.exe -m validation.linear_modal.runner --generate-only

# Reproduce one case. All model files are still generated; the report covers this selection.
.\.venv-build\Scripts\python.exe -m validation.linear_modal.runner --case 015_inclined_cantilever_v5

# Set the number of simultaneous, isolated solver subprocesses.
.\.venv-build\Scripts\python.exe -m validation.linear_modal.runner --jobs 2
```

`--output <directory>` writes a separate suite tree. `--timeout <seconds>` sets
the solver subprocess time limit per model (90 seconds by default). No new
Python packages are needed in the existing `.venv-build` environment.

The saved numerical results also have **200 named unittest assertions**:

```powershell
.\.venv-build\Scripts\python.exe -m unittest validation.linear_modal.test_verification
```

This replays the 100 static and 100 modal comparisons against newly calculated
independent references without rerunning the production solvers. Model and
solver-source SHA-256 hashes invalidate stale saved results; rerun the main
runner after changing either. The assertions deliberately fail for a solver
defect rather than marking the case as an expected success.

## Models and checks

There are **20 structural families with five variants each**. Variants change
lengths, elastic moduli, density, section properties, mesh density, and, where
appropriate, load location or orientation. The minimum line mesh is six
elements; frame members use two to six elements each.

| Family | Physical model and verification emphasis |
|---|---|
| `cantilever_tip_y` | Euler–Bernoulli cantilever; force in global Y, tip displacement and slope |
| `cantilever_tip_z` | Cantilever bending about the second section axis; force in global Z |
| `inclined_cantilever` | Inclined/vertical 3D Timoshenko cantilever, local-axis roll, transformed tip force |
| `cantilever_udl` | Cantilever under uniform member load; tip displacement, slope, root shear |
| `cantilever_tip_moment` | Pure bending moment at the free end; displacement and rotation |
| `axial_bar` | Uniform axial rod; extension, reaction, exact discrete lumped-mass frequencies |
| `torsion_bar` | Uniform torsional bar with explicit nodal rotary inertias; twist and chain frequencies |
| `simply_supported_point` | Pin/roller beam with a point load inside an element; reactions and support slopes |
| `simply_supported_udl` | Pin/roller beam under UDL; center displacement, slope, reaction |
| `fixed_fixed_point` | Fixed-ended beam with a center force; center displacement and end actions |
| `fixed_fixed_udl` | Fixed-ended beam under UDL; center displacement and end moment |
| `propped_udl` | Fixed/pinned propped cantilever; statically indeterminate support reactions |
| `continuous_two_span` | Equal two-span continuous beam under UDL; three support reactions |
| `rigid_portal` | Fixed-base portal with rigid joints, lateral forces and beam UDL |
| `pinned_base_portal` | Portal with pinned bases and rigid roof joints; frame stability and sway |
| `released_beam_portal` | Fixed-base columns with roof-member bending end releases; cantilever-column sway |
| `two_story_frame` | Two-story, two-column frame with lateral floor forces and beam UDL |
| `space_frame` | Four-column 3D roof frame under biaxial lateral and gravity loads |
| `stepped_axial_chain` | Axial chain with varying cross-sectional area; summed axial compliance |
| `elastic_support_beam` | Pin and vertical elastic support; spring reaction and support settlement |

All 100 cases compare complete nodal displacement/rotation vectors, support
force/moment vectors, modal frequencies, mode shapes, and masses with the
independent discretized reference. The suite additionally contains **220 scalar
analytical static checks and 70 analytical modal frequency checks**, distributed
across the families for which concise closed-form or exact discrete formulas
apply. Not every frame has a textbook closed-form solution.

Two valid projects deliberately reorder their input node records without
changing physical node IDs or connectivity:

- `015_inclined_cantilever_v5`
- `085_two_story_frame_v5`

These test invariance to JSON record ordering. The native `DataManager` maps
indices using sorted IDs but previously stored nodes in input order, while assembly code
accesses `dm.nodes[index]`. The independent reference resolves coordinates by
ID. These cases expose that mismatch instead of arranging records to hide it.

## Independent reference and analytical solutions

`reference.py` imports no OpenCivil element, assembly, mass, or solver routines.
It derives frame stiffness from integrated force flexibility and Castigliano's
theorem, integrates member loads against the independently derived static
interpolation, and uses dense SciPy linear/eigenvalue solves. This is a second
calculation of the same discretized model.

Textbook/continuum comparisons are recorded separately. Examples include:

- Cantilever tip force: `δ = PL³/(3EI)`, `θ = PL²/(2EI)`; Timoshenko tip
  displacement adds `PL/(GAs)`.
- Cantilever UDL: `δ = qL⁴/(8EI)` and `θ = qL³/(6EI)`.
- Simply supported UDL: `δ_mid = 5qL⁴/(384EI)`.
- Fixed-fixed center force: `δ_mid = PL³/(192EI)`; fixed-fixed UDL:
  `δ_mid = qL⁴/(384EI)`.
- Axial extension: `δ = PΣ[Li/(EiAi)]`; torsional twist: `θ = TL/(GJ)`.
- Euler–Bernoulli first bending frequency:
  `f1 = β1² sqrt(EI/(ρm A))/(2πL²)`, with `β1 = 1.8751040687` for a
  cantilever, `π` for a pin/roller beam, and `4.7300407449` for a fixed-fixed beam.
- Uniform fixed-free axial rod, lumped interior mass `m` and half mass at the
  tip: `fr = sqrt(4k/m) sin[(2r−1)π/(4n)]/(2π)`.
- Uniform fixed-free torsional chain with equal nodal rotary inertia `Jm`:
  `fr = sqrt(4k/Jm) sin[(2r−1)π/(4n+2)]/(2π)`.

The actual signed values, node/DOF locations, and formulas are stored in
`manifest.json` and each `expected.json`. The runner gates actual solver results
against these formulas as well as against the independent reference.

Sources:

- Gere and Timoshenko, *Mechanics of Materials*: bar, beam, and support-action formulas.
- Clough and Penzien, *Dynamics of Structures*: vibration and discrete-chain eigenproblems.
- [Scott Whitney, University of Nebraska: Vibrations of Cantilever Beams](https://emweb.unl.edu/mechanics-pages/Scott-Whitney/325hweb/Beams.htm): cantilever static and frequency derivations.
- [CALFEM for Python element library](https://github.com/CALFEM/calfem-python/blob/master/src/calfem/core.py): public bar/frame formulations and a useful library benchmark starting point. The suite does not import CALFEM or claim that CALFEM was run.
- [OpenSees Example 3.1](https://github.com/OpenSees/OpenSees/blob/master/EXAMPLES/ExampleScripts/Example3.1.tcl): a public portal-frame modelling example, not an analytical solution used as the numerical oracle here.

## Mass model and tolerances

All `.mf` quantities are SI base values. `info.units` controls display units;
material `rho` is **weight density in N/m³**. Physical mass density is
`rho / 9.80665`. Native frame self-mass is lumped equally at element endpoints,
using gross area and the mass modifier, with no automatic rotary self-inertia.
The torsion models supply rotary inertia through zero-stiffness mass-only links.

The native modal engine regularizes each massless free DOF with a mass equal to
`1e-6` times the smallest positive free mass. The reference reports both the
ideal massless-DOF-condensed spectrum and the explicitly regularized spectrum.
Native modal checks use the latter, so an undocumented mass floor cannot be
mistaken for agreement with ideal continuum dynamics. Elastic releases also
carry a documented tiny native stiffness floor in the regularized reference.

Default gates are:

| Check | Tolerance |
|---|---|
| Nodal displacement and rotation | `2e-6 × abs(expected) + 1e-10` per component |
| Support force and moment | `2e-6 × abs(expected) + 1e-4` per component (N or N·m) |
| Free-DOF static equilibrium residual | Relative residual ≤ `2e-6` |
| Frequencies against independent regularized reference | Relative error ≤ `2e-5` |
| Modal eigen residual, mass normalization, orthogonality | ≤ `2e-5` |
| Modal subspace mismatch, `1 − MAC` | ≤ `2e-4` |
| Physical assembled nodal masses | Relative `1e-8`, absolute `1e-10` |
| Textbook static formulas | Relative `2e-6`, with displacement/reaction absolute floors above |
| Exact discrete axial/torsional frequencies | Relative `1e-6`, absolute `1e-9` Hz |
| Continuum first bending frequency | Relative 2%; fixed-fixed 3%, plus `1e-9` Hz |

Continuum frequency tolerances allow the specified finite lumped-mass mesh
error; they are not loosened according to a failing result. Mode count,
finite/positive/sorted frequencies, and period/frequency/omega/eigenvalue
identities are also checked. Mode-shape comparison uses repeated-eigenvalue
subspaces, allowing arbitrary signs and bases of repeated modes.

## Saved files

At the suite root:

- `manifest.json`: all 100 cases and analytical metadata.
- `summary.json` and `summary.csv`: machine-readable results and pass/fail totals.
- `report.html`: searchable local report linking to every case artifact.
- `report.md`: concise report suitable for source control.
- `schema_roundtrip.json`: independent GUI-model schema roundtrip audit.
- `reference_audit.md`: analytical and CALFEM reference cross-check evidence.
- `node_order_diagnostic.md` and `node_order_controls.json`: isolated node-order defect and passing sorted-record controls.
- `run_history.json`: initial sweep and targeted retry provenance.
- `verification_replay.log`: the 200 named numerical assertion results.

In `cases/<id>/`:

- `<id>.mf`: native project containing both analysis cases.
- `expected.json`: independent static/modal solutions, ideal/regularized details, and formula comparisons.
- `<id>_STATIC_results.json` and `<id>_MODAL_results.json`: production solver results.
- `comparison.json`: individual checks, errors, and tolerances.
- `<id>_STATIC.log`, `<id>_MODAL.log`, and `<id>_process.log`: diagnostics recreated by each run; passing-case copies can be archived.
- `execution.json`: subprocess outcome and model identity information.
- `<id>_STATIC_matrices.json`: native static matrix export, when produced.

`work/` is ignored scratch space, recreated by audits when needed. Optional logs
and scratch/cache copies are retained in `archives/case_logs_*.zip` and
`archives/scratch_*.zip`; each ZIP includes original suite-relative paths and a
SHA-256 manifest. Extract into this suite folder to restore them. Native matrices
remain beside the model for app result viewing. See `../README.md` for cleanup.
Reports describe only the selected run; a
single-case command replaces the root summary with that selection. A full run
restores the 100-model summary.

## Current validation status

The post-fix run passes **100/100 static and 100/100 modal checks**, with all 200
named numerical assertions passing. The original result was 98/100 in each
analysis. A shared solver node-ordering defect was corrected in
`core/solver/linear_static/data_manager.py`; the two original shuffled projects
remain in the suite and now pass without changing their input record order.
Before-fix outputs are preserved in `archives/before_fix_*.zip`, with original
`baseline_before_node_order_fix/` paths inside the archive.

Four focused regressions also pass:

```powershell
.\.venv-build\Scripts\python.exe -m unittest discover -s tests -p test_solver_node_order.py
```

They cover noncontiguous IDs, all record permutations, static/modal response,
supports, springs, mass and appended link nodes. See
`../VALIDATION_STATUS.md` for the short handoff note and `run_history.json` for
the before/after run history.

## Native project compatibility

The GUI's `StructuralModel.load_from_file()` and `save_to_file()` were exercised
without launching windows: **100/100 projects passed** preservation checks for
node coordinates/IDs, topology, material and section properties, release flags,
loads, active DOFs, mass sources/links, and elastic support matrices. Reproduce
that audit with:

```powershell
.\.venv-build\Scripts\python.exe -m validation.linear_modal.audit_model_roundtrip
```

The GUI loader creates its usual additional `DEAD` and `TEST` cases when
constructing/loading these projects. The explicitly requested `STATIC` and
`MODAL` cases retain their definitions. Display-unit application remains the
GUI caller's responsibility; numeric model values survive the roundtrip.

## Scope

This suite covers elastic 3D frame elements, axial/torsional behavior, bending
and shear, elastic support springs, member point/UDL loads, elastic end releases,
mass assembly, and unprestressed eigenvalue analysis. Here a hinge is an
**elastic moment release**, not a nonlinear/plastic fiber hinge.

It does not establish validation of shell/solid/cable elements, nonlinear
materials, plastic hinges, P–Delta/buckling, rigid diaphragms, seismic analysis,
or time integration. Matching another discretized reference is not proof of
mesh convergence or certification. The separate continuum checks make that
distinction visible.
