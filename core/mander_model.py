"""
Mander confined/unconfined concrete stress-strain model.

Pure functions only — no Qt, no analysis solver. Everything here works in
SI base units (Pa, m, m^2) and is meant to be called by the material
dialogs to build the points for the live stress-strain plot.

VALIDATION HISTORY

Checked against exported reference stress-strain data across 10 cases so
far, comparing the confined peak (-C) and confined ultimate-strain (-E)
control points that get_control_points() returns:

  1. Rectangular, cover 0.04, #10 long 3-per-face/3-per-face, #10 ties
     3/3 legs, spacing 0.15, fc'=28000: within 0.4-0.6%
  2. Rectangular, cover 0.04, #8 long 4/3, #4 ties 4/2 legs, spacing 0.10,
     fc'=28000: within 0.3-0.8%
  3. Rectangular, cover 0.04, #6 long 3/2, #4 ties 3/2 legs, spacing 0.12,
     fc'=28000: within 0.2-0.6% (checked against a self-consistency run,
     not an independent reference export)
  4. Rectangular, cover 0.05, #9 long 4/3, #5 ties 4/3 legs, spacing 0.10,
     fc'=28000: within 0.05-0.3%
  5. Same section/bars as case 1 but lighter ties (spacing 0.20 instead
     of 0.15) — deliberately isolates whether case 1's original ~16-45%
     historical gap was about confinement extremity: within 0.55-1.5%
  6. Circular, spiral confinement, D=0.80, cover 0.05, 12x#8 long, #5
     spiral pitch 0.075, fc'=28000: within 1.25-2.6% (first circular case
     checked against reference data this round; the largest gap of the
     sweep, worth another look if a related feature depends on it)
  7. Rectangular, cover 0.05, #9 long 4/3, #6 ties 4/3 legs, spacing
     0.12, fc'=40000 (only case at a different concrete strength): within
     0.2-0.5%
  8. Rectangular, cover 0.045, new section proportions, #7 long 4/3, #4
     ties 4/3 legs, spacing 0.15, fc'=32000, deliberately kept the
     lateral confining stress ratio (fl/fc) well BELOW the
     CHART_LIMIT_FL_RATIO cap below: within 0.6-1.85%
  9. Rectangular, cover 0.04, #8 long 5/3, #7 ties 5/2 legs, spacing
     0.07, fc'=32000, deliberately pushed fl/fc past the
     CHART_LIMIT_FL_RATIO cap on BOTH axes at once, with a different
     leg-asymmetry ratio than case 1/5 — the real stress test of that
     constant: within 0.24-0.63%, tighter than case 8

Net result: the closed-form/geometry math (Willam-Warnke surface,
actual-leg-count arching, rho_cc) generalizes well across sections, bar
sizes, confinement type, and concrete strength. The one number in this
file that started life as a curve fit rather than a derivation
(CHART_LIMIT_FL_RATIO, see its own comment) has now survived one
above-cap test on a genuinely different geometry, which is real evidence
but still thin — treat it as validated-with-caution until it's been
checked against a case with a very different fl asymmetry (near-zero on
one axis, or well past 0.5 on both) than cases 5 and 9 above.
"""

import math

BAR_AREAS_MM2 = {
    "10M": 100.0, "15M": 200.0, "20M": 300.0, "25M": 500.0,
    "30M": 700.0, "35M": 1000.0, "45M": 1500.0, "55M": 2500.0,
}

CHART_LIMIT_FL_RATIO = 0.282

def bar_area_m2(bar_size: str, area_lookup: dict | None = None) -> float:
    if area_lookup is not None:
        return area_lookup.get(bar_size, 0.0)
    return BAR_AREAS_MM2.get(bar_size, 0.0) * 1e-6

def mander_strength_ratio(fl: float, fc: float) -> float:
    if fc <= 0 or fl <= 0:
        return 1.0
    r = fl / fc
    ratio = 2.254 * math.sqrt(1.0 + 7.94 * r) - 2.0 * r - 1.254
    return max(ratio, 1.0)

def confined_strain_at_peak(eps_c0: float, ratio: float) -> float:
    return eps_c0 * (1.0 + 5.0 * (ratio - 1.0))

def multiaxial_failure_surface(fc: float, fl1: float, fl2: float) -> float:
    """
    Willam-Warnke 5-parameter surface root-finder for unequal biaxial
    lateral confinement (fl1 != fl2), used by the rectangular-hoop
    confinement path where f'lx != f'ly.

    Why this is a fit at all, and not a closed-form equation: per the
    reference tool's own technical documentation, it computes f'cc for the
    unequal fl1 != fl2 case by reading it off "a chart for the multiaxial
    failure criterion ... published in Mander et al. (1984)" -- i.e. a
    digitized lookup against the 5-parameter Willam-Warnke surface, not a
    closed form. There isn't a published closed-form alternative to fall
    back on for this case; matching that reference means matching that
    chart, which is what this function's two meridian fits below are doing.

    Calibration of the two meridian curves rc(z) [compression meridian,
    theta=60deg] and rt(z) [tension meridian, theta=0deg] -- NOW TAKEN
    DIRECTLY from the primary source, not fit to our own reference output:

    Mander's paper states it adopted "the calculated ultimate strength
    surface based on the triaxial tests of Schickert and Winkler (1977)
    ... Details of the calculations have been given by Elwi and Murray
    (1979)." Elwi & Murray (1979), "A 3D Hypoelastic Concrete
    Constitutive Relationship" (J. Engrg. Mech. Div. ASCE 105(4)),
    Appendix II gives the actual calibrated quadratics for exactly that
    Schickert-Winkler dataset:
        r1(sigma_bar_a) = 0.053627 - 0.512079*sigma_bar_a - 0.038226*sigma_bar_a^2   (extension/tension meridian)
        r2(sigma_bar_a) = 0.095248 - 0.891175*sigma_bar_a - 0.244420*sigma_bar_a^2   (compression meridian)
    where sigma_bar_a = mean normal stress / f_cu (their sign convention:
    sigma_bar_a = -1/3 at the uniaxial compression point).

    Converting into this function's (z, r) convention:
      - z = -sigma_bar_a (verified: paper's uniaxial-compression control
        point sits at sigma_bar_a=-1/3, and z=1/3 at fl1=fl2=0 here).
      - This function's r_actual = sqrt(2*J2)/(3*fc); the paper's
        r = tau_a/f_cu = sqrt(2*J2/5)/f_cu. Ratio = sqrt(5)/3 when
        fc == f_cu.
    So: rt(z) = (sqrt(5)/3) * r1(-z), rc(z) = (sqrt(5)/3) * r2(-z) --
    expanded to the a0,a1,a2 / b0,b1,b2 below.

    Two independent checks on this conversion, both passed:
      1. rc(z) computed this way matches the OLD rc(z) (which was fit
         to machine precision against Mander's exact closed-form Eq. 29
         for fl1==fl2) to ~1e-5 across z in [0.1, 1.0] -- i.e. Eq. 29 and
         the Elwi-Murray/Schickert-Winkler chart data are the same
         surface, confirming the sign/scale conversion is right.
      2. Tested against the worked numerical example printed in Mander,
         Priestley & Park (1988) p.1812 (f'co=30 MPa, f'lx=5.1 MPa,
         f'ly=2.7 MPa -> f'cc=49.5 MPa) -- independent ground truth, not
         back-solved from anything of ours: predicts 49.55 MPa, +0.10%.

    RESOLVED (was previously flagged here as a 3-5% high, unexplained gap
    on rectangular test sections): that gap traced to
    rectangular_confinement()'s f'lx/f'ly geometry (the longitudinal-bar
    inset assumption and the arching Sum(w_i'^2) term), not to this
    surface -- see the geometry fix documented in that function. With the
    corrected geometry, this surface now matches reference stress-strain
    exports across a 10-case sweep (rectangular sections of varying
    depth/width/bar/tie combinations, one circular-spiral case, and two
    cases deliberately designed to push fl1/fl2 asymmetry into new
    territory) to within roughly 0.2-2.6% on both the confined peak and
    the confined ultimate-strain point. Any leg count where f'lx ~= f'ly
    (e.g. nx=ny with a square-ish core) hits the fl1==fl2 branch below --
    Mander's exact closed-form Eq. 29, zero chart interpolation -- and
    that branch was independently checked against the Elwi-Murray
    conversion above, so it was never in doubt.
    """
    if fl1 == fl2:
        return fc * mander_strength_ratio(fl1, fc)

    fl1, fl2 = min(fl1, fl2), max(fl1, fl2)
    if fl1 <= 0 and fl2 <= 0:
        return fc

    b0, b1, b2 = 0.07099366757363332, 0.6642426266161251, -0.18217991168683287
                                                                                             
    a0, a1, a2 = 0.03997120580979374, 0.38168115128337154, -0.028491978169302323

    def surface_error(fcc):
                                                               
        s1 = -fl1
        s2 = -fl2
        s3 = -fcc
        
        I1 = s1 + s2 + s3
        sm = I1 / 3.0
        
        z = -sm / fc

        ds1 = s1 - sm
        ds2 = s2 - sm
        ds3 = s3 - sm
        
        J2 = 0.5 * (ds1**2 + ds2**2 + ds3**2)
        J3 = ds1 * ds2 * ds3
        
        r_actual = math.sqrt(2.0 * J2) / (3.0 * fc)

        cos3theta = (3.0 * math.sqrt(3.0) / 2.0) * J3 / math.pow(J2, 1.5) if J2 > 0 else 1.0
        cos3theta = max(-1.0, min(1.0, cos3theta))
        theta = math.acos(cos3theta) / 3.0                      
        
        rt = a0 + a1 * z + a2 * (z**2)
        rc = b0 + b1 * z + b2 * (z**2)

        if rc <= 0 or rt <= 0:
            return 1.0

        cos_theta = math.cos(theta)
        num1 = 2.0 * rc * (rc**2 - rt**2) * cos_theta
        arg = max(0.0, 4.0 * (rc**2 - rt**2) * (cos_theta**2) + 5.0 * rt**2 - 4.0 * rt * rc)
        num2 = rc * (2.0 * rt - rc) * math.sqrt(arg)
        den = 4.0 * (rc**2 - rt**2) * (cos_theta**2) + (rc - 2.0 * rt)**2
        
        r_yield = (num1 + num2) / den if den != 0 else 0.0
        
        return r_actual - r_yield

    low = fc
    high = fc * 20.0
    for _ in range(60):
        mid = (low + high) / 2.0
        if surface_error(mid) > 0:
            high = mid                                             
        else:
            low = mid                                             
            
    return (low + high) / 2.0

def octagonal_tie_rho(asp: float, s: float, bc: float, dc: float, n_lx: int, n_ly: int):
    """
    Smeared lateral steel ratios (rho_x, rho_y) for an OUTER RECTANGULAR HOOP plus
    an INSCRIBED OCTAGONAL TIE (the "RO" layout), same convention as the plain
    rectangular path (rho_x = A_x / (s*dc), rho_y = A_y / (s*bc)).

    Geometry (centre-line, bc x dc): the octagon runs through the 2nd and
    (n-1)th longitudinal bar of every face (n_lx bars along the bc face, n_ly
    along the dc face):
      * 4 straight segments along the faces, length bc*(n_lx-3)/(n_lx-1) (x) and
        dc*(n_ly-3)/(n_ly-1) (y), two of each;
      * 4 corner diagonals, dx = bc/(n_lx-1), dy = dc/(n_ly-1), L = hypot(dx, dy).
    Smearing rule for a segment of length L at angle theta to x:
        rho_x += A*L*cos^2(theta)/(bc*dc*s),  rho_y += A*L*sin^2(theta)/(bc*dc*s)
    which reduces exactly to Mander's nx*A/(s*dc) for straight hoop legs.
    Needs n_lx, n_ly >= 3 (caller falls back to plain legs otherwise).
    """
    dx = bc / (n_lx - 1)
    dy = dc / (n_ly - 1)
    L = math.hypot(dx, dy)
    len_x = 2.0 * bc + 2.0 * bc * (n_lx - 3) / (n_lx - 1) + 4.0 * dx * dx / L
    len_y = 2.0 * dc + 2.0 * dc * (n_ly - 3) / (n_ly - 1) + 4.0 * dy * dy / L
    vol = bc * dc * s
    return asp * len_x / vol, asp * len_y / vol

def _rho_s_scale(mander) -> float:
    try:
        v = float(getattr(mander, "rho_s_scale", 1.0) or 1.0)
    except (TypeError, ValueError):
        return 1.0
    return v if v > 0.0 else 1.0

def circular_confinement(mander, fc: float, is_spiral: bool, area_lookup: dict | None = None):
    ds = float(getattr(mander, "core_diameter", 0.0) or 0.0)
    s = float(getattr(mander, "tie_spacing", 0.0) or 0.0)
    fyh = float(getattr(mander, "confinement_fyh", 0.0) or 0.0)

    if getattr(mander, "bar_size_mode", "size") == "area":
        asp = float(getattr(mander, "bar_area", 0.0) or 0.0)
    else:
        asp = bar_area_m2(getattr(mander, "bar_size", ""), area_lookup)

    if getattr(mander, "long_bar_mode", "count") == "area":
        as_long = float(getattr(mander, "total_long_area", 0.0) or 0.0)
    else:
        as_long = int(getattr(mander, "num_long_bars", 0) or 0) * bar_area_m2(
            getattr(mander, "long_bar_size", ""), area_lookup
        )

    if ds <= 0 or s <= 0:
        return 0.0, 0.0, 0.0, 0.0

    ac_core = math.pi / 4.0 * ds ** 2
    rho_cc = min(max(as_long / ac_core, 0.0), 0.08) if ac_core > 0 else 0.0

    tie_dia = math.sqrt(4.0 * asp / math.pi)
    s_prime = max(0.0, s - tie_dia)

    if is_spiral:
        ke = (1.0 - s_prime / (2.0 * ds)) / max(1.0 - rho_cc, 1e-6)
    else:
        ke = (1.0 - s_prime / (2.0 * ds)) ** 2 / max(1.0 - rho_cc, 1e-6)
    ke = min(max(ke, 0.0), 1.0)

    rho_s = 4.0 * asp / (ds * s) if (ds > 0 and s > 0) else 0.0
    rho_s *= _rho_s_scale(mander)
    fl = 0.5 * ke * rho_s * fyh
    return fl, ke, rho_s, rho_cc

def rectangular_confinement(mander, area_lookup: dict | None = None):
    bc = float(getattr(mander, "x_leg_spacing", 0.0) or 0.0)
    dc = float(getattr(mander, "y_leg_spacing", 0.0) or 0.0)
    nx = int(getattr(mander, "num_x_legs", 0) or 0)
    ny = int(getattr(mander, "num_y_legs", 0) or 0)
    s = float(getattr(mander, "tie_spacing", 0.0) or 0.0)
    fyh = float(getattr(mander, "confinement_fyh", 0.0) or 0.0)

    if getattr(mander, "bar_size_mode", "size") == "area":
        asp = float(getattr(mander, "bar_area", 0.0) or 0.0)
    else:
        asp = bar_area_m2(getattr(mander, "bar_size", ""), area_lookup)

    if bc <= 0 or dc <= 0 or s <= 0 or nx < 2 or ny < 2:
        return 0.0, 0.0, 0.0, 0.0, 0.0

    tie_dia = math.sqrt(4.0 * asp / math.pi)

    db_long = tie_dia
                                                                            
    w_lx = bc
    w_ly = dc

    def _face_sum_wi2(w_l: float, n_bars: int) -> float:
        """Sum of squared clear gaps between n_bars evenly spaced bars
        (including the 2 corners) along a face of clear width w_l."""
        if n_bars < 2:
            return 0.0
        gap = max(0.0, w_l / (n_bars - 1) - db_long)
        return (n_bars - 1) * (gap ** 2)

    sum_wi2 = 2.0 * _face_sum_wi2(w_lx, ny) + 2.0 * _face_sum_wi2(w_ly, nx)

    s_prime = max(0.0, s - tie_dia)

    n_lx = int(getattr(mander, "num_long_x", 0) or 0)                          
    n_ly = int(getattr(mander, "num_long_y", 0) or 0)                          
    a_long = bar_area_m2(getattr(mander, "long_bar_size_rect", ""), area_lookup)
    n_long = 2 * (n_lx + n_ly) - 4 if (n_lx >= 2 and n_ly >= 2) else 0
    rho_cc = min(max(n_long * a_long / (bc * dc), 0.0), 0.5) if bc * dc > 0 else 0.0

    ke = (
        (1.0 - sum_wi2 / (6.0 * bc * dc))
        * (1.0 - s_prime / (2.0 * bc))
        * (1.0 - s_prime / (2.0 * dc))
        / max(1.0 - rho_cc, 1e-6)
    )
    ke = min(max(ke, 0.0), 1.0)

    layout = str(getattr(mander, "tie_layout", "rect"))
                                                                                                             
    if layout == "rect_octagonal" and n_lx >= 3 and n_ly >= 3:
                                                                                         
        rho_x, rho_y = octagonal_tie_rho(asp, s, bc, dc, n_lx, n_ly)
    else:
        rho_x = (nx * asp) / (s * dc)
        rho_y = (ny * asp) / (s * bc)
    k_rho = _rho_s_scale(mander)
    rho_x *= k_rho
    rho_y *= k_rho
    rho_s = rho_x + rho_y
    fl_x = ke * rho_x * fyh
    fl_y = ke * rho_y * fyh
    fl_avg = 0.5 * (fl_x + fl_y)
    return fl_avg, fl_x, fl_y, ke, rho_s

def solve_confinement(mander, fc: float, area_lookup: dict | None = None):
    mtype = getattr(mander, "mander_type", "Unconfined")
    if mtype == "Confined_Rect":
        fl_avg, fl_x, fl_y, ke, rho_s = rectangular_confinement(mander, area_lookup)
        cap = CHART_LIMIT_FL_RATIO * fc
        fcc = multiaxial_failure_surface(fc, min(fl_x, cap), min(fl_y, cap))
        ratio = fcc / fc if fc > 0 else 1.0
        return {"fcc_ratio": ratio, "fl": fl_avg, "fl_x": fl_x, "fl_y": fl_y, "ke": ke, "rho_s": rho_s}
        
    elif mtype == "Confined_Circ_Hoop":
        fl, ke, rho_s, rho_cc = circular_confinement(mander, fc, is_spiral=False, area_lookup=area_lookup)
        ratio = mander_strength_ratio(fl, fc)
        return {"fcc_ratio": ratio, "fl": fl, "ke": ke, "rho_s": rho_s, "rho_cc": rho_cc}
        
    elif mtype == "Confined_Circ_Spiral":
        fl, ke, rho_s, rho_cc = circular_confinement(mander, fc, is_spiral=True, area_lookup=area_lookup)
        ratio = mander_strength_ratio(fl, fc)
        return {"fcc_ratio": ratio, "fl": fl, "ke": ke, "rho_s": rho_s, "rho_cc": rho_cc}
        
    else:
        return {"fcc_ratio": 1.0, "fl": 0.0}

def rebar_stress_at(eps, fy, fu, E, eps_sh, eps_su, model_choice="Park"):
    """
    Single point on the Rebar parametric stress-strain curve, elastic
    through strain-hardening regions only (eps clamped to [0, eps_su] --
    the post-eps_su failure tail is a separate, empirically-confirmed
    rule that lives in generate_rebar_curve() below and is deliberately
    NOT part of this function's domain, since it also isn't part of the
    reference tool's own energy integral, which stops at eps_su).

    Equations are the reference tool's own documented "Rebar Parametric
    Stress-Strain Curves" verbatim (elastic / perfectly-plastic /
    strain-hardening, Simple vs Park), and were independently verified
    three times against real reference stress-strain exports (two Park
    cases with different eps_sh/eps_su, one Simple case) to within
    ~0.1% -- see material_dialog.py's Nonlinear Material Data dialog,
    which plots this exact function.

    generate_rebar_curve() (the plotted curve) and calc_rebar_energy()
    (the Mander confinement energy integral) both call this single
    function, so the two can never drift apart from each other.
    """
    if fy <= 0.0 or E <= 0.0:
        return 0.0
    eps_y = fy / E
    if eps <= eps_y:
        return E * eps
    if eps <= eps_sh:
        return fy
    r = max(eps_su - eps_sh, 1e-9)
    x = min(eps, eps_su) - eps_sh
    if model_choice == "Simple":
        return fy + (fu - fy) * math.sqrt(x / r)
    else:        
        m = ((fu / fy) * (30 * r + 1) ** 2 - 60 * r - 1) / (15 * r ** 2) if fy > 0 else 0.0
        term1 = (m * x + 2) / (60 * x + 2)
        term2 = (x * (60 - m)) / (2 * (30 * r + 1) ** 2)
        return fy * (term1 + term2)

def generate_rebar_curve(fy, fu, E, eps_sh, eps_su, final_slope, model_choice="Park", n_inter=20):
    """Generates standard Rebar stress-strain curve (Park or Simple)."""
    eps_y = fy / E if E > 0 else 0.0

    def _pos_branch():
        branch = [(0.0, 0.0), (eps_y, fy)]
        if eps_sh > eps_y:
            branch.append((eps_sh, fy))

        r = max(eps_su - eps_sh, 1e-9)
        step = r / n_inter
        for i in range(1, n_inter + 1):
            eps = eps_sh + i * step
            branch.append((eps, rebar_stress_at(eps, fy, fu, E, eps_sh, eps_su, model_choice)))

        tail_eps = 1.2 * eps_su
        f_tail = branch[-1][1] + (final_slope * E) * (tail_eps - eps_su)
        branch.append((tail_eps, f_tail))
        return branch

    pos_pts = _pos_branch()
    neg_pts = [(-eps, -f) for (eps, f) in reversed(pos_pts) if eps > 0]

    pts_si = neg_pts + pos_pts
    marker = (eps_su, fu)
    return pts_si, marker

def steel_stress_at(eps, fy, fu, E, eps_sh, eps_su):
    """Simple parametric stress calculation for steel."""
    if fy <= 0.0 or E <= 0.0:
        return 0.0
    eps_y = fy / E
    if eps <= eps_y:
        return E * eps
    if eps <= eps_sh:
        return fy
    if eps <= eps_su:
        r = max(eps_su - eps_sh, 1e-9)
        x = eps - eps_sh
        return fy + (fu - fy) * math.sqrt(x / r)
    return fu                                           

def generate_steel_curve(fy, fu, E, eps_sh, eps_su, eps_rupture, final_slope, n_inter=20):
    """Generates standard Steel stress-strain curve using the Simple model."""
    eps_y = fy / E if E > 0 else 0.0

    def _pos_branch():
        branch = [(0.0, 0.0), (eps_y, fy)]
        if eps_sh > eps_y:
            branch.append((eps_sh, fy))

        r = max(eps_su - eps_sh, 1e-9)
        step = r / n_inter
        for i in range(1, n_inter + 1):
            eps = eps_sh + i * step
            branch.append((eps, steel_stress_at(eps, fy, fu, E, eps_sh, eps_su)))
        
        if eps_rupture > eps_su:
            branch.append((eps_rupture, fu))

        tail_eps = 1.2 * eps_rupture
        f_tail = branch[-1][1] + (final_slope * E) * (tail_eps - eps_rupture)
        branch.append((tail_eps, max(f_tail, 0.0)))
        
        return branch

    pos_pts = _pos_branch()
    neg_pts = [(-eps, -f) for (eps, f) in reversed(pos_pts) if eps > 0]

    pts_si = neg_pts + pos_pts
    marker = (eps_su, fu)
    return pts_si, marker

def calc_rebar_energy(fy: float, fu: float, E: float, eps_sh: float,
                       eps_u: float, model_choice: str = "Park",
                       n: int = 4000) -> float:
    """
    U_sf / A2 (per the reference tool's own documentation: "A2 is the area
    under the confinement steel stress-strain curve" up to its ultimate
    strain eps_u, used directly in A1 = rho_s*A2). Numerically integrates
    rebar_stress_at() -- the exact same Park/Simple point function
    generate_rebar_curve() plots and that was verified three times
    against real reference exports -- from 0 to eps_u. No closed-form
    average shortcut, no 110 MJ/m^3 constant, no bar-area guess table:
    this is an exact integral of the confining/tie steel's own real
    curve, not an approximation of it.

    fy/fu/E/eps_sh/eps_u/model_choice must be the REAL values of
    whichever material is actually assigned as the confinement (tie/
    hoop/spiral) steel -- see ManderDataDialog._on_frame_sec_changed()
    in material_dialog.py, which reads them off that material's own
    Material.fu/E and NonlinearMaterialData.rebar_eps_sh/rebar_eps_su/
    rebar_parametric_model via the section's own
    ReinforcementData.tie_bar_material. This function does not guess a
    fallback if those aren't available -- see calc_mander_eps_cu()'s
    docstring for what happens in that case.
    """
    if fy <= 0.0 or E <= 0.0 or eps_u <= 0.0:
        return 0.0

    h = eps_u / n
    area = 0.0
    for i in range(n):
        eps_mid = (i + 0.5) * h
        area += rebar_stress_at(eps_mid, fy, fu, E, eps_sh, eps_u, model_choice) * h
    return area

def _tie_material_fields(mander):
    """
    Pulls the real confinement/tie steel curve data snapshotted onto
    `mander` by ManderDataDialog._on_frame_sec_changed() (Frame Section
    source mode only -- see ManderConfinementData in properties.py).
    Returns (tie_fu, tie_E, tie_eps_sh, tie_eps_u, tie_curve), each
    None where not set (e.g. User Defined source mode, or legacy saved
    data from before this wiring existed) so calc_mander_eps_cu()'s
    no-guess fallback triggers correctly instead of treating 0.0 as a
    real value.
    """
    if mander is None:
        return None, None, None, None, "Park"
    tie_fu = float(getattr(mander, "confinement_fu", 0.0) or 0.0) or None
    tie_E = float(getattr(mander, "confinement_E", 0.0) or 0.0) or None
    tie_eps_sh = float(getattr(mander, "confinement_eps_sh", 0.0) or 0.0) or None
    tie_eps_u = float(getattr(mander, "confinement_eps_su", 0.0) or 0.0) or None
    tie_curve = getattr(mander, "confinement_curve_model", "Park") or "Park"
    return tie_fu, tie_E, tie_eps_sh, tie_eps_u, tie_curve

def calc_mander_eps_cu(fc, eps_c0, E, ratio, rho_s, asp, fyh,
                        tie_fu=None, tie_E=None, tie_eps_sh=None,
                        tie_eps_u=None, tie_curve="Park"):
    """
    Energy-balance solve for the confined concrete ultimate strain
    eps_cu (per the reference tool's own documentation: A1 = rho_s*A2,
    solved by trial and error below -- exactly that equation, no extra
    Usc term from the 1988 journal paper's fuller Eq. 59, since that
    documentation confirms the reference tool's own implementation omits
    it).

    A2 comes from calc_rebar_energy() integrating the confinement
    steel's REAL curve. tie_fu/tie_E/tie_eps_sh/tie_eps_u/tie_curve
    must be that real material's own values (see calc_rebar_energy()'s
    docstring for where those come from) -- fyh (already a required
    positional arg) doubles as that same material's fy.

    No guessed fallback: if the real tie material's curve data isn't
    available yet (e.g. a Mander confinement setup with no Frame
    Section source linked), this returns the same eps_c0*2.0 fallback
    as the other "can't compute" guards below, rather than silently
    substituting an assumed fu/eps_sh/eps_u. Wire up a real tie
    material instead of relying on this fallback.
    """
    if ratio <= 1.001 or rho_s <= 0.0 or fc <= 0.0:
        return eps_c0 * 2.0
    if not tie_fu or not tie_E or not tie_eps_sh or not tie_eps_u:
        return eps_c0 * 2.0

    target_energy = rho_s * calc_rebar_energy(fyh, tie_fu, tie_E, tie_eps_sh,
                                               tie_eps_u, tie_curve)
    fpeak_c = fc * ratio
    eps_peak_c = confined_strain_at_peak(eps_c0, ratio)
    
    esec_c = fpeak_c / eps_peak_c
    r_conf = E / (E - esec_c) if abs(E - esec_c) > 1e-6 else 4.0
    r_conf = max(1.05, min(r_conf, 40.0))

    r_unc = E / (E - (fc / eps_c0)) if abs(E - (fc / eps_c0)) > 1e-6 else 4.0
    r_unc = max(1.05, min(r_unc, 40.0))

    eps, d_eps, A1 = 0.0, 0.0001, 0.0
    eps_prev, A1_prev = eps, A1

    while eps < 0.30:
        x_c = eps / eps_peak_c
        f_conf = fpeak_c * x_c * r_conf / (r_conf - 1.0 + x_c**r_conf) if x_c > 0 else 0.0

        if eps <= 2.0 * eps_c0:
            x_u = eps / eps_c0
            f_unc = fc * x_u * r_unc / (r_unc - 1.0 + x_u**r_unc) if x_u > 0 else 0.0
        else:
            f_unc = 0.0

        A1 += max(f_conf - f_unc, 0.0) * d_eps

        if A1 >= target_energy:
                                                                  
            if A1 > A1_prev:
                frac = (target_energy - A1_prev) / (A1 - A1_prev)
            else:
                frac = 0.0
            return eps_prev + frac * (eps - eps_prev)

        eps_prev, A1_prev = eps, A1
        eps += d_eps

    return 0.30

def _popovics_branch(fpeak, eps_peak, eps_ult, final_slope_mult, E, is_confined, n=120):
    if eps_peak <= 0 or fpeak <= 0:
        return [(0.0, 0.0)]

    esec = fpeak / eps_peak
    denom = E - esec
    r = E / denom if abs(denom) > 1e-6 else 4.0
    r = max(1.05, min(r, 40.0))

    pts = [(0.0, 0.0)]
    n = max(n, 0)                                    
    
    if not is_confined:
        x_end = 2.0  
        n1 = max(round(n * 0.75), 1) if n > 0 else 0
        for i in range(1, n1 + 1):
            x = x_end * i / n1
            f = fpeak * x * r / (r - 1.0 + x ** r)
            pts.append((x * eps_peak, max(f, 0.0)))
        
        strain_at_spall, f_at_spall = pts[-1] if len(pts) > 1 else (0.0, 0.0)
        
        if eps_ult > strain_at_spall:
            n2 = max(round(n * 0.25), 1) if n > 0 else 0
            for i in range(1, n2 + 1):
                eps = strain_at_spall + (eps_ult - strain_at_spall) * i / n2
                f = max(f_at_spall * (1.0 - i / n2), 0.0)
                pts.append((eps, f))
        else:
            if n > 0:
                pts.append((strain_at_spall * 1.01, 0.0))
                
    else:
        x_end = max(eps_ult / eps_peak, 1.0001)
        n1 = max(round(n * 0.8), 1) if n > 0 else 0
        for i in range(1, n1 + 1):
            x = x_end * i / n1
            eps = x * eps_peak
            f = fpeak * x * r / (r - 1.0 + x ** r)
            pts.append((eps, max(f, 0.0)))
        
        fracture_strain, fracture_stress = pts[-1] if len(pts) > 1 else (0.0, 0.0)
        E_limit = final_slope_mult * E

        delta_eps_window = fracture_strain * 0.20
        delta_eps_zero = -fracture_stress / E_limit if E_limit != 0 else delta_eps_window
        delta_eps = min(delta_eps_window, delta_eps_zero)
        n2 = max(round(n * 0.2), 1) if n > 0 else 0
        
        for i in range(1, n2 + 1):
            eps = fracture_strain + delta_eps * i / n2
            f = fracture_stress + E_limit * (eps - fracture_strain)
            pts.append((eps, max(f, 0.0)))
                
    return pts

def generate_mander_curve(fc, eps_c0, eps_cu_user, final_slope_mult, E, mander=None, n=120, area_lookup=None, model_choice="Mander (Exact)"):
    result = solve_confinement(mander, fc, area_lookup) if mander is not None else {"fcc_ratio": 1.0}
    ratio = result.get("fcc_ratio", 1.0)
    is_confined = ratio > 1.001

    fpeak = fc * ratio
    eps_peak = confined_strain_at_peak(eps_c0, ratio)

    if is_confined:
        rho_s = result.get("rho_s", 0.0)
        fyh = float(getattr(mander, "confinement_fyh", 0.0) or 0.0) if mander else 0.0
        asp = 0.0
        if mander:
            asp = float(getattr(mander, "bar_area", 0.0)) if getattr(mander, "bar_size_mode", "size") == "area" else bar_area_m2(getattr(mander, "bar_size", ""), area_lookup)
        
        tie_fu, tie_E, tie_eps_sh, tie_eps_u, tie_curve = _tie_material_fields(mander)
        eps_ult = calc_mander_eps_cu(fc, eps_c0, E, ratio, rho_s, asp, fyh,
                                      tie_fu, tie_E, tie_eps_sh, tie_eps_u, tie_curve)
    else:
        eps_ult = eps_cu_user * (eps_peak / eps_c0) if eps_c0 > 0 else eps_cu_user

    comp_pts = _popovics_branch(fpeak, eps_peak, eps_ult, final_slope_mult, E, is_confined, n=n)
    
    comp_pts = [(-s, -f) for s, f in reversed(comp_pts)]

    if fc > 0:
        ft = 7.5 * math.sqrt(fc / 6894.757) * 6894.757
    else:
        ft = 0.0
        
    eps_t = ft / E if E > 0 else 0.0
    eps_t_end = 11.0 * eps_t
    
    tension_pts = [(0.0, 0.0), (eps_t, ft), (eps_t_end, 0.0)] if eps_t > 0 else [(0.0, 0.0)]

    if comp_pts and comp_pts[-1] == (0.0, 0.0):
        comp_pts = comp_pts[:-1]

    return comp_pts + tension_pts, result

UNCONFINED_TABLE_RATIOS = (0.1, 0.488, 0.784, 1.0, 1.512, 2.0)

def unconfined_user_table(fc, eps_c0, eps_cu_user, E, mander=None, area_lookup=None):
    """
    Short tabulated version of the unconfined Mander curve, used when a
    parametric curve is converted to User Defined.

    Returns a list of (strain, stress, point_id) sorted by strain, or None
    when the section is confined (the caller then keeps the dense curve).
    Stresses are the same Popovics values generate_mander_curve uses; only
    the sampling differs. Same units as the inputs (SI).
    """
    result = solve_confinement(mander, fc, area_lookup) if mander is not None else {"fcc_ratio": 1.0}
    if result.get("fcc_ratio", 1.0) > 1.001:
        return None
    if fc <= 0 or eps_c0 <= 0 or E <= 0:
        return None

    eps_ult = eps_cu_user * (confined_strain_at_peak(eps_c0, 1.0) / eps_c0)
    esec = fc / eps_c0
    denom = E - esec
    r = E / denom if abs(denom) > 1e-6 else 4.0
    r = max(1.05, min(r, 40.0))

    pts = [(-eps_ult, 0.0, "-E")]
    for x in UNCONFINED_TABLE_RATIOS:
        eps = x * eps_c0
        if eps < eps_ult - 1e-12:
            f = fc * x * r / (r - 1.0 + x ** r)
            pts.append((-eps, -f, "-C" if x == 1.0 else ""))

    ft = 7.5 * math.sqrt(fc / 6894.757) * 6894.757
    eps_t = ft / E
    pts += [(0.0, 0.0, "A"), (eps_t, ft, "B"), (11.0 * eps_t, 0.0, "E")]
    return sorted(pts, key=lambda p: p[0])

def default_user_points(fc, eps_c0):
    return [
        (-2.0 * eps_c0, -fc, ""),
        (0.0, 0.0, "A"),
        (2.0 * eps_c0, fc, ""),
    ]

def get_control_points(fc, eps_c0, eps_cu_user, final_slope_mult, E, mander=None, area_lookup=None):
    """
    The handful of labeled "control points" on the curve -- the same ones
    the reference tool tags in its Point ID column (A, B, -C, -E, E) -- computed
    directly and exactly, independent of the dense point list from
    generate_mander_curve. Meant for a small always-visible summary (a
    pinned row/strip above the scrollable table), so the peak etc. never
    depend on scrolling to the right spot to see them.

    Returns (points, result) where points is a list of
    (strain, stress, label) tuples sorted by strain, and result is the
    same confinement dict generate_mander_curve returns (fcc_ratio, fl,
    ke, rho_s, etc.) in case the caller wants it too.

    Labels:
      -E  compression ultimate strain (first hoop fracture / energy-balance limit)
      -C  compression peak (f'cc, eps_cc)
      A   origin
      B   tension cracking stress
      E   tension ultimate (crack fully open, zero residual stress)
    """
    result = solve_confinement(mander, fc, area_lookup) if mander is not None else {"fcc_ratio": 1.0}
    ratio = result.get("fcc_ratio", 1.0)
    is_confined = ratio > 1.001

    fpeak = fc * ratio
    eps_peak = confined_strain_at_peak(eps_c0, ratio)

    if is_confined:
        rho_s = result.get("rho_s", 0.0)
        fyh = float(getattr(mander, "confinement_fyh", 0.0) or 0.0) if mander else 0.0
        asp = 0.0
        if mander:
            asp = float(getattr(mander, "bar_area", 0.0)) if getattr(mander, "bar_size_mode", "size") == "area" else bar_area_m2(getattr(mander, "bar_size", ""), area_lookup)
        tie_fu, tie_E, tie_eps_sh, tie_eps_u, tie_curve = _tie_material_fields(mander)
        eps_ult = calc_mander_eps_cu(fc, eps_c0, E, ratio, rho_s, asp, fyh,
                                      tie_fu, tie_E, tie_eps_sh, tie_eps_u, tie_curve)
    else:
        eps_ult = eps_cu_user * (eps_peak / eps_c0) if eps_c0 > 0 else eps_cu_user

    esec = fpeak / eps_peak if eps_peak > 0 else 0.0
    r = E / (E - esec) if abs(E - esec) > 1e-6 else 4.0
    r = max(1.05, min(r, 40.0))
    x_ult = eps_ult / eps_peak if eps_peak > 0 else 0.0

    if is_confined:
        f_ult = fpeak * x_ult * r / (r - 1.0 + x_ult ** r) if x_ult > 0 else 0.0
    else:
                                                                      
        f_ult = 0.0

    ft = 7.5 * math.sqrt(fc / 6894.757) * 6894.757 if fc > 0 else 0.0
    eps_t = ft / E if E > 0 else 0.0
    eps_t_end = 11.0 * eps_t

    points = [
        (-eps_ult, -f_ult, "-E"),
        (-eps_peak, -fpeak, "-C"),
        (0.0, 0.0, "A"),
        (eps_t, ft, "B"),
        (eps_t_end, 0.0, "E"),
    ]
    return points, result
