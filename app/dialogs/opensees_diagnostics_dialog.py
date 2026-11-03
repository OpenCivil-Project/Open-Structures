"""OpenSees run diagnostics: drift decomposition, damage events, fit against the test curve.

A pure reader of a *_results.json written by run_opensees_nonlinear_static. It needs, under "info":
    opensees_history        {u_m, V_N, ...}               control-node history (always written)
    opensees_drift_history  {steps, u_total, u_slip, u_shear, u_flex}   (None if the model has no springs)
    opensees_damage_events  [{event, label, step, u_m, V_N, section, strain}, ...]
and optionally a reference curve (u, V in mm / kN) to score the fit.

    dlg = OpenSeesDiagnosticsDialog(results_json_path, ref_u_mm=ref_x, ref_V_kN=ref_y, parent=self)
    dlg.exec()

Units shown: mm and kN.
"""

import json

import numpy as np
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QTabWidget, QWidget, QTableWidget, QTableWidgetItem,
                             QLabel, QPlainTextEdit, QHeaderView, QAbstractItemView, QSplitter)
from PyQt6.QtCore import Qt
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from app.ui.theme import (apply_dialog_style, style_plot_axes, style_legend, COLORS, plot_color,
                          current_theme, on_theme_changed, off_theme_changed)

try:                                                      
    from core.opensees_port.os_curve_metrics import compare, format_report
except ImportError:                                 
    from os_curve_metrics import compare, format_report

_EVENT_COLORS = {
    "Light": {"first_yield": "#e6a700", "bar_compression_yield": "#c78a00", "bar_hardening": "#b8860b",
              "cover_peak": "#e0662a", "cover_spalling": "#c0392b", "core_crushing": "#7a1f1f",
              "bar_ultimate": "#444444"},
    "Dark":  {"first_yield": "#ffc233", "bar_compression_yield": "#e0a800", "bar_hardening": "#d4a017",
              "cover_peak": "#ff8a4c", "cover_spalling": "#ff5c4d", "core_crushing": "#c94c4c",
              "bar_ultimate": "#cccccc"},
}

def _event_colors():
    return _EVENT_COLORS[current_theme()]

C_SLIP, C_SHEAR, C_FLEX = "#2ca02c", "#9467bd", "#1f77b4"

def _info(path):
    with open(path, "r", encoding="utf-8") as f:
        d = json.load(f)
    return d.get("info", d)

class OpenSeesDiagnosticsDialog(QDialog):
    def __init__(self, results_path, ref_u_mm=None, ref_V_kN=None, parent=None):
        super().__init__(parent)
        apply_dialog_style(self)
        self.setWindowTitle("OpenSees Diagnostics")
        self.resize(1000, 680)
        info = _info(results_path)
        hist = info.get("opensees_history") or {}
        self.u = np.asarray(hist.get("u_m") or [], float) * 1e3
        self.V = np.asarray(hist.get("V_N") or [], float) / 1e3
        self.drift = info.get("opensees_drift_history")
        self.events = info.get("opensees_damage_events") or []
        self.monitor_warnings = [w for w in (info.get("warnings") or []) if str(w).startswith("[monitor]")]
        self.failed = info.get("failed_steps") or []
        self.relaxed = info.get("relaxed_steps") or []
        self.ref_u = None if ref_u_mm is None else np.asarray(ref_u_mm, float)
        self.ref_V = None if ref_V_kN is None else np.asarray(ref_V_kN, float)

        lay = QVBoxLayout(self)
        self.status = QLabel(self._status_text())
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs)
        self._build_tabs()
        on_theme_changed(self._on_theme_changed)

    def _build_tabs(self):
        current = self.tabs.currentIndex()
        while self.tabs.count():
            w = self.tabs.widget(0)
            self.tabs.removeTab(0)
            w.deleteLater()
        self.tabs.addTab(self._tab_drift(), "Drift decomposition")
        self.tabs.addTab(self._tab_events(), "Damage events")
        self.tabs.addTab(self._tab_fit(), "Fit vs test")
        if current > 0:
            self.tabs.setCurrentIndex(current)

    def _on_theme_changed(self, _name):
        apply_dialog_style(self)
        self._build_tabs()

    def done(self, r):
        off_theme_changed(self._on_theme_changed)
        super().done(r)

    def _status_text(self):
        bits = [f"{len(self.u)} accepted steps."]
        if self.failed:
            f = self.failed[0]
            bits.append(f"STOPPED EARLY in case '{f.get('case')}' at commanded u = "
                        f"{1e3 * float(f.get('commanded_disp', 0.0)):.3f} mm (status {f.get('status')}).")
        if self.relaxed:
            bits.append(f"{len(self.relaxed)} step(s) converged only at a relaxed tolerance (approximate); "
                        f"first at u = {1e3 * float(self.relaxed[0]['cmd']):.3f} mm.")
        if not self.failed and not self.relaxed:
            bits.append("All steps converged at the strict tolerance.")
        return " ".join(bits)

    @staticmethod
    def _fig():
        fig = Figure(figsize=(6, 4), tight_layout=True)
        return fig, FigureCanvas(fig)

    def _tab_drift(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        d = self.drift
        if not d or not d.get("steps"):
            msg = ("No drift decomposition: the model has no bar-slip or shear spring at a support, "
                   "or the control DOF is not a translation.")
            if self.monitor_warnings:
                msg += "\n\nMonitor problem(s):\n" + "\n".join(self.monitor_warnings)
            lab = QLabel(msg)
            lab.setWordWrap(True)
            lay.addWidget(lab)
            return w
        fig, canvas = self._fig()
        ax1, ax2 = fig.subplots(1, 2)
        style_plot_axes(fig, ax1)
        style_plot_axes(fig, ax2)
        st = np.asarray(d["steps"], float)
        ut, us, uh, uf = (np.asarray(d[k], float) * 1e3 for k in ("u_total", "u_slip", "u_shear", "u_flex"))
        ax1.plot(st, us, color=C_SLIP, label="bar slip (fixed-end rotation)")
        ax1.plot(st, uh, color=C_SHEAR, label="shear spring")
        ax1.plot(st, uf, color=C_FLEX, label="flexure")
        ax1.plot(st, ut, color=COLORS["text_primary"], lw=0.8, ls="--", label="total")
        ax1.set_xlabel("step")
        ax1.set_ylabel("control displacement (mm)")
        style_legend(ax1.legend(fontsize=8))
                                                  
        pk = [i for i in range(1, len(ut) - 1) if ut[i] >= ut[i - 1] and ut[i] > ut[i + 1] and ut[i] > 0.1 * np.max(np.abs(ut))]
        if pk:
            lab = [f"{ut[i]:.1f}" for i in pk]
            tot = np.array([ut[i] for i in pk])
            shares = np.array([[us[i], uh[i], uf[i]] for i in pk]) / tot[:, None] * 100.0
            x = np.arange(len(pk))
            ax2.bar(x, shares[:, 2], color=C_FLEX, label="flexure")
            ax2.bar(x, shares[:, 0], bottom=shares[:, 2], color=C_SLIP, label="bar slip")
            ax2.bar(x, shares[:, 1], bottom=shares[:, 2] + shares[:, 0], color=C_SHEAR, label="shear")
            ax2.set_xticks(x)
            ax2.set_xticklabels(lab, rotation=45, fontsize=7)
            ax2.set_xlabel("positive peak displacement (mm)")
            ax2.set_ylabel("share of drift (%)")
            style_legend(ax2.legend(fontsize=8))
        lay.addWidget(canvas)
        return w

    def _tab_events(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        sp = QSplitter(Qt.Orientation.Vertical)
        fig, canvas = self._fig()
        ax = fig.subplots()
        style_plot_axes(fig, ax)
        ev_colors = _event_colors()
        if self.ref_u is not None:
            ax.plot(self.ref_u, self.ref_V, color=plot_color("reference"), lw=0.8, ls="--", label="test")
        ax.plot(self.u, self.V, color=COLORS["accent"], lw=0.9, label="analysis")
        for e in self.events:
            if e.get("V_N") is None:
                continue
            ax.plot([e["u_m"] * 1e3], [e["V_N"] / 1e3], "o",
                    color=ev_colors.get(e["event"], COLORS["text_primary"]), ms=7,
                    label=e["label"].split(" (")[0])
        ax.set_xlabel("displacement (mm)")
        ax.set_ylabel("base shear (kN)")
        style_legend(ax.legend(fontsize=7))
        sp.addWidget(canvas)
        tbl = QTableWidget(len(self.events), 5)
        tbl.setHorizontalHeaderLabels(["Event", "Step", "u (mm)", "V (kN)", "Section / strain"])
        tbl.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for r, e in enumerate(self.events):
            V = "" if e.get("V_N") is None else f"{e['V_N'] / 1e3:.1f}"
            for c, t in enumerate([e["label"], str(e["step"]), f"{e['u_m'] * 1e3:.3f}", V,
                                   f"{e['section']}  ({e['strain']:.4g})"]):
                tbl.setItem(r, c, QTableWidgetItem(t))
        sp.addWidget(tbl)
        lay.addWidget(sp)
        note = QLabel("Strain-based model events (first time any fibre of a hinge-end section reaches the limit). "
                      "Compare with the damage observed in the test; they are not observations.")
        note.setWordWrap(True)
        lay.addWidget(note)
        if not self.events:
            if self.monitor_warnings:
                lab = QLabel("Event detection did NOT run properly (this is not a result):\n" + "\n".join(self.monitor_warnings))
            else:
                lab = QLabel("The monitor ran and no strain limit was reached.")
            lab.setWordWrap(True)
            lay.addWidget(lab)
        return w

    def _tab_fit(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        if self.ref_u is None or len(self.u) < 3:
            lay.addWidget(QLabel("No reference curve supplied."))
            return w
        res = compare(self.u, self.V, self.ref_u, self.ref_V)
        fig, canvas = self._fig()
        ax1, ax2 = fig.subplots(1, 2)
        style_plot_axes(fig, ax1)
        style_plot_axes(fig, ax2)
        ax1.plot(self.ref_u, self.ref_V, color=plot_color("reference"), lw=0.8, ls="--", label="test")
        ax1.plot(self.u, self.V, color=COLORS["accent"], lw=0.9, label="analysis")
        ax1.set_xlabel("displacement (mm)")
        ax1.set_ylabel("base shear (kN)")
        style_legend(ax1.legend(fontsize=8))
        cy = res["cycles"]
        if cy:
            x = np.arange(len(cy))
            ax2.bar(x - 0.2, [c["energy_ratio"] for c in cy], 0.4, label="energy ratio", color="#e6a700")
            ax2.bar(x + 0.2, [c["k_ratio"] for c in cy], 0.4, label="secant stiffness ratio", color="#2ca02c")
            ax2.axhline(1.0, color=COLORS["text_secondary"], lw=0.8)
            ax2.set_xticks(x)
            ax2.set_xticklabels([f"{c['u_peak_ref']:.1f}" for c in cy], fontsize=8)
            ax2.set_xlabel("cycle (test peak displacement, mm)")
            ax2.set_ylabel("analysis / test")
            style_legend(ax2.legend(fontsize=8))
        lay.addWidget(canvas, 3)
        rep = QPlainTextEdit(format_report(res))
        rep.setReadOnly(True)
        rep.setStyleSheet("font-family: Consolas, monospace;")
        lay.addWidget(rep, 2)
        return w
