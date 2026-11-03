"""Score an analysed force-displacement history against a test (reference) curve, and sweep parameters.

Pure numpy, no Qt, no OpenSees: usable from the UI, from harness.run_case, or from a plain script.
Units are whatever you pass in, as long as BOTH curves use the same ones (the harness gives mm and kN, and the
reference_curves entries of an OpenCivil .mf keep raw_x / raw_y in the same display units).

What it reports
---------------
per half-cycle extremum (turning point of the displacement history, matched in order):
    u_ref, V_ref, V_ana, ratio = V_ana / V_ref
per full cycle (positive extremum to the next positive extremum):
    energy_ref, energy_ana (dissipated energy = closed-loop integral of V du), energy ratio,
    secant stiffness ref/ana (peak-to-peak (V+ - V-)/(u+ - u-)), stiffness ratio
overall:
    NRMSE of V (analysis interpolated onto the reference path branch by branch, normalised by max|V_ref|),
    mean / worst peak-force error, total energy ratio, completion (fraction of the reference extrema reached
    and max|u| reached), and a single `score` (lower is better) for ranking sweep runs.
"""

import itertools
import math

import numpy as np

def turning_points(u, rel_threshold=0.02):
    """Indices of the displacement extrema (including first/last point), ignoring reversals smaller than
    rel_threshold * max|u| (noise in digitised test data). Alternates max / min."""
    u = np.asarray(u, float)
    if u.size < 3:
        return [0, max(u.size - 1, 0)]
    thr = rel_threshold * float(np.max(np.abs(u)) or 1.0)
    idx = [0]
    direction = 0
    ext_i = 0
    for i in range(1, u.size):
        if direction >= 0 and u[i] > u[ext_i]:
            ext_i = i
            if direction == 0 and u[i] - u[idx[0]] > thr:
                direction = 1
        elif direction <= 0 and u[i] < u[ext_i]:
            ext_i = i
            if direction == 0 and u[idx[0]] - u[i] > thr:
                direction = -1
        if direction == 1 and u[ext_i] - u[i] > thr:
            idx.append(ext_i)
            direction = -1
            ext_i = i
        elif direction == -1 and u[i] - u[ext_i] > thr:
            idx.append(ext_i)
            direction = 1
            ext_i = i
    if idx[-1] != ext_i:
        idx.append(ext_i)
    if idx[-1] != u.size - 1:
        idx.append(u.size - 1)
    out = []
    for i in idx:                                     
        if not out or i != out[-1]:
            out.append(i)
    return out

def cumulative_work(u, V):
    """Running integral of V du (trapezoid)."""
    u = np.asarray(u, float)
    V = np.asarray(V, float)
    w = np.zeros(u.size)
    if u.size > 1:
        w[1:] = np.cumsum(0.5 * (V[1:] + V[:-1]) * np.diff(u))
    return w

REPEAT_TOL = 0.10                                                                                                   
MIN_REF_FRAC = 0.05                                                                                                 

def _branch_crossings(u, V, i0, i1):
    """On the branch i0..i1: displacement where V first crosses 0 and force where u first crosses 0 (nan if none)."""
    u0 = V0 = float("nan")
    for i in range(i0 + 1, i1 + 1):
        if V[i - 1] * V[i] < 0 and np.isnan(u0):
            u0 = float(u[i - 1] + (u[i] - u[i - 1]) * (-V[i - 1]) / (V[i] - V[i - 1]))
        if u[i - 1] * u[i] < 0 and np.isnan(V0):
            V0 = float(V[i - 1] + (V[i] - V[i - 1]) * (-u[i - 1]) / (u[i] - u[i - 1]))
    return u0, V0

def _ratio(a, b):
    return a / b if (a == a and b == b and abs(b) > 1e-12) else float("nan")

def compare(u_ana, V_ana, u_ref, V_ref, rel_threshold=0.02):
    """Score an analysis against a test curve.

    Conventions (fixed vs. the first version, which mis-paired cycles and divided by ~0 at the record end):
      * the first point (u = 0) and the LAST point of each record are never treated as reversals: the last point is
        just where the record stops (often mid-branch, V ~ 0), not a peak;
      * dissipated energy is only evaluated on REPEATED cycles (a positive peak and the next positive peak of the same
        amplitude, within REPEAT_TOL): only those are closed loops. Ramp cycles to a larger amplitude are skipped;
      * per repeated cycle it also reports where the descending branch crosses V = 0 (u0, the residual displacement)
        and the force at u = 0 (V0): these show directly whether the loop is too thin / pinched.
    """
    ua, Va = np.asarray(u_ana, float), np.asarray(V_ana, float)
    ur, Vr = np.asarray(u_ref, float), np.asarray(V_ref, float)
    ta_all, tr_all = turning_points(ua, rel_threshold), turning_points(ur, rel_threshold)
    ta, tr = ta_all[1:-1], tr_all[1:-1]                                            
    n = min(len(ta), len(tr))
    out = {"n_ref_extrema": len(tr), "n_ana_extrema": len(ta), "extrema": [], "cycles": []}
    vmax = float(np.max(np.abs(Vr))) or 1.0
    umax = float(np.max(np.abs(ur))) or 1.0
    for k in range(n):
        i, j = ta[k], tr[k]
        ratio = float(Va[i] / Vr[j]) if abs(Vr[j]) > MIN_REF_FRAC * vmax else float("nan")
        out["extrema"].append({"k": k, "u_ref": float(ur[j]), "u_ana": float(ua[i]),
                               "V_ref": float(Vr[j]), "V_ana": float(Va[i]), "ratio": ratio})

    wa, wr = cumulative_work(ua, Va), cumulative_work(ur, Vr)
    for k in range(n - 2):
        if ur[tr[k]] <= 0 or ur[tr[k + 2]] <= 0 or ua[ta[k]] <= 0 or ua[ta[k + 2]] <= 0:
            continue
        if abs(ur[tr[k + 2]] - ur[tr[k]]) > REPEAT_TOL * abs(ur[tr[k]]):
            continue                                                                                      
        Ea = float(wa[ta[k + 2]] - wa[ta[k]])
        Er = float(wr[tr[k + 2]] - wr[tr[k]])
        sa = (Va[ta[k]] - Va[ta[k + 1]]) / (ua[ta[k]] - ua[ta[k + 1]]) if abs(ua[ta[k]] - ua[ta[k + 1]]) > 1e-12 else float("nan")
        sr = (Vr[tr[k]] - Vr[tr[k + 1]]) / (ur[tr[k]] - ur[tr[k + 1]]) if abs(ur[tr[k]] - ur[tr[k + 1]]) > 1e-12 else float("nan")
        u0a, V0a = _branch_crossings(ua, Va, ta[k], ta[k + 1])
        u0r, V0r = _branch_crossings(ur, Vr, tr[k], tr[k + 1])
        out["cycles"].append({
            "cycle": len(out["cycles"]) + 1, "u_peak_ref": float(ur[tr[k]]),
            "energy_ref": Er, "energy_ana": Ea, "energy_ratio": _ratio(Ea, Er),
            "k_sec_ref": float(sr), "k_sec_ana": float(sa), "k_ratio": _ratio(sa, sr),
            "u0_ref": u0r, "u0_ana": u0a, "u0_ratio": _ratio(u0a, u0r),
            "V0_ref": V0r, "V0_ana": V0a, "V0_ratio": _ratio(V0a, V0r)})

    se, cnt = 0.0, 0
    for k in range(min(len(ta_all), len(tr_all)) - 1):
        ia0, ia1 = ta_all[k], ta_all[k + 1]
        ir0, ir1 = tr_all[k], tr_all[k + 1]
        ba_u, ba_v = ua[ia0:ia1 + 1], Va[ia0:ia1 + 1]
        br_u, br_v = ur[ir0:ir1 + 1], Vr[ir0:ir1 + 1]
        if ba_u.size < 2 or br_u.size < 2:
            continue
        order = np.argsort(ba_u)
        m = (br_u >= ba_u.min()) & (br_u <= ba_u.max())
        if not m.any():
            continue
        v_i = np.interp(br_u[m], ba_u[order], ba_v[order])
        se += float(np.sum((v_i - br_v[m]) ** 2))
        cnt += int(m.sum())
    nrmse = math.sqrt(se / cnt) / vmax if cnt else float("nan")

    errs = [abs(e["ratio"] - 1.0) for e in out["extrema"] if e["ratio"] == e["ratio"] and abs(e["u_ref"]) > 0.2 * umax]
    cy = out["cycles"]
    e_ref_tot = float(sum(c["energy_ref"] for c in cy))
    e_ana_tot = float(sum(c["energy_ana"] for c in cy))
    u0e = [abs(c["u0_ratio"] - 1.0) for c in cy if c["u0_ratio"] == c["u0_ratio"]]
    completion_u = float(np.max(np.abs(ua)) / umax)
    completion_n = min(n / len(tr), 1.0) if len(tr) else float("nan")
    out["overall"] = {
        "nrmse_V": nrmse,
        "mean_peak_err": float(np.mean(errs)) if errs else float("nan"),
        "worst_peak_err": float(np.max(errs)) if errs else float("nan"),
        "energy_ratio_total": e_ana_tot / e_ref_tot if abs(e_ref_tot) > 1e-12 else float("nan"),
        "u0_mean_err": float(np.mean(u0e)) if u0e else float("nan"),
        "n_repeat_cycles": len(cy),
        "completion_u": completion_u, "completion_extrema": completion_n,
        "Vmax_ref": float(np.max(Vr)), "Vmax_ana": float(np.max(Va)),
        "Vmin_ref": float(np.min(Vr)), "Vmin_ana": float(np.min(Va)),
    }
    o = out["overall"]
    nan1 = lambda x: x if x == x else 1.0
    o["score"] = float(nan1(o["nrmse_V"]) + 0.5 * nan1(o["mean_peak_err"])
                       + 0.5 * abs(nan1(o["energy_ratio_total"]) - 1.0) + 0.5 * nan1(o["u0_mean_err"])
                       + 2.0 * (1.0 - min(nan1(completion_n), 1.0)))
    return out

def format_report(res, u_name="mm", v_name="kN"):
    o = res["overall"]
    L = [f"NRMSE(V) {100 * o['nrmse_V']:.1f}% | mean peak error {100 * o['mean_peak_err']:.1f}% "
         f"(worst {100 * o['worst_peak_err']:.1f}%) | loop-energy ratio {o['energy_ratio_total']:.2f} "
         f"({o['n_repeat_cycles']} repeated cycles) | residual-u error {100 * o['u0_mean_err']:.0f}% | "
         f"completed {100 * o['completion_extrema']:.0f}% of reversals, {100 * o['completion_u']:.0f}% of max |u|",
         f"Vmax ref/ana {o['Vmax_ref']:.1f}/{o['Vmax_ana']:.1f} {v_name}; Vmin ref/ana {o['Vmin_ref']:.1f}/{o['Vmin_ana']:.1f} {v_name}",
         f"{'cycle':>5} {'u_peak':>8} {'E ratio':>8} {'k ratio':>8} {'u0 ref':>8} {'u0 ana':>8} {'V0 ref':>8} {'V0 ana':>8}"]
    for c in res["cycles"]:
        L.append(f"{c['cycle']:>5} {c['u_peak_ref']:>8.2f} {c['energy_ratio']:>8.2f} {c['k_ratio']:>8.2f} "
                 f"{c['u0_ref']:>8.2f} {c['u0_ana']:>8.2f} {c['V0_ref']:>8.1f} {c['V0_ana']:>8.1f}")
    return "\n".join(L)

def sweep(run_fn, grid, u_ref, V_ref, rel_threshold=0.02, progress=None):
    """Run `run_fn(**params)` for every combination in `grid` (dict name -> list of values) and rank them.

    run_fn must return (u, V) in the same units as the reference (harness.run_case returns mm, kN as its first
    two values, so wrap it: lambda **p: run_case(opensees_over=p)[:2]). A run that raises is recorded with its
    error and skipped in the ranking. Returns a list of dicts sorted by score (best first)."""
    names = list(grid)
    rows = []
    combos = list(itertools.product(*(grid[n] for n in names)))
    for i, vals in enumerate(combos, 1):
        params = dict(zip(names, vals))
        row = {"params": params}
        try:
            u, V = run_fn(**params)
            res = compare(u, V, u_ref, V_ref, rel_threshold)
            row["overall"] = res["overall"]
            row["score"] = res["overall"]["score"]
        except Exception as exc:                                                                       
            row["error"] = f"{type(exc).__name__}: {exc}"
            row["score"] = float("inf")
        rows.append(row)
        if progress:
            progress(i, len(combos), row)
    rows.sort(key=lambda r: r["score"])
    return rows

def reference_from_oc(oc_data, index=0):
    """(u, V) arrays from an OpenCivil model's reference_curves entry (raw_x / raw_y, display units)."""
    rc = (oc_data.get("reference_curves") or [])[index]
    return np.asarray(rc["raw_x"], float), np.asarray(rc["raw_y"], float)
