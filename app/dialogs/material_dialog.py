from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QListWidget, QPushButton, QGroupBox, QFormLayout,
                             QLineEdit, QComboBox, QMessageBox, QColorDialog,
                             QFrame, QSizePolicy)
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtCore import Qt
from core.properties import Material
from core.units import unit_registry
from core.integrity_checks import check_material_in_use

FORCE_SCALES = {
    "N":    1.0,
    "kN":   1 / 1_000.0,
    "kgf":  1 / 9.80665,
    "Tonf": 1 / 9_806.65,
    "kip":  1 / 4_448.22,
}

LENGTH_SCALES = {
    "m":  1.0,
    "cm": 100.0,
    "mm": 1_000.0,
    "ft": 3.28084,
    "in": 39.3701,
}

_STEEL_SI    = dict(E=2.0e11, nu=0.30, gamma=78_500.0, fy=2.75e8, fu=4.1e8)
_CONCRETE_SI = dict(E=3.0e10, nu=0.20, gamma=25_000.0, fy=3.0e7,  fu=0.0)

def _divider():
    """Thin horizontal separator line."""
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFrameShadow(QFrame.Shadow.Sunken)
    return line

class MaterialEditor(QDialog):
    """
    Material property editor with a dialog-local unit system.

    The local unit combo does NOT touch the project's unit_registry.
    It only controls how values are displayed / entered here.
    All data is stored internally and returned in SI base (N, m).
    """

    def __init__(self, material: Material | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Material Property Data")
        self.setFixedWidth(400)
        self.material_data: Material | None = None
        self.selected_color = (0.7, 0.7, 0.7, 1.0)

        self._f_scale  = FORCE_SCALES.get(unit_registry.force_unit_name,  1/1_000.0)
        self._l_scale  = LENGTH_SCALES.get(unit_registry.length_unit_name, 1.0)

        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(14, 14, 14, 14)

        id_group = QGroupBox("Identity")
        id_form  = QFormLayout(id_group)
        id_form.setVerticalSpacing(6)

        self.name_edit = QLineEdit("Mat1")
        id_form.addRow("Name:", self.name_edit)

        self.type_combo = QComboBox()
        self.type_combo.addItems(["Steel", "Concrete", "Other"])
        id_form.addRow("Type:", self.type_combo)

        color_row = QHBoxLayout()
        self.btn_color = QPushButton()
        self.btn_color.setFixedSize(80, 22)
        self.btn_color.setToolTip("Click to pick display colour")
        self.btn_color.clicked.connect(self._pick_color)
        color_row.addWidget(self.btn_color)
        color_row.addStretch()
        id_form.addRow("Colour:", color_row)

        root.addWidget(id_group)

        unit_group = QGroupBox("Input Units")
        unit_group.setToolTip("Dialog-only — project units are not affected")
        unit_layout = QHBoxLayout(unit_group)
        unit_layout.setSpacing(8)

        unit_layout.addWidget(QLabel("Force:"))
        self.combo_force = QComboBox()
        self.combo_force.addItems(list(FORCE_SCALES.keys()))
        self.combo_force.setCurrentText(unit_registry.force_unit_name)
        unit_layout.addWidget(self.combo_force)

        unit_layout.addSpacing(12)

        unit_layout.addWidget(QLabel("Length:"))
        self.combo_length = QComboBox()
        self.combo_length.addItems(list(LENGTH_SCALES.keys()))
        self.combo_length.setCurrentText(unit_registry.length_unit_name)
        unit_layout.addWidget(self.combo_length)

        note = QLabel("(project units unchanged)")
        note.setStyleSheet("color: gray; font-size: 10px;")
        unit_layout.addStretch()
        unit_layout.addWidget(note)

        root.addWidget(unit_group)

        prop_group = QGroupBox("Analysis Properties")
        prop_form  = QFormLayout(prop_group)
        prop_form.setVerticalSpacing(6)

        self.input_E   = QLineEdit()
        self.input_nu  = QLineEdit()
        self.input_rho = QLineEdit()

        self.lbl_E   = QLabel()                               
        self.lbl_rho = QLabel()

        prop_form.addRow(self.lbl_E,              self.input_E)
        prop_form.addRow("Poisson's Ratio (ν):", self.input_nu)
        prop_form.addRow(self.lbl_rho,            self.input_rho)

        root.addWidget(prop_group)

        des_group = QGroupBox("Design Strength")
        des_form  = QFormLayout(des_group)
        des_form.setVerticalSpacing(6)

        self.input_fy = QLineEdit()
        self.input_fu = QLineEdit()
        self.lbl_fy   = QLabel()
        self.lbl_fu   = QLabel()

        des_form.addRow(self.lbl_fy, self.input_fy)
        des_form.addRow(self.lbl_fu, self.input_fu)

        root.addWidget(des_group)

        root.addWidget(_divider())
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)
        ok_btn = QPushButton("OK")
        ok_btn.setFixedHeight(30)
        ok_btn.clicked.connect(self._save_data)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedHeight(30)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        root.addLayout(btn_layout)

        self.combo_force.currentTextChanged.connect(self._on_unit_changed)
        self.combo_length.currentTextChanged.connect(self._on_unit_changed)
        self.type_combo.currentTextChanged.connect(self._on_type_changed)

        self._refresh_labels()

        if material:
            self._load_material(material)
        else:
            self._on_type_changed(self.type_combo.currentText())

        self._update_color_button()

    def _stress_scale(self) -> float:
        """display_stress = SI_stress × stress_scale"""
        return self._f_scale / (self._l_scale ** 2)

    def _gamma_scale(self) -> float:
        """display_gamma = SI_gamma × gamma_scale"""
        return self._f_scale / (self._l_scale ** 3)

    def _force_unit(self) -> str:
        return self.combo_force.currentText()

    def _length_unit(self) -> str:
        return self.combo_length.currentText()

    def _stress_unit(self) -> str:
        return f"{self._force_unit()}/{self._length_unit()}²"

    def _gamma_unit(self) -> str:
        return f"{self._force_unit()}/{self._length_unit()}³"

    def _refresh_labels(self):
        su = self._stress_unit()
        gu = self._gamma_unit()
        self.lbl_E.setText(f"Elastic Modulus E  [{su}]:")
        self.lbl_rho.setText(f"Unit Weight γ  [{gu}]:")
        self.lbl_fy.setText(f"Yield Strength Fy  [{su}]:")
        self.lbl_fu.setText(f"Ultimate Strength Fu  [{su}]:")

    def _on_unit_changed(self):
        """Re-express all fields in the newly selected units."""

        old_ss = self._stress_scale()
        old_gs = self._gamma_scale()

        try:
            si_E   = float(self.input_E.text()   or 0) / old_ss
            si_rho = float(self.input_rho.text() or 0) / old_gs
            si_fy  = float(self.input_fy.text()  or 0) / old_ss
            si_fu  = float(self.input_fu.text()  or 0) / old_ss
        except ValueError:
            si_E = si_rho = si_fy = si_fu = 0.0

        self._f_scale = FORCE_SCALES[self.combo_force.currentText()]
        self._l_scale = LENGTH_SCALES[self.combo_length.currentText()]

        new_ss = self._stress_scale()
        new_gs = self._gamma_scale()

        self.input_E.setText(  self._fmt(si_E   * new_ss))
        self.input_rho.setText(self._fmt(si_rho * new_gs))
        self.input_fy.setText( self._fmt(si_fy  * new_ss))
        self.input_fu.setText( self._fmt(si_fu  * new_ss))

        self._refresh_labels()

    def _on_type_changed(self, text: str):
        if text == "Steel":
            si = _STEEL_SI
        elif text == "Concrete":
            si = _CONCRETE_SI
        else:
            return                                

        ss = self._stress_scale()
        gs = self._gamma_scale()

        self.input_E.setText(  self._fmt(si["E"]     * ss))
        self.input_nu.setText( str(si["nu"]))
        self.input_rho.setText(self._fmt(si["gamma"] * gs))
        self.input_fy.setText( self._fmt(si["fy"]    * ss))
        self.input_fu.setText( self._fmt(si["fu"]    * ss))

    def _load_material(self, mat: Material):
        self.name_edit.setText(mat.name)
                                                                   
        self.type_combo.blockSignals(True)
        self.type_combo.setCurrentText(mat.mat_type.capitalize())
        self.type_combo.blockSignals(False)

        ss = self._stress_scale()
        gs = self._gamma_scale()

        self.input_E.setText(  self._fmt(mat.E       * ss))
        self.input_nu.setText( str(mat.nu))
        self.input_rho.setText(self._fmt(mat.density * gs))
        self.input_fy.setText( self._fmt(mat.fy      * ss))
        self.input_fu.setText( self._fmt(getattr(mat, "fu", 0.0) * ss))

        if hasattr(mat, "color"):
            self.selected_color = mat.color

    def _pick_color(self):
        r = int(self.selected_color[0] * 255)
        g = int(self.selected_color[1] * 255)
        b = int(self.selected_color[2] * 255)
        color = QColorDialog.getColor(QColor(r, g, b), self, "Select Material Color")
        if color.isValid():
            self.selected_color = (color.redF(), color.greenF(), color.blueF(), 1.0)
            self._update_color_button()

    def _update_color_button(self):
        r = int(self.selected_color[0] * 255)
        g = int(self.selected_color[1] * 255)
        b = int(self.selected_color[2] * 255)
        self.btn_color.setStyleSheet(
            f"background-color: rgb({r},{g},{b}); border: 1px solid #666; border-radius: 3px;"
        )

    def _save_data(self):
        try:
            ss = self._stress_scale()
            gs = self._gamma_scale()

            base_E   = float(self.input_E.text()   or 0) / ss
            base_rho = float(self.input_rho.text() or 0) / gs
            base_fy  = float(self.input_fy.text()  or 0) / ss
            base_fu  = float(self.input_fu.text()  or 0) / ss
            nu       = float(self.input_nu.text()  or 0)

            new_mat = Material(
                name    = self.name_edit.text().strip() or "Mat1",
                E       = base_E,
                nu      = nu,
                density = base_rho,
                mat_type= self.type_combo.currentText().lower(),
                fy      = base_fy,
                fu      = base_fu,
            )
            new_mat.color = self.selected_color

            self.material_data = new_mat
            self.accept()

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not create material:\n{e}")

    @staticmethod
    def _fmt(val: float) -> str:
        """4 significant figures, strip trailing zeros."""
        return f"{val:.4g}"

class MaterialManagerDialog(QDialog):
    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model
        self.setWindowTitle("Define Materials")
        self.resize(400, 300)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(12, 12, 12, 12)

        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget)

        btn_layout = QHBoxLayout()
        add_btn = QPushButton("Add New…")
        add_btn.clicked.connect(self.add_material)
        mod_btn = QPushButton("Modify / Show…")
        mod_btn.clicked.connect(self.modify_material)
        del_btn = QPushButton("Delete")
        del_btn.clicked.connect(self.delete_material)

        btn_layout.addWidget(add_btn)
        btn_layout.addWidget(mod_btn)
        btn_layout.addWidget(del_btn)
        layout.addLayout(btn_layout)

        layout.addWidget(_divider())
        close_btn = QPushButton("OK")
        close_btn.setFixedHeight(30)
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

        self.refresh_list()

    def refresh_list(self):
        self.list_widget.clear()
        for name in self.model.materials:
            self.list_widget.addItem(name)

    def add_material(self):
        dialog = MaterialEditor(parent=self)
        if dialog.exec() and dialog.material_data:
            self.model.add_material(dialog.material_data)
            self.refresh_list()

    def modify_material(self):
        items = self.list_widget.selectedItems()
        if not items:
            return
        mat_name = items[0].text()
        mat_obj  = self.model.materials[mat_name]

        dialog = MaterialEditor(material=mat_obj, parent=self)
        if dialog.exec() and dialog.material_data:
            new_mat = dialog.material_data
            if new_mat.name != mat_name:
                del self.model.materials[mat_name]
            self.model.add_material(new_mat)
            self.refresh_list()

    def delete_material(self):
        items = self.list_widget.selectedItems()
        if not items:
            return
        name = items[0].text()

        in_use, msg = check_material_in_use(self.model, name)
        if in_use:
            QMessageBox.warning(self, "Material In Use", msg)
            return

        if QMessageBox.question(
            self, "Delete Material", f"Delete material '{name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        ) != QMessageBox.StandardButton.Yes:
            return

        del self.model.materials[name]
        self.refresh_list()
