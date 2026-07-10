import numpy as np
from scipy.sparse.linalg import spsolve
from scipy.sparse import csc_matrix
from error_definitions import SolverException

class LinearSolver:
    def __init__(self, K_global, P_global, data_manager, T=None, kept_dofs=None):
        self.K = K_global
        self.P = P_global
        self.dm = data_manager
        self.T = T                                                            
        self.kept_dofs = kept_dofs                                           
        
        self.U_full = np.zeros(self.dm.total_dofs)
        self.Reactions = np.zeros(self.dm.total_dofs)

    def _build_imposed_displacements(self, is_free):
        """
        Extracts Ground Displacements from the active load case.
        Per standard FEA logic, we ONLY apply these to DOFs that are restrained.
        """
        U_imp = np.zeros(self.dm.total_dofs)
        active_patterns = {pat: scale for pat, scale in self.dm.load_case['patterns']}
        
        has_imposed = False
        for load in self.dm.raw.get('loads', []):
            pat = load.get('pattern') or load.get('pattern_name')
            if load.get('type') == 'ground_displacement' and pat in active_patterns:
                scale = active_patterns[pat]
                node_idx = self.dm.node_id_to_idx[load['node_id']]
                start = node_idx * 6
                
                vals = [
                    load.get('ux', 0.0), load.get('uy', 0.0), load.get('uz', 0.0),
                    load.get('rx', 0.0), load.get('ry', 0.0), load.get('rz', 0.0)
                ]
                
                dof_names = ['UX', 'UY', 'UZ', 'RX', 'RY', 'RZ']
                for i, val in enumerate(vals):
                    if abs(val) > 1e-12:
                                                       
                        if not is_free[start + i]:
                            U_imp[start + i] += val * scale
                            has_imposed = True
                        else:
                            print(f"      [!] Warning: Ground Displacement {val} on Node {load['node_id']} ({dof_names[i]}) ignored because it is a FREE Degree of Freedom.")
                            
        return U_imp, has_imposed

    def solve(self):
        """
        Executes the linear algebra solution: K_ff * U_f = P_f
        """
        print("Solver: Applying Boundary Conditions...")
        
        is_free = np.ones(self.dm.total_dofs, dtype=bool)
        
        for node in self.dm.nodes:
            start_idx = node['idx'] * 6
            restraints = node['restraints']                           
            
            for i in range(6):
                if restraints[i]:                  
                    is_free[start_idx + i] = False

        U_imp, has_imposed = self._build_imposed_displacements(is_free)

        if self.T is not None:
            return self._solve_with_diaphragm_elimination(is_free, U_imp, has_imposed)

        if has_imposed:
            print("Solver: Converting Ground Displacements to Equivalent Loads...")
            P_eff = self.P - self.K.dot(U_imp)
        else:
            P_eff = self.P

        K_csc = self.K.tocsc()
        K_ff = K_csc[is_free, :][:, is_free]
        P_f = P_eff[is_free]                                

        if K_ff.shape[0] == 0:
            print("Warning: Structure is fully constrained (0 free DOFs).")
            self.U_full[~is_free] = U_imp[~is_free]                                    
            self.Reactions = self.K.dot(self.U_full) - self.P
            return self.U_full, self.Reactions

        print(f"Solver: Solving system with {K_ff.shape[0]} equations...")
        self.num_free_dofs = K_ff.shape[0]
        self.K_ff_nnz      = K_ff.nnz
        try:
            U_f = spsolve(K_ff, P_f)
        except (RuntimeError, ValueError) as e:
            raise SolverException("E301", f"Math Error during spsolve: {str(e)}")

        self.U_full[is_free] = U_f
                                                                                  
        self.U_full[~is_free] = U_imp[~is_free] 

        print("Solver: Computing Reactions...")
                                                                                    
        self.Reactions = self.K.dot(self.U_full) - self.P

        return self.U_full, self.Reactions

    def _solve_with_diaphragm_elimination(self, is_free_full, U_imp, has_imposed):
        """
        Reduces K, P into the diaphragm-eliminated space via T, applies
        boundary conditions there, solves, then expands U back to full size.
        """
        total = self.dm.total_dofs
        eliminated_set = set(range(total)) - set(self.kept_dofs)

        bad = sorted(d for d in eliminated_set if not is_free_full[d])
        if bad:
            raise SolverException(
                "E205",
                f"Restraint found on diaphragm-slaved DOF index(es) {bad}. "
                f"Restrain the diaphragm MASTER node instead."
            )

        K_csr = self.K.tocsr()
        K_red = (self.T.T @ K_csr @ self.T).tocsc()
        
        P_red = self.T.T @ self.P

        U_imp_red = U_imp[self.kept_dofs]
        if has_imposed:
            print("Solver: Converting Ground Displacements for Rigid Diaphragms...")
            P_red_eff = P_red - K_red.dot(U_imp_red)
        else:
            P_red_eff = P_red

        is_free_red = is_free_full[self.kept_dofs]

        K_ff = K_red[is_free_red, :][:, is_free_red]
        P_f = P_red_eff[is_free_red]                                

        if K_ff.shape[0] == 0:
            print("Warning: Structure is fully constrained (0 free DOFs).")
            U_red = np.zeros(K_red.shape[0])
            U_red[~is_free_red] = U_imp_red[~is_free_red]
            self.U_full = self.T @ U_red
            self.Reactions = self.K.dot(self.U_full) - self.P
            return self.U_full, self.Reactions

        print(f"Solver: Solving REDUCED system with {K_ff.shape[0]} equations "
              f"({len(eliminated_set)} diaphragm slave DOFs eliminated exactly)...")
        self.num_free_dofs = K_ff.shape[0]
        self.K_ff_nnz = K_ff.nnz
        try:
            U_f = spsolve(K_ff, P_f)
        except (RuntimeError, ValueError) as e:
            raise SolverException("E301", f"Math Error during spsolve: {str(e)}")

        U_red = np.zeros(K_red.shape[0])
        U_red[is_free_red] = U_f
        
        U_red[~is_free_red] = U_imp_red[~is_free_red]

        self.U_full = self.T @ U_red

        print("Solver: Computing Reactions...")
        self.Reactions = self.K.dot(self.U_full) - self.P              

        return self.U_full, self.Reactions

    def get_results_dict(self):
        """Packages results into a dictionary for the Writer."""
        results = {
            "displacements": {},
            "reactions": {},
            "base_reaction": {                     
                "Fx": 0.0, "Fy": 0.0, "Fz": 0.0,
                "Mx": 0.0, "My": 0.0, "Mz": 0.0
            }
        }
        
        sum_fx, sum_fy, sum_fz = 0.0, 0.0, 0.0
        sum_mx, sum_my, sum_mz = 0.0, 0.0, 0.0
        
        for node in self.dm.nodes:
            n_id = node['id']
            idx = node['idx'] * 6
            coords = node['coords']            
            
            disp = self.U_full[idx : idx+6].tolist()
            reac = self.Reactions[idx : idx+6].tolist()
            
            results["displacements"][n_id] = disp
            results["reactions"][n_id] = reac
            
            if any(node['restraints']):
                fx, fy, fz, mx, my, mz = reac
                
                sum_fx += fx
                sum_fy += fy
                sum_fz += fz
                
                x, y, z = coords
                
                sum_mx += mx + (y * fz - z * fy)
                sum_my += my + (z * fx - x * fz)
                sum_mz += mz + (x * fy - y * fx)

        results["base_reaction"] = {
            "Fx": sum_fx, "Fy": sum_fy, "Fz": sum_fz,
            "Mx": sum_mx, "My": sum_my, "Mz": sum_mz
        }

        results["restrained_nodes"] = [
            str(n['id']) for n in self.dm.nodes if any(n['restraints'])
        ]

        return results
