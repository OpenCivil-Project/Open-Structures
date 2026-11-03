"""
OpenCivil / MetuFire Nonlinear Solver Extensions
=================================================

Two additive capabilities, designed to slot into the EXISTING
Newton-Raphson loop in nonlinear_engine.py without touching its
corotational math, residual assembly, or line-search logic:

    1. LOAD CASE CHAINING       (state continuity: Case B starts where
                                  Case A ended)
    2. DISPLACEMENT CONTROL     (Batoz & Dhatt 1979 partitioning, for
                                  snap-through / limit-point tracing)

No material LAWS live in here (no plastic hinges, fiber sections or
hysteresis rules). Both features work through the elastic tangent +
geometric stiffness (P-Delta / Large Displacements) machinery your
engine already has. Load case chaining ALSO carries the committed
MATERIAL state of fiber hinges (snapped-fiber masks now, per-fiber
hysteresis history later) from the end of one case to the start of the
next -- see PERSISTENT_HINGE_KEYS / capture_hinge_state /
apply_hinge_state below. The module only moves that state around; it
never interprets it.

INTEGRATION POINTS (line numbers refer to your current nonlinear_engine.py):
    - Replace line ~519   `U_free = np.zeros(num_free_dofs)`
    - Wrap step-loop top  `for step in range(1, max_total_steps+1):` (~615)
    - Replace the residual/solve block at lines ~669-685:
          P_target_free = _compute_reprojected_target_free(step_frac)
          R_free = P_target_free - F_int_free
          dU_free = spsolve(K_total_free, R_free)
    - The lagged-K_g rebuild block at lines ~763-862 (P-Delta path only)

Everything below is written against the exact objects your loop already
carries: dm, node_rot, corot_elements, K_E_full/sys/free, is_free_sys,
kept_dofs, T, has_T, element_matrices (the parsed *_matrices.json).
"""

import copy
import numpy as np
from dataclasses import dataclass, field
from typing import Any, Dict, Optional
from scipy.sparse import coo_matrix
from scipy.sparse.linalg import spsolve

from error_definitions import SolverException

PERSISTENT_HINGE_KEYS = ('failed', 'mat_state')

def _copy_state_value(v):
    if isinstance(v, np.ndarray):
        return v.copy()
    return copy.deepcopy(v)

def capture_hinge_state(hinge_elements) -> Dict[str, Dict[str, Any]]:
    """
    {eid_str: {key: copy_of_value}} for every hinge that currently holds
    committed material history. Hinges with none (never snapped, never
    loaded) are simply absent, which is identical to "fresh" on apply.
    Always returns COPIES, so later mutation of the live hinge dicts cannot
    change a captured state.
    """
    out: Dict[str, Dict[str, Any]] = {}
    for eid, hd in (hinge_elements or {}).items():
        entry = {k: _copy_state_value(hd[k])
                 for k in PERSISTENT_HINGE_KEYS if hd.get(k) is not None}
        if entry:
            out[str(eid)] = entry
    return out

def apply_hinge_state(hinge_elements, hinge_state, case_name="") -> int:
    """
    Seeds this case's (freshly built) hinge dicts from a captured state.
    Returns the number of hinges seeded.

    Fails loudly instead of silently dropping history: a chained case that
    quietly restarts a hinge from virgin material would produce plausible
    but wrong results, which is worse than an error.
    """
    n_seeded = 0
    hinge_elements = hinge_elements or {}
    for eid, entry in (hinge_state or {}).items():
        hd = hinge_elements.get(eid)
        if hd is None:
            raise SolverException(
                "E104",
                f"Load Case Chaining: '{case_name}' ended with material state on the "
                f"fiber hinge of element {eid}, but this case has no hinge on that "
                f"element. Chained cases must share the same hinge assignments.")
        n_fib = getattr(hd.get('fiber_section'), 'n_fibers', None)
        for k, v in entry.items():
            if k not in PERSISTENT_HINGE_KEYS:
                continue
            if k == 'failed' and n_fib is not None and np.shape(v) != (n_fib,):
                raise SolverException(
                    "E104",
                    f"Load Case Chaining: the snapped-fiber mask carried from '{case_name}' "
                    f"for element {eid} has shape {np.shape(v)}, but its hinge now has "
                    f"{n_fib} fibers. The hinge property changed between the chained cases.")
            if (k == 'mat_state' and n_fib is not None and isinstance(v, dict)
                    and np.shape(v.get('eps_c')) != (n_fib,)):
                raise SolverException(
                    "E104",
                    f"Load Case Chaining: the hysteresis state carried from '{case_name}' "
                    f"for element {eid} is for {np.shape(v.get('eps_c'))} fibers, but its hinge now "
                    f"has {n_fib} fibers. The hinge property changed between the chained cases.")
            hd[k] = _copy_state_value(v)
        hd.pop('_memo', None)                                                                        
        n_seeded += 1
    return n_seeded

@dataclass
class CaseEndState:
    """
    Everything needed to make Load Case B start exactly where Load Case
    A left off. Built directly from the live objects your loop already
    holds -- no JSON round-trip required if both cases run in the same
    process. Every field IS JSON-safe (ndarrays -> .tolist()) if you do
    want to persist it between separate solver invocations.

    U_sys is deliberately stored in REDUCED (post-diaphragm-elimination)
    numbering -- the same vector your own code builds at line ~1094
    (`U_sys = U_imp_target_sys.copy(); U_sys[is_free_sys] = U_free`) --
    rather than reconstructed by inverting T from U_full. T maps
    reduced -> full; it is not (in general) invertible by indexing, so
    capturing U_sys directly avoids that trap entirely.
    """
    U_sys: np.ndarray                                                             
    node_rot_R: Dict[int, np.ndarray]                                              
    corot_Rr: Dict[str, np.ndarray]                                                 
    axial_force: Dict[str, float]                                                
    P_final_full: np.ndarray                                                       
                                                                                    
    case_name: str
    converged: bool
    formulation: str = "Corotational"                                             
                                                                     
    hinge_state: Dict[str, Dict[str, Any]] = field(default_factory=dict)

def capture_case_end_state(dm, U_sys, node_rot, corot_elements, U_full,
                            element_matrices, P_final_full, case_name="", converged=True,
                            formulation="Corotational") -> CaseEndState:
    """
    Call this ONCE, right where nonlinear_engine.py currently builds
    `results_dict` for the writer (around line 1094-1117), i.e. after
    `U_sys` and `U_full` for the final step are already assembled.

    Axial force is recovered exactly the way element_forces.py already
    does it: k_local @ (t @ u_global) + fef. No new solver bookkeeping
    needed -- element_matrices is the same dict already loaded from
    `*_matrices.json` right after assembling.

    formulation is recorded (not acted on here) so a LATER case trying
    to continue from this one can check what it's actually inheriting --
    only ElementCorotState's .R_r has been verified as the complete
    per-element persistent state; ElementULState (Updated Lagrangian,
    ul_element.py) was never inspected, so .R_r is read defensively via
    getattr below (never assumed present) and nonlinear_engine.py is
    responsible for refusing to CONSUME a "Updated Lagrangian" state
    under Large Displacements until that's been reviewed -- this
    function only avoids crashing on capture, it does not certify the
    capture is complete for that formulation.
    """
    Rr_map, N_map = {}, {}
    for el in dm.elements:
        eid = str(el['id'])

        st = corot_elements.get(eid)
        Rr = getattr(st, 'R_r', None) if st is not None else None
        if Rr is not None:
            Rr_map[eid] = Rr.copy()

        if eid in element_matrices:
            k = np.array(element_matrices[eid]['k'])
            t = np.array(element_matrices[eid]['t'])
            fef = np.array(element_matrices[eid]['fef'])
            idx_i, idx_j = el['node_indices']
            u_glob = np.concatenate([U_full[idx_i * 6: idx_i * 6 + 6],
                                      U_full[idx_j * 6: idx_j * 6 + 6]])
            f_local = k @ (t @ u_glob) + fef
            N_map[eid] = 0.5 * (f_local[6] - f_local[0])

    node_R_map = {idx: st.R.copy() for idx, st in node_rot.items()}

    return CaseEndState(
        U_sys=U_sys.copy(),
        node_rot_R=node_R_map,
        corot_Rr=Rr_map,
        axial_force=N_map,
        P_final_full=P_final_full.copy(),
        case_name=case_name,
        converged=converged,
        formulation=formulation,
        hinge_state=capture_hinge_state(getattr(dm, 'hinge_elements', None)),
    )

def apply_initial_state(node_rot, corot_elements, is_free_sys, prior: CaseEndState,
                        hinge_elements=None):
    """
    Seeds Case B's mutable solver state from Case A's CaseEndState.
    Call this right after node_rot/corot_elements are built (after your
    existing lines ~495-508) and use its return value in place of the
    `U_free = np.zeros(num_free_dofs)` line.

    Assumes Case A and Case B share the same mesh/DOF numbering (always
    true for two load cases on the same structure). Does NOT assume the
    same restraint pattern -- U_sys's restrained slots are simply carried
    over; a restraint added only in Case B is still handled correctly by
    Case B's own boundary-condition partition (is_free_sys), since we
    only read out the entries that are free THIS case.

    hinge_elements : this case's dm.hinge_elements (pass it whenever the
    model can have fiber hinges). Seeds each hinge's committed material
    state (PERSISTENT_HINGE_KEYS) from prior.hinge_state. If the prior case
    ended with hinge state and no hinge_elements are supplied this raises,
    because carrying the geometry but dropping the material history is
    exactly the silent inconsistency chaining must never produce.
    """
    for idx, R in prior.node_rot_R.items():
        if idx in node_rot:
            node_rot[idx].R = R.copy()

    for eid, Rr in prior.corot_Rr.items():
        if eid in corot_elements:
            corot_elements[eid].R_r = Rr.copy()

    prior_hinge_state = getattr(prior, 'hinge_state', None)
    if prior_hinge_state:
        if hinge_elements is None:
            raise SolverException(
                "E104",
                f"Load Case Chaining: '{prior.case_name}' ended with fiber-hinge material "
                f"state, but apply_initial_state() was not given this case's hinge_elements, "
                f"so that state would be silently dropped.")
        apply_hinge_state(hinge_elements, prior_hinge_state, prior.case_name)

    U_free_0 = prior.U_sys[is_free_sys]
    return U_free_0

def build_geometric_stiffness_full(dm, element_matrices, axial_force_map,
                                    has_T=False, T=None):
    """
    Standalone factoring-out of the P-Delta K_g assembly your engine
    already does inline at lines ~769-862, parameterized so N_axial can
    come from ANY source -- not just "recompute from this step's u",
    which is all the inline version currently supports. This lets the
    SAME function:

      (a) seed Case B's step-1 tangent from Case A's final forces
          (axial_force_map = prior.axial_force), and
      (b) still serve your existing per-step P-Delta update unchanged
          (axial_force_map computed fresh each step as before).

    Math (releases condensation, eccentricity, rigid-zone moment
    correction) is copied verbatim from your existing block -- only the
    source of N_axial has been made a parameter. NOTE: this is the
    lagged-tangent (P-Delta) path only. For "Large Displacements"
    (corotational), N_axial is recomputed fresh every iteration inside
    compute_corotational_element itself, so no separate seeding is
    needed there beyond apply_initial_state() above.

    Returns (KG_full, kg_local_map). KG_full is the assembled global (or
    T-reduced) sparse matrix, exactly as before. kg_local_map[eid] is the
    SAME per-element geometric stiffness after release condensation but
    BEFORE the eccentricity/rotation transform -- i.e. in the identical
    basis as the element's own stored elastic "k" in *_matrices.json
    (assembler.py builds k_global = T_total.T @ k_local @ T_total in one
    step, with eccentricity folded into T_total rather than into k_local
    itself -- see assembler.py's per-element loop). Because
    T_rot.T @ (T_ecc.T @ kg_local @ T_ecc) @ T_rot is algebraically
    identical to (T_ecc @ T_rot).T @ kg_local @ (T_ecc @ T_rot) =
    T_total.T @ kg_local @ T_total, this kg_local_map value is exactly
    what's addable to element_matrices[eid]['k'] to get the TRUE local
    end-force vector consistent with the stored 't': (k_local + kg_local)
    @ (t @ u_global) + fef. This is what nonlinear_engine.py's final
    force-diagram export uses -- see the "Element Force Diagram fix"
    block near the end of run_nonlinear_analysis.
    """
    from element_library import get_geometric_stiffness_matrix, get_rotation_matrix, get_eccentricity_matrix

    kg_row, kg_col, kg_data = [], [], []
    kg_local_map = {}

    for el in dm.elements:
        eid_str = str(el['id'])
        if eid_str not in element_matrices or eid_str not in axial_force_map:
            continue
        N_axial = axial_force_map[eid_str]

        sec, mat = el['section'], el['material']
        L_geom = el['L_clear']
        phi_y = (12 * mat['E'] * sec['I33']) / (mat['G'] * sec['As2'] * L_geom ** 2) if sec['As2'] > 0 else 0.0
        phi_z = (12 * mat['E'] * sec['I22']) / (mat['G'] * sec['As3'] * L_geom ** 2) if sec['As3'] > 0 else 0.0

        kg_local = get_geometric_stiffness_matrix(
            -N_axial, L_geom, phi_y=phi_y, phi_z=phi_z,
            A=sec['A'], I22=sec['I22'], I33=sec['I33']
        )

        k_local = np.array(element_matrices[eid_str]['k'])
        rel_vec = el.get('releases', [[False] * 6, [False] * 6])[0] +\
                  el.get('releases', [[False] * 6, [False] * 6])[1]
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

        kg_local_map[eid_str] = kg_local.copy()

        idx_i, idx_j = el['node_indices']
        p1, p2 = dm.nodes[idx_i]['coords'], dm.nodes[idx_j]['coords']
        off_i, off_j = np.array(el['offsets'][0]), np.array(el['offsets'][1])
        beta_eff = el.get('beta', 0.0) - np.degrees(sec.get('theta_p', 0.0))
        R_3x3 = get_rotation_matrix(p1 + off_i, p2 + off_j, beta_eff)
        T_rot = np.zeros((12, 12))
        for i in range(4):
            T_rot[i * 3:(i + 1) * 3, i * 3:(i + 1) * 3] = R_3x3

        local_off_i, local_off_j = R_3x3 @ off_i, R_3x3 @ off_j
        rz_factor = el.get('rz_factor', 0.0)
        ri, rj = el.get('end_off_i', 0.0) * rz_factor, el.get('end_off_j', 0.0) * rz_factor
        local_off_i[0] += ri
        local_off_j[0] -= rj

        T_ecc = get_eccentricity_matrix(local_off_i, local_off_j)
        kg_local_node = T_ecc.T @ kg_local @ T_ecc
        if ri > 0:
            kg_local_node[4, 4] += N_axial * ri
            kg_local_node[5, 5] += N_axial * ri
        if rj > 0:
            kg_local_node[10, 10] += N_axial * rj
            kg_local_node[11, 11] += N_axial * rj

        kg_global = T_rot.T @ kg_local_node @ T_rot
        start_i, start_j = idx_i * 6, idx_j * 6
        gidx = [start_i + x for x in range(6)] + [start_j + x for x in range(6)]
        for r in range(12):
            for c in range(12):
                v = kg_global[r, c]
                if v != 0.0:
                    kg_row.append(gidx[r])
                    kg_col.append(gidx[c])
                    kg_data.append(v)

    KG_full = coo_matrix((kg_data, (kg_row, kg_col)), shape=(dm.total_dofs, dm.total_dofs)).tocsc()
    KG_out = (T.T @ KG_full @ T) if has_T else KG_full
    return KG_out, kg_local_map

"""
    # after building node_rot / corot_elements (existing lines ~492-508):

    if prior_case_state is not None:
        U_free = apply_initial_state(node_rot, corot_elements, is_free_sys,
                                      prior_case_state)
    else:
        U_free = np.zeros(num_free_dofs)               # <- your existing line

    KG_seed_sys = None
    if prior_case_state is not None and geom_nonlin == "P-Delta":
        # Large Displacements needs no seed - N_axial is recomputed fresh
        # from p_local every iteration inside compute_corotational_element.
        KG_seed_sys = build_geometric_stiffness_full(
            dm, element_matrices, prior_case_state.axial_force,
            has_T=has_T, T=T)

    for step in range(1, max_total_steps + 1):
        ...
        if step == 1 and KG_seed_sys is not None:
            K_total_sys  = (K_E_sys + KG_seed_sys).tocsc()
            K_total_free = K_total_sys[is_free_sys, :][:, is_free_sys]
        else:
            K_total_free = K_E_free.copy()              # <- your existing lines
            K_total_sys  = K_E_sys.tocsc()
        ...

    # at the end, right where results_dict is built (~line 1094):
    case_end_state = capture_case_end_state(
        dm, U_sys, node_rot, corot_elements, U_full, element_matrices,
        case_name=target_case_name, converged=not bool(failed_steps))
    # persist case_end_state (in-memory dict keyed by case name, or
    # serialize it) so the NEXT case's "Continue from State at End of
    # Nonlinear Case <X>" dropdown can hand it back in as prior_case_state.
"""

def get_controlled_dof_free_index(dm, is_free_sys, kept_dofs, has_T, node_id, dof_name):
    """
    Converts the UI's (Joint, DOF) pair -- e.g. "Joint 2, U1" from the
    Load Application Control dialog -- into an index within the reduced
    free-DOF vector U_free the Newton loop actually solves for. Mirrors
    the exact is_free_sys/kept_dofs pipeline your engine already builds
    at lines ~438-475.
    """
    dof_map = {'U1': 0, 'U2': 1, 'U3': 2, 'R1': 3, 'R2': 4, 'R3': 5}
    node_idx = dm.node_id_to_idx[node_id]
    full_dof = node_idx * 6 + dof_map[dof_name]

    if has_T:
        matches = np.where(kept_dofs == full_dof)[0]
        if len(matches) == 0:
            raise SolverException(
                "E205",
                f"Monitored DOF (Joint {node_id}, {dof_name}) is a diaphragm "
                f"slave DOF -- control the diaphragm MASTER node instead."
            )
        sys_dof = int(matches[0])
    else:
        sys_dof = full_dof

    free_positions = np.where(is_free_sys)[0]
    matches = np.where(free_positions == sys_dof)[0]
    if len(matches) == 0:
        raise SolverException(
            "E203",
            f"Monitored DOF (Joint {node_id}, {dof_name}) is restrained or "
            f"inactive -- cannot be displacement-controlled."
        )
    return int(matches[0])

def solve_displacement_control_iteration(K_total_free, R_free, P_ref_free,
                                          ctrl_dof_free_idx, delta_u_target_step,
                                          u_free_at_step_start, u_free_now):
    """
    ONE Newton iteration of the Batoz & Dhatt (1979) displacement-control
    partition. Drop-in replacement for the residual/solve block at
    nonlinear_engine.py lines ~669-685, for load cases whose "Load
    Application Control" is set to Displacement Control (your attached
    dialog screenshots).

    Standard partition:
        K * dU_R = R_free        (correction at the CURRENT load level)
        K * dU_T = P_ref_free    (response to the unit reference load)

    Delta-lambda is then chosen so the controlled DOF's cumulative
    displacement change SINCE THE START OF THIS STEP hits the prescribed
    target exactly:

        (u_now[dof] + dU_R[dof] - u_at_step_start[dof]) + d_lambda*dU_T[dof]
            == delta_u_target_step

    This is what makes snap-through / limit points tractable: dU_T[dof]
    naturally changes sign past a limit point, so d_lambda (and hence the
    applied load) automatically reverses to keep tracing the equilibrium
    path in displacement space, which a pure load-controlled step cannot
    do (it diverges at the limit point).

    Parameters
    ----------
    K_total_free : current tangent (elastic + geometric, P-Delta lagged
                   OR the corotational K_total_free -- identical either
                   way, this function doesn't care which formulation
                   produced it).
    R_free        : out-of-balance residual at the CURRENT lambda, i.e.
                   lam_now * P_ref_free - F_int_free. Pass an all-zero
                   array on the very first iteration of a fresh step.
    P_ref_free    : the case's reference load pattern, UNSCALED -- this
                   is exactly your existing P_total_free, NOT
                   step_frac * P_total_free (lambda replaces step_frac).
    ctrl_dof_free_idx : from get_controlled_dof_free_index().
    delta_u_target_step : signed displacement increment to reach by the
                   END of this step, relative to u_free_at_step_start
                   (e.g. 0.1 m total over max_total_steps steps ->
                   0.1/max_total_steps per step, sign = push direction).
    u_free_at_step_start : U_free snapshot taken at the TOP of the step,
                   before its first iteration.
    u_free_now    : U_free at the start of THIS iteration.

    Returns
    -------
    dU_free, d_lambda : apply as `U_free += dU_free; lam += d_lambda`,
    then proceed with your existing node_rot update / large_disp
    bookkeeping exactly as for a load-controlled iteration.
    """
    dU_R = spsolve(K_total_free, R_free) if np.any(R_free) else np.zeros_like(R_free)
    dU_T = spsolve(K_total_free, P_ref_free)

    denom = dU_T[ctrl_dof_free_idx]
    if abs(denom) < 1e-14:
        raise SolverException(
            "E301",
            "Displacement-control tangent at the monitored DOF is ~0 "
            "(structure has gone rigid, or the monitored DOF has "
            "decoupled from the reference load pattern). Try a smaller "
            "step size or verify the monitored joint/direction."
        )

    u_disp_so_far = (u_free_now[ctrl_dof_free_idx] + dU_R[ctrl_dof_free_idx])\
                    - u_free_at_step_start[ctrl_dof_free_idx]
    d_lambda = (delta_u_target_step - u_disp_so_far) / denom

    dU_free = dU_R + d_lambda * dU_T
    return dU_free, d_lambda

"""
    ctrl_dof_free_idx = get_controlled_dof_free_index(
        dm, is_free_sys, kept_dofs, has_T, node_id=monitored_node_id,
        dof_name=monitored_dof_name)

    total_target_disp = nl_params["monitored_disp_magnitude"]   # e.g. 0.1
    lam = 0.0

    for step in range(1, max_total_steps + 1):
        u_free_at_step_start = U_free.copy()
        delta_u_target_step = total_target_disp / max_total_steps

        # K_total_free at the top of the step: unchanged from your
        # existing code (elastic, or elastic+KG-from-Case-A-seed on step 1
        # per the chaining section above; the corotational path rebuilds
        # it every iteration inside _compute_corot_residual as always).

        for iter_count in range(1, max_nr_iter + 1):
            # --- existing F_int_free / K_total_free recovery: UNCHANGED
            # (large_disp branch calls _compute_corot_residual exactly as
            # today; non-large_disp branch does K_total_sys.dot(U_sys_now)
            # exactly as today)

            R_free = lam * P_ref_free - F_int_free          # was: P_target_free - F_int_free

            residual_norm = np.linalg.norm(R_free)
            P_norm = np.linalg.norm(lam * P_ref_free)
            rel_error = residual_norm / P_norm if P_norm > 1e-9 else residual_norm

            disp_err = abs((U_free[ctrl_dof_free_idx] - u_free_at_step_start[ctrl_dof_free_idx])
                           - delta_u_target_step)
            disp_tol = nl_params.get("disp_control_tol", 1e-6)   # absolute, in model length units

            if rel_error < iter_conv_tol and disp_err < disp_tol:
                step_converged = True
                break

            dU_free, d_lambda = solve_displacement_control_iteration(
                K_total_free, R_free, P_ref_free, ctrl_dof_free_idx,
                delta_u_target_step, u_free_at_step_start, U_free)

            # existing max_disp_per_iter clamp: apply to dU_free exactly
            # as today (lines ~696-698) BEFORE adding it in, so a clamped
            # step also proportionally damps d_lambda -- otherwise the
            # constraint equation and the applied displacement disagree:
            _trial_max = np.max(np.abs(dU_free)) if dU_free.size else 0.0
            if _trial_max > max_disp_per_iter:
                scale = max_disp_per_iter / _trial_max
                dU_free *= scale
                d_lambda *= scale

            U_free += dU_free
            lam += d_lambda

            # existing large_disp node_rot.update(d_theta) bookkeeping:
            # UNCHANGED, driven off dU_free exactly as it is today.
"""

def build_disp_history_path(history, zero_tol=1e-12):
    """
    Displacement-history (cyclic) path for Displacement Control cases.

    history : sequence of ABSOLUTE targets of the monitored DOF, in solver (SI)
              units, measured from the monitored DOF's value at the START of
              the case. Row k is reached from row k-1 (row 1 from zero), same
              meaning as the OpenSees History Table.

    Returns (s_nodes, u_nodes, breaks):
      u_nodes = [0, t1, t2, ...] with zero-length segments removed;
      s_nodes = cumulative |du| / total path length, so s runs 0 -> 1 and a
                uniform step in s is a uniform step in displacement;
      breaks  = the interior s values (the targets) - the step controller must
                land exactly on each one, otherwise a reversal peak is skipped.
    The monitored displacement at path fraction s is np.interp(s, s_nodes, u_nodes).
    """
    t = [0.0]
    for v in history:
        v = float(v)
        if not np.isfinite(v):
            raise SolverException("E104", "Displacement history contains a non-numeric target.")
        if abs(v - t[-1]) > zero_tol:
            t.append(v)
    if len(t) < 2:
        raise SolverException(
            "E104", "Displacement history never moves away from zero - nothing to apply.")
    u = np.array(t, dtype=float)
    cum = np.concatenate([[0.0], np.cumsum(np.abs(np.diff(u)))])
    s = cum / cum[-1]
    s[-1] = 1.0
    breaks = [float(x) for x in s[1:-1]]
    return s, u, breaks
