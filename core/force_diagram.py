import os
import json
import numpy as np
from core.units import unit_registry
from core.result_file_cache import json_file_signature
from core.opensees_port.os_force_recovery import (
    is_opensees_result, recover_member_forces, select_opensees_force_state,
)

class ForceDiagramBuilder:
    """
    Builds 3D OpenGL geometry for structural force/moment diagrams.

    For every element in the model:
      1. Recovers NVM arrays with shared matrix/result data and indexed member loads.
      2. Projects force values as perpendicular world-space offsets using local axes.
      3. Returns packed numpy arrays ready for the VBO pipeline:
           fill  -> GLMeshItem (vertices, faces, vertexColors)
           lines -> GLLinePlotItem (pos, color, mode='lines')

    Native force calculations remain in MemberAnalyzer. Each saved file is
    parsed once per revision, and each build indexes loads once instead of
    scanning the whole structure for every member. Geometry uses NumPy arrays.
    """

    PERP_AXIS = {
        'P':  'z',
        'V2': 'y',                                     
        'V3': 'z',                                       
        'M3': 'y',                                                 
        'M2': 'z',     
        'T':  'z',           
    }

    POS_COLOR  = np.array([0.15, 0.40, 1.00, 0.72], dtype=np.float32)
    NEG_COLOR = np.array([1.00, 0.35, 0.35, 0.85], dtype=np.float32)
    LINE_COLOR = np.array([0.08, 0.08, 0.08, 0.90], dtype=np.float32)

    def __init__(self, model, component='M3', scale_factor=None, n_stations=21,
                 displacements=None, matrices_path=None, show_labels=True,
                 show_labels_mode='all', text_size=None, selected_ids=None, active_view_plane=None, show_ghost_structure=True, is_envelope=True, step_number=None,
                 cancelled=None):
        self.model       = model
        self.show_labels = show_labels
        self.show_labels_mode = show_labels_mode
        self.text_size   = text_size
        self.selected_ids = selected_ids or []
        self._selected_ids = set(self.selected_ids)
        self._cancelled = cancelled or (lambda: False)
        self.active_view_plane    = active_view_plane
        self.show_ghost_structure = show_ghost_structure
        self.component   = component
        self._scale      = scale_factor
        self.n_stations  = max(n_stations, 5)
        self.is_envelope = is_envelope
        self.step_number = step_number
        self.displacements  = displacements                                       
        self.matrices_path  = matrices_path                                               
        self.is_opensees = is_opensees_result(getattr(model, 'results', {}) or {}, model)
        self.force_recovery_error = None

        self._reset_output()

    def _reset_output(self):
        """A rebuild replaces every buffer, including empty/failed states."""
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
        self._reset_output()
        self.force_recovery_error = None
        self._selected_ids = set(self.selected_ids)
        if self._cancelled() or not getattr(self.model, 'has_results', False) or not self.model.elements:
            return False

        nvm_results = self._batch_compute_nvm()
        if self._cancelled() or not nvm_results:
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
            if self._cancelled():
                self._reset_output()
                return False
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

            if self.component == 'V2':
                perp = -perp

            if self.component == 'M2':
                perp = -perp
                                                                       
            p_i = el.node_i.get_coords().astype(np.float64)
            p_j = el.node_j.get_coords().astype(np.float64)

            n = len(stations)

            ts    = (stations / L)[:, None]
            bases = p_i[None, :] + ts * (p_j - p_i)[None, :]
            tips  = bases + (scale * farr)[:, None] * perp[None, :]

            if self.component in ['M2', 'M3'] or (self.is_opensees and self.component == 'T'):
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

            def add_label(idx, align='center', val_idx=None, station=None):
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

                    base = bases[idx] if station is None else p_i + (station / L) * (p_j - p_i)
                    self.labels.append({
                        'pos_3d': (base + anchor_offset).tolist(),
                        'text':   f"{disp_val:.2f} {unit_str}", 
                        'val':         val,
                        'v_right':     v_right_label.tolist(),
                        'v_up':        v_up_label.tolist(),
                        'align':       align,
                        'text_height': label_text_height,
                    })

            if self.show_labels:
                show_for_this_element = True
                if self.show_labels_mode == 'selected' and el_id not in self._selected_ids:
                    show_for_this_element = False
                if show_for_this_element:
                    if self.is_opensees:
                        label_start = len(self.labels)
                        for idx, align, station in self._opensees_label_specs(stations, farr):
                            add_label(idx, align=align, station=station)
                        self._separate_member_labels(self.labels[label_start:], perp)
                    else:
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

        if self._cancelled():
            self._reset_output()
            return False
        if all_fv:
            self.fill_verts  = np.concatenate(all_fv)
            self.fill_colors = np.concatenate(all_fc)
            self.fill_faces  = np.concatenate(all_ff)
        if all_lp:
            self.line_pos    = np.concatenate(all_lp)
            self.line_colors = np.concatenate(all_lc)

        return True

    @staticmethod
    def _opensees_label_specs(stations, values):
        """Select physical stations without promoting roundoff to an extremum.

        Split beams retain duplicate stations for one-sided force jumps. Index
        distance therefore cannot determine whether a peak is near an end.
        Keep true signed extrema, even at a jump next to the end; deduplicate
        only values equal within solver roundoff. Constant diagrams need one
        centered value, rather than two ends and an accidental interior peak.
        """
        lo, hi = float(stations[0]), float(stations[-1])
        midpoint = (lo + hi) / 2.0
        tolerance = max(1e-8, 1e-9 * float(np.max(np.abs(values))))
        if float(np.max(values) - np.min(values)) <= tolerance:
            idx = int(np.argmin(np.abs(stations - midpoint)))
            return [(idx, 'center', midpoint)]

        inset = (hi - lo) * 0.05
        specs = [(0, 'left', lo + inset), (len(values) - 1, 'right', hi - inset)]
        end_min, end_max = min(values[0], values[-1]), max(values[0], values[-1])
        for idx, distinct in (
            (int(np.argmin(values)), float(np.min(values)) < end_min - tolerance),
            (int(np.argmax(values)), float(np.max(values)) > end_max + tolerance),
        ):
            if distinct and 0 < idx < len(values) - 1:
                specs.append((idx, 'center', float(stations[idx])))
        return specs

    @staticmethod
    def _separate_member_labels(labels, perp):
        """Separate retained labels using the SDF renderer's glyph extents.

        Keep the station along the member unchanged. Move a conflicting label
        outwards by one text row, so a real near-end peak is still reported.
        """
        occupied = []
        for label in labels:
            height = label['text_height']
            right = np.asarray(label['v_right'])
            up = np.asarray(label['v_up'])
            origin = np.asarray(label['pos_3d'])
            width = len(label['text']) * height * 0.55
            align = label['align']
            shift = height * 0.5 if align == 'left' else (
                -width - height * 0.5 if align == 'right' else -width / 2.0)
            x0 = float(np.dot(origin, right)) + shift
                                                                          
            x1 = x0 + width + height * 0.45
            y0 = float(np.dot(origin, up)) + height * 0.4
            y1 = y0 + height
            safe_dir = -perp if label['val'] >= 0 else perp
            direction = 1.0 if np.dot(safe_dir, up) > 0 else -1.0
            gap = height * 0.15
            epsilon = height * 1e-8
            while True:
                conflicts = [box for box in occupied
                             if x0 < box[1] + gap and x1 > box[0] - gap
                             and y0 < box[3] + gap - epsilon and y1 > box[2] - gap + epsilon]
                if not conflicts:
                    break
                delta = (max(box[3] for box in conflicts) + gap - y0
                         if direction > 0 else min(box[2] for box in conflicts) - gap - y1)
                origin = origin + delta * up
                y0, y1 = y0 + delta, y1 + delta
            label['pos_3d'] = origin.tolist()
            occupied.append((x0, x1, y0, y1))

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
        if is_opensees_result(active_results, self.model):
            return None
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

    def _compute_opensees_nvm(self, results):
        """Use recorded OpenSees forces without importing the Qt/native analyzer."""
        self.force_recovery_error = None
        try:
            state = select_opensees_force_state(results, self.step_number)
            records = state['opensees_forces']
            recovered = {}
            for el_id in self.model.elements:
                if self._cancelled():
                    return {}
                record = records.get(str(el_id))
                if record is None:
                    raise ValueError(f"OpenSees force data for element {el_id} is unavailable.")
                recovered[el_id] = recover_member_forces(record, num_stations=self.n_stations)
            return recovered
        except (KeyError, TypeError, ValueError) as exc:
            self.force_recovery_error = f"OpenSees member forces unavailable: {exc}"
            if 'rerun' not in self.force_recovery_error.lower():
                self.force_recovery_error += ' Rerun the analysis to export member forces.'
            print(f"[ForceDiagram] {self.force_recovery_error}")
            return {}
    
    def _batch_compute_nvm(self):
        active_results = getattr(self.model, 'results', {}) or {}
        active_case = active_results.get('info', {}).get('case_name', '')
        combinations = getattr(self.model, 'load_combos', {}) or {}
        combo_name = active_case
        if combo_name not in combinations:
            for suffix in (' (Max)', ' (Min)'):
                if active_case.endswith(suffix):
                    combo_name = active_case[:-len(suffix)]
                    break
        is_combination = combo_name in combinations
        self.is_opensees = is_opensees_result(active_results, self.model)
        if self.is_opensees and not is_combination:
                                                                                
            return self._compute_opensees_nvm(active_results)
                                                                   
        res_info = active_results.get("info", {})
        is_ltha = res_info.get("type") == "Linear Time History Analysis"
        
        if is_ltha:
            results = {}
            history_path = getattr(self.model, 'results', {}).get("history_path")
            
            try:
                import numpy as np
                                                                
                signature = json_file_signature(history_path)
                source_model = getattr(self.model, '_force_source_model', self.model)
                cached = getattr(source_model, '_ltha_force_history_cache', None)
                if cached is None or cached[0] != signature:
                    npz_data = {}
                    with np.load(history_path) as raw_npz:
                        for key in raw_npz.files:
                            if self._cancelled():
                                return {}
                            if key.startswith('force_elem_'):
                                npz_data[key] = raw_npz[key]
                    if json_file_signature(history_path) != signature:
                        raise OSError('Force history changed while reading; select the result again.')
                                                                              
                    source_model._ltha_force_history_cache = (signature, npz_data)
                else:
                    npz_data = cached[1]
                                                                  
            except Exception as e:
                print(f"Error loading NPZ: {e}")
                return {}

            for el_id, el in self.model.elements.items():
                if self._cancelled():
                    return {}

                key = f"force_elem_{el_id}"
                if key not in npz_data: 
                    continue
                
                hist = npz_data[key] 
                if not self.is_envelope:
                                                                           
                    step = self.step_number if self.step_number is not None else 1
                    step_idx = max(0, min(step - 1, hist.shape[0] - 1))
                    hist = hist[step_idx:step_idx + 1]
                
                L_full = el.length()
                ri = getattr(el, 'end_offset_i', 0.0)
                rj = getattr(el, 'end_offset_j', 0.0)
                stations = np.linspace(ri, L_full - rj, self.n_stations)
                
                Fx1 = hist[:, 0:1]                      
                Fy1 = hist[:, 1:2]
                Fz1 = hist[:, 2:3]
                My1 = hist[:, 4:5]
                Mz1 = hist[:, 5:6]
                
                x_c = (stations - ri).reshape(1, -1)                         
                
                P_hist = np.repeat(-Fx1, self.n_stations, axis=1)                               
                V2_hist = np.repeat(Fy1, self.n_stations, axis=1)
                V3_hist = np.repeat(-Fz1, self.n_stations, axis=1)
                
                M3_hist = Mz1 - Fy1 @ x_c                               
                M2_hist = My1 + Fz1 @ x_c
                
                if getattr(self, 'is_envelope', True):
                                                                                                    
                    idx_P = np.argmax(np.abs(P_hist), axis=0)
                    P_arr = P_hist[idx_P, np.arange(self.n_stations)]
                    
                    idx_V2 = np.argmax(np.abs(V2_hist), axis=0)
                    V2_arr = V2_hist[idx_V2, np.arange(self.n_stations)]
                    
                    idx_V3 = np.argmax(np.abs(V3_hist), axis=0)
                    V3_arr = V3_hist[idx_V3, np.arange(self.n_stations)]
                    
                    idx_M2 = np.argmax(np.abs(M2_hist), axis=0)
                    M2_arr = M2_hist[idx_M2, np.arange(self.n_stations)]
                    
                    idx_M3 = np.argmax(np.abs(M3_hist), axis=0)
                    M3_arr = M3_hist[idx_M3, np.arange(self.n_stations)]
                else:
                                                                                    
                    step_idx = 0
                    
                    P_arr = P_hist[step_idx, :]
                    V2_arr = V2_hist[step_idx, :]
                    V3_arr = V3_hist[step_idx, :]
                    M2_arr = M2_hist[step_idx, :]
                    M3_arr = M3_hist[step_idx, :]
                    
                results[el_id] = {
                    'stations': stations, 'P': P_arr, 'V2': V2_arr, 'V3': V3_arr, 'M2': M2_arr, 'M3': M3_arr
                }
                
            return results

        from app.dialogs.spy_dialogs import MemberAnalyzer, ForceAnalysisContext

        mat_path = self._resolve_matrices_path()
        if is_combination and mat_path is None:
                                                                           
            mat_path = self.matrices_path
        if not mat_path and not is_combination:
            print("[ForceDiagram] matrices file not found.")
            return {}

        results = {}
        context = ForceAnalysisContext(self.model, cancelled=self._cancelled)
        for el_id, el in self.model.elements.items():
            if self._cancelled():
                return {}
            analyzer = MemberAnalyzer(
                element=el,
                model=self.model,
                num_stations=self.n_stations,
                displacements=self.displacements,
                matrices_path=mat_path,
                results_dict=active_results,
                                                                            
                step_number=None if is_combination else self.step_number,
                _analysis_context=context,
            )
            
            if not analyzer.forces_loaded:
                if is_combination:
                    self.force_recovery_error = (analyzer.force_recovery_error or
                                                 f'Combination member forces for element {el_id} are unavailable.')
                    return {}
                continue
            if is_combination:
                self.is_opensees = analyzer.is_opensees
            
            results[el_id] = {
                'stations': analyzer.stations,
                'P': analyzer.P,
                'V2': analyzer.V2,
                'V3': analyzer.V3,
                'M2': analyzer.M2,
                'M3': analyzer.M3,
                'T': analyzer.T,
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
            'T':  data.T,
        }.get(self.component, data.M3)
