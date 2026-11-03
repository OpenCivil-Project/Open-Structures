"""
metrics.py   (core/)

Hysteresis verification metrics for a cyclic response curve y(x): force-displacement,
moment-curvature, moment-rotation. Pure NumPy, no Qt, no solver imports, and UNIT-AGNOSTIC:
energy comes out in (y-unit x x-unit), so feed it SI (N, m) or display units (kN, mm) as you like.
Every dialog should call the same functions so that "model" and "test" are processed identically.

Definitions
  cycle         from one upward zero-crossing of x to the next (the first cycle starts at the first
                sample). The path returns to x = 0, so the enclosed work is a true closed-loop energy
                even when the amplitude grows from cycle to cycle. A trailing partial cycle is kept if
                it ends back at x ~ 0 (closed=True), otherwise it is flagged closed=False.
  E_D           dissipated energy of a cycle = closed-path integral of y dx (trapezoid).
  E_S           strain energy at the peaks = 0.25 * (y+ * x+ + y- * x-), average of both directions.
  xi_eq         equivalent viscous damping ratio = E_D / (4 pi E_S). A metric only, not a model input.
  K_sec         peak-to-peak secant stiffness (y+ - y-) / (x+ - x-).
  level         consecutive cycles whose amplitude is within `level_tol` of the first cycle of the group.
  strength_ratio  mean peak force of the cycle / mean peak force of the first cycle of its level.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
import math
import numpy as np

__all__ = [
    "CycleMetrics", "cumulative_work", "cycle_table", "summarize", "compare",
    "series_from_opensees_history", "series_from_section_states", "series_from_hinge_history",
]

@dataclass
class CycleMetrics:
    cycle: int                          
    level: int                                          
    cycle_in_level: int                 
    closed: bool
    x_pos: float                                   
    x_neg: float                                   
    y_at_x_pos: float
    y_at_x_neg: float
    y_peak_pos: float                              
    y_peak_neg: float                              
    E_D: float                                                  
    E_D_cum: float                                                                
    E_S: float
    xi_eq: float
    K_sec: float
    strength_ratio: float                                   
    stiffness_ratio: float                                        

    def as_dict(self):
        return asdict(self)

def _as_xy(x, y):
    x = np.asarray(x, dtype=float).ravel()
    y = np.asarray(y, dtype=float).ravel()
    if x.shape != y.shape or x.size < 2:
        raise ValueError("x and y must be 1-D arrays of the same length (>= 2).")
    ok = np.isfinite(x) & np.isfinite(y)
    return x[ok], y[ok]

def _trapz(y, x):
    if len(x) < 2:
        return 0.0
    return float(np.sum(0.5 * (y[1:] + y[:-1]) * np.diff(x)))

def cumulative_work(x, y):
    """Running integral of y dx from the first sample (same length as x). Equals dissipated energy
    whenever x returns to 0; in between it also contains the recoverable (stored) part."""
    x, y = _as_xy(x, y)
    out = np.zeros_like(x)
    out[1:] = np.cumsum(0.5 * (y[1:] + y[:-1]) * np.diff(x))
    return out

def _cycle_paths(x, y, tol):
    """Split into closed paths at upward zero-crossings of x, with a dead band `tol` so that noise
    around zero (digitized test data) cannot create spurious cycles. Returns [(xp, yp, closed)]."""
    n = len(x)
    state = 0
    cuts = []                                                                                            
    for j in range(n):
        if x[j] > tol:
            if state == -1:
                i = j - 1
                while i > 0 and x[i] > 0.0:
                    i -= 1
                dx = x[i + 1] - x[i]
                t = (0.0 - x[i]) / dx if dx != 0.0 else 0.0
                cuts.append((i, min(max(t, 0.0), 1.0)))
            state = 1
        elif x[j] < -tol:
            state = -1

    def point(i, t):
        return x[i] + t * (x[i + 1] - x[i]), y[i] + t * (y[i + 1] - y[i])

    paths, start_i, start_pt = [], 0, (x[0], y[0])
    for k, (i, t) in enumerate(cuts):
        end_pt = point(i, t)
        xp = np.r_[start_pt[0], x[start_i + 1: i + 1], end_pt[0]]
        yp = np.r_[start_pt[1], y[start_i + 1: i + 1], end_pt[1]]
        paths.append((xp, yp, True))
        start_i, start_pt = i, end_pt
                                                                                                   
    xp = np.r_[start_pt[0], x[start_i + 1:]]
    yp = np.r_[start_pt[1], y[start_i + 1:]]
    paths.append((xp, yp, abs(x[-1]) <= tol))
    return paths

def cycle_table(x, y, tol_frac=0.02, level_tol=0.15, min_amp_frac=0.05):
    """Per-cycle metrics list[CycleMetrics]. tol_frac: dead band as a fraction of max|x|;
    min_amp_frac: cycles whose amplitude is below this fraction of max|x| are dropped (tail noise)."""
    x, y = _as_xy(x, y)
    xmax = float(np.max(np.abs(x)))
    if xmax <= 0:
        return []
    tol = tol_frac * xmax
    rows, cum = [], 0.0
    lvl, lvl_first, lvl_count = 0, None, 0
    for xp, yp, closed in _cycle_paths(x, y, tol):
        if len(xp) < 3:
            continue
        ip, im = int(np.argmax(xp)), int(np.argmin(xp))
        xpos, xneg = float(xp[ip]), float(xp[im])
        if 0.5 * (abs(xpos) + abs(xneg)) < min_amp_frac * xmax:
            continue
        ypos, yneg = float(yp[ip]), float(yp[im])
        ED = _trapz(yp, xp)
        cum += ED
        ES = 0.25 * (ypos * xpos + yneg * xneg)
        xi = ED / (4.0 * math.pi * ES) if ES > 0 else float("nan")
        ksec = (ypos - yneg) / (xpos - xneg) if xpos != xneg else float("nan")
        amp = 0.5 * (abs(xpos) + abs(xneg))
        fpk = 0.5 * (float(np.max(yp)) + abs(float(np.min(yp))))
        if lvl_first is None or abs(amp - lvl_first["amp"]) > level_tol * lvl_first["amp"]:
            lvl += 1
            lvl_count = 0
            lvl_first = {"amp": amp, "fpk": fpk, "k": ksec}
        lvl_count += 1
        rows.append(CycleMetrics(
            cycle=len(rows) + 1, level=lvl, cycle_in_level=lvl_count, closed=closed,
            x_pos=xpos, x_neg=xneg, y_at_x_pos=ypos, y_at_x_neg=yneg,
            y_peak_pos=float(np.max(yp)), y_peak_neg=float(np.min(yp)),
            E_D=ED, E_D_cum=cum, E_S=ES, xi_eq=xi, K_sec=ksec,
            strength_ratio=fpk / lvl_first["fpk"] if lvl_first["fpk"] else float("nan"),
            stiffness_ratio=ksec / lvl_first["k"] if lvl_first["k"] else float("nan"),
        ))
    return rows

def summarize(x, y, **kw):
    """Whole-curve numbers: absolute peaks and the displacement where they occur, total E_D."""
    x, y = _as_xy(x, y)
    rows = cycle_table(x, y, **kw)
    ip, im = int(np.argmax(y)), int(np.argmin(y))
    return {
        "y_max": float(y[ip]), "x_at_y_max": float(x[ip]),
        "y_min": float(y[im]), "x_at_y_min": float(x[im]),
        "x_max": float(np.max(x)), "x_min": float(np.min(x)),
        "n_cycles": len(rows), "n_levels": (rows[-1].level if rows else 0),
        "E_D_total": rows[-1].E_D_cum if rows else 0.0,
        "all_closed": all(r.closed for r in rows),
    }

def _pct(a, b):
    return 100.0 * (a - b) / b if b not in (0, 0.0) and math.isfinite(b) else float("nan")

def compare(model, ref, **kw):
    """Model vs reference. model/ref are (x, y) tuples in the SAME units. Cycles are matched by
    (level, cycle_in_level), with levels paired by nearest amplitude. Errors are % of the reference.
    Returns {"global": {...}, "cycles": [ {...} ]}."""
    sm, sr = summarize(*model, **kw), summarize(*ref, **kw)
    tm, tr = cycle_table(*model, **kw), cycle_table(*ref, **kw)

    def level_amp(rows):
        out = {}
        for r in rows:
            out.setdefault(r.level, 0.5 * (abs(r.x_pos) + abs(r.x_neg)))
        return out

    am, ar = level_amp(tm), level_amp(tr)
    pair = {lr: min(am, key=lambda lm: abs(am[lm] - a)) if am else None for lr, a in ar.items()}
    mdl = {(r.level, r.cycle_in_level): r for r in tm}
    cycles = []
    for r in tr:
        m = mdl.get((pair.get(r.level), r.cycle_in_level))
        row = {"cycle_ref": r.cycle, "level_ref": r.level, "cycle_in_level": r.cycle_in_level,
               "x_amp_ref": 0.5 * (abs(r.x_pos) + abs(r.x_neg)),
               "E_D_ref": r.E_D, "xi_ref": r.xi_eq, "K_ref": r.K_sec,
               "Fpk_pos_ref": r.y_peak_pos, "Fpk_neg_ref": r.y_peak_neg}
        if m is not None:
            row.update({"cycle_model": m.cycle,
                        "x_amp_model": 0.5 * (abs(m.x_pos) + abs(m.x_neg)),
                        "E_D_model": m.E_D, "E_D_err_pct": _pct(m.E_D, r.E_D),
                        "xi_model": m.xi_eq, "xi_err_pct": _pct(m.xi_eq, r.xi_eq),
                        "K_model": m.K_sec, "K_err_pct": _pct(m.K_sec, r.K_sec),
                        "Fpk_pos_model": m.y_peak_pos, "Fpk_pos_err_pct": _pct(m.y_peak_pos, r.y_peak_pos),
                        "Fpk_neg_model": m.y_peak_neg, "Fpk_neg_err_pct": _pct(m.y_peak_neg, r.y_peak_neg),
                        "E_D_cum_model": m.E_D_cum, "E_D_cum_ref": r.E_D_cum,
                        "E_D_cum_err_pct": _pct(m.E_D_cum, r.E_D_cum)})
        cycles.append(row)
    glob = {
        "peak_pos_model": sm["y_max"], "peak_pos_ref": sr["y_max"], "peak_pos_err_pct": _pct(sm["y_max"], sr["y_max"]),
        "peak_neg_model": sm["y_min"], "peak_neg_ref": sr["y_min"], "peak_neg_err_pct": _pct(sm["y_min"], sr["y_min"]),
        "x_at_peak_pos_model": sm["x_at_y_max"], "x_at_peak_pos_ref": sr["x_at_y_max"],
        "E_D_total_model": sm["E_D_total"], "E_D_total_ref": sr["E_D_total"],
        "E_D_total_err_pct": _pct(sm["E_D_total"], sr["E_D_total"]),
        "n_cycles_model": sm["n_cycles"], "n_cycles_ref": sr["n_cycles"],
        "n_levels_model": sm["n_levels"], "n_levels_ref": sr["n_levels"],
    }
    return {"global": glob, "cycles": cycles}

def series_from_opensees_history(results):
    """Full-resolution (every accepted step) displacement-force history of a Nonlinear Static
    OpenSees case: info['opensees_history'] -> (u [m], V [N]). Applied force = -reaction, as the
    writer already stores it. Returns None if the case has no history."""
    h = (results.get("info") or {}).get("opensees_history") or {}
    u, V = h.get("u_m"), h.get("V_N")
    if not u or not V or len(u) != len(V):
        return None
    return np.asarray(u, float), np.asarray(V, float)

def series_from_section_states(results, section_key, axis="z"):
    """Moment-curvature series of one OpenSees fiber section from saved_states[i]['hinge_states'].
    OpenSees ordering: force [P, Mz, My, T, Vy, Vz], deformation [eps, kz, ky, ...]; axis 'z'|'y'.
    Only states that carry hinge_states are used (they are written on a stride), so loop energy from
    this series is coarser than from the F-D history. Returns (kappa [1/m], M [N*m], step_numbers)."""
    idx = {"z": 1, "y": 2}[axis]
    k, m, st = [], [], []
    for s in results.get("saved_states") or []:
        sec = ((s.get("hinge_states") or {}).get(section_key))
        if not sec:
            continue
        k.append(float(sec["section_deformation"][idx]))
        m.append(float(sec["section_force"][idx]))
        st.append(int(s.get("step", len(st))))
    if len(k) < 2:
        return None
    return np.asarray(k), np.asarray(m), np.asarray(st)

def series_from_hinge_history(results, section_key, axis="z"):
    """EXACT moment-curvature series of one OpenSees section: info['opensees_hinge_history'] holds
    [eps, kz, ky] and [P, Mz, My] of every section at every accepted step (see os_hinge_results.py).
    Falls back to the thinned hinge_states of saved_states for result files written before that record
    existed. Returns (kappa [1/m], M [N*m], step_numbers) or None."""
    h = ((results.get("info") or {}).get("opensees_hinge_history") or {}).get(section_key)
    if h and len(h.get("steps") or []) >= 2:
        idx = {"z": 1, "y": 2}[axis]
        return (np.array([d[idx] for d in h["d"]], float), np.array([f[idx] for f in h["f"]], float),
                np.asarray(h["steps"], int))
    return series_from_section_states(results, section_key, axis)
