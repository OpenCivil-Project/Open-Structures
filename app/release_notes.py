NOTICES = [
    (
        "Section Designer  [Beta]",
        "Not functional yet — UI is accessible but output is not wired to the solver."
    ),
    (
        "Shell / Area Elements & Area Sections  [Display Only]",
        "Visualization and selection work, but the solver does not process them. Do not rely on analysis results when shell elements are present."
    ),
    (
        "Orphan Node Warning",
        "Using shell/area elements may leave orphan nodes. Avoid area/shell elements for now."
    ),
]

RELEASE_NOTES = [
    {
        "version": "v0.7.90",
        "date": "August 16, 2026",
        "items": [
            ("new", "Dual-Formulation Corotational Engine — implemented UI-toggled support for Commercial Compatibility (Updated Lagrangian Match) and Strict Global Equilibrium (Native O//S)."),
            ("fix", "Large Deflection Force Recovery — aligned element constitutive and geometric stiffness evaluations with the original undeformed length (L0) to eliminate artificial softening and match commercial solvers."),
            ("new", "Analytical Spin Matrix (K_spin) — formulated and injected the exact geometric spin tangent into the global Jacobian to guarantee perfect Newton-Raphson convergence without numerical approximations."),
            ("validated", "Large Displacement Verification — achieved nanometer-perfect correlation with commercial benchmark data on a highly nonlinear 37-degree massive rotation cantilever test."),
        ]
    },
    {
        "version": "v0.7.85",
        "date": "July 26, 2026",
        "items": [
            ("fix", "Geometric Stiffness (K_G) Moment Releases — implemented exact static condensation to eliminate zero-energy phantom buckling modes."),
            ("fix", "Rigid Zone P-Delta Correction — injected exact rotational overturning stiffness (windshield wiper effect) for asymmetric end offsets."),
            ("validated", "LTHA Base Reactions (Fy/Fz/Mx under single-direction excitation) — confirmed via per-node force inspection that near-zero global Fy/Fz/Mx values under X-only ground motion are genuine overturning/rocking cancellation (large, real, opposite-signed forces at individual supports summing to ~zero), not a computation error. No code change required."),
            ("fix", "Joint Reaction Output Filter — filtered out internal rigid diaphragm constraint forces from the output tables to strictly report true external ground reactions (fixed supports and springs)."),
            ("validated", "Link Element Boundary Conditions — confirmed 1-joint link reactions evaluate perfectly through the global matrix, utilizing automated phantom nodes to safely bypass internal constraint noise."),
        ]
    },
    {
        "version": "v0.7.80",
        "date": "June 17, 2026",
        "items": [
            ("new", "RSA Seismic Precision Engine — true participation factor (Γ) reconstruction using mass-normalized eigenvalue data with 1:1 benchmark correlation."),
            ("new", "Modal Force Extraction Pipeline — vectorized mode-by-mode internal force and moment extraction (P, V, M) preserving RSA equilibrium."),
            ("new", "CQC & SRSS Modal Combination — automated modal combination for global displacements and element-level internal forces."),
            ("new", "JSON Handoff Architecture — serialized uncombined mode shapes and modal frequencies for real-time seismic envelope inspection."),
            ("fix", "Solver data handoff — resolved ndarray serialization crashes with automatic NumPy-to-list conversion."),
            ("fix", "Modal scaling — corrected Participation Factor mapping for accurate seismic inertial loads."),
            ("fix", "Dialog stability — synchronized FBDViewerDialog and NodeResultsDialog RSA data handling."),
        ]
    },
    {
        "version": "v0.7.72",
        "date": "June 2026",
        "items": [
            ("new", "Shell/area element full pipeline — visualization, selection, hover tooltip"),
            ("new", "Area load rendering migrated to GPU buffers"),
            ("fix", "VBO dirty-flag patterns for LTHA and modal animation"),
            ("fix", "Active-plane suppression and transparency fix for shell elements"),
        ]
    },
    {
        "version": "v0.7.70",
        "date": "May 2026",
        "items": [
            ("new", "Force diagram (NVM) visualization with vectorized batch rendering"),
            ("new", "Select menu: by section, by story, invert, Ctrl+A"),
            ("new", "Quick Cross Brace tool with hover-highlight cell preview"),
            ("fix", "Dual-viewport canvas-2 sync bugs"),
            ("fix", "UI theme centralization with QSS and SVG arrows"),
        ]
    },
    {
        "version": "v0.7.65",
        "date": "April 2026",
        "items": [
            ("new", "Embedded CLI terminal with bidirectional GUI sync"),
            ("new", "Parametric Python API (import opencivil as oc (Beta))"),
            ("new", "Multi-instance window architecture"),
            ("new", "Analysis progress dialog with callback-based solver integration"),
            ("fix", "PyInstaller packaging fixes"),
        ]
    },
]
