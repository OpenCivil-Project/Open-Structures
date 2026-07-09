"""
dlg_area_gravity_load.py
------------------------
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGroupBox, QFormLayout,
    QLabel, QComboBox, QLineEdit, QPushButton, QRadioButton,
    QButtonGroup, QMessageBox, QSizePolicy
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QDoubleValidator

class AreaGravityLoadDialog(QDialog):
    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model
        
        self.setWindowFlag(Qt.WindowType.Tool)

        self.setWindowTitle("Assign Area Gravity Loads")
        self.setFixedWidth(370)
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
        self.combo_coord.addItem("GLOBAL")                                
        form_gen.addRow("Coordinate System:", self.combo_coord)

        root.addWidget(grp_gen)

        grp_grav = QGroupBox("Gravity Multipliers  (dimensionless)")
        form_grav = QFormLayout(grp_grav)
        form_grav.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form_grav.setHorizontalSpacing(12)

        validator = QDoubleValidator()
        validator.setNotation(QDoubleValidator.Notation.StandardNotation)

        self.edit_gx = QLineEdit("0")
        self.edit_gy = QLineEdit("0")
        self.edit_gz = QLineEdit("0")

        for edit in (self.edit_gx, self.edit_gy, self.edit_gz):
            edit.setValidator(validator)
            edit.setAlignment(Qt.AlignmentFlag.AlignRight)
            edit.setMinimumWidth(120)

        form_grav.addRow("Global X:", self.edit_gx)
        form_grav.addRow("Global Y:", self.edit_gy)
        form_grav.addRow("Global Z:", self.edit_gz)

        note = QLabel(
            "Tip: gz = \u22121.0 applies full self-weight downward.\n"
            "These multipliers are unit-independent.\n\n"
            "⚠️ Note: In-plane multipliers (gx, gy) cannot be applied to Tributary Area slabs."
        )
        note.setStyleSheet("color: gray; font-size: 11px;")
        note.setWordWrap(True)
        form_grav.addRow("", note)

        root.addWidget(grp_grav)

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
        self.combo_coord.setCurrentText("GLOBAL")
        self.edit_gx.setText("0")
        self.edit_gy.setText("0")
        self.edit_gz.setText("0")
        self.rb_replace.setChecked(True)

    def _apply(self):
                                                                      
        main_window = self.parent()
        selected_ids = list(main_window.selected_area_ids)

        if not selected_ids:
            QMessageBox.information(self, "No Selection", "Please select one or more area elements first.")
            return

        pattern = self.combo_pattern.currentText()
        if not pattern:
            QMessageBox.warning(self, "No Pattern", "Please select a load pattern.")
            return

        coord = self.combo_coord.currentText()
        gx    = self._read_float(self.edit_gx)
        gy    = self._read_float(self.edit_gy)
        gz    = self._read_float(self.edit_gz)
        mode  = self._get_mode()

        errors = []
        trib_error_flag = False

        for aid in selected_ids:
            area = self.model.area_elements.get(aid)
            if not area: continue
            
            if hasattr(area.section, 'modeling_type') and area.section.modeling_type == "Tributary Area":
                if abs(gx) > 1e-9 or abs(gy) > 1e-9:
                    trib_error_flag = True
                    continue                                                         

            try:
                self.model.assign_area_gravity_load(aid, pattern, gx, gy, gz, coord, mode)
            except KeyError as e:
                errors.append(str(e))

        if trib_error_flag:
            QMessageBox.warning(self, "Invalid Multiplier", "In-plane gravity multipliers (gx, gy) cannot be applied to Tributary Area slabs. They only transfer vertical (gz) self-weight.\n\nThose slabs were skipped.")

        if errors:
            QMessageBox.warning(self, "Assignment Error", "Some elements could not be updated:\n" + "\n".join(errors))

        main_window.selected_area_ids.clear()
        main_window._refresh_selection_overlay()
        main_window.update_yield_lines()
        main_window.draw_both_canvases()

    def _ok(self):
        self._apply()
        self.close()
