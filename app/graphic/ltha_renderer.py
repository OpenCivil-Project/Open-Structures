import numpy as np

def _contour_colormap_batch(t):
    """
    Vectorized port of Canvas._contour_colormap. t is an array of any shape,
    normalized to [0, 1]. Returns an array of shape t.shape + (4,) RGBA.
    Same blue->cyan->green->yellow->red bands, same edges, array-shaped.
    """
    t = np.clip(t, 0.0, 1.0)
    r = np.zeros_like(t)
    g = np.zeros_like(t)
    b = np.ones_like(t)

    band0 = t < 0.25
    band1 = (t >= 0.25) & (t < 0.5)
    band2 = (t >= 0.5) & (t < 0.75)
    band3 = t >= 0.75

    g = np.where(band0, t / 0.25, g)

    r = np.where(band1, 0.0, r)
    g = np.where(band1, 1.0, g)
    b = np.where(band1, 1.0 - (t - 0.25) / 0.25, b)

    r = np.where(band2, (t - 0.5) / 0.25, r)
    g = np.where(band2, 1.0, g)
    b = np.where(band2, 0.0, b)

    r = np.where(band3, 1.0, r)
    g = np.where(band3, 1.0 - (t - 0.75) / 0.25, g)
    b = np.where(band3, 0.0, b)

    a = np.ones_like(t)
    return np.stack([r, g, b, a], axis=-1)

def _contour_scalar_batch(u_global, component, absolute=False):
    """
    Vectorized port of Canvas._contour_scalar. u_global is (..., 3) of raw
    (unscaled) global Ux,Uy,Uz. Returns (...,) scalar: picked component or
    resultant norm -- same convention as the static contour render.
    """
    idx = {"Ux": 0, "Uy": 1, "Uz": 2}.get(component)
    if idx is not None:
        val = u_global[..., idx]
        return np.abs(val) if absolute else val
    return np.linalg.norm(u_global, axis=-1)

def _make_coil_template(turns, lead_frac, pts_per_turn=12):
    """
    Builds a unit coil path ONCE: point(t) = p1 + axial*L*u + rc*R*v + rs*R*w,
    where L=actual length, R=actual radius, u/v/w=actual per-spring frame.
    Sample sequence matches the original add_line_spring exactly (p1 -> lead-in
    -> coil turns -> lead-out -> p2), so a zero-displacement frame renders
    pixel-identical to the old static geometry.
    """
    total_pts = turns * pts_per_turn
    coil_len_frac = 1.0 - 2.0 * lead_frac

    axial = [0.0, lead_frac]
    rc = [0.0, 0.0]
    rs = [0.0, 0.0]
    for i in range(1, total_pts + 1):
        t = i / total_pts
        angle = t * turns * 2 * np.pi
        axial.append(lead_frac + coil_len_frac * t)
        rc.append(np.cos(angle))
        rs.append(np.sin(angle))
    axial += [1.0 - lead_frac, 1.0]
    rc += [0.0, 0.0]
    rs += [0.0, 0.0]

    return (np.array(axial, dtype=np.float32),
            np.array(rc, dtype=np.float32),
            np.array(rs, dtype=np.float32))

def _coil_batch(p1, p2, v, w, radius, axial_frac, radial_cos, radial_sin):
    """
    Vectorized coil polyline for N springs at once. p1/p2/v/w: (N,3),
    radius: (N,1). Zero Python loops, zero trig -- trig is baked into the
    template already. Returns flat (2*(M-1)*N, 3) line-segment vertex array
    (pairs, mode='lines').
    """
    vec = p2 - p1
    L = np.maximum(np.linalg.norm(vec, axis=1, keepdims=True), 1e-6)
    u = vec / L

    axial = axial_frac[None, :] * L
    rc = radial_cos[None, :] * radius
    rs = radial_sin[None, :] * radius

    pts = (p1[:, None, :]
           + axial[:, :, None] * u[:, None, :]
           + rc[:, :, None] * v[:, None, :]
           + rs[:, :, None] * w[:, None, :])

    start = pts[:, :-1, :]
    end = pts[:, 1:, :]
    return np.stack([start, end], axis=2).reshape(-1, 3)

def _perp_frame(axis):
    """Given (N,3) unit axis vectors, returns (v, w) perpendicular frame."""
    up = np.tile(np.array([0.0, 0.0, 1.0], dtype=np.float32), (axis.shape[0], 1))
    parallel = np.abs(np.sum(axis * up, axis=1)) > 0.99
    up[parallel] = np.array([0.0, 1.0, 0.0], dtype=np.float32)
    v = np.cross(axis, up)
    v /= np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-9)
    w = np.cross(axis, v)
    return v, w

class VectorizedLTHAEngine:
    """
    High-performance vectorized engine for LTHA animation.
    Eliminates Python loops by computing Hermite curves for all elements 
    simultaneously using batched NumPy tensor operations.
    """
    def __init__(self, num_elements):
        self.N = num_elements
        self.num_points = 11
        
        self.P1 = np.zeros((self.N, 3), dtype=np.float32)
        self.P2 = np.zeros((self.N, 3), dtype=np.float32)
        self.L = np.zeros((self.N, 1), dtype=np.float32)
        self.off_i = np.zeros((self.N, 1), dtype=np.float32)
        self.off_j = np.zeros((self.N, 1), dtype=np.float32)
        self.R = np.zeros((self.N, 3, 3), dtype=np.float32)
        
        self.idx_i = np.zeros(self.N, dtype=np.int32)
        self.idx_j = np.zeros(self.N, dtype=np.int32)
        self.colors = np.zeros((self.N, 4), dtype=np.float32)

        self.contour_active = False
        self.contour_component = "Resultant"
        self.contour_c_min = 0.0
        self.contour_c_max = 1.0
        self.contour_opacity = 1.0
        self.contour_absolute = False

        self._tmpl_axis = _make_coil_template(turns=3, lead_frac=0.20)
        self._tmpl_link1 = _make_coil_template(turns=4, lead_frac=0.15)
        self._tmpl_link2 = _make_coil_template(turns=5, lead_frac=0.40)

        self.n_nodal_springs = 0
        self.n_link1_springs = 0
        self.n_link2_springs = 0
        
        s = np.linspace(0, 1, self.num_points).reshape(1, self.num_points).astype(np.float32)
        s2 = s * s
        s3 = s2 * s
        
        self.s = s
        self.one_minus_s = 1.0 - s
        self.H1 = 1.0 - 3.0*s2 + 2.0*s3
        self.H3 = 3.0*s2 - 2.0*s3
        self.H2_base = s * (1.0 - s)**2
        self.H4_base = s * (s2 - s)

    def set_contour(self, active, component, c_min, c_max, opacity=1.0, absolute=False):
        """Called from canvas.py whenever contour settings change (load time
        or live toggle/component switch). c_min/c_max should be the stable,
        precomputed range for `component` -- not rescanned here."""
        self.contour_active = active
        self.contour_component = component
        self.contour_c_min = c_min
        self.contour_c_max = c_max
        self.contour_opacity = opacity
        self.contour_absolute = absolute

    def compute_wireframe(self, U_nodes, scale):
        """
        Calculates all line geometry for the current frame instantly.
        U_nodes: NumPy array of shape (N_nodes, 6) containing current timestep displacements
        """
        if self.N == 0:
            return np.array([]), np.array([])

        U_i = U_nodes[self.idx_i] * scale
        U_j = U_nodes[self.idx_j] * scale
        
        u_global_i, theta_global_i = U_i[:, :3], U_i[:, 3:]
        u_global_j, theta_global_j = U_j[:, :3], U_j[:, 3:]
        u_global_i_raw = U_nodes[self.idx_i][:, :3]
        u_global_j_raw = U_nodes[self.idx_j][:, :3]
        
        u_local_i = np.einsum('nij,nj->ni', self.R, u_global_i)
        theta_local_i = np.einsum('nij,nj->ni', self.R, theta_global_i)
        u_local_j = np.einsum('nij,nj->ni', self.R, u_global_j)
        theta_local_j = np.einsum('nij,nj->ni', self.R, theta_global_j)
        
        u1_i, u1_j = u_local_i[:, 0:1], u_local_j[:, 0:1]
        v_i, v_j   = u_local_i[:, 1:2], u_local_j[:, 1:2]
        w_i, w_j   = u_local_i[:, 2:3], u_local_j[:, 2:3]
        
        dv_i, dv_j = theta_local_i[:, 2:3], theta_local_j[:, 2:3]
        dw_i, dw_j = -theta_local_i[:, 1:2], -theta_local_j[:, 1:2]
        
        x_val = self.L @ self.s
        
        v_flex_i, w_flex_i = v_i + dv_i * self.off_i, w_i + dw_i * self.off_i
        v_flex_j, w_flex_j = v_j - dv_j * self.off_j, w_j - dw_j * self.off_j
        
        L_flex = np.maximum(self.L - self.off_i - self.off_j, 1e-6)
        s_flex = np.clip((x_val - self.off_i) / L_flex, 0.0, 1.0)
        
        s2 = s_flex * s_flex
        s3 = s2 * s_flex
        H1 = 1.0 - 3.0*s2 + 2.0*s3
        H2 = (s_flex * L_flex) * (1.0 - s_flex)**2
        H3 = 3.0*s2 - 2.0*s3
        H4 = (s_flex * L_flex) * (s2 - s_flex)
        
        disp_axial = u1_i + (u1_j - u1_i) * s_flex
        disp_v = v_flex_i * H1 + dv_i * H2 + v_flex_j * H3 + dv_j * H4
        disp_w = w_flex_i * H1 + dw_i * H2 + w_flex_j * H3 + dw_j * H4
        
        mask_i = x_val <= self.off_i + 1e-6
        mask_j = x_val >= self.L - self.off_j - 1e-6
        
        disp_axial = np.where(mask_i, u1_i * np.ones_like(x_val), disp_axial)
        disp_v = np.where(mask_i, v_i + dv_i * x_val, disp_v)
        disp_w = np.where(mask_i, w_i + dw_i * x_val, disp_w)
        
        dx_from_j = x_val - self.L
        disp_axial = np.where(mask_j, u1_j * np.ones_like(x_val), disp_axial)
        disp_v = np.where(mask_j, v_j + dv_j * dx_from_j, disp_v)
        disp_w = np.where(mask_j, w_j + dw_j * dx_from_j, disp_w)

        local_pos = np.stack([x_val + disp_axial, disp_v, disp_w], axis=2)
        
        RT = self.R.transpose(0, 2, 1)
        global_disp = np.einsum('nij,nkj->nki', RT, local_pos)
        v1_global = self.R[:, 0, :]
        P1_shifted = self.P1 + v1_global * self.off_i

        global_pos = P1_shifted[:, None, :] + global_disp
                                                                              
        start_pts = global_pos[:, :-1, :]              
        end_pts   = global_pos[:, 1:, :]               
        
        lines = np.stack([start_pts, end_pts], axis=2)                
        lines_flat = lines.reshape(-1, 3)                         
        
        if self.contour_active:
            scalar_i = _contour_scalar_batch(u_global_i_raw, self.contour_component, self.contour_absolute).reshape(self.N, 1)
            scalar_j = _contour_scalar_batch(u_global_j_raw, self.contour_component, self.contour_absolute).reshape(self.N, 1)
            scalar_station = scalar_i + (scalar_j - scalar_i) * self.s
            span = max(self.contour_c_max - self.contour_c_min, 1e-12)
            t = (scalar_station - self.contour_c_min) / span
            colors_station = _contour_colormap_batch(t)
            start_colors = colors_station[:, :-1, :]
            end_colors   = colors_station[:, 1:, :]
            colors_flat = np.stack([start_colors, end_colors], axis=2).reshape(-1, 4)
        else:
            colors_flat = np.repeat(self.colors, 20, axis=0)
        
        return lines_flat, colors_flat
    
    def set_extruded_mapping(self, E, P, off, Y, Z, colors):
        """Stores the flat topology mapping for instantly building 3D faces."""
        self.ext_E = np.array(E, dtype=np.int32)
        self.ext_P = np.array(P, dtype=np.int32)
        self.ext_off = np.array(off, dtype=np.float32)
        self.ext_Y = np.array(Y, dtype=np.float32)[:, None]
        self.ext_Z = np.array(Z, dtype=np.float32)[:, None]
        self.ext_colors_flat = np.array(colors, dtype=np.float32).flatten()

    def compute_extruded(self, U_nodes, scale):
        if not hasattr(self, 'ext_E') or len(self.ext_E) == 0:
            return np.array([]), np.array([])
            
        U_i = U_nodes[self.idx_i] * scale
        U_j = U_nodes[self.idx_j] * scale
        u_global_i_raw = U_nodes[self.idx_i][:, :3]
        u_global_j_raw = U_nodes[self.idx_j][:, :3]
        
        u_local_i = np.einsum('nij,nj->ni', self.R, U_i[:, :3])
        theta_local_i = np.einsum('nij,nj->ni', self.R, U_i[:, 3:])
        u_local_j = np.einsum('nij,nj->ni', self.R, U_j[:, :3])
        theta_local_j = np.einsum('nij,nj->ni', self.R, U_j[:, 3:])
        
        u1_i, u1_j = u_local_i[:, 0:1], u_local_j[:, 0:1]
        v_i, v_j   = u_local_i[:, 1:2], u_local_j[:, 1:2]
        w_i, w_j   = u_local_i[:, 2:3], u_local_j[:, 2:3]
        dv_i, dv_j = theta_local_i[:, 2:3], theta_local_j[:, 2:3]
        dw_i, dw_j = -theta_local_i[:, 1:2], -theta_local_j[:, 1:2]
        twist_i, twist_j = theta_local_i[:, 0:1], theta_local_j[:, 0:1]

        v_flex_i, w_flex_i = v_i + dv_i * self.off_i, w_i + dw_i * self.off_i
        v_flex_j, w_flex_j = v_j - dv_j * self.off_j, w_j - dw_j * self.off_j
        
        L_flex = np.maximum(self.L - self.off_i - self.off_j, 1e-6)
        x_val = self.off_i + L_flex @ self.s
        s_flex = self.s                                       
        
        s2 = s_flex * s_flex
        s3 = s2 * s_flex
        H1 = 1.0 - 3.0*s2 + 2.0*s3
        H2 = (s_flex * L_flex) * (1.0 - s_flex)**2
        H3 = 3.0*s2 - 2.0*s3
        H4 = (s_flex * L_flex) * (s2 - s_flex)
        
        dH1 = -6.0*s_flex + 6.0*s2
        dH2 = L_flex * (1.0 - 4.0*s_flex + 3.0*s2)
        dH3 = 6.0*s_flex - 6.0*s2
        dH4 = L_flex * (3.0*s2 - 2.0*s_flex)
        
        axial_strain = (u1_j - u1_i) / self.L
        disp_axial = u1_i + axial_strain * x_val
        disp_v = v_flex_i * H1 + dv_i * H2 + v_flex_j * H3 + dv_j * H4
        disp_w = w_flex_i * H1 + dw_i * H2 + w_flex_j * H3 + dw_j * H4
        
        d_axial_ds = (L_flex + axial_strain * L_flex) * np.ones((1, self.num_points), dtype=np.float32)
        d_v_ds = (v_flex_i * dH1 + dv_i * dH2 + v_flex_j * dH3 + dv_j * dH4)
        d_w_ds = (w_flex_i * dH1 + dw_i * dH2 + w_flex_j * dH3 + dw_j * dH4)
        curr_twist = twist_i + (twist_j - twist_i) * (x_val / self.L)

        local_pos = np.stack([x_val + disp_axial, disp_v, disp_w], axis=2)
        local_tan = np.stack([d_axial_ds, d_v_ds, d_w_ds], axis=2)
        
        RT = self.R.transpose(0, 2, 1)
        global_pos = self.P1[:, None, :] + np.einsum('nij,nkj->nki', RT, local_pos)
        
        norms = np.linalg.norm(local_tan, axis=2, keepdims=True)
        norms[norms < 1e-9] = 1.0
        local_tan_norm = local_tan / norms
        v1_curr = np.einsum('nij,nkj->nki', RT, local_tan_norm)

        v2_orig = self.R[:, 1, :][:, None, :] 
        v3_orig = self.R[:, 2, :][:, None, :] 
        
        c_t = np.cos(curr_twist)[..., None] 
        s_t = np.sin(curr_twist)[..., None]
        
        v2_twisted = c_t * v2_orig + s_t * v3_orig
        proj = np.sum(v2_twisted * v1_curr, axis=2, keepdims=True) * v1_curr
        v2_curr = v2_twisted - proj
        
        norms_v2 = np.linalg.norm(v2_curr, axis=2, keepdims=True)
        norms_v2[norms_v2 < 1e-9] = 1.0
        v2_curr = v2_curr / norms_v2
        v3_curr = np.cross(v1_curr, v2_curr)
        
        E = self.ext_E
        P = self.ext_P
        verts = global_pos[E, P] + self.ext_off + self.ext_Y * v2_curr[E, P] + self.ext_Z * v3_curr[E, P]
        
        if self.contour_active:
            scalar_i = _contour_scalar_batch(u_global_i_raw, self.contour_component, self.contour_absolute).reshape(self.N, 1)
            scalar_j = _contour_scalar_batch(u_global_j_raw, self.contour_component, self.contour_absolute).reshape(self.N, 1)
            scalar_station = scalar_i + (scalar_j - scalar_i) * self.s
            span = max(self.contour_c_max - self.contour_c_min, 1e-12)
            t = (scalar_station - self.contour_c_min) / span
            colors_station = _contour_colormap_batch(t)
            colors_station[..., 3] = self.contour_opacity
            colors_flat = colors_station[E, P].flatten()
        else:
            colors_flat = self.ext_colors_flat
        
        return verts.flatten(), colors_flat

    def set_nodal_spring_mapping(self, springs):
        """
        springs: list of dicts, one per active DOF spring:
          {'node_id': str, 'base_pt': (x,y,z), 'axis_vec': (ax,ay,az) unit,
           'length': float, 'radius': float, 'color': (r,g,b,a)}
        node_map / dummy_idx resolve node_id -> row in the displacement tensor.
        axis_vec is world-fixed (it's the DOF direction, not the node's
        orientation), so the coil's (v,w) roll frame is exact, not
        approximate -- it never needs to be recomputed.
        """
        self.n_nodal_springs = len(springs)
        if not springs:
            return
        self.ns_idx = np.array([s['idx'] for s in springs], dtype=np.int32)
        base = np.array([s['base_pt'] for s in springs], dtype=np.float32)
        axis = np.array([s['axis_vec'] for s in springs], dtype=np.float32)
        length = np.array([s['length'] for s in springs], dtype=np.float32).reshape(-1, 1)
        self.ns_radius = np.array([s['radius'] for s in springs], dtype=np.float32).reshape(-1, 1)
        self.ns_colors = np.array([s['color'] for s in springs], dtype=np.float32)

        self.ns_p_orig = base                                                
        self.ns_p_anchor = base + axis * length                          
        self.ns_v, self.ns_w = _perp_frame(axis)

    def compute_nodal_springs(self, U_nodes, scale):
        if not self.n_nodal_springs:
            return np.array([]), np.array([])
        p_moving = self.ns_p_orig + U_nodes[self.ns_idx][:, :3] * scale
        lines = _coil_batch(p_moving, self.ns_p_anchor, self.ns_v, self.ns_w,
                             self.ns_radius, *self._tmpl_axis)
        segs = self._tmpl_axis[0].shape[0] - 1
        colors = np.repeat(self.ns_colors, 2 * segs, axis=0)
        return lines, colors

    def set_link1_mapping(self, links):
        """
        links: list of dicts:
          {'idx': int, 'base_pt': (x,y,z), 'ground_pt': (x,y,z),
           'radius': float, 'color': (r,g,b,a)}
        ground_pt is fixed forever. The (v,w) roll frame is derived once from
        the ORIGINAL base_pt->ground_pt direction and reused every frame --
        this is the one approximation in the whole system: the coil's twist
        doesn't re-orient for transverse displacement, only its true
        start/end points and length do (those are exact, every frame).
        """
        self.n_link1_springs = len(links)
        if not links:
            return
        self.l1_idx = np.array([l['idx'] for l in links], dtype=np.int32)
        self.l1_p_orig = np.array([l['base_pt'] for l in links], dtype=np.float32)
        self.l1_p_ground = np.array([l['ground_pt'] for l in links], dtype=np.float32)
        self.l1_radius = np.array([l['radius'] for l in links], dtype=np.float32).reshape(-1, 1)
        self.l1_colors = np.array([l['color'] for l in links], dtype=np.float32)

        vec0 = self.l1_p_ground - self.l1_p_orig
        u0 = vec0 / np.maximum(np.linalg.norm(vec0, axis=1, keepdims=True), 1e-9)
        self.l1_v, self.l1_w = _perp_frame(u0)

    def compute_link1_springs(self, U_nodes, scale):
        if not self.n_link1_springs:
            return np.array([]), np.array([])
        p_moving = self.l1_p_orig + U_nodes[self.l1_idx][:, :3] * scale
        lines = _coil_batch(p_moving, self.l1_p_ground, self.l1_v, self.l1_w,
                             self.l1_radius, *self._tmpl_link1)
        segs = self._tmpl_link1[0].shape[0] - 1
        colors = np.repeat(self.l1_colors, 2 * segs, axis=0)
        return lines, colors

    def set_link2_mapping(self, links):
        """
        links: list of dicts:
          {'idx_i': int, 'idx_j': int, 'base_i': (x,y,z), 'base_j': (x,y,z),
           'radius': float, 'color': (r,g,b,a)}
        Same roll-frame approximation as link1, from original geometry.
        """
        self.n_link2_springs = len(links)
        if not links:
            return
        self.l2_idx_i = np.array([l['idx_i'] for l in links], dtype=np.int32)
        self.l2_idx_j = np.array([l['idx_j'] for l in links], dtype=np.int32)
        self.l2_p_orig_i = np.array([l['base_i'] for l in links], dtype=np.float32)
        self.l2_p_orig_j = np.array([l['base_j'] for l in links], dtype=np.float32)
        self.l2_radius = np.array([l['radius'] for l in links], dtype=np.float32).reshape(-1, 1)
        self.l2_colors = np.array([l['color'] for l in links], dtype=np.float32)

        vec0 = self.l2_p_orig_j - self.l2_p_orig_i
        u0 = vec0 / np.maximum(np.linalg.norm(vec0, axis=1, keepdims=True), 1e-9)
        self.l2_v, self.l2_w = _perp_frame(u0)

    def compute_link2_springs(self, U_nodes, scale):
        if not self.n_link2_springs:
            return np.array([]), np.array([])
        p_i = self.l2_p_orig_i + U_nodes[self.l2_idx_i][:, :3] * scale
        p_j = self.l2_p_orig_j + U_nodes[self.l2_idx_j][:, :3] * scale
        lines = _coil_batch(p_i, p_j, self.l2_v, self.l2_w,
                             self.l2_radius, *self._tmpl_link2)
        segs = self._tmpl_link2[0].shape[0] - 1
        colors = np.repeat(self.l2_colors, 2 * segs, axis=0)
        return lines, colors

    def compute_all_springs(self, U_nodes, scale):
        parts_v, parts_c = [], []
        for fn in (self.compute_nodal_springs, self.compute_link1_springs,
                   self.compute_link2_springs):
            v, c = fn(U_nodes, scale)
            if len(v):
                parts_v.append(v)
                parts_c.append(c)
        if not parts_v:
            return np.array([]), np.array([])
        return np.concatenate(parts_v, axis=0), np.concatenate(parts_c, axis=0)
