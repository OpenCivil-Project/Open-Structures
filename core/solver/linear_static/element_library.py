                                                                
import numpy as np

def get_local_stiffness_matrix(E, G, A, J, I22, I33, As2, As3, L, L_tor=None):
    """
    Calculates the complete 12x12 Timoshenko 3D Frame stiffness matrix.
    Includes Axial, Torsion, and bi-axial Bending with Shear Deformation.
    """
    """
    L      : Clear Length (for Bending/Shear/Axial)
    L_tor  : Torsional Length (usually Center-to-Center to match SAP2000)
    """

    if L == 0: return np.eye(12) * 1e12                         
    if L_tor is None:
        L_tor = L
                                      
    phi_y = (12 * E * I33) / (G * As2 * L**2) if As2 > 0 else 0.0
    phi_z = (12 * E * I22) / (G * As3 * L**2) if As3 > 0 else 0.0
    
    k = np.zeros((12, 12))
    
    EA_L = E * A / (L_tor if L_tor else L)
    k[0, 0] =  EA_L;  k[0, 6] = -EA_L
    k[6, 0] = -EA_L;  k[6, 6] =  EA_L
    
    GJ_L = G * J / L_tor
    k[3, 3] =  GJ_L;  k[3, 9] = -GJ_L
    k[9, 3] = -GJ_L;  k[9, 9] =  GJ_L
    
    EI33 = E * I33
    L2 = L * L
    L3 = L * L * L
    Py = 1 + phi_y
    
    k1_z = (12 * EI33) / (L3 * Py)                    
    k2_z = (6 * EI33) / (L2 * Py)                    
    k3_z = ((4 + phi_y) * EI33) / (L * Py)          
    k4_z = ((2 - phi_y) * EI33) / (L * Py)          
    
    k[1, 1] =  k1_z
    k[1, 5] =  k2_z
    k[1, 7] = -k1_z
    k[1, 11]=  k2_z
    
    k[5, 1] =  k2_z
    k[5, 5] =  k3_z
    k[5, 7] = -k2_z
    k[5, 11]=  k4_z                            
    
    k[7, 1] = -k1_z
    k[7, 5] = -k2_z
    k[7, 7] =  k1_z
    k[7, 11]= -k2_z
    
    k[11, 1] =  k2_z
    k[11, 5] =  k4_z
    k[11, 7] = -k2_z
    k[11, 11]=  k3_z

    EI22 = E * I22
    Pz = 1 + phi_z
    
    k1_y = (12 * EI22) / (L3 * Pz)
    k2_y = (6 * EI22) / (L2 * Pz)
    k3_y = ((4 + phi_z) * EI22) / (L * Pz)
    k4_y = ((2 - phi_z) * EI22) / (L * Pz)
    
    k[2, 2] =  k1_y
    k[2, 4] = -k2_y                      
    k[2, 8] = -k1_y
    k[2, 10]= -k2_y
    
    k[4, 2] = -k2_y
    k[4, 4] =  k3_y
    k[4, 8] =  k2_y
    k[4, 10]=  k4_y
    
    k[8, 2] = -k1_y
    k[8, 4] =  k2_y
    k[8, 8] =  k1_y
    k[8, 10]=  k2_y
    
    k[10, 2]= -k2_y
    k[10, 4]=  k4_y
    k[10, 8]=  k2_y
    k[10, 10]= k3_y
    
    return k

def get_rotation_matrix(p1, p2, beta_deg):
    V_x = p2 - p1
    L = np.linalg.norm(V_x)
    if L == 0: return np.eye(3)
    vx = V_x / L 

    if np.abs(vx[2]) > 0.999:
        temp_v = np.array([1.0, 0.0, 0.0])
    else:
        temp_v = np.array([0.0, 0.0, 1.0])

    vy = np.cross(temp_v, vx)
    vy /= np.linalg.norm(vy)
    vz = np.cross(vx, vy)

    beta_rad = np.radians(beta_deg)
    c, s = np.cos(beta_rad), np.sin(beta_rad)
    
    vy_final = vy * c + vz * s
    vz_final = -vy * s + vz * c
    
    R = np.array([vx, vy_final, vz_final])
    
    print(f"Rotation Matrix for element from {p1} to {p2}:")
    print(f"  vx (local X): {vx}")
    print(f"  vy (local Y): {vy_final}")
    print(f"  vz (local Z): {vz_final}")
    
    return R

def get_eccentricity_matrix(off_i, off_j):
    Te = np.eye(12)
    def apply_offset(node_idx, offset):
        ex, ey, ez = offset
        block = np.eye(6)
        block[0, 4] = ez;  block[0, 5] = -ey
        block[1, 3] = -ez; block[1, 5] = ex
        block[2, 3] = ey;  block[2, 4] = -ex
        return block

    Te[0:6, 0:6] = apply_offset(0, off_i)
    Te[6:12, 6:12] = apply_offset(1, off_j)
    return Te

def get_geometric_stiffness_matrix(P_axial, L, phi_y=0.0, phi_z=0.0, A=1.0, I22=0.0, I33=0.0):
    """
    Calculates the 12x12 Geometric Stiffness Matrix (K_g) for a 3D Frame Element.
    MATCHING SAP2000: Uses Euler-Bernoulli consistent formulation for K_g (phi = 0).
    """
    kg = np.zeros((12, 12))
    if L <= 1e-9: return kg

    P_c = -P_axial                          
    
    phi_y = 0.0
    phi_z = 0.0

    if A > 1e-12:
        r0_sq = (I22 + I33) / A
        t_term = (P_c * r0_sq) / L
        kg[3, 3] =  t_term
        kg[3, 9] = -t_term
        kg[9, 3] = -t_term
        kg[9, 9] =  t_term

    cy = P_c / (30 * L * (1 + phi_y)**2)
    ky_11 = 36 + 60*phi_y + 30*phi_y**2
    ky_12 = 3*L + 15*L*phi_y
    ky_22 = 4*L**2 + 5*L**2*phi_y + 2.5*L**2*phi_y**2
    ky_24 = -L**2 - 5*L**2*phi_y - 2.5*L**2*phi_y**2

    kg[1, 1] =  ky_11 * cy
    kg[1, 5] =  ky_12 * cy
    kg[1, 7] = -ky_11 * cy
    kg[1, 11] = ky_12 * cy

    kg[5, 1] =  ky_12 * cy
    kg[5, 5] =  ky_22 * cy
    kg[5, 7] = -ky_12 * cy
    kg[5, 11] = ky_24 * cy

    kg[7, 1] = -ky_11 * cy
    kg[7, 5] = -ky_12 * cy
    kg[7, 7] =  ky_11 * cy
    kg[7, 11] = -ky_12 * cy

    kg[11, 1] =  ky_12 * cy
    kg[11, 5] =  ky_24 * cy
    kg[11, 7] = -ky_12 * cy
    kg[11, 11] = ky_22 * cy

    cz = P_c / (30 * L * (1 + phi_z)**2)
    kz_11 = 36 + 60*phi_z + 30*phi_z**2
    kz_12 = 3*L + 15*L*phi_z
    kz_22 = 4*L**2 + 5*L**2*phi_z + 2.5*L**2*phi_z**2
    kz_24 = -L**2 - 5*L**2*phi_z - 2.5*L**2*phi_z**2

    kg[2, 2]  =  kz_11 * cz
    kg[2, 4]  = -kz_12 * cz
    kg[2, 8]  = -kz_11 * cz
    kg[2, 10] = -kz_12 * cz

    kg[4, 2]  = -kz_12 * cz
    kg[4, 4]  =  kz_22 * cz
    kg[4, 8]  =  kz_12 * cz
    kg[4, 10] =  kz_24 * cz

    kg[8, 2]  = -kz_11 * cz
    kg[8, 4]  =  kz_12 * cz
    kg[8, 8]  =  kz_11 * cz
    kg[8, 10] =  kz_12 * cz

    kg[10, 2]  = -kz_12 * cz
    kg[10, 4]  =  kz_24 * cz
    kg[10, 8]  =  kz_12 * cz
    kg[10, 10] =  kz_22 * cz

    return kg
