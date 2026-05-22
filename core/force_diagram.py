import os
import json
import numpy as np
from core.units import unit_registry

class ForceDiagramBuilder:
    """
    Builds 3D OpenGL geometry for structural force/moment diagrams.

    For every element in the model:
      1. Runs a single batched NVM computation (replaces per-element MemberAnalyzer loop).
      2. Projects force values as perpendicular world-space offsets using local axes.
      3. Returns packed numpy arrays ready for the VBO pipeline:
           fill  -> GLMeshItem (vertices, faces, vertexColors)
           lines -> GLLinePlotItem (pos, color, mode='lines')

    Performance vs. old MemberAnalyzer loop:
      - JSON read:      N file opens  →  1 file open
      - end_forces:     N serial matmuls  →  1 batched einsum (E, 12, 12)
      - NVM stations:   N × S Python scalar loop  →  1 broadcast over (E, S)
      - Point loads:    N × S inner loop  →  boolean mask, no inner loop
    """

    PERP_AXIS = {
        'P':  'y',
        'V2': 'y',                         
        'V3': 'z',                         
        'M3': 'y',                         
        'M2': 'z',                         
    }

    POS_COLOR  = np.array([0.15, 0.40, 1.00, 0.72], dtype=np.float32)
    NEG_COLOR  = np.array([1.00, 0.20, 0.20, 0.72], dtype=np.float32)
    LINE_COLOR = np.array([0.08, 0.08, 0.08, 0.90], dtype=np.float32)

    def __init__(self, model, component='M3', scale_factor=None, n_stations=21,
                 displacements=None, matrices_path=None, show_labels=True):
        self.model       = model
        self.show_labels = show_labels
        self.component   = component
        self._scale      = scale_factor
        self.n_stations  = max(n_stations, 5)
        self.displacements  = displacements                                       
        self.matrices_path  = matrices_path                                               

        self.fill_verts  = np.zeros((0, 3), dtype=np.float32)
        self.fill_colors = np.zeros((0, 4), dtype=np.float32)
        self.fill_faces  = np.zeros((0, 3), dtype=np.uint32)
        self.line_pos    = np.zeros((0, 3), dtype=np.float32)
        self.line_colors = np.zeros((0, 4), dtype=np.float32)
        self.scale_used  = 0.0

        self.labels = []

    def build(self):
        """
        Executes the vectorized pipeline.
        Returns True on success, False if no results are available.
        """
        if not getattr(self.model, 'has_results', False) or not self.model.elements:
            return False

        nvm_results = self._batch_compute_nvm()
        if not nvm_results:
            return False                                                

        if self._scale is not None and self._scale > 0:
            scale = float(self._scale)
        else:
                                                                                 
            max_f = max(
                (float(np.max(np.abs(data[self.component]))) for data in nvm_results.values()),
                default=0.0,
            )
            if max_f < 1e-12:
                return True

            char_len = float(np.mean([el.length() for el in self.model.elements.values()]))
            scale = 0.20 * char_len / max_f

        self.scale_used = scale

        all_fv, all_fc, all_ff = [], [], []
        all_lp, all_lc         = [], []
        v_offset = 0

        for el_id, data in nvm_results.items():
            el       = self.model.elements[el_id]
            farr     = data[self.component]
            stations = data['stations']

            L = el.length()
            if L < 1e-9:
                continue

            v_x, v_y, v_z = el.get_local_axes()
            perp = v_y if self.PERP_AXIS.get(self.component, 'y') == 'y' else v_z
            perp = np.asarray(perp, dtype=np.float64)

            if self.component in ['M2', 'M3']:
                perp = -perp
                                                                       
            p_i = el.node_i.get_coords().astype(np.float64)
            p_j = el.node_j.get_coords().astype(np.float64)

            n = len(stations)

            ts    = (stations / L)[:, None]
            bases = p_i[None, :] + ts * (p_j - p_i)[None, :]
            tips  = bases + (scale * farr)[:, None] * perp[None, :]

            if self.component in ['M2', 'M3']:
                disp_scale = unit_registry.force_scale * unit_registry.length_scale
                unit_str = f"{unit_registry.force_unit_name}-{unit_registry.length_unit_name}"
            else:
                disp_scale = unit_registry.force_scale
                unit_str = unit_registry.force_unit_name

            def add_label(idx):
                val = farr[idx]
                                                                
                if abs(val) > 1e-4:
                    disp_val = val * disp_scale
                    self.labels.append({
                        'pos_3d': tips[idx].tolist(),
                        'text':   f"{disp_val:.2f} {unit_str}",
                        'val':    val,
                    })

            if self.show_labels:
                add_label(0)
                add_label(-1)
                max_idx = int(np.argmax(np.abs(farr)))
                if max_idx != 0 and max_idx != (len(farr) - 1):
                    add_label(max_idx)

            colors = np.where(
                farr[:, None] >= 0,
                self.POS_COLOR[None, :],
                self.NEG_COLOR[None, :],
            ).astype(np.float32)

            fv = np.empty((2 * n, 3), dtype=np.float32)
            fc = np.empty((2 * n, 4), dtype=np.float32)

            fv[0::2] = bases.astype(np.float32)
            fv[1::2] = tips.astype(np.float32)
            fc[0::2] = colors
            fc[1::2] = colors

            quads = n - 1
            ff    = np.empty((2 * quads, 3), dtype=np.uint32)
            idx   = np.arange(quads, dtype=np.uint32)

            b0 = v_offset + idx * 2
            t0 = b0 + 1
            b1 = v_offset + (idx + 1) * 2
            t1 = b1 + 1

            ff[0::2] = np.column_stack([b0, t0, b1])
            ff[1::2] = np.column_stack([b1, t0, t1])

            all_fv.append(fv); all_fc.append(fc); all_ff.append(ff)
            v_offset += 2 * n

            tip_f32 = tips.astype(np.float32)
            seg_n   = n - 1

            lp        = np.empty((2 * seg_n, 3), dtype=np.float32)
            lp[0::2]  = tip_f32[:-1]
            lp[1::2]  = tip_f32[1:]
            lc        = np.tile(self.LINE_COLOR, (2 * seg_n, 1))

            close   = np.array([bases[0], tips[0], bases[-1], tips[-1]], dtype=np.float32)
            close_c = np.tile(self.LINE_COLOR, (4, 1))

            all_lp.extend([lp, close])
            all_lc.extend([lc, close_c])

        if all_fv:
            self.fill_verts  = np.concatenate(all_fv)
            self.fill_colors = np.concatenate(all_fc)
            self.fill_faces  = np.concatenate(all_ff)
        if all_lp:
            self.line_pos    = np.concatenate(all_lp)
            self.line_colors = np.concatenate(all_lc)

        return True

    def _resolve_matrices_path(self):
        """Resolve the matrices JSON path exactly once for the whole batch."""
        active_results  = getattr(self.model, 'results', {}) or {}
        active_mat_path = (active_results.get("matrices_path") or
                           active_results.get("matrices_file"))

        if self.matrices_path and os.path.exists(self.matrices_path):
            return self.matrices_path
        if active_mat_path and os.path.exists(active_mat_path):
            return active_mat_path
        if hasattr(self.model, "file_path") and self.model.file_path:
            fallback = self.model.file_path.replace(".mf", "_matrices.json")
            if os.path.exists(fallback):
                return fallback
        return None

    def _batch_compute_nvm(self):
        """
        Computes P, V2, V3, M2, M3 arrays for every element in a single
        vectorized pass.  Mirrors MemberAnalyzer._calculate() exactly —
        same DOF convention, same sign convention, same load handling —
        but eliminates all per-element Python overhead.

        Returns
        -------
        dict  {el_id: {'stations': (S,), 'P': (S,), 'V2': (S,),
                        'V3': (S,), 'M2': (S,), 'M3': (S,)}}
        """

        mat_path = self._resolve_matrices_path()
        if not mat_path:
            print("[ForceDiagram] matrices file not found.")
            return {}

        try:
            with open(mat_path, 'r') as f:
                mat_data = json.load(f)
        except Exception as exc:
            print(f"[ForceDiagram] Error loading matrices: {exc}")
            return {}

        if self.displacements is not None:
            disp_dict = self.displacements
        else:
            res       = getattr(self.model, 'results', {}) or {}
            disp_dict = res.get("_base_displacements", res.get("displacements", {}))

        res              = getattr(self.model, 'results', {}) or {}
        active_case_name = res.get("info", {}).get("case_name", "")

        el_ids       = []
        K_list       = []
        T_list       = []
        FEF_list     = []
        U_list       = []                               
        L_list       = []

        for el_id, el in self.model.elements.items():
            str_id = str(el_id)
            if str_id not in mat_data:
                print(f"[ForceDiagram] Skipping element {el_id}: not in matrices file.")
                continue

            el_data = mat_data[str_id]
            K_list.append(el_data['k'])
            T_list.append(el_data['t'])
            FEF_list.append(el_data['fef'])

            n1_str = str(el.node_i.id)
            n2_str = str(el.node_j.id)
            u1 = disp_dict.get(n1_str, [0.0] * 6)
            u2 = disp_dict.get(n2_str, [0.0] * 6)
            U_list.append(list(u1) + list(u2))                   

            L_list.append(el.length())
            el_ids.append(el_id)

        if not el_ids:
            return {}

        E = len(el_ids)
        S = self.n_stations

        K_all   = np.array(K_list,   dtype=np.float64)                
        T_all   = np.array(T_list,   dtype=np.float64)                
        FEF_all = np.array(FEF_list, dtype=np.float64)            
        U_all   = np.array(U_list,   dtype=np.float64)            
        L_all   = np.array(L_list,   dtype=np.float64)         

        TU         = np.einsum('eij,ej->ei', T_all, U_all)                 
        end_forces = np.einsum('eij,ej->ei', K_all, TU) + FEF_all           

        Fx1 = end_forces[:, 0]         
        Fy1 = end_forces[:, 1]
        Fz1 = end_forces[:, 2]
        My1 = end_forces[:, 4]
        Mz1 = end_forces[:, 5]

        w_loc = np.zeros((E, 3), dtype=np.float64)                           

        for e, el_id in enumerate(el_ids):
            el    = self.model.elements[el_id]
            R_3x3 = T_all[e, 0:3, 0:3]                            

            if active_case_name and hasattr(self.model, 'load_cases'):
                if active_case_name in self.model.load_cases:
                    active_case = self.model.load_cases[active_case_name]
                    for pat_name, sf in active_case.loads:
                        if pat_name in getattr(self.model, 'load_patterns', {}):
                            pat = self.model.load_patterns[pat_name]
                            if getattr(pat, 'self_weight_multiplier', 0) > 0:
                                area    = getattr(el.section, 'A', 0)
                                density = getattr(el.section.material, 'density', 0)
                                w_sw_mag    = area * density * pat.self_weight_multiplier * sf
                                w_sw_global = np.array([0.0, 0.0, -w_sw_mag])
                                w_loc[e]   += R_3x3 @ w_sw_global

            for load in self.model.loads:
                if getattr(load, 'element_id', None) != int(el_id):
                    continue
                if not hasattr(load, 'wx'):
                    continue
                is_local = getattr(load, 'coord_system', 'Global').lower() == 'local'
                w_vec = np.array([load.wx, load.wy, load.wz])
                if not is_local:
                    w_vec = R_3x3 @ w_vec
                w_loc[e] += w_vec

        x = np.linspace(0.0, 1.0, S)[None, :] * L_all[:, None]           

        P_all  = -Fx1[:, None] - w_loc[:, 0:1] * x
        V2_all = -(Fy1[:, None] + w_loc[:, 1:2] * x)
        V3_all = -(Fz1[:, None] + w_loc[:, 2:3] * x)
        M3_all =  Mz1[:, None] + Fy1[:, None] * x + w_loc[:, 1:2] * x**2 / 2.0
        M2_all =  My1[:, None] + Fz1[:, None] * x + w_loc[:, 2:3] * x**2 / 2.0

        for e, el_id in enumerate(el_ids):
            el    = self.model.elements[el_id]
            L_e   = L_all[e]
            R_3x3 = T_all[e, 0:3, 0:3]
            x_e   = x[e]                                              

            for load in self.model.loads:
                if getattr(load, 'element_id', None) != int(el_id):
                    continue
                if not hasattr(load, 'force'):
                    continue                                                

                a        = load.dist * L_e if getattr(load, 'is_relative', False) else load.dist
                is_local = getattr(load, 'coord_system', 'Global').lower() == 'local'

                dir_map = {'X': 0, 'Y': 1, 'Z': 2, '1': 0, '2': 1, '3': 2}
                idx_d   = dir_map.get(str(getattr(load, 'direction', 'Z')).upper(), 2)
                vec     = np.zeros(3)
                vec[idx_d] = load.force
                if not is_local:
                    vec = R_3x3 @ vec

                l_type = getattr(load, 'load_type', 'Force').lower()
                if l_type == 'moment':
                    F_vec = np.zeros(3)
                    M_vec = vec
                else:
                    F_vec = vec
                    M_vec = np.zeros(3)

                mask   = x_e > a                     
                dist_x = x_e - a                      

                P_all[e]  -= F_vec[0] * mask
                V2_all[e] -= F_vec[1] * mask
                V3_all[e] -= F_vec[2] * mask
                M3_all[e] += (F_vec[1] * dist_x - M_vec[2]) * mask
                M2_all[e] += (F_vec[2] * dist_x - M_vec[1]) * mask

        results = {}
        for e, el_id in enumerate(el_ids):
            results[el_id] = {
                'stations': x[e],
                'P':        P_all[e],
                'V2':       V2_all[e],
                'V3':       V3_all[e],
                'M2':       M2_all[e],
                'M3':       M3_all[e],
            }
        return results

    def _get_array(self, data):
        """
        Fetches the correct results array.
        `data` is now the dict returned by _batch_compute_nvm, not a
        MemberAnalyzer instance — but the call-site in build() no longer
        needs this; kept for any external code that calls it directly.
        """
        if isinstance(data, dict):
            return data.get(self.component, data['M3'])
                                                                          
        return {
            'P':  data.P,
            'V2': data.V2,
            'V3': data.V3,
            'M2': data.M2,
            'M3': data.M3,
        }.get(self.component, data.M3)
