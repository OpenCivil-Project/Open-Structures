# Independent audit of the second 150-model batch

Audit date: 2026-11-03. This audit reads the generated model physics and
independent references; it does not tune formulas to production solver results.

There are 150 unique new model specifications, numbered 101 through 250.
Semantic fingerprints include geometry, connectivity, materials, sections,
supports/springs, loads, mass sources and mass-only links while ignoring case
names, input record order and node/element ID labels. All 150 fingerprints are
unique, and none duplicates one of the original 100 specifications. This is a
check for equivalent stored specifications, not a claim that every topology is
a new published external benchmark.

All 150 independent force-flexibility references construct successfully.
All **735 static** and **95 modal** analytical scalar checks pass against those
references before production success is measured. Each model has at least five
free DOFs, so its request for three modes is not reduced by the native
`free_dofs - 2` limit. All reference fundamental frequencies are positive;
the smallest is approximately 0.674474 Hz.

The beam audit reviewed six-action Timoshenko cantilever compliance, off-mesh
point forces/couples, closed-form integration of piecewise-linear load
profiles, projected gravity, self weight and weight modifiers, section
stiffness modifiers, load-pattern superposition including inactive loads, and
clear-length compliance with a rigid root segment. The corresponding 50 beam
references satisfy 360 static and five modal formula checks.

The mass/support audit reviewed equal-mass and half-tip-mass axial chain
spectra, distributed/point/nodal load-pattern mass partition, uniform self-mass
scaling, added tip-mass characteristic roots, fixed-fixed rotary chain
frequencies, a tip axial support, a symmetric positive-definite coupled global
spring with Castigliano tip flexibility, and the hyperbolic displacement
solution for a uniform nodal foundation chain. These 50 references satisfy
255 static and 90 modal formula checks.

The new frame families include asymmetric multibay and setback buildings,
braced and mixed-support/release frames, 3D branching and skew roofs, a tapered
box frame, and zigzag, reversed-connectivity rolled and polygonal curved
cantilevers. The single-root families satisfy 120 exact equilibrium reaction
checks. Complex frame static/modal responses use independent assembled
stiffness and mass solutions. Models use at most 24 nodes in this frame group.

The previously documented numerical CALFEM cross-check exercised selected
planar `beam2e` and `beam2te` formulations. It supplies evidence for the shared
independent reference formulations; it is not a claim that all new 3D frames
were separately solved by CALFEM. See
`../linear_modal/reference_audit.md` for the checked source hash and measurements.

Modal results retain the native lumped translational mass convention and
explicit rotary inertias, with physical and numerically regularized spectra
distinguished. Continuum frequency tolerances allow the declared finite mesh;
exact discrete spectra have tighter tolerances. Elastic end releases are
linear connections, not nonlinear plastic hinges.

Production success rates belong to the new batch's `summary.json` and
`report.html`. Reference consistency alone does not imply that the production
solver passes these new checks.
