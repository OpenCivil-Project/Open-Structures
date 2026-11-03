# Independent reference audit

Audit date: 3 November 2026. This audit did not change the production solver or install another finite-element package.

The suite reference imports no OpenCivil element, assembly, mass, or solver routines. Its frame stiffness follows integrated force flexibility, its equivalent nodal loads follow virtual work with exact static interpolation, and its modal solve uses dense symmetric compliance eigenanalysis. These provide an independent implementation of the specified discretized model.

## Analytical checks across the complete suite

All 100 reference solutions were independently recomputed from the saved model files and their manifest specifications. All 220 supplied static formula checks and all 70 supplied modal formula checks satisfied their intended tolerances. These counts are scalar checks; the suite has 100 static analyses and 100 modal analyses.

The audited formulas cover cantilever tip force, uniform load and tip moment; both bending directions; inclined Timoshenko cantilevers; axial extension; uniform torsional chains; simply supported, fixed-fixed, propped and two-span beams; released portal sway; stepped axial compliance; and elastic support reactions/settlement. General frame models use the independent assembled reference where a simple closed form is unavailable.

| Modal formula family | Largest relative reference-to-formula error |
|---|---:|
| Euler-Bernoulli cantilevers, first mode | 1.2584112% |
| Simply supported Euler-Bernoulli beams, first mode | 0.00560461% |
| Fixed-fixed Euler-Bernoulli beams, first mode | 0.0424922% |
| Exact discrete axial bar, first three modes | 2.9500e-15 |
| Exact discrete torsional chain, first three modes | 2.7654e-15 |

The cantilever maximum occurs in the coarsest six-element mesh and is within its 2% continuum comparison tolerance. Exact discrete chain formulas are checked at much tighter tolerances. Zero analytical response components require an absolute tolerance to account for floating-point roundoff; dividing by a zero expected value is not an accuracy measure.

The runner applies applicable formula checks directly to actual production results as part of their static or modal pass/fail status, in addition to the independent discretized reference comparisons.

## CALFEM formulation cross-check

The public CALFEM for Python source was fetched over HTTPS and the complete `beam2e` and `beam2te` function bodies were inspected before executing only those functions in memory. No downloaded package was installed, and the external module as a whole was not executed.

Source: <https://raw.githubusercontent.com/CALFEM/calfem-python/master/src/calfem/core.py>

Human-readable source: <https://github.com/CALFEM/calfem-python/blob/master/src/calfem/core.py>

SHA-256 of the fetched UTF-8 source text:

`9d0a13275f0f1e1c700cbb5ce42410528350a218e7743e331836fec8d73b5194`

`master` is a moving branch; this hash identifies the source used for these measurements.

For the two saved planar cases below, CALFEM `beam2e` assembled stiffness and uniform-load vectors from coordinates, connectivity, material and section data. Nodal loads were then applied, and independent dense static and generalized eigenvalue solves were performed. The modal comparison explicitly used the suite's translational lumped mass and massless-rotation regularization convention, rather than CALFEM's consistent beam mass matrix.

| Saved case | Relative stiffness matrix difference | Relative applied load vector difference | Relative displacement vector difference | Largest relative error in first three frequencies |
|---|---:|---:|---:|---:|
| `016_cantilever_udl_v1` | 3.9892e-17 | 6.8794e-17 | 9.0130e-14 | 3.7651e-9 |
| `066_rigid_portal_v1` | 8.9835e-17 | 1.0208e-16 | 5.9649e-16 | 7.3835e-12 |

Matrix and vector differences above are Euclidean/Frobenius norm differences divided by the corresponding CALFEM norm. The saved planar cases compare global UX, UY and RZ degrees of freedom.

An additional non-axis-aligned planar Timoshenko element was compared against CALFEM `beam2te`: endpoints `(0, 0)` and `(3, 2)` m, E = 70 GPa, G = E/2.6, A = 0.04 m², I = 8e-5 m⁴, and effective shear area = 0.03 m². The relative global stiffness matrix difference was `7.5370e-18`.

These cross-checks verify the independent reference's beam stiffness, coordinate transformation, uniform-load assembly, static response and eigenvalue solution through an established public FE formulation. They do not constitute a CALFEM consistent-mass comparison or a claim that every generated case is an established external benchmark.

## Comparison safeguards reviewed

The runner checks result JSON status and subprocess outcome, clears stale case result files before execution, compares individual nodal response components with absolute and relative tolerances, and checks independent free-DOF equilibrium. Its modal checks include the expected mode count, positive sorted frequencies, period/frequency/eigenvalue consistency, independent eigen residuals, mass orthogonality/normalization, physical assembled nodal mass, and modal subspace agreement. Comparing eigenspaces permits arbitrary signs and bases for repeated eigenvalues.

The reference records physical frequencies separately from frequencies with the native solver's artificial mass and released-rotation stiffness terms. Agreement with the latter is a regression result for the chosen numerical conventions; it does not validate those artificial terms as physical inertia or physical stiffness.

One-joint mass-only links produce extra restrained phantom nodes in the native solver. They do not change the original free degrees of freedom or the physical masses used by this suite, so comparisons on the original node IDs remain valid.

## Confirmed node-order defect (before the fix)

An independent in-memory production probe confirmed that changing only the order of node records changes the assembled stiffness. `DataManager._map_nodes` assigns degrees of freedom by sorted IDs while retaining raw node-record order, and the batched assembler obtains member coordinates by indexing that raw-order list with the sorted degree-of-freedom index.

For a three-node L-shaped cantilever under a 1,000 N tip X load, node order `[1, 2, 3]` gave tip UX = `0.0067556875` m, UZ = `-0.0015` m and RY = `0.002625` rad. Reordering the same records to `[3, 1, 2]`, with unchanged IDs, coordinates and connectivity, gave UX = `0.0004655096154` m, UZ = `0.0009394023646` m and RY = `-0.0004160251472` rad. The relative stiffness matrix difference was `1.1140376`, and the relative displacement vector difference was `1.0066388`.

The suite retains shuffled/reversed node-record cases as regression coverage.
The independent reference maps coordinates by node ID and is invariant to record
order. The production fix aligns the initial solver node list with its sorted
DOF indices; see `node_order_diagnostic.md` and the latest run summary.

## Limits

This is a linear elastic frame, spring and mass-only-link verification suite. Its dense independent reference does not cover shells, cables, diaphragm constraints, nonlinear material hinges or nonlinear analyses. The generated moment-release frame checks concern ideal elastic end releases. Each modal analysis requests the first three modes; the suite does not certify every higher mode. Continuum beam comparisons distinguish discretization error from numerical solver error, and an independent discretized match alone does not establish continuum convergence.
