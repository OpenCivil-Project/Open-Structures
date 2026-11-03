"""
os_capabilities.py

Single source of truth for "does this material setting have a real OpenSees
equivalent". Used by BOTH material_dialog.py (to grey out unsupported combo
items when Analysis Engine = OpenSees) and os_nonlinear.py (the converter,
which must apply the exact same rule when actually building materials).

Keeping this in one place is the whole point: the dialog and the converter
must never disagree about what's supported. If either of them adds/removes
support for a hysteresis type, only this file changes.
"""

UNSUPPORTED_HYSTERESIS = {"Pivot", "BRB Hardening", "Degrading"}

DEFAULT_HYSTERESIS = "Takeda"

UNSUPPORTED_CURVE_MODE = {"User Defined"}

def hysteresis_supported(hyst_type: str) -> bool:
    return hyst_type not in UNSUPPORTED_HYSTERESIS

def curve_mode_supported(curve_mode: str) -> bool:
    return curve_mode not in UNSUPPORTED_CURVE_MODE

def is_opensees(model) -> bool:
    return getattr(model, "analysis_engine", "native") == "opensees"

def apply_engine_switch(model, new_engine: str):
    """
    Call this ONCE, right when the Analysis Engine is changed (Analysis
    Options dialog), not from inside individual material dialogs -- so the
    warning appears at the moment that actually caused it, for every
    affected material at once, instead of one surprise per dialog opened
    later.

    Walks every material's nonlinear data and:
      - switching TO opensees: any unsupported hysteresis_type is backed up
        into native_hysteresis_backup and forced to DEFAULT_HYSTERESIS.
      - switching TO native: any material holding a backup gets its
        original value restored and the backup cleared.

    Returns a list of (material_name, old_value, new_value) for everything
    that changed, so the caller can show one consolidated message (or none,
    if the list is empty).
    """
    changed = []
    to_opensees = (new_engine == "opensees")
    for name, mat in getattr(model, "materials", {}).items():
        d = getattr(mat, "nonlinear", None)
        if d is None:
            continue
        if to_opensees and d.hysteresis_type in UNSUPPORTED_HYSTERESIS:
            old = d.hysteresis_type
            if d.native_hysteresis_backup is None:
                d.native_hysteresis_backup = old
            d.hysteresis_type = DEFAULT_HYSTERESIS
            changed.append((name, old, DEFAULT_HYSTERESIS))
        elif not to_opensees and d.native_hysteresis_backup is not None:
            old = d.hysteresis_type
            d.hysteresis_type = d.native_hysteresis_backup
            d.native_hysteresis_backup = None
            changed.append((name, old, d.hysteresis_type))
    return changed
