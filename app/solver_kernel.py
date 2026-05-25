                                                              
import numpy as np
from scipy.sparse.linalg import spsolve
from scipy.sparse import csc_matrix
from error_definitions import SolverException

class LinearSolver:
    def __init__(self, K_global, P_global, data_manager):
        self.K = K_global
        self.P = P_global
        self.dm = data_manager
        
        self.U_full = np.zeros(self.dm.total_dofs)
        self.Reactions = np.zeros(self.dm.total_dofs)

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

        K_csc = self.K.tocsc()
        K_ff = K_csc[is_free, :][:, is_free]
        P_f = self.P[is_free]

        if K_ff.shape[0] == 0:
            print("Warning: Structure is fully constrained (0 free DOFs).")
            return np.zeros(self.dm.total_dofs), self.P

        print(f"Solver: Solving system with {K_ff.shape[0]} equations...")
        self.num_free_dofs = K_ff.shape[0]
        self.K_ff_nnz      = K_ff.nnz
        try:
            U_f = spsolve(K_ff, P_f)
        except (RuntimeError, ValueError) as e:
                                               
            raise SolverException("E301", f"Math Error during spsolve: {str(e)}")

        self.U_full[is_free] = U_f

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
