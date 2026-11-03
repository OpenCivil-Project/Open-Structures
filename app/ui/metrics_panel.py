"""
metrics_panel.py   (app/ui/)

Reusable side panel with the NUMBERS of a cyclic curve and its comparison with reference curves.
Pure display: the owner dialog hands in plain arrays that are already in display units, plus the
two unit names. It never reads results files or the model, so the same panel can sit in the
pushover curve dialog (force-displacement), the hinge results dialog (moment-curvature,
moment-rotation) or anything else that shows a loop:

    panel = MetricsPanel(self)
    panel.set_data((x, y), [("Test", rx, ry), ...], x_unit="mm", y_unit="kN",
                   primary_name="Analysis", notes=["..."])

All the maths lives in core/metrics.py (see its docstring for the definitions).
"""
import csv
import math

import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QKeySequence
from PyQt6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QFileDialog, QHBoxLayout, QHeaderView,
    QLabel, QPushButton, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from core import metrics as M

DASH = "\u2014"
XI = "\u03be"
DELTA = "\u0394"
MINUS = "\u2212"

def _fmt(v, nd=4):
    if v is None:
        return DASH
    try:
        v = float(v)
    except (TypeError, ValueError):
        return str(v)
    return DASH if not math.isfinite(v) else f"{v:.{nd}g}"

def _pct(v):
    if v is None:
        return DASH
    v = float(v)
    return DASH if not math.isfinite(v) else f"{v:+.1f}"

def _err(a, r):
    """(analysis - reference) / reference in %, '-' when the reference is zero/undefined."""
    try:
        a, r = float(a), float(r)
    except (TypeError, ValueError):
        return None
    return 100.0 * (a - r) / r if r != 0.0 and math.isfinite(r) and math.isfinite(a) else None

class _Table(QTableWidget):
    """Read-only table; Ctrl+C copies the selected cells as tab-separated text (pastes into Excel)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.verticalHeader().hide()
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.horizontalHeader().setStretchLastSection(True)

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.StandardKey.Copy):
            sel = self.selectedIndexes()
            if sel:
                r0, r1 = min(i.row() for i in sel), max(i.row() for i in sel)
                c0, c1 = min(i.column() for i in sel), max(i.column() for i in sel)
                lines = []
                for r in range(r0, r1 + 1):
                    lines.append("\t".join((self.item(r, c).text() if self.item(r, c) else "")
                                           for c in range(c0, c1 + 1)))
                QApplication.clipboard().setText("\n".join(lines))
            return
        super().keyPressEvent(event)

    def fill(self, headers, rows):
        self.clear()
        self.setColumnCount(len(headers))
        self.setHorizontalHeaderLabels(headers)
        self.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, text in enumerate(row):
                it = QTableWidgetItem(str(text))
                it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if c > 0:
                    it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.setItem(r, c, it)

    def as_rows(self):
        head = [self.horizontalHeaderItem(c).text() if self.horizontalHeaderItem(c) else ""
                for c in range(self.columnCount())]
        body = [[(self.item(r, c).text() if self.item(r, c) else "") for c in range(self.columnCount())]
                for r in range(self.rowCount())]
        return head, body

class MetricsPanel(QWidget):
    TOL_FRAC = 0.02                                                                                    
    LEVEL_TOL = 0.15                                                                                 

    def __init__(self, parent=None):
        super().__init__(parent)
        self._primary = None
        self._refs = []
        self._x_unit = ""
        self._y_unit = ""
        self._pname = "Analysis"
        self._notes = []
        self.setMinimumWidth(480)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 0, 0, 0)
        title = QLabel("Curve Metrics")
        f = QFont(title.font())
        f.setBold(True)
        title.setFont(f)
        lay.addWidget(title)

        row = QHBoxLayout()
        self.lbl_cmp = QLabel("Compare with")
        self.combo_ref = QComboBox()
        self.combo_ref.currentIndexChanged.connect(self._rebuild)
        row.addWidget(self.lbl_cmp)
        row.addWidget(self.combo_ref, 1)
        lay.addLayout(row)

        self.tabs = QTabWidget()
        self.tbl_sum = _Table()
        self.tbl_cyc = _Table()
        self.tabs.addTab(self.tbl_sum, "Summary")
        self.tabs.addTab(self.tbl_cyc, "Per Cycle")
        lay.addWidget(self.tabs, 1)

        self.lbl_note = QLabel("")
        self.lbl_note.setWordWrap(True)
        self.lbl_note.setStyleSheet("color: gray;")
        lay.addWidget(self.lbl_note)

        btns = QHBoxLayout()
        self.btn_export = QPushButton("Export Metrics to CSV...")
        self.btn_export.setObjectName("secondary")
        self.btn_export.clicked.connect(self._on_export)
        btns.addWidget(self.btn_export)
        btns.addStretch(1)
        lay.addLayout(btns)

    def set_data(self, primary, references=(), x_unit="", y_unit="", primary_name="Analysis", notes=()):
        """primary: (x, y) arrays or None.  references: [(name, x, y), ...].  Units are labels only."""
        self._primary = primary
        self._refs = [(n, np.asarray(x, float), np.asarray(y, float)) for n, x, y in references]
        self._x_unit, self._y_unit, self._pname, self._notes = x_unit, y_unit, primary_name, list(notes)
        prev = self.combo_ref.currentText()
        self.combo_ref.blockSignals(True)
        self.combo_ref.clear()
        for n, _, _ in self._refs:
            self.combo_ref.addItem(n)
        i = self.combo_ref.findText(prev)
        self.combo_ref.setCurrentIndex(i if i >= 0 else 0)
        self.combo_ref.blockSignals(False)
        has_ref = bool(self._refs)
        self.combo_ref.setVisible(has_ref)
        self.lbl_cmp.setVisible(has_ref)
        self._rebuild()

    def _message(self, text):
        self.tbl_sum.fill([""], [])
        self.tbl_cyc.fill([""], [])
        self.lbl_note.setText(text)

    def _rebuild(self, *_):
        if self._primary is None:
            self._message("No curve to analyse.")
            return
        x, y = self._primary
        kw = dict(tol_frac=self.TOL_FRAC, level_tol=self.LEVEL_TOL)
        lu, fu = self._x_unit, self._y_unit
        eu = f"{fu}\u00b7{lu}"
        notes = list(self._notes)
        try:
            s_an = M.summarize(x, y, **kw)
            t_an = M.cycle_table(x, y, **kw)
            ref = None
            if self._refs:
                i = max(0, self.combo_ref.currentIndex())
                ref = self._refs[i]
                s_ref = M.summarize(ref[1], ref[2], **kw)
                t_ref = M.cycle_table(ref[1], ref[2], **kw)
                cmp = M.compare((x, y), (ref[1], ref[2]), **kw)
        except Exception as exc:                                               
            self._message(f"Metrics unavailable for this curve ({exc}).")
            return

        def largest(rows):
            return max(rows, key=lambda r: r.x_pos - r.x_neg) if rows else None

        L_an = largest(t_an)
        sym = "*" if not s_an["all_closed"] else ""

        def srow(label, a, r=None, nd=4, err=True):
            if ref is None:
                return [label, _fmt(a, nd)]
            return [label, _fmt(a, nd), _fmt(r, nd), _pct(_err(a, r)) if err else DASH]

        L_ref = largest(t_ref) if ref else None
        sr = s_ref if ref else {}
        rows = [
            srow(f"Peak + force ({fu})", s_an["y_max"], sr.get("y_max")),
            srow(f"   at displacement ({lu})", s_an["x_at_y_max"], sr.get("x_at_y_max"), err=False),
            srow(f"Peak {MINUS} force ({fu})", s_an["y_min"], sr.get("y_min")),
            srow(f"   at displacement ({lu})", s_an["x_at_y_min"], sr.get("x_at_y_min"), err=False),
            srow(f"Max displacement ({lu})", s_an["x_max"], sr.get("x_max"), err=False),
            srow(f"Min displacement ({lu})", s_an["x_min"], sr.get("x_min"), err=False),
        ]
        cyc_a = f"{s_an['n_cycles']} ({s_an['n_levels']} levels)"
        rows.append([f"Cycles"] + ([cyc_a] if ref is None else
                                    [cyc_a, f"{sr['n_cycles']} ({sr['n_levels']} levels)", DASH]))
        rows.append(srow(f"Dissipated energy ({eu}){sym}", s_an["E_D_total"], sr.get("E_D_total")))
        if L_an is not None:
            rows.append(srow(f"{XI}_eq, largest cycle", L_an.xi_eq, L_ref.xi_eq if L_ref else None, nd=3))
            rows.append(srow(f"Secant stiffness, largest cycle ({fu}/{lu})", L_an.K_sec,
                             L_ref.K_sec if L_ref else None))
            rows.append(srow("Strength ratio, last cycle of largest level",
                             self._last_of_largest_level(t_an),
                             self._last_of_largest_level(t_ref) if ref else None, nd=3))
        head = ["", self._pname] if ref is None else ["", self._pname, ref[0], f"{DELTA} %"]
        self.tbl_sum.fill(head, rows)

        if ref is None:
            h = ["Cycle", "Level", f"x+ ({lu})", f"x{MINUS} ({lu})", f"F+ peak ({fu})", f"F{MINUS} peak ({fu})",
                 f"E_D ({eu})", f"E_D cum ({eu})", f"{XI}_eq", f"K_sec ({fu}/{lu})", "Str. ratio"]
            body = [[f"{r.cycle}{'' if r.closed else '*'}", r.level, _fmt(r.x_pos), _fmt(r.x_neg),
                     _fmt(r.y_peak_pos), _fmt(r.y_peak_neg), _fmt(r.E_D), _fmt(r.E_D_cum),
                     _fmt(r.xi_eq, 3), _fmt(r.K_sec), _fmt(r.strength_ratio, 3)] for r in t_an]
        else:
            open_ref = {r.cycle: not r.closed for r in t_ref}
            open_an = {r.cycle: not r.closed for r in t_an}
            h = ["Cycle", "Level", f"Amp ({lu})", f"E_D {self._pname[:8]} ({eu})", f"E_D ref ({eu})",
                 f"{DELTA}E %", f"{DELTA}F+ %", f"{DELTA}F{MINUS} %", f"{DELTA}K %",
                 f"{XI} {self._pname[:8]}", f"{XI} ref"]
            body = []
            for r in cmp["cycles"]:
                star = open_ref.get(r["cycle_ref"]) or open_an.get(r.get("cycle_model"), False)
                body.append([f"{r['cycle_ref']}{'*' if star else ''}", r["level_ref"], _fmt(r["x_amp_ref"]),
                             _fmt(r.get("E_D_model")), _fmt(r["E_D_ref"]), _pct(r.get("E_D_err_pct")),
                             _pct(r.get("Fpk_pos_err_pct")), _pct(r.get("Fpk_neg_err_pct")),
                             _pct(r.get("K_err_pct")), _fmt(r.get("xi_model"), 3), _fmt(r["xi_ref"], 3)])
        self.tbl_cyc.fill(h, body)

        if s_an["n_cycles"] < 2 or (ref is not None and sr["n_cycles"] < 2):
            notes.append("Fewer than two zero-crossing cycles found (monotonic or one-sided curve): "
                         "per-cycle numbers and energy are not meaningful for it.")
        if sym or (ref is not None and not sr["all_closed"]):
            notes.append("* This cycle does not return to zero displacement, so its energy also contains "
                         "some recoverable strain energy.")
        if ref is not None:
            notes.append(f"{DELTA} = (analysis {MINUS} reference) / reference. Cycles are matched by amplitude "
                         f"level and cycle number within the level.")
            if s_an["n_cycles"] != sr["n_cycles"]:
                notes.append(f"Cycle count differs: analysis {s_an['n_cycles']}, reference {sr['n_cycles']}.")
        self.lbl_note.setText("\n".join(notes))

    @staticmethod
    def _last_of_largest_level(rows):
        if not rows:
            return None
        lvl = max(rows, key=lambda r: r.x_pos - r.x_neg).level
        return [r for r in rows if r.level == lvl][-1].strength_ratio

    def _on_export(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export Curve Metrics", "curve_metrics.csv",
                                              "CSV Files (*.csv)")
        if path:
            self.export_csv(path)

    def export_csv(self, path):
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow([f"Units: x = {self._x_unit}, y = {self._y_unit}, energy = {self._y_unit}*{self._x_unit}"])
            for tbl in (self.tbl_sum, self.tbl_cyc):
                head, body = tbl.as_rows()
                w.writerow([])
                w.writerow(head)
                w.writerows(body)
            if self.lbl_note.text():
                w.writerow([])
                for line in self.lbl_note.text().splitlines():
                    w.writerow([line])
