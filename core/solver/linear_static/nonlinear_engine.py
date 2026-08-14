import sys
import os
import time
import numpy as np
from scipy.sparse.linalg import spsolve

current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

from error_definitions import SolverException
from data_manager import DataManager
from assembler import GlobalAssembler
from core.units import unit_registry

def _write_error(out_path, error_code, extra=""):
    """Writes the error to JSON and returns True so the UI loads the error dialog."""
    ex = SolverException(error_code, extra)
    try:
        import json
        with open(out_path, 'w') as f:
            json.dump({"status": "FAILED", "error": ex.get_details()}, f, indent=4)
    except:
        pass
    return True

def run_nonlinear_analysis(input_json_path, output_json_path, target_case_name, progress_callback=None):
    """
    Step 1: The Engine Skeleton for Nonlinear Static (P-Delta) Analysis.
    """
    print("="*60)
    print(f"METUFIRE NONLINEAR ENGINE | V0.1 Beta")
    print(f"Target: {os.path.basename(input_json_path)} | Case: {target_case_name}")
    print("="*60)

    if progress_callback is None:
        def noop_callback(msg, val):
            pass
        progress_callback = noop_callback

    start_time = time.time()

    try:
                                                                   
        print("[1/5] Initializing Data Manager & Reading Parameters...")
        progress_callback("Loading model data...", 5)
        dm = DataManager(input_json_path)
        dm.process_all(case_name=target_case_name)

        case_data = next((c for c in dm.raw['load_cases'] if c['name'] == target_case_name), None)
        if not case_data:
            raise SolverException("E104", f"Load Case '{target_case_name}' not found.")

        geom_nonlin = case_data.get("geom_nonlin", "None")
        nl_params = case_data.get("nl_params", {})
        
        max_total_steps = nl_params.get("max_total_steps", 10)                              
        max_nr_iter = nl_params.get("max_nr_iter", 40)
        iter_conv_tol = nl_params.get("iter_conv_tol", 1e-4)

        progress_callback(f"NONLINEAR TYPE                       = {geom_nonlin:>10}", 8)
        progress_callback(f"TOTAL LOAD STEPS                     = {max_total_steps:>10}", 8)
        progress_callback(f"MAX ITERATIONS PER STEP              = {max_nr_iter:>10}", 8)
        progress_callback(f"CONVERGENCE TOLERANCE                = {iter_conv_tol:>10.2E}", 8)
        progress_callback("", 8)

        print("[2/5] Assembling Baseline Elastic System...")
        progress_callback("Assembling initial elastic stiffness matrix...", 15)
        
        import json
        matrix_path = output_json_path.replace("_results.json", "_matrices.json")
        assembler = GlobalAssembler(dm, export_path=matrix_path)
        
        K_E_full, P_total_full = assembler.assemble_system(exact_diaphragm=True)

        with open(matrix_path, 'r') as f:
            element_matrices = json.load(f)
                                                                   
        print("[3/5] Applying Boundary Conditions...")
        is_free_full = np.ones(dm.total_dofs, dtype=bool)
        for node in dm.nodes:
            start_idx = node['idx'] * 6
            restraints = node['restraints']                           
            for i in range(6):
                if restraints[i] or not dm.active_dofs[i]:           
                    is_free_full[start_idx + i] = False

        has_T = hasattr(assembler, 'T') and assembler.T is not None
        if has_T:
            T = assembler.T
            kept_dofs = assembler.kept_dofs
            K_E_sys = T.T @ K_E_full @ T
            P_total_sys = T.T @ P_total_full
            is_free_sys = is_free_full[kept_dofs]
        else:
            K_E_sys = K_E_full
            P_total_sys = P_total_full
            is_free_sys = is_free_full

        K_E_free = K_E_sys.tocsc()[is_free_sys, :][:, is_free_sys]
        P_total_free = P_total_sys[is_free_sys]

        num_free_dofs = K_E_free.shape[0]
        if num_free_dofs == 0:
            raise SolverException("E301", "Structure is fully constrained. No free DOFs.")

        print("[4/5] Entering Nonlinear Load Stepping Loop...")
        progress_callback("Starting Incremental Load Analysis...", 20)

        U_free = np.zeros(num_free_dofs)                                       
        
        dP_ext_free = P_total_free / max_total_steps

        for step in range(1, max_total_steps + 1):
            print(f"   -> Step {step}/{max_total_steps}")
            progress_callback(f"Solving Step {step} of {max_total_steps}...", 20 + int(70 * (step / max_total_steps)))
            
            P_target_free = dP_ext_free * step 

            K_total_free = K_E_free.copy()

            for iter_count in range(1, max_nr_iter + 1):
                
                F_int_free = K_total_free.dot(U_free) 
                
                R_free = P_target_free - F_int_free
                
                residual_norm = np.linalg.norm(R_free)
                                                                                               
                P_norm = np.linalg.norm(P_target_free)
                rel_error = residual_norm / P_norm if P_norm > 1e-9 else residual_norm

                if rel_error < iter_conv_tol:
                    print(f"      Converged at step {step}, iteration {iter_count} (Relative Error: {rel_error:.2E})")
                    break                                                  

                try:
                    dU_free = spsolve(K_total_free, R_free)
                except Exception as e:
                    raise SolverException("E301", f"Matrix singular at step {step}, iter {iter_count}: {e}")
                
                U_free += dU_free

                if geom_nonlin in ["P-Delta", "Large Displacements"]:
                    
                    U_sys = np.zeros(K_E_sys.shape[0])
                    U_sys[is_free_sys] = U_free
                    U_full = T @ U_sys if has_T else U_sys

                    kg_row, kg_col, kg_data = [], [], []
                    
                    for el in dm.elements:
                        eid_str = str(el['id'])
                        if eid_str not in element_matrices: continue
                        
                        k_local = np.array(element_matrices[eid_str]['k'])
                        t_total = np.array(element_matrices[eid_str]['t'])
                        fef_local = np.array(element_matrices[eid_str]['fef'])
                        
                        idx_i, idx_j = el['node_indices']
                        u_global = np.concatenate([
                            U_full[idx_i*6 : idx_i*6+6], 
                            U_full[idx_j*6 : idx_j*6+6]
                        ])
                        
                        f_local = k_local @ (t_total @ u_global) + fef_local
                        N_axial = (f_local[6] - f_local[0]) / 2.0
                        
                        sec = el['section']
                        L_geom = el['L_clear']
                        mat = el['material']
                        
                        phi_y = (12 * mat['E'] * sec['I33']) / (mat['G'] * sec['As2'] * L_geom**2) if sec['As2'] > 0 else 0.0
                        phi_z = (12 * mat['E'] * sec['I22']) / (mat['G'] * sec['As3'] * L_geom**2) if sec['As3'] > 0 else 0.0
                        
                        from element_library import get_geometric_stiffness_matrix, get_rotation_matrix, get_eccentricity_matrix
                        kg_local = get_geometric_stiffness_matrix(
                            -N_axial, L_geom, phi_y=phi_y, phi_z=phi_z, 
                            A=sec['A'], I22=sec['I22'], I33=sec['I33']
                        )
                        
                        rel_vec = el.get('releases', [[False]*6, [False]*6])[0] + el.get('releases', [[False]*6, [False]*6])[1]
                        if any(rel_vec):
                            idx_c = [i for i, r in enumerate(rel_vec) if r]
                            idx_k = [i for i, r in enumerate(rel_vec) if not r]
                            K_cc = k_local[np.ix_(idx_c, idx_c)]                                                  
                            K_cr = k_local[np.ix_(idx_c, idx_k)]
                            try:
                                T_cr = -np.linalg.inv(K_cc) @ K_cr
                                Tc = np.eye(12)
                                Tc[idx_c, :] = 0.0
                                for i_c, orig_c in enumerate(idx_c):
                                    for i_r, orig_r in enumerate(idx_k):
                                        Tc[orig_c, orig_r] = T_cr[i_c, i_r]
                                kg_local = Tc.T @ kg_local @ Tc
                            except np.linalg.LinAlgError:
                                pass

                        p1 = dm.nodes[idx_i]['coords']
                        p2 = dm.nodes[idx_j]['coords']
                        global_off_i = np.array(el['offsets'][0])
                        global_off_j = np.array(el['offsets'][1])
                        
                        R_3x3 = get_rotation_matrix(p1 + global_off_i, p2 + global_off_j, el.get('beta', 0.0))
                        T_rot = np.zeros((12, 12))
                        for i in range(4): T_rot[i*3:(i+1)*3, i*3:(i+1)*3] = R_3x3
                        
                        local_off_i = R_3x3 @ global_off_i
                        local_off_j = R_3x3 @ global_off_j
                        
                        rz_factor = el.get('rz_factor', 0.0)
                        ri = el.get('end_off_i', 0.0) * rz_factor
                        rj = el.get('end_off_j', 0.0) * rz_factor
                        local_off_i[0] += ri
                        local_off_j[0] -= rj
                        
                        T_ecc = get_eccentricity_matrix(local_off_i, local_off_j)
                        kg_local_node = T_ecc.T @ kg_local @ T_ecc
                        
                        P_c = N_axial                                                                                  
                        if ri > 0:
                            kg_local_node[4, 4] += P_c * ri               
                            kg_local_node[5, 5] += P_c * ri               
                        if rj > 0:
                            kg_local_node[10, 10] += P_c * rj             
                            kg_local_node[11, 11] += P_c * rj         
                            
                        kg_global = T_rot.T @ kg_local_node @ T_rot
                        
                        start_i = idx_i * 6
                        start_j = idx_j * 6
                        global_indices = [start_i + x for x in range(6)] + [start_j + x for x in range(6)]
                        for r_idx in range(12):
                            for c_idx in range(12):
                                val = kg_global[r_idx, c_idx]
                                if val != 0.0:
                                    kg_row.append(global_indices[r_idx])
                                    kg_col.append(global_indices[c_idx])
                                    kg_data.append(val)

                    from scipy.sparse import coo_matrix
                    KG_full = coo_matrix((kg_data, (kg_row, kg_col)), shape=(dm.total_dofs, dm.total_dofs)).tocsc()
                    
                    if has_T:
                        KG_sys = T.T @ KG_full @ T
                    else:
                        KG_sys = KG_full
                        
                    KG_free = KG_sys.tocsc()[is_free_sys, :][:, is_free_sys]
                    
                    K_total_free = K_E_free + KG_free

            else:
                                                                              
                print(f"      WARNING: Step {step} failed to converge after {max_nr_iter} iterations!")
                                                                                             
        print("[5/5] Nonlinear Analysis Complete.")
        
        print("      Extracting Final Displacements and Reactions...")
        progress_callback("Formatting results...", 90)

        U_sys = np.zeros(dm.total_dofs)
        U_sys[is_free_sys] = U_free
        U_full = T @ U_sys if has_T else U_sys

        if geom_nonlin in ["P-Delta", "Large Displacements"] and 'KG_full' in locals():
            K_final_full = K_E_full + KG_full
        else:
            K_final_full = K_E_full
            
        Reactions_full = K_final_full.dot(U_full) - P_total_full

        results_dict = {
            "displacements": {},
            "reactions": {},
            "base_reaction": {"Fx": 0.0, "Fy": 0.0, "Fz": 0.0, "Mx": 0.0, "My": 0.0, "Mz": 0.0}
        }
        
        sum_fx, sum_fy, sum_fz, sum_mx, sum_my, sum_mz = 0.0, 0.0, 0.0, 0.0, 0.0, 0.0

        for node in dm.nodes:
            n_id = str(node['id'])
            idx = node['idx'] * 6
            coords = node['coords']            
            
            disp = U_full[idx : idx+6]
            reac = Reactions_full[idx : idx+6]
            
            spring_force = np.zeros(6)
            if node.get('spring_matrix') is not None:
                spring_force = -(node['spring_matrix'] @ disp)
                
            output_reac = np.zeros(6)
            for i in range(6):
                if node['restraints'][i]:
                    output_reac[i] = reac[i]
                else:
                    output_reac[i] = spring_force[i]
            
            results_dict["displacements"][n_id] = disp.tolist()
            results_dict["reactions"][n_id] = output_reac.tolist()
            
            fx, fy, fz, mx, my, mz = output_reac
            sum_fx += fx; sum_fy += fy; sum_fz += fz
            x, y, z = coords
            sum_mx += mx + (y * fz - z * fy)
            sum_my += my + (z * fx - x * fz)
            sum_mz += mz + (x * fy - y * fx)

        results_dict["base_reaction"] = {
            "Fx": sum_fx, "Fy": sum_fy, "Fz": sum_fz,
            "Mx": sum_mx, "My": sum_my, "Mz": sum_mz
        }
        results_dict["restrained_nodes"] = [
            str(n['id']) for n in dm.nodes if any(n['restraints']) or n.get('spring_matrix') is not None
        ]

        from result_writer import ResultWriter
        writer = ResultWriter(output_json_path)
        meta_info = {
            "version": "0.1 Nonlinear",
            "type": "Nonlinear Static",
            "case_name": target_case_name,
            "geom_nonlin": geom_nonlin,
            "dofs": dm.total_dofs,
            "steps_completed": max_total_steps
        }
        writer.write_results(results_dict, meta_info)
        
        elapsed_total = time.time() - start_time
        progress_callback("A N A L Y S I S   C O M P L E T E", 100)
        print("="*60)
        print(f"Total Time: {elapsed_total:.4f}s")
        print("="*60)
        return True

    except Exception as e:
        print(f"FATAL ERROR: {e}")
        return _write_error(output_json_path, "E000", str(e))

if __name__ == "__main__":
                    
    test_in = os.path.join(current_dir, "test.mf")
    test_out = os.path.join(current_dir, "test_nonlinear_results.json")
    if os.path.exists(test_in):
        run_nonlinear_analysis(test_in, test_out, "DEAD")
