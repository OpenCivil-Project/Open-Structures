from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, 
                             QTableWidgetItem, QHeaderView, QPushButton, QTabWidget,
                             QWidget)
from PyQt6.QtGui import QColor
from core.units import unit_registry
from core.mesh import Node, FrameElement, AreaElement                             

class ObjectInfoDialog(QDialog):
    def __init__(self, obj, model, parent=None):
        super().__init__(parent)
        self.obj = obj
        self.model = model
        
        self.obj_label = getattr(self.obj, 'label', str(self.obj.id))
        
        if isinstance(self.obj, Node):
            self.setWindowTitle(f"Object Model - Joint Information (Label: {self.obj_label})")
        elif isinstance(self.obj, FrameElement):
            self.setWindowTitle(f"Object Model - Frame Information (Label: {self.obj_label})")
        elif isinstance(self.obj, AreaElement):
            self.setWindowTitle(f"Object Model - Area Information (Label: {self.obj_label})")
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
        item_val = QTableWidgetItem(str(value))
        
        if sub_header:
            font = item_lbl.font()
            font.setBold(True)
            item_lbl.setFont(font)
            item_val.setFont(font)
            c = QColor("lightgray")
            item_lbl.setBackground(c)
            item_val.setBackground(c)
        elif bold:
            font = item_lbl.font()
            font.setBold(True)
            item_lbl.setFont(font)
            item_val.setFont(font)
            c = QColor("aliceblue") 
            item_lbl.setBackground(c)
            item_val.setBackground(c)

        table.setItem(row, 0, item_lbl)
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
            self.add_row(table, "Area Label", self.obj_label, bold=True)
            self.add_row(table, "Internal ID", self.obj.id)
            self.add_row(table, "Smart Type", getattr(self.obj, 'element_type', 'Undefined'))
            
            self.add_row(table, "Corner Nodes", "", sub_header=True)
            for i, n in enumerate(self.obj.nodes):
                self.add_row(table, f"Node {i+1}", f"Label: {getattr(n, 'label', n.id)} | ({to_L(n.x):.3f}, {to_L(n.y):.3f}, {to_L(n.z):.3f}) {L_unit}")

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
                except:
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

        elif isinstance(self.obj, AreaElement):
            sec = self.obj.section
            self.add_row(table, "Area Section Property", sec.name, bold=True)
            self.add_row(table, "Section Type", sec.__class__.__name__.replace("Section", ""))
            
            if hasattr(sec, 'material') and sec.material:
                self.add_row(table, "Material", sec.material.name)
                
            self.add_row(table, "Geometry", "", sub_header=True)
            if hasattr(sec, 'thickness'):
                self.add_row(table, "Thickness", f"{to_L(sec.thickness):.4f} {L_unit}")
            if hasattr(sec, 'membrane_thickness'):
                self.add_row(table, "Membrane Thickness", f"{to_L(sec.membrane_thickness):.4f} {L_unit}")
            if hasattr(sec, 'bending_thickness'):
                self.add_row(table, "Bending Thickness", f"{to_L(sec.bending_thickness):.4f} {L_unit}")

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
            table.setItem(row, 0, QTableWidgetItem("No Loads Assigned"))
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

        table.setItem(row, 0, QTableWidgetItem(target_str))
        table.setItem(row, 1, QTableWidgetItem(disp_type))
        table.setItem(row, 2, QTableWidgetItem(pattern))
        table.setItem(row, 3, QTableWidgetItem(disp_dir))
        table.setItem(row, 4, QTableWidgetItem(disp_val))
        table.setItem(row, 5, QTableWidgetItem(disp_loc))
