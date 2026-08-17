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
from solver_kernel import build_imposed_displacements

from corotational_beam import ElementCorotState, NodeRotationState, compute_corotational_element
from rotation_utils import update_corotational_frame

def _snapshot_corot_state(node_rot, corot_elements):
    """
    Deep-copies the MUTABLE parts of the corotational state (node
    orientation triads + each element's rotation-minimizing frame) so a
    trial line-search step can be evaluated and then cleanly undone if
    rejected. Rotations are matrices composed multiplicatively, so a
    rejected trial can't be "subtracted off" - it has to be restored from
    a snapshot taken before the trial was applied.
    """
    node_snap = {k: v.R.copy() for k, v in node_rot.items()}
    elem_snap = {k: v.R_r.copy() for k, v in corot_elements.items()}
    return node_snap, elem_snap

def _restore_corot_state(node_rot, corot_elements, node_snap, elem_snap):
    """Undoes a rejected trial step by writing the snapshot back in place."""
    for k, R in node_snap.items():
        node_rot[k].R = R.copy()
    for k, R_r in elem_snap.items():
        corot_elements[k].R_r = R_r.copy()

def _compute_corot_residual(dm, U_full_now, node_rot, corot_elements, T, has_T, is_free_sys, is_strict_statics=False, element_fef=None):
    """
    One evaluation of the corotational internal-force / tangent-stiffness
    state at a given full displacement vector U_full_now, against the
    CURRENT node_rot / corot_elements orientation state (caller is
    responsible for making sure that state already reflects U_full_now -
    see the rotation composition step in the caller).

    Extracted out of the main loop so both the "real" per-iteration
    evaluation and speculative line-search trial evaluations can share
    the exact same force-recovery code path, instead of two copies
    drifting out of sync over time.

    element_fef: optional {element_id_str: np.array(12)} of fixed-end-force
    vectors (member distributed/trapezoidal/self-weight/point loads and
    point moments applied along the span), exactly as recorded by
    GlobalAssembler/MatrixSpy into the *_matrices.json export. Without
    this, compute_corotational_element() only sees nodal-displacement-
    induced internal force and silently drops every member load that
    isn't applied directly at a node.

    NOTE: calling this mutates corot_elements[*].R_r in place (each
    compute_corotational_element() call updates its element's
    rotation-minimizing frame as a side effect) - callers doing a
    speculative trial MUST snapshot/restore around this call.
    """
    F_int_full = np.zeros(dm.total_dofs)
    kg_row, kg_col, kg_data = [], [], []

    for el in dm.elements:
        eid_str = str(el['id'])
        state = corot_elements.get(eid_str)
        if state is None:
            continue
        idx_i, idx_j = el['node_indices']

        p1_current = dm.nodes[idx_i]['coords'] + U_full_now[idx_i*6: idx_i*6+3]
        p2_current = dm.nodes[idx_j]['coords'] + U_full_now[idx_j*6: idx_j*6+3]

        fef_local = element_fef.get(eid_str) if element_fef else None

        f_g, K_g, N_axial = compute_corotational_element(
            state, p1_current, p2_current,
            node_rot[idx_i], node_rot[idx_j],
            is_strict_statics, fef_local
        )

        dof_map = ([idx_i*6+k for k in range(6)] +
                   [idx_j*6+k for k in range(6)])
        for a in range(12):
            F_int_full[dof_map[a]] += f_g[a]
            for b in range(12):
                val = K_g[a, b]
                if val != 0.0:
                    kg_row.append(dof_map[a])
                    kg_col.append(dof_map[b])
                    kg_data.append(val)

    from scipy.sparse import coo_matrix
    K_full_ld = coo_matrix((kg_data, (kg_row, kg_col)),
                            shape=(dm.total_dofs, dm.total_dofs)).tocsc()

    if has_T:
        K_sys_ld = T.T @ K_full_ld @ T
        F_int_sys = T.T @ F_int_full
    else:
        K_sys_ld = K_full_ld
        F_int_sys = F_int_full

    K_total_free = K_sys_ld.tocsc()[is_free_sys, :][:, is_free_sys]
    F_int_free = F_int_sys[is_free_sys]

    return F_int_full, F_int_free, K_total_free

def _fd_consistent_tangent(dm, U_free, F_int_free_base, node_rot, corot_elements,
                            T, has_T, is_free_sys, K_E_sys, eps=1e-6, is_strict_statics=False, element_fef=None):
    """
    Builds the TRUE consistent tangent stiffness by CENTRAL finite
    differences, rather than the analytical approximation (K_approx,
    which is missing the corotational "spin" term - see
    corotational_beam.py docstring).

    Central differences (f(x+eps) - f(x-eps)) / (2*eps) rather than
    forward differences ((f(x+eps) - f(x)) / eps): this halves the
    truncation error order (O(eps^2) instead of O(eps)) and, more
    importantly, removes a systematic bias that a forward-difference
    tangent carries relative to the exact tangent at the CURRENT state -
    that bias is the most likely explanation for why an earlier
    forward-difference version of this function converged some load
    steps to 1e-8 cleanly but plateaued inconsistently on others.

    For each free DOF, perturb it by +-eps (composing the perturbation
    onto the rotation state the SAME way the real solver does, via
    NodeRotationState.update - not just adding to a flat vector, since
    rotations are non-additive), recompute the true internal force via
    the exact same _compute_corot_residual used everywhere else, and
    take the central-difference column. Costs 2*num_free_dofs extra full
    residual evaluations per Newton iteration - fine for verifying on a
    small test model, not meant for production use on large meshes.
    """
    num_free = U_free.shape[0]
    node_snap, elem_snap = _snapshot_corot_state(node_rot, corot_elements)

    cols = np.zeros((num_free, num_free))

    def _perturbed_force(dU_free_pert):
        dU_sys = np.zeros(K_E_sys.shape[0])
        dU_sys[is_free_sys] = dU_free_pert
        dU_full = T @ dU_sys if has_T else dU_sys

        for node in dm.nodes:
            n_idx = node['idx']
            d_theta = dU_full[n_idx*6+3: n_idx*6+6]
            if np.any(d_theta):
                node_rot[n_idx].update(d_theta)

        U_free_pert = U_free + dU_free_pert
        U_sys_pert = np.zeros(K_E_sys.shape[0])
        U_sys_pert[is_free_sys] = U_free_pert
        U_full_pert = T @ U_sys_pert if has_T else U_sys_pert

        _, F_int_free_pert, _ = _compute_corot_residual(
            dm, U_full_pert, node_rot, corot_elements, T, has_T, is_free_sys, is_strict_statics, element_fef
        )
        return F_int_free_pert

    for j in range(num_free):
        dplus = np.zeros(num_free); dplus[j] = eps
        dminus = np.zeros(num_free); dminus[j] = -eps

        node_snap_j, elem_snap_j = _snapshot_corot_state(node_rot, corot_elements)
        F_plus = _perturbed_force(dplus)
        _restore_corot_state(node_rot, corot_elements, node_snap_j, elem_snap_j)

        node_snap_j, elem_snap_j = _snapshot_corot_state(node_rot, corot_elements)
        F_minus = _perturbed_force(dminus)
        _restore_corot_state(node_rot, corot_elements, node_snap_j, elem_snap_j)

        cols[:, j] = (F_plus - F_minus) / (2 * eps)

    _restore_corot_state(node_rot, corot_elements, node_snap, elem_snap)

    from scipy.sparse import csc_matrix
    return csc_matrix(cols)

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
        corot_type = nl_params.get("corot_type", "Commercial Compatibility")
        is_strict_statics = (corot_type == "Strict Global Equilibrium (Native)")

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

        element_fef = {
            eid: np.array(mats['fef'])
            for eid, mats in element_matrices.items()
            if mats.get('fef') is not None
        }

        geom_nonlin_for_reproj = case_data.get("geom_nonlin", "None")
        large_disp_for_reproj = (geom_nonlin_for_reproj == "Large Displacements")

        active_patterns_dict = {pat: sc for pat, sc in dm.load_case['patterns']}
        global_coord_member_loads = []
        if large_disp_for_reproj:
            for load in dm.raw.get('loads', []):
                if load.get('pattern') not in active_patterns_dict: continue
                if load.get('type') not in ('member_dist', 'member_point'): continue
                if str(load.get('coord', 'Global')).upper() != 'GLOBAL': continue
                global_coord_member_loads.append((load, active_patterns_dict[load['pattern']]))

        P_global_baseline_full = np.zeros(dm.total_dofs)
                                                                         
        element_fef_global_baseline_local = {}
        if global_coord_member_loads:
            print(f"      [Large Displacements] {len(global_coord_member_loads)} coord='Global' "
                  f"member load(s) will be re-projected onto the current corotational frame "
                  f"each iteration instead of held fixed at the undeformed orientation.")
            for load, scale in global_coord_member_loads:
                result = assembler.compute_single_member_load_fef_global(load, scale)
                if result is None:
                    continue
                fef_global, fef_local, idx_i, idx_j = result
                P_global_baseline_full[idx_i*6: idx_i*6+6] -= fef_global[0:6]
                P_global_baseline_full[idx_j*6: idx_j*6+6] -= fef_global[6:12]
                eid_str = str(load['element_id'])
                element_fef_global_baseline_local[eid_str] = (
                    element_fef_global_baseline_local.get(eid_str, np.zeros(12)) + fef_local
                )

        P_static_full = P_total_full - P_global_baseline_full

        def _compute_dynamic_global_load_full():
            """
            Re-evaluates the coord='Global' member loads' equivalent-nodal-
            load contribution using each element's CURRENT corotational
            frame (corot_elements[eid].R_r), via the SAME validated FEF
            math as the static assembler. Must be called AFTER corot_
            elements[*].R_r has been updated to reflect the state being
            evaluated (compute_corotational_element/_compute_corot_residual
            already does this as a side effect).

            corot_elements[eid].R_r is stored LOCAL->GLOBAL (columns = local
            axes in global coords - see corotational_beam.py). The
            assembler's R_3x3 convention is GLOBAL->LOCAL (v_local =
            R_3x3 @ v_global). Hence the transpose below.
            """
            P_dyn_full = np.zeros(dm.total_dofs)
            for load, scale in global_coord_member_loads:
                eid_str = str(load['element_id'])
                state = corot_elements.get(eid_str)
                if state is None:
                    continue
                R_current_global_to_local = state.R_r.T
                result = assembler.compute_single_member_load_fef_global(
                    load, scale, R_3x3_override=R_current_global_to_local
                )
                if result is None:
                    continue
                fef_global, fef_local, idx_i, idx_j = result
                P_dyn_full[idx_i*6: idx_i*6+6] -= fef_global[0:6]
                P_dyn_full[idx_j*6: idx_j*6+6] -= fef_global[6:12]
            return P_dyn_full

        element_fef_static_local_only = dict(element_fef)
        for eid_str, fef_glob_local in element_fef_global_baseline_local.items():
            base = element_fef_static_local_only.get(eid_str, np.zeros(12))
            element_fef_static_local_only[eid_str] = base - fef_glob_local

        def _compute_dynamic_element_fef():
            """
            Per-element LOCAL-axis fef_local dict for compute_corotational_
            element()'s N_axial (-> k_geo geometric-stiffness) calculation,
            with the coord='Global' loads' contribution re-integrated from
            each element's corot_elements[eid].R_r AS IT CURRENTLY STANDS
            (i.e. left over from the previous iteration's
            compute_corotational_element call, since that call is what's
            about to consume the dict this function builds -- one Newton
            iteration of staleness, unavoidable without predicting R_r
            before computing it).

            This existed as a real gap even after P_target_free started
            being reprojected: f_local (the value that actually drives the
            residual/reactions) never includes fef_local by construction
            (see corotational_beam.py's double-counting-fix comment) --
            but fef_local still feeds N_axial, which builds k_geo, i.e.
            the TANGENT stiffness. A coord='Global' load like self-weight
            (pure Global -Z) couples strongly into the member's axial
            direction once it rotates far enough toward horizontal, so a
            STALE (undeformed-orientation) fef_local here measurably biases
            k_geo and can stall Newton convergence -- confirmed as the
            cause of the ~2-5% gap that showed up only once self-weight
            was added at large rotation, even though the assembled load
            (P_target_free) was already being correctly reprojected.

            One iteration of staleness here would be a standard modified-
            Newton approximation (only shapes the tangent used to GET to
            equilibrium, not the equilibrium condition itself) -- but it's
            avoidable and measurably mattered here (self-weight is pure
            Global -Z, a case where the staleness turned out not to be
            negligible), so callers should run _sync_corot_frames(U_full)
            first each iteration to eliminate it: that updates R_r from
            geometry alone (which is all update_corotational_frame ever
            depends on -- see corotational_beam.py), before this function
            reprojects fef_local against it, so what this function reads
            is the SAME R_r the subsequent compute_corotational_element
            call will independently re-derive from that same geometry --
            zero lag, not one iteration behind.
            """
            eff = dict(element_fef_static_local_only)
            for load, scale in global_coord_member_loads:
                eid_str = str(load['element_id'])
                state = corot_elements.get(eid_str)
                if state is None:
                    continue
                R_current_global_to_local = state.R_r.T
                result = assembler.compute_single_member_load_fef_global(
                    load, scale, R_3x3_override=R_current_global_to_local
                )
                if result is None:
                    continue
                _, fef_local, idx_i, idx_j = result
                eff[eid_str] = eff.get(eid_str, np.zeros(12)) + fef_local
            return eff

        def _sync_corot_frames(U_full_now):
            """
            Advances each element's corot_elements[eid].R_r to match the
            chord geometry implied by U_full_now, WITHOUT doing the full
            local-stiffness / internal-force recovery that
            compute_corotational_element does. This is exactly that
            function's own R_r update (see corotational_beam.py's
            `state.R_r = update_corotational_frame(state.R_r, e1_new)`),
            pulled out standalone -- R_r's update depends only on the
            element's current p1/p2 positions, never on fef_local, so it's
            safe to run this BEFORE reprojecting fef_local instead of
            chasing R_r one iteration behind it.

            Calling compute_corotational_element afterwards on the SAME
            U_full_now re-derives an identical R_r (update_corotational_
            frame from an already-aligned frame is a no-op rotation), so
            this is not a second, competing source of truth -- it just
            gives fef reprojection early access to what that call would
            have produced anyway.
            """
            for el in dm.elements:
                eid_str = str(el['id'])
                state = corot_elements.get(eid_str)
                if state is None:
                    continue
                idx_i, idx_j = el['node_indices']
                p1_current = dm.nodes[idx_i]['coords'] + U_full_now[idx_i*6: idx_i*6+3]
                p2_current = dm.nodes[idx_j]['coords'] + U_full_now[idx_j*6: idx_j*6+3]
                chord = p2_current - p1_current
                L_n = np.linalg.norm(chord)
                if L_n < 1e-12:
                    continue
                state.R_r = update_corotational_frame(state.R_r, chord / L_n)

        print("[3/5] Applying Boundary Conditions...")
        is_free_full = np.ones(dm.total_dofs, dtype=bool)
        for node in dm.nodes:
            start_idx = node['idx'] * 6
            restraints = node['restraints']                           
            for i in range(6):
                if restraints[i] or not dm.active_dofs[i]:           
                    is_free_full[start_idx + i] = False

        print("      Checking for Imposed Joint (Ground) Displacements...")
        U_imp_full, has_imposed = build_imposed_displacements(dm, is_free_full)

        has_T = hasattr(assembler, 'T') and assembler.T is not None
        T = None                                                               
                                                                            
        if has_T:
            T = assembler.T
            kept_dofs = assembler.kept_dofs

            eliminated_set = set(range(dm.total_dofs)) - set(kept_dofs)
            bad = sorted(d for d in eliminated_set if not is_free_full[d])
            if bad:
                raise SolverException(
                    "E205",
                    f"Restraint found on diaphragm-slaved DOF index(es) {bad}. "
                    f"Restrain the diaphragm MASTER node instead."
                )

            K_E_sys = T.T @ K_E_full @ T
            P_total_sys = T.T @ P_total_full
            P_static_sys = T.T @ P_static_full
            is_free_sys = is_free_full[kept_dofs]
            U_imp_sys = U_imp_full[kept_dofs]
        else:
            K_E_sys = K_E_full
            P_total_sys = P_total_full
            P_static_sys = P_static_full
            is_free_sys = is_free_full
            U_imp_sys = U_imp_full

        K_E_free = K_E_sys.tocsc()[is_free_sys, :][:, is_free_sys]
        P_total_free = P_total_sys[is_free_sys]
                                                                    
        P_static_free = P_static_sys[is_free_sys]

        num_free_dofs = K_E_free.shape[0]
        if num_free_dofs == 0:
            raise SolverException("E301", "Structure is fully constrained. No free DOFs.")

        if has_imposed:
            n_imp = int(np.sum(np.abs(U_imp_sys) > 1e-12))
            print(f"      {n_imp} restrained DOF(s) carry an imposed joint displacement; "
                  f"ramping alongside the {max_total_steps} load steps.")

        large_disp = (geom_nonlin == "Large Displacements")
        corot_elements = {}                                     
        node_rot = {}                                              

        if large_disp:
            print("      [Large Displacements] Building corotational element/node state...")
            for node in dm.nodes:
                node_rot[node['idx']] = NodeRotationState()

            for el in dm.elements:
                idx_i, idx_j = el['node_indices']
                p1_0 = dm.nodes[idx_i]['coords'] + np.array(el['offsets'][0])
                p2_0 = dm.nodes[idx_j]['coords'] + np.array(el['offsets'][1])
                                                                                       
                # L_clear/L_total come straight from data_manager (same keys
                # assembler.py already reads for the linear/P-Delta path) so
                # the Large Displacements element uses the SAME flexible
                # span / torsional length as everywhere else, instead of
                # silently treating the whole offset-adjusted chord as
                # flexible.
                corot_elements[str(el['id'])] = ElementCorotState(
                    p1_0, p2_0, el.get('beta', 0.0), el['section'], el['material'],
                    L_clear=el['L_clear'], L_tor=el['L_total']
                )

        print("[4/5] Entering Nonlinear Load Stepping Loop...")
        progress_callback("Starting Incremental Load Analysis...", 20)

        U_free = np.zeros(num_free_dofs)                                       
        F_int_full_ld_last = None                                                                           

        dU_imp_sys = U_imp_sys / max_total_steps

        def _compute_reprojected_target_free(step_frac):
            """
            Builds the external-load target for the CURRENT Newton
            iteration's residual, at load-step fraction step_frac
            (= step / max_total_steps, standard proportional loading).

            For the static portion (direct nodal loads + coord='Local'
            member loads) this is just step_frac * P_static_free, exactly
            like the old fixed dP_ext_free * step scheme.

            For coord='Global' member loads under Large Displacements,
            the equivalent nodal load is instead RE-INTEGRATED here, every
            call, from each element's corot_elements[*].R_r as it stands
            right now -- so calling this after compute_corotational_element
            has updated R_r for the current displacement iterate gives the
            load re-projected onto the member's actual current orientation,
            not the undeformed one. Falls back to the plain static ramp
            when there's nothing to reproject (non-Large-Displacements
            cases, or Large Displacements with no coord='Global' member
            loads) -- zero behavior change for those.
            """
            if not (large_disp and global_coord_member_loads):
                return step_frac * P_total_free

            P_dyn_full = _compute_dynamic_global_load_full()
            P_dyn_sys = T.T @ P_dyn_full if has_T else P_dyn_full
            P_dyn_free = P_dyn_sys[is_free_sys]
            return step_frac * (P_static_free + P_dyn_free)

        for step in range(1, max_total_steps + 1):
            print(f"   -> Step {step}/{max_total_steps}")
            progress_callback(f"Solving Step {step} of {max_total_steps}...", 20 + int(70 * (step / max_total_steps)))

            step_frac = step / max_total_steps
            U_imp_target_sys = dU_imp_sys * step

            K_total_free = K_E_free.copy()
            K_total_sys = K_E_sys.tocsc()

            if large_disp and has_imposed:
                                                                              
                dU_imp_full_this_step = T @ dU_imp_sys if has_T else dU_imp_sys
                for node in dm.nodes:
                    n_idx = node['idx']
                    d_theta_imp = dU_imp_full_this_step[n_idx*6+3: n_idx*6+6]
                    if np.any(np.abs(d_theta_imp) > 1e-14):
                        node_rot[n_idx].update(d_theta_imp)

            for iter_count in range(1, max_nr_iter + 1):

                if large_disp:
                    U_sys_now = U_imp_target_sys.copy()
                    U_sys_now[is_free_sys] = U_free
                    U_full_now = T @ U_sys_now if has_T else U_sys_now

                    if global_coord_member_loads:
                                                                           
                        _sync_corot_frames(U_full_now)
                        element_fef_this_iter = _compute_dynamic_element_fef()
                    else:
                        element_fef_this_iter = element_fef

                    F_int_full, F_int_free, K_total_free = _compute_corot_residual(
                    dm, U_full_now, node_rot, corot_elements, T, has_T, is_free_sys, is_strict_statics, element_fef_this_iter
                    )
                    F_int_full_ld_last = F_int_full                                             

                    if nl_params.get("use_fd_tangent", False):
                        K_total_free = _fd_consistent_tangent(
                            dm, U_free, F_int_free, node_rot, corot_elements,
                            T, has_T, is_free_sys, K_E_sys, is_strict_statics=is_strict_statics, element_fef=element_fef_this_iter
                        )

                else:
                                                                                      
                    U_sys_now = U_imp_target_sys.copy()
                    U_sys_now[is_free_sys] = U_free
                    F_int_free = K_total_sys.dot(U_sys_now)[is_free_sys]

                P_target_free = _compute_reprojected_target_free(step_frac)
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
                
                if large_disp and nl_params.get("use_line_search", False):
                                                      
                    node_snap, elem_snap = _snapshot_corot_state(node_rot, corot_elements)

                    def _apply_trial(alpha_try):
                        """Composes alpha_try*dU_free onto the (already-restored,
                        pristine) rotation state and returns the resulting residual
                        norm. Leaves node_rot/corot_elements mutated at this alpha -
                        caller must restore before trying a different alpha."""
                        dU_sys_trial = np.zeros(K_E_sys.shape[0])
                        dU_sys_trial[is_free_sys] = alpha_try * dU_free
                        dU_full_trial = T @ dU_sys_trial if has_T else dU_sys_trial
                        for node in dm.nodes:
                            n_idx = node['idx']
                            node_rot[n_idx].update(dU_full_trial[n_idx*6+3: n_idx*6+6])

                        U_free_trial = U_free + alpha_try * dU_free
                        U_sys_trial = U_imp_target_sys.copy()
                        U_sys_trial[is_free_sys] = U_free_trial
                        U_full_trial = T @ U_sys_trial if has_T else U_sys_trial

                        _, F_int_free_trial, _ = _compute_corot_residual(
                        dm, U_full_trial, node_rot, corot_elements, T, has_T, is_free_sys, is_strict_statics, element_fef_this_iter
                        )
                                                                             
                        P_target_free_trial = _compute_reprojected_target_free(step_frac)
                        return np.linalg.norm(P_target_free_trial - F_int_free_trial)

                    alpha = 1.0
                    accepted = False
                    for _ls_try in range(10):
                        trial_norm = _apply_trial(alpha)
                        if step == 1:
                            print(f"      [dbg-ls] step 1 iter {iter_count} try {_ls_try}: "
                                  f"alpha={alpha:.4f} trial_norm={trial_norm:.4E} "
                                  f"(pre-step residual={residual_norm:.4E})")
                        if trial_norm < residual_norm:
                            accepted = True
                            break
                        _restore_corot_state(node_rot, corot_elements, node_snap, elem_snap)
                        alpha *= 0.5

                    if not accepted:
                                                                                      
                        _apply_trial(alpha)

                    U_free = U_free + alpha * dU_free
                    continue

                U_free += dU_free

                if large_disp:
                                                                                  
                    dU_sys = np.zeros(K_E_sys.shape[0])
                    dU_sys[is_free_sys] = dU_free
                    dU_full = T @ dU_sys if has_T else dU_sys
                    for node in dm.nodes:
                        n_idx = node['idx']
                        d_theta = dU_full[n_idx*6+3: n_idx*6+6]
                        node_rot[n_idx].update(d_theta)
                                                                                       
                    continue

                if geom_nonlin in ["P-Delta", "Large Displacements"]:
                    
                    U_sys = U_imp_target_sys.copy()
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
                        
                        # Match assembler.py's beta_eff = beta - degrees(theta_p) so the
                        # P-Delta geometric-stiffness local axes line up with the elastic
                        # local axes used to build K_E_full for this same element.
                        beta_eff = el.get('beta', 0.0) - np.degrees(sec.get('theta_p', 0.0))
                        R_3x3 = get_rotation_matrix(p1 + global_off_i, p2 + global_off_j, beta_eff)
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
                        
                    K_total_sys = (K_E_sys + KG_sys).tocsc()
                    K_total_free = K_total_sys[is_free_sys, :][:, is_free_sys]

            else:
                                                                              
                print(f"      WARNING: Step {step} failed to converge after {max_nr_iter} iterations!")
                                                                                             
        print("[5/5] Nonlinear Analysis Complete.")
        
        print("      Extracting Final Displacements and Reactions...")
        progress_callback("Formatting results...", 90)

        U_sys = U_imp_target_sys.copy()
        U_sys[is_free_sys] = U_free
        U_full = T @ U_sys if has_T else U_sys

        if large_disp and F_int_full_ld_last is not None:
                                                                   
            if global_coord_member_loads:
                P_dyn_full_final = _compute_dynamic_global_load_full()
                P_target_full_final = P_static_full + P_dyn_full_final
            else:
                P_target_full_final = P_total_full
            Reactions_full = F_int_full_ld_last - P_target_full_final
        else:
                                                       
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
        run_nonlinear_analysis(test_in, test_out, "Large_deflection")
    else:
        print(f"Test file not found: {test_in}")
        print("Create a simple cantilever .mf with a Nonlinear Static case")
        print("(Large Displacements enabled, nodal load only) and place it here.")