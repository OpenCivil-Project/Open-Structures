import math
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QListWidget, QPushButton, QGroupBox, QFormLayout,
                             QLineEdit, QComboBox, QMessageBox, QColorDialog,
                             QFrame, QSizePolicy, QRadioButton, QGridLayout, QToolButton)
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtCore import Qt

from app.ui.theme import apply_dialog_style

class CableEditorDialog(QDialog):
    """
    Open // Structures Cable Section Editor
    Matches SAP2000 Cable Section Data Dialog.
    """
    def __init__(self, model, cable_data=None, parent=None):
        super().__init__(parent)
        self.model = model
        self.original_cable = cable_data
        
        apply_dialog_style(self)
        
        self.setWindowTitle("Cable Section Data")
        self.setFixedWidth(500) 
        
        self.selected_color = (1.0, 0.0, 0.0, 1.0)                     
        self.local_scale = 1.0

        root = QVBoxLayout(self)
        root.setSpacing(12)
        root.setContentsMargins(16, 16, 16, 16)

        header_layout = QHBoxLayout()
        header_layout.addWidget(QLabel("<b>Cable Section Name:</b>"))
        
        self.name_edit = QLineEdit("CAB1")
        self.name_edit.setFixedWidth(150)
        header_layout.addWidget(self.name_edit)
        
        header_layout.addStretch()
        
        self.btn_notes = QPushButton("Modify/Show Notes...")
        header_layout.addWidget(self.btn_notes)
        root.addLayout(header_layout)

        mat_group = QGroupBox("Cable Material")
        mat_layout = QHBoxLayout(mat_group)
        
        mat_layout.addWidget(QLabel("Material Property"))
        self.btn_add_mat = QToolButton()
        self.btn_add_mat.setText("+")
        self.btn_add_mat.clicked.connect(self._launch_material_manager)
        mat_layout.addWidget(self.btn_add_mat)
        
        self.combo_material = QComboBox()
        self._populate_cable_materials()
        mat_layout.addWidget(self.combo_material, stretch=1)
        
        root.addWidget(mat_group)

        prop_group = QGroupBox("Cable Properties")
        prop_layout = QVBoxLayout(prop_group)
        prop_layout.setSpacing(10)

        geom_form = QFormLayout()
        geom_form.setVerticalSpacing(8)

        self.radio_dia = QRadioButton("Specify Cable Diameter")
        self.radio_area = QRadioButton("Specify Cable Area")
        self.radio_area.setChecked(True)                                        

        def_dia = 0.0287
        def_area = 6.452e-4
        def_j = 6.625e-8
        def_i = 3.312e-8
        def_as = 5.806e-4
        
        if self.original_cable:
            self.name_edit.setText(self.original_cable.name)
            self.name_edit.setEnabled(False)                        
        
            if hasattr(self.original_cable, 'color'):
                self.selected_color = self.original_cable.color
        
            if hasattr(self.original_cable, 'is_dia'):
                self.radio_dia.setChecked(self.original_cable.is_dia)
                self.radio_area.setChecked(not self.original_cable.is_dia)
        
            def_dia = getattr(self.original_cable, 'dia', def_dia)
            def_area = getattr(self.original_cable, 'area', def_area)
            def_j = getattr(self.original_cable, 'J', def_j)
            def_i = getattr(self.original_cable, 'I', def_i)
            def_as = getattr(self.original_cable, 'As', def_as)
        
            if hasattr(self.original_cable, 'material') and self.original_cable.material:
                idx = self.combo_material.findText(self.original_cable.material.name)
                if idx >= 0: self.combo_material.setCurrentIndex(idx)

        self.input_dia = QLineEdit(str(def_dia))
        self.input_area = QLineEdit(str(def_area))
        self.input_j = QLineEdit(str(def_j))
        self.input_i = QLineEdit(str(def_i))
        self.input_as = QLineEdit(str(def_as))

        for derived_edit in (self.input_j, self.input_i, self.input_as):
            derived_edit.setReadOnly(True)
            derived_edit.setEnabled(False)

        geom_form.addRow(self.radio_dia, self.input_dia)
        geom_form.addRow(self.radio_area, self.input_area)
        geom_form.addRow("Torsional Constant:", self.input_j)
        geom_form.addRow("Moment of Inertia:", self.input_i)
        geom_form.addRow("Shear Area:", self.input_as)
        
        prop_layout.addLayout(geom_form)
        
        self.btn_modifiers = QPushButton("Modify/Show Cable Property Modifiers...")
        self.btn_modifiers.clicked.connect(self._show_modifiers_dialog)
        prop_layout.addWidget(self.btn_modifiers)
        
        root.addWidget(prop_group)

        self._updating_geometry = False
        self.radio_dia.toggled.connect(self._toggle_geometry_inputs)
        self.input_dia.textChanged.connect(self._on_dia_changed)
        self.input_area.textChanged.connect(self._on_area_changed)
        self._toggle_geometry_inputs()
        self._recompute_circular_properties()

        bot_layout = QHBoxLayout()
        
        unit_layout = QVBoxLayout()
        unit_layout.addWidget(QLabel("Units"))
        self.combo_units = QComboBox()
        self.combo_units.addItems(["kN, m, C", "N, m, C", "N, mm, C", "Tonf, m, C", "kgf, m, C", "kip, ft, F", "kip, in, F"]) 
        from core.units import unit_registry
        idx = self.combo_units.findText(unit_registry.current_unit_label)
        if idx >= 0: self.combo_units.setCurrentIndex(idx)
        self._on_unit_changed()
        self.combo_units.currentIndexChanged.connect(self._on_unit_changed)
        unit_layout.addWidget(self.combo_units)
        bot_layout.addLayout(unit_layout)
        
        bot_layout.addStretch()
        
        color_layout = QHBoxLayout()
        color_layout.addWidget(QLabel("Display Color"))
        self.btn_color = QPushButton()
        self.btn_color.setFixedSize(24, 24)
        self.btn_color.clicked.connect(self._pick_color)
        self._update_color_button()
        color_layout.addWidget(self.btn_color)
        bot_layout.addLayout(color_layout)

        root.addLayout(bot_layout)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        ok_btn = QPushButton("OK")
        ok_btn.setObjectName("primary")
        ok_btn.setFixedWidth(100)
        ok_btn.clicked.connect(self._save_data) 
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("secondary")
        cancel_btn.setFixedWidth(80)
        cancel_btn.clicked.connect(self.reject)
        
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        root.addLayout(btn_layout)

    def _populate_cable_materials(self):
        """Filters model.materials."""
        self.combo_material.clear()
        if not self.model: return
        for mat_name, mat_obj in self.model.materials.items():
            self.combo_material.addItem(mat_name)

    def _toggle_geometry_inputs(self):
        is_dia = self.radio_dia.isChecked()
        self.input_dia.setEnabled(is_dia)
        self.input_area.setEnabled(not is_dia)
        self._recompute_circular_properties()

    def _on_dia_changed(self):
        if self.radio_dia.isChecked(): self._recompute_circular_properties()

    def _on_area_changed(self):
        if self.radio_area.isChecked(): self._recompute_circular_properties()

    def _recompute_circular_properties(self):
        if self._updating_geometry: return
        self._updating_geometry = True
        try:
            if self.radio_dia.isChecked():
                D = float(self.input_dia.text() or 0.0)
                if D < 0: D = 0.0
                A = math.pi * D**2 / 4.0
                self.input_area.setText(f"{A:.6g}")
            else:
                A = float(self.input_area.text() or 0.0)
                if A < 0: A = 0.0
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
        r, g, b = [int(c * 255) for c in self.selected_color[:3]]
        color = QColorDialog.getColor(QColor(r, g, b), self, "Select Cable Color")
        if color.isValid():
            self.selected_color = (color.redF(), color.greenF(), color.blueF(), 1.0)
            self._update_color_button()

    def _update_color_button(self):
        r, g, b = [int(c * 255) for c in self.selected_color[:3]]
        self.btn_color.setStyleSheet(f"background-color: rgb({r},{g},{b}); border: 1px solid #666; border-radius: 3px;")

    def _launch_material_manager(self):
        current_mat = self.combo_material.currentText()
        from app.dialogs.material_dialog import MaterialManagerDialog
        dlg = MaterialManagerDialog(self.model, parent=self)
        dlg.exec()
        self._populate_cable_materials()
        index = self.combo_material.findText(current_mat)
        if index >= 0: self.combo_material.setCurrentIndex(index)

    def _show_modifiers_dialog(self):
        QMessageBox.information(self, "Modifiers", "Stiffness Modifier dialog placeholder. Connecting later!")

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
            if not name: raise ValueError("Cable Section Name cannot be empty.")
                
            mat_name = self.combo_material.currentText()
            if not mat_name: raise ValueError("Please define and select a Material first.")
                
            material = self.model.materials.get(mat_name)
            if not material: raise ValueError("Selected material is invalid.")

            if self.original_cable:
                self.original_cable.material = material
                self.original_cable.is_dia = self.radio_dia.isChecked()
                self.original_cable.dia = float(self.input_dia.text() or 0.0) / (self.local_scale**1)
                self.original_cable.area = float(self.input_area.text() or 0.0) / (self.local_scale**2)
                self.original_cable.J = float(self.input_j.text() or 0.0) / (self.local_scale**4)
                self.original_cable.I = float(self.input_i.text() or 0.0) / (self.local_scale**4)
                self.original_cable.As = float(self.input_as.text() or 0.0) / (self.local_scale**2)
                self.original_cable.color = self.selected_color
            else:
                from core.properties import CableSection                            
                new_cable = CableSection(
                    name=name,
                    material=material,
                    is_dia=self.radio_dia.isChecked(),
                    dia=float(self.input_dia.text() or 0.0) / (self.local_scale**1),
                    area=float(self.input_area.text() or 0.0) / (self.local_scale**2),
                    J=float(self.input_j.text() or 0.0) / (self.local_scale**4),
                    I=float(self.input_i.text() or 0.0) / (self.local_scale**4),
                    As=float(self.input_as.text() or 0.0) / (self.local_scale**2),
                    color=self.selected_color
                )
                                                                                 
                if not hasattr(self.model, 'cable_sections'):
                    self.model.cable_sections = {}
                self.model.cable_sections[name] = new_cable
                
            self.accept()
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not save Cable Section:\n{e}")

class CableManagerDialog(QDialog):
    """
    Open // Structures Cable Manager
    Matches SAP2000 Cable Sections Dialog.
    """
    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model
        
        apply_dialog_style(self)
        
        self.setWindowTitle("Cable Sections")
        self.resize(400, 300)

        root = QHBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        list_group = QGroupBox("Sections")
        list_layout = QVBoxLayout(list_group)
        self.list_widget = QListWidget()
        self.list_widget.setAlternatingRowColors(True) 
        list_layout.addWidget(self.list_widget)
        root.addWidget(list_group, stretch=1)

        btn_group = QGroupBox("Click to:")
        btn_layout = QVBoxLayout(btn_group)
        btn_layout.setSpacing(8)
        
        self.btn_add = QPushButton("Add New Section...")
        self.btn_copy = QPushButton("Add Copy of Section...")
        self.btn_mod = QPushButton("Modify/Show Section...")
        self.btn_del = QPushButton("Delete Section")

        self.btn_add.clicked.connect(self._launch_editor)
        self.btn_mod.clicked.connect(self._launch_editor)
        self.btn_del.clicked.connect(self._delete_section)

        btn_layout.addWidget(self.btn_add)
        btn_layout.addWidget(self.btn_copy)
        btn_layout.addWidget(self.btn_mod)
        btn_layout.addWidget(self.btn_del)
        btn_layout.addStretch()

        ok_btn = QPushButton("OK")
        ok_btn.setObjectName("primary")
        ok_btn.clicked.connect(self.accept)
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("secondary")
        cancel_btn.clicked.connect(self.reject)
        
        bot_btns = QHBoxLayout()
        bot_btns.addStretch()
        bot_btns.addWidget(ok_btn)
        bot_btns.addWidget(cancel_btn)
        
        btn_layout.addLayout(bot_btns)
        
        root.addWidget(btn_group)

        self.refresh_list()

    def refresh_list(self):
        self.list_widget.clear()
        if self.model and hasattr(self.model, 'cable_sections'):
            for name in self.model.cable_sections.keys():
                self.list_widget.addItem(name)

    def _launch_editor(self):
        cable_data = None
        if self.sender() == self.btn_mod:
            items = self.list_widget.selectedItems()
            if not items: return
            name = items[0].text()
            cable_data = getattr(self.model, 'cable_sections', {}).get(name)
            
        dlg = CableEditorDialog(self.model, cable_data=cable_data, parent=self)
        if dlg.exec():
            self.refresh_list()
            if hasattr(self.parent(), 'draw_both_canvases'):
                self.parent().draw_both_canvases()
            
    def _delete_section(self):
        items = self.list_widget.selectedItems()
        if not items: return
        name = items[0].text()
        
        if QMessageBox.question(self, "Delete Cable", f"Delete cable section '{name}'?") == QMessageBox.StandardButton.Yes:
            del self.model.cable_sections[name]
            self.refresh_list()
