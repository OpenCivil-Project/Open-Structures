OpenCivil force display performance updates - 29 October 2026

These nine updated source files are already applied in E:\MetuFire\OpenCivil.
This archive preserves their current contents, including existing edits in those files.
To install elsewhere, close OpenCivil, back up the corresponding files, and extract this archive into the OpenCivil repository root, preserving app/ and core/ paths. Use all nine files together. No new dependencies are required.

Changes:
- Read unchanged matrices/results once, sharing data across members and combinations.
- Load cold force-dialog results in background jobs with stale-request protection.
- Prepare geometry and force text buffers in the worker; keep OpenGL uploads on the UI thread.
- Coalesce repeated Apply requests, cancel obsolete builds, and prevent Clear/unlock from resurrecting late results.
- Reuse CQC modal weights and batch station/component arithmetic while retaining the original formula and summation order.
- Cache only force history arrays, invalidate rewritten archives, and calculate selected history steps from one row.

Verified:
- Exact force arrays, diagram buffers, and labels against the pre-update implementation for native DEAD/LIVE, spectrum, Max/Min combinations, and LTHA envelope/selected steps.
- All six components for native/spectrum/combinations; the five existing LTHA components.
- Label modes, user scale, visibility, history rewrites, GPU buffer layouts, request coalescing, cancellation, error handling, and 11 result-loading checks.
- Syntax checks passed for all nine files.

Measured CPU diagram-build timings (GPU painting and complete application launch are excluded):
204-member DEAD: 9.26 s -> 0.55 s.
204-member LIVE: 8.78 s -> 0.14 s.
17-member spectrum: 15.38 s -> 0.30 s.
17-member combination Max: 19.71 s -> 0.53 s.
400 synthetic members: 24.54 s -> 1.46 s cold / 0.92 s warm; exact buffers.
2,000 synthetic members: 4.40 s optimized.
5,000 synthetic members: 12.08 s cold / 10.46 s warm.

Runtime still grows with member count. Solver equations and analysis behavior were not changed. Full interactive GPU rendering on the user's largest project was not benchmarked.
