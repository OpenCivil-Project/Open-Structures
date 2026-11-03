"""
os_materials.py

Catalog of OpenSees uniaxial materials OpenCivil can emit, plus a single-element
tester (run_uniaxial) that drives any of them through a strain history.

ONE catalog entry per OpenSees model. Everything else (material_dialog.py fields,
os_nonlinear.py emission, the preview plot) reads from here, so adding a model means
adding one entry, not editing three files.

Entry layout:
    CONCRETE_MODELS / STEEL_MODELS[name] = {
        "label":  text for the combo box,
        "tip":    one-line description,
        "params": [ {key, label, default, tip}, ... ],   # default None -> auto from ctx
        "emit":   function(ops, tag, ctx, p)             # p = resolved params (floats/bools)
        "auto":   function(ctx) -> {key: value}          # values used when the user leaves a param blank
    }

ctx (concrete): fpc, epsc0, epscu (all NEGATIVE), Ec, fct (+), et (+)   [from concrete04_params]
ctx (steel):    fy, fu, Es, esh, eu, Esh (ReinforcingSteel hardening modulus), P

Sign convention everywhere: compression negative, as OpenSees wants.

All argument orders below were EXECUTED against openseespy (see test_os_materials.py).
"""
import math

def _P(key, label, default, tip, kind="float"):
    return {"key": key, "label": label, "default": default, "tip": tip, "kind": kind}

def resolve_params(entry, ctx, user):
    """user: dict of overrides (value or None/'' = auto). Returns fully-resolved dict."""
    out = dict(entry["auto"](ctx)) if entry.get("auto") else {}
    for spec in entry["params"]:
        k = spec["key"]
        v = (user or {}).get(k, None)
        if v is None or v == "":
            v = spec["default"] if spec["default"] is not None else out.get(k)
        out[k] = v
    return out

def _c04(ops, tag, c, p):
    fct, et = c["fct"], c["et"]
    ft = (p or {}).get("ft")
    if ft not in (None, ""):
                                                                                                          
        fct, et = float(ft), 11.0 * float(ft) / c["Ec"]
    ops.uniaxialMaterial("Concrete04", tag, c["fpc"], c["epsc0"], c["epscu"], c["Ec"], fct, et)

def _c01(ops, tag, c, p):
    ops.uniaxialMaterial("Concrete01", tag, c["fpc"], c["epsc0"], p["fpcu"], p["epsU"])

def _c01_auto(c):
    return {"fpcu": 0.2 * c["fpc"], "epsU": c["epscu"]}

def _c02(ops, tag, c, p):
    ops.uniaxialMaterial("Concrete02", tag, c["fpc"], c["epsc0"], p["fpcu"], p["epsU"],
                         p["lam"], p["ft"], p["Ets"])

def _c02_auto(c):
    ft = c["fct"]
    return {"fpcu": 0.2 * c["fpc"], "epsU": c["epscu"], "ft": ft,
            "Ets": ft / max(c["et"] - ft / c["Ec"], 1e-9)}                                             

def _ccm(ops, tag, c, p):
                                                                                                
    rc = c["Ec"] / (c["Ec"] - c["fpc"] / c["epsc0"])
    ops.uniaxialMaterial("ConcreteCM", tag, c["fpc"], c["epsc0"], c["Ec"], rc, p["xcrn"],
                         p["ft"], p["ft"] / c["Ec"], p["rt"], p["xcrp"])

def _ccm_auto(c):
    return {"ft": c["fct"]}

def _c06(ops, tag, c, p):
    ops.uniaxialMaterial("Concrete06", tag, c["fpc"], c["epsc0"], p["n"], p["k"], p["alpha1"],
                         p["ft"], p["et"], p["b"], p["alpha2"])

def _c06_auto(c):
                                                                                            
    n = c["Ec"] * c["epsc0"] / (c["Ec"] * c["epsc0"] - c["fpc"])
    return {"n": n, "k": 0.67 + abs(c["fpc"]) / 1e6 / 62.0, "ft": c["fct"], "et": c["fct"] / c["Ec"]}

def _c07(ops, tag, c, p):
    ops.uniaxialMaterial("Concrete07", tag, c["fpc"], c["epsc0"], c["Ec"], p["ft"], p["et"],
                         p["xp"], p["xn"], p["r"])

def _c07_auto(c):
    r = c["Ec"] / (c["Ec"] - c["fpc"] / c["epsc0"])
    return {"ft": c["fct"], "et": c["fct"] / c["Ec"], "r": r}

def _cd(ops, tag, c, p):
    ops.uniaxialMaterial("ConcreteD", tag, c["fpc"], c["epsc0"], p["ft"], p["et"], c["Ec"], p["alphac"], p["alphat"])

def _cd_auto(c):
                                                                                                                        
    return {"ft": c["fct"], "et": 2.0 * c["fct"] / c["Ec"]}

CONCRETE_MODELS = {
    "Concrete04": {
        "label": "Concrete04 (Popovics / Mander envelope)",
        "tip": "Default. Popovics compression envelope with strength cut-off at eps_cu, exponential tension decay.",
        "params": [_P("ft", "ft  tensile strength [Pa]", None, "Auto = Mander control-point tensile strength (0.62*sqrt(f'c)). Ultimate tensile strain follows as 11*ft/Ec.")],
        "auto": None, "emit": _c04},
    "Concrete01": {
        "label": "Concrete01 (Kent-Scott-Park, no tension)",
        "tip": "Parabola to f'c then linear softening to residual fpcu at epsU. No tensile strength.",
        "params": [_P("fpcu", "fpcu  residual crushing strength [Pa, neg]", None, "Auto = 0.2*f'c"),
                   _P("epsU", "epsU  strain at crushing [neg]", None, "Auto = eps_cu from the Mander curve")],
        "auto": _c01_auto, "emit": _c01},
    "Concrete02": {
        "label": "Concrete02 (linear tension softening)",
        "tip": "Concrete01 compression + tensile strength with linear softening (Ets).",
        "params": [_P("fpcu", "fpcu  residual crushing strength [Pa, neg]", None, "Auto = 0.2*f'c"),
                   _P("epsU", "epsU  strain at crushing [neg]", None, "Auto = eps_cu"),
                   _P("lam", "lambda  unloading slope ratio", 0.1, "Ratio of unloading slope at epsU to initial slope (typ. 0.1)"),
                   _P("ft", "ft  tensile strength [Pa]", None, "Auto = Mander control-point tensile strength"),
                   _P("Ets", "Ets  tension softening stiffness [Pa]", None, "Auto = ft / (eps_t_end - ft/Ec)")],
        "auto": _c02_auto, "emit": _c02},
    "ConcreteCM": {
        "label": "ConcreteCM (Chang-Mander cyclic)",
        "tip": "Chang-Mander (1994): same envelope, own unload/reload rules and tension branch. No crushing strain.",
        "params": [_P("xcrn", "xcrn  compression", 2.3, "Typical 2.3"),
                   _P("rt", "rt  tension shape", 1.2, "Typical 1.2"),
                   _P("xcrp", "xcrp  tension", 10000.0, "Typical 10000"),
                   _P("ft", "ft  tensile strength [Pa]", None, "Auto = Mander control-point tensile strength")],
        "auto": _ccm_auto, "emit": _ccm},
    "Concrete06": {
        "label": "Concrete06 (Thorenfeldt / Popovics-Collins)",
        "tip": "Hysteretic concrete with Thorenfeldt compression and exponential tension (Waugh). No crushing strain: concrete softens but never drops to zero, so eps_cu is not used.",
        "params": [_P("n", "n  pre-peak exponent", None, "Auto = Ec*e0/(Ec*e0 - f'c)"),
                   _P("k", "k  post-peak decay", None, "Auto = 0.67 + f'c[MPa]/62"),
                   _P("alpha1", "alpha1  pre-peak parameter", 0.32, "Typical 0.32"),
                   _P("ft", "ft  tensile strength [Pa]", None, "Auto = Mander tensile strength"),
                   _P("et", "et  strain at ft", None, "Auto = ft/Ec"),
                   _P("b", "b  tension decay exponent", 4.0, "Typical 4"),
                   _P("alpha2", "alpha2  tension parameter", 1.0, "Typical 1.0")],
        "auto": _c06_auto, "emit": _c06},
    "ConcreteD": {
        "label": "ConcreteD (damage-based, Mazars-type)",
        "tip": "Damage model: compression/tension damage evolution. et must exceed ft/Ec (auto = 2*ft/Ec). No crushing strain: concrete softens but never drops to zero, so eps_cu is not used.",
        "params": [_P("ft", "ft  tensile strength [Pa]", None, "Auto = Mander tensile strength"),
                   _P("et", "et  strain at ft", None, "Auto = 2*ft/Ec (must be > ft/Ec)"),
                   _P("alphac", "alphac  compression damage", 1.0, "Damage evolution, compression"),
                   _P("alphat", "alphat  tension damage", 1.0, "Damage evolution, tension")],
        "auto": _cd_auto, "emit": _cd},
    "Concrete07": {
        "label": "Concrete07 (Chang-Mander monotonic + cyclic)",
        "tip": "Chang-Mander 1994 with Popovics compression and tension branch. No crushing strain: concrete softens but never drops to zero, so eps_cu is not used.",
        "params": [_P("ft", "ft  tensile strength [Pa]", None, "Auto = Mander tensile strength"),
                   _P("et", "et  strain at ft", None, "Auto = ft/Ec"),
                   _P("xp", "xp  tension", 2.0, "Typical 2.0"),
                   _P("xn", "xn  compression", 2.3, "Typical 2.3"),
                   _P("r", "r  Popovics exponent", None, "Auto = Ec/(Ec - f'cc/eps_cc)")],
        "auto": _c07_auto, "emit": _c07},
}

def _b_hardening(s):
    """Strain-hardening ratio b = Esh_secant / Es from fy, fu, eu (secant from yield to ultimate)."""
    ey = s["fy"] / s["Es"]
    return max((s["fu"] - s["fy"]) / max(s["eu"] - ey, 1e-9) / s["Es"], 1e-4)

def _rs(ops, tag, s, p):
    args = ["ReinforcingSteel", tag, s["fy"], s["fu"], s["Es"], s["Esh"], s["esh"], s["eu"]]
    if p.get("buckle") == "GA":
        args += ["-GABuck", p["lsr"], p["beta"], p["r"], p["gama"]]
    elif p.get("buckle") == "DM":
        args += ["-DMBuck", p["lsr"], p["alpha"]]
    if p.get("fatigue"):
        args += ["-CMFatigue", p["Cf"], p["alpha_f"], p["Cd"]]
    if p.get("iso"):
        args += ["-IsoHard", p["a1"], p["limit"]]
    ops.uniaxialMaterial(*args)

def _s01(ops, tag, s, p):
    ops.uniaxialMaterial("Steel01", tag, s["fy"], s["Es"], p["b"])

def _s02(ops, tag, s, p):
    ops.uniaxialMaterial("Steel02", tag, s["fy"], s["Es"], p["b"], p["R0"], p["cR1"], p["cR2"],
                         p["a1"], p["a2"], p["a3"], p["a4"])

def _s4(ops, tag, s, p):
    ops.uniaxialMaterial("Steel4", tag, s["fy"], s["Es"], "-kin", p["b"], p["R0"], p["r1"], p["r2"])

def _smpf(ops, tag, s, p):
    ops.uniaxialMaterial("SteelMPF", tag, s["fy"], s["fy"], s["Es"], p["b"], p["b"], p["R0"], p["cR1"], p["cR2"])

def _hardening_auto(s):
    return {"b": _b_hardening(s)}

def _hard(ops, tag, s, p):
    b = p["b"]
    ops.uniaxialMaterial("Hardening", tag, s["Es"], s["fy"], p["H_iso"], p["H_kin"] if p["H_kin"] is not None else b * s["Es"] / (1 - b))

def _epp(ops, tag, s, p):
    ops.uniaxialMaterial("ElasticPP", tag, s["Es"], s["fy"] / s["Es"])

def _hyst(ops, tag, s, p):
    ey = s["fy"] / s["Es"]
    e2, e3 = s["eu"], p["e3_mult"] * s["eu"]
    s3 = s["fu"] * p["s3_ratio"]
    ops.uniaxialMaterial("Hysteretic", tag, s["fy"], ey, s["fu"], e2, s3, e3,
                         -s["fy"], -ey, -s["fu"], -e2, -s3, -e3,
                         p["pinchX"], p["pinchY"], p["damage1"], p["damage2"], p["beta"])

_BUCKLE_CHOICES = ["None", "GA", "DM"]

STEEL_MODELS = {
    "ReinforcingSteel": {
        "label": "ReinforcingSteel (Chang-Mander, buckling / fatigue)",
        "tip": "Default. Esh is fitted to the OpenCivil hardening curve. Optional bar buckling, fatigue, isotropic hardening.",
        "params": [_P("buckle", "Bar buckling", "None", "None | GA (Gomes-Appleton) | DM (Dhakal-Maekawa)", kind="choice:None,GA,DM"),
                   _P("lsr", "lsr  slenderness  L/d (buckling)", 6.0, "Tie spacing / bar diameter"),
                   _P("beta", "beta  GA amplification", 1.0, "GA only. Typ. 1.0"),
                   _P("r", "r  GA reduction", 0.8, "GA only. Typ. 0.8"),
                   _P("gama", "gama  GA buckled-stress factor", 0.5, "GA only. Typ. 0.5"),
                   _P("alpha", "alpha  DM parameter", 1.0, "DM only"),
                   _P("fatigue", "Low-cycle fatigue (Coffin-Manson)", False, "Bar fracture by cumulative damage", kind="bool"),
                   _P("Cf", "Cf  fatigue ductility coeff", 0.26, "Typ. 0.26"),
                   _P("alpha_f", "alpha  fatigue exponent", 0.506, "Typ. 0.506"),
                   _P("Cd", "Cd  cyclic strength reduction", 0.389, "Typ. 0.389"),
                   _P("iso", "Isotropic hardening", False, "Switch -IsoHard on", kind="bool"),
                   _P("a1", "a1  isotropic hardening", 4.3, "Typ. 4.3"),
                   _P("limit", "limit  isotropic hardening cap", 0.01, "Typ. 0.01")],
        "auto": None, "emit": _rs},
    "Steel02": {
        "label": "Steel02 (Giuffre-Menegotto-Pinto)",
        "tip": "Smooth Bauschinger transition, optional isotropic hardening. b is derived from fy, fu, eps_su.",
        "params": [_P("b", "b  strain-hardening ratio", None, "Auto = secant (fu-fy)/(eu-ey)/Es"),
                   _P("R0", "R0", 18.5, "Typ. 18.5"), _P("cR1", "cR1", 0.925, "Typ. 0.925"),
                   _P("cR2", "cR2", 0.15, "Typ. 0.15"),
                   _P("a1", "a1  isotropic (compression)", 0.0, "0 = no isotropic hardening"),
                   _P("a2", "a2", 1.0, ""), _P("a3", "a3  isotropic (tension)", 0.0, ""), _P("a4", "a4", 1.0, "")],
        "auto": _hardening_auto, "emit": _s02},
    "Steel01": {
        "label": "Steel01 (bilinear kinematic)",
        "tip": "Bilinear with kinematic hardening. Simplest option.",
        "params": [_P("b", "b  strain-hardening ratio", None, "Auto = secant (fu-fy)/(eu-ey)/Es")],
        "auto": _hardening_auto, "emit": _s01},
    "Steel4": {
        "label": "Steel4 (kinematic, Menegotto-Pinto)",
        "tip": "Steel4 with kinematic hardening and smooth transition.",
        "params": [_P("b", "b_k  kinematic hardening ratio", None, "Auto = secant (fu-fy)/(eu-ey)/Es"),
                   _P("R0", "R_0", 20.0, "Typ. 20"), _P("r1", "r_1", 0.9, "Typ. 0.9"), _P("r2", "r_2", 0.15, "Typ. 0.15")],
        "auto": _hardening_auto, "emit": _s4},
    "SteelMPF": {
        "label": "SteelMPF (Menegotto-Pinto, Filippou)",
        "tip": "Menegotto-Pinto with Filippou isotropic hardening.",
        "params": [_P("b", "b  strain-hardening ratio", None, "Auto = secant (fu-fy)/(eu-ey)/Es"),
                   _P("R0", "R0", 20.0, "Typ. 20"), _P("cR1", "cR1", 0.925, "Typ. 0.925"), _P("cR2", "cR2", 0.15, "Typ. 0.15")],
        "auto": _hardening_auto, "emit": _smpf},
}

STEEL_MODELS["Hardening"] = {
    "label": "Hardening (isotropic + kinematic)",
    "tip": "Bilinear with separate isotropic and kinematic hardening moduli.",
    "params": [_P("b", "b  hardening ratio (used if H_kin blank)", None, "Auto = secant (fu-fy)/(eu-ey)/Es"),
               _P("H_iso", "H_iso  isotropic modulus [Pa]", 0.0, "0 = purely kinematic"),
               _P("H_kin", "H_kin  kinematic modulus [Pa]", None, "Auto = b*Es/(1-b)")],
    "auto": _hardening_auto, "emit": _hard}
STEEL_MODELS["ElasticPP"] = {
    "label": "ElasticPP (elastic-perfectly-plastic)",
    "tip": "No hardening, no rupture strain. Good for quick checks and structural steel.",
    "params": [], "auto": None, "emit": _epp}
STEEL_MODELS["Hysteretic"] = {
    "label": "Hysteretic (trilinear, optional pinching / damage)",
    "tip": "Points: (fy,ey) -> (fu,eps_su) -> (s3,e3). Symmetric. Pinch/damage 1/0 = none.",
    "params": [_P("s3_ratio", "s3/fu  third point stress ratio", 1.0, "<1 gives post-peak softening"),
               _P("e3_mult", "e3/eps_su  third point strain multiple", 1.5, "> 1"),
               _P("pinchX", "pinchX", 1.0, "1 = no pinching"), _P("pinchY", "pinchY", 1.0, "1 = no pinching"),
               _P("damage1", "damage1  ductility damage", 0.0, "0 = none"), _P("damage2", "damage2  energy damage", 0.0, "0 = none"),
               _P("beta", "beta  stiffness degradation", 0.0, "0 = none")],
    "auto": None, "emit": _hyst}

def models_for(kind):
    return CONCRETE_MODELS if kind == "concrete" else STEEL_MODELS

def emit_material(ops, kind, name, tag, ctx, user=None, rupture=False, next_tag=None):
    """
    Emit one uniaxial material. Returns the tag the SECTION should reference
    (the MinMax wrapper tag if rupture=True and kind == steel).  next_tag() must
    return a fresh tag when a wrapper is needed.
    """
    entry = models_for(kind).get(name)
    if entry is None:
        raise KeyError(f"unknown OpenSees {kind} model '{name}'")
    p = resolve_params(entry, ctx, user)
    entry["emit"](ops, tag, ctx, p)
    out = tag
    if kind == "steel" and rupture:
        out = next_tag()
                                                                                        
        ops.uniaxialMaterial("MinMax", out, tag, "-min", -ctx["eu"], "-max", ctx["eu"])
    return out

def strain_history(peaks, steps_per_leg=40):
    """[0, p1, 0, p2, ...] style list -> dense list of strains through the given peak sequence."""
    pts, cur = [0.0], 0.0
    for pk in peaks:
        n = max(2, int(abs(pk - cur) / max(max(abs(x) for x in peaks), 1e-12) * steps_per_leg * 2) + 2)
        pts += [cur + (pk - cur) * (i + 1) / n for i in range(n)]
        cur = pk
    return pts

def cyclic_history(comp_levels, tension=0.0, steps_per_leg=60):
    """
    Increasing-amplitude compression cycles for the preview:
        0 -> -a1 -> +t -> -a2 -> +t -> ... -> -an -> +t -> 0
    comp_levels: positive compression amplitudes (strain magnitudes), ascending.
    tension:     positive strain reached at every reversal (0 = unload only to zero strain).
    Returns (strains, cycle_idx), same length; cycle_idx[i] = k for every point on cycle k
    (the load leg into level k plus its unload leg), so the plot can shade cycles individually.
    """
    levels = [abs(float(a)) for a in comp_levels]
    ref = max(max(levels), abs(tension), 1e-12)
    strains, ids, cur = [0.0], [0], 0.0
    for k, a in enumerate(levels):
        legs = [-a, abs(tension)] if k < len(levels) - 1 else [-a, abs(tension)]
        for target in legs:
            n = max(6, int(math.ceil(abs(target - cur) / ref * steps_per_leg)))
            for i in range(1, n + 1):
                strains.append(cur + (target - cur) * i / n)
                ids.append(k)
            cur = target
    n = max(4, int(math.ceil(abs(cur) / ref * steps_per_leg)))
    for i in range(1, n + 1):
        strains.append(cur * (1.0 - i / n))
        ids.append(len(levels) - 1)
    return strains, ids

def monotonic_history(end, n=400):
    """0 -> -end (compression), n steps; used for the dashed envelope in the preview."""
    return [-abs(end) * i / n for i in range(n + 1)]

def run_uniaxial(emit_fn, strains):
    """
    emit_fn(ops, tag) must create a uniaxial material with that tag.
    Drives it with a unit zeroLength element (displacement == strain, force == stress).
    Returns (strains, stresses, ok) -- stops early (ok False) on a non-converged step.
    """
    import openseespy.opensees as ops
    ops.wipe()
    ops.model("basic", "-ndm", 1, "-ndf", 1)
    ops.node(1, 0.0); ops.node(2, 0.0)
    ops.fix(1, 1)
    emit_fn(ops, 1)
    ops.element("zeroLength", 1, 1, 2, "-mat", 1, "-dir", 1)
    ops.timeSeries("Linear", 1)
    ops.pattern("Plain", 1, 1)
    ops.load(2, 1.0)
    ops.system("BandGeneral"); ops.numberer("Plain"); ops.constraints("Plain")
    ops.test("NormDispIncr", 1e-10, 100); ops.algorithm("ModifiedNewton", "-initial")
    out_e, out_s, ok = [0.0], [0.0], True
    last = 0.0
    for target in strains[1:]:
        ops.integrator("DisplacementControl", 2, 1, target - ops.nodeDisp(2, 1))
        ops.analysis("Static")
        if ops.analyze(1) != 0:
            ok = False
            break
        last = target
        out_e.append(ops.nodeDisp(2, 1))
        ops.reactions()
        out_s.append(-ops.nodeReaction(1, 1))
    ops.wipe()
    return out_e, out_s, ok
