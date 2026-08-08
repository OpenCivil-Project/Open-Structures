"""
SolidAssembler — OpenCivil
===========================
Assembles the global K and P for the Tet4 solid mesh,
then delegates solving to the existing LinearSolver from solver_kernel.py.

No duplicated solve logic — reuses the frame solver kernel directly.

Usage:
    asm = SolidAssembler(dm)
    K, P = asm.assemble_system()
    U, R = asm.solve()
    stress_results = asm.compute_element_stresses(U)
"""

import numpy as np
from scipy.sparse import lil_matrix, coo_matrix
import sys, os
import numpy as np
from scipy.sparse import lil_matrix, coo_matrix
from scipy.sparse.linalg import spsolve
from error_definitions import SolverException 

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from solid_element_library import get_tet10_stiffness_matrix, get_tet10_stiffness_matrix_batch, _build_C_batch
                                                                                       
class SolidAssembler:
    def __init__(self, solid_data_manager):
        self.dm = solid_data_manager
        self.K  = None                                                                 
        self.P  = np.zeros(self.dm.total_dofs)
        self._solver = None                                                  

    def assemble_system(self):
        """Builds global K and P. Returns (K_csc, P)."""
        print("SolidAssembler: building stiffness matrix "
              f"({len(self.dm.elements)} elements, "
              f"{self.dm.total_dofs} DOFs)...")

        rows_parts, cols_parts, data_parts = [], [], []

        r, c, d = self._build_stiffness()
        rows_parts.append(r); cols_parts.append(c); data_parts.append(d)

        r, c, d = self._build_rigid_links()
        if r is not None:
            rows_parts.append(r); cols_parts.append(c); data_parts.append(d)

        all_rows = np.concatenate(rows_parts)
        all_cols = np.concatenate(cols_parts)
        all_data = np.concatenate(data_parts)

        n = self.dm.total_dofs
                                                                             
        self.K = coo_matrix((all_data, (all_rows, all_cols)), shape=(n, n)).tocsc()

        print("SolidAssembler: building load vector...")
        self.P += self.dm.build_load_vector()

        K_csc = self.K
        print(f"SolidAssembler: done. Non-zeros: {K_csc.nnz}")
        return K_csc, self.P

    def solve(self):
        """
        Applies BCs and solves.  Supports two submodeling modes:

        Displacement-based (legacy):
            self.dm.prescribed_displacements is set.
            Cut-node rigid-link masters are pinned at the global U values.
            Requires K_fs * U_s correction to the RHS.

        Force-based (new):
            self.dm.cut_node_forces is set.
            Cut-node rigid-link masters stay FREE; their cut forces are
            injected directly into P.  No K_fs correction needed for those DOFs.
            Real supports inside the selection still use disp=0 BCs.
        """
        print("SolidAssembler: Applying Boundary Conditions and Partitioning...")

        is_free = np.ones(self.dm.total_dofs, dtype=bool)
        U_full  = np.zeros(self.dm.total_dofs)

        is_force_based = hasattr(self.dm, 'cut_node_forces')
        cut_nodes      = getattr(self.dm, 'cut_nodes', set())                          
        if is_force_based:
            print("  Mode: Force-Based Submodeling")

        for node in self.dm.nodes:
            start_idx  = node['idx'] * 3
            restraints = node['restraints']
            for i in range(3):
                if restraints[i]:
                    is_free[start_idx + i] = False

        def _find_raw_node(master_coords):
            for raw_n in self.dm.raw['nodes']:
                if (abs(raw_n['x'] - master_coords[0]) < 1e-5 and
                        abs(raw_n['y'] - master_coords[1]) < 1e-5 and
                        abs(raw_n['z'] - master_coords[2]) < 1e-5):
                    return raw_n
            return None

        old_id_to_idx = {}
        if hasattr(self.dm, 'prescribed_displacements'):
            user_ids = sorted(n['id'] for n in self.dm.raw['nodes'])
            old_id_to_idx = {uid: i for i, uid in enumerate(user_ids)}

        def _get_prescribed(raw_n):
            if not hasattr(self.dm, 'prescribed_displacements') or raw_n is None:
                return [0.0] * 6
            old_idx = old_id_to_idx.get(raw_n['id'])
            if old_idx is not None and old_idx in self.dm.prescribed_displacements:
                return self.dm.prescribed_displacements[old_idx]
            return [0.0] * 6

        if hasattr(self.dm, 'rigid_links'):
            for rl in self.dm.rigid_links:
                m_start    = rl['master_dof_start']
                restraints = rl['restraints']
                raw_n      = _find_raw_node(rl['master_coords'])
                node_id    = raw_n['id'] if raw_n else None

                if is_force_based and node_id in cut_nodes:
                    continue

                prescribed_disp = _get_prescribed(raw_n)
                for i in range(6):
                    if restraints[i]:
                        is_free[m_start + i] = False
                        U_full[m_start + i]  = prescribed_disp[i]

        if is_force_based and hasattr(self.dm, 'rigid_links'):
            cut_forces = self.dm.cut_node_forces or {}
            for rl in self.dm.rigid_links:
                raw_n = _find_raw_node(rl['master_coords'])
                if raw_n and raw_n['id'] in cut_forces:
                    F   = cut_forces[raw_n['id']]
                    m   = rl['master_dof_start']
                    self.P[m : m + 6] += F
                    print(f"  [Force BC] Node {raw_n['id']} master DOF {m}: "
                          f"F=[{F[0]:.2f}, {F[1]:.2f}, {F[2]:.2f}] "
                          f"M=[{F[3]:.2f}, {F[4]:.2f}, {F[5]:.2f}]")

        K_csc   = self.K.tocsc()
        is_supp = ~is_free

        K_ff = K_csc[is_free,  :][:, is_free ]
        K_fs = K_csc[is_free,  :][:, is_supp ]
        P_f  = self.P[is_free]
        U_s  = U_full[is_supp]
        P_eff = P_f - K_fs.dot(U_s)                                                            

        if K_ff.shape[0] == 0:
            print("Warning: Structure is fully constrained (0 free DOFs).")
            return U_full, self.P

        print(f"SolidAssembler: Solving system with {K_ff.shape[0]} equations...")
        try:
            U_f = spsolve(K_ff, P_eff)
        except (RuntimeError, ValueError) as e:
            raise Exception(f"Math Error during spsolve: {str(e)}")

        U_full[is_free] = U_f

        print("SolidAssembler: Computing Reactions...")
        Reactions = self.K.dot(U_full) - self.P

        return U_full, Reactions
    
    def _build_stiffness(self):
        """
        Same math as before (get_tet10_stiffness_matrix per element, summed
        into K at [dofs[r], dofs[c]]) but vectorized:
          1. all element stiffness matrices computed in one batched call
             instead of a Python loop calling get_tet10_stiffness_matrix
             element-by-element.
          2. instead of 900 individual K[i,j] += val writes into a lil_matrix
             per element (the actual bottleneck), we build flat (row, col,
             data) triplet arrays for every element at once and let
             coo_matrix sum duplicates in C code.
        Returns (rows, cols, data) — 1D arrays ready to feed into coo_matrix.
        """
        n_elem = len(self.dm.elements)
        if n_elem == 0:
            return (np.array([], dtype=np.int64),
                    np.array([], dtype=np.int64),
                    np.array([], dtype=float))

        node_indices = np.array([el['node_indices'] for el in self.dm.elements],
                                 dtype=np.int64)                              
        coords_arr = np.stack([el['coords'] for el in self.dm.elements])             
        E_arr  = np.array([el['material']['E']  for el in self.dm.elements])
        nu_arr = np.array([el['material']['nu'] for el in self.dm.elements])

        K_all, _ = get_tet10_stiffness_matrix_batch(E_arr, nu_arr, coords_arr)             

        dofs = (node_indices[:, :, None] * 3 + np.arange(3)[None, None, :]).reshape(n_elem, 30)

        rows = np.repeat(dofs, 30, axis=1).reshape(-1)                                
        cols = np.tile(dofs, (1, 30)).reshape(-1)                                     
        data = K_all.reshape(-1)                                                                      

        return rows, cols, data

    def compute_element_stresses(self, U_full):
        """
        Same math as before (C @ B @ u_e per Gauss point per element, then
        the standard von Mises combination) but computed for every element
        and every Gauss point in one batched pass instead of a Python loop
        that rebuilds B and re-does the matrix products element-by-element.
        """
        n_elem = len(self.dm.elements)
        if n_elem == 0:
            return []

        a = (5.0 + 3.0*np.sqrt(5.0)) / 20.0
        b = (5.0 - np.sqrt(5.0)) / 20.0
        gauss_L = [(a, b, b), (b, a, b), (b, b, a), (b, b, b)]

        node_indices = np.array([el['node_indices'] for el in self.dm.elements], dtype=np.int64)          
        coords_arr   = np.stack([el['coords'] for el in self.dm.elements])                                  
        E_arr  = np.array([el['material']['E']  for el in self.dm.elements])
        nu_arr = np.array([el['material']['nu'] for el in self.dm.elements])

        C_arr = _build_C_batch(E_arr, nu_arr)            

        dofs = (node_indices[:, :, None] * 3 + np.arange(3)[None, None, :]).reshape(n_elem, 30)
        u_e = U_full[dofs]                               

        stress_per_gauss = []                                                                      
        vm_per_gauss = []                            

        for (L1, L2, L3) in gauss_L:
            B = _build_B_tet10_node_batch(coords_arr, L1, L2, L3)             
            strain = np.einsum('nij,nj->ni', B, u_e)                       
            stress = np.einsum('nab,nb->na', C_arr, strain)                

            sxx, syy, szz, sxy, syz, sxz = (stress[:, 0], stress[:, 1], stress[:, 2],
                                             stress[:, 3], stress[:, 4], stress[:, 5])
            vm = np.sqrt(0.5 * ((sxx-syy)**2 + (syy-szz)**2 + (szz-sxx)**2
                                 + 6*(sxy**2 + syz**2 + sxz**2)))

            stress_per_gauss.append(stress)
            vm_per_gauss.append(vm)

        stress_all = np.stack(stress_per_gauss, axis=1).tolist()                            
        vm_all     = np.stack(vm_per_gauss, axis=1).tolist()              

        results = []
        for i, el in enumerate(self.dm.elements):
            results.append({
                'id':        el['id'],
                'stress':    stress_all[i],
                'von_mises': vm_all[i],
            })
        return results
    
    def _build_rigid_links(self):
        """
        Same penalty-MPC math as before, vectorized: for every (rigid link,
        slave node) pair we compute the same 9x9 K_pen = k_p * C^T C and,
        instead of 81 individual K[i,j] += val writes per pair, emit flat
        triplet arrays and let coo_matrix sum duplicates.
        Returns (rows, cols, data) or (None, None, None) if there are no links.
        """
        if not hasattr(self.dm, 'rigid_links') or not self.dm.rigid_links:
            return None, None, None
        print(f"SolidAssembler: building {len(self.dm.rigid_links)} rigid links (MPCs)...")

        k_p = 1e14

        rows_parts, cols_parts, data_parts = [], [], []

        for rl in self.dm.rigid_links:
            m_coords = rl['master_coords']
            m_dof = rl['master_dof_start']
            slave_indices = np.array(rl['slave_indices'], dtype=np.int64)
            n_slaves = slave_indices.shape[0]
            if n_slaves == 0:
                continue

            s_coords = np.array([self.dm.nodes[s]['coords'] for s in slave_indices])         
            s_dofs   = slave_indices * 3                                                    

            delta = s_coords - np.asarray(m_coords)                              
            dx, dy, dz = delta[:, 0], delta[:, 1], delta[:, 2]

            n = n_slaves
            C = np.zeros((n, 3, 9))
            C[:, 0, 0] = 1; C[:, 0, 3] = -1; C[:, 0, 7] = dz;  C[:, 0, 8] = -dy
            C[:, 1, 1] = 1; C[:, 1, 4] = -1; C[:, 1, 6] = -dz; C[:, 1, 8] = dx
            C[:, 2, 2] = 1; C[:, 2, 5] = -1; C[:, 2, 6] = dy;  C[:, 2, 7] = -dx

            K_pen = k_p * np.einsum('nai,naj->nij', C, C)

            m_dofs = np.array([m_dof, m_dof+1, m_dof+2, m_dof+3, m_dof+4, m_dof+5])
            dofs = np.concatenate([
                s_dofs[:, None], (s_dofs+1)[:, None], (s_dofs+2)[:, None],
                np.broadcast_to(m_dofs, (n, 6))
            ], axis=1)                                                        

            rows = np.repeat(dofs, 9, axis=1).reshape(-1)
            cols = np.tile(dofs, (1, 9)).reshape(-1)
            data = K_pen.reshape(-1)

            rows_parts.append(rows); cols_parts.append(cols); data_parts.append(data)

        if not rows_parts:
            return None, None, None

        return (np.concatenate(rows_parts),
                np.concatenate(cols_parts),
                np.concatenate(data_parts))

def _build_B_tet10_node_batch(coords_arr, L1, L2, L3):
    """
    Vectorized version of _build_B_tet10_node — same formulas, computed for
    all elements at once. coords_arr: (n,10,3) -> returns B: (n,6,30).
    """
    n_elem = coords_arr.shape[0]
    L4 = 1.0 - L1 - L2 - L3
    dN_dL = np.zeros((3, 10))

    dN_dL[0, 0] = 4*L1 - 1; dN_dL[1, 0] = 0;        dN_dL[2, 0] = 0
    dN_dL[0, 1] = 0;        dN_dL[1, 1] = 4*L2 - 1; dN_dL[2, 1] = 0
    dN_dL[0, 2] = 0;        dN_dL[1, 2] = 0;        dN_dL[2, 2] = 4*L3 - 1
    dN_dL[0, 3] = -(4*L4 - 1); dN_dL[1, 3] = -(4*L4 - 1); dN_dL[2, 3] = -(4*L4 - 1)

    dN_dL[0, 4] = 4*L2;  dN_dL[1, 4] = 4*L1;  dN_dL[2, 4] = 0
    dN_dL[0, 5] = 0;     dN_dL[1, 5] = 4*L3;  dN_dL[2, 5] = 4*L2
    dN_dL[0, 6] = 4*L3;  dN_dL[1, 6] = 0;     dN_dL[2, 6] = 4*L1

    dN_dL[0, 7] = 4*(L4 - L1); dN_dL[1, 7] = -4*L1;       dN_dL[2, 7] = -4*L1
    dN_dL[0, 8] = -4*L2;       dN_dL[1, 8] = 4*(L4 - L2); dN_dL[2, 8] = -4*L2
    dN_dL[0, 9] = -4*L3;       dN_dL[1, 9] = -4*L3;       dN_dL[2, 9] = 4*(L4 - L3)

    J = np.einsum('ik,nkj->nij', dN_dL, coords_arr)              
    J_inv = np.linalg.inv(J)
    dN_dx = np.einsum('nij,jk->nik', J_inv, dN_dL)                 

    B = np.zeros((n_elem, 6, 30))
    B[:, 0, 0::3] = dN_dx[:, 0, :]
    B[:, 1, 1::3] = dN_dx[:, 1, :]
    B[:, 2, 2::3] = dN_dx[:, 2, :]
    B[:, 3, 0::3] = dN_dx[:, 1, :]; B[:, 3, 1::3] = dN_dx[:, 0, :]
    B[:, 4, 1::3] = dN_dx[:, 2, :]; B[:, 4, 2::3] = dN_dx[:, 1, :]
    B[:, 5, 0::3] = dN_dx[:, 2, :]; B[:, 5, 2::3] = dN_dx[:, 0, :]

    return B

def _build_B_tet10_node(coords, L1, L2, L3):
    """6x30 strain-displacement matrix evaluated at specific natural coords."""
    L4 = 1.0 - L1 - L2 - L3
    dN_dL = np.zeros((3, 10))
    
    dN_dL[0, 0] = 4*L1 - 1; dN_dL[1, 0] = 0;        dN_dL[2, 0] = 0
    dN_dL[0, 1] = 0;        dN_dL[1, 1] = 4*L2 - 1; dN_dL[2, 1] = 0
    dN_dL[0, 2] = 0;        dN_dL[1, 2] = 0;        dN_dL[2, 2] = 4*L3 - 1
    dN_dL[0, 3] = -(4*L4 - 1); dN_dL[1, 3] = -(4*L4 - 1); dN_dL[2, 3] = -(4*L4 - 1)
    
    dN_dL[0, 4] = 4*L2;  dN_dL[1, 4] = 4*L1;  dN_dL[2, 4] = 0
    dN_dL[0, 5] = 0;     dN_dL[1, 5] = 4*L3;  dN_dL[2, 5] = 4*L2
    dN_dL[0, 6] = 4*L3;  dN_dL[1, 6] = 0;     dN_dL[2, 6] = 4*L1
    
    dN_dL[0, 7] = 4*(L4 - L1); dN_dL[1, 7] = -4*L1;       dN_dL[2, 7] = -4*L1
    dN_dL[0, 8] = -4*L2;       dN_dL[1, 8] = 4*(L4 - L2); dN_dL[2, 8] = -4*L2
    dN_dL[0, 9] = -4*L3;       dN_dL[1, 9] = -4*L3;       dN_dL[2, 9] = 4*(L4 - L3)

    J = dN_dL @ coords
    J_inv = np.linalg.inv(J)
    dN_dx = J_inv @ dN_dL
    
    B = np.zeros((6, 30))
    for i in range(10):
        col = i * 3
        B[0, col  ] = dN_dx[0, i]
        B[1, col+1] = dN_dx[1, i]
        B[2, col+2] = dN_dx[2, i]
        
        B[3, col  ] = dN_dx[1, i]; B[3, col+1] = dN_dx[0, i]
        B[4, col+1] = dN_dx[2, i]; B[4, col+2] = dN_dx[1, i]
        B[5, col  ] = dN_dx[2, i]; B[5, col+2] = dN_dx[0, i]
        
    return B

def _build_C(E, nu):
    """6×6 isotropic constitutive matrix."""
    lam = E * nu / ((1 + nu) * (1 - 2*nu))
    mu  = E / (2 * (1 + nu))
    return np.array([
        [lam+2*mu, lam,      lam,      0,  0,  0],
        [lam,      lam+2*mu, lam,      0,  0,  0],
        [lam,      lam,      lam+2*mu, 0,  0,  0],
        [0,        0,        0,        mu, 0,  0],
        [0,        0,        0,        0,  mu, 0],
        [0,        0,        0,        0,  0,  mu],
    ])

if __name__ == "__main__":
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from solid_data_manager import SolidDataManager
    from solid_mesher import SolidMesher, patch_data_manager

    path = sys.argv[1] if len(sys.argv) > 1 else "test.mf"

    print("=== Step 1: Data Manager ===")
    dm = SolidDataManager(path)
    dm.process_all(case_name="DEAD")
    patch_data_manager(dm)

    print("\n=== Step 2: Mesher ===")
    mesher = SolidMesher(dm, nx=4, ny=2, nz=2)
    mesher.mesh_all()

    print("\n=== Step 3: Assembler ===")
    asm = SolidAssembler(dm)
    K, P = asm.assemble_system()

    print("\n=== Step 4: Solve ===")
    U, R = asm.solve()

    max_u = np.max(np.abs(U))
    print(f"\nMax displacement: {max_u:.4e} m")

    print("\n=== Step 5: Stresses (first 3 elements) ===")
    stress_results = asm.compute_element_stresses(U)
    for s in stress_results[:3]:
        print(f"  elem {s['id']:4d}  vm={s['von_mises']:.4e} Pa  "
              f"sxx={s['stress'][0]:.4e}")

    print("\n✅ Full solid pipeline working.")
