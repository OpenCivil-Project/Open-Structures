# Mass and elastic-support reference audit

Audit date: 2026-11-03. IDs 151–200 contain 50 new shared models in ten
families. All 50 independent references constructed successfully, and all
**255 static plus 90 modal analytical checks** passed their declared tolerances
before production solver measurement. A second agent independently repeated
the formula/reference audit with the same result. This audit does not assert
production solver success; see the batch report for that result.

The mass-source cases cover section Mass modifiers, gravity-pattern mass from
nodal loads, uniform member loads and interior point loads, self mass combined
with superimposed nodal mass, explicit concentrated tip masses, and explicit
rotary inertia in fixed-fixed torsional chains. Pattern scale factors are
included when constructing the known masses. The pattern cases exclude those
loads from STATIC, keeping their inertia and static load definitions explicit.

Axial chain spectra distinguish equal masses at every free node from the
half-mass free endpoint produced by uniform member mass. Fixed-fixed torsional
spectra use equal rotary inertia at each interior node. These are exact
discrete sine formulas, checked at relative tolerance 1e-6. The axial uniform
foundation adds identical nodal springs and masses: its exact spectrum is the
unfounded chain spectrum plus ks/m in omega squared, and its static displacement
is the hyperbolic recurrence solution.

The concentrated-tip-mass beam check solves the standard Euler-Bernoulli
characteristic equation from the tip inertia boundary condition. Those and
uniform-mass-scaled continuum beam frequencies use a separate 2% finite-mesh
tolerance. Static beam flexibility and coupled tip-spring response follow
Castigliano flexibility with a symmetric positive-definite 6x6 global spring.

All models have at least five free coordinates and positive fundamental
frequencies. Thirty cases preserve sparse, shuffled node records to exercise
the node-index fix. No production solver or independent reference code was
changed in constructing this set.
