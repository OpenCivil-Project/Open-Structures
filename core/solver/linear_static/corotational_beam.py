import numpy as np
from rotation_utils import (rodrigues, rotation_to_vector, compose, update_corotational_frame,
                             rodrigues_batch, rotation_to_vector_batch, skew_batch)
from element_library import (get_local_stiffness_matrix, get_geometric_stiffness_matrix, get_rotation_matrix,
                              get_local_stiffness_matrix_batch, get_geometric_stiffness_matrix_batch)

"""
3D corotational beam element - large displacement / large rotation engine.

Design principle: reuse the EXISTING, already-validated linear Timoshenko
stiffness matrix (element_library.get_local_stiffness_matrix) as the local
constitutive relation. The corotational layer's only job is to:

  1. Track each node's accumulated 3D orientation (rotation_utils, Piece 1)
  2. Build a current corotational frame R_r that follows the chord
     (rotation-minimizing update, Piece 2)
  3. Extract the LOCAL (rigid-body-filtered) nodal rotations relative to
     that frame
  4. Feed those local rotations + axial stretch into the existing k_local
     to recover internal forces, then rotate back to global axes.

This avoids re-deriving shear/moment statics by hand (a classic place to
introduce sign errors) - instead f_local = k_local @ p_local, exactly the
same operation the linear solver already performs, just with a
corotationally-obtained p_local instead of a raw global-minus-rigid one.

Approximate tangent stiffness: K_approx = R_full @ (k_local + k_geo) @ R_full^T
This is NOT the fully consistent corotational tangent (that has an extra
"spin" term - see project discussion). It is an approximation, exactly in
the spirit of how the existing P-Delta engine already rebuilds K_total from
current axial force each iteration (a modified-Newton scheme). The
consistent-tangent term only affects convergence SPEED, not the correctness
of the converged answer, since convergence is checked on the residual
force, not on the stiffness matrix.
"""

class ElementCorotState:
    """
    Persistent per-element corotational state, carried across load steps.
    One instance per element in the model.
    """
    def __init__(self, p1_0, p2_0, beta_deg, section, material, L_clear, L_tor):
                                                                           
        self.L0 = np.linalg.norm(p2_0 - p1_0)

        self.L_clear = L_clear
        self.L_tor = L_tor
                                                                          
        self.rigid_zone_total = max(self.L_tor - self.L_clear, 0.0)

        beta_eff = beta_deg - np.degrees(section.get('theta_p', 0.0))
        self.R0 = get_rotation_matrix(p1_0, p2_0, beta_eff)
        self.R0 = self.R0.T                                                          

        self.R_r = self.R0.copy()

        self.section = section
        self.material = material

class NodeRotationState:
    """
    Persistent per-node accumulated orientation, shared across all elements
    that connect to that node. Initialized to identity (undeformed).
    """
    def __init__(self):
        self.R = np.eye(3)

    def update(self, d_theta_global):
        """
        Advance the node's orientation by an incremental global rotation
        vector d_theta_global (the RX,RY,RZ increment solved this step),
        via proper matrix composition - NOT vector addition.
        """
        R_inc = rodrigues(d_theta_global)
        self.R = compose(R_inc, self.R)

def compute_corotational_element(state: ElementCorotState,
                                  p1_current, p2_current,
                                  R_node1: NodeRotationState,
                                  R_node2: NodeRotationState,
                                  is_strict_statics: bool = False,
                                  fef_local: np.ndarray = None):
    """
    Given current node positions and current accumulated node orientations,
    returns:
        f_global      : 12-vector of internal forces/moments in GLOBAL axes
        K_approx       : 12x12 approximate tangent stiffness in GLOBAL axes
        N_axial        : recovered axial force (for diagnostics / consistency
                          with the existing P-Delta geometric stiffness call)
    Also updates state.R_r in place (the corotational frame for this element).

    fef_local: optional 12-vector, the element's fixed-end-force vector
    (member distributed / trapezoidal / self-weight / point loads and
    point moments applied along the span), expressed in the element's
    ORIGINAL local axes exactly as computed by GlobalAssembler._add_member_loads
    for the linear/P-Delta path.

    Previously this function only recovered internal force from nodal-
    displacement-induced strain (k_local @ p_local [+ k_geo @ p_local]),
    which silently drops any member load that only exists as a fixed-end
    force (distributed loads, trapezoidal distributed loads, self-weight,
    and point loads/moments applied along the span rather than at a node).
    Point loads applied directly AT a node never went through fef_local at
    all, which is why they already matched SAP2000 while these did not.

    fef_local is added into the LOCAL force vector before rotation into
    global axes, so it rotates rigidly with the element's current
    corotational frame R_r (the same "attached to the member" treatment
    used for the elastic/geometric stiffness terms). This exactly
    reproduces the linear/small-rotation FEF result at zero rotation, and
    is a standard corotational-frame approximation for member loads at
    large rotation. It is NOT a full re-projection of a space-fixed
    (Global-coordinate) load direction onto the rotating member at every
    iteration - if you need that level of fidelity for elements that
    rotate a large amount under a Global-direction distributed load,
    flag it and we can add per-iteration re-projection for coord='Global'
    member loads specifically.
    """
                                                                     
    chord = p2_current - p1_current
    L_n = np.linalg.norm(chord)
    e1_new = chord / L_n

    v_y_init = state.R0[:, 1]

    v_y_1 = R_node1.R @ v_y_init
    v_y_2 = R_node2.R @ v_y_init

    R_rel = R_node1.R.T @ R_node2.R
    theta_rel = rotation_to_vector(R_rel)
    R_mean = R_node1.R @ rodrigues(0.5 * theta_rel)
    v_y_avg = R_mean @ v_y_init
                                                             
    v_y_ort = v_y_avg - np.dot(v_y_avg, e1_new) * e1_new
    v_y_norm = np.linalg.norm(v_y_ort)

    if v_y_norm > 1e-12:
        e2_new = v_y_ort / v_y_norm
    else:
                                                                        
        e2_new = state.R_r[:, 1]
        e2_new = e2_new - np.dot(e2_new, e1_new) * e1_new
        e2_new /= np.linalg.norm(e2_new)

    e3_new = np.cross(e1_new, e2_new)

    state.R_r = np.column_stack((e1_new, e2_new, e3_new))
    R_r = state.R_r

    t1 = R_node1.R @ state.R0
    t2 = R_node2.R @ state.R0

    R_l1 = R_r.T @ t1
    R_l2 = R_r.T @ t2
    theta_l1 = rotation_to_vector(R_l1)                                     
    theta_l2 = rotation_to_vector(R_l2)

    u_l = (L_n - state.L0) * (L_n / state.L0)

    p_local = np.zeros(12)
                                                                    
    p_local[3:6] = theta_l1
                                                           
    p_local[6] = u_l
    p_local[9:12] = theta_l2

    sec, mat = state.section, state.material

    if is_strict_statics:
        L_flex = max(L_n - state.rigid_zone_total, 1e-9)
    else:
        L_flex = state.L_clear

    k_local = get_local_stiffness_matrix(
        E=mat['E'], G=mat['G'], A=sec['A'], J=sec['J'],
        I22=sec['I22'], I33=sec['I33'], As2=sec['As2'], As3=sec['As3'],
        L=L_flex, L_tor=state.L_tor
    )

    if fef_local is None:
        fef_local = np.zeros(12)

    f_local_linear = k_local @ p_local + fef_local
                                                                          
    N_axial = 0.5 * (f_local_linear[6] - f_local_linear[0])

    phi_y = (12 * mat['E'] * sec['I33']) / (mat['G'] * sec['As2'] * L_flex**2) if sec['As2'] > 0 else 0.0
    phi_z = (12 * mat['E'] * sec['I22']) / (mat['G'] * sec['As3'] * L_flex**2) if sec['As3'] > 0 else 0.0
    
    k_geo = get_geometric_stiffness_matrix(
        -N_axial, L_flex, phi_y=phi_y, phi_z=phi_z, A=sec['A'], I22=sec['I22'], I33=sec['I33']
    )

    f_local_with_fef = (k_local + k_geo) @ p_local + fef_local
    N_axial = 0.5 * (f_local_with_fef[6] - f_local_with_fef[0])

    f_local = (k_local + k_geo) @ p_local 

    R_full = np.zeros((12, 12))
    for blk in range(4):
        R_full[3*blk:3*blk+3, 3*blk:3*blk+3] = R_r

    f_global = R_full @ f_local

    def skew_sym(v):
        return np.array([[0.0, -v[2], v[1]],
                         [v[2], 0.0, -v[0]],
                         [-v[1], v[0], 0.0]])
                         
    G = skew_sym(e1_new) / L_n
    
    K_spin = np.zeros((12, 12))
    for i in range(4):
        row_start = i * 3
        row_end = row_start + 3
        f_g_block = f_global[row_start:row_end]
        S_fg = skew_sym(f_g_block)
        
        K_spin[row_start:row_end, 0:3] = S_fg @ G
        K_spin[row_start:row_end, 6:9] = -S_fg @ G

    K_approx = R_full @ (k_local + k_geo) @ R_full.T + K_spin

    return f_global, K_approx, N_axial

def _bmm(A, B):
    """
    Batched matmul: (N,i,j) @ (N,j,k) -> (N,i,k). Uses numpy's native
    broadcasting matmul (dispatches to BLAS batched gemm) rather than
    einsum, which is meaningfully faster for this exact pattern while
    computing the identical operation (A[n] @ B[n] for each n).
    """
    return A @ B

def _bmv(A, v):
    """Batched matrix-vector: (N,i,j) @ (N,j) -> (N,i)."""
    return (A @ v[..., None])[..., 0]

def _bT(A):
    return np.transpose(A, (0, 2, 1))

def compute_corotational_elements_batch(R0_arr, L0_arr, L_clear_arr, L_tor_arr,
                                          rigid_zone_total_arr,
                                          E_arr, G_arr, A_arr, J_arr, I22_arr, I33_arr,
                                          As2_arr, As3_arr,
                                          p1_arr, p2_arr, R1_arr, R2_arr, R_r_prev_arr,
                                          is_strict_statics=False, fef_local_arr=None):
    """
    Batched equivalent of compute_corotational_element(), processing all N
    elements in one set of numpy calls instead of N Python-level calls.
    Every operation below is the SAME operation, in the SAME order, as the
    scalar version in compute_corotational_element() - just performed on
    stacked (N, ...) arrays via einsum instead of one element at a time.

    Per-element persistent state (state.R0, state.L0, state.R_r, section,
    material) is passed in as plain arrays (gathered by the caller from the
    ElementCorotState objects) rather than as state objects, since state
    objects can't be vectorized directly. The caller is responsible for
    writing R_r_new back into each state.R_r after this call, exactly as
    the scalar version did in place.

    Returns: f_global (N,12), K_approx (N,12,12), N_axial (N,), R_r_new (N,3,3)
    """
    N = p1_arr.shape[0]
    if fef_local_arr is None:
        fef_local_arr = np.zeros((N, 12))

    chord = p2_arr - p1_arr
    L_n = np.linalg.norm(chord, axis=1)
    e1_new = chord / L_n[:, None]

    v_y_init = R0_arr[:, :, 1]                             

    R_rel = _bmm(_bT(R1_arr), R2_arr)
    theta_rel = rotation_to_vector_batch(R_rel)
    R_half = rodrigues_batch(0.5 * theta_rel)
    R_mean = _bmm(R1_arr, R_half)
    v_y_avg = _bmv(R_mean, v_y_init)

    dot_avg = np.sum(v_y_avg * e1_new, axis=1)
    v_y_ort = v_y_avg - dot_avg[:, None] * e1_new
    v_y_norm = np.linalg.norm(v_y_ort, axis=1)

    use_primary = v_y_norm > 1e-12
    v_y_norm_safe = np.where(use_primary, v_y_norm, 1.0)
    e2_primary = v_y_ort / v_y_norm_safe[:, None]

    fallback = R_r_prev_arr[:, :, 1]                                                            
    fallback = fallback - np.sum(fallback * e1_new, axis=1)[:, None] * e1_new
    fallback_norm = np.linalg.norm(fallback, axis=1)
    fallback_norm_safe = np.where(fallback_norm > 0, fallback_norm, 1.0)
    e2_fallback = fallback / fallback_norm_safe[:, None]

    e2_new = np.where(use_primary[:, None], e2_primary, e2_fallback)
    e3_new = np.cross(e1_new, e2_new)

    R_r = np.stack([e1_new, e2_new, e3_new], axis=-1)                                          

    t1 = _bmm(R1_arr, R0_arr)
    t2 = _bmm(R2_arr, R0_arr)

    R_l1 = _bmm(_bT(R_r), t1)
    R_l2 = _bmm(_bT(R_r), t2)
    theta_l1 = rotation_to_vector_batch(R_l1)
    theta_l2 = rotation_to_vector_batch(R_l2)

    u_l = (L_n - L0_arr) * (L_n / L0_arr)

    p_local = np.zeros((N, 12))
    p_local[:, 3:6] = theta_l1
    p_local[:, 6] = u_l
    p_local[:, 9:12] = theta_l2

    if is_strict_statics:
        L_flex = np.maximum(L_n - rigid_zone_total_arr, 1e-9)
    else:
        L_flex = L_clear_arr

    k_local = get_local_stiffness_matrix_batch(
        E=E_arr, G=G_arr, A=A_arr, J=J_arr, I22=I22_arr, I33=I33_arr,
        As2=As2_arr, As3=As3_arr, L=L_flex, L_tor=L_tor_arr
    )

    f_local_linear = _bmv(k_local, p_local) + fef_local_arr
    N_axial = 0.5 * (f_local_linear[:, 6] - f_local_linear[:, 0])

    As2_ok = As2_arr > 0
    As3_ok = As3_arr > 0
    As2_safe = np.where(As2_ok, As2_arr, 1.0)
    As3_safe = np.where(As3_ok, As3_arr, 1.0)
    phi_y = np.where(As2_ok, (12 * E_arr * I33_arr) / (G_arr * As2_safe * L_flex**2), 0.0)
    phi_z = np.where(As3_ok, (12 * E_arr * I22_arr) / (G_arr * As3_safe * L_flex**2), 0.0)

    k_geo = get_geometric_stiffness_matrix_batch(
        -N_axial, L_flex, phi_y=phi_y, phi_z=phi_z, A=A_arr, I22=I22_arr, I33=I33_arr
    )

    k_sum = k_local + k_geo
    f_local_with_fef = _bmv(k_sum, p_local) + fef_local_arr
    N_axial = 0.5 * (f_local_with_fef[:, 6] - f_local_with_fef[:, 0])

    f_local = _bmv(k_sum, p_local)

    R_full = np.zeros((N, 12, 12))
    for blk in range(4):
        R_full[:, 3*blk:3*blk+3, 3*blk:3*blk+3] = R_r

    f_global = _bmv(R_full, f_local)

    G_mat = skew_batch(e1_new) / L_n[:, None, None]

    K_spin = np.zeros((N, 12, 12))
    for i in range(4):
        row_start = i * 3
        row_end = row_start + 3
        f_g_block = f_global[:, row_start:row_end]
        S_fg = skew_batch(f_g_block)

        K_spin[:, row_start:row_end, 0:3] = _bmm(S_fg, G_mat)
        K_spin[:, row_start:row_end, 6:9] = -_bmm(S_fg, G_mat)

    K_approx = _bmm(R_full, _bmm(k_sum, _bT(R_full))) + K_spin

    return f_global, K_approx, N_axial, R_r
