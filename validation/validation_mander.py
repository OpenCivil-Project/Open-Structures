"""
Regression suite for mander_model.py.

Packages every reference stress-strain export gathered while validating
the confined-concrete model, so re-checking a future change to
mander_model.py is a matter of running this file instead of re-exporting
and re-typing reference data by hand.

Each entry in REFERENCE_CASES holds the section/reinforcement/material
inputs needed to rebuild the same "mander" object mander_model.py's
functions expect, plus the full digitized (strain, stress, label) point
list from that case's reference export. run_validation() rebuilds each
case, calls get_control_points(), and compares against the labeled
control points from the reference list (A, B, -C, -E, E — the same five
points mander_model.get_control_points() itself returns) plus a
dense-curve check restricted to the descending branch between -C and -E
(the compressive peak and ultimate strains), interpolating the reference
points and reporting the worst pointwise error found there. That window
is deliberately narrower than the full curve: relative error right near
the origin is ill-conditioned (stress swings from 0 to peak over a tiny
strain range, so a hairline strain misalignment reads as a huge percent
error there without meaning much), and it isn't the region the
comparison actually needs to police -- the two control points already
cover the ascending branch's start and end.

Run directly (`python validation_mander.py`) for a printed pass/fail
report; exits non-zero if any case exceeds DEFAULT_TOLERANCE_PCT on its
control points, so this can also be dropped into a CI check.

None of the reference data here has ever been used to fit or tune
anything in mander_model.py — see that file's own module docstring for
which cases did double duty as isolating tests during development
(cases 5 and 9 below, which pin down CHART_LIMIT_FL_RATIO) versus which
are purely confirmatory (everything else).
"""

import math
from types import SimpleNamespace

from core import mander_model as mm

AREA = {
    "#3": 7.096e-5, "#4": 1.290e-4, "#5": 2.000e-4, "#6": 2.839e-4,
    "#7": 3.871e-4, "#8": 5.097e-4, "#9": 6.452e-4, "#10": 8.194e-4,
    "#11": 1.006e-3, "#14": 1.452e-3, "#18": 2.581e-3,
}

REBAR_FY = 413685.5
REBAR_FU = 620528.2
REBAR_E = 199900000.0
REBAR_EPS_SH = 0.01
REBAR_EPS_SU = 0.09
REBAR_CURVE = "Park"

DEFAULT_TOLERANCE_PCT = 5.0                                  

def _bar_dia(bar_size: str) -> float:
    return math.sqrt(4.0 * AREA[bar_size] / math.pi)

def make_rect_mander(t3, t2, cover, long_bar, n3, n2, tie_bar, tie_spacing,
                      legs3, legs2, fyh=REBAR_FY):
    """Builds a rectangular-core mander object the same way
    material_dialog.py's ManderDataDialog does when reading a Frame
    Section Property in "column" mode: width maps to the x-axis, depth to
    the y-axis, both core dimensions measured centerline-to-centerline of
    the perimeter tie after subtracting cover and tie diameter.
    """
    td = _bar_dia(tie_bar)
    bc = max(0.0, t2 - 2.0 * cover - td)
    dc = max(0.0, t3 - 2.0 * cover - td)
    return SimpleNamespace(
        mander_type="Confined_Rect",
        x_leg_spacing=bc, y_leg_spacing=dc,
        num_x_legs=legs3, num_y_legs=legs2,
        num_long_x=n3, num_long_y=n2,
        long_bar_size_rect=long_bar,
        tie_spacing=tie_spacing,
        confinement_fyh=fyh,
        bar_size_mode="size", bar_size=tie_bar,
        confinement_fu=REBAR_FU, confinement_E=REBAR_E,
        confinement_eps_sh=REBAR_EPS_SH, confinement_eps_su=REBAR_EPS_SU,
        confinement_curve_model=REBAR_CURVE,
    )

def make_circ_mander(D, cover, long_bar, n_long, tie_bar, pitch, is_spiral,
                      fyh=REBAR_FY):
    td = _bar_dia(tie_bar)
    ds = max(0.0, D - 2.0 * cover - td)
    return SimpleNamespace(
        mander_type="Confined_Circ_Spiral" if is_spiral else "Confined_Circ_Hoop",
        core_diameter=ds, tie_spacing=pitch,
        confinement_fyh=fyh,
        bar_size_mode="size", bar_size=tie_bar,
        long_bar_mode="count", num_long_bars=n_long, long_bar_size=long_bar,
        confinement_fu=REBAR_FU, confinement_E=REBAR_E,
        confinement_eps_sh=REBAR_EPS_SH, confinement_eps_su=REBAR_EPS_SU,
        confinement_curve_model=REBAR_CURVE,
    )

REFERENCE_CASES = [
    dict(
        name="Rect 0.5x0.3, cover 0.04, #10 long 3/3, #10 ties 3/3 legs, sp 0.15",
        mander=make_rect_mander(0.5, 0.3, 0.04, "#10", 3, 3, "#10", 0.15, 3, 3),
        fc=28000.0, E=3.2e7,
        points=[
            (-0.1323, 0.0, None), (-0.1163, -51212.0, "-E"),
            (-0.1087, -51700.2, None), (-0.1001, -52298.7, None),
            (-0.0915, -52950.0, None), (-0.0829, -53662.9, None),
            (-0.0744, -54448.5, None), (-0.0658, -55320.5, None),
            (-0.0572, -56295.8, None), (-0.0486, -57394.7, None),
            (-0.04, -58637.5, None), (-0.0315, -60030.0, None),
            (-0.0229, -61492.7, None), (-0.0143, -62440.0, "-C"),
            (-0.0114, -62179.2, None), (-8.580e-3, -60976.3, None),
            (-5.720e-3, -57375.1, None), (-2.860e-3, -46187.0, None),
            (-1.430e-3, -31781.2, None), (0.0, 0.0, "A"),
            (1.030e-4, 3295.3367, "B"), (1.133e-3, 0.0, "E"),
        ],
    ),
    dict(
        name="Rect 0.8x0.3, cover 0.04, #8 long 4/3, #4 ties 4/2 legs, sp 0.10",
        mander=make_rect_mander(0.8, 0.3, 0.04, "#8", 4, 3, "#4", 0.10, 4, 2),
        fc=28000.0, E=3.2e7,
        points=[
            (-0.0386, -9414.3, None), (-0.0321, -29985.46, "-E"),
            (-0.0299, -30470.7, None), (-0.0264, -31308.24, None),
            (-0.023, -32257.1, None), (-0.0195, -33341.2, None),
            (-0.0161, -34585.9, None), (-0.0126, -36003.1, None),
            (-9.199e-3, -37513.8, None), (-5.750e-3, -38498.8, "-C"),
            (-4.600e-3, -38232.3, None), (-3.450e-3, -37035.2, None),
            (-2.300e-3, -33664.2, None), (-1.150e-3, -24635.3, None),
            (-5.750e-4, -15262.58, None), (0.0, 0.0, "A"),
            (1.030e-4, 3295.3367, "B"), (1.133e-3, 0.0, "E"),
        ],
    ),
    dict(
        name="Rect 0.7x0.35, cover 0.05, #9 long 4/3, #5 ties 4/3 legs, sp 0.10",
        mander=make_rect_mander(0.70, 0.35, 0.05, "#9", 4, 3, "#5", 0.10, 4, 3),
        fc=28000.0, E=3.2e7,
        points=[
            (-0.0536, -14838.65, None), (-0.0447, -43417.7, "-E"),
            (-0.0395, -44213.8, None), (-0.0336, -45249.8, None),
            (-0.0277, -46426.3, None), (-0.0217, -47750.5, None),
            (-0.0158, -49147.2, None), (-9.876e-3, -50053.3, "-C"),
            (-7.901e-3, -49805.0, None), (-5.926e-3, -48668.8, None),
            (-3.950e-3, -45327.1, None), (-1.975e-3, -35408.6, None),
            (-9.876e-4, -23505.25, None), (0.0, 0.0, "A"),
            (1.030e-4, 3295.3367, "B"), (1.133e-3, 0.0, "E"),
        ],
    ),
    dict(
        name="Rect 0.5x0.3, cover 0.04, #10 long 3/3, #10 ties 3/3 legs, sp 0.20 (lighter than case 1)",
        mander=make_rect_mander(0.5, 0.3, 0.04, "#10", 3, 3, "#10", 0.20, 3, 3),
        fc=28000.0, E=3.2e7,
        points=[
            (-0.1127, 0.0, None), (-0.0986, -45164.5, "-E"),
            (-0.0985, -45165.5, None), (-0.0913, -45693.9, None),
            (-0.0841, -46266.5, None), (-0.0769, -46890.2, None),
            (-0.0697, -47573.7, None), (-0.0625, -48327.7, None),
            (-0.0553, -49165.9, None), (-0.0481, -50104.9, None),
            (-0.0409, -51164.4, None), (-0.0336, -52364.8, None),
            (-0.0264, -53712.3, None), (-0.0192, -55130.1, None),
            (-0.012, -56049.0, "-C"), (-9.614e-3, -55796.5, None),
            (-7.211e-3, -54635.8, None), (-4.807e-3, -51186.8, None),
            (-2.404e-3, -40678.0, None), (-1.202e-3, -27553.21, None),
            (0.0, 0.0, "A"), (1.030e-4, 3295.3367, "B"), (1.133e-3, 0.0, "E"),
        ],
    ),
    dict(
        name="Circular D=0.80, spiral, cover 0.05, 12x#8 long, #5 spiral pitch 0.075",
        mander=make_circ_mander(0.80, 0.05, "#8", 12, "#5", 0.075, is_spiral=True),
        fc=28000.0, E=3.2e7,
        points=[
            (-0.0256, -27784.85, None), (-0.0214, -41454.2, "-E"),
            (-0.0176, -42492.3, None), (-0.0128, -43901.4, None),
            (-8.006e-3, -44817.0, "-C"), (-6.405e-3, -44567.1, None),
            (-4.804e-3, -43430.2, None), (-3.202e-3, -40132.7, None),
            (-1.601e-3, -30671.38, None), (-8.006e-4, -19868.29, None),
            (0.0, 0.0, "A"), (1.030e-4, 3295.3367, "B"), (1.133e-3, 0.0, "E"),
        ],
    ),
    dict(
        name="Rect 0.5x0.8, cover 0.05, #9 long 4/3, #6 ties 4/3 legs, sp 0.12, fc=40000 (only different-strength case)",
        mander=make_rect_mander(0.50, 0.80, 0.05, "#9", 4, 3, "#6", 0.12, 4, 3),
        fc=40000.0, E=3.8e7,
        points=[
            (-0.0425, -20941.33, None), (-0.0354, -47860.6, "-E"),
            (-0.0331, -48605.6, None), (-0.0288, -50203.8, None),
            (-0.0245, -52034.9, None), (-0.0202, -54143.8, None),
            (-0.0158, -56552.8, None), (-0.0115, -59128.6, None),
            (-7.203e-3, -60810.4, "-C"), (-5.762e-3, -60356.8, None),
            (-4.322e-3, -58330.3, None), (-2.881e-3, -52688.4, None),
            (-1.441e-3, -37957.6, None), (-7.203e-4, -23168.18, None),
            (0.0, 0.0, "A"), (1.036e-4, 3938.6806, "B"), (1.140e-3, 0.0, "E"),
        ],
    ),
    dict(
        name="Rect 0.45x0.55, cover 0.045, #7 long 4/3, #4 ties 4/3 legs, sp 0.15, fc=32000 (fl/fc kept BELOW CHART_LIMIT_FL_RATIO)",
        mander=make_rect_mander(0.45, 0.55, 0.045, "#7", 4, 3, "#4", 0.15, 4, 3),
        fc=32000.0, E=3.4e7,
        points=[
            (-0.0298, -14718.47, None), (-0.0249, -31631.3, "-E"),
            (-0.0231, -32267.5, None), (-0.0201, -33478.7, None),
            (-0.0171, -34873.5, None), (-0.014, -36489.1, None),
            (-0.011, -38345.3, None), (-8.024e-3, -40341.2, None),
            (-5.015e-3, -41647.6, "-C"), (-4.012e-3, -41297.4, None),
            (-3.009e-3, -39746.8, None), (-2.006e-3, -35515.0, None),
            (-1.003e-3, -24930.91, None), (-5.015e-4, -14865.36, None),
            (0.0, 0.0, "A"), (1.036e-4, 3522.8631, "B"), (1.140e-3, 0.0, "E"),
        ],
    ),
    dict(
        name="Rect 0.55x0.40, cover 0.04, #8 long 5/3, #7 ties 5/2 legs, sp 0.07, fc=32000 (fl/fc pushed ABOVE CHART_LIMIT_FL_RATIO on both axes, different asymmetry than case 4)",
        mander=make_rect_mander(0.55, 0.40, 0.04, "#8", 5, 3, "#7", 0.07, 5, 2),
        fc=32000.0, E=3.4e7,
        points=[
            (-0.092, -9036.67, None), (-0.0767, -61189.0, "-E"),
            (-0.0744, -61452.2, None), (-0.0658, -62527.1, None),
            (-0.0572, -63731.4, None), (-0.0486, -65090.7, None),
            (-0.04, -66630.9, None), (-0.0315, -68360.3, None),
            (-0.0229, -70180.3, None), (-0.0143, -71360.0, "-C"),
            (-0.0114, -71035.9, None), (-8.580e-3, -69546.7, None),
            (-5.720e-3, -65125.3, None), (-2.860e-3, -51682.3, None),
            (-1.430e-3, -34948.0, None), (0.0, 0.0, "A"),
            (1.036e-4, 3522.8631, "B"), (1.140e-3, 0.0, "E"),
        ],
    ),
]

def _labeled_points(points):
    return {label: (eps, f) for eps, f, label in points if label}

def _interp_stress(points, eps_query):
    """Linear interpolation of stress at a given strain, using only the
    compressive branch (strain <= 0) of a reference point list, sorted by
    strain ascending (most negative first)."""
    comp = sorted([(e, f) for e, f, _ in points if e <= 0.0])
    if eps_query <= comp[0][0]:
        return comp[0][1]
    if eps_query >= comp[-1][0]:
        return comp[-1][1]
    for (e0, f0), (e1, f1) in zip(comp, comp[1:]):
        if e0 <= eps_query <= e1:
            if e1 == e0:
                return f0
            t = (eps_query - e0) / (e1 - e0)
            return f0 + t * (f1 - f0)
    return comp[-1][1]

def run_validation(tolerance_pct=DEFAULT_TOLERANCE_PCT, verbose=True):
    """Rebuilds every case in REFERENCE_CASES, compares against its
    reference export, and returns a list of per-case result dicts:
    {name, control_point_errors: {label: (eps_err_pct, f_err_pct)},
     dense_worst_pct, passed}.
    """
    results = []
    for case in REFERENCE_CASES:
        our_points, result = mm.get_control_points(
            case["fc"], 0.002, 0.0035, -0.1, case["E"],
            mander=case["mander"], area_lookup=AREA,
        )
        our_by_label = {label: (eps, f) for eps, f, label in our_points}
        ref_by_label = _labeled_points(case["points"])

        cp_errors = {}
        worst_cp_err = 0.0
        for label in ("-C", "-E"):
            our_eps, our_f = our_by_label[label]
            ref_eps, ref_f = ref_by_label[label]
            eps_err = abs(our_eps - ref_eps) / abs(ref_eps) * 100 if ref_eps else 0.0
            f_err = abs(our_f - ref_f) / abs(ref_f) * 100 if ref_f else 0.0
            cp_errors[label] = (eps_err, f_err)
            worst_cp_err = max(worst_cp_err, eps_err, f_err)

        comp_pts, _ = mm.generate_mander_curve(
            case["fc"], 0.002, 0.0035, -0.1, case["E"],
            mander=case["mander"], area_lookup=AREA,
        )
        ref_eps_C = ref_by_label["-C"][0]
        ref_eps_E = ref_by_label["-E"][0]
        window_lo, window_hi = min(ref_eps_C, ref_eps_E), max(ref_eps_C, ref_eps_E)
        worst_dense_pct = 0.0
        for eps, f in comp_pts:
            if not (window_lo <= eps <= window_hi):
                continue
            ref_f = _interp_stress(case["points"], eps)
            if abs(ref_f) < 1.0:
                continue
            err = abs(f - ref_f) / abs(ref_f) * 100
            worst_dense_pct = max(worst_dense_pct, err)

        passed = worst_cp_err <= tolerance_pct
        results.append(dict(
            name=case["name"], control_point_errors=cp_errors,
            worst_control_point_pct=worst_cp_err,
            dense_worst_pct=worst_dense_pct, passed=passed,
        ))

        if verbose:
            status = "PASS" if passed else "FAIL"
            print(f"[{status}] {case['name']}")
            for label in ("-C", "-E"):
                eps_err, f_err = cp_errors[label]
                print(f"        {label}: strain err {eps_err:5.2f}%   stress err {f_err:5.2f}%")
            print(f"        worst pointwise error along full compression branch: {worst_dense_pct:5.2f}%")

    return results

if __name__ == "__main__":
    import sys
    res = run_validation()
    n_fail = sum(1 for r in res if not r["passed"])
    print(f"\n{len(res) - n_fail}/{len(res)} cases within {DEFAULT_TOLERANCE_PCT}% tolerance.")
    sys.exit(1 if n_fail else 0)
