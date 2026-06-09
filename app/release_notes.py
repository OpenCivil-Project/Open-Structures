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
            ("new", "Parametric Python API (import opencivil as oc)"),
            ("new", "Multi-instance window architecture"),
            ("new", "Analysis progress dialog with callback-based solver integration"),
            ("fix", "PyInstaller packaging fixes"),
        ]
    },
]
