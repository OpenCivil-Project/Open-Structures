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
