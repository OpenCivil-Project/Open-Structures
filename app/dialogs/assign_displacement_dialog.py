from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QLineEdit, QComboBox, QGroupBox, 
                             QRadioButton, QGridLayout, QMessageBox)
from PyQt6.QtCore import Qt
                                         
from app.commands import CmdAssignJointDisplacement                   

from core.units import unit_registry 

class AssignJointDisplacementDialog(QDialog):
    def __init__(self, main_window):
        super().__init__(main_window)
        self.main_window = main_window
        self.model = main_window.model
        
        self.setWindowTitle("Assign Joint Ground Displacements")
        self.resize(400, 500)
        
        self.setModal(False)
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
        
        layout = QVBoxLayout(self)

        general_group = QGroupBox("General")
        general_layout = QGridLayout()
        
        general_layout.addWidget(QLabel("Load Pattern:"), 0, 0)
        self.pattern_combo = QComboBox()
        self.pattern_combo.addItems(list(self.model.load_patterns.keys()))
        general_layout.addWidget(self.pattern_combo, 0, 1)

        general_layout.addWidget(QLabel("Coordinate System:"), 1, 0)
        self.coord_combo = QComboBox()
        self.coord_combo.addItems(["GLOBAL"])                             
        general_layout.addWidget(self.coord_combo, 1, 1)
        
        general_group.setLayout(general_layout)
        layout.addWidget(general_group)

        unit_parts = unit_registry.current_unit_label.split(',')
        u_len = unit_parts[1].strip() if len(unit_parts) > 1 else "m"
        
        disp_group = QGroupBox(f"Ground Displacements (Units: {u_len}, rad)")
        grid = QGridLayout()
        
        self.in_ux = QLineEdit("0")
        self.in_uy = QLineEdit("0")
        self.in_uz = QLineEdit("0") 
        self.in_rx = QLineEdit("0")
        self.in_ry = QLineEdit("0")
        self.in_rz = QLineEdit("0")

        grid.addWidget(QLabel("Translation Global X"), 0, 0); grid.addWidget(self.in_ux, 0, 1); grid.addWidget(QLabel(u_len), 0, 2)
        grid.addWidget(QLabel("Translation Global Y"), 1, 0); grid.addWidget(self.in_uy, 1, 1); grid.addWidget(QLabel(u_len), 1, 2)
        grid.addWidget(QLabel("Translation Global Z"), 2, 0); grid.addWidget(self.in_uz, 2, 1); grid.addWidget(QLabel(u_len), 2, 2)
        
        grid.addWidget(QLabel("Rotation about Global X"), 3, 0); grid.addWidget(self.in_rx, 3, 1); grid.addWidget(QLabel("rad"), 3, 2)
        grid.addWidget(QLabel("Rotation about Global Y"), 4, 0); grid.addWidget(self.in_ry, 4, 1); grid.addWidget(QLabel("rad"), 4, 2)
        grid.addWidget(QLabel("Rotation about Global Z"), 5, 0); grid.addWidget(self.in_rz, 5, 1); grid.addWidget(QLabel("rad"), 5, 2)
        
        disp_group.setLayout(grid)
        layout.addWidget(disp_group)

        opt_group = QGroupBox("Options")
        opt_layout = QVBoxLayout()
        self.rb_add = QRadioButton("Add to Existing Loads")
        self.rb_replace = QRadioButton("Replace Existing Loads")
        self.rb_delete = QRadioButton("Delete Existing Loads")
        self.rb_replace.setChecked(True) 
        
        opt_layout.addWidget(self.rb_add)
        opt_layout.addWidget(self.rb_replace)
        opt_layout.addWidget(self.rb_delete)
        opt_group.setLayout(opt_layout)
        layout.addWidget(opt_group)

        btn_layout = QHBoxLayout()
        
        self.btn_reset = QPushButton("Reset Form to Default Values")
        self.btn_reset.clicked.connect(self.reset_form)
        
        self.btn_ok = QPushButton("OK")
        self.btn_ok.clicked.connect(self.accept_loads)
        
        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self.close)
        
        self.btn_apply = QPushButton("Apply")
        self.btn_apply.clicked.connect(self.apply_displacements)
        
        layout.addWidget(self.btn_reset)
        
        action_btn_layout = QHBoxLayout()
        action_btn_layout.addWidget(self.btn_ok)
        action_btn_layout.addWidget(self.btn_close)
        action_btn_layout.addWidget(self.btn_apply)
        layout.addLayout(action_btn_layout)

    def reset_form(self):
        self.in_ux.setText("0")
        self.in_uy.setText("0")
        self.in_uz.setText("0")
        self.in_rx.setText("0")
        self.in_ry.setText("0")
        self.in_rz.setText("0")
        self.rb_replace.setChecked(True)

    def accept_loads(self):
        self.apply_displacements()
        self.close()

    def apply_displacements(self):
        selected_nodes = self.main_window.selected_node_ids
        if not selected_nodes:
            QMessageBox.warning(self, "Selection Error", "Please select at least one Joint.")
            return

        try:
                               
            user_ux = float(self.in_ux.text() or 0)
            user_uy = float(self.in_uy.text() or 0)
            user_uz = float(self.in_uz.text() or 0)
            user_rx = float(self.in_rx.text() or 0)
            user_ry = float(self.in_ry.text() or 0)
            user_rz = float(self.in_rz.text() or 0)
            
            ux = unit_registry.from_display_length(user_ux) if hasattr(unit_registry, 'from_display_length') else user_ux
            uy = unit_registry.from_display_length(user_uy) if hasattr(unit_registry, 'from_display_length') else user_uy
            uz = unit_registry.from_display_length(user_uz) if hasattr(unit_registry, 'from_display_length') else user_uz
            
            pat = self.pattern_combo.currentText()
            mode = "replace"
            if self.rb_add.isChecked(): mode = "add"
            elif self.rb_delete.isChecked(): mode = "delete"

            cmd = CmdAssignJointDisplacement(
                self.model, 
                self.main_window, 
                list(selected_nodes), 
                pat, 
                ux, uy, uz, user_rx, user_ry, user_rz, 
                mode
            )
            self.main_window.add_command(cmd)

            self.main_window.status.showMessage(f"Assigned Ground Displacements to {len(selected_nodes)} Joints.")
            
            self.main_window.selected_node_ids = []
            self.main_window.selected_ids = [] 
            self.main_window.canvas.draw_model(self.model, [], [])

        except ValueError:
            QMessageBox.warning(self, "Input Error", "Please enter valid numeric values.")
