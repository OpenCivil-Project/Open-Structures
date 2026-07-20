import os
import sys
import json
import numpy as np

current_dir = os.path.dirname(os.path.abspath(__file__))
solver_dir = os.path.dirname(current_dir)
linear_static_dir = os.path.join(solver_dir, 'linear_static')

if current_dir not in sys.path:
    sys.path.append(current_dir)
if solver_dir not in sys.path:
    sys.path.append(solver_dir)
if linear_static_dir not in sys.path:
    sys.path.append(linear_static_dir)

from newmark_sdof import newmark_elastic_sdof, exact_analytical_sdof
from linear_static.data_manager import DataManager
from linear_static.assembler import GlobalAssembler

def run_ltha_analysis(input_path, modal_results_path, model_data, output_path, case_name="LTHA"):
    print("=" * 60)
    print("METUFIRE LTHA ENGINE | V0.3 (Modal Superposition + Reactions)")
    print("=" * 60)

    if not os.path.exists(modal_results_path):
        _write_error(output_path, "Modal results not found. Run MODAL analysis first.")
        return False

    with open(modal_results_path, 'r') as f:
        modal_data = json.load(f)

    if modal_data.get("status") != "SUCCESS":
        _write_error(output_path, "Modal analysis did not succeed.")
        return False

    periods_table = modal_data["tables"]["periods"]
    mass_ratios   = modal_data["tables"]["participation_mass"]
    mode_shapes   = modal_data["mode_shapes"]

    print(f"[1/5] Loaded {len(periods_table)} modes from modal results.")

    load_cases  = model_data.get("load_cases", {})
    case_obj    = load_cases.get(case_name)
    th_functions = getattr(model_data, "th_functions", None) or model_data.get("th_functions", {})

    zeta = 0.05
    if case_obj is not None:
        zeta = getattr(case_obj, "damping", 0.05)

    ltha_loads_raw = getattr(case_obj, "ltha_loads", []) if case_obj else []

    if not ltha_loads_raw:
        _write_error(output_path, "No ground motion loads defined. Add at least one function in the LTHA case.")
        return False

    resolved_loads = []
    for direction, func_name, scale in ltha_loads_raw:
        func_data = th_functions.get(func_name)
        if not func_data:
            _write_error(output_path, f"Function '{func_name}' not found in model.")
            return False

        values = func_data.get("values", [])
        if not values:
            file_path = func_data.get("file_path", "")
            header_skip = func_data.get("header_skip", 0)
            accel_col   = func_data.get("accel_col", 0)
            if file_path and os.path.exists(file_path):
                values = _read_values_from_file(file_path, header_skip, accel_col)
            if not values:
                _write_error(output_path, f"Function '{func_name}' has no data. Check the file path.")
                return False

        dt = func_data.get("dt", 0.01)
        resolved_loads.append((direction, np.array(values, dtype=float), dt, float(scale)))
        print(f"[2/5] Function '{func_name}' ({direction}): {len(values)} steps, dt={dt:.4f}s")

    n_steps = max(len(a) for _, a, _, _ in resolved_loads)
    dt_ref = resolved_loads[0][2]

    print("[3/5] Assembling stiffness matrix K for reaction recovery...")
    try:
        dm = DataManager(input_path)
        dm.process_all(case_name=case_name)
        assembler = GlobalAssembler(dm)          
        K, _ = assembler.assemble_system()
        K_csr = K.tocsr()

        from core.solver.modal.mass_assembler import GlobalMassAssembler
        mass_asm = GlobalMassAssembler(dm)
        ms_name = dm.raw["mass_sources"][0]["name"] if dm.raw.get("mass_sources") else "Default"
        M_full = mass_asm.build_mass_matrix(ms_name)
        M_diag = M_full.diagonal()

    except Exception as e:
        _write_error(output_path, f"Could not assemble stiffness matrix for reactions: {e}")
        return False

    restrained_indices = []
    restrained_node_dof = []
    node_coords = {}

    for node in dm.nodes:
        nid = str(node['id'])
        idx = node['idx'] * 6
        restraints = node['restraints']
        for d in range(6):
            if restraints[d]:
                restrained_indices.append(idx + d)
                restrained_node_dof.append((nid, d))
        if any(restraints):
            node_coords[nid] = tuple(node['coords'])

    restrained_indices = np.array(restrained_indices, dtype=int)
    has_restraints = len(restrained_indices) > 0

    if has_restraints:
        K_restrained_rows = K_csr[restrained_indices, :]
    else:
        print("      WARNING: No restrained DOFs found — joint/base reactions will be zero.")

    node_ids = list(mode_shapes["Mode 1"].keys())
    U_history = {nid: np.zeros((n_steps, 6)) for nid in node_ids}
    V_history = {nid: np.zeros((n_steps, 6)) for nid in node_ids}
    A_history = {nid: np.zeros((n_steps, 6)) for nid in node_ids}

    restrained_node_ids = sorted(set(nid for nid, _ in restrained_node_dof))
    R_history = {nid: np.zeros((n_steps, 6)) for nid in restrained_node_ids}
    
    R_inertia = {nid: np.zeros((n_steps, 3)) for nid in restrained_node_ids}

    directions_str = " + ".join(d for d, _, _, _ in resolved_loads)
    print(f"[4/5] Running modal superposition (directions={directions_str})...")

    for direction, accel_raw, dt, scale in resolved_loads:
        if len(accel_raw) < n_steps:
            accel_padded = np.zeros(n_steps)
            accel_padded[:len(accel_raw)] = accel_raw
        else:
            accel_padded = accel_raw[:n_steps]

        accel_scaled = scale * accel_padded

        ground_v = np.zeros(n_steps)
        for j in range(n_steps - 1):
            ground_v[j+1] = ground_v[j] + 0.5 * (accel_scaled[j] + accel_scaled[j+1]) * dt

        dir_idx = 0 if direction == "X" else (1 if direction == "Y" else 2)

        for nid, hist in R_history.items():
            node_idx = next((n['idx'] for n in dm.nodes if str(n['id']) == nid), None)
            if node_idx is not None:
                m_val = M_diag[node_idx * 6 + dir_idx]
                inertia_force = m_val * accel_scaled
                hist[:, dir_idx] += inertia_force
                R_inertia[nid][:, dir_idx] += inertia_force

        for i, mode_info in enumerate(periods_table):
            T     = mode_info["T"]
            omega = mode_info["omega"]

            if T < 1e-6 or omega < 1e-6: continue

            pm = mass_ratios[i]
            m_total_x = modal_data.get("total_mass", {}).get("x", 0.0)
            m_total_y = modal_data.get("total_mass", {}).get("y", 0.0)
            m_total_z = modal_data.get("total_mass", {}).get("z", 0.0)

            if direction == "X":
                ratio, raw_g = pm.get("Ux", 0.0), pm.get("Gamma_x", 0.0)
                Gamma = np.sign(raw_g) * np.sqrt(ratio * m_total_x) if m_total_x > 0 else 0.0
            elif direction == "Y":
                ratio, raw_g = pm.get("Uy", 0.0), pm.get("Gamma_y", 0.0)
                Gamma = np.sign(raw_g) * np.sqrt(ratio * m_total_y) if m_total_y > 0 else 0.0
            else:
                ratio, raw_g = pm.get("Uz", 0.0), pm.get("Gamma_z", 0.0)
                Gamma = np.sign(raw_g) * np.sqrt(ratio * m_total_z) if m_total_z > 0 else 0.0

            accel_eff = Gamma * accel_scaled
            q_n, v_n, a_n = exact_analytical_sdof(accel_eff, dt, T, zeta, m=1.0)

            mode_key   = f"Mode {i+1}"
            shape_data = mode_shapes.get(mode_key, {})

            for nid in node_ids:
                if nid not in shape_data: continue
                phi = np.array(shape_data[nid])
                U_history[nid] += np.outer(q_n, phi)
                V_history[nid] += np.outer(v_n, phi)
                A_history[nid] += np.outer(a_n, phi)

            if has_restraints:
                phi_full = np.zeros(dm.total_dofs)
                for node in dm.nodes:
                    snid = str(node['id'])
                    if snid in shape_data:
                        sidx = node['idx'] * 6
                        phi_full[sidx: sidx + 6] = shape_data[snid]

                if hasattr(assembler, 'eliminated_dofs') and assembler.eliminated_dofs:
                    for s_dof, terms in assembler.eliminated_dofs.items():
                        phi_full[s_dof] = sum(phi_full[m_dof] * coeff for m_dof, coeff in terms.items())

                for nid in restrained_node_ids:
                    node_idx = next(n['idx'] for n in dm.nodes if str(n['id']) == nid)
                    y_c, z_c, rx_c = phi_full[node_idx*6+1], phi_full[node_idx*6+2], phi_full[node_idx*6+3]
                    if abs(y_c) > 1e-12 or abs(z_c) > 1e-12 or abs(rx_c) > 1e-12:
                        print(f"  {mode_key} node {nid}: Y={y_c:.3e} Z={z_c:.3e} RX={rx_c:.3e}")

                r_n_vec = K_restrained_rows.dot(phi_full)     

                for k, (nid, dof) in enumerate(restrained_node_dof):
                    R_history[nid][:, dof] += q_n * r_n_vec[k]

        for nid in node_ids:
            if nid in V_history: V_history[nid][:, dir_idx] += ground_v
            if nid in A_history: A_history[nid][:, dir_idx] += accel_scaled

    print("[5/5] Extracting envelopes and writing results...")

    def _get_envelopes(hist_dict):
        v_min, v_max, v_abs = {}, {}, {}
        for nid, hist in hist_dict.items():
            v_min[nid] = np.min(hist, axis=0).tolist()
            v_max[nid] = np.max(hist, axis=0).tolist()
            v_abs[nid] = np.max(np.abs(hist), axis=0).tolist()
        return v_min, v_max, v_abs

    peak_displacements = {nid: np.max(np.abs(hist), axis=0).tolist() for nid, hist in U_history.items()}
    
    displacements_min, displacements_max, displacements_abs = _get_envelopes(U_history)
    velocities_min, velocities_max, velocities_abs = _get_envelopes(V_history)
    accelerations_min, accelerations_max, accelerations_abs = _get_envelopes(A_history)

    if has_restraints:
        reactions_min, reactions_max, reactions_abs = _get_envelopes(R_history)
    else:
        reactions_min, reactions_max, reactions_abs = {}, {}, {}

    base_reaction_history = np.zeros((n_steps, 6))

    mx_term = np.zeros(n_steps)
    cross_term = np.zeros(n_steps)
    for nid, hist in R_history.items():
        x, y, z = node_coords.get(nid, (0.0, 0.0, 0.0))
        fx, fy, fz = hist[:, 0], hist[:, 1], hist[:, 2]
        mx, my, mz = hist[:, 3], hist[:, 4], hist[:, 5]

        mx_term += mx
        cross_term += y * fz - z * fy

        base_reaction_history[:, 0] += fx
        base_reaction_history[:, 1] += fy
        base_reaction_history[:, 2] += fz
        
        base_reaction_history[:, 3] += mx + (y * fz - z * fy)
        base_reaction_history[:, 4] += my + (z * fx - x * fz)
        base_reaction_history[:, 5] += mz + (x * fy - y * fx)

    imax = np.argmax(np.abs(mx_term + cross_term))

    print("\n===== MX DEBUG =====")
    print("Peak timestep:", imax)
    print("Sum of support Mx =", mx_term[imax])
    print("Sum of y*Fz-z*Fy =", cross_term[imax])
    print("Total Mx =", mx_term[imax] + cross_term[imax])
    print("====================")

    br_min = np.min(base_reaction_history, axis=0)
    imax = np.argmax(base_reaction_history[:, 3])

    print("\n===== PEAK MX =====")
    print("Time step:", imax)
    print("Mx =", base_reaction_history[imax, 3])

    for nid, hist in R_history.items():
        print(
            nid,
            hist[imax, 3],      
            hist[imax, 2]       
        )

    br_max = np.max(base_reaction_history, axis=0)
    br_absmax = np.max(np.abs(base_reaction_history), axis=0)

    dof_keys = ["Fx", "Fy", "Fz", "Mx", "My", "Mz"]
    base_reaction_min = {k: float(v) for k, v in zip(dof_keys, br_min)}
    base_reaction_max = {k: float(v) for k, v in zip(dof_keys, br_max)}
    base_reaction_absmax = {k: float(v) for k, v in zip(dof_keys, br_absmax)}

    print("\n===== BASE REACTION =====")
    for k, v in base_reaction_absmax.items():
        print(f"{k}: {v}")
    print("=========================\n")

    history_path = output_path.replace("_results.json", "_LTHA_history.npz")
    npz_payload = {"node_" + str(nid): hist for nid, hist in U_history.items()}
    npz_payload.update({"vel_node_" + str(nid): hist for nid, hist in V_history.items()})
    npz_payload.update({"acc_node_" + str(nid): hist for nid, hist in A_history.items()})

    npz_payload.update({"reac_node_" + str(nid): hist for nid, hist in R_history.items()})
    npz_payload["base_reaction_history"] = base_reaction_history
    np.savez_compressed(history_path, **npz_payload)

    accel_history_dict = {}
    for direction, accel_raw, dt, scale in resolved_loads:
        if len(accel_raw) < n_steps:
            padded = np.zeros(n_steps)
            padded[:len(accel_raw)] = accel_raw
            accel_history_dict[direction] = padded.tolist()
        else:
            accel_history_dict[direction] = accel_raw[:n_steps].tolist()

    output_data = {
        "status": "SUCCESS",
        "info": {
            "type":       "Linear Time History Analysis",
            "case":       case_name,
            "directions": [d for d, _, _, _ in resolved_loads],
            "damping":    zeta,
            "n_modes":    len(periods_table),
            "n_steps":    n_steps,
            "dt":         dt_ref
        },
        "displacements":          peak_displacements,
        "displacements_min":      displacements_min,
        "displacements_max":      displacements_max,
        "displacements_abs":      displacements_abs,
        "velocities_min":         velocities_min,
        "velocities_max":         velocities_max,
        "velocities_abs":         velocities_abs,
        "accelerations_min":      accelerations_min,
        "accelerations_max":      accelerations_max,
        "accelerations_abs":      accelerations_abs,
        "restrained_nodes":       restrained_node_ids,
        "reactions_min":          reactions_min,
        "reactions_max":          reactions_max,
        "reactions_abs":          reactions_abs,
        "base_reaction":          base_reaction_absmax,
        "base_reaction_min":      base_reaction_min,
        "base_reaction_max":      base_reaction_max,
        "history_path":           history_path,
        "accel_history":          accel_history_dict
    }

    with open(output_path, 'w') as f:
        json.dump(output_data, f, indent=4)

    print("LTHA Complete.")
    return True

def _read_values_from_file(file_path, header_skip, accel_col):
    """
    Fallback reader if th_functions cache is empty.
    Mirrors the logic in TimeHistoryFunctionDialog._read_file.
    """
    import csv
    values = []
    try:
        with open(file_path, 'r') as f:
            sample = f.read(2048)
            f.seek(0)
            delimiter = '\t' if '\t' in sample else ','
            reader = csv.reader(f, delimiter=delimiter)
            for row_i, row in enumerate(reader):
                if row_i < header_skip:
                    continue
                if not row or len(row) <= accel_col:
                    continue
                try:
                    values.append(float(row[accel_col]))
                except ValueError:
                    continue
    except Exception:
        pass
    return values

def _load_ground_motion(csv_path, dt):
    """
    Legacy CSV loader — kept intact for any external callers.
    Acceleration is read from the column named 'acceleration_m_s2' (index 2 fallback).
    """
    import csv

    accels = []
    accel_col_idx = None

    with open(csv_path, 'r') as f:
        sample = f.read(1024)
        f.seek(0)
        delimiter = '\t' if '\t' in sample else ','
        reader = csv.reader(f, delimiter=delimiter)

        for row in reader:
            if not row:
                continue

            if accel_col_idx is None:
                for i, cell in enumerate(row):
                    if 'acceleration_m_s2' in cell.lower():
                        accel_col_idx = i
                        break
                if accel_col_idx is None:
                    accel_col_idx = 2
                continue

            if len(row) <= accel_col_idx:
                continue

            try:
                accels.append(float(row[accel_col_idx]))
            except ValueError:
                continue

    if len(accels) < 10:
        raise ValueError(f"Ground motion file has too few data rows: {csv_path}")

    return np.array(accels)

def _write_error(output_path, message):
    with open(output_path, 'w') as f:
        json.dump({"status": "FAILED",
                   "error": {"title": "LTHA Error", "desc": message}}, f, indent=4)
    print(f"LTHA ERROR: {message}")
