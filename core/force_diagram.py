import numpy as np
from core.units import unit_registry

class ForceDiagramBuilder:
    """
    Builds 3D OpenGL geometry for structural force/moment diagrams.
    
    For every element in the model:
      1. Runs MemberAnalyzer to get force arrays at n_stations.
      2. Projects force values as perpendicular world-space offsets using local axes.
      3. Returns packed numpy arrays ready for pyqtgraph.opengl:
           fill  -> GLMeshItem (vertices, faces, vertexColors)
           lines -> GLLinePlotItem (pos, color, mode='lines')
    """
    
    PERP_AXIS = {
        'P':  'y',
        'V2': 'y',   # minor axis → local y
        'V3': 'z',   # major axis → local z
        'M3': 'y',   # minor axis → local y
        'M2': 'z',   # major axis → local z
    }

    # SAP2000-style: Positive = Blue, Negative = Red
    POS_COLOR  = np.array([0.15, 0.40, 1.00, 0.72], dtype=np.float32)
    NEG_COLOR  = np.array([1.00, 0.20, 0.20, 0.72], dtype=np.float32)
    LINE_COLOR = np.array([0.08, 0.08, 0.08, 0.90], dtype=np.float32)

    def __init__(self, model, component='M3', scale_factor=None, n_stations=21,
                 displacements=None, matrices_path=None, show_labels=True):
        self.model      = model
        self.show_labels = show_labels
        self.component  = component
        self._scale     = scale_factor
        self.n_stations = max(n_stations, 5)
        self.displacements  = displacements   # override model.results if provided
        self.matrices_path  = matrices_path   # explicit path fixes the no-case-suffix bug

        # Outputs (Populated by build())
        self.fill_verts  = np.zeros((0, 3), dtype=np.float32)
        self.fill_colors = np.zeros((0, 4), dtype=np.float32)
        self.fill_faces  = np.zeros((0, 3), dtype=np.uint32)
        self.line_pos    = np.zeros((0, 3), dtype=np.float32)
        self.line_colors = np.zeros((0, 4), dtype=np.float32)
        self.scale_used  = 0.0

        self.labels = []

    def build(self):
        """
        Executes the vectorization pipeline.
        Returns True on success, False if no results are available.
        """
        # Note: Late import prevents circular dependency for now.
        # Future architecture goal: Move MemberAnalyzer to a core/results module.
        from app.dialogs.spy_dialogs import MemberAnalyzer

        if not getattr(self.model, 'has_results', False) or not self.model.elements:
            return False

        # Phase 1: Build analyzers for all elements
        analyzers = {}
        for el_id, el in self.model.elements.items():
            try:
                analyzers[el_id] = MemberAnalyzer(
                    el, self.model,
                    num_stations=self.n_stations,
                    displacements=self.displacements,
                    matrices_path=self.matrices_path,
                )
            except Exception as exc:
                print(f"[ForceDiagram] Skipping element {el_id}: {exc}")

        if not analyzers:
            return False  # nothing to draw — caller handles empty state

        # Phase 2: Determine Global Scale Factor
        if self._scale is not None and self._scale > 0:
            scale = float(self._scale)
        else:
            # Auto-scale: Max diagram height = 20% of the average element length
            max_f = max(
                (float(np.max(np.abs(self._get_array(a)))) for a in analyzers.values()),
                default=0.0
            )
            if max_f < 1e-12:
                return True
            
            char_len = float(np.mean([el.length() for el in self.model.elements.values()]))
            scale = 0.20 * char_len / max_f
            
        self.scale_used = scale

        # Phase 3: Accumulate Geometry (Vectorized)
        all_fv, all_fc, all_ff = [], [], []
        all_lp, all_lc         = [], []
        v_offset = 0

        for el_id, analyzer in analyzers.items():
            el = self.model.elements[el_id]
            farr = self._get_array(analyzer)
            
            L = el.length()
            if L < 1e-9:
                continue

            v_x, v_y, v_z = el.get_local_axes()
            perp = v_y if self.PERP_AXIS.get(self.component, 'y') == 'y' else v_z
            perp = np.asarray(perp, dtype=np.float64)

            # ---------------------------------------------------------
            # Invert perpendicular axis for Moments 
            # (Draws positive moment on tension side / bottom)
            # ---------------------------------------------------------
            if self.component in ['M2', 'M3']:
                perp = -perp
            # ---------------------------------------------------------
            
            p_i = el.node_i.get_coords().astype(np.float64)
            p_j = el.node_j.get_coords().astype(np.float64)

            stations = analyzer.stations
            n = len(stations)
            
            # Base and Tip coordinate generation (Pure NumPy)
            ts = (stations / L)[:, None]
            bases = p_i[None, :] + ts * (p_j - p_i)[None, :]
            tips = bases + (scale * farr)[:, None] * perp[None, :]

            if self.component in ['M2', 'M3']:
                disp_scale = unit_registry.force_scale * unit_registry.length_scale
                unit_str = f"{unit_registry.force_unit_name}-{unit_registry.length_unit_name}"
            else:
                disp_scale = unit_registry.force_scale
                unit_str = unit_registry.force_unit_name

            def add_label(idx):
                val = farr[idx]
                # Skip tiny zero-values to keep the screen clean
                if abs(val) > 1e-4:
                    disp_val = val * disp_scale
                    self.labels.append({
                        'pos_3d': tips[idx].tolist(),
                        'text': f"{disp_val:.2f} {unit_str}",
                        'val': val # Keep raw value for color logic
                    })

            if self.show_labels:
                add_label(0)
                add_label(-1)
                max_idx = int(np.argmax(np.abs(farr)))
                if max_idx != 0 and max_idx != (len(farr) - 1):
                    add_label(max_idx)

            # Color assignment based on force sign
            colors = np.where(
                farr[:, None] >= 0,
                self.POS_COLOR[None, :],
                self.NEG_COLOR[None, :]
            ).astype(np.float32)

            # --- Fill Geometry (Triangle Strip logic via Quads) ---
            fv = np.empty((2 * n, 3), dtype=np.float32)
            fc = np.empty((2 * n, 4), dtype=np.float32)
            
            fv[0::2] = bases.astype(np.float32)
            fv[1::2] = tips.astype(np.float32)
            fc[0::2] = colors
            fc[1::2] = colors

            quads = n - 1
            ff = np.empty((2 * quads, 3), dtype=np.uint32)
            idx = np.arange(quads, dtype=np.uint32)
            
            b0 = v_offset + idx * 2
            t0 = b0 + 1
            b1 = v_offset + (idx + 1) * 2
            t1 = b1 + 1
            
            ff[0::2] = np.column_stack([b0, t0, b1])
            ff[1::2] = np.column_stack([b1, t0, t1])

            all_fv.append(fv); all_fc.append(fc); all_ff.append(ff)
            v_offset += 2 * n

            # --- Outline Geometry (Lines) ---
            tip_f32 = tips.astype(np.float32)
            seg_n = n - 1
            
            lp = np.empty((2 * seg_n, 3), dtype=np.float32)
            lp[0::2] = tip_f32[:-1]
            lp[1::2] = tip_f32[1:]
            lc = np.tile(self.LINE_COLOR, (2 * seg_n, 1))
            
            close = np.array([bases[0], tips[0], bases[-1], tips[-1]], dtype=np.float32)
            close_c = np.tile(self.LINE_COLOR, (4, 1))
            
            all_lp.extend([lp, close])
            all_lc.extend([lc, close_c])

        # Phase 4: Pack arrays for GPU
        if all_fv:
            self.fill_verts  = np.concatenate(all_fv)
            self.fill_colors = np.concatenate(all_fc)
            self.fill_faces  = np.concatenate(all_ff)
        if all_lp:
            self.line_pos    = np.concatenate(all_lp)
            self.line_colors = np.concatenate(all_lc)

        return True

    def _get_array(self, analyzer):
        """Fetches the correct results array from the MemberAnalyzer based on component."""
        return {
            'P':  analyzer.P,
            'V2': analyzer.V2,
            'V3': analyzer.V3,
            'M2': analyzer.M2,
            'M3': analyzer.M3,
        }.get(self.component, analyzer.M3)