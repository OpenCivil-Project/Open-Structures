"""
fiber_section.py

Displacement-based fiber section state determination for RC hinges.

Given a trial section deformation (axial strain eps0, curvature kappa2
about local axis 2, curvature kappa3 about local axis 3), returns the
stress resultants (N, M2, M3) and the 3x3 tangent section stiffness,
by summing over a fixed list of fibers (as produced by
hinge_dialog.generate_property_preserving_fibers): each fiber is
{"area", "coord2", "coord3", "material"}.

Axis / sign convention (locked against element_library.get_local_
stiffness_matrix's DOF coupling -- I33 <-> (U2, R3), I22 <-> (U3, R2) --
and the fiber generator's own "coord2 = vertical/axis-2, coord3 =
horizontal/axis-3" convention):

    eps(fiber) = eps0 + kappa2 * coord3 - kappa3 * coord2

(coord2 / coord3 = fiber position along the element's local axes 2 / 3.)
This is the sign that matches hinge_element.py's basic-force convention:
Sm maps q to the INTERNAL moment at the hinge (positive M2 = tension on the
+3 side, positive M3 = tension on the -2 side) and Bv defines the basic
rotations as nodal rotation minus chord rotation (theta2 = -dw/dx,
theta3 = +dv/dx). A beam curving toward +3 therefore shortens its +3 fibers.
FiberSection stores the NEGATED coordinates (self._c2 = -coord2,
self._c3 = -coord3) so every formula below stays in the compact form
eps0 - kappa2*_c3 + kappa3*_c2 with work-conjugate M2/M3 and a symmetric
tangent. Anything reading fs._c2 / fs._c3 gets the stored (negated) values.

Each fiber's material is resolved to a monotonic (strain, stress)
backbone via backbone_lookup()'s material-object dispatch (mirrors
material_dialog.py's NonlinearMaterialDialog call sites exactly -- same
functions, same argument mapping, so this can never silently diverge
from what the hinge-property preview already shows).

No cyclic/hysteretic behavior: this is backbone-only state
determination, correct for monotonic (one-way, e.g. pushover) loading.
Do NOT use this for cyclic/dynamic analysis without adding strain-history
tracking (last-max-strain-reached etc per fiber) first.
"""

import numpy as np
from bisect import bisect_left
from types import SimpleNamespace

def _user_defined_backbone(raw_points):
    """
    NonlinearMaterialData.user_points -> sorted [(strain, stress), ...] (SI).
    Rows are stored as [strain, stress, point_id] (the id is display-only and
    dropped here).  Rows that don't parse are skipped.  Returns None when
    fewer than 2 usable points remain.  Sort is stable on strain only, so a
    deliberate vertical segment (two rows with the same strain) keeps its
    order.
    """
    pts = []
    for p in raw_points or []:
        try:
            pts.append((float(p[0]), float(p[1])))
        except (TypeError, ValueError, IndexError):
            continue
    if len(pts) < 2:
        return None
    pts.sort(key=lambda q: q[0])
    return pts

def get_material_backbone(material, area_lookup=None):
    """
    Mirrors material_dialog.py's NonlinearMaterialDialog.get_points_fn()
    call sites EXACTLY (same functions, same positional args) so this
    can never drift from what the hinge-property preview widget shows.

    material : dict, matching data_manager.py's own convention (dm.raw
               materials are plain dicts read from the exported JSON --
               confirmed against data_manager.py's el['material']['rho']
               style access, NOT dataclass attribute access. An earlier
               draft of this function assumed Material dataclass
               attributes (material.fy etc); fixed to match what
               data_manager.py actually hands elements.
               Expected keys: 'name', 'mat_type', 'E', 'fy', 'fu',
               'nonlinear' (nested dict, or None), matching
               core.properties.Material/NonlinearMaterialData field
               names 1:1 (ASSUMPTION: the JSON export is a straight
               field-name-preserving dict of the dataclasses -- verify
               against a real exported .mf file with a hinge in it; if
               key names differ, only this function needs updating).

    Returns: list of (strain, stress) tuples, sorted ascending by strain,
    tension positive / compression negative (SI base units).

    NOTE ON "fc": the dialog's "fc_si" is nothing but the plain .fy
    field reused positionally as generate_mander_curve's first
    (strength) argument for Concrete-type materials -- Material has no
    separate fc field. This mirrors that exact reuse, confirmed against
    material_dialog.py lines 1803/1814/1824, not guessed.
    """
    nl = material.get('nonlinear')
    if nl is None:
        raise ValueError(
            f"Material '{material.get('name', '?')}' has no nonlinear "
            f"data (nonlinear=None) -- cannot be used as a hinge fiber material."
        )

    if nl.get('curve_mode') == "User Defined":
        user_pts = _user_defined_backbone(nl.get('user_points'))
        if user_pts is not None:
            return user_pts
        print(f"      [!] Warning: material '{material.get('name', '?')}' is set "
              f"to 'User Defined' but has fewer than 2 valid points -- "
              f"falling back to its parametric curve.")

    from mander_model import generate_mander_curve, generate_rebar_curve, generate_steel_curve

    slope = nl['final_slope_mult']
    E = material['E']
                                                                
    mat_type = (material.get('type') or '').lower()

    if mat_type == "rebar":
        pts, _marker = generate_rebar_curve(
            material['fy'], material['fu'], E,
            nl['rebar_eps_sh'], nl['rebar_eps_su'],
            slope, nl['rebar_parametric_model'], n_inter=40
        )
    elif mat_type == "steel":
        pts, _marker = generate_steel_curve(
            material['fy'], material['fu'], E,
            nl['steel_eps_sh'], nl['steel_eps_su'], nl['steel_eps_rupture'],
            slope, n_inter=40
        )
    else:
                                                                      
        mander_dict = nl.get('mander')
        mander_obj = SimpleNamespace(**mander_dict) if mander_dict else None

        pts, _result = generate_mander_curve(
            material['fy'], nl['eps_c0'], nl['eps_cu'], slope, E,
            mander=mander_obj, area_lookup=area_lookup,
            model_choice=nl['parametric_model']
        )

    pts = sorted(pts, key=lambda p: p[0])
    return pts

def backbone_lookup(points, eps):
    """
    Given a sorted (strain, stress) backbone and a trial strain, returns
    (stress, tangent_modulus) via linear interpolation between the two
    bracketing points (tangent = local secant slope of that segment).

    Backbone-only (monotonic envelope) -- no unload/reload branches.
    Strain beyond the table's ends is clamped to the end point's own
    local slope (constant extrapolation of the last segment's tangent),
    rather than raising -- a fiber pushed past the tabulated range should
    degrade gracefully (usually toward the near-zero "final_slope_mult"
    tail already baked into the table) rather than crash the analysis.
    """
    n = len(points)
    if n == 0:
        return 0.0, 0.0
    if n == 1:
        return points[0][1], 0.0

    strains = [p[0] for p in points]

    if eps <= strains[0]:
        return points[0][1], 0.0
    if eps >= strains[-1]:
        return points[-1][1], 0.0

    i = bisect_left(strains, eps)
    if strains[i] == eps:
                                                                        
        j = i if i < n - 1 else i - 1
    else:
        j = i - 1

    s0, f0 = points[j]
    s1, f1 = points[j + 1]
    tangent = (f1 - f0) / (s1 - s0) if s1 != s0 else 0.0
    stress = f0 + tangent * (eps - s0)
    return stress, tangent

EVENT_KINK_TANGENT_RATIO = 0.35

def major_kinks(points, ratio=EVENT_KINK_TANGENT_RATIO):
    """Sorted np.array of strains at which this backbone changes character."""
    n = len(points)
    if n < 2:
        return np.zeros(0)
    s = np.array([p[0] for p in points], dtype=float)
    f = np.array([p[1] for p in points], dtype=float)
    ds = np.diff(s)
    with np.errstate(divide="ignore", invalid="ignore"):
        t = np.where(ds != 0.0, np.diff(f) / np.where(ds != 0.0, ds, 1.0), 0.0)
    tmax = float(np.max(np.abs(t))) if t.size else 0.0
    flat = 1e-3 * tmax
    kinks = [s[0], s[-1]]
    for j in range(1, n - 1):
        ta, tb = t[j - 1], t[j]
        if ds[j - 1] == 0.0 or ds[j] == 0.0:
            kinks.append(s[j])                                             
            continue
        a_flat, b_flat = abs(ta) <= flat, abs(tb) <= flat
        sign_change = (ta > flat and tb < -flat) or (ta < -flat and tb > flat)
        big_jump = abs(tb - ta) > ratio * max(abs(ta), abs(tb))
        if sign_change or (a_flat != b_flat) or (big_jump and not (a_flat and b_flat)):
            kinks.append(s[j])
    return np.unique(np.array(kinks))

class FiberSection:
    """
    Precomputed, ready-to-integrate fiber section: fiber list resolved
    to actual backbone tables once (materials looked up by name), so
    the hot Newton-iteration path (section_state) never re-runs curve
    generation or dict lookups per call.
    """
    def __init__(self, fibers, materials_by_name, area_lookup=None):
        """
        fibers            : list of {"area","coord2","coord3","material"}
                             dicts, e.g. from
                             hinge_dialog.generate_property_preserving_fibers
        materials_by_name : dict name -> core.properties.Material
                             (same object as data_manager.py's
                             self.materials, e.g. dm.materials)
        area_lookup       : rebar-size -> area table, passed straight
                             through to Mander confinement math (same
                             as material_dialog.py's _rebar_area_lookup)
        """
        self._areas = np.array([f["area"] for f in fibers], dtype=float)
                                                                          
        self._c2 = -np.array([f["coord2"] for f in fibers], dtype=float)
        self._c3 = -np.array([f["coord3"] for f in fibers], dtype=float)

        backbone_cache = {}
        self._backbones = []
        bb_ids, bb_id_of_name, kink_list = [], {}, []
        hyst_type_of_name = {}
        for f in fibers:
            mat_name = f["material"]
            if mat_name not in backbone_cache:
                mat_obj = materials_by_name[mat_name]
                backbone_cache[mat_name] = get_material_backbone(mat_obj, area_lookup)
                _nl = mat_obj.get('nonlinear') if isinstance(mat_obj, dict) else getattr(mat_obj, 'nonlinear', None)
                _ht = _nl.get('hysteresis_type') if isinstance(_nl, dict) else getattr(_nl, 'hysteresis_type', None)
                hyst_type_of_name[mat_name] = str(_ht or '')
                bb_id_of_name[mat_name] = len(kink_list)
                kink_list.append(major_kinks(backbone_cache[mat_name]))
            self._backbones.append(backbone_cache[mat_name])
            bb_ids.append(bb_id_of_name[mat_name])

        self.n_fibers = len(fibers)
                                                                                                       
        self.hysteresis_types = [hyst_type_of_name[f["material"]] for f in fibers]
        self.takeda_mask = np.array([h.strip().lower() == 'takeda' for h in self.hysteresis_types], dtype=bool)
        self.hysteresis = None                                                                             
        self._vec_tables = None                                                    
        self._init_events(np.array(bb_ids, dtype=int), kink_list)
        if self.takeda_mask.any():
            self.attach_hysteresis(self.takeda_mask)

    def _init_events(self, bb_ids, kink_list):
        self._bb_id = bb_ids
        self._kinks = kink_list

    def fiber_strains(self, eps0, kappa2, kappa3):
        return eps0 - kappa2 * self._c3 + kappa3 * self._c2

    def event_segments(self, eps_fiber):
        """Per-fiber index of the event-kink interval the strain lies in.
        Two states with different arrays have crossed at least one kink."""
        seg = np.zeros(self.n_fibers, dtype=np.int64)
        for b, kinks in enumerate(self._kinks):
            m = self._bb_id == b
            if np.any(m):
                seg[m] = np.searchsorted(kinks, eps_fiber[m], side="right")
        return seg

    def first_crossing(self, i, seg_a, seg_b):
        """Strain of the first event kink fiber i meets going from
        interval seg_a to seg_b."""
        kinks = self._kinks[self._bb_id[i]]
        if seg_b > seg_a:
            return float(kinks[seg_a])                                      
        return float(kinks[seg_a - 1])                                      

    def _build_vec_tables(self):
        tables = []
        for b in range(len(self._kinks)):
            idx = np.nonzero(self._bb_id == b)[0]
            if idx.size == 0:
                continue
            pts = self._backbones[int(idx[0])]
            n = len(pts)
            s = np.array([p[0] for p in pts], dtype=float)
            f = np.array([p[1] for p in pts], dtype=float)
            tan = None
            if n >= 2:
                ds = s[1:] - s[:-1]
                nz = ds != 0.0
                tan = np.where(nz, (f[1:] - f[:-1]) / np.where(nz, ds, 1.0), 0.0)
                                                                          
                tw = (f[0] - f[-1]) / (s[0] - s[-1]) if s[0] != s[-1] else 0.0
                tan = np.concatenate([tan, [tw]])
            tables.append((idx, n, s, f, tan))
        return tables

    def _lookup_all(self, eps_fiber):
        """(stress, tangent) arrays for every fiber, == looping backbone_lookup."""
        vt = getattr(self, '_vec_tables', None)
        if vt is None:
            vt = self._vec_tables = self._build_vec_tables()
        stress = np.empty(self.n_fibers)
        tangent = np.empty(self.n_fibers)
        with np.errstate(invalid='ignore', over='ignore'):
            for idx, n, s, f, tan in vt:
                if n == 0:
                    stress[idx] = 0.0
                    tangent[idx] = 0.0
                    continue
                if n == 1:
                    stress[idx] = f[0]
                    tangent[idx] = 0.0
                    continue
                e = eps_fiber[idx]
                i = np.searchsorted(s, e, side='left')                          
                ic = np.minimum(i, n - 1)
                j = np.where(s[ic] == e, ic, i - 1)
                                                                                 
                tg = tan[j]
                sg = f[j] + tg * (e - s[j])
                hi = e >= s[-1]
                sg[hi] = f[-1]
                tg[hi] = 0.0
                lo = e <= s[0]                                                                 
                sg[lo] = f[0]
                tg[lo] = 0.0
                stress[idx] = sg
                tangent[idx] = tg
        return stress, tangent

    def attach_hysteresis(self, hysteretic=None):
        """Attach the cyclic hysteresis law (fiber_hysteresis.py) for this section's fibers.
        hysteretic: bool mask of fibers that follow it (default: the Takeda-material fibers).
        Nothing changes until the solver gives the hinge a mat_state."""
        from fiber_hysteresis import FiberHysteresis
        if hysteretic is None:
            hysteretic = self.takeda_mask
        self.hysteresis = FiberHysteresis.from_fiber_section(self, hysteretic=hysteretic)
        return self.hysteresis

    def resultants_from_stress(self, stress):
        """(N, M2, M3) for given per-fiber stresses (shape (..., n_fibers)); the same sums as
        state(), so a viewer can rebuild section forces from the solver's own (history-dependent)
        fiber stresses instead of the backbone."""
        s = np.asarray(stress, dtype=float)
        a = self._areas
        return (a * s).sum(-1), -(a * s * self._c3).sum(-1), (a * s * self._c2).sum(-1)

    def fiber_tangents(self, eps0, kappa2, kappa3, mat_state=None):
        """Per-fiber (strain, stress, tangent) arrays at section deformation d,
        on the raw backbones (no failure mask applied). With mat_state (the
        committed hysteresis state) and hysteresis attached, stress/tangent
        follow the hysteresis rule instead of the backbone."""
        eps = self.fiber_strains(eps0, kappa2, kappa3)
        if mat_state is not None and self.hysteresis is not None:
            sig, tan, _ = self.hysteresis.evaluate(eps, mat_state)
        else:
            sig, tan = self._lookup_all(eps)
        return eps, sig, tan

    def state(self, eps0, kappa2, kappa3, failed=None, mat_state=None):
        """
        Returns (N, M2, M3, K_section) where K_section is the 3x3
        tangent [[dN/deps0, dN/dk2, dN/dk3],
                 [dM2/deps0, dM2/dk2, dM2/dk3],
                 [dM3/deps0, dM3/dk2, dM3/dk3]]
        (symmetric by construction -- each entry built from the same
        per-fiber sums, no independent derivation to drift out of sync).

        Sign convention: eps(fiber) = eps0 + kappa2*coord3 - kappa3*coord2,
        implemented as eps0 - kappa2*_c3 + kappa3*_c2 on the stored negated
        coordinates (see module docstring).
        """
        eps_fiber = (eps0
                     - kappa2 * self._c3
                     + kappa3 * self._c2)

        if mat_state is not None and self.hysteresis is not None:
                                                                                   
            stress, tangent, _ = self.hysteresis.evaluate(eps_fiber, mat_state)
        else:
            stress, tangent = self._lookup_all(eps_fiber)
        if failed is not None:
                                                                          
            stress[failed] = 0.0
            tangent[failed] = 0.0

        a = self._areas
        c2 = self._c2
        c3 = self._c3

        N = (a * stress).sum()
        M2 = (a * stress * c3).sum() * -1.0                                                            
        M3 = (a * stress * c2).sum()

        at = a * tangent
        K_ee = at.sum()                                   
        K_ek2 = -(at * c3).sum()                                                 
        K_ek3 = (at * c2).sum()                                      
        K_k2k2 = (at * c3 * c3).sum()                                                     
        K_k2k3 = -(at * c2 * c3).sum()
        K_k3k3 = (at * c2 * c2).sum()

        K_section = np.array([
            [K_ee,   K_ek2,  K_ek3],
            [K_ek2,  K_k2k2, K_k2k3],
            [K_ek3,  K_k2k3, K_k3k3],
        ])

        return N, M2, M3, K_section
