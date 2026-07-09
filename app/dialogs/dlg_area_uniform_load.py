"""
dlg_area_uniform_load.py
------------------------
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
    DIRECTIONS = [
        "Gravity",                             
        "Local 1",                             
        "Local 2",                 
        "Local 3",                 
        "Global X",
        "Global Y",
        "Global Z",
    ]

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model
        
        self.setWindowFlag(Qt.WindowType.Tool)
        
        self.setWindowTitle("Assign Area Uniform Loads")
        self.setFixedWidth(390)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)

        self._build_ui()
        self._populate_patterns()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        grp_gen = QGroupBox("General")
        form_gen = QFormLayout(grp_gen)
        form_gen.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
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
        form_load.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
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

        self._mode_grp.addButton(self.rb_add, 0)
        self._mode_grp.addButton(self.rb_replace, 1)
        self._mode_grp.addButton(self.rb_delete, 2)

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
        btn_close.clicked.connect(self.close)
        btn_apply.clicked.connect(self._apply)

        btn_row.addWidget(btn_ok)
        btn_row.addWidget(btn_close)
        btn_row.addWidget(btn_apply)
        root.addLayout(btn_row)

    def _populate_patterns(self):
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
        self.combo_coord.setCurrentIndex(0)
        self.combo_direction.setCurrentText("Gravity")
        self.edit_load.setText("0")
        self.rb_replace.setChecked(True)
        self.lbl_unit.setText(unit_registry.pressure_unit)

    def _apply(self):
                                                                       
        main_window = self.parent()
        selected_ids = list(main_window.selected_area_ids)

        if not selected_ids:
            QMessageBox.information(self, "No Selection", "Please select one or more area elements on the canvas first.")
            return

        pattern = self.combo_pattern.currentText()
        if not pattern:
            QMessageBox.warning(self, "No Pattern", "Please select a load pattern.")
            return

        coord     = self.combo_coord.currentText()
        direction = self.combo_direction.currentText()
        mode      = self._get_mode()

        display_load = self._read_float(self.edit_load)
        load_si      = unit_registry.from_display_pressure(display_load)

        errors = []
        trib_error_flag = False
        valid_trib_dirs = ["Gravity", "Global Z", "Local 3"]

        for aid in selected_ids:
            area = self.model.area_elements.get(aid)
            if not area: continue
            
            if hasattr(area.section, 'modeling_type') and area.section.modeling_type == "Tributary Area":
                if direction not in valid_trib_dirs:
                    trib_error_flag = True
                    continue                                

            try:
                self.model.assign_area_uniform_load(aid, pattern, load_si, direction, coord, mode)
            except KeyError as e:
                errors.append(str(e))

        if trib_error_flag:
            QMessageBox.warning(self, "Invalid Direction", "In-plane loads (X, Y, Local 1, Local 2) cannot be applied to Tributary Area slabs. They only transfer Gravity/Z loads.\n\nThose slabs were skipped.")

        if errors:
            QMessageBox.warning(self, "Assignment Error", "Some elements could not be updated:\n" + "\n".join(errors))

        main_window.selected_area_ids.clear()
        main_window._refresh_selection_overlay()
        main_window.update_yield_lines()
        main_window.draw_both_canvases()

    def _ok(self):
        self._apply()
        self.close()
