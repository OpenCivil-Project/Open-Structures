from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QTableWidget, QTableWidgetItem, QPushButton,
                             QLineEdit, QRadioButton, QHeaderView, QMessageBox,
                             QGroupBox, QComboBox)
from PyQt6.QtCore import Qt
from core.units import unit_registry 
                                                             
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

class UserSeismicDialog(QDialog):
    def __init__(self, load_pattern, model, parent=None):
        super().__init__(parent)
        self.load_pattern = load_pattern
        self.model = model
        self.setWindowTitle(f"User Seismic Load Pattern - {load_pattern.name}")
        self.resize(750, 500)

        if not hasattr(self.load_pattern, 'seismic_data') or not self.load_pattern.seismic_data:
            from core.model import UserSeismicData                                            
            self.load_pattern.seismic_data = UserSeismicData()
            
        self.seismic_data = self.load_pattern.seismic_data

        self._f_scale = FORCE_SCALES.get(unit_registry.force_unit_name, 1/1_000.0)
        self._l_scale = LENGTH_SCALES.get(unit_registry.length_unit_name, 1.0)

        layout = QVBoxLayout(self)

        unit_group = QGroupBox("Input Units (Dialog Local)")
        unit_layout = QHBoxLayout(unit_group)
        
        unit_layout.addWidget(QLabel("Force:"))
        self.combo_force = QComboBox()
        self.combo_force.addItems(list(FORCE_SCALES.keys()))
        self.combo_force.setCurrentText(unit_registry.force_unit_name)
        unit_layout.addWidget(self.combo_force)

        unit_layout.addSpacing(15)

        unit_layout.addWidget(QLabel("Length:"))
        self.combo_length = QComboBox()
        self.combo_length.addItems(list(LENGTH_SCALES.keys()))
        self.combo_length.setCurrentText(unit_registry.length_unit_name)
        unit_layout.addWidget(self.combo_length)
        
        unit_layout.addStretch()
        layout.addWidget(unit_group)

        table_label = QLabel("User Seismic Loads on Diaphragms")
        table_label.setStyleSheet("font-weight: bold; color: #0055A4;")
        layout.addWidget(table_label)

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)

        bottom_layout = QHBoxLayout()
        
        radio_layout = QVBoxLayout()
        self.rb_user = QRadioButton("User Specified Application Point")
        self.rb_user.setEnabled(False)                         
        self.rb_com = QRadioButton("Apply at Center of Mass")
        self.rb_com.setChecked(True)
        radio_layout.addWidget(self.rb_user)
        radio_layout.addWidget(self.rb_com)
        bottom_layout.addLayout(radio_layout)

        ecc_layout = QHBoxLayout()
        ecc_layout.addWidget(QLabel("Additional Ecc. Ratio (all Diaph.):"))
        self.input_ecc = QLineEdit(str(self.seismic_data.eccentricity))
        self.input_ecc.setFixedWidth(60)
        ecc_layout.addWidget(self.input_ecc)
        ecc_layout.addStretch()
        bottom_layout.addLayout(ecc_layout)

        layout.addLayout(bottom_layout)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_ok = QPushButton("OK")
        btn_ok.setObjectName("primary")
        btn_ok.setFixedWidth(100)
        btn_ok.clicked.connect(self.save_and_accept)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_ok)
        btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)

        self.combo_force.currentTextChanged.connect(self._on_unit_changed)
        self.combo_length.currentTextChanged.connect(self._on_unit_changed)
        
        self.update_headers()
        self.populate_table()

    def update_headers(self):
        """Updates the table headers to show the current active units."""
        f_unit = self.combo_force.currentText()
        l_unit = self.combo_length.currentText()
        headers = ["Diaphragm", f"FX ({f_unit})", f"FY ({f_unit})", f"MZ ({f_unit}-{l_unit})"]
        self.table.setHorizontalHeaderLabels(headers)

    def populate_table(self):
        """Cleanly lists only relevant or 'Ghost' load entries."""
                                                                       
        active_diaphs = set()
        for node in self.model.nodes.values():
            d_name = getattr(node, 'diaphragm_name', None)
            if d_name: active_diaphs.add(d_name)
        
        defined_diaphs = set(self.model.constraints.keys())
        saved_force_diaphs = set(self.seismic_data.diaphragm_loads.keys())
        all_relevant = sorted(list(defined_diaphs.union(saved_force_diaphs)))

        rows_to_add = []
        for dia_name in all_relevant:
            loads = self.seismic_data.diaphragm_loads.get(dia_name, {"Fx": 0.0, "Fy": 0.0, "Mz": 0.0})
            has_force = any(abs(v) > 1e-9 for v in loads.values())
            is_deleted = dia_name not in defined_diaphs
            is_unassigned = dia_name not in active_diaphs

            if not has_force and (is_deleted or is_unassigned):
                continue
                
            rows_to_add.append((dia_name, loads, is_deleted, is_unassigned))

        self.table.setRowCount(len(rows_to_add))
        
        for row, (dia_name, loads, is_deleted, is_unassigned) in enumerate(rows_to_add):
                                              
            label = dia_name
            if is_deleted: label += " (DELETED)"
            elif is_unassigned: label += " (UNASSIGNED)"
            
            item_name = QTableWidgetItem(label)
            item_name.setFlags(item_name.flags() & ~Qt.ItemFlag.ItemIsEditable)
            
            if is_deleted or is_unassigned:
                from PyQt6.QtGui import QColor, QBrush
                item_name.setForeground(QBrush(QColor("red")))
                item_name.setToolTip("Warning: Force applied to a Diaphragm that is not active or deleted.")
                                                        
                for col in range(4):
                    self.table.setItem(row, col, QTableWidgetItem(""))              
                    self.table.item(row, col).setBackground(QBrush(QColor(255, 230, 230)))
            
            self.table.setItem(row, 0, item_name)

            fx_disp = loads["Fx"] * self._f_scale
            fy_disp = loads["Fy"] * self._f_scale
            mz_disp = loads["Mz"] * (self._f_scale * self._l_scale)

            self.table.setItem(row, 1, QTableWidgetItem(f"{fx_disp:.4g}"))
            self.table.setItem(row, 2, QTableWidgetItem(f"{fy_disp:.4g}"))
            self.table.setItem(row, 3, QTableWidgetItem(f"{mz_disp:.4g}"))
            
    def _on_unit_changed(self):
        """Live-updates the table values when the user toggles a dropdown."""
        old_f_scale = self._f_scale
        old_l_scale = self._l_scale

        self._f_scale = FORCE_SCALES[self.combo_force.currentText()]
        self._l_scale = LENGTH_SCALES[self.combo_length.currentText()]

        self.update_headers()

        for row in range(self.table.rowCount()):
            try:
                fx_val = float(self.table.item(row, 1).text() or 0)
                fy_val = float(self.table.item(row, 2).text() or 0)
                mz_val = float(self.table.item(row, 3).text() or 0)

                fx_si = fx_val / old_f_scale
                fy_si = fy_val / old_f_scale
                mz_si = mz_val / (old_f_scale * old_l_scale)

                new_fx = fx_si * self._f_scale
                new_fy = fy_si * self._f_scale
                new_mz = mz_si * (self._f_scale * self._l_scale)

                self.table.item(row, 1).setText(f"{new_fx:.4g}")
                self.table.item(row, 2).setText(f"{new_fy:.4g}")
                self.table.item(row, 3).setText(f"{new_mz:.4g}")
            except ValueError:
                pass                                               

    def save_and_accept(self):
        """Reads local display units, converts back to SI, and saves to model."""
        try:
            self.seismic_data.eccentricity = float(self.input_ecc.text())
        except ValueError:
            QMessageBox.warning(self, "Error", "Eccentricity ratio must be a number.")
            return

        self.seismic_data.diaphragm_loads.clear()
        
        for row in range(self.table.rowCount()):
            dia_name = self.table.item(row, 0).text()
            try:
                fx_disp = float(self.table.item(row, 1).text() or 0)
                fy_disp = float(self.table.item(row, 2).text() or 0)
                mz_disp = float(self.table.item(row, 3).text() or 0)

                fx_si = fx_disp / self._f_scale
                fy_si = fy_disp / self._f_scale
                mz_si = mz_disp / (self._f_scale * self._l_scale)

                if fx_si != 0 or fy_si != 0 or mz_si != 0:
                    self.seismic_data.diaphragm_loads[dia_name] = {"Fx": fx_si, "Fy": fy_si, "Mz": mz_si}
                    
            except ValueError:
                QMessageBox.warning(self, "Error", f"Invalid numeric entry in row {row + 1}")
                return

        self.accept()
