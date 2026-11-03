"""
pushover_curve_dialog.py

Analyze > Show Static Pushover Curve...

Displays the capacity curve (Base Shear vs Monitored Displacement) for a
Nonlinear Static load case that was run with:
    Load Application Control = "Displacement Control"
    Results Saved             = "Multiple States"

Both flags -- plus the monitored (joint, DOF) pair that Displacement
Control targets -- are written into "info" of the case's own
*_results.json by nonlinear_engine.py (see the "Pushover Curve support"
block at the end of run_nonlinear_analysis()). This dialog is purely a
reader of that JSON: it never re-runs or re-derives the analysis, so a
case that was run WITHOUT those two settings simply has nothing to show
here (info["disp_control"] is False, or "saved_states" is absent/short),
which is why the dialog reports "no pushover results" instead of trying
to fabricate a curve from a single converged point.

Base Shear convention: the model's vertical/gravity axis is Z (confirmed
against data_manager.py's self-weight generator, which loads only 'wz'),
so for a HORIZONTAL push (monitored DOF U1/U2/rotation) the "Resultant Base
Shear" is the horizontal resultant of the base reaction, sqrt(Fx^2 + Fy^2).
For a VERTICAL push (monitored DOF U3, e.g. a gravity / vertical-displacement
case) the horizontal reaction is only numerical noise, so 
the resultant is the force in the pushed direction, |Fz|.
"""

import json
import os

import numpy as np
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QIntValidator, QPixmap
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton,
    QLineEdit, QMenuBar, QSizePolicy, QFileDialog, QMenu,
    QGroupBox, QCheckBox, QWidget
)

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from app.ui.theme import apply_dialog_style, style_plot_axes, PlotNavigator, COLORS, RangeSlider
from app.ui.metrics_panel import MetricsPanel
from app.dialogs.pushover_parameters_dialog import (
    PLOT_TYPES, PLOT_TYPE_AXES, axis_to_display, axis_unit_name
)
from core.units import make_unit_converter, unit_registry, UNIT_SYSTEMS, MODEL_DISPLAY_UNITS

DOF_INDEX = {"U1": 0, "U2": 1, "U3": 2, "R1": 3, "R2": 4, "R3": 5}

def _build_unit_defs():
    defs = {}
    for label in UNIT_SYSTEMS:
        c = make_unit_converter(label)
        defs[label] = {"force": c.force_scale, "length": c.length_scale,
                       "flabel": c.force_unit_name, "llabel": c.length_unit_name}
    return defs

UNIT_DEFS = _build_unit_defs()

def _load_pushover_case(path, case_name):
    """
    Reads one case's *_results.json and returns a dict of step-by-step
    data if (and only if) it's a genuine Displacement-Control, Multiple-
    States pushover run; otherwise returns None.
    """
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'r') as f:
            data = json.load(f)
    except Exception:
        return None

    if data.get("status") != "SUCCESS":
        return None

    info = data.get("info", {})
    if info.get("type") != "Nonlinear Static":
        return None
    if not info.get("results_saved_multiple"):
        return None

    saved_states = data.get("saved_states")
    if not saved_states or len(saved_states) < 2:
        return None

    os_hist = info.get("opensees_history") or {}
    node_id = info.get("disp_control_node_id")
    if node_id is None:
        node_id = os_hist.get("control_node")

    dof_name = info.get("disp_control_dof")
    if not dof_name and os_hist.get("control_dof"):
        dof_name = {1: "U1", 2: "U2", 3: "U3", 4: "R1", 5: "R2", 6: "R3"}.get(int(os_hist["control_dof"]), "U1")
    dof_name = dof_name or "U1"
    dof_idx = DOF_INDEX.get(dof_name, 0)
    node_key = str(node_id)

    last_disps = saved_states[-1].get("displacements", {})
    if node_key not in last_disps and last_disps:
        node_key, dof_idx = max(
            ((nk, di) for nk, dv in last_disps.items() if len(dv) >= 3 for di in (0, 1, 2)),
            key=lambda item: abs(float(last_disps[item[0]][item[1]])),
            default=(next(iter(last_disps)), 0),
        )
        node_id = int(node_key) if str(node_key).isdigit() else node_key
        dof_name = ("U1", "U2", "U3", "R1", "R2", "R3")[dof_idx]

    steps = []
    for st in saved_states:
        disp_vec = st.get("displacements", {}).get(node_key)
        if disp_vec is None or len(disp_vec) < 6:
            continue
        br = st.get("base_reaction", {}) or {}
        fx = float(br.get("Fx", 0.0))
        fy = float(br.get("Fy", 0.0))
        fz = float(br.get("Fz", 0.0))
        steps.append({
            "step": st.get("step", 0),
            "disp": float(disp_vec[dof_idx]),
            "Fx": fx, "Fy": fy, "Fz": fz,
                                                                                          
            "V_resultant": abs(fz) if dof_idx == 2 else (fx * fx + fy * fy) ** 0.5,
        })
        if info.get("engine") == "opensees" and dof_idx in (0, 1):
                                                                                                  
            steps[-1]["V_resultant"] = -(fx if dof_idx == 0 else fy)

    if len(steps) < 2:
        return None

    steps.sort(key=lambda s: s["step"])

    history = None
    if info.get("engine") == "opensees" and dof_idx in (0, 1):
        _u, _v = os_hist.get("u_m"), os_hist.get("V_N")
        if _u and _v and len(_u) == len(_v) and len(_u) >= 2 and str(os_hist.get("control_node")) == str(node_id):
            history = {"u": np.asarray(_u, dtype=float), "V": np.asarray(_v, dtype=float)}

    return {
        "case_name": case_name,
        "node_id": node_id,
        "dof_name": dof_name,
        "steps": steps,
        "history": history,
                                                                                  
        "os_failed": (info.get("failed_steps") or None) if info.get("engine") == "opensees" else None,
    }

class _StepRangeRow(QWidget):
    """One step range: [From step] ====slider==== [To step] [x]. Edits are in STEP numbers."""
    changed = pyqtSignal()
    removeRequested = pyqtSignal(object)

    def __init__(self, steps, lo_step, hi_step, parent=None, title=None, unit="step", removable=True):
        super().__init__(parent)
        self._steps = np.asarray(steps)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        self.lbl_color = QLabel()
        self.lbl_color.setFixedSize(18, 12)
        lay.addWidget(self.lbl_color)
        if title:
            lbl = QLabel(title)
            lbl.setMaximumWidth(150)
            lay.addWidget(lbl)
        lay.addWidget(QLabel(f"From {unit}"))
        self.edit_lo = QLineEdit()
        self.edit_lo.setFixedWidth(64)
        self.edit_lo.setValidator(QIntValidator(self))
        lay.addWidget(self.edit_lo)
        self.slider = RangeSlider(minimum=0, maximum=max(0, len(self._steps) - 1))
        lay.addWidget(self.slider, 1)
        lay.addWidget(QLabel(f"To {unit}"))
        self.edit_hi = QLineEdit()
        self.edit_hi.setFixedWidth(64)
        self.edit_hi.setValidator(QIntValidator(self))
        lay.addWidget(self.edit_hi)
        self.btn_remove = QPushButton("x")
        self.btn_remove.setObjectName("danger")
        self.btn_remove.setFixedWidth(28)
        self.btn_remove.setToolTip("Remove this range")
        self.btn_remove.clicked.connect(lambda: self.removeRequested.emit(self))
        lay.addWidget(self.btn_remove)
        if not removable:
            self.btn_remove.hide()

        self.slider.rangeChanged.connect(self._on_slider)
        self.edit_lo.editingFinished.connect(self._on_edit)
        self.edit_hi.editingFinished.connect(self._on_edit)
        self._set_from_steps(lo_step, hi_step)

    def _set_from_steps(self, lo, hi):
        n = len(self._steps)
        il = min(int(np.searchsorted(self._steps, lo, side="left")), n - 1)
        ih = max(int(np.searchsorted(self._steps, hi, side="right")) - 1, 0)
        self.slider.setValues(il, max(il, ih))
        self._refresh_edits()

    def _refresh_edits(self):
        lo, hi = self.slider.values()
        self.edit_lo.setText(str(int(self._steps[lo])))
        self.edit_hi.setText(str(int(self._steps[hi])))

    def _on_slider(self, lo, hi):
        self._refresh_edits()
        self.changed.emit()

    def _on_edit(self):
        try:
            lo, hi = int(self.edit_lo.text()), int(self.edit_hi.text())
        except ValueError:
            self._refresh_edits()
            return
        if lo > hi:
            lo, hi = hi, lo
        self._set_from_steps(lo, hi)
        self.changed.emit()

    def values(self):
        lo, hi = self.slider.values()
        return int(self._steps[lo]), int(self._steps[hi])

    def set_color(self, color):
        pm = QPixmap(18, 12)
        pm.fill(QColor(color))
        self.lbl_color.setPixmap(pm)

    def set_removable(self, on):
        self.btn_remove.setEnabled(on)

class PushoverCurveDialog(QDialog):
    """
    Analyze > Show Static Pushover Curve... display dialog.

    "Pick a case, pick a parameter set, see the plot". The case is chosen
    here (so it works for any case of a single or batch run); everything
    about HOW the curve is drawn (plot type, units, axis range, labels,
    notes) lives in the parameter sets defined under
    Define > Pushover Parameter Sets > Force vs Displacement...
    and saved with the model (model.pushover_param_sets). This dialog never
    edits them (the model is locked once results exist anyway). The Units
    box here only changes how THIS plot is shown, on the fly; it is not
    written back to the set, and picking another set resets it to that
    set's own units.

    Read-only with respect to the model/results on disk -- it only plots
    what nonlinear_engine.py already wrote out for eligible cases.
    """
    OVERLAY_COLORS = ["#555555", "#d9534f", "#2e8b57", "#8e44ad", "#e08a00"]
    RANGE_COLORS = [None, "#ff9f1c", "#2ec4b6", "#e71d36", "#9b5de5", "#8d99ae"]                                 
    MAX_RANGES = 6

    def __init__(self, parent, base_name, case_paths, model):
        super().__init__(parent)
        self.setWindowTitle("Pushover Curve")
        self.resize(820, 870)
        apply_dialog_style(self)

        self.base_name = base_name
        self.model = model
        self._overlay_override = {}                                                             
        self._ranges = {}                                                                    
        self._range_rows = []
        self._keep_view = False
        self._ref_ranges = {}                                                                               
        self._ref_rows = {}
        self._ref_key = None
        self._series_cache = {}                                                                                                  
        self._conv_cache = {}                                      
        self._art = None                                                                                  
        self._bg = None                                                                            
        self._upd_pending = False
                                                                   
        self._case_data = {}
        for case_name, path in case_paths.items():
            data = _load_pushover_case(path, case_name)
            if data is not None:
                self._case_data[case_name] = data

        self._build_ui()
        self._sync_range_rows()
        self.reload_sets()

    def has_any_eligible_case(self):
        return len(self._case_data) > 0

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 4, 6, 6)

        self.menubar = QMenuBar(self)
        file_menu = self.menubar.addMenu("File")
        export_action = file_menu.addAction("Export Curve to CSV...")
        export_action.triggered.connect(self._on_export_csv)
        file_menu.addSeparator()
        close_action = file_menu.addAction("Close")
        close_action.triggered.connect(self.reject)
        root.setMenuBar(self.menubar)

        body = QHBoxLayout()
        root.addLayout(body, 1)
        outer = QVBoxLayout()                                                                     
        body.addLayout(outer, 1)
        self.metrics_panel = MetricsPanel(self)                                                 
        self.metrics_panel.hide()
        body.addWidget(self.metrics_panel)
        self._metrics_key = None

        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("Case"))
        self.combo_case = QComboBox()
        self.combo_case.addItems(sorted(self._case_data.keys()))
        self.combo_case.currentIndexChanged.connect(self._on_case_changed)
        top_row.addWidget(self.combo_case)
        top_row.addSpacing(16)
        top_row.addWidget(QLabel("Pushover Parameters"))
        self.combo_sets = QComboBox()
        self.combo_sets.setMinimumWidth(180)
        self.combo_sets.currentIndexChanged.connect(self._on_set_changed)
        top_row.addWidget(self.combo_sets)
        top_row.addSpacing(16)
        top_row.addWidget(QLabel("Units"))
        self.combo_units = QComboBox()
        self.combo_units.addItems(UNIT_SYSTEMS)
        self.combo_units.currentIndexChanged.connect(self._redraw)
        top_row.addWidget(self.combo_units)
        top_row.addSpacing(16)
        self.btn_overlay = QPushButton("Reference Curves")
        self.btn_overlay.setObjectName("secondary")
        self.btn_overlay.setToolTip("Show/hide imported experimental curves on this plot.\nImport and edit them in Define > Pushover Parameter Sets.")
        self.menu_overlay = QMenu(self.btn_overlay)
        self.menu_overlay.aboutToShow.connect(self._rebuild_overlay_menu)
        self.btn_overlay.setMenu(self.menu_overlay)
        top_row.addWidget(self.btn_overlay)
        self.btn_metrics = QPushButton("Metrics >>")
        self.btn_metrics.setObjectName("secondary")
        self.btn_metrics.setCheckable(True)
        self.btn_metrics.setToolTip("Expand the dialog with the numbers of the analysis curve and of the\n"
                                    "reference curves drawn here (peaks, dissipated energy, damping, stiffness)\n"
                                    "and the comparison between them.")
        self.btn_metrics.toggled.connect(self._on_metrics_toggled)
        top_row.addWidget(self.btn_metrics)
        top_row.addStretch(1)
        outer.addLayout(top_row)

        self.figure = Figure(figsize=(5, 4))
        self.canvas = FigureCanvas(self.figure)
        self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.ax = self.figure.add_subplot(111)
        self.canvas.mpl_connect('motion_notify_event', self._on_mouse_move)
        self.canvas.mpl_connect('draw_event', self._on_draw_event)
        self.canvas.mpl_connect('resize_event', self._on_resize_event)
        self.nav = PlotNavigator(self.canvas, self.ax)
        self.canvas.setToolTip("Mouse wheel: zoom   |   Drag: pan   |   Double-click: reset view")
        outer.addWidget(self.canvas, stretch=1)

        self.grp_range = QGroupBox("Step Range  -  drag the handles, or drag the bar between them to slide the window")
        gl = QVBoxLayout(self.grp_range)
        gl.setContentsMargins(6, 4, 6, 4)
        gl.setSpacing(2)
        self._rows_layout = QVBoxLayout()
        self._rows_layout.setSpacing(2)
        gl.addLayout(self._rows_layout)
        opts = QHBoxLayout()
        self.btn_add_range = QPushButton("+ Add Range")
        self.btn_add_range.setObjectName("secondary")
        self.btn_add_range.clicked.connect(self._on_add_range)
        self.btn_reset_range = QPushButton("Show All")
        self.btn_reset_range.setObjectName("secondary")
        self.btn_reset_range.clicked.connect(self._on_reset_ranges)
        self.chk_fade = QCheckBox("Fade the rest")
        self.chk_fade.setChecked(True)
        self.chk_fade.toggled.connect(self._redraw_keep_view)
        self.chk_fit = QCheckBox("Fit axes to range")
        self.chk_fit.toggled.connect(self._redraw)
        for w in (self.btn_add_range, self.btn_reset_range, self.chk_fade, self.chk_fit):
            opts.addWidget(w)
        opts.addStretch(1)
        gl.addLayout(opts)
        outer.addWidget(self.grp_range)

        self.grp_ref = QGroupBox("Reference Curve Range")
        rl = QVBoxLayout(self.grp_ref)
        rl.setContentsMargins(6, 4, 6, 4)
        rl.setSpacing(2)
        self.chk_sync = QCheckBox("Link to the analysis range (same % of the loading history)")
        self.chk_sync.setChecked(True)
        self.chk_sync.setToolTip("On: the reference follows the Step Range above, matched by loading-path progress\n"
                                 "(cumulative displacement travelled), not by step count.\n"
                                 "Only meaningful if both follow the same loading history.\n"
                                 "Off: choose the point range of each reference curve yourself.")
        self.chk_sync.toggled.connect(self._on_sync_toggled)
        rl.addWidget(self.chk_sync)
        self._ref_rows_layout = QVBoxLayout()
        self._ref_rows_layout.setSpacing(2)
        rl.addLayout(self._ref_rows_layout)
        outer.addWidget(self.grp_ref)
        self.grp_ref.hide()

        self.lbl_notes = QLabel("")
        self.lbl_notes.setWordWrap(True)
        self.lbl_notes.setStyleSheet("color: gray;")
        self.lbl_notes.hide()
        outer.addWidget(self.lbl_notes)

        mouse_row = QHBoxLayout()
        mouse_row.addWidget(QLabel("Mouse Pointer Location"))
        mouse_row.addSpacing(20)
        mouse_row.addWidget(QLabel("Horiz"))
        self.edit_horiz = QLineEdit()
        self.edit_horiz.setReadOnly(True)
        self.edit_horiz.setFixedWidth(90)
        mouse_row.addWidget(self.edit_horiz)
        mouse_row.addWidget(QLabel("Vert"))
        self.edit_vert = QLineEdit()
        self.edit_vert.setReadOnly(True)
        self.edit_vert.setFixedWidth(90)
        mouse_row.addWidget(self.edit_vert)
        mouse_row.addStretch(1)
        outer.addLayout(mouse_row)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.btn_close = QPushButton("Close")
        self.btn_close.setObjectName("primary")
        self.btn_close.setDefault(True)
        self.btn_close.clicked.connect(self.accept)
        btn_row.addWidget(self.btn_close)
        outer.addLayout(btn_row)

    def _reference_curves(self):
        return getattr(self.model, "reference_curves", None) or []

    def _active_overlay(self, pset):
        """Curves shown: the set's own list, unless toggled here (view-only, not saved)."""
        if pset["name"] in self._overlay_override:
            return self._overlay_override[pset["name"]]
        return set(pset.get("overlay_curves") or [])

    def _rebuild_overlay_menu(self):
        menu = self.menu_overlay
        menu.clear()
        pset = self._current_set()
        curves = self._reference_curves()
        if pset is None or not curves:
            menu.addAction("(none defined - see Define > Pushover Parameter Sets)").setEnabled(False)
            return
        active = self._active_overlay(pset)
        for c in curves:
            act = menu.addAction(c["name"])
            act.setCheckable(True)
            act.setChecked(c["name"] in active)
            act.toggled.connect(lambda on, n=c["name"]: self._toggle_overlay(n, on))
        if pset["name"] in self._overlay_override:
            menu.addSeparator()
            menu.addAction("Reset to this set's curves").triggered.connect(self._reset_overlay)

    def _toggle_overlay(self, name, on):
        pset = self._current_set()
        if pset is None:
            return
        cur = set(self._active_overlay(pset))
        (cur.add if on else cur.discard)(name)
        self._overlay_override[pset["name"]] = cur
        self._redraw()

    def _reset_overlay(self):
        pset = self._current_set()
        if pset is not None:
            self._overlay_override.pop(pset["name"], None)
            self._redraw()

    def _sets(self):
        return getattr(self.model, "pushover_param_sets", None) or []

    def reload_sets(self):
        """(Re)fills the picker from the model, keeping the current selection if it still exists."""
        self._series_cache.clear()
        self._conv_cache.clear()
        prev = self.combo_sets.currentText()
        self.combo_sets.blockSignals(True)
        self.combo_sets.clear()
        for s in self._sets():
            self.combo_sets.addItem(s["name"])
        i = self.combo_sets.findText(prev)
        self.combo_sets.setCurrentIndex(i if i >= 0 else 0)
        self.combo_sets.blockSignals(False)
        self._sync_units_combo()
        self._redraw()

    def _on_set_changed(self, *_):
        self._sync_units_combo()                                                 
        self._redraw()

    def _sync_units_combo(self):
        """Show the current set's units (resolving 'Model display units' to the global label)."""
        pset = self._current_set()
        if pset is None:
            return
        label = pset.get("units")
        if not label or label == MODEL_DISPLAY_UNITS or label not in UNIT_SYSTEMS:
            label = unit_registry.current_unit_label
        self.combo_units.blockSignals(True)
        self.combo_units.setCurrentText(label)
        self.combo_units.blockSignals(False)

    def on_global_units_changed(self, *_):
        """Global units combo changed: a set that follows 'Model display units' follows it here too."""
        self._series_cache.clear()
        self._conv_cache.clear()
        pset = self._current_set()
        if pset is not None and pset.get("units", MODEL_DISPLAY_UNITS) == MODEL_DISPLAY_UNITS:
            self._sync_units_combo()
        self._redraw()

    def _current_set(self):
        i = self.combo_sets.currentIndex()
        sets = self._sets()
        return sets[i] if 0 <= i < len(sets) else None

    def _current_case(self):
        name = self.combo_case.currentText()
        return name, self._case_data.get(name)

    def _on_mouse_move(self, event):
        if event.xdata is None or event.ydata is None:
            self.edit_horiz.clear()
            self.edit_vert.clear()
            return
        self.edit_horiz.setText(f"{event.xdata:.6g}")
        self.edit_vert.setText(f"{event.ydata:.6g}")

    def _message_plot(self, text):
        self.ax.text(0.5, 0.5, text, ha='center', va='center', wrap=True,
                     transform=self.ax.transAxes, color=COLORS["text_secondary"])
        self.canvas.draw_idle()

    def _series(self, case, ptype, conv):
        """Cached -> (x, y, default_xlabel, default_ylabel) in display units."""
        key = (case["case_name"], ptype, conv.length_unit_name, conv.force_unit_name)
        hit = self._series_cache.get(key)
        if hit is None:
            hit = self._series_uncached(case, ptype, conv)
            self._series_cache[key] = hit
        return hit

    def _conv(self):
        label = self.combo_units.currentText()
        c = self._conv_cache.get(label)
        if c is None:
            c = make_unit_converter(label)
            self._conv_cache[label] = c
        return c

    def _series_uncached(self, case, ptype, conv):
        """-> (x, y, default_xlabel, default_ylabel) in display units."""
        steps = case["steps"]
        disp = np.array([s["disp"] for s in steps])
        lu, fu = conv.length_unit_name, conv.force_unit_name

        if ptype == "Monitored Displacement vs Step Number":
            return (np.array([s["step"] for s in steps], dtype=float),
                    conv.to_display_length(disp),
                    "Step Number", f"Monitored Displacement ({lu})")

        x = conv.to_display_length(disp)
        xl = f"Displacement ({lu})"
        if ptype == "Base Reaction FX vs Monitored Displacement":
            return x, conv.to_display_force(np.array([s["Fx"] for s in steps])), xl, f"Base Reaction FX ({fu})"
        if ptype == "Base Reaction FY vs Monitored Displacement":
            return x, conv.to_display_force(np.array([s["Fy"] for s in steps])), xl, f"Base Reaction FY ({fu})"
        if ptype == "Base Reaction FZ vs Monitored Displacement":
            return x, conv.to_display_force(np.array([s["Fz"] for s in steps])), xl, f"Base Reaction FZ ({fu})"
        return x, conv.to_display_force(np.array([s["V_resultant"] for s in steps])), xl, f"Base Reaction ({fu})"

    @staticmethod
    def _case_steps(case):
        arr = case.get("_steps_arr")
        if arr is None:
            arr = np.array([int(s["step"]) for s in case["steps"]])
            case["_steps_arr"] = arr
        return arr

    def _range_color(self, i, base):
        c = self.RANGE_COLORS[i % len(self.RANGE_COLORS)]
        return base if (i == 0 or c is None) else c

    def _sync_range_rows(self):
        """Rebuild the rows from the stored ranges of the current case (default: all steps)."""
        for r in self._range_rows:
            self._rows_layout.removeWidget(r)
            r.setParent(None)
            r.deleteLater()
        self._range_rows = []
        name, case = self._current_case()
        self.grp_range.setEnabled(case is not None)
        if case is None:
            return
        steps = self._case_steps(case)
        ranges = self._ranges.get(name)
        if not ranges:
            ranges = [[int(steps[0]), int(steps[-1])]]
            self._ranges[name] = ranges
        for lo, hi in ranges:
            self._add_row(steps, lo, hi)
        self._update_range_buttons()

    def _add_row(self, steps, lo, hi):
        row = _StepRangeRow(steps, lo, hi)
        row.changed.connect(self._on_range_changed)
        row.removeRequested.connect(self._on_remove_range)
        self._rows_layout.addWidget(row)
        self._range_rows.append(row)

    def _update_range_buttons(self):
        for r in self._range_rows:
            r.set_removable(len(self._range_rows) > 1)
        self.btn_add_range.setEnabled(len(self._range_rows) < self.MAX_RANGES)

    def _store_ranges(self):
        name, case = self._current_case()
        if case is not None:
            self._ranges[name] = [list(r.values()) for r in self._range_rows]

    def _on_case_changed(self, *_):
        self._sync_range_rows()
        self._redraw()

    def _on_range_changed(self):
        self._store_ranges()
        self._schedule_update()

    def _on_add_range(self):
        name, case = self._current_case()
        if case is None or len(self._range_rows) >= self.MAX_RANGES:
            return
        steps = self._case_steps(case)
        self._add_row(steps, int(steps[0]), int(steps[-1]))
        self._store_ranges()
        self._update_range_buttons()
        self._redraw_keep_view()

    def _on_remove_range(self, row):
        if len(self._range_rows) <= 1 or row not in self._range_rows:
            return
        self._range_rows.remove(row)
        self._rows_layout.removeWidget(row)
        row.setParent(None)
        row.deleteLater()
        self._store_ranges()
        self._update_range_buttons()
        self._redraw_keep_view()

    def _on_reset_ranges(self):
        name, case = self._current_case()
        if case is None:
            return
        self._ranges.pop(name, None)
        self._sync_range_rows()
        self._redraw_keep_view()

    def _redraw_keep_view(self, *_):
        """Redraw without throwing away the user's zoom/pan (used while dragging the slider)."""
        self._keep_view = True
        try:
            self._redraw()
        finally:
            self._keep_view = False

    def _active_ref_curves(self, pset):
        """[(index, curve)] of the reference curves drawn on this plot (length-vs-force types only)."""
        if pset is None:
            return []
        axes = PLOT_TYPE_AXES.get(pset.get("plot_type"), PLOT_TYPE_AXES[PLOT_TYPES[0]])
        if axes != ("length", "force"):
            return []
        names = self._active_overlay(pset)
        return [(i, rc) for i, rc in enumerate(self._reference_curves()) if rc["name"] in names]

    def _ensure_ref_rows(self):
        """Rebuild the per-reference rows only when the set of drawn curves changes (never mid-drag)."""
        if not hasattr(self, "chk_sync"):
            return
        active = self._active_ref_curves(self._current_set())
        key = tuple((rc["name"], len(rc["x"])) for _, rc in active)
        if key == self._ref_key:
            return
        self._ref_key = key
        for r in self._ref_rows.values():
            self._ref_rows_layout.removeWidget(r)
            r.setParent(None)
            r.deleteLater()
        self._ref_rows = {}
        self.grp_ref.setVisible(bool(active))
        for i, rc in active:
            n = len(rc["x"])
            lo, hi = self._ref_ranges.get(rc["name"], [1, n])
            row = _StepRangeRow(np.arange(1, n + 1), lo, hi, title=rc["name"], unit="point", removable=False)
            row.set_color(rc.get("color") or self.OVERLAY_COLORS[i % len(self.OVERLAY_COLORS)])
            row.changed.connect(lambda name=rc["name"], r=row: self._on_ref_range_changed(name, r))
            row.setVisible(not self.chk_sync.isChecked())
            self._ref_rows_layout.addWidget(row)
            self._ref_rows[rc["name"]] = row

    def _on_ref_range_changed(self, name, row):
        self._ref_ranges[name] = list(row.values())
        self._schedule_update()

    def _on_sync_toggled(self, on):
        for r in self._ref_rows.values():
            r.setVisible(not on)
        self._redraw_keep_view()

    @staticmethod
    def _path_cum(u):
        """Cumulative path length travelled by a displacement history (starts at 0)."""
        u = np.asarray(u, dtype=float)
        if u.size == 0:
            return np.zeros(1)
        return np.concatenate(([0.0], np.cumsum(np.abs(np.diff(u)))))

    @staticmethod
    def _interp_window(rx, ry, s_ref, a, b):
        """Reference points between path positions a..b, with interpolated end points."""
        if b < a:
            a, b = b, a
        j0 = int(np.searchsorted(s_ref, a, side="right"))
        j1 = int(np.searchsorted(s_ref, b, side="left"))
        xa, xb = np.interp((a, b), s_ref, rx)
        ya, yb = np.interp((a, b), s_ref, ry)
        return (np.concatenate(([xa], rx[j0:j1], [xb])),
                np.concatenate(([ya], ry[j0:j1], [yb])))

    def _sync_window(self, case, x_vals, units_key, rx, ry, i_lo, i_hi):
        """
        Part of the reference curve that matches analysis points i_lo..i_hi (inclusive indices).

        Matching is by the distance travelled along the displacement path, NOT by step count:
        the solver takes a different number of sub-steps on every target (many more on the big
        cycles), so "same % of steps" drifts away from "same point of the loading history".
        """
        n_an = len(x_vals)
        key = ("path", case["case_name"], units_key)
        s_an = self._series_cache.get(key)
        if s_an is None:
            s_an = self._path_cum(np.concatenate(([0.0], x_vals)))                                             
            self._series_cache[key] = s_an
        s_ref = self._path_cum(rx)
        tot_an, tot_ref = float(s_an[-1]), float(s_ref[-1])
        if tot_an <= 0.0 or tot_ref <= 0.0:                                                               
            dn, n = max(1, n_an - 1), len(rx)
            a = int(round(i_lo / dn * (n - 1)))
            b = int(round(i_hi / dn * (n - 1)))
            return rx[a:b + 1], ry[a:b + 1]
        failed = bool(case.get("os_failed"))                                                                    
        scale = 1.0 if failed else tot_ref / tot_an
        a = 0.0 if i_lo <= 0 else float(s_an[i_lo + 1]) * scale
        b = tot_ref if (i_hi >= n_an - 1 and not failed) else float(s_an[i_hi + 1]) * scale
        return self._interp_window(rx, ry, s_ref, a, b)

    def _compute_state(self):
        pset = self._current_set()
        case_name, case = self._current_case()
        if pset is None or case is None or not case["steps"]:
            return None
        conv = self._conv()
        ptype = pset.get("plot_type")
        if ptype not in PLOT_TYPES:
            ptype = PLOT_TYPES[0]
        kx, ky = PLOT_TYPE_AXES[ptype]
        x_vals, y_vals, xlabel, ylabel = self._series(case, ptype, conv)
        if pset.get("label_x"):
            xlabel = pset["label_x"] if kx == "step" else f"{pset['label_x']} ({axis_unit_name(kx, conv)})"
        if pset.get("label_y"):
            ylabel = pset["label_y"] if ky == "step" else f"{pset['label_y']} ({axis_unit_name(ky, conv)})"

        steps_arr = self._case_steps(case)
        n_an = len(steps_arr)
        ranges = self._ranges.get(case_name) or [[int(steps_arr[0]), int(steps_arr[-1])]]
        partial = not (len(ranges) == 1 and ranges[0][0] <= steps_arr[0] and ranges[0][1] >= steps_arr[-1])
        an = []                                                                                               
        for lo, hi in ranges:
            an.append((int(np.searchsorted(steps_arr, lo, side="left")),
                       int(np.searchsorted(steps_arr, hi, side="right"))))

        sync = self.chk_sync.isChecked()
        units_key = (conv.length_unit_name, conv.force_unit_name)
        refs = []
        for i, rc in self._active_ref_curves(pset):
            rx = np.asarray(conv.to_display_length(np.asarray(rc["x"], dtype=float)), dtype=float)
            ry = np.asarray(conv.to_display_force(np.asarray(rc["y"], dtype=float)), dtype=float)
            n = len(rx)
            if sync:
                segs = [self._sync_window(case, x_vals, units_key, rx, ry, i0, i1 - 1)
                        for i0, i1 in an if i1 > i0]
                full = len(an) == 1 and an[0][0] <= 0 and an[0][1] >= n_an
            else:
                lo, hi = self._ref_ranges.get(rc["name"], [1, n])
                s0, s1 = max(0, lo - 1), min(n - 1, hi - 1)
                segs = [(rx[s0:s1 + 1], ry[s0:s1 + 1])]
                full = s0 <= 0 and s1 >= n - 1
            refs.append({"i": i, "rc": rc, "rx": rx, "ry": ry, "segs": segs, "full": full})

        sig = (case_name, pset["name"], ptype, units_key, len(an), partial, sync,
               self.chk_fade.isChecked(),
               tuple((r["rc"]["name"], r["full"], len(r["segs"])) for r in refs))
        return {"sig": sig, "pset": pset, "case_name": case_name, "case": case, "conv": conv,
                "kx": kx, "ky": ky, "x_vals": x_vals, "y_vals": y_vals,
                "xlabel": xlabel, "ylabel": ylabel, "ranges": ranges, "an": an,
                "partial": partial, "refs": refs}

    @staticmethod
    def _selected(st):
        """Visible parts of the analysis and reference curves (for 'Fit axes to range')."""
        sel_x, sel_y = [], []
        for r in st["refs"]:
            for xs, ys in r["segs"]:
                sel_x.append(xs)
                sel_y.append(ys)
        for i0, i1 in st["an"]:
            sel_x.append(st["x_vals"][i0:i1])
            sel_y.append(st["y_vals"][i0:i1])
        return sel_x, sel_y

    def _apply_limits(self, st):
        pset, conv, kx, ky = st["pset"], st["conv"], st["kx"], st["ky"]
        ref_partial = any(not r["full"] for r in st["refs"])
        if (st["partial"] or ref_partial) and self.chk_fit.isChecked():                                      
            sel_x, sel_y = self._selected(st)
            sel_x = [a for a in sel_x if a.size]
            sel_y = [a for a in sel_y if a.size]
            if sel_x:
                for setter, v in ((self.ax.set_xlim, np.concatenate(sel_x)),
                                  (self.ax.set_ylim, np.concatenate(sel_y))):
                    v_lo, v_hi = float(v.min()), float(v.max())
                    pad = 0.05 * (v_hi - v_lo) if v_hi > v_lo else max(abs(v_hi) * 0.05, 1e-9)
                    setter(v_lo - pad, v_hi + pad)
        if not pset.get("auto_x", True):
            lo, hi = (axis_to_display(kx, pset.get("x_min", 0.0), conv),
                      axis_to_display(kx, pset.get("x_max", 0.0), conv))
            if lo < hi:
                self.ax.set_xlim(lo, hi)
        if not pset.get("auto_y", True):
            lo, hi = (axis_to_display(ky, pset.get("y_min", 0.0), conv),
                      axis_to_display(ky, pset.get("y_max", 0.0), conv))
            if lo < hi:
                self.ax.set_ylim(lo, hi)

    def _pick_legend_loc(self, curves):
        """A fixed legend corner with the fewest data points under it ('best' is re-searched on every draw)."""
        try:
            x0, x1 = self.ax.get_xlim()
            y0, y1 = self.ax.get_ylim()
            dx, dy = (x1 - x0) or 1.0, (y1 - y0) or 1.0
            us, vs = [], []
            for x, y in curves:
                x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
                if x.size > 4000:
                    sel = np.linspace(0, x.size - 1, 4000).astype(int)
                    x, y = x[sel], y[sel]
                us.append((x - x0) / dx)
                vs.append((y - y0) / dy)
            u, v = np.concatenate(us), np.concatenate(vs)
            w, h = 0.45, 0.20
            boxes = {"upper left": (0, 1 - h, w, 1), "upper right": (1 - w, 1 - h, 1, 1),
                     "lower left": (0, 0, w, h), "lower right": (1 - w, 0, 1, h)}
            return min(boxes.items(),
                       key=lambda kv: np.count_nonzero((u >= kv[1][0]) & (u <= kv[1][2]) &
                                                       (v >= kv[1][1]) & (v <= kv[1][3])))[0]
        except Exception:
            return "best"

    def _on_resize_event(self, event):
        self._bg = None

    def _on_draw_event(self, event):
        """After every normal draw: snapshot the static part, then draw the animated artists on top."""
        if self._art is None:
            self._bg = None
            return
        self._bg = self.canvas.copy_from_bbox(self.figure.bbox)
        self._draw_animated()

    def _draw_animated(self):
        art = self._art
        if art:
            for a in art["animated"]:
                self.figure.draw_artist(a)

    def _schedule_update(self):
        """Coalesce bursts of slider events into one update per event-loop turn."""
        if not self._upd_pending:
            self._upd_pending = True
            QTimer.singleShot(0, self._flush_update)

    def _apply_state(self, st, art):
        x_vals, y_vals = st["x_vals"], st["y_vals"]
        for k, (i0, i1) in enumerate(st["an"]):
            xs, ys = x_vals[i0:i1], y_vals[i0:i1]
            art["an_lines"][k].set_data(xs, ys)
            dot = art["an_dots"][k]
            if dot is not None:
                dot.set_data(xs[-1:], ys[-1:])
        for ci, r in enumerate(st["refs"]):
            for k, (xs, ys) in enumerate(r["segs"]):
                art["ref_lines"][ci][k].set_data(xs, ys)
                dot = art["ref_dots"][ci][k]
                if dot is not None:
                    dot.set_data(xs[-1:], ys[-1:])
        leg = art.get("leg")
        if leg is not None and st["partial"]:
            texts = leg.get_texts()
            for k, ti in enumerate(art["legend_an"]):
                if ti < len(texts):
                    lo, hi = st["ranges"][k]
                    texts[ti].set_text(f"Analysis: {st['case_name']} (steps {lo}-{hi})")

    def _flush_update(self):
        self._upd_pending = False
        art = self._art
        if art is None:
            self._redraw_keep_view()
            return
        st = self._compute_state()
        if st is None or st["sig"] != art["sig"]:                                                               
            self._redraw_keep_view()
            return
        self._apply_state(st, art)
        ref_partial = any(not r["full"] for r in st["refs"])
        if (st["partial"] or ref_partial) and self.chk_fit.isChecked():
            if not self.nav.user_zoomed:                                                             
                self._apply_limits(st)
                self._bg = None
                self.canvas.draw_idle()
                return
        if self._bg is None:
            self.canvas.draw_idle()
            return
        self.canvas.restore_region(self._bg)
        self._draw_animated()
        self.canvas.blit(self.figure.bbox)

    def _redraw(self, *_):
        self._ensure_ref_rows()
        self._refresh_metrics()
        keep_view = self._keep_view and self.nav.user_zoomed
        saved_view = (self.ax.get_xlim(), self.ax.get_ylim()) if keep_view else None
        self._art = None
        self._bg = None
        self.ax.clear()
        style_plot_axes(self.figure, self.ax)
        self.lbl_notes.hide()

        pset = self._current_set()
        if pset is None:
            self._message_plot("No pushover parameter sets defined.\nSee Define > Pushover Parameter Sets.")
            return

        case_name, case = self._current_case()
        if case is None or not case["steps"]:
            self._message_plot("No pushover results for this case.\n"
                               "Run a Nonlinear Static case with Displacement Control\n"
                               "and Results Saved = Multiple States.")
            return

        st = self._compute_state()
        conv, x_vals, y_vals = st["conv"], st["x_vals"], st["y_vals"]
        fade = self.chk_fade.isChecked()
        partial = st["partial"]
        art = {"sig": st["sig"], "an_lines": [], "an_dots": [], "ref_lines": [], "ref_dots": [],
               "animated": [], "legend_an": [], "leg": None}

        def _animated(artist):
            artist.set_animated(True)
            art["animated"].append(artist)
            return artist

        drawn_overlay = False
        n_ref_entries = 0
        for r in st["refs"]:
            rc, i = r["rc"], r["i"]
            color = rc.get("color") or self.OVERLAY_COLORS[i % len(self.OVERLAY_COLORS)]
            rlw, rls = rc.get("linewidth", 1.2), rc.get("linestyle", "--")
            if not r["full"]:
                self.ax.plot(r["rx"], r["ry"], color=color, linewidth=rlw, linestyle=rls, zorder=1,
                             alpha=0.12 if fade else 0.0, label="_nolegend_")
            lines, dots = [], []
            for k, (xs, ys) in enumerate(r["segs"]):
                (ln,) = self.ax.plot(xs, ys, color=color, linewidth=rlw, linestyle=rls, zorder=1,
                                     label=rc["name"] if k == 0 else "_nolegend_")
                lines.append(_animated(ln))
                dot = None
                if not r["full"]:
                    (dot,) = self.ax.plot(xs[-1:], ys[-1:], marker="o", markersize=4, color=color,
                                          linestyle="none", zorder=2, label="_nolegend_")
                    _animated(dot)
                dots.append(dot)
            art["ref_lines"].append(lines)
            art["ref_dots"].append(dots)
            if r["segs"]:
                n_ref_entries += 1
            drawn_overlay = True

        base_color = pset.get("curve_color") or COLORS["accent"]
        lw, ls = pset.get("curve_width", 2.2), pset.get("curve_style", "-")
        for i, row in enumerate(self._range_rows):
            row.set_color(self._range_color(i, base_color))

        if partial:                                                                               
            self.ax.plot(x_vals, y_vals, color=base_color, linewidth=lw, linestyle=ls, zorder=2,
                         alpha=0.15 if fade else 0.0, label="_nolegend_")
        for k, ((i0, i1), (lo, hi)) in enumerate(zip(st["an"], st["ranges"])):
            color = self._range_color(k, base_color)
            label = f"Analysis: {st['case_name']} (steps {lo}-{hi})" if partial else f"Analysis: {st['case_name']}"
            xs, ys = x_vals[i0:i1], y_vals[i0:i1]
            (ln,) = self.ax.plot(xs, ys, color=color, linewidth=lw, linestyle=ls, marker=None,
                                 solid_capstyle='round', zorder=3, label=label)
            art["an_lines"].append(_animated(ln))
            dot = None
            if partial:                                              
                (dot,) = self.ax.plot(xs[-1:], ys[-1:], marker="o", markersize=5, color=color,
                                      linestyle="none", zorder=4, label="_nolegend_")
                _animated(dot)
            art["an_dots"].append(dot)
            art["legend_an"].append(n_ref_entries + k)

        self.ax.axhline(0, color=COLORS["text_secondary"], lw=0.8)
        self.ax.axvline(0, color=COLORS["text_secondary"], lw=0.8)
        self.ax.ticklabel_format(style="sci", axis="both", scilimits=(-2, 4), useMathText=True)
        self.ax.set_xlabel(st["xlabel"])
        self.ax.set_ylabel(st["ylabel"])
        self.ax.set_title(f"{pset['name']}  -  Case: {case_name}  (Joint {case['node_id']}, {case['dof_name']})",
                          fontsize=9)

        self._apply_limits(st)

        if drawn_overlay or partial:
            curves = [(x_vals, y_vals)] + [(r["rx"], r["ry"]) for r in st["refs"]]
            leg = self.ax.legend(fontsize=8, loc=self._pick_legend_loc(curves))
            art["leg"] = _animated(leg)

        notes = (pset.get("notes") or "").strip()
        if case.get("os_failed"):
            u_stop = conv.to_display_length(case["steps"][-1]["disp"])
            fail_note = (f"Analysis stopped at u = {u_stop:.6g} {conv.length_unit_name} "
                         f"(OpenSees did not converge); only the converged part of the curve is shown.")
            notes = f"{notes}\n{fail_note}" if notes else fail_note
        if notes:
            self.lbl_notes.setText(notes)
            self.lbl_notes.show()

        art["animated"].sort(key=lambda a: a.get_zorder())
        self.figure.tight_layout()
        if keep_view:
            self.ax.set_xlim(*saved_view[0])
            self.ax.set_ylim(*saved_view[1])
        else:
            self.nav.mark_home()
        self._art = art
        self.canvas.draw_idle()

    def _on_metrics_toggled(self, on):
        """Show/hide the metrics panel and grow/shrink the dialog by the panel's width."""
        panel = self.metrics_panel
        w0 = self.width()                                                                                       
        if on:
            self._refresh_metrics()
            w = max(panel.minimumWidth(), 520)
            panel.setFixedWidth(w)
            panel.show()
            self.resize(w0 + w + 8, self.height())
            self.btn_metrics.setText("<< Metrics")
        else:
            w = panel.width() + 8
            panel.hide()
            self.layout().invalidate()
            self.layout().activate()                                                                                         
            self.resize(w0 - w, self.height())
            self.btn_metrics.setText("Metrics >>")

    def _metrics_xy(self, case, ptype, conv):
        """(x, y, note) of the analysis curve for the metrics, in display units. Uses the full OpenSees
        history (every solver step) when the plotted quantity is the resultant base shear."""
        hist = case.get("history")
        if hist is not None and ptype == PLOT_TYPES[0]:
            return (np.asarray(conv.to_display_length(hist["u"]), dtype=float),
                    np.asarray(conv.to_display_force(hist["V"]), dtype=float),
                    f"Analysis: {len(hist['u'])} points (every solver step).")
        x, y, _xl, _yl = self._series(case, ptype, conv)
        return (np.asarray(x, dtype=float), np.asarray(y, dtype=float),
                f"Analysis: {len(x)} points (saved states only; save all steps for exact energy).")

    def _refresh_metrics(self):
        """Feed the panel. Skipped while hidden; cached so a redraw that changes nothing costs nothing."""
        panel = self.metrics_panel
        if not panel.isVisible() and not self.btn_metrics.isChecked():
            return
        pset = self._current_set()
        case_name, case = self._current_case()
        if pset is None or case is None or not case["steps"]:
            self._metrics_key = None
            panel.set_data(None)
            return
        ptype = pset.get("plot_type")
        if ptype not in PLOT_TYPES:
            ptype = PLOT_TYPES[0]
        if PLOT_TYPE_AXES[ptype] != ("length", "force"):
            self._metrics_key = None
            panel.set_data(None)
            panel.lbl_note.setText("Metrics need a force-vs-displacement plot type "
                                   "(pick another Pushover Parameters set).")
            return
        conv = self._conv()
        refs = self._active_ref_curves(pset)
        key = (case_name, ptype, conv.length_unit_name, conv.force_unit_name,
               tuple((rc["name"], len(rc["x"])) for _, rc in refs))
        if key == self._metrics_key:
            return
        self._metrics_key = key
        x, y, note = self._metrics_xy(case, ptype, conv)
        ref_data = [(rc["name"],
                     conv.to_display_length(np.asarray(rc["x"], dtype=float)),
                     conv.to_display_force(np.asarray(rc["y"], dtype=float))) for _, rc in refs]
        notes = [note]
        if not ref_data:
            notes.append("Turn on a reference curve (Reference Curves button) to compare with it.")
        panel.set_data((x, y), ref_data, x_unit=conv.length_unit_name, y_unit=conv.force_unit_name,
                       primary_name=f"Analysis", notes=notes)

    def _on_export_csv(self):
        pset = self._current_set()
        if pset is None:
            return
        case_name, case = self._current_case()
        if case is None:
            return
        default_path = f"{self.base_name}_{case_name}_pushover.csv"
        path, _ = QFileDialog.getSaveFileName(self, "Export Pushover Curve", default_path, "CSV Files (*.csv)")
        if not path:
            return
        conv = make_unit_converter(self.combo_units.currentText())
        lu, fu = conv.length_unit_name, conv.force_unit_name
        with open(path, 'w') as f:
            f.write(f"Step,Monitored Displacement ({lu}),"
                    f"Base Reaction FX ({fu}),"
                    f"Base Reaction FY ({fu}),"
                    f"Resultant Base Shear ({fu}),"
                    f"Base Reaction FZ ({fu})\n")
            for s in case["steps"]:
                f.write(f"{s['step']},{conv.to_display_length(s['disp']):.6g},"
                        f"{conv.to_display_force(s['Fx']):.6g},{conv.to_display_force(s['Fy']):.6g},"
                        f"{conv.to_display_force(s['V_resultant']):.6g},{conv.to_display_force(s['Fz']):.6g}\n")
