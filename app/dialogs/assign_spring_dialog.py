import numpy as np
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QLineEdit, QComboBox, QGroupBox, 
                             QRadioButton, QGridLayout, QMessageBox)
from PyQt6.QtCore import Qt

from core.units import unit_registry
from app.commands import CmdAssignJointSpring

class AdvancedSpringDialog(QDialog):
    """Sub-dialog to handle the 6x6 coupled stiffness matrix."""
    def __init__(self, parent, current_matrix=None):
        super().__init__(parent)
        self.setWindowTitle("Coupled 6x6 Joint Spring")
        self.setModal(True)
        
        u_f = unit_registry.force_unit_name
        u_l = unit_registry.length_unit_name
        
        layout = QVBoxLayout(self)
        
        matrix_group = QGroupBox("Upper Stiffness Matrix - Local Coordinate System")
        grid = QGridLayout()
        
        self.inputs = {}
        headers = ['u1', 'u2', 'u3', 'r1', 'r2', 'r3']
        
        for j, h in enumerate(headers):
            lbl = QLabel(h)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            grid.addWidget(lbl, 0, j * 2 + 1)
            
        for i in range(6):
                        
            grid.addWidget(QLabel(headers[i]), i + 1, 0)
            for j in range(6):
                if j >= i:
                    le = QLineEdit("0")
                    le.setFixedWidth(60)
                    
                    if i < 3 and j < 3:
                        unit_str = f"{u_f}/{u_l}"                        
                    elif (i < 3 and j >= 3) or (i >= 3 and j < 3):
                        unit_str = f"{u_f}/rad"                                 
                    else:
                        unit_str = f"{u_f}-{u_l}/rad"              

                    unit_lbl = QLabel(unit_str)
                    
                    self.inputs[(i, j)] = le
                    
                    cell_layout = QHBoxLayout()
                    cell_layout.addWidget(le)
                    cell_layout.addWidget(unit_lbl)
                    cell_layout.setContentsMargins(0, 0, 0, 0)
                    
                    grid.addLayout(cell_layout, i + 1, j * 2 + 1)

        matrix_group.setLayout(grid)
        layout.addWidget(matrix_group)
        
        btn_layout = QVBoxLayout()
        
        self.btn_clear_off = QPushButton("Clear Off-Diagonal Terms")
        self.btn_clear_off.setFixedWidth(200)
        self.btn_clear_off.clicked.connect(self.clear_off_diagonals)
        
        bottom_btns = QHBoxLayout()
        self.btn_ok = QPushButton("OK")
        self.btn_cancel = QPushButton("Cancel")
        self.btn_ok.clicked.connect(self.accept)
        self.btn_cancel.clicked.connect(self.reject)
        
        bottom_btns.addStretch()
        bottom_btns.addWidget(self.btn_ok)
        bottom_btns.addWidget(self.btn_cancel)
        bottom_btns.addStretch()
        
        btn_layout.addWidget(self.btn_clear_off, alignment=Qt.AlignmentFlag.AlignCenter)
        btn_layout.addLayout(bottom_btns)
        
        layout.addLayout(btn_layout)

        if current_matrix is not None:
            self.populate_matrix(current_matrix)

    def clear_off_diagonals(self):
        """Zeroes out all terms where i != j"""
        for (i, j), le in self.inputs.items():
            if i != j:
                le.setText("0")

    def populate_matrix(self, matrix):
        """Fills the UI from an existing 6x6 array."""
        for (i, j), le in self.inputs.items():
            le.setText(str(matrix[i, j]))

    def get_matrix(self):
        """Returns a full, symmetric 6x6 numpy array from UI inputs."""
        mat = np.zeros((6, 6))
        for (i, j), le in self.inputs.items():
            try:
                val = float(le.text() or 0)
            except ValueError:
                val = 0.0
            mat[i, j] = val
            mat[j, i] = val                             
        return mat

class AssignJointSpringDialog(QDialog):
    def __init__(self, main_window):
        super().__init__(main_window)
        self.main_window = main_window
        self.model = main_window.model
        
        self.setWindowTitle("Assign Joint Springs")
        self.resize(350, 500)
        
        self.setModal(False)
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
        
        self.advanced_matrix = np.zeros((6, 6))
        
        layout = QVBoxLayout(self)

        type_group = QGroupBox("Spring Type")
        type_layout = QVBoxLayout()
        
        self.rb_simple = QRadioButton("Simple")
        self.rb_advanced = QRadioButton("Advanced - Coupled 6x6 Spring")
        self.rb_simple.setChecked(True)
        
        self.btn_advanced_stiffness = QPushButton("Modify/Show Advanced Spring Stiffness...")
        self.btn_advanced_stiffness.setEnabled(False)
        self.btn_advanced_stiffness.clicked.connect(self.open_advanced_dialog)
        
        self.rb_simple.toggled.connect(self.toggle_mode)
        
        type_layout.addWidget(self.rb_simple)
        type_layout.addWidget(self.rb_advanced)
        type_layout.addWidget(self.btn_advanced_stiffness)
        type_group.setLayout(type_layout)
        layout.addWidget(type_group)

        coord_group = QGroupBox("Spring Coordinate System")
        coord_layout = QGridLayout()
        coord_layout.addWidget(QLabel("Direction"), 0, 0)
        self.coord_combo = QComboBox()
        self.coord_combo.addItems(["GLOBAL"])
        coord_layout.addWidget(self.coord_combo, 0, 1)
        coord_group.setLayout(coord_layout)
        layout.addWidget(coord_group)

        u_f = unit_registry.force_unit_name
        u_l = unit_registry.length_unit_name
        
        self.simple_group = QGroupBox("Simple Spring Stiffness")
        grid = QGridLayout()
        
        self.in_ux = QLineEdit("0"); self.in_uy = QLineEdit("0"); self.in_uz = QLineEdit("0")
        self.in_rx = QLineEdit("0"); self.in_ry = QLineEdit("0"); self.in_rz = QLineEdit("0")

        grid.addWidget(QLabel("Translation Global X"), 0, 0); grid.addWidget(self.in_ux, 0, 1); grid.addWidget(QLabel(f"{u_f}/{u_l}"), 0, 2)
        grid.addWidget(QLabel("Translation Global Y"), 1, 0); grid.addWidget(self.in_uy, 1, 1); grid.addWidget(QLabel(f"{u_f}/{u_l}"), 1, 2)
        grid.addWidget(QLabel("Translation Global Z"), 2, 0); grid.addWidget(self.in_uz, 2, 1); grid.addWidget(QLabel(f"{u_f}/{u_l}"), 2, 2)
        
        grid.addWidget(QLabel("Rotation about Global X"), 3, 0); grid.addWidget(self.in_rx, 3, 1); grid.addWidget(QLabel(f"{u_f}-{u_l}/rad"), 3, 2)
        grid.addWidget(QLabel("Rotation about Global Y"), 4, 0); grid.addWidget(self.in_ry, 4, 1); grid.addWidget(QLabel(f"{u_f}-{u_l}/rad"), 4, 2)
        grid.addWidget(QLabel("Rotation about Global Z"), 5, 0); grid.addWidget(self.in_rz, 5, 1); grid.addWidget(QLabel(f"{u_f}-{u_l}/rad"), 5, 2)
        
        self.simple_group.setLayout(grid)
        layout.addWidget(self.simple_group)

        opt_group = QGroupBox("Options")
        opt_layout = QVBoxLayout()
        self.rb_add = QRadioButton("Add to Existing Springs")
        self.rb_replace = QRadioButton("Replace Existing Springs")
        self.rb_delete = QRadioButton("Delete Existing Springs")
        self.rb_replace.setChecked(True) 
        
        opt_layout.addWidget(self.rb_add)
        opt_layout.addWidget(self.rb_replace)
        opt_layout.addWidget(self.rb_delete)
        opt_group.setLayout(opt_layout)
        layout.addWidget(opt_group)

        self.btn_reset = QPushButton("Reset Form to Default Values")
        self.btn_reset.clicked.connect(self.reset_form)
        layout.addWidget(self.btn_reset)
        
        action_btn_layout = QHBoxLayout()
        self.btn_ok = QPushButton("OK")
        self.btn_close = QPushButton("Close")
        self.btn_apply = QPushButton("Apply")
        
        self.btn_ok.clicked.connect(self.accept_springs)
        self.btn_close.clicked.connect(self.close)
        self.btn_apply.clicked.connect(self.apply_springs)
        
        action_btn_layout.addWidget(self.btn_ok)
        action_btn_layout.addWidget(self.btn_close)
        action_btn_layout.addWidget(self.btn_apply)
        layout.addLayout(action_btn_layout)

    def toggle_mode(self):
        """Switches UI states between Simple and Advanced"""
        is_simple = self.rb_simple.isChecked()
        self.simple_group.setEnabled(is_simple)
        self.btn_advanced_stiffness.setEnabled(not is_simple)

    def open_advanced_dialog(self):
        dlg = AdvancedSpringDialog(self, self.advanced_matrix)
        if dlg.exec():
            self.advanced_matrix = dlg.get_matrix()

    def reset_form(self):
        self.in_ux.setText("0"); self.in_uy.setText("0"); self.in_uz.setText("0")
        self.in_rx.setText("0"); self.in_ry.setText("0"); self.in_rz.setText("0")
        self.advanced_matrix = np.zeros((6, 6))
        self.rb_replace.setChecked(True)
        self.rb_simple.setChecked(True)

    def accept_springs(self):
        self.apply_springs()
        self.close()

    def apply_springs(self):
        selected_nodes = self.main_window.selected_node_ids
        if not selected_nodes:
            QMessageBox.warning(self, "Selection Error", "Please select at least one Joint.")
            return

        try:
                                                                    
            raw_matrix = np.zeros((6, 6))
            if self.rb_simple.isChecked():
                raw_matrix[0, 0] = float(self.in_ux.text() or 0)
                raw_matrix[1, 1] = float(self.in_uy.text() or 0)
                raw_matrix[2, 2] = float(self.in_uz.text() or 0)
                raw_matrix[3, 3] = float(self.in_rx.text() or 0)
                raw_matrix[4, 4] = float(self.in_ry.text() or 0)
                raw_matrix[5, 5] = float(self.in_rz.text() or 0)
            else:
                raw_matrix = self.advanced_matrix.copy()

            si_matrix = np.zeros((6, 6))
            f_scale = unit_registry.force_scale
            l_scale = unit_registry.length_scale

            for i in range(6):
                for j in range(6):
                    val = raw_matrix[i, j]
                    if val == 0: continue
                    
                    if i < 3 and j < 3: 
                                                                                         
                        si_matrix[i, j] = val * (l_scale / f_scale)
                    elif (i < 3 and j >= 3) or (i >= 3 and j < 3):
                                                                    
                        si_matrix[i, j] = val / f_scale
                    else:
                                                                                          
                        si_matrix[i, j] = val / (f_scale * l_scale)

            mode = "replace"
            if self.rb_add.isChecked(): mode = "add"
            elif self.rb_delete.isChecked(): mode = "delete"

            print("--- SPRING ASSIGNMENT (SI UNITS) ---")
            print(f"Nodes: {list(selected_nodes)}")
            print(f"Mode: {mode}")
            print(si_matrix)
            print("------------------------------------")
            
            cmd = CmdAssignJointSpring(self.model, self.main_window, list(selected_nodes), si_matrix, mode)
            self.main_window.add_command(cmd)

            self.main_window.status.showMessage(f"Assigned Springs to {len(selected_nodes)} Joints.")
            self.main_window.selected_node_ids = []
            self.main_window.selected_ids = [] 
            self.main_window.canvas.draw_model(self.model, [], [])

        except ValueError:
            QMessageBox.warning(self, "Input Error", "Please enter valid numeric values.")
