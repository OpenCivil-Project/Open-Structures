"""
pushover_parameters_dialog.py

Define > Pushover Parameter Sets > Force vs Displacement...

Two dialogs:

    PushoverParametersDialog   the list ("Define Pushover Parameters"):
                               Add New / Add Copy / Modify-Show / Delete.
                               Works on a deep copy and only hands it back
                               on OK, so Cancel really cancels.
    PushoverParamEditDialog    one set: plot type, units, axis range
                               (auto or manual), labels, notes.

A parameter set is a plain dict (see StructuralModel.make_pushover_param_set)
that is saved with the model. A set says HOW to draw, never WHICH case:
the case is picked in the Pushover Curve viewer, so one set works for any
case of a single or batch run. The viewer only *consumes* these sets.

Manual axis ranges are stored in BASE units (N, m, step number) and shown
in the set's own units, so they stay physically correct if the units
change (either this set's units, or the global ones when the set follows
"Model display units").

Rules:
  * there is always at least one set -- the last one cannot be deleted
  * names are unique
"""

import copy

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QDoubleValidator
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox, QLabel,
    QComboBox, QPushButton, QLineEdit, QCheckBox, QPlainTextEdit,
    QListWidget, QListWidgetItem, QDialogButtonBox, QMessageBox,
)

from app.ui.theme import apply_dialog_style, CurveStyleEditor
from core.units import UNIT_SYSTEMS, MODEL_DISPLAY_UNITS, make_unit_converter

PLOT_TYPES = [
    "Resultant Base Shear vs Monitored Displacement",
    "Base Reaction FX vs Monitored Displacement",
    "Base Reaction FY vs Monitored Displacement",
    "Base Reaction FZ vs Monitored Displacement",
    "Monitored Displacement vs Step Number",
]

PLOT_TYPE_AXES = {
    PLOT_TYPES[0]: ("length", "force"),
    PLOT_TYPES[1]: ("length", "force"),
    PLOT_TYPES[2]: ("length", "force"),
    PLOT_TYPES[3]: ("length", "force"),
    PLOT_TYPES[4]: ("step", "length"),
}

def axis_to_display(kind, base_val, conv):
    if kind == "length":
        return conv.to_display_length(base_val)
    if kind == "force":
        return conv.to_display_force(base_val)
    return base_val

def axis_from_display(kind, disp_val, conv):
    if kind == "length":
        return conv.from_display_length(disp_val)
    if kind == "force":
        return conv.from_display_force(disp_val)
    return disp_val

def axis_unit_name(kind, conv):
    if kind == "length":
        return conv.length_unit_name
    if kind == "force":
        return conv.force_unit_name
    return "step"

class PushoverParamEditDialog(QDialog):
    def __init__(self, parent, model, pset, existing_names, curve_names=()):
        super().__init__(parent)
        self.setWindowTitle("Pushover Parameters - Force vs Displacement")
        self.setModal(True)
        apply_dialog_style(self)

        self._model = model
        self._curve_names = list(curve_names)
        self._pset = copy.deepcopy(pset)
        self._existing = {n for n in existing_names if n != pset.get("name")}

        self._state_ptype = self._pset.get("plot_type", PLOT_TYPES[0])
        if self._state_ptype not in PLOT_TYPES:
            self._state_ptype = PLOT_TYPES[0]
        self._state_units = self._pset.get("units", MODEL_DISPLAY_UNITS)
        self._base = {k: float(self._pset.get(k, 0.0))
                      for k in ("x_min", "x_max", "y_min", "y_max")}

        self._build_ui()
        self._load_into_widgets()

    def _build_ui(self):
        outer = QVBoxLayout(self)

        gen = QGroupBox("Parameters")
        g = QGridLayout(gen)

        g.addWidget(QLabel("Name"), 0, 0)
        self.edit_name = QLineEdit()
        g.addWidget(self.edit_name, 0, 1)

        g.addWidget(QLabel("Plot Type"), 1, 0)
        self.combo_plot = QComboBox()
        self.combo_plot.addItems(PLOT_TYPES)
        g.addWidget(self.combo_plot, 1, 1)

        g.addWidget(QLabel("Units"), 2, 0)
        self.combo_units = QComboBox()
        self.combo_units.addItem(MODEL_DISPLAY_UNITS)
        self.combo_units.addItems(UNIT_SYSTEMS)
        g.addWidget(self.combo_units, 2, 1)
        g.setColumnStretch(1, 1)
        outer.addWidget(gen)

        ranges = QHBoxLayout()
        self.grp_x, self.chk_auto_x, self.edit_x_min, self.edit_x_max = self._range_group("Horizontal Range")
        self.grp_y, self.chk_auto_y, self.edit_y_min, self.edit_y_max = self._range_group("Vertical Range")
        ranges.addWidget(self.grp_x)
        ranges.addWidget(self.grp_y)
        outer.addLayout(ranges)

        lab = QGroupBox("Axis Labels")
        lg = QGridLayout(lab)
        lg.addWidget(QLabel("Horizontal"), 0, 0)
        self.edit_label_x = QLineEdit()
        self.edit_label_x.setPlaceholderText("Automatic")
        lg.addWidget(self.edit_label_x, 0, 1)
        lg.addWidget(QLabel("Vertical"), 1, 0)
        self.edit_label_y = QLineEdit()
        self.edit_label_y.setPlaceholderText("Automatic")
        lg.addWidget(self.edit_label_y, 1, 1)
        lg.setColumnStretch(1, 1)
        outer.addWidget(lab)

        notes = QGroupBox("Notes")
        nl = QVBoxLayout(notes)
        self.edit_notes = QPlainTextEdit()
        self.edit_notes.setFixedHeight(60)
        nl.addWidget(self.edit_notes)
        outer.addWidget(notes)

        sty = QGroupBox("Analysis Curve Style")
        stl = QVBoxLayout(sty)
        self.style_curve = CurveStyleEditor(default_width=2.2, default_style="-")
        stl.addWidget(self.style_curve)
        outer.addWidget(sty)

        ov = QGroupBox("Overlay Reference Curves")
        ovl = QVBoxLayout(ov)
        if self._curve_names:
            self.list_overlay = QListWidget()
            self.list_overlay.setFixedHeight(72)
            for n in self._curve_names:
                it = QListWidgetItem(n)
                it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                it.setCheckState(Qt.CheckState.Unchecked)
                self.list_overlay.addItem(it)
            ovl.addWidget(self.list_overlay)
        else:
            self.list_overlay = None
            hint = QLabel('No reference curves defined. Use "Import Reference Curve..." '
                          'in the Define Pushover Parameters list.')
            hint.setWordWrap(True)
            hint.setStyleSheet("color: gray;")
            ovl.addWidget(hint)
        outer.addWidget(ov)

        btn_row = QHBoxLayout()
        self.btn_reset = QPushButton("Reset Defaults")
        self.btn_reset.setObjectName("secondary")
        self.btn_reset.clicked.connect(self._on_reset)
        btn_row.addWidget(self.btn_reset)
        btn_row.addStretch(1)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.button(QDialogButtonBox.StandardButton.Ok).setObjectName("primary")
        btns.button(QDialogButtonBox.StandardButton.Cancel).setObjectName("secondary")
        btns.accepted.connect(self._on_accept)
        btns.rejected.connect(self.reject)
        btn_row.addWidget(btns)
        outer.addLayout(btn_row)

        self.combo_plot.currentIndexChanged.connect(self._on_basis_changed)
        self.combo_units.currentIndexChanged.connect(self._on_basis_changed)
        self.chk_auto_x.toggled.connect(self._sync_enabled)
        self.chk_auto_y.toggled.connect(self._sync_enabled)

    def _range_group(self, title):
        grp = QGroupBox(title)
        lay = QGridLayout(grp)
        chk = QCheckBox("Automatic")
        lay.addWidget(chk, 0, 0, 1, 2)
        e_min, e_max = QLineEdit(), QLineEdit()
        for e in (e_min, e_max):
            v = QDoubleValidator()
            v.setNotation(QDoubleValidator.Notation.ScientificNotation)
            e.setValidator(v)
        lay.addWidget(QLabel("Min"), 1, 0)
        lay.addWidget(e_min, 1, 1)
        lay.addWidget(QLabel("Max"), 2, 0)
        lay.addWidget(e_max, 2, 1)
        return grp, chk, e_min, e_max

    def _kinds(self):
        return PLOT_TYPE_AXES[self._state_ptype]

    def _commit_fields(self):
        """Text boxes -> base-unit state, using the units/plot type they were shown in."""
        conv = make_unit_converter(self._state_units)
        kx, ky = self._kinds()
        for key, edit, kind in (("x_min", self.edit_x_min, kx), ("x_max", self.edit_x_max, kx),
                                ("y_min", self.edit_y_min, ky), ("y_max", self.edit_y_max, ky)):
            try:
                self._base[key] = axis_from_display(kind, float(edit.text()), conv)
            except ValueError:
                pass                                                         

    def _refresh_fields(self):
        """Base-unit state -> text boxes in the CURRENT units/plot type, and retitle groups."""
        conv = make_unit_converter(self._state_units)
        kx, ky = self._kinds()
        for key, edit, kind in (("x_min", self.edit_x_min, kx), ("x_max", self.edit_x_max, kx),
                                ("y_min", self.edit_y_min, ky), ("y_max", self.edit_y_max, ky)):
            edit.setText(f"{axis_to_display(kind, self._base[key], conv):.6g}")
        self.grp_x.setTitle(f"Horizontal Range ({axis_unit_name(kx, conv)})")
        self.grp_y.setTitle(f"Vertical Range ({axis_unit_name(ky, conv)})")

    def _on_basis_changed(self, *_):
        self._commit_fields()                                                    
        self._state_ptype = self.combo_plot.currentText()
        self._state_units = self.combo_units.currentText()
        self._refresh_fields()                                                

    def _sync_enabled(self, *_):
        for chk, a, b in ((self.chk_auto_x, self.edit_x_min, self.edit_x_max),
                          (self.chk_auto_y, self.edit_y_min, self.edit_y_max)):
            a.setEnabled(not chk.isChecked())
            b.setEnabled(not chk.isChecked())

    def _load_into_widgets(self):
        p = self._pset
        self.edit_name.setText(p.get("name", ""))

        self.combo_plot.blockSignals(True)
        self.combo_units.blockSignals(True)
        self.combo_plot.setCurrentText(self._state_ptype)
        u = p.get("units", MODEL_DISPLAY_UNITS)
        self.combo_units.setCurrentText(u if self.combo_units.findText(u) >= 0 else MODEL_DISPLAY_UNITS)
        self._state_units = self.combo_units.currentText()
        self.combo_plot.blockSignals(False)
        self.combo_units.blockSignals(False)

        self.chk_auto_x.setChecked(bool(p.get("auto_x", True)))
        self.chk_auto_y.setChecked(bool(p.get("auto_y", True)))
        self._refresh_fields()
        self._sync_enabled()

        self.edit_label_x.setText(p.get("label_x", ""))
        self.edit_label_y.setText(p.get("label_y", ""))
        self.edit_notes.setPlainText(p.get("notes", ""))
        self.style_curve.set_values(p.get("curve_color", ""), p.get("curve_width", 2.2),
                                    p.get("curve_style", "-"))
        if self.list_overlay is not None:
            wanted = set(p.get("overlay_curves") or [])
            for i in range(self.list_overlay.count()):
                it = self.list_overlay.item(i)
                it.setCheckState(Qt.CheckState.Checked if it.text() in wanted else Qt.CheckState.Unchecked)

    def _on_reset(self):
        fresh = self._model.make_pushover_param_set(                                    
            self.edit_name.text().strip() or self._pset.get("name", "PO"))
        self._pset = fresh
        self._state_ptype = fresh["plot_type"]
        self._state_units = fresh["units"]
        self._base = {k: float(fresh[k]) for k in ("x_min", "x_max", "y_min", "y_max")}
        self._load_into_widgets()

    def _on_accept(self):
        name = self.edit_name.text().strip()
        if not name:
            QMessageBox.warning(self, "Name Required", "Please enter a name for this parameter set.")
            return
        if name in self._existing:
            QMessageBox.warning(self, "Duplicate Name", "A parameter set with that name already exists.")
            return

        self._commit_fields()
        if not self.chk_auto_x.isChecked() and self._base["x_min"] >= self._base["x_max"]:
            QMessageBox.warning(self, "Invalid Range", "Horizontal range: Min must be less than Max.")
            return
        if not self.chk_auto_y.isChecked() and self._base["y_min"] >= self._base["y_max"]:
            QMessageBox.warning(self, "Invalid Range", "Vertical range: Min must be less than Max.")
            return
        self.accept()

    def result_values(self):
        out = copy.deepcopy(self._pset)
        out.pop("case_name", None)                                                                 
        out.update({
            "name": self.edit_name.text().strip(),
            "kind": "force_disp",
            "plot_type": self.combo_plot.currentText(),
            "units": self.combo_units.currentText(),
            "auto_x": self.chk_auto_x.isChecked(),
            "auto_y": self.chk_auto_y.isChecked(),
            "label_x": self.edit_label_x.text().strip(),
            "label_y": self.edit_label_y.text().strip(),
            "notes": self.edit_notes.toPlainText().strip(),
            "curve_color": self.style_curve.values()[0],
            "curve_width": self.style_curve.values()[1],
            "curve_style": self.style_curve.values()[2],
            "overlay_curves": ([self.list_overlay.item(i).text() for i in range(self.list_overlay.count())
                                if self.list_overlay.item(i).checkState() == Qt.CheckState.Checked]
                               if self.list_overlay is not None else list(self._pset.get("overlay_curves") or [])),
        })
        out.update(self._base)
        return out

class PushoverParametersDialog(QDialog):
    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Define Pushover Parameters - Force vs Displacement")
        self.setModal(True)
        self.resize(560, 540)
        apply_dialog_style(self)

        self._model = model
        self._sets = copy.deepcopy(getattr(model, "pushover_param_sets", []) or [])
        if not self._sets:                                                                   
            self._sets = [model.make_pushover_param_set("PO1")]

        self._curves = copy.deepcopy(getattr(model, "reference_curves", []) or [])
        self._build_ui()
        self._fill_list(select=0)
        self._fill_curves()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        row = QHBoxLayout()

        left = QGroupBox("Pushover Parameters")
        ll = QVBoxLayout(left)
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._on_selection)
        self.list.itemDoubleClicked.connect(lambda *_: self._on_modify())
        ll.addWidget(self.list, 1)
        self.lbl_summary = QLabel("")
        self.lbl_summary.setWordWrap(True)
        self.lbl_summary.setStyleSheet("color: gray;")
        ll.addWidget(self.lbl_summary)
        row.addWidget(left, 1)

        right = QGroupBox("Click to:")
        rl = QVBoxLayout(right)
        self.btn_add = QPushButton("Add New Parameters...")
        self.btn_copy = QPushButton("Add Copy of Parameters...")
        self.btn_modify = QPushButton("Modify/Show Parameters...")
        self.btn_delete = QPushButton("Delete Parameters")
        self.btn_delete.setObjectName("danger")
        self.btn_add.clicked.connect(self._on_add)
        self.btn_copy.clicked.connect(self._on_copy)
        self.btn_modify.clicked.connect(self._on_modify)
        self.btn_delete.clicked.connect(self._on_delete)
        for b in (self.btn_add, self.btn_copy, self.btn_modify, self.btn_delete):
            rl.addWidget(b)
        rl.addStretch(1)
        right.setFixedWidth(220)
        row.addWidget(right)
        outer.addLayout(row, 1)

        cgrp = QGroupBox("Reference Curves (experimental / literature, for overlay)")
        crow = QHBoxLayout(cgrp)
        self.list_curves = QListWidget()
        self.list_curves.setMinimumHeight(110)
        self.list_curves.currentRowChanged.connect(self._on_curve_selection)
        self.list_curves.itemDoubleClicked.connect(lambda *_: self._on_modify_curve())
        crow.addWidget(self.list_curves, 1)
        cbtns = QVBoxLayout()
        self.btn_curve_import = QPushButton("Import Reference Curve...")
        self.btn_curve_modify = QPushButton("Modify/Show Reference Curve...")
        self.btn_curve_remove = QPushButton("Remove Reference Curve")
        self.btn_curve_remove.setObjectName("danger")
        self.btn_curve_import.clicked.connect(self._on_import_curve)
        self.btn_curve_modify.clicked.connect(self._on_modify_curve)
        self.btn_curve_remove.clicked.connect(self._on_remove_curve)
        cbtns.addWidget(self.btn_curve_import)
        cbtns.addWidget(self.btn_curve_modify)
        cbtns.addWidget(self.btn_curve_remove)
        cbtns.addStretch(1)
        crow.addLayout(cbtns)
        outer.addWidget(cgrp)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.button(QDialogButtonBox.StandardButton.Ok).setObjectName("primary")
        btns.button(QDialogButtonBox.StandardButton.Cancel).setObjectName("secondary")
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        outer.addWidget(btns)

    def _names(self):
        return [s["name"] for s in self._sets]

    def _next_name(self):
        n = 1
        while f"PO{n}" in self._names():
            n += 1
        return f"PO{n}"

    def _fill_list(self, select=0):
        self.list.blockSignals(True)
        self.list.clear()
        for s in self._sets:
            self.list.addItem(s["name"])
        self.list.blockSignals(False)
        self.list.setCurrentRow(max(0, min(select, len(self._sets) - 1)))
        self._on_selection(self.list.currentRow())

    def _on_selection(self, row):
        have = 0 <= row < len(self._sets)
        self.btn_copy.setEnabled(have)
        self.btn_modify.setEnabled(have)
        self.btn_delete.setEnabled(have and len(self._sets) > 1)                                  
        self.btn_delete.setToolTip("" if len(self._sets) > 1 else "At least one parameter set must exist.")
        if have:
            s = self._sets[row]
            self.lbl_summary.setText(f"{s.get('plot_type', '')}\nUnits: {s.get('units', '')}")
        else:
            self.lbl_summary.setText("")

    def _edit(self, pset):
        dlg = PushoverParamEditDialog(self, self._model, pset, self._names(),
                                      [c["name"] for c in self._curves])
        if dlg.exec() == QDialog.DialogCode.Accepted:
            return dlg.result_values()
        return None

    def _on_add(self):
        fresh = self._model.make_pushover_param_set(self._next_name())
        vals = self._edit(fresh)
        if vals is not None:
            self._sets.append(vals)
            self._fill_list(select=len(self._sets) - 1)

    def _on_copy(self):
        row = self.list.currentRow()
        if not (0 <= row < len(self._sets)):
            return
        src = copy.deepcopy(self._sets[row])
        src["name"] = self._next_name()
        vals = self._edit(src)
        if vals is not None:
            self._sets.append(vals)
            self._fill_list(select=len(self._sets) - 1)

    def _on_modify(self):
        row = self.list.currentRow()
        if not (0 <= row < len(self._sets)):
            return
        vals = self._edit(self._sets[row])
        if vals is not None:
            self._sets[row] = vals
            self._fill_list(select=row)

    def _on_delete(self):
        row = self.list.currentRow()
        if len(self._sets) <= 1 or not (0 <= row < len(self._sets)):
            return
        del self._sets[row]
        self._fill_list(select=row)

    def _fill_curves(self, select=0):
        self.list_curves.blockSignals(True)
        self.list_curves.clear()
        for c in self._curves:
            src = f", {c['source']}" if c.get("source") else ""
            self.list_curves.addItem(f"{c['name']}   ({len(c['x'])} pts{src})")
        self.list_curves.blockSignals(False)
        if self._curves:
            self.list_curves.setCurrentRow(max(0, min(select, len(self._curves) - 1)))
        self._on_curve_selection(self.list_curves.currentRow())

    def _on_curve_selection(self, row):
        have = 0 <= row < len(self._curves)
        self.btn_curve_remove.setEnabled(have)
        self.btn_curve_modify.setEnabled(have)

    def _on_import_curve(self):
        from app.dialogs.reference_curve_import_dialog import ReferenceCurveImportDialog
        dlg = ReferenceCurveImportDialog(self, [c["name"] for c in self._curves])
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        curve = dlg.result_curve()
        if curve is not None:
            self._curves.append(curve)
            self._fill_curves(select=len(self._curves) - 1)

    def _on_modify_curve(self):
        from app.dialogs.reference_curve_import_dialog import ReferenceCurveImportDialog
        row = self.list_curves.currentRow()
        if not (0 <= row < len(self._curves)):
            return
        old = self._curves[row]
        dlg = ReferenceCurveImportDialog(self, [c["name"] for c in self._curves], curve=old)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        new = dlg.result_curve()
        if new is None:
            return
        if new["name"] != old["name"]:                                                              
            for s in self._sets:
                s["overlay_curves"] = [new["name"] if n == old["name"] else n
                                       for n in (s.get("overlay_curves") or [])]
        self._curves[row] = new
        self._fill_curves(select=row)

    def _on_remove_curve(self):
        row = self.list_curves.currentRow()
        if not (0 <= row < len(self._curves)):
            return
        name = self._curves[row]["name"]
        used = [s["name"] for s in self._sets if name in (s.get("overlay_curves") or [])]
        msg = f"Remove reference curve '{name}'?"
        if used:
            msg += "\n\nIt is overlaid by: " + ", ".join(used) + "."
        if QMessageBox.question(self, "Remove Reference Curve", msg) != QMessageBox.StandardButton.Yes:
            return
        del self._curves[row]
        for s in self._sets:
            if name in (s.get("overlay_curves") or []):
                s["overlay_curves"] = [n for n in s["overlay_curves"] if n != name]
        self._fill_curves(select=row)

    def accept(self):
                                                                                     
        self._model.reference_curves = self.result_curves()
        super().accept()

    def result_curves(self):
        return copy.deepcopy(self._curves)

    def result_sets(self):
        return copy.deepcopy(self._sets)
