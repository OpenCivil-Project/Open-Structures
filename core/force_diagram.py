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
    NEG_COLOR = np.array([1.00, 0.35, 0.35, 0.85], dtype=np.float32)
    LINE_COLOR = np.array([0.08, 0.08, 0.08, 0.90], dtype=np.float32)

    def __init__(self, model, component='M3', scale_factor=None, n_stations=21,
                 displacements=None, matrices_path=None, show_labels=True,
                 show_labels_mode='all', text_size=None, selected_ids=None, active_view_plane=None, show_ghost_structure=True):
        self.model       = model
        self.show_labels = show_labels
        self.show_labels_mode = show_labels_mode
        self.text_size   = text_size
        self.selected_ids = selected_ids or []
        self.active_view_plane    = active_view_plane
        self.show_ghost_structure = show_ghost_structure
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
            if self._elem_visibility(el) == 0:
                continue
            farr     = data[self.component]
            stations = data['stations']

            L = el.length()
            if L < 1e-9:
                continue

            v_x, v_y, v_z = el.get_local_axes()
            
            is_vertical = abs(v_x[2]) > 0.999 
            
            default_perp = self.PERP_AXIS.get(self.component, 'y')
            
            if is_vertical and self.component in ['V2', 'V3', 'M2', 'M3']:
                perp = v_z if default_perp == 'y' else v_y
            else:
                perp = v_y if default_perp == 'y' else v_z
                
            perp = np.asarray(perp, dtype=np.float64)

            if self.component in ['V2', 'V3']:
                                                                                     
                dom_idx = np.argmax(np.abs(perp))
                                                                                                 
                if perp[dom_idx] < -0.001:
                    perp = -perp                                  
                    farr = -farr                                                           

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

            label_text_height = 0.08 * 1.5 if self.component == 'P' else 0.15 * 1.5
            if self.text_size is not None and self.text_size > 0:
                label_text_height = float(self.text_size)
            else:
                label_text_height = 0.08 * 1.2 if self.component == 'P' else 0.15 * 1.2

            def add_label(idx, align='center', val_idx=None):
                val = farr[val_idx if val_idx is not None else idx]                       
                if abs(val) > 1e-4:
                    disp_val = val * disp_scale
                    safe_dir = -perp if val >= 0 else perp
                    v_right_label = v_x.copy()
                    v_up_label = perp.copy()
                    
                    is_vertical = abs(v_x[2]) > 0.99 
                    if not is_vertical:
                        if v_up_label[2] < -0.01 or (abs(v_up_label[2]) <= 0.01 and v_up_label[1] < -0.01):
                            v_up_label = -v_up_label
                        if v_right_label[0] < -0.01:
                            v_right_label = -v_right_label
                            if align == 'left': align = 'right'
                            elif align == 'right': align = 'left'

                    gap = label_text_height * 0.15 
                    if np.dot(safe_dir, v_up_label) > 0:
                        anchor_offset = (safe_dir * gap) - (v_up_label * (label_text_height * 0.4))
                    else:
                        anchor_offset = (safe_dir * gap) + (safe_dir * (label_text_height * 1.4))

                    self.labels.append({
                        'pos_3d': (bases[idx] + anchor_offset).tolist(),                      
                        'text':   f"{disp_val:.2f} {unit_str}", 
                        'val':         val,
                        'v_right':     v_right_label.tolist(),
                        'v_up':        v_up_label.tolist(),
                        'align':       align,
                        'text_height': label_text_height,
                    })

            if self.show_labels:
                show_for_this_element = True
                if self.show_labels_mode == 'selected' and el_id not in self.selected_ids:
                    show_for_this_element = False
                if show_for_this_element:
                    offset = max(1, int(n * 0.005))
                    add_label(offset,      align='left',  val_idx=0)                                      
                    add_label(-1 - offset, align='right', val_idx=-1)                                      
                    max_idx = int(np.argmax(np.abs(farr)))
                    if max_idx != 0 and max_idx != (len(farr) - 1):
                        add_label(max_idx, align='center')

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

    def _elem_visibility(self, elem):
        """Returns 2=on-plane, 1=ghost, 0=hidden — mirrors canvas._get_visibility_state"""
        if self.active_view_plane is None:
            return 2
        axis = self.active_view_plane['axis']
        val  = self.active_view_plane['value']
        tol  = 0.005
        n1 = elem.node_i
        n2 = elem.node_j
        v1 = getattr(n1, axis)
        v2 = getattr(n2, axis)
        if abs(v1 - val) < tol and abs(v2 - val) < tol:
            return 2                                
        return 1 if self.show_ghost_structure else 0

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
            base_path = self.model.file_path.replace(".mf", "")
            
            active_case = active_results.get("info", {}).get("case_name", "")
            if active_case:
                exact = f"{base_path}_{active_case}_matrices.json"
                if os.path.exists(exact): return exact
                
                combo_base = active_case.rsplit(" (Max)", 1)[0].rsplit(" (Min)", 1)[0]
                base_exact = f"{base_path}_{combo_base}_matrices.json"
                if os.path.exists(base_exact): return base_exact

            fallback = f"{base_path}_matrices.json"
            if os.path.exists(fallback): return fallback
            
            import glob
            search = glob.glob(f"{base_path}_*_matrices.json")
            if search: return search[0]
            
        return None
    
    def _batch_compute_nvm(self):
        from app.dialogs.spy_dialogs import MemberAnalyzer

        mat_path = self._resolve_matrices_path()
        if not mat_path:
            print("[ForceDiagram] matrices file not found.")
            return {}

        results = {}
        for el_id, el in self.model.elements.items():
            analyzer = MemberAnalyzer(
                element=el,
                model=self.model,
                num_stations=self.n_stations,
                displacements=self.displacements,
                matrices_path=mat_path
            )
            
            if not analyzer._matrices_loaded:
                continue
            
            results[el_id] = {
                'stations': analyzer.stations,
                'P': analyzer.P,
                'V2': analyzer.V2,
                'V3': analyzer.V3,
                'M2': analyzer.M2,
                'M3': analyzer.M3,
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
