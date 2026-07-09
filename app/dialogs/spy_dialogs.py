import sys
import json
import os
import numpy as np
import functools

def get_cached_matrices(path):
    if not os.path.exists(path): return {}
    with open(path, 'r') as f: return json.load(f)
    
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
    """

    def __init__(self, element, model, num_stations=21,
                 displacements=None, matrices_path=None, results_dict=None):
        self.el          = element
        self.model       = model
        self.n_stations  = num_stations
        self.results_dict = results_dict

        self.L_clear  = self.el.length()
        self.stations = np.linspace(0, self.L_clear, num_stations)
        
        self.P  = np.zeros(num_stations)
        self.V2 = np.zeros(num_stations)
        self.V3 = np.zeros(num_stations)
        self.M2 = np.zeros(num_stations)
        self.M3 = np.zeros(num_stations)
        
        self.Defl_2_Rel = np.zeros(num_stations)
        self.Defl_3_Rel = np.zeros(num_stations)
        self.Defl_2_Abs = np.zeros(num_stations)
        self.Defl_3_Abs = np.zeros(num_stations)
        
        self.end_forces = np.zeros(12)

        self._k   = None
        self._t   = None
        self._fef = np.zeros(12)
        self._matrices_loaded = False
        self.matrices_path = None

        self._displacements = displacements

        self._load_matrices(matrices_path)
        self._calculate()

    def _load_matrices(self, matrices_path):
        resolved = None
        active_results   = self.results_dict if self.results_dict is not None else (getattr(self.model, 'results', {}) or {})
        active_mat_path  = (active_results.get("matrices_path") or active_results.get("matrices_file"))

        if matrices_path and os.path.exists(matrices_path):
            resolved = matrices_path
        elif active_mat_path and os.path.exists(active_mat_path):
            resolved = active_mat_path
        elif hasattr(self.model, "file_path") and self.model.file_path:
            fallback = self.model.file_path.replace(".mf", "_matrices.json")
            if os.path.exists(fallback):
                resolved = fallback

        if not resolved:
            return

        self.matrices_path = resolved

        try:
            data = get_cached_matrices(resolved)
            str_id = str(self.el.id)
            if str_id in data:
                self._k   = np.array(data[str_id]["k"])
                self._t   = np.array(data[str_id]["t"])
                self._fef = np.array(data[str_id]["fef"])
                self._matrices_loaded = True
        except Exception as e:
            print(f"[MemberAnalyzer] Error loading matrices: {e}")

    def _calculate(self):
        if not self._matrices_loaded:
            return

        res = self.results_dict if self.results_dict is not None else (getattr(self.model, 'results', {}) or {})
        active_case_name = res.get("info", {}).get("case_name", "")

        combo_base_name = active_case_name
        is_combo = False
        is_max_env = True
        
        if active_case_name.endswith(" (Max)"):
            combo_base_name = active_case_name.rsplit(" (Max)", 1)[0]
            is_max_env = True
            is_combo = True
        elif active_case_name.endswith(" (Min)"):
            combo_base_name = active_case_name.rsplit(" (Min)", 1)[0]
            is_max_env = False
            is_combo = True
        elif hasattr(self.model, 'load_combos') and active_case_name in self.model.load_combos:
            is_combo = True

        if is_combo and hasattr(self.model, 'load_combos') and combo_base_name in self.model.load_combos:
            combo_obj = self.model.load_combos[combo_base_name]
            c_type = getattr(combo_obj, 'combo_type', 'Linear Add')
            
            base_path = ""
            if hasattr(self.model, 'file_path') and self.model.file_path:
                base_path = self.model.file_path.replace(".mf", "")
            elif self.matrices_path:
                temp = self.matrices_path.replace("_matrices.json", "")
                base_name = os.path.basename(temp)
                if "_" in base_name:
                    base_path = os.path.join(os.path.dirname(temp), base_name.rsplit("_", 1)[0])
                else:
                    base_path = temp
                                                                       
            if c_type == 'Envelope':
                self.P.fill(-np.inf if is_max_env else np.inf)
                self.V2.fill(-np.inf if is_max_env else np.inf)
                self.V3.fill(-np.inf if is_max_env else np.inf)
                self.M2.fill(-np.inf if is_max_env else np.inf)
                self.M3.fill(-np.inf if is_max_env else np.inf)
                self.end_forces.fill(-np.inf if is_max_env else np.inf)

            for b_case, scale in combo_obj.cases:
                files_to_eval = []
                base_file = f"{base_path}_{b_case}_results.json"
                max_file = f"{base_path}_{b_case} (Max)_results.json"
                min_file = f"{base_path}_{b_case} (Min)_results.json"
                
                if c_type == 'Envelope':
                    if os.path.exists(max_file): files_to_eval.append(max_file)
                    if os.path.exists(min_file): files_to_eval.append(min_file)
                    if not files_to_eval and os.path.exists(base_file): files_to_eval.append(base_file)
                else: 
                    if is_max_env and os.path.exists(max_file): files_to_eval.append(max_file)
                    elif not is_max_env and os.path.exists(min_file): files_to_eval.append(min_file)
                    elif os.path.exists(base_file): files_to_eval.append(base_file)
                    
                for r_file in files_to_eval:
                    mat_file = r_file.replace("_results.json", "_matrices.json")
                    if not os.path.exists(mat_file): mat_file = self.matrices_path
                    if not os.path.exists(r_file): continue
                    
                    with open(r_file, 'r') as f: b_res = json.load(f)
                        
                    is_rsa = b_res.get("info", {}).get("type", "") in ["Response Spectrum", "Response Spectrum Combined"]
                    
                    sub = MemberAnalyzer(self.el, self.model, self.n_stations, matrices_path=mat_file, results_dict=b_res)
                    
                    self.stations = sub.stations
                    self.L_clear = sub.L_clear
                    
                    net_scale = scale
                    if is_rsa and c_type == 'Linear Add':
                        net_scale = scale * (1.0 if is_max_env else -1.0)
                        
                    if c_type == 'Linear Add':
                        self.P += sub.P * net_scale
                        self.V2 += sub.V2 * net_scale
                        self.V3 += sub.V3 * net_scale
                        self.M2 += sub.M2 * net_scale
                        self.M3 += sub.M3 * net_scale
                        self.end_forces += sub.end_forces * net_scale
                        self.Defl_2_Rel += sub.Defl_2_Rel * net_scale
                        self.Defl_3_Rel += sub.Defl_3_Rel * net_scale
                        self.Defl_2_Abs += sub.Defl_2_Abs * net_scale
                        self.Defl_3_Abs += sub.Defl_3_Abs * net_scale
                    elif c_type == 'Envelope':
                        if is_max_env:
                            self.P = np.maximum(self.P, sub.P * net_scale)
                            self.V2 = np.maximum(self.V2, sub.V2 * net_scale)
                            self.V3 = np.maximum(self.V3, sub.V3 * net_scale)
                            self.M2 = np.maximum(self.M2, sub.M2 * net_scale)
                            self.M3 = np.maximum(self.M3, sub.M3 * net_scale)
                            self.end_forces = np.maximum(self.end_forces, sub.end_forces * net_scale)
                        else:
                            self.P = np.minimum(self.P, sub.P * net_scale)
                            self.V2 = np.minimum(self.V2, sub.V2 * net_scale)
                            self.V3 = np.minimum(self.V3, sub.V3 * net_scale)
                            self.M2 = np.minimum(self.M2, sub.M2 * net_scale)
                            self.M3 = np.minimum(self.M3, sub.M3 * net_scale)
                            self.end_forces = np.minimum(self.end_forces, sub.end_forces * net_scale)
            return

        el     = self.el
        n1_str = str(el.node_i.id)
        n2_str = str(el.node_j.id)

        L_full = el.length()
        ri = getattr(el, 'end_offset_i', 0.0)
        rj = getattr(el, 'end_offset_j', 0.0)
        L_clear = L_full - ri - rj
        self.L_clear = L_clear
        self.stations = np.linspace(ri, L_full - rj, self.n_stations)

        if "rsa_info" in res:
            rsa = res["rsa_info"]
            dir_comb = rsa.get("dir_comb", "SRSS")
            dirs_data = rsa.get("directions", [rsa])

            P_final = np.zeros(self.n_stations); V2_final = np.zeros(self.n_stations); V3_final = np.zeros(self.n_stations)
            M2_final = np.zeros(self.n_stations); M3_final = np.zeros(self.n_stations)
            final_end_forces = np.zeros(12)

            for d_info in dirs_data:
                method = d_info.get("method", "SRSS")
                zeta = d_info.get("zeta", 0.05)
                omega = d_info.get("omega_array", [])
                u_raw = d_info.get("uncombined_u", {})
                
                n_modes = len(omega)
                if n_modes == 0: continue

                u1_modes = u_raw.get(n1_str, [np.zeros(6)] * n_modes)
                u2_modes = u_raw.get(n2_str, [np.zeros(6)] * n_modes)

                P_modes = np.zeros((n_modes, self.n_stations)); V2_modes = np.zeros((n_modes, self.n_stations))
                V3_modes = np.zeros((n_modes, self.n_stations)); M2_modes = np.zeros((n_modes, self.n_stations))
                M3_modes = np.zeros((n_modes, self.n_stations))
                per_mode_forces = np.zeros((n_modes, 12))

                for i in range(n_modes):
                    u_global_mode = np.concatenate([u1_modes[i], u2_modes[i]])
                    end_f_mode = self._k @ (self._t @ u_global_mode)
                    per_mode_forces[i] = end_f_mode
                    Fx1, Fy1, Fz1 = end_f_mode[0:3]
                    Mx1, My1, Mz1 = end_f_mode[3:6]

                    for j, x_abs in enumerate(self.stations):
                        x_c = x_abs - ri
                        P_modes[i, j] = -Fx1
                        V2_modes[i, j] = Fy1
                        V3_modes[i, j] = -Fz1
                        M3_modes[i, j] = Mz1 - Fy1 * x_c
                        M2_modes[i, j] = My1 + Fz1 * x_c

                P_dir = np.zeros(self.n_stations); V2_dir = np.zeros(self.n_stations); V3_dir = np.zeros(self.n_stations)
                M2_dir = np.zeros(self.n_stations); M3_dir = np.zeros(self.n_stations)
                d_end_forces = np.zeros(12)

                if method == "CQC" and n_modes > 0:
                    for d in range(12):
                        f_total = 0.0
                        for i in range(n_modes):
                            for j in range(n_modes):
                                if omega[i] == 0 or omega[j] == 0: rho = 1.0 if omega[i] == omega[j] else 0.0
                                else:
                                    r = omega[i] / omega[j]
                                    den = (1.0 - r**2)**2 + 4.0 * zeta**2 * r * (1.0 + r)**2
                                    rho = (8.0 * zeta**2 * (1.0 + r) * r**1.5) / den if den != 0.0 else 1.0
                                f_total += per_mode_forces[i, d] * rho * per_mode_forces[j, d]
                        d_end_forces[d] = np.sqrt(abs(f_total))

                    for j in range(self.n_stations):
                        p_tot=0; v2_tot=0; v3_tot=0; m2_tot=0; m3_tot=0
                        for m1 in range(n_modes):
                            for m2 in range(n_modes):
                                if omega[m1] == 0 or omega[m2] == 0: rho = 1.0 if omega[m1]==omega[m2] else 0.0
                                else:
                                    r = omega[m1] / omega[m2]
                                    den = (1.0 - r**2)**2 + 4.0 * zeta**2 * r * (1.0 + r)**2
                                    rho = (8.0 * zeta**2 * (1.0 + r) * r**1.5) / den if den != 0.0 else 1.0
                                p_tot  += P_modes[m1, j] * rho * P_modes[m2, j]
                                v2_tot += V2_modes[m1, j] * rho * V2_modes[m2, j]
                                v3_tot += V3_modes[m1, j] * rho * V3_modes[m2, j]
                                m2_tot += M2_modes[m1, j] * rho * M2_modes[m2, j]
                                m3_tot += M3_modes[m1, j] * rho * M3_modes[m2, j]
                        P_dir[j] = np.sqrt(abs(p_tot)); V2_dir[j] = np.sqrt(abs(v2_tot)); V3_dir[j] = np.sqrt(abs(v3_tot))
                        M2_dir[j] = np.sqrt(abs(m2_tot)); M3_dir[j] = np.sqrt(abs(m3_tot))
                else:
                    d_end_forces = np.sqrt(np.sum(per_mode_forces**2, axis=0))
                    P_dir = np.sqrt(np.sum(P_modes**2, axis=0))
                    V2_dir = np.sqrt(np.sum(V2_modes**2, axis=0))
                    V3_dir = np.sqrt(np.sum(V3_modes**2, axis=0))
                    M2_dir = np.sqrt(np.sum(M2_modes**2, axis=0))
                    M3_dir = np.sqrt(np.sum(M3_modes**2, axis=0))

                if dir_comb == "SRSS":
                    final_end_forces += d_end_forces**2
                    P_final += P_dir**2; V2_final += V2_dir**2; V3_final += V3_dir**2; M2_final += M2_dir**2; M3_final += M3_dir**2
                else:
                    final_end_forces += np.abs(d_end_forces)
                    P_final += np.abs(P_dir); V2_final += np.abs(V2_dir); V3_final += np.abs(V3_dir); M2_final += np.abs(M2_dir); M3_final += np.abs(M3_dir)

            if dir_comb == "SRSS":
                self.end_forces = np.sqrt(final_end_forces)
                self.P = np.sqrt(P_final); self.V2 = np.sqrt(V2_final); self.V3 = np.sqrt(V3_final); self.M2 = np.sqrt(M2_final); self.M3 = np.sqrt(M3_final)
            else:
                self.end_forces = final_end_forces
                self.P = P_final; self.V2 = V2_final; self.V3 = V3_final; self.M2 = M2_final; self.M3 = M3_final
                
        else:         
            if self._displacements is not None:
                disp_dict = self._displacements
            else:
                disp_dict = res.get("_base_displacements", res.get("displacements", {}))

            u1 = np.array(disp_dict.get(n1_str, [0.0] * 6))
            u2 = np.array(disp_dict.get(n2_str, [0.0] * 6))
            u_global = np.concatenate([u1, u2])

            self.end_forces = self._k @ (self._t @ u_global) + self._fef
            Fx1, Fy1, Fz1 = self.end_forces[0], self.end_forces[1], self.end_forces[2]
            Mx1, My1, Mz1 = self.end_forces[3], self.end_forces[4], self.end_forces[5]

            u_local = self._t @ u_global
            u1_l, v1, w1, thx1, thy1, thz1 = u_local[0:6]
            u2_l, v2, w2, thx2, thy2, thz2 = u_local[6:12]

            R_3x3 = self._t[0:3, 0:3]
            p1_coords = np.array([el.node_i.x, el.node_i.y, el.node_i.z])
            p2_coords = np.array([el.node_j.x, el.node_j.y, el.node_j.z])
            
            line_loads = []
            point_loads = []

            pattern_scales = {}
            if active_case_name in getattr(self.model, 'load_cases', {}):
                active_case = self.model.load_cases[active_case_name]
                for pat_name, case_scale in active_case.loads:
                    pattern_scales[pat_name] = pattern_scales.get(pat_name, 0.0) + case_scale

            for pat_name, net_scale in pattern_scales.items():
                if pat_name in getattr(self.model, 'load_patterns', {}):
                    pat = self.model.load_patterns[pat_name]
                    if getattr(pat, 'self_weight_multiplier', 0) > 0:
                        area = getattr(el.section, 'A', 0)
                        density = getattr(el.section.material, 'density', 0)
                        w_sw_mag = area * density * pat.self_weight_multiplier * net_scale
                        w_sw_local = R_3x3 @ np.array([0.0, 0.0, -w_sw_mag])
                        if np.any(np.abs(w_sw_local) > 1e-9):
                            line_loads.append({
                                'dists': [0.0, L_full],
                                'vecs': [w_sw_local.copy(), w_sw_local.copy()]
                            })

            for raw_load in getattr(self.model, 'loads', []):
                                                                                   
                is_dict = isinstance(raw_load, dict)
                def get_p(k, default=None): return raw_load.get(k, default) if is_dict else getattr(raw_load, k, default)
                def has_p(k): return k in raw_load if is_dict else hasattr(raw_load, k)

                if get_p('element_id') == int(el.id):
                    load_pat = get_p('pattern', get_p('pattern_name'))
                    if load_pat not in pattern_scales: continue
                    net_scale = pattern_scales[load_pat]
                    
                    l_type = get_p('type', get_p('load_type', ''))
                    is_local = str(get_p('coord_system', get_p('coord', 'Global'))).lower() == 'local'
                    
                    if l_type == 'member_dist' or (has_p('wx') and not has_p('force')):
                        mags = np.array(get_p('magnitudes', [0, 0, 0, 0])) * net_scale
                        dists = np.array(get_p('distances', [0, 0.25, 0.75, 1.0]))
                        has_trap = any(abs(m) > 1e-9 for m in mags)
                        
                        if has_trap:
                            is_rel = get_p('is_relative', True)
                            if is_rel: dists = dists * L_full
                            dir_str = str(get_p('load_direction', 'Gravity')).upper()
                            w_vectors = []
                            for m in mags:
                                vec = np.zeros(3)
                                if "GRAVITY" in dir_str: vec[2] = m
                                elif "X" in dir_str or "1" in dir_str: vec[0] = m
                                elif "Y" in dir_str or "2" in dir_str: vec[1] = m
                                elif "Z" in dir_str or "3" in dir_str: vec[2] = m
                                if not is_local: vec = R_3x3 @ vec
                                if get_p('projected', False) and not is_local:
                                    dx = p2_coords[0] - p1_coords[0]
                                    dy = p2_coords[1] - p1_coords[1]
                                    L_horiz = np.sqrt(dx**2 + dy**2)
                                    if L_full > 1e-9: vec = vec * (L_horiz / L_full)
                                w_vectors.append(vec)
                            line_loads.append({'dists': dists, 'vecs': w_vectors})
                        else:
                            w_vec = np.array([get_p('wx', 0), get_p('wy', 0), get_p('wz', 0)]) * net_scale
                            if not is_local: w_vec = R_3x3 @ w_vec
                            if get_p('projected', False) and not is_local:
                                dx = p2_coords[0] - p1_coords[0]
                                dy = p2_coords[1] - p1_coords[1]
                                L_horiz = np.sqrt(dx**2 + dy**2)
                                if L_full > 1e-9: w_vec = w_vec * (L_horiz / L_full)
                            line_loads.append({'dists': [0.0, L_full], 'vecs': [w_vec, w_vec]})
                            
                    elif l_type == 'member_point' or has_p('force'):
                        is_rel = get_p('is_rel', get_p('is_relative', False))
                        dist_val = get_p('dist', 0.0)
                        if is_rel and dist_val > 1.0: dist_val /= 100.0
                        a = dist_val * L_full if is_rel else dist_val
                        a_clear = a - ri
                        
                        if 0 <= a_clear <= L_clear:
                            dir_str = str(get_p('direction', get_p('dir', get_p('axis', 'Z')))).upper()

                            sign = 1.0
                            idx = 2
                            if "GRAVITY" in dir_str:
                                idx = 2
                                sign = -1.0
                                is_local = False
                            elif "X" in dir_str or "1" in dir_str: idx = 0
                            elif "Y" in dir_str or "2" in dir_str: idx = 1
                            elif "Z" in dir_str or "3" in dir_str: idx = 2
                            
                            vec = np.zeros(3)
                            vec[idx] = get_p('force', 0.0) * sign * net_scale
                            
                            if not is_local: 
                                vec = R_3x3 @ vec
                                
                            l_type_str = str(get_p('load_type', get_p('l_type', 'Force'))).upper()
                            if 'MOMENT' in l_type_str: 
                                point_loads.append({'a_clear': a_clear, 'F': np.zeros(3), 'M': vec})
                            else: 
                                point_loads.append({'a_clear': a_clear, 'F': vec, 'M': np.zeros(3)})

            E = getattr(el.section.material, 'E', 1.0)
            I33 = getattr(el.section, 'I33', 1.0)
            I22 = getattr(el.section, 'I22', 1.0)

            for i, x_abs in enumerate(self.stations):
                x_c = x_abs - ri
                xi = x_c / L_clear if L_clear > 0 else 0
                
                w_P_tot = 0.0; w_V2_tot = 0.0; w_V3_tot = 0.0
                w_M3_tot = 0.0; w_M2_tot = 0.0
                
                w_loc_sum = np.zeros(3)
                len_sum = 0.0
                
                for ll in line_loads:
                    dists = ll['dists']
                    vecs = ll['vecs']
                    for k in range(len(dists) - 1):
                        x1_dist = dists[k]; x2_dist = dists[k+1]
                        
                        w_vec1 = vecs[k]; w_vec2 = vecs[k+1]
                        
                        if x2_dist - x1_dist < 1e-9: continue
                        
                        s_start = max(ri, x1_dist)
                        s_end = min(x_abs, x2_dist)
                        
                        if s_start < s_end:
                            t_start = (s_start - x1_dist) / (x2_dist - x1_dist)
                            t_end = (s_end - x1_dist) / (x2_dist - x1_dist)
                            ws = w_vec1 + t_start * (w_vec2 - w_vec1)
                            we = w_vec1 + t_end * (w_vec2 - w_vec1)
                            
                            L_seg = s_end - s_start
                            F_vec = 0.5 * (ws + we) * L_seg
                            
                            w_P_tot += F_vec[0]
                            w_V2_tot += F_vec[1]
                            w_V3_tot += F_vec[2]
                            
                            arm_rect = x_abs - 0.5 * (s_start + s_end)
                            M_rect = ws * L_seg * arm_rect
                            
                            arm_tri = x_abs - (s_start + (2.0/3.0) * L_seg)
                            M_tri = 0.5 * (we - ws) * L_seg * arm_tri
                            
                            M_vec = M_rect + M_tri
                            w_M3_tot += M_vec[1]
                            w_M2_tot += M_vec[2]
                            
                            w_loc_sum += 0.5 * (ws + we) * L_seg
                            len_sum += L_seg
                            
                w_loc_avg = w_loc_sum / len_sum if len_sum > 1e-9 else np.zeros(3)
                
                P_val = -Fx1 - w_P_tot
                V2_val = Fy1 + w_V2_tot
                V3_val = -(Fz1 + w_V3_tot)
                M3_val = Mz1 - Fy1 * x_c - w_M3_tot
                M2_val = My1 + Fz1 * x_c + w_M2_tot
                
                for pl in point_loads:
                    a_c = pl['a_clear']
                    if x_c > a_c:
                        dist_x = x_c - a_c
                        P_val -= pl['F'][0]; V2_val += pl['F'][1]; V3_val -= pl['F'][2]                              
                        M3_val += -pl['F'][1] * dist_x + pl['M'][2]                                
                        M2_val += pl['F'][2] * dist_x + pl['M'][1]
                        
                self.P[i] = P_val; self.V2[i] = V2_val; self.V3[i] = V3_val; self.M3[i] = M3_val; self.M2[i] = M2_val
                
                N1 = 1 - 3*xi**2 + 2*xi**3
                N2 = x_c * (1 - 2*xi + xi**2)
                N3 = 3*xi**2 - 2*xi**3
                N4 = x_c * (xi**2 - xi)
                
                defl_2_abs = N1*v1 + N2*thz1 + N3*v2 + N4*thz2
                defl_3_abs = N1*w1 + N2*(-thy1) + N3*w2 + N4*(-thy2) 
                
                chord_2 = v1 + (v2 - v1) * xi
                chord_3 = w1 + (w2 - w1) * xi
                
                defl_bubble_2 = (w_loc_avg[1] * (x_c**2) * ((L_clear - x_c)**2)) / (24 * E * I33) if I33 > 0 else 0
                defl_bubble_3 = (w_loc_avg[2] * (x_c**2) * ((L_clear - x_c)**2)) / (24 * E * I22) if I22 > 0 else 0
                
                self.Defl_2_Rel[i] = (defl_2_abs - chord_2) + defl_bubble_2
                self.Defl_3_Rel[i] = (defl_3_abs - chord_3) + defl_bubble_3
                self.Defl_2_Abs[i] = defl_2_abs + defl_bubble_2
                self.Defl_3_Abs[i] = defl_3_abs + defl_bubble_3
                          
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

        self.results_path = results_path   
        self.matrices_path = matrices_path                   
        self.matrices_path = matrices_path
        
        self.results = self._load_json(results_path)
        self.matrices = self._load_json(matrices_path)
        
        self.beam_length = self.element.length()                               
        self.beam_length_display = unit_registry.to_display_length(self.beam_length)
        
        self._run_analyzer()
        
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

        self.case_combo = QComboBox()
        self.case_combo.setStyleSheet("""
            QComboBox { padding: 4px 10px; border: 1px solid #c0c0c0; border-radius: 4px; background-color: #ffffff; font-size: 10pt; font-weight: light; color: #000000; }
        """)
        layout.addWidget(self.case_combo)
        self._populate_case_switcher(results_path)
        self.case_combo.currentIndexChanged.connect(self._on_case_switched)
        
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

    def _populate_case_switcher(self, current_results_path):
        import glob
        import json
        self.case_combo.blockSignals(True)
        self.case_combo.clear()

        active_case = self.results.get("info", {}).get("case_name", "")

        is_single_case = active_case in getattr(self.model, 'load_cases', {})

        if is_single_case:
            self.case_combo.addItem(active_case, active_case)
            self.case_combo.setCurrentIndex(0)
            self.case_combo.setEnabled(False)                                           
            self.case_combo.blockSignals(False)
            return                       
                                                  
        if active_case and f"_{active_case}_results.json" in current_results_path:
            self._base_file_path = current_results_path.replace(f"_{active_case}_results.json", "")
        else:
            self._base_file_path = current_results_path.replace("_results.json", "")
            if "_" in self._base_file_path.split(os.sep)[-1]:
                self._base_file_path = self._base_file_path.rsplit("_", 1)[0]

        valid_cases = []
        excluded_types = ["Modal", "Buckling", "LTHA"]
        
        search_pattern = f"{self._base_file_path}_*_results.json"
        for file_path in glob.glob(search_pattern):
            try:
                with open(file_path, 'r') as f:
                    temp_data = json.load(f)
                
                case_type = temp_data.get("info", {}).get("type", "")
                if case_type in excluded_types:
                    continue
            except Exception:
                continue

            filename = os.path.basename(file_path)
            base_name = os.path.basename(self._base_file_path)
            case_name = filename.replace(base_name + "_", "").replace("_results.json", "")
            valid_cases.append(case_name)

        valid_cases = list(dict.fromkeys(valid_cases))
        current_idx = -1
        
        for i, case_name in enumerate(valid_cases):
            self.case_combo.addItem(case_name, case_name)
            if case_name == active_case:
                current_idx = i

        if current_idx >= 0:
            self.case_combo.setCurrentIndex(current_idx)

        self.case_combo.blockSignals(False)

    def _on_case_switched(self):
        import glob
        target_case = self.case_combo.currentData()
        if not target_case: return

        new_results = f"{self._base_file_path}_{target_case}_results.json"
        new_matrices = f"{self._base_file_path}_{target_case}_matrices.json"

        if not os.path.exists(new_matrices):
            search = glob.glob(f"{self._base_file_path}_*_matrices.json")
            if search: new_matrices = search[0]

        prev_tab_index    = self.tabs.currentIndex()
        prev_nvm_axis_idx = self.nvm_combo.currentIndex()
        prev_defl_idx     = self.defl_combo.currentIndex()
        prev_slider_val   = self.nvm_slider.value()

        self.results = self._load_json(new_results)
        self.matrices = self._load_json(new_matrices)

        self.results_path = new_results
        self.matrices_path = new_matrices

        self._run_analyzer()

        while self.tabs.count() > 0:
            w = self.tabs.widget(0)
            self.tabs.removeTab(0)
            w.deleteLater()

        self.add_axial_tab()
        self.add_Minor_axis_tab()
        self.add_Major_axis_tab()
        self.add_torsion_tab()
        self.add_nvm_tab()

        self.nvm_combo.blockSignals(True)
        self.nvm_combo.setCurrentIndex(prev_nvm_axis_idx)
        self.nvm_combo.blockSignals(False)

        self.defl_combo.blockSignals(True)
        self.defl_combo.setCurrentIndex(prev_defl_idx)
        self.defl_combo.blockSignals(False)

        self.update_nvm_plot()
        self.nvm_slider.setValue(prev_slider_val)

        self.tabs.setCurrentIndex(prev_tab_index)

    def _run_analyzer(self):
        """Forces the FBD Viewer to use the exact same MemberAnalyzer as the 3D graphics."""
        self.forces_base = None
        self.forces = None
        self._nvm_cache = None
        
        if self.element_id not in self.matrices: return
        if int(self.element_id) not in self.model.elements: return
        
        analyzer = MemberAnalyzer(
            element=self.element,
            model=self.model,
            num_stations=101,
            matrices_path=self.matrices_path,
            results_dict=self.results
        )
        if not analyzer._matrices_loaded: return
        
        self.forces_base = analyzer.end_forces
        self.forces = np.zeros(12)
        for i in range(12):
            if i % 6 < 3:                                 
                self.forces[i] = unit_registry.to_display_force(self.forces_base[i])
            else:                                  
                self.forces[i] = unit_registry.to_display_force(self.forces_base[i])
                
        self._nvm_cache = (
            analyzer.stations, analyzer.P, analyzer.V2, analyzer.V3, analyzer.M2, analyzer.M3,
            analyzer.Defl_2_Rel, analyzer.Defl_3_Rel, analyzer.Defl_2_Abs, analyzer.Defl_3_Abs
        )

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

        stations, P, V2, V3, M2, M3, Defl_2_Rel, Defl_3_Rel, Defl_2_Abs, Defl_3_Abs = self._nvm_cache

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
