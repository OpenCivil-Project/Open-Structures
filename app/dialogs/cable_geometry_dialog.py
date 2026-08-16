import math
import numpy as np
from PyQt6.QtWidgets import (QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QGroupBox, QFormLayout, QLineEdit,
                             QComboBox, QCheckBox, QRadioButton, QTableWidget,
                             QTableWidgetItem, QHeaderView, QFrame, QGridLayout)
from PyQt6.QtCore import Qt
import pyqtgraph as pg

from app.ui.theme import apply_dialog_style
from core.cable_catenary_solver import solve_cable_geometry, CableTargetType
from core.units import unit_registry

class CableGeometryDialog(QDialog):
    """
    Open // Structures Cable Geometry Editor
    Matches SAP2000's extensive Cable Geometry formulation interface.
    """
    def __init__(self, cable, model, parent=None):
        super().__init__(parent)
        self.cable = cable
        self.model = model
        
        apply_dialog_style(self)
        self.setWindowTitle(f"Cable Geometry - {cable.label}")
        self.setMinimumSize(950, 750)
        self.resize(950, 750)

        root_layout = QVBoxLayout(self)
        root_layout.setSpacing(6)
        root_layout.setContentsMargins(10, 8, 10, 6)

        top_layout = QHBoxLayout()
        top_layout.setSpacing(16)

        left_col = QVBoxLayout()
        
        param_group = QGroupBox("Line Object Parameters")
        param_form = QFormLayout(param_group)
        param_form.setContentsMargins(8, 6, 8, 6)
        param_form.setVerticalSpacing(3)
        param_form.setHorizontalSpacing(6)
        
        self.combo_obj_type = QComboBox()
        self.combo_obj_type.addItem("Cable")
        self.combo_obj_type.setEnabled(False)                  
        
        self.combo_cable_type = QComboBox()
        self.cable_types = [
            "Cable - Undeformed Length",
            "Cable - Tension at I-End",
            "Cable - Tension at J-End",
            "Cable - Horizontal Tension Component",
            "Cable - Maximum Vertical Sag",
            "Cable - Low-Point Vertical Sag"
        ]
        self.combo_cable_type.addItems(self.cable_types)
        self.combo_cable_type.currentIndexChanged.connect(self._update_active_inputs)

        self.combo_section = QComboBox()
        self._populate_cable_sections()
        
        param_form.addRow("Line Object Type:", self.combo_obj_type)
        param_form.addRow("Cable Type:", self.combo_cable_type)
        param_form.addRow("Section Property:", self.combo_section)

        coord_grid = QGridLayout()
        coord_grid.addWidget(QLabel("X"), 0, 1, alignment=Qt.AlignmentFlag.AlignCenter)
        coord_grid.addWidget(QLabel("Y"), 0, 2, alignment=Qt.AlignmentFlag.AlignCenter)
        coord_grid.addWidget(QLabel("Z"), 0, 3, alignment=Qt.AlignmentFlag.AlignCenter)
        
        coord_grid.addWidget(QLabel("Start"), 1, 0)
        self.txt_sx = QLineEdit(f"{unit_registry.to_display_length(cable.node_i.x):.4g}"); self.txt_sx.setReadOnly(True)
        self.txt_sy = QLineEdit(f"{unit_registry.to_display_length(cable.node_i.y):.4g}"); self.txt_sy.setReadOnly(True)
        self.txt_sz = QLineEdit(f"{unit_registry.to_display_length(cable.node_i.z):.4g}"); self.txt_sz.setReadOnly(True)
        coord_grid.addWidget(self.txt_sx, 1, 1)
        coord_grid.addWidget(self.txt_sy, 1, 2)
        coord_grid.addWidget(self.txt_sz, 1, 3)

        coord_grid.addWidget(QLabel("End"), 2, 0)
        self.txt_ex = QLineEdit(f"{unit_registry.to_display_length(cable.node_j.x):.4g}"); self.txt_ex.setReadOnly(True)
        self.txt_ey = QLineEdit(f"{unit_registry.to_display_length(cable.node_j.y):.4g}"); self.txt_ey.setReadOnly(True)
        self.txt_ez = QLineEdit(f"{unit_registry.to_display_length(cable.node_j.z):.4g}"); self.txt_ez.setReadOnly(True)
        coord_grid.addWidget(self.txt_ex, 2, 1)
        coord_grid.addWidget(self.txt_ey, 2, 2)
        coord_grid.addWidget(self.txt_ez, 2, 3)
        
        param_form.addRow(coord_grid)

        self.chk_straight_frame = QCheckBox("Model Cable Using Straight Frame Objects")
        self.chk_straight_frame.setChecked(getattr(cable, 'model_as_straight_frame', True))
        param_form.addRow(self.chk_straight_frame)
        
        left_col.addWidget(param_group)

        mesh_group = QGroupBox("Line Object Meshing")
        mesh_layout = QVBoxLayout(mesh_group)
        mesh_layout.setContentsMargins(8, 6, 8, 6)
        mesh_layout.setSpacing(3)
        self.rad_mesh_single = QRadioButton("Keep as Single Object")
        self.rad_mesh_equal = QRadioButton("Break into Multiple Equal Length Objects")
        self.rad_mesh_proj = QRadioButton("Break into Multiple Objects with Equal Projected Length on Chord")
        self.rad_mesh_single.setChecked(True)
        
        mesh_layout.addWidget(self.rad_mesh_single)
        mesh_layout.addWidget(self.rad_mesh_equal)
        mesh_layout.addWidget(self.rad_mesh_proj)
        
        left_col.addWidget(mesh_group)
        left_col.addStretch()

        right_col = QVBoxLayout()
        
        cable_param_group = QGroupBox(
            f"Cable Parameters  (Force: {unit_registry.force_unit_name}, "
            f"Length: {unit_registry.length_unit_name})"
        )
        cp_layout = QGridLayout(cable_param_group)
        cp_layout.setContentsMargins(8, 6, 8, 6)
        cp_layout.setVerticalSpacing(2)
        cp_layout.setHorizontalSpacing(6)
        cable_param_group.setMaximumHeight(425)
        
        cp_layout.addWidget(QLabel("Number of Cable Segments"), 0, 0)
        self.txt_segments = QLineEdit(str(getattr(cable, 'number_of_segments', 1)))
        cp_layout.addWidget(self.txt_segments, 0, 1)
        
        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.clicked.connect(self._simulate_refresh)
        cp_layout.addWidget(self.btn_refresh, 0, 2)

        cp_layout.addWidget(QLabel("Added Weight Per Unit Length"), 1, 0)
        self.txt_add_wt = QLineEdit("0.0")
        cp_layout.addWidget(self.txt_add_wt, 1, 1)
        cp_layout.addWidget(QLabel(unit_registry.distributed_load_unit), 1, 2)

        cp_layout.addWidget(QLabel("Projected Uniform Gravity Load"), 2, 0)
        self.txt_proj_load = QLineEdit("0.0")
        cp_layout.addWidget(self.txt_proj_load, 2, 1)
        cp_layout.addWidget(QLabel(unit_registry.distributed_load_unit), 2, 2)

        cp_layout.addWidget(QLabel("Tension At I-End"), 3, 0)
        self.txt_tens_i = QLineEdit("0.0")
        cp_layout.addWidget(self.txt_tens_i, 3, 1)
        cp_layout.addWidget(QLabel(unit_registry.force_unit_name), 3, 2)

        cp_layout.addWidget(QLabel("Tension At J-End"), 4, 0)
        self.txt_tens_j = QLineEdit("0.0")
        cp_layout.addWidget(self.txt_tens_j, 4, 1)
        cp_layout.addWidget(QLabel(unit_registry.force_unit_name), 4, 2)

        cp_layout.addWidget(QLabel("Horizontal Tension Component"), 5, 0)
        self.txt_tens_h = QLineEdit("0.0")
        cp_layout.addWidget(self.txt_tens_h, 5, 1)
        cp_layout.addWidget(QLabel(unit_registry.force_unit_name), 5, 2)

        cp_layout.addWidget(QLabel("Deformed"), 6, 1, alignment=Qt.AlignmentFlag.AlignCenter)
        cp_layout.addWidget(QLabel("Undeformed"), 6, 2, alignment=Qt.AlignmentFlag.AlignCenter)

        cp_layout.addWidget(QLabel("Maximum Vertical Sag"), 7, 0)
        self.txt_def_max_sag = QLineEdit("0.0"); self.txt_def_max_sag.setReadOnly(True)
        self.txt_undef_max_sag = QLineEdit("0.0")
        cp_layout.addWidget(self.txt_def_max_sag, 7, 1)
        cp_layout.addWidget(self.txt_undef_max_sag, 7, 2)

        cp_layout.addWidget(QLabel("Low-Point Vertical Sag"), 8, 0)
        self.txt_def_low_sag = QLineEdit("0.0"); self.txt_def_low_sag.setReadOnly(True)
        self.txt_undef_low_sag = QLineEdit("0.0")
        cp_layout.addWidget(self.txt_def_low_sag, 8, 1)
        cp_layout.addWidget(self.txt_undef_low_sag, 8, 2)

        cp_layout.addWidget(QLabel("Length"), 9, 0)
        self.txt_def_len = QLineEdit(f"{cable.length():.4f}"); self.txt_def_len.setReadOnly(True)
        self.txt_undef_len = QLineEdit(f"{getattr(cable, 'undeformed_length', cable.length()):.4f}")
        cp_layout.addWidget(self.txt_def_len, 9, 1)
        cp_layout.addWidget(self.txt_undef_len, 9, 2)

        cp_layout.addWidget(QLabel("Relative Length"), 10, 0)
        self.txt_def_rel_len = QLineEdit("1.0"); self.txt_def_rel_len.setReadOnly(True)
        self.txt_undef_rel_len = QLineEdit("1.0"); self.txt_undef_rel_len.setReadOnly(True)
        cp_layout.addWidget(self.txt_def_rel_len, 10, 1)
        cp_layout.addWidget(self.txt_undef_rel_len, 10, 2)

        self.lbl_solve_status = QLabel("")
        self.lbl_solve_status.setWordWrap(True)
        self.lbl_solve_status.setStyleSheet("color: #b00020;")
        cp_layout.addWidget(self.lbl_solve_status, 11, 0, 1, 3)

        right_col.addWidget(cable_param_group)

        sys_unit_layout = QHBoxLayout()
        
        sys_group = QGroupBox("Coordinate System")
        sl = QVBoxLayout(sys_group)
        sl.setContentsMargins(8, 5, 8, 5)
        sl.setSpacing(2)
        self.combo_sys = QComboBox()
        self.combo_sys.addItem("GLOBAL")
        sl.addWidget(self.combo_sys)
        sys_unit_layout.addWidget(sys_group)

        unit_group = QGroupBox("Units")
        ul = QVBoxLayout(unit_group)
        ul.setContentsMargins(8, 5, 8, 5)
        ul.setSpacing(2)
        self.combo_units = QComboBox()
        self.combo_units.addItem(unit_registry.current_unit_label)
        ul.addWidget(self.combo_units)
        sys_unit_layout.addWidget(unit_group)

        right_col.addLayout(sys_unit_layout)

        top_layout.addLayout(left_col, stretch=1)
        top_layout.addLayout(right_col, stretch=1)

        top_container = QWidget()
        top_container.setFixedHeight(485)
        top_container.setLayout(top_layout)
        root_layout.addWidget(top_container)

        bot_layout = QHBoxLayout()
        bot_layout.setSpacing(10)
        bot_layout.setContentsMargins(0, 0, 0, 0)

        table_group = QGroupBox("Computed Point Coordinates for Linear Segments")
        tbl_layout = QVBoxLayout(table_group)
        tbl_layout.setContentsMargins(6, 4, 6, 4)
        tbl_layout.setSpacing(3)
        
        tbl_radio_layout = QHBoxLayout()
        self.rad_tbl_undef = QRadioButton("Use Undeformed Geometry for Cable Object")
        self.rad_tbl_def = QRadioButton("Use Deformed Geometry for Cable Object")
        self.rad_tbl_undef.setChecked(True)
        tbl_radio_layout.addWidget(self.rad_tbl_undef)
        tbl_radio_layout.addWidget(self.rad_tbl_def)
        tbl_layout.addLayout(tbl_radio_layout)

        self.table = QTableWidget()
        self.table.setColumnCount(7)
        _lu = unit_registry.length_unit_name
        self.table.setHorizontalHeaderLabels(
            ["Pt.", f"X ({_lu})", f"Y ({_lu})", f"Z ({_lu})",
             f"Sag ({_lu})", f"Distance ({_lu})", "Rel. Dist."]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.table.setMinimumHeight(92)
        self.table.setMaximumHeight(105)
        tbl_layout.addWidget(self.table)
        
        bot_layout.addWidget(table_group, stretch=2)

        plot_group = QGroupBox("Planar View")
        plot_layout = QVBoxLayout(plot_group)
        plot_layout.setContentsMargins(5, 4, 5, 4)
        plot_layout.setSpacing(2)
        self.plot_widget = pg.PlotWidget(background='w')
        self.plot_widget.showGrid(x=False, y=False)
        self.plot_widget.setMenuEnabled(False)
        self.plot_widget.setMouseEnabled(x=False, y=False)
        self.plot_widget.hideAxis('left')
        self.plot_widget.hideAxis('bottom')
        plot_layout.addWidget(self.plot_widget)
        
        bot_layout.addWidget(plot_group, stretch=1)

        bottom_container = QWidget()
        bottom_container.setFixedHeight(145)
        bottom_container.setLayout(bot_layout)
        root_layout.addWidget(bottom_container)

        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.setSpacing(6)
        btn_layout.addStretch()
        
        self.btn_ok = QPushButton("OK")
        self.btn_ok.setObjectName("primary")
        self.btn_ok.setFixedSize(90, 28)
        self.btn_ok.clicked.connect(self.accept)
        
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setObjectName("secondary")
        self.btn_cancel.setFixedSize(80, 28)
        self.btn_cancel.clicked.connect(self.reject)
        
        btn_layout.addWidget(self.btn_ok)
        btn_layout.addWidget(self.btn_cancel)
        root_layout.addLayout(btn_layout)

        self._update_active_inputs()

        saved_target = getattr(self.cable, 'target_type', "Cable - Undeformed Length")
        idx = self.combo_cable_type.findText(saved_target)
        if idx >= 0:
            self.combo_cable_type.setCurrentIndex(idx)
            
        try:
            target_enum, target_field = self._get_active_target_field()
            tv = getattr(self.cable, 'target_value', None)
            if tv is not None:
                if target_enum in self._LENGTH_TARGETS:
                    target_field.setText(f"{unit_registry.to_display_length(tv):.4g}")
                else:
                    target_field.setText(f"{unit_registry.to_display_force(tv):.4g}")
        except Exception:
            pass
            
        saved_add_wt = getattr(self.cable, 'added_weight', 0.0)
        saved_proj_load = getattr(self.cable, 'projected_load', 0.0)
        self.txt_add_wt.setText(f"{self._si_to_dist_load(saved_add_wt):.4g}")
        self.txt_proj_load.setText(f"{self._si_to_dist_load(saved_proj_load):.4g}")

        self._simulate_refresh()

    def _populate_cable_sections(self):
        if not hasattr(self.model, 'cable_sections'): return
        self.combo_section.addItems(list(self.model.cable_sections.keys()))
        if self.cable.cable_section:
            idx = self.combo_section.findText(self.cable.cable_section.name)
            if idx >= 0:
                self.combo_section.setCurrentIndex(idx)

    def _update_active_inputs(self):
        """
        Locks/Unlocks inputs based on the target specification type.
        Mirrors SAP2000's parameter dependencies.
        """
        sel = self.combo_cable_type.currentText()
        
        for field in [self.txt_tens_i, self.txt_tens_j, self.txt_tens_h, 
                      self.txt_undef_max_sag, self.txt_undef_low_sag, self.txt_undef_len]:
            field.setReadOnly(True)
            field.setStyleSheet("background-color: #f0f0f0; color: #888;")

        def activate(field):
            field.setReadOnly(False)
            field.setStyleSheet("")

        if "Undeformed Length" in sel:
            activate(self.txt_undef_len)
        elif "Tension at I-End" in sel:
            activate(self.txt_tens_i)
        elif "Tension at J-End" in sel:
            activate(self.txt_tens_j)
        elif "Horizontal Tension" in sel:
            activate(self.txt_tens_h)
        elif "Maximum Vertical Sag" in sel:
            activate(self.txt_undef_max_sag)
        elif "Low-Point Vertical Sag" in sel:
            activate(self.txt_undef_low_sag)

    _LENGTH_TARGETS = {CableTargetType.UNDEFORMED_LENGTH,
                        CableTargetType.MAX_VERTICAL_SAG,
                        CableTargetType.LOW_POINT_SAG}
    _FORCE_TARGETS = {CableTargetType.TENSION_I,
                       CableTargetType.TENSION_J,
                       CableTargetType.HORIZONTAL_TENSION}

    def _get_active_target_field(self):
        sel = self.combo_cable_type.currentText()
        if "Undeformed Length" in sel:
            return CableTargetType.UNDEFORMED_LENGTH, self.txt_undef_len
        elif "Tension at I-End" in sel:
            return CableTargetType.TENSION_I, self.txt_tens_i
        elif "Tension at J-End" in sel:
            return CableTargetType.TENSION_J, self.txt_tens_j
        elif "Horizontal Tension" in sel:
            return CableTargetType.HORIZONTAL_TENSION, self.txt_tens_h
        elif "Maximum Vertical Sag" in sel:
            return CableTargetType.MAX_VERTICAL_SAG, self.txt_undef_max_sag
        elif "Low-Point Vertical Sag" in sel:
            return CableTargetType.LOW_POINT_SAG, self.txt_undef_low_sag
        raise ValueError(f"Unrecognized cable type selection: {sel!r}")

    @staticmethod
    def _dist_load_to_si(disp_val):
        dist_scale = unit_registry.force_scale / unit_registry.length_scale
        return disp_val / dist_scale

    @staticmethod
    def _si_to_dist_load(si_val):
        dist_scale = unit_registry.force_scale / unit_registry.length_scale
        return si_val * dist_scale

    def _get_EA_and_weight(self):
        """
        Pulls axial stiffness and distributed weight from the cable section
        currently assigned. Everything on the model (area, E, unit weight)
        is already stored in SI, per app convention -- only the user-typed
        display fields (added weight, projected load) need conversion.
        Returns (EA, weight_per_length, error_message) in SI (N, N/m).
        error_message is None if everything needed was found.
        """
        section = self.cable.cable_section
        if section is None:
            return None, None, "No cable section assigned -- pick one in Section Property."

        area = getattr(section, 'area', None)                   
        material = getattr(section, 'material', None)
        E = getattr(material, 'E', None) if material else None                  

        if not area or area <= 0 or E is None or E <= 0:
            return None, None, ("Cable section/material is missing area or E -- "
                                 "check Section Property assignment.")

        EA = E * area         

        unit_weight = getattr(material, 'unit_weight', 0.0) or 0.0
        self_weight = area * unit_weight           

        try:
            added_weight_disp = float(self.txt_add_wt.text() or 0.0)
        except ValueError:
            added_weight_disp = 0.0
        added_weight = self._dist_load_to_si(added_weight_disp)           

        try:
            proj_load_disp = float(self.txt_proj_load.text() or 0.0)
        except ValueError:
            proj_load_disp = 0.0

        weight_per_length = self_weight + added_weight
        warning = None
        if abs(proj_load_disp) > 1e-9:
            warning = ("Projected Uniform Gravity Load is set but not yet "
                        "supported by this solver -- it is being ignored.")

        return EA, weight_per_length, warning

    def _simulate_refresh(self):
        """
        Real catenary solve, driven by whichever cable-type target the user
        selected. Populates the point table, the planar plot, and the
        deformed/undeformed length & sag fields. Shows an inline message if
        the target is infeasible or inputs are incomplete.
        """
        self.lbl_solve_status.setText("")

        try:
            n_segs = max(int(self.txt_segments.text()), 1)
        except ValueError:
            n_segs = 1
        n_pts = n_segs + 1

        EA, weight_per_length, warning_or_error = self._get_EA_and_weight()
        if EA is None:
            self.table.setRowCount(0)
            self.plot_widget.clear()
            self.lbl_solve_status.setText(warning_or_error)
            return

        try:
            target_type, target_field = self._get_active_target_field()
            target_value_disp = float(target_field.text())
        except ValueError as e:
            self.table.setRowCount(0)
            self.plot_widget.clear()
            self.lbl_solve_status.setText(f"Enter a valid numeric target value ({e}).")
            return

        if target_type in self._LENGTH_TARGETS:
            target_value = unit_registry.from_display_length(target_value_disp)
        else:
            target_value = unit_registry.from_display_force(target_value_disp)

        node_i = (self.cable.node_i.x, self.cable.node_i.y, self.cable.node_i.z)
        node_j = (self.cable.node_j.x, self.cable.node_j.y, self.cable.node_j.z)

        result = solve_cable_geometry(
            node_i, node_j, weight_per_length, EA,
            target_type, target_value,
            gravity_dir=(0.0, 0.0, -1.0),                                   
            n_points=n_pts,
        )

        if not result.converged:
            self.table.setRowCount(0)
            self.plot_widget.clear()
            self.lbl_solve_status.setText(result.message)
            return

        if warning_or_error:                                                  
            self.lbl_solve_status.setStyleSheet("color: #b8860b;")
            self.lbl_solve_status.setText(warning_or_error)
        else:
            self.lbl_solve_status.setStyleSheet("color: #b00020;")

        L = unit_registry.to_display_length
        self.table.setRowCount(len(result.points))
        for i, pt in enumerate(result.points):
            self.table.setItem(i, 0, QTableWidgetItem(str(i + 1)))
            self.table.setItem(i, 1, QTableWidgetItem(f"{L(pt.xyz[0]):.4f}"))
            self.table.setItem(i, 2, QTableWidgetItem(f"{L(pt.xyz[1]):.4f}"))
            self.table.setItem(i, 3, QTableWidgetItem(f"{L(pt.xyz[2]):.4f}"))
            self.table.setItem(i, 4, QTableWidgetItem(f"{L(pt.sag):.4f}"))
            self.table.setItem(i, 5, QTableWidgetItem(f"{L(pt.s_unstressed):.4f}"))
            self.table.setItem(i, 6, QTableWidgetItem(f"{pt.rel_dist:.4f}"))                 

        F = unit_registry.to_display_force
        self.txt_def_len.setText(f"{L(result.deformed_length):.4f}")
        self.txt_undef_len.setText(f"{L(result.L0):.4f}")
        self.txt_def_max_sag.setText(f"{L(result.max_sag):.4f}")
        self.txt_undef_max_sag.setText(f"{L(result.max_sag):.4f}")
        if result.low_point_sag == result.low_point_sag:           
            self.txt_def_low_sag.setText(f"{L(result.low_point_sag):.4f}")
            self.txt_undef_low_sag.setText(f"{L(result.low_point_sag):.4f}")
        else:
            self.txt_def_low_sag.setText("N/A")
            self.txt_undef_low_sag.setText("N/A")
        self.txt_tens_i.setText(f"{F(result.T_i):.4f}")
        self.txt_tens_j.setText(f"{F(result.T_j):.4f}")
        self.txt_tens_h.setText(f"{F(result.H):.4f}")

        if result.is_compression_anywhere:
            note = "Note: solved state includes non-tension (compression/zero) segments."
            self.lbl_solve_status.setStyleSheet("color: #b00020;")
            self.lbl_solve_status.setText(
                (self.lbl_solve_status.text() + "  " + note).strip()
            )

        self.plot_widget.clear()
        L_arc = L(result.points[-1].s_unstressed) if result.points else 0.0
        self.plot_widget.plot([0, L_arc], [0, 0], pen=pg.mkPen('c', width=2))
        if result.points:
            x_vals = [L(p.s_unstressed) for p in result.points]
            y_vals = [-L(p.sag) for p in result.points]
            self.plot_widget.plot(x_vals, y_vals, pen=pg.mkPen('y', width=2))

    def accept(self):
        """Harvest all UI data and apply it to the cable object."""
        sec_name = self.combo_section.currentText()
        if hasattr(self.model, 'cable_sections') and sec_name in self.model.cable_sections:
            self.cable.cable_section = self.model.cable_sections[sec_name]

        self.cable.model_as_straight_frame = self.chk_straight_frame.isChecked()
        try:
            self.cable.number_of_segments = int(self.txt_segments.text())
        except ValueError:
            self.cable.number_of_segments = 1

        self.cable.target_type = self.combo_cable_type.currentText()
        try:
            target_enum, target_field = self._get_active_target_field()
            disp_target = float(target_field.text())
            if target_enum in self._LENGTH_TARGETS:
                self.cable.target_value = unit_registry.from_display_length(disp_target)
            else:
                self.cable.target_value = unit_registry.from_display_force(disp_target)
        except ValueError:
            pass

        try:
            self.cable.added_weight = self._dist_load_to_si(float(self.txt_add_wt.text()))
        except ValueError:
            self.cable.added_weight = 0.0

        try:
            self.cable.projected_load = self._dist_load_to_si(float(self.txt_proj_load.text()))
        except ValueError:
            self.cable.projected_load = 0.0
                                                  
        self._simulate_refresh()

        try:
            disp_len = float(self.txt_undef_len.text())
            self.cable.undeformed_length = unit_registry.from_display_length(disp_len)
        except ValueError:
            pass
            
        if hasattr(self, 'model') and hasattr(self.model, 'cables'):
            if self.cable.id in self.model.cables:
                self.model.cables[self.cable.id] = self.cable

        super().accept()
