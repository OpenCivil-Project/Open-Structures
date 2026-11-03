# Node-record order defect and fix

Before the fix, two physically valid projects failed both analyses:
`015_inclined_cantilever_v5` and `085_two_story_frame_v5`. The maximum frequency
errors among the first three modes are 19.6324% and 13.3817%, respectively.
The static errors also exceed the declared tolerances by large margins.

The cause was inconsistent indexing. `DataManager._map_nodes()` assigns DOF
indices in sorted node-ID order (`core/solver/linear_static/data_manager.py`),
but previously stored `dm.nodes` in input record order. The batched assembler
then obtains member coordinates from `dm.nodes[idx]`
(`core/solver/linear_static/assembler.py`, lines 286–287). Those list positions
need not correspond to the node IDs used for connectivity and DOFs.

The same assembly serves both analysis types, so the discrepancy affects both
stiffness-dependent static response and eigenvalues/mode shapes. Physical nodal
mass still agrees with the independent reference in these two cases.

As an isolated control, copies of the exact two projects were sorted by node ID
while preserving every ID, coordinate, member connection, material, section,
load, support and mass. Both sorted copies pass every static and modal check.
The control comparisons are preserved in `node_order_controls.json`; original
failing projects remain in `cases/`. Temporary sorted input/results are retained
in `archives/scratch_*.zip`, under the original `work/node_order_probe/` paths.

The independent reference accesses coordinates by node ID and is invariant to
record order. The production fix sorts the initial solver node list by ID in
`DataManager._map_nodes()`, so list positions match the already sorted DOF
indices. The source `.mf` records remain untouched. Appended link/cable phantom
nodes retain the same invariant because their index is the list's append
position. The original shuffled cases remain in the suite as regression checks.

After the fix, the full suite passes **100/100 static and 100/100 modal
verifications**, and all **200 named numerical assertions** pass. Four focused
tests in `tests/test_solver_node_order.py` also pass; they cover sparse node IDs,
all record permutations, static/modal response, supports/springs/mass, and an
appended mass-only link node. The focused tests fail under simulated pre-fix
record ordering, confirming that they detect this defect.

`archives/before_fix_*.zip` preserves the preceding summary and both failing
projects/results, under original `baseline_before_node_order_fix/` paths. The root `report.html` and `summary.json` describe the
latest run; `run_history.json` records the before/after outcome.

The full sweep initially also encountered one Windows process fast-fail
(`0xC0000409`) on `100_elastic_support_beam_v5` before any results were written.
Its isolated rerun completed and passed all checks. `initial_execution.json`
and `run_history.json` preserve both attempts. The full post-fix run had no
process failures; the earlier observation does not establish the crash cause.
