from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QListWidget,
                             QPushButton, QLabel, QComboBox, QTableWidget,
                             QTableWidgetItem, QGroupBox, QSpinBox, QCheckBox,
                             QMessageBox, QHeaderView, QLineEdit, QWidget,
                             QRadioButton, QButtonGroup, QFileDialog)
from PyQt6.QtCore import Qt
from core.model import LoadCase

from app.ui.theme import apply_dialog_style                      

class LoadCaseDetailDialog(QDialog):
    """The 'Modify/Show' window for a single load case."""
    def __init__(self, model, case, parent=None, is_new=False):
        super().__init__(parent)
        self.model = model

        if isinstance(case, dict):
            from core.model import LoadCase
            name  = case.get("name", "Unknown")
            c_type = case.get("type", "Linear Static")
            real_case = LoadCase(name, c_type)
            if c_type == "Response Spectrum":
                func      = case.get("function", "FUNC1")
                direction = case.get("direction", "X")
                dir_map   = {"X": "U1", "Y": "U2", "Z": "U3"}
                u_dir     = dir_map.get(direction, "U1")
                real_case.rsa_loads = [(u_dir, func, 9.81)]
            self.case = real_case
        else:
            self.case = case

        self.original_name = self.case.name
        self.is_new        = is_new

        self.setWindowTitle("Load Case Data - " + self.case.case_type)
        self.resize(700, 550)

        apply_dialog_style(self)                                                

        layout = QVBoxLayout(self)

        grp_top = QGroupBox("General")
        h_top   = QHBoxLayout(grp_top)

        h_top.addWidget(QLabel("Load Case Name:"))
        self.input_name = QLineEdit(self.case.name)
                                                                                          
        self.input_name.setStyleSheet("font-weight: bold; font-size: 11pt;")
        h_top.addWidget(self.input_name)

        h_top.addSpacing(20)

        h_top.addWidget(QLabel("Load Case Type:"))
        self.combo_type = QComboBox()
        self.combo_type.addItems(["Linear Static", "Modal", "Response Spectrum", "LTHA", "Buckling"])
        self.combo_type.setCurrentText(self.case.case_type)
        self.combo_type.currentTextChanged.connect(self.on_type_changed)
        h_top.addWidget(self.combo_type)

        layout.addWidget(grp_top)

        self.grp_stiffness = QGroupBox("Stiffness to Use")
        v_stiff = QVBoxLayout(self.grp_stiffness)
        self.radio_zero     = QRadioButton("Zero Initial Conditions - Unstressed State")
        self.radio_continue = QRadioButton("Stiffness at End of Nonlinear Case")
        self.radio_zero.setChecked(True)
        self.radio_continue.setEnabled(False)
        v_stiff.addWidget(self.radio_zero)
        v_stiff.addWidget(self.radio_continue)
        layout.addWidget(self.grp_stiffness)

        self.group_loads = QGroupBox("Loads Applied")
        v_loads = QVBoxLayout(self.group_loads)

        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["Load Pattern", "Scale Factor"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        v_loads.addWidget(self.table)

        h_tbl_btns = QHBoxLayout()
        self.btn_add_row = QPushButton("Add")
        self.btn_add_row.clicked.connect(self.add_load_row)
        self.btn_del_row = QPushButton("Delete")
        self.btn_del_row.setObjectName("danger")                             
        self.btn_del_row.clicked.connect(self.delete_load_row)
        h_tbl_btns.addStretch()
        h_tbl_btns.addWidget(self.btn_add_row)
        h_tbl_btns.addWidget(self.btn_del_row)
        v_loads.addLayout(h_tbl_btns)

        layout.addWidget(self.group_loads)

        self.group_modal = QGroupBox("Modal Analysis Parameters")
        h_modal_main = QHBoxLayout(self.group_modal)

        v_mod_left = QVBoxLayout()
        grp_method = QGroupBox("Type of Modes")
        v_method   = QVBoxLayout(grp_method)
        self.radio_eigen = QRadioButton("Eigen Vectors")
        self.radio_ritz  = QRadioButton("Ritz Vectors")
        self.radio_eigen.setChecked(True)
        v_method.addWidget(self.radio_eigen)
        v_method.addWidget(self.radio_ritz)
        v_mod_left.addWidget(grp_method)
        v_mod_left.addStretch()
        h_modal_main.addLayout(v_mod_left)

        v_mod_right = QVBoxLayout()
        grp_num = QGroupBox("Number of Modes")
        f_num   = QVBoxLayout(grp_num)
        h_max   = QHBoxLayout()
        h_max.addWidget(QLabel("Maximum Number of Modes:"))
        self.spin_max_modes = QSpinBox()
        self.spin_max_modes.setRange(1, 999)
        self.spin_max_modes.setValue(getattr(self.case, 'num_modes', 12))
        h_max.addWidget(self.spin_max_modes)
        f_num.addLayout(h_max)
        h_min = QHBoxLayout()
        h_min.addWidget(QLabel("Minimum Number of Modes:"))
        self.spin_min_modes = QSpinBox()
        self.spin_min_modes.setRange(1, 999)
        self.spin_min_modes.setValue(getattr(self.case, 'min_modes', 1))
        h_min.addWidget(self.spin_min_modes)
        f_num.addLayout(h_min)
        v_mod_right.addWidget(grp_num)

        grp_mass = QGroupBox("Mass Source")
        v_mass   = QVBoxLayout(grp_mass)
        self.combo_mass = QComboBox()
        if hasattr(self.model, 'mass_sources'):
            self.combo_mass.addItems(self.model.mass_sources.keys())
        else:
            self.combo_mass.addItem("MSSSRC1")
        self.combo_mass.setCurrentText(getattr(self.case, 'mass_source', 'MSSSRC1'))
        v_mass.addWidget(self.combo_mass)
        v_mod_right.addWidget(grp_mass)
        h_modal_main.addLayout(v_mod_right)
        layout.addWidget(self.group_modal)

        self.group_rsa = QGroupBox("Response Spectrum Parameters")
        layout_rsa = QVBoxLayout(self.group_rsa)

        h_rsa_top = QHBoxLayout()

        grp_comb = QGroupBox("Modal Combination")
        v_comb   = QVBoxLayout(grp_comb)
        self.radio_cqc  = QRadioButton("CQC")
        self.radio_srss = QRadioButton("SRSS")
        self.radio_cqc.setChecked(True)
        v_comb.addWidget(self.radio_cqc)
        v_comb.addWidget(self.radio_srss)
        h_rsa_top.addWidget(grp_comb)

        grp_dir = QGroupBox("Directional Combination")
        v_dir   = QVBoxLayout(grp_dir)
        self.radio_dir_srss = QRadioButton("SRSS")
        self.radio_dir_abs  = QRadioButton("Absolute")
        self.radio_dir_srss.setChecked(True)
        v_dir.addWidget(self.radio_dir_srss)
        v_dir.addWidget(self.radio_dir_abs)
        h_rsa_top.addWidget(grp_dir)
        layout_rsa.addLayout(h_rsa_top)

        grp_rsa_loads = QGroupBox("Loads Applied")
        v_rsa_loads   = QVBoxLayout(grp_rsa_loads)

        self.table_rsa = QTableWidget()
        self.table_rsa.setColumnCount(3)
        self.table_rsa.setHorizontalHeaderLabels(["Load Name", "Function", "Scale Factor"])
        self.table_rsa.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        v_rsa_loads.addWidget(self.table_rsa)

        h_rsa_btns = QHBoxLayout()
        self.btn_rsa_preview = QPushButton("Preview Spectrum")
        self.btn_rsa_preview.clicked.connect(self.preview_spectrum)
        self.btn_rsa_add = QPushButton("Add")
        self.btn_rsa_add.clicked.connect(self.add_rsa_row)
        self.btn_rsa_del = QPushButton("Delete")
        self.btn_rsa_del.setObjectName("danger")                      
        self.btn_rsa_del.clicked.connect(self.delete_rsa_row)
        h_rsa_btns.addWidget(self.btn_rsa_preview)
        h_rsa_btns.addStretch()
        h_rsa_btns.addWidget(self.btn_rsa_add)
        h_rsa_btns.addWidget(self.btn_rsa_del)
        v_rsa_loads.addLayout(h_rsa_btns)

        layout_rsa.addWidget(grp_rsa_loads)
        layout.addWidget(self.group_rsa)

        self.group_buckling = QGroupBox("Buckling Parameters")
        v_buck = QVBoxLayout(self.group_buckling)

        h_buck_modes = QHBoxLayout()
        h_buck_modes.addWidget(QLabel("Number of Buckling Modes:"))
        self.spin_buck_modes = QSpinBox()
        self.spin_buck_modes.setRange(1, 999)
        self.spin_buck_modes.setValue(getattr(self.case, 'num_modes', 6))
        h_buck_modes.addWidget(self.spin_buck_modes)
        h_buck_modes.addStretch()
        v_buck.addLayout(h_buck_modes)

        h_buck_tol = QHBoxLayout()
        h_buck_tol.addWidget(QLabel("Eigenvalue Convergence Tolerance:"))
        tol_val = getattr(self.case, 'eigen_tol', 1e-9)
        self.input_buck_tol = QLineEdit(f"{tol_val:.3E}")
        self.input_buck_tol.setFixedWidth(100)
        h_buck_tol.addWidget(self.input_buck_tol)
        h_buck_tol.addStretch()
        v_buck.addLayout(h_buck_tol)

        h_buck_mass = QHBoxLayout()
        h_buck_mass.addWidget(QLabel("Mass Source:"))
        self.combo_buck_mass = QComboBox()
        if hasattr(self.model, 'mass_sources') and self.model.mass_sources:
            self.combo_buck_mass.addItems(self.model.mass_sources.keys())
        else:
            self.combo_buck_mass.addItem("MSSSRC1")
        self.combo_buck_mass.setCurrentText(getattr(self.case, 'mass_source', 'MSSSRC1'))
        h_buck_mass.addWidget(self.combo_buck_mass)
        h_buck_mass.addStretch()
        v_buck.addLayout(h_buck_mass)

        layout.addWidget(self.group_buckling)

        self.group_ltha = QGroupBox("Linear Time History Parameters")
        v_ltha = QVBoxLayout(self.group_ltha)

        h_ltha_opts = QHBoxLayout()
        h_ltha_opts.addWidget(QLabel("Damping Ratio:"))
        self.input_ltha_damping = QLineEdit()
        self.input_ltha_damping.setText(str(getattr(self.case, 'damping', 0.05)))
        self.input_ltha_damping.setFixedWidth(70)
        h_ltha_opts.addWidget(self.input_ltha_damping)
        h_ltha_opts.addStretch()
        v_ltha.addLayout(h_ltha_opts)

        self.table_ltha = QTableWidget()
        self.table_ltha.setColumnCount(3)
        self.table_ltha.setHorizontalHeaderLabels(["Direction", "Function", "Scale Factor"])
        self.table_ltha.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table_ltha.setMaximumHeight(160)
        v_ltha.addWidget(self.table_ltha)

        h_ltha_btns = QHBoxLayout()
        self.btn_ltha_add = QPushButton("Add")
        self.btn_ltha_add.clicked.connect(self.add_ltha_row)
        self.btn_ltha_del = QPushButton("Delete")
        self.btn_ltha_del.setObjectName("danger")                     
        self.btn_ltha_del.clicked.connect(self.delete_ltha_row)
        h_ltha_btns.addStretch()
        h_ltha_btns.addWidget(self.btn_ltha_add)
        h_ltha_btns.addWidget(self.btn_ltha_del)
        v_ltha.addLayout(h_ltha_btns)

        layout.addWidget(self.group_ltha)

        self.group_settings = QGroupBox("Extra Settings")
        v_set = QVBoxLayout(self.group_settings)

        self.chk_pdelta = QCheckBox("Geometric Nonlinearity (P-Delta)")
        self.chk_pdelta.setChecked(self.case.p_delta)
        v_set.addWidget(self.chk_pdelta)

        h_damp = QHBoxLayout()
        self.lbl_damp    = QLabel("Constant Modal Damping:")
        self.input_damping = QLineEdit()
        self.input_damping.setText(str(getattr(self.case, 'modal_damping', 0.05)))
        self.input_damping.setPlaceholderText("e.g. 0.05")
        h_damp.addWidget(self.lbl_damp)
        h_damp.addWidget(self.input_damping)
        v_set.addLayout(h_damp)

        layout.addWidget(self.group_settings)

        h_btns = QHBoxLayout()
        h_btns.addStretch()
        btn_ok = QPushButton("OK")
        btn_ok.setFixedWidth(100)
        btn_ok.setObjectName("primary")                              
        btn_ok.clicked.connect(self.on_ok)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.setFixedWidth(100)
                                                 
        btn_cancel.clicked.connect(self.reject)
        h_btns.addWidget(btn_ok)
        h_btns.addWidget(btn_cancel)
        layout.addLayout(h_btns)

        self.populate_loads()
        self.populate_rsa()
        self.populate_ltha()
        self.on_type_changed(self.combo_type.currentText())

        if hasattr(self.case, 'modal_type'):
            if self.case.modal_type == "Ritz": self.radio_ritz.setChecked(True)
            else: self.radio_eigen.setChecked(True)

        if hasattr(self.case, 'modal_comb'):
            if self.case.modal_comb == "CQC": self.radio_cqc.setChecked(True)
            else: self.radio_srss.setChecked(True)

        if hasattr(self.case, 'dir_comb'):
            if self.case.dir_comb == "Absolute": self.radio_dir_abs.setChecked(True)
            else: self.radio_dir_srss.setChecked(True)

    def on_type_changed(self, text):
        is_modal     = (text == "Modal")
        is_nonlinear = (text == "Nonlinear Static")
        is_rsa       = (text == "Response Spectrum")
        is_ltha      = (text == "LTHA")
        is_buckling  = (text == "Buckling")

        self.group_loads.setVisible(not is_modal and not is_rsa and not is_ltha)
        self.group_modal.setVisible(is_modal)
        self.group_rsa.setVisible(is_rsa)
        self.group_ltha.setVisible(is_ltha)
        self.group_buckling.setVisible(is_buckling)
        self.grp_stiffness.setVisible(True)
        self.group_settings.setVisible(is_nonlinear or is_rsa)
        self.chk_pdelta.setVisible(is_nonlinear)
        self.lbl_damp.setVisible(is_rsa)
        self.input_damping.setVisible(is_rsa)
        self.setWindowTitle("Load Case Data - " + text)

    def populate_loads(self):
        self.table.setRowCount(0)
        for pat, scale in self.case.loads:
            row = self.table.rowCount()
            self.table.insertRow(row)
            cmb = QComboBox()
            cmb.addItems(self.model.load_patterns.keys())
            cmb.setCurrentText(pat)
            self.table.setCellWidget(row, 0, cmb)
            self.table.setItem(row, 1, QTableWidgetItem(str(scale)))

    def add_load_row(self):
        row = self.table.rowCount()
        self.table.insertRow(row)
        cmb = QComboBox()
        cmb.addItems(self.model.load_patterns.keys())
        self.table.setCellWidget(row, 0, cmb)
        self.table.setItem(row, 1, QTableWidgetItem("1.0"))

    def delete_load_row(self):
        cr = self.table.currentRow()
        if cr >= 0: self.table.removeRow(cr)

    def add_ltha_row(self):
        if self.table_ltha.rowCount() >= 3:
            QMessageBox.information(self, "Limit Reached",
                                    "Maximum 3 ground motion functions (X, Y, Z).")
            return
        row = self.table_ltha.rowCount()
        self.table_ltha.insertRow(row)
        cmb_dir = QComboBox()
        cmb_dir.addItems(["X", "Y", "Z"])
        used = [self.table_ltha.cellWidget(r, 0).currentText()
                for r in range(row)
                if self.table_ltha.cellWidget(r, 0)]
        for d in ["X", "Y", "Z"]:
            if d not in used:
                cmb_dir.setCurrentText(d)
                break
        self.table_ltha.setCellWidget(row, 0, cmb_dir)
        cmb_func = QComboBox()
        th_funcs = getattr(self.model, 'th_functions', {})
        if th_funcs:
            cmb_func.addItems(th_funcs.keys())
        else:
            cmb_func.addItem("(No functions defined)")
        self.table_ltha.setCellWidget(row, 1, cmb_func)
        self.table_ltha.setItem(row, 2, QTableWidgetItem("1.0"))

    def delete_ltha_row(self):
        cr = self.table_ltha.currentRow()
        if cr >= 0: self.table_ltha.removeRow(cr)

    def populate_ltha(self):
        self.table_ltha.setRowCount(0)
        ltha_loads = getattr(self.case, 'ltha_loads', [])
        th_funcs   = getattr(self.model, 'th_functions', {})
        for direction, func_name, scale in ltha_loads:
            row = self.table_ltha.rowCount()
            self.table_ltha.insertRow(row)
            cmb_dir = QComboBox()
            cmb_dir.addItems(["X", "Y", "Z"])
            cmb_dir.setCurrentText(direction)
            self.table_ltha.setCellWidget(row, 0, cmb_dir)
            cmb_func = QComboBox()
            if th_funcs:
                cmb_func.addItems(th_funcs.keys())
            else:
                cmb_func.addItem("(No functions defined)")
            cmb_func.setCurrentText(func_name)
            self.table_ltha.setCellWidget(row, 1, cmb_func)
            self.table_ltha.setItem(row, 2, QTableWidgetItem(str(scale)))

    def on_ok(self):
        new_name = self.input_name.text().strip()
        if not new_name:
            QMessageBox.warning(self, "Error", "Name cannot be empty.")
            return
        if new_name != self.original_name and new_name in self.model.load_cases:
            QMessageBox.warning(self, "Error",
                                f"Load Case '{new_name}' already exists.\nPlease choose a unique name.")
            return
        if self.combo_type.currentText() == "Response Spectrum":
            if not self.validate_rsa_loads():
                return
        self.accept()

    def get_data(self):
        c = LoadCase(self.input_name.text().strip(), self.combo_type.currentText())
        c.p_delta = self.chk_pdelta.isChecked()
        try:
            c.modal_damping = float(self.input_damping.text())
        except ValueError:
            c.modal_damping = 0.05

        if c.case_type == "Modal":
            c.num_modes   = self.spin_max_modes.value()
            c.min_modes   = self.spin_min_modes.value()
            c.mass_source = self.combo_mass.currentText()
            c.modal_type  = "Ritz" if self.radio_ritz.isChecked() else "Eigen"

        elif c.case_type == "Response Spectrum":
            c.modal_comb = "CQC" if self.radio_cqc.isChecked() else "SRSS"
            c.dir_comb   = "SRSS" if self.radio_dir_srss.isChecked() else "Absolute"
            c.rsa_loads  = []
            for r in range(self.table_rsa.rowCount()):
                cmb_name   = self.table_rsa.cellWidget(r, 0)
                cmb_func   = self.table_rsa.cellWidget(r, 1)
                item_scale = self.table_rsa.item(r, 2)
                if cmb_name and cmb_func and item_scale:
                    try: val = float(item_scale.text())
                    except: val = 1.0
                    c.rsa_loads.append((cmb_name.currentText(), cmb_func.currentText(), val))

        elif c.case_type == "LTHA":
            try: c.damping = float(self.input_ltha_damping.text())
            except ValueError: c.damping = 0.05
            c.ltha_loads = []
            for r in range(self.table_ltha.rowCount()):
                cmb_dir    = self.table_ltha.cellWidget(r, 0)
                cmb_func   = self.table_ltha.cellWidget(r, 1)
                item_scale = self.table_ltha.item(r, 2)
                if cmb_dir and cmb_func and item_scale:
                    try: scale = float(item_scale.text())
                    except ValueError: scale = 1.0
                    c.ltha_loads.append((cmb_dir.currentText(), cmb_func.currentText(), scale))

        elif c.case_type == "Buckling":
            c.num_modes = self.spin_buck_modes.value()
            try: c.eigen_tol = float(self.input_buck_tol.text())
            except ValueError: c.eigen_tol = 1e-9
            c.mass_source = self.combo_buck_mass.currentText()
            c.loads = []
            for r in range(self.table.rowCount()):
                cmb = self.table.cellWidget(r, 0)
                if not cmb: continue
                try: scale = float(self.table.item(r, 1).text())
                except: scale = 1.0
                c.loads.append((cmb.currentText(), scale))

        else:
            for r in range(self.table.rowCount()):
                cmb = self.table.cellWidget(r, 0)
                if not cmb: continue
                try: scale = float(self.table.item(r, 1).text())
                except: scale = 1.0
                c.loads.append((cmb.currentText(), scale))

        return c

    def validate_rsa_loads(self):
        warnings = []
        for r in range(self.table_rsa.rowCount()):
            cmb_name = self.table_rsa.cellWidget(r, 0)
            cmb_func = self.table_rsa.cellWidget(r, 1)
            if cmb_name and cmb_func:
                load_dir  = cmb_name.currentText()
                func_name = cmb_func.currentText()
                if func_name in self.model.functions:
                    func_data     = self.model.functions[func_name]
                    spectrum_dir  = func_data.get('Direction', 'Horizontal')
                    if load_dir in ["U1", "U2"] and spectrum_dir == "Vertical":
                        warnings.append(f"⚠ Row {r+1}: '{func_name}' is Vertical but applied to {load_dir} (Horizontal)")
                    elif load_dir == "U3" and spectrum_dir == "Horizontal":
                        warnings.append(f"⚠ Row {r+1}: '{func_name}' is Horizontal but applied to U3 (Vertical)")
        if warnings:
            msg  = "Direction Mismatches Found:\n\n" + "\n".join(warnings)
            msg += "\n\nTypically:\n• U1/U2 → Horizontal Spectrum\n• U3 → Vertical Spectrum"
            QMessageBox.warning(self, "Check Spectrum Directions", msg)
            return False
        return True

    def add_rsa_row(self):
        row = self.table_rsa.rowCount()
        self.table_rsa.insertRow(row)
        cmb_name = QComboBox()
        cmb_name.addItems(["U1", "U2", "U3"])
        self.table_rsa.setCellWidget(row, 0, cmb_name)
        cmb_func = QComboBox()
        if hasattr(self.model, 'functions'):
            cmb_func.addItems(self.model.functions.keys())
        else:
            cmb_func.addItem("FUNC1")
        self.table_rsa.setCellWidget(row, 1, cmb_func)
        self.table_rsa.setItem(row, 2, QTableWidgetItem("9.81"))

    def delete_rsa_row(self):
        cr = self.table_rsa.currentRow()
        if cr >= 0: self.table_rsa.removeRow(cr)

    def populate_rsa(self):
        self.table_rsa.setRowCount(0)
        rsa_loads = getattr(self.case, 'rsa_loads', [])
        for load_name, func_name, scale in rsa_loads:
            row = self.table_rsa.rowCount()
            self.table_rsa.insertRow(row)
            cmb_name = QComboBox()
            cmb_name.addItems(["U1", "U2", "U3"])
            cmb_name.setCurrentText(load_name)
            self.table_rsa.setCellWidget(row, 0, cmb_name)
            cmb_func = QComboBox()
            if hasattr(self.model, 'functions'):
                cmb_func.addItems(self.model.functions.keys())
            cmb_func.setCurrentText(func_name)
            self.table_rsa.setCellWidget(row, 1, cmb_func)
            self.table_rsa.setItem(row, 2, QTableWidgetItem(str(scale)))

    def preview_spectrum(self):
        cr = self.table_rsa.currentRow()
        if cr < 0:
            QMessageBox.information(self, "No Selection", "Please select a row first.")
            return
        cmb_func = self.table_rsa.cellWidget(cr, 1)
        if not cmb_func: return
        func_name = cmb_func.currentText()
        if func_name not in self.model.functions:
            QMessageBox.warning(self, "Not Found", f"Function '{func_name}' doesn't exist.")
            return
        from app.dialogs.response_spectrum_dialog import ResponseSpectrumDialog
        dlg = ResponseSpectrumDialog(self)
        dlg.setWindowTitle(f"Preview: {func_name}")
        data = self.model.functions[func_name]
        dlg.input_name.setText(data.get('name', ''))
        dlg.input_name.setReadOnly(True)
        dlg.in_ss.setText(str(data.get('Ss', 0.55)))
        dlg.in_s1.setText(str(data.get('S1', 0.22)))
        dlg.in_tl.setText(str(data.get('TL', 6.0)))
        dlg.in_R.setText(str(data.get('R', 8.0)))
        dlg.in_D.setText(str(data.get('D', 3.0)))
        dlg.in_I.setText(str(data.get('I', 1.0)))
        dlg.combo_site.setCurrentText(data.get('SiteClass', 'ZB'))
        dlg.combo_dir.setCurrentText(data.get('Direction', 'Horizontal'))
        dlg.in_damp.setText(str(data.get('Damping', 0.05)))
        dlg.btn_ok.setText("Close")
        dlg.btn_cancel.setVisible(False)
        dlg.update_graph()
        dlg.exec()

class LoadCaseManagerDialog(QDialog):
    """The Main List Window (Define Load Cases)"""
    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model
        self.setWindowTitle("Define Load Cases")
        self.resize(500, 300)

        apply_dialog_style(self)                             

        layout = QHBoxLayout(self)

        self.list_widget = QListWidget()
        self.refresh_list()
        layout.addWidget(self.list_widget)

        v_btns = QVBoxLayout()

        btn_add = QPushButton("Add New Case...")
        btn_add.clicked.connect(self.add_case)

        btn_mod = QPushButton("Modify/Show Case...")
        btn_mod.clicked.connect(self.modify_case)

        btn_del = QPushButton("Delete Case")
        btn_del.clicked.connect(self.delete_case)

        v_btns.addWidget(btn_add)
        v_btns.addWidget(btn_mod)
        v_btns.addWidget(btn_del)
        v_btns.addStretch()

        btn_ok = QPushButton("OK")
        btn_ok.setObjectName("primary")                              
        btn_ok.clicked.connect(self.accept)
        v_btns.addWidget(btn_ok)

        layout.addLayout(v_btns)

    def refresh_list(self):
        self.list_widget.clear()
        for name, case in self.model.load_cases.items():
            c_type = case.get("type", "Linear Static") if isinstance(case, dict) else case.case_type
            self.list_widget.addItem(f"{name}  ({c_type})")

    def add_case(self):
        idx = 1
        while f"CASE{idx}" in self.model.load_cases:
            idx += 1
        temp_case = LoadCase(f"CASE{idx}", "Linear Static")
        dlg = LoadCaseDetailDialog(self.model, temp_case, self, is_new=True)
        if dlg.exec():
            final_case = dlg.get_data()
            self.model.load_cases[final_case.name] = final_case
            self.refresh_list()

    def modify_case(self):
        item = self.list_widget.currentItem()
        if not item: return
        old_name = item.text().split("  (")[0]
        if old_name in self.model.load_cases:
            original_case = self.model.load_cases[old_name]
            dlg = LoadCaseDetailDialog(self.model, original_case, self, is_new=False)
            if dlg.exec():
                new_case = dlg.get_data()
                if new_case.name != old_name:
                    del self.model.load_cases[old_name]
                self.model.load_cases[new_case.name] = new_case
                self.refresh_list()

    def delete_case(self):
        item = self.list_widget.currentItem()
        if not item: return
        name = item.text().split("  (")[0]
        if name == "DEAD":
            QMessageBox.warning(self, "Error", "Cannot delete default DEAD case.")
            return
        del self.model.load_cases[name]
        self.refresh_list()
