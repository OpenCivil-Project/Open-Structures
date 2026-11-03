import sys
import os
import time
import numpy as np
from scipy.sparse.linalg import spsolve

current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

from error_definitions import SolverException
import os as _os
                                                                        
_MF_MULT_ROT = _os.environ.get('MF_ADD_ROT', '0') != '1'
_MF_NO_REPROJ = _os.environ.get('MF_NO_REPROJ','0') == '1'                                                      
                                                                                         
_NO_SPEEDUPS = _os.environ.get('OPENCIVIL_NO_SPEEDUPS', '0') == '1'
from data_manager import DataManager
from assembler import GlobalAssembler
from core.units import unit_registry
from solver_kernel import build_imposed_displacements

from rotation_utils import rotation_to_vector, rodrigues
from corotational_beam import ElementCorotState, NodeRotationState, compute_corotational_element
from element_library import get_rotation_matrix
from hinge_element import compute_hinge_element
from ul_element import ElementULState, compute_ul_element
from rotation_utils import update_corotational_frame
from residual_batch import compute_corot_residual_vectorized as _compute_corot_residual_vectorized_impl
from nl_chaining_and_disp_control import (
    CaseEndState, capture_case_end_state, apply_initial_state,
    build_geometric_stiffness_full, get_controlled_dof_free_index,
    solve_displacement_control_iteration, build_disp_history_path,
    PERSISTENT_HINGE_KEYS, _copy_state_value,
)

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

def _compute_corot_residual(dm, U_full_now, node_rot, corot_elements, T, has_T, is_free_sys, is_strict_statics=False, element_fef=None, compute_fn=compute_corotational_element):
    """
    One evaluation of the large-displacement internal-force / tangent-
    stiffness state at a given full displacement vector U_full_now,
    against the CURRENT node_rot / corot_elements orientation state
    (caller is responsible for making sure that state already reflects
    U_full_now - see the rotation composition step in the caller).

    Extracted out of the main loop so both the "real" per-iteration
    evaluation and speculative line-search trial evaluations can share
    the exact same force-recovery code path, instead of two copies
    drifting out of sync over time.

    compute_fn: per-element internal-force/tangent routine, sharing the
    exact call signature and return contract of
    corotational_beam.compute_corotational_element - either that function
    (Corotational formulation, default) or ul_beam.compute_ul_element
    (Updated Lagrangian formulation). Selected once per run by the
    caller based on the load case's "formulation" setting; corot_elements
    must already hold the matching per-element state type
    (ElementCorotState / ElementULState respectively).

    element_fef: optional {element_id_str: np.array(12)} of fixed-end-force
    vectors (member distributed/trapezoidal/self-weight/point loads and
    point moments applied along the span), exactly as recorded by
    GlobalAssembler/MatrixSpy into the *_matrices.json export. Without
    this, compute_fn() only sees nodal-displacement-induced internal
    force and silently drops every member load that isn't applied
    directly at a node.

    NOTE: calling this mutates corot_elements[*].R_r in place (each
    compute_fn() call updates its element's rotation-minimizing frame as
    a side effect) - callers doing a speculative trial MUST
    snapshot/restore around this call.

    VECTORIZED: the per-element loop and the COO stiffness scatter that
    used to live in this function's body now live in
    residual_batch.compute_corot_residual_vectorized (imported at module
    top as _compute_corot_residual_vectorized_impl). Same inputs, same
    outputs, same math and branch structure - the corotational per-element
    kinematics are batched via corotational_beam.compute_corotational_elements_batch
    instead of one compute_fn() call per element, and the sparse assembly
    is built from vectorized numpy arrays instead of a 144-append-per-
    element Python double loop. Verified against the original scalar
    per-element loop to ~1e-15 relative difference (floating-point
    reordering noise only) across randomized test models - see
    test_batch_layer1/2/3.py. Formulations other than the default
    Corotational one (e.g. compute_fn=compute_ul_element for Updated
    Lagrangian) automatically fall back to the original per-element
    compute_fn() call inside that same helper - only their scatter step
    is vectorized, since ul_element.py's own math wasn't touched here.
    """
    return _compute_corot_residual_vectorized_impl(
        dm, U_full_now, node_rot, corot_elements, T, has_T,
        is_free_sys, is_strict_statics, element_fef, compute_fn
    )

def _fd_consistent_tangent(dm, U_free, node_rot, corot_elements,
                            T, has_T, is_free_sys, K_E_sys, eps=1e-6, 
                            is_strict_statics=False, element_fef=None, 
                            step_frac=1.0, get_target_free=None, _split=False,
                            compute_fn=compute_corotational_element):
    """
    Builds the 100% EXACT consistent tangent stiffness by central finite
    differences of the ENTIRE RESIDUAL (Internal Force - External Force).
    This perfectly captures the 3D geometric stiffness AND the Load
    Stiffness (follower forces) to machine precision, for whichever
    per-element formulation compute_fn selects (Corotational or Updated
    Lagrangian - see _compute_corot_residual).
    """
    num_free = U_free.shape[0]
    node_snap, elem_snap = _snapshot_corot_state(node_rot, corot_elements)
    cols = np.zeros((num_free, num_free))

    def _perturbed_residual(dU_free_pert):
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

        _, F_int_pert, _ = _compute_corot_residual(
            dm, U_full_pert, node_rot, corot_elements, T, has_T, is_free_sys, is_strict_statics, element_fef, compute_fn
        )
        
        if get_target_free is not None:
            P_ext_pert = get_target_free(step_frac)
        else:
            P_ext_pert = np.zeros_like(F_int_pert)
            
        if _split:
            return F_int_pert.copy(), P_ext_pert.copy()
        return F_int_pert - P_ext_pert

    cols_i = np.zeros((num_free, num_free)) if _split else None
    cols_e = np.zeros((num_free, num_free)) if _split else None
    for j in range(num_free):
        dplus = np.zeros(num_free); dplus[j] = eps
        dminus = np.zeros(num_free); dminus[j] = -eps

        node_snap_j, elem_snap_j = _snapshot_corot_state(node_rot, corot_elements)
        R_plus = _perturbed_residual(dplus)
        _restore_corot_state(node_rot, corot_elements, node_snap_j, elem_snap_j)

        node_snap_j, elem_snap_j = _snapshot_corot_state(node_rot, corot_elements)
        R_minus = _perturbed_residual(dminus)
        _restore_corot_state(node_rot, corot_elements, node_snap_j, elem_snap_j)

        if _split:
            cols_i[:, j] = (R_plus[0] - R_minus[0]) / (2 * eps)
            cols_e[:, j] = (R_plus[1] - R_minus[1]) / (2 * eps)
            cols[:, j] = cols_i[:, j] - cols_e[:, j]
        else:
            cols[:, j] = (R_plus - R_minus) / (2 * eps)

    _restore_corot_state(node_rot, corot_elements, node_snap, elem_snap)
    from scipy.sparse import csc_matrix
    if _split:
        return csc_matrix(cols), csc_matrix(cols_i), csc_matrix(cols_e)
    return csc_matrix(cols)

def _backtracking_line_search(trial_fn, reset_fn, norm0, c1=1e-4, alpha_min=1e-2,
                              max_tries=12, debug_tag=None):
    """
    Single shared line search for every Newton path in run_nonlinear_analysis
    (P-Delta / material-only hinge / Large Displacements, load control AND
    displacement control, with or without hinges).

    trial_fn(alpha) -> ||R(alpha)||, the equilibrium residual norm evaluated
        at the trial point U + alpha*dU (and lambda + alpha*d_lambda under
        displacement control). May mutate solver state (corotational
        orientations); reset_fn() is called after EVERY trial so state is
        always pristine again on return -- the caller then applies the
        accepted step exactly once.
    norm0 -> ||R(0)||, the pre-step residual norm.

    Merit function phi = ||R||^2. For an exact tangent the Newton direction
    gives phi'(0) = -2*phi(0), so the Armijo test is
        ||R(a)||^2 <= (1 - 2*c1*a) * ||R(0)||^2.
    Backtracking uses safeguarded quadratic interpolation (step shrink
    limited to [0.1, 0.5] per try), floor alpha_min.

    Failure handling (the old code's real bug): when no alpha satisfies
    Armijo,
      * if some tried alpha still lowered the residual, use the best one;
      * if NOTHING lowered it, the Newton direction is not a descent
        direction for ||R|| (lagged K_g, approximate corotational tangent,
        or a brittle hinge snap where the residual must jump). Shrinking
        the step cannot help there and used to freeze the iteration at
        alpha ~ 1e-3 until max_nr_iter ran out; instead take the FULL
        Newton step (alpha = 1) and let the next iteration re-linearize.

    Returns (alpha, armijo_satisfied, residual_norm_at_alpha).
    """
    n0sq = norm0 * norm0
    if not np.isfinite(norm0) or n0sq == 0.0:
        return 1.0, True, norm0

    best_alpha, best_norm = None, np.inf
    alpha = 1.0
    for k in range(max_tries):
        n = trial_fn(alpha)
        reset_fn()
        if not np.isfinite(n):
            n = np.inf
        if debug_tag:
            print(f"      [ls{debug_tag}] try {k}: alpha={alpha:.4f} |R|={n:.4E} (pre={norm0:.4E})")
        if n < best_norm:
            best_alpha, best_norm = alpha, n
        if n * n <= (1.0 - 2.0 * c1 * alpha) * n0sq:
            return alpha, True, n
        if alpha <= alpha_min:
            break
        if np.isfinite(n):
            denom = n * n - n0sq + 2.0 * n0sq * alpha
            a_q = (n0sq * alpha * alpha / denom) if denom > 0.0 else 0.5 * alpha
        else:
            a_q = 0.1 * alpha
        alpha = max(min(max(a_q, 0.1 * alpha), 0.5 * alpha), alpha_min)

    if best_alpha is not None and best_norm < norm0:
        return best_alpha, False, best_norm
    return 1.0, False, norm0

_HINGE_MEMO_MAX = 8

def _hinge_solve(hd, p_local, el):
    """compute_hinge_element(..., return_info=True) for hinge data `hd` on element
    `el`, memoized. Returns (f_local, K_local, N_axial, info)."""
    failed = hd.get('failed')
    res = hd.get('residual_stiffness')
    if _NO_SPEEDUPS:
        return compute_hinge_element(
            hd['fiber_section'], hd['rel_dist'], hd['length'], p_local,
            el['material'], el['section'], el['L_clear'], return_info=True,
            failed=failed, residual_stiffness=res, mat_state=(hd.get('mat_state') if hd.get('_hyst_active') else None))
    key = (p_local.tobytes(), None if failed is None else failed.tobytes(), res, hd.get('_mat_ver', 0))
    memo = hd.get('_memo')
    if memo is None:
        memo = hd['_memo'] = {}
    hit = memo.get(key)
    if hit is None:
        hit = compute_hinge_element(
            hd['fiber_section'], hd['rel_dist'], hd['length'], p_local,
            el['material'], el['section'], el['L_clear'], return_info=True,
            failed=failed, residual_stiffness=res, mat_state=(hd.get('mat_state') if hd.get('_hyst_active') else None))
        if len(memo) >= _HINGE_MEMO_MAX:
            memo.pop(next(iter(memo)))                                 
        memo[key] = hit
    f, K, N, info = hit
    return f.copy(), K.copy(), N, dict(info, q=info['q'].copy(), d=info['d'].copy())

class _KGFastPath:
    """
    SPEED-ONLY shortcut for the P-Delta geometric-stiffness block, for elements
    WITHOUT a fiber hinge. For such an element, everything that turns the axial
    force N_axial into its global KG contribution (geometric stiffness matrix,
    release condensation, rigid-offset / eccentricity transforms, rotation to
    global) is constant geometry times N_axial, so the 12x12 global matrix is
    N_axial * U_e with U_e fixed for the whole run. The original code rebuilds it
    from scratch for every element on every Newton iteration; this reuses U_e.

    It never assumes that linearity: an element only goes onto the fast path after
    the ORIGINAL code path has produced two samples at two clearly different N of
    the same sign and the second sample equals the first scaled by N2/N1 (to 1e-9
    of the largest entry). Each sign of N is verified on its own. Anything that
    fails the check, any non-finite N and N == 0 keep using the original code.
    Entries keep the original order (row-major per element, zeros skipped), so
    duplicate entries are still summed in the same order; values differ from the
    direct computation only by floating-point rounding (~1e-16 relative).
    """
    _MIN_SEP = 0.02                                                                      
                                                                                      
    _TOL = 1e-11                                                                          
                                                                    
    def __init__(self):
        self._seen = {}                                                                  
        self._unit = {}                                                              
        self._bad = set()                                                              

    def fast(self, eid, N):
        """(rows, cols, data) lists for this element's KG entries, or None."""
        if N == 0.0 or not np.isfinite(N):
            return None
        u = self._unit.get((eid, N > 0.0))
        if u is None:
            return None
        return u[0], u[1], (u[2] * N).tolist()

    def observe(self, eid, N, gidx, kg):
        """Feed the original path's result (global 12x12 `kg` for axial force `N`)."""
        if N == 0.0 or not np.isfinite(N):
            return
        key = (eid, N > 0.0)
        if key in self._unit or key in self._bad:
            return
        prev = self._seen.get(key)
        if prev is None:
            self._seen[key] = (N, kg.copy())
            return
        N1, kg1 = prev
        if abs(N - N1) <= self._MIN_SEP * max(abs(N), abs(N1)):
            return                                                                         
        scale = float(np.max(np.abs(kg)))
        dev = float(np.max(np.abs(kg - (N / N1) * kg1)))
        del self._seen[key]
        if np.isfinite(dev) and np.isfinite(scale) and dev <= self._TOL * scale:
            r, c = np.nonzero(kg != 0.0)                                                   
            self._unit[key] = ([gidx[i] for i in r], [gidx[j] for j in c], (kg / N)[r, c])
        else:
            self._bad.add(key)

def _hinge_event_signature(dm, elements_by_id, element_matrices, U_full_vec):
    """
    {eid: {'fs','seg','eps'}} for every fiber hinge at displacement U_full_vec.
    seg[i] = which event-kink interval fiber i's strain lies in
    (FiberSection.event_segments); two signatures that differ mean at least
    one fiber crossed a backbone kink (crack, yield, peak, crush, rupture)
    between the two states. Hinges whose local solve fails are omitted
    (treated as unchanged) rather than aborting the analysis.
    """
    hinge_elements = getattr(dm, 'hinge_elements', {})
    out = {}
    for eid_str, hd in hinge_elements.items():
        mats = element_matrices.get(eid_str)
        el = elements_by_id.get(eid_str)
        if mats is None or el is None:
            continue
        t_total = np.array(mats['t'])
        i_i, i_j = el['node_indices']
        u_g = np.concatenate([U_full_vec[i_i*6:i_i*6+6], U_full_vec[i_j*6:i_j*6+6]])
        try:
            _f, _K, _N, info = _hinge_solve(hd, t_total @ u_g, el)
        except Exception:
            continue
        fs = hd['fiber_section']
        eps = fs.fiber_strains(*info['d'])
        out[eid_str] = {'fs': fs, 'seg': fs.event_segments(eps), 'eps': eps}
    return out

def _hinge_events_changed(sig_a, sig_b):
    """List of hinge ids whose fibers crossed an event kink between the two signatures."""
    if not sig_a or not sig_b:
        return []
    return [e for e in sig_b if e in sig_a and not np.array_equal(sig_a[e]['seg'], sig_b[e]['seg'])]

def _estimate_event_fraction(sig_lo, sig_hi, s_lo, s_hi):
    """
    Load fraction at which the EARLIEST fiber crossing happened, by linear
    interpolation of each crossing fiber's strain between the two states.
    """
    t_min = 1.0
    for e in _hinge_events_changed(sig_lo, sig_hi):
        a, b = sig_lo[e], sig_hi[e]
        for i in np.nonzero(a['seg'] != b['seg'])[0]:
            kink = a['fs'].first_crossing(i, int(a['seg'][i]), int(b['seg'][i]))
            den = b['eps'][i] - a['eps'][i]
            t = (kink - a['eps'][i]) / den if den != 0.0 else 1.0
            t_min = min(t_min, min(max(t, 0.0), 1.0))
    return s_lo + t_min * (s_hi - s_lo)

class _StepController:
    """
    Decides the next load-fraction target and what to do with each outcome.
    Pure logic (no solver state) so it can be tested in isolation. Cumulative
    load fraction s runs 0 -> 1 (for displacement control: fraction of the
    monitored displacement).

    Cutback: a Newton failure halves the increment (down to ds_min) and retries.
    Event-to-event: a converged trial whose hinge signature differs from the
    last committed one brackets an event in (s_done, s_try]. The controller
    probes at the interpolated crossing (+ half the tolerance) from the last
    committed state; a probe with no change is committed as the new lower
    bound, a probe with change tightens the upper bound (its converged state
    is stored as a snapshot). It stops when the upper bound is within
    event_tol of the estimated crossing, the bracket is narrower than
    event_tol, or max_probes is used, then commits the upper-bound state:
    the converged equilibrium just PAST the event, ready for the new tangent.

    on_success / on_fail return one of:
      'commit'               commit the current state as a normal step
      'commit_probe'         commit current state (internal lower bound, don't save), keep locating
      'commit_event_current' current state is the located post-event state: commit + flag
      'commit_event_stored'  restore .finished_snap (stored post-event state), commit + flag
      'restore_retry'        discard current state, restore start-of-attempt state, retry at .target()
      'retry'                (on_fail) restore start-of-attempt state, retry at .target()
      'abort'                (on_fail) out of cutback room
    """
    def __init__(self, ds_plan, ds_min, event_tol, max_probes, event_on, auto_cutback,
                 changed_fn=_hinge_events_changed, estimate_fn=_estimate_event_fraction,
                 easy_iters=4, breaks=None):
        self.ds_plan, self.ds_min = ds_plan, ds_min
                                                                                   
        self.breaks = sorted(float(b) for b in breaks) if breaks else []
        self.event_tol, self.max_probes = event_tol, max_probes
        self.event_on, self.auto_cutback = event_on, auto_cutback
        self.changed_fn, self.estimate_fn = changed_fn, estimate_fn
        self.easy_iters = easy_iters
        self.s_done, self.ds, self.sig_done = 0.0, ds_plan, None
        self.bracket, self.probes = None, 0
        self.last_side, self.same_side = None, 0
        self.events, self.n_cutbacks, self.finished_snap = [], 0, None
        self.cap = float('inf')                                                             

    @property
    def finished(self):
        return self.s_done >= 1.0 - 1e-12

    def target(self):
        self.ds = max(self.ds, self.ds_min)
        s = min(self.s_done + self.ds, 1.0)
        if 1.0 - s < 0.5 * self.ds_min:
            s = 1.0
        if self.breaks:
            nb = next((b for b in self.breaks if b > self.s_done + 1e-12), None)
            if nb is not None and s >= nb - 0.5 * self.ds_min:
                s = nb
        return s

    def force_advance(self, s_try):
        """Non-converged step accepted anyway (continue_if_no_converge)."""
        self.s_done, self.ds, self.bracket, self.probes = s_try, self.ds_plan, None, 0

    def _finish(self):
        b = self.bracket
        self.events.append({"load_fraction": float(b["s_hi"]),
                            "hinges": [str(e) for e in self.changed_fn(self.sig_done, b["sig"])]})
        self.finished_snap = b["snap"]
        self.s_done, self.sig_done = b["s_hi"], b["sig"]
        self.bracket, self.probes, self.ds = None, 0, self.ds_plan
        self.last_side, self.same_side = None, 0

    def _note_side(self, side):
        self.same_side = self.same_side + 1 if side == self.last_side else 1
        self.last_side = side

    def _refine_or_finish(self, current_is_hi):
        b, s_lo = self.bracket, self.s_done
        s_hi = b["s_hi"]
        w = s_hi - s_lo
                                                                                
        if w <= max(self.event_tol, self.ds_min) or self.probes >= self.max_probes:
            self._finish()
            return 'commit_event_current' if current_is_hi else 'commit_event_stored'
        if self.same_side >= 2:
            s_probe = s_lo + 0.5 * w                                                        
        else:
            est = self.estimate_fn(self.sig_done, b["sig"], s_lo, s_hi)
            s_probe = min(max(est + 0.5 * self.event_tol, s_lo + 0.05 * w), s_hi - 0.05 * w)
        self.probes += 1
        self.ds = s_probe - s_lo
        return 'restore_retry' if current_is_hi else 'commit_probe'

    def on_success(self, s_try, sig_try, iters, snap_thunk):
        changed = self.event_on and bool(self.changed_fn(self.sig_done, sig_try))
        if changed:
            self.bracket = {"s_hi": s_try, "sig": sig_try, "snap": snap_thunk()}
            self._note_side('hi')
            return self._refine_or_finish(current_is_hi=True)
        self.s_done = s_try
        if self.event_on:
            self.sig_done = sig_try
        if self.bracket is None:
            self.cap *= 1.05                                                        
            if iters <= self.easy_iters:
                self.ds = min(self.ds_plan, self.ds * 1.5, self.cap)
            return 'commit'
        self._note_side('lo')
        act = self._refine_or_finish(current_is_hi=False)
        return act

    def on_fail(self, s_try):
        d = s_try - self.s_done
        if self.auto_cutback and 0.5 * d >= self.ds_min:
            self.ds = 0.5 * d
            self.cap = 0.7 * d                                                               
            self.n_cutbacks += 1
            return 'retry'
        if self.bracket is not None:
            self._finish()
            return 'commit_event_stored'
        return 'abort'

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

def _downsample_states(states, max_count):
    """Evenly samples down to at most max_count entries, always keeping the
    first and last state. states must already be in ascending step order."""
    if len(states) <= max_count:
        return states
    if max_count <= 1:
        return [states[-1]]
    idx = set(int(round(i)) for i in np.linspace(0, len(states) - 1, max_count))
                                                                                  
    idx.update(i for i, st in enumerate(states) if st.get("vertex"))
    idx = sorted(idx)
    return [states[i] for i in idx]

def _snapshot_hinge_states(dm, elements_by_id, element_matrices, U_full_vec):
    """
    For every element in dm.hinge_elements, recovers this converged state's
    local end-deformation vector via the SAME t_total = element_matrices
    [eid]['t'] transform the "Fiber hinge correction (P-Delta path only)"
    block elsewhere in this file already uses, re-solves the hinge's own
    section-deformation unknowns at that converged p_local via
    hinge_element.compute_hinge_element(..., return_info=True), and returns

        {element_id_str: {"d": [eps0, kappa2, kappa3], "Lh": hinge_length}}

    -- exactly the per-hinge contract hinge_results_dialog.py's module
    docstring documents as "hinge_states". Everything past `d` (fiber
    strains/stresses, hinge moment-rotation) is rebuilt from `d` by that
    dialog itself using the same fiber_section.FiberSection the solver
    used, so nothing else needs to be exported here.

    P-Delta only: the whole fiber-hinge feature is wired only into the
    P-Delta path today (see the existing "Fiber hinge correction (P-Delta
    path only)" comments above) -- Large Displacements hinges don't exist
    yet, so the caller only invokes this for geom_nonlin == "P-Delta".

    Best-effort: returns None if the model has no hinges. A single hinge
    that fails to re-converge here (should be rare -- the global Newton
    loop only accepts a step once every hinge inside it has itself
    converged during the iteration that produced U_full_vec) is skipped
    with a warning rather than raising, so a hiccup in this purely
    diagnostic snapshot can never turn an otherwise-successful analysis
    into a failed one.
    """
    hinge_elements = getattr(dm, 'hinge_elements', {})
    if not hinge_elements:
        return None

    out = {}
    for eid_str, hinge_data in hinge_elements.items():
        mats = element_matrices.get(eid_str)
        el = elements_by_id.get(eid_str)
        if mats is None or el is None:
            continue
        t_total = np.array(mats['t'])
        idx_i, idx_j = el['node_indices']
        u_global = np.concatenate([
            U_full_vec[idx_i * 6: idx_i * 6 + 6],
            U_full_vec[idx_j * 6: idx_j * 6 + 6]
        ])
        p_local = t_total @ u_global
        try:
            _f, _K, _N, info = _hinge_solve(hinge_data, p_local, el)
        except Exception as e:
            print(f"      [!] WARNING: could not snapshot hinge state for "
                  f"element {eid_str} ({e}); omitted from this saved state.")
            continue
        if not info.get('converged', True):
            print(f"      [!] WARNING: hinge on element {eid_str} did not "
                  f"re-converge while snapshotting saved-state data "
                  f"(method={info.get('method')}); recorded anyway as the "
                  f"best available estimate.")
        out[eid_str] = {
            "d": [float(v) for v in info['d']],
            "Lh": float(hinge_data['length']),
        }
                                                                                             
        _fs_h, _ms_h = hinge_data['fiber_section'], hinge_data.get('mat_state')
        if hinge_data.get('_hyst_active') and _ms_h is not None and getattr(_fs_h, 'hysteresis', None) is not None:
            _eps_h = _fs_h.fiber_strains(*info['d'])
            out[eid_str]["fiber_stress"] = [float(v) for v in _fs_h.hysteresis.evaluate(_eps_h, _ms_h)[0]]
    return out or None

def _commit_hinge_fiber_failures(dm, elements_by_id, element_matrices, U_full_vec, scope='tension', commit=True):
    """
    SAP-compatible fiber snap, applied ONLY when a load step is accepted.

    Rule (no fitted constants): a fiber whose converged state at the end of an
    accepted step lies on a NEGATIVE-tangent (softening) branch of its
    backbone is declared snapped: from the next step on it carries zero
    stress and zero stiffness. Rationale: with a softening fiber the 2x2
    section tangent is indefinite (det ~ 4 E_c E_t < 0 for two opposed
    fibers), and the commercial solver's Newton iteration jumps to the
    zero-stress branch at the next step instead of following the descending
    branch. Following the descending branch is an equally valid equilibrium
    path, so this is switchable: nl_params['hinge_snap'] = False.

    commit=False only DETECTS newly failed fibers (nothing is zeroed); used by
    'Stop at First Fiber Failure' when Hinge Snap is off.

    Returns list of (eid, [fiber indices newly snapped]).
    """
    newly = []
    for eid_str, hd in getattr(dm, 'hinge_elements', {}).items():
        mats = element_matrices.get(eid_str)
        el = elements_by_id.get(eid_str)
        if mats is None or el is None:
            continue
        t_total = np.array(mats['t'])
        i_i, i_j = el['node_indices']
        u_g = np.concatenate([U_full_vec[i_i*6:i_i*6+6], U_full_vec[i_j*6:i_j*6+6]])
        fs = hd['fiber_section']
        failed = hd.get('failed')
        try:
            _f, _K, _N, info = _hinge_solve(hd, t_total @ u_g, el)
        except Exception:
            continue
        _eps, _sig, tan = fs.fiber_tangents(*info['d'])
        soft = tan < -1.0                                             
        if scope != 'all':
                                                                                       
            soft = soft & (_eps > 0.0)
        if failed is not None:
            soft = soft & ~failed
        if np.any(soft):
            if commit:
                hd['failed'] = soft.copy() if failed is None else (failed | soft)
            newly.append((eid_str, [int(k) for k in np.nonzero(soft)[0]]))
    return newly

def _commit_hinge_hysteresis(dm, elements_by_id, element_matrices, U_full_vec):
    """
    Cyclic hysteresis commit (fiber_hysteresis.py), applied ONLY when a load step is
    accepted: re-solves each hinge at the converged state with the PREVIOUS committed
    material state (exactly what the accepted step used), then stores the state the
    hysteresis law returns for those converged fiber strains as the new committed state.
    Rejected steps / probes never reach this, and _restore_snapshot rolls back anything
    already committed (mat_state is in PERSISTENT_HINGE_KEYS). Returns the hinge count.
    """
    n = 0
    for eid_str, hd in getattr(dm, 'hinge_elements', {}).items():
        fs = hd['fiber_section']
        ms = hd.get('mat_state')
        if not hd.get('_hyst_active') or ms is None or getattr(fs, 'hysteresis', None) is None:
            continue
        mats = element_matrices.get(eid_str)
        el = elements_by_id.get(eid_str)
        if mats is None or el is None:
            continue
        t_total = np.array(mats['t'])
        i_i, i_j = el['node_indices']
        u_g = np.concatenate([U_full_vec[i_i*6:i_i*6+6], U_full_vec[i_j*6:i_j*6+6]])
        try:
            _f, _K, _N, info = _hinge_solve(hd, t_total @ u_g, el)
        except Exception as e:
            print(f"      [!] WARNING: hysteresis commit skipped for element {eid_str} ({e}); "
                  f"its material history is NOT advanced this step.")
            continue
        eps = fs.fiber_strains(*info['d'])
        hd['mat_state'] = fs.hysteresis.evaluate(eps, ms)[2]
        hd['_mat_ver'] = hd.get('_mat_ver', 0) + 1
        hd.pop('_memo', None)
        n += 1
    return n

def _compute_pdelta_hinge_force_correction(dm, elements_by_id, element_matrices, U_full_vec):
    """
    Returns the full-length (dm.total_dofs,) GLOBAL force vector that
    converts K_E's purely-elastic recovery for every fiber-hinge element
    into that hinge's actual nonlinear force -- i.e. exactly
    "F_hinge_corr_full" from the "Fiber hinge correction (P-Delta path
    only)" residual block, factored out here so BOTH the main residual
    evaluation and the P-Delta line-search trial evaluation (added
    below, which needs to re-evaluate this at several candidate step
    lengths per iteration) call the identical code rather than risking
    the two copies drifting apart.

    Returns None if the model has no hinges (cheap no-op, mirroring the
    original inline "if hinge_elements:" guard).
    """
    hinge_elements = getattr(dm, 'hinge_elements', {})
    if not hinge_elements:
        return None

    from element_library import get_eccentricity_matrix

    F_hinge_corr_full = np.zeros(dm.total_dofs)
    for eid_str, hinge_data in hinge_elements.items():
        if eid_str not in element_matrices:
            continue
        el = elements_by_id.get(eid_str)
        if el is None:
            continue

        k_local = np.array(element_matrices[eid_str]['k'])
        t_total = np.array(element_matrices[eid_str]['t'])

        idx_i, idx_j = el['node_indices']
        u_global = np.concatenate([
            U_full_vec[idx_i*6: idx_i*6+6],
            U_full_vec[idx_j*6: idx_j*6+6]
        ])
        p_local = t_total @ u_global

        f_elastic_local = k_local @ p_local                                              
        f_hinge_local, _K_hinge_unused, _N_unused, _info_unused = _hinge_solve(
            hinge_data, p_local, el
        )
                                                                          
        dK_frozen = hinge_data.get('_dK_frozen')
        df_local = f_hinge_local - f_elastic_local
        if dK_frozen is not None:
            df_local = df_local - dK_frozen @ p_local

        R_3x3 = get_rotation_matrix(
            dm.nodes[idx_i]['coords'] + np.array(el['offsets'][0]),
            dm.nodes[idx_j]['coords'] + np.array(el['offsets'][1]),
            el.get('beta', 0.0) - np.degrees(el['section'].get('theta_p', 0.0))
        )
        local_off_i_pd = R_3x3 @ np.array(el['offsets'][0])
        local_off_j_pd = R_3x3 @ np.array(el['offsets'][1])
        rz_factor_pd = el.get('rz_factor', 0.0)
        local_off_i_pd = local_off_i_pd.copy()
        local_off_j_pd = local_off_j_pd.copy()
        local_off_i_pd[0] += el.get('end_off_i', 0.0) * rz_factor_pd
        local_off_j_pd[0] -= el.get('end_off_j', 0.0) * rz_factor_pd
        T_ecc_pd = get_eccentricity_matrix(local_off_i_pd, local_off_j_pd)
                                                                    
        df_local_node = T_ecc_pd.T @ df_local
        T_rot = np.zeros((12, 12))
        for blk in range(4):
            T_rot[blk*3:(blk+1)*3, blk*3:(blk+1)*3] = R_3x3
        df_global = T_rot.T @ df_local_node

        start_i, start_j = idx_i * 6, idx_j * 6
        F_hinge_corr_full[start_i:start_i+6] += df_global[0:6]
        F_hinge_corr_full[start_j:start_j+6] += df_global[6:12]

    return F_hinge_corr_full

def run_nonlinear_analysis(input_json_path, output_json_path, target_case_name, progress_callback=None,
                            prior_case_state=None, case_states_out=None):
    """
    Step 1: The Engine Skeleton for Nonlinear Static (P-Delta) Analysis.

    prior_case_state : CaseEndState or None. Required when this case's
        "Stiffness to Use" is set to "Stiffness at End of Nonlinear Case"
        (nl_params["continue_from_case"] is set) -- the caller (normally
        solver_worker.py, which runs cases in dependency order and keeps
        a {case_name: CaseEndState} map) must resolve the named
        predecessor case and pass its CaseEndState in here. Ignored (may
        be None) for a "Zero Initial Conditions" case.

    case_states_out : optional dict. If provided, this run's own
        CaseEndState is written into case_states_out[target_case_name]
        on completion (converged or not, provided at least step 1 ran),
        so a LATER call in the same batch can chain from this one.
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
                                                                   
        import json as _json_peek
        with open(input_json_path, "r") as _fp_peek:
            _raw_peek = _json_peek.load(_fp_peek)
        if _raw_peek.get("info", {}).get("analysis_engine", "native") == "opensees":
            print("      Analysis Engine: OpenSees")
            from core.opensees_port.OS_OP import run_opensees_nonlinear_static
            return run_opensees_nonlinear_static(_raw_peek, output_json_path, target_case_name, progress_callback)
        print("[1/5] Initializing Data Manager & Reading Parameters...")
        progress_callback("Loading model data...", 5)
        dm = DataManager(input_json_path)
        dm.process_all(case_name=target_case_name)

        from hinge_loader import build_hinge_elements
        dm.hinge_elements = build_hinge_elements(dm)
        if dm.hinge_elements:
            try:
                import hinge_element as _he, hinge_loader as _hl, fiber_section as _fsec, inspect as _insp
                print(f"      [hinge build] RESIDUAL_STIFFNESS={getattr(_he,'RESIDUAL_STIFFNESS','MISSING (old hinge_element.py!)')}, "
                      f"FIBER_COORDS_ARE_SAP_LOCAL_AXES={getattr(_hl,'FIBER_COORDS_ARE_SAP_LOCAL_AXES','MISSING (old hinge_loader.py!)')}, "
                      f"fiber_section clamps tails={'ZERO tangent beyond table' in _insp.getsource(_fsec.backbone_lookup) or 'Outside the tabulated' in _insp.getsource(_fsec.backbone_lookup)}, "
                      f"dK double-count fix={'_dK_frozen' in open(__file__).read()}")
            except Exception as _e:
                print(f"      [hinge build] banner failed: {_e}")
            print(f"      Fiber hinges wired: {len(dm.hinge_elements)} "
                  f"element(s) -> {list(dm.hinge_elements.keys())}")

        case_data = next((c for c in dm.raw['load_cases'] if c['name'] == target_case_name), None)
        if not case_data:
            raise SolverException("E104", f"Load Case '{target_case_name}' not found.")

        geom_nonlin = case_data.get("geom_nonlin", "None")
        nl_params = case_data.get("nl_params", {})
        
        _res_floor = nl_params.get("residual_stiffness", None)
        for _hd in getattr(dm, 'hinge_elements', {}).values():
            _hd['residual_stiffness'] = None if _res_floor is None else float(_res_floor)

        _hyst_hinges = [_hd for _hd in getattr(dm, 'hinge_elements', {}).values()
                        if getattr(_hd['fiber_section'], 'hysteresis', None) is not None]
        _hyst_on = bool(_hyst_hinges) and os.environ.get('MF_NO_HYSTERESIS', '0') in ('', '0')
        if _hyst_on and bool(nl_params.get("hinge_snap", nl_params.get("sap_hinge_snap", True))):
            print("      [i] Takeda hysteresis is inactive for this case because Hinge Snap = Yes "
                  "(snap is for monotonic loading). Set Hinge Snap = No for cyclic behavior.")
            _hyst_on = False
        if _hyst_on:
            for _hd in _hyst_hinges:
                _hd['mat_state'] = _hd['fiber_section'].hysteresis.init_state()                                         
                _hd['_mat_ver'] = 0
                _hd['_hyst_active'] = True
            print(f"      Cyclic hysteresis ON for {len(_hyst_hinges)} fiber hinge(s) (Takeda material).")

        max_total_steps = nl_params.get("max_total_steps", 200)                              
        max_nr_iter = nl_params.get("max_nr_iter", 40)
        iter_conv_tol = nl_params.get("iter_conv_tol", 1e-4)
        corot_type = nl_params.get("corot_type", "Commercial Compatibility")
        is_strict_statics = (corot_type == "Strict Global Equilibrium (Native)")

        formulation = nl_params.get("formulation", "Corotational")
        is_ul = (formulation == "Updated Lagrangian")
        element_state_cls = ElementULState if is_ul else ElementCorotState
        compute_element_fn = compute_ul_element if is_ul else compute_corotational_element
        if is_ul:
            print("      [Formulation] Updated Lagrangian selected - ul_element.py. Passes 15/15 "
                  "reference-free checks, p=4.01 on the roll-up, and is ~3x more accurate per "
                  "element than the corotational path against the mesh-converged answer. It does "
                  "NOT reproduce SAP2000's coarse-mesh rows, because SAP is a chord-only element "
                  "and those rows carry SAP's own discretisation error (21% at n=1, 2.4% at n=4). "
                  "Use formulation='Corotational' when the acceptance test is SAP compatibility. "
                  "See ul_element.py header section 8.")

        results_saved_multiple = (nl_params.get("results_saved", "Final State Only") == "Multiple States")
        min_saved_states = max(1, int(nl_params.get("min_saved_states", 1)))
        _msv = int(nl_params.get("max_saved_states", 100) or 0)
        save_all_states = (_msv <= 0)                                                               
        max_saved_states = 10**9 if save_all_states else max(1, _msv)
        step_states = []

        continue_from_case = nl_params.get("continue_from_case", None)
        if continue_from_case and prior_case_state is None:
            raise SolverException(
                "E104",
                f"Load Case '{target_case_name}' is set to continue from the "
                f"state at the end of '{continue_from_case}', but that case's "
                f"converged state was not supplied to the solver. Make sure "
                f"'{continue_from_case}' is run first (in the same batch) and "
                f"converges before running '{target_case_name}'."
            )
        if continue_from_case and prior_case_state is not None\
                and prior_case_state.case_name != continue_from_case:
            raise SolverException(
                "E104",
                f"Load Case '{target_case_name}' expects to continue from "
                f"'{continue_from_case}', but the state supplied to the solver "
                f"belongs to '{prior_case_state.case_name}'."
            )
        if continue_from_case and prior_case_state is not None and not prior_case_state.converged:
            print(f"      [!] WARNING: '{continue_from_case}' did not fully converge; "
                  f"'{target_case_name}' will still continue from its last computed state.")

        if prior_case_state is not None and geom_nonlin == "Large Displacements":
            if is_ul:
                raise SolverException(
                    "E104",
                    f"Load Case '{target_case_name}' uses formulation='Updated "
                    f"Lagrangian' under Large Displacements and is set to "
                    f"continue from '{continue_from_case}'. Load Case Chaining "
                    f"is only verified for formulation='Corotational' -- switch "
                    f"this case to Corotational, or extend nl_chaining_and_"
                    f"disp_control.py once ElementULState's persistent state "
                    f"has been reviewed."
                )
            if getattr(prior_case_state, 'formulation', 'Corotational') == "Updated Lagrangian":
                raise SolverException(
                    "E104",
                    f"Load Case '{target_case_name}' is set to continue from "
                    f"'{continue_from_case}', which used formulation='Updated "
                    f"Lagrangian'. Load Case Chaining is only verified for "
                    f"formulation='Corotational' -- re-run '{continue_from_case}' "
                    f"with Corotational, or extend nl_chaining_and_disp_control.py "
                    f"once ElementULState's persistent state has been reviewed."
                )

        load_application = nl_params.get("load_application", "Full Load")
        disp_control = (load_application == "Displacement Control")
        disp_control_node_id = nl_params.get("disp_control_node_id", None)
        disp_control_dof = nl_params.get("disp_control_dof", "U1")
        disp_control_magnitude = nl_params.get("disp_control_magnitude", 0.1)
        disp_control_tol = nl_params.get("disp_control_tol", 1e-6)
        if disp_control and disp_control_node_id is None:
            raise SolverException(
                "E104",
                f"Load Case '{target_case_name}' is set to Displacement Control "
                f"but no monitored joint is defined (disp_control_node_id is None)."
            )
        hist_s = hist_u = None
        hist_breaks = []
        hist_targets = None
        if disp_control:
            if nl_params.get("disp_history"):
                hist_targets, _hsrc = nl_params["disp_history"], "nl_params"
            else:
                _ob = case_data.get("opensees") or {}
                if (isinstance(_ob, dict) and str(_ob.get("path_mode", "")) == "History Table"
                        and _ob.get("disp_history")):
                    hist_targets, _hsrc = _ob["disp_history"], "case opensees block"
        if hist_targets:
            hist_s, hist_u, hist_breaks = build_disp_history_path(hist_targets)
            _n_rev = int(np.sum(np.diff(np.sign(np.diff(hist_u))) != 0))
            print(f"      [Displacement History] {len(hist_u) - 1} target(s) from {_hsrc}; "
                  f"{_n_rev} reversal(s); peak |u| = {np.max(np.abs(hist_u)):.6g}. "
                  f"Single-target magnitude is ignored; max_total_steps = steps over the WHOLE path.")
        progress_callback(f"NONLINEAR TYPE                       = {geom_nonlin:>10}", 8)
        if geom_nonlin == "Large Displacements":
            progress_callback(f"FORMULATION                          = {formulation:>10}", 8)
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

        _elem_np = {}
        _kgfast = None if _NO_SPEEDUPS else _KGFastPath()

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

        if disp_control and global_coord_member_loads:
            raise SolverException(
                "E104",
                f"Load Case '{target_case_name}': Displacement Control cannot "
                f"currently be combined with coord='Global' member loads under "
                f"Large Displacements (per-iteration load reprojection assumes "
                f"proportional load control). Use coord='Local' member loads "
                f"for this case, or switch to Full Load."
            )

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

        P_baseline_full = (prior_case_state.P_final_full.copy()
                          if prior_case_state is not None else np.zeros(dm.total_dofs))
        P_baseline_sys = T.T @ P_baseline_full if has_T else P_baseline_full
        P_baseline_free = P_baseline_sys[is_free_sys]

        P_ref_free = P_total_free

        ctrl_dof_free_idx = None
        if disp_control:
            ctrl_dof_free_idx = get_controlled_dof_free_index(
                dm, is_free_sys, kept_dofs if has_T else None, has_T,
                node_id=disp_control_node_id, dof_name=disp_control_dof
            )

        if hist_s is not None and has_imposed:
            raise SolverException(
                "E104",
                f"Load Case '{target_case_name}' uses a displacement history, but the load "
                f"patterns include ground/joint displacements on restrained DOFs. Those are ramped "
                f"with the path fraction, which is not meaningful for a cyclic path. Remove them, "
                f"or drive the support motion through the monitored joint instead.")

        KG_seed_sys = None
        if prior_case_state is not None and geom_nonlin == "P-Delta":
            KG_seed_sys, _ = build_geometric_stiffness_full(
                dm, element_matrices, prior_case_state.axial_force, has_T=has_T, T=T
            )

        if has_imposed:
            n_imp = int(np.sum(np.abs(U_imp_sys) > 1e-12))
            print(f"      {n_imp} restrained DOF(s) carry an imposed joint displacement; "
                  f"ramping alongside the {max_total_steps} load steps.")

        large_disp = (geom_nonlin == "Large Displacements")
        corot_elements = {}                                     
        node_rot = {}                                              

        elements_by_id = {str(el['id']): el for el in dm.elements}

        if large_disp:
            print(f"      [Large Displacements] Building {formulation} element/node state...")
            for node in dm.nodes:
                node_rot[node['idx']] = NodeRotationState()

            for el in dm.elements:
                idx_i, idx_j = el['node_indices']
                p1_0 = dm.nodes[idx_i]['coords'] + np.array(el['offsets'][0])
                p2_0 = dm.nodes[idx_j]['coords'] + np.array(el['offsets'][1])
                                                                                       
                corot_elements[str(el['id'])] = element_state_cls(
                    p1_0, p2_0, el.get('beta', 0.0), el['section'], el['material'],
                    L_clear=el['L_clear'], L_tor=el['L_total']
                )

        print("[4/5] Entering Nonlinear Load Stepping Loop...")
        progress_callback("Starting Incremental Load Analysis...", 20)

        _elem_lengths = [el.get('L_clear', el.get('L_total', np.inf)) for el in dm.elements]
        min_elem_length = min(_elem_lengths) if _elem_lengths else np.inf
        if not np.isfinite(min_elem_length) or min_elem_length <= 0:
            min_elem_length = 1.0
        max_disp_per_iter = 0.25 * min_elem_length

        if prior_case_state is not None:
            U_free = apply_initial_state(node_rot, corot_elements, is_free_sys, prior_case_state,
                                         hinge_elements=getattr(dm, 'hinge_elements', None) or {})
            print(f"      [Load Case Chaining] Continuing from '{prior_case_state.case_name}' -- "
                  f"seeded U_free, {len(prior_case_state.node_rot_R)} node orientation(s), "
                  f"{len(prior_case_state.corot_Rr)} corotational frame(s), "
                  f"{len(getattr(prior_case_state, 'hinge_state', {}) or {})} fiber hinge(s) with carried material state.")
        else:
            U_free = np.zeros(num_free_dofs)
        F_int_full_ld_last = None                                                                           

        dU_imp_sys = U_imp_sys / max_total_steps

        failed_steps = []

        lam = 0.0
        u_ctrl0 = float(U_free[ctrl_dof_free_idx]) if hist_s is not None else 0.0
        P_peak_hist = 0.0

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
            if _MF_NO_REPROJ or not (large_disp and global_coord_member_loads):
                return P_baseline_free + step_frac * P_total_free

            P_dyn_full = _compute_dynamic_global_load_full()
            P_dyn_sys = T.T @ P_dyn_full if has_T else P_dyn_full
            P_dyn_free = P_dyn_sys[is_free_sys]
            return P_baseline_free + step_frac * (P_static_free + P_dyn_free)

        def _compute_target_full(step_frac_val):
            """Full-order (not reduced-to-free-DOFs) version of
            _compute_reprojected_target_free -- used to recover per-step
            reactions for saved-state snapshots, and mirrors exactly the
            math the final-state reaction computation already uses at
            step_frac_val=1.0."""
            if _MF_NO_REPROJ or not (large_disp and global_coord_member_loads):
                return P_baseline_full + step_frac_val * P_total_full
            P_dyn_full = _compute_dynamic_global_load_full()
            return P_baseline_full + step_frac_val * (P_static_full + P_dyn_full)

        def _format_node_results(U_full_x, Reactions_full_x):
            """Builds the {node_id: [...]} displacement/reaction dicts and
            the summed base reaction. Factored out of the final-state
            formatting below so per-step saved states go through the exact
            same, already-validated per-node logic (spring reaction
            handling, base reaction moment summation) instead of a second
            copy that could drift out of sync."""
            disp_out = {}
            reac_out = {}
            sum_fx = sum_fy = sum_fz = sum_mx = sum_my = sum_mz = 0.0
            for node in dm.nodes:
                n_id = str(node['id'])
                idx = node['idx'] * 6
                coords = node['coords']
                disp = U_full_x[idx: idx + 6]
                reac = Reactions_full_x[idx: idx + 6]

                if _MF_MULT_ROT:
                    try:
                        disp = np.array(disp, dtype=float).copy()
                        disp[3:6] = rotation_to_vector(node_rot[node['idx']].R)
                    except Exception:
                        pass

                spring_force = np.zeros(6)
                if node.get('spring_matrix') is not None:
                    spring_force = -(node['spring_matrix'] @ disp)

                output_reac = np.zeros(6)
                for i in range(6):
                    if node['restraints'][i]:
                        output_reac[i] = reac[i]
                    else:
                        output_reac[i] = spring_force[i]

                disp_out[n_id] = disp.tolist()
                reac_out[n_id] = output_reac.tolist()

                fx, fy, fz, mx, my, mz = output_reac
                sum_fx += fx; sum_fy += fy; sum_fz += fz
                x, y, z = coords
                sum_mx += mx + (y * fz - z * fy)
                sum_my += my + (z * fx - x * fz)
                sum_mz += mz + (x * fy - y * fx)

            base_reac = {"Fx": sum_fx, "Fy": sum_fy, "Fz": sum_fz,
                         "Mx": sum_mx, "My": sum_my, "Mz": sum_mz}
            return disp_out, reac_out, base_reac

        hinge_elements_ev = getattr(dm, 'hinge_elements', {})
        hinge_carry = bool(hinge_elements_ev) and not large_disp
        event_on = bool(nl_params.get("event_to_event", nl_params.get("use_event_stepping", True))) and hinge_carry
        ds_plan = 1.0 / max_total_steps
        ctrl = _StepController(
            ds_plan=ds_plan,
            ds_min=ds_plan * float(nl_params.get("min_step_frac", 1e-4)),
            event_tol=ds_plan * float(nl_params.get("event_tol_frac", nl_params.get("event_lumping_tol", 0.01))),
            max_probes=int(nl_params.get("max_event_probes", 12)),
            event_on=event_on,
            auto_cutback=bool(nl_params.get("auto_cutback", True)),
            breaks=hist_breaks,
        )
        if hist_s is not None:
            if np.any(np.diff(np.sign(np.diff(hist_u))) != 0):
                if not (_hyst_on and hinge_carry and geom_nonlin == "P-Delta"):
                    print("      [!] WARNING: the displacement history reverses direction, but cyclic "
                          "material memory is NOT active for this case (needs fiber hinges with Takeda "
                          "hysteresis, Hinge Snap = No, geometric nonlinearity = P-Delta). "
                          "Hinges will follow the monotonic backbone on the way back.")
            if not results_saved_multiple:
                print("      [i] Results Saved = Final State Only: only the end of the path is written. "
                      "Choose Multiple States (All Steps) to get the hysteresis loop.")
        max_attempts = int(nl_params.get("max_step_attempts") or (20 * max_total_steps + 500))
        stop_on_fiber_failure = bool(nl_params.get("stop_on_fiber_failure", False))
        fiber_stop = False                                                                            
        n_accepted = 0
        KG_full = None
        K_total_sys = K_E_sys.tocsc()
        K_total_free = K_E_free.copy()

        def _take_snapshot():
            ns, es = _snapshot_corot_state(node_rot, corot_elements)
            return {"U_free": U_free.copy(), "lam": lam, "node": ns, "elem": es,
                    "dK": {k: (None if v.get('_dK_frozen') is None else v['_dK_frozen'].copy())
                           for k, v in hinge_elements_ev.items()},
                                                                                  
                    "hinge_hist": {k: {kk: (None if v.get(kk) is None else _copy_state_value(v[kk]))
                                       for kk in PERSISTENT_HINGE_KEYS}
                                   for k, v in hinge_elements_ev.items()},
                    "K_sys": K_total_sys, "K_free": K_total_free, "KG_full": KG_full}

        def _restore_snapshot(sn):
            _restore_corot_state(node_rot, corot_elements, sn["node"], sn["elem"])
            for k, v in hinge_elements_ev.items():
                v['_dK_frozen'] = sn["dK"].get(k)
                for kk, val in sn["hinge_hist"].get(k, {}).items():
                    v[kk] = None if val is None else _copy_state_value(val)
                v.pop('_memo', None)
            return sn["U_free"].copy(), sn["lam"], sn["K_sys"], sn["K_free"], sn["KG_full"]

        if event_on:
            _U0 = np.zeros(K_E_sys.shape[0]); _U0[is_free_sys] = U_free
            ctrl.sig_done = _hinge_event_signature(
                dm, elements_by_id, element_matrices, T @ _U0 if has_T else _U0)
            print(f"      Event-to-event stepping ON: {len(hinge_elements_ev)} hinge(s), "
                  f"event tol = {ctrl.event_tol:.2e} of full load.")

        for step in range(1, max_attempts + 1):
            if ctrl.finished:
                break
            s_try = ctrl.target()
            d_s = s_try - ctrl.s_done
            attempt_snap = _take_snapshot()
            print(f"   -> Load fraction {ctrl.s_done:.5f} -> {s_try:.5f}  "
                  f"(attempt {step}, {n_accepted} state(s) committed)")
            progress_callback(f"Solving load fraction {s_try:.4f}...", 20 + int(70 * s_try))

            step_converged = False
            action = None
            step_frac = s_try
            U_imp_target_sys = U_imp_sys * s_try

            if disp_control:
                u_free_at_step_start = U_free.copy()
                if hist_s is not None:
                                                                                                 
                    delta_u_target_step = (float(np.interp(s_try, hist_s, hist_u))
                                           - (float(U_free[ctrl_dof_free_idx]) - u_ctrl0))
                else:
                    delta_u_target_step = disp_control_magnitude * d_s

            if n_accepted == 0 and KG_seed_sys is not None:
                                                                        
                K_total_sys = (K_E_sys + KG_seed_sys).tocsc()
                K_total_free = K_total_sys[is_free_sys, :][:, is_free_sys]
            elif hinge_carry and n_accepted > 0:
                                                                                     
                pass
            else:
                K_total_free = K_E_free.copy()
                K_total_sys = K_E_sys.tocsc()

            if large_disp and has_imposed:
                dU_imp_step = U_imp_sys * d_s
                dU_imp_full_this_step = T @ dU_imp_step if has_T else dU_imp_step
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

                    if global_coord_member_loads and not _MF_NO_REPROJ:
                                                                           
                        _sync_corot_frames(U_full_now)
                        element_fef_this_iter = _compute_dynamic_element_fef()
                    else:
                        element_fef_this_iter = element_fef

                    F_int_full, F_int_free, K_total_free = _compute_corot_residual(
                    dm, U_full_now, node_rot, corot_elements, T, has_T, is_free_sys, is_strict_statics, element_fef_this_iter, compute_element_fn
                    )
                    F_int_full_ld_last = F_int_full                                             

                    if nl_params.get("use_fd_tangent", False):
                        K_total_free = _fd_consistent_tangent(
                            dm, U_free, node_rot, corot_elements,
                            T, has_T, is_free_sys, K_E_sys, eps=1e-6, 
                            is_strict_statics=is_strict_statics, element_fef=element_fef_this_iter,
                            step_frac=step_frac, get_target_free=_compute_reprojected_target_free,
                            compute_fn=compute_element_fn
                        )

                else:
                                                                                      
                    U_sys_now = U_imp_target_sys.copy()
                    U_sys_now[is_free_sys] = U_free
                    F_int_free = K_total_sys.dot(U_sys_now)[is_free_sys]

                    U_full_now_pd = T @ U_sys_now if has_T else U_sys_now
                    F_hinge_corr_full = _compute_pdelta_hinge_force_correction(
                        dm, elements_by_id, element_matrices, U_full_now_pd
                    )
                    if F_hinge_corr_full is not None:
                        F_hinge_corr_sys = T.T @ F_hinge_corr_full if has_T else F_hinge_corr_full
                        F_int_free = F_int_free + F_hinge_corr_sys[is_free_sys]

                if disp_control:
                                                                            
                    R_free = (P_baseline_free + lam * P_ref_free) - F_int_free
                    P_norm = np.linalg.norm(P_baseline_free + lam * P_ref_free)
                    if hist_s is not None:
                                                                                                     
                        P_norm = max(P_norm, 0.1 * P_peak_hist)
                else:
                    P_target_free = _compute_reprojected_target_free(step_frac)
                    R_free = P_target_free - F_int_free
                    P_norm = np.linalg.norm(P_target_free)

                residual_norm = np.linalg.norm(R_free)
                import os as _os
                if _os.environ.get("OPENCIVIL_HINGE_DEBUG") and iter_count >= 3:
                    _worst = int(np.argmax(np.abs(R_free)))
                    print(f"      [dbg] step={step} it={iter_count} lam={lam:.6e} |R|={np.linalg.norm(R_free):.4e} "
                          f"|P|={P_norm:.4e} worst_free_dof={_worst} R_worst={R_free[_worst]:.4e} "
                          f"U_ctrl={U_free[ctrl_dof_free_idx] if disp_control else float('nan'):.6e} "
                          f"|U|max={np.max(np.abs(U_free)):.4e}")
                rel_error = residual_norm / P_norm if P_norm > 1e-9 else residual_norm

                disp_converged = True
                if disp_control:
                    disp_err = abs((U_free[ctrl_dof_free_idx] - u_free_at_step_start[ctrl_dof_free_idx])
                                   - delta_u_target_step)
                    disp_converged = disp_err < disp_control_tol

                if rel_error < iter_conv_tol and disp_converged:
                    msg = f"Converged at step {step}, iteration {iter_count} (Relative Error: {rel_error:.2E})"
                    print(f"      {msg}")
                    progress_callback(f"      {msg}", 20 + int(70 * s_try))
                    step_converged = True
                    break                                              

                d_lambda = 0.0
                if disp_control:
                    try:
                        dU_free, d_lambda = solve_displacement_control_iteration(
                            K_total_free, R_free, P_ref_free, ctrl_dof_free_idx,
                            delta_u_target_step, u_free_at_step_start, U_free
                        )
                    except Exception as e:
                        if isinstance(e, SolverException):
                            raise
                        raise SolverException("E301", f"Matrix singular at step {step}, iter {iter_count}: {e}")
                else:
                    try:
                        dU_free = spsolve(K_total_free, R_free)
                    except Exception as e:
                        raise SolverException("E301", f"Matrix singular at step {step}, iter {iter_count}: {e}")

                if not np.isfinite(dU_free).all():
                    raise SolverException(
                        "E301",
                        f"Non-finite Newton update at step {step}, iteration {iter_count}. "
                        f"K_total_free is likely NaN-poisoned from a prior over-large step."
                    )

                _trial_max = np.max(np.abs(dU_free)) if dU_free.size > 0 else 0.0
                if _trial_max > max_disp_per_iter:
                    _clamp_scale = max_disp_per_iter / _trial_max
                    dU_free = dU_free * _clamp_scale
                    if disp_control:
                                                                                
                        d_lambda = d_lambda * _clamp_scale

                if nl_params.get("use_line_search", False):
                                                                            
                    _ls_snap = _snapshot_corot_state(node_rot, corot_elements) if large_disp else None

                    def _ls_trial(alpha_try, _dU=dU_free, _dl=d_lambda):
                        U_free_trial = U_free + alpha_try * _dU
                        U_sys_trial = U_imp_target_sys.copy()
                        U_sys_trial[is_free_sys] = U_free_trial
                        U_full_trial = T @ U_sys_trial if has_T else U_sys_trial

                        if large_disp:
                            dU_sys_trial = np.zeros(K_E_sys.shape[0])
                            dU_sys_trial[is_free_sys] = alpha_try * _dU
                            dU_full_trial = T @ dU_sys_trial if has_T else dU_sys_trial
                            for node in dm.nodes:
                                n_idx = node['idx']
                                node_rot[n_idx].update(dU_full_trial[n_idx*6+3: n_idx*6+6])
                            _, F_int_free_trial, _ = _compute_corot_residual(
                                dm, U_full_trial, node_rot, corot_elements, T, has_T, is_free_sys,
                                is_strict_statics, element_fef_this_iter, compute_element_fn
                            )
                        else:
                                                                                 
                            F_int_free_trial = K_total_sys.dot(U_sys_trial)[is_free_sys]
                            F_hc_trial = _compute_pdelta_hinge_force_correction(
                                dm, elements_by_id, element_matrices, U_full_trial
                            )
                            if F_hc_trial is not None:
                                F_hc_sys_trial = T.T @ F_hc_trial if has_T else F_hc_trial
                                F_int_free_trial = F_int_free_trial + F_hc_sys_trial[is_free_sys]

                        if disp_control:
                                                                                      
                            P_trial = P_baseline_free + (lam + alpha_try * _dl) * P_ref_free
                        else:
                                                                                  
                            P_trial = _compute_reprojected_target_free(step_frac)
                        return np.linalg.norm(P_trial - F_int_free_trial)

                    def _ls_reset():
                        if large_disp:
                            _restore_corot_state(node_rot, corot_elements, _ls_snap[0], _ls_snap[1])

                    _ls_dbg = "-ld" if large_disp else "-pd"
                    alpha, _ls_ok, _ls_norm = _backtracking_line_search(
                        _ls_trial, _ls_reset, residual_norm,
                        debug_tag=_ls_dbg if _os.environ.get("OPENCIVIL_LS_DEBUG") else None
                    )
                                                                              
                    dU_free = alpha * dU_free
                    d_lambda = alpha * d_lambda

                U_free += dU_free
                if disp_control:
                    lam += d_lambda

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
                        
                        _arrs = None if _NO_SPEEDUPS else _elem_np.get(eid_str)
                        if _arrs is None:
                            _arrs = (np.array(element_matrices[eid_str]['k']),
                                     np.array(element_matrices[eid_str]['t']),
                                     np.array(element_matrices[eid_str]['fef']))
                            if not _NO_SPEEDUPS:
                                for _a in _arrs:
                                    _a.flags.writeable = False
                                _elem_np[eid_str] = _arrs
                        k_local, t_total, fef_local = _arrs
                        
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

                        hinge_elements = getattr(dm, 'hinge_elements', {})
                        hinge_data = hinge_elements.get(eid_str)
                        dK_hinge_local = None
                        if hinge_data is not None:
                            p_local_h = t_total @ u_global
                            f_hinge_local, K_hinge_local, N_hinge, _info_unused = _hinge_solve(
                                hinge_data, p_local_h, el)
                            N_axial = N_hinge
                            dK_hinge_local = K_hinge_local - k_local
                            hinge_data['_dK_frozen'] = dK_hinge_local                                         
                        elif _kgfast is not None:
                                                                                    
                            _fr = _kgfast.fast(eid_str, N_axial)
                            if _fr is not None:
                                kg_row.extend(_fr[0]); kg_col.extend(_fr[1]); kg_data.extend(_fr[2])
                                continue

                        phi_y = (12 * mat['E'] * sec['I33']) / (mat['G'] * sec['As2'] * L_geom**2) if sec['As2'] > 0 else 0.0
                        phi_z = (12 * mat['E'] * sec['I22']) / (mat['G'] * sec['As3'] * L_geom**2) if sec['As3'] > 0 else 0.0
                        
                        from element_library import get_geometric_stiffness_matrix, get_eccentricity_matrix
                        kg_local = get_geometric_stiffness_matrix(
                            -N_axial, L_geom, phi_y=phi_y, phi_z=phi_z, 
                            A=sec['A'], I22=sec['I22'], I33=sec['I33']
                        )

                        if dK_hinge_local is not None:
                                                                         
                            kg_local = kg_local + dK_hinge_local

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
                        if hinge_data is None and _kgfast is not None:
                            _kgfast.observe(eid_str, N_axial, global_indices, kg_global)
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
                msg = (f"WARNING: load fraction {s_try:.5f} failed to converge after "
                       f"{max_nr_iter} iterations! (Rel Error: {rel_error:.2E})")
                print(f"      {msg}")
                progress_callback(f"      {msg}", 20 + int(70 * s_try))
                action = ctrl.on_fail(s_try)
                if action == 'retry':
                    U_free, lam, K_total_sys, K_total_free, KG_full = _restore_snapshot(attempt_snap)
                    print(f"      Cutting back load increment to {ctrl.ds:.3e} and retrying.")
                    continue
                elif action == 'commit_event_stored':
                    step_converged = True                                              
                else:                                                           
                    action = None
                    if not nl_params.get("continue_if_no_converge", False):
                        raise SolverException("E302", f"Huge Displacements Detected: load fraction {s_try:.5f} failed to converge after {max_nr_iter} iterations, even after step cutback! (Rel Error: {rel_error:.2E})")
                    else:
                        failed_steps.append({"step": step, "load_fraction": s_try, "error": rel_error})

            if action is None:
                if step_converged:
                    if large_disp:
                        for _ul_state in corot_elements.values():
                            _commit = getattr(_ul_state, "commit", None)
                            if _commit is not None:
                                _commit()
                    _sig_try = None
                    if event_on:
                        _U_ev = U_imp_target_sys.copy(); _U_ev[is_free_sys] = U_free
                        _sig_try = _hinge_event_signature(
                            dm, elements_by_id, element_matrices, T @ _U_ev if has_T else _U_ev)
                    action = ctrl.on_success(s_try, _sig_try, iter_count, _take_snapshot)
                else:
                    ctrl.force_advance(s_try)
                    action = 'commit_failed'

            if action == 'restore_retry':
                U_free, lam, K_total_sys, K_total_free, KG_full = _restore_snapshot(attempt_snap)
                print(f"      Hinge event bracketed; re-solving at load fraction "
                      f"{ctrl.s_done + ctrl.ds:.5f} (probe {ctrl.probes}).")
                continue
            if action == 'commit_event_stored':
                U_free, lam, K_total_sys, K_total_free, KG_full = _restore_snapshot(ctrl.finished_snap)

            step_frac = ctrl.s_done
            U_imp_target_sys = U_imp_sys * step_frac
            if hist_s is not None:
                P_peak_hist = max(P_peak_hist, float(np.linalg.norm(P_baseline_free + lam * P_ref_free)))
            _is_event = action.startswith('commit_event')
            _do_save = action in ('commit', 'commit_event_current', 'commit_event_stored')
            n_accepted += 1
            if _is_event:
                print(f"      EVENT: hinge state change(s) in element(s) "
                      f"{ctrl.events[-1]['hinges']} at load fraction {step_frac:.5f}")

            if step_converged and _do_save and results_saved_multiple:
                if large_disp:
                    U_full_step = U_full_now.copy()
                                                                             
                    for node in dm.nodes:
                        n_idx = node['idx']
                        U_full_step[n_idx*6+3: n_idx*6+6] = rotation_to_vector(node_rot[n_idx].R)
                                                                            
                    Reactions_full_step = F_int_full - _compute_target_full(lam if disp_control else step_frac)
                else:
                    U_sys_step = U_imp_target_sys.copy()
                    U_sys_step[is_free_sys] = U_free
                    U_full_step = T @ U_sys_step if has_T else U_sys_step

                    if geom_nonlin == "P-Delta" and KG_full is not None:
                        K_final_full_step = K_E_full + KG_full
                    else:
                        K_final_full_step = K_E_full
                    Reactions_full_step = K_final_full_step.dot(U_full_step) - (P_baseline_full + P_total_full * (lam if disp_control else step_frac))
                                                                                         
                    _F_hc_rx = _compute_pdelta_hinge_force_correction(
                        dm, elements_by_id, element_matrices, U_full_step)
                    if _F_hc_rx is not None:
                        Reactions_full_step = Reactions_full_step + _F_hc_rx

                hinge_states_step = None
                if not large_disp:
                    hinge_states_step = _snapshot_hinge_states(
                        dm, elements_by_id, element_matrices, U_full_step
                    )

                step_states.append({
                    "step": n_accepted,
                    "step_frac": step_frac,
                    "U_full": U_full_step,
                    "Reactions_full": Reactions_full_step,
                    "hinge_states": hinge_states_step,
                    "event": _is_event,
                    "vertex": bool(hist_s is not None and (step_frac >= 1.0 - 1e-9 or
                                   any(abs(step_frac - _b) < 1e-9 for _b in hist_breaks))),
                })

            if _hyst_on and step_converged and hinge_carry and geom_nonlin == "P-Delta":
                _U_h = U_imp_target_sys.copy(); _U_h[is_free_sys] = U_free
                _commit_hinge_hysteresis(dm, elements_by_id, element_matrices, T @ _U_h if has_T else _U_h)

            _snap_on = bool(nl_params.get("hinge_snap", nl_params.get("sap_hinge_snap", True)))
            if (step_converged and hinge_carry and geom_nonlin == "P-Delta"
                    and (_snap_on or stop_on_fiber_failure)):
                _U_c = U_imp_target_sys.copy(); _U_c[is_free_sys] = U_free
                _newly = _commit_hinge_fiber_failures(
                    dm, elements_by_id, element_matrices, T @ _U_c if has_T else _U_c,
                    scope=str(nl_params.get('hinge_snap_scope', nl_params.get('sap_hinge_snap_scope', 'tension'))),
                    commit=_snap_on)
                for _eid, _fib in _newly:
                    if _snap_on:
                        print(f"      HINGE SNAP: element {_eid} fiber(s) {_fib} past peak -> "
                              f"zero stress from next step (step {n_accepted}).")
                    else:
                        print(f"      HINGE FAILURE: element {_eid} fiber(s) {_fib} past peak "
                              f"(step {n_accepted}).")
                if _newly and stop_on_fiber_failure:
                    fiber_stop = True
                    print(f"      STOPPED AT FIRST FIBER FAILURE: load fraction {ctrl.s_done:.5f}, "
                          f"{n_accepted} state(s) committed. Results up to and including this step are kept.")
                    break

        if not ctrl.finished and not fiber_stop:
            raise SolverException(
                "E302",
                f"Huge Displacements Detected: reached only load fraction {ctrl.s_done:.4f} "
                f"after {max_attempts} solve attempts (raise nl_params['max_step_attempts'] "
                f"or the minimum step size).")
                                                                      
        U_imp_target_sys = U_imp_sys * min(ctrl.s_done, 1.0)
        step_frac = ctrl.s_done if fiber_stop else 1.0

        _eig = _os.environ.get('MF_EIG', '')
        if _eig:
            _Kt, _Ki, _Ke = _fd_consistent_tangent(
                dm, U_free, node_rot, corot_elements,
                T, has_T, is_free_sys, K_E_sys, eps=1e-6,
                is_strict_statics=is_strict_statics,
                element_fef=element_fef_this_iter,
                step_frac=step_frac,
                get_target_free=_compute_reprojected_target_free, _split=True,
                compute_fn=compute_element_fn)
            _Kd = np.asarray(_Kt.todense() if hasattr(_Kt, 'todense') else _Kt, dtype=float)
            _Ks = 0.5 * (_Kd + _Kd.T)
            _asym = np.abs(_Kd - _Kd.T).max() / max(np.abs(_Kd).max(), 1e-30)
            _w, _V = np.linalg.eigh(_Ks)
                                                                
            _map = []
            _fidx = np.where(is_free_sys)[0]
            _nd_by_idx = {nd['idx']: nd for nd in dm.nodes}
            _DOF = ['U1', 'U2', 'U3', 'R1', 'R2', 'R3']
            for _j in _fidx:
                _n, _c = divmod(int(_j), 6)
                _nd = _nd_by_idx.get(_n)
                _map.append(('%s' % (tuple(round(float(q), 3) for q in _nd['coords']),) if _nd else '?', _DOF[_c]))
            with open(_eig, 'w') as _f:
                _f.write('n_free = %d   tangent asymmetry (rel) = %.3e\n' % (len(_w), _asym))
                for _nm, _M in (('K_int', _Ki), ('K_ext', _Ke)):
                    _A = np.asarray(_M.todense(), dtype=float)
                    _f.write('   %s: max|K| = %.6e   asym(abs) = %.6e   asym(rel) = %.3e\n'
                             % (_nm, np.abs(_A).max(), np.abs(_A-_A.T).max(),
                                np.abs(_A-_A.T).max()/max(np.abs(_A).max(),1e-30)))
                _Ai = np.asarray(_Ki.todense(), dtype=float)
                _Sk = 0.5*(_Ai-_Ai.T)
                _f.write('   K_int skew part, largest entries:\n')
                _fi = np.where(is_free_sys)[0]
                _nb = {nd['idx']: nd for nd in dm.nodes}
                _DN = ['U1','U2','U3','R1','R2','R3']
                def _lbl(_j):
                    _n,_c = divmod(int(_fi[_j]),6)
                    _nd=_nb.get(_n)
                    return '%s.%s' % (tuple(round(float(q),1) for q in _nd['coords']) if _nd else '?', _DN[_c])
                _fl = np.dstack(np.unravel_index(np.argsort(-np.abs(_Sk).ravel()), _Sk.shape))[0]
                _seen=set()
                for _a,_b in _fl:
                    if (_b,_a) in _seen or _a==_b: continue
                    _seen.add((_a,_b))
                    if len(_seen)>10: break
                    _f.write('      %-24s %-24s  skew = %+.4e   (K=%+.4e / K^T=%+.4e)\n'
                             % (_lbl(_a), _lbl(_b), _Sk[_a,_b], _Ai[_a,_b], _Ai[_b,_a]))
                _f.write('lowest 8 eigenvalues:\n')
                for _k in range(min(8, len(_w))):
                    _f.write('  %2d  %+.6e\n' % (_k, _w[_k]))
                _f.write('highest eigenvalue: %+.6e\n' % _w[-1])
                for _k in range(min(4, len(_w))):
                    _f.write('\n--- mode %d  lambda = %+.6e ---\n' % (_k, _w[_k]))
                    _v = _V[:, _k]
                    _v = _v / np.abs(_v).max()
                    _ordr = np.argsort(-np.abs(_v))
                    for _q in _ordr[:14]:
                        _f.write('   %-22s %-3s  %+.4f\n' % (_map[_q][0], _map[_q][1], _v[_q]))
            print('      [MF_EIG] wrote %s' % _eig)

        _dmp = _os.environ.get('MF_DUMP', '')
        if _dmp:
            import json as _json2
            _U_s = U_imp_target_sys.copy()
            _U_s[is_free_sys] = U_free
            _U_c = T @ _U_s if has_T else _U_s
            _st = []
            for _nd in dm.nodes:
                _i = _nd['idx']
                _tr = list(np.asarray(_U_c[_i*6: _i*6+3], dtype=float))
                _ro = list(np.asarray(rotation_to_vector(node_rot[_i].R), dtype=float))
                if max(abs(v) for v in _tr + _ro) < 1e-14:
                    continue
                _st.append([[float(c) for c in _nd['coords']],
                            [float(v) for v in _tr + _ro]])
            _json2.dump({'state': _st}, open(_dmp, 'w'), indent=1)

        _probe = _os.environ.get('MF_PROBE', '')
        if _probe:
            import json as _json
            _spec = _json.load(open(_probe))
            _tol = 1e-6
            _U_p = np.zeros(dm.total_dofs)
            _hit = []
            for _c, _d in _spec['state']:
                _found = None
                for _nd in dm.nodes:
                    if np.linalg.norm(np.array(_nd['coords']) - np.array(_c)) < _tol:
                        _found = _nd
                        break
                if _found is None:
                    raise RuntimeError(f'probe node {_c} not in model')
                _U_p[_found['idx']*6: _found['idx']*6+6] = _d
                _hit.append((_found['idx'], _c))
                                                          
            for _k in node_rot:
                node_rot[_k].R = np.eye(3)
                                                                            
            _prot = _os.environ.get('MF_PROBE_ROT', 'log')
            def _to_R(_v):
                _v = np.asarray(_v, dtype=float)
                if _prot == 'log':
                    return rodrigues(_v)
                import cardan as _cd
                _sq = tuple(int(_ch) for _ch in _prot[-3:])
                _in = _prot.startswith('I')
                _ang = [_v[_a] for _a in _sq]
                return _cd.compose(_sq, _ang, _in)
            for _idx, _c in _hit:
                node_rot[_idx].R = _to_R(_U_p[_idx*6+3: _idx*6+6])
            for _k, _st in corot_elements.items():
                _st.R_r = _st.R0.copy()
            if large_disp and global_coord_member_loads and not _MF_NO_REPROJ:
                _sync_corot_frames(_U_p)
                _fef_p = _compute_dynamic_element_fef()
            else:
                _fef_p = element_fef
            _Fi_full, _Fi_free, _Kp = _compute_corot_residual(
                dm, _U_p, node_rot, corot_elements, T, has_T,
                is_free_sys, is_strict_statics, _fef_p)
            _P_free = _compute_reprojected_target_free(1.0)
            _R = _Fi_free - _P_free
            _fi = np.where(np.asarray(is_free_sys))[0]
            _lbl = ['U1','U2','U3','R1','R2','R3']
            _po = open(_os.environ.get('MF_PROBE_OUT','/tmp/mf/probe_out.txt'),'w')
            _po.write('PROBE_BEGIN\n')
            _po.write('PROBE has_T=%s nfree=%d\n' % (has_T, len(_fi)))
            for _q, _g in enumerate(_fi):
                _n, _dd = divmod(int(_g), 6)
                _cc = dm.nodes[_n]['coords']
                _po.write('PROBE_DOF %-22s %-3s  Fint %+16.6f   Pext %+16.6f   RESID %+14.6e\n'
                      % (str(tuple(np.round(_cc, 4))), _lbl[_dd],
                         _Fi_free[_q], _P_free[_q], _R[_q]))
                                                                              
            import corotational_beam as _cbm
            _po.write('PROBE_ELEM\n')
            for _el in dm.elements:
                _eid = str(_el['id'])
                _stt = corot_elements.get(_eid)
                if _stt is None: continue
                _ii, _jj = _el['node_indices']
                _p1 = dm.nodes[_ii]['coords'] + _U_p[_ii*6: _ii*6+3]
                _p2 = dm.nodes[_jj]['coords'] + _U_p[_jj*6: _jj*6+3]
                _pl, _Rr, _Ln, _ax = _cbm._corot_kinematics(
                    _stt, _p1, _p2, node_rot[_ii].R, node_rot[_jj].R)
                _fl = _ax.get('f_local_last')
                _po.write('  EL %-4s L0=%.4f Ln=%.6f  u_l=%+.3e  |th_l1|=%.5f |th_l2|=%.5f  th_rel=%.5f\n'
                          % (_eid, _stt.L0, _Ln, _pl[6],
                             np.linalg.norm(_pl[3:6]), np.linalg.norm(_pl[9:12]),
                             np.linalg.norm(_ax['theta_rel'])))
                _po.write('     th_l1 = [%+.6f %+.6f %+.6f]   th_l2 = [%+.6f %+.6f %+.6f]\n'
                          % (_pl[3], _pl[4], _pl[5], _pl[9], _pl[10], _pl[11]))
                                                                              
                _fefl = (_fef_p or {}).get(_eid)
                _fg, _Ka, _Nx = _cbm.compute_corotational_element(
                    _stt, _p1, _p2, node_rot[_ii], node_rot[_jj],
                    is_strict_statics=is_strict_statics, fef_local=_fefl)
                _fl = getattr(_stt, '_f_local_dbg', np.zeros(12))
                _pld = getattr(_stt, '_p_local_dbg', np.zeros(12))
                _kl  = getattr(_stt, '_kl_dbg', np.zeros(12))
                _kg  = getattr(_stt, '_kg_dbg', np.zeros(12))
                for _tag, _v in (('p_loc', _pld), ('kl@p', _kl), ('kg@p', _kg)):
                    _po.write('     %-6s_i = [%s]\n' % (_tag, ' '.join('%+11.5f' % _q for _q in _v[0:6])))
                    _po.write('     %-6s_j = [%s]\n' % (_tag, ' '.join('%+11.5f' % _q for _q in _v[6:12])))
                _po.write('     f_loc_i  = [%s]\n' % ' '.join('%+11.3f' % _v for _v in _fl[0:6]))
                _po.write('     f_loc_j  = [%s]\n' % ' '.join('%+11.3f' % _v for _v in _fl[6:12]))
                _po.write('     f_glob_i = [%s]\n' % ' '.join('%+11.3f' % _v for _v in _fg[0:6]))
                _po.write('     f_glob_j = [%s]\n' % ' '.join('%+11.3f' % _v for _v in _fg[6:12]))
            _po.write('PROBE_NORM  |R| = %.6e   |P| = %.6e   rel = %.6e\n'
                  % (np.linalg.norm(_R), np.linalg.norm(_P_free),
                     np.linalg.norm(_R)/max(np.linalg.norm(_P_free), 1e-30)))
            _po.write('PROBE_END\n')
            _po.close()

        print("[5/5] Nonlinear Analysis Complete.")
        
        print("      Extracting Final Displacements and Reactions...")
        progress_callback("Formatting results...", 90)

        U_sys = U_imp_target_sys.copy()
        U_sys[is_free_sys] = U_free
        U_full = T @ U_sys if has_T else U_sys

        if large_disp and F_int_full_ld_last is not None:
                                                                   
            if global_coord_member_loads:
                P_dyn_full_final = _compute_dynamic_global_load_full()
                P_applied_full_final = P_baseline_full + P_static_full + P_dyn_full_final
            elif disp_control:
                P_applied_full_final = P_baseline_full + lam * P_total_full
            else:
                P_applied_full_final = P_baseline_full + P_total_full
            Reactions_full = F_int_full_ld_last - P_applied_full_final
        else:
                                                       
            if geom_nonlin in ["P-Delta", "Large Displacements"] and KG_full is not None:
                K_final_full = K_E_full + KG_full
            else:
                K_final_full = K_E_full

            P_applied_full_final = P_baseline_full + P_total_full * (lam if disp_control else 1.0)
            Reactions_full = K_final_full.dot(U_full) - P_applied_full_final
            _F_hc_fin = _compute_pdelta_hinge_force_correction(
                dm, elements_by_id, element_matrices, U_full)
            if _F_hc_fin is not None:
                Reactions_full = Reactions_full + _F_hc_fin                                  

        disp_out, reac_out, base_reac = _format_node_results(U_full, Reactions_full)

        try:
            if geom_nonlin in ("P-Delta", "None"):
                N_final_map = {}
                for el in dm.elements:
                    eid = str(el['id'])
                    if eid not in element_matrices:
                        continue
                    k_e = np.array(element_matrices[eid]['k'])
                    t_e = np.array(element_matrices[eid]['t'])
                    fef_e = np.array(element_matrices[eid]['fef'])
                    i_i, i_j = el['node_indices']
                    u_g = np.concatenate([U_full[i_i*6:i_i*6+6], U_full[i_j*6:i_j*6+6]])
                    f_lin = k_e @ (t_e @ u_g) + fef_e
                    N_final_map[eid] = 0.5 * (f_lin[6] - f_lin[0])

                kg_local_map = {}
                if geom_nonlin == "P-Delta":
                    _, kg_local_map = build_geometric_stiffness_full(
                        dm, element_matrices, N_final_map, has_T=False, T=None
                    )

                for el in dm.elements:
                    eid = str(el['id'])
                    if eid not in element_matrices:
                        continue
                    k_e = np.array(element_matrices[eid]['k'])
                    t_e = np.array(element_matrices[eid]['t'])
                    fef_e = np.array(element_matrices[eid]['fef'])
                    i_i, i_j = el['node_indices']
                    u_g = np.concatenate([U_full[i_i*6:i_i*6+6], U_full[i_j*6:i_j*6+6]])
                    kg_e = kg_local_map.get(eid)
                    k_eff = (k_e + kg_e) if kg_e is not None else k_e
                    f_local_final = k_eff @ (t_e @ u_g) + fef_e
                    assembler.spy.record_final_forces(el['id'], f_local_final)
                assembler.spy.save_to_json()

            elif large_disp and not is_ul:
                for el in dm.elements:
                    eid = str(el['id'])
                    state = corot_elements.get(eid)
                    if state is None:
                        continue
                    i_i, i_j = el['node_indices']
                    p1c = np.array(dm.nodes[i_i]['coords']) + U_full[i_i*6:i_i*6+3]
                    p2c = np.array(dm.nodes[i_j]['coords']) + U_full[i_j*6:i_j*6+3]
                    fef_l = element_fef.get(eid) if element_fef else None
                    f_global_final, _, _ = compute_corotational_element(
                        state, p1c, p2c, node_rot[i_i], node_rot[i_j],
                        is_strict_statics, fef_l
                    )
                    R_full_final = np.zeros((12, 12))
                    for blk in range(4):
                        R_full_final[3*blk:3*blk+3, 3*blk:3*blk+3] = state.R_r
                    f_local_final = R_full_final.T @ f_global_final
                    assembler.spy.record_final_forces(el['id'], f_local_final)
                assembler.spy.save_to_json()
        except Exception as e:
            print(f"      [!] WARNING: could not export final element forces for force diagrams: {e}")

        final_hinge_states = None
        if geom_nonlin == "P-Delta":
            final_hinge_states = _snapshot_hinge_states(dm, elements_by_id, element_matrices, U_full)

        results_dict = {
            "displacements": disp_out,
            "reactions": reac_out,
            "base_reaction": base_reac
        }
        results_dict["restrained_nodes"] = [
            str(n['id']) for n in dm.nodes if any(n['restraints']) or n.get('spring_matrix') is not None
        ]

        if case_states_out is not None:
            case_states_out[target_case_name] = capture_case_end_state(
                dm, U_sys, node_rot, corot_elements, U_full, element_matrices,
                P_applied_full_final,
                case_name=target_case_name, converged=(len(failed_steps) == 0),
                formulation=formulation
            )

        saved_states_out = None
        if results_saved_multiple and step_states:
            print(f"      [Results Saved] {len(step_states)} converged step(s) captured; "
                  + ("keeping all steps." if save_all_states else
                     f"downsampling to at most {max_saved_states} (min requested: {min_saved_states})."))
            step_states = _downsample_states(step_states, max_saved_states)
            saved_states_out = []
            for st in step_states:
                st_disp, st_reac, st_base = _format_node_results(st["U_full"], st["Reactions_full"])
                saved_states_out.append({
                    "step": st["step"],
                    "step_frac": st["step_frac"],
                    "displacements": st_disp,
                    "reactions": st_reac,
                    "base_reaction": st_base,
                    "hinge_states": st.get("hinge_states"),
                    "event": st.get("event", False),
                })

        from result_writer import ResultWriter
        writer = ResultWriter(output_json_path)
        meta_info = {
            "version": "0.1 Nonlinear",
            "type": "Nonlinear Static",
            "case_name": target_case_name,
            "geom_nonlin": geom_nonlin,
            "dofs": dm.total_dofs,
            "steps_completed": max_total_steps,
            "steps_accepted": n_accepted,
            "event_to_event": event_on,
            "n_events": len(ctrl.events),
            "n_cutbacks": ctrl.n_cutbacks,
            "events": ctrl.events[:1000],
            "failed_steps": failed_steps,
            "stopped_at_fiber_failure": fiber_stop,
            "stop_load_fraction": float(ctrl.s_done) if fiber_stop else None,
                                                                        
            "load_application": load_application,
            "disp_control": disp_control,
            "disp_control_node_id": disp_control_node_id if disp_control else None,
            "disp_control_dof": disp_control_dof if disp_control else None,
            "disp_control_magnitude": disp_control_magnitude if disp_control else None,
            "disp_history": [float(x) for x in hist_u[1:]] if hist_s is not None else None,
            "results_saved_multiple": results_saved_multiple,
        }
        writer.write_results(results_dict, meta_info, saved_states=saved_states_out,
                              hinge_states=final_hinge_states)
        
        elapsed_total = time.time() - start_time
        progress_callback("A N A L Y S I S   C O M P L E T E", 100)
        print("="*60)
        print(f"Total Time: {elapsed_total:.4f}s")
        print("="*60)
        return True

    except SolverException as e:
                                                                        
        print(f"FATAL ERROR: {e}")
        return _write_error(output_json_path, e.error_code, e.extra_info)

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
