from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGroupBox,
                             QCheckBox, QRadioButton, QLineEdit, QLabel,
                             QPushButton, QGridLayout, QFormLayout, QSpinBox)
from PyQt6.QtCore import Qt

class RelabelDialog(QDialog):
    def __init__(self, main_window):
        super().__init__(main_window)
        self.main_window = main_window
        self.setWindowTitle("Auto-Relabel Members")
        self.resize(550, 350)
        
        main_layout = QVBoxLayout(self)
        
        # --- TOP SECTION: Members & Sorting ---
        top_layout = QHBoxLayout()
        
        # 1. Members to Relabel
        members_group = QGroupBox("Target Members")
        members_layout = QVBoxLayout()
        self.chk_columns = QCheckBox("Columns")
        self.chk_beams = QCheckBox("Beams")
        self.chk_braces = QCheckBox("Braces")
        self.chk_areas = QCheckBox("Areas / Shells")
        self.chk_joints = QCheckBox("Joints (Nodes)")
        
        # Default selections
        self.chk_columns.setChecked(True)
        self.chk_beams.setChecked(True)
        
        members_layout.addWidget(self.chk_columns)
        members_layout.addWidget(self.chk_beams)
        members_layout.addWidget(self.chk_braces)
        members_layout.addWidget(self.chk_areas)
        members_layout.addWidget(self.chk_joints)
        members_layout.addStretch()
        members_group.setLayout(members_layout)
        
        # 2. Sorting Reference
        sort_group = QGroupBox("Plan View Sort Reference (X-Y)")
        sort_layout = QGridLayout()
        
        self.rad_lt_rb = QRadioButton("Left-Top --> Right-Bot")
        self.rad_rt_lb = QRadioButton("Right-Top --> Left-Bot")
        self.rad_lb_rt = QRadioButton("Left-Bot --> Right-Top")
        self.rad_rb_lt = QRadioButton("Right-Bot --> Left-Top")
        self.rad_lt_rb.setChecked(True) # Default
        
        sort_layout.addWidget(self.rad_lt_rb, 0, 0)
        sort_layout.addWidget(self.rad_rt_lb, 0, 1)
        sort_layout.addWidget(self.rad_lb_rt, 1, 0)
        sort_layout.addWidget(self.rad_rb_lt, 1, 1)
        
        # Storey Grouping
        self.chk_group_storeys = QCheckBox("Group and sort by Storeys (Z-Elevation)")
        self.chk_group_storeys.setChecked(True)
        sort_layout.addWidget(self.chk_group_storeys, 2, 0, 1, 2)
        
        sort_group.setLayout(sort_layout)
        
        top_layout.addWidget(members_group, 1)
        top_layout.addWidget(sort_group, 2)
        main_layout.addLayout(top_layout)
        
        # --- BOTTOM SECTION: Naming Rules ---
        naming_group = QGroupBox("Naming Rules")
        naming_layout = QFormLayout()
        
        self.edit_prefix = QLineEdit()
        self.edit_prefix.setPlaceholderText("Leave blank for smart prefix (C, B, S...)")
        
        self.spin_start_num = QSpinBox()
        self.spin_start_num.setRange(1, 99999)
        self.spin_start_num.setValue(1)
        
        naming_layout.addRow(QLabel("Custom Prefix Override:"), self.edit_prefix)
        naming_layout.addRow(QLabel("Start Numbering At:"), self.spin_start_num)
        naming_group.setLayout(naming_layout)
        
        main_layout.addWidget(naming_group)
        
        # --- BUTTON BOX ---
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        self.btn_ok = QPushButton("Apply Labels")
        self.btn_cancel = QPushButton("Cancel")
        
        # Connect to our custom sorting logic
        self.btn_ok.clicked.connect(self.apply_labels) 
        self.btn_cancel.clicked.connect(self.reject)
        
        btn_layout.addWidget(self.btn_ok)
        btn_layout.addWidget(self.btn_cancel)
        main_layout.addLayout(btn_layout)

    def apply_labels(self):
        """The mathematical backend that assigns physical names to mathematical IDs"""
        model = self.main_window.model
        if not model: 
            return

        do_cols = self.chk_columns.isChecked()
        do_beams = self.chk_beams.isChecked()
        do_braces = self.chk_braces.isChecked()
        do_areas = self.chk_areas.isChecked()
        do_nodes = self.chk_joints.isChecked()
        
        custom_prefix = self.edit_prefix.text().strip()
        start_num = self.spin_start_num.value()
        group_storeys = self.chk_group_storeys.isChecked()

        # 1. Determine spatial sorting direction
        tol = 1e-3
        def rounded(val): return round(val / tol) * tol

        if self.rad_lt_rb.isChecked(): 
            sort_func = lambda item: (-rounded(item['pt'][1]), rounded(item['pt'][0]))
        elif self.rad_rt_lb.isChecked(): 
            sort_func = lambda item: (-rounded(item['pt'][1]), -rounded(item['pt'][0]))
        elif self.rad_lb_rt.isChecked(): 
            sort_func = lambda item: (rounded(item['pt'][1]), rounded(item['pt'][0]))
        else: # rb_lt
            sort_func = lambda item: (rounded(item['pt'][1]), -rounded(item['pt'][0]))

        # Helper to get the top-center point of any element for accurate sorting
        def get_pt(obj):
            if hasattr(obj, 'x'): return (obj.x, obj.y, obj.z)
            if hasattr(obj, 'node_i'): 
                return ((obj.node_i.x + obj.node_j.x)/2.0, (obj.node_i.y + obj.node_j.y)/2.0, max(obj.node_i.z, obj.node_j.z))
            if hasattr(obj, 'nodes'): 
                xs = [n.x for n in obj.nodes]; ys = [n.y for n in obj.nodes]; zs = [n.z for n in obj.nodes]
                return (sum(xs)/len(xs), sum(ys)/len(ys), max(zs))
            return (0.0, 0.0, 0.0)

        # 2. Gather requested elements
        items = []
        if do_nodes:
            for n in model.nodes.values():
                items.append({'obj': n, 'pt': get_pt(n), 'def_prefix': 'N'})
        
        for el in model.elements.values():
            etype = getattr(el, 'element_type', 'Undefined')
            if do_cols and etype == "Column":
                items.append({'obj': el, 'pt': get_pt(el), 'def_prefix': 'C'})
            elif do_beams and etype == "Beam":
                items.append({'obj': el, 'pt': get_pt(el), 'def_prefix': 'B'})
            elif do_braces and etype == "Brace":
                items.append({'obj': el, 'pt': get_pt(el), 'def_prefix': 'V'})
                
        if do_areas and hasattr(model, 'area_elements'):
            for ae in model.area_elements.values():
                items.append({'obj': ae, 'pt': get_pt(ae), 'def_prefix': 'S'})

        if not items:
            self.reject()
            return

        # 3. Cluster elements by their Z-elevation (Storey Level)
        if group_storeys:
            z_vals = sorted(list(set(rounded(item['pt'][2]) for item in items)))
            clusters = {z: [] for z in z_vals}
            for item in items:
                clusters[rounded(item['pt'][2])].append(item)
        else:
            clusters = {0.0: items} # Throw them all in one bucket if storeys are disabled

        # 4. Sort and Apply Labels
        for z_idx, (z_val, cluster_items) in enumerate(sorted(clusters.items())):
            # CHANGED: Now generates "S1 ", "S2 ", etc. instead of just "1"
            storey_prefix = f"S{z_idx + 1} " if group_storeys else ""
            
            cluster_items.sort(key=sort_func)
            
            counters = {} 
            for item in cluster_items:
                prefix = custom_prefix if custom_prefix else item['def_prefix']
                if prefix not in counters:
                    counters[prefix] = start_num
                
                # Formula: [Storey][Prefix][Number] -> e.g., "S1 C101"
                item['obj'].label = f"{storey_prefix}{prefix}{counters[prefix]}"
                counters[prefix] += 1

        self.main_window.status.showMessage(f"Successfully relabeled {len(items)} elements based on geometry.")
        self.main_window.refresh_canvas()
        self.accept()