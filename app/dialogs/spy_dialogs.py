import sys
import json
import os
import numpy as np
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QTableWidget, 
                             QTableWidgetItem, QHeaderView, QLabel, QWidget, QComboBox, QSlider)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from mpl_toolkits.mplot3d import Axes3D

from core.units import unit_registry
from PyQt6.QtCore import Qt, pyqtSignal

class MemberAnalyzer:
    """
    Standalone element force analyzer — the single source of truth for NVM results.

    Uses the pre-saved k and T matrices from the solver JSON (ground truth),
    NOT recomputed matrices.  ForceDiagramBuilder imports this class so that
    any future fix made here propagates automatically to the 3D canvas diagrams.

    Mirrors the calculation logic of FBDViewerDialog.calculate_forces() and
    FBDViewerDialog._calculate_nvm_data() — do NOT diverge from those methods.
    """

    def __init__(self, element, model, num_stations=21,
                 displacements=None, matrices_path=None):
        self.el          = element
        self.model       = model
        self.n_stations  = num_stations

        self.L_clear  = self.el.length()
        self.stations = np.linspace(0, self.L_clear, num_stations)
        self.P  = np.zeros(num_stations)
        self.V2 = np.zeros(num_stations)
        self.V3 = np.zeros(num_stations)
        self.M2 = np.zeros(num_stations)
        self.M3 = np.zeros(num_stations)
        self.end_forces = np.zeros(12)

        self._k   = None
        self._t   = None
        self._fef = np.zeros(12)
        self._matrices_loaded = False

        self._displacements = displacements

        self._load_matrices(matrices_path)
        self._calculate()

    def _load_matrices(self, matrices_path):
        resolved = None
        active_results   = getattr(self.model, 'results', {}) or {}
        active_mat_path  = (active_results.get("matrices_path") or
                            active_results.get("matrices_file"))

        if matrices_path and os.path.exists(matrices_path):
            resolved = matrices_path
        elif active_mat_path and os.path.exists(active_mat_path):
            resolved = active_mat_path
        elif hasattr(self.model, "file_path") and self.model.file_path:
            fallback = self.model.file_path.replace(".mf", "_matrices.json")
            if os.path.exists(fallback):
                resolved = fallback

        if not resolved:
            print(f"[MemberAnalyzer] Warning: matrices file not found for "
                  f"element {self.el.id}. Forces will be zero.")
            return

        try:
            with open(resolved, "r") as f:
                data = json.load(f)
            str_id = str(self.el.id)
            if str_id in data:
                self._k   = np.array(data[str_id]["k"])
                self._t   = np.array(data[str_id]["t"])
                self._fef = np.array(data[str_id]["fef"])
                self._matrices_loaded = True
            else:
                print(f"[MemberAnalyzer] Element {self.el.id} not in matrices file.")
        except Exception as e:
            print(f"[MemberAnalyzer] Error loading matrices: {e}")

    def _calculate(self):
        if not self._matrices_loaded:
            return

        el     = self.el
        n1_str = str(el.node_i.id)
        n2_str = str(el.node_j.id)

        if self._displacements is not None:
            disp_dict = self._displacements
        else:
            res = getattr(self.model, 'results', {}) or {}
            disp_dict = res.get("_base_displacements",
                                res.get("displacements", {}))

        u1 = np.array(disp_dict.get(n1_str, [0.0] * 6))
        u2 = np.array(disp_dict.get(n2_str, [0.0] * 6))
        u_global = np.concatenate([u1, u2])

        self.end_forces = self._k @ (self._t @ u_global) + self._fef

        Fx1, Fy1, Fz1 = self.end_forces[0], self.end_forces[1], self.end_forces[2]
        Mx1, My1, Mz1 = self.end_forces[3], self.end_forces[4], self.end_forces[5]

        L = self.L_clear
        if L < 1e-9:
            return

        R_3x3 = self._t[0:3, 0:3]

        w_loc       = np.zeros(3)
        point_loads = []

        res              = getattr(self.model, 'results', {}) or {}
        active_case_name = res.get("info", {}).get("case_name", "")

        if active_case_name and hasattr(self.model, 'load_cases'):
            if active_case_name in self.model.load_cases:
                active_case = self.model.load_cases[active_case_name]
                for pat_name, scale_factor in active_case.loads:
                    if pat_name in getattr(self.model, 'load_patterns', {}):
                        pat = self.model.load_patterns[pat_name]
                        if getattr(pat, 'self_weight_multiplier', 0) > 0:
                            area    = getattr(el.section, 'A', 0)
                            density = getattr(el.section.material, 'density', 0)
                            w_sw_mag    = area * density * pat.self_weight_multiplier * scale_factor
                            w_sw_global = np.array([0.0, 0.0, -w_sw_mag])
                            w_loc      += R_3x3 @ w_sw_global

        for load in self.model.loads:
            if getattr(load, 'element_id', None) != int(self.el.id):
                continue
            is_local = getattr(load, 'coord_system', 'Global').lower() == 'local'

            if hasattr(load, 'wx'):                                            
                w_vec = np.array([load.wx, load.wy, load.wz])
                if not is_local:
                    w_vec = R_3x3 @ w_vec
                w_loc += w_vec

            elif hasattr(load, 'force'):                                 
                a       = load.dist * L if getattr(load, 'is_relative', False) else load.dist
                dir_map = {'X': 0, 'Y': 1, 'Z': 2, '1': 0, '2': 1, '3': 2}
                idx     = dir_map.get(str(getattr(load, 'direction', 'Z')).upper(), 2)
                vec     = np.zeros(3)
                vec[idx] = load.force
                if not is_local:
                    vec = R_3x3 @ vec
                l_type = getattr(load, 'load_type', 'Force').lower()
                if l_type == 'moment':
                    point_loads.append({'a': a, 'F': np.zeros(3), 'M': vec})
                else:
                    point_loads.append({'a': a, 'F': vec,          'M': np.zeros(3)})

        for i, x in enumerate(self.stations):
            P_val  = -Fx1 - w_loc[0] * x
            V2_val = Fy1 + w_loc[1] * x
            V3_val = -(Fz1 + w_loc[2] * x)
            M3_val =  Mz1 - Fy1 * x - w_loc[1] * (x ** 2) / 2.0
            M2_val =  My1 + Fz1 * x + w_loc[2] * (x ** 2) / 2.0

            for pl in point_loads:
                a = pl['a']
                if x > a:
                    dist_x  = x - a
                    P_val  -= pl['F'][0]
                    V2_val += pl['F'][1]
                    V3_val -= pl['F'][2]
                    M3_val += -pl['F'][1] * dist_x - pl['M'][2]
                    M2_val += pl['F'][2] * dist_x - pl['M'][1]

            self.P[i]  = P_val
            self.V2[i] = V2_val
            self.V3[i] = V3_val
            self.M3[i] = M3_val
            self.M2[i] = M2_val

class MatrixSpyDialog(QDialog):
    def __init__(self, element_id, model, matrices_path, parent=None):
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle(f"Element {element_id} - Internal Matrices Spy")
        self.resize(900, 600)
        self.element_id = str(element_id)
        self.model = model
        self.matrices_data = self._load_json(matrices_path)
        
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs)
        
        self.tab_k = QWidget(); self.tab_k_layout = QVBoxLayout(self.tab_k)
        tabs.addTab(self.tab_k, "Local Stiffness [k]")
        
        self.tab_t = QWidget(); self.tab_t_layout = QVBoxLayout(self.tab_t)
        tabs.addTab(self.tab_t, "Transformation [T]")
        
        self.tab_fef = QWidget(); self.tab_fef_layout = QVBoxLayout(self.tab_fef)
        tabs.addTab(self.tab_fef, "Fixed End Forces (FEE)")

        self._populate_ui()

    def _load_json(self, path):
        if not os.path.exists(path): return {}
        with open(path, 'r') as f: return json.load(f)

    def _populate_ui(self):
        if self.element_id not in self.matrices_data:
            self.tab_k_layout.addWidget(QLabel("No matrix data found."))
            return
        data = self.matrices_data[self.element_id]
        self._add_matrix_table(self.tab_k_layout, data['k'], "12x12 Local Stiffness")
        self._add_matrix_table(self.tab_t_layout, data['t'], "12x12 Transformation Matrix")
        fef_col = [[x] for x in data['fef']]
        self._add_matrix_table(self.tab_fef_layout, fef_col, "12x1 Fixed End Force Vector")

    def _add_matrix_table(self, layout, matrix_data, title):
        if not matrix_data: return
        lbl = QLabel(title); lbl.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        layout.addWidget(lbl)
        rows = len(matrix_data); cols = len(matrix_data[0])
        table = QTableWidget(rows, cols)
        for r in range(rows):
            for c in range(cols):
                val = matrix_data[r][c]
                txt = f"{val:.4e}" if (abs(val)>1e7 or (abs(val)<1e-4 and abs(val)>0)) else f"{val:.4f}"
                item = QTableWidgetItem(txt)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if abs(val) < 1e-9: item.setForeground(Qt.GlobalColor.gray)
                table.setItem(r, c, item)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(table)

class FBDViewerDialog(QDialog):
                                                   
    COLORS = {
        'beam': '#000000',                  
        'node': '#000000',                   
        'axial': '#000000',                    
        'shear': "#000000",                     
        'moment': '#000000',                       
        'torsion': '#000000',
        'deflection': '#000000'                                        
    }
    
    inspection_location_changed = pyqtSignal(object, float)
    inspection_closed = pyqtSignal()

    def __init__(self, element_id, model, results_path, matrices_path, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Element {element_id} - Free Body Diagrams")
        self.setFixedSize(650, 700)
        
        self.element_id = str(element_id)
        self.model = model
        
        self.element = self.model.elements[int(self.element_id)] 
        
        self.results = self._load_json(results_path)
        self.matrices = self._load_json(matrices_path)
        
        self.beam_length = self.element.length()                               
        self.beam_length_display = unit_registry.to_display_length(self.beam_length)
        
        self.forces_base = self.calculate_forces()
        self.forces = self._convert_forces_to_display()
        
        self._nvm_cache = self._calculate_nvm_data() if self.forces_base is not None else None
        
        self.force_unit = unit_registry.force_unit_name
        self.length_unit = unit_registry.length_unit_name
        self.moment_unit = f"{self.force_unit}·{self.length_unit}"
        
        layout = QVBoxLayout(self)
        
        info_text = (f"Element Length: {self.beam_length_display:.3f} {self.length_unit}  |  "
                    f"Units: Force [{self.force_unit}], Moment [{self.moment_unit}]")
        unit_label = QLabel(info_text)
        unit_label.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        unit_label.setStyleSheet("color: #555; padding: 5px;")
        layout.addWidget(unit_label)
        
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        
        self.add_axial_tab()
        self.add_Minor_axis_tab()
        self.add_Major_axis_tab()
        self.add_torsion_tab()
        self.add_nvm_tab()
        
    def _load_json(self, path):
        if not os.path.exists(path): return {}
        with open(path, 'r') as f: return json.load(f)

    def calculate_forces(self):
        if self.element_id not in self.matrices: return None
        if int(self.element_id) not in self.model.elements: return None

        el = self.model.elements[int(self.element_id)]
        k = np.array(self.matrices[self.element_id]['k'])
        t = np.array(self.matrices[self.element_id]['t'])
        fef = np.array(self.matrices[self.element_id]['fef'])
        
        n1, n2 = str(el.node_i.id), str(el.node_j.id)
        
        base_dict = self.results.get("_base_displacements", self.results.get("displacements", {}))
        u1 = base_dict.get(n1, [0]*6)
        u2 = base_dict.get(n2, [0]*6)
        
        u_global = np.array(u1 + u2)

        return k @ (t @ u_global) + fef

    def _convert_forces_to_display(self):
        if self.forces_base is None: return None
        
        forces_display = np.zeros(12)
        for i in range(12):
            if i % 6 < 3:                                 
                forces_display[i] = unit_registry.to_display_force(self.forces_base[i])
            else:                                  
                forces_display[i] = unit_registry.to_display_force(self.forces_base[i])
        return forces_display

    def _calculate_nvm_data(self):
        L_full = self.beam_length
        ri = getattr(self.element, 'end_offset_i', 0.0)
        rj = getattr(self.element, 'end_offset_j', 0.0)
        L_clear = L_full - ri - rj
        
        Defl_2_Abs = np.zeros(101); Defl_3_Abs = np.zeros(101)
        stations = np.linspace(ri, L_full - rj, 101)
        
        Fx1, Fy1, Fz1, Mx1, My1, Mz1 = self.forces_base[0:6]
        
        t_matrix = np.array(self.matrices[self.element_id]['t'])
        R_3x3 = t_matrix[0:3, 0:3] 
        
        el = self.element
        n1 = str(el.node_i.id)
        n2 = str(el.node_j.id)
        base_dict = self.results.get("_base_displacements", self.results.get("displacements", {}))
        u1_disp = base_dict.get(n1, [0.0]*6)
        u2_disp = base_dict.get(n2, [0.0]*6)
        u_global = np.array(u1_disp + u2_disp)
        
        u_local = t_matrix @ u_global
        u1, v1, w1, thx1, thy1, thz1 = u_local[0:6]
        u2, v2, w2, thx2, thy2, thz2 = u_local[6:12]
        
        w_loc = np.zeros(3)
        point_loads = []

        active_case_name = self.results.get("info", {}).get("case_name", "")
        
        if active_case_name in self.model.load_cases:
            active_case = self.model.load_cases[active_case_name]
            
            for pat_name, scale_factor in active_case.loads:
                if pat_name in self.model.load_patterns:
                    pat = self.model.load_patterns[pat_name]
                    
                    if pat.self_weight_multiplier > 0:
                        area = getattr(self.element.section, 'A', 0)
                        density = getattr(self.element.section.material, 'density', 0)
                        
                        w_sw_mag = area * density * pat.self_weight_multiplier * scale_factor
                        
                        w_sw_global = np.array([0.0, 0.0, -w_sw_mag])
                        w_sw_local = R_3x3 @ w_sw_global
                        
                        w_loc += w_sw_local
        
        for load in self.model.loads:
            if getattr(load, 'element_id', None) == int(self.element_id):
                is_local = getattr(load, 'coord_system', 'Global').lower() == 'local'
                
                if hasattr(load, 'wx'): 
                    w_vec = np.array([load.wx, load.wy, load.wz])
                    if not is_local: w_vec = R_3x3 @ w_vec
                    w_loc += w_vec
                    
                elif hasattr(load, 'force'): 
                    a = load.dist * L_full if getattr(load, 'is_relative', False) else load.dist
                    a_clear = a - ri
                    
                    if 0 <= a_clear <= L_clear:
                        dir_map = {'X': 0, 'Y': 1, 'Z': 2, '1': 0, '2': 1, '3': 2}
                        idx = dir_map.get(str(getattr(load, 'direction', 'Z')).upper(), 2)
                        
                        vec = np.zeros(3)
                        vec[idx] = load.force
                        if not is_local: vec = R_3x3 @ vec
                        
                        l_type = getattr(load, 'load_type', 'Force').lower()
                        if l_type == 'moment': point_loads.append({'a_clear': a_clear, 'F': np.zeros(3), 'M': vec})
                        else: point_loads.append({'a_clear': a_clear, 'F': vec, 'M': np.zeros(3)})
        
        P = np.zeros(101)
        V2 = np.zeros(101); M3 = np.zeros(101)
        V3 = np.zeros(101); M2 = np.zeros(101)
        Defl_2_Rel = np.zeros(101); Defl_3_Rel = np.zeros(101)
        
        for i, x_abs in enumerate(stations):
            x_c = x_abs - ri
            xi = x_c / L_clear if L_clear > 0 else 0
            
            P[i] = -Fx1 - w_loc[0] * x_c
            V2[i] = Fy1 + w_loc[1] * x_c
            V3[i] = -(Fz1 + w_loc[2] * x_c)
            
            M3[i] = Mz1 - Fy1 * x_c - w_loc[1] * (x_c**2) / 2.0
            M2[i] = My1 + Fz1 * x_c + w_loc[2] * (x_c**2) / 2.0
            
            for pl in point_loads:
                a_c = pl['a_clear']
                if x_c > a_c:
                    dist_x = x_c - a_c
                    P[i] -= pl['F'][0]
                    V2[i] += pl['F'][1]                            
                    V3[i] -= pl['F'][2]                              
                    M3[i] += -pl['F'][1] * dist_x - pl['M'][2]
                    M2[i] += pl['F'][2] * dist_x - pl['M'][1]
            
            N1 = 1 - 3*xi**2 + 2*xi**3
            N2 = x_c * (1 - 2*xi + xi**2)
            N3 = 3*xi**2 - 2*xi**3
            N4 = x_c * (xi**2 - xi)
            
            defl_2_abs = N1*v1 + N2*thz1 + N3*v2 + N4*thz2
            defl_3_abs = N1*w1 + N2*(-thy1) + N3*w2 + N4*(-thy2) 
            
            chord_2 = v1 + (v2 - v1) * xi
            chord_3 = w1 + (w2 - w1) * xi
            
            E = getattr(self.element.section.material, 'E', 1.0)
            I33 = getattr(self.element.section, 'I33', 1.0)
            I22 = getattr(self.element.section, 'I22', 1.0)
            
            defl_bubble_2 = (w_loc[1] * (x_c**2) * ((L_clear - x_c)**2)) / (24 * E * I33) if I33 > 0 else 0
            defl_bubble_3 = (w_loc[2] * (x_c**2) * ((L_clear - x_c)**2)) / (24 * E * I22) if I22 > 0 else 0
            
            Defl_2_Rel[i] = (defl_2_abs - chord_2) + defl_bubble_2
            Defl_3_Rel[i] = (defl_3_abs - chord_3) + defl_bubble_3

            Defl_2_Abs[i] = defl_2_abs + defl_bubble_2
            Defl_3_Abs[i] = defl_3_abs + defl_bubble_3
            
        return stations, P, V2, V3, M2, M3, Defl_2_Rel, Defl_3_Rel, Defl_2_Abs, Defl_3_Abs
    
    def add_nvm_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        self.nvm_fig = Figure(figsize=(8, 5.5), dpi=100, facecolor='white')
        self.nvm_canvas = FigureCanvas(self.nvm_fig)
        self.nvm_canvas.mpl_connect('resize_event', self._on_canvas_resize)
        layout.addWidget(self.nvm_canvas)

        _combo_style = """
            QComboBox {
                padding: 4px 10px; border: 1px solid #c0c0c0; border-radius: 4px;
                background-color: #ffffff; font-size: 10pt; color: #333; min-height: 25px;
            }
        """

        self.nvm_combo = QComboBox()
        self.nvm_combo.addItems(["Minor Axis (P, V3, M2, Deflection)", "Major Axis (P, V2, M3, Deflection)"])
        self.nvm_combo.setStyleSheet(_combo_style)
        
        self.defl_combo = QComboBox()
        self.defl_combo.addItems(["Relative to Beam Ends", "Absolute"])
        self.defl_combo.setStyleSheet(_combo_style)

        combo_layout = QHBoxLayout()
        combo_layout.addWidget(self.nvm_combo)
        combo_layout.addWidget(self.defl_combo)
        combo_layout.addStretch()                          
        layout.addLayout(combo_layout)

        slider_widget = QWidget()
        self.slider_layout = QHBoxLayout(slider_widget)
        self.slider_layout.setContentsMargins(0, 0, 0, 0)
        
        self.nvm_slider = QSlider(Qt.Orientation.Horizontal)
        self.nvm_slider.setRange(0, 100)
        self.nvm_slider.setValue(0)
        
        self.nvm_slider.setStyleSheet("""
            QSlider::groove:horizontal { height: 6px; background: #d0d0d0; border-radius: 3px; }
            QSlider::handle:horizontal { background: #2980b9; border: 1px solid #1c5e8a;
                                         width: 16px; height: 16px; margin: -5px 0; border-radius: 8px; }
            QSlider::sub-page:horizontal { background: #2980b9; border-radius: 3px; }
        """)
        self.slider_layout.addWidget(self.nvm_slider)
        layout.addWidget(slider_widget)

        self.nvm_val_label = QLabel("Move the slider to inspect values at any position along the beam.")
        self.nvm_val_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.nvm_val_label.setStyleSheet(
            "font-size: 9pt; color: #154360; padding: 4px 8px; "
            "background: #ffffff; border: 1px solid #a9cce3; border-radius: 4px;"
        )
        layout.addWidget(self.nvm_val_label)

        self.tabs.addTab(tab, "NVM & Deflection")

        self._nvm_axes   = None                         
        self._nvm_arrays = None                                         
        self._nvm_vlines = []                                  

        self.nvm_combo.currentIndexChanged.connect(self.update_nvm_plot)
        self.defl_combo.currentIndexChanged.connect(self.update_nvm_plot)
        self.nvm_slider.valueChanged.connect(self._update_nvm_slider)

        self.update_nvm_plot()

    def _on_canvas_resize(self, event):
        """Rebuild the background cache if the window resizes to prevent graphical tearing."""
        if not hasattr(self, '_nvm_vlines') or not self._nvm_vlines: return
            
        for vl in self._nvm_vlines:
            vl.set_visible(False)
            
        self.nvm_canvas.draw()
        self._bg_cache = self.nvm_canvas.copy_from_bbox(self.nvm_fig.bbox)
        
        for vl in self._nvm_vlines:
            vl.set_visible(True)
            
        self._sync_slider_layout()
        
    def _sync_slider_layout(self):
        """Align the QSlider handle exactly with the Matplotlib axes."""
        if not hasattr(self, '_nvm_axes') or not self._nvm_axes: return
        bbox = self._nvm_axes[3].get_position() 
        canvas_w = self.nvm_canvas.width()
        left_margin = max(0, int(bbox.x0 * canvas_w) - 8)
        right_margin = max(0, int(canvas_w - (bbox.x1 * canvas_w)) - 8)
        self.slider_layout.setContentsMargins(left_margin, 0, right_margin, 0)

    def update_nvm_plot(self):
        if self.forces_base is None: return
        self.nvm_fig.clear()

        self.nvm_fig.subplots_adjust(right=0.95, left=0.1, hspace=0.45)

        stations, P, V2, V3, M2, M3, Defl_2_Rel, Defl_3_Rel, Defl_2_Abs, Defl_3_Abs = self._calculate_nvm_data()

        L_scale = getattr(unit_registry, 'length_scale', 1.0)
        def to_F(v): return np.array([unit_registry.to_display_force(x) for x in v])
        def to_M(v): return np.array([unit_registry.to_display_force(x) * L_scale for x in v])
        def to_L(v): return np.array([unit_registry.to_display_length(x) for x in v])

        is_absolute = self.defl_combo.currentIndex() == 1

        idx = self.nvm_combo.currentIndex()
        if idx == 0:
            shear  = to_F(V2);  moment = to_M(M3)
            defl   = to_L(Defl_2_Abs) if is_absolute else to_L(Defl_2_Rel)
            shear_lbl = f'Shear Force (V2) [{self.force_unit}]'
            mom_lbl   = f'Bending Moment (M3) [{self.moment_unit}]'
            defl_lbl  = f'{"Absolute" if is_absolute else "Relative"} Deflection (u2) [{self.length_unit}]'
        else:
            shear  = to_F(V3);  moment = to_M(M2)
            defl   = to_L(Defl_3_Abs) if is_absolute else to_L(Defl_3_Rel)
            shear_lbl = f'Shear Force (V2) [{self.force_unit}]'
            mom_lbl   = f'Bending Moment (M3) [{self.moment_unit}]'
            defl_lbl  = f'{"Absolute" if is_absolute else "Relative"} Deflection (u3) [{self.length_unit}]'

        axial  = to_F(P)
        x_disp = stations * L_scale

        self._nvm_arrays = (x_disp, axial, shear, moment, defl)

        C_POS  = '#4a90d9'                               
        C_NEG  = '#d9534f'                                   
        C_LINE = '#1a252f'                       
        C_ZERO = '#888888'

        def fill_signed(ax, x, y):
            ax.plot(x, y, color=C_LINE, linewidth=1.8, zorder=3)
            ax.fill_between(x, 0, y, where=(y >= 0), color=C_POS, alpha=0.55, interpolate=True)
            ax.fill_between(x, 0, y, where=(y <  0), color=C_NEG, alpha=0.55, interpolate=True)

        ax1 = self.nvm_fig.add_subplot(411)
        fill_signed(ax1, x_disp, axial)
        ax1.axhline(0, color=C_ZERO, linewidth=0.8)
        ax1.set_title(f'Axial Force (P) [{self.force_unit}]', fontsize=9, fontweight='bold')
        ax1.grid(True, linestyle='--', alpha=0.5)

        ax2 = self.nvm_fig.add_subplot(412)
        fill_signed(ax2, x_disp, shear)
        ax2.axhline(0, color=C_ZERO, linewidth=0.8)
        ax2.set_title(shear_lbl, fontsize=9, fontweight='bold')
        ax2.grid(True, linestyle='--', alpha=0.5)

        ax3 = self.nvm_fig.add_subplot(413)
        fill_signed(ax3, x_disp, moment)
        ax3.axhline(0, color=C_ZERO, linewidth=0.8)
        ax3.set_title(mom_lbl, fontsize=9, fontweight='bold')
        ax3.grid(True, linestyle='--', alpha=0.5)
        ax3.invert_yaxis()

        ax4 = self.nvm_fig.add_subplot(414)
        ax4.plot(x_disp, defl, color='#2c3e50', linewidth=2.2, zorder=3)
        ax4.axhline(0, color=C_ZERO, linewidth=0.8, linestyle='--')
        ax4.set_title(defl_lbl, fontsize=9, fontweight='bold')
        ax4.grid(True, linestyle='--', alpha=0.5)

        self._nvm_axes = (ax1, ax2, ax3, ax4)

        vline_kw = dict(color='#2980b9', linewidth=1.5, linestyle='--', zorder=6)
        self._nvm_vlines = [ax.axvline(x_disp[0], **vline_kw) for ax in self._nvm_axes]

        self.nvm_fig.tight_layout()

        for vl in self._nvm_vlines:
            vl.set_visible(False)
        
        self.nvm_canvas.draw()
        self._bg_cache = self.nvm_canvas.copy_from_bbox(self.nvm_fig.bbox)
        
        for vl in self._nvm_vlines:
            vl.set_visible(True)
                                             
        self._sync_slider_layout()
        self._update_nvm_slider(self.nvm_slider.value())
                                             
        def sync_slider_width():
            if not self._nvm_axes: return
            bbox = self._nvm_axes[3].get_position() 
            canvas_w = self.nvm_canvas.width()
            
            left_margin = int(bbox.x0 * canvas_w) - 8
            right_margin = int(canvas_w - (bbox.x1 * canvas_w)) - 8
            
            left_margin = max(0, left_margin)
            right_margin = max(0, right_margin)
            
            self.slider_layout.setContentsMargins(left_margin, 0, right_margin, 0)

        from PyQt6.QtCore import QTimer
        QTimer.singleShot(50, sync_slider_width)

        self._update_nvm_slider(self.nvm_slider.value())

    def _update_nvm_slider(self, value):
        """Move the inspection line across all 4 NVM plots with zero lag."""
        if self._nvm_arrays is None or self._nvm_axes is None:
            return

        x_disp, axial, shear, moment, defl = self._nvm_arrays
        station_idx = int(np.clip(value, 0, len(x_disp) - 1))
        x_val = x_disp[station_idx]

        p_val = axial[station_idx]
        v_val = shear[station_idx]
        m_val = moment[station_idx]
        d_val = defl[station_idx]

        self.nvm_val_label.setText(
            f"x = {x_val:.3f} {self.length_unit}  │  "
            f"P = {p_val:+.4f} {self.force_unit}  │  "
            f"V = {v_val:+.4f} {self.force_unit}  │  "
            f"M = {m_val:+.4f} {self.moment_unit}  │  "
            f"δ = {d_val:+.6f} {self.length_unit}"
        )

        try:
            if hasattr(self, '_bg_cache'):
                self.nvm_canvas.restore_region(self._bg_cache)
                for vl in self._nvm_vlines:
                    vl.set_xdata([x_val, x_val])
                    vl.axes.draw_artist(vl)
                self.nvm_canvas.blit(self.nvm_fig.bbox)
                self.nvm_canvas.flush_events()
            else:
                raise ValueError
        except ValueError:
            for vl in self._nvm_vlines:
                vl.set_xdata([x_val, x_val])
            self.nvm_canvas.draw_idle()

        ratio = value / 100.0 
        self.inspection_location_changed.emit(self.element, ratio)

    def _nvm_endpoints(self):
        """Return display-unit NVM values at x=0 (i) and x=L (j).
        Returns dict with keys: P_i, P_j, V2_i, V2_j, V3_i, V3_j,
                                M2_i, M2_j, M3_i, M3_j  (all in display units)
        """
        if self._nvm_cache is None:
            return None
        stations, P, V2, V3, M2, M3, *_ = self._nvm_cache
        L_scale = getattr(unit_registry, 'length_scale', 1.0)
        def fF(v): return unit_registry.to_display_force(v)
        def fM(v): return unit_registry.to_display_force(v) * L_scale
        return dict(
            P_i=fF(P[0]),   P_j=fF(P[-1]),
            V2_i=fF(V2[0]), V2_j=fF(V2[-1]),
            V3_i=fF(V3[0]), V3_j=fF(V3[-1]),
            M2_i=fM(M2[0]), M2_j=fM(M2[-1]),
            M3_i=fM(M3[0]), M3_j=fM(M3[-1]),
        )

    def _add_value_table(self, ax_table, rows, col_labels=('Location', 'Symbol', 'Value', 'Unit')):
        """Render a clean summary table in the given axes."""
        ax_table.axis('off')
        tbl = ax_table.table(
            cellText=rows,
            colLabels=col_labels,
            loc='center',
            cellLoc='center'
        )
        tbl.auto_set_font_size(False)
        tbl.set_fontsize(10)
        tbl.scale(1, 1.8)
                          
        for c in range(len(col_labels)):
            cell = tbl[0, c]
            cell.set_facecolor('#2c3e50')
            cell.set_text_props(color='white', fontweight='bold')
                               
        for r in range(1, len(rows) + 1):
            for c in range(len(col_labels)):
                tbl[r, c].set_facecolor('#f0f4f8' if r % 2 == 0 else 'white')

    def add_axial_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        figure = Figure(figsize=(8, 5), dpi=100, facecolor='white', layout='constrained')
        canvas = FigureCanvas(figure)
        layout.addWidget(canvas)
        self.tabs.addTab(tab, "Axial Force (P)")

        if self.forces is None: return

        gs = figure.add_gridspec(2, 1, height_ratios=[3, 1], hspace=0.05)
        ax = figure.add_subplot(gs[0])
        ax_table = figure.add_subplot(gs[1])
        
        L_display = self.beam_length_display
        L_norm = 10                                 
        
        ax.plot([0, L_norm], [0, 0], color=self.COLORS['beam'], linewidth=3, solid_capstyle='round')
        ax.plot([0, 0], [-0.3, 0.3], color=self.COLORS['node'], linewidth=2.5)          
        ax.plot([L_norm, L_norm], [-0.3, 0.3], color=self.COLORS['node'], linewidth=2.5)          
        
        ax.text(0, -0.8, f'i\n(0.00)', ha='center', va='top', fontsize=10, fontweight='bold')
        ax.text(L_norm, -0.8, f'j\n({L_display:.2f})', ha='center', va='top', fontsize=10, fontweight='bold')
        
        fx_i = self.forces[0]
        fx_j = self.forces[6]
        
        self._draw_axial_arrow(ax, 0, fx_i, 'left', L_norm)
        self._draw_axial_arrow(ax, L_norm, fx_j, 'right', L_norm)

        ax.set_ylim(-2, 2)
        ax.set_xlim(-3, L_norm + 3)
        ax.set_aspect('equal')
        ax.axis('off')
        ax.set_title(f'Axial Force Diagram (Fx) [{self.force_unit}]', 
                    fontsize=12, fontweight='bold', pad=20)
        
        nvm = self._nvm_endpoints()
        p_i = nvm['P_i'] if nvm else abs(unit_registry.to_display_force(self.forces_base[0]))
        p_j = nvm['P_j'] if nvm else abs(unit_registry.to_display_force(self.forces_base[6]))
        self._add_value_table(ax_table, [
            [f'i  (x = 0.00 {self.length_unit})',  'P', f'{abs(p_i):.4f}', self.force_unit],
            [f'j  (x = {L_display:.2f} {self.length_unit})', 'P', f'{abs(p_j):.4f}', self.force_unit],
        ])
        
        canvas.draw()

    def add_Minor_axis_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        figure = Figure(figsize=(8, 6), dpi=100, facecolor='white', layout='constrained')
        canvas = FigureCanvas(figure)
        layout.addWidget(canvas)
        self.tabs.addTab(tab, "Minor Axis (V3-M2)")

        if self.forces is None: return

        gs = figure.add_gridspec(2, 1, height_ratios=[3, 1], hspace=0.05)
        ax = figure.add_subplot(gs[0])
        ax_table = figure.add_subplot(gs[1])
        
        L_display = self.beam_length_display
        L_norm = 10
        
        ax.plot([0, L_norm], [0, 0], color=self.COLORS['beam'], linewidth=3, solid_capstyle='round')
        ax.plot([0, 0], [-0.3, 0.3], color=self.COLORS['node'], linewidth=2.5)
        ax.plot([L_norm, L_norm], [-0.3, 0.3], color=self.COLORS['node'], linewidth=2.5)
        
        ax.text(0, -0.6, f'i\n(0.00)', ha='center', va='top', fontsize=10, fontweight='bold')
        ax.text(L_norm, -0.6, f'j\n({L_display:.2f})', ha='center', va='top', fontsize=10, fontweight='bold')
        
        fy_i = self.forces[1]
        fy_j = self.forces[7]
        
        self._draw_shear_arrow(ax, 0, fy_i, 'left', L_norm)
        self._draw_shear_arrow(ax, L_norm, -fy_j, 'right', L_norm)
        
        mz_i = self.forces[5]
        mz_j = self.forces[11]
        
        self._draw_moment(ax, 0, mz_i, 'left', L_norm)
        self._draw_moment(ax, L_norm, mz_j, 'right', L_norm)

        ax.set_ylim(-3.5, 3.5)
        ax.set_xlim(-3, L_norm + 3)
        ax.set_aspect('equal')
        ax.axis('off')
        ax.set_title(f'Minor Axis Bending - Fy [{self.force_unit}], Mz [{self.moment_unit}]', 
                    fontsize=12, fontweight='bold', pad=20)
        
        nvm = self._nvm_endpoints()
        v2_i = nvm['V2_i'] if nvm else abs(self.forces[1])
        v2_j = nvm['V2_j'] if nvm else abs(self.forces[7])
        m3_i = nvm['M3_i'] if nvm else abs(self.forces[5])
        m3_j = nvm['M3_j'] if nvm else abs(self.forces[11])
        self._add_value_table(ax_table, [
                                                             
            [f'i  (x = 0.00 {self.length_unit})',  'V3', f'{abs(v2_i):.4f}', self.force_unit],
            [f'j  (x = {L_display:.2f} {self.length_unit})', 'V3', f'{abs(v2_j):.4f}', self.force_unit],
            [f'i  (x = 0.00 {self.length_unit})',  'M2', f'{abs(m3_i):.4f}', self.moment_unit],
            [f'j  (x = {L_display:.2f} {self.length_unit})', 'M2', f'{abs(m3_j):.4f}', self.moment_unit],
        ])
        
        canvas.draw()

    def add_Major_axis_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        figure = Figure(figsize=(8, 6), dpi=100, facecolor='white', layout='constrained')
        canvas = FigureCanvas(figure)
        layout.addWidget(canvas)
        self.tabs.addTab(tab, "Major Axis (M3-V2)")

        if self.forces is None: return

        gs = figure.add_gridspec(2, 1, height_ratios=[3, 1], hspace=0.05)
        ax = figure.add_subplot(gs[0])
        ax_table = figure.add_subplot(gs[1])
        
        L_display = self.beam_length_display
        L_norm = 10
        
        ax.plot([0, L_norm], [0, 0], color=self.COLORS['beam'], linewidth=3, solid_capstyle='round')
        ax.plot([0, 0], [-0.3, 0.3], color=self.COLORS['node'], linewidth=2.5)
        ax.plot([L_norm, L_norm], [-0.3, 0.3], color=self.COLORS['node'], linewidth=2.5)
        
        ax.text(0, -0.6, f'i\n(0.00)', ha='center', va='top', fontsize=10, fontweight='bold')
        ax.text(L_norm, -0.6, f'j\n({L_display:.2f})', ha='center', va='top', fontsize=10, fontweight='bold')
        
        fz_i = self.forces[2]
        fz_j = self.forces[8]
        
        self._draw_shear_arrow(ax, 0, fz_i, 'left', L_norm)
        self._draw_shear_arrow(ax, L_norm, fz_j, 'right', L_norm)
        
        my_i = self.forces[4]
        my_j = self.forces[10]
        
        self._draw_moment(ax, 0, my_i, 'left', L_norm)
        self._draw_moment(ax, L_norm, my_j, 'right', L_norm)

        ax.set_ylim(-3.5, 3.5)
        ax.set_xlim(-3, L_norm + 3)
        ax.set_aspect('equal')
        ax.axis('off')
        ax.set_title(f'Major Axis Bending - Fz [{self.force_unit}], My [{self.moment_unit}]', 
                    fontsize=12, fontweight='bold', pad=20)
        
        nvm = self._nvm_endpoints()
        v3_i = nvm['V3_i'] if nvm else abs(self.forces[2])
        v3_j = nvm['V3_j'] if nvm else abs(self.forces[8])
        m2_i = nvm['M2_i'] if nvm else abs(self.forces[4])
        m2_j = nvm['M2_j'] if nvm else abs(self.forces[10])
        self._add_value_table(ax_table, [
                                                             
            [f'i  (x = 0.00 {self.length_unit})',  'V2', f'{abs(v3_i):.4f}', self.force_unit],
            [f'j  (x = {L_display:.2f} {self.length_unit})', 'V2', f'{abs(v3_j):.4f}', self.force_unit],
            [f'i  (x = 0.00 {self.length_unit})',  'M3', f'{abs(m2_i):.4f}', self.moment_unit],
            [f'j  (x = {L_display:.2f} {self.length_unit})', 'M3', f'{abs(m2_j):.4f}', self.moment_unit],
        ])
        
        canvas.draw()

    def add_torsion_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        figure = Figure(figsize=(8, 5), dpi=100, facecolor='white', layout='constrained')
        canvas = FigureCanvas(figure)
        layout.addWidget(canvas)
        self.tabs.addTab(tab, "Torsion (T)")

        if self.forces is None: return

        gs = figure.add_gridspec(2, 1, height_ratios=[3, 1], hspace=0.05)
        ax = figure.add_subplot(gs[0])
        ax_table = figure.add_subplot(gs[1])
        
        L_display = self.beam_length_display
        L_norm = 10
        
        ax.plot([0, L_norm], [0, 0], color=self.COLORS['beam'], linewidth=3, solid_capstyle='round')
        ax.plot([0, 0], [-0.3, 0.3], color=self.COLORS['node'], linewidth=2.5)
        ax.plot([L_norm, L_norm], [-0.3, 0.3], color=self.COLORS['node'], linewidth=2.5)
        
        ax.text(0, -0.8, f'i\n(0.00)', ha='center', va='top', fontsize=10, fontweight='bold')
        ax.text(L_norm, -0.8, f'j\n({L_display:.2f})', ha='center', va='top', fontsize=10, fontweight='bold')
        
        mx_i = self.forces[3]
        mx_j = self.forces[9]
        
        self._draw_torsion(ax, 0, mx_i, 'left', L_norm)
        self._draw_torsion(ax, L_norm, mx_j, 'right', L_norm)

        ax.set_ylim(-2, 2)
        ax.set_xlim(-3, L_norm + 3)
        ax.set_aspect('equal')
        ax.axis('off')
        ax.set_title(f'Torsional Moment Diagram (Mx) [{self.moment_unit}]', 
                    fontsize=12, fontweight='bold', pad=20)
        
        self._add_value_table(ax_table, [
            [f'i  (x = 0.00 {self.length_unit})',  'Mx', f'{abs(mx_i):.4f}', self.moment_unit],
            [f'j  (x = {L_display:.2f} {self.length_unit})', 'Mx', f'{abs(mx_j):.4f}', self.moment_unit],
        ])
        
        canvas.draw()

    def _draw_axial_arrow(self, ax, x_pos, force, side, beam_length=10):
        if abs(force) < 0.001: return
        arrow_len = 1.2
        y_pos = 0.5
        s = 1 if force > 0 else -1
        dx = s * arrow_len if side == 'left' else s * arrow_len

        ax.arrow(
            x_pos, y_pos, dx * 0.85, 0, head_width=0.25, head_length=0.15,
            fc=self.COLORS['axial'], ec=self.COLORS['axial'], linewidth=2, length_includes_head=True
        )

    def _draw_shear_arrow(self, ax, x_pos, force, side, beam_length=10):
        if abs(force) < 0.001: return
        arrow_len = 1.0
        dy = arrow_len if force > 0 else -arrow_len
        
        ax.arrow(x_pos, 0, 0, dy * 0.85, head_width=0.2, head_length=0.15,
                fc=self.COLORS['shear'], ec=self.COLORS['shear'], linewidth=2, length_includes_head=True)

    def _draw_moment(self, ax, x_pos, moment, side, beam_length=10):
        if abs(moment) < 0.001: return
        radius = 0.5
        theta = np.linspace(0, 1.5 * np.pi, 30)

        if moment < 0:
            arc_x = x_pos + radius * np.cos(theta)
            arc_y = radius * np.sin(theta)
        else:
            arc_x = x_pos + radius * np.cos(-theta)
            arc_y = radius * np.sin(-theta)

        ax.plot(arc_x, arc_y, color=self.COLORS['moment'], linewidth=2)

        ax.annotate('', xy=(arc_x[-1], arc_y[-1]), xytext=(arc_x[-3], arc_y[-3]),
            arrowprops=dict(arrowstyle='->', color=self.COLORS['moment'], lw=2))

    def _draw_torsion(self, ax, x_pos, torque, side, beam_length=10):
        if abs(torque) < 0.001: return
        ax.plot([x_pos, x_pos], [-0.8, 0.8], color=self.COLORS['torsion'], linewidth=2, linestyle='--', alpha=0.6)
        
        theta = np.linspace(0, 2 * np.pi, 20)
        radius = 0.4
        circ_x = x_pos + radius * np.cos(theta)
        circ_y = radius * np.sin(theta)
        
        ax.plot(circ_x, circ_y, color=self.COLORS['torsion'], linewidth=2, linestyle='-', alpha=0.8)
        
        direction = '⟲' if torque > 0 else '⟳'
        ax.text(x_pos, 0, direction, ha='center', va='center', fontsize=18, color=self.COLORS['torsion'], fontweight='bold')

    def closeEvent(self, event):
        """Hides the red dot when the user closes the FBD dialog."""
        self.inspection_closed.emit()
        super().closeEvent(event)
