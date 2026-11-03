"""Read the recorded OpenSees integration-section and fiber responses.

This viewer is deliberately independent of the native hinge result reader.
Only converged, saved solver points are plotted; missing responses stay gaps.
OpenSees local y=-OpenCivil local 3 and z=OpenCivil local 2, so M2=Mz,
M3=-My (and the corresponding curvatures use the same signs).

Fiber map convention (one place: _to_display): a recorded fiber (y, z) is shown at
x = -y (= OpenCivil coord 3, horizontal) and y = z (= OpenCivil coord 2, vertical),
the same layout as the native hinge dialog. The map also draws the model's section
outline and rebar layout underneath, and _build_geometry checks that the recorded
fibers really sit on that layout, so a wrong y/z convention in the recorder shows up.
"""

import csv
import json
import math
import os

import numpy as np
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QFileDialog,
    QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QMessageBox,
    QPushButton, QSlider, QSpinBox, QTableWidget, QTableWidgetItem,
    QTabWidget, QVBoxLayout, QWidget,
)
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import Circle, Polygon
from matplotlib.path import Path
from matplotlib.ticker import MaxNLocator

from app.ui.theme import (apply_dialog_style, style_plot_axes, style_legend, PlotNavigator, COLORS,
                          plot_color, on_theme_changed, off_theme_changed, section_map_palette)
from core.units import make_unit_converter, UNIT_SYSTEMS

TAG_COLORS = ["#1f77b4", "#ff7f0e", "#2ca02c", "#9467bd", "#17becf",
              "#8c564b", "#e377c2", "#bcbd22", "#7f7f7f", "#d62728"]
REBAR_PICK_PX = 10                                          
FIBER_PICK_PX = 6                                                    
PICK_FALLBACK_PX = 20                                                          

def _vector(value, size, exact=False):
    """Return a finite numeric vector, or None; never fabricate a response."""
    try:
        result = np.asarray(value, dtype=float)
        if result.ndim != 1 or len(result) < size or (exact and len(result) != size):
            return None
        if not np.isfinite(result).all():
            return None
        return result
    except (TypeError, ValueError, OverflowError):
        return None

def _number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None

def _to_display(y, z):
    """Recorded OpenSees fiber (y, z) -> map position (OpenCivil coord 3, coord 2).
    Every place that shows or picks a fiber goes through this, so a convention
    fix is a one-line change here."""
    return -y, z

def _tag_text(fiber):
    tag = fiber.get("material_tag")
    return "Unknown" if tag is None or tag == "" else str(tag)

def _explicit_kind(fiber):
    """Kind written by the recorder (any of these keys), else None."""
    for key in ("kind", "type", "role", "region", "label", "name"):
        value = fiber.get(key)
        if not isinstance(value, str):
            continue
        text = value.lower()
        if any(word in text for word in ("rebar", "steel", "reinf", "bar")):
            return "Rebar"
        if "core" in text or "confin" in text:
            return "Core concrete"
        if "cover" in text or "unconf" in text:
            return "Cover concrete"
        if "concrete" in text:
            return "Concrete"
    return None

_FRAME_OPS = (
    ("as plotted", ((1, 0), (0, 1))),
    ("mirrored left-right (x -> -x)", ((-1, 0), (0, 1))),
    ("mirrored up-down (y -> -y)", ((1, 0), (0, -1))),
    ("rotated 180 degrees", ((-1, 0), (0, -1))),
    ("local 2 and 3 swapped (x <-> y)", ((0, 1), (1, 0))),
    ("rotated 90 degrees counter-clockwise", ((0, -1), (1, 0))),
    ("rotated 90 degrees clockwise", ((0, 1), (-1, 0))),
    ("swapped and rotated 180 degrees", ((0, -1), (-1, 0))),
)

def _model_section(model, section):
    """The model Section object (outline, rebar) behind a recorded section, or None."""
    secs = getattr(model, "sections", None) or {}
    try:
        found = secs.get(section.get("section_name"))
    except AttributeError:
        found = None
    if found is not None and hasattr(found, "get_shape_coords"):
        return found
    els = getattr(model, "elements", None) or {}
    eid = section.get("element_id")
    element = els.get(eid, els.get(str(eid)))
    if element is None:
        return None
    for attr in ("sec_name", "section_name", "section"):
        value = getattr(element, attr, None)
        if value is None:
            continue
        if hasattr(value, "get_shape_coords"):
            return value
        if isinstance(value, str) and value in secs:
            return secs[value]
    return None

def _match_rebars(pts, area, rebars):
    """Fiber index sitting on each model bar, or None. A hit needs a fiber within the bar's
    tolerance whose area is within 4x of the bar area (a concrete cell is not a bar)."""
    hits = []
    for rx, ry, dia in rebars:
        distance = np.hypot(pts[:, 0] - rx, pts[:, 1] - ry)
        tol = max(0.75 * dia, 0.005)
        bar_area = math.pi * dia * dia / 4.0
        near = np.flatnonzero(distance <= tol)
        if bar_area > 0:
            near = near[(area[near] >= 0.25 * bar_area) & (area[near] <= 4.0 * bar_area)]
        if near.size == 0:
            hits.append(None)
            continue
        cost = distance[near] / tol
        if bar_area > 0:
            cost = cost + 0.5 * np.abs(area[near] / bar_area - 1.0)
        hits.append(int(near[np.argmin(cost)]))
    return hits

def _build_geometry(model, section):
    """Fiber positions in map frame, kinds (Rebar / Concrete / ...), the model outline and rebar
    layout, and a warning when the recorded fibers do not sit on that layout."""
    fibers = section.get("fibers", [])
    pts = np.array([_to_display(float(f["y"]), float(f["z"])) for f in fibers], float).reshape(-1, 2)
    area = np.array([float(f["area"]) for f in fibers], float)
    outline, rebars = [], []
    sec = _model_section(model, section)
    if sec is not None:
        try:
            outline = [(float(p[0]), float(p[1])) for p in (sec.get_shape_coords() or [])]
        except Exception:
            outline = []
        try:
            from core.properties import compute_rebar_positions
            rebars = [(float(r[0]), float(r[1]), float(r[2]))
                      for r in compute_rebar_positions(sec, getattr(model, "rebar_sizes", []))]
        except Exception:
            rebars = []
    tie = None
    reinf = getattr(sec, "reinforcement", None) if sec is not None else None
    if reinf is not None and getattr(sec, "b", None) is not None:
        try:
            tie_dia = 0.01
            for r in getattr(model, "rebar_sizes", []) or []:
                if r.get("id") == reinf.tie_bar_size:
                    tie_dia = r.get("diameter", 0.01)
                    break
            off = reinf.clear_cover + tie_dia / 2.0
            cb, ch = sec.b - 2 * off, sec.h - 2 * off
            if cb > 0 and ch > 0:
                tie = [(cb / 2, ch / 2), (-cb / 2, ch / 2), (-cb / 2, -ch / 2), (cb / 2, -ch / 2)]
        except Exception:
            tie = None
    path = Path(np.array(outline, float)) if len(outline) >= 3 else None

    def score(matrix):
        moved = pts @ np.asarray(matrix, float).T
        parts, hits = [], []
        if rebars:
            hits = _match_rebars(moved, area, rebars)
            parts.append(sum(h is not None for h in hits) / len(rebars))
        if path is not None and len(moved):
            parts.append(float(np.mean(path.contains_points(moved))))
        return (float(np.mean(parts)) if parts else None), hits

    warning, use_hits = None, []
    if len(pts) and (rebars or path is not None):
        results = [score(matrix) for _name, matrix in _FRAME_OPS]
        scores = [r[0] for r in results]
        best = int(np.argmax(scores))
        if scores[0] >= scores[best] - 0.02:
            best = 0
        if best != 0 and scores[best] >= 0.8:
            warning = ("Fiber positions do not line up with the model's section outline / rebar layout "
                       f"as plotted, but they do when the fibers are {_FRAME_OPS[best][0]}. "
                       "Check the OpenSees recorder's y/z convention "
                       "(assumed: y = -local 3, z = local 2).")
            use_hits = results[best][1]
        else:
            use_hits = results[0][1]
            if scores[0] < 0.8:
                warning = (f"Fiber positions only partly agree with the model's section outline / rebar "
                           f"layout ({100 * scores[0]:.0f}% match, no orientation fits). The section may "
                           "have changed since the analysis ran, or the recorder wrote different geometry.")
    kinds = [_explicit_kind(f) for f in fibers]
    for hit in use_hits:
        if hit is not None:
            kinds[hit] = "Rebar"
    matched_bars = sum(h is not None for h in use_hits)
    know_concrete = bool(rebars) and matched_bars >= 0.5 * len(rebars)
    kinds = [k or ("Concrete" if know_concrete else "Fiber") for k in kinds]
    return {"xy": pts, "area": area, "kind": kinds, "tags": [_tag_text(f) for f in fibers],
            "outline": outline, "rebars": rebars, "tie": tie,
            "name": str(getattr(sec, "name", "") or section.get("section_name") or ""),
            "warning": warning}

def _load_opensees_case(path, case_name):
    """Load an engine-tagged case with section metadata, preserving saved order."""
    try:
        with open(path, encoding="utf-8-sig") as stream:
            data = json.load(stream)
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(data, dict) or data.get("status") != "SUCCESS":
        return None
    info = data.get("info")
    if not isinstance(info, dict) or info.get("type") != "Nonlinear Static":
        return None
    if info.get("engine") != "opensees":
        return None
    raw_sections = info.get("opensees_hinge_sections")
    if not isinstance(raw_sections, dict) or not raw_sections:
        return None
    warnings = []
    if info.get("failed_steps"):
        warnings.append("Analysis stopped early. These are partial results through the last converged state.")
    for source in ("opensees_hinge_warnings", "hinge_warnings"):
        values = info.get(source) or []
        if isinstance(values, str):
            values = [values]
        if isinstance(values, list):
            warnings.extend(str(value) for value in values)
    sections = {}
    for key, section in raw_sections.items():
        if not isinstance(section, dict) or section.get("element_id") is None:
            warnings.append(f"Section {key}: invalid section metadata.")
            continue
        fibers = section.get("fibers", [])
        if not isinstance(fibers, list) or any(
            not isinstance(fiber, dict)
            or any(_number(fiber.get(field)) is None for field in ("y", "z", "area"))
            or float(fiber["area"]) <= 0
            for fiber in fibers
        ):
            warnings.append(f"Section {key}: invalid fiber geometry; this section was skipped.")
            continue
        sections[str(key)] = section
    if not sections:
        return None
    raw_steps = data.get("saved_states")
    steps = []
    if isinstance(raw_steps, list):
        for index, state in enumerate(raw_steps):
            state = state if isinstance(state, dict) else {}
            records = state.get("hinge_states")
            steps.append({
                "step": state.get("step", index),
                "factor": state.get("load_factor", state.get("factor")),
                "records": records if isinstance(records, dict) else {},
            })
    has_record = any(any(key in step["records"] for key in sections) for step in steps)
    if has_record:
                                                                                 
        steps = [step for step in steps if any(key in step["records"] for key in sections)]
    final_records = data.get("hinge_states")
    if not has_record and isinstance(final_records, dict):
        steps = [{"step": "Final", "factor": None, "records": final_records}]
        has_record = any(key in final_records for key in sections)
    if not has_record:
        return None
    return {"case_name": case_name, "sections": sections, "steps": steps,
            "warnings": warnings}

def _section_history(case, key):
    """Use NaN rows for unrecorded data so matplotlib displays honest gaps."""
    section = case["sections"][key]
    count, fibers = len(case["steps"]), len(section.get("fibers", []))
    deformations = np.full((count, 3), np.nan)
    forces = np.full((count, 3), np.nan)
    strains = np.full((count, fibers), np.nan)
    stresses = np.full((count, fibers), np.nan)
    missing_section = missing_fiber = 0
    for index, step in enumerate(case["steps"]):
        record = step["records"].get(key)
        record = record if isinstance(record, dict) else {}
        deformation = _vector(record.get("section_deformation"), 3)
        force = _vector(record.get("section_force"), 3)
        if deformation is not None:
            deformations[index] = deformation[:3]
        if force is not None:
            forces[index] = force[:3]
        if deformation is None or force is None:
            missing_section += 1
        strain = _vector(record.get("fiber_strain"), fibers, exact=True)
        stress = _vector(record.get("fiber_stress"), fibers, exact=True)
        if fibers and strain is not None:
            strains[index] = strain
        if fibers and stress is not None:
            stresses[index] = stress
        if fibers and (strain is None or stress is None):
            missing_fiber += 1
    return {"d": deformations, "force": forces, "strain": strains,
            "stress": stresses, "missing_section": missing_section,
            "missing_fiber": missing_fiber}

class _Blitter:
    """Redraws only the animated artists (trail + selected-state marker) over a cached background,
    so moving the slider never redraws the whole figure."""

    def __init__(self, canvas, axes):
        self.canvas, self.axes = canvas, axes
        self.artists = []
        self.background = None
        canvas.mpl_connect("draw_event", self._on_draw)

    def reset(self, artists):
        self.artists = list(artists)
        self.background = None

    def _draw_artists(self):
        for artist in self.artists:
            self.axes.draw_artist(artist)

    def _on_draw(self, _event=None):
        self.background = self.canvas.copy_from_bbox(self.canvas.figure.bbox)
        self._draw_artists()

    def update(self):
        canvas = self.canvas
        if self.background is None:
            canvas.draw_idle()
            return
        try:
            canvas.restore_region(self.background)
            self._draw_artists()
            canvas.blit(canvas.figure.bbox)
        except Exception:
            self.background = None
            canvas.draw_idle()

def _fmt(value):
    return f"{value:.6g}" if math.isfinite(value) else "Unavailable"

class OpenSeesHingeResultsDialog(QDialog):
    """Section/hinge and fiber histories from OpenSees, without native backbones."""

    def __init__(self, parent, model, base_name, case_paths,
                 selected_element_ids=None, animation_manager=None):
        super().__init__(parent)
        self.setWindowTitle("Hinge / Section Results — OpenSees")
        self.resize(1120, 800)
        apply_dialog_style(self)
        self.model = model
        self.base_name = base_name
        self._selected_ids = {str(value) for value in (selected_element_ids or [])}
        self._cases = {}
        self._histories = {}
        self._geo_cache = {}
        self._fiber_index = 0
        self._ring = None
        self.build_warnings = []
        for name, path in case_paths.items():
            case = _load_opensees_case(path, name)
            if case is not None:
                self._cases[name] = case
        self.status = "ok" if self._cases else "no_hinge_results"
        if self.status != "ok":
            self.build_warnings = [
                "No successful OpenSees nonlinear static result contains recorded "
                "section responses. Run the OpenSees analysis again to record them."
            ]
            return
        self._build_ui()

    def _build_ui(self):
        self._map_key = None
        self._ring = None
        self._dirty = {"section": True, "fiber": True}
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._render)
        outer = QVBoxLayout(self)
        top = QGridLayout()
        self.combo_case = QComboBox()
        self.combo_case.addItems(sorted(self._cases))
        self.combo_section = QComboBox()
        self.chk_selected_only = QCheckBox("Only sections on selected frames")
        self.chk_selected_only.setEnabled(bool(self._selected_ids))
        self.combo_units = QComboBox()
        self.combo_units.addItems(list(UNIT_SYSTEMS))
        self.combo_units.setCurrentText("kN, m, C")
        top.addWidget(QLabel("Load case"), 0, 0)
        top.addWidget(self.combo_case, 0, 1)
        top.addWidget(QLabel("Units"), 0, 2)
        top.addWidget(self.combo_units, 0, 3)
        top.addWidget(QLabel("Section"), 1, 0)
        top.addWidget(self.combo_section, 1, 1, 1, 3)
        top.addWidget(self.chk_selected_only, 2, 1, 1, 3)
        outer.addLayout(top)
        self.lbl_section = QLabel()
        self.lbl_section.setWordWrap(True)
        outer.addWidget(self.lbl_section)
        step_row = QHBoxLayout()
        step_row.addWidget(QLabel("Saved state"))
        self.slider_step = QSlider(Qt.Orientation.Horizontal)
        self.spin_step = QSpinBox()
        self.lbl_step = QLabel()
        step_row.addWidget(self.slider_step, 1)
        step_row.addWidget(self.spin_step)
        step_row.addWidget(self.lbl_step)
        outer.addLayout(step_row)
        self.lbl_warning = QLabel()
        self.lbl_warning.setWordWrap(True)
        self.lbl_warning.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        outer.addWidget(self.lbl_warning)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_section_tab(), "Section / Hinge Response")
        self.tabs.addTab(self._build_fiber_tab(), "Fiber Response")
        outer.addWidget(self.tabs, 1)
        footer = QHBoxLayout()
        note = QLabel("Recorded solver points. ABCDE hinge states are not defined for these OpenSees materials.")
        note.setWordWrap(True)
        footer.addWidget(note, 1)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        footer.addWidget(close)
        outer.addLayout(footer)
        self.combo_case.currentIndexChanged.connect(self._case_changed)
        self.combo_section.currentIndexChanged.connect(self._section_changed)
        self.chk_selected_only.toggled.connect(self._populate_sections)
        self.combo_units.currentIndexChanged.connect(self._units_changed)
        self.slider_step.valueChanged.connect(self._step_changed)
        self.spin_step.valueChanged.connect(self._step_changed)
        self.tabs.currentChanged.connect(lambda _i: self._render())
        self._relayout_timer = QTimer(self)
        self._relayout_timer.setSingleShot(True)
        self._relayout_timer.setInterval(120)
        self._relayout_timer.timeout.connect(self._relayout_all)
        for canvas in (self.h_canvas, self.f_canvas, self.s_canvas):
            canvas.mpl_connect("resize_event", lambda _event: self._relayout_timer.start())
        self._case_changed()
        on_theme_changed(self._on_theme_changed)

    def _on_theme_changed(self, _name):
        """Light/Dark switched while open: restyle widgets and rebuild every plot."""
        apply_dialog_style(self)
        self._style_fiber_table()
        self._map_key = None
        self._refresh()

    def _style_fiber_table(self):
        self.f_table.setStyleSheet(f"QTableWidget {{ color: {COLORS['text_primary']}; }}")

    def done(self, r):
        off_theme_changed(self._on_theme_changed)
        super().done(r)

    @staticmethod
    def _relayout(figure):
        try:
            figure.tight_layout()
        except Exception:
            pass

    def _relayout_all(self):
        for figure, canvas in ((self.h_fig, self.h_canvas), (self.f_fig, self.f_canvas),
                               (self.s_fig, self.s_canvas)):
            if canvas.isVisible():
                self._relayout(figure)
                canvas.draw_idle()

    @staticmethod
    def _plot():
        figure = Figure(figsize=(5, 4))
        canvas = FigureCanvas(figure)
        axes = figure.add_subplot(111)
        style_plot_axes(figure, axes)
        return figure, canvas, axes

    def _build_section_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        row = QHBoxLayout()
        self.combo_dof = QComboBox()
        self.combo_dof.addItems(["M2", "M3"])
        self.chk_rotation = QCheckBox("End-section rotation contribution (curvature × Lp)")
        self.chk_rotation.setToolTip("At a HingeRadau end section, curvature times its integration weight Lp is this section's contribution to rotation. It is not the total end-region or plastic rotation.")
        row.addWidget(QLabel("Bending axis"))
        row.addWidget(self.combo_dof)
        row.addWidget(self.chk_rotation)
        row.addStretch(1)
        export = QPushButton("Export section history…")
        export.clicked.connect(lambda: self._export(False))
        row.addWidget(export)
        layout.addLayout(row)
        self.h_fig, self.h_canvas, self.h_ax = self._plot()
        self.h_nav = PlotNavigator(self.h_canvas, self.h_ax)
        self._h_blit = _Blitter(self.h_canvas, self.h_ax)
        layout.addWidget(self.h_canvas, 1)
        self.lbl_response = QLabel()
        self.lbl_response.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.lbl_response)
        self.combo_dof.currentIndexChanged.connect(self._refresh)
        self.chk_rotation.toggled.connect(self._refresh)
        return widget

    def _build_fiber_tab(self):
        widget = QWidget()
        layout = QHBoxLayout(widget)
        left = QVBoxLayout()
        self.f_table = QTableWidget(0, 8)
        self._style_fiber_table()
        self.f_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.f_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.f_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.f_table.verticalHeader().setVisible(False)
        self.f_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.f_table.itemSelectionChanged.connect(self._fiber_selected)
        left.addWidget(self.f_table, 2)
        self.s_fig, self.s_canvas, self.s_ax = self._plot()
        self.s_canvas.setMinimumHeight(220)
        self.s_canvas.mpl_connect("button_press_event", self._map_clicked)
        self.s_nav = PlotNavigator(self.s_canvas, self.s_ax, pan_buttons=(2, 3))
        self.s_canvas.setToolTip("Left-click: pick a fiber (rebar first; click it again for the concrete under it)   |   "
                                 "Mouse wheel: zoom   |   Right/middle-drag: pan   |   Double-click: reset view")
        left.addWidget(self.s_canvas, 3)
        self.chk_hide_reinf = QCheckBox("Hide reinforcement / confinement (fibers only)")
        self.chk_hide_reinf.toggled.connect(self._outline_toggled)
        left.addWidget(self.chk_hide_reinf)
        layout.addLayout(left, 4)
        right = QVBoxLayout()
        self.f_fig, self.f_canvas, self.f_ax = self._plot()
        self.f_nav = PlotNavigator(self.f_canvas, self.f_ax)
        self._f_blit = _Blitter(self.f_canvas, self.f_ax)
        right.addWidget(self.f_canvas, 1)
        self.lbl_fiber = QLabel()
        self.lbl_fiber.setWordWrap(True)
        self.lbl_fiber.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        right.addWidget(self.lbl_fiber)
        self.btn_export_fiber = QPushButton("Export selected fiber history…")
        self.btn_export_fiber.clicked.connect(lambda: self._export(True))
        right.addWidget(self.btn_export_fiber)
        layout.addLayout(right, 5)
        return widget

    def _case(self):
        return self._cases.get(self.combo_case.currentText())

    def _section(self):
        case, key = self._case(), self.combo_section.currentData()
        return case["sections"].get(key) if case else None

    def _history(self):
        key = self.combo_section.currentData()
        case = self._case()
        if not case or key is None:
            return None
        cache_key = (case["case_name"], key)
        if cache_key not in self._histories:
            self._histories[cache_key] = _section_history(case, key)
        return self._histories[cache_key]

    def _units(self):
        units = make_unit_converter(self.combo_units.currentText())
        return {"L": units.length_scale, "F": units.force_scale,
                "M": units.force_scale * units.length_scale,
                "S": units.force_scale / units.length_scale ** 2,
                "length": units.length_unit_name,
                "moment": f"{units.force_unit_name}·{units.length_unit_name}",
                "stress": f"{units.force_unit_name}/{units.length_unit_name}²"}

    def _case_changed(self, *_):
        count = len(self._case()["steps"])
        for widget in (self.slider_step, self.spin_step):
            widget.blockSignals(True)
            widget.setRange(0, max(0, count - 1))
            widget.setValue(count - 1)
            widget.blockSignals(False)
        self._populate_sections()

    def _populate_sections(self, *_):
        case = self._case()
        old_key = self.combo_section.currentData()
        self.combo_section.blockSignals(True)
        self.combo_section.clear()
        for key, section in case["sections"].items():
            if self.chk_selected_only.isChecked() and str(section["element_id"]) not in self._selected_ids:
                continue
            text = (f"Frame {section['element_id']} — {section.get('section_name', 'Section')} "
                    f"— integration point {section.get('section_index', '?')} "
                    f"(element {section.get('element_tag', '?')})")
            self.combo_section.addItem(text, key)
        old_index = self.combo_section.findData(old_key)
        if old_index >= 0:
            self.combo_section.setCurrentIndex(old_index)
        self.combo_section.blockSignals(False)
        self._section_changed()

    def _section_changed(self, *_):
        self._fiber_index = 0
        section = self._section()
        length = _number(section.get("hinge_length_m")) if section else None
        valid_length = length is not None and length > 0
        self.chk_rotation.blockSignals(True)
        self.chk_rotation.setEnabled(valid_length)
        if not valid_length:
            self.chk_rotation.setChecked(False)
        self.chk_rotation.blockSignals(False)
        self._populate_fibers()
        self._refresh()

    def _units_changed(self, *_):
        self._populate_fibers()
        self._refresh()

    def _outline_toggled(self, *_):
        self._map_key = None
        self._refresh()

    def _geometry(self):
        """Cached map geometry (positions, kinds, model outline/rebar) of the selected section."""
        case, section = self._case(), self._section()
        if not case or section is None or not section.get("fibers"):
            return None
        key = (case["case_name"], self.combo_section.currentData())
        if key not in self._geo_cache:
            self._geo_cache[key] = _build_geometry(self.model, section)
        return self._geo_cache[key]

    def _populate_fibers(self):
        section, units = self._section(), self._units()
        fibers = section.get("fibers", []) if section else []
        geo = self._geometry()
        self.f_table.blockSignals(True)
        self.f_table.setUpdatesEnabled(False)
        self.f_table.setHorizontalHeaderLabels([
            "Fiber", "Kind", "Material tag", f"Coord 2 ({units['length']})",
            f"Coord 3 ({units['length']})", f"Area ({units['length']}²)",
            "Strain", f"Stress ({units['stress']})",
        ])
        self.f_table.setRowCount(len(fibers))
        for row, fiber in enumerate(fibers):
            values = [str(row + 1), geo["kind"][row], geo["tags"][row],
                      f"{geo['xy'][row, 1] * units['L']:.6g}",
                      f"{geo['xy'][row, 0] * units['L']:.6g}",
                      f"{fiber['area'] * units['L'] ** 2:.6g}", "—", "—"]
            for column, value in enumerate(values):
                self.f_table.setItem(row, column, QTableWidgetItem(value))
        self._fiber_index = min(self._fiber_index, max(0, len(fibers) - 1))
        if fibers:
            self.f_table.selectRow(self._fiber_index)
        self.f_table.resizeColumnsToContents()
        for column in (6, 7):
            self.f_table.setColumnWidth(column, max(self.f_table.columnWidth(column), 110))
        self.f_table.setUpdatesEnabled(True)
        self.f_table.blockSignals(False)
        self.btn_export_fiber.setEnabled(bool(fibers))

    def _step_changed(self, value):
        for widget in (self.slider_step, self.spin_step):
            widget.blockSignals(True)
            widget.setValue(value)
            widget.blockSignals(False)
        self._timer.start(0)                                                                     

    def _fiber_selected(self):
                                                                                            
        rows = self.f_table.selectionModel().selectedRows()
        if not rows:
            return
        row = rows[0].row()
        if row != self._fiber_index:
            self._fiber_index = row
            self._dirty["fiber"] = True
            self._render()

    def _map_clicked(self, event):
        """Pick a fiber. Rebar and concrete fibers sit almost on top of each other, so plain
        nearest-point picking flipped between them with every pixel of mouse jitter. Now: a click
        inside a marker picks that marker (rebar before concrete); a click on the selected rebar
        again reaches the concrete under it; clicks far from every fiber change nothing."""
        geo = self._geometry()
        if event.inaxes is not self.s_ax or event.button != 1 or geo is None:
            return
        points = geo["xy"] * self._units()["L"]
        display = self.s_ax.transData.transform(points)
        distance = np.hypot(display[:, 0] - event.x, display[:, 1] - event.y)
        is_rebar = np.array([kind == "Rebar" for kind in geo["kind"]])
        radius = np.where(is_rebar, REBAR_PICK_PX, FIBER_PICK_PX)
        inside = np.flatnonzero(distance <= radius)
        if inside.size == 0:
            nearest = int(np.argmin(distance))
            if distance[nearest] > PICK_FALLBACK_PX:
                return
            inside = np.array([nearest])
        order = sorted((int(i) for i in inside), key=lambda i: (not is_rebar[i], distance[i]))
        pick = order[0]
        if pick == self._fiber_index and is_rebar[pick]:
            below = [i for i in order if not is_rebar[i]]
            if below:
                pick = below[0]
        self.f_table.selectRow(pick)

    @staticmethod
    def _format(value):
        return f"{value:.6g}" if np.isfinite(value) else "Unavailable"

    @staticmethod
    def _init_history_axes(figure, axes, x, y):
        axes.clear()
        style_plot_axes(figure, axes)
        axes.xaxis.set_major_locator(MaxNLocator(nbins=5))
        line, = axes.plot(x, y, "o-", color=plot_color("history"), markersize=3, linewidth=1, label="Saved history")
        trail, = axes.plot([], [], "o-", color=plot_color("trail"), markersize=4, linewidth=1.5,
                           label="Through selected state", animated=True)
        mark, = axes.plot([], [], "o", color=plot_color("marker"), markersize=9, label="Selected state", animated=True)
        warn = axes.text(.5, .96, "Response unavailable at this saved state", ha="center", va="top",
                         transform=axes.transAxes, animated=True, visible=False,
                         color=COLORS["text_primary"], fontsize=9)
        if not (np.isfinite(x) & np.isfinite(y)).any():
            axes.text(.5, .5, "No recorded response for this selection", ha="center",
                      va="center", transform=axes.transAxes, color=COLORS["text_secondary"])
        style_legend(axes.legend(handles=[line, trail, mark], loc="best", fontsize=8))
        return {"trail": trail, "mark": mark, "warn": warn}

    @staticmethod
    def _move_history(art, x, y, index, blit):
        """Cheap per-step update: only the animated artists change."""
        art["trail"].set_data(x[:index + 1], y[:index + 1])
        ok = bool(np.isfinite(x[index]) and np.isfinite(y[index]))
        art["mark"].set_data([x[index]] if ok else [], [y[index]] if ok else [])
        art["warn"].set_visible(not ok)
        blit.update()

    def _tab_name(self):
        return "section" if self.tabs.currentIndex() == 0 else "fiber"

    def _refresh(self, *_):
        """Section / unit / axis changed: rebuild what is visible, mark the other tab stale."""
        self._dirty = {"section": True, "fiber": True}
        self._render()

    def _render(self):
        case, section = self._case(), self._section()
        index = self.spin_step.value()
        step = case["steps"][index]
        self.lbl_step.setText(f"Step {step['step']} · {index + 1} / {len(case['steps'])}")
        if section is None:
            self.lbl_section.setText("No recorded sections match the selected-frame filter.")
            self.lbl_warning.setText("")
            self.lbl_response.setText("")
            self.lbl_fiber.setText("")
            for figure, axes, canvas in ((self.h_fig, self.h_ax, self.h_canvas),
                                         (self.f_fig, self.f_ax, self.f_canvas),
                                         (self.s_fig, self.s_ax, self.s_canvas)):
                axes.clear()
                style_plot_axes(figure, axes)
                canvas.draw_idle()
            self._map_key = None
            return
        history, units = self._history(), self._units()
        if self._dirty.get("header", True) or self._header_key != (case["case_name"], self.combo_section.currentData(), self.combo_units.currentText()):
            self._update_header(case, section, history, units)
        tab = self._tab_name()
        if tab == "section":
            if self._dirty["section"]:
                self._rebuild_section(section, history, units)
                self._dirty["section"] = False
            self._step_section(history, units, index)
        else:
            if self._dirty["fiber"]:
                self._rebuild_fiber(case, section, history, units)
                self._dirty["fiber"] = False
            self._step_fiber(section, history, units, index)

    _header_key = None

    def _update_header(self, case, section, history, units):
        self._header_key = (case["case_name"], self.combo_section.currentData(), self.combo_units.currentText())
        self._dirty["header"] = False
        position = _number(section.get("position_m"))
        length = _number(section.get("hinge_length_m"))
        details = [f"Frame {section['element_id']}", str(section.get("integration", "Integration section"))]
        if position is not None:
            details.append(f"Position from element {section.get('element_tag', '?')} i-end: {position * units['L']:.6g} {units['length']}")
        if length is not None and length > 0:
            details.append(f"Lp: {length * units['L']:.6g} {units['length']}")
        else:
            details.append("Distributed section: response shown as moment–curvature")
        self.lbl_section.setText("  |  ".join(details))
        warnings = list(case["warnings"])
        geo = self._geometry()
        if geo is not None and geo["warning"]:
            warnings.insert(0, geo["warning"])
        if history["missing_section"]:
            warnings.append(f"Section responses are missing or invalid at {history['missing_section']} saved state(s).")
        if history["missing_fiber"]:
            warnings.append(f"Fiber responses are missing or invalid at {history['missing_fiber']} saved state(s).")
        if not section.get("fibers"):
            warnings.append("No fiber geometry was recorded for this section.")
        self.lbl_warning.setText("\n".join(warnings[:3]) + (f"\n{len(warnings) - 3} additional warning(s); hover to read." if len(warnings) > 3 else ""))
        self.lbl_warning.setToolTip("\n".join(warnings))

    def _rebuild_section(self, section, history, units):
        length = _number(section.get("hinge_length_m"))
        column, sign = (1, 1.0) if self.combo_dof.currentText() == "M2" else (2, -1.0)
        rotation = self.chk_rotation.isChecked() and self.chk_rotation.isEnabled()
        x = history["d"][:, column] * sign
        if rotation:
            x = x * length
            x_label = "End-section rotation contribution (rad)"
        else:
            x = x / units["L"]
            x_label = f"Curvature (1/{units['length']})"
        y = history["force"][:, column] * sign * units["M"]
        self._h_x, self._h_y, self._h_xlabel = x, y, x_label
        self._h_art = self._init_history_axes(self.h_fig, self.h_ax, x, y)
        self.h_ax.set_xlabel(x_label)
        self.h_ax.set_ylabel(f"{self.combo_dof.currentText()} ({units['moment']})")
        self.h_ax.set_title("Recorded section response", fontsize=9)
        self._relayout(self.h_fig)
        self._h_blit.reset(self._h_art.values())

    def _step_section(self, history, units, index):
        x, y = self._h_x, self._h_y
        force_unit = make_unit_converter(self.combo_units.currentText()).force_unit_name
        self.lbl_response.setText(
            f"{self.combo_dof.currentText()}: {_fmt(y[index])} {units['moment']}   |   "
            f"{self._h_xlabel}: {_fmt(x[index])}   |   "
            f"Axial force: {_fmt(history['force'][index, 0] * units['F'])} {force_unit}")
        self._move_history(self._h_art, x, y, index, self._h_blit)

    def _rebuild_fiber(self, case, section, history, units):
        fibers = section.get("fibers", [])
        self.f_ax.clear()
        style_plot_axes(self.f_fig, self.f_ax)
        if not fibers:
            self._f_art = None
            self._f_blit.reset([])
            self.s_ax.clear()
            style_plot_axes(self.s_fig, self.s_ax)
            self._map_key = None
            self.lbl_fiber.setText("Fiber responses are unavailable for this section.")
            self.f_canvas.draw_idle()
            self.s_canvas.draw_idle()
            return
        fiber_index = min(self._fiber_index, len(fibers) - 1)
        fx = history["strain"][:, fiber_index]
        fy = history["stress"][:, fiber_index] * units["S"]
        self._f_x, self._f_y, self._f_units = fx, fy, units
        self._f_art = self._init_history_axes(self.f_fig, self.f_ax, fx, fy)
        self.f_ax.set_xlabel("Strain")
        self.f_ax.set_ylabel(f"Stress ({units['stress']})")
        self.f_ax.set_title(f"Fiber {fiber_index + 1}: recorded stress–strain", fontsize=9)
        self._relayout(self.f_fig)
        self._f_blit.reset(self._f_art.values())
        self._rebuild_map(case, section, units, fiber_index)

    def _rebuild_map(self, case, section, units, fiber_index):
        """Section map in the native hinge dialog's style: outline, tie box, model rebars,
        fibers sized by area and coloured by material tag, selected fiber ringed."""
        geo = self._geometry()
        fibers = section.get("fibers", [])
        has_reference = bool(geo["outline"] or geo["rebars"] or geo["tie"])
        self.chk_hide_reinf.setEnabled(has_reference)
        hide = has_reference and self.chk_hide_reinf.isChecked()
        scale = units["L"]
        points = geo["xy"] * scale
        sizes = 10 + 70 * (geo["area"] / max(float(geo["area"].max()), 1e-30))
        key = (case["case_name"], self.combo_section.currentData(), self.combo_units.currentText(), hide)
        if key == self._map_key and self._ring is not None:
            self._ring.set_offsets(points[[fiber_index]])
            self._ring.set_sizes([sizes[fiber_index] * 3 + 60])
            self.s_canvas.draw_idle()
            return
        self._map_key = key
        ax = self.s_ax
        ax.clear()
        style_plot_axes(self.s_fig, ax)
        pal = section_map_palette()
        ax.set_facecolor(pal["bg"])
        ax.grid(False)
        ax.set_xticks([])
        ax.set_yticks([])
        xs, ys = list(points[:, 0]), list(points[:, 1])
        if geo["outline"]:
            outline = np.asarray(geo["outline"], float) * scale
            ax.add_patch(Polygon(outline, closed=True, facecolor=pal["fill"],
                                 edgecolor=pal["outline"], lw=2, zorder=1))
            xs += list(outline[:, 0])
            ys += list(outline[:, 1])
        if not hide:
            if geo["tie"]:
                ax.add_patch(Polygon(np.asarray(geo["tie"], float) * scale, closed=True, fill=False,
                                     edgecolor="#00c853", lw=1.6, ls="--", zorder=2))
            for rx, ry, dia in geo["rebars"]:
                ax.add_patch(Circle((rx * scale, ry * scale), max(dia / 2.0, 1e-4) * scale,
                                    facecolor="#d81f1f", edgecolor="#000000", lw=0.8, zorder=3))
                xs.append(rx * scale)
                ys.append(ry * scale)
        ax.axhline(0, color=pal["axis"], alpha=0.14, lw=1, zorder=0)
        ax.axvline(0, color=pal["axis"], alpha=0.14, lw=1, zorder=0)
        tags = geo["tags"]
        order = {tag: n for n, tag in enumerate(dict.fromkeys(tags))}
        colors = [TAG_COLORS[order[tag] % len(TAG_COLORS)] for tag in tags]
        ax.scatter(points[:, 0], points[:, 1], s=sizes, c=colors, edgecolors="none", zorder=4)
        handles = []
        for tag, n in order.items():
            members = [i for i, t in enumerate(tags) if t == tag]
            name = str(fibers[members[0]].get("material_name") or f"Tag {tag}")
            if all(geo["kind"][i] == "Rebar" for i in members):
                name += " (rebar)"
            handles.append(Line2D([], [], marker="o", ls="", color=TAG_COLORS[n % len(TAG_COLORS)], label=name))
        style_legend(ax.legend(handles=handles, loc="upper right", fontsize=7))
        self._ring = ax.scatter([points[fiber_index, 0]], [points[fiber_index, 1]],
                                s=sizes[fiber_index] * 3 + 60, facecolors="none",
                                edgecolors=pal["ring"], linewidths=1.6, zorder=5)
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        pad = 0.12 * max(x1 - x0, y1 - y0, 1e-6)
        ax.set_xlim(x0 - pad, x1 + pad)
        ax.set_ylim(y0 - pad, y1 + pad)
        ax.set_aspect("equal", adjustable="datalim")
        parts = [geo["name"]]
        if geo["rebars"] and not hide:
            parts.append(f"{len(geo['rebars'])} bar(s)")
        parts.append(f"{len(fibers)} fiber(s)")
        ax.text(0.02, 0.02, "  --  ".join(p for p in parts if p), transform=ax.transAxes,
                fontsize=7, color=pal["text"], ha="left", va="bottom")
        ox, oy, length = 0.90, 0.10, 0.10
        arrow = dict(arrowstyle="->", color=pal["text"], lw=1.4)
        ax.annotate("", xy=(ox, oy + length), xytext=(ox, oy), xycoords="axes fraction",
                    textcoords="axes fraction", arrowprops=arrow, annotation_clip=False)
        ax.annotate("", xy=(ox - length, oy), xytext=(ox, oy), xycoords="axes fraction",
                    textcoords="axes fraction", arrowprops=arrow, annotation_clip=False)
        ax.text(ox, oy + length + 0.02, "2", transform=ax.transAxes, fontsize=8, color=pal["text"],
                ha="center", va="bottom")
        ax.text(ox - length - 0.02, oy, "3", transform=ax.transAxes, fontsize=8, color=pal["text"],
                ha="right", va="center")
        self._relayout(self.s_fig)
        self.s_nav.mark_home()
        self.s_nav.user_zoomed = False
        self.s_canvas.draw_idle()

    def _step_fiber(self, section, history, units, index):
        fibers = section.get("fibers", [])
        if not fibers or self._f_art is None:
            return
        strains = history["strain"][index].tolist()
        stresses = (history["stress"][index] * units["S"]).tolist()
        table = self.f_table
        table.setUpdatesEnabled(False)
        for row in range(len(fibers)):
            table.item(row, 6).setText(_fmt(strains[row]))
            table.item(row, 7).setText(_fmt(stresses[row]))
        table.setUpdatesEnabled(True)
        fiber_index = min(self._fiber_index, len(fibers) - 1)
        fx, fy = self._f_x, self._f_y
        self.lbl_fiber.setText(f"Fiber {fiber_index + 1}   |   Strain: {_fmt(fx[index])}   |   "
                               f"Stress: {_fmt(fy[index])} {units['stress']}")
        self._move_history(self._f_art, fx, fy, index, self._f_blit)

    def export_history(self, path, fiber=False):
        """Export recorded points in the selected display units; gaps are blank."""
        case, section, history = self._case(), self._section(), self._history()
        if section is None:
            raise ValueError("Select a section first.")
        if fiber and not section.get("fibers"):
            raise ValueError("No fibers are recorded for this section.")
        units = self._units()
        with open(path, "w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.writer(stream)
            common = ["case", "frame", "element_tag", "section_index", "saved_state", "step"]
            if fiber:
                writer.writerow(common + ["fiber", "kind", "material_tag", f"coord2_{units['length']}",
                                          f"coord3_{units['length']}", "strain", f"stress_{units['stress']}"])
            else:
                writer.writerow(common + ["axial_strain", f"curvature2_1/{units['length']}",
                    f"curvature3_1/{units['length']}", f"N_{make_unit_converter(self.combo_units.currentText()).force_unit_name}",
                    f"M2_{units['moment']}", f"M3_{units['moment']}", "end_section_rotation_contribution2_rad", "end_section_rotation_contribution3_rad"])
            length = _number(section.get("hinge_length_m"))
            for index, step in enumerate(case["steps"]):
                values = [case["case_name"], section["element_id"], section.get("element_tag"),
                          section.get("section_index"), index, step["step"]]
                if fiber:
                    fiber_record = section["fibers"][self._fiber_index]
                    geo = self._geometry()
                    values += [self._fiber_index + 1, geo["kind"][self._fiber_index],
                               fiber_record.get("material_tag"),
                               geo["xy"][self._fiber_index, 1] * units["L"],
                               geo["xy"][self._fiber_index, 0] * units["L"],
                               history["strain"][index, self._fiber_index],
                               history["stress"][index, self._fiber_index] * units["S"]]
                else:
                    d, force = history["d"][index], history["force"][index]
                    values += [d[0], d[1] / units["L"], -d[2] / units["L"],
                               force[0] * units["F"], force[1] * units["M"], -force[2] * units["M"],
                               d[1] * length if length is not None and length > 0 else None,
                               -d[2] * length if length is not None and length > 0 else None]
                writer.writerow(["" if value is None or isinstance(value, (float, np.floating)) and not np.isfinite(value)
                                 else value for value in values])

    def _export(self, fiber):
        section = self._section()
        if section is None:
            return
        suffix = f"fiber_{self._fiber_index + 1}" if fiber else "section"
        default = (f"{self.base_name}_{self.combo_case.currentText()}_opensees_"
                   f"{section['element_id']}_{section.get('element_tag', '')}_"
                   f"{section.get('section_index', '')}_{suffix}.csv")
        path, _ = QFileDialog.getSaveFileName(self, "Export recorded OpenSees history", default, "CSV files (*.csv)")
        if not path:
            return
        try:
            self.export_history(path, fiber=fiber)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Export failed", str(error))

def show_opensees_hinge_results(window):
    """Engine-specific entry point; leave the native handler untouched."""
    import glob

    model = window.model
    if not model or not getattr(model, "file_path", None):
        QMessageBox.warning(window, "No Results", "Please run an OpenSees nonlinear static analysis first.")
        return
    base_name = os.path.splitext(model.file_path)[0]
    paths = getattr(model, "valid_result_paths", None) or glob.glob(f"{base_name}_*_results.json")
    prefix = os.path.basename(base_name) + "_"
    cases = {}
    for path in sorted(paths):
        filename = os.path.basename(path)
        if filename.startswith(prefix) and filename.endswith("_results.json"):
            name = filename[len(prefix):-len("_results.json")]
            if name:
                cases[name] = path
    previous = getattr(window, "_opensees_hinge_results_dlg", None)
    if previous is not None:
        if previous.isVisible():
            previous.raise_()
            previous.activateWindow()
            return
        previous.deleteLater()
        window._opensees_hinge_results_dlg = None
    dialog = OpenSeesHingeResultsDialog(
        window, model, base_name, cases,
        selected_element_ids=list(getattr(window, "selected_ids", [])),
        animation_manager=getattr(window.canvas, "animation_manager", None),
    )
    if dialog.status != "ok":
        QMessageBox.information(
            window, "No OpenSees Hinge / Section Results",
            "No recorded OpenSees fiber-section responses were found.\n\n"
            "Run a Nonlinear Static case using OpenSees and a frame section with supported "
            "reinforcement and nonlinear material data. Choose Multiple States for response "
            "curves; Final State Only shows the final recorded point.\n\n"
            "Existing result files must be regenerated with the updated OpenSees recorder.",
        )
        dialog.deleteLater()
        return
    window._opensees_hinge_results_dlg = dialog
    dialog.setWindowModality(Qt.WindowModality.NonModal)
    dialog.show()
