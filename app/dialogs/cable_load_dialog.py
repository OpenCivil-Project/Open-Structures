from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QComboBox, QRadioButton, QLineEdit, QPushButton,
                             QGroupBox, QFormLayout, QMessageBox)
from PyQt6.QtCore import Qt
from app.ui.theme import apply_dialog_style
from core.units import unit_registry

class AssignCableLoadDialog(QDialog):
    """
    Open // Structures - Assign Cable Distributed Loads
    Matches SAP2000's interface exactly.
    """
    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model
        
        apply_dialog_style(self)
        self.setWindowTitle("Assign Cable Distributed Loads")
        self.setFixedWidth(500)

        root = QVBoxLayout(self)
        root.setSpacing(12)
        root.setContentsMargins(16, 16, 16, 16)

        top_layout = QHBoxLayout()
        top_layout.setSpacing(16)

        general_group = QGroupBox("General")
        general_form = QFormLayout(general_group)
        general_form.setVerticalSpacing(10)

        self.combo_pattern = QComboBox()
        if self.model and hasattr(self.model, 'load_patterns'):
            self.combo_pattern.addItems(list(self.model.load_patterns.keys()))
        else:
            self.combo_pattern.addItem("DEAD")

        self.combo_coord = QComboBox()
        self.combo_coord.addItems(["GLOBAL", "LOCAL"])

        self.combo_dir = QComboBox()
        self.combo_dir.addItems(["Gravity", "X", "Y", "Z", "Projected X", "Projected Y", "Projected Z"])

        self.combo_type = QComboBox()
        self.combo_type.addItems(["Force", "Moment"])

        general_form.addRow("Load Pattern", self.combo_pattern)
        general_form.addRow("Coordinate System", self.combo_coord)
        general_form.addRow("Load Direction", self.combo_dir)
        general_form.addRow("Load Type", self.combo_type)

        top_layout.addWidget(general_group, stretch=2)

        options_col = QVBoxLayout()
        
        opt_group = QGroupBox("Options")
        opt_layout = QVBoxLayout(opt_group)
        opt_layout.setSpacing(8)

        self.rad_add = QRadioButton("Add to Existing Loads")
        self.rad_replace = QRadioButton("Replace Existing Loads")
        self.rad_delete = QRadioButton("Delete Existing Loads")
        self.rad_replace.setChecked(True)

        opt_layout.addWidget(self.rad_add)
        opt_layout.addWidget(self.rad_replace)
        opt_layout.addWidget(self.rad_delete)
        options_col.addWidget(opt_group)

        uni_group = QGroupBox("Uniform Load")
        uni_layout = QHBoxLayout(uni_group)
        
        self.input_load = QLineEdit("0")
        self.lbl_unit = QLabel("")                        
        
        uni_layout.addWidget(self.input_load)
        uni_layout.addWidget(self.lbl_unit)
        options_col.addWidget(uni_group)

        top_layout.addLayout(options_col, stretch=1)
        root.addLayout(top_layout)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.btn_reset = QPushButton("Reset Form to Default Values")
        self.btn_reset.clicked.connect(self._reset_form)

        self.btn_ok = QPushButton("OK")
        self.btn_ok.setObjectName("primary")
        self.btn_ok.setFixedWidth(80)
        self.btn_ok.clicked.connect(self.accept)

        self.btn_close = QPushButton("Close")
        self.btn_close.setObjectName("secondary")
        self.btn_close.setFixedWidth(80)
        self.btn_close.clicked.connect(self.reject)

        self.btn_apply = QPushButton("Apply")
        self.btn_apply.setFixedWidth(80)

        btn_layout.addWidget(self.btn_reset)
        btn_layout.addSpacing(20)
        btn_layout.addWidget(self.btn_ok)
        btn_layout.addWidget(self.btn_close)
        btn_layout.addWidget(self.btn_apply)

        root.addLayout(btn_layout)

        self.combo_coord.currentIndexChanged.connect(self._update_directions)
        self.combo_type.currentTextChanged.connect(self._update_units_label)
        self._update_units_label()

    def _update_directions(self):
        coord = self.combo_coord.currentText()
        self.combo_dir.clear()
        if coord == "GLOBAL":
            self.combo_dir.addItems(["Gravity", "X", "Y", "Z", "Projected X", "Projected Y", "Projected Z"])
        else:
            self.combo_dir.addItems(["1", "2", "3"])

    def _update_units_label(self):
        """Updates the text label next to the input box based on Force vs Moment."""
        if self.combo_type.currentText() == "Force":
            self.lbl_unit.setText(unit_registry.distributed_load_unit)
        else:
            self.lbl_unit.setText(unit_registry.force_unit_name)

    def _reset_form(self):
        self.combo_pattern.setCurrentIndex(0)
        self.combo_coord.setCurrentText("GLOBAL")
        self.combo_dir.setCurrentText("Gravity")
        self.combo_type.setCurrentText("Force")
        self.rad_replace.setChecked(True)
        self.input_load.setText("0")

    def get_data(self):
        """Returns a clean dictionary of the user's inputs converted exactly to base SI units."""
        try:
            disp_val = float(self.input_load.text() or 0)
        except ValueError:
            QMessageBox.warning(self, "Input Error", "Please enter a valid numeric value for the load.")
            return None

        load_type = self.combo_type.currentText()
        
        dist_scale = unit_registry.force_scale / unit_registry.length_scale
        
        if load_type == "Moment":
                                                       
            si_val = disp_val / unit_registry.force_scale
        else:
                                                
            si_val = disp_val / dist_scale

        mode = "replace"
        if self.rad_add.isChecked(): mode = "add"
        elif self.rad_delete.isChecked(): mode = "delete"

        return {
            "pattern": self.combo_pattern.currentText(),
            "coord_sys": self.combo_coord.currentText(),
            "direction": self.combo_dir.currentText(),
            "load_type": load_type,
            "mode": mode,
            "value": si_val 
        }
