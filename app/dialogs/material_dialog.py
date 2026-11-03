import math
import csv
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QListWidget, QPushButton, QGroupBox, QFormLayout,
                             QLineEdit, QComboBox, QMessageBox, QColorDialog,
                             QFrame, QSizePolicy, QRadioButton, QButtonGroup,
                             QStackedWidget, QWidget, QTableWidget, QTableWidgetItem,
                             QHeaderView, QAbstractItemView, QGridLayout, QCheckBox,
                             QApplication, QFileDialog, QCheckBox, QApplication, QFileDialog, QScrollArea)                                  
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QPainterPath, QKeySequence                     
from PyQt6.QtCore import Qt, QPointF, QRectF
from core.properties import (Material, NonlinearMaterialData, ManderConfinementData, MaterialDamping,
                             derived_materials, hinge_fiber_users, refresh_derived_twins)
from core.units import unit_registry
from core.integrity_checks import check_material_in_use
from app.ui.theme import apply_dialog_style
from core.mander_model import generate_mander_curve, default_user_points, get_control_points, unconfined_user_table, generate_rebar_curve, generate_steel_curve
from app.dialogs.os_model_panel import OsModelPanel
from core.opensees_port.os_capabilities import UNSUPPORTED_HYSTERESIS, DEFAULT_HYSTERESIS, UNSUPPORTED_CURVE_MODE, is_opensees

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
_TENDON_SI   = dict(E=1.965e11, nu=0.30, gamma=78_500.0, fy=1.69e9, fu=1.86e9)
                                                                                              
_REBAR_SI    = dict(E=2.0e11, nu=0.30, gamma=76_973.0,
                     fy=4.137e8, fu=6.205e8, fye=4.551e8, fue=6.826e8, grade="Gr60")

def _divider():
    """Thin horizontal separator line."""
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFrameShadow(QFrame.Shadow.Sunken)
    return line

def _rebar_ids(model):
    """
    Bar ID list from the model's user-editable rebar catalog
    (app/dialogs/rebar_size_dialog.py), auto-seeding the same defaults
    reinforcement_dialog.py uses if the project hasn't touched the Rebar
    Size Manager yet. Keeps Mander's confinement/longitudinal bar
    pickers in sync with the same catalog section reinforcement uses,
    instead of the old hardcoded metric-only list.
    """
    if not getattr(model, "rebar_sizes", []):
        import copy
        from app.dialogs.rebar_size_dialog import DEFAULT_REBARS
        model.rebar_sizes = copy.deepcopy(DEFAULT_REBARS)
    return [b["id"] for b in model.rebar_sizes]

def _rebar_area_lookup(model):
    """{bar_id: area_m2} from the same catalog, for core/mander_model.py's
    confinement calculations — see bar_area_m2's area_lookup parameter."""
    return {b["id"]: b["area"] for b in getattr(model, "rebar_sizes", [])}

class CopyableTableWidget(QTableWidget):
    """QTableWidget with Excel-style Ctrl+C: copies the selected cell
    rectangle (rows x columns) as tab-separated text to the clipboard."""

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.StandardKey.Copy):
            self.copy_selection_to_clipboard()
        else:
            super().keyPressEvent(event)

    def copy_selection_to_clipboard(self):
        indexes = self.selectedIndexes()
        if not indexes:
            return

        rows = sorted(set(i.row() for i in indexes))
        cols = sorted(set(i.column() for i in indexes))
        selected_set = set((i.row(), i.column()) for i in indexes)

        lines = []
        header_item = self.horizontalHeaderItem
        lines.append("\t".join(
            (header_item(c).text() if header_item(c) else "") for c in cols
        ))

        for r in rows:
            line_vals = []
            for c in cols:
                if (r, c) in selected_set:
                    item = self.item(r, c)
                    line_vals.append(item.text() if item else "")
                else:
                    line_vals.append("")
            lines.append("\t".join(line_vals))

        QApplication.clipboard().setText("\n".join(lines))

class MaterialEditor(QDialog):
    """
    Material property editor with a dialog-local unit system.

    The local unit combo does NOT touch the project's unit_registry.
    It only controls how values are displayed / entered here.
    All data is stored internally and returned in SI base (N, m).
    """

    def __init__(self, model, material: Material | None = None, parent=None):
        super().__init__(parent)
        apply_dialog_style(self)
        self.setWindowTitle("Material Property Data")
        self.resize(430, 600)                                                                 
        self.model = model
        self.material_data: Material | None = None
        self.selected_color = (0.7, 0.7, 0.7, 1.0)

        self._f_scale  = FORCE_SCALES.get(unit_registry.force_unit_name,  1/1_000.0)
        self._l_scale  = LENGTH_SCALES.get(unit_registry.length_unit_name, 1.0)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent;")
        
        content_widget = QWidget()
        content_widget.setStyleSheet("background: transparent;")
        root = QVBoxLayout(content_widget)
        root.setSpacing(10)
        root.setContentsMargins(14, 14, 14, 14)

        id_group = QGroupBox("Identity")
        id_form  = QFormLayout(id_group)
        id_form.setVerticalSpacing(6)

        self.name_edit = QLineEdit("Mat1")
        id_form.addRow("Name:", self.name_edit)

        self.type_combo = QComboBox()
        self.type_combo.addItems(["Steel", "Concrete", "Rebar", "Tendon", "Other"])
        id_form.addRow("Type:", self.type_combo)

        self.grade_edit = QLineEdit()
        self.grade_edit.setPlaceholderText("e.g. Gr60")
        self.grade_row_label = QLabel("Grade:")
        id_form.addRow(self.grade_row_label, self.grade_edit)

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
        self.input_fye = QLineEdit()
        self.input_fue = QLineEdit()
        self.lbl_fy   = QLabel()
        self.lbl_fu   = QLabel()
        self.lbl_fye  = QLabel()
        self.lbl_fue  = QLabel()

        des_form.addRow(self.lbl_fy, self.input_fy)
        des_form.addRow(self.lbl_fu, self.input_fu)
        des_form.addRow(self.lbl_fye, self.input_fye)
        des_form.addRow(self.lbl_fue, self.input_fue)

        root.addWidget(des_group)

        self.adv_group = QGroupBox("Advanced Material Property Data")
        adv_layout = QHBoxLayout(self.adv_group)
        adv_layout.setSpacing(8)
        self.btn_nonlinear = QPushButton("Nonlinear Material Data...")
        self.btn_nonlinear.clicked.connect(self._open_nonlinear_dialog)
        self.btn_damping = QPushButton("Material Damping Properties...")
        self.btn_damping.clicked.connect(self._open_damping_dialog)
        adv_layout.addWidget(self.btn_nonlinear)
        adv_layout.addWidget(self.btn_damping)
        root.addWidget(self.adv_group)

        self._nonlinear_data: NonlinearMaterialData | None = None
        self._damping_data: MaterialDamping | None = None

        scroll.setWidget(content_widget)
        main_layout.addWidget(scroll)

        main_layout.addWidget(_divider())
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)
        btn_layout.setContentsMargins(14, 0, 14, 14)                                    
        ok_btn = QPushButton("OK")
        ok_btn.setFixedHeight(30)
        ok_btn.clicked.connect(self._save_data)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedHeight(30)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        main_layout.addLayout(btn_layout)

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
        if self.type_combo.currentText() == "Concrete":
            self.lbl_fy.setText(f"Specified Compressive Strength, f'c  [{su}]:")
            self.lbl_fye.setText(f"Expected Compressive Strength, f'ce  [{su}]:")
        else:
            self.lbl_fy.setText(f"Minimum Yield Fy  [{su}]:")
            self.lbl_fye.setText(f"Expected Yield Fye  [{su}]:")
        self.lbl_fu.setText(f"Minimum Tensile Fu  [{su}]:")
        self.lbl_fue.setText(f"Expected Tensile Fue  [{su}]:")

    def _on_unit_changed(self):
        """Re-express all fields in the newly selected units."""

        old_ss = self._stress_scale()
        old_gs = self._gamma_scale()

        try:
            si_E   = float(self.input_E.text()   or 0) / old_ss
            si_rho = float(self.input_rho.text() or 0) / old_gs
            si_fy  = float(self.input_fy.text()  or 0) / old_ss
            si_fu  = float(self.input_fu.text()  or 0) / old_ss
            si_fye = float(self.input_fye.text() or 0) / old_ss
            si_fue = float(self.input_fue.text() or 0) / old_ss
        except ValueError:
            si_E = si_rho = si_fy = si_fu = si_fye = si_fue = 0.0

        self._f_scale = FORCE_SCALES[self.combo_force.currentText()]
        self._l_scale = LENGTH_SCALES[self.combo_length.currentText()]

        new_ss = self._stress_scale()
        new_gs = self._gamma_scale()

        self.input_E.setText(  self._fmt(si_E   * new_ss))
        self.input_rho.setText(self._fmt(si_rho * new_gs))
        self.input_fy.setText( self._fmt(si_fy  * new_ss))
        self.input_fu.setText( self._fmt(si_fu  * new_ss))
        self.input_fye.setText(self._fmt(si_fye * new_ss))
        self.input_fue.setText(self._fmt(si_fue * new_ss))

        self._refresh_labels()

    def _on_type_changed(self, text: str):
        is_rebar = (text == "Rebar")
        self.grade_edit.setVisible(is_rebar)
        self.grade_row_label.setVisible(is_rebar)

        is_concrete = (text == "Concrete")
        self.input_fye.setEnabled(is_rebar or is_concrete)
        self.input_fue.setEnabled(is_rebar)
        self.input_fu.setVisible(not is_concrete)
        self.lbl_fu.setVisible(not is_concrete)
        self.input_fue.setVisible(not is_concrete)
        self.lbl_fue.setVisible(not is_concrete)
        
        is_nonlinear_capable = text in ("Concrete", "Rebar", "Steel")
        self.adv_group.setVisible(is_nonlinear_capable)
        if not is_nonlinear_capable:
            self._nonlinear_data = None
            self._damping_data = None
            
        self._refresh_labels()

        if text == "Steel":
            si = _STEEL_SI
        elif text == "Concrete":
            si = _CONCRETE_SI
        elif text == "Rebar":
            si = _REBAR_SI
        elif text == "Tendon":
            si = _TENDON_SI
        else:
            return                                

        ss = self._stress_scale()
        gs = self._gamma_scale()

        self.input_E.setText(  self._fmt(si["E"]     * ss))
        self.input_nu.setText( str(si["nu"]))
        self.input_rho.setText(self._fmt(si["gamma"] * gs))
        self.input_fy.setText( self._fmt(si["fy"]    * ss))
        self.input_fu.setText( self._fmt(si["fu"]    * ss))

        if is_rebar:
            self.grade_edit.setText(si.get("grade", ""))
            self.input_fye.setText(self._fmt(si["fye"] * ss))
            self.input_fue.setText(self._fmt(si["fue"] * ss))
        else:
            self.input_fye.setText("")
            self.input_fue.setText("")

    def _load_material(self, mat: Material):
        self.name_edit.setText(mat.name)
                                                                   
        self.type_combo.blockSignals(True)
        self.type_combo.setCurrentText(mat.mat_type.capitalize())
        self.type_combo.blockSignals(False)
        is_rebar = (mat.mat_type.capitalize() == "Rebar")
        self.grade_edit.setVisible(is_rebar)
        self.grade_row_label.setVisible(is_rebar)
        is_concrete_load = (mat.mat_type.capitalize() == "Concrete")
        self.input_fye.setEnabled(is_rebar or is_concrete_load)
        self.input_fue.setEnabled(is_rebar)
        self.input_fu.setVisible(not is_concrete_load)
        self.lbl_fu.setVisible(not is_concrete_load)
        self.input_fue.setVisible(not is_concrete_load)
        self.lbl_fue.setVisible(not is_concrete_load)
        self._refresh_labels()

        ss = self._stress_scale()
        gs = self._gamma_scale()

        self.input_E.setText(  self._fmt(mat.E       * ss))
        self.input_nu.setText( str(mat.nu))
        self.input_rho.setText(self._fmt(mat.density * gs))
        self.input_fy.setText( self._fmt(mat.fy      * ss))
        self.input_fu.setText( self._fmt(getattr(mat, "fu", 0.0) * ss))
        self.grade_edit.setText(getattr(mat, "grade", "") or "")
        self.input_fye.setText(self._fmt(getattr(mat, "fye", 0.0) * ss) if getattr(mat, "fye", 0.0) else "")
        self.input_fue.setText(self._fmt(getattr(mat, "fue", 0.0) * ss) if getattr(mat, "fue", 0.0) else "")

        if hasattr(mat, "color"):
            self.selected_color = mat.color

        self.adv_group.setVisible(mat.mat_type.capitalize() in ("Concrete", "Rebar", "Steel"))
        self._nonlinear_data = getattr(mat, "nonlinear", None)
        self._damping_data = getattr(mat, "damping", None)

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
            base_fye = float(self.input_fye.text() or 0) / ss
            base_fue = float(self.input_fue.text() or 0) / ss
            nu       = float(self.input_nu.text()  or 0)

            new_mat = Material(
                name    = self.name_edit.text().strip() or "Mat1",
                E       = base_E,
                nu      = nu,
                density = base_rho,
                mat_type= self.type_combo.currentText().lower(),
                fy      = base_fy,
                fu      = base_fu,
                fye     = base_fye,
                fue     = base_fue,
                grade   = self.grade_edit.text().strip(),
            )
            new_mat.color = self.selected_color
            
            if self.type_combo.currentText() in ("Concrete", "Rebar", "Steel"):
                new_mat.nonlinear = self._nonlinear_data
                new_mat.damping = self._damping_data

            self.material_data = new_mat
            self.accept()

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not create material:\n{e}")

    def _current_fc_and_E_si(self):
        """Reads the currently-typed fy (used as f'c for Concrete) and E
        fields and converts them to SI base, using the same convention
        as _save_data."""
        ss = self._stress_scale()
        try:
            fc_si = float(self.input_fy.text() or 0) / ss
        except ValueError:
            fc_si = 0.0
        try:
            e_si = float(self.input_E.text() or 0) / ss
        except ValueError:
            e_si = 0.0
        return fc_si, e_si

    def _open_nonlinear_dialog(self):
        fc_si, e_si = self._current_fc_and_E_si()
        ss = self._stress_scale()
        try:
            fu_si = float(self.input_fu.text() or 0) / ss
        except ValueError:
            fu_si = 0.0

        if fc_si <= 0:
            QMessageBox.warning(
                self, "Nonlinear Material Data",
                "Specified Compressive/Yield Strength is currently 0.\n\n"
                "Set it in the Design Strength section before defining "
                "nonlinear data, or the curve will plot flat."
            )
        dlg = NonlinearMaterialDialog(
            model=self.model,
            material_name=self.name_edit.text().strip() or "Mat1",
            material_type=self.type_combo.currentText(),
            fc_si=fc_si, e_si=e_si, fu_si=fu_si,                
            data=self._nonlinear_data,
            stress_unit=self._stress_unit(), stress_scale=self._stress_scale(),
            length_unit=self._length_unit(), length_scale=self._l_scale,
            parent=self,
        )
        if dlg.exec():
            self._nonlinear_data = dlg.get_data()

    def _open_damping_dialog(self):
        dlg = MaterialDampingDialog(self._damping_data, parent=self)
        if dlg.exec():
            self._damping_data = dlg.get_data()

    @staticmethod
    def _fmt(val: float) -> str:
        """Standard float format, strip trailing zeros."""
        if val == 0:
            return "0"
        return f"{val:.6f}".rstrip('0').rstrip('.')

class MaterialManagerDialog(QDialog):
    def __init__(self, model, parent=None):
        super().__init__(parent)
        apply_dialog_style(self)
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
        dialog = MaterialEditor(model=self.model, parent=self)
        if dialog.exec() and dialog.material_data:
            self.model.add_material(dialog.material_data)
            self.refresh_list()

    def modify_material(self):
        items = self.list_widget.selectedItems()
        if not items:
            return
        mat_name = items[0].text()
        mat_obj  = self.model.materials[mat_name]

        parent_name = getattr(mat_obj, "derived_from", "")
        if parent_name:
            QMessageBox.information(
                self, "Auto-Generated Material",
                f"'{mat_name}' is an automatic unconfined copy of '{parent_name}' and is\n"
                f"regenerated from it by the hinge dialog, so edits here would be overwritten.\n"
                f"Edit '{parent_name}' instead."
            )
            return

        dialog = MaterialEditor(model=self.model, material=mat_obj, parent=self)
        if dialog.exec() and dialog.material_data:
            new_mat = dialog.material_data
            if new_mat.name != mat_name:
                del self.model.materials[mat_name]
                                                                                 
                for tw in derived_materials(self.model, mat_name):
                    tw.derived_from = new_mat.name
            self.model.add_material(new_mat)
                                                                                
            refreshed = refresh_derived_twins(self.model, new_mat.name)
            self.refresh_list()
            if refreshed:
                QMessageBox.information(
                    self, "Unconfined Copies Updated",
                    "Updated from '%s': %s" % (new_mat.name, ", ".join(refreshed))
                )

    def delete_material(self):
        items = self.list_widget.selectedItems()
        if not items:
            return
        name = items[0].text()

        in_use, msg = check_material_in_use(self.model, name)
        if in_use:
            QMessageBox.warning(self, "Material In Use", msg)
            return

        twins = derived_materials(self.model, name)
        blockers = {}
        for mn in [name] + [tw.name for tw in twins]:
            users = hinge_fiber_users(self.model, mn)
            if users:
                blockers[mn] = users
        if blockers:
            lines = "\n".join(f"  {mn}: used by hinge(s) {', '.join(u)}" for mn, u in blockers.items())
            QMessageBox.warning(
                self, "Material In Use",
                "Can't delete this material because hinge fibers still reference it:\n\n" + lines
            )
            return

        extra = f"\n\nIts unconfined copies will be deleted too: {', '.join(tw.name for tw in twins)}." if twins else ""
        if QMessageBox.question(
            self, "Delete Material", f"Delete material '{name}'?" + extra,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        ) != QMessageBox.StandardButton.Yes:
            return

        for tw in twins:
            del self.model.materials[tw.name]
        del self.model.materials[name]
        self.refresh_list()

def _fmt4(val: float) -> str:
    """Standard float format, strip trailing zeros. Shared formatter."""
    if val == 0:
        return "0"
    return f"{val:.6f}".rstrip('0').rstrip('.')

class DampingConversionDialog(QDialog):
    """
    'Damping Conversion' popup (Image 3): lets the user pick a Period or
    Frequency at which to convert a damping ratio into equivalent
    Rayleigh mass/stiffness proportional coefficients (or vice versa).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        apply_dialog_style(self)
        self.setWindowTitle("Damping Conversion")

        root = QVBoxLayout(self)
        group = QGroupBox("Convert Damping at this Frequency")
        form = QVBoxLayout(group)

        row = QHBoxLayout()
        self.period_radio = QRadioButton("Period")
        self.freq_radio = QRadioButton("Frequency")
        self.period_radio.setChecked(True)
        self.btn_group = QButtonGroup(self)
        self.btn_group.addButton(self.period_radio)
        self.btn_group.addButton(self.freq_radio)
        row.addWidget(self.period_radio)
        row.addWidget(self.freq_radio)
        form.addLayout(row)

        self.value_edit = QLineEdit("1.")
        form.addWidget(self.value_edit)
        root.addWidget(group)

        btn_row = QHBoxLayout()
        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        root.addLayout(btn_row)

    def get_omega(self) -> float:
        """Circular frequency (rad/s) implied by the chosen Period or Frequency."""
        try:
            val = float(self.value_edit.text() or 0)
        except ValueError:
            val = 0.0
        if val <= 0:
            return 0.0
        if self.period_radio.isChecked():
            return 2.0 * math.pi / val
        return 2.0 * math.pi * val

class MaterialDampingDialog(QDialog):
    """
    'Additional Material Damping' dialog (Image 2): Modal, Viscous
    Proportional, and Hysteretic Proportional damping, each with a
    'Make Other Damping Similar' helper.

    Conversion convention (agreed simplification, no solver involved):
    at circular frequency omega, a damping ratio zeta is split evenly
    between the mass- and stiffness-proportional Rayleigh terms:
        a = zeta * omega        b = zeta / omega
    which satisfies zeta = a/(2*omega) + b*omega/2 at that frequency.
    """

    def __init__(self, damping_data: "MaterialDamping | None" = None, parent=None):
        super().__init__(parent)
        apply_dialog_style(self)
        self.setWindowTitle("Additional Material Damping")
        self.result_data: MaterialDamping | None = None

        root = QVBoxLayout(self)
        root.setSpacing(10)

        modal_group = QGroupBox("Modal Damping")
        modal_form = QHBoxLayout(modal_group)
        modal_form.addWidget(QLabel("Damping Ratio"))
        self.modal_edit = QLineEdit("0.")
        modal_form.addWidget(self.modal_edit)
        modal_similar_btn = QPushButton("Make Other Damping Similar...")
        modal_similar_btn.clicked.connect(lambda: self._make_similar("modal"))
        modal_form.addWidget(modal_similar_btn)
        root.addWidget(modal_group)
        root.addWidget(QLabel(
            "Applies to Response-Spectrum and Modal Time-History load cases.\n"
            "Also applies to Direct Integration Time History load cases where\n"
            "Modal Damping has been enabled."))

        visc_group = QGroupBox("Viscous Proportional Damping")
        visc_form = QFormLayout(visc_group)
        self.visc_mass_edit = QLineEdit("0.")
        self.visc_stiff_edit = QLineEdit("0.")
        visc_form.addRow("Mass Coefficient", self.visc_mass_edit)
        visc_form.addRow("Stiffness Coefficient", self.visc_stiff_edit)
        visc_similar_btn = QPushButton("Make Other Damping Similar...")
        visc_similar_btn.clicked.connect(lambda: self._make_similar("visc"))
        visc_form.addRow(visc_similar_btn)
        root.addWidget(visc_group)
        root.addWidget(QLabel("Applies to Direct-Integration Time-History load cases"))

        hyst_group = QGroupBox("Hysteretic Proportional Damping")
        hyst_form = QFormLayout(hyst_group)
        self.hyst_mass_edit = QLineEdit("0.")
        self.hyst_stiff_edit = QLineEdit("0.")
        hyst_form.addRow("Mass Coefficient", self.hyst_mass_edit)
        hyst_form.addRow("Stiffness Coefficient", self.hyst_stiff_edit)
        hyst_similar_btn = QPushButton("Make Other Damping Similar...")
        hyst_similar_btn.clicked.connect(lambda: self._make_similar("hyst"))
        hyst_form.addRow(hyst_similar_btn)
        root.addWidget(hyst_group)
        root.addWidget(QLabel("Applies to Steady-State and Power-Spectral-Density load cases"))

        root.addWidget(_divider())
        btn_row = QHBoxLayout()
        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(self._save)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        root.addLayout(btn_row)

        if damping_data:
            self.modal_edit.setText(_fmt4(damping_data.modal_ratio))
            self.visc_mass_edit.setText(_fmt4(damping_data.visc_mass_coeff))
            self.visc_stiff_edit.setText(_fmt4(damping_data.visc_stiff_coeff))
            self.hyst_mass_edit.setText(_fmt4(damping_data.hyst_mass_coeff))
            self.hyst_stiff_edit.setText(_fmt4(damping_data.hyst_stiff_coeff))

    def _make_similar(self, source: str):
        conv = DampingConversionDialog(self)
        if not conv.exec():
            return
        omega = conv.get_omega()
        if omega <= 0:
            QMessageBox.warning(self, "Damping Conversion", "Period/Frequency must be positive.")
            return

        def f(text):
            try:
                return float(text or 0)
            except ValueError:
                return 0.0

        if source == "modal":
            zeta = f(self.modal_edit.text())
            a, b = zeta * omega, (zeta / omega if omega > 0 else 0.0)
            self.visc_mass_edit.setText(_fmt4(a))
            self.visc_stiff_edit.setText(_fmt4(b))
            self.hyst_mass_edit.setText(_fmt4(a))
            self.hyst_stiff_edit.setText(_fmt4(b))
        elif source == "visc":
            a, b = f(self.visc_mass_edit.text()), f(self.visc_stiff_edit.text())
            zeta = a / (2 * omega) + b * omega / 2
            self.modal_edit.setText(_fmt4(zeta))
            self.hyst_mass_edit.setText(_fmt4(a))
            self.hyst_stiff_edit.setText(_fmt4(b))
        else:        
            a, b = f(self.hyst_mass_edit.text()), f(self.hyst_stiff_edit.text())
            zeta = a / (2 * omega) + b * omega / 2
            self.modal_edit.setText(_fmt4(zeta))
            self.visc_mass_edit.setText(_fmt4(a))
            self.visc_stiff_edit.setText(_fmt4(b))

    def _save(self):
        try:
            self.result_data = MaterialDamping(
                modal_ratio=float(self.modal_edit.text() or 0),
                visc_mass_coeff=float(self.visc_mass_edit.text() or 0),
                visc_stiff_coeff=float(self.visc_stiff_edit.text() or 0),
                hyst_mass_coeff=float(self.hyst_mass_edit.text() or 0),
                hyst_stiff_coeff=float(self.hyst_stiff_edit.text() or 0),
            )
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not save damping data:\n{e}")

    def get_data(self) -> "MaterialDamping | None":
        return self.result_data

def _nice_ticks(lo, hi, target=6):
    """Round-number tick positions covering [lo, hi]; returns (ticks, step)."""
    span = hi - lo
    if not (span > 0) or not math.isfinite(span):
        return [lo], 1.0
    raw = span / max(target, 1)
    mag = 10 ** math.floor(math.log10(raw))
    step = mag * 10
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * mag + 1e-15:
            step = m * mag
            break
    k0, k1 = math.ceil(lo / step - 1e-9), math.floor(hi / step + 1e-9)
    return [k * step for k in range(k0, k1 + 1)], step

def _fmt_tick(v, step):
    if abs(v) < step * 1e-6:
        return "0"
    if step >= 1:
        return f"{v:.0f}"
    dec = max(0, -math.floor(math.log10(step)))
    if abs(step * 10 ** dec - round(step * 10 ** dec)) > 1e-6:                      
        dec += 1
    return f"{v:.{dec}f}"

class StressStrainPlotWidget(QWidget):
    """
    Custom-painted strain/stress plot with labelled axes, a grid on round tick values, per-layer
    colour / width / dash, a legend, and pan (drag) / zoom (wheel) / reset (double-click).

    set_curve(...)  -- original API (one main curve + optional extra curves + marker).
    set_layers(...) -- list of {"pts": [(x, y), ...], "color": "#rrggbb", "width": 2.0, "dash": False},
                       drawn in order (first = bottom).  legend entries: (label, color) or (label, color, dashed).
    """

    MARGIN_L = 70
    MARGIN_R = 16
    MARGIN_T = 26
    MARGIN_B = 52

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(440, 340)
        self.setMouseTracking(True)
        self._layers = []
        self._marker = None
        self._x_label = "Strain (m/m)"
        self._y_label = "Stress"
        self._hover = None
        self._legend = []                                           
        self._view_bounds = None
        self._pan_start_pos = None

    def set_curve(self, points, marker=None, x_label=None, y_label=None, extra=None, legend=None, color=None):
        layers = [dict(pts=list(pts), color=col, width=2.0, dash=False) for pts, col in (extra or [])]
        layers.append(dict(pts=list(points) if points else [(0.0, 0.0)],
                           color=color or "#d32f2f", width=2.0, dash=False))
        self._apply(layers, marker, x_label, y_label, legend)

    def set_layers(self, layers, x_label=None, y_label=None, legend=None):
        self._apply(list(layers), None, x_label, y_label, legend)

    def _apply(self, layers, marker, x_label, y_label, legend):
        self._layers = layers
        self._marker = marker
        self._legend = list(legend or [])
        if x_label:
            self._x_label = x_label
        if y_label:
            self._y_label = y_label
        self._view_bounds = self._calculate_initial_bounds()
        self.update()

    def _calculate_initial_bounds(self):
        """Tight data limits with a 6% pad."""
        _all = [p for layer in self._layers for p in layer["pts"]]
        if not _all:
            return -1.0, 1.0, -1.0, 1.0
        xs = [p[0] for p in _all]
        ys = [p[1] for p in _all]
        xmin, xmax = min(xs), max(xs)
        ymin, ymax = min(ys), max(ys)
        if xmax - xmin < 1e-12:
            xmin, xmax = xmin - 1.0, xmax + 1.0
        if ymax - ymin < 1e-12:
            ymin, ymax = ymin - 1.0, ymax + 1.0
        pad_x = (xmax - xmin) * 0.06
        pad_y = (ymax - ymin) * 0.06
        return xmin - pad_x, xmax + pad_x, ymin - pad_y, ymax + pad_y

    def _bounds(self):
        if self._view_bounds is None:
            self._view_bounds = self._calculate_initial_bounds()
        return self._view_bounds

    def _to_pixel(self, x, y, xmin, xmax, ymin, ymax, w, h):
        px = self.MARGIN_L + (x - xmin) / (xmax - xmin) * (w - self.MARGIN_L - self.MARGIN_R)
        py = self.MARGIN_T + (1 - (y - ymin) / (ymax - ymin)) * (h - self.MARGIN_T - self.MARGIN_B)
        return px, py

    def _to_data(self, px, py, xmin, xmax, ymin, ymax, w, h):
        x = xmin + (px - self.MARGIN_L) / max(w - self.MARGIN_L - self.MARGIN_R, 1) * (xmax - xmin)
        y = ymin + (1 - (py - self.MARGIN_T) / max(h - self.MARGIN_T - self.MARGIN_B, 1)) * (ymax - ymin)
        return x, y

    def wheelEvent(self, event):
        xmin, xmax, ymin, ymax = self._bounds()
        zoom_factor = 0.9 if event.angleDelta().y() > 0 else 1.1
        cx, cy = (xmin + xmax) / 2.0, (ymin + ymax) / 2.0
        w, h = (xmax - xmin) * zoom_factor, (ymax - ymin) * zoom_factor
        self._view_bounds = (cx - w / 2.0, cx + w / 2.0, cy - h / 2.0, cy + h / 2.0)
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._pan_start_pos = event.position()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._pan_start_pos = None

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._view_bounds = self._calculate_initial_bounds()
            self.update()

    def mouseMoveEvent(self, event):
        xmin, xmax, ymin, ymax = self._bounds()
        w, h = self.width(), self.height()
        pos = event.position()
        if self._pan_start_pos is not None:
            dx_pixels = pos.x() - self._pan_start_pos.x()
            dy_pixels = pos.y() - self._pan_start_pos.y()
            dx_data = dx_pixels / max(w - self.MARGIN_L - self.MARGIN_R, 1) * (xmax - xmin)
            dy_data = dy_pixels / max(h - self.MARGIN_T - self.MARGIN_B, 1) * (ymax - ymin)
            self._view_bounds = (xmin - dx_data, xmax - dx_data, ymin + dy_data, ymax + dy_data)
            self._pan_start_pos = pos
            self._hover = None
        else:
            self._hover = self._to_data(pos.x(), pos.y(), xmin, xmax, ymin, ymax, w, h)
        self.update()

    def leaveEvent(self, event):
        self._hover = None
        self.update()

    def paintEvent(self, event):
        w, h = self.width(), self.height()
        xmin, xmax, ymin, ymax = self._bounds()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("#ffffff"))
        font = QFont(p.font())
        font.setPointSizeF(8.5)
        p.setFont(font)

        L, T, R, B = self.MARGIN_L, self.MARGIN_T, w - self.MARGIN_R, h - self.MARGIN_B
        if R - L < 20 or B - T < 20:
            return
        plot_rect = QRectF(L, T, R - L, B - T)
        tx = lambda x, y: self._to_pixel(x, y, xmin, xmax, ymin, ymax, w, h)

        xt, xs = _nice_ticks(xmin, xmax, max(3, int((R - L) // 80)))
        yt, ys = _nice_ticks(ymin, ymax, max(3, int((B - T) // 50)))
        for v in xt:
            px, _ = tx(v, 0)
            p.setPen(QPen(QColor("#e4e4e4"), 1))
            p.drawLine(int(px), T, int(px), B)
            p.setPen(QColor("#444444"))
            p.drawText(QRectF(px - 40, B + 4, 80, 16),
                       Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, _fmt_tick(v, xs))
        for v in yt:
            _, py = tx(0, v)
            p.setPen(QPen(QColor("#e4e4e4"), 1))
            p.drawLine(L, int(py), R, int(py))
            p.setPen(QColor("#444444"))
            p.drawText(QRectF(0, py - 8, L - 6, 16),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, _fmt_tick(v, ys))

        p.save()
        p.setClipRect(plot_rect)
                                 
        ox, oy = tx(0, 0)
        p.setPen(QPen(QColor("#666666"), 1.4))
        if xmin <= 0 <= xmax:
            p.drawLine(int(ox), T, int(ox), B)
        if ymin <= 0 <= ymax:
            p.drawLine(L, int(oy), R, int(oy))

        for layer in self._layers:
            pts = layer["pts"]
            if len(pts) < 2:
                continue
            path = QPainterPath()
            path.moveTo(*tx(*pts[0]))
            for x, y in pts[1:]:
                path.lineTo(*tx(x, y))
            pen = QPen(QColor(layer["color"]), layer.get("width", 2.0))
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            if layer.get("dash"):
                pen.setStyle(Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)

        if self._marker is not None:
            mx, my = tx(self._marker[0], self._marker[1])
            p.setPen(QPen(QColor("#b71c1c"), 1))
            p.setBrush(QColor("#d32f2f"))
            p.drawEllipse(QPointF(mx, my), 4, 4)
        p.restore()

        p.setPen(QPen(QColor("#9a9a9a"), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(plot_rect)

        if self._legend:
            fm = p.fontMetrics()
            lw = max(fm.horizontalAdvance(e[0]) for e in self._legend)
            box = QRectF(L + 8, T + 8, 44 + lw + 8, 18 * len(self._legend) + 6)
            p.setPen(QPen(QColor("#cccccc"), 1))
            p.setBrush(QColor(255, 255, 255, 225))
            p.drawRect(box)
            for i, entry in enumerate(self._legend):
                label, col = entry[0], entry[1]
                dashed = len(entry) > 2 and entry[2]
                ly = box.top() + 12 + 18 * i
                pen = QPen(QColor(col), 2.5)
                if dashed:
                    pen.setStyle(Qt.PenStyle.DashLine)
                p.setPen(pen)
                p.drawLine(int(box.left() + 8), int(ly), int(box.left() + 32), int(ly))
                p.setPen(QColor("#333333"))
                p.drawText(QRectF(box.left() + 38, ly - 8, lw + 12, 16),
                           Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label)

        p.setPen(QColor("#222222"))
        p.drawText(QRectF(L, h - 22, R - L, 18), Qt.AlignmentFlag.AlignHCenter, self._x_label)
        p.save()
        p.translate(14, (T + B) / 2.0)
        p.rotate(-90)
        p.drawText(QRectF(-120, -10, 240, 20), Qt.AlignmentFlag.AlignHCenter, self._y_label)
        p.restore()

        if self._hover is not None:
            hx, hy = self._hover
            if xmin <= hx <= xmax and ymin <= hy <= ymax:
                p.setPen(QColor("#222222"))
                p.drawText(QRectF(L, 4, R - L, 18),
                           Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                           f"Strain: {hx:.4g}    Stress: {hy:.4g}")

class ManderDataDialog(QDialog):
    """
    'Mander Concrete Stress-Strain Data' dialog (Images 8-11): confinement
    type + geometry feeding core/mander_model.py. Mutates the shared
    ManderConfinementData instance in place; 'Update Plot' pushes a live
    preview via on_update(), Cancel restores the snapshot taken at open.
    """

    def __init__(self, model, mander_data: ManderConfinementData, fc_si: float,
                 stress_unit: str, stress_scale: float,
                 length_unit: str, length_scale: float,
                 on_update=None, parent=None):
        super().__init__(parent)
        apply_dialog_style(self)
        self.setWindowTitle("Mander Concrete Stress-Strain Data")
        self.model = model
        self.data = mander_data
        self._snapshot = mander_data.to_dict()
        self.fc_si = fc_si
        self.ss = stress_scale
        self.ls = length_scale
        self.length_unit = length_unit
        self.on_update = on_update
                                                                     
        self._bar_items = _rebar_ids(model)

        root = QVBoxLayout(self)
        top_row = QHBoxLayout()

        self.type_group = QGroupBox("Mander Type")
        type_layout = QVBoxLayout(self.type_group)
        self.radio_unconf = QRadioButton("Unconfined")
        self.radio_rect = QRadioButton("Confined;  Rectangular Core")
        self.radio_circ_hoop = QRadioButton("Confined;  Circular Core;  Hoop Confinement Steel")
        self.radio_circ_spiral = QRadioButton("Confined;  Circular Core;  Spiral Confinement Steel")
        for rb in (self.radio_unconf, self.radio_rect, self.radio_circ_hoop, self.radio_circ_spiral):
            type_layout.addWidget(rb)
        self.type_group_btns = QButtonGroup(self)
        for rb in (self.radio_unconf, self.radio_rect, self.radio_circ_hoop, self.radio_circ_spiral):
            self.type_group_btns.addButton(rb)
        top_row.addWidget(self.type_group)

        source_group = QGroupBox("Mander Data Source")
        source_layout = QFormLayout(source_group)
        self.radio_frame = QRadioButton("Frame Section Property")
        self.radio_user = QRadioButton("User Defined")
        self.radio_user.setChecked(True)
        self.source_group_btns = QButtonGroup(self)
        self.source_group_btns.addButton(self.radio_frame)
        self.source_group_btns.addButton(self.radio_user)
        
        self.combo_frame_sec = QComboBox()
                                                    
        concrete_sections = [name for name, sec in self.model.sections.items() if getattr(sec.material, "mat_type", "").lower() == "concrete"]
        self.combo_frame_sec.addItems(concrete_sections)
        self.combo_frame_sec.setEnabled(False)                                        
        
        source_layout.addRow(self.radio_frame, self.combo_frame_sec)
        source_layout.addRow(self.radio_user, QLabel(""))
        top_row.addWidget(source_group)

        self.bar_group = QGroupBox("Confinement Bar Data")
        bar_form = QFormLayout(self.bar_group)
        self.radio_bar_size = QRadioButton("Confinement Bar Size")
        self.radio_bar_area = QRadioButton("Confinement Bar Area")
        self.radio_bar_size.setChecked(True)
        self.bar_size_group = QButtonGroup(self)
        self.bar_size_group.addButton(self.radio_bar_size)
        self.bar_size_group.addButton(self.radio_bar_area)
        self.combo_bar_size = QComboBox()
        self.combo_bar_size.addItems(self._bar_items)
        self.edit_bar_area = QLineEdit("0.")
        bar_form.addRow(self.radio_bar_size, self.combo_bar_size)
        bar_form.addRow(self.radio_bar_area, self.edit_bar_area)
        top_row.addWidget(self.bar_group)
        root.addLayout(top_row)

        self.geo_stack = QStackedWidget()

        rect_page = QWidget()
        rect_layout = QVBoxLayout(rect_page)                                              
        
        rect_long_group = QGroupBox("Rectangular Core Longitudinal Bar Data")
        rect_long_form = QFormLayout(rect_long_group)
        self.edit_num_long_x = QLineEdit("0")
        self.edit_num_long_y = QLineEdit("0")
        self.combo_long_bar_rect = QComboBox()
        self.combo_long_bar_rect.addItems(self._bar_items)
        rect_long_form.addRow("Number of Longit Bars Along X-Direction Face:", self.edit_num_long_x)
        rect_long_form.addRow("Number of Longit Bars Along Y-Direction Face:", self.edit_num_long_y)
        rect_long_form.addRow("Longitudinal Bar Size:", self.combo_long_bar_rect)
        rect_layout.addWidget(rect_long_group)

        x_group = QGroupBox("Rectangular Core X-Direction Confinement Bar Data")
        x_form = QFormLayout(x_group)
        self.edit_num_x_legs = QLineEdit("2")
        self.edit_x_spacing = QLineEdit("0.")
        x_form.addRow("Number of X-Direction Tie Legs", self.edit_num_x_legs)
        x_form.addRow(f"CL to CL Distance Between X-Direction Perimeter Tie Legs [{length_unit}]", self.edit_x_spacing)
        
        y_group = QGroupBox("Rectangular Core Y-Direction Confinement Bar Data")
        y_form = QFormLayout(y_group)
        self.edit_num_y_legs = QLineEdit("2")
        self.edit_y_spacing = QLineEdit("0.")
        y_form.addRow("Number of Y-Direction Tie Legs", self.edit_num_y_legs)
        y_form.addRow(f"CL to CL Distance Between Y-Direction Perimeter Hoop Legs [{length_unit}]", self.edit_y_spacing)
        
        ties_layout = QHBoxLayout()
        ties_layout.addWidget(x_group)
        ties_layout.addWidget(y_group)
        rect_layout.addLayout(ties_layout)
        
        self.geo_stack.addWidget(rect_page)

        circ_page = QWidget()
        circ_layout = QVBoxLayout(circ_page)
        circ_geo_group = QGroupBox("Circular Core Confinement Bar Data")
        circ_geo_form = QFormLayout(circ_geo_group)
        self.edit_core_diameter = QLineEdit("0.")
        self.lbl_core_diameter = QLabel(f"Diameter of Hoops (CL to CL) [{length_unit}]")
        circ_geo_form.addRow(self.lbl_core_diameter, self.edit_core_diameter)
        circ_layout.addWidget(circ_geo_group)

        long_group = QGroupBox("Circular Core Longitudinal Bar Data")
        long_form = QFormLayout(long_group)
        self.radio_long_count = QRadioButton("Number and Size of Bars")
        self.radio_long_area = QRadioButton("Total Area of Longitudinal Bars")
        self.radio_long_count.setChecked(True)
        self.long_group_btns = QButtonGroup(self)
        self.long_group_btns.addButton(self.radio_long_count)
        self.long_group_btns.addButton(self.radio_long_area)
        count_row = QHBoxLayout()
        self.edit_num_long_bars = QLineEdit("0")
        self.combo_long_bar_size = QComboBox()
        self.combo_long_bar_size.addItems(self._bar_items)
        count_row.addWidget(self.edit_num_long_bars)
        count_row.addWidget(self.combo_long_bar_size)
        long_form.addRow(self.radio_long_count, count_row)
        self.edit_total_long_area = QLineEdit("0.")
        long_form.addRow(self.radio_long_area, self.edit_total_long_area)
        circ_layout.addWidget(long_group)
        self.geo_stack.addWidget(circ_page)

        root.addWidget(self.geo_stack)

        self.gen_group = QGroupBox("General Confinement Bar Data")
        gen_form = QFormLayout(self.gen_group)
        self.edit_fyh = QLineEdit("0.")
        gen_form.addRow(f"Confinement Bar Yield Stress [{stress_unit}]", self.edit_fyh)
        self.lbl_tie_spacing = QLabel(f"Tie Longitudinal Spacing (CL to CL) [{length_unit}]")
        self.edit_tie_spacing = QLineEdit("0.")
        gen_form.addRow(self.lbl_tie_spacing, self.edit_tie_spacing)
        root.addWidget(self.gen_group)

        update_btn = QPushButton("Update Plot")
        update_btn.clicked.connect(self._apply_and_update)
        root.addWidget(update_btn)

        root.addWidget(_divider())
        btn_row = QHBoxLayout()
        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(self._on_ok)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self._on_cancel)
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        root.addLayout(btn_row)

        self.radio_unconf.toggled.connect(self._on_type_toggled)
        self.radio_rect.toggled.connect(self._on_type_toggled)
        self.radio_circ_hoop.toggled.connect(self._on_type_toggled)
        self.radio_circ_spiral.toggled.connect(self._on_type_toggled)
        self.radio_bar_area.toggled.connect(lambda c: self.combo_bar_size.setEnabled(not c))
        self.radio_bar_size.toggled.connect(lambda c: self.edit_bar_area.setEnabled(not c))
        self.radio_long_area.toggled.connect(self._on_long_mode_toggled)
        self.radio_long_count.toggled.connect(self._on_long_mode_toggled)

        self.radio_frame.toggled.connect(self._on_source_toggled)
        self.radio_user.toggled.connect(self._on_source_toggled)
        self.combo_frame_sec.currentTextChanged.connect(self._on_frame_sec_changed)

        self._load_from_data()

    def _current_type(self) -> str:
        if self.radio_rect.isChecked():
            return "Confined_Rect"
        if self.radio_circ_hoop.isChecked():
            return "Confined_Circ_Hoop"
        if self.radio_circ_spiral.isChecked():
            return "Confined_Circ_Spiral"
        return "Unconfined"

    def _on_type_toggled(self):
        t = self._current_type()
        is_confined = t != "Unconfined"
        for w in (self.combo_bar_size, self.edit_bar_area, self.radio_bar_size, self.radio_bar_area):
            w.setEnabled(is_confined)
        if t == "Confined_Rect":
            self.geo_stack.setCurrentIndex(0)
            self.geo_stack.setEnabled(True)
            self.lbl_tie_spacing.setText(f"Tie Longitudinal Spacing (CL to CL) [{self.length_unit}]")
        elif t in ("Confined_Circ_Hoop", "Confined_Circ_Spiral"):
            self.geo_stack.setCurrentIndex(1)
            self.geo_stack.setEnabled(True)
            word = "Hoops" if t == "Confined_Circ_Hoop" else "Spirals"
            self.lbl_core_diameter.setText(f"Diameter of {word} (CL to CL) [{self.length_unit}]")
            self.lbl_tie_spacing.setText(f"{word[:-1]} Longitudinal Spacing (CL to CL) [{self.length_unit}]")
        else:
            self.geo_stack.setEnabled(False)

    def _on_long_mode_toggled(self):
        is_area = self.radio_long_area.isChecked()
        self.edit_num_long_bars.setEnabled(not is_area)
        self.combo_long_bar_size.setEnabled(not is_area)
        self.edit_total_long_area.setEnabled(is_area)

    def _load_from_data(self):
        d = self.data
        
        if getattr(d, "source_mode", "user") == "frame":
            self.radio_frame.setChecked(True)
            if getattr(d, "frame_section_name", ""):
                self.combo_frame_sec.setCurrentText(d.frame_section_name)
        else:
            self.radio_user.setChecked(True)

        {
            "Unconfined": self.radio_unconf,
            "Confined_Rect": self.radio_rect,
            "Confined_Circ_Hoop": self.radio_circ_hoop,
            "Confined_Circ_Spiral": self.radio_circ_spiral,
        }.get(d.mander_type, self.radio_unconf).setChecked(True)

        if d.bar_size_mode == "area":
            self.radio_bar_area.setChecked(True)
        else:
            self.radio_bar_size.setChecked(True)
        if d.bar_size in self._bar_items:
            self.combo_bar_size.setCurrentText(d.bar_size)
        self.edit_bar_area.setText(_fmt4(d.bar_area * (self.ls ** 2)))

        self.edit_num_x_legs.setText(str(d.num_x_legs))
        self.edit_x_spacing.setText(_fmt4(d.x_leg_spacing * self.ls))
        self.edit_num_y_legs.setText(str(d.num_y_legs))
        self.edit_y_spacing.setText(_fmt4(d.y_leg_spacing * self.ls))

        self.edit_num_long_x.setText(str(getattr(d, "num_long_x", 0)))
        self.edit_num_long_y.setText(str(getattr(d, "num_long_y", 0)))
        if getattr(d, "long_bar_size_rect", "") in self._bar_items:
            self.combo_long_bar_rect.setCurrentText(d.long_bar_size_rect)

        self.edit_core_diameter.setText(_fmt4(d.core_diameter * self.ls))
        if d.long_bar_mode == "area":
            self.radio_long_area.setChecked(True)
        else:
            self.radio_long_count.setChecked(True)
        self.edit_num_long_bars.setText(str(d.num_long_bars))
        if d.long_bar_size in self._bar_items:
            self.combo_long_bar_size.setCurrentText(d.long_bar_size)
        self.edit_total_long_area.setText(_fmt4(d.total_long_area * (self.ls ** 2)))

        self.edit_fyh.setText(_fmt4(d.confinement_fyh * self.ss))
        self.edit_tie_spacing.setText(_fmt4(d.tie_spacing * self.ls))

        self._on_type_toggled()
        self._on_long_mode_toggled()

    def _pull_into_data(self):
        def f(edit, default=0.0):
            try:
                return float(edit.text() or default)
            except ValueError:
                return default

        d = self.data
        
        d.source_mode = "frame" if self.radio_frame.isChecked() else "user"
        d.frame_section_name = self.combo_frame_sec.currentText()

        d.mander_type = self._current_type()
        d.bar_size_mode = "area" if self.radio_bar_area.isChecked() else "size"
        d.bar_size = self.combo_bar_size.currentText()
        d.bar_area = f(self.edit_bar_area) / (self.ls ** 2)

        d.num_long_x = int(f(self.edit_num_long_x, 0))
        d.num_long_y = int(f(self.edit_num_long_y, 0))
        d.long_bar_size_rect = self.combo_long_bar_rect.currentText()

        d.num_x_legs = int(f(self.edit_num_x_legs, 0))
        d.x_leg_spacing = f(self.edit_x_spacing) / self.ls
        d.num_y_legs = int(f(self.edit_num_y_legs, 0))
        d.y_leg_spacing = f(self.edit_y_spacing) / self.ls

        d.core_diameter = f(self.edit_core_diameter) / self.ls
        d.long_bar_mode = "area" if self.radio_long_area.isChecked() else "count"
        d.num_long_bars = int(f(self.edit_num_long_bars, 0))
        d.long_bar_size = self.combo_long_bar_size.currentText()
        d.total_long_area = f(self.edit_total_long_area) / (self.ls ** 2)

        d.confinement_fyh = f(self.edit_fyh) / self.ss
        d.tie_spacing = f(self.edit_tie_spacing) / self.ls

    def _apply_and_update(self):
        self._pull_into_data()
        if self.on_update:
            self.on_update()

    def _on_ok(self):
        self._pull_into_data()
        self.accept()

    def _on_cancel(self):
        restored = ManderConfinementData.from_dict(self._snapshot)
        for f in self.data.__dataclass_fields__:
            setattr(self.data, f, getattr(restored, f))
        if self.on_update:
            self.on_update()
        self.reject()

    def _get_rebar_diameter(self, bar_id: str) -> float:
        """Helper to fetch the true bar diameter in SI base units."""
        for b in getattr(self.model, "rebar_sizes", []):
            if b["id"] == bar_id:
                return b["diameter"]
        return 0.0

    def _on_source_toggled(self):
        is_frame = self.radio_frame.isChecked()
        self.combo_frame_sec.setEnabled(is_frame)
        
        self.type_group.setEnabled(not is_frame)
        self.bar_group.setEnabled(not is_frame)
        self.geo_stack.setEnabled(not is_frame)
        self.gen_group.setEnabled(not is_frame)
        
        if not is_frame:
            self.data.tie_layout = "rect"
            self.data.rho_s_scale = 1.0
        if is_frame:
            self._on_frame_sec_changed()

    def _on_frame_sec_changed(self):
        if not self.radio_frame.isChecked():
            return
            
        sec_name = self.combo_frame_sec.currentText()
        if not sec_name or sec_name not in self.model.sections:
            return
            
        sec = self.model.sections[sec_name]
        r = getattr(sec, "reinforcement", None)
        
        if not r or r.design_type != "column":
            QMessageBox.warning(self, "No Reinforcement Data", 
                f"The frame section '{sec_name}' has no Concrete Column reinforcement defined. "
                "Please assign reinforcement in the Section Properties menu first.\n\n"
                "Reverting to User Defined mode."
            )
                                                              
            self.radio_user.setChecked(True)
            return

        def fmt(val_si):
            return f"{val_si * self.ls:.4g}"

        tie_dia = self._get_rebar_diameter(r.tie_bar_size)

        if sec.__class__.__name__ == "RectangularSection":
            self.radio_rect.setChecked(True)
            
            bc = max(0.0, sec.b - 2.0 * r.clear_cover - tie_dia)
            dc = max(0.0, sec.h - 2.0 * r.clear_cover - tie_dia)
            
            self.edit_x_spacing.setText(fmt(bc))
            self.edit_y_spacing.setText(fmt(dc))
            
            self.edit_num_x_legs.setText(str(r.num_ties_3dir))
            self.edit_num_y_legs.setText(str(r.num_ties_2dir))
            
            self.edit_num_long_x.setText(str(r.num_bars_3dir))
            self.edit_num_long_y.setText(str(r.num_bars_2dir))
            
            if r.long_bar_size in self._bar_items:
                self.combo_long_bar_rect.setCurrentText(r.long_bar_size)
                
        elif sec.__class__.__name__ == "CircularSection":
            self.radio_circ_spiral.setChecked(True) if r.confinement_type == "spiral" else self.radio_circ_hoop.setChecked(True)
            
            ds = max(0.0, sec.d - 2.0 * r.clear_cover - tie_dia)
            self.edit_core_diameter.setText(fmt(ds))
            self.edit_num_long_bars.setText(str(r.num_bars_circ))
            
            if r.long_bar_size in self._bar_items:
                self.combo_long_bar_size.setCurrentText(r.long_bar_size)

        self.radio_bar_size.setChecked(True)
        if r.tie_bar_size in self._bar_items:
            self.combo_bar_size.setCurrentText(r.tie_bar_size)
            
        self.edit_tie_spacing.setText(fmt(r.tie_spacing))
        
        _is_os = getattr(self.model, "analysis_engine", "native") == "opensees"
        self.data.tie_layout = (getattr(r, "tie_layout", "rect") or "rect") if _is_os else "rect"
        self.data.rho_s_scale = float(getattr(r, "rho_s_scale", 1.0) or 1.0) if _is_os else 1.0

        self.data.tie_bar_material = r.tie_bar_material
        self.data.confinement_fu = 0.0
        self.data.confinement_E = 0.0
        self.data.confinement_eps_sh = 0.0
        self.data.confinement_eps_su = 0.0
        self.data.confinement_curve_model = "Park"

        if r.tie_bar_material in self.model.materials:
            mat = self.model.materials[r.tie_bar_material]
            self.edit_fyh.setText(f"{getattr(mat, 'fy', 0.0) * self.ss:.4g}")
            self.data.confinement_fu = float(getattr(mat, "fu", 0.0) or 0.0)
            self.data.confinement_E = float(getattr(mat, "E", 0.0) or 0.0)

            nl = getattr(mat, "nonlinear", None)
            if nl is not None and getattr(mat, "mat_type", "").lower() == "rebar":
                self.data.confinement_eps_sh = float(getattr(nl, "rebar_eps_sh", 0.0) or 0.0)
                self.data.confinement_eps_su = float(getattr(nl, "rebar_eps_su", 0.0) or 0.0)
                self.data.confinement_curve_model = getattr(nl, "rebar_parametric_model", "Park") or "Park"

def _shade(hex_color, k, n, max_white=0.62):
    """Cycle k of n: the first cycle is a pale tint of the colour, the last one the full colour."""
    c = QColor(hex_color)
    mix = 0.0 if n <= 1 else max_white * (1.0 - k / (n - 1))
    return QColor(int(c.red() + (255 - c.red()) * mix),
                  int(c.green() + (255 - c.green()) * mix),
                  int(c.blue() + (255 - c.blue()) * mix)).name()

def _split_cycles(pts, ids):
    """One polyline per cycle; each starts at the last point of the previous one so the lines join."""
    out = {}
    for i, (pt, k) in enumerate(zip(pts, ids)):
        seg = out.setdefault(k, [])
        if not seg and i > 0:
            seg.append(pts[i - 1])
        seg.append(pt)
    return [out[k] for k in sorted(out)]

class OsConcretePreviewDialog(QDialog):
    """
    OpenSees concrete preview. 'Modify/Show Mander Data...' opens the SAME Mander dialog as the native plot.
    Both curves are run through the selected OpenSees concrete model with an increasing-amplitude cyclic history
    (4 compression cycles, each unloaded into a small tension excursion). Cycles are shaded light -> dark so
    the order is readable, and the dashed line is the monotonic envelope the loops come from.
    The Show box lets you look at the confined core or the unconfined cover on their own.
    """
    UNCONF, CONF = "#d32f2f", "#1565c0"

    def __init__(self, dlg, parent=None):
        super().__init__(parent)
        apply_dialog_style(self)
        self.setWindowTitle("OpenSees Concrete Response (cyclic)")
        self.resize(700, 660)
        self._dlg = dlg                                                                 
        self._res = {}
        root = QVBoxLayout(self)
        root.addWidget(QLabel(f"Material: {dlg.material_name}    Type: Concrete    Model: {dlg.nl_data.os_concrete_model}"))

        ctl = QHBoxLayout()
        ctl.addWidget(QLabel("Show:"))
        self.combo_show = QComboBox()
        self.combo_show.addItems(["Confined core + unconfined cover", "Confined core only", "Unconfined cover only"])
        self.combo_show.currentIndexChanged.connect(self._render)
        ctl.addWidget(self.combo_show)
        self.chk_env = QCheckBox("Monotonic envelope")
        self.chk_env.setChecked(True)
        self.chk_env.toggled.connect(self._render)
        ctl.addWidget(self.chk_env)
        ctl.addStretch(1)
        root.addLayout(ctl)

        self.plot = StressStrainPlotWidget()
        root.addWidget(self.plot, 1)
        self.lbl = QLabel("")
        self.lbl.setWordWrap(True)
        root.addWidget(self.lbl)
        self.mander_btn = QPushButton("Modify/Show Mander Data...")
        self.mander_btn.clicked.connect(self._open_mander_dialog)
        root.addWidget(self.mander_btn)
        done = QPushButton("Done"); done.clicked.connect(self.accept)
        root.addWidget(done)
        self._refresh()

    def _open_mander_dialog(self):
        dlg = self._dlg
        ManderDataDialog(model=dlg.model, mander_data=dlg.nl_data.mander, fc_si=dlg.fc_si,
                         stress_unit=dlg.stress_unit, stress_scale=dlg.stress_scale,
                         length_unit=dlg.length_unit, length_scale=dlg.length_scale,
                         on_update=self._refresh, parent=self).exec()
        self._refresh()

    def _run(self, osm, ctx, user, name):
        """Cyclic loops + monotonic envelope for one set of Concrete04-style parameters."""
        e0, ecu = abs(ctx["epsc0"]), abs(ctx["epscu"])
        top = ecu if ecu > 1.05 * e0 else 1.5 * e0                                                       
        levels = [0.5 * e0, e0, 0.5 * (e0 + top), 0.98 * top]                                
        strains, ids = osm.cyclic_history(levels, tension=2.0 * ctx["et"])
        sc = self._dlg.stress_scale
        emit = lambda ops, tag: osm.emit_material(ops, "concrete", name, tag, ctx, user)
        es, ss, ok = osm.run_uniaxial(emit, strains)
        pts = [(e, s_ * sc) for e, s_ in zip(es, ss)]
        ee, se, ok_env = osm.run_uniaxial(emit, osm.monotonic_history(1.25 * top))
        env = [(e, s_ * sc) for e, s_ in zip(ee, se)]
        return {"cyc": _split_cycles(pts, ids[:len(pts)]), "env": env, "ok": ok and ok_env}

    def _refresh(self, *_):
        from core.opensees_port import os_materials as osm
        from core.opensees_port import os_nonlinear as osn
        dlg = self._dlg
        d = dlg.nl_data
        note = []
        self._res = {}
        try:
            mat = {"name": "preview", "fy": dlg.fc_si, "E": dlg.e_si}
            area = _rebar_area_lookup(dlg.model)
            keys = ("fpc", "epsc0", "epscu", "Ec", "fct", "et")
            pu = osn.concrete04_params(mat, d, None, area)
            cu = {k: pu[k] for k in keys}
            cc = pc = None
            mander = d.mander
            if getattr(mander, "mander_type", "Unconfined") != "Unconfined":
                pc = osn.concrete04_params(mat, d, mander, area)
                cc = {k: pc[k] for k in keys}
            name = d.os_concrete_model
            self._res["u"] = self._run(osm, cu, pu["user"], name)
            if not self._res["u"]["ok"]:
                note.append("Unconfined run stopped early: no convergence.")
            if cc:
                self._res["c"] = self._run(osm, cc, pc["user"], name)
                self._res["c_label"] = "Confined (" + mander.mander_type.replace("_", " ") + ")"
                note.append(f"Confined: f'cc = {abs(cc['fpc']) * dlg.stress_scale:.4g} {dlg.stress_unit} "
                            f"(x{pc['fcc_ratio']:.2f}),  eps_cc = {cc['epsc0']:.5f},  eps_cu = {cc['epscu']:.5f}")
                if not self._res["c"]["ok"]:
                    note.append("Confined run stopped early: no convergence.")
            else:
                note.append(f"Unconfined: f'c = {abs(cu['fpc']) * dlg.stress_scale:.4g} {dlg.stress_unit},  "
                            f"eps_c0 = {cu['epsc0']:.5f},  eps_cu = {cu['epscu']:.5f}")
            if name == "Concrete04":
                note.append("Concrete04 drops to zero stress at eps_cu (its built-in crushing cut-off).")
            note.append("Cycles are shaded light to dark (first to last); dashed = monotonic envelope. "
                        "Preview only: in the section model the core is rebuilt from each section's own ties.")
        except Exception as ex:
            note.append(f"Preview failed: {ex}")
        self.combo_show.blockSignals(True)
        if "c" not in self._res:
            self.combo_show.setCurrentIndex(2)
        self.combo_show.setEnabled("c" in self._res)
        self.combo_show.blockSignals(False)
        self.lbl.setText("\n".join(note))
        self._render()

    def _render(self, *_):
        r = self._res
        if "u" not in r:
            self.plot.set_layers([], x_label="Strain (m/m)", y_label=f"Stress [{self._dlg.stress_unit}]")
            return
        show = self.combo_show.currentIndex()                                                        
        layers, legend = [], []

        def add(key, base, label):
            data = r[key]
            if self.chk_env.isChecked():
                layers.append(dict(pts=data["env"], color=_shade(base, 0, 2, 0.45), width=1.4, dash=True))
            n = len(data["cyc"])
            for k, poly in enumerate(data["cyc"]):
                layers.append(dict(pts=poly, color=_shade(base, k, n), width=1.7))
            legend.append((label, base))

        if show in (0, 2):
            add("u", self.UNCONF, "Unconfined cover")
        if show in (0, 1) and "c" in r:
            add("c", self.CONF, r["c_label"])
        if self.chk_env.isChecked():
            legend.append(("Monotonic envelope", "#8a8a8a", True))
        self.plot.set_layers(layers, x_label="Strain (m/m)",
                             y_label=f"Stress [{self._dlg.stress_unit}]", legend=legend)

class StressStrainPlotDialog(QDialog):
    """
    'Material Stress-Strain Curve Plot' dialog (Image 7). Cosmetic controls
    (background/colour pickers, border checkboxes, disable-snap) are
    intentionally omitted — just a live plot + hover readout + (for the
    Mander parametric model) the 'Modify/Show Mander Data' button.

    get_points_fn() must return (points, marker) in DISPLAY units, called
    fresh every time the plot needs to (re)draw — this is what makes the
    plot "live" against whatever is currently typed in the parent dialog.
    """

    def __init__(self, material_name, material_type, get_points_fn,
                 model=None, mander_data=None, fc_si=0.0,
                 stress_unit="", stress_scale=1.0, length_unit="", length_scale=1.0,
                 show_mander_button=False, parent=None):
        super().__init__(parent)
        apply_dialog_style(self)
        self.setWindowTitle("Material Stress-Strain Curve Plot")
        self.resize(560, 480)
        self.model = model
        self.get_points_fn = get_points_fn
        self.mander_data = mander_data
        self.fc_si = fc_si
        self.stress_unit = stress_unit
        self.stress_scale = stress_scale
        self.length_unit = length_unit
        self.length_scale = length_scale

        root = QVBoxLayout(self)
        header = QHBoxLayout()
        header.addWidget(QLabel(f"Material: {material_name}    Type: {material_type}"))
        root.addLayout(header)

        self.plot_widget = StressStrainPlotWidget()
        self.plot_widget.set_curve([(0, 0)], x_label="Strain (m/m)", y_label=f"Stress [{stress_unit}]")
        root.addWidget(self.plot_widget)

        if show_mander_button:
            self.mander_btn = QPushButton("Modify/Show Mander Data...")
            self.mander_btn.clicked.connect(self._open_mander_dialog)
            root.addWidget(self.mander_btn)

        root.addWidget(_divider())
        done_btn = QPushButton("Done")
        done_btn.clicked.connect(self.accept)
        root.addWidget(done_btn)

        self.refresh()

    def refresh(self):
        points, marker = self.get_points_fn()
        self.plot_widget.set_curve(points, marker=marker, y_label=f"Stress [{self.stress_unit}]")

    def _open_mander_dialog(self):
        dlg = ManderDataDialog(
            model=self.model,
            mander_data=self.mander_data, fc_si=self.fc_si,
            stress_unit=self.stress_unit, stress_scale=self.stress_scale,
            length_unit=self.length_unit, length_scale=self.length_scale,
            on_update=self.refresh, parent=self,
        )
        dlg.exec()
        self.refresh()

HYSTERESIS_TYPES = [
    "Elastic", "Kinematic", "Takeda", "Pivot", "Concrete",
    "BRB Hardening", "Degrading", "Isotropic",
]

class NonlinearMaterialDialog(QDialog):
    def __init__(self, model, material_name, material_type, fc_si, e_si, fu_si,
                 data: "NonlinearMaterialData | None",
                 stress_unit, stress_scale, length_unit, length_scale, parent=None):
        super().__init__(parent)
        apply_dialog_style(self)
        self.setWindowTitle("Nonlinear Material Data")
        self.resize(680, 500)

        self.model = model
        self.material_name = material_name
        self.material_type = material_type
        self.fc_si = fc_si
        self.e_si = e_si
        self.fu_si = fu_si
        self.stress_unit = stress_unit
        self.stress_scale = stress_scale
        self.length_unit = length_unit
        self.length_scale = length_scale

        import copy
        self.nl_data = copy.deepcopy(data) if data else NonlinearMaterialData()
        self.result_data = None

        main_layout = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent;")
        content_widget = QWidget()
        content_widget.setStyleSheet("background: transparent;")
        root = QVBoxLayout(content_widget)

        header_form = QFormLayout()
        name_edit = QLineEdit(material_name)
        name_edit.setReadOnly(True)
        type_edit = QLineEdit(material_type)
        type_edit.setReadOnly(True)
        header_form.addRow("Material Name", name_edit)
        header_form.addRow("Material Type", type_edit)
        root.addLayout(header_form)

        hyst_group = QGroupBox("Hysteresis Type")
        hyst_layout = QHBoxLayout(hyst_group)
        self.combo_hysteresis = QComboBox()
        self.combo_hysteresis.addItems(HYSTERESIS_TYPES)
        hyst_layout.addWidget(self.combo_hysteresis)
        self.lbl_hyst_note = QLabel("")
        self.lbl_hyst_note.setStyleSheet("color: #b06000; font-size: 10px;")
        self.lbl_hyst_note.setWordWrap(True)
        hyst_layout.addWidget(self.lbl_hyst_note)
        root.addWidget(hyst_group)

        dp_group = QGroupBox("Drucker-Prager Parameters")
        dp_form = QFormLayout(dp_group)
        self.edit_friction = QLineEdit("0.")
        self.edit_dilatational = QLineEdit("0.")
        dp_form.addRow("Friction Angle", self.edit_friction)
        dp_form.addRow("Dilatational Angle", self.edit_dilatational)
        root.addWidget(dp_group)

        dp_group.setEnabled(self.material_type != "Rebar")

        curve_group = QGroupBox("Stress-Strain Curve Definition Options")
        curve_layout = QVBoxLayout(curve_group)
        mode_row = QHBoxLayout()
        self.radio_parametric = QRadioButton("Parametric")
        self.radio_user_defined = QRadioButton("User Defined")
        self.radio_parametric.setChecked(True)
        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.radio_parametric)
        self.mode_group.addButton(self.radio_user_defined)
        
        self.combo_parametric_model = QComboBox()
        if self.material_type == "Rebar":
            self.combo_parametric_model.addItems(["Park", "Simple"])
        elif self.material_type == "Steel":
            self.combo_parametric_model.addItems(["Simple"])
        else:
            self.combo_parametric_model.addItems(["Mander (Exact)"])
            
        mode_row.addWidget(self.radio_parametric)
        mode_row.addWidget(self.combo_parametric_model)
        mode_row.addWidget(self.radio_user_defined)
        curve_layout.addLayout(mode_row)

        convert_btn = QPushButton("Convert To User Defined")
        convert_btn.clicked.connect(self._convert_to_user_defined)
        curve_layout.addWidget(convert_btn)

        self.curve_stack = QStackedWidget()

        param_page = QWidget()
        param_layout = QVBoxLayout(param_page)
        
        self.param_input_stack = QStackedWidget()
        
        concrete_w = QWidget()
        concrete_form = QFormLayout(concrete_w)
        self.edit_eps_c0 = QLineEdit("2.000E-03")
        self.edit_eps_cu = QLineEdit("5.000E-03")
        concrete_form.addRow("Strain At Unconfined Compressive Strength, f'c", self.edit_eps_c0)
        concrete_form.addRow("Ultimate Unconfined Strain Capacity", self.edit_eps_cu)
        self.combo_core_epscu = QComboBox()
        self.combo_core_epscu.addItems(["Mander (energy balance)", "User value"])
        self.edit_core_epscu = QLineEdit("-3.500E-02")
        self.combo_core_epscu.currentIndexChanged.connect(self._sync_core_epscu)
        concrete_form.addRow("Confined Core \u03b5_cu (OpenSees)", self.combo_core_epscu)
        concrete_form.addRow("Confined Core \u03b5_cu Value", self.edit_core_epscu)
        _tip = ("OpenSees engine only. Ultimate compressive strain of the CONFINED CORE concrete. "
                "'Mander (energy balance)' keeps the computed value; 'User value' overrides it "
                "(negative = compression). Cover concrete is not affected.")
        self.combo_core_epscu.setToolTip(_tip); self.edit_core_epscu.setToolTip(_tip)
        self.os_conc_panel = OsModelPanel("concrete")
        self.os_conc_panel.model_changed.connect(self._sync_core_epscu)
        self.os_conc_panel.preview_requested.connect(self._preview_opensees)
        concrete_form.addRow("OpenSees Concrete Model", self.os_conc_panel)
        self.param_input_stack.addWidget(concrete_w)
        
        rebar_w = QWidget()
        rebar_form = QFormLayout(rebar_w)
        self.edit_rebar_eps_sh = QLineEdit("0.015")
        self.edit_rebar_eps_su = QLineEdit("0.09")

        rebar_form.addRow("Strain At Onset of Strain Hardening", self.edit_rebar_eps_sh)
        rebar_form.addRow("Ultimate Strain Capacity", self.edit_rebar_eps_su)
        self.os_rebar_panel = OsModelPanel("steel")
        self.os_rebar_panel.preview_requested.connect(self._preview_opensees)
        rebar_form.addRow("OpenSees Steel Model", self.os_rebar_panel)
        self.param_input_stack.addWidget(rebar_w)

        steel_w = QWidget()
        steel_form = QFormLayout(steel_w)
        self.edit_steel_eps_sh = QLineEdit("0.015")
        self.edit_steel_eps_su = QLineEdit("0.110")
        self.edit_steel_eps_rupture = QLineEdit("0.170")

        steel_form.addRow("Strain At Onset of Strain Hardening", self.edit_steel_eps_sh)
        steel_form.addRow("Strain At Maximum Stress", self.edit_steel_eps_su)
        steel_form.addRow("Strain At Rupture", self.edit_steel_eps_rupture)
        self.os_steel_panel = OsModelPanel("steel")
        self.os_steel_panel.preview_requested.connect(self._preview_opensees)
        steel_form.addRow("OpenSees Steel Model", self.os_steel_panel)
        self.param_input_stack.addWidget(steel_w)

        shared_form = QFormLayout()
        self.edit_final_slope = QLineEdit("-0.1")
        shared_form.addRow("Final Slope (Multiplier on E)", self.edit_final_slope)
        
        param_layout.addWidget(self.param_input_stack)
        param_layout.addLayout(shared_form)
        
        self.btn_show_plot = QPushButton("Show Stress-Strain Plot...")
        self.btn_show_plot.clicked.connect(self._show_parametric_plot)
        param_layout.addWidget(self.btn_show_plot)
        self.curve_stack.addWidget(param_page)

        ud_page = QWidget()
        ud_layout = QVBoxLayout(ud_page)
        count_row = QHBoxLayout()
        count_row.addWidget(QLabel("Number of Points in Stress-Strain Curve"))
        self.edit_num_points = QLineEdit("120") 
        self.edit_num_points.editingFinished.connect(self._resize_table)
        count_row.addWidget(self.edit_num_points)
        ud_layout.addLayout(count_row)

        key_group = QGroupBox("Key Points")
        key_layout = QVBoxLayout(key_group)
        selection_style = """
            QTableWidget { selection-background-color: #cce4f7; selection-color: black; }
            QTableWidget::item:selected { background-color: #cce4f7; color: black; }
        """
        self.table_key_points = CopyableTableWidget(0, 3)
        self.table_key_points.setHorizontalHeaderLabels(["Strain", "Stress", "Point ID"])
        self.table_key_points.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table_key_points.verticalHeader().setVisible(False)
        self.table_key_points.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table_key_points.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.table_key_points.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table_key_points.setStyleSheet(selection_style)
        self.table_key_points.setFixedHeight(100)
        key_layout.addWidget(self.table_key_points)
        ud_layout.addWidget(key_group)

        self.table_points = CopyableTableWidget(0, 3)
        self.table_points.setHorizontalHeaderLabels(["Strain", "Stress", "Point ID"])
        self.table_points.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table_points.itemChanged.connect(self._refresh_key_points_panel)
        self.table_points.setMinimumHeight(150)
        self.table_points.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.table_points.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table_points.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.AnyKeyPressed)
        self.table_points.setStyleSheet(selection_style)
        
        ud_layout.addWidget(self.table_points)
        
        ud_btn_row = QHBoxLayout()
        order_btn = QPushButton("Order Rows")
        order_btn.clicked.connect(self._order_rows)
        ud_show_plot_btn = QPushButton("Show Plot...")
        ud_show_plot_btn.clicked.connect(self._show_user_defined_plot)
        export_csv_btn = QPushButton("Export CSV")
        export_csv_btn.clicked.connect(self._export_csv)
        export_excel_btn = QPushButton("Export Excel")
        export_excel_btn.clicked.connect(self._export_excel)

        ud_btn_row.addWidget(order_btn)
        ud_btn_row.addWidget(ud_show_plot_btn)
        ud_btn_row.addWidget(export_csv_btn)
        ud_btn_row.addWidget(export_excel_btn)
        ud_layout.addLayout(ud_btn_row)
        self.curve_stack.addWidget(ud_page)

        curve_layout.addWidget(self.curve_stack)
        root.addWidget(curve_group)
        scroll.setWidget(content_widget)
        main_layout.addWidget(scroll)

        main_layout.addWidget(_divider())
        btn_row = QHBoxLayout()
        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(self._on_ok)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        main_layout.addLayout(btn_row)

        self.radio_parametric.toggled.connect(self._on_mode_toggled)
        self.radio_user_defined.toggled.connect(self._on_mode_toggled)

        if self.material_type == "Rebar":
            self.param_input_stack.setCurrentIndex(1)
        elif self.material_type == "Steel":
            self.param_input_stack.setCurrentIndex(2)
        else:
            self.param_input_stack.setCurrentIndex(0)
            
        self._load_from_data()
        self._apply_opensees_restrictions()

    def _sync_core_epscu(self, *_):
        opensees = is_opensees(self.model)
        is_conc = self.material_type not in ("Rebar", "Steel")
        self.combo_core_epscu.setEnabled(opensees and is_conc)
        self.edit_core_epscu.setEnabled(opensees and is_conc and self.combo_core_epscu.currentIndex() == 1)
        for _p in (self.os_conc_panel, self.os_rebar_panel, self.os_steel_panel):
            _p.set_os_enabled(opensees)
                                                                                                              
        self.btn_show_plot.setEnabled(not opensees)
        self.btn_show_plot.setToolTip("Native solver only. With the OpenSees engine use \"Preview OpenSees response...\" "
                                      "in the OpenSees model section, which runs the real material." if opensees else "")
                                                                                  
        _uses_ecu = self.os_conc_panel.current_model() in ("Concrete04", "Concrete01", "Concrete02")                                           
        self.combo_core_epscu.setEnabled(opensees and is_conc and _uses_ecu)
        self.edit_core_epscu.setEnabled(opensees and is_conc and _uses_ecu and self.combo_core_epscu.currentIndex() == 1)

    def _apply_opensees_restrictions(self):
        """Grey out combo items / radio buttons OpenSees can't back, per
        os_capabilities.py (the same rule os_nonlinear.py's converter uses).
        Runs after _load_from_data(), so it can see (and if needed override)
        whatever value was actually loaded.

        NOTE: the pop-up warning + bulk backup/restore for EXISTING materials
        happens once, at the moment the Analysis Engine is switched (see
        analysis_options_dialog.apply_changes -> apply_engine_switch). This
        method only needs to (a) grey out the combo so a NEW selection can't
        be made here, and (b) catch the edge case of a material CREATED
        after the engine was already switched to OpenSees, which the
        switch-time scan never saw. That edge case gets a quiet inline note,
        not another pop-up -- the user already saw the warning once."""
        d = self.nl_data
        opensees = is_opensees(self.model)
        self._sync_core_epscu()

        model_view = self.combo_hysteresis.model()
        for i in range(self.combo_hysteresis.count()):
            item = model_view.item(i)
            unsupported = opensees and self.combo_hysteresis.itemText(i) in UNSUPPORTED_HYSTERESIS
            item.setEnabled(not unsupported)

        if opensees and d.hysteresis_type in UNSUPPORTED_HYSTERESIS:
            if d.native_hysteresis_backup is None:
                d.native_hysteresis_backup = d.hysteresis_type
            d.hysteresis_type = DEFAULT_HYSTERESIS
            idx = self.combo_hysteresis.findText(DEFAULT_HYSTERESIS)
            self.combo_hysteresis.setCurrentIndex(idx if idx >= 0 else 0)
            self.lbl_hyst_note.setText(f"'{d.native_hysteresis_backup}' has no OpenSees equivalent -> "
                                        f"using '{DEFAULT_HYSTERESIS}'.")
        elif not opensees and d.native_hysteresis_backup is not None:
            idx = self.combo_hysteresis.findText(d.native_hysteresis_backup)
            self.combo_hysteresis.setCurrentIndex(idx if idx >= 0 else 2)
            d.hysteresis_type = d.native_hysteresis_backup
            d.native_hysteresis_backup = None

        if opensees and self.radio_user_defined.isChecked() and UNSUPPORTED_CURVE_MODE:
                                                                          
            self.radio_parametric.setChecked(True)
            note = "Note: 'User Defined' stress-strain curves are not converted for OpenSees yet; using Parametric."
            self.lbl_hyst_note.setText(
                self.lbl_hyst_note.text() + "  " + note if self.lbl_hyst_note.text() else note)
        self.radio_user_defined.setEnabled(not opensees)

    def _load_from_data(self):
        d = self.nl_data
        idx = self.combo_hysteresis.findText(d.hysteresis_type)
        self.combo_hysteresis.setCurrentIndex(idx if idx >= 0 else 2)
        self.edit_friction.setText(_fmt4(d.friction_angle))
        self.edit_dilatational.setText(_fmt4(d.dilatational_angle))

        if d.curve_mode == "User Defined":
            self.radio_user_defined.setChecked(True)
        else:
            self.radio_parametric.setChecked(True)

        if self.material_type == "Rebar":
            idx = self.combo_parametric_model.findText(getattr(d, "rebar_parametric_model", "Park"))
            self.edit_rebar_eps_sh.setText(_fmt4(getattr(d, "rebar_eps_sh", 0.015)))
            self.edit_rebar_eps_su.setText(_fmt4(getattr(d, "rebar_eps_su", 0.090)))
            self.os_rebar_panel.set_state(getattr(d, "os_steel_model", "ReinforcingSteel"),
                                          getattr(d, "os_params", None), getattr(d, "os_rupture", False))
        elif self.material_type == "Steel":
            idx = self.combo_parametric_model.findText("Simple")
            self.edit_steel_eps_sh.setText(_fmt4(getattr(d, "steel_eps_sh", 0.015)))
            self.edit_steel_eps_su.setText(_fmt4(getattr(d, "steel_eps_su", 0.110)))
            self.edit_steel_eps_rupture.setText(_fmt4(getattr(d, "steel_eps_rupture", 0.170)))
            self.os_steel_panel.set_state(getattr(d, "os_steel_model", "ReinforcingSteel"),
                                          getattr(d, "os_params", None), getattr(d, "os_rupture", False))
        else:
            idx = self.combo_parametric_model.findText(getattr(d, "parametric_model", "Mander (Exact)"))
            self.edit_eps_c0.setText(_fmt4(d.eps_c0))
            self.edit_eps_cu.setText(_fmt4(d.eps_cu))
            self.combo_core_epscu.setCurrentIndex(1 if getattr(d, "core_eps_cu_mode", "Mander") == "User" else 0)
            self.edit_core_epscu.setText(_fmt4(getattr(d, "core_eps_cu_user", -0.035)))
            _user = dict(getattr(d, "os_params", None) or {})
            if getattr(d, "os_concrete_model", "Concrete04") == "ConcreteCM":                          
                _user.setdefault("xcrn", getattr(d, "cm_xcrn", 2.3))
                _user.setdefault("rt", getattr(d, "cm_rt", 1.2))
                _user.setdefault("xcrp", getattr(d, "cm_xcrp", 10000.0))
            self.os_conc_panel.set_state(getattr(d, "os_concrete_model", "Concrete04"), _user)
            
        if idx >= 0:
            self.combo_parametric_model.setCurrentIndex(idx)
        self.edit_final_slope.setText(_fmt4(d.final_slope_mult))

        self._set_table_points_display([
            (s, f * self.stress_scale, pid) for (s, f, pid) in d.user_points
        ])
        self._on_mode_toggled()

    def _pull_common_fields(self):
        def f(edit, default=0.0):
            try:
                return float(edit.text() or default)
            except ValueError:
                return default

        d = self.nl_data
        d.hysteresis_type = self.combo_hysteresis.currentText()
        d.friction_angle = f(self.edit_friction)
        d.dilatational_angle = f(self.edit_dilatational)
        d.curve_mode = "User Defined" if self.radio_user_defined.isChecked() else "Parametric"
        
        if self.material_type == "Rebar":
            d.rebar_parametric_model = self.combo_parametric_model.currentText()
            d.rebar_eps_sh = f(self.edit_rebar_eps_sh, 0.015)
            d.rebar_eps_su = f(self.edit_rebar_eps_su, 0.090)
            d.os_steel_model, d.os_params, d.os_rupture = self.os_rebar_panel.get_state()

        elif self.material_type == "Steel":
            d.parametric_model = self.combo_parametric_model.currentText()
            d.steel_eps_sh = f(self.edit_steel_eps_sh, 0.015)
            d.steel_eps_su = f(self.edit_steel_eps_su, 0.110)
            d.steel_eps_rupture = f(self.edit_steel_eps_rupture, 0.170)
            d.os_steel_model, d.os_params, d.os_rupture = self.os_steel_panel.get_state()
        else:
            d.parametric_model = self.combo_parametric_model.currentText()
            d.eps_c0 = f(self.edit_eps_c0, 2.0e-3)
            d.eps_cu = f(self.edit_eps_cu, 5.0e-3)
            d.core_eps_cu_mode = "User" if self.combo_core_epscu.currentIndex() == 1 else "Mander"
            d.core_eps_cu_user = -abs(f(self.edit_core_epscu, -0.035)) or -0.035
            d.os_concrete_model, d.os_params, _ = self.os_conc_panel.get_state()
            for _k in ("xcrn", "rt", "xcrp"):                                                                
                if _k in d.os_params:
                    setattr(d, "cm_" + _k, d.os_params[_k])
            
        d.final_slope_mult = f(self.edit_final_slope, -0.1)
        d.user_points = [
            (s, f_ / self.stress_scale, pid) for (s, f_, pid) in self._pull_table_points_display()
        ]

    def _preview_opensees(self):
        """Cyclic strain history on this one material in OpenSees -> stress-strain plot."""
        try:
            import openseespy.opensees              
        except Exception:
            QMessageBox.warning(self, "OpenSees not available", "openseespy is not installed in this environment.")
            return
        from core.opensees_port import os_materials as osm
        from core.opensees_port import os_nonlinear as osn
        self._pull_common_fields()
        d = self.nl_data
        try:
            if self.material_type in ("Rebar", "Steel"):
                mat = {"name": "preview", "type": "rebar" if self.material_type == "Rebar" else "steel",
                       "fy": self.fc_si, "fu": self.fu_si, "E": self.e_si}
                ctx = osn.rebar_params(mat, d)
                kind, name, user = "steel", d.os_steel_model, d.os_params
                ey, eu = ctx["fy"] / ctx["Es"], ctx["eu"]
                peaks = [2 * ey, -2 * ey, 0.25 * eu, -0.25 * eu, 0.5 * eu, -0.5 * eu, 0.9 * eu]
                rupture = d.os_rupture
                if rupture:
                    peaks += [-1.1 * eu, 1.1 * eu]
            else:
                OsConcretePreviewDialog(self, parent=self).exec()
                return
            strains = osm.strain_history(peaks)

            def _emit(ops, tag):
                if rupture:                                                                                        
                    osm.emit_material(ops, kind, name, tag + 10, ctx, user, True, next_tag=lambda: tag)
                else:
                    osm.emit_material(ops, kind, name, tag, ctx, user)
            es, ss, ok = osm.run_uniaxial(_emit, strains)
        except Exception as ex:
            QMessageBox.warning(self, "OpenSees preview failed", str(ex))
            return
        pts = [(e, s_ * self.stress_scale) for e, s_ in zip(es, ss)]
        dlg = StressStrainPlotDialog(f"{name} (OpenSees, cyclic)", self.material_type, lambda: (pts, None),
                                     model=self.model, fc_si=self.fc_si, stress_unit=getattr(self, "stress_unit", ""),
                                     stress_scale=self.stress_scale, parent=self)
        if not ok:
            dlg.setWindowTitle("Material Stress-Strain Curve Plot  (analysis stopped early: no convergence)")
        dlg.exec()

    def _show_parametric_plot(self):
        self._pull_common_fields()

        def get_points_fn():
            def f(edit, default=0.0):
                try:
                    return float(edit.text() or default)
                except ValueError:
                    return default

            slope = f(self.edit_final_slope, -0.1)
            model_choice = self.combo_parametric_model.currentText()
            
            if self.material_type == "Rebar":
                eps_sh = f(self.edit_rebar_eps_sh, 0.015)
                eps_su = f(self.edit_rebar_eps_su, 0.090)
                pts_si, marker_si = generate_rebar_curve(
                    self.fc_si, self.fu_si, self.e_si, eps_sh, eps_su, slope, model_choice, n_inter=40
                )
                pts_display = [(s, f_ * self.stress_scale) for (s, f_) in pts_si]
                marker = (marker_si[0], marker_si[1] * self.stress_scale)
                return pts_display, marker

            elif self.material_type == "Steel":
                eps_sh = f(self.edit_steel_eps_sh, 0.015)
                eps_su = f(self.edit_steel_eps_su, 0.110)
                eps_rup = f(self.edit_steel_eps_rupture, 0.170)
                pts_si, marker_si = generate_steel_curve(
                    self.fc_si, self.fu_si, self.e_si, eps_sh, eps_su, eps_rup, slope, n_inter=40
                )
                pts_display = [(s, f_ * self.stress_scale) for (s, f_) in pts_si]
                marker = (marker_si[0], marker_si[1] * self.stress_scale)
                return pts_display, marker
                
            else:
                eps_c0 = f(self.edit_eps_c0, 2.0e-3)
                eps_cu = f(self.edit_eps_cu, 5.0e-3)
                pts_si, result = generate_mander_curve(
                    self.fc_si, eps_c0, eps_cu, slope, self.e_si, mander=self.nl_data.mander,
                    area_lookup=_rebar_area_lookup(self.model),
                    model_choice=model_choice
                )
                pts_display = [(s, f_ * self.stress_scale) for (s, f_) in pts_si]
                ratio = result.get("fcc_ratio", 1.0)
                eps_peak = eps_c0 * (1.0 + 5.0 * (ratio - 1.0))
                fpeak = self.fc_si * ratio
                marker = (-eps_peak, -fpeak * self.stress_scale)
                return pts_display, marker

        dlg = StressStrainPlotDialog(
            self.material_name, self.material_type, get_points_fn,
            model=self.model,
            mander_data=self.nl_data.mander, fc_si=self.fc_si,
            stress_unit=self.stress_unit, stress_scale=self.stress_scale,
            length_unit=self.length_unit, length_scale=self.length_scale,
            show_mander_button=(self.material_type != "Rebar"), parent=self,
        )
        dlg.exec()

    def _repopulate_user_defined(self, n_inter):
        def f(edit, default=0.0):
            try:
                return float(edit.text() or default)
            except ValueError:
                return default

        slope = f(self.edit_final_slope, -0.1)
        model_choice = self.combo_parametric_model.currentText()

        if self.material_type == "Rebar":
            eps_sh = f(self.edit_rebar_eps_sh, 0.015)
            eps_su = f(self.edit_rebar_eps_su, 0.090)
            pts_si, _ = generate_rebar_curve(
                self.fc_si, self.fu_si, self.e_si, eps_sh, eps_su, slope, model_choice, n_inter
            )
                                                                                     
            pts_display = [[s, f_ * self.stress_scale, ""] for (s, f_) in pts_si]
            
            tol = 1e-6
            for row in pts_display:
                if abs(row[0] - 0.0) < tol: row[2] = "A"
                elif abs(row[0] - (self.fc_si/self.e_si)) < tol: row[2] = "B"
                elif abs(row[0] - eps_sh) < tol: row[2] = "C"
                elif abs(row[0] - eps_su) < tol: row[2] = "E"
                
                elif abs(row[0] - -(self.fc_si/self.e_si)) < tol: row[2] = "-B"
                elif abs(row[0] - -eps_sh) < tol: row[2] = "-C"
                elif abs(row[0] - -eps_su) < tol: row[2] = "-E"
            
        elif self.material_type == "Steel":
            eps_sh = f(self.edit_steel_eps_sh, 0.015)
            eps_su = f(self.edit_steel_eps_su, 0.110)
            eps_rup = f(self.edit_steel_eps_rupture, 0.170)
            pts_si, _ = generate_steel_curve(
                self.fc_si, self.fu_si, self.e_si, eps_sh, eps_su, eps_rup, slope, n_inter
            )
            pts_display = [[s, f_ * self.stress_scale, ""] for (s, f_) in pts_si]
            
            tol = 1e-6
            for row in pts_display:
                if abs(row[0] - 0.0) < tol: row[2] = "A"
                elif abs(row[0] - (self.fc_si/self.e_si)) < tol: row[2] = "B"
                elif abs(row[0] - eps_sh) < tol: row[2] = "C"
                elif abs(row[0] - eps_su) < tol: row[2] = "D"
                elif abs(row[0] - eps_rup) < tol: row[2] = "E"
                
                elif abs(row[0] - -(self.fc_si/self.e_si)) < tol: row[2] = "-B"
                elif abs(row[0] - -eps_sh) < tol: row[2] = "-C"
                elif abs(row[0] - -eps_su) < tol: row[2] = "-D"
                elif abs(row[0] - -eps_rup) < tol: row[2] = "-E"

        else:
            eps_c0 = f(self.edit_eps_c0, 2.0e-3)
            eps_cu = f(self.edit_eps_cu, 5.0e-3)
            pts_si, _result = generate_mander_curve(
                self.fc_si, eps_c0, eps_cu, slope, self.e_si, mander=self.nl_data.mander,
                n=n_inter, area_lookup=_rebar_area_lookup(self.model), model_choice=model_choice
            )
            control_pts_si, _cp_result = get_control_points(
                self.fc_si, eps_c0, eps_cu, slope, self.e_si, mander=self.nl_data.mander,
                area_lookup=_rebar_area_lookup(self.model),
            )
            pts_display = [[s, f_ * self.stress_scale, ""] for (s, f_) in pts_si]

            tol = max(abs(eps_c0) * 1e-3, 1e-9)
            for cs, cf, label in control_pts_si:
                match = next((row for row in pts_display if abs(row[0] - cs) <= tol), None)
                if match is not None:
                    match[0], match[1], match[2] = cs, cf * self.stress_scale, label
                else:
                    pts_display.append([cs, cf * self.stress_scale, label])

        pts_display.sort(key=lambda row: row[0])
        self._set_table_points_display([tuple(row) for row in pts_display])

    def _set_table_points_display(self, points):
        self.table_points.blockSignals(True)
        self.table_points.setRowCount(len(points))
        for row, (strain, stress, pid) in enumerate(points):
            self.table_points.setItem(row, 0, QTableWidgetItem(_fmt4(strain)))
            self.table_points.setItem(row, 1, QTableWidgetItem(_fmt4(stress)))
            self.table_points.setItem(row, 2, QTableWidgetItem(str(pid)))
        self.table_points.blockSignals(False)
        self._refresh_key_points_panel()

    def _refresh_key_points_panel(self):
        """Pulls just the labeled rows (non-empty Point ID) out of the full
        table and pins them in the small always-visible Key Points table,
        sorted by strain -- so A/B/-C/-E/etc. are visible regardless of
        where they land in the full (possibly 100+ row) curve."""
        labeled = [p for p in self._pull_table_points_display() if p[2].strip()]
        labeled.sort(key=lambda p: p[0])
        self.table_key_points.setRowCount(len(labeled))
        for row, (strain, stress, pid) in enumerate(labeled):
            self.table_key_points.setItem(row, 0, QTableWidgetItem(_fmt4(strain)))
            self.table_key_points.setItem(row, 1, QTableWidgetItem(_fmt4(stress)))
            self.table_key_points.setItem(row, 2, QTableWidgetItem(str(pid)))

    def _pull_table_points_display(self):
        pts = []
        for row in range(self.table_points.rowCount()):
            def cell(col):
                item = self.table_points.item(row, col)
                return item.text() if item else ""
            try:
                strain = float(cell(0) or 0)
                stress = float(cell(1) or 0)
            except ValueError:
                continue
            pts.append((strain, stress, cell(2)))
        return pts

    def _order_rows(self):
        pts = sorted(self._pull_table_points_display(), key=lambda p: p[0])
        self._set_table_points_display(pts)

    def _on_mode_toggled(self):
        is_param = self.radio_parametric.isChecked()
        self.curve_stack.setCurrentIndex(0 if is_param else 1)

    def _unconfined_short_table(self):
        """Short fixed-grid table for an unconfined Mander concrete curve,
        or None for any other material / a confined section."""
        if self.material_type in ("Rebar", "Steel"):
            return None

        def f(edit, default):
            try:
                return float(edit.text() or default)
            except ValueError:
                return default

        return unconfined_user_table(
            self.fc_si, f(self.edit_eps_c0, 2.0e-3), f(self.edit_eps_cu, 5.0e-3),
            self.e_si, mander=self.nl_data.mander,
            area_lookup=_rebar_area_lookup(self.model),
        )

    def _convert_to_user_defined(self):
        self._pull_common_fields()
        self._short_table_count = None

        short = self._unconfined_short_table()
        if short is not None:
                                                                    
            pts_display = [(s, f_ * self.stress_scale, pid) for (s, f_, pid) in short]
            self._set_table_points_display(pts_display)
            self._short_table_count = len(pts_display)
            self.edit_num_points.setText(str(len(pts_display)))
            self.radio_user_defined.setChecked(True)
            return

        try:
            n_inter = max(int(self.edit_num_points.text() or 120), 0)
        except ValueError:
            n_inter = 120
            self.edit_num_points.setText("120")
            
        self._repopulate_user_defined(n_inter)
        self.radio_user_defined.setChecked(True)

    def _resize_table(self):
                                                                            
        short_n = getattr(self, "_short_table_count", None)
        if short_n is not None and self.edit_num_points.text().strip() == str(short_n):
            return
        self._short_table_count = None
        try:
            n_inter = max(int(self.edit_num_points.text() or 120), 0)
        except ValueError:
            n_inter = 120
            self.edit_num_points.setText("120")
            
        self._repopulate_user_defined(n_inter)

    def _show_user_defined_plot(self):
        def get_points_fn():
            pts = sorted(
                [(s, f) for (s, f, _pid) in self._pull_table_points_display()],
                key=lambda p: p[0],
            )
            return (pts if pts else [(0.0, 0.0)]), None

        dlg = StressStrainPlotDialog(
            self.material_name, self.material_type, get_points_fn,
            stress_unit=self.stress_unit, stress_scale=self.stress_scale,
            length_unit=self.length_unit, length_scale=self.length_scale,
            show_mander_button=False, parent=self,
        )
        dlg.exec()

    def _on_ok(self):
        try:
            self._pull_common_fields()
            self.result_data = self.nl_data
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not save nonlinear data:\n{e}")

    def get_data(self) -> "NonlinearMaterialData | None":
        return self.result_data

    def _export_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export CSV", f"{self.material_name}_points.csv", "CSV Files (*.csv)")
        if not path:
            return

        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                headers = [self.table_points.horizontalHeaderItem(c).text() for c in range(self.table_points.columnCount())]
                writer.writerow(headers)
                for r in range(self.table_points.rowCount()):
                    row_vals = [self.table_points.item(r, c).text() if self.table_points.item(r, c) else "" for c in range(self.table_points.columnCount())]
                    writer.writerow(row_vals)
            QMessageBox.information(self, "Export Complete", f"Table exported to:\n{path}")
        except OSError as e:
            QMessageBox.warning(self, "Export Failed", str(e))

    def _export_excel(self):
        try:
            import openpyxl
        except ImportError:
            QMessageBox.warning(
                self, "Missing Dependency",
                "Excel export requires the 'openpyxl' package.\n\nInstall it with:\npip install openpyxl"
            )
            return

        path, _ = QFileDialog.getSaveFileName(self, "Export Excel", f"{self.material_name}_points.xlsx", "Excel Files (*.xlsx)")
        if not path:
            return

        try:
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "User Points"

            headers = [self.table_points.horizontalHeaderItem(c).text() for c in range(self.table_points.columnCount())]
            ws.append(headers)
            for r in range(self.table_points.rowCount()):
                ws.append([self.table_points.item(r, c).text() if self.table_points.item(r, c) else "" for c in range(self.table_points.columnCount())])

            wb.save(path)
            QMessageBox.information(self, "Export Complete", f"Table exported to:\n{path}")
        except OSError as e:
            QMessageBox.warning(self, "Export Failed", str(e))
