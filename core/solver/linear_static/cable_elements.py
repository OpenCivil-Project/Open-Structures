"""
cable_elements.py

Surgical, additive bridge between the Cable UI objects (saved in the .mf
JSON as "cables" / "cable_sections") and the existing FEM pipeline
(DataManager.elements / assembler.py / solver_kernel.py / nonlinear_engine.py).

Nothing in this file is imported by default by any existing solver file.
It is wired in via exactly two tiny, additive hooks in data_manager.py
(see _parse_cables / _generate_cable_self_weight there) and one
try/except block in main_engine.py (Stage 1 compression warning). No
existing computational logic in assembler.py, solver_kernel.py, or
nonlinear_engine.py is modified.

Architecture (matches the 3-stage plan)
----------------------------------------
Every cable, regardless of stage, is turned into 1..N straight frame
segments between the cable's two end joints and N-1 newly-created
"phantom" interior nodes. Each segment carries the cable's actual (small)
section properties with NO end releases -- ordinary frame elements, not
a pin-jointed truss (see the correction note below for why release was
tried first and abandoned). This reuses 100% of the existing linear
stiffness / assembly / solver machinery: no new element type, no new
matrix math, no condensation path.

  Stage 1 (Linear Static):
    -> the segments above, self-weight lumped as nodal loads at the break
       points (member_dist would bend a single pin-pin frame instead of
       letting it sag axially -- see chat). Solved once via the existing
       untouched LinearSolver. check_cable_tension_state() is then called
       AFTER solving to flag (not correct) any segment in compression.

  Stage 2 (P-Delta) / Stage 3 (Large Displacements):
    -> handled by cable_nonlinear_driver.py, which calls the EXISTING,
       UNMODIFIED nonlinear_engine.run_nonlinear_analysis() repeatedly,
       toggling a `_cable_deactivated_segments` list in the raw JSON
       between calls (near-zero EA for segments found in compression),
       until the active set stabilizes. See that file for the loop.

CORRECTION (found by directly running the real assembler against this
model, not by inspection -- see chat): the first version of this file
released bending (My/Mz) at both ends of every segment, intending a true
pin-jointed polygon-method truss chain. That is a genuine MECHANISM, not
a numerical-conditioning problem: a perfectly straight chain of two-force
members has EXACTLY ZERO transverse stiffness in linear theory (a real
cable's sag stiffness only exists once axial tension develops a
geometric/P-Delta restoring force after the chain is no longer straight
-- a nonlinear effect that a single linear solve, starting straight,
cannot supply). Restraining the phantom nodes' rotations did not fix
this either -- it's the moment release itself that removes the only
thing that could resist the first infinitesimal lateral nudge.

Fix: segments carry NO releases -- they are ordinary frame elements with
the cable's actual (small) section properties, exactly matching what
"Model Cable Using Straight Frame Objects" already implies. This is
simpler than the truss design it replaces and removes the whole
release/condensation code path for cables. Self-weight is still injected
as explicit lumped nodal loads (see generate_cable_self_weight_loads)
rather than relying on the generic self-weight generator, purely to keep
this bridge self-contained and independently testable -- A_gross is
still forced to 0.0 to guarantee no double-counting regardless of that
generator's exact internals.
"""

import numpy as np

from element_library import get_rotation_matrix
from error_definitions import SolverException

try:
    from cable_catenary_solver import solve_cable_geometry, CableTargetType
except ImportError:
                                                                           
    solve_cable_geometry = None
    CableTargetType = None

def _segment_id(cable_id, k):
    """Deterministic, JSON-safe (string) id for the k-th segment of a cable."""
    return f"CAB{cable_id}_S{k}"

def _node_id(cable_id, k):
    """Deterministic id for the k-th INTERNAL (phantom) breakpoint node."""
    return f"{cable_id}~CAB{k}"

def build_cable_elements(dm):
    """
    Called once from DataManager._parse_cables(), AFTER _parse_links()
    (so phantom-node idx allocation via len(dm.nodes) doesn't collide)
    and BEFORE _prepare_load_case() / self-weight generation.

    Mutates: dm.nodes, dm.node_id_to_idx, dm.total_dofs, dm.elements.
    Adds: dm.cable_segments (cable_id -> [segment_ids]),
          dm.cable_solve_results (cable_id -> CableSolveResult or None),
          dm.cable_meta (cable_id -> dict of weight/EA/etc, reused by
          _generate_cable_self_weight and the tension-only driver).

    No-op (does nothing at all, touches nothing) if the .mf has no
    "cables" key -- so every existing non-cable model is byte-for-byte
    unaffected.
    """
    cables_raw = dm.raw.get('cables', [])
    dm.cable_segments = {}
    dm.cable_solve_results = {}
    dm.cable_meta = {}

    if not cables_raw:
        return

    cable_sections_by_name = {cs['name']: cs for cs in dm.raw.get('cable_sections', [])}
    deactivated = set(dm.raw.get('_cable_deactivated_segments', []))
    if deactivated:
        print(f"      Cable tension-only: {len(deactivated)} segment(s) held near-zero EA this pass.")

    node_by_id = {n['id']: n for n in dm.nodes}

    count_built = 0
    for c in cables_raw:
        if not c.get('is_active', True):
            continue

        cable_id = c['id']
        n1 = node_by_id.get(c['n1_id'])
        n2 = node_by_id.get(c['n2_id'])
        cs = cable_sections_by_name.get(c.get('sec_name'))

        if n1 is None or n2 is None or cs is None:
            raise SolverException(
                "E103",
                f"Cable {cable_id} references a missing node or missing "
                f"cable section '{c.get('sec_name')}'."
            )

        mat = dm.materials.get(cs.get('mat_name'))
        if mat is None:
            raise SolverException(
                "E103",
                f"Cable section '{cs.get('name')}' references missing "
                f"material '{cs.get('mat_name')}'."
            )

        mods = cs.get('modifiers', {}) or {}
        area = float(cs.get('area', 0.0)) * mods.get('A', 1.0)
        if area <= 1e-12:
            raise SolverException("E202", f"Cable {cable_id}: section area is zero or invalid.")

        EA = mat['E'] * area
        gamma = mat['rho']                                                            
        self_w_per_len = area * gamma * mods.get('Weight', 1.0)
        added_w = float(c.get('added_weight', 0.0) or 0.0)
        w_total = max(self_w_per_len + added_w, 0.0)

        p1 = np.asarray(n1['coords'], dtype=float)
        p2 = np.asarray(n2['coords'], dtype=float)
        chord_len = float(np.linalg.norm(p2 - p1))
        if chord_len < 1e-9:
            raise SolverException("E201", f"Cable {cable_id}: end nodes are coincident.")

        L0_total = chord_len
        solve_result = None
        if solve_cable_geometry is not None:
            try:
                target_type = c.get('target_type', 'Cable - Undeformed Length')
                target_value = c.get('target_value', c.get('undeformed_length', chord_len))
                if target_value is None:
                    target_value = chord_len
                solve_result = solve_cable_geometry(
                    tuple(p1), tuple(p2), w_total, EA,
                    target_type, float(target_value),
                    gravity_dir=(0.0, 0.0, -1.0),
                )
                if solve_result.converged and solve_result.L0 > 1e-9:
                    L0_total = solve_result.L0
                else:
                    print(f"      [!] Cable {cable_id}: catenary target solve did not converge "
                          f"({getattr(solve_result, 'message', '')}); falling back to zero-prestress "
                          f"(natural length = chord length).")
            except Exception as e:
                print(f"      [!] Cable {cable_id}: catenary solve raised {e}; "
                      f"falling back to zero-prestress (natural length = chord length).")
        dm.cable_solve_results[cable_id] = solve_result

        n_segs = max(int(c.get('number_of_segments', 1) or 1), 1)
        L0_seg_informational = L0_total / n_segs                                                  
        L_seg_actual = chord_len / n_segs                                                               

        chain_node_ids = [c['n1_id']]
        chain_idx = [n1['idx']]
        for k in range(1, n_segs):
            t = k / n_segs
            pt = p1 + t * (p2 - p1)
            new_id = _node_id(cable_id, k)
            new_idx = len(dm.nodes)
            dm.node_id_to_idx[new_id] = new_idx
            dm.nodes.append({
                'id': new_id,
                'idx': new_idx,
                'coords': pt,
                                                                       
                'restraints': [False, False, False, False, False, False],
                'diaphragm': None,
                'spring_matrix': None,
            })
            dm.total_dofs += 6
            chain_node_ids.append(new_id)
            chain_idx.append(new_idx)
        chain_node_ids.append(c['n2_id'])
        chain_idx.append(n2['idx'])

        seg_ids = []
        for k in range(n_segs):
            seg_id = _segment_id(cable_id, k)
            seg_ids.append(seg_id)

            area_eff = area
            as_eff = float(cs.get('As', 0.0) or 0.0)
            j_eff = float(cs.get('J', 0.0) or 0.0)
            if seg_id in deactivated:
                                                                          
                area_eff *= 1e-6
                as_eff *= 1e-6
                j_eff *= 1e-6

            dm.elements.append({
                'id': seg_id,
                'node_indices': [chain_idx[k], chain_idx[k + 1]],
                'section': {
                    'mat_name': cs.get('mat_name'),
                    'A_gross': 0.0,                                      
                                                                          
                    'A': area_eff,
                    'J': max(j_eff, 1e-12),
                    'I33': float(cs.get('I', 0.0) or 0.0),
                    'I22': float(cs.get('I', 0.0) or 0.0),
                    'As2': max(as_eff, 1e-9),
                    'As3': max(as_eff, 1e-9),
                    'theta_p': 0.0,
                    'mass_mod': mods.get('Mass', 1.0),
                    'weight_mod': mods.get('Weight', 1.0),
                },
                'material': mat,
                'L_total': L_seg_actual,
                'L_clear': L_seg_actual,
                'end_off_i': 0.0,
                'end_off_j': 0.0,
                'rz_factor': 0.0,
                'beta': 0.0,
                                                                   
                'releases': [[False, False, False, False, False, False],
                             [False, False, False, False, False, False]],
                'offsets': [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]],
                '_is_cable_segment': True,
                '_cable_id': cable_id,
            })
            count_built += 1

        dm.cable_segments[cable_id] = seg_ids
        dm.cable_meta[cable_id] = {
            'w_total': w_total,
            'EA': EA,
            'L0_total': L0_total,                                                                       
            'chord_len': chord_len,                                                                             
            'n_segs': n_segs,
            'chain_node_ids': chain_node_ids,
        }

        GJ_per_seg = mat['G'] * float(cs.get('J', 0.0) or 0.0) / max(chord_len / n_segs, 1e-9)
        k_drill = max(GJ_per_seg * 0.01, 1e-3)
        if n1.get('spring_matrix') is None:
            n1['spring_matrix'] = np.zeros((6, 6))
        n1['spring_matrix'][3, 3] += k_drill

    if count_built:
        print(f"      Cables: built {count_built} truss segment(s) across {len(cables_raw)} cable(s).")

def generate_cable_self_weight_loads(dm):
    """
    Called once from DataManager._generate_cable_self_weight(), right
    after the existing _generate_self_weight(). Lumps each cable's total
    weight-per-length (self-weight + added_weight, same number already
    used to seed the catenary solve above) as NODAL loads at every
    segment break point, tributary-split, for every load pattern that
    already has sw_mult != 0 -- i.e. cables ride the same "self-weight
    patterns" convention as everything else, just via nodal lumping
    instead of member_dist (see the polygon-method note up top).

    No-op if there are no cables. Never touches dm.elements or the
    existing frame/link self-weight loads.
    """
    if not getattr(dm, 'cable_meta', None):
        return
    if 'load_patterns' not in dm.raw:
        return

    active_pattern_names = {p[0] for p in dm.load_case['patterns']}
    target_patterns = [p for p in dm.raw['load_patterns']
                        if p['name'] in active_pattern_names and p.get('sw_mult', 0) != 0]
    if not target_patterns:
        return

    count = 0
    for cable_id, meta in dm.cable_meta.items():
        chain_ids = meta['chain_node_ids']
        n_segs = meta['n_segs']
        w_total = meta['w_total']
        if w_total <= 1e-12 or n_segs < 1:
            continue

        seg_len = meta['chord_len'] / n_segs                                                            
        seg_weight = w_total * seg_len                                    

        for pat in target_patterns:
            mult = pat['sw_mult']
            fz_per_node_half = -1.0 * seg_weight * mult / 2.0

            node_load = {nid: 0.0 for nid in chain_ids}
            for k in range(n_segs):
                node_load[chain_ids[k]] += fz_per_node_half
                node_load[chain_ids[k + 1]] += fz_per_node_half

            for nid, fz in node_load.items():
                if abs(fz) <= 1e-12:
                    continue
                dm.raw.setdefault('loads', []).append({
                    'type': 'nodal',
                    'pattern': pat['name'],
                    'node_id': nid,
                    'fx': 0.0, 'fy': 0.0, 'fz': fz,
                    'mx': 0.0, 'my': 0.0, 'mz': 0.0,
                    '_is_sw': True,
                    '_is_cable_sw': True,
                    '_cable_id': cable_id,
                })
                count += 1

    if count:
        print(f"      -> Injected {count} lumped cable self-weight load record(s).")

def _axial_force_linear(dm, el, U_full):
    """
    Recovers a pin-pin truss segment's axial force straight from nodal
    displacements, WITHOUT needing the exported k/t/fef matrices. Valid
    because get_local_stiffness_matrix's axial block (rows/cols 0 & 6) has
    zero coupling to bending/torsion rows -- true regardless of releases,
    so no condensation step is needed for this specific quantity.

        N = (EA / L0_seg) * (u2 - u1) . e_chord

    where e_chord is the CURRENT (as-drawn) chord direction and u1,u2 are
    the two end nodes' translational displacement vectors.
    """
    idx_i, idx_j = el['node_indices']
    p1 = dm.nodes[idx_i]['coords']
    p2 = dm.nodes[idx_j]['coords']
    chord = p2 - p1
    L = np.linalg.norm(chord)
    if L < 1e-9:
        return 0.0
    e_x = chord / L

    u1 = U_full[idx_i * 6: idx_i * 6 + 3]
    u2 = U_full[idx_j * 6: idx_j * 6 + 3]

    EA = el['material']['E'] * el['section']['A']
    L0 = el['L_clear']
    elongation = float(np.dot(u2 - u1, e_x))
    return (EA / L0) * elongation if L0 > 1e-9 else 0.0

def check_cable_tension_state(dm, U_full):
    """
    Stage 1 post-solve check ONLY -- called from main_engine.py after the
    existing, untouched LinearSolver.solve() has already produced U_full.
    Read-only: never mutates results, never re-solves. Returns a list of
    human-readable warning strings (empty list if every segment is in
    tension), matching Stage 1's spec ("no state check, but warn").
    """
    warnings = []
    for cable_id, seg_ids in getattr(dm, 'cable_segments', {}).items():
        for seg_id in seg_ids:
            el = next((e for e in dm.elements if e['id'] == seg_id), None)
            if el is None:
                continue
            N = _axial_force_linear(dm, el, U_full)
            if N < 0:
                warnings.append(
                    f"Cable {cable_id}, segment {seg_id}: solved in COMPRESSION "
                    f"(N = {N:.2f}). Linear static has no state check -- this "
                    f"segment is physically invalid for a real cable. Run "
                    f"P-Delta or Large Displacements for tension-only behavior."
                )
    return warnings
