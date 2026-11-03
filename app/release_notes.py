NOTICES = [
    (
            "Graphical User Interface (GUI)  [Beta]",
            "The GUI is still under development, if this is laggy or unresponsive, please be patient. Go to Options > Graphics Preferences > General > Set MSAA to 1x to improve performance. On slower PCs, turn MSAA off and use FXAA instead. Then go to Lighting and Disable Blinn-Phong shading. If it's still laggy, then go to Display > Turn off Extrude Frames/Area. The GUI is still under development and may have bugs or missing features."
        ),

    (
        "Dark Mode",
        "Dark Mode is now supported. Go to Options > Graphics Preferences > General > UI Theme, select the dark theme, apply and restart the application."
    ),

    (
        "Section Designer  [Beta]",
        "Not functional yet — UI is accessible but output is not wired to the solver. The reinforcement parts are completely missing and are still under development."
    ),
    (
        "Shell, Plate, and Solid Elements  [Display Only]",
        "Visualization and selection work, but the solver does not process them. Do not rely on analysis results when shell elements are present. Shell, plate, and A solid elements are currently not working."
    ),
    (
        "Shell Forces  [Not Supported]",
        "Shell force recovery is not supported yet. Shell elements are still in beta, so no shell forces or stress resultants are available."
    ),
    (
        "Tributary Shell Elements",
        "Meshing and dynamic beam assignment are active, but this is exclusively for gravity load transfer. They provide no structural stiffness; use the diaphragm effect instead to simulate stiffness."
    ),
    (
        "Orphan Node Warning",
        "Using shell/area elements may leave orphan nodes. Avoid area/shell elements for now."
    ),
    (
        "Cable Sections  [Beta]",
        "Cables are in beta. They are not verified and are not working yet. Do not use them for analysis."
    ),
    (
        "Tendons",
        "Tendons work, but there are known bugs that we are trying to solve. For now, a tendon works as a load only, not as an element."
    ),
    (
        "OpenSees Options",
        "OpenSees options (nonlinear static, P-Delta, materials, etc.) are only available when the analysis solver is set to OpenSees in Analyze > Analysis Options."
    ),
    (
        "Concrete Frame Reinforcement",
        "Reinforcement definitions for concrete frame sections are still under development. Do not use them."
    ),
    (
        "Non-Linear Material Definitions",
        "Non-linear material data drives fiber hinges in Nonlinear Static (P-Delta) cases only; other analysis types do not use it yet. Verified so far: concrete cracking, tension softening, failure, and cyclic unloading/reloading. Not yet verified: rebar yielding and strain hardening, concrete post-peak crushing, partial and inner hysteresis loops, and very coarse load steps."
    ),
    (
        "Non-Linear Static Analysis",
        "Takes geometric non-linearity (P-Delta, large displacement) and, through fiber hinges, material non-linearity with Takeda hysteresis. Hinge Snap must be set to No for hysteresis. Reversals are detected per converged step, so keep load steps small around load reversals. Distributed plasticity is planned for future development."
    ),
    (
        "Link Elements",
        "Link elements are still under construction."
    ),
    (
        "Linear Time History Analysis (LTHA)",
        "Force recovery for LTHA is still under construction."
    ),
    (
        "Load Combinations",
        "Load combination functionality is partially active but is not 100% complete. It remains under construction."
    ),
    (
        "Command Line Interpreter (CLI)",
        "The CLI is still under construction."
    ),
    (
        "Pip Installation",
        "Installation via pip is still under construction and is not currently live or functioning."
    ),
    (
        "Solid Analysis",
        "Solid analysis functionality is experimental and is not currently working."
    ),
]

RELEASE_NOTES = [

    {
        "version": "v0.8.10",
        "date": "October 29, 2026",
        "items": [
            ("new", "Load Combination Engine & Post-Processing Fixes — fully integrated runtime evaluation for Linear Add and Envelope load combinations covering torsion, full internal force components, and native deflections."),
            ("new", "OpenSees Nonlinear Static (P-Delta) with Displacement Control History Table — displacement-controlled cases can now be driven by a history table, intended for verification against the PEER database."),
            ("new", "More OpenSees Materials — additional OpenSees material definitions are now available."),
            ("new", "OpenSees Option Gating — OpenSees options are only available when the analysis solver is set to OpenSees in Analyze > Analysis Options."),
            ("new", "Multi-Case Run — run a single load case, or run everything at once with Run All Load Cases from Run Analysis."),
            ("new", "Dark Mode Support — select the dark theme in Options > Graphics Preferences > General > UI Theme."),
            ("new", "FXAA Anti-Aliasing — added FXAA in Graphics Preferences. On slower PCs, turn MSAA off and use FXAA."),
            ("new", "Check for Updates — use Help > Check for Updates to see whether a newer version is available."),

            ("fix", "Envelope & Negative Factor Handling — corrected max/min bound selection when applying negative scale factors and Response Spectrum Analysis (RSA) symmetric bounds."),
            ("fix", "OpenSees & Stale Record Bypasses — combination evaluation now correctly intercepts execution before OpenSees direct force recovery and filters out inherited stale force records."),
            ("fix", "Cross-Namespace Name Collision Validation — load combination names are now strictly validated against existing load cases and other combinations (including Windows case-insensitive checks) to avoid disk file overwrites."),
            ("fix", "Station Grid Harmonization & Native Deflections — native deflections are evaluated reliably across all stations, and differing station grids between constituent cases are interpolated at common cuts without dropping load jumps."),

            ("validated", "Load Combination Suite — verified via 51 automated regression and integration test suites covering torsion, deflection envelopes, negative scaling, RSA bounds, multi-grid station cuts, circular dependency handling, and explicit error-raising on missing constituent files."),

        ]   
    },
    {
        "version": "v0.8.01",
        "date": "October 16, 2026",
        "items": [
            ("new", "Fiber Hinges in Nonlinear Static — P-M2-M3 fiber hinges now run in P-Delta nonlinear static cases. Each fiber is defined by explicit coordinates, area and material (reinforcing bars, cover and core concrete), and fiber strain, stress and material state are written for every saved step."),
            ("new", "Material Nonlinearity Connected to the Solver — concrete (Mander or user-defined stress-strain tables) and rebar (Park or user-defined) now drive hinge response, with cracking, tension softening and failure reported per fiber."),
            ("new", "Per-Fiber Takeda Hysteresis — each fiber remembers its last converged strain, direction of travel and unload/reload path, and detects its own reversals at every accepted step. Unloading follows a degraded elastic slope that softens with peak strain instead of retracing the backbone. No dependence on load case names, load patterns or control type. Requires a Takeda material and Hinge Snap = No."),
            ("new", "Chained Nonlinear Cases with Hysteresis — fiber state and plastic deformation carry across continued cases, so a case that starts from another case correctly treats its first step as a reversal. Load reversal by negative scale factor works with displacement control and P-Delta through the whole chain."),
            ("validated", "Fiber Hinge Generation and Response — a two-span beam with fiber hinges was run as a four-case chain (load, reverse, reload, reverse; 1000 displacement-controlled P-Delta steps each, 54 fibers per step) and compared with independent benchmark fiber output on all 216,000 fiber records: strain within 1e-6, concrete stress within 0.006 MPa, rebar stress within 0.08 MPa, median relative stress error below 0.1%."),
            ("validated", "Hinge Resultants and Equilibrium — hinge moment within 0.03% of its peak (0.1 kN·m on 290 kN·m) and axial force within 0.25 kN of the benchmark. Axial force balance between adjacent hinges holds through load reversal to 1e-4 kN. Cracking, tension softening, fiber failure and cyclic unloading/reloading are reproduced."),
            ("validated", "Chain Closure — the reload case reproduces the initial loading state and the second reversal reproduces the first to better than 1e-6 relative, confirming that fiber state is carried correctly case to case."),
        ]
    },
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
