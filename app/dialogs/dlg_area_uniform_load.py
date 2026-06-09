"""
dlg_area_uniform_load.py
------------------------
SAP2000-style "Assign Area Uniform Loads" dialog.

Applies a uniform pressure (force / area) to selected AreaElements.

Unit handling
-------------
Values are **entered and displayed** in the active unit system (e.g. kN/m²).
They are **stored in SI** (N/m²) via unit_registry.from_display_pressure().

The pressure unit label next to the input field updates automatically from
unit_registry.pressure_unit so it always reflects the current unit system.

ONLY valid on AreaElements (shells/planes/asolids).  Frames don't have
uniform pressure loads — they use MemberLoad / MemberPointLoad instead.

Connection from main.py
-----------------------
    from app.dialogs.dlg_area_uniform_load import AreaUniformLoadDialog

    def on_assign_area_uniform_load(self):
        selected_ids = getattr(self.canvas, 'selected_area_ids', [])
        if not selected_ids:
            QMessageBox.information(self, "No Selection",
                                    "Select one or more area elements first.")
            return
        from app.dialogs.dlg_area_uniform_load import AreaUniformLoadDialog
        dlg = AreaUniformLoadDialog(self.model, selected_ids, parent=self)
        dlg.exec()
        self.draw_both_canvases()
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGroupBox, QFormLayout,
    QLabel, QComboBox, QLineEdit, QPushButton, QRadioButton,
    QButtonGroup, QMessageBox, QSizePolicy
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QDoubleValidator
from core.units import unit_registry

class AreaUniformLoadDialog(QDialog):
    """
    Assign Area Uniform Loads dialog — mirrors the SAP2000 UI.

    Parameters
    ----------
    model : StructuralModel
        The live model instance.
    selected_area_ids : list[int]
        IDs of the area elements currently selected on the canvas.
    parent : QWidget, optional
    """

    DIRECTIONS = [
        "Gravity",                             
        "Local 1",                             
        "Local 2",                 
        "Local 3",                 
        "Global X",
        "Global Y",
        "Global Z",
    ]

    def __init__(self, model, selected_area_ids, parent=None):
        super().__init__(parent)
        self.model = model
        self.selected_area_ids = list(selected_area_ids)

        self.setWindowTitle("Assign Area Uniform Loads")
        self.setFixedWidth(390)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )

        self._build_ui()
        self._populate_patterns()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        grp_gen = QGroupBox("General")
        form_gen = QFormLayout(grp_gen)
        form_gen.setLabelAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        form_gen.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )
        form_gen.setHorizontalSpacing(12)

        self.combo_pattern = QComboBox()
        form_gen.addRow("Load Pattern:", self.combo_pattern)

        self.combo_coord = QComboBox()
        self.combo_coord.addItems(["GLOBAL", "Local"])
        form_gen.addRow("Coordinate System:", self.combo_coord)

        self.combo_direction = QComboBox()
        self.combo_direction.addItems(self.DIRECTIONS)
        form_gen.addRow("Load Direction:", self.combo_direction)

        root.addWidget(grp_gen)

        grp_load = QGroupBox("Uniform Load")
        form_load = QFormLayout(grp_load)
        form_load.setLabelAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        form_load.setHorizontalSpacing(12)

        load_row = QHBoxLayout()
        load_row.setSpacing(6)

        self.edit_load = QLineEdit("0")
        self.edit_load.setValidator(QDoubleValidator(-1e18, 1e18, 6, self))
        self.edit_load.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.edit_load.setMinimumWidth(120)

        self.lbl_unit = QLabel(unit_registry.pressure_unit)
        self.lbl_unit.setMinimumWidth(60)

        load_row.addWidget(self.edit_load)
        load_row.addWidget(self.lbl_unit)
        load_row.addStretch()

        form_load.addRow("Load:", load_row)
        root.addWidget(grp_load)

        grp_opts = QGroupBox("Options")
        vlay = QVBoxLayout(grp_opts)
        vlay.setSpacing(4)

        self._mode_grp = QButtonGroup(self)
        self.rb_add     = QRadioButton("Add to Existing Loads")
        self.rb_replace = QRadioButton("Replace Existing Loads")
        self.rb_delete  = QRadioButton("Delete Existing Loads")
        self.rb_replace.setChecked(True)

        self._mode_grp.addButton(self.rb_add,     0)
        self._mode_grp.addButton(self.rb_replace, 1)
        self._mode_grp.addButton(self.rb_delete,  2)

        vlay.addWidget(self.rb_add)
        vlay.addWidget(self.rb_replace)
        vlay.addWidget(self.rb_delete)
        root.addWidget(grp_opts)

        btn_reset = QPushButton("Reset Form to Default Values")
        btn_reset.clicked.connect(self._reset)
        root.addWidget(btn_reset)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        btn_ok    = QPushButton("OK")
        btn_close = QPushButton("Close")
        btn_apply = QPushButton("Apply")

        for b in (btn_ok, btn_close, btn_apply):
            b.setFixedWidth(75)

        btn_ok.clicked.connect(self._ok)
        btn_close.clicked.connect(self.reject)
        btn_apply.clicked.connect(self._apply)

        btn_row.addWidget(btn_ok)
        btn_row.addWidget(btn_close)
        btn_row.addWidget(btn_apply)
        root.addLayout(btn_row)

    def _populate_patterns(self):
        """Fill Load Pattern combo from model."""
        self.combo_pattern.clear()
        for name in self.model.load_patterns:
            self.combo_pattern.addItem(name)

    def _get_mode(self) -> str:
        if self.rb_add.isChecked():     return "add"
        if self.rb_replace.isChecked(): return "replace"
        return "delete"

    def _read_float(self, edit: QLineEdit, fallback=0.0) -> float:
        try:
            return float(edit.text()) if edit.text().strip() else fallback
        except ValueError:
            return fallback

    def _reset(self):
        """Restore dialog to SAP2000 default values."""
        self.combo_coord.setCurrentIndex(0)
        self.combo_direction.setCurrentText("Gravity")
        self.edit_load.setText("0")
        self.rb_replace.setChecked(True)
                                                                             
        self.lbl_unit.setText(unit_registry.pressure_unit)

    def _apply(self):
        """
        Apply uniform load to all selected area elements.

        The user enters the value in the active display unit system
        (e.g. kN/m²).  We convert to SI (N/m²) before passing to the
        model so all stored values are always in base SI units.
        """
        pattern = self.combo_pattern.currentText()
        if not pattern:
            QMessageBox.warning(self, "No Pattern",
                                "Please select a load pattern.")
            return

        coord     = self.combo_coord.currentText()
        direction = self.combo_direction.currentText()
        mode      = self._get_mode()

        display_load = self._read_float(self.edit_load)
        load_si      = unit_registry.from_display_pressure(display_load)

        errors = []
        for aid in self.selected_area_ids:
            try:
                self.model.assign_area_uniform_load(
                    aid, pattern, load_si, direction, coord, mode)
            except KeyError as e:
                errors.append(str(e))

        if errors:
            QMessageBox.warning(self, "Assignment Error",
                                "Some elements could not be updated:\n" +
                                "\n".join(errors))

    def _ok(self):
        self._apply()
        self.accept()
