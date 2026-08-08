import numpy as np

def get_tet4_stiffness_matrix(E, nu, coords):
    """
    Linear Tetrahedron (Tet4) - Constant Strain Element.
    12x12 stiffness matrix. 4 nodes x 3 DOF (u, v, w).
    """
    coords = np.array(coords, dtype=float)
    x1,y1,z1 = coords[0]
    x2,y2,z2 = coords[1]
    x3,y3,z3 = coords[2]
    x4,y4,z4 = coords[3]

    edge = coords[1:] - coords[0]
    V = np.linalg.det(edge) / 6.0
    if abs(V) < 1e-14:
        raise ValueError("Tet4: zero or near-zero volume. Check node coordinates.")
    if V < 0: V = abs(V)

    J = np.array([[1, x1, y1, z1], [1, x2, y2, z2], [1, x3, y3, z3], [1, x4, y4, z4]])
    J_inv = np.linalg.inv(J)
    dN_dx, dN_dy, dN_dz = J_inv[1, :], J_inv[2, :], J_inv[3, :]

    B = np.zeros((6, 12))
    for i in range(4):
        col = i * 3
        B[0, col  ] = dN_dx[i]
        B[1, col+1] = dN_dy[i]
        B[2, col+2] = dN_dz[i]
        B[3, col  ] = dN_dy[i];  B[3, col+1] = dN_dx[i]
        B[4, col+1] = dN_dz[i];  B[4, col+2] = dN_dy[i]
        B[5, col  ] = dN_dz[i];  B[5, col+2] = dN_dx[i]

    lam = E * nu / ((1 + nu) * (1 - 2*nu))
    mu  = E / (2 * (1 + nu))
    C = np.array([
        [lam+2*mu, lam,      lam,      0,  0,  0 ],
        [lam,      lam+2*mu, lam,      0,  0,  0 ],
        [lam,      lam,      lam+2*mu, 0,  0,  0 ],
        [0,        0,        0,        mu, 0,  0 ],
        [0,        0,        0,        0,  mu, 0 ],
        [0,        0,        0,        0,  0,  mu],
    ])

    return B.T @ C @ B * V, V

def get_tet10_stiffness_matrix(E, nu, coords):
    """
    Quadratic Tetrahedron (Tet10) - Linear Strain Element.
    30x30 stiffness matrix. 10 nodes x 3 DOF (u, v, w).
    Overcomes shear locking in bending!
    
    Node Order (Gmsh standard):
    0,1,2,3 (corners)
    4(0-1), 5(1-2), 6(2-0), 7(0-3), 8(1-3), 9(2-3) (mid-edges)
    """
    coords = np.array(coords, dtype=float)
    
    lam = E * nu / ((1 + nu) * (1 - 2*nu))
    mu  = E / (2 * (1 + nu))
    C = np.array([
        [lam+2*mu, lam,      lam,      0,  0,  0 ],
        [lam,      lam+2*mu, lam,      0,  0,  0 ],
        [lam,      lam,      lam+2*mu, 0,  0,  0 ],
        [0,        0,        0,        mu, 0,  0 ],
        [0,        0,        0,        0,  mu, 0 ],
        [0,        0,        0,        0,  0,  mu],
    ])

    a = (5.0 + 3.0*np.sqrt(5.0)) / 20.0
    b = (5.0 - np.sqrt(5.0)) / 20.0
    
    gauss_pts = [
        (a, b, b),
        (b, a, b),
        (b, b, a),
        (b, b, b)                                                  
    ]
                                                            
    weight = 1.0 / 24.0  
    
    K = np.zeros((30, 30))
    
    for pt in gauss_pts:
        L1, L2, L3 = pt
        L4 = 1.0 - L1 - L2 - L3
        
        dN_dL = np.zeros((3, 10))
        
        dN_dL[0, 0] = 4*L1 - 1; dN_dL[1, 0] = 0;        dN_dL[2, 0] = 0
        dN_dL[0, 1] = 0;        dN_dL[1, 1] = 4*L2 - 1; dN_dL[2, 1] = 0
        dN_dL[0, 2] = 0;        dN_dL[1, 2] = 0;        dN_dL[2, 2] = 4*L3 - 1
        
        dN_dL[0, 3] = -(4*L4 - 1)
        dN_dL[1, 3] = -(4*L4 - 1)
        dN_dL[2, 3] = -(4*L4 - 1)
        
        dN_dL[0, 4] = 4*L2;  dN_dL[1, 4] = 4*L1;  dN_dL[2, 4] = 0
                               
        dN_dL[0, 5] = 0;     dN_dL[1, 5] = 4*L3;  dN_dL[2, 5] = 4*L2
                               
        dN_dL[0, 6] = 4*L3;  dN_dL[1, 6] = 0;     dN_dL[2, 6] = 4*L1
        
        dN_dL[0, 7] = 4*(L4 - L1); dN_dL[1, 7] = -4*L1;       dN_dL[2, 7] = -4*L1
        
        dN_dL[0, 8] = -4*L2;       dN_dL[1, 8] = 4*(L4 - L2); dN_dL[2, 8] = -4*L2
        
        dN_dL[0, 9] = -4*L3;       dN_dL[1, 9] = -4*L3;       dN_dL[2, 9] = 4*(L4 - L3)
        
        J = dN_dL @ coords
        detJ = np.linalg.det(J)
        
        if detJ < 0:
            detJ = abs(detJ)
            
        J_inv = np.linalg.inv(J)
        
        dN_dx = J_inv @ dN_dL
        
        B = np.zeros((6, 30))
        for i in range(10):
            col = i * 3
            B[0, col  ] = dN_dx[0, i]
            B[1, col+1] = dN_dx[1, i]
            B[2, col+2] = dN_dx[2, i]
            
            B[3, col  ] = dN_dx[1, i]
            B[3, col+1] = dN_dx[0, i]
            
            B[4, col+1] = dN_dx[2, i]
            B[4, col+2] = dN_dx[1, i]
            
            B[5, col  ] = dN_dx[2, i]
            B[5, col+2] = dN_dx[0, i]

        K += B.T @ C @ B * detJ * weight
        
    edge = coords[1:4] - coords[0]
    V = abs(np.linalg.det(edge)) / 6.0

    return K, V

def _tet10_dN_dL(L1, L2, L3):
    """
    3x10 shape-function-derivative matrix in natural coords, evaluated at
    one Gauss point. Identical formulas to the per-element loop version in
    get_tet10_stiffness_matrix — kept separate (not shared) so the existing
    single-element function is never touched.
    """
    L4 = 1.0 - L1 - L2 - L3
    dN_dL = np.zeros((3, 10))

    dN_dL[0, 0] = 4*L1 - 1; dN_dL[1, 0] = 0;        dN_dL[2, 0] = 0
    dN_dL[0, 1] = 0;        dN_dL[1, 1] = 4*L2 - 1; dN_dL[2, 1] = 0
    dN_dL[0, 2] = 0;        dN_dL[1, 2] = 0;        dN_dL[2, 2] = 4*L3 - 1

    dN_dL[0, 3] = -(4*L4 - 1)
    dN_dL[1, 3] = -(4*L4 - 1)
    dN_dL[2, 3] = -(4*L4 - 1)

    dN_dL[0, 4] = 4*L2;  dN_dL[1, 4] = 4*L1;  dN_dL[2, 4] = 0
    dN_dL[0, 5] = 0;     dN_dL[1, 5] = 4*L3;  dN_dL[2, 5] = 4*L2
    dN_dL[0, 6] = 4*L3;  dN_dL[1, 6] = 0;     dN_dL[2, 6] = 4*L1

    dN_dL[0, 7] = 4*(L4 - L1); dN_dL[1, 7] = -4*L1;       dN_dL[2, 7] = -4*L1
    dN_dL[0, 8] = -4*L2;       dN_dL[1, 8] = 4*(L4 - L2); dN_dL[2, 8] = -4*L2
    dN_dL[0, 9] = -4*L3;       dN_dL[1, 9] = -4*L3;       dN_dL[2, 9] = 4*(L4 - L3)

    return dN_dL

def _build_C_batch(E_arr, nu_arr):
    """Vectorized isotropic constitutive matrix, one 6x6 per element -> (n,6,6)."""
    E_arr  = np.asarray(E_arr, dtype=float)
    nu_arr = np.asarray(nu_arr, dtype=float)
    lam = E_arr * nu_arr / ((1 + nu_arr) * (1 - 2*nu_arr))
    mu  = E_arr / (2 * (1 + nu_arr))
    n = E_arr.shape[0]
    C = np.zeros((n, 6, 6))
    C[:, 0, 0] = lam + 2*mu; C[:, 0, 1] = lam;        C[:, 0, 2] = lam
    C[:, 1, 0] = lam;        C[:, 1, 1] = lam + 2*mu; C[:, 1, 2] = lam
    C[:, 2, 0] = lam;        C[:, 2, 1] = lam;        C[:, 2, 2] = lam + 2*mu
    C[:, 3, 3] = mu
    C[:, 4, 4] = mu
    C[:, 5, 5] = mu
    return C

def get_tet10_stiffness_matrix_batch(E_arr, nu_arr, coords_arr):
    """
    Vectorized version of get_tet10_stiffness_matrix — computes the 30x30
    stiffness matrix for ALL elements in one shot instead of looping in
    Python element-by-element. Produces bit-for-bit the same math as calling
    get_tet10_stiffness_matrix() once per element and stacking the results
    (same Gauss points, same weight, same B/C formulas) — just batched with
    numpy broadcasting instead of a Python loop.

    Args:
        E_arr, nu_arr : (n_elem,) arrays (or scalars, broadcast)
        coords_arr    : (n_elem, 10, 3) array of element node coordinates

    Returns:
        K_all : (n_elem, 30, 30)
        V_all : (n_elem,)  element volumes (same definition as the original)
    """
    coords_arr = np.asarray(coords_arr, dtype=float)
    n_elem = coords_arr.shape[0]

    if n_elem == 0:
        return np.zeros((0, 30, 30)), np.zeros((0,))

    E_arr  = np.broadcast_to(np.asarray(E_arr,  dtype=float), (n_elem,))
    nu_arr = np.broadcast_to(np.asarray(nu_arr, dtype=float), (n_elem,))

    C_arr = _build_C_batch(E_arr, nu_arr)                   

    a = (5.0 + 3.0*np.sqrt(5.0)) / 20.0
    b = (5.0 - np.sqrt(5.0)) / 20.0
    gauss_pts = [(a, b, b), (b, a, b), (b, b, a), (b, b, b)]
    weight = 1.0 / 24.0

    K = np.zeros((n_elem, 30, 30))

    for (L1, L2, L3) in gauss_pts:
        dN_dL = _tet10_dN_dL(L1, L2, L3)                                                        

        J = np.einsum('ik,nkj->nij', dN_dL, coords_arr)                 
        detJ = np.linalg.det(J)                                       
        detJ = np.abs(detJ)                                                                            

        J_inv = np.linalg.inv(J)                                         
        dN_dx = np.einsum('nij,jk->nik', J_inv, dN_dL)                    

        B = np.zeros((n_elem, 6, 30))
        B[:, 0, 0::3] = dN_dx[:, 0, :]
        B[:, 1, 1::3] = dN_dx[:, 1, :]
        B[:, 2, 2::3] = dN_dx[:, 2, :]
        B[:, 3, 0::3] = dN_dx[:, 1, :]
        B[:, 3, 1::3] = dN_dx[:, 0, :]
        B[:, 4, 1::3] = dN_dx[:, 2, :]
        B[:, 4, 2::3] = dN_dx[:, 1, :]
        B[:, 5, 0::3] = dN_dx[:, 2, :]
        B[:, 5, 2::3] = dN_dx[:, 0, :]

        K += np.einsum('nai,nab,nbj,n->nij', B, C_arr, B, detJ * weight)

    edge = coords_arr[:, 1:4, :] - coords_arr[:, 0:1, :]                 
    V_all = np.abs(np.linalg.det(edge)) / 6.0

    return K, V_all

if __name__ == "__main__":
    print("Tet10 math initialized and ready.")
