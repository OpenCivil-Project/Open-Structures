"""
os_nonlinear.py

Converts OpenCivil reinforced-concrete frame sections (reinforcement +
nonlinear material data, as saved by StructuralModel.save_to_file()) into
OpenSees fiber sections, for use by OS_OP.py.

Everything that is pure geometry / parameter extraction is separate from
the code that talks to OpenSees, so the plan for every section can be
built and inspected WITHOUT openseespy:

    builder = NonlinearSectionBuilder(oc_data, ops=None)
    plan = builder.plan_section("C1")        # pure Python, no OpenSees
    print(builder.describe(plan))

and only build_section()/add_element() need a real (or stub) `ops`.

----------------------------------------------------------------------
WHAT IS CONVERTED (v1)
----------------------------------------------------------------------
  * Rectangular and circular sections carrying a `reinforcement` block,
    design_type "column" or (rectangular only) "beam".
  * Column: cover concrete (unconfined Mander) + core concrete (Mander
    confined, rebuilt PER SECTION from sec.reinforcement exactly like
    ManderDataDialog._on_frame_sec_changed, NOT from the material's own
    single `mander` snapshot, which can only describe one section).
  * Beam: whole section unconfined concrete; top/bottom bars as saved.
  * Longitudinal bars as individual fibers, laid out with the same rule
    the section dialog preview uses.
  * Concrete -> Concrete04, rebar -> ReinforcingSteel, hysteresis_type
    mapped where a real equivalent exists (see HYSTERESIS notes below).
  * Shear and torsion added elastically (G*As2, G*As3, G*J) with a
    Section Aggregator, since a bare 3D fiber section has neither.

NOT CONVERTED (section stays elastic, a warning is recorded):
  trapezoidal / other section types with reinforcement, circular "beam"
  design type, nonlinear "User Defined" curve mode, materials without
  nonlinear data.

----------------------------------------------------------------------
KNOWN APPROXIMATIONS (by design, reported not hidden)
----------------------------------------------------------------------
  * Concrete04 compression is the same Popovics equation your Mander code
    uses, so the ascending/descending branch up to eps_cu matches. What
    Concrete04 cannot reproduce: your post-eps_cu residual tail (confined)
    and the linear spall segment from 2*eps_c0 to eps_cu (unconfined).
  * ReinforcingSteel's hardening curve has a different shape family than
    your Park/Simple curves. Esh is FITTED (least squares over the
    hardening branch) and the max fit error is reported per material.
  * Displaced concrete under the bars is not subtracted (standard practice).
  * The OpenSees material argument orders below are from the OpenSees
    documentation as remembered, NOT executed against openseespy in the
    environment this was written in. First run on a real install should
    be treated as the verification step.

----------------------------------------------------------------------
AXES
----------------------------------------------------------------------
OpenCivil section coordinates: y = local axis 2 (b direction),
z = local axis 3 (h direction, +z is "up" in the section preview).
OS_OP.py builds geomTransf with vecxz = OC local-2, which makes OpenSees
local z = OC local-2 and OpenSees local y = -OC local-3. A point at
OC section coords (y, z) therefore lands at OpenSees fiber coords
(y_os, z_os) = (-z, y). See _to_os(). Column layouts are symmetric so
only the swap matters there; beams (different top/bottom steel) need the
sign too, and get it.
"""
import math

from core import mander_model as mm
from core.opensees_port import os_materials as osm
from core.properties import NonlinearMaterialData, ManderConfinementData, ReinforcementData

class ConversionError(Exception):
    """A section/material cannot be converted; caller keeps it elastic."""

DEBUG_CORE_EPSCU = None

def _hyst_plan(kind, hyst):
    """kind: 'concrete' | 'rebar'.  Returns (wrap_path_independent, note|None)."""
    h = hyst or "Takeda"
    if kind == "concrete":
        if h in ("Takeda", "Concrete"):
            return False, None
        if h == "Elastic":
            return True, None
        if h in ("Kinematic", "Isotropic"):
            return False, (f"hysteresis '{h}' is not defined for concrete -> "
                           f"using Concrete04's built-in unload/reload rules")
        return False, (f"hysteresis '{h}' has no OpenSees equivalent with the stored data -> "
                       f"using Concrete04's built-in unload/reload rules")
           
    if h == "Kinematic":
        return False, None
    if h == "Elastic":
        return True, None
    if h == "Takeda":
        return False, "hysteresis 'Takeda' (default) on rebar -> ReinforcingSteel's kinematic model"
    if h == "Isotropic":
        return False, ("hysteresis 'Isotropic' -> ReinforcingSteel kinematic model; isotropic-hardening "
                       "option NOT switched on (no parameters are stored for it)")
    return False, (f"hysteresis '{h}' has no OpenSees equivalent with the stored data -> "
                   f"ReinforcingSteel's kinematic model")

def rebar_tables(oc_data):
    """({id: area_m2}, {id: diameter_m}, warning|None) from data['rebar_sizes']."""
    sizes = oc_data.get("rebar_sizes") or []
    if sizes:
        return ({b["id"]: b["area"] for b in sizes},
                {b["id"]: b["diameter"] for b in sizes}, None)
    area = {k: v * 1e-6 for k, v in mm.BAR_AREAS_MM2.items()}
    dia = {k: math.sqrt(4.0 * a / math.pi) for k, a in area.items()}
    return area, dia, ("model has no rebar_sizes catalog; using built-in CSA metric bars only "
                       "(imperial ids like '#9' will fail)")

def build_mander_for_section(sec, r, dia_lookup, tie_mat, tie_nl, warnings):
    """
    Same mapping ManderDataDialog._on_frame_sec_changed performs, as a pure
    function. Returns a ManderConfinementData for a column section.
    """
    if r.tie_bar_size not in dia_lookup:
        raise ConversionError(f"tie bar size '{r.tie_bar_size}' not in rebar catalog")
    td = dia_lookup[r.tie_bar_size]
    c = r.clear_cover
    m = ManderConfinementData()
    m.source_mode = "frame"
    m.frame_section_name = sec["name"]
    m.bar_size_mode = "size"
    m.bar_size = r.tie_bar_size
    m.tie_spacing = r.tie_spacing
    m.tie_bar_material = r.tie_bar_material

    if sec["type"] == "rectangular":
        m.mander_type = "Confined_Rect"
        m.x_leg_spacing = max(0.0, sec["b"] - 2.0 * c - td)
        m.y_leg_spacing = max(0.0, sec["h"] - 2.0 * c - td)
        m.num_x_legs = r.num_ties_3dir
        m.num_y_legs = r.num_ties_2dir
        m.num_long_x = r.num_bars_3dir
        m.num_long_y = r.num_bars_2dir
        m.long_bar_size_rect = r.long_bar_size
        m.tie_layout = getattr(r, "tie_layout", "rect") or "rect"
        if m.tie_layout == "rect_octagonal" and (r.num_bars_3dir < 3 or r.num_bars_2dir < 3):
            warnings.append(f"section '{sec['name']}': octagonal ties need >= 3 longitudinal bars per face "
                            f"-> falling back to plain rectangular legs")
            m.tie_layout = "rect"
    else:
        m.mander_type = "Confined_Circ_Spiral" if r.confinement_type == "spiral" else "Confined_Circ_Hoop"
        m.core_diameter = max(0.0, sec["d"] - 2.0 * c - td)
        m.num_long_bars = r.num_bars_circ
        m.long_bar_size = r.long_bar_size
        m.long_bar_mode = "count"

    m.rho_s_scale = float(getattr(r, "rho_s_scale", 1.0) or 1.0)
    m.confinement_fyh = float(tie_mat.get("fy", 0.0) or 0.0)
    m.confinement_fu = float(tie_mat.get("fu", 0.0) or 0.0)
    m.confinement_E = float(tie_mat.get("E", 0.0) or 0.0)
    if tie_nl is not None and str(tie_mat.get("type", "")).lower() == "rebar":
        m.confinement_eps_sh = float(tie_nl.rebar_eps_sh or 0.0)
        m.confinement_eps_su = float(tie_nl.rebar_eps_su or 0.0)
        m.confinement_curve_model = tie_nl.rebar_parametric_model or "Park"
    else:
        warnings.append(f"section '{sec['name']}': tie material '{r.tie_bar_material}' has no rebar "
                        f"nonlinear data -> confined eps_cu falls back to 2*eps_c0 (mander_model's own fallback)")
    return m

def concrete04_params(mat, nl, mander, area_lookup):
    """
    Concrete04 arguments from your exact control points (-C peak, -E ultimate,
    B cracking, E tension end). Compression values negative, as OpenSees wants.
    """
    fc = float(mat["fy"])                                              
    E = float(mat["E"])
    if fc <= 0 or E <= 0:
        raise ConversionError(f"concrete '{mat['name']}': need fy(=f'c) > 0 and E > 0")
    pts, res = mm.get_control_points(fc, nl.eps_c0, nl.eps_cu, nl.final_slope_mult, E,
                                     mander=mander, area_lookup=area_lookup)
    cp = {label: (s, f) for (s, f, label) in pts}
    eps_ult, _ = cp["-E"]
    eps_peak, f_peak = cp["-C"]
    if DEBUG_CORE_EPSCU is not None and mander is not None:                 
        print(f"[DEBUG_CORE_EPSCU] core epscu {eps_ult:.5f} -> {DEBUG_CORE_EPSCU:.5f}")
        eps_ult = float(DEBUG_CORE_EPSCU)
    if mander is not None and getattr(nl, "core_eps_cu_mode", "Mander") == "User":              
        eps_ult = -abs(float(getattr(nl, "core_eps_cu_user", -0.035)))
    _, ft = cp["B"]
    eps_t_end, _ = cp["E"]
    return {
        "fpc": f_peak,                           
        "epsc0": eps_peak,                       
        "epscu": eps_ult,                        
        "Ec": E,
        "fct": ft,
        "et": eps_t_end,
        "fcc_ratio": res.get("fcc_ratio", 1.0),
        "confinement": res,
        "os_model": str(getattr(nl, "os_concrete_model", "Concrete04") or "Concrete04"),
        "user": _concrete_user_params(nl),
    }

def _concrete_user_params(nl):
    """os_params overrides for the chosen concrete model; legacy cm_* fields still honoured for ConcreteCM."""
    user = dict(getattr(nl, "os_params", None) or {})
    if str(getattr(nl, "os_concrete_model", "")) == "ConcreteCM":
        user.setdefault("xcrn", float(getattr(nl, "cm_xcrn", 2.3)))
        user.setdefault("rt", float(getattr(nl, "cm_rt", 1.2)))
        user.setdefault("xcrp", float(getattr(nl, "cm_xcrp", 10000.0)))
    return user

def _cm_hardening(e, fy, fu, esh, esu, P):
    """Chang-Mander hardening branch (ReinforcingSteel's shape family)."""
    t = min(max((esu - e) / (esu - esh), 0.0), 1.0)
    return fu + (fy - fu) * t ** P

def rebar_params(mat, nl):
    """ReinforcingSteel arguments; Esh fitted to your Park/Simple hardening branch."""
    kind = str(mat.get("type", "")).lower()
    fy, fu, E = float(mat["fy"]), float(mat["fu"]), float(mat["E"])
    if kind == "rebar":
        esh, esu, model = nl.rebar_eps_sh, nl.rebar_eps_su, (nl.rebar_parametric_model or "Park")
    else:
        esh, esu, model = nl.steel_eps_sh, nl.steel_eps_su, "Simple"
    if fy <= 0 or E <= 0 or fu <= fy:
        raise ConversionError(f"rebar '{mat['name']}': need fy > 0, E > 0, fu > fy")
    if esu <= esh:
        raise ConversionError(f"rebar '{mat['name']}': eps_su must exceed eps_sh")
    note = None
    ey = fy / E
    if esh <= ey:
        note = f"eps_sh <= yield strain for '{mat['name']}'; nudged to 1.001*eps_y (no plateau)"
        esh = 1.001 * ey
        if esu <= esh:
            raise ConversionError(f"rebar '{mat['name']}': eps_su <= yield strain")

    n = 80
    es = [esh + (esu - esh) * i / n for i in range(n + 1)]
    target = [mm.rebar_stress_at(e, fy, fu, E, esh, esu, model) for e in es]

    def sse(P):
        return sum((_cm_hardening(e, fy, fu, esh, esu, P) - t) ** 2 for e, t in zip(es, target))

    best_P = min((0.2 * 1.04 ** k for k in range(0, 200)), key=sse)                         
    lo, hi = best_P / 1.04, best_P * 1.04                                                    
    g = (math.sqrt(5) - 1) / 2
    for _ in range(60):
        a, b = hi - g * (hi - lo), lo + g * (hi - lo)
        lo, hi = (lo, b) if sse(a) < sse(b) else (a, hi)
    P = 0.5 * (lo + hi)
    fit_err = max(abs(_cm_hardening(e, fy, fu, esh, esu, P) - t) for e, t in zip(es, target)) / (fu - fy)
    return {"fy": fy, "fu": fu, "Es": E, "Esh": P * (fu - fy) / (esu - esh),
            "esh": esh, "eu": esu, "P": P, "fit_err_rel": fit_err, "model": model, "note": note,
            "os_model": str(getattr(nl, "os_steel_model", "ReinforcingSteel") or "ReinforcingSteel"),
            "user": dict(getattr(nl, "os_params", None) or {}),
            "rupture": bool(getattr(nl, "os_rupture", False))}

def bond_slip_params(db, fy, fu, fc, b=0.3, R=0.5, su_mult=35.0, sy_mult=1.0):
    """
    Zhao & Sritharan (2007) bar stress-slip law for Bond_SP01 (strain-penetration / fixed-end
    rotation of a longitudinal bar anchored in a footing or joint).  SI in/out (m, Pa).
        s_y = 2.54*( db/8437 * fy / sqrt(fc') )**(1/0.4) + 0.34      [mm; db mm; fy, fc' MPa]
        s_u = 35 * s_y,  hardening ratio b = 0.3,  pinching R = 0.5
    """
    db_mm, fy_mpa, fc_mpa = db * 1e3, fy / 1e6, fc / 1e6
    sy_mm = 2.54 * (db_mm / 8437.0 * fy_mpa / math.sqrt(fc_mpa)) ** (1.0 / 0.4) + 0.34
    sy = sy_mult * sy_mm * 1e-3
    return {"fy": fy, "sy": sy, "fu": fu, "su": su_mult * sy, "b": b, "R": R}

def hinge_length(L, fy, fu):
    """
    Plastic-hinge length for the FIBER ELEMENT when bar slip is modelled separately
    (Priestley/Paulay): Lp = k*L, k = 0.2*(fu/fy - 1) <= 0.08.  The strain-penetration term
    0.022*fy*db is deliberately NOT included -- the slip section supplies that rotation.
    L = shear span (cantilever length, or distance to the point of contraflexure).
    """
    k = min(0.2 * (fu / fy - 1.0), 0.08)
    return k * L

class SectionPlan:
    def __init__(self, name):
        self.name = name
        self.shape = None                             
        self.design = None                              
        self.patches = []                                                      
        self.bars = []                             
        self.concrete = {}                                                 
        self.rebar = None                                          
        self.G = self.J = self.As2 = self.As3 = 0.0
        self.notes = []
        self.slip = None                                                         

def _linspace(a, b, n):
    return [a] if n == 1 else [a + (b - a) * i / (n - 1) for i in range(n)]

class NonlinearSectionBuilder:
    def __init__(self, oc_data, ops=None, fiber_size_ratio=16, n_int_pts=5,
                 first_mat_tag=1, first_sec_tag=1, first_int_tag=1):
        self.d = oc_data
        self.ops = ops
        self.materials = {m["name"]: m for m in oc_data.get("materials", [])}
        self.sections = {s["name"]: s for s in oc_data.get("sections", [])}
        self.area, self.dia, w = rebar_tables(oc_data)
        self.warnings = []
        if w:
            self.warnings.append(w)
        self.fiber_size_ratio = fiber_size_ratio
        self.slip_b, self.slip_R, self.slip_su_mult, self.slip_sy_mult = 0.3, 0.5, 35.0, 1.0                                             
        self.slip_concrete = "stiff"                                                                                                                                                                                           
        self.fbc_iter = (50, 1e-12)                                                                                                      
        self.shear_spring = None                                                                               
        self.n_int_pts = n_int_pts
        self._next_mat, self._next_sec, self._next_int = first_mat_tag, first_sec_tag, first_int_tag
        self._plans = {}
        self._built = {}
        self._mat_cache = {}

    def _warn(self, msg):
        if msg not in self.warnings:
            self.warnings.append(msg)

    def _bar(self, bar_id):
        if bar_id not in self.area or bar_id not in self.dia:
            raise ConversionError(f"bar size '{bar_id}' not in rebar catalog")
        return self.area[bar_id], self.dia[bar_id]

    def _material(self, name, role):
        if name not in self.materials:
            raise ConversionError(f"{role} material '{name}' not found")
        return self.materials[name]

    def _nl(self, mat):
        nl = NonlinearMaterialData.from_dict(mat.get("nonlinear"))
        if nl is None:
            raise ConversionError(f"material '{mat['name']}' has no nonlinear data")
        if nl.curve_mode == "User Defined":
            raise ConversionError(f"material '{mat['name']}': 'User Defined' curve mode not converted in v1")
        return nl

    def plan_section(self, sec_name):
        """Pure-Python plan for one section, or None (reason in self.warnings)."""
        if sec_name in self._plans:
            return self._plans[sec_name]
        try:
            plan = self._plan(sec_name)
        except ConversionError as e:
            self._warn(f"section '{sec_name}': not converted to fiber ({e}); stays elastic")
            plan = None
        self._plans[sec_name] = plan
        return plan

    def _plan(self, sec_name):
        sec = self.sections.get(sec_name)
        if sec is None:
            raise ConversionError("section not found")
        r = ReinforcementData.from_dict(sec.get("reinforcement"))
        if r is None:
            raise ConversionError("no reinforcement data")
        stype = sec.get("type")
        if stype not in ("rectangular", "circular"):
            raise ConversionError(f"section type '{stype}' with reinforcement is not supported yet")
        if stype == "circular" and r.design_type != "column":
            raise ConversionError("circular section with 'beam' design type is not supported")

        plan = SectionPlan(sec_name)
        plan.shape = "rect" if stype == "rectangular" else "circ"
        plan.design = r.design_type

        conc_mat = self._material(sec["mat_name"], "concrete")
        if str(conc_mat.get("type", "")).lower() != "concrete":
            raise ConversionError(f"section material '{conc_mat['name']}' is not Concrete type")
        conc_nl = self._nl(conc_mat)
        long_mat = self._material(r.long_bar_material, "longitudinal rebar")
        long_nl = self._nl(long_mat)

        props = sec["properties"]
        plan.G = float(conc_mat["G"]) if conc_mat.get("G") else conc_mat["E"] / (2 * (1 + conc_mat["nu"]))
        plan.J = props["J"]
        plan.As2 = props.get("As2", props["A"])
        plan.As3 = props.get("As3", props["A"])

        rp = rebar_params(long_mat, long_nl)
        plan.slip = {"db": self._bar(r.long_bar_size)[1], "fy": float(long_mat["fy"]),
                     "fu": float(long_mat["fu"]), "fc": float(conc_mat["fy"])}
        wrap, hnote = _hyst_plan("rebar", long_nl.hysteresis_type)
        if hnote and getattr(long_nl, "os_steel_model", "ReinforcingSteel") == "ReinforcingSteel":
            self._warn(f"rebar '{long_mat['name']}': {hnote}")
        if rp["note"]:
            self._warn(rp["note"])
        plan.rebar = {"key": ("rebar", long_mat["name"]), "kind": "ReinforcingSteel", "params": rp, "wrap": wrap}

        cover_key = ("conc-unconf", conc_mat["name"])
        cover_params = concrete04_params(conc_mat, conc_nl, None, self.area)
        cwrap, cnote = _hyst_plan("concrete", conc_nl.hysteresis_type)
        if cnote:
            self._warn(f"concrete '{conc_mat['name']}': {cnote}")
        plan.concrete["cover"] = {"key": cover_key, "kind": "Concrete04", "params": cover_params, "wrap": cwrap}

        if r.design_type == "column":
            tie_mat = self._material(r.tie_bar_material, "tie rebar")
            tie_nl = None
            try:
                tie_nl = self._nl(tie_mat)
            except ConversionError:
                tie_nl = None
            warns = []
            mander = build_mander_for_section(sec, r, self.dia, tie_mat, tie_nl, warns)
            for w in warns:
                self._warn(w)
            core_params = concrete04_params(conc_mat, conc_nl, mander, self.area)
            if core_params["fcc_ratio"] <= 1.001:
                self._warn(f"section '{sec_name}': confinement gives no strength gain "
                           f"(check tie legs/spacing); core uses unconfined properties")
            plan.concrete["core"] = {"key": ("conc-conf", sec_name), "kind": "Concrete04",
                                     "params": core_params, "wrap": cwrap}
            self._layout_column(plan, sec, r)
        else:
            plan.concrete["core"] = None
            self._layout_beam(plan, sec, r)
        return plan

    def _layout_column(self, plan, sec, r):
        a_l, d_l = self._bar(r.long_bar_size)
        _, d_t = self._bar(r.tie_bar_size)
        c = r.clear_cover
        eff = c + d_t + d_l / 2.0                                                           
        if plan.shape == "rect":
            b, h = sec["b"], sec["h"]
            yb, zh = b / 2 - c - d_t / 2, h / 2 - c - d_t / 2                              
            if yb <= 0 or zh <= 0:
                raise ConversionError("cover + tie leave no core")
            plan.patches.append({"kind": "rect", "role": "core", "geom": (-yb, -zh, yb, zh)})
            plan.patches += [
                {"kind": "rect", "role": "cover", "geom": (-b / 2, zh, b / 2, h / 2)},           
                {"kind": "rect", "role": "cover", "geom": (-b / 2, -h / 2, b / 2, -zh)},            
                {"kind": "rect", "role": "cover", "geom": (-b / 2, -zh, -yb, zh)},                
                {"kind": "rect", "role": "cover", "geom": (yb, -zh, b / 2, zh)},                   
            ]
            n3, n2 = r.num_bars_3dir, r.num_bars_2dir
            if n3 < 2 or n2 < 2:
                raise ConversionError("need >= 2 bars per face (num_bars_2dir / num_bars_3dir)")
            y0, y1, z0, z1 = -b / 2 + eff, b / 2 - eff, -h / 2 + eff, h / 2 - eff
            if y1 <= y0 or z1 <= z0:
                raise ConversionError("cover leaves no room for longitudinal bars")
            for y in _linspace(y0, y1, n2):                                                       
                plan.bars += [(y, z1, a_l), (y, z0, a_l)]
            for i in range(1, n3 - 1):                                                    
                z = z0 + i * (z1 - z0) / (n3 - 1)
                plan.bars += [(y0, z, a_l), (y1, z, a_l)]
        else:
            d = sec["d"]
            rc = d / 2 - c - d_t / 2
            if rc <= 0:
                raise ConversionError("cover + tie leave no core")
            plan.patches.append({"kind": "circ", "role": "core", "geom": (0.0, rc)})
            plan.patches.append({"kind": "circ", "role": "cover", "geom": (rc, d / 2)})
            n = r.num_bars_circ
            if n < 2:
                raise ConversionError("need >= 2 longitudinal bars (num_bars_circ)")
            rb = d / 2 - eff
            if rb <= 0:
                raise ConversionError("cover leaves no room for longitudinal bars")
            for i in range(n):
                th = 2.0 * math.pi * i / n
                plan.bars.append((rb * math.cos(th), rb * math.sin(th), a_l))

    def _layout_beam(self, plan, sec, r):
        b, h = sec["b"], sec["h"]
        plan.patches.append({"kind": "rect", "role": "cover", "geom": (-b / 2, -h / 2, b / 2, h / 2)})
        y_edge = b / 2 - r.cover_side                                                             
        for count, size, z in ((r.top_bar_count, r.top_bar_size, h / 2 - r.cover_top),
                               (r.bottom_bar_count, r.bottom_bar_size, -(h / 2 - r.cover_bottom))):
            if count <= 0:
                continue
            a_bar, _ = self._bar(size)
            ys = [0.0] if count == 1 else _linspace(-y_edge, y_edge, count)
            plan.bars += [(y, z, a_bar) for y in ys]
        if not plan.bars:
            raise ConversionError("beam has no longitudinal bars")
        plan.notes.append("beam: whole section unconfined concrete (no stirrup confinement path yet)")

    def describe(self, plan):
        if plan is None:
            return "(not converted)"
        lines = [f"section {plan.name}: {plan.shape} {plan.design}, {len(plan.bars)} bars, "
                 f"As={sum(b[2] for b in plan.bars) * 1e4:.2f} cm2"]
        for role in ("core", "cover"):
            c = plan.concrete.get(role)
            if c:
                p = c["params"]
                lines.append(f"  {role:5s} Concrete04  fpc={p['fpc']/1e6:.2f} MPa  ec0={p['epsc0']:.5f}  "
                             f"ecu={p['epscu']:.5f}  ft={p['fct']/1e6:.2f} MPa  et={p['et']:.5f}"
                             + ("  [PathIndependent]" if c["wrap"] else ""))
        rp = plan.rebar["params"]
        lines.append(f"  rebar {rp.get('os_model','ReinforcingSteel')} fy={rp['fy']/1e6:.0f} fu={rp['fu']/1e6:.0f} MPa "
                     f"Esh={rp['Esh']/1e9:.2f} GPa esh={rp['esh']:.4f} eu={rp['eu']:.4f}  "
                     f"(hardening fit err {rp['fit_err_rel']*100:.1f}% of fu-fy, {rp['model']})")
        lines += [f"  note: {n}" for n in plan.notes]
        return "\n".join(lines)

    @staticmethod
    def _to_os(y, z):
        """OpenCivil section (y=local2, z=local3) -> OpenSees fiber (y_os, z_os)."""
        return -z, y

    def _new(self, which):
        tag = getattr(self, f"_next_{which}")
        setattr(self, f"_next_{which}", tag + 1)
        return tag

    def _emit_material(self, spec):
        if spec["key"] in self._mat_cache:
            return self._mat_cache[spec["key"]]
        ops, p = self.ops, spec["params"]
        tag = self._new("mat")
        if spec["kind"] == "Concrete04":
            ctx = {k: p[k] for k in ("fpc", "epsc0", "epscu", "Ec", "fct", "et")}
            out = osm.emit_material(ops, "concrete", p.get("os_model", "Concrete04"), tag, ctx, p.get("user"))
        else:
            out = osm.emit_material(ops, "steel", p.get("os_model", "ReinforcingSteel"), tag, p, p.get("user"),
                                    rupture=p.get("rupture", False), next_tag=lambda: self._new("mat"))
        tag = out
        if spec["wrap"]:
            inner, tag = tag, self._new("mat")
            ops.uniaxialMaterial("PathIndependent", tag, inner)
        self._mat_cache[spec["key"]] = tag
        return tag

    def _ndiv(self, length, size, minimum=1):
        return max(minimum, int(round(length / size)))

    def build_section(self, sec_name):
        """Emit materials + fiber section + aggregator + integration. Returns dict or None."""
        if sec_name in self._built:
            return self._built[sec_name]
        plan = self.plan_section(sec_name)
        if plan is None:
            self._built[sec_name] = None
            return None
        ops = self.ops
        mat_tag = {role: self._emit_material(spec) for role, spec in plan.concrete.items() if spec}
        steel_tag = self._emit_material(plan.rebar)

        fiber_tag, agg_tag, int_tag = self._new("sec"), self._new("sec"), self._new("int")
        ops.section("Fiber", fiber_tag, "-GJ", plan.G * plan.J)

        size = max(self._extent(plan)) / self.fiber_size_ratio
        for p in plan.patches:
            role_tag = mat_tag["core"] if (p["role"] == "core" and "core" in mat_tag) else mat_tag["cover"]
            if p["kind"] == "rect":
                y0, z0, y1, z1 = p["geom"]
                (ya, za), (yb_, zb) = self._to_os(y0, z0), self._to_os(y1, z1)
                ylo, yhi, zlo, zhi = min(ya, yb_), max(ya, yb_), min(za, zb), max(za, zb)
                thin = 2 if p["role"] == "cover" and plan.design == "column" else 1
                ny = self._ndiv(yhi - ylo, size, thin if (yhi - ylo) < (zhi - zlo) else 1)
                nz = self._ndiv(zhi - zlo, size, thin if (zhi - zlo) < (yhi - ylo) else 1)
                ops.patch("rect", role_tag, ny, nz, ylo, zlo, yhi, zhi)
            else:
                r_in, r_out = p["geom"]
                nrad = self._ndiv(r_out - r_in, size, 2 if p["role"] == "cover" else 4)
                ops.patch("circ", role_tag, 32, nrad, 0.0, 0.0, r_in, r_out, 0.0, 360.0)
        for (y, z, a) in plan.bars:
            y_os, z_os = self._to_os(y, z)
            ops.fiber(y_os, z_os, a, steel_tag)

        vy, vz = self._new("mat"), self._new("mat")
        ops.uniaxialMaterial("Elastic", vy, plan.G * plan.As3)
        ops.uniaxialMaterial("Elastic", vz, plan.G * plan.As2)
        ops.section("Aggregator", agg_tag, vy, "Vy", vz, "Vz", "-section", fiber_tag)
        ops.beamIntegration("Lobatto", int_tag, agg_tag, self.n_int_pts)

        info = {"section_tag": agg_tag, "fiber_tag": fiber_tag, "int_tag": int_tag, "plan": plan}
        self._built[sec_name] = info
        return info

    @staticmethod
    def _extent(plan):
        xs = []
        for p in plan.patches:
            g = p["geom"]
            xs += [abs(v) * 2 for v in (g if p["kind"] == "rect" else (g[1],))]
        return xs or [1.0]

    def _slip_scaled_spec(self, role, spec, lsp):
        """Member concrete re-expressed for the UNIT-GAUGE slip section ("scaled" mode).

        Real strain over the strain-penetration length Lsp is eps = delta/Lsp, but the zero-length section
        reports eps_u = delta/1 m = eps*Lsp.  So the same physical stress-strain law is, in unit-gauge strain:
            strains (epsc0, epscu, et, epsU)  ->  x Lsp
            moduli  (Ec, Ets)                 ->  / Lsp
            stresses and dimensionless shape parameters unchanged.
        The concrete then peaks / crushes at the REAL strains, so it neither crushes at ~0.7% drift ("full")
        nor needs a stiff elastic stand-in ("stiff").  User overrides of strain-like / modulus-like parameters
        are scaled too (epsU, et -> x Lsp ; Ets -> / Lsp)."""
        p = dict(spec["params"])
        for k in ("epsc0", "epscu", "et"):
            p[k] = float(p[k]) * lsp
        p["Ec"] = float(p["Ec"]) / lsp
        user = dict(p.get("user") or {})
        for k in ("epsU", "et"):
            if user.get(k) not in (None, ""):
                user[k] = float(user[k]) * lsp
        if user.get("Ets") not in (None, ""):
            user["Ets"] = float(user["Ets"]) / lsp
        p["user"] = user
        return {"key": ("slip-conc", role, spec["key"], round(lsp, 6)), "kind": spec["kind"], "params": p,
                "wrap": spec["wrap"]}

    def build_slip_section(self, sec_name):
        """
        Zero-length fiber section for a zeroLengthSection at a fixed end: same fiber layout and
        concrete as the member section, but every longitudinal bar uses Bond_SP01 (stress vs SLIP).
        With a zero-length element the section 'strain' is the relative displacement, so a bar
        fibre's strain IS its slip and curvature IS the fixed-end rotation.  Returns the aggregator
        tag, or None if the section isn't convertible / has no slip data.
        """
        plan = self.plan_section(sec_name)
        if plan is None or plan.slip is None:
            return None
        key = ("slip", sec_name)
        if key in self._built:
            return self._built[key]
        ops = self.ops
        if self.slip_concrete == "full":
            mat_tag = {role: self._emit_material(spec) for role, spec in plan.concrete.items() if spec}
        elif self.slip_concrete == "scaled":
            lsp = max(0.022 * plan.slip["fy"] * 1e-6 * plan.slip["db"], 1e-3)                            
            mat_tag = {role: self._emit_material(self._slip_scaled_spec(role, spec, lsp))
                       for role, spec in plan.concrete.items() if spec}
        else:
                                                                                                                            
            ec = float(plan.concrete["cover"]["params"]["Ec"])
            lsp = max(0.022 * plan.slip["fy"] * 1e-6 * plan.slip["db"], 1e-3)
            ent = self._new("mat")
            ops.uniaxialMaterial("ENT", ent, ec / lsp)
            mat_tag = {"cover": ent, "core": ent}
        sp = bond_slip_params(**plan.slip, b=self.slip_b, R=self.slip_R, su_mult=self.slip_su_mult, sy_mult=self.slip_sy_mult)
        bond = self._new("mat")
        ops.uniaxialMaterial("Bond_SP01", bond, sp["fy"], sp["sy"], sp["fu"], sp["su"], sp["b"], sp["R"])
        fiber_tag, agg_tag = self._new("sec"), self._new("sec")
        ops.section("Fiber", fiber_tag, "-GJ", plan.G * plan.J)
        size = max(self._extent(plan)) / self.fiber_size_ratio
        for p in plan.patches:                                                                 
            role_tag = mat_tag["core"] if (p["role"] == "core" and "core" in mat_tag) else mat_tag["cover"]
            if p["kind"] == "rect":
                y0, z0, y1, z1 = p["geom"]
                (ya, za), (yb_, zb) = self._to_os(y0, z0), self._to_os(y1, z1)
                ylo, yhi, zlo, zhi = min(ya, yb_), max(ya, yb_), min(za, zb), max(za, zb)
                thin = 2 if p["role"] == "cover" and plan.design == "column" else 1
                ny = self._ndiv(yhi - ylo, size, thin if (yhi - ylo) < (zhi - zlo) else 1)
                nz = self._ndiv(zhi - zlo, size, thin if (zhi - zlo) < (yhi - ylo) else 1)
                ops.patch("rect", role_tag, ny, nz, ylo, zlo, yhi, zhi)
            else:
                r_in, r_out = p["geom"]
                nrad = self._ndiv(r_out - r_in, size, 2 if p["role"] == "cover" else 4)
                ops.patch("circ", role_tag, 32, nrad, 0.0, 0.0, r_in, r_out, 0.0, 360.0)
        for (y, z, a) in plan.bars:
            y_os, z_os = self._to_os(y, z)
            ops.fiber(y_os, z_os, a, bond)
        vy, vz = self._new("mat"), self._new("mat")
        ops.uniaxialMaterial("Elastic", vy, plan.G * plan.As3)
        ops.uniaxialMaterial("Elastic", vz, plan.G * plan.As2)
        ops.section("Aggregator", agg_tag, vy, "Vy", vz, "Vz", "-section", fiber_tag)
        self._built[key] = agg_tag
        self._slip_params = getattr(self, "_slip_params", {})
        self._slip_params[sec_name] = sp
        return agg_tag

    def add_hinge_element(self, ele_tag, node_i, node_j, transf_tag, sec_name, length, lp_i=None, lp_j=None):
        """
        forceBeamColumn with HingeRadau integration (hinge length lp at each end, same fibre section
        in the interior).  lp defaults to hinge_length(length, fy, fu).  Returns False if not convertible.
        """
        info = self.build_section(sec_name)
        if info is None:
            return False
        plan = info["plan"]
        if lp_i is None or lp_j is None:
            d = hinge_length(length, plan.slip["fy"], plan.slip["fu"]) if plan.slip else 0.08 * length
            if plan.slip and getattr(self, "hinge_add_sp", False):
                                                                                                                 
                d += 0.022 * plan.slip["fy"] * 1e-6 * plan.slip["db"]
            lp_i = d if lp_i is None else lp_i
            lp_j = d if lp_j is None else lp_j
        itag = self._new("int")
        s = info["section_tag"]
        self.ops.beamIntegration("HingeRadau", itag, s, lp_i, s, lp_j, s)
        self.ops.element("forceBeamColumn", ele_tag, node_i, node_j, transf_tag, itag, "-iter", int(self.fbc_iter[0]), float(self.fbc_iter[1]))
        self.hinge_lengths = getattr(self, "hinge_lengths", {})
        self.hinge_lengths[ele_tag] = (lp_i, lp_j)
        return True

    def add_slip_spring(self, ele_tag, node_fixed, node_member, sec_name, orient):
        """
        zeroLengthSection between a coincident pair of nodes (node_fixed = the support, node_member =
        the member's end node).  orient = (x1,x2,x3, y1,y2,y3): global vectors of the member's LOCAL x
        and LOCAL y axes (so the fibre coordinates line up with the member section).
        """
        tag = self.build_slip_section(sec_name)
        if tag is None:
            return False
        self.ops.element("zeroLengthSection", ele_tag, node_fixed, node_member, tag, "-orient", *orient)
        return True

    SHEAR_REQUIRED = ("shear_stiffness", "alpha", "pinchX", "pinchY", "damage1", "damage2", "beta", "e3_mult")

    def derive_shear_spring(self, sec_name, L, N=0.0):
        """AUTO values for k0 and Vy, from the section/material/geometry only (nothing fitted to any test):
          k0 = G*As/L                                   uncracked shear stiffness of the member (N/m)
          Vy = Vc + Vs  (ACI 318-19 nominal shear strength, SI):
               Vc = 0.17*(1 + N/(14*Ag))*sqrt(f'c[MPa])*bw*d   [N, mm],   Vs = Av*fyt*d/s
        N = axial compression (N), passed from the UI/load case (0 if unknown -> warning).
        Code nominal strength is a design (lower-bound) value, so the UI must let the user override or scale it."""
        plan = self.plan_section(sec_name)
        sec = self.sections[sec_name]; r = ReinforcementData.from_dict(sec.get("reinforcement"))
        conc = self._material(sec["mat_name"], "concrete"); tie = self._material(r.tie_bar_material, "tie rebar")
        if sec.get("type") != "rectangular":
            raise ConversionError(f"section '{sec_name}': auto shear derivation implemented for rectangular sections only")
        b, h = sec["b"], sec["h"]
        td = self.dia[r.tie_bar_size]; db = self.dia[r.long_bar_size]
        d = h - r.clear_cover - td - 0.5 * db
        Ag = b * h; fc = float(conc["fy"]) / 1e6
        legs = max(int(r.num_ties_3dir), int(r.num_ties_2dir), 2)
        Av = legs * self.area[r.tie_bar_size]; fyt = float(tie["fy"])
                                                           
        Vc = 0.17 * (1.0 + N / (14.0 * Ag * 1e6)) * math.sqrt(fc) * (b * 1e3) * (d * 1e3)             
        Vs = Av * fyt * d / r.tie_spacing if r.tie_spacing > 0 else 0.0
        if N == 0.0:
            self._warn(f"section '{sec_name}': shear spring auto-Vy assumes N=0; pass axial load N in shear_spring")
        k_unc = plan.G * plan.As2 / L
                                                                                                                                     
        Es = float(tie.get("E", 2.0e11))
        k_cr = min(Av * Es * d / (2.0 * r.tie_spacing * L), k_unc) if r.tie_spacing > 0 else k_unc
        return {"k0": k_unc, "k_cr": k_cr, "Vcr": Vc, "Vy": Vc + Vs, "Vc": Vc, "Vs": Vs}

    def shear_spring_params(self, sec_name, L):
        q = dict(self.shear_spring or {})
        missing = [k for k in self.SHEAR_REQUIRED if k not in q]
        if missing:
            raise ConversionError("shear_spring is missing UI-supplied parameters: " + ", ".join(missing))
        auto = self.derive_shear_spring(sec_name, L, float(q.get("N", 0.0)))
        sk, sv = float(q.get("k0_scale", 1.0)), float(q.get("Vy_scale", 1.0))
        q["k_unc"] = auto["k0"] * sk
        q["k_cr"] = (auto["k_cr"] if q["shear_stiffness"] == "cracked" else auto["k0"]) * sk
        q["Vy"] = auto["Vy"] * sv
        q["Vcr"] = min(auto["Vcr"] * sv, 0.999 * q["Vy"])
        q["_auto"] = auto
        return q

    def build_shear_material(self, sec_name, L):
        """Hysteretic (pinched, symmetric) lateral force-deformation material for the in-series shear/slip spring."""
        key = ("shear", sec_name, round(L, 9))
        if key in self._built:
            return self._built[key]
        q = self.shear_spring_params(sec_name, L)
                                                                                                       
        e1, s1 = q["Vcr"] / q["k_unc"], q["Vcr"]
        e2 = e1 + (q["Vy"] - q["Vcr"]) / q["k_cr"]; s2 = q["Vy"]
        e3 = q["e3_mult"] * e2
        s3 = s2 + q["alpha"] * q["k_cr"] * (e3 - e2)
        tag = self._new("mat")
        self.ops.uniaxialMaterial("Hysteretic", tag, s1, e1, s2, e2, s3, e3, -s1, -e1, -s2, -e2, -s3, -e3,
                                  q["pinchX"], q["pinchY"], q["damage1"], q["damage2"], q["beta"])
        if getattr(self, "_shear_rigid", None) is None:
            self._shear_rigid = self._new("mat")
            self.ops.uniaxialMaterial("Elastic", self._shear_rigid, 1.0e12)
        self._built[key] = tag
        return tag

    def add_shear_spring(self, ele_tag, node_a, node_b, sec_name, L, orient):
        """zeroLength between coincident nodes: pinched Hysteretic in local y and z (shear), rigid in axial and rotations,
        orient as add_slip_spring.  Series with the fibre member -> total drift = flexure + spring."""
        if not self.shear_spring:
            return False
        m = self.build_shear_material(sec_name, L); r = self._shear_rigid
        self.ops.element("zeroLength", ele_tag, node_a, node_b, "-mat", r, m, m, r, r, r,
                         "-dir", 1, 2, 3, 4, 5, 6, "-orient", *orient)
        return True

    def add_element(self, ele_tag, node_i, node_j, transf_tag, sec_name):
        """forceBeamColumn using the fiber section, or False if the section isn't convertible."""
        info = self.build_section(sec_name)
        if info is None:
            return False
        self.ops.element("forceBeamColumn", ele_tag, node_i, node_j, transf_tag, info["int_tag"], "-iter", int(self.fbc_iter[0]), float(self.fbc_iter[1]))
        return True

def main(path):
    import json
    with open(path, "r") as f:
        data = json.load(f)
    b = NonlinearSectionBuilder(data, ops=None)
    for name, sec in b.sections.items():
        if sec.get("reinforcement"):
            print(b.describe(b.plan_section(name)))
    if b.warnings:
        print("\nWarnings:")
        for w in b.warnings:
            print(" -", w)

if __name__ == "__main__":
    import sys
    main(sys.argv[1])
