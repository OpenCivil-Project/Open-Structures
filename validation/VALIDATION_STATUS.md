# Validation handoff — updated 2026-11-04

There are now **250 shared `.mf` models in two verification batches**, each
with linear-static and modal cases, independent solutions and solver results:

- [First 100 models](linear_modal/report.html): **100/100 static and 100/100 modal pass**.
- [Next 150 models](linear_modal_150/report.html), IDs 101–250: **150/150 static and 150/150 modal pass** (100% in each analysis).

All **500 named numerical assertions** pass on the original saved snapshots.
The first batch has 20 families;
the new batch adds 30 families and **735 static plus 95 modal analytical scalar
checks**. All new formulas and 150 native project roundtrips passed before
production verification. Selected reference formulations were cross-checked
against CALFEM; see each batch's README and reference audits.

Live-file note, 2026-11-04: cases **190, 205, 236 and 250** have since been
re-saved through the application and currently have no saved modal output.
The repository replay correctly stops at case 190's changed model hash. The
original delivered snapshots still pass all 500 checks against the current
solver sources. These exploratory files were preserved during the display fix;
their cached comparisons should not be treated as fresh verification of edits.

The baseline was **98/100 in each analysis**. Cases
`015_inclined_cantilever_v5` and `085_two_story_frame_v5` exposed inconsistent
indexing: DOFs used sorted IDs while the solver node list used raw record order.
`DataManager._map_nodes()` now orders its node list by ID to match DOF indices.
The original shuffled files remain as regression coverage; earlier failing
results are preserved in `linear_modal/archives/before_fix_*.zip`, with their
original paths and SHA-256 manifest.

From `E:\MetuFire\OpenCivil`:

```powershell
.\.venv-build\Scripts\python.exe -m validation.linear_modal.runner
.\.venv-build\Scripts\python.exe -m validation.linear_modal_150.runner
.\.venv-build\Scripts\python.exe -m unittest validation.linear_modal.test_verification validation.linear_modal_150.test_verification
.\.venv-build\Scripts\python.exe -m unittest discover -s tests -p test_solver_node_order.py
```

The runners regenerate their own batch. The assertions reject stale model or
solver hashes. Four focused regressions also pass; they cover sparse IDs,
permutations, supports, masses and appended link nodes.

A prior `0xC0000409` process crash on case 100 passed an isolated retry;
`linear_modal/run_history.json` preserves it; the post-fix and new 150-model
runs had no process failures. No solver code changed for the second batch.
Coverage is linear elastic frames, releases, springs
and masses; nonlinear/plastic hinges and shell/solid elements remain outside it.

Folder cleanup preserves all active models, expected answers, solver results,
comparisons, execution hashes and native matrices. Optional passing-case logs,
scratch/cache copies and the pre-fix snapshot are in each suite's `archives/`.
The earlier run history and defect controls remain visible. See [README.md](README.md)
for the folder map, restore instructions and `python -m validation.tidy` command.
After cleanup, all **500 numerical assertions** and **six cleanup checks** pass.
All 1,757 active case artifacts are unchanged byte-for-byte, and all 1,258 local
report links still resolve. The cleanup archived 1,437 optional files into five
ZIPs verified with CRC and SHA-256.

## Deformation animation follow-up — 2026-11-04

The application animation fix is in `app/canvas.py`. With extrusion enabled,
general sections have no outline; their static display already used lines,
but animation tried only solid geometry. Mixed shaped/general models also
omitted animated general-section lines.

Animation now uploads solid faces and general-section lines together, each
using peak-minus-rest displacement. Empty buffers clear obsolete geometry when
switching section mixes. Standard-section geometry and solver code are unchanged.
Restart the application to load the edited Python module, then animation can
keep **Extrude Frames/Areas** enabled for general-only and mixed models.

Five new regressions in `tests/test_animation_general_sections.py` pass; the
general-only and mixed cases failed before the fix. All **81 targeted rendering,
animation/dialog and time-history playback checks** pass. Headless smoke checks
also passed for **250/250 current static models** and **12/12 modal shapes** from
cases 001, 015, 236 and 250; the latter two use their original delivered model/result
snapshots because the current modal outputs are absent. Ten pure-torsion cases
correctly have zero centerline displacement: a section without an outline cannot
show rotation about that unchanged line. No validation input/results were edited
by this fix. No graphical app session was launched for these checks.

```powershell
.\.venv-build\Scripts\python.exe -m unittest discover -s tests -p test_animation_general_sections.py -v
```
