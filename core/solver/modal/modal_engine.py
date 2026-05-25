import sys
import os
import time
import numpy as np
import json
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
from linear_static.error_definitions import SolverException
from mass_assembler import GlobalMassAssembler

def _write_error(out_path, error_code, extra=""):
    """Writes the error to JSON and returns True so the UI loads the error dialog."""
    ex = SolverException(error_code, extra)
    try:
        with open(out_path, 'w') as f:
            json.dump({"status": "FAILED", "error": ex.get_details()}, f, indent=4)
    except:
        pass
    return True

def run_modal_analysis(input_json_path, output_json_path, target_case_name="MODAL", progress_callback=None):
    print("="*60)
    print(f"METUFIRE MODAL ENGINE | V0.3 (Shift-Invert)")
    print(f"Target: {os.path.basename(input_json_path)}")
    print("="*60)
    
    start_time = time.time()

    if progress_callback is None:
        from progress import noop_callback
        progress_callback = noop_callback
    
    try:
        print("[1/6] Initializing Data Manager...")
        progress_callback("Loading model data...", 8)
        dm = DataManager(input_json_path)
        target_case = "MODAL"
        dm.process_all(case_name=target_case_name)
    except Exception as e:
        print(f"FATAL: Data Load Error: {e}")
        return _write_error(output_json_path, "E102", str(e))

    try:
        print("[2/6] Assembling System Matrices (K & M)...")
        
        assembler = GlobalAssembler(dm)

        progress_callback("Assembling stiffness matrix...", 18)
                                                                                                 
        res = assembler.assemble_system()
        K_full = res[0]                    
        
        modal_case_def = next((c for c in dm.raw['load_cases'] if c['name'] == target_case_name), None)
        ms_name = modal_case_def.get("mass_source", "Default") if modal_case_def else "Default"
        
        mass_assembler = GlobalMassAssembler(dm)

        progress_callback("Assembling mass matrix...", 28)
        M_full = mass_assembler.build_mass_matrix(ms_name, progress_callback=progress_callback)

        if M_full.nnz == 0 or M_full.diagonal().sum() < 1e-9:
            return _write_error(output_json_path, "E105", f"Mass Source '{ms_name}' resulted in zero mass.")

        results = {
            "status": "SUCCESS",
            "info": {"type": "Modal Analysis"},
            "mode_shapes": {},
            "tables": { ... }
        }
        
    except Exception as e:
        print(f"FATAL: Matrix Assembly Error: {e}")
        return _write_error(output_json_path, "E000", f"Matrix Assembly Error: {e}")

    print("[3/6] Applying Boundary Conditions...")

    progress_callback("Applying boundary conditions...", 35)

    is_free = np.ones(dm.total_dofs, dtype=bool)
    for node in dm.nodes:
        start_idx = node['idx'] * 6
        restraints = node['restraints']                           
        for i in range(6):
            if restraints[i]:           
                is_free[start_idx + i] = False
    
    free_dof_indices = np.where(is_free)[0]
    num_free_dofs = len(free_dof_indices)
    
    print(f"      Total DOFs: {dm.total_dofs}")
    print(f"      Free  DOFs: {num_free_dofs}")

    progress_callback("", 35)
    progress_callback("B E G I N   A N A L Y S I S", 35)
    progress_callback("", 35)
    progress_callback(f"NUMBER OF JOINTS                     = {len(dm.nodes):>10}", 35)
    progress_callback(f"NUMBER OF FRAME ELEMENTS             = {len(dm.elements):>10}", 35)
    progress_callback(f"NUMBER OF STIFFNESS DOFs             = {dm.total_dofs:>10}", 35)
    progress_callback(f"NUMBER OF FREE DOFs                  = {num_free_dofs:>10}", 35)
    progress_callback("", 35)

    if num_free_dofs == 0:
        print("Error: Structure is fully constrained.")
        return _write_error(output_json_path, "E301", "Structure is fully constrained. No free DOFs.")

    K_free = K_full.tocsc()[is_free, :][:, is_free]
    M_free = M_full.tocsc()[is_free, :][:, is_free]

    m_diag = M_free.diagonal()
    min_nonzero_mass = m_diag[m_diag > 1e-10].min() * 1e-6
    from scipy.sparse import diags
    zero_mask = m_diag < 1e-10
    reg = diags(zero_mask.astype(float) * min_nonzero_mass)
    M_free = M_free + reg

    print(f"DEBUG: M_free sum = {M_free.sum():.6f}")
    print(f"DEBUG: M_free diagonal sum = {M_free.diagonal().sum():.6f}")

    try:
        req_modes = modal_case_def.get("num_modes", 12) if modal_case_def else 12
  
        n_free_dofs = K_free.shape[0]
        max_safe_modes = max(1, n_free_dofs - 2)
        safe_num_modes = min(req_modes, max_safe_modes)
        
        if safe_num_modes <= 0:
            return _write_error(output_json_path, "E304",
                f"Structure only has {n_free_dofs} free DOFs. Need at least 2 free DOFs for modal analysis.")
            
        if safe_num_modes < req_modes:
            print(f"Warning: Requested {req_modes} modes but model only has {n_free_dofs} free DOFs. Clamped to {safe_num_modes} modes.")
            req_modes = safe_num_modes

        print(f"[4/6] Solving Eigenvalues (Shift-Invert @ -0.1)...")
        sigma_shift = -0.1

        print(f"K_free shape: {K_free.shape}")
        print(f"M_free shape: {M_free.shape}")
        print(f"K_free diagonal min: {K_free.diagonal().min():.6f}")
        print(f"M_free diagonal min: {M_free.diagonal().min():.6f}")
        print(f"M_free diagonal sum: {M_free.diagonal().sum():.6f}")

        k_row_sums = np.abs(K_free).sum(axis=1).A1
        zero_k_rows = np.where(k_row_sums < 1e-10)[0]
        print(f"Zero rows in K_free: {len(zero_k_rows)} -> indices: {zero_k_rows[:10]}")

        m_diag = M_free.diagonal()
        zero_m_rows = np.where(m_diag < 1e-10)[0]
        print(f"Zero diagonal in M_free: {len(zero_m_rows)} / {len(m_diag)}")

        progress_callback("Solving eigenvalue problem — this may take a moment...", 42)
                             
        vals, vecs = eigsh(K_free, M=M_free, k=req_modes, sigma=sigma_shift)
        
        print(f"      Converged. Found {len(vals)} modes.")

        progress_callback("Eigenvalue solve complete. Extracting modes...", 65)
        num_mass_dofs = int(np.sum(M_free.diagonal() > 1e-10))
        progress_callback(f"NUMBER OF MASS DOFs                  = {num_mass_dofs:>10}", 65)
        progress_callback(f"NUMBER OF MODES REQUESTED            = {req_modes:>10}", 65)
        progress_callback(f"NUMBER OF MODES FOUND                = {len(vals):>10}", 65)
        progress_callback("", 65)

    except Exception as e:
        err_str = str(e)
        print(f"FATAL: Eigen Solver Error: {err_str}")
        if "-9999" in err_str or "Arnoldi" in err_str:
            return _write_error(output_json_path, "E304",
                f"Requested {req_modes} modes but the solver could not converge. "
                f"Your model has {n_free_dofs} free DOFs. "
                f"Try reducing Number of Modes to {max(1, req_modes // 2)} or check for disconnected nodes.")
        else:
            return _write_error(output_json_path, "E303", f"ARPACK Error: {err_str}")

    print("[5/6] Calculating Modal Participation...")
    
    results = {
        "status": "SUCCESS",
        "info": {"type": "Modal Analysis"},
        "mode_shapes": {},
        "tables": {
            "periods": [],
            "participation_mass": []
        }
    }

    print("      Extracting Assembled Joint Masses...")
    assembled_mass = {}
    M_diag = M_full.diagonal()                                        
    
    for node in dm.nodes:
        nid = str(node['id'])
        idx = node['idx'] * 6
        m_vals = M_diag[idx : idx+6].tolist()
        assembled_mass[nid] = m_vals
        
    results["assembled_mass"] = assembled_mass

    diag_M = M_full.diagonal()
    
    mask_x = np.zeros(dm.total_dofs, dtype=bool); mask_x[0::6] = True
    mask_y = np.zeros(dm.total_dofs, dtype=bool); mask_y[1::6] = True
    mask_z = np.zeros(dm.total_dofs, dtype=bool); mask_z[2::6] = True
    
    total_mass_x = np.sum(diag_M[mask_x & is_free])
    total_mass_y = np.sum(diag_M[mask_y & is_free])
    total_mass_z = np.sum(diag_M[mask_z & is_free])                                      

    print(f"DEBUG: total_mass_x = {total_mass_x:.6f} kg")
    print(f"DEBUG: total_mass_x in kN-s²/m = {total_mass_x / 1000:.6f}")
    print(f"DEBUG: Sum of all assembled masses X = {sum(assembled_mass[nid][0] for nid in assembled_mass):.6f}")

    results["total_mass"] = {
        "x": float(total_mass_x),
        "y": float(total_mass_y),
        "z": float(total_mass_z)
    }
    
    sum_ratio_x = 0.0
    sum_ratio_y = 0.0
    sum_ratio_z = 0.0                                 

    r_x = np.zeros(dm.total_dofs); r_x[0::6] = 1.0
    r_y = np.zeros(dm.total_dofs); r_y[1::6] = 1.0
    r_z = np.zeros(dm.total_dofs); r_z[2::6] = 1.0                               
    
    r_x_free = r_x[is_free]
    r_y_free = r_y[is_free]
    r_z_free = r_z[is_free]                                

    for i in range(len(vals)):
        w2 = vals[i]
        phi_free = vecs[:, i]              

        phi_raw = vecs[:, i] 

        Mn_raw = (phi_raw.T @ M_free @ phi_raw)
        
        if Mn_raw > 0:
            scale_factor = 1.0 / np.sqrt(Mn_raw)
        else:
            scale_factor = 1.0
            
        phi_free = phi_raw * scale_factor
        
        Mn = (phi_free.T @ M_free @ phi_free)
        
        if w2 < 1e-6:
             omega = 0.0
             freq = 0.0
             period = 999.99           
                                                              
        else:
             omega = np.sqrt(w2)
             freq = omega / (2 * np.pi)
             period = 1.0 / freq

        pct = 65 + int(20 * (i + 1) / len(vals))
        progress_callback(f"Processing mode {i+1} of {len(vals)}  —  T = {period:.3f} s", pct)
        
        results["tables"]["periods"].append({
            "mode": i + 1,
            "T": float(period),
            "f": float(freq),
            "omega": float(omega),
            "eigen": float(w2)
        })

        Mn = (phi_free.T @ M_free @ phi_free)
        
        if Mn == 0: Mn = 1.0                                

        L_x = phi_free.T @ M_free @ r_x_free
        L_y = phi_free.T @ M_free @ r_y_free
        L_z = phi_free.T @ M_free @ r_z_free                                         

        if i == 3 or i == 6:                             
            print(f"  DEBUG Mode {i+1}: L_x={L_x:.6f}, Mn={Mn:.6f}, Gamma={L_x/np.sqrt(total_mass_x * Mn):.6f}")

        if i == 3:          
            print(f"    phi_free shape: {phi_free.shape}")
            print(f"    M_free shape: {M_free.shape}")
            print(f"    r_x_free shape: {r_x_free.shape}")
            print(f"    Sum of r_x_free: {np.sum(r_x_free)}")
            print(f"    M @ r_x sum: {np.sum(M_free @ r_x_free)}")

        em_x = (L_x**2) / Mn 
        em_y = (L_y**2) / Mn 
        em_z = (L_z**2) / Mn                                          
        
        ratio_x = em_x / total_mass_x if total_mass_x > 0 else 0
        ratio_y = em_y / total_mass_y if total_mass_y > 0 else 0
        ratio_z = em_z / total_mass_z if total_mass_z > 0 else 0                                 
        
        sum_ratio_x += ratio_x
        sum_ratio_y += ratio_y
        sum_ratio_z += ratio_z                            
        
        gamma_x = float(L_x / np.sqrt(total_mass_x * Mn))
        gamma_y = float(L_y / np.sqrt(total_mass_y * Mn))
        gamma_z = float(L_z / np.sqrt(total_mass_z * Mn))                                 

        results["tables"]["participation_mass"].append({
            "mode": i + 1,
            "Ux": float(ratio_x), "SumUx": float(sum_ratio_x),
            "Uy": float(ratio_y), "SumUy": float(sum_ratio_y),
            "Uz": float(ratio_z), "SumUz": float(sum_ratio_z),                           
            "Gamma_x": gamma_x, "Gamma_y": gamma_y, "Gamma_z": gamma_z                            
        })
        
        phi_full = np.zeros(dm.total_dofs)
        phi_full[is_free] = phi_free
        
        shape_data = {}
        for node in dm.nodes:
            nid = str(node['id'])
            idx = node['idx'] * 6
            node_dofs = phi_full[idx : idx+6].tolist()
            shape_data[nid] = node_dofs
            
        results["mode_shapes"][f"Mode {i+1}"] = shape_data

    try:
        progress_callback("Computing rotational participation...", 88)
        rot_results, total_mass_rot = compute_rotational_participation(
            dm, M_full, M_free, is_free, vecs, vals
        )
        for i, row in enumerate(results["tables"]["participation_mass"]):
            row.update(rot_results[i])
        results["total_mass"].update({
            "rx": total_mass_rot["Rx"],
            "ry": total_mass_rot["Ry"],
            "rz": total_mass_rot["Rz"]
        })
        print(f"      Rotational participation computed OK.")
    except Exception as e:
        print(f"WARNING: Rotational participation failed (non-fatal): {e}")

    progress_callback("", 89)
    progress_callback(f"{'MODE':<6} {'T(s)':>9} {'f(Hz)':>9} {'ω(rad/s)':>10} {'Ux%':>7} {'Uy%':>7} {'Uz%':>7} {'ΣUx%':>8} {'ΣUy%':>8} {'ΣUz%':>8}", 89)
    progress_callback("-" * 80, 89)
    for row_p, row_t in zip(results["tables"]["participation_mass"], results["tables"]["periods"]):
        progress_callback(
            f"{row_p['mode']:<6} {row_t['T']:>9.4f} {row_t['f']:>9.4f} {row_t['omega']:>10.3f} "
            f"{row_p['Ux']*100:>7.2f} {row_p['Uy']*100:>7.2f} {row_p['Uz']*100:>7.2f} "
            f"{row_p['SumUx']*100:>8.2f} {row_p['SumUy']*100:>8.2f} {row_p['SumUz']*100:>8.2f}",
            89
        )
    progress_callback("-" * 80, 89)
    tm = results["total_mass"]
    progress_callback(f"TOTAL MASS   X = {tm['x']:.4f} kg    Y = {tm['y']:.4f} kg    Z = {tm['z']:.4f} kg", 90)
    progress_callback("", 90)

    try:
        print("[6/6] Writing Results...")
        progress_callback("Writing results...", 95)
        with open(output_json_path, 'w') as f:
            json.dump(results, f, indent=4)
        print("Done.")
        elapsed_total = time.time() - start_time
        progress_callback("A N A L Y S I S   C O M P L E T E", 98)
        progress_callback("", 98)
        progress_callback(f"TOTAL TIME FOR THIS ANALYSIS         = {elapsed_total:>8.3f}  sec", 100)
        progress_callback("", 100)
        return True
    except Exception as e:
        print(f"FATAL: Write Error: {e}")
        return _write_error(output_json_path, "E401", str(e))

def compute_rotational_participation(dm, M_full, M_free, is_free, vecs, vals):
    """
    Computes rotational mass participation ratios (Rx, Ry, Rz) for each mode.
    
    Completely non-destructive - receives already-computed vecs/vals/M_free,
    does NOT touch the main solver pipeline at all.
    
    Uses rigid-body rotation kinematics about the center of mass:
      Rz: r_rz[Ux] = -(y-yCM), r_rz[Uy] = +(x-xCM), r_rz[Rz] = 1
      Rx: r_rx[Uy] = -(z-zCM), r_rx[Uz] = +(y-yCM), r_rx[Rx] = 1
      Ry: r_ry[Ux] = +(z-zCM), r_ry[Uz] = -(x-xCM), r_ry[Ry] = 1

    Returns:
        rot_results  : list of per-mode dicts with Rx/SumRx, Ry/SumRy, Rz/SumRz
        total_mass_rot: dict with generalized rotational masses Rx, Ry, Rz
    """
    total_dofs = dm.total_dofs

    M_diag_full = M_full.diagonal()
    x_cm, y_cm, z_cm, total_m = 0.0, 0.0, 0.0, 0.0
    for node in dm.nodes:
        idx = node['idx'] * 6
        m_avg = (M_diag_full[idx] + M_diag_full[idx+1] + M_diag_full[idx+2]) / 3.0
        x, y, z = node['coords']
        x_cm += m_avg * x
        y_cm += m_avg * y
        z_cm += m_avg * z
        total_m += m_avg

    if total_m > 1e-12:
        x_cm /= total_m
        y_cm /= total_m
        z_cm /= total_m

    print(f"[ROT] Center of Mass: ({x_cm:.3f}, {y_cm:.3f}, {z_cm:.3f})")

    r_rx = np.zeros(total_dofs)
    r_ry = np.zeros(total_dofs)
    r_rz = np.zeros(total_dofs)

    for node in dm.nodes:
        idx = node['idx'] * 6
        x, y, z = node['coords']
        dx = x - x_cm
        dy = y - y_cm
        dz = z - z_cm

        r_rz[idx + 0] = -dy   
        r_rz[idx + 1] = +dx    
        r_rz[idx + 5] = 1.0    

        r_rx[idx + 1] = -dz    
        r_rx[idx + 2] = +dy  
        r_rx[idx + 3] = 1.0 

        r_ry[idx + 0] = +dz   
        r_ry[idx + 2] = -dx    
        r_ry[idx + 4] = 1.0   

    r_rx_free = r_rx[is_free]
    r_ry_free = r_ry[is_free]
    r_rz_free = r_rz[is_free]

    total_mass_rx = float(r_rx_free @ M_free @ r_rx_free)
    total_mass_ry = float(r_ry_free @ M_free @ r_ry_free)
    total_mass_rz = float(r_rz_free @ M_free @ r_rz_free)

    print(f"[ROT] Generalized Rotational Mass: Rx={total_mass_rx:.3f}, Ry={total_mass_ry:.3f}, Rz={total_mass_rz:.3f}")

    rot_results = []
    sum_rx, sum_ry, sum_rz = 0.0, 0.0, 0.0

    for i in range(len(vals)):
        phi_raw = vecs[:, i]
        Mn_raw = float(phi_raw.T @ M_free @ phi_raw)
        scale = 1.0 / np.sqrt(Mn_raw) if Mn_raw > 0 else 1.0
        phi = phi_raw * scale
        Mn = float(phi.T @ M_free @ phi)
        if Mn == 0:
            Mn = 1.0

        L_rx = float(phi.T @ M_free @ r_rx_free)
        L_ry = float(phi.T @ M_free @ r_ry_free)
        L_rz = float(phi.T @ M_free @ r_rz_free)

        ratio_rx = (L_rx**2 / Mn) / total_mass_rx if total_mass_rx > 0 else 0.0
        ratio_ry = (L_ry**2 / Mn) / total_mass_ry if total_mass_ry > 0 else 0.0
        ratio_rz = (L_rz**2 / Mn) / total_mass_rz if total_mass_rz > 0 else 0.0

        sum_rx += ratio_rx
        sum_ry += ratio_ry
        sum_rz += ratio_rz

        rot_results.append({
            "Rx": ratio_rx, "SumRx": sum_rx,
            "Ry": ratio_ry, "SumRy": sum_ry,
            "Rz": ratio_rz, "SumRz": sum_rz,
        })

    return rot_results, {"Rx": total_mass_rx, "Ry": total_mass_ry, "Rz": total_mass_rz}

if __name__ == "__main__":
    test_in = os.path.join(current_dir, "test3.mf")
    test_out = os.path.join(current_dir, "test3_results.json")
    if os.path.exists(test_in):
        run_modal_analysis(test_in, test_out)
