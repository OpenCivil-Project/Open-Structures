import sys
import os
import time
import numpy as np
import json
from scipy.sparse import lil_matrix
from scipy.sparse.linalg import eigsh

current_dir = os.path.dirname(os.path.abspath(__file__))
solver_dir = os.path.dirname(current_dir)
linear_static_dir = os.path.join(solver_dir, 'linear_static')

if current_dir not in sys.path:
    sys.path.append(current_dir)
if solver_dir not in sys.path:
    sys.path.append(solver_dir)
if linear_static_dir not in sys.path:
    sys.path.append(linear_static_dir)

from linear_static.data_manager import DataManager
from linear_static.assembler import GlobalAssembler
from linear_static.element_forces import ForceExtractor
from linear_static.error_definitions import SolverException
from linear_static.element_library import get_geometric_stiffness_matrix, get_rotation_matrix, get_eccentricity_matrix

def _write_error(out_path, error_code, extra=""):
    ex = SolverException(error_code, extra)
    try:
        with open(out_path, 'w') as f:
            json.dump({"status": "FAILED", "error": ex.get_details()}, f, indent=4)
    except:
        pass
    return True

def run_buckling_analysis(input_json_path, output_json_path, results_path, matrices_path, case_name="BUCKLING", progress_callback=None):
    print("="*60)
    print(f"OPENCIVIL BUCKLING ENGINE | V0.75 Stable Beta")
    print(f"Target: {os.path.basename(input_json_path)}")
    print("="*60)

    if progress_callback is None:
        from progress import noop_callback
        progress_callback = noop_callback

    start_time = time.time()
    
    try:
        print("[1/6] Initializing Data Manager...")
        progress_callback("Loading model data...", 5)
        dm = DataManager(input_json_path)
        dm.process_all(case_name=case_name)

        num_restrained = sum(1 for n in dm.nodes if any(n['restraints']))
        buckling_case_def = next((c for c in dm.raw.get('load_cases', []) if c['name'] == case_name), None)
        req_modes = buckling_case_def.get("num_modes", 12) if buckling_case_def else 12

        progress_callback("", 8)
        progress_callback("B E G I N   A N A L Y S I S", 8)
        progress_callback("", 8)
        progress_callback(f"NUMBER OF JOINTS                     = {len(dm.nodes):>10}", 8)
        progress_callback(f"  WITH RESTRAINTS                    = {num_restrained:>10}", 8)
        progress_callback(f"NUMBER OF FRAME ELEMENTS             = {len(dm.elements):>10}", 8)
        progress_callback(f"NUMBER OF STIFFNESS DOFs             = {dm.total_dofs:>10}", 8)
        progress_callback(f"NUMBER OF BUCKLING MODES REQUESTED   = {req_modes:>10}", 8)
        progress_callback(f"GRAVITATIONAL ACCELERATION           = {'9.80665':>10}", 8)
        progress_callback(f"UNITS (FORCE, LENGTH)                = {'kN, m':>10}", 8)
        progress_callback("", 8)

    except Exception as e:
        print(f"FATAL: Data Load Error: {e}")
        return _write_error(output_json_path, "E102", str(e))

    try:
        print("[2/6] Re-Assembling Global Elastic Stiffness (K_E)...")
        progress_callback("E L E M E N T   F O R M A T I O N", 15)
        progress_callback("", 15)
        progress_callback("Assembling elastic stiffness matrix K_E...", 18)
        assembler = GlobalAssembler(dm)
        K_full, _ = assembler.assemble_system()

        ke_nnz = K_full.nnz
        total_cells = dm.total_dofs ** 2
        sparsity = 1.0 - (ke_nnz / total_cells) if total_cells > 0 else 0

        progress_callback(f"K_E NON-ZERO TERMS                   = {ke_nnz:>10}", 22)
        progress_callback(f"MATRIX SPARSITY                      = {sparsity*100:>9.2f}%", 22)
        progress_callback("", 22)

    except Exception as e:
        print(f"FATAL: K_E Matrix Assembly Error: {e}")
        return _write_error(output_json_path, "E000", f"Matrix Assembly Error: {e}")

    try:
        print("[3/6] Assembling Geometric Stiffness (K_G)...")
        progress_callback("G E O M E T R I C   S T I F F N E S S", 28)
        progress_callback("", 28)
        progress_callback("Extracting internal forces from static results...", 32)

        extractor = ForceExtractor(input_json_path, results_path, matrices_path)
        KG_full = lil_matrix((dm.total_dofs, dm.total_dofs))
        
        elements_in_compression = 0

        for el in dm.elements:
            eid = str(el['id'])
            
            forces = extractor.get_element_forces(el['id'])
            if forces is None: continue
                
            N_axial = (forces[6] - forces[0]) / 2.0
            if N_axial < -1e-5:
                elements_in_compression += 1

            sec_props = el['section']
            
            L_geom = el['L_clear']
            
            E = el['material']['E']
            G = el['material']['G']
            As2 = sec_props['As2']
            As3 = sec_props['As3']
            I22 = sec_props['I22']
            I33 = sec_props['I33']
            
            phi_y = (12 * E * I33) / (G * As2 * L_geom**2) if As2 > 0 else 0.0
            phi_z = (12 * E * I22) / (G * As3 * L_geom**2) if As3 > 0 else 0.0

            kg_local = get_geometric_stiffness_matrix(
                N_axial, L_geom, 
                phi_y=phi_y, phi_z=phi_z, 
                A=sec_props['A'], I22=sec_props['I22'], I33=sec_props['I33']
            )
            
            idx_i, idx_j = el['node_indices']
            p1 = dm.nodes[idx_i]['coords']
            p2 = dm.nodes[idx_j]['coords']
            
            offsets_i = el['offsets'][0]
            offsets_j = el['offsets'][1]
            
            p1_adj = p1 + np.array(offsets_i)
            p2_adj = p2 + np.array(offsets_j)
            
            R_3x3 = get_rotation_matrix(p1_adj, p2_adj, el.get('beta', 0.0))
            T_rot = np.zeros((12, 12))
            for i in range(4): 
                T_rot[i*3:(i+1)*3, i*3:(i+1)*3] = R_3x3
                
            T_ecc = get_eccentricity_matrix(offsets_i, offsets_j)
            
            T_total = T_ecc @ T_rot
            
            kg_global = T_total.T @ kg_local @ T_total
            
            start_i = idx_i * 6
            start_j = idx_j * 6
            
            KG_full[start_i:start_i+6, start_i:start_i+6] += kg_global[0:6, 0:6]
            KG_full[start_i:start_i+6, start_j:start_j+6] += kg_global[0:6, 6:12]
            KG_full[start_j:start_j+6, start_i:start_i+6] += kg_global[6:12, 0:6]
            KG_full[start_j:start_j+6, start_j:start_j+6] += kg_global[6:12, 6:12]

        print(f"      Extracted forces from previous static run.")
        print(f"      Elements in compression: {elements_in_compression}/{len(dm.elements)}")

        kg_nnz = KG_full.nnz
        elements_in_tension = len(dm.elements) - elements_in_compression

        progress_callback("Assembling geometric stiffness matrix K_G...", 38)
        progress_callback(f"K_G NON-ZERO TERMS                   = {kg_nnz:>10}", 42)
        progress_callback(f"ELEMENTS IN COMPRESSION              = {elements_in_compression:>10}", 42)
        progress_callback(f"ELEMENTS IN TENSION / ZERO           = {elements_in_tension:>10}", 42)
        progress_callback("", 42)

    except Exception as e:
        print(f"FATAL: K_G Assembly Error: {e}")
        return _write_error(output_json_path, "E000", f"K_G Assembly Error: {e}")

    print("[4/6] Applying Boundary Conditions & Diaphragm Constraints...")
    progress_callback("Applying boundary conditions & diaphragms...", 48)

    is_free_full = np.ones(dm.total_dofs, dtype=bool)
    for node in dm.nodes:
        start_idx = node['idx'] * 6
        restraints = node['restraints']                           
        for i in range(6):
            if restraints[i]:           
                is_free_full[start_idx + i] = False

    has_T = hasattr(assembler, 'T') and assembler.T is not None
    if has_T:
        print("      Applying Exact Diaphragm Transformation (T) to K_E and K_G...")
        T = assembler.T
        kept_dofs = assembler.kept_dofs
        
        K_sys = T.T @ K_full @ T
        KG_sys = T.T @ KG_full @ T
        
        is_free_sys = is_free_full[kept_dofs]
    else:
        K_sys = K_full
        KG_sys = KG_full
        is_free_sys = is_free_full
    
    num_free_dofs = int(np.sum(is_free_sys))
    num_constrained = dm.total_dofs - num_free_dofs                                    

    if num_free_dofs == 0:
        return _write_error(output_json_path, "E301", "Structure is fully constrained. No free DOFs.")

    K_free  = K_sys.tocsc()[is_free_sys, :][:, is_free_sys]
    KG_free = KG_sys.tocsc()[is_free_sys, :][:, is_free_sys]

    try:
        print(f"[5/6] Solving Buckling Eigenvalues...")
        progress_callback("B U C K L I N G   E I G E N S O L U T I O N", 52)
        progress_callback("", 52)
        progress_callback(f"TOTAL EQUILIBRIUM EQUATIONS          = {num_free_dofs:>10}", 52)
        progress_callback(f"CONSTRAINED DOFs                     = {num_constrained:>10}", 52)
        progress_callback("", 52)

        if num_free_dofs < 100:
            import scipy.linalg as la
            print(f"      Using Dense Solver (Small Model: {num_free_dofs} DOFs)")
            progress_callback(f"SOLVER TYPE                          = {'Dense (Small Model)':>20}", 55)

            K_dense  = K_free.toarray()
            KG_dense = KG_free.toarray()
            
            eigenvalues, eigenvectors = la.eig(K_dense, KG_dense)
            
            valid_modes = []
            for i in range(len(eigenvalues)):
                lam = eigenvalues[i].real
                if np.isfinite(lam) and lam > 1e-6 and abs(eigenvalues[i].imag) < 1e-6:
                    valid_modes.append((lam, eigenvectors[:, i].real))
            
            valid_modes.sort(key=lambda x: x[0])
            valid_modes = valid_modes[:req_modes]
            
        else:
            safe_num_modes = min(req_modes, max(1, num_free_dofs - 2))
            if safe_num_modes < req_modes:
                print(f"Warning: Model only has {num_free_dofs} free DOFs. Clamped to {safe_num_modes} modes.")
                req_modes = safe_num_modes

            print(f"      Using Sparse Solver (Inverse Formulation)")
            progress_callback(f"SOLVER TYPE                          = {'Sparse (Inverse Formulation)':>28}", 55)

            eigenvalues_mu, eigenvectors = eigsh(A=KG_free, M=K_free, k=req_modes, which='LA')
            
            valid_modes = []
            for i in range(len(eigenvalues_mu)):
                mu = eigenvalues_mu[i]
                if mu > 1e-12: 
                    lam = 1.0 / mu
                    if lam > 1e-6:
                        valid_modes.append((lam, eigenvectors[:, i]))

            valid_modes.sort(key=lambda x: x[0])

        print(f"      Converged. Found {len(valid_modes)} buckling modes.")
        progress_callback(f"MODES FOUND                          = {len(valid_modes):>10}", 75)
        progress_callback("", 75)

    except Exception as e:
        err_str = str(e)
        print(f"FATAL: Eigen Solver Error: {err_str}")
        return _write_error(output_json_path, "E303", f"Solver Error: {err_str}")

    print("[6/6] Formatting Results...")
    progress_callback("B U C K L I N G   F A C T O R S", 80)
    progress_callback("", 80)
    progress_callback(f"{'MODE':<6} {'Lambda (λ)':>14} {'Description':>24}", 80)
    progress_callback("-" * 46, 80)

    results = {
        "status": "SUCCESS",
        "info": {"type": "Buckling Analysis"},
        "mode_shapes": {},
        "tables": {
            "buckling_factors": []
        }
    }

    for i, (lam, phi_free) in enumerate(valid_modes):
        
        phi_sys = np.zeros(K_sys.shape[0])
        phi_sys[is_free_sys] = phi_free
        
        if has_T:
            phi_full = T @ phi_sys
        else:
            phi_full = phi_sys
            
        max_val = np.max(np.abs(phi_full))
        if max_val > 0:
            phi_full = phi_full / max_val
            
        results["tables"]["buckling_factors"].append({
            "mode": i + 1,
            "lambda": float(lam)
        })
        
        shape_data = {}
        for node in dm.nodes:
            nid = str(node['id'])
            idx = node['idx'] * 6
            node_dofs = phi_full[idx : idx+6].tolist()
            shape_data[nid] = node_dofs
            
        results["mode_shapes"][f"Mode {i+1}"] = shape_data
        
        print(f"      Mode {i+1}: Buckling Factor (Lambda) = {lam:.4f}")
        progress_callback(f"{i+1:<6} {lam:>14.4f} {'Critical Load Factor':>24}", 80)

    progress_callback("-" * 46, 88)
    progress_callback("", 88)
    progress_callback("Writing results to disk...", 95)

    try:
        with open(output_json_path, 'w') as f:
            json.dump(results, f, indent=4)

        elapsed_total = time.time() - start_time
        progress_callback("A N A L Y S I S   C O M P L E T E", 98)
        progress_callback("", 98)
        progress_callback(f"TOTAL TIME FOR THIS ANALYSIS         = {elapsed_total:>8.3f}  sec", 100)
        progress_callback("", 100)

        print("="*60)
        print(f"Total Time: {elapsed_total:.4f}s")
        print("="*60)
        return True
    except Exception as e:
        print(f"FATAL: Write Error: {e}")
        return _write_error(output_json_path, "E401", str(e))

if __name__ == "__main__":
    test_in = os.path.join(current_dir, "test.mf")
    test_out = os.path.join(current_dir, "test_buckling_results.json")
    test_res = os.path.join(current_dir, "results.json")
    test_mat = os.path.join(current_dir, "cli_matrices.json")
    
    if os.path.exists(test_in):
        run_buckling_analysis(test_in, test_out, test_res, test_mat)
