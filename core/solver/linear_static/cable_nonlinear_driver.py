"""
cable_nonlinear_driver.py

Stage 2 (P-Delta) / Stage 3 (Large Displacements) tension-only driver.

Deliberately does NOT modify nonlinear_engine.py. That file's inner
Newton-Raphson loop is untouched and behaves 100% identically for every
existing (non-cable) model. Instead, this module wraps it as a black box:

  1. Run the existing nonlinear engine to convergence, as-is.
  2. Recover each cable segment's axial force from the matrices/results
     it already exports (MatrixSpy's *_matrices.json + the results.json
     displacements -- both existing, unmodified outputs).
  3. Any segment with N < 0 gets flagged "deactivated" (near-zero EA,
     via the `_cable_deactivated_segments` key cable_elements.py already
     knows how to read) for the NEXT call.
  4. Repeat until the deactivated set stops changing (converged active
     set) or max_outer_iters is hit.

This is exactly the mechanism described for Stage 2 ("drop stiffness to
near-zero, re-converge, repeat until all active elements are in
tension"), just implemented as an outer wrapper instead of being fused
into the existing inner NR loop -- so the delicate existing solver files
are never edited.

Works for BOTH P-Delta and Large Displacements: which one runs is still
controlled the existing way, by `geom_nonlin` inside the load case in the
.mf file. This driver is agnostic to that setting; it only cares about
cable segment axial force sign.
"""

import json
import os
import numpy as np

from nonlinear_engine import run_nonlinear_analysis
from cable_elements import _segment_id

def _load_json(path):
    with open(path, 'r') as f:
        return json.load(f)

def _build_segment_node_map(raw):
    """
    Rebuilds {segment_id: (n1_id, n2_id)} purely from raw['cables'] /
    raw['cable_sections'], mirroring cable_elements.build_cable_elements's
    node-chain construction, WITHOUT importing DataManager (keeps this
    driver a thin, standalone JSON-in/JSON-out wrapper).
    """
    seg_node_map = {}
    for c in raw.get('cables', []):
        if not c.get('is_active', True):
            continue
        cable_id = c['id']
        n_segs = max(int(c.get('number_of_segments', 1) or 1), 1)
        chain = [c['n1_id']] + [f"{cable_id}~CAB{k}" for k in range(1, n_segs)] + [c['n2_id']]
        for k in range(n_segs):
            seg_node_map[_segment_id(cable_id, k)] = (chain[k], chain[k + 1])
    return seg_node_map

def _compute_deactivated_set(raw, results_path, matrices_path):
    if not os.path.exists(results_path) or not os.path.exists(matrices_path):
        return set()

    results = _load_json(results_path)
    matrices = _load_json(matrices_path)
    displacements = results.get('displacements', {})
    seg_node_map = _build_segment_node_map(raw)

    deactivated = set()
    for seg_id, (n1_id, n2_id) in seg_node_map.items():
        mats = matrices.get(str(seg_id))
        if not mats or mats.get('k') is None or mats.get('t') is None:
            continue
        u1 = displacements.get(str(n1_id), [0.0] * 6)
        u2 = displacements.get(str(n2_id), [0.0] * 6)
        u_global = np.array(u1 + u2)

        k = np.array(mats['k'])
        t = np.array(mats['t'])
        fef = np.array(mats.get('fef', [0.0] * 12))

        f_local = k @ (t @ u_global) + fef
        N_axial = (f_local[6] - f_local[0]) / 2.0

        if N_axial < 0:
            deactivated.add(seg_id)

    return deactivated

def run_cable_aware_nonlinear_analysis(input_json_path, output_json_path,
                                        target_case_name, progress_callback=None,
                                        max_outer_iters=15):
    """
    Drop-in replacement call site for run_nonlinear_analysis() -- same
    signature, same return convention (True/False) -- for models that may
    contain cables. If the model has no cables at all, this adds
    literally zero overhead: one JSON peek, then a direct passthrough
    to the existing, unmodified run_nonlinear_analysis().
    """
    with open(input_json_path, 'r') as f:
        raw = json.load(f)

    if not raw.get('cables'):
        return run_nonlinear_analysis(input_json_path, output_json_path,
                                       target_case_name, progress_callback)

    matrices_path = output_json_path.replace("_results.json", "_matrices.json")
    working_path = output_json_path.replace("_results.json", "_cable_iter.mf")

    deactivated = set(raw.get('_cable_deactivated_segments', []))

    ok = False
    for outer in range(1, max_outer_iters + 1):
        raw['_cable_deactivated_segments'] = sorted(deactivated)
        with open(working_path, 'w') as f:
            json.dump(raw, f)

        print(f"[Cable tension-only] Outer iteration {outer}/{max_outer_iters} "
              f"({len(deactivated)} segment(s) currently held slack)...")
        if progress_callback:
            progress_callback(f"Cable tension-only: outer iteration {outer}/{max_outer_iters}...", 20)

        ok = run_nonlinear_analysis(working_path, output_json_path, target_case_name, progress_callback)
        if not ok:
            break

        new_deactivated = _compute_deactivated_set(raw, output_json_path, matrices_path)

        if new_deactivated == deactivated:
            print(f"[Cable tension-only] Active set stabilized after {outer} outer iteration(s).")
            break
        deactivated = new_deactivated
    else:
        print(f"[Cable tension-only] WARNING: active set did not stabilize within "
              f"{max_outer_iters} outer iterations; reporting last computed state.")

    try:
        os.remove(working_path)
    except OSError:
        pass

    return ok
