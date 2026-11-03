"""
Vectorized replacement for nonlinear_engine._compute_corot_residual's
per-element loop + COO scatter. Same inputs/outputs/contract as the
original; the only change is HOW the per-element results are computed
and scattered into F_int_full / K_full_ld (batched instead of a
144-iteration-per-element Python double loop).

Fast path: when every element's persistent state is an ElementCorotState
and compute_fn is the corotational formulation, the per-element math
itself is batched via compute_corotational_elements_batch too (see
corotational_beam.py). Any other formulation (e.g. Updated Lagrangian,
compute_fn=compute_ul_element) falls back to calling compute_fn per
element exactly as before - only the scatter step is vectorized for it,
since ul_element.py's math wasn't part of what was vectorized here.
"""
import numpy as np
from scipy.sparse import coo_matrix
from corotational_beam import ElementCorotState, compute_corotational_element, compute_corotational_elements_batch

def _get_or_build_static_cache(dm, corot_elements, compute_fn):
    """
    Per-element data that never changes across Newton iterations or load
    steps within one run (element->node wiring, dof map, and - for the
    corotational fast path only - each element's material/section/L0/
    R0/L_clear/L_tor/rigid_zone_total). Built once and cached on dm so
    repeated calls in the iteration loop don't redo this every time.
    """
    cache = getattr(dm, '_corot_batch_cache', None)
    if cache is not None and cache.get('n_elements') == len(dm.elements):
        return cache

    eid_strs, idx_i_list, idx_j_list = [], [], []
    for el in dm.elements:
        eid_str = str(el['id'])
        if corot_elements.get(eid_str) is None:
            continue
        idx_i, idx_j = el['node_indices']
        eid_strs.append(eid_str)
        idx_i_list.append(idx_i)
        idx_j_list.append(idx_j)

    idx_i_arr = np.array(idx_i_list, dtype=np.int64)
    idx_j_arr = np.array(idx_j_list, dtype=np.int64)
    N = len(eid_strs)

    dof_map = np.zeros((N, 12), dtype=np.int64)
    for k in range(6):
        dof_map[:, k] = idx_i_arr * 6 + k
        dof_map[:, 6 + k] = idx_j_arr * 6 + k

    fast_path = (compute_fn is compute_corotational_element) and all(
        isinstance(corot_elements[e], ElementCorotState) for e in eid_strs
    )

    cache = {
        'n_elements': len(dm.elements),
        'eid_strs': eid_strs,
        'idx_i': idx_i_arr,
        'idx_j': idx_j_arr,
        'dof_map': dof_map,
        'fast_path': fast_path,
    }

    if fast_path:
        states = [corot_elements[e] for e in eid_strs]
        cache['R0_arr'] = np.array([s.R0 for s in states])
        cache['L0_arr'] = np.array([s.L0 for s in states])
        cache['L_clear_arr'] = np.array([s.L_clear for s in states])
        cache['L_tor_arr'] = np.array([s.L_tor for s in states])
        cache['rigid_zone_arr'] = np.array([s.rigid_zone_total for s in states])
        cache['E_arr'] = np.array([s.material['E'] for s in states])
        cache['G_arr'] = np.array([s.material['G'] for s in states])
        cache['A_arr'] = np.array([s.section['A'] for s in states])
        cache['J_arr'] = np.array([s.section['J'] for s in states])
        cache['I22_arr'] = np.array([s.section['I22'] for s in states])
        cache['I33_arr'] = np.array([s.section['I33'] for s in states])
        cache['As2_arr'] = np.array([s.section['As2'] for s in states])
        cache['As3_arr'] = np.array([s.section['As3'] for s in states])
        cache['states'] = states

    dm._corot_batch_cache = cache
    return cache

def compute_corot_residual_vectorized(dm, U_full_now, node_rot, corot_elements, T, has_T,
                                       is_free_sys, is_strict_statics=False, element_fef=None,
                                       compute_fn=compute_corotational_element):
    cache = _get_or_build_static_cache(dm, corot_elements, compute_fn)
    eid_strs = cache['eid_strs']
    idx_i, idx_j = cache['idx_i'], cache['idx_j']
    dof_map = cache['dof_map']
    N = len(eid_strs)

    if N == 0:
        F_int_full = np.zeros(dm.total_dofs)
        K_full_ld = coo_matrix((dm.total_dofs, dm.total_dofs)).tocsc()
    else:
                                                                                                     
        coords_i = np.array([dm.nodes[i]['coords'] for i in idx_i])
        coords_j = np.array([dm.nodes[j]['coords'] for j in idx_j])
        disp_i = U_full_now[np.repeat(idx_i * 6, 3) + np.tile(np.arange(3), N)].reshape(N, 3)
        disp_j = U_full_now[np.repeat(idx_j * 6, 3) + np.tile(np.arange(3), N)].reshape(N, 3)
        p1_arr = coords_i + disp_i
        p2_arr = coords_j + disp_j

        fef_arr = np.zeros((N, 12))
        if element_fef:
            for n, eid in enumerate(eid_strs):
                v = element_fef.get(eid)
                if v is not None:
                    fef_arr[n] = v

        if cache['fast_path']:
            R1_arr = np.array([node_rot[i].R for i in idx_i])
            R2_arr = np.array([node_rot[j].R for j in idx_j])
            states = cache['states']
            Rr_prev_arr = np.array([s.R_r for s in states])

            f_global, K_approx, N_axial, R_r_new = compute_corotational_elements_batch(
                cache['R0_arr'], cache['L0_arr'], cache['L_clear_arr'], cache['L_tor_arr'],
                cache['rigid_zone_arr'],
                cache['E_arr'], cache['G_arr'], cache['A_arr'], cache['J_arr'],
                cache['I22_arr'], cache['I33_arr'], cache['As2_arr'], cache['As3_arr'],
                p1_arr, p2_arr, R1_arr, R2_arr, Rr_prev_arr,
                is_strict_statics=is_strict_statics, fef_local_arr=fef_arr
            )
                                                                                              
            for n, s in enumerate(states):
                s.R_r = R_r_new[n]
        else:
                                                                                       
            f_list, K_list = [], []
            for n, eid in enumerate(eid_strs):
                state = corot_elements[eid]
                fef_local = element_fef.get(eid) if element_fef else None
                f_g, K_g, _ = compute_fn(
                    state, p1_arr[n], p2_arr[n],
                    node_rot[idx_i[n]], node_rot[idx_j[n]],
                    is_strict_statics, fef_local
                )
                f_list.append(f_g)
                K_list.append(K_g)
            f_global = np.array(f_list)
            K_approx = np.array(K_list)

        F_int_full = np.zeros(dm.total_dofs)
        np.add.at(F_int_full, dof_map.reshape(-1), f_global.reshape(-1))

        row = np.repeat(dof_map, 12, axis=1).reshape(-1)                                         
        col = np.tile(dof_map, (1, 12)).reshape(-1)                                            
        data = K_approx.reshape(-1)

        K_full_ld = coo_matrix((data, (row, col)), shape=(dm.total_dofs, dm.total_dofs)).tocsc()

    if has_T:
        K_sys_ld = T.T @ K_full_ld @ T
        F_int_sys = T.T @ F_int_full
    else:
        K_sys_ld = K_full_ld
        F_int_sys = F_int_full

    K_total_free = K_sys_ld.tocsc()[is_free_sys, :][:, is_free_sys]
    F_int_free = F_int_sys[is_free_sys]

    return F_int_full, F_int_free, K_total_free
