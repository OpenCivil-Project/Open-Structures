"""
reference_curve_import_dialog.py   (app/dialogs/)

Import OR modify a reference (experimental) force-displacement curve.

    ReferenceCurveImportDialog(parent, existing_names)               -> import from a file
    ReferenceCurveImportDialog(parent, existing_names, curve=dict)   -> modify a stored curve

Modify works from the RAW columns kept with the curve, so changing units / flip /
scale is exact. "Browse..." in modify mode replaces the data from another file.
result_curve() returns the dict stored in model.reference_curves (base units m, N).
"""

import os

import numpy as np
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox, QLabel, QLineEdit,
    QComboBox, QPushButton, QCheckBox, QDialogButtonBox, QFileDialog, QMessageBox,
    QSizePolicy,
)
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from app.ui.theme import apply_dialog_style, style_plot_axes, COLORS, CurveStyleEditor
from core.reference_curve import (
    parse_numeric_table, make_reference_curve, curve_raw, LENGTH_UNITS, FORCE_UNITS,
)

class ReferenceCurveImportDialog(QDialog):
    def __init__(self, parent, existing_names, path=None, curve=None):
        super().__init__(parent)
        self._editing = curve is not None
        self.setWindowTitle("Modify Reference Curve" if self._editing else "Import Reference Curve")
        self.setModal(True)
        self.resize(660, 700)
        apply_dialog_style(self)

        own = curve["name"] if self._editing else None
        self._existing = {n for n in existing_names if n != own}
        self._table = None
        self._path = ""
        self._curve = None

        self._build_ui()
        if self._editing:
            self._load_stored(curve)
        elif path:
            self._load_file(path)

    def _build_ui(self):
        outer = QVBoxLayout(self)

        row = QHBoxLayout()
        row.addWidget(QLabel("File"))
        self.edit_path = QLineEdit()
        self.edit_path.setReadOnly(True)
        row.addWidget(self.edit_path, 1)
        btn = QPushButton("Replace from file..." if self._editing else "Browse...")
        btn.setObjectName("secondary")
        btn.clicked.connect(self._on_browse)
        row.addWidget(btn)
        outer.addLayout(row)

        self.lbl_info = QLabel("")
        self.lbl_info.setWordWrap(True)
        self.lbl_info.setStyleSheet("color: gray;")
        outer.addWidget(self.lbl_info)

        box = QGroupBox("Curve")
        g = QGridLayout(box)
        g.addWidget(QLabel("Name"), 0, 0)
        self.edit_name = QLineEdit()
        g.addWidget(self.edit_name, 0, 1, 1, 3)

        g.addWidget(QLabel("Horizontal (displacement)"), 1, 0)
        self.combo_xcol = QComboBox()
        g.addWidget(self.combo_xcol, 1, 1)
        g.addWidget(QLabel("Unit"), 1, 2)
        self.combo_xunit = QComboBox()
        self.combo_xunit.addItems(LENGTH_UNITS.keys())
        self.combo_xunit.setCurrentText("mm")
        g.addWidget(self.combo_xunit, 1, 3)

        g.addWidget(QLabel("Vertical (force)"), 2, 0)
        self.combo_ycol = QComboBox()
        g.addWidget(self.combo_ycol, 2, 1)
        g.addWidget(QLabel("Unit"), 2, 2)
        self.combo_yunit = QComboBox()
        self.combo_yunit.addItems(FORCE_UNITS.keys())
        self.combo_yunit.setCurrentText("kN")
        g.addWidget(self.combo_yunit, 2, 3)

        self.chk_flip_x = QCheckBox("Flip sign of displacement")
        self.chk_flip_y = QCheckBox("Flip sign of force")
        g.addWidget(self.chk_flip_x, 3, 0, 1, 2)
        g.addWidget(self.chk_flip_y, 3, 2, 1, 2)

        g.addWidget(QLabel("Scale factor X"), 4, 0)
        self.edit_sx = QLineEdit("1")
        g.addWidget(self.edit_sx, 4, 1)
        g.addWidget(QLabel("Scale factor Y"), 4, 2)
        self.edit_sy = QLineEdit("1")
        g.addWidget(self.edit_sy, 4, 3)

        g.addWidget(QLabel("Notes"), 5, 0)
        self.edit_notes = QLineEdit()
        g.addWidget(self.edit_notes, 5, 1, 1, 3)
        g.setColumnStretch(1, 1)
        g.setColumnStretch(3, 1)
        outer.addWidget(box)

        sbox = QGroupBox("Line Style (as drawn in the Pushover Curve viewer)")
        sl = QVBoxLayout(sbox)
        self.style = CurveStyleEditor(default_width=1.2, default_style="--")
        sl.addWidget(self.style)
        outer.addWidget(sbox)

        self.figure = Figure(figsize=(5, 3.2))
        self.canvas = FigureCanvas(self.figure)
        self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.ax = self.figure.add_subplot(111)
        outer.addWidget(self.canvas, 1)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.button(QDialogButtonBox.StandardButton.Ok).setObjectName("primary")
        btns.button(QDialogButtonBox.StandardButton.Cancel).setObjectName("secondary")
        btns.accepted.connect(self._on_accept)
        btns.rejected.connect(self.reject)
        outer.addWidget(btns)

        for w in (self.combo_xcol, self.combo_ycol, self.combo_xunit, self.combo_yunit):
            w.currentIndexChanged.connect(self._preview)
        for w in (self.chk_flip_x, self.chk_flip_y):
            w.toggled.connect(self._preview)
        for w in (self.edit_sx, self.edit_sy):
            w.textChanged.connect(self._preview)
        self.style.changed.connect(self._preview)

    def _fill_columns(self, ncols, xi=0, yi=1):
        for c in (self.combo_xcol, self.combo_ycol):
            c.blockSignals(True)
            c.clear()
            c.addItems([f"Column {i + 1}" for i in range(ncols)])
        self.combo_xcol.setCurrentIndex(xi)
        self.combo_ycol.setCurrentIndex(yi)
        for c in (self.combo_xcol, self.combo_ycol):
            c.blockSignals(False)

    def _load_stored(self, curve):
        rx, ry, xu, yu, fx, fy, sx, sy = curve_raw(curve)
        self._table = {"data": np.column_stack([rx, ry]), "header": [],
                       "declared_count": None, "skipped_rows": 0}
        self._path = curve.get("source", "")
        self.edit_path.setText(self._path or "(stored data)")
        self._fill_columns(2)
        self.combo_xunit.setCurrentText(xu)
        self.combo_yunit.setCurrentText(yu)
        self.chk_flip_x.setChecked(fx)
        self.chk_flip_y.setChecked(fy)
        self.edit_sx.setText(f"{sx:g}")
        self.edit_sy.setText(f"{sy:g}")
        self.edit_name.setText(curve["name"])
        self.edit_notes.setText(curve.get("notes", ""))
        self.style.set_values(curve.get("color", ""), curve.get("linewidth", 1.2),
                              curve.get("linestyle", "--"))
        self.lbl_info.setText(f"{len(rx)} stored points. Change units / flip / scale / style below, "
                              f"or replace the data from another file.")
        self._preview()

    def _on_browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Reference Curve File", "",
            "Text / data files (*.txt *.dat *.csv *.tsv *.asc);;All files (*)")
        if path:
            self._load_file(path)

    def _load_file(self, path):
        try:
            t = parse_numeric_table(path)
        except Exception as e:
            QMessageBox.warning(self, "Cannot Read File", str(e))
            return
        self._table, self._path = t, path
        self.edit_path.setText(path)

        n, ncols = t["data"].shape
        self._fill_columns(ncols)

        if not self._editing or not self.edit_name.text().strip():
            title = t["header"][0].strip() if t["header"] else ""
            self.edit_name.setText(title or os.path.splitext(os.path.basename(path))[0])

        msg = f"{n} points, {ncols} columns; {len(t['header'])} header line(s) skipped."
        if t["declared_count"] is not None:
            msg += (f" Header declares {t['declared_count']} points"
                    + (" (matches)." if t["declared_count"] == n else f" -- MISMATCH with the {n} parsed."))
        if t["skipped_rows"]:
            msg += f" {t['skipped_rows']} numeric row(s) with a different column count were ignored."
        self.lbl_info.setText(msg)
        self._preview()

    def _scales(self):
        try:
            return float(self.edit_sx.text()), float(self.edit_sy.text())
        except ValueError:
            return None

    def _build_curve(self):
        if self._table is None:
            return None
        sc = self._scales()
        if sc is None:
            return None
        xi, yi = self.combo_xcol.currentIndex(), self.combo_ycol.currentIndex()
        if xi < 0 or yi < 0 or xi == yi:
            return None
        d = self._table["data"]
        color, width, style = self.style.values()
        return make_reference_curve(
            self.edit_name.text() or "Reference", d[:, xi], d[:, yi],
            self.combo_xunit.currentText(), self.combo_yunit.currentText(),
            self.chk_flip_x.isChecked(), self.chk_flip_y.isChecked(),
            sc[0], sc[1], source=self._path, notes=self.edit_notes.text().strip(),
            color=color, linewidth=width, linestyle=style)

    def _preview(self, *_):
        self.ax.clear()
        style_plot_axes(self.figure, self.ax)
        c = self._build_curve()
        if c is not None:
            xs = np.array(c["x"]) / LENGTH_UNITS[self.combo_xunit.currentText()]
            ys = np.array(c["y"]) / FORCE_UNITS[self.combo_yunit.currentText()]
            self.ax.plot(xs, ys, color=c["color"] or COLORS["accent"],
                         linewidth=c["linewidth"], linestyle=c["linestyle"])
            self.ax.axhline(0, color=COLORS["text_secondary"], lw=0.8)
            self.ax.axvline(0, color=COLORS["text_secondary"], lw=0.8)
            self.ax.set_xlabel(f"Displacement ({self.combo_xunit.currentText()})")
            self.ax.set_ylabel(f"Force ({self.combo_yunit.currentText()})")
        self.figure.tight_layout()
        self.canvas.draw_idle()

    def _on_accept(self):
        if self._table is None:
            QMessageBox.warning(self, "No File", "Select a file first.")
            return
        name = self.edit_name.text().strip()
        if not name:
            QMessageBox.warning(self, "Name Required", "Please enter a name for this curve.")
            return
        if name in self._existing:
            QMessageBox.warning(self, "Duplicate Name", "A reference curve with that name already exists.")
            return
        if self._scales() is None:
            QMessageBox.warning(self, "Invalid Scale", "Scale factors must be numbers.")
            return
        if self.combo_xcol.currentIndex() == self.combo_ycol.currentIndex():
            QMessageBox.warning(self, "Columns", "Horizontal and vertical columns must differ.")
            return
        self._curve = self._build_curve()
        self.accept()

    def result_curve(self):
        return self._curve
