import math
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QListWidget, QPushButton, QGroupBox, QFormLayout,
                             QLineEdit, QComboBox, QMessageBox, QColorDialog,
                             QFrame, QSizePolicy, QRadioButton, QGridLayout, QToolButton)
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtCore import Qt

from app.ui.theme import apply_dialog_style

class TendonEditorDialog(QDialog):
    """
    Open // Structures Tendon Section Editor
    Modern 2-column dashboard layout.
    """
    def __init__(self, model, tendon_data=None, parent=None):
        super().__init__(parent)
        self.model = model
        self.original_tendon = tendon_data
        
        apply_dialog_style(self)
        
        self.setWindowTitle("Define Tendon Section")
        self.setFixedWidth(600) 
        
        self.selected_color = (0.0, 1.0, 1.0, 1.0) 

        root = QVBoxLayout(self)
        root.setSpacing(12)
        root.setContentsMargins(16, 16, 16, 16)

        header_layout = QHBoxLayout()
        header_layout.addWidget(QLabel("<b>Section Name:</b>"))
        
        self.name_edit = QLineEdit("TEN1")
        self.name_edit.setFixedWidth(150)
        header_layout.addWidget(self.name_edit)
        
        header_layout.addStretch()
        
        header_layout.addWidget(QLabel("Display:"))
        self.btn_color = QPushButton()
        self.btn_color.setFixedSize(24, 24)
        self.btn_color.clicked.connect(self._pick_color)
        self._update_color_button()
        header_layout.addWidget(self.btn_color)
        
        self.btn_notes = QPushButton("Notes...")
        self.btn_notes.setFixedWidth(70)
        header_layout.addWidget(self.btn_notes)
        
        root.addLayout(header_layout)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        root.addWidget(line)

        cols_layout = QHBoxLayout()
        cols_layout.setSpacing(16)
        
        left_col = QVBoxLayout()
        left_col.setSpacing(10)
        
        mat_group = QGroupBox("Material")
        mat_layout = QFormLayout(mat_group)
        mat_layout.setVerticalSpacing(10)

        mat_row = QHBoxLayout()
        self.combo_material = QComboBox()
        self._populate_tendon_materials()
        mat_row.addWidget(self.combo_material, stretch=1)
        
        self.btn_add_mat = QToolButton()
        self.btn_add_mat.setText("+")
        self.btn_add_mat.clicked.connect(self._launch_material_manager)
        mat_row.addWidget(self.btn_add_mat)
        
        mat_layout.addRow("Material:", mat_row)
        left_col.addWidget(mat_group)
        left_col.addStretch()
        
        cols_layout.addLayout(left_col, stretch=1)

        right_col = QVBoxLayout()
        
        prop_group = QGroupBox("Section Geometry")
        prop_layout = QVBoxLayout(prop_group)
        prop_layout.setSpacing(10)

        geom_toggle_layout = QHBoxLayout()
        self.radio_dia = QRadioButton("Specify Tendon Diameter")
        self.radio_area = QRadioButton("Specify Tendon Area")
        self.radio_dia.setChecked(True)
        geom_toggle_layout.addWidget(self.radio_dia)
        geom_toggle_layout.addWidget(self.radio_area)
        prop_layout.addLayout(geom_toggle_layout)

        geom_form = QFormLayout()
        geom_form.setVerticalSpacing(8)

        def_dia = 0.0287
        def_area = 6.452e-4
        def_j = 6.625e-8
        def_i = 3.312e-8
        def_as = 5.806e-4

        from core.units import unit_registry
        self.local_scale = 1.0           
        
        if self.original_tendon:
            self.name_edit.setText(self.original_tendon.name)
            self.name_edit.setEnabled(False)                              
        
            if hasattr(self.original_tendon, 'color'):
                self.selected_color = self.original_tendon.color
                self._update_color_button()
        
            if hasattr(self.original_tendon, 'is_dia'):
                self.radio_dia.setChecked(self.original_tendon.is_dia)
                self.radio_area.setChecked(not self.original_tendon.is_dia)
        
            def_dia = getattr(self.original_tendon, 'dia', def_dia)
            def_area = getattr(self.original_tendon, 'area', def_area)
            def_j = getattr(self.original_tendon, 'J', def_j)
            def_i = getattr(self.original_tendon, 'I', def_i)
            def_as = getattr(self.original_tendon, 'As', def_as)
        
            if hasattr(self.original_tendon, 'material') and self.original_tendon.material:
                idx = self.combo_material.findText(self.original_tendon.material.name)
                if idx >= 0: self.combo_material.setCurrentIndex(idx)
        
        self.input_dia = QLineEdit(str(def_dia))
        self.input_area = QLineEdit(str(def_area))
        self.input_j = QLineEdit(str(def_j))
        self.input_i = QLineEdit(str(def_i))
        self.input_as = QLineEdit(str(def_as))

        for derived_edit in (self.input_j, self.input_i, self.input_as):
            derived_edit.setReadOnly(True)
            derived_edit.setEnabled(False)

        geom_form.addRow("Diameter:", self.input_dia)
        geom_form.addRow("Area:", self.input_area)
        geom_form.addRow("Torsional Constant:", self.input_j)
        geom_form.addRow("Moment of Inertia:", self.input_i)
        geom_form.addRow("Shear Area:", self.input_as)
        
        prop_layout.addLayout(geom_form)
        right_col.addWidget(prop_group)
        right_col.addStretch()
        
        cols_layout.addLayout(right_col, stretch=1)
        root.addLayout(cols_layout)

        self._updating_geometry = False
        self.radio_dia.toggled.connect(self._toggle_geometry_inputs)
        self.input_dia.textChanged.connect(self._on_dia_changed)
        self.input_area.textChanged.connect(self._on_area_changed)
        self._toggle_geometry_inputs()
        self._recompute_circular_properties()

        bot_layout = QHBoxLayout()
        
        self.combo_units = QComboBox()
        self.combo_units.addItems(["kN, m, C", "N, m, C", "N, mm, C", "Tonf, m, C", "kgf, m, C", "kip, ft, F", "kip, in, F"]) 
        from core.units import unit_registry
        idx = self.combo_units.findText(unit_registry.current_unit_label)
        if idx >= 0: self.combo_units.setCurrentIndex(idx)
        
        self.local_scale = 1.0                                   
        self._on_unit_changed()
        self.combo_units.currentIndexChanged.connect(self._on_unit_changed)

        bot_layout.addWidget(QLabel("Current Units:"))
        bot_layout.addWidget(self.combo_units)
        
        bot_layout.addStretch()
        
        ok_btn = QPushButton("Save Section")
        ok_btn.setObjectName("primary")                           
        ok_btn.setFixedWidth(100)
        ok_btn.clicked.connect(self._save_data) 
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("secondary")
        cancel_btn.setFixedWidth(80)
        cancel_btn.clicked.connect(self.reject)
        
        bot_layout.addWidget(ok_btn)
        bot_layout.addWidget(cancel_btn)
        root.addLayout(bot_layout)

    def _populate_tendon_materials(self):
        """Filters model.materials to only show tendons."""
        self.combo_material.clear()
        if not self.model: return
        for mat_name, mat_obj in self.model.materials.items():
            if getattr(mat_obj, 'mat_type', '').lower() == 'tendon':
                self.combo_material.addItem(mat_name)

    def _toggle_geometry_inputs(self):
        is_dia = self.radio_dia.isChecked()
        self.input_dia.setEnabled(is_dia)
        self.input_area.setEnabled(not is_dia)
        self._recompute_circular_properties()

    def _on_dia_changed(self):
        if self.radio_dia.isChecked():
            self._recompute_circular_properties()

    def _on_area_changed(self):
        if self.radio_area.isChecked():
            self._recompute_circular_properties()

    def _recompute_circular_properties(self):
        """
        Solid circular tendon section properties, derived exactly the way
        SAP2000 derives them (see 'Tendon Section Data' dialog):

            A  = pi * D^2 / 4
            I  = pi * D^4 / 64
            J  = pi * D^4 / 32   (= 2*I, polar moment of inertia)
            As = 0.9 * A         (shear correction factor for a solid
                                   circular section)

        Whichever of Diameter / Area is the active input (per the radio
        buttons) drives the calculation; the other three fields (and the
        inactive one of Diameter/Area) are recomputed and kept read-only.
        """
        if self._updating_geometry:
            return
        self._updating_geometry = True
        try:
            is_dia = self.radio_dia.isChecked()
            if is_dia:
                D = float(self.input_dia.text() or 0.0)
                if D < 0:
                    D = 0.0
                A = math.pi * D**2 / 4.0
                self.input_area.setText(f"{A:.6g}")
            else:
                A = float(self.input_area.text() or 0.0)
                if A < 0:
                    A = 0.0
                D = math.sqrt(4.0 * A / math.pi) if A > 0 else 0.0
                self.input_dia.setText(f"{D:.6g}")

            I = math.pi * D**4 / 64.0
            J = 2.0 * I
            As = 0.9 * A

            self.input_i.setText(f"{I:.6g}")
            self.input_j.setText(f"{J:.6g}")
            self.input_as.setText(f"{As:.6g}")
        except ValueError:
            pass
        finally:
            self._updating_geometry = False

    def _pick_color(self):
        r = int(self.selected_color[0] * 255)
        g = int(self.selected_color[1] * 255)
        b = int(self.selected_color[2] * 255)
        color = QColorDialog.getColor(QColor(r, g, b), self, "Select Tendon Color")
        if color.isValid():
            self.selected_color = (color.redF(), color.greenF(), color.blueF(), 1.0)
            self._update_color_button()

    def _update_color_button(self):
        r = int(self.selected_color[0] * 255)
        g = int(self.selected_color[1] * 255)
        b = int(self.selected_color[2] * 255)
                                                                                                
        self.btn_color.setStyleSheet(f"background-color: rgb({r},{g},{b}); border: 1px solid #666; border-radius: 3px;")

    def _launch_material_manager(self):
        current_mat = self.combo_material.currentText()
        from app.dialogs.material_dialog import MaterialManagerDialog
        dlg = MaterialManagerDialog(self.model, parent=self)
        dlg.exec()
        
        self._populate_tendon_materials()
        index = self.combo_material.findText(current_mat)
        if index >= 0:
            self.combo_material.setCurrentIndex(index)

    def _parse_length_scale(self, unit_str):
        parts = unit_str.replace(" ", "").split(",")
        if len(parts) > 1:
            u = parts[1]
            if u == "m": return 1.0
            if u == "mm": return 1000.0
            if u == "cm": return 100.0
            if u == "ft": return 3.28084
            if u == "in": return 39.3701
        return 1.0

    def _on_unit_changed(self):
        new_scale = self._parse_length_scale(self.combo_units.currentText())
        ratio = new_scale / self.local_scale
        self.local_scale = new_scale

        self._updating_geometry = True
        try:
            driver = self.input_dia if self.radio_dia.isChecked() else self.input_area
            power = 1 if driver is self.input_dia else 2
            try:
                val = float(driver.text()) * (ratio ** power)
                driver.setText(f"{val:.6g}")
            except ValueError:
                pass
        finally:
            self._updating_geometry = False

        self._recompute_circular_properties()

    def _save_data(self):
        try:
            name = self.name_edit.text().strip()
            if not name:
                raise ValueError("Tendon Section Name cannot be empty.")
                
            mat_name = self.combo_material.currentText()
            if not mat_name:
                raise ValueError("Please define and select a Tendon Material first.")
                
            material = self.model.materials.get(mat_name)
            if not material:
                raise ValueError("Selected material is invalid.")

            if self.original_tendon:
                self.original_tendon.material = material
                self.original_tendon.is_dia = self.radio_dia.isChecked()
                self.original_tendon.dia = float(self.input_dia.text() or 0.0) / (self.local_scale**1)
                self.original_tendon.area = float(self.input_area.text() or 0.0) / (self.local_scale**2)
                self.original_tendon.J = float(self.input_j.text() or 0.0) / (self.local_scale**4)
                self.original_tendon.I = float(self.input_i.text() or 0.0) / (self.local_scale**4)
                self.original_tendon.As = float(self.input_as.text() or 0.0) / (self.local_scale**2)
                self.original_tendon.color = self.selected_color
            else:
                from core.properties import TendonSection
                new_tendon = TendonSection(
                    name=name,
                    material=material,
                    modeling_option="Loads",                                         
                    prestress_type="Prestress",                                      
                    is_dia=self.radio_dia.isChecked(),
                    dia=float(self.input_dia.text() or 0.0) / (self.local_scale**1),
                    area=float(self.input_area.text() or 0.0) / (self.local_scale**2),
                    J=float(self.input_j.text() or 0.0) / (self.local_scale**4),
                    I=float(self.input_i.text() or 0.0) / (self.local_scale**4),
                    As=float(self.input_as.text() or 0.0) / (self.local_scale**2),
                    color=self.selected_color
                )
                self.model.add_tendon_section(new_tendon)
                
            self.accept()
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not save Tendon Section:\n{e}")
             
class TendonManagerDialog(QDialog):
    """
    Open // Structures Tendon Manager
    Modern horizontal action-bar layout.
    """
    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model
        
        apply_dialog_style(self)
        
        self.setWindowTitle("Tendon Section Manager")
        self.resize(500, 350)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        action_layout = QHBoxLayout()
        action_layout.setSpacing(8)
        
        self.btn_add = QPushButton(" + Add New")
        self.btn_copy = QPushButton("Copy")
        self.btn_mod = QPushButton("Modify / Show")
        self.btn_del = QPushButton("Delete")
        
        self.btn_del.setObjectName("danger")

        self.btn_add.clicked.connect(self._launch_editor)
        self.btn_mod.clicked.connect(self._launch_editor)
        self.btn_del.clicked.connect(self._delete_section)

        action_layout.addWidget(self.btn_add)
        action_layout.addWidget(self.btn_copy)
        action_layout.addWidget(self.btn_mod)
        action_layout.addStretch()
        action_layout.addWidget(self.btn_del)
        
        root.addLayout(action_layout)

        self.list_widget = QListWidget()
        self.list_widget.setAlternatingRowColors(True) 
        root.addWidget(self.list_widget)

        bottom_layout = QHBoxLayout()
        bottom_layout.addStretch()
        ok_btn = QPushButton("Done")
        ok_btn.setObjectName("primary")                         
        ok_btn.setFixedWidth(90)
        ok_btn.clicked.connect(self.accept)
        
        bottom_layout.addWidget(ok_btn)
        root.addLayout(bottom_layout)

        self.refresh_list()

    def refresh_list(self):
        self.list_widget.clear()
        if self.model and hasattr(self.model, 'tendon_sections'):
            for name in self.model.tendon_sections.keys():
                self.list_widget.addItem(name)

    def _launch_editor(self):
        tendon_data = None
                                                                    
        if self.sender() == self.btn_mod:
            items = self.list_widget.selectedItems()
            if not items: return
            name = items[0].text()
            tendon_data = getattr(self.model, 'tendon_sections', {}).get(name)
            
        dlg = TendonEditorDialog(self.model, tendon_data=tendon_data, parent=self)
        if dlg.exec():
            self.refresh_list()
                                                                             
            if hasattr(self.parent(), 'draw_both_canvases'):
                self.parent().draw_both_canvases()
            
    def _delete_section(self):
        items = self.list_widget.selectedItems()
        if not items: return
        name = items[0].text()
        
        if QMessageBox.question(self, "Delete Tendon", f"Delete tendon section '{name}'?") == QMessageBox.StandardButton.Yes:
            del self.model.tendon_sections[name]
            self.refresh_list()
