from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, 
                             QTableWidgetItem, QHeaderView, QPushButton, QTabWidget,
                             QWidget, QLabel)
from PyQt6.QtGui import QColor
from PyQt6.QtCore import Qt
import numpy as np

from core.units import unit_registry
from core.mesh import Node, FrameElement, AreaElement
from app.ui.theme import apply_dialog_style, COLORS

class ViewSpringMatrixDialog(QDialog):
    def __init__(self, matrix, parent=None):
        super().__init__(parent)
        apply_dialog_style(self)
        self.setWindowTitle("Assigned Joint Spring Stiffness")
        self.resize(550, 300)
        
        layout = QVBoxLayout(self)
        
        u_f = unit_registry.force_unit_name
        u_l = unit_registry.length_unit_name
        f_scale = unit_registry.force_scale
        l_scale = unit_registry.length_scale
        
        table = QTableWidget(6, 6)
        headers = ['U1', 'U2', 'U3', 'R1', 'R2', 'R3']
        table.setHorizontalHeaderLabels(headers)
        table.setVerticalHeaderLabels(headers)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        
        for i in range(6):
            for j in range(6):
                si_val = matrix[i, j]
                
                if i < 3 and j < 3: 
                    disp_val = si_val * (f_scale / l_scale)
                elif (i < 3 and j >= 3) or (i >= 3 and j < 3):
                    disp_val = si_val * f_scale
                else:
                    disp_val = si_val * (f_scale * l_scale)
                    
                item = QTableWidgetItem(f"{disp_val:g}")
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                item.setForeground(QColor(COLORS["text_primary"]))
                table.setItem(i, j, item)
        
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(table)
        
        legend_layout = QHBoxLayout()
        legend_layout.addWidget(QLabel(f"<b>Translational:</b> {u_f}/{u_l}"))
        legend_layout.addWidget(QLabel(f"<b>Coupled:</b> {u_f}/rad"))
        legend_layout.addWidget(QLabel(f"<b>Rotational:</b> {u_f}-{u_l}/rad"))
        layout.addLayout(legend_layout)
        
        btn_close = QPushButton("Close")
        btn_close.setObjectName("secondary")
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close)

class ObjectInfoDialog(QDialog):
    def __init__(self, obj, model, parent=None):
        super().__init__(parent)
        apply_dialog_style(self)
        self.obj = obj
        self.model = model
        
        if isinstance(self.obj, dict):
            self.obj_label = f"Link {self.obj.get('id')}"
        else:
            self.obj_label = getattr(self.obj, 'label', str(self.obj.id))

        if isinstance(self.obj, Node):
            self.setWindowTitle(f"Object Model - Joint Information (Label: {self.obj_label})")
        elif isinstance(self.obj, FrameElement):
            self.setWindowTitle(f"Object Model - Frame Information (Label: {self.obj_label})")
        elif isinstance(self.obj, AreaElement):
            self.setWindowTitle(f"Object Model - Area Information (Label: {self.obj_label})")
        elif isinstance(self.obj, dict):
            self.setWindowTitle(f"Object Model - Link Information (Label: {self.obj_label})")
        else:
            self.setWindowTitle(f"Object Model - Information (ID: {self.obj.id})")

        self.resize(750, 600)
        
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        
        self.tabs.addTab(self.create_location_tab(), "Location & Geometry")
        self.tabs.addTab(self.create_assignments_tab(), "Assignments")
        self.tabs.addTab(self.create_loads_tab(), "Loads")
        
        layout.addWidget(self.tabs)
        
        btn_box = QHBoxLayout()
        btn_box.addStretch()
        btn_ok = QPushButton("OK")
        btn_ok.setObjectName("primary")
        btn_ok.clicked.connect(self.accept)
        btn_box.addWidget(btn_ok)
        layout.addLayout(btn_box)

    def create_table(self, headers=None):
        table = QTableWidget()
        if headers:
            table.setColumnCount(len(headers))
            table.setHorizontalHeaderLabels(headers)
            table.horizontalHeader().setVisible(True)
        else:
            table.setColumnCount(2)
            table.horizontalHeader().setVisible(False)
            
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(True)
        
        if not headers:
            table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        else:
            table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
            
        return table

    def add_row(self, table, label, value, bold=False, sub_header=False):
        row = table.rowCount()
        table.insertRow(row)
        
        item_lbl = QTableWidgetItem(str(label))
        
        if sub_header:
            font = item_lbl.font()
            font.setBold(True)
            item_lbl.setFont(font)
            c = QColor(COLORS["bg_table_header"])
            fg = QColor(COLORS["text_primary"])
            item_lbl.setBackground(c)
            item_lbl.setForeground(fg)
        elif bold:
            font = item_lbl.font()
            font.setBold(True)
            item_lbl.setFont(font)
            c = QColor(COLORS["selection_bg"])
            fg = QColor(COLORS["selection_text"])
            item_lbl.setBackground(c)
            item_lbl.setForeground(fg)
        else:
            item_lbl.setForeground(QColor(COLORS["text_primary"]))

        table.setItem(row, 0, item_lbl)

        if isinstance(value, QWidget):
            table.setCellWidget(row, 1, value)
        else:
            item_val = QTableWidgetItem(str(value))
            if sub_header or bold:
                item_val.setFont(font)
                item_val.setBackground(c)
                item_val.setForeground(fg)
            else:
                item_val.setForeground(QColor(COLORS["text_primary"]))
            table.setItem(row, 1, item_val)

    def create_location_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        table = self.create_table()
        
        L_unit = unit_registry.length_unit_name
        def to_L(val): return unit_registry.to_display_length(val)

        if isinstance(self.obj, Node):
            self.add_row(table, "Joint Label", self.obj_label, bold=True)
            self.add_row(table, "Internal ID", self.obj.id)
            self.add_row(table, "Coordinates", "", sub_header=True)
            self.add_row(table, "X", f"{to_L(self.obj.x):.4f} {L_unit}")
            self.add_row(table, "Y", f"{to_L(self.obj.y):.4f} {L_unit}")
            self.add_row(table, "Z", f"{to_L(self.obj.z):.4f} {L_unit}")

        elif isinstance(self.obj, FrameElement):
            n1, n2 = self.obj.node_i, self.obj.node_j
            
            self.add_row(table, "Element Label", self.obj_label, bold=True)
            self.add_row(table, "Internal ID", self.obj.id)
            self.add_row(table, "Smart Type", getattr(self.obj, 'element_type', 'Undefined'))
            self.add_row(table, "Length", f"{to_L(self.obj.length()):.4f} {L_unit}")
            
            self.add_row(table, "Start Node (I)", f"Label: {getattr(n1, 'label', n1.id)}", sub_header=True)
            self.add_row(table, "Coordinates", f"({to_L(n1.x):.3f}, {to_L(n1.y):.3f}, {to_L(n1.z):.3f}) {L_unit}")
            
            self.add_row(table, "End Node (J)", f"Label: {getattr(n2, 'label', n2.id)}", sub_header=True)
            self.add_row(table, "Coordinates", f"({to_L(n2.x):.3f}, {to_L(n2.y):.3f}, {to_L(n2.z):.3f}) {L_unit}")

            self.add_row(table, "Rigid End Zones / Offsets", "", sub_header=True)
            
            e_off_i = getattr(self.obj, 'end_offset_i', 0.0)                                          
            e_off_j = getattr(self.obj, 'end_offset_j', 0.0)
            rz = getattr(self.obj, 'rigid_zone_factor', 0.0)

            self.add_row(table, "End Offset I", f"{to_L(e_off_i):.4f} {L_unit}")
            self.add_row(table, "End Offset J", f"{to_L(e_off_j):.4f} {L_unit}")
            self.add_row(table, "Rigid Zone Factor", f"{rz:.2f}")

        elif isinstance(self.obj, AreaElement):
            nodes = self.obj.nodes
            k = len(nodes)
            pts = [np.array([n.x, n.y, n.z], dtype=float) for n in nodes]

            topo = "4-Node Quad" if k == 4 else ("3-Node Triangle" if k == 3 else f"{k}-Node Polygon")
            self.add_row(table, "Area Label", self.obj_label, bold=True)
            self.add_row(table, "Internal ID", self.obj.id)
            self.add_row(table, "Smart Type", getattr(self.obj, 'element_type', 'Undefined'))
            self.add_row(table, "Topology", topo)

            edge_lengths_si = [float(np.linalg.norm(pts[(i + 1) % k] - pts[i])) for i in range(k)]
            perim_si = sum(edge_lengths_si)
            area_si = sum(
                0.5 * float(np.linalg.norm(np.cross(pts[i] - pts[0], pts[i + 1] - pts[0])))
                for i in range(1, k - 1)
            ) if k >= 3 else 0.0
            centroid = np.mean(pts, axis=0) if k else np.zeros(3)

            self.add_row(table, "Surface Area", f"{area_si * (unit_registry.length_scale ** 2):.4f} {L_unit}²")
            self.add_row(table, "Perimeter", f"{to_L(perim_si):.4f} {L_unit}")
            self.add_row(table, "Centroid (X, Y, Z)",
                         f"({to_L(centroid[0]):.3f}, {to_L(centroid[1]):.3f}, {to_L(centroid[2]):.3f}) {L_unit}")

            ins_off = getattr(self.obj, 'insertion_offset', 0.0)
            self.add_row(table, "Insertion Offset (Local 3)", f"{to_L(ins_off):.4f} {L_unit}")

            self.add_row(table, "Corner Nodes", "", sub_header=True)
            for i, n in enumerate(nodes):
                self.add_row(table, f"Node {i+1}",
                             f"Label: {getattr(n, 'label', n.id)} | ({to_L(n.x):.3f}, {to_L(n.y):.3f}, {to_L(n.z):.3f}) {L_unit}")

            self.add_row(table, "Mesh & Element Quality", "", sub_header=True)
            for i in range(k):
                j = (i + 1) % k
                self.add_row(table, f"Edge {i+1}→{j+1} Length", f"{to_L(edge_lengths_si[i]):.4f} {L_unit}")

            min_e, max_e = min(edge_lengths_si, default=0.0), max(edge_lengths_si, default=0.0)
            aspect = (max_e / min_e) if min_e > 1e-9 else 0.0
            self.add_row(table, "Aspect Ratio (Max/Min Edge)", f"{aspect:.2f}")

            if k >= 3:
                angles = []
                for i in range(k):
                    v1 = pts[(i - 1) % k] - pts[i]
                    v2 = pts[(i + 1) % k] - pts[i]
                    n1, n2 = np.linalg.norm(v1), np.linalg.norm(v2)
                    if n1 > 1e-9 and n2 > 1e-9:
                        cos_a = np.clip(np.dot(v1, v2) / (n1 * n2), -1.0, 1.0)
                        angles.append(float(np.degrees(np.arccos(cos_a))))
                if angles:
                    self.add_row(table, "Interior Angles (Min / Max)", f"{min(angles):.1f}° / {max(angles):.1f}°")

                n_vec = np.cross(pts[1] - pts[0], pts[-1] - pts[0])
                n_norm = np.linalg.norm(n_vec)
                if n_norm > 1e-9:
                    unit_n = n_vec / n_norm
                    self.add_row(table, "Local 3 Normal", f"({unit_n[0]:.3f}, {unit_n[1]:.3f}, {unit_n[2]:.3f})")
                    if k == 4:
                        warp_si = abs(float(np.dot(pts[3] - pts[0], unit_n)))
                        self.add_row(table, "Out-of-Plane Warp", f"{to_L(warp_si):.4f} {L_unit}")

            node_id_set = {n.id for n in nodes}
            adj_areas = [
                getattr(ae, 'label', f"A{ae.id}")
                for ae in getattr(self.model, 'area_elements', {}).values()
                if ae.id != self.obj.id and len(node_id_set.intersection(n.id for n in ae.nodes)) >= 2
            ]
            border_frames = [
                getattr(el, 'label', f"F{el.id}")
                for el in getattr(self.model, 'elements', {}).values()
                if el.node_i.id in node_id_set and el.node_j.id in node_id_set
            ]
            self.add_row(table, "Adjacent Mesh Elements",
                         f"{len(adj_areas)} ({', '.join(adj_areas[:8])}{'...' if len(adj_areas) > 8 else ''})" if adj_areas else "None (Unmeshed / Isolated)")
            self.add_row(table, "Bordering Frames",
                         f"{len(border_frames)} ({', '.join(border_frames[:8])}{'...' if len(border_frames) > 8 else ''})" if border_frames else "None")

        elif isinstance(self.obj, dict):
            link_type = self.obj.get('type', 'link')
            type_label = "1-Joint (Grounded)" if link_type == "link_1j" else "2-Joint"
            self.add_row(table, "Link Label", self.obj_label, bold=True)
            self.add_row(table, "Internal ID", self.obj.get('id'))
            self.add_row(table, "Link Type", type_label)

            self.add_row(table, "Connected Joints", "", sub_header=True)
            node_ids = self.obj.get('nodes', [])
            for i, nid in enumerate(node_ids):
                n = self.model.nodes.get(nid)
                role = "I" if i == 0 else "J"
                if n:
                    self.add_row(table, f"Node {role}", f"Label: {getattr(n, 'label', n.id)} | ({to_L(n.x):.3f}, {to_L(n.y):.3f}, {to_L(n.z):.3f}) {L_unit}")
                else:
                    self.add_row(table, f"Node {role}", f"Missing (ID {nid})")

            if len(node_ids) == 2:
                n1 = self.model.nodes.get(node_ids[0])
                n2 = self.model.nodes.get(node_ids[1])
                if n1 and n2:
                    length = ((n1.x - n2.x)**2 + (n1.y - n2.y)**2 + (n1.z - n2.z)**2)**0.5
                    self.add_row(table, "Length", f"{to_L(length):.4f} {L_unit}")

            self.add_row(table, "Local Axis Angle (Beta)", f"{self.obj.get('beta', 0.0):.1f}°")

        layout.addWidget(table)
        return tab

    def create_assignments_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        table = self.create_table()
        
        L_unit = unit_registry.length_unit_name
        def to_L(val): return unit_registry.to_display_length(val)

        if isinstance(self.obj, Node):
            self.add_row(table, "Restraints & Constraints", "", sub_header=True)
            restr = self.obj.restraints
            labels = ["U1", "U2", "U3", "R1", "R2", "R3"]
            active_restr = [labels[i] for i, val in enumerate(restr) if val]
            self.add_row(table, "Restraints", ", ".join(active_restr) if active_restr else "None")
            self.add_row(table, "Rigid Diaphragm", self.obj.diaphragm_name or "None")
            
            spring = getattr(self.obj, 'spring_matrix', None)
            if spring is not None:
                btn_view = QPushButton("View 6×6 Matrix...")
                btn_view.setObjectName("secondary")
                btn_view.clicked.connect(
                    lambda checked=False, m=spring: ViewSpringMatrixDialog(m, self).exec()
                )
                self.add_row(table, "Joint Spring", btn_view)
            else:
                self.add_row(table, "Joint Spring", "None")

        elif isinstance(self.obj, FrameElement):
            sec = self.obj.section
            self.add_row(table, "Section Property", sec.name, bold=True)
            self.add_row(table, "Material", sec.material.name)
            
            self.add_row(table, "Insertion Point & Offsets", "", sub_header=True)
            cp = getattr(self.obj, 'cardinal_point', 10)
            cp_map = {
                1: "Bottom Left", 2: "Bottom Center", 3: "Bottom Right",
                4: "Middle Left", 5: "Middle Center", 6: "Middle Right",
                7: "Top Left",    8: "Top Center",    9: "Top Right",
                10: "Centroid",   11: "Shear Center"
            }
            self.add_row(table, "Cardinal Point", f"{cp} - {cp_map.get(cp, 'Unknown')}")
            
            off_i = getattr(self.obj, 'joint_offset_i', [0.0, 0.0, 0.0])
            off_j = getattr(self.obj, 'joint_offset_j', [0.0, 0.0, 0.0])

            def fmt_list(lst):
                try:
                    vals = [to_L(float(x)) for x in lst]
                    return "(" + ", ".join([f"{val:.3f}" for val in vals]) + f") {L_unit}"
                except Exception:
                    return f"Error: {lst}"

            self.add_row(table, "Cardinal Offset I (Global)", fmt_list(off_i))
            self.add_row(table, "Cardinal Offset J (Global)", fmt_list(off_j))
            self.add_row(table, "Local Axis Angle (Beta)", f"{getattr(self.obj, 'beta_angle', 0.0):.1f}°")

            self.add_row(table, "Releases", "", sub_header=True)
            def fmt_rel(r):
                if not r or not any(r): return "None"
                labels = ["P", "V2", "V3", "T", "M22", "M33"]
                active = [labels[i] for i, val in enumerate(r) if val and i < 6]
                return ", ".join(active)

            self.add_row(table, "Start (I)", fmt_rel(getattr(self.obj, 'releases_i', [])))
            self.add_row(table, "End (J)", fmt_rel(getattr(self.obj, 'releases_j', [])))

            self.add_row(table, "Hinges", "", sub_header=True)
            frame_hinges = getattr(self.model, 'frame_hinges', {})
            elem_hinges = sorted(
                (h for h in frame_hinges.values() if h.element_id == self.obj.id),
                key=lambda h: h.rel_dist
            )
            if elem_hinges:
                for h in elem_hinges:
                    self.add_row(table, h.hinge_name, f"at {h.rel_dist:.3f} (rel.)")
            else:
                self.add_row(table, "Assigned Hinges", "None")

        elif isinstance(self.obj, AreaElement):
            sec = self.obj.section
            sec_cls = sec.__class__.__name__
            modeling_type = getattr(sec, 'modeling_type', 'True FEM (Shell)')
            is_tributary = (modeling_type == "Tributary Area")

            self.add_row(table, "Area Section Property", sec.name, bold=True)

            self.add_row(table, "Section & Formulation", "", sub_header=True)
            if is_tributary:
                self.add_row(table, "Category", "Slab (Tributary Area)")
                self.add_row(table, "Structural Role", "Load Transfer Only (Not a FEM Shell)")
            elif sec_cls == "ShellSection":
                shell_type = getattr(sec, 'shell_type', 'Shell - Thin')
                self.add_row(table, "Category", "Shell")
                self.add_row(table, "Shell Behavior Type", shell_type)

                if shell_type in ("Shell - Thin", "Plate - Thin"):
                    form_code = getattr(sec, 'thin_formulation', 'DKQ')
                    form_str = "True Kirchhoff (DKQ)" if form_code == "DKQ" else "MITC4 (Mindlin)"
                elif "Thick" in shell_type:
                    form_str = "MITC4 (Reissner-Mindlin w/ Transverse Shear)"
                elif shell_type == "Membrane":
                    form_str = "In-Plane Membrane Only (No Bending)"
                else:
                    form_str = "Layered / Nonlinear Shell"
                self.add_row(table, "Bending Formulation", form_str)

                active_action = (
                    "Membrane + Bending" if "Shell" in shell_type else
                    ("Bending Only" if "Plate" in shell_type else "In-Plane Membrane Only")
                )
                self.add_row(table, "Active Stress Action", active_action)

            elif sec_cls == "PlaneSection":
                self.add_row(table, "Category", "Plane (2D Continuum)")
                self.add_row(table, "Plane Type", getattr(sec, 'plane_type', 'Plane-Stress'))
                self.add_row(table, "Incompatible Modes", "Yes" if getattr(sec, 'incompatible_modes', False) else "No")

            elif sec_cls == "AsolidSection":
                self.add_row(table, "Category", "Axisymmetric Solid (Asolid)")
                self.add_row(table, "Coordinate System", getattr(sec, 'coord_system', 'GLOBAL'))
                arc = getattr(sec, 'arc_degrees', 0.0)
                self.add_row(table, "Arc Angle", f"{arc:g}°" if arc != 0 else "0° (1 radian)")
                self.add_row(table, "Incompatible Modes", "Yes" if getattr(sec, 'incompatible_modes', False) else "No")
            else:
                self.add_row(table, "Category", sec_cls.replace("Section", ""))

            self.add_row(table, "Thickness & Offset", "", sub_header=True)
            if is_tributary:
                self.add_row(table, "Slab Thickness (h)", f"{to_L(getattr(sec, 'membrane_thickness', 0.0)):.4f} {L_unit}")
            elif sec_cls == "ShellSection":
                self.add_row(table, "Membrane Thickness", f"{to_L(getattr(sec, 'membrane_thickness', 0.0)):.4f} {L_unit}")
                self.add_row(table, "Bending Thickness", f"{to_L(getattr(sec, 'bending_thickness', 0.0)):.4f} {L_unit}")
            elif hasattr(sec, 'thickness'):
                self.add_row(table, "Thickness", f"{to_L(sec.thickness):.4f} {L_unit}")

            ins_off = getattr(self.obj, 'insertion_offset', 0.0)
            self.add_row(table, "Insertion Offset (Local 3)",
                         f"{to_L(ins_off):.4f} {L_unit}" if abs(ins_off) > 1e-9 else "0.0 (Mid-Surface at Joints)")

            self.add_row(table, "Material & Orientation", "", sub_header=True)
            if hasattr(sec, 'material') and sec.material:
                mat = sec.material
                mat_type = getattr(mat, 'mat_type', '')
                self.add_row(table, "Material", f"{mat.name} ({mat_type})" if mat_type else mat.name)
            else:
                self.add_row(table, "Material", "None")
            self.add_row(table, "Material Angle", f"{getattr(sec, 'material_angle', 0.0):.1f}°")

            self.add_row(table, "Meshing & Stiffness Modifiers", "", sub_header=True)
            if is_tributary:
                mesh_status = "Skipped (Tributary Area transfers loads to beams)"
            elif len(self.obj.nodes) == 4:
                mesh_status = "Eligible for Auto Quad Mesh (N×M or Max Size)"
            else:
                mesh_status = f"Fixed ({len(self.obj.nodes)}-Node element; quad mesher requires 4 nodes)"
            self.add_row(table, "Auto-Mesh Status", mesh_status)

            mods = getattr(sec, 'stiffness_modifiers', {}) or {}
            non_unit = {k: v for k, v in mods.items() if abs(float(v) - 1.0) > 1e-6}
            if non_unit:
                for k_mod, v_mod in non_unit.items():
                    self.add_row(table, f"Modifier ({k_mod})", f"{v_mod:g}")
            else:
                self.add_row(table, "Stiffness Modifiers", "Default (All 1.0)")

        elif isinstance(self.obj, dict):
            prop_name = self.obj.get('prop_name', 'None')
            self.add_row(table, "Link Property", prop_name, bold=True)

            prop = getattr(self.model, 'link_properties', {}).get(prop_name)
            if prop:
                fixed = prop.get('is_fixed', [False]*6)
                labels = ["U1", "U2", "U3", "R1", "R2", "R3"]
                active_fixed = [labels[i] for i, val in enumerate(fixed) if val]
                self.add_row(table, "Fixed DOFs", ", ".join(active_fixed) if active_fixed else "None")

                stiffness = prop.get('stiffness')
                if stiffness is not None:
                    btn_view = QPushButton("View 6×6 Matrix...")
                    btn_view.setObjectName("secondary")
                    btn_view.clicked.connect(
                        lambda checked=False, m=stiffness: ViewSpringMatrixDialog(m, self).exec()
                    )
                    self.add_row(table, "Stiffness", btn_view)
                else:
                    self.add_row(table, "Stiffness", "None")

                self.add_row(table, "Mass & Weight", "", sub_header=True)
                self.add_row(table, "Mass", f"{prop.get('mass', 0.0):g}")
                self.add_row(table, "Weight", f"{prop.get('weight', 0.0):g}")

                damping = prop.get('damping')
                if damping is not None and hasattr(damping, 'any') and damping.any():
                    btn_damp = QPushButton("View 6×6 Matrix...")
                    btn_damp.setObjectName("secondary")
                    btn_damp.clicked.connect(
                        lambda checked=False, m=damping: ViewSpringMatrixDialog(m, self).exec()
                    )
                    self.add_row(table, "Damping", btn_damp)
                else:
                    self.add_row(table, "Damping", "None")
            else:
                self.add_row(table, "Stiffness", "Property Not Found")

        layout.addWidget(table)
        return tab

    def create_loads_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        headers = ["Target", "Type", "Pattern", "Dir", "Value", "Dist/Loc"]
        table = self.create_table(headers)
        
        found_loads = False
        
        for load in self.model.loads:
            if isinstance(self.obj, Node):
                if hasattr(load, 'node_id') and load.node_id == self.obj.id:
                    found_loads = True
                    self._add_load_row(table, load, "Joint")
                    
            elif isinstance(self.obj, FrameElement):
                if hasattr(load, 'element_id') and load.element_id == self.obj.id:
                    found_loads = True
                    self._add_load_row(table, load, "Member")
                elif hasattr(load, 'node_id'):
                    target = None
                    if load.node_id == self.obj.node_i.id:
                        target = f"Node I ({getattr(self.obj.node_i, 'label', self.obj.node_i.id)})"
                    elif load.node_id == self.obj.node_j.id:
                        target = f"Node J ({getattr(self.obj.node_j, 'label', self.obj.node_j.id)})"
                    if target:
                        found_loads = True
                        self._add_load_row(table, load, target)
                        
            elif isinstance(self.obj, AreaElement):
                if hasattr(load, 'area_id') and load.area_id == self.obj.id:
                    found_loads = True
                    self._add_load_row(table, load, "Area")
        
        if not found_loads:
            row = table.rowCount()
            table.insertRow(row)
            empty_item = QTableWidgetItem("No Loads Assigned")
            empty_item.setForeground(QColor(COLORS["text_secondary"]))
            table.setItem(row, 0, empty_item)
            table.setSpan(row, 0, 1, 6)

        layout.addWidget(table)
        return tab

    def _add_load_row(self, table, load, target_str):
        row = table.rowCount()
        table.insertRow(row)
        
        F_unit = unit_registry.force_unit_name
        L_unit = unit_registry.length_unit_name
        M_unit = f"{F_unit}.{L_unit}"              
        W_unit = unit_registry.distributed_load_unit               
        
        def to_F(val): return unit_registry.to_display_force(val)
        def to_L(val): return unit_registry.to_display_length(val)
        
        pattern = getattr(load, 'pattern_name', 'Unknown')
        
        if hasattr(load, 'force') and hasattr(load, 'dist'):
            l_type = getattr(load, 'load_type', "Force")                      
            disp_type = f"Point {l_type}"
            coord = getattr(load, 'coord_system', 'Global')
            direction = getattr(load, 'direction', '?')
            disp_dir = f"{coord}-{direction}"
            raw_val = float(load.force)
            if l_type == "Moment":
                disp_val = f"{to_F(raw_val) * unit_registry.length_scale:.2f} {M_unit}"
            else:
                disp_val = f"{to_F(raw_val):.2f} {F_unit}"
            dist = float(load.dist)
            if getattr(load, 'is_relative', False):
                disp_loc = f"{dist*100:.1f}% (Rel)"
            else:
                disp_loc = f"{to_L(dist):.3f} {L_unit} (Abs)"

        elif hasattr(load, 'wx') and hasattr(load, 'wy') and hasattr(load, 'wz'):
            disp_type = "Distributed"
            comps = []
            if load.wx != 0: comps.append(f"Wx={to_F(load.wx)/unit_registry.length_scale:.2f}")
            if load.wy != 0: comps.append(f"Wy={to_F(load.wy)/unit_registry.length_scale:.2f}")
            if load.wz != 0: comps.append(f"Wz={to_F(load.wz)/unit_registry.length_scale:.2f}")
            disp_val = " / ".join(comps) + f" {W_unit}"
            coord = getattr(load, 'coord_system', 'Global')
            proj = " (Proj)" if getattr(load, 'projected', False) else ""
            disp_dir = f"{coord}{proj}"
            disp_loc = "Full Span"

        elif hasattr(load, 'ux'):                        
            disp_type = "Ground Disp."
            disp_dir = "Global"
            disp_loc = "Joint"
            val_strs = []
            if getattr(load, 'ux', 0) != 0: val_strs.append(f"Ux={to_L(load.ux):.3f}")
            if getattr(load, 'uy', 0) != 0: val_strs.append(f"Uy={to_L(load.uy):.3f}")
            if getattr(load, 'uz', 0) != 0: val_strs.append(f"Uz={to_L(load.uz):.3f}")
            if getattr(load, 'rx', 0) != 0: val_strs.append(f"Rx={load.rx:.4f}")
            if getattr(load, 'ry', 0) != 0: val_strs.append(f"Ry={load.ry:.4f}")
            if getattr(load, 'rz', 0) != 0: val_strs.append(f"Rz={load.rz:.4f}")
            disp_val = f"{', '.join(val_strs)} [{L_unit}, rad]" if val_strs else "None"

        elif hasattr(load, 'fx'):                        
            disp_type = "Joint Force"
            disp_dir = "Global"
            disp_loc = "Joint"
            val_strs = []
            if load.fx != 0: val_strs.append(f"Fx={to_F(load.fx):.2f}")
            if load.fy != 0: val_strs.append(f"Fy={to_F(load.fy):.2f}")
            if load.fz != 0: val_strs.append(f"Fz={to_F(load.fz):.2f}")
            if load.mx != 0: val_strs.append(f"Mx={to_F(load.mx)*unit_registry.length_scale:.2f}")
            if load.my != 0: val_strs.append(f"My={to_F(load.my)*unit_registry.length_scale:.2f}")
            if load.mz != 0: val_strs.append(f"Mz={to_F(load.mz)*unit_registry.length_scale:.2f}")
            disp_val = f"{', '.join(val_strs)} [{F_unit}, {M_unit}]"

        elif hasattr(load, 'uniform_load'):
            disp_type = "Area Uniform"
            disp_dir = getattr(load, 'load_direction', 'Gravity')
            disp_val = f"{to_F(load.uniform_load) / (unit_registry.length_scale**2):.2f} {F_unit}/{L_unit}²"
            disp_loc = "Full Area"

        elif hasattr(load, 'gx'):
            disp_type = "Area Gravity"
            disp_dir = getattr(load, 'coord_system', 'GLOBAL')
            vals = []
            if load.gx != 0: vals.append(f"Gx={load.gx}")
            if load.gy != 0: vals.append(f"Gy={load.gy}")
            if load.gz != 0: vals.append(f"Gz={load.gz}")
            disp_val = ", ".join(vals) + " (Mult)"
            disp_loc = "Full Area"

        else:
            disp_type = "Unknown"
            disp_dir = "-"
            disp_val = "Error reading data"
            disp_loc = "-"

        for col, text in enumerate((target_str, disp_type, pattern, disp_dir, disp_val, disp_loc)):
            item = QTableWidgetItem(str(text))
            item.setForeground(QColor(COLORS["text_primary"]))
            table.setItem(row, col, item)
