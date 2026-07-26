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

from newmark_sdof import exact_analytical_sdof
from linear_static.data_manager import DataManager
from linear_static.assembler import GlobalAssembler

def run_ltha_analysis(input_path, modal_results_path, model_data, output_path, case_name="LTHA", progress_callback=None):
    if progress_callback is None:
        from progress import noop_callback
        progress_callback = noop_callback

    progress_callback("=" * 60, 0)
    progress_callback("METUFIRE LTHA ENGINE | V0.4 (Vectorized Matrix Superposition)", 2)
    progress_callback("=" * 60, 5)

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
    n_modes       = len(periods_table)

    progress_callback(f"[1/5] Loaded {n_modes} modes from modal results.", 15)

    load_cases   = model_data.get("load_cases", {})
    case_obj     = load_cases.get(case_name)
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
        progress_callback(f"[2/5] Function '{func_name}' ({direction}): {len(values)} steps, dt={dt:.4f}s", 25)

    n_steps = max(len(a) for _, a, _, _ in resolved_loads)
    dt_ref = resolved_loads[0][2]

    progress_callback("[3/5] Assembling system structures & mode shape matrices...", 35)
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
    node_id_to_idx = {}

    for node in dm.nodes:
        nid = str(node['id'])
        idx = node['idx'] * 6
        node_id_to_idx[nid] = node['idx']
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
    restrained_node_ids = sorted(set(nid for nid, _ in restrained_node_dof))

    Phi_full = np.zeros((dm.total_dofs, n_modes))
    for m_idx in range(n_modes):
        mode_key = f"Mode {m_idx + 1}"
        shape_data = mode_shapes.get(mode_key, {})
        for node in dm.nodes:
            snid = str(node['id'])
            if snid in shape_data:
                sidx = node['idx'] * 6
                Phi_full[sidx: sidx + 6, m_idx] = shape_data[snid]

        if hasattr(assembler, 'eliminated_dofs') and assembler.eliminated_dofs:
            for s_dof, terms in assembler.eliminated_dofs.items():
                Phi_full[s_dof, m_idx] = sum(Phi_full[m_dof, m_idx] * coeff for m_dof, coeff in terms.items())

    if has_restraints:
        R_modal = K_restrained_rows.dot(Phi_full)
    else:
        R_modal = np.zeros((0, n_modes))

    z_rows = [k for k, (nid, dof) in enumerate(restrained_node_dof) if dof == 2]
    print(f"DEBUG: {len(z_rows)} Z-restrained rows found")
    if z_rows:
        row0 = z_rows[0]
        print(f"DEBUG: K_restrained_rows nonzero cols for first Z row: {K_restrained_rows[row0, :].nnz}")
        print(f"DEBUG: R_modal for that Z row, modes 12-16: {R_modal[row0, 12:16]}")

    Q_global = np.zeros((n_steps, n_modes))
    V_global = np.zeros((n_steps, n_modes))
    A_global = np.zeros((n_steps, n_modes))

    R_history_raw = np.zeros((n_steps, len(restrained_node_dof)))
    R_inertia_dict = {nid: np.zeros((n_steps, 3)) for nid in restrained_node_ids}

    total_ground_v = {nid: np.zeros((n_steps, 6)) for nid in node_ids}
    total_ground_a = {nid: np.zeros((n_steps, 6)) for nid in node_ids}

    directions_str = " + ".join(d for d, _, _, _ in resolved_loads)
    progress_callback(f"[4/5] Vectorized modal superposition (directions={directions_str})...", 50)

    for direction, accel_raw, dt, scale in resolved_loads:
        if len(accel_raw) < n_steps:
            accel_padded = np.zeros(n_steps)
            accel_padded[:len(accel_raw)] = accel_raw
        else:
            accel_padded = accel_raw[:n_steps]

        accel_scaled = scale * accel_padded

        ground_v = np.zeros(n_steps)
        ground_v[1:] = np.cumsum(0.5 * (accel_scaled[:-1] + accel_scaled[1:]) * dt)

        dir_idx = 0 if direction == "X" else (1 if direction == "Y" else 2)

        for nid in node_ids:
            total_ground_v[nid][:, dir_idx] += ground_v
            total_ground_a[nid][:, dir_idx] += accel_scaled

        for nid in restrained_node_ids:
            node_idx = node_id_to_idx.get(nid)
            if node_idx is not None:
                m_val = M_diag[node_idx * 6 + dir_idx]
                inertia_force = m_val * accel_scaled
                R_inertia_dict[nid][:, dir_idx] += inertia_force

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

            if i in [12, 13, 14, 15]:
                print(f"DEBUG Mode {i+1}: ratio={ratio!r}, raw_g={raw_g!r}, Gamma={Gamma!r}")

            accel_eff = Gamma * accel_scaled
            q_n, v_n, a_n = exact_analytical_sdof(accel_eff, dt, T, zeta, m=1.0)

            Q_global[:, i] += q_n
            V_global[:, i] += v_n
            A_global[:, i] += a_n

    U_full_hist = Q_global @ Phi_full.T                                
    V_full_hist = V_global @ Phi_full.T
    A_full_hist = A_global @ Phi_full.T

    U_history = {}
    V_history = {}
    A_history = {}

    for nid in node_ids:
        n_idx = node_id_to_idx[nid] * 6
        U_history[nid] = U_full_hist[:, n_idx: n_idx + 6]
        V_history[nid] = V_full_hist[:, n_idx: n_idx + 6] + total_ground_v[nid]
        A_history[nid] = A_full_hist[:, n_idx: n_idx + 6] + total_ground_a[nid]

    R_history = {nid: np.zeros((n_steps, 6)) for nid in restrained_node_ids}
    if has_restraints:
        R_history_raw = Q_global @ R_modal.T                                    
        for k, (nid, dof) in enumerate(restrained_node_dof):
            R_history[nid][:, dof] += R_history_raw[:, k]

        for nid in restrained_node_ids:
            R_history[nid][:, :3] += R_inertia_dict[nid]

    progress_callback("[5/5] Extracting envelopes and writing results...", 80)

    import glob
    base_path = input_path.replace(".mf", "")
    search_pattern = f"{base_path}_*_matrices.json"
    found_matrices = glob.glob(search_pattern)

    matrices_data = {}
    if found_matrices:
        matrices_path = found_matrices[0]
        print(f"      Found matrices file at: {matrices_path}")
        with open(matrices_path, 'r') as f:
            matrices_data = json.load(f)
    else:
        print(f"      WARNING: No matrices file found matching {search_pattern}. Skipping element force recovery.")

    F_history = {}

    if matrices_data:
        elements_raw = dm.raw.get("elements", [])

        for el_data in elements_raw:
            eid = str(el_data.get("id"))

            if eid not in matrices_data:
                continue

            if "n1_id" in el_data and "n2_id" in el_data:
                n_i, n_j = str(el_data["n1_id"]), str(el_data["n2_id"])
            elif "node_i" in el_data and "node_j" in el_data:
                n_i, n_j = str(el_data["node_i"]), str(el_data["node_j"])
            elif "nodes" in el_data:
                n_i, n_j = str(el_data["nodes"][0]), str(el_data["nodes"][1])
            else:
                continue

            idx_i = node_id_to_idx[n_i] * 6
            idx_j = node_id_to_idx[n_j] * 6

            u_global = np.hstack((U_full_hist[:, idx_i: idx_i + 6], U_full_hist[:, idx_j: idx_j + 6]))

            k_mat = np.array(matrices_data[eid]["k"])
            t_mat = np.array(matrices_data[eid]["t"])

            kT = k_mat @ t_mat
            F_history[eid] = u_global @ kT.T

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

    forces_min, forces_max, forces_abs = _get_envelopes(F_history)

    base_reaction_history = np.zeros((n_steps, 6))

    for nid, hist in R_history.items():
        x, y, z = node_coords.get(nid, (0.0, 0.0, 0.0))
        fx, fy, fz = hist[:, 0], hist[:, 1], hist[:, 2]
        mx, my, mz = hist[:, 3], hist[:, 4], hist[:, 5]

        base_reaction_history[:, 0] += fx
        base_reaction_history[:, 1] += fy
        base_reaction_history[:, 2] += fz

        base_reaction_history[:, 3] += mx + (y * fz - z * fy)
        base_reaction_history[:, 4] += my + (z * fx - x * fz)
        base_reaction_history[:, 5] += mz + (x * fy - y * fx)

    z_forces_per_node = {nid: hist[:, 2] for nid, hist in R_history.items()}

    peak_step = np.argmax(np.abs(base_reaction_history[:, 0]))

    signed_sum = sum(arr[peak_step] for arr in z_forces_per_node.values())
    abs_sum    = sum(abs(arr[peak_step]) for arr in z_forces_per_node.values())

    print(f"DEBUG @ step {peak_step} (peak FX):")
    print(f"  Signed sum of Fz across all base nodes: {signed_sum:.4f} kN")
    print(f"  Sum of |Fz| across all base nodes:       {abs_sum:.4f} kN")
    print(f"  Individual node Fz values: {[f'{v[peak_step]:.2f}' for v in z_forces_per_node.values()]}")

    br_min = np.min(base_reaction_history, axis=0)
    br_max = np.max(base_reaction_history, axis=0)
    br_absmax = np.max(np.abs(base_reaction_history), axis=0)

    dof_keys = ["Fx", "Fy", "Fz", "Mx", "My", "Mz"]
    base_reaction_min = {k: float(v) for k, v in zip(dof_keys, br_min)}
    base_reaction_max = {k: float(v) for k, v in zip(dof_keys, br_max)}
    base_reaction_absmax = {k: float(v) for k, v in zip(dof_keys, br_absmax)}

    history_path = output_path.replace("_results.json", "_LTHA_history.npz")
    npz_payload = {"node_" + str(nid): hist for nid, hist in U_history.items()}
    npz_payload.update({"vel_node_" + str(nid): hist for nid, hist in V_history.items()})
    npz_payload.update({"acc_node_" + str(nid): hist for nid, hist in A_history.items()})
    npz_payload.update({"reac_node_" + str(nid): hist for nid, hist in R_history.items()})
    npz_payload.update({"force_elem_" + str(eid): hist for eid, hist in F_history.items()})
    npz_payload["base_reaction_history"] = base_reaction_history

    np.savez(history_path, **npz_payload)

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
            "case_name":  case_name,
            "directions": [d for d, _, _, _ in resolved_loads],
            "damping":    zeta,
            "n_modes":    n_modes,
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
        "forces_min":             forces_min,
        "forces_max":             forces_max,
        "forces_abs":             forces_abs,
        "history_path":           history_path,
        "accel_history":          accel_history_dict
    }

    with open(output_path, 'w') as f:
        json.dump(output_data, f, indent=4)

    progress_callback("LTHA Complete.", 100)
    return True

def _read_values_from_file(file_path, header_skip, accel_col):
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

def _write_error(output_path, message):
    with open(output_path, 'w') as f:
        json.dump({"status": "FAILED",
                   "error": {"title": "LTHA Error", "desc": message}}, f, indent=4)
    print(f"LTHA ERROR: {message}")
