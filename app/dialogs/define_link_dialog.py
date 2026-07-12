import numpy as np
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QLineEdit, QGroupBox, QGridLayout, 
                             QCheckBox, QMessageBox, QListWidget, QComboBox,
                             QTabWidget, QWidget, QRadioButton, QButtonGroup)
from PyQt6.QtCore import Qt

from core.units import UnitConverter, unit_registry

class LinkPropertyDataDialog(QDialog):
    def __init__(self, parent=None, prop_name="LINK1", prop_data=None):
        super().__init__(parent)
        self.setWindowTitle("Link/Support Property Data")
        self.setModal(True)
        self.setMinimumWidth(650)
        
        self.prop_data = prop_data if prop_data else {}
        
        self.local_units = UnitConverter()
        self.local_units.set_unit_system(unit_registry.current_unit_label)
        self.current_unit_str = self.local_units.current_unit_label
        
        main_layout = QVBoxLayout(self)
        
        unit_layout = QHBoxLayout()
        unit_layout.addWidget(QLabel("<b>Input Units:</b>"))
        self.combo_units = QComboBox()
        self.combo_units.addItems([
            "kN, m, C", "N, m, C", "kgf, m, C", 
            "kip, ft, F", "kip, in, F", "N, mm, C"
        ])
                                                       
        idx = self.combo_units.findText(self.current_unit_str)
        if idx >= 0: self.combo_units.setCurrentIndex(idx)
        self.combo_units.currentTextChanged.connect(self.on_unit_changed)
        
        unit_layout.addWidget(self.combo_units)
        unit_layout.addStretch()
        main_layout.addLayout(unit_layout)

        gen_group = QGroupBox("General")
        gen_layout = QGridLayout()
        
        self.in_name = QLineEdit(prop_name)
        self.in_mass = QLineEdit()
        self.in_weight = QLineEdit()
        self.in_r1 = QLineEdit()
        self.in_r2 = QLineEdit()
        self.in_r3 = QLineEdit()
        
        gen_layout.addWidget(QLabel("Property Name:"), 0, 0)
        gen_layout.addWidget(self.in_name, 0, 1)
        gen_layout.addWidget(QLabel("Mass:"), 1, 0)
        gen_layout.addWidget(self.in_mass, 1, 1)
        gen_layout.addWidget(QLabel("Weight:"), 2, 0)
        gen_layout.addWidget(self.in_weight, 2, 1)
        
        gen_layout.addWidget(QLabel("Rot. Inertia 1:"), 0, 2)
        gen_layout.addWidget(self.in_r1, 0, 3)
        gen_layout.addWidget(QLabel("Rot. Inertia 2:"), 1, 2)
        gen_layout.addWidget(self.in_r2, 1, 3)
        gen_layout.addWidget(QLabel("Rot. Inertia 3:"), 2, 2)
        gen_layout.addWidget(self.in_r3, 2, 3)
        
        gen_group.setLayout(gen_layout)
        main_layout.addWidget(gen_group)
        
        fix_group = QGroupBox("Directional Fixity (Fixed = Infinite Stiffness)")
        fix_layout = QHBoxLayout()
        self.dof_names = ["U1", "U2", "U3", "R1", "R2", "R3"]
        self.fix_checks = []
        
        saved_fixed = self.prop_data.get('is_fixed', [False]*6)
        for i, dof in enumerate(self.dof_names):
            chk = QCheckBox(f"{dof} Fixed")
            chk.setChecked(saved_fixed[i])
            self.fix_checks.append(chk)
            fix_layout.addWidget(chk)
            
        fix_group.setLayout(fix_layout)
        main_layout.addWidget(fix_group)
        
        self.tabs = QTabWidget()
        
        self.tab_stiffness, self.k_inputs, self.k_is_coupled = self._build_matrix_tab()
        self.tab_damping, self.c_inputs, self.c_is_coupled = self._build_matrix_tab()
        
        self.tabs.addTab(self.tab_stiffness, "Linear Stiffness")
        self.tabs.addTab(self.tab_damping, "Linear Damping")
        
        self.tabs.setTabEnabled(1, False)
        
        main_layout.addWidget(self.tabs)
        
        self._populate_ui_from_si(self.prop_data)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.btn_ok = QPushButton("OK")
        self.btn_cancel = QPushButton("Cancel")
        self.btn_ok.clicked.connect(self.accept_data)
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_ok)
        btn_layout.addWidget(self.btn_cancel)
        main_layout.addLayout(btn_layout)

    def _build_matrix_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        radio_layout = QHBoxLayout()
        rb_uncoupled = QRadioButton("Uncoupled (Diagonal Only)")
        rb_coupled = QRadioButton("Coupled (Full 6x6 Symmetric)")
        rb_uncoupled.setChecked(True)
        
        btn_group = QButtonGroup(tab)
        btn_group.addButton(rb_uncoupled)
        btn_group.addButton(rb_coupled)
        
        radio_layout.addWidget(rb_uncoupled)
        radio_layout.addWidget(rb_coupled)
        radio_layout.addStretch()
        layout.addLayout(radio_layout)
        
        grid_layout = QGridLayout()
        inputs = []
        
        for col, dof in enumerate(self.dof_names):
            lbl = QLabel(f"<b>{dof}</b>")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            grid_layout.addWidget(lbl, 0, col + 1)
            
        for r in range(6):
            grid_layout.addWidget(QLabel(f"<b>{self.dof_names[r]}</b>"), r + 1, 0)
            row_inputs = []
            for c in range(6):
                le = QLineEdit("0.0")
                le.setAlignment(Qt.AlignmentFlag.AlignRight)
                grid_layout.addWidget(le, r + 1, c + 1)
                row_inputs.append(le)
            inputs.append(row_inputs)
            
        layout.addLayout(grid_layout)
        layout.addStretch()

        for r in range(6):
            for c in range(6):
                if r < c:
                    def make_sync(row, col):
                        def sync_text(text):
                            if rb_coupled.isChecked():
                                inputs[col][row].setText(text)
                        return sync_text
                    inputs[r][c].textEdited.connect(make_sync(r, c))

        def toggle_grid():
            is_coupled = rb_coupled.isChecked()
            for r in range(6):
                for c in range(6):
                    if r == c:
                        inputs[r][c].setEnabled(True)
                    elif r < c:
                        inputs[r][c].setEnabled(is_coupled)
                        if not is_coupled:
                            inputs[r][c].setText("0.0")
                            inputs[c][r].setText("0.0")
                    else:                                            
                        inputs[r][c].setEnabled(False)
                        if not is_coupled:
                            inputs[r][c].setText("0.0")

        rb_uncoupled.toggled.connect(toggle_grid)
        rb_coupled.toggled.connect(toggle_grid)
        
        toggle_grid()
        return tab, inputs, rb_coupled

    def _scale_mass(self, val, to_display=True):
                                        
        factor = self.local_units.force_scale / self.local_units.length_scale
        return val * factor if to_display else val / factor

    def _scale_rot_inertia(self, val, to_display=True):
                                           
        factor = self.local_units.force_scale * self.local_units.length_scale
        return val * factor if to_display else val / factor
        
    def _scale_stiffness(self, val, r, c, to_display=True):
        f = self.local_units.force_scale
        l = self.local_units.length_scale
        if r < 3 and c < 3: factor = f / l                          
        elif r >= 3 and c >= 3: factor = f * l                       
        else: factor = f                                                       
        return val * factor if to_display else val / factor

    def _populate_ui_from_si(self, si_data):
        """Injects raw SI data into the UI, converting it to the active display unit."""
        self.in_mass.setText(f"{self._scale_mass(si_data.get('mass', 0.0)):.4f}")
        self.in_weight.setText(f"{self.local_units.to_display_force(si_data.get('weight', 0.0)):.4f}")
        
        self.in_r1.setText(f"{self._scale_rot_inertia(si_data.get('r1', 0.0)):.4f}")
        self.in_r2.setText(f"{self._scale_rot_inertia(si_data.get('r2', 0.0)):.4f}")
        self.in_r3.setText(f"{self._scale_rot_inertia(si_data.get('r3', 0.0)):.4f}")
        
        k_si = si_data.get('stiffness', np.zeros((6,6)))
        if np.any(k_si - np.diag(np.diagonal(k_si))):
            self.k_is_coupled.setChecked(True)
            
        for r in range(6):
            for c in range(6):
                val_disp = self._scale_stiffness(k_si[r, c], r, c)
                self.k_inputs[r][c].setText(f"{val_disp:.4g}")
                
        c_si = si_data.get('damping', np.zeros((6,6)))
        for r in range(6):
            for c in range(6):
                self.c_inputs[r][c].setText("0.0")

    def _extract_si_from_ui(self):
        """Reads the UI, converts from active display unit back to raw SI."""
        try:
            mass_disp = float(self.in_mass.text() or 0.0)
            weight_disp = float(self.in_weight.text() or 0.0)
            r1_disp = float(self.in_r1.text() or 0.0)
            r2_disp = float(self.in_r2.text() or 0.0)
            r3_disp = float(self.in_r3.text() or 0.0)
            
            si_data = {
                'mass': self._scale_mass(mass_disp, False),
                'weight': self.local_units.from_display_force(weight_disp),
                'r1': self._scale_rot_inertia(r1_disp, False),
                'r2': self._scale_rot_inertia(r2_disp, False),
                'r3': self._scale_rot_inertia(r3_disp, False),
                'is_fixed': [chk.isChecked() for chk in self.fix_checks],
                'stiffness': np.zeros((6,6)),
                'damping': np.zeros((6,6))
            }
            
            is_coupled = self.k_is_coupled.isChecked()
            for r in range(6):
                for c in range(6):
                    if is_coupled or r == c:
                        disp_k = float(self.k_inputs[r][c].text() or 0.0)
                        si_data['stiffness'][r, c] = self._scale_stiffness(disp_k, r, c, False)
                        
            if is_coupled:
                si_data['stiffness'] = (si_data['stiffness'] + si_data['stiffness'].T) / 2.0
                
            return si_data
        except ValueError:
            return None

    def on_unit_changed(self, new_unit_str):
        """Extracts current screen values as SI, switches the converter, and repopulates."""
        current_si = self._extract_si_from_ui()
        if current_si is None:
                                                                              
            idx = self.combo_units.findText(self.current_unit_str)
            self.combo_units.blockSignals(True)
            self.combo_units.setCurrentIndex(idx)
            self.combo_units.blockSignals(False)
            QMessageBox.warning(self, "Input Error", "Fix invalid numbers before changing units.")
            return

        self.local_units.set_unit_system(new_unit_str)
        self.current_unit_str = new_unit_str
        self._populate_ui_from_si(current_si)

    def accept_data(self):
        self.final_name = self.in_name.text().strip()
        if not self.final_name:
            QMessageBox.warning(self, "Error", "Property name cannot be empty.")
            return
            
        self.final_data = self._extract_si_from_ui()
        if self.final_data is None:
            QMessageBox.warning(self, "Input Error", "Please ensure all matrix and mass inputs are valid numbers.")
            return
            
        self.accept()

class LinkManagerDialog(QDialog):
    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model
        self.setWindowTitle("Define Link Properties")
        self.setMinimumSize(350, 400)
        
        layout = QHBoxLayout(self)
        
        self.list_widget = QListWidget()
        self.refresh_list()
        layout.addWidget(self.list_widget)
        
        btn_layout = QVBoxLayout()
        self.btn_add = QPushButton("Add New Property...")
        self.btn_mod = QPushButton("Modify/Show Property...")
        self.btn_del = QPushButton("Delete Property")
        
        self.btn_add.clicked.connect(self.add_prop)
        self.btn_mod.clicked.connect(self.mod_prop)
        self.btn_del.clicked.connect(self.del_prop)
        
        btn_layout.addWidget(self.btn_add)
        btn_layout.addWidget(self.btn_mod)
        btn_layout.addWidget(self.btn_del)
        btn_layout.addStretch()
        
        self.btn_ok = QPushButton("OK")
        self.btn_ok.clicked.connect(self.accept)
        btn_layout.addWidget(self.btn_ok)
        
        layout.addLayout(btn_layout)

    def refresh_list(self):
        self.list_widget.clear()
        if hasattr(self.model, 'link_properties'):
            self.list_widget.addItems(list(self.model.link_properties.keys()))

    def add_prop(self):
        idx = len(self.model.link_properties) + 1 if hasattr(self.model, 'link_properties') else 1
        dlg = LinkPropertyDataDialog(self, prop_name=f"LINK{idx}")
        if dlg.exec():
            self.model.link_properties[dlg.final_name] = dlg.final_data
            self.refresh_list()

    def mod_prop(self):
        current = self.list_widget.currentItem()
        if not current: return
        name = current.text()
        
        dlg = LinkPropertyDataDialog(self, prop_name=name, prop_data=self.model.link_properties[name])
        if dlg.exec():
            if dlg.final_name != name:
                del self.model.link_properties[name]
            self.model.link_properties[dlg.final_name] = dlg.final_data
            self.refresh_list()

    def del_prop(self):
        current = self.list_widget.currentItem()
        if not current: return
        name = current.text()
        del self.model.link_properties[name]
        self.refresh_list()
