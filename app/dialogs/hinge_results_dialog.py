"""
hinge_results_dialog.py

Analyze > Show Hinge Results...

Inspect fiber-hinge results of a Nonlinear Static case: for any assigned
hinge, the moment-rotation response, and for any single fiber inside it, the
stress-strain response against that fiber's material backbone (zoom to the
reached range, or zoom out to the full curve).

Display conventions
  * M2 / M3 are labels. hinge_loader rotates the fibers 90 deg into the
    solver's element frame, so M3 is the solver's M2 (kappa2) and vice
    versa. The swap is applied here, in one place (_HingeContext._sdof).
  * DISPLAY_SIGN flips moment AND rotation of an axis together so the
    moment-rotation curve lands in the correct quadrant.
  * The fiber map is drawn like the Hinge Property dialog's preview: section
    outline, tie box, rebars, fibers at (coord3 horizontal, coord2 vertical).

DATA CONTRACT (what the solver must write -- not implemented yet)
-----------------------------------------------------------------
In the case's *_results.json, every entry of "saved_states" (and/or, for a
run that saves only the final state, a top-level "hinge_states" key) carries:

    "hinge_states": {
        "<element_id>": {
            "d":  [eps0, kappa2, kappa3],   # section deformation at the hinge
            "Lh": 0.35                       # OPTIONAL hinge length (m)
        },
        ...
    }

`d` is exactly what hinge_element.compute_hinge_element(..., return_info=True)
already returns as info['d']. Everything else is rebuilt HERE from the model:
fiber strain = eps0 - kappa2*c3 + kappa3*c2, fiber stress from the material
backbone (fiber_section.backbone_lookup), hinge moment from the section
state, hinge rotation = curvature * hinge length. If "Lh" is missing the
length is estimated from the model (relative lengths use the full element
length, NOT the clear length -- write "Lh" from the solver to be exact).

The dialog is a pure reader: it never re-runs or modifies the analysis.

"""

import json
import os

import numpy as np
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox, QLabel,
    QComboBox, QPushButton, QLineEdit, QMenuBar, QMessageBox, QSizePolicy,
    QSpinBox, QSlider, QCheckBox, QRadioButton, QTabWidget, QTableWidget,
    QTableWidgetItem, QAbstractItemView, QHeaderView, QWidget, QFileDialog,
    QApplication,
)

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import Polygon, Circle

from app.ui.theme import (apply_dialog_style, style_plot_axes, PlotNavigator, COLORS,
                          current_theme, on_theme_changed, off_theme_changed,
                          section_map_palette)
from app.dialogs.pushover_curve_dialog import UNIT_DEFS

STATE_ORDER = ["A to <=B", "B to <=C", "C to <=D", "D to <=E", ">E"]
STATE_COLORS = {
    "A to <=B":   "#2e9e4f",           
    "B to <=C":   "#e6a700",                       
    "C to <=D":   "#e0662a",                  
    "D to <=E":   "#c0392b",                       
    ">E":         "#7a1f1f",          
}
MATERIAL_COLORS = ["#1f77b4", "#d62728", "#2ca02c", "#9467bd", "#ff7f0e",
                   "#17becf", "#8c564b", "#e377c2"]
BACKBONE_COLOR = "#c0392b"
SUBSTEPS = 8                                                                      
                                                                                
DISPLAY_SIGN = {"M3": -1.0, "M2": 1.0}

def _dense_path(ds):
    """Vectorised version of the old per-step interpolation: origin, then
    SUBSTEPS points towards every saved step. Row (k + 1) * SUBSTEPS is saved
    step k."""
    seq = np.vstack([np.zeros(3)] + [np.asarray(d, float) for d in ds])
    t = np.arange(1, SUBSTEPS + 1) / SUBSTEPS
    seg = seq[:-1, None, :] + (seq[1:, None, :] - seq[:-1, None, :]) * t[None, :, None]
    return np.vstack([seq[:1], seg.reshape(-1, 3)])

def _side_info(points, sign):
    """
    (eps_first_deviation, eps_peak, eps_end) magnitudes for one side of a
    backbone (sign=+1 tension, -1 compression), walking out from the origin.
    """
    pts = [(0.0, 0.0)] + [(e, s) for e, s in points if sign * e > 1e-15]
    pts.sort(key=lambda p: sign * p[0])
    if len(pts) < 2:
        return 0.0, 0.0, 0.0
    e_end = abs(pts[-1][0])
    e0, s0 = pts[0]
    e1, s1 = pts[1]
    E0 = abs((s1 - s0) / (e1 - e0)) if e1 != e0 else 0.0
    e_dev = e_end
    if E0 > 0.0:
        for (ea, sa), (eb, sb) in zip(pts[:-1], pts[1:]):
            slope = abs((sb - sa) / (eb - ea)) if eb != ea else 0.0
            if slope < 0.9 * E0 or (sb - sa) * (s1 - s0) < 0.0:
                e_dev = abs(ea)
                break
    peak_i = int(np.argmax([abs(p[1]) for p in pts]))
    e_peak = abs(pts[peak_i][0])
    return e_dev, e_peak, e_end

def _classify(eps, info):
    """Maps fiber strain to compatible ABCDE states."""
    a = abs(eps)
    e_dev, e_peak, e_end = info
    
    if a <= e_dev * (1.0 + 1e-9):
        return "A to <=B"
    if a <= e_peak * (1.0 + 1e-9):
        return "B to <=C"
        
    if e_end <= e_peak * (1.0 + 1e-9):
        return ">E"
        
    e_D = e_peak + 0.5 * (e_end - e_peak)
    
    if a <= e_D * (1.0 + 1e-9):
        return "C to <=D"
    if a <= e_end * (1.0 + 1e-9):
        return "D to <=E"
        
    return ">E"

class _HingeContext:
    def __init__(self, assign, prop_name, prop, fs, fibers_def, lh_model, backbone_lookup,
                 swap_axes=False, section=None, rebars=None):
        self.key = str(assign.element_id)                                               
        self.element_id = assign.element_id
        self.prop_name = prop_name
        self.rel_dist = float(assign.rel_dist)
        self.lh_model = lh_model
        self.lh_raw = float(prop.hinge_length)
        self.lh_relative = bool(getattr(prop, "hinge_length_relative", True))
        self.swap_axes = swap_axes                                             
        self.section = section                                                           
        self.rebars = rebars or []                                                   
        self.has_reinf = bool(self.rebars) or (
            getattr(section, "reinforcement", None) is not None and getattr(section, "b", None) is not None)
        self.fs = fs
        self.fibers_def = fibers_def                                                           
        self.n = fs.n_fibers
        self.c2, self.c3, self.area = fs._c2, fs._c3, fs._areas
        self.backbones = fs._backbones
        self.materials = [f["material"] for f in fibers_def]
        self._lookup = backbone_lookup
        self._info_cache = {}
        self._infos = [(self._info(bb, +1), self._info(bb, -1)) for bb in self.backbones]
                                                                                      
        self._st_info = np.array([[list(s) for s in pair] for pair in self._infos], dtype=float)
        self._rows = np.arange(len(self._infos))

    def _info(self, bb, sign):
        k = (id(bb), sign)
        if k not in self._info_cache:
            self._info_cache[k] = _side_info(bb, sign)
        return self._info_cache[k]

    def fiber_strains(self, d):
        return d[0] - d[1] * self.c3 + d[2] * self.c2

    def fiber_stress_at(self, i, eps):
        return self._lookup(self.backbones[i], eps)[0]

    def fiber_state_at(self, i, eps):
        return _classify(eps, self._infos[i][0 if eps >= 0 else 1])

    def evaluate(self, d):
        eps = self.fiber_strains(d)
        sig = np.array([self.fiber_stress_at(i, e) for i, e in enumerate(eps)])
        states = [self.fiber_state_at(i, e) for i, e in enumerate(eps)]
        return eps, sig, states

    def state_indices(self, eps):
        """Vectorised _classify: index into STATE_ORDER for every fiber."""
        eps = np.asarray(eps, float)
        info = self._st_info[self._rows, (eps < 0).astype(int)]
        dev, peak, end = info[..., 0], info[..., 1], info[..., 2]                             
        a = np.abs(eps)
        k = 1.0 + 1e-9
        e_D = peak + 0.5 * (end - peak)
        return np.select(
            [a <= dev * k, a <= peak * k, end <= peak * k, a <= e_D * k, a <= end * k],
            [0, 1, 4, 2, 3], default=4)

    def worst_state(self, d):
        return STATE_ORDER[int(self.state_indices(self.fiber_strains(d)).max())]

    def worst_state_indices(self, ds):
        """Most critical fiber state (index into STATE_ORDER) for EVERY saved
        step at once. ds: (S, 3) section deformations -> (S,) ints."""
        ds = np.asarray(ds, float)
        eps = ds[:, 0:1] - ds[:, 1:2] * self.c3[None, :] + ds[:, 2:3] * self.c2[None, :]
        return self.state_indices(eps).max(axis=1)

    def _sdof(self, dof):
        """Label -> the solver's bending axis (swapped when fibers were rotated)."""
        if self.swap_axes:
            return "M2" if dof == "M3" else "M3"
        return dof

    def curv_col(self, dof):
        """Column of d = [eps0, kappa2, kappa3] holding this axis' curvature."""
        return 2 if self._sdof(dof) == "M3" else 1

    @staticmethod
    def sign(dof):
        return DISPLAY_SIGN.get(dof, 1.0)

    def moment(self, d, dof):
        st = self.fs.state(d[0], d[1], d[2])
        return self.sign(dof) * (st[2] if self._sdof(dof) == "M3" else st[1]) + 0.0                  

    def moment_from_sigma(self, sig, dof):
        """Moment from the solver's own fiber stresses (history-dependent). sig: (..., n_fibers)."""
        _N, M2, M3 = self.fs.resultants_from_stress(sig)
        return self.sign(dof) * (M3 if self._sdof(dof) == "M3" else M2) + 0.0

    def curvature(self, d, dof):
        return self.sign(dof) * d[self.curv_col(dof)] + 0.0

    def lever_arm(self, dof):
        """Largest fiber distance that gives moment about this bending axis."""
        return float(np.abs(self.c2 if self._sdof(dof) == "M3" else self.c3).max())

    def k_max(self, dof):
        emax = max(max(abs(p[0]) for p in bb) for bb in self.backbones)
        lever = self.lever_arm(dof)
        if lever < 1e-6:
            lever = max(np.abs(self.c2).max(), np.abs(self.c3).max(), 1e-9)
        return emax / lever

    def hinge_path(self, ds, dof):
        """Dense (curvature, moment) trace through the saved steps (origin first).
        Returns k, M and, per saved step, the index of its point in k/M."""
        seq = [np.zeros(3)] + [np.asarray(d, float) for d in ds]
        dense, idx = [seq[0]], [0]
        for a, b in zip(seq[:-1], seq[1:]):
            for t in range(1, SUBSTEPS + 1):
                dense.append(a + (b - a) * t / SUBSTEPS)
            idx.append(len(dense) - 1)
        ks = np.array([self.curvature(d, dof) for d in dense])
        ms = np.array([self.moment(d, dof) for d in dense])
        return ks, ms, idx

    def fiber_path(self, i, ds):
        seq = [np.zeros(3)] + [np.asarray(d, float) for d in ds]
        eps_l, sig_l = [0.0], [0.0]
        for a, b in zip(seq[:-1], seq[1:]):
            for t in range(1, SUBSTEPS + 1):
                d = a + (b - a) * t / SUBSTEPS
                e = d[0] - d[1] * self.c3[i] + d[2] * self.c2[i]
                eps_l.append(e)
                sig_l.append(self.fiber_stress_at(i, e))
        return np.array(eps_l), np.array(sig_l)

def _material_to_dict(mat):
    """Same record shape model.save() writes (and hinge_loader consumes)."""
    nl = getattr(mat, "nonlinear", None)
    return {
        "name": mat.name, "E": mat.E, "G": mat.G, "type": mat.mat_type,
        "fy": mat.fy, "fu": mat.fu,
        "nonlinear": nl.to_dict() if nl else None,
    }

def _element_length(model, element_id):
    els = getattr(model, "elements", {})
    el = els.get(element_id, els.get(str(element_id)))
    try:
        return float(el.length()) if el is not None else None
    except Exception:
        return None

def _resolve_section(model, element_id):
    """The frame element's Section object (for the outline), or None."""
    els = getattr(model, "elements", {})
    el = els.get(element_id, els.get(str(element_id)))
    if el is None:
        return None
    secs = getattr(model, "sections", {}) or {}
    for attr in ("sec_name", "section_name", "section"):
        v = getattr(el, attr, None)
        if v is None:
            continue
        if hasattr(v, "get_shape_coords"):
            return v
        if isinstance(v, str) and v in secs:
            return secs[v]
    return None

def _build_contexts(model):
    """Returns (contexts, warnings). Skips hinges it cannot build, with a reason."""
    from fiber_section import FiberSection, backbone_lookup
    from hinge_loader import FIBER_COORDS_ARE_SAP_LOCAL_AXES

    try:
        from core.properties import compute_rebar_positions
    except Exception:
        compute_rebar_positions = None

    warnings, contexts = [], []
    area_lookup = {r["id"]: r["area"] for r in getattr(model, "rebar_sizes", [])}
    fs_cache = {}

    for assign in getattr(model, "frame_hinges", {}).values():
        name = assign.hinge_name
        prop = model.hinge_properties.get(name)
        if prop is None:
            warnings.append(f"Frame {assign.element_id}: hinge property '{name}' not found.")
            continue
        fibers = list(getattr(prop, "fibers", None) or [])
        if not fibers:
            warnings.append(f"Frame {assign.element_id}: hinge '{name}' has no calculated fibers.")
            continue
        if name not in fs_cache:
            try:
                solver_fibers = fibers
                if FIBER_COORDS_ARE_SAP_LOCAL_AXES:
                    solver_fibers = [dict(f, coord2=-f["coord3"], coord3=f["coord2"]) for f in fibers]
                used = {f["material"] for f in fibers}
                mats = {m: _material_to_dict(model.materials[m]) for m in used}
                fs_cache[name] = FiberSection(solver_fibers, mats, area_lookup=area_lookup)
            except Exception as e:
                fs_cache[name] = None
                warnings.append(f"Hinge '{name}': cannot build fiber section ({e}).")
        fs = fs_cache[name]
        if fs is None:
            continue
        lh = float(prop.hinge_length)
        if getattr(prop, "hinge_length_relative", True):
            L = _element_length(model, assign.element_id)
            lh = lh * L if L else None
        section = _resolve_section(model, assign.element_id)
        rebars = []
        if section is not None and compute_rebar_positions is not None:
            try:
                rebars = compute_rebar_positions(section, getattr(model, "rebar_sizes", []))
            except Exception:
                rebars = []
        contexts.append(_HingeContext(assign, name, prop, fs, fibers, lh, backbone_lookup,
                                      swap_axes=bool(FIBER_COORDS_ARE_SAP_LOCAL_AXES),
                                      section=section, rebars=rebars))

    contexts.sort(key=lambda c: (str(c.element_id).zfill(8), c.rel_dist))
    return contexts, warnings

def _parse_hinge_states(hs, lh_out):
    d_by_eid = {}
    for eid, rec in (hs or {}).items():
        d = rec.get("d")
        if d is None or len(d) < 3:
            continue
        d_by_eid[str(eid)] = np.array(d[:3], dtype=float)
        if rec.get("Lh") is not None:
            lh_out[str(eid)] = float(rec["Lh"])
    return d_by_eid

def _parse_fiber_stress(hs):
    """{eid: stress array} of the solver's own fiber stresses ("fiber_stress", written when cyclic
    hysteresis is active -- stress then depends on load history and cannot be rebuilt from d)."""
    out = {}
    for eid, rec in (hs or {}).items():
        s = rec.get("fiber_stress")
        if s is not None:
            out[str(eid)] = np.array(s, dtype=float)
    return out

def _load_case(path, case_name):
    """Returns {'case_name','steps','lh'} for a Nonlinear Static result
    (steps is [] if it carries no hinge_states), else None."""
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r") as f:
            data = json.load(f)
    except Exception:
        return None
    if data.get("status") != "SUCCESS":
        return None
    if data.get("info", {}).get("type") != "Nonlinear Static":
        return None

    lh, steps = {}, []
    for k, st in enumerate(data.get("saved_states") or []):
        d = _parse_hinge_states(st.get("hinge_states"), lh)
        if d:
            steps.append({"step": st.get("step", k), "d": d,
                          "sig": _parse_fiber_stress(st.get("hinge_states"))})
    if not steps and data.get("hinge_states"):
        d = _parse_hinge_states(data["hinge_states"], lh)
        if d:
            steps.append({"step": 0, "d": d, "sig": _parse_fiber_stress(data["hinge_states"])})
    steps.sort(key=lambda s: s["step"])
    return {"case_name": case_name, "steps": steps, "lh": lh}

def compute_hinge_state_history(model, saved_states):
    """
    {element_id (str): int8 array (n_steps,)} of the most critical fiber state
    (index into STATE_ORDER) of each fiber hinge at every saved step. The
    index of a step here is the index in `saved_states`, i.e. the same index
    the viewport playback uses. A step that lacks a hinge holds its last known
    state (same rule as the dialog). Raises ImportError if the solver modules
    are unavailable -- callers should treat that as "no colouring".
    """
    contexts, _warn = _build_contexts(model)
    n = len(saved_states)
    out = {}
    for ctx in contexts:
        ds = np.zeros((n, 3))
        last = np.zeros(3)
        for k, st in enumerate(saved_states):
            rec = (st.get("hinge_states") or {}).get(ctx.key)
            if rec is not None and rec.get("d") is not None and len(rec["d"]) >= 3:
                last = np.array(rec["d"][:3], dtype=float)
            ds[k] = last
        out[ctx.key] = ctx.worst_state_indices(ds).astype(np.int8)
    return out

def _demo_case(contexts, n_steps=40):
    """Synthetic monotonic ramp for UI testing only (clearly labelled in the UI)."""
    steps = []
    for j in range(n_steps + 1):
        t = j / n_steps
        d = {}
        for n, c in enumerate(contexts):
            sign = 1.0 if n % 2 == 0 else -1.0
            k3 = sign * t * 0.7 * c.k_max("M3") * (0.6 + 0.4 * ((n % 3) / 2.0))
            dd = np.zeros(3)
            dd[c.curv_col("M3")] = k3
            d[c.key] = dd
        steps.append({"step": j, "d": d})
    return {"case_name": "DEMO (synthetic data)", "steps": steps, "lh": {}}

def _style_axes(fig, ax):
    style_plot_axes(fig, ax)                                                                   

def _limits(full_lo, full_hi, path_vals, full):
    span_full = max(full_hi - full_lo, 1e-12)
    if full:
        pad = 0.05 * span_full
        return full_lo - pad, full_hi + pad
    lo = min(float(np.min(path_vals)), 0.0)
    hi = max(float(np.max(path_vals)), 0.0)
    span = max(hi - lo, 0.04 * span_full)
    pad = 0.15 * span
    return lo - pad, hi + pad

def _readonly(width=110):
    e = QLineEdit()
    e.setReadOnly(True)
    e.setFixedWidth(width)
    return e

class HingeResultsDialog(QDialog):
    """
    status: 'ok'               -> ready to show
            'no_hinges'        -> the model has no usable fiber hinges
            'no_hinge_results' -> cases exist but none carries hinge_states
                                  (call use_demo_data() to preview the UI)
    """

    def __init__(self, parent, model, base_name, case_paths, selected_element_ids=None,
                 animation_manager=None):
        super().__init__(parent)
        self.setWindowTitle("Hinge Results")
        self.resize(1040, 720)
        apply_dialog_style(self)

        self.main_window = parent
        self.model = model
        self.base_name = base_name
        self._selected_ids = {str(i) for i in (selected_element_ids or [])}
        self._cases = {}
        self._pending_case_names = []
        self._hpath_cache = {}
        self._ui_built = False
        self._syncing = False
                                                                               
        self.animation_manager = animation_manager
        self._scrub_connected = False
        self._from_external = False
                                                                     
        self._tracks = {}
        self._h_key = self._f_key = self._s_key = None
        self._h_art = self._f_art = self._s_art = None
        self._h_rng = self._f_rng = None
        self._s_present = None
        self._dirty = [True, True]

        try:
            self._contexts, self.build_warnings = _build_contexts(model)
        except ImportError as e:
            self._contexts = []
            self.build_warnings = [f"Solver modules not importable ({e})."]

        if not self._contexts:
            self.status = "no_hinges"
            return

        for name, path in case_paths.items():
            c = _load_case(path, name)
            if c is None:
                continue
            if c["steps"]:
                self._cases[name] = c
            else:
                self._pending_case_names.append(name)

        if self._cases:
            self.status = "ok"
            self._build_ui()
        elif self._pending_case_names:
            self.status = "no_hinge_results"
        else:
            self.status = "no_hinge_results"

    def use_demo_data(self):
        self._cases = {"DEMO (synthetic data)": _demo_case(self._contexts)}
        self.status = "ok"
        self.setWindowTitle("Hinge Results  --  DEMO DATA (not analysis results)")
        self._build_ui()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 4, 6, 6)

        menubar = QMenuBar(self)
        file_menu = menubar.addMenu("File")
        file_menu.addAction("Export Hinge History to CSV...").triggered.connect(self._on_export_csv)
        file_menu.addSeparator()
        file_menu.addAction("Close").triggered.connect(self.reject)
        outer.setMenuBar(menubar)

        top = QHBoxLayout()

        hbox = QGroupBox("Hinge")
        hl = QGridLayout(hbox)
        self.combo_hinge = QComboBox()
        hl.addWidget(self.combo_hinge, 0, 0, 1, 2)
        self.chk_selected_only = QCheckBox("Only hinges on selected frames")
        self.chk_selected_only.setEnabled(bool(self._selected_ids))
        hl.addWidget(self.chk_selected_only, 1, 0, 1, 2)
        self.lbl_frame, self.lbl_pos, self.lbl_len, self.lbl_prop = (_readonly(), _readonly(),
                                                                      _readonly(), _readonly())
        for r, (t, w) in enumerate([("Frame", self.lbl_frame), ("Position (rel.)", self.lbl_pos),
                                    ("Hinge length", self.lbl_len), ("Property", self.lbl_prop)], start=2):
            hl.addWidget(QLabel(t), r, 0)
            hl.addWidget(w, r, 1)
        self.lbl_len.setFixedWidth(160)
        top.addWidget(hbox, stretch=2)

        cbox = QGroupBox("Load Case / Step")
        cl = QGridLayout(cbox)
        self.combo_case = QComboBox()
        self.combo_case.addItems(sorted(self._cases.keys()))
        cl.addWidget(self.combo_case, 0, 0, 1, 3)
        self.slider_step = QSlider(Qt.Orientation.Horizontal)
        self.spin_step = QSpinBox()
        cl.addWidget(QLabel("Step"), 1, 0)
        cl.addWidget(self.slider_step, 1, 1)
        cl.addWidget(self.spin_step, 1, 2)
        self.lbl_step = QLabel("")
        cl.addWidget(self.lbl_step, 2, 0, 1, 2)
        self.chk_sync_view = QCheckBox("Sync with 3D View")
        self.chk_sync_view.setToolTip("Switch the 3D viewport to this load case's deformed shape and sync the step scrubber.")
        cl.addWidget(self.chk_sync_view, 2, 2)
        top.addWidget(cbox, stretch=2)

        ubox = QGroupBox("Units")
        ul = QVBoxLayout(ubox)
        self.combo_units = QComboBox()
        self.combo_units.addItems(list(UNIT_DEFS.keys()))
        self.combo_units.setCurrentText("kN, m, C")
        ul.addWidget(self.combo_units)
        ul.addStretch(1)
        top.addWidget(ubox, stretch=1)
        outer.addLayout(top)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_hinge_tab(), "Hinge Response")
        self.tabs.addTab(self._build_fiber_tab(), "Fiber Response")
        outer.addWidget(self.tabs, stretch=1)

        row = QHBoxLayout()
        row.addStretch(1)
        btn = QPushButton("Close")
        btn.setObjectName("secondary")
        btn.clicked.connect(self.accept)
        row.addWidget(btn)
        outer.addLayout(row)

        self.combo_hinge.currentIndexChanged.connect(self._on_hinge_changed)
        self.chk_selected_only.toggled.connect(self._populate_hinges)
        self.combo_case.currentIndexChanged.connect(self._on_case_changed)
        self.combo_units.currentIndexChanged.connect(self._refresh_all)
        self.slider_step.valueChanged.connect(self._on_step_widget)
        self.spin_step.valueChanged.connect(self._on_step_widget)
        self.chk_sync_view.toggled.connect(self._on_sync_view_toggled)
        self.tabs.currentChanged.connect(self._on_tab_changed)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(12)
        self._timer.timeout.connect(self._flush)
        self._relayout_timer = QTimer(self)
        self._relayout_timer.setSingleShot(True)
        self._relayout_timer.setInterval(120)
        self._relayout_timer.timeout.connect(self._relayout_all)
        for cv in (self.h_canvas, self.f_canvas, self.s_canvas):
            cv.mpl_connect("resize_event", lambda ev: self._relayout_timer.start())

        self._ui_built = True
        self._populate_hinges()
        self._on_case_changed()
        self.chk_sync_view.blockSignals(True)
        self.chk_sync_view.setChecked(self._scrub_sync_ok())
        self.chk_sync_view.blockSignals(False)
        self._timer.stop()
        self._flush()
        self._connect_scrubber()
        on_theme_changed(self._on_theme_changed)

    def _on_theme_changed(self, _name):
        """Light/Dark switched while this dialog is open: restyle the widgets
        and force every plot (incl. the section map) to rebuild."""
        apply_dialog_style(self)
        self._h_key = self._f_key = self._s_key = None
        self._s_present = None
        self._refresh_all()

    def _build_hinge_tab(self):
        w = QWidget()
        lay = QHBoxLayout(w)
        left = QVBoxLayout()
        self.h_fig = Figure(figsize=(5, 4))
        self.h_canvas = FigureCanvas(self.h_fig)
        self.h_canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.h_ax = self.h_fig.add_subplot(111)
        _style_axes(self.h_fig, self.h_ax)
        self.h_nav = PlotNavigator(self.h_canvas, self.h_ax)
        self.h_canvas.setToolTip("Mouse wheel: zoom   |   Drag: pan   |   Double-click: reset view")
        self.h_canvas.mpl_connect("motion_notify_event", lambda ev: self._mouse(ev, self.h_horiz, self.h_vert))
        left.addWidget(self.h_canvas, stretch=1)
        mrow = QHBoxLayout()
        mrow.addWidget(QLabel("Pointer"))
        self.h_horiz, self.h_vert = _readonly(90), _readonly(90)
        mrow.addWidget(QLabel("x"))
        mrow.addWidget(self.h_horiz)
        mrow.addWidget(QLabel("y"))
        mrow.addWidget(self.h_vert)
        mrow.addStretch(1)
        left.addLayout(mrow)
        lay.addLayout(left, stretch=4)

        side = QGroupBox("Current Hinge Data")
        sl = QGridLayout(side)
        self.combo_dof = QComboBox()
        self.combo_dof.addItems(["M3", "M2"])
        self.combo_dof.currentIndexChanged.connect(self._refresh_all)
        sl.addWidget(QLabel("Bending"), 0, 0)
        sl.addWidget(self.combo_dof, 0, 1)
        self.h_fields = {}
        for r, name in enumerate(["Moment", "Rotation", "Rotation max", "Rotation min", "State"], start=1):
            sl.addWidget(QLabel(name), r, 0)
            self.h_fields[name] = _readonly()
            sl.addWidget(self.h_fields[name], r, 1)
        sl.setRowStretch(6, 1)
        side.setFixedWidth(240)
        lay.addWidget(side)
        return w

    def _build_fiber_tab(self):
        w = QWidget()
        lay = QHBoxLayout(w)

        left = QVBoxLayout()
        self.f_table = QTableWidget(0, 5)
        self.f_table.setHorizontalHeaderLabels(["#", "Material", "Coord 2", "Coord 3", "Area"])
        self.f_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.f_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.f_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.f_table.verticalHeader().setVisible(False)
        self.f_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.f_table.itemSelectionChanged.connect(self._on_fiber_table_selected)
        left.addWidget(self.f_table, stretch=2)

        self.s_fig = Figure(figsize=(3, 3))
        self.s_canvas = FigureCanvas(self.s_fig)
        self.s_canvas.setMinimumHeight(200)
        self.s_ax = self.s_fig.add_subplot(111)
        _style_axes(self.s_fig, self.s_ax)
        self.s_nav = PlotNavigator(self.s_canvas, self.s_ax, pan_buttons=(2, 3))
        self.s_canvas.setToolTip("Left-click: pick a fiber   |   Mouse wheel: zoom   |   "
                                 "Right/middle-drag: pan   |   Double-click: reset view")
        self.s_canvas.mpl_connect("button_press_event", self._on_section_click)
        left.addWidget(self.s_canvas, stretch=3)
        crow = QHBoxLayout()
        crow.addWidget(QLabel("Color by"))
        self.rad_mat = QRadioButton("Material")
        self.rad_state = QRadioButton("State")
        self.rad_state.setChecked(True)
        self.rad_mat.toggled.connect(self._refresh_all)
        crow.addWidget(self.rad_mat)
        crow.addWidget(self.rad_state)
        crow.addStretch(1)
        left.addLayout(crow)
        self.chk_hide_reinf = QCheckBox("Hide reinforcement / confinement (fibers only)")
        self.chk_hide_reinf.setEnabled(False)                                                    
        self.chk_hide_reinf.toggled.connect(self._refresh_all)
        left.addWidget(self.chk_hide_reinf)
        lay.addLayout(left, stretch=3)

        mid = QVBoxLayout()
        self.f_fig = Figure(figsize=(5, 4))
        self.f_canvas = FigureCanvas(self.f_fig)
        self.f_canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.f_ax = self.f_fig.add_subplot(111)
        _style_axes(self.f_fig, self.f_ax)
        self.f_nav = PlotNavigator(self.f_canvas, self.f_ax)
        self.f_canvas.setToolTip("Mouse wheel: zoom   |   Drag: pan   |   Double-click: reset view")
        self.f_canvas.mpl_connect("motion_notify_event", lambda ev: self._mouse(ev, self.f_horiz, self.f_vert))
        mid.addWidget(self.f_canvas, stretch=1)
        mrow = QHBoxLayout()
        mrow.addWidget(QLabel("Pointer"))
        self.f_horiz, self.f_vert = _readonly(90), _readonly(90)
        mrow.addWidget(QLabel("x"))
        mrow.addWidget(self.f_horiz)
        mrow.addWidget(QLabel("y"))
        mrow.addWidget(self.f_vert)
        mrow.addStretch(1)
        mid.addLayout(mrow)
        lay.addLayout(mid, stretch=4)

        side = QGroupBox("Current Fiber Data")
        sl = QGridLayout(side)
        self.f_fields = {}
        for r, name in enumerate(["Fiber", "Stress", "Strain", "Strain max", "Strain min", "State"]):
            sl.addWidget(QLabel(name), r, 0)
            self.f_fields[name] = _readonly()
            sl.addWidget(self.f_fields[name], r, 1)
        self.chk_f_full = QCheckBox("Show full backbone")
        self.chk_f_full.setChecked(False)
        self.chk_f_full.toggled.connect(self._refresh_all)
        sl.addWidget(self.chk_f_full, 6, 0, 1, 2)
        sl.setRowStretch(7, 1)
        side.setFixedWidth(220)
        lay.addWidget(side)
        return w

    def _ctx(self):
        i = self.combo_hinge.currentIndex()
        if i < 0:
            return None
        return self._contexts[self.combo_hinge.itemData(i)]

    def _case(self):
        return self._cases.get(self.combo_case.currentText())

    def _units(self):
        u = UNIT_DEFS[self.combo_units.currentText()]
        return {
            "M": u["force"] * u["length"], "S": u["force"] / (u["length"] ** 2),
            "Mlabel": f"{u['flabel']}-{u['llabel']}", "Slabel": f"{u['flabel']}/{u['llabel']}²",
        }

    def _step_index(self):
        return self.spin_step.value()

    def _ds_upto(self, ctx, case, upto):
        """Section deformations for saved steps 0..upto (holding the last known
        value if a step lacks this hinge)."""
        out, last = [], np.zeros(3)
        for st in case["steps"][:upto + 1]:
            last = st["d"].get(ctx.key, last)
            out.append(last)
        return out

    def _sig_upto(self, ctx, case, upto):
        """Solver fiber stresses for saved steps 0..upto, or None when the result carries none for this
        hinge (no cyclic hysteresis in the run -> the backbone rebuild is exact and is used)."""
        out, last = [], None
        for st in case["steps"][:upto + 1]:
            last = (st.get("sig") or {}).get(ctx.key, last)
            if last is None or len(last) != ctx.n:
                return None
            out.append(last)
        return out

    def _lh(self, ctx, case):
        return case["lh"].get(ctx.key, ctx.lh_model)

    def _populate_hinges(self, *_):
        only_sel = self.chk_selected_only.isChecked() and bool(self._selected_ids)
        self.combo_hinge.blockSignals(True)
        self.combo_hinge.clear()
        for idx, c in enumerate(self._contexts):
            if only_sel and c.key not in self._selected_ids:
                continue
            self.combo_hinge.addItem(f"Frame {c.element_id}  -  {c.prop_name} @ {c.rel_dist:.3g}", idx)
        self.combo_hinge.blockSignals(False)
        self._on_hinge_changed()

    def _on_sync_view_toggled(self, checked):
        if checked:
            case = self._case()
            if case and self.main_window and hasattr(self.main_window, "sync_canvas_to_case"):
                self.main_window.sync_canvas_to_case(case["case_name"], self._step_index())
                self._update_highlight()

    def _on_case_changed(self, *_):
        case = self._case()
        n = len(case["steps"]) if case else 0
        self._syncing = True
        for w in (self.spin_step, self.slider_step):
            w.setRange(0, max(n - 1, 0))
            w.setValue(max(n - 1, 0))                                   
        self._syncing = False
        if getattr(self, "chk_sync_view", None) and self.chk_sync_view.isChecked():
            if case and self.main_window and hasattr(self.main_window, "sync_canvas_to_case"):
                self.main_window.sync_canvas_to_case(case["case_name"], self._step_index())
        self._refresh_all()

    def _on_step_widget(self, value):
        if self._syncing:
            return
        self._syncing = True
        self.spin_step.setValue(value)
        self.slider_step.setValue(value)
        self._syncing = False
        self._refresh_all()
        if not self._from_external and getattr(self, "chk_sync_view", None) and self.chk_sync_view.isChecked():
            case = self._case()
            if not self._scrub_sync_ok() and case and self.main_window and hasattr(self.main_window, "sync_canvas_to_case"):
                self.main_window.sync_canvas_to_case(case["case_name"], int(value))
            elif self._scrub_sync_ok():
                self.animation_manager.scrub_to_step(int(value))

    def _scrub_sync_ok(self):
        """True when the viewport is playing the SAME case with the same
        number of steps, so slider index == viewport step index."""
        mgr, case = self.animation_manager, self._case()
        if mgr is None or case is None or not getattr(mgr, "ltha_mode", False):
            return False
        loaded = getattr(getattr(mgr, "canvas", None), "_ltha_loaded_case", None)
        return (loaded == case["case_name"]
                and int(mgr.ltha_n_steps) == len(case["steps"]))

    def _connect_scrubber(self):
        mgr = self.animation_manager
        if mgr is None or self._scrub_connected:
            return
        mgr.signal_ltha_frame_update.connect(self._on_external_step)
        self._scrub_connected = True
        if self._scrub_sync_ok():                                                       
            cv = getattr(mgr, "canvas", None)
            self._on_external_step(int(getattr(cv, "ltha_current_step", mgr.ltha_current_step)))

    def _disconnect_scrubber(self):
        mgr = self.animation_manager
        if mgr is not None and self._scrub_connected:
            try:
                mgr.signal_ltha_frame_update.disconnect(self._on_external_step)
            except Exception:
                pass
        self._scrub_connected = False

    def _on_external_step(self, t_index):
        """Playback / Deformed Shape scrubber / plot dialog moved the step."""
        if (not self._ui_built or self._syncing or not self._scrub_sync_ok()
                or not (getattr(self, "chk_sync_view", None) and self.chk_sync_view.isChecked())):
            return
        t_index = max(0, min(int(t_index), self.spin_step.maximum()))
        if t_index == self.spin_step.value():
            return
        self._from_external = True
        try:
            self._on_step_widget(t_index)                                                 
        finally:
            self._from_external = False
            
    def _update_highlight(self, clear=False):
        cv = getattr(self.animation_manager, "canvas", None)
        if cv is None or not hasattr(cv, "set_highlight_hinge"):
            return
        ctx = None if (clear or not self._ui_built) else self._ctx()
        try:
            cv.set_highlight_hinge(ctx.key if ctx is not None else None)
        except RuntimeError:                                                     
            pass

    def showEvent(self, event):
        super().showEvent(event)
        self._update_highlight()

    def done(self, r):
        off_theme_changed(self._on_theme_changed)
        self._disconnect_scrubber()
        self._update_highlight(clear=True)
        super().done(r)

    def closeEvent(self, event):
        self._disconnect_scrubber()
        self._update_highlight(clear=True)
        super().closeEvent(event)

    def _on_hinge_changed(self, *_):
        ctx = self._ctx()
        self.f_table.blockSignals(True)
        self.f_table.setUpdatesEnabled(False)
        self.f_table.clearContents()
        self.f_table.setRowCount(0)
        if ctx is not None:
            fibers = ctx.fibers_def
            self.f_table.setRowCount(len(fibers))
            center = Qt.AlignmentFlag.AlignCenter
            for i, f in enumerate(fibers):
                for j, txt in enumerate([str(i + 1), f["material"], f"{f['coord2']:.4f}",
                                         f"{f['coord3']:.4f}", f"{f['area']:.4g}"]):
                    it = QTableWidgetItem(txt)
                    it.setTextAlignment(center)
                    self.f_table.setItem(i, j, it)
            self.f_table.selectRow(0)
            self._auto_select_dof(ctx)
        self.f_table.setUpdatesEnabled(True)
        self.f_table.blockSignals(False)
        self._refresh_all()
        if self._ui_built:
            self._update_highlight()

    def _auto_select_dof(self, ctx):
        """If the chosen bending axis has no lever arm for this hinge (uniaxial
        section bending about the other axis), switch to the axis that does.
        Leaves the user's choice alone whenever it is meaningful."""
        cur = self.combo_dof.currentText()
        other = "M2" if cur == "M3" else "M3"
        if ctx.lever_arm(cur) < 1e-6 <= ctx.lever_arm(other):
            self.combo_dof.blockSignals(True)
            self.combo_dof.setCurrentText(other)
            self.combo_dof.blockSignals(False)

    def _on_fiber_table_selected(self):
        self._refresh_all()

    def _on_section_click(self, ev):
        ctx = self._ctx()
        if ctx is None or ev.xdata is None or ev.ydata is None:
            return
        x = np.array([f["coord3"] for f in ctx.fibers_def])
        y = np.array([f["coord2"] for f in ctx.fibers_def])
        i = int(np.argmin((x - ev.xdata) ** 2 + (y - ev.ydata) ** 2))
        self.f_table.selectRow(i)                               

    def _sel_fiber(self):
        rows = self.f_table.selectionModel().selectedRows() if self.f_table.rowCount() else []
        return rows[0].row() if rows else 0

    @staticmethod
    def _mouse(ev, ex, ey):
        if ev.xdata is None or ev.ydata is None:
            ex.clear()
            ey.clear()
            return
        ex.setText(f"{ev.xdata:.5g}")
        ey.setText(f"{ev.ydata:.5g}")

    def _refresh_all(self, *_):
        """Request a redraw (cheap; the work happens once in _flush)."""
        if not self._ui_built:
            return
        self._dirty = [True, True]
        if not self._timer.isActive():
            self._timer.start()

    def _on_tab_changed(self, idx):
        if self._ui_built and self._dirty[idx]:
            self._timer.stop()
            self._flush()

    @staticmethod
    def _relayout(fig):
        try:
            fig.tight_layout()
        except Exception:
            pass

    def _relayout_all(self):
        for fig, cv in ((self.h_fig, self.h_canvas), (self.f_fig, self.f_canvas),
                        (self.s_fig, self.s_canvas)):
            if cv.isVisible():
                self._relayout(fig)
                cv.draw_idle()

    def _draw_empty(self):
        for ax, cv in ((self.h_ax, self.h_canvas), (self.f_ax, self.f_canvas), (self.s_ax, self.s_canvas)):
            ax.clear()
            _style_axes(ax.figure, ax)
            ax.text(0.5, 0.5, "No hinge selected / no data", ha="center", va="center",
                    transform=ax.transAxes, color=COLORS["text_secondary"])
            cv.draw_idle()
        self._h_key = self._f_key = self._s_key = None
        self._s_present = None
        for nav in (self.h_nav, self.f_nav, self.s_nav):
            nav.user_zoomed = False

    def _flush(self):
        if not self._ui_built:
            return
        ctx, case = self._ctx(), self._case()
        if ctx is None or case is None or not case["steps"]:
            self._draw_empty()
            self._dirty = [False, False]
            return

        step = self._step_index()
        st_no = case["steps"][step]["step"]
        self.lbl_step.setText(f"Step number {st_no}   ({step + 1} of {len(case['steps'])})")
        lh = self._lh(ctx, case)
        self.lbl_frame.setText(str(ctx.element_id))
        self.lbl_pos.setText(f"{ctx.rel_dist:.4g}")
        if not lh:
            self.lbl_len.setText("n/a")
        elif ctx.lh_relative:
            self.lbl_len.setText(f"{ctx.lh_raw:.4g} rel = {lh:.4g} m")                            
        else:
            self.lbl_len.setText(f"{lh:.4g} m")
        self.lbl_prop.setText(ctx.prop_name)

        tab = self.tabs.currentIndex()
        if tab == 0:
            self._draw_hinge(ctx, case, step, lh)
        else:
            self._draw_fiber(ctx, case, step)
            self._draw_section(ctx, self._track(ctx, case)["ds"][step])
        self._dirty[tab] = False

    def _track(self, ctx, case):
        """Dense response path of one hinge through ALL saved steps (cached)."""
        key = (case["case_name"], ctx.key)
        tr = self._tracks.get(key)
        if tr is None:
            ds = np.array(self._ds_upto(ctx, case, len(case["steps"]) - 1), float)
            S = None
            sg = self._sig_upto(ctx, case, len(case["steps"]) - 1)
            if sg is not None:
                                                                                                       
                seq = np.vstack([np.zeros(ctx.n)] + sg)
                tt = np.arange(1, SUBSTEPS + 1) / SUBSTEPS
                seg = seq[:-1, None, :] + (seq[1:, None, :] - seq[:-1, None, :]) * tt[None, :, None]
                S = np.vstack([seq[:1], seg.reshape(-1, ctx.n)])
            tr = {"ds": ds, "D": _dense_path(ds), "M": {}, "F": {}, "S": S}
            self._tracks[key] = tr
        return tr

    @staticmethod
    def _hinge_series(ctx, tr, dof):
        if dof not in tr["M"]:
                                                                              
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                if tr.get("S") is not None:
                    tr["M"][dof] = ctx.moment_from_sigma(tr["S"], dof)
                else:
                    tr["M"][dof] = np.array([ctx.moment(d, dof) for d in tr["D"]])
            finally:
                QApplication.restoreOverrideCursor()
        return ctx.sign(dof) * tr["D"][:, ctx.curv_col(dof)] + 0.0, tr["M"][dof] + 0.0

    @staticmethod
    def _fiber_series(ctx, tr, i):
        if i not in tr["F"]:
            D = tr["D"]
            eps = D[:, 0] - D[:, 1] * ctx.c3[i] + D[:, 2] * ctx.c2[i]
            if tr.get("S") is not None:
                sig = tr["S"][:, i]
            else:
                sig = np.array([ctx.fiber_stress_at(i, e) for e in eps])
            tr["F"][i] = (eps, sig)
        return tr["F"][i]

    def _draw_hinge(self, ctx, case, step, lh):
        dof = self.combo_dof.currentText()
        u = self._units()
        rs = lh if lh else 1.0

        tr = self._track(ctx, case)
        pk_all, pm_all = self._hinge_series(ctx, tr, dof)
        pk_all, pm_all = pk_all * rs, pm_all * u["M"]
        n = (step + 1) * SUBSTEPS + 1                                                
        pk, pm = pk_all[:n], pm_all[:n]
        cur_k, cur_m = pk[-1], pm[-1]

        ax = self.h_ax
        key = (ctx.key, case["case_name"], dof, self.combo_units.currentText(), rs)
        if key != self._h_key:
            ax.clear()
            _style_axes(self.h_fig, ax)
            resp, = ax.plot(pk, pm, color=COLORS["accent"], lw=2.2)
            mark, = ax.plot([cur_k], [cur_m], "o", mfc=COLORS["bg_panel"],
                            mec=COLORS["text_primary"], ms=7, zorder=5)
            ax.axhline(0, color=COLORS["text_secondary"], lw=0.8)
            ax.axvline(0, color=COLORS["text_secondary"], lw=0.8)
                                                                                   
            for setter, vals in ((ax.set_xlim, pk_all), (ax.set_ylim, pm_all)):
                lo, hi = min(float(vals.min()), 0.0), max(float(vals.max()), 0.0)
                if hi - lo < 1e-12:
                    lo, hi = -1.0, 1.0
                setter(*_limits(lo, hi, vals, True))
            ax.set_xlabel("Rotation (rad)" if lh else "Curvature (1/m)")
            ax.set_ylabel(f"Moment {dof} ({u['Mlabel']})")
            ax.set_title(f"Frame {ctx.element_id} - {ctx.prop_name}", fontsize=9)
            self._relayout(self.h_fig)
            self.h_nav.mark_home()
            self._h_art, self._h_key = (resp, mark), key

        resp, mark = self._h_art
        resp.set_data(pk, pm)
        mark.set_data([cur_k], [cur_m])
        self.h_canvas.draw_idle()

        rots = pk[::SUBSTEPS]                                                            
        self.h_fields["Moment"].setText(f"{cur_m:.5g}")
        self.h_fields["Rotation"].setText(f"{cur_k:.5g}")
        self.h_fields["Rotation max"].setText(f"{rots.max():.5g}")
        self.h_fields["Rotation min"].setText(f"{rots.min():.5g}")
        self.h_fields["State"].setText(ctx.worst_state(tr["ds"][step]))

    def _draw_fiber(self, ctx, case, step):
        i = self._sel_fiber()
        u = self._units()
        full = self.chk_f_full.isChecked()

        tr = self._track(ctx, case)
        pe_all, ps_all = self._fiber_series(ctx, tr, i)
        n = (step + 1) * SUBSTEPS + 1
        pe, ps = pe_all[:n], ps_all[:n] * u["S"]
        cur_e, cur_s = pe[-1], ps[-1]

        ax = self.f_ax
        key = (ctx.key, case["case_name"], i, self.combo_units.currentText(), full)
        if key != self._f_key:
            bb = ctx.backbones[i]
            bx = np.array([p[0] for p in bb])
            by = np.array([p[1] for p in bb]) * u["S"]
            self._f_rng = (bx.min(), bx.max(), by.min(), by.max())
            ax.clear()
            _style_axes(self.f_fig, ax)
            ax.plot(bx, by, color=BACKBONE_COLOR, lw=1.0, label="Material backbone")
            resp, = ax.plot(pe, ps, color=COLORS["accent"], lw=2.4, label="Response")
            mark, = ax.plot([cur_e], [cur_s], "o", mfc=COLORS["bg_panel"],
                            mec=COLORS["text_primary"], ms=7, zorder=5)
            ax.axhline(0, color=COLORS["text_secondary"], lw=0.8)
            ax.axvline(0, color=COLORS["text_secondary"], lw=0.8)
            if full:
                ax.set_xlim(*_limits(self._f_rng[0], self._f_rng[1], pe, True))
                ax.set_ylim(*_limits(self._f_rng[2], self._f_rng[3], ps, True))
            ax.set_xlabel("Strain")
            ax.set_ylabel(f"Stress ({u['Slabel']})")
            ax.set_title(f"Fiber {i + 1} - {ctx.fibers_def[i]['material']}", fontsize=9)
            ax.legend(loc="lower right", fontsize=8, facecolor=COLORS["bg_panel"],
                      edgecolor=COLORS["border"], labelcolor=COLORS["text_primary"])
            self._relayout(self.f_fig)
            self.f_nav.user_zoomed = False                                         
            self._f_art, self._f_key = (resp, mark), key

        resp, mark = self._f_art
        resp.set_data(pe, ps)
        mark.set_data([cur_e], [cur_s])
        if not full and not self.f_nav.user_zoomed:                                       
            x0, x1, y0, y1 = self._f_rng
            ax.set_xlim(*_limits(x0, x1, pe, False))
            ax.set_ylim(*_limits(y0, y1, ps, False))
        if not self.f_nav.user_zoomed:
            self.f_nav.mark_home()
        self.f_canvas.draw_idle()

        step_eps = pe[::SUBSTEPS]
        self.f_fields["Fiber"].setText(f"{i + 1}")
        self.f_fields["Stress"].setText(f"{cur_s:.5g}")
        self.f_fields["Strain"].setText(f"{cur_e:.5g}")
        self.f_fields["Strain max"].setText(f"{step_eps.max():.5g}")
        self.f_fields["Strain min"].setText(f"{step_eps.min():.5g}")
        self.f_fields["State"].setText(ctx.fiber_state_at(i, cur_e))

    @staticmethod
    def _map_palette():
        """Section-map colours for the active theme (shared with the hinge dialog preview)."""
        return section_map_palette()

    def _build_section_map(self, ctx, by_state, i, cols, hide_reinf=False):
        ax = self.s_ax
        ax.clear()
        _style_axes(self.s_fig, ax)
        pal = self._map_palette()
        ax.set_facecolor(pal["bg"])
        ax.grid(False)
        ax.set_xticks([])
        ax.set_yticks([])
        light = pal["text"]

        x = np.array([f["coord3"] for f in ctx.fibers_def])
        y = np.array([f["coord2"] for f in ctx.fibers_def])
        px, py = list(x), list(y)

        sec = ctx.section
        shape = []
        if sec is not None:
            try:
                shape = list(sec.get_shape_coords() or [])
            except Exception:
                shape = []
        if shape:
            ax.add_patch(Polygon(shape, closed=True, facecolor=pal["fill"],
                                 edgecolor=pal["outline"], lw=2, zorder=1))
            px += [p[0] for p in shape]
            py += [p[1] for p in shape]
            reinf = getattr(sec, "reinforcement", None)
            if (not hide_reinf) and reinf is not None and getattr(sec, "b", None) is not None:
                tie_dia = 0.01
                for r in getattr(self.model, "rebar_sizes", []) or []:
                    if r.get("id") == reinf.tie_bar_size:
                        tie_dia = r.get("diameter", 0.01)
                        break
                off = reinf.clear_cover + tie_dia / 2.0
                cb, ch = sec.b - 2 * off, sec.h - 2 * off
                if cb > 0 and ch > 0:
                    ax.add_patch(Polygon([(cb / 2, ch / 2), (-cb / 2, ch / 2), (-cb / 2, -ch / 2),
                                          (cb / 2, -ch / 2)], closed=True, fill=False,
                                         edgecolor="#00c853", lw=1.6, ls="--", zorder=2))
        for ry, rz, dia in ([] if hide_reinf else ctx.rebars):
            ax.add_patch(Circle((ry, rz), max(dia / 2.0, 1e-4), facecolor="#d81f1f",
                                edgecolor="#000000", lw=0.8, zorder=3))
            px.append(ry)
            py.append(rz)

        ax.axhline(0, color=pal["axis"], alpha=0.14, lw=1, zorder=0)
        ax.axvline(0, color=pal["axis"], alpha=0.14, lw=1, zorder=0)

        if by_state:
            init_cols = cols
        else:
            names = sorted(set(ctx.materials))
            cmap = {n: MATERIAL_COLORS[k % len(MATERIAL_COLORS)] for k, n in enumerate(names)}
            init_cols = [cmap[m] for m in ctx.materials]
            handles = [Line2D([], [], marker="o", ls="", color=cmap[n], label=n) for n in names]
            ax.legend(handles=handles, loc="upper right", fontsize=7, framealpha=0.85,
                      facecolor=COLORS["bg_panel"], edgecolor=COLORS["border"],
                      labelcolor=COLORS["text_primary"])
        sizes = 10 + 70 * (ctx.area / max(ctx.area.max(), 1e-30))
        sc = ax.scatter(x, y, s=sizes, c=init_cols, edgecolors="none", zorder=4)
        ax.scatter([x[i]], [y[i]], s=sizes[i] * 3 + 60, facecolors="none",
                   edgecolors=pal["ring"], linewidths=1.6, zorder=5)

        x0, x1, y0, y1 = min(px), max(px), min(py), max(py)
        mx, my = max(x1 - x0, 1e-6), max(y1 - y0, 1e-6)
        pad = 0.12 * max(mx, my)
        ax.set_xlim(x0 - pad, x1 + pad)
        ax.set_ylim(y0 - pad, y1 + pad)
        ax.set_aspect("equal", adjustable="datalim")

        parts = []
        if sec is not None:
            parts.append(str(getattr(sec, "name", "")))
        if ctx.rebars and not hide_reinf:
            parts.append(f"{len(ctx.rebars)} bar(s)")
        parts.append(f"{ctx.n} fiber(s)")
        ax.text(0.02, 0.02, "  --  ".join(p for p in parts if p), transform=ax.transAxes,
                fontsize=7, color=light, ha="left", va="bottom")

        ox, oy, L = 0.90, 0.10, 0.10
        arrow = dict(arrowstyle="->", color=light, lw=1.4)
        ax.annotate("", xy=(ox, oy + L), xytext=(ox, oy), xycoords="axes fraction",
                    textcoords="axes fraction", arrowprops=arrow, annotation_clip=False)
        ax.annotate("", xy=(ox - L, oy), xytext=(ox, oy), xycoords="axes fraction",
                    textcoords="axes fraction", arrowprops=arrow, annotation_clip=False)
        ax.text(ox, oy + L + 0.02, "2", transform=ax.transAxes, fontsize=8, color=light,
                ha="center", va="bottom")
        ax.text(ox - L - 0.02, oy, "3", transform=ax.transAxes, fontsize=8, color=light,
                ha="right", va="center")
        self._relayout(self.s_fig)
        return sc

    def _draw_section(self, ctx, d):
        i = self._sel_fiber()
        by_state = self.rad_state.isChecked()
        ax = self.s_ax
        self.chk_hide_reinf.setEnabled(ctx.has_reinf)
        hide = ctx.has_reinf and self.chk_hide_reinf.isChecked()
        key = (ctx.key, by_state, i, hide)
        rebuilt = key != self._s_key
        cols = None
        if by_state:
            sidx = ctx.state_indices(ctx.fiber_strains(d))
            cols = [STATE_COLORS[STATE_ORDER[k]] for k in sidx]

        if rebuilt:
            keep = None
            if self.s_nav.user_zoomed and self._s_key is not None and self._s_key[0] == key[0]:
                keep = (ax.get_xlim(), ax.get_ylim())                                 
            sc = self._build_section_map(ctx, by_state, i, cols, hide)
            self._s_art, self._s_key, self._s_present = sc, key, None
            self.s_nav.mark_home()
            if keep is not None:
                ax.set_xlim(*keep[0])
                ax.set_ylim(*keep[1])
                self.s_nav.user_zoomed = True

        if by_state:
            self._s_art.set_facecolor(cols)
            present = tuple(sorted({int(k) for k in sidx}))
            if present != self._s_present:                                                   
                handles = [Line2D([], [], marker="o", ls="", color=STATE_COLORS[STATE_ORDER[k]],
                                  label=STATE_ORDER[k]) for k in present]
                if handles:
                    ax.legend(handles=handles, loc="upper right", fontsize=7, framealpha=0.85,
                              facecolor=COLORS["bg_panel"], edgecolor=COLORS["border"],
                              labelcolor=COLORS["text_primary"])
                self._s_present = present
        self.s_canvas.draw_idle()

    def _on_export_csv(self):
        ctx, case = self._ctx(), self._case()
        if ctx is None or case is None:
            return
        dof = self.combo_dof.currentText()
        u = self._units()
        lh = self._lh(ctx, case)
        scale = lh if lh else 1.0
        default = f"{self.base_name}_{case['case_name']}_hinge_{ctx.element_id}_{dof}.csv"
        path, _ = QFileDialog.getSaveFileName(self, "Export Hinge History", default, "CSV Files (*.csv)")
        if not path:
            return
        ds = self._ds_upto(ctx, case, len(case["steps"]) - 1)
        sg = self._sig_upto(ctx, case, len(case["steps"]) - 1)
        with open(path, "w") as f:
            f.write(f"Step,{'Rotation (rad)' if lh else 'Curvature (1/m)'},Moment {dof} ({u['Mlabel']}),State\n")
            for k, (st, d) in enumerate(zip(case["steps"], ds)):
                m = ctx.moment_from_sigma(sg[k], dof) if sg is not None else ctx.moment(d, dof)
                f.write(f"{st['step']},{ctx.curvature(d, dof) * scale:.6g},"
                        f"{m * u['M']:.6g},{ctx.worst_state(d)}\n")
        QMessageBox.information(self, "Export Complete", f"Hinge history exported to:\n{path}")
