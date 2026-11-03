"""
core/reference_curve.py

Qt-free helpers for importing an experimental / literature force-displacement
curve (e.g. from the PEER structural performance database) and turning it
into a plain dict that is saved with the model (model.reference_curves).

Stored curve (all arrays in BASE units: x in m, y in N):
    {"name", "x": [...], "y": [...], "x_unit", "y_unit",   # units of the SOURCE file
     "source", "notes"}
"""

import math
import os
import re
from collections import Counter

import numpy as np

LENGTH_UNITS = {"mm": 1e-3, "cm": 1e-2, "m": 1.0, "in": 0.0254, "ft": 0.3048}
FORCE_UNITS = {"N": 1.0, "kN": 1e3, "MN": 1e6, "lbf": 4.4482216152605,
               "kip": 4448.2216152605, "kgf": 9.80665, "tonf": 9806.65}

_SPLIT = re.compile(r"[,\s;]+")
_FORTRAN = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)[dD][+-]?\d+$")

def _tok_to_float(tok):
    """float(tok), also accepting Fortran 'D' exponents. Raises ValueError if not a finite number."""
    if _FORTRAN.match(tok):
        tok = tok.replace("D", "E").replace("d", "e")
    v = float(tok)
    if not math.isfinite(v) or "_" in tok:
        raise ValueError(tok)
    return v

def parse_numeric_table(path):
    """
    Reads any text file and keeps only lines in which EVERY token is a number
    (separators: whitespace, tab, comma, semicolon). Everything else is a header.

    Returns dict:
        data            (n, ncols) float array of the dominant-width numeric rows
        header          list of skipped non-numeric lines (title, column names, ...)
        declared_count  a lone integer line before the data (PEER 'npts'), or None
        skipped_rows    numeric rows dropped because their width differed from the data
    """
    with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
        lines = f.read().splitlines()

    header, numeric = [], []                                           
    for i, raw in enumerate(lines):
        s = raw.strip()
        if not s:
            continue
        toks = [t for t in _SPLIT.split(s) if t]
        try:
            numeric.append((i, [_tok_to_float(t) for t in toks]))
        except ValueError:
            header.append(s)

    widths = Counter(len(v) for _, v in numeric if len(v) >= 2)
    if not widths:
        raise ValueError("No numeric table with at least 2 columns was found in this file.")
    ncols = max(widths, key=lambda w: (widths[w], w))

    rows = [v for _, v in numeric if len(v) == ncols]
    skipped = sum(1 for _, v in numeric if len(v) >= 2 and len(v) != ncols)

    declared = None
    first_idx = next(i for i, v in numeric if len(v) == ncols)
    for i, v in numeric:
        if i < first_idx and len(v) == 1 and float(v[0]).is_integer():
            declared = int(v[0])

    return {"data": np.array(rows, dtype=float), "header": header,
            "declared_count": declared, "skipped_rows": skipped}

def make_reference_curve(name, raw_x, raw_y, x_unit, y_unit, flip_x=False, flip_y=False,
                         scale_x=1.0, scale_y=1.0, source="", notes="",
                         color="", linewidth=1.2, linestyle="--"):
    """
    Builds the storable dict. The RAW columns (in the source file's units) are kept
    together with the unit/flip/scale settings, and x/y (base units m, N) are derived
    from them -- so a later Modify can change units/flip/scale exactly, never
    compounding conversions. color "" = automatic (palette by order in the viewer).
    """
    if x_unit not in LENGTH_UNITS:
        raise ValueError(f"Unknown length unit: {x_unit}")
    if y_unit not in FORCE_UNITS:
        raise ValueError(f"Unknown force unit: {y_unit}")
    rx = np.asarray(raw_x, dtype=float)
    ry = np.asarray(raw_y, dtype=float)
    xs = rx * float(scale_x) * (-1.0 if flip_x else 1.0) * LENGTH_UNITS[x_unit]
    ys = ry * float(scale_y) * (-1.0 if flip_y else 1.0) * FORCE_UNITS[y_unit]
    return {
        "name": name.strip(),
        "x": xs.tolist(), "y": ys.tolist(),                                                             
        "raw_x": rx.tolist(), "raw_y": ry.tolist(),                                
        "x_unit": x_unit, "y_unit": y_unit,
        "flip_x": bool(flip_x), "flip_y": bool(flip_y),
        "scale_x": float(scale_x), "scale_y": float(scale_y),
        "source": os.path.basename(source) if source else "",
        "notes": notes,
        "color": color or "", "linewidth": float(linewidth), "linestyle": linestyle,
    }

def curve_raw(curve):
    """
    -> (raw_x, raw_y, x_unit, y_unit, flip_x, flip_y, scale_x, scale_y) for the Modify dialog.
    Falls back to deriving raw data from x/y (base units) if a curve has no raw columns.
    """
    xu = curve.get("x_unit") if curve.get("x_unit") in LENGTH_UNITS else "m"
    yu = curve.get("y_unit") if curve.get("y_unit") in FORCE_UNITS else "N"
    if curve.get("raw_x") and len(curve["raw_x"]) == len(curve["x"]) == len(curve.get("raw_y", [])):
        return (np.array(curve["raw_x"], dtype=float), np.array(curve["raw_y"], dtype=float), xu, yu,
                bool(curve.get("flip_x")), bool(curve.get("flip_y")),
                float(curve.get("scale_x", 1.0)), float(curve.get("scale_y", 1.0)))
    return (np.array(curve["x"], dtype=float) / LENGTH_UNITS[xu],
            np.array(curve["y"], dtype=float) / FORCE_UNITS[yu], xu, yu, False, False, 1.0, 1.0)

def sanitize_loaded_curves(raw):
    """Used by the model loader: keep only well-formed curves and fill style defaults."""
    out = []
    for c in raw or []:
        if not isinstance(c, dict) or not c.get("name"):
            continue
        x, y = c.get("x"), c.get("y")
        if not isinstance(x, list) or not isinstance(y, list) or len(x) != len(y) or len(x) < 2:
            continue
        c = dict(c)
        c.setdefault("color", "")
        c.setdefault("linewidth", 1.2)
        c.setdefault("linestyle", "--")
        c.setdefault("notes", "")
        out.append(c)
    return out
