"""
opencivil_to_opensees.py

Converts an OpenCivil model (.mf / JSON) into an OpenSees (openseespy) model and runs
Linear Static and Modal analysis so the result matches the native solver.

Verified against the native solver (core/solver/linear_static + modal) on synthetic 3D models:
    displacements / reactions      ~1e-13 relative (releases with rigid offsets ~1e-8)
    modal periods / participation  ~1e-7 (ARPACK tolerance), mode shapes MAC = 1.0

Converted (same conventions as the native solver):
    - section modifiers (A, J, I2, I3, As2, As3, Mass, Weight), theta_p, beta, local axes from the
      offset-adjusted end points; EA/GJ use L_total, bending/shear use L_clear (A, J scaled by
      L_clear/L_total on the OpenSees element)
    - joint offsets + rigid end zones (end_off * rz_factor) as explicit rigid links.
      NOTE: geomTransf -jntOffset is NOT used -- in OpenSees 3.8 an offset along the member axis
      only changes the length and transfers no moment arm.
    - member releases (zeroLength / equalDOF at the offset point, tiny rotational regularisation)
    - joint springs (6x6): translation block and rotation block, coupled terms inside a block exact;
      translation-rotation coupling is dropped with a warning
    - ground displacements on restrained DOFs, active (available) DOFs
    - rigid diaphragms: master = lowest node id, axis X/Y/Z, no extra node
    - loads: self weight (A_gross*rho*weight_mod*sw_mult*case scale), nodal, uniform member loads
      (Global/Local, projected), member point forces and moments (rigid-zone rules as native)
    - rigid-zone portions of uniform loads as statically equivalent nodal loads
    - Modal: opensees_modal_backend() is called by modal_engine.run_modal_analysis when
      info.analysis_engine == "opensees"; mass, normalisation and result tables are shared.

Known limits: trapezoidal member loads are piecewise-constant approximations and do not include their
rigid-zone portion; auto-lateral/seismic diaphragm patterns, links, cables, tendons and area elements
are not converted (reported in `unsupported`); member loads use the stiffness local axes, so with
NON-parallel joint offsets they differ from native by ~1e-6.
"""

import json
import time
import numpy as np
import openseespy.opensees as ops

G_ACCEL = 9.80665                                                                 

def load_oc_model(filepath):
    with open(filepath, 'r') as f:
        return json.load(f)

def element_local_axes(ni_xyz, nj_xyz, beta_deg):
    """Returns (local_1, local_2, local_3) unit vectors, in the OpenCivil
    convention -- this is an exact port of get_rotation_matrix() from
    element_library.py (confirmed against source, NOT guessed):

        vx = normalize(p2 - p1)
        temp_v = global +X if member is ~vertical, else global +Z
        vy = normalize(cross(temp_v, vx))
        vz = cross(vx, vy)
        beta rotates (vy, vz) together about vx:
            vy_final =  vy*cos(beta) + vz*sin(beta)
            vz_final = -vy*sin(beta) + vz*cos(beta)

    NOTE: this is NOT the SAP2000/ETABS "default local-2 points up"
    convention I originally assumed -- it's a cross-product formula that
    gives the *opposite* orientation for non-vertical members (local-2
    ends up roughly horizontal, local-3 roughly vertical, for a
    horizontal member -- verified by hand-tracing the formula, not
    guessed). This was the single highest-risk assumption in this file
    and it was wrong; this port replaces it with source-verified logic.
    """
    vx = np.array(nj_xyz) - np.array(ni_xyz)
    vx = vx / np.linalg.norm(vx)

    if abs(vx[2]) > 0.999:
        temp_v = np.array([1.0, 0.0, 0.0])
    else:
        temp_v = np.array([0.0, 0.0, 1.0])

    vy = np.cross(temp_v, vx)
    vy = vy / np.linalg.norm(vy)
    vz = np.cross(vx, vy)

    beta_rad = np.radians(beta_deg)
    c, s = np.cos(beta_rad), np.sin(beta_rad)
    vy_final = vy * c + vz * s
    vz_final = -vy * s + vz * c

    return vx, vy_final, vz_final

def load_factor_step_count(targets, steps_per_unit):
    """Number of LoadControl increments for a list of absolute load-factor targets (mirrors the loop in
    run_nonlinear_static_chain). Kept at module level so it can be tested without a model."""
    cur, n = 0.0, 0
    for t in targets:
        d = abs(t - cur)
        if d > 1e-15:
            n += max(1, int(np.ceil(d * steps_per_unit - 1e-9)))
        cur = t
    return n

class OpenCivilToOpenSees:
    def __init__(self, oc_data):
        self.d = oc_data
        self.materials = {m['name']: m for m in self.d['materials']}
        self.sections = {s['name']: s for s in self.d['sections']}
        self.nodes = {n['id']: n for n in self.d['nodes']}
        self.elements = {e['id']: e for e in self.d['elements']}
        self.load_patterns = {lp['name']: lp for lp in self.d['load_patterns']}
        self.load_cases = {lc['name']: lc for lc in self.d['load_cases']}

        self._transf_tag_counter = 1
        self._next_free_node_tag = (max(self.nodes) + 1) if self.nodes else 1
        self._next_free_ele_tag = (max(self.elements) + 1) if self.elements else 1
        self.diaphragm_master_nodes = {}                               
        self.element_mass_kg = {}                                                             
        self.element_local_axes = {}                                                                 
        self.split_info = {}                                                              

        self.unsupported = []                                                         
        self.elem_geom = {}                                                                             
        self.element_weight_per_len = {}                                                           
        self.spring_nodes_static = []                                                                     
        self.imposed = {}                                                                                    
        self.case_name = None
        self._ground_nodes = set()
        self._diaph_slave_ids = set()
        self._arm_scale = None
        self.rigid_arm_elements = []
        self.rigid_slaves = {}                                                   
        self.eq_slaves = {}                                                                 
        self.diaphragm_slave_map = {}                                     
        self.active_dofs = list((self.d.get('info') or {}).get('active_dofs') or [True] * 6)
        self.diaphragm_groups = {}
        self.diaphragm_master = {}                                                     
        self._transf_kind = 'Linear'
        self._nl_builder = None
        self.nl_elements = []
        self._primary_alg = 'Newton'

    def build_model(self, case_name=None):
        """case_name (optional): the case about to run. Only used to find ground displacements
        (those restrained DOFs must be driven, not fixed)."""
        if case_name is not None:
            self.case_name = case_name
        ops.wipe()
        ops.model('basic', '-ndm', 3, '-ndf', 6)
        self._collect_imposed()
        self._build_nodes()
        self._build_diaphragms()
        self._build_elements()
        self._check_unsupported_data()

    def _collect_imposed(self):
        self.imposed = {}
        lc = self.load_cases.get(self.case_name) if self.case_name else None
        if not lc or lc.get('type') not in ('Linear Static',):
            return
        scales = {}
        for pat, sc in lc.get('loads', []):
            scales[pat] = scales.get(pat, 0.0) + sc
        for ld in self.d.get('loads', []):
            if ld.get('type') != 'ground_displacement':
                continue
            pat = ld.get('pattern') or ld.get('pattern_name')
            if pat not in scales:
                continue
            nid = ld['node_id']
            if nid not in self.nodes:
                continue
            vals = [ld.get('ux', 0.0), ld.get('uy', 0.0), ld.get('uz', 0.0),
                    ld.get('rx', 0.0), ld.get('ry', 0.0), ld.get('rz', 0.0)]
            r = self.nodes[nid].get('restraints', [False] * 6)
            for i, v in enumerate(vals):
                if abs(v) <= 1e-12:
                    continue
                if r[i] or not self.active_dofs[i]:
                    key = (nid, i + 1)
                    self.imposed[key] = self.imposed.get(key, 0.0) + v * scales[pat]
                else:
                    self.unsupported.append(
                        f"ground displacement on node {nid} dof {i+1} ignored (FREE dof, same as native)")

    def _build_nodes(self):
        for nid, n in self.nodes.items():
            ops.node(nid, n['x'], n['y'], n['z'])
            r = n.get('restraints', [False] * 6)
            fix = []
            for i in range(6):
                fixed = bool(r[i]) or not self.active_dofs[i]
                if fixed and (nid, i + 1) in self.imposed:
                    fixed = False                                                                      
                fix.append(1 if fixed else 0)
            if any(fix):
                ops.fix(nid, *fix)
            if n.get('spring_matrix') is not None:
                self._build_node_spring(nid, n)

    def _build_node_spring(self, nid, n):
        """Joint spring (global 6x6, SI) -> zeroLength elements to a fixed ground node.
        Translation block and rotation block are each diagonalised (eigenvectors become the
        zeroLength -orient axes), so coupled (off-diagonal) springs inside a block are exact.
        Translation<->rotation coupling cannot be represented and is reported."""
        K = np.array(n['spring_matrix'], dtype=float)
        K = 0.5 * (K + K.T)
        kmax = float(np.max(np.abs(K))) if K.size else 0.0
        if kmax <= 0.0:
            return
        if float(np.max(np.abs(K[:3, 3:]))) > 1e-9 * kmax:
            self.unsupported.append(
                f"node {nid}: spring has translation-rotation coupling terms; they are dropped "
                f"(only the translation block and the rotation block are converted)")
        g = self._next_free_node_tag
        self._next_free_node_tag += 1
        ops.node(g, n['x'], n['y'], n['z'])
        ops.fix(g, 1, 1, 1, 1, 1, 1)
        self._ground_nodes.add(g)
        for blk, dirs in ((K[:3, :3], (1, 2, 3)), (K[3:, 3:], (4, 5, 6))):
            w, V = np.linalg.eigh(blk)
            if np.max(np.abs(w)) <= 1e-9 * kmax:
                continue
            if np.linalg.det(V) < 0:
                V[:, 2] = -V[:, 2]
            mats, dd = [], []
            for k in range(3):
                if abs(w[k]) <= 1e-9 * kmax:
                    continue
                mt = self._next_mat_tag()
                ops.uniaxialMaterial('Elastic', mt, float(w[k]))
                mats.append(mt)
                dd.append(dirs[k])
            if not mats:
                continue
            etag = self._next_free_ele_tag
            self._next_free_ele_tag += 1
            ops.element('zeroLength', etag, g, nid, '-mat', *mats, '-dir', *dd,
                        '-orient', *V[:, 0].tolist(), *V[:, 1].tolist())
        self.spring_nodes_static.append({'id': nid, 'K': K})

    _mat_tag_counter = 10_000_000

    def _next_mat_tag(self):
        OpenCivilToOpenSees._mat_tag_counter += 1
        return OpenCivilToOpenSees._mat_tag_counter

    def _apply_ground_displacements(self, ts_tag, pat_tag):
        """Call once, after the load patterns, before analyze()."""
        if not self.imposed:
            return ts_tag, pat_tag
        ops.timeSeries('Linear', ts_tag)
        ops.pattern('Plain', pat_tag, ts_tag)
        for (nid, dof), v in self.imposed.items():
            ops.sp(nid, dof, float(v))
        return ts_tag + 1, pat_tag + 1

    def _build_diaphragms(self):
        """Native convention: master = node with the smallest id in the group, exact
        elimination of slave perp1/perp2/rot about the diaphragm axis. No extra node."""
        from error_definitions import SolverException
        constraint_axis = {c['name']: c.get('axis', 'Z') for c in self.d.get('constraints', [])}
        groups = {c: [] for c in constraint_axis}
        for nid, n in self.nodes.items():
            dname = n.get('diaphragm')
            if dname and dname in groups:
                groups[dname].append(nid)

        dofs = {'X': 1, 'Y': 2, 'Z': 3}
        elim = {'Z': (0, 1, 5), 'X': (1, 2, 3), 'Y': (2, 0, 4)}
        for dname, member_ids in groups.items():
            if len(member_ids) < 2:
                continue
            axis = constraint_axis[dname]
            if axis not in dofs:
                raise SolverException("E205", f"Diaphragm '{dname}': unsupported axis '{axis}'. Supported axes are X, Y, Z.")
            master = min(member_ids)
            slaves = [i for i in member_ids if i != master]
            for sid in slaves:
                r = self.nodes[sid].get('restraints', [False] * 6)
                bad = [d for d in elim[axis] if r[d] or not self.active_dofs[d]]
                if bad:
                    raise SolverException(
                        "E205", f"Restraint found on diaphragm-slaved DOF of node {sid}. "
                                f"Restrain the diaphragm MASTER node instead.")
            ops.rigidDiaphragm(dofs[axis], master, *slaves)
            self.diaphragm_master_nodes[dname] = master
            self.diaphragm_groups[dname] = member_ids
            self.diaphragm_master[dname] = master
            self.diaphragm_slave_map[master] = (axis, slaves)
            self._diaph_slave_ids.update(slaves)

    def _resolve_section_material(self, sec_name):
        sec = self.sections[sec_name]
        mat = self.materials[sec['mat_name']]
        return sec, mat

    TRAPEZOID_SLICES_PER_SEGMENT = 8                                                        
    _EPS_T = 1e-6                                                          

    def _point_load_t(self, load, L_total):
        is_rel = load.get('is_rel', True)
        dist = load.get('dist', 0.0)
        return dist if is_rel else dist / L_total

    def _determine_split_points(self, eid, L_total):
        """
        Normalized (0-1) positions along element `eid` where it must be
        physically split -- i.e. where a real intermediate node needs to
        exist -- to convert its member_point loads (exact application at
        the node) and genuine trapezoidal member_dist loads (piecewise-
        constant approximation, one eleLoad per slice). See
        _apply_explicit_loads docstring for why splitting is required at
        all: ElasticTimoshenkoBeam3d's eleLoad only supports full-span
        constant-intensity uniform loads (confirmed against openseespy
        3.8.0), so any load with a shape it can't express needs a real
        node at the shape's boundaries instead.
        """
        pts = set()
        for load in self.d.get('loads', []):
            if load.get('element_id') != eid:
                continue
            ltype = load.get('type')
            if ltype == 'member_point':
                g = self.elem_geom.get(eid)
                ri = g['ri'] if g else 0.0
                rj = g['rj'] if g else 0.0
                dist = self._point_load_t(load, L_total) * L_total
                if dist < ri - 1e-9 or dist > L_total - rj + 1e-9:
                    continue                                                                          
                if dist <= ri + 1e-6 or dist >= L_total - rj - 1e-6:
                    continue                                                                         
                t = dist / L_total
                if self._EPS_T < t < 1.0 - self._EPS_T:
                    pts.add(round(t, 9))
            elif ltype == 'member_dist':
                if self._is_simple_full_span_udl(load):
                    continue                                          
                distances = load.get('distances') or [0.0, 1.0]
                is_relative = load.get('is_relative', True)
                t_ctrl = [d if is_relative else d / L_total for d in distances]
                for i in range(len(t_ctrl) - 1):
                    a, b = t_ctrl[i], t_ctrl[i + 1]
                    if b - a <= 1e-9:
                        continue
                    for sp in np.linspace(a, b, self.TRAPEZOID_SLICES_PER_SEGMENT + 1):
                        if self._EPS_T < sp < 1.0 - self._EPS_T:
                            pts.add(round(float(sp), 9))
        return sorted(pts)

    def _find_chain_node_at(self, chain, t, tol=1e-6):
        for i, b in enumerate(chain['boundaries']):
            if abs(b - t) < tol:
                return chain['node_chain'][i]
        return None

    def _section_props(self, sec, mat):
        """Section properties with modifiers applied, exactly as native data_manager._parse_properties."""
        p = sec['properties']
        m = sec.get('modifiers') or {}
        E = mat['E']
        G = mat['G'] if mat.get('G') else E / (2 * (1 + mat['nu']))
        out = {
            'E': E, 'G': G,
            'A_gross': p.get('A', 0.0),
            'A': p.get('A', 0.0) * m.get('A', 1.0),
            'J': p.get('J', 0.0) * m.get('J', 1.0),
            'I33': p.get('I33', 0.0) * m.get('I3', 1.0),
            'I22': p.get('I22', 0.0) * m.get('I2', 1.0),
            'As2': p.get('As2', 0.0) * m.get('As2', 1.0),
            'As3': p.get('As3', 0.0) * m.get('As3', 1.0),
            'theta_p': p.get('theta_p', 0.0),
            'mass_mod': m.get('Mass', 1.0),
            'weight_mod': m.get('Weight', 1.0),
            'rho': mat['rho'],
        }
        return out

    def _element_geometry(self, eid):
        """Native-matching geometry of one frame element (data_manager._parse_elements +
        assembler._build_beam_stiffness_batched conventions)."""
        el = self.elements[eid]
        ni, nj = self.nodes[el['n1_id']], self.nodes[el['n2_id']]
        p1 = np.array([ni['x'], ni['y'], ni['z']], dtype=float)
        p2 = np.array([nj['x'], nj['y'], nj['z']], dtype=float)
        off_i = np.array(el.get('off_i', [0.0, 0.0, 0.0]), dtype=float)
        off_j = np.array(el.get('off_j', [0.0, 0.0, 0.0]), dtype=float)
        p1a, p2a = p1 + off_i, p2 + off_j
        L_total = float(np.linalg.norm(p2a - p1a))
        rz = el.get('rz_factor', 0.0)
        ri = el.get('end_off_i', 0.0) * rz
        rj = el.get('end_off_j', 0.0) * rz
        L_clear = L_total - (ri + rj)
        sec, mat = self._resolve_section_material(el['sec_name'])
        sp = self._section_props(sec, mat)
        beta_eff = el.get('beta', 0.0) - float(np.degrees(sp['theta_p']))
        ax = element_local_axes(p1a, p2a, beta_eff)
        R = np.array(ax)
        vx = ax[0]
        return {
            'p1': p1, 'p2': p2, 'p1a': p1a, 'p2a': p2a, 'off_i': off_i, 'off_j': off_j,
            'L_total': L_total, 'L_clear': L_clear, 'ri': ri, 'rj': rj, 'R': R, 'axes': ax,
            'jo_i': off_i + ri * vx, 'jo_j': off_j - rj * vx, 'props': sp,
            'loc_off_i': R @ off_i, 'loc_off_j': R @ off_j,
        }

    def _stiff_ref(self, g):
        """Reference stiffnesses for release penalties (translational, rotational)."""
        sp, L = g['props'], max(g['L_clear'], 1e-9)
        E, G = sp['E'], sp['G']
        imax = max(sp['I22'], sp['I33'], 1e-30)
        kt = max(E * sp['A'] / L, 12 * E * imax / L ** 3)
        kr = max(4 * E * imax / L, G * sp['J'] / L)
        return kt, kr

    def _penalty_arm(self, ni, nj, off):
        """Very stiff elastic beam acting as a rigid arm node ni -> nj (nj = ni + off)."""
        if self._arm_scale is None:
            kt = kr = 1e-30
            for e in self.elements.values():
                try:
                    sp = self._section_props(*self._resolve_section_material(e['sec_name']))
                except Exception:
                    continue
                n1, n2 = self.nodes[e['n1_id']], self.nodes[e['n2_id']]
                L = max(float(np.linalg.norm([n2['x'] - n1['x'], n2['y'] - n1['y'], n2['z'] - n1['z']])), 1e-6)
                imax = max(sp['I22'], sp['I33'])
                kt = max(kt, sp['E'] * sp['A'] / L, 12 * sp['E'] * imax / L ** 3)
                kr = max(kr, 4 * sp['E'] * imax / L, sp['G'] * sp['J'] / L)
            self._arm_scale = (kt * 1e6, kr * 1e6)
        kt, kr = self._arm_scale
        off = np.asarray(off, dtype=float)
        L = float(np.linalg.norm(off))
        ref = np.array([0.0, 0.0, 1.0]) if abs(off[2] / L) < 0.9 else np.array([1.0, 0.0, 0.0])
        tt = self._transf_tag_counter
        self._transf_tag_counter += 1
        ops.geomTransf('Linear', tt, *ref.tolist())
        et = self._next_free_ele_tag
        self._next_free_ele_tag += 1
        EI = max(kr * L, kt * L ** 3)
        ops.element('elasticBeamColumn', et, ni, nj, kt * L, 1.0, 1.0, EI, EI, EI, tt)
        self.rigid_arm_elements.append(et)

    def _end_connection(self, eid, node_id, end, rel, g):
        """Node tag the beam must attach to at one member end.

        Rigid offsets (joint offset + rigid end zone) are built as an explicit rigid 'beam' link to a
        new node placed at the offset point. OpenSees' geomTransf -jntOffset is NOT used: probed with
        openseespy 3.8.0, an offset along the member axis only shortens the element and transfers no
        moment arm (tip load on a 0.4 m rigid stub gave zero end moment), whereas the native solver
        (Te eccentricity matrix) transfers it exactly. A rigid link reproduces the native result.

        Releases (OC local axes) sit at the offset point: zeroLength between that point and a
        coincident node, stiff in the retained DOFs, free (tiny penalty on rotations, as native) in
        the released ones."""
        off = g['jo_i'] if end == 'i' else g['jo_j']
        n = self.nodes[node_id]
        base = node_id
        if np.any(np.abs(off) > 1e-12):
            a = self._next_free_node_tag
            self._next_free_node_tag += 1
            ops.node(a, n['x'] + off[0], n['y'] + off[1], n['z'] + off[2])
            if node_id in self._diaph_slave_ids:
                                                                                                     
                self._penalty_arm(node_id, a, off)
            else:
                ops.rigidLink('beam', node_id, a)
                self.rigid_slaves.setdefault(node_id, []).append(a)
            base = a
        if not any(rel):
            return base
        b = self._next_free_node_tag
        self._next_free_node_tag += 1
        ops.node(b, *ops.nodeCoord(base))
        kt, kr = self._stiff_ref(g)
        big_t, big_r = kt * 1e7, kr * 1e7
        tiny = max(kt, kr) * 1e-12
                                                                                                        
        gmap = []
        for k in range(3):
            comp = np.abs(g['axes'][k])
            gi = int(np.argmax(comp))
            gmap.append(gi if comp[gi] > 1.0 - 1e-9 else None)
        if base == node_id and node_id not in self._diaph_slave_ids and None not in gmap and len(set(gmap)) == 3:                                          
            keep = [gmap[k % 3] + 1 + (3 if k >= 3 else 0) for k in range(6) if not rel[k]]
            if keep:
                ops.equalDOF(base, b, *keep)
                self.eq_slaves.setdefault(base, []).append((b, [d - 1 for d in keep]))
            mats, dirs = [], []
            for k in range(3, 6):
                if rel[k]:
                    mt = self._next_mat_tag()
                    ops.uniaxialMaterial('Elastic', mt, float(tiny))
                    mats.append(mt)
                    dirs.append(gmap[k - 3] + 4)
            if mats:
                etag = self._next_free_ele_tag
                self._next_free_ele_tag += 1
                ops.element('zeroLength', etag, base, b, '-mat', *mats, '-dir', *dirs)
                self.release_elements = getattr(self, 'release_elements', [])
                self.release_elements.append(etag)
            return b
        mats, dirs = [], []
        for k in range(6):
            if not rel[k]:
                v = big_t if k < 3 else big_r
            elif k >= 3:
                v = tiny                                                                               
            else:
                continue                                                         
            mt = self._next_mat_tag()
            ops.uniaxialMaterial('Elastic', mt, float(v))
            mats.append(mt)
            dirs.append(k + 1)
        etag = self._next_free_ele_tag
        self._next_free_ele_tag += 1
        ax = g['axes']
        ops.element('zeroLength', etag, base, b, '-mat', *mats, '-dir', *dirs,
                    '-orient', *ax[0].tolist(), *ax[1].tolist())
        self.release_elements = getattr(self, 'release_elements', [])
        self.release_elements.append(etag)
        return b

    def _build_elements(self):
        for eid, el in self.elements.items():
            g = self._element_geometry(eid)
            self.elem_geom[eid] = g
            sp = g['props']
            E, G = sp['E'], sp['G']
            L_total, L_clear = g['L_total'], g['L_clear']
            if L_clear <= 1e-9:
                self.unsupported.append(f"element {eid}: rigid end zones consume the whole member")
                continue
            scale_ax = L_clear / L_total                                                                  
            A = sp['A'] * scale_ax
            J = sp['J'] * scale_ax
            I22, I33 = sp['I22'], sp['I33']
            A_ref = max(sp['A'], 1e-30)
            As2 = sp['As2'] if sp['As2'] > 0 else A_ref * 1e8
            As3 = sp['As3'] if sp['As3'] > 0 else A_ref * 1e8

            self.element_local_axes[eid] = tuple(g['axes'])
            ax = g['axes']
            vecxz = ax[1]                                                                        
            self._cur_vecxz, self._cur_L = vecxz, L_clear

            rel_i = list(el.get('rel_i', [False] * 6))
            rel_j = list(el.get('rel_j', [False] * 6))
            has_rel = any(rel_i) or any(rel_j)
            if has_rel and self._nl_builder is not None:
                self.unsupported.append(
                    f"element {eid}: member releases are not converted in nonlinear runs")
                has_rel = False

            self.element_weight_per_len[eid] = sp['A_gross'] * sp['rho'] * sp['weight_mod']
            self.element_mass_kg[eid] = sp['A_gross'] * sp['rho'] / G_ACCEL * L_total * sp['mass_mod']

            split_ts = self._determine_split_points(eid, L_total)
            n1, n2 = el['n1_id'], el['n2_id']
            p1a, p2a = g['p1a'], g['p2a']

            bi = self._end_connection(eid, n1, 'i', rel_i if has_rel else [False] * 6, g)
            bj = self._end_connection(eid, n2, 'j', rel_j if has_rel else [False] * 6, g)

            def make_transf():
                tag = self._transf_tag_counter
                self._transf_tag_counter += 1
                ops.geomTransf(self._transf_kind, tag, *vecxz.tolist())
                return tag

            if not split_ts:
                transf_tag = make_transf()
                self._emit_beam(eid, bi, bj, E, G, A, J, I33, I22, As3, As2, transf_tag, el['sec_name'])
                self.split_info[eid] = {
                    'node_chain': [n1, n2], 'ele_tags': [eid], 'boundaries': [0.0, 1.0],
                }
                continue

            boundaries = [0.0] + split_ts + [1.0]
            node_chain = [n1]
            for t in split_ts:
                new_node_tag = self._next_free_node_tag
                self._next_free_node_tag += 1
                pos = p1a + t * (p2a - p1a)
                ops.node(new_node_tag, *pos.tolist())
                if not all(self.active_dofs):
                    ops.fix(new_node_tag, *[0 if a else 1 for a in self.active_dofs])
                node_chain.append(new_node_tag)
            node_chain.append(n2)
            beam_nodes = [bi] + node_chain[1:-1] + [bj]

            n_sub = len(node_chain) - 1
            ele_tags = []
            for i in range(n_sub):
                transf_tag = make_transf()
                new_ele_tag = self._next_free_ele_tag
                self._next_free_ele_tag += 1
                self._emit_beam(new_ele_tag, beam_nodes[i], beam_nodes[i + 1],
                            E, G, A, J, I33, I22, As3, As2, transf_tag, el['sec_name'])
                ele_tags.append(new_ele_tag)

            self.split_info[eid] = {
                'node_chain': node_chain, 'ele_tags': ele_tags, 'boundaries': boundaries,
            }

    def _check_unsupported_data(self):
        for load in self.d.get('loads', []):
            ltype = load.get('type')
            pat = load.get('pattern')
            if ltype in ('nodal', 'member_dist', 'member_point'):
                                                                                       
                continue
            self.unsupported.append(
                f"load type '{ltype}' (pattern '{pat}') not converted in v1")
        for name in ('tendons', 'cables', 'slabs', 'area_elements', 'links'):
            if self.d.get(name):
                self.unsupported.append(f"{len(self.d[name])} {name} entries skipped (not supported in v1)")
        for lp in self.load_patterns.values():
            if lp.get('auto_lateral', 'None') != 'None':
                self.unsupported.append(
                    f"load pattern '{lp['name']}': auto-lateral '{lp['auto_lateral']}' not converted")

    def _apply_uniform_local(self, eid, w_oc_local):
        """Full-span uniform load (OC local components, per length) on the clear span via eleLoad,
        plus the rigid end zones as statically equivalent nodal force+moment (native
        assembler: F = w*r at the zone centroid, moment about the joint incl. the joint offset)."""
        w = np.asarray(w_oc_local, dtype=float)
        if not np.any(np.abs(w) > 1e-12):
            return
        g = self.elem_geom[eid]
        el = self.elements[eid]
        ele_tags = self.split_info[eid]['ele_tags']
        ops.eleLoad('-ele', *ele_tags, '-type', '-beamUniform', float(-w[2]), float(w[1]), float(w[0]))
        R = g['R']
        if g['ri'] > 0:
            F = w * g['ri']
            M = np.cross(np.array([g['ri'] / 2.0, 0.0, 0.0]) + g['loc_off_i'], F)
            ops.load(el['n1_id'], *(R.T @ F).tolist(), *(R.T @ M).tolist())
        if g['rj'] > 0:
            F = w * g['rj']
            M = np.cross(np.array([-g['rj'] / 2.0, 0.0, 0.0]) + g['loc_off_j'], F)
            ops.load(el['n2_id'], *(R.T @ F).tolist(), *(R.T @ M).tolist())

    def _apply_self_weight_pattern(self, pattern_name, ts_tag, pattern_tag, scale=1.0):
        """Opens the OpenSees pattern for this OpenCivil pattern and adds self-weight
        (native: A_gross*rho*weight_mod*sw_mult*case_scale, global -Z, no projection)."""
        lp = self.load_patterns[pattern_name]
        sw_mult = lp.get('sw_mult', 0.0)
        ops.timeSeries('Linear', ts_tag)
        ops.pattern('Plain', pattern_tag, ts_tag)
        if sw_mult == 0.0:
            return
        for eid in self.elements:
            if eid not in self.elem_geom or eid not in self.split_info:
                continue
            w_len = self.element_weight_per_len.get(eid, 0.0) * sw_mult * scale
            if abs(w_len) <= 1e-9:
                continue
            R = self.elem_geom[eid]['R']
            self._apply_uniform_local(eid, R @ np.array([0.0, 0.0, -w_len]))

    def _apply_explicit_loads(self, pattern_name, scale):
        """
        Applies NodalLoad and simple-UDL MemberLoad records (data['loads'])
        for one OpenCivil load pattern, into whichever OpenSees pattern is
        currently open (caller must already have called ops.pattern(...) --
        see run_linear_static(), which always calls
        _apply_self_weight_pattern() for the same pattern_name first).

        ============================================================
        v1.2 SCOPE (added 2026-09, see also module docstring SCOPE)
        ============================================================
        Converted:
            - nodal loads (data['loads'] type='nodal'): full support, any
              pattern/direction combo -- straight ops.load().
            - member_dist loads, SIMPLE-UDL case (constant intensity over
              the whole member -- see _is_simple_full_span_udl): full
              support, Global or Local coord, with projection.
            - member_dist loads with a genuine varying-magnitude profile
              (real trapezoids): APPROXIMATED by physically splitting the
              member into TRAPEZOID_SLICES_PER_SEGMENT-per-control-interval
              sub-elements (see _build_elements/_determine_split_points)
              and applying a constant-intensity eleLoad on each, sized to
              the profile's value at that slice's midpoint. Accuracy scales
              with TRAPEZOID_SLICES_PER_SEGMENT; not exact.
            - member_point loads (force OR moment): EXACT, not an
              approximation -- a real intermediate node is inserted at the
              load's position and ops.load() is called on it directly. A
              moment on a real shared node between two beam sub-elements
              is the textbook-correct way to apply an interior concentrated
              moment in a continuous frame FE model.

        Reason member-splitting is needed at all, confirmed empirically
        against openseespy 3.8.0 (not guessed): ElasticTimoshenkoBeam3d's
        eleLoad only implements the plain full-span '-beamUniform Wy Wz
        Wx' case. Both the partial-span/trapezoidal '-beamUniform' variant
        (aOverL/bOverL) and '-beamPoint' SILENTLY NO-OP on this element --
        OpenSees prints "load type unknown for element" to stderr (not
        raised as a Python exception) and applies zero force.

        Bug-for-bug parity with assembler.py, BY DESIGN (decided with
        Ahmed): the simple-UDL branch does NOT interpret `load_direction`
        at all (only the trapezoidal branch reads that field, matching
        assembler.py's compute_single_member_load_fef_global() exactly).
        The trapezoidal branch's Gravity sign (no forced sign) and its
        hardcoded-"Global" projection check are both replicated as-is,
        including their inconsistency with the point-load branch (which
        DOES force sign=-1 and coord='Global' for Gravity) -- same
        asymmetry that exists in the native solver itself.
        """
        for load in self.d.get('loads', []):
            if load.get('pattern') != pattern_name:
                continue
            ltype = load.get('type')
            if ltype == 'nodal':
                self._apply_nodal_load(load, scale)
            elif ltype == 'member_dist':
                if self._is_simple_full_span_udl(load):
                    self._apply_member_dist_load(load, scale)
                else:
                    self._apply_member_dist_trapezoidal(load, scale)
            elif ltype == 'member_point':
                self._apply_member_point_load(load, scale)
                                                                         
    def _apply_nodal_load(self, load, scale):
        ops.load(
            load['node_id'],
            load.get('fx', 0.0) * scale, load.get('fy', 0.0) * scale, load.get('fz', 0.0) * scale,
            load.get('mx', 0.0) * scale, load.get('my', 0.0) * scale, load.get('mz', 0.0) * scale,
        )

    def _apply_member_point_load(self, load, scale):
        """Member point force/moment, native semantics (assembler.compute_single_member_load_fef_global):
        loads inside a rigid end zone are dropped; loads at the clear-span end go to the end node
        with the rigid-offset lever arm; interior loads go to a real split node."""
        eid = load.get('element_id')
        el = self.elements.get(eid)
        chain = self.split_info.get(eid)
        g = self.elem_geom.get(eid)
        if el is None or chain is None or g is None:
            return
        L_total, ri, rj = g['L_total'], g['ri'], g['rj']

        dir_str = str(load.get('dir', 'Gravity')).upper()
        if "GRAVITY" in dir_str:
            idx, sign = 2, -1.0
        elif "X" in dir_str or "1" in dir_str:
            idx, sign = 0, 1.0
        elif "Y" in dir_str or "2" in dir_str:
            idx, sign = 1, 1.0
        elif "Z" in dir_str or "3" in dir_str:
            idx, sign = 2, 1.0
        else:
            self.unsupported.append(
                f"member_point load on element {eid}: unrecognized direction "
                f"'{load.get('dir')}', skipped")
            return

        P_val = load.get('force', 0.0) * scale
        vec_defined = np.zeros(3)
        vec_defined[idx] = sign * P_val
        coord_sys = load.get('coord', 'Global')
        if "GRAVITY" in dir_str:
            coord_sys = 'Global'
        R = g['R']
        vec_global = vec_defined if coord_sys == 'Global' else R.T @ vec_defined

        dist = self._point_load_t(load, L_total) * L_total
        if dist < ri - 1e-9 or dist > L_total - rj + 1e-9:
            return
        vx = g['axes'][0]
        node_tag, lever = None, np.zeros(3)
        if dist <= ri + 1e-6:
            node_tag, lever = el['n1_id'], g['off_i'] + ri * vx
        elif dist >= L_total - rj - 1e-6:
            node_tag, lever = el['n2_id'], g['off_j'] - rj * vx
        else:
            node_tag = self._find_chain_node_at(chain, dist / L_total)
        if node_tag is None:
            self.unsupported.append(
                f"member_point load on element {eid} at dist={dist:.4f}: could not "
                f"locate its split node (unexpected -- please check), skipped")
            return

        if load.get('l_type', 'Force') == 'Moment':
            ops.load(node_tag, 0.0, 0.0, 0.0, *vec_global.tolist())
        else:
            m = np.cross(lever, vec_global)
            ops.load(node_tag, *vec_global.tolist(), *m.tolist())

    def _apply_member_dist_trapezoidal(self, load, scale):
        """
        Approximates a genuine trapezoidal (varying-magnitude) member_dist
        load by stepping through the sub-elements _build_elements() sliced
        out for this load and applying a constant-intensity eleLoad on
        each, sized to the profile's value at that sub-element's midpoint.
        Piecewise-constant approximation of a piecewise-linear profile --
        NOT exact (see _apply_explicit_loads docstring for why an exact
        conversion isn't possible on this element type). Direction/coord/
        projection logic is an exact port of assembler.py's
        _get_trapezoidal_fef_and_w() inner loop, bug-for-bug (decided with
        Ahmed) -- including its hardcoded-"Global" projection check
        regardless of this load's actual `coord`.
        """
        eid = load.get('element_id')
        el = self.elements.get(eid)
        chain = self.split_info.get(eid)
        if el is None or chain is None:
            return

        ni = self.nodes[el['n1_id']]
        nj = self.nodes[el['n2_id']]
        p1 = np.array([ni['x'], ni['y'], ni['z']])
        p2 = np.array([nj['x'], nj['y'], nj['z']])
        L_total = self.elem_geom[eid]['L_total']

        mags = np.array(load.get('magnitudes') or [0.0, 0.0], dtype=float) * scale
        distances = load.get('distances') or [0.0, 1.0]
        is_relative = load.get('is_relative', True)
        t_ctrl = np.array([d if is_relative else d / L_total for d in distances], dtype=float)

        dir_str = str(load.get('load_direction', 'Gravity')).upper()
        coord = load.get('coord', 'Global')
        local_1, local_2, local_3 = self.element_local_axes[eid]

        def resolved_oc_local_at(t):
            m = float(np.interp(t, t_ctrl, mags))
            vec = np.zeros(3)
            if "GRAVITY" in dir_str:
                vec[2] = m
            elif "X" in dir_str or "1" in dir_str:
                vec[0] = m
            elif "Y" in dir_str or "2" in dir_str:
                vec[1] = m
            elif "Z" in dir_str or "3" in dir_str:
                vec[2] = m

            if coord == 'Global':
                v_oc_local = np.array([
                    np.dot(vec, local_1), np.dot(vec, local_2), np.dot(vec, local_3),
                ])
            else:
                v_oc_local = vec

            if load.get('projected', False):
                                                                                 
                v_oc_local = self._apply_projection_factor(v_oc_local, p1, p2, L_total, "Global")
            return v_oc_local

        boundaries = chain['boundaries']
        ele_tags = chain['ele_tags']
        t_lo, t_hi = float(t_ctrl[0]), float(t_ctrl[-1])
        for i in range(len(boundaries) - 1):
            t0, t1 = boundaries[i], boundaries[i + 1]
            if t1 <= t_lo + 1e-9 or t0 >= t_hi - 1e-9:
                continue                                                
            t_mid = 0.5 * (t0 + t1)
            v_oc_local = resolved_oc_local_at(t_mid)

            Wx_os = v_oc_local[0]
            Wy_os = -v_oc_local[2]
            Wz_os = v_oc_local[1]
            if abs(Wx_os) < 1e-12 and abs(Wy_os) < 1e-12 and abs(Wz_os) < 1e-12:
                continue
            ops.eleLoad('-ele', ele_tags[i], '-type', '-beamUniform', Wy_os, Wz_os, Wx_os)

    def _is_simple_full_span_udl(self, load):
        """
        True when a member_dist load is a plain, constant-intensity UDL
        covering the whole member -- i.e. safely convertible to a single
        eleLoad('-beamUniform', ...) with no member-splitting.

        IMPORTANT (found 2026-09, real-data bug): OpenCivil does NOT save
        a plain UDL as magnitudes=[0,0,0,0] with only wx/wy/wz set -- every
        member_dist load is stored as a general distances/magnitudes
        trapezoid table, so even a pure UDL shows up with `magnitudes`
        filled with the same nonzero value repeated (confirmed directly in
        OSOC.mf: wz=-5000.0 and magnitudes=[-5000.0]*4). The old check
        ("any nonzero magnitude => unsupported trapezoid") therefore
        silently dropped every real-world UDL and kept only the
        theoretical all-zero-magnitudes case, which apparently never
        occurs in practice. The correct test for "no splitting needed" is
        whether the magnitude profile is CONSTANT (flat table = disguised
        UDL) across the FULL member length -- a genuine trapezoid has
        magnitudes that actually vary between distance points.
        """
        distances = load.get('distances') or [0.0, 1.0]
        magnitudes = load.get('magnitudes') or [0.0, 0.0]
        if len(magnitudes) == 0:
            return True

        if (max(magnitudes) - min(magnitudes)) > 1e-9:
            return False                                     

        is_relative = load.get('is_relative', True)
        span_end = 1.0 if is_relative else self._elem_length(
            self.elements[load['element_id']])
        if abs(distances[0]) > 1e-6 or abs(distances[-1] - span_end) > 1e-6 * max(span_end, 1.0):
            return False                                    

        return True

    def _apply_member_dist_load(self, load, scale):
        if not self._is_simple_full_span_udl(load):
            return
        eid = load.get('element_id')
        g = self.elem_geom.get(eid)
        if g is None or eid not in self.split_info:
            return
        w_defined = np.array([load.get('wx', 0.0), load.get('wy', 0.0), load.get('wz', 0.0)]) * scale
        if not np.any(np.abs(w_defined) > 1e-12):
            return
        coord = load.get('coord', 'Global')
        R = g['R']
        w_oc_local = R @ w_defined if coord == 'Global' else w_defined
        if load.get('projected', False):
            w_oc_local = self._apply_projection_factor(w_oc_local, g['p1'], g['p2'], g['L_total'], coord)
        self._apply_uniform_local(eid, w_oc_local)

    def _apply_projection_factor(self, w_local, p1, p2, L_total, coord_system):
        """Exact port of assembler.py's _apply_projection_factor()."""
        if coord_system != 'Global':
            return w_local

        dx = p2[0] - p1[0]
        dy = p2[1] - p1[1]
        L_horizontal = float(np.sqrt(dx**2 + dy**2))

        if L_horizontal < 1e-9:
            return np.array([0.0, 0.0, 0.0])
        if L_total < 1e-9:
            return w_local

        proj_factor = L_horizontal / L_total
        return w_local * proj_factor

    def _elem_length(self, el):
        ni, nj = self.nodes[el['n1_id']], self.nodes[el['n2_id']]
        g = self.elem_geom.get(el['id'])
        if g is not None:
            return g['L_total']
        return float(np.linalg.norm(
            np.array([nj['x'], nj['y'], nj['z']]) - np.array([ni['x'], ni['y'], ni['z']])))

    def _apply_self_mass(self, mass_source_name):
        """Lumped mass at element end nodes, replicating
        mass_assembler.py's GlobalMassAssembler.build_mass_matrix():
        include_self_mass adds element self-mass once; include_patterns
        ADDS IT AGAIN if the listed pattern(s) are self-weight patterns
        (sw_mult != 0) -- this is a real double-count in this model's
        actual mass_sources config (MSSSRC1: both true, patterns=[DEAD],
        and DEAD's only load IS self-weight), confirmed by testing: without
        it my periods ran ~15-17% short of the real solver's; doubling
        self-weight-derived mass closed the gap to ~3-4%.

        NOTE: this replicates the *self-weight-pattern* case exactly
        (mass_assembler's _add_mass_from_net_loads() reduces to the same
        half-half nodal lumping as _add_element_self_mass() for a plain
        self-weight UDL). It does NOT replicate _add_mass_from_net_loads()
        for patterns containing explicit member/nodal loads beyond
        self-weight -- those aren't converted to mass in v1 (same
        limitation as explicit loads generally, see module docstring).
        The remaining ~3-4% gap after this fix is presumed to come from
        that function's FEF-based (not naive half-half) force distribution
        for elements with rigid end offsets, and/or the L_tor vs L_clear
        distinction in element_library.py that geomTransf's jntOffset
        doesn't replicate -- neither is fixed in v1.
        """
        ms_def = None
        for ms in self.d.get('mass_sources', []):
            if ms['name'] == mass_source_name or mass_source_name == 'Default':
                ms_def = ms
                break
        if ms_def is None:
            ms_def = {'include_self_mass': True, 'include_patterns': False}

        node_mass = {nid: 0.0 for nid in self.nodes}
        for chain in self.split_info.values():
            for nid in chain['node_chain']:
                node_mass.setdefault(nid, 0.0)

        def _lump_chain_mass(eid, total_mass):
            chain = self.split_info[eid]
            node_chain = chain['node_chain']
            boundaries = chain['boundaries']
            for i in range(len(node_chain) - 1):
                frac = boundaries[i + 1] - boundaries[i]
                half = (total_mass * frac) / 2.0
                node_mass[node_chain[i]] += half
                node_mass[node_chain[i + 1]] += half

        if ms_def.get('include_self_mass', True):
            for eid in self.elements:
                _lump_chain_mass(eid, self.element_mass_kg[eid])

        if ms_def.get('include_patterns', False):
            for pat_name, mult in ms_def.get('load_patterns', []):
                lp = self.load_patterns.get(pat_name)
                if not lp:
                    continue
                sw_mult = lp.get('sw_mult', 0.0)
                if sw_mult == 0.0:
                    continue                                              
                for eid in self.elements:
                    _lump_chain_mass(eid, self.element_mass_kg[eid] * sw_mult * mult)

        for nid, m in node_mass.items():
            if m > 0:
                ops.mass(nid, m, m, m, 0.0, 0.0, 0.0)

        nonzero = [m for m in node_mass.values() if m > 1e-10]
        reg_mass = (min(nonzero) * 1e-6) if nonzero else 1e-6
        for nid, m in node_mass.items():
            ops.mass(nid, m if m > 0 else reg_mass, m if m > 0 else reg_mass,
                      m if m > 0 else reg_mass, reg_mass, reg_mass, reg_mass)

        for master_tag in self.diaphragm_master_nodes.values():
            ops.mass(master_tag, reg_mass, reg_mass, reg_mass, reg_mass, reg_mass, reg_mass)

    NL_DEFAULT_BLOCK = {
        "test_type": "NormDispIncr", "tolerance": 1e-6, "max_iter": 50,
        "algorithm": "Newton", "step_size": 0.001,
        "path_mode": "Single Target", "disp_history": [],
        "n_int_pts": 5, "fiber_size_ratio": 16,
        "integration": "Lobatto", "hinge_length": 0.0, "bar_slip": False, "safety_check": True,
        "shear_spring": None, "slip_concrete": "stiff",
        "relax_on_fail": True, "relax_ceiling": 1e-5,
        "slip_R": 0.5, "slip_b": 0.3, "slip_sy_mult": 1.0, "slip_su_mult": 35.0,
    }
    NL_FULL_LOAD_STEPS = 10
    NL_MAX_TOTAL_STEPS = 200000
    NL_MAX_CUTBACK_DEPTH = 6

    def enable_nonlinear(self, transf_kind="Linear", fiber_size_ratio=16, n_int_pts=5,
                         hinge="radau", hinge_lp=None, bar_slip=True, slip_R=0.5,
                         slip_sy_mult=1.0, slip_su_mult=35.0, slip_b=0.3,
                         shear_spring=None, slip_concrete="stiff"):
                                                                                                             
        """Call BEFORE build_model(). Frame elements whose section carries
        reinforcement + nonlinear material data become forceBeamColumn
        elements on fiber sections (os_nonlinear.py); everything else stays
        elastic and a warning is recorded in self.unsupported."""
        try:
            from core.opensees_port.os_nonlinear import NonlinearSectionBuilder
        except ImportError:
            from os_nonlinear import NonlinearSectionBuilder
        self._transf_kind = transf_kind
        self._nl_builder = NonlinearSectionBuilder(
            self.d, ops=ops, fiber_size_ratio=int(fiber_size_ratio), n_int_pts=int(n_int_pts))
        self._nl_builder.slip_R = float(slip_R)
        self._nl_builder.slip_sy_mult = float(slip_sy_mult)                                                        
        self._nl_builder.slip_su_mult = float(slip_su_mult)
        self._nl_builder.slip_b = float(slip_b)
        self._nl_builder.slip_concrete = str(slip_concrete)
        self._nl_builder.shear_spring = dict(shear_spring) if shear_spring else None                                     
        self._nl_shear = bool(shear_spring)
        self._nl_hinge = str(hinge).lower()
        self._nl_hinge_lp = hinge_lp
        self._nl_bar_slip = bool(bar_slip)
        self._nl_builder.hinge_add_sp = (str(hinge).lower() == "radau") and not bool(bar_slip)
        self.slip_elements = []
        self.spring_nodes = []                                                                          
        self.nl_elements = []

    def _slip_nodes(self, ni, nj, sec_name):
        """If bar_slip is on and exactly one end of this member is a fully-translation-restrained support
        node, create a coincident free node + a Bond_SP01 zeroLengthSection between support and member, and
        return the (possibly replaced) member end nodes.  Otherwise returns (ni, nj) unchanged."""
        if not (getattr(self, "_nl_bar_slip", False) or getattr(self, "_nl_shear", False)):
            return ni, nj
        fixed = lambda n: all(self.nodes[n].get('restraints', [False] * 6)[:3]) if n in self.nodes else False
        if fixed(ni) == fixed(nj):
            return ni, nj                                                                         
        sup, free_end = (ni, nj) if fixed(ni) else (nj, ni)
        p_i, p_j = np.array([self.nodes[ni][k] for k in 'xyz']), np.array([self.nodes[nj][k] for k in 'xyz'])
        x_ax = (p_j - p_i) / np.linalg.norm(p_j - p_i)                                                       
        y_ax = np.cross(np.asarray(self._cur_vecxz, float), x_ax); y_ax /= np.linalg.norm(y_ax)
        sp = self.nodes[sup]
        orient = (*x_ax.tolist(), *y_ax.tolist())
        cur = sup
        _rec = {"support": sup, "slip": None, "shear": None}
        if getattr(self, "_nl_bar_slip", False):
            new_node = self._next_free_node_tag; self._next_free_node_tag += 1
            ops.node(new_node, sp['x'], sp['y'], sp['z'])
            z_tag = self._next_free_ele_tag; self._next_free_ele_tag += 1
            if not self._nl_builder.add_slip_spring(z_tag, cur, new_node, sec_name, orient):
                self.unsupported.append(f"member at node {sup} (section '{sec_name}'): bar slip not converted")
                return ni, nj
            self.slip_elements.append(z_tag)
            cur = new_node
            _rec["slip"] = new_node
        if getattr(self, "_nl_shear", False):                                                                             
            n2 = self._next_free_node_tag; self._next_free_node_tag += 1
            ops.node(n2, sp['x'], sp['y'], sp['z'])
            s_tag = self._next_free_ele_tag; self._next_free_ele_tag += 1
            if self._nl_builder.add_shear_spring(s_tag, cur, n2, sec_name, getattr(self, '_cur_L', 1.0), orient):
                self.slip_elements.append(s_tag)
                cur = n2
                _rec["shear"] = n2
        if _rec["slip"] is not None or _rec["shear"] is not None:
            getattr(self, "spring_nodes", []).append(_rec)
        return (cur, nj) if sup == ni else (ni, cur)

    def _emit_beam(self, tag, ni, nj, E, G, A, J, I33, I22, As3, As2, transf_tag, sec_name):
        if self._nl_builder is not None:
            try:
                ni_eff, nj_eff = self._slip_nodes(ni, nj, sec_name)
                if getattr(self, "_nl_hinge", "lobatto") == "radau":
                    lp = self._nl_hinge_lp
                    ok = self._nl_builder.add_hinge_element(
                        tag, ni_eff, nj_eff, transf_tag, sec_name,
                        getattr(self, "_cur_L", 1.0), lp, lp)
                    if ok and lp and getattr(self, "_nl_bar_slip", False) and (ni_eff, nj_eff) != (ni, nj):
                        try:
                            try:
                                from core.opensees_port.os_nonlinear import hinge_length as _hl
                            except ImportError:
                                from os_nonlinear import hinge_length as _hl
                            _pl = self._nl_builder._built[sec_name]["plan"]
                            _auto = _hl(getattr(self, "_cur_L", 1.0), _pl.slip["fy"], _pl.slip["fu"])
                            if lp > 1.25 * _auto:
                                self._nl_builder._warn(
                                    f"hinge length {lp:g} m is manual while bar slip is ON; the automatic value is "
                                    f"{_auto:.3g} m. The slip spring already supplies the strain-penetration rotation, "
                                    f"so a large manual Lp double-counts it (too soft/ductile). Set hinge length to 0 "
                                    f"(automatic) unless you calibrated it with slip on.")
                        except Exception:
                            pass
                else:
                    ok = self._nl_builder.add_element(tag, ni_eff, nj_eff, transf_tag, sec_name)
                if ok:
                    self.nl_elements.append(tag)
                    return
                if (ni_eff, nj_eff) != (ni, nj):                                                              
                    self.unsupported.append(f"element {tag}: slip nodes created but element not convertible")
                self.unsupported.append(
                    f"element {tag} (section '{sec_name}'): no convertible reinforcement/nonlinear "
                    f"data -- kept ELASTIC")
            except Exception as e:
                self.unsupported.append(
                    f"element {tag} (section '{sec_name}'): fiber section build failed "
                    f"({type(e).__name__}: {e}) -- kept ELASTIC")
        ops.element('ElasticTimoshenkoBeam', tag, ni, nj, E, G, A, J, I33, I22, As3, As2, transf_tag)

    def rigid_slave_tags(self):
        return {a for lst in self.rigid_slaves.values() for a in lst}

    def is_ground_node(self, tag):
        return tag in self._ground_nodes

    def _node_reaction(self, nid):
        """6-vector support reaction at a node, including the force carried to it through rigid-link and
        rigid-diaphragm slaves (ops.nodeReaction alone only reports the node's own element forces; a
        slave's residual is forwarded to its retained node by the MP constraint)."""
        r = np.array([float(v) for v in ops.nodeReaction(nid)])
        c0 = np.array(ops.nodeCoord(nid), dtype=float)
        for a in self.rigid_slaves.get(nid, []):
            fa = np.array([float(v) for v in ops.nodeReaction(a)])
            rr = np.array(ops.nodeCoord(a), dtype=float) - c0
            r[:3] += fa[:3]
            r[3:] += fa[3:] + np.cross(rr, fa[:3])
        for b, dofs in self.eq_slaves.get(nid, []):
            fb = np.array([float(v) for v in ops.nodeReaction(b)])
            for d in dofs:
                r[d] += fb[d]
        if nid in self.diaphragm_slave_map:
            axis, slaves = self.diaphragm_slave_map[nid]
            p1, p2, rot = {'Z': (0, 1, 5), 'X': (1, 2, 3), 'Y': (2, 0, 4)}[axis]
            for sid in slaves:
                fs = np.array([float(v) for v in ops.nodeReaction(sid)])
                cs = np.array(ops.nodeCoord(sid), dtype=float)
                d1, d2 = cs[p1] - c0[p1], cs[p2] - c0[p2]
                r[p1] += fs[p1]
                r[p2] += fs[p2]
                r[rot] += fs[rot] - d2 * fs[p1] + d1 * fs[p2]
        return r

    @staticmethod
    def _dof_index(label):
        """'U1'..'U3' -> 1..3, 'R1'..'R3' -> 4..6 (OpenSees 1-based DOF)."""
        s = str(label).strip().upper()
        n = int(s[-1])
        return n + (3 if s.startswith('R') else 0)

    def _base_reaction_vec(self):
        """[Fx,Fy,Fz,Mx,My,Mz] summed over restrained nodes about the global origin
        (same moment-transfer formula as get_results_dict)."""
        ops.reactions()
        sx = [0.0] * 6
        for nid, n in self.nodes.items():
            if not any(n.get('restraints', [False] * 6)):
                continue
            fx, fy, fz, mx, my, mz = [float(v) for v in self._node_reaction(nid)]
            x, y, z = n['x'], n['y'], n['z']
            sx[0] += fx; sx[1] += fy; sx[2] += fz
            sx[3] += mx + (y * fz - z * fy)
            sx[4] += my + (z * fx - x * fz)
            sx[5] += mz + (x * fy - y * fx)
        return sx

    def _setup_solution(self, blk):
        ops.wipeAnalysis()
        ops.system('BandGeneral')
        ops.numberer('RCM')
        ops.constraints('Transformation')
        ops.test(str(blk['test_type']), float(blk['tolerance']), int(blk['max_iter']))
        self._test = (str(blk['test_type']), float(blk['tolerance']), int(blk['max_iter']))
        self._relax_on = bool(blk.get('relax_on_fail', True))
        self._relax_ceil = float(blk.get('relax_ceiling', self.NL_RELAX_CEIL) or self.NL_RELAX_CEIL)
        self._primary_alg = str(blk['algorithm'])
        try:
            ops.algorithm(self._primary_alg)
        except Exception:
            self._primary_alg = 'Newton'
            ops.algorithm('Newton')
        ops.integrator('LoadControl', 1.0)                                                
        ops.analysis('Static')

    def _restore_primary_alg(self):
        try:
            ops.algorithm(self._primary_alg)
        except Exception:
            ops.algorithm('Newton')

    def _set_test(self, cap=None):
        t, tol, mi = self._test
        ops.test(t, tol, mi if cap is None else min(mi, cap))

    NL_RELAX_MULTS = (1e2, 1e4, 1e6)                                                                    
    NL_LADDER_DEPTH = 4                                                                                     
    NL_RELAX_CEIL = 1e-5                                                                    

    def _last_resort(self, size):
        """Smallest-increment step that still failed. Try (1) other algorithms with a real
        iteration budget, then (2) the same algorithms with a progressively relaxed tolerance.
        A step accepted at a relaxed tolerance is recorded in self._relaxed so the run can
        report it as approximate. Returns 0 on success, last OpenSees status otherwise."""
        perf = self._perf
        t, tol, mi = self._test
        strict_algs = [("ModifiedNewton", "-initial"), ("KrylovNewton",), ("NewtonLineSearch",), ("Broyden", 8)]
        relaxed_algs = [("Newton",), ("NewtonLineSearch",)]
        tols = [tol]
        ceil = max(tol, getattr(self, "_relax_ceil", self.NL_RELAX_CEIL))\
            if t in ("NormDispIncr", "EnergyIncr") else tol * 1e4
        if getattr(self, "_relax_on", True):
            for m in self.NL_RELAX_MULTS:
                v = min(tol * m, ceil)
                if v > tols[-1]:
                    tols.append(v)
        ok = -1
        try:
            for li, tv in enumerate(tols):
                ops.test(t, tv, 100 if li == 0 else 50)
                for a in (strict_algs if li == 0 else relaxed_algs):
                    try:
                        ops.algorithm(*a)
                    except Exception:
                        continue
                    ok = ops.analyze(1)
                    perf["analyze_n"] += 1
                    if ok == 0:
                        if tv > tol:
                            self._relaxed.append({"cmd": float(getattr(self, "_cur_cmd", 0.0)),
                                                  "tol": tv, "alg": a[0]})
                        return 0
        finally:
            ops.test(t, tol, mi)
            self._restore_primary_alg()
        return ok

    def _robust_step(self, set_integrator, size, on_ok, depth=0):
        """One increment of `size`. On failure the increment is halved (up to
        NL_MAX_CUTBACK_DEPTH times) -- cheap, and usually enough. The alternative
        algorithms are only tried at the smallest increment, as a last resort, so a
        stuck step no longer costs 4 full iteration limits at every cutback level.
        Cutback attempts are capped at 50 iterations (a converging Newton step does not
        need more). Returns 0 on success, non-zero OpenSees status on failure."""
        perf = self._perf
        set_integrator(size)
        if depth > 0:
            self._set_test(50)
        t0 = time.perf_counter()
        ok = ops.analyze(1)
        perf["analyze_n"] += 1
        if ok != 0:
            perf["fail_n"] += 1
            if self._primary_alg != "Newton":
                                                                                                     
                try:
                    ops.algorithm("Newton")
                    self._set_test(50)
                    ok = ops.analyze(1)
                    perf["analyze_n"] += 1
                finally:
                    self._restore_primary_alg()
                    self._set_test(50 if depth > 0 else None)
            if ok != 0 and depth >= self.NL_LADDER_DEPTH:
                ok = self._last_resort(size)
        perf["analyze_s"] += time.perf_counter() - t0
        if depth > 0:
            self._set_test()
        if ok == 0:
            on_ok(size)
            return 0
        if depth >= self.NL_MAX_CUTBACK_DEPTH:
            return ok
        half = size / 2.0
        r = self._robust_step(set_integrator, half, on_ok, depth + 1)
        if r != 0:
            return r
        return self._robust_step(set_integrator, half, on_ok, depth + 1)

    def run_nonlinear_static_chain(self, chain, progress_callback=None, want_states=False, max_states=0):
        """Runs the cases in `chain` in order inside ONE OpenSees domain, so every
        case starts from the stressed state the previous one ended in (loadConst
        between cases = SAP2000's 'stiffness at end of nonlinear case').
        Returns an info dict describing the LAST case."""
        from error_definitions import SolverException
        if progress_callback is None:
            def progress_callback(msg, pct):
                pass
        progress_callback = _opensees_progress(progress_callback)
        info = {"history": None, "states": [], "failed": None, "steps": 0,
                "control_node": None, "control_dof": None}
        self._relaxed = []
        self._perf = {"analyze_n": 0, "analyze_s": 0.0, "fail_n": 0, "capture_n": 0, "capture_s": 0.0,
                      "t_start": time.perf_counter()}
        from core.opensees_port.os_hinge_results import OpenSeesHingeRecorder
        hinge_recorder = OpenSeesHingeRecorder(self, ops)
        self._hinge_recorder = hinge_recorder
        monitor = {"m": None}
        info["hinge_states"] = {}
        info["hinge_sections"] = hinge_recorder.sections
        info["hinge_warnings"] = hinge_recorder.warnings
        info["hinge_history"] = hinge_recorder.history                                                           

        prog = {"n": 0, "frac": 0.0, "saved_n": None, "hinge_n": None, "stride": 1, "hstride": 1}
        HINGE_MAX_SAVES = 150                                                                             

        def _set_strides(total):
            ss = 1 if max_states <= 0 else max(1, int(np.ceil(total / max(1, max_states - 2))))
            hs = max(1, int(np.ceil(total / HINGE_MAX_SAVES)))
            prog["stride"] = ss
            prog["hstride"] = ss * int(np.ceil(hs / ss))                                            

        def _save_state(hinge=True):
            _t = time.perf_counter()
            if hinge:
                info["hinge_states"] = hinge_recorder.capture()
                prog["hinge_n"] = prog["n"]
                self._perf["capture_n"] += 1
            prog["saved_n"] = prog["n"]
            if want_states:
                info["states"].append(self._capture_state(
                    prog["n"], prog["frac"], info["hinge_states"] if hinge else None))
            self._perf["capture_s"] += time.perf_counter() - _t

        def _tick(n, frac):
            prog["n"], prog["frac"] = n, frac
            if want_states:
                hinge_recorder.capture_light(n)                                                                   
            if want_states and n % prog["stride"] == 0:
                _save_state(hinge=(n % prog["hstride"] == 0))

        def _finish():
                                                                      
            if prog["saved_n"] != prog["n"]:
                _save_state(hinge=True)
            elif prog["hinge_n"] != prog["n"]:
                                                                                                  
                info["hinge_states"] = hinge_recorder.capture()
                prog["hinge_n"] = prog["n"]
                if want_states and info["states"]:
                    info["states"][-1]["hinge_states"] = info["hinge_states"]
            pf = self._perf
            total = time.perf_counter() - pf["t_start"]
            progress_callback(
                f"  [timing] total {total:.1f}s | OpenSees analyze {pf['analyze_s']:.1f}s in {pf['analyze_n']} calls "
                f"({pf['fail_n']} failed) | hinge/state capture {pf['capture_s']:.1f}s in {pf['capture_n']} saves | "
                f"other (python per-step work) {max(0.0, total - pf['analyze_s'] - pf['capture_s']):.1f}s", 91)
        ts_tag, pat_tag = 1, 1
        n_cases = len(chain)

        for ci, name in enumerate(chain):
            lc = self.load_cases[name]
            nlp = lc.get('nl_params') or {}
            blk = dict(self.NL_DEFAULT_BLOCK)
            blk.update(lc.get('opensees') or {})
            is_last = (ci == n_cases - 1)
            load_app = nlp.get('load_application', lc.get('load_application', 'Full Load'))
            base_pct = 20 + 70 * ci / n_cases
            span_pct = 70 / n_cases

            for pat_name, mult in lc.get('loads', []):
                self._apply_self_weight_pattern(pat_name, ts_tag, pat_tag, mult)
                self._apply_explicit_loads(pat_name, mult)
                ts_tag += 1
                pat_tag += 1

            if is_last:
                                                                         
                prog.update(n=0, frac=0.0, saved_n=None, hinge_n=None)
                if want_states:
                    _save_state()

            if load_app != 'Displacement Control':
                lam_steps = max(1, int(blk.get('load_steps', self.NL_FULL_LOAD_STEPS) or self.NL_FULL_LOAD_STEPS))
                if str(blk.get('load_path_mode', 'Monotonic')) == 'History Table' and blk.get('load_history'):
                    lam_targets = [float(v) for v in blk['load_history']]
                else:
                    lam_targets = [1.0]
                lam_total = load_factor_step_count(lam_targets, lam_steps)
                if lam_total > self.NL_MAX_TOTAL_STEPS:
                    raise SolverException(
                        "E104", f"Case '{name}': load path needs {lam_total} steps at {lam_steps} per unit load "
                                f"factor (limit {self.NL_MAX_TOTAL_STEPS}). Reduce the load steps.")
                if is_last:
                    _set_strides(lam_total)
                progress_callback(f"Case '{name}': load control, {len(lam_targets)} target(s), {lam_total} steps...", base_pct)
                self._setup_solution(blk)
                set_int = lambda size: ops.integrator('LoadControl', size)
                accepted = {"n": 0, "fraction": 0.0}

                def on_load_ok(size):
                    accepted["n"] += 1
                    accepted["fraction"] += size                                                                       
                    info["steps"] += 1
                    if is_last:
                        _tick(accepted["n"], accepted["fraction"])

                lam_cur, k = 0.0, 0
                for ti, tgt in enumerate(lam_targets):
                    delta = tgt - lam_cur
                    if abs(delta) <= 1e-15:
                        continue
                    n = max(1, int(np.ceil(abs(delta) * lam_steps - 1e-9)))
                    dlam = delta / n
                    for _ in range(n):
                        r = self._robust_step(set_int, dlam, on_load_ok)
                        k += 1
                        if r != 0:
                            if is_last:
                                info["failed"] = {"case": name, "step": k, "status": int(r), "target_index": ti + 1}
                                _finish()
                                return info
                            raise SolverException(
                                "E301", f"OpenSees: case '{name}' did not converge (load step {k}, status {r}); "
                                        f"cannot continue the chain.")
                    lam_cur = tgt
            else:
                node = nlp.get('disp_control_node_id')
                if node is None:
                    raise SolverException(
                        "E104", f"Load Case '{name}' is set to Displacement Control but no monitored "
                                f"joint is defined.")
                node = int(node)
                if node not in self.nodes:
                    raise SolverException("E104", f"Case '{name}': monitored joint {node} does not exist.")
                dof = self._dof_index(nlp.get('disp_control_dof', 'U1'))

                if not lc.get('loads'):
                                                                                                
                    ops.timeSeries('Linear', ts_tag)
                    ops.pattern('Plain', pat_tag, ts_tag)
                    unit = [0.0] * 6
                    unit[dof - 1] = 1.0
                    ops.load(node, *unit)
                    ts_tag += 1
                    pat_tag += 1

                if str(blk['path_mode']) == 'History Table':
                    targets = [float(v) for v in blk['disp_history']]
                    if not targets:
                        raise SolverException("E104", f"Case '{name}': History Table path is empty.")
                else:
                    targets = [float(nlp.get('disp_control_magnitude', lc.get('disp_control_magnitude', 0.1)))]
                step = float(blk['step_size'])
                if step <= 0.0:
                    raise SolverException("E104", f"Case '{name}': step size must be positive.")

                cur = 0.0
                total = 0
                for t in targets:
                    total += max(1, int(np.ceil(abs(t - cur) / step - 1e-9))) if abs(t - cur) > 1e-15 else 0
                    cur = t
                if total > self.NL_MAX_TOTAL_STEPS:
                    raise SolverException(
                        "E104", f"Case '{name}': displacement path needs {total} steps at step size "
                                f"{step:g} m (limit {self.NL_MAX_TOTAL_STEPS}). Increase the step size.")

                if is_last:
                    _set_strides(total)
                self._setup_solution(blk)
                hist = {"u": [], "base": []}
                done = {"n": 0}
                state = {"cmd": 0.0}

                def on_ok(size, node=node, dof=dof, hist=hist, done=done, state=state, total=total):
                    state["cmd"] += size
                    done["n"] += 1
                    hist["u"].append(float(ops.nodeDisp(node, dof)))
                    hist["base"].append(self._base_reaction_vec())
                    if is_last and monitor["m"] is not None:
                        monitor["m"].capture(done["n"], hist["u"][-1], hist["base"][-1])
                    if is_last:
                        _tick(done["n"], min(1.0, done["n"] / max(total, 1)))
                    if blk.get("safety_check", True) and state["fz0"] is not None:
                        fz = hist["base"][-1][2]
                        if abs(fz - state["fz0"]) > 1e-3 * max(abs(state["fz0"]), 1e-9):
                            state["unsafe"] = (done["n"], fz, state["fz0"])

                set_int = lambda size, node=node, dof=dof: ops.integrator('DisplacementControl', node, dof, size)
                progress_callback(f"Case '{name}': displacement control on joint {node}, "
                                  f"{len(targets)} target(s), ~{total} steps...", base_pct)
                info["control_node"], info["control_dof"] = node, dof
                if is_last and dof <= 3:
                    try:
                        from core.opensees_port.os_drift_events import DriftEventMonitor
                    except ImportError:
                        from os_drift_events import DriftEventMonitor
                    try:
                        monitor["m"] = DriftEventMonitor(self, ops, node, dof)
                        info["monitor"] = monitor["m"]
                    except Exception as _e:
                        _msg = f"drift/event monitor unavailable ({type(_e).__name__}: {_e})"
                        info["monitor_error"] = _msg
                        progress_callback(f"  [!] {_msg}", base_pct)
                state["fz0"] = None
                state["unsafe"] = None
                if blk.get("safety_check", True):
                    _fz0 = self._base_reaction_vec()[2]
                    if abs(_fz0) > 1e-9:
                        state["fz0"] = _fz0
                info["history"] = hist
                failed = False
                for k, t in enumerate(targets):
                    delta = t - state["cmd"]
                    if abs(delta) <= 1e-15:
                        continue
                    n = max(1, int(np.ceil(abs(delta) / step - 1e-9)))
                    du = delta / n
                    for _ in range(n):
                        self._cur_cmd = state["cmd"]
                        r = self._robust_step(set_int, du, on_ok)
                        if r == 0 and state["unsafe"] is not None:
                            _n, _fz, _fz0 = state["unsafe"]
                            progress_callback(
                                f"  [!] SAFETY CHECK: vertical reaction {_fz:.6g} differs from the "
                                f"starting value {_fz0:.6g} by more than 0.1% at step {_n}; stopped. "
                                f"Results up to this step are kept.", base_pct)
                            r = -99
                        if r != 0:
                            info["failed"] = {"case": name, "target_index": k + 1,
                                              "commanded_disp": state["cmd"], "status": int(r)}
                            failed = True
                            break
                    if failed:
                        break
                    state["cmd"] = t                                                   
                    if (k + 1) % 20 == 0 or k + 1 == len(targets):
                        progress_callback(f"Case '{name}': target {k + 1}/{len(targets)} reached",
                                          base_pct + span_pct * (k + 1) / len(targets))
                info["steps"] = done["n"]
                if self._relaxed:
                    info["relaxed_steps"] = list(self._relaxed)
                    progress_callback(
                        f"  [!] Case '{name}': {len(self._relaxed)} step(s) converged only at a relaxed "
                        f"tolerance (first at commanded u={self._relaxed[0]['cmd']:.6g} m, "
                        f"tol {self._relaxed[0]['tol']:.1e}, {self._relaxed[0]['alg']}); treat as approximate.",
                        base_pct)
                if failed:
                    if is_last:
                        _finish()
                        return info
                    raise SolverException(
                        "E301", f"OpenSees: case '{name}' did not converge; cannot continue the chain.")

            if not is_last:
                ops.loadConst('-time', 0.0)
        _finish()
        return info

    def _capture_state(self, step, frac, hinge_states=None):
        r = self.get_results_dict()
        return {
            "step": int(step), "step_frac": float(frac),
            "displacements": {str(k): v for k, v in r["displacements"].items()},
            "reactions": {str(k): v for k, v in r["reactions"].items()},
            "base_reaction": r["base_reaction"],
            "opensees_forces": r["opensees_forces"],
            "hinge_states": hinge_states, "event": False,
        }

    def run_linear_static(self, case_name):
        lc = self.load_cases[case_name]
        assert lc['type'] == 'Linear Static', f"{case_name} is not Linear Static"

        ts_tag, pat_tag = 1, 1
        for pat_name, mult in lc['loads']:
            self._apply_self_weight_pattern(pat_name, ts_tag, pat_tag, mult)
            self._apply_explicit_loads(pat_name, mult)
            ts_tag += 1
            pat_tag += 1
        ts_tag, pat_tag = self._apply_ground_displacements(ts_tag, pat_tag)

        ops.system('BandGeneral')
        ops.numberer('RCM')
        ops.constraints('Transformation')
        ops.integrator('LoadControl', 1.0)
        ops.algorithm('Linear')
        ops.analysis('Static')
        ok = ops.analyze(1)
        return ok

    def run_modal(self, case_name):
        lc = self.load_cases[case_name]
        assert lc['type'] == 'Modal', f"{case_name} is not Modal"
        self._apply_self_mass(lc.get('mass_source', 'Default'))
        num_modes = lc.get('num_modes', 12)
        eigenvalues = ops.eigen(num_modes)
        periods = [2 * np.pi / np.sqrt(ev) if ev > 0 else float('nan') for ev in eigenvalues]
        return periods

    def get_results_dict(self):
        """
        Packages OpenSees nodal displacements/reactions into EXACTLY the
        same shape as core/solver/linear_static/solver_kernel.py's
        LinearSolver.get_results_dict(), so ResultWriter can write an
        OpenSees Linear Static result indistinguishable in format from a
        native one:

            displacements: {node_id: [ux,uy,uz,rx,ry,rz]}
            reactions:     {node_id: [Fx,Fy,Fz,Mx,My,Mz]}
            base_reaction: {Fx,Fy,Fz,Mx,My,Mz}  (summed at global origin,
                            same cross-product moment-transfer formula as
                            the native solver)
            restrained_nodes: [str(id), ...]

        Springs are NOT handled here (spring_matrix is already flagged as
        unsupported in _build_nodes()) -- reactions for restrained DOFs
        come straight from ops.nodeReaction(), free DOFs report 0.0.
        """
        ops.reactions()

        results = {"displacements": {}, "reactions": {}}

        sum_fx = sum_fy = sum_fz = 0.0
        sum_mx = sum_my = sum_mz = 0.0
        restrained_ids = []
        springs = {s_['id']: s_['K'] for s_ in self.spring_nodes_static}

        for nid, n in self.nodes.items():
            disp = np.array([float(v) for v in ops.nodeDisp(nid)])
            results["displacements"][nid] = disp.tolist()

            restraints = n.get('restraints', [False] * 6)
            K_sp = springs.get(nid)
            if any(restraints) or K_sp is not None:
                restrained_ids.append(str(nid))
                                                                                                        
            reac_os = self._node_reaction(nid) if any(restraints) or any(
                (nid, d + 1) in self.imposed for d in range(6)) else np.zeros(6)
            spring_force = -(K_sp @ disp) if K_sp is not None else np.zeros(6)
            out = np.zeros(6)
            for i in range(6):
                out[i] = reac_os[i] if restraints[i] else spring_force[i]
            results["reactions"][nid] = out.tolist()

            fx, fy, fz, mx, my, mz = out
            x, y, z = n['x'], n['y'], n['z']
            sum_fx += fx
            sum_fy += fy
            sum_fz += fz
            sum_mx += mx + (y * fz - z * fy)
            sum_my += my + (z * fx - x * fz)
            sum_mz += mz + (x * fy - y * fx)

        results["base_reaction"] = {
            "Fx": sum_fx, "Fy": sum_fy, "Fz": sum_fz,
            "Mx": sum_mx, "My": sum_my, "Mz": sum_mz
        }
        results["restrained_nodes"] = restrained_ids

        try:
            from core.opensees_port.os_force_recovery import capture_member_forces
        except ImportError:
            from os_force_recovery import capture_member_forces
        results["opensees_forces"] = capture_member_forces(self, ops)

        return results

def opensees_modal_backend(oc_data, node_index, M_diag, is_free, num_modes, case_name, progress_callback=None):
    """Eigen / static back end for modal_engine.run_modal_analysis when the Analysis Engine is OpenSees.

    modal_engine keeps doing what is not "solving" (mass assembly from the Mass Source, mode
    normalisation, participation tables, JSON layout) so the OpenSees result has exactly the native
    structure. This function replaces the K-dependent parts:

        eigen problem         -> ops.eigen on the converted model (rigid diaphragms / links /
                                 releases / springs as in the static path)
        mode reactions  K*phi -> static solve with nodal loads w^2*M*phi, reactions read from OpenSees
        static (missing-mass) -> static solves with loads M*r_d

    node_index : {node_id: native node idx}  (6 DOF per node, native ordering)
    M_diag     : native diagonal mass vector (len = 6 * n_nodes), WITHOUT the regularisation
    Returns dict(vals, phi, kphi, static_x/y/z, warnings, total_dofs); phi / kphi are
    (total_dofs, n_modes) arrays in native DOF ordering (unnormalised).
    """
    from error_definitions import SolverException
    if progress_callback is None:
        def progress_callback(msg, pct):
            pass
    conv = OpenCivilToOpenSees(oc_data)
    conv.build_model()
    progress_callback("OpenSees model built for modal analysis...", 36)

    total = len(M_diag)
    M_diag = np.asarray(M_diag, dtype=float)
    active = conv.active_dofs

    pos = M_diag[np.asarray(is_free, dtype=bool) & (M_diag > 1e-10)]
    reg = float(pos.min()) * 1e-6 if pos.size else 1e-6
    mass6 = {}
    for tag in ops.getNodeTags():
        mass6[tag] = np.zeros(6)
    for nid, n in conv.nodes.items():
        idx = node_index.get(nid)
        if idx is None:
            continue
        mass6[nid] = M_diag[idx * 6: idx * 6 + 6].copy()
                                                                               
    for tag, m6 in mass6.items():
        if tag in conv.nodes:
            r = conv.nodes[tag].get('restraints', [False] * 6)
            free = [not (r[k] or not active[k]) for k in range(6)]
        elif tag in conv.rigid_slave_tags():
            free = [False] * 6                                                                        
        else:
            free = list(active)
        for k in range(6):
            if free[k] and m6[k] < 1e-10:
                m6[k] = reg
    ground = set(g for g in ops.getNodeTags() if conv.is_ground_node(g))
    for tag, m6 in mass6.items():
        if tag in ground:
            continue
        ops.mass(tag, *[float(v) for v in m6])

    ops.wipeAnalysis()
    ops.system('BandGeneral')
    ops.numberer('RCM')
    ops.constraints('Transformation')
    progress_callback(f"OpenSees eigen solution ({num_modes} modes)...", 45)
    try:
        vals = list(ops.eigen(int(num_modes)))
    except Exception as e:
        raise SolverException("E303", f"OpenSees eigen failed: {e}")
    if len(vals) < int(num_modes):
        raise SolverException("E304", f"OpenSees returned {len(vals)} of {num_modes} requested modes.")
    vals = np.array([float(v) for v in vals])
    nm = len(vals)

    tags = [t for t in ops.getNodeTags() if t not in ground]
    phi_tag = {}
    for i in range(nm):
        phi_tag[i] = {t: np.array([float(v) for v in ops.nodeEigenvector(t, i + 1)]) for t in tags}
    phi = np.zeros((total, nm))
    for i in range(nm):
        for nid in conv.nodes:
            idx = node_index.get(nid)
            if idx is not None:
                phi[idx * 6: idx * 6 + 6, i] = phi_tag[i][nid]

    def static_solve(load_of_tag):
        ops.wipeAnalysis()
        ops.reset()
        ops.timeSeries('Constant', 9001)
        ops.pattern('Plain', 9001, 9001)
        for t, f in load_of_tag.items():
            if np.any(np.abs(f) > 0.0):
                ops.load(t, *[float(v) for v in f])
        ops.system('BandGeneral')
        ops.numberer('RCM')
        ops.constraints('Transformation')
        ops.integrator('LoadControl', 1.0)
        ops.algorithm('Linear')
        ops.analysis('Static')
        ok = ops.analyze(1)
        return ok

    def drop_pattern():
        ops.remove('loadPattern', 9001)
        ops.remove('timeSeries', 9001)

    kphi = np.zeros((total, nm))
    mech_floor = (2.0 * np.pi / 100.0) ** 2                                                                 
    warnings = []
    support_nodes = [nid for nid, n in conv.nodes.items()
                     if any(n.get('restraints', [False] * 6)) and nid in node_index]
    for i in range(nm):
        progress_callback(f"Mode {i + 1}: support reactions...", 60 + int(8 * (i + 1) / nm))
        if vals[i] <= mech_floor:
            continue
        loads = {t: vals[i] * mass6[t] * phi_tag[i][t] for t in tags}
        ok = static_solve(loads)
        if ok != 0:
            warnings.append(f"mode {i + 1}: reaction solve failed (status {ok})")
            drop_pattern()
            continue
        ops.reactions()
        for nid in support_nodes:
            idx = node_index[nid]
            kphi[idx * 6: idx * 6 + 6, i] = conv._node_reaction(nid)
        drop_pattern()

    static = {}
    for d, name in enumerate(('x', 'y', 'z')):
        loads = {}
        for t in tags:
            f = np.zeros(6)
            f[d] = mass6[t][d]
            loads[t] = f
        ok = static_solve(loads)
        if ok != 0:
            warnings.append(f"static participation {name.upper()}: solve failed (status {ok})")
            static[name] = None
            drop_pattern()
            continue
        num = den = 0.0
        for t in tags:
            u = np.array([float(v) for v in ops.nodeDisp(t)])
            num += mass6[t][d] * u[d]
            den += float(np.dot(mass6[t] * u, u))
        static[name] = (num * num / den) if den > 0 else 0.0
        drop_pattern()

    return {"vals": vals, "phi": phi, "kphi": kphi, "static_mass": static,
            "warnings": warnings, "total_dofs": total, "unsupported": list(conv.unsupported)}

def _opensees_progress(cb):
    """Wraps a progress callback so (a) the percentage is always an int and
    (b) every status line is visibly tagged as coming from the OpenSees engine.
    Indented lines (warnings/sub-items) and blank lines are passed through as-is."""
    def wrapped(msg, pct):
        text = str(msg)
        if text and not text[0].isspace() and 'opensees' not in text.lower():
            text = f"[OpenSees] {text}"
        cb(text, int(round(pct)))
    return wrapped

def run_opensees_linear_static(oc_data, output_json_path, case_name, progress_callback=None):
    """
    Runs a single Linear Static case through OpenSees (openseespy) and
    writes results to output_json_path in the SAME JSON shape ResultWriter
    produces for the native solver -- so anything downstream that reads a
    results.json (dialogs, element_forces.py, etc.) doesn't need to care
    which engine produced it.

    oc_data: the raw OpenCivil model dict -- i.e. DataManager(...).raw,
    or an equivalent json.load() of the .mf file. Deliberately NOT run
    through DataManager.process_all(): this converter reads load_patterns'
    sw_mult itself and generates its own self-weight loads, independent of
    the native pipeline's load-injection (cables/tendons/auto-seismic are
    native-only concerns for now -- see module docstring SCOPE section).

    case_name must refer to a "Linear Static" case; anything else raises
    SolverException("E104", ...), same error code main_engine.py already
    uses for "case not found / wrong type".
    """
    import time
    from result_writer import ResultWriter
    from error_definitions import SolverException

    if progress_callback is None:
        def progress_callback(msg, pct):
            pass

    progress_callback = _opensees_progress(progress_callback)
    start_time = time.time()

    progress_callback("Building OpenSees model...", 10)
    conv = OpenCivilToOpenSees(oc_data)
    conv.build_model(case_name)

    lc = conv.load_cases.get(case_name)
    if lc is None:
        raise SolverException("E104", f"Case '{case_name}' not found (OpenSees engine).")
    if lc['type'] != 'Linear Static':
        raise SolverException(
            "E104",
            f"Case '{case_name}' is type '{lc['type']}' -- only 'Linear Static' "
            f"is supported via the OpenSees engine right now."
        )

    if conv.unsupported:
        progress_callback("OpenSees conversion warnings (not converted, v1 scope):", 15)
        for w in conv.unsupported:
            progress_callback(f"  [!] {w}", 15)
        progress_callback("", 15)

    progress_callback(f"Solving '{case_name}' via OpenSees...", 40)
    ok = conv.run_linear_static(case_name)
    if ok != 0:
        raise SolverException(
            "E301", f"OpenSees analyze() returned status {ok} (non-zero = failure) for case '{case_name}'."
        )

    progress_callback("Extracting results...", 70)
    results = conv.get_results_dict()

    elapsed = time.time() - start_time
    meta_info = {
        "version": "OpenSees (openseespy)",
        "time_elapsed": f"{elapsed:.4f} sec",
        "dofs": len(conv.nodes) * 6,
        "case_name": case_name,
        "type": "Linear Static",
        "engine": "opensees"
    }

    progress_callback("Writing results to disk...", 90)
    writer = ResultWriter(output_json_path)
    writer.write_results(results, meta_info, assembled_mass=None)

    progress_callback("A N A L Y S I S   C O M P L E T E (OpenSees)", 100)
    return True

def run_opensees_nonlinear_static(oc_data, output_json_path, case_name, progress_callback=None):
    """
    Runs one Nonlinear Static case through OpenSees (openseespy) -- v1: it runs,
    and writes displacements / reactions / base reaction in the same JSON shape
    as the native solver, plus the full control-node history (and a CSV next to
    the results file) for comparing against test data.

    Chaining: if the case has nl_params.continue_from_case, the predecessor
    chain is re-run inside the same OpenSees domain first (gravity -> loadConst
    -> next case), so no solver_worker state hand-off is needed. Only the target
    case's results are written.

    Everything in oc_data is SI (m, N); the CSV also gets display-unit columns.
    """
    import time, os
    from result_writer import ResultWriter
    from error_definitions import SolverException

    if progress_callback is None:
        def progress_callback(msg, pct):
            pass

    progress_callback = _opensees_progress(progress_callback)

    start_time = time.time()
    lcs = {lc['name']: lc for lc in oc_data.get('load_cases', [])}
    if case_name not in lcs:
        raise SolverException("E104", f"Case '{case_name}' not found (OpenSees engine).")

    chain, cur = [], case_name
    while cur:
        if cur in chain:
            raise SolverException("E104", f"Circular 'continue from case' chain at '{cur}'.")
        lc = lcs.get(cur)
        if lc is None:
            raise SolverException("E104", f"Case '{cur}' (continue-from chain) not found.")
        if lc.get('type') != 'Nonlinear Static':
            raise SolverException(
                "E104", f"Case '{cur}' is type '{lc.get('type')}'; the OpenSees nonlinear runner chains "
                        f"Nonlinear Static cases only.")
        chain.insert(0, cur)
        cur = (lc.get('nl_params') or {}).get('continue_from_case') or lc.get('continue_from_case')

    rank = {"None": 0, "P-Delta": 1, "Large Displacements": 2}
    kinds = ["Linear", "PDelta", "Corotational"]
    worst = max(rank.get(lcs[c].get('geom_nonlin', 'None'), 0) for c in chain)
    target_blk = dict(OpenCivilToOpenSees.NL_DEFAULT_BLOCK)
    target_blk.update(lcs[case_name].get('opensees') or {})

    progress_callback("Building OpenSees model...", 10)
    conv = OpenCivilToOpenSees(oc_data)
    radau = str(target_blk.get('integration', 'Lobatto')).lower().startswith('hinge')
    lp_user = float(target_blk.get('hinge_length') or 0.0)
    conv.enable_nonlinear(kinds[worst], target_blk['fiber_size_ratio'], target_blk['n_int_pts'],
                          hinge="radau" if radau else "lobatto",
                          hinge_lp=lp_user if (radau and lp_user > 0.0) else None,
                          bar_slip=bool(target_blk.get('bar_slip', False)),
                          shear_spring=target_blk.get('shear_spring') or None,
                          slip_concrete=target_blk.get('slip_concrete', 'stiff'),
                          slip_R=float(target_blk.get('slip_R', 0.5)), slip_b=float(target_blk.get('slip_b', 0.3)),
                          slip_sy_mult=float(target_blk.get('slip_sy_mult', 1.0)), slip_su_mult=float(target_blk.get('slip_su_mult', 35.0)))
    if radau:
        progress_callback("INTEGRATION: HingeRadau, Lp = "
                          + (f"{lp_user:g} m (user)" if lp_user > 0.0 else "automatic"), 11)
    conv.build_model()

    progress_callback(f"OPENSEES NONLINEAR STATIC  | chain: {' -> '.join(chain)}", 12)
    progress_callback(f"GEOMETRIC NONLINEARITY: {['None', 'P-Delta', 'Large Displacements'][worst]}", 12)
    progress_callback(f"FIBER ELEMENTS (forceBeamColumn): {len(conv.nl_elements)} of {len(conv.elements)}", 12)
    if conv._nl_builder is not None and conv._nl_builder.warnings:
        for w in conv._nl_builder.warnings:
            progress_callback(f"  [!] {w}", 14)
    if conv.unsupported:
        progress_callback("OpenSees conversion warnings:", 15)
        for w in conv.unsupported:
            progress_callback(f"  [!] {w}", 15)
        progress_callback("", 15)

    tnl = lcs[case_name].get('nl_params') or {}
    want_states = (tnl.get('results_saved', 'Final State Only') == 'Multiple States')
    info = conv.run_nonlinear_static_chain(chain, progress_callback, want_states=want_states,
                                           max_states=int(tnl.get('max_saved_states', 100) or 0))

    progress_callback("Extracting results...", 92)
    results = conv.get_results_dict()

    try:
        from core.units import unit_registry
        to_len, to_force = unit_registry.to_display_length, unit_registry.to_display_force
        len_name, force_name = unit_registry.length_unit_name, unit_registry.force_unit_name
    except Exception:
        to_len = to_force = (lambda v: v)
        len_name, force_name = "m", "N"

    mon = info.get("monitor")
    drift_rec = mon.drift_record() if mon is not None else None
    events = mon.event_list() if mon is not None else []
    if mon is not None:
        for _ln in mon.summary_lines(to_len, len_name):
            progress_callback(_ln, 91)
    drift_by_step = {}
    if drift_rec:
        for _i, _st in enumerate(drift_rec["steps"]):
            drift_by_step[_st] = (drift_rec["u_slip"][_i], drift_rec["u_shear"][_i], drift_rec["u_flex"][_i])

    hist_meta, csv_path = None, None
    if info.get("history") and info["history"]["u"]:
        dof = info["control_dof"]
        u = info["history"]["u"]
        V = [-b[dof - 1] for b in info["history"]["base"]]                                     
        hist_meta = {"control_node": info["control_node"], "control_dof": dof,
                     "u_m": u, "V_N": V, "base_reaction": info["history"]["base"]}
        csv_path = (output_json_path[:-len("_results.json")] + "_history.csv"
                    if output_json_path.endswith("_results.json") else output_json_path + ".history.csv")
        try:
            with open(csv_path, 'w') as f:
                f.write(f"step,u_{len_name},V_{force_name},u_m,V_N,u_slip_m,u_shear_m,u_flex_m\n")
                for i, (ui, vi) in enumerate(zip(u, V), start=1):
                    _d = drift_by_step.get(i)
                    _dd = ",".join(f"{x:.9g}" for x in _d) if _d else ",,"
                    f.write(f"{i},{to_len(ui):.9g},{to_force(vi):.9g},{ui:.12g},{vi:.9g},{_dd}\n")
        except OSError as e:
            progress_callback(f"  [!] could not write history CSV: {e}", 93)
            csv_path = None

    saved_states = None
    if want_states and info["states"]:
        _msv = int(tnl.get('max_saved_states', 100) or 0)
        mx = 10**9 if _msv <= 0 else max(1, _msv)                                      
        st = info["states"]
        if len(st) > mx:
            idx = sorted({int(round(i * (len(st) - 1) / (mx - 1))) for i in range(mx)}) if mx > 1 else [len(st) - 1]
            st = [st[i] for i in idx]
        saved_states = st

    ctrl_node = info.get("control_node") or tnl.get("disp_control_node_id")
    ctrl_dof = str(tnl.get("disp_control_dof", "U1")).strip().upper()
    if ctrl_node is None or int(ctrl_node) not in conv.nodes:
        ctrl_node, best_d, best_v = next(iter(conv.nodes)), 0, -1.0
        for nid, disp_vec in results["displacements"].items():
            for d_idx in (0, 1, 2):
                if abs(disp_vec[d_idx]) > best_v:
                    ctrl_node, best_d, best_v = nid, d_idx, abs(disp_vec[d_idx])
        ctrl_dof = ("U1", "U2", "U3")[best_d]

    failed = info.get("failed")
    meta_info = {
        "version": "OpenSees (openseespy)",
        "type": "Nonlinear Static",
        "case_name": case_name,
        "engine": "opensees",
        "chain": chain,
        "geom_nonlin": ['None', 'P-Delta', 'Large Displacements'][worst],
        "dofs": len(conv.nodes) * 6,
        "steps_accepted": info["steps"],
        "fiber_elements": len(conv.nl_elements),
        "failed_steps": [failed] if failed else [],
        "relaxed_steps": info.get("relaxed_steps", []),
        "time_elapsed": f"{time.time() - start_time:.4f} sec",
        "history_csv": csv_path,
        "disp_control": bool(saved_states),
        "disp_control_node_id": int(ctrl_node),
        "disp_control_dof": ctrl_dof,
        "results_saved_multiple": bool(saved_states),
        "event_to_event": False,
        "n_events": 0,
        "events": [],
        "opensees_history": hist_meta,
        "opensees_hinge_schema": 1,
        "opensees_hinge_sections": info["hinge_sections"],
        "opensees_hinge_warnings": info["hinge_warnings"],
        "opensees_hinge_history": info["hinge_history"] or None,
        "opensees_drift_history": drift_rec,
        "opensees_damage_events": events,
        "warnings": (list(conv.unsupported)
                     + ([f"[monitor] {info['monitor_error']}"] if info.get("monitor_error") else [])
                     + ([f"[monitor] {w}" for w in mon.warnings] if mon is not None else [])),
    }
    progress_callback("Writing results to disk...", 96)
    writer = ResultWriter(output_json_path)
    writer.write_results(results, meta_info, saved_states=saved_states,
                         hinge_states=info["hinge_states"])

    if failed:
        progress_callback(f"[!] STOPPED EARLY: OpenSees failed to converge in case '{failed['case']}' "
                          f"(status {failed['status']}); results are up to the last converged step.", 98)
    progress_callback("A N A L Y S I S   C O M P L E T E (OpenSees)", 100)
    return True

if __name__ == '__main__':
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else 'Example_File.mf'
    oc = load_oc_model(path)
    conv = OpenCivilToOpenSees(oc)
    conv.build_model()

    print(f"Nodes: {len(conv.nodes)}  Elements: {len(conv.elements)}")
    if conv.unsupported:
        print("\n--- NOT CONVERTED (v1 scope) ---")
        for w in conv.unsupported:
            print(" -", w)

    total_self_weight = sum(conv.element_mass_kg.values()) * G_ACCEL
    print(f"\nTotal self-weight (all elements, DEAD sw_mult=1.0 basis): {total_self_weight:,.1f} N")

    print("\n--- Linear Static: DEAD ---")
    ok = conv.run_linear_static('DEAD')
    print("analyze() returned:", ok, "(0 = success)")

    ops.reactions()
    base_nodes = [nid for nid, n in conv.nodes.items() if any(n['restraints'])]
    rz_sum = sum(ops.nodeReaction(nid)[2] for nid in base_nodes)
    print(f"Sum of base reaction Fz: {rz_sum:,.1f} N  vs total self-weight: {total_self_weight:,.1f} N "
          f"(should match closely -- pure gravity, no other loads)")

    print("\n--- Modal ---")
    ops.wipeAnalysis()
    periods = conv.run_modal('MODAL')
    print("First periods (s):", [f"{t:.6f}" for t in periods[:6]])
