import numpy as np
from rotation_utils import rodrigues, rotation_to_vector, compose, update_corotational_frame
from element_library import get_local_stiffness_matrix, get_geometric_stiffness_matrix, get_rotation_matrix

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
    def __init__(self, p1_0, p2_0, beta_deg, section, material):
        self.L0 = np.linalg.norm(p2_0 - p1_0)
                                                                              
        self.R0 = get_rotation_matrix(p1_0, p2_0, beta_deg)                     
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
                                  is_strict_statics: bool = False):
    """
    Given current node positions and current accumulated node orientations,
    returns:
        f_global      : 12-vector of internal forces/moments in GLOBAL axes
        K_approx       : 12x12 approximate tangent stiffness in GLOBAL axes
        N_axial        : recovered axial force (for diagnostics / consistency
                          with the existing P-Delta geometric stiffness call)
    Also updates state.R_r in place (the corotational frame for this element).
    """
                                                                     
    chord = p2_current - p1_current
    L_n = np.linalg.norm(chord)
    e1_new = chord / L_n
    state.R_r = update_corotational_frame(state.R_r, e1_new)
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
    
    L_eval = L_n if is_strict_statics else state.L0

    k_local = get_local_stiffness_matrix(
        E=mat['E'], G=mat['G'], A=sec['A'], J=sec['J'],
        I22=sec['I22'], I33=sec['I33'], As2=sec['As2'], As3=sec['As3'],
        L=L_eval
    )
    
    f_local_linear = k_local @ p_local
    N_axial = f_local_linear[6]   

    phi_y = (12 * mat['E'] * sec['I33']) / (mat['G'] * sec['As2'] * L_eval**2) if sec['As2'] > 0 else 0.0
    phi_z = (12 * mat['E'] * sec['I22']) / (mat['G'] * sec['As3'] * L_eval**2) if sec['As3'] > 0 else 0.0
    
    k_geo = get_geometric_stiffness_matrix(
        -N_axial, L_eval, phi_y=phi_y, phi_z=phi_z, A=sec['A'], I22=sec['I22'], I33=sec['I33']
    )

    f_local = (k_local + k_geo) @ p_local
    N_axial = f_local[6]                      
    
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
