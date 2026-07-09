from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QLineEdit, QComboBox, QGroupBox, 
                             QRadioButton, QGridLayout, QMessageBox, QWidget)
from PyQt6.QtCore import Qt
from core.units import unit_registry
from app.commands import CmdAssignFrameLoad                   

class AssignFrameLoadDialog(QDialog):
    def __init__(self, main_window):
        super().__init__(main_window)
        self.main_window = main_window
        self.model = main_window.model
        
        self.setWindowTitle("Assign Frame Distributed Loads")
        self.resize(550, 450)
        self.setModal(False)
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
        
        main_layout = QVBoxLayout(self)

        top_layout = QHBoxLayout()

        grp_general = QGroupBox("General")
        grid_gen = QGridLayout()
        
        grid_gen.addWidget(QLabel("Load Pattern:"), 0, 0)
        self.pattern_combo = QComboBox()
        self.pattern_combo.addItems(list(self.model.load_patterns.keys()))
        grid_gen.addWidget(self.pattern_combo, 0, 1)

        grid_gen.addWidget(QLabel("Coordinate System:"), 1, 0)
        self.combo_coord = QComboBox()
        self.combo_coord.addItems(["Global", "Local"])
        self.combo_coord.currentIndexChanged.connect(self.update_direction_options)
        grid_gen.addWidget(self.combo_coord, 1, 1)

        grid_gen.addWidget(QLabel("Load Direction:"), 2, 0)
        self.combo_dir = QComboBox()
        grid_gen.addWidget(self.combo_dir, 2, 1)

        grid_gen.addWidget(QLabel("Load Type:"), 3, 0)
        self.combo_type = QComboBox()
        self.combo_type.addItems(["Force", "Moment"])
        grid_gen.addWidget(self.combo_type, 3, 1)
        
        grp_general.setLayout(grid_gen)
        top_layout.addWidget(grp_general, stretch=2)

        right_col_layout = QVBoxLayout()
        
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
        right_col_layout.addWidget(opt_group)

        u_label = unit_registry.current_unit_label
        grp_uniform = QGroupBox(f"Uniform Load ({u_label})")
        u_layout = QHBoxLayout()
        self.in_uniform = QLineEdit("0")
        u_layout.addWidget(self.in_uniform)
        grp_uniform.setLayout(u_layout)
        right_col_layout.addWidget(grp_uniform)

        top_layout.addLayout(right_col_layout, stretch=1)
        main_layout.addLayout(top_layout)

        grp_trap = QGroupBox("Trapezoidal Loads")
        grid_trap = QGridLayout()
        
        for i in range(4):
            lbl = QLabel(f"{i+1}.")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            grid_trap.addWidget(lbl, 0, i+1)
            
        grid_trap.addWidget(QLabel("Distance"), 1, 0)
        grid_trap.addWidget(QLabel("Loads"), 2, 0)

        self.dist_inputs = []
        self.load_inputs = []
        default_dists = ["0", "0.25", "0.75", "1"]
        
        for i in range(4):
            d_in = QLineEdit(default_dists[i])
            l_in = QLineEdit("0")
            self.dist_inputs.append(d_in)
            self.load_inputs.append(l_in)
            grid_trap.addWidget(d_in, 1, i+1)
            grid_trap.addWidget(l_in, 2, i+1)

        dist_type_layout = QHBoxLayout()
        self.rb_rel_dist = QRadioButton("Relative Distance from End-I")
        self.rb_abs_dist = QRadioButton("Absolute Distance from End-I")
        self.rb_rel_dist.setChecked(True)
        dist_type_layout.addWidget(self.rb_rel_dist)
        dist_type_layout.addWidget(self.rb_abs_dist)
        grid_trap.addLayout(dist_type_layout, 3, 0, 1, 5)

        grp_trap.setLayout(grid_trap)
        main_layout.addWidget(grp_trap)

        btn_layout = QHBoxLayout()
        self.btn_reset = QPushButton("Reset Form to Default Values")
        self.btn_reset.clicked.connect(self.reset_form)
        self.btn_ok = QPushButton("OK")
        self.btn_ok.clicked.connect(self.apply_and_close)
        self.btn_apply = QPushButton("Apply")
        self.btn_apply.clicked.connect(self.apply_loads)
        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self.close)
        
        btn_layout.addWidget(self.btn_reset)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_ok)
        btn_layout.addWidget(self.btn_close)
        btn_layout.addWidget(self.btn_apply)
        main_layout.addLayout(btn_layout)
        
        self.update_direction_options()

    def update_direction_options(self):
        coord = self.combo_coord.currentText()
        self.combo_dir.clear()
        if coord == "Global":
            self.combo_dir.addItems(["Gravity", "X", "Y", "Z"])
        else:
            self.combo_dir.addItems(["1 (Axial)", "2 (Major)", "3 (Minor)"])

    def reset_form(self):
        self.in_uniform.setText("0")
        default_dists = ["0", "0.25", "0.75", "1"]
        for i in range(4):
            self.dist_inputs[i].setText(default_dists[i])
            self.load_inputs[i].setText("0")
        self.rb_rel_dist.setChecked(True)
        self.rb_replace.setChecked(True)

    def apply_and_close(self):
        if self.apply_loads():
            self.close()

    def apply_loads(self):
        selected_frames = self.main_window.selected_ids
        if not selected_frames:
            QMessageBox.warning(self, "Selection Error", "Please select at least one Frame Element.")
            return False

        try:
                           
            dist_scale = unit_registry.force_scale / unit_registry.length_scale
            
            pat = self.pattern_combo.currentText()
            coord = self.combo_coord.currentText()
            direction = self.combo_dir.currentText()
            l_type = self.combo_type.currentText()
            is_relative = self.rb_rel_dist.isChecked()
            
            uniform_val = float(self.in_uniform.text() or 0) / dist_scale

            distances = [float(d.text() or 0) for d in self.dist_inputs]
            magnitudes = [float(l.text() or 0) / dist_scale for l in self.load_inputs]

            if abs(uniform_val) > 1e-9:
                magnitudes = [m + uniform_val for m in magnitudes]

            has_trap = any(abs(m) > 1e-9 for m in magnitudes)

            direction_sign = -1.0 if (coord == "Global" and direction == "Gravity") else 1.0

            ref_val = max(magnitudes, key=lambda m: abs(m)) if has_trap else uniform_val
            signed_ref = direction_sign * ref_val

            signed_magnitudes = [direction_sign * m for m in magnitudes] if has_trap else None

            wx = wy = wz = 0.0
            if coord == "Global":
                if direction == "Gravity":
                    wz = signed_ref
                elif direction == "X":
                    wx = signed_ref
                elif direction == "Y":
                    wy = signed_ref
                elif direction == "Z":
                    wz = signed_ref
            else:         
                if direction.startswith("1"):
                    wx = signed_ref
                elif direction.startswith("2"):
                    wy = signed_ref
                elif direction.startswith("3"):
                    wz = signed_ref

            mode = "replace"
            if self.rb_add.isChecked(): mode = "add"
            elif self.rb_delete.isChecked(): mode = "delete"

            cmd = CmdAssignFrameLoad(
                self.model,
                self.main_window,
                list(selected_frames),
                pat,
                wx, wy, wz,
                False,                     
                coord,                     
                mode,
                distances=distances if has_trap else None,
                magnitudes=signed_magnitudes,
                is_relative=is_relative,
                load_direction=direction,
                load_type=l_type,
            )
            self.main_window.add_command(cmd)

            self.main_window.status.showMessage(f"Assigned {pat} Loads to {len(selected_frames)} Frames.")
            self.main_window.selected_ids = []
            self.main_window.canvas.draw_model(self.model, [], [])
            return True

        except ValueError:
            QMessageBox.warning(self, "Input Error", "Please enter valid numeric values.")
            return False
