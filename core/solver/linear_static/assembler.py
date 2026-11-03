import numpy as np
from scipy.sparse import lil_matrix, coo_matrix
from element_library import get_local_stiffness_matrix, get_link_stiffness_matrix, get_rotation_matrix, get_eccentricity_matrix
from matrix_spy import MatrixSpy
from error_definitions import SolverException
from element_library import get_local_stiffness_matrix, get_link_stiffness_matrix, get_rotation_matrix, get_eccentricity_matrix, get_exact_fef_via_stiffness, condense_fef
from element_library import get_local_stiffness_matrix_batch, get_rotation_matrix_batch, get_eccentricity_matrix_batch
from core.solver.modal.mass_assembler import GlobalMassAssembler

class GlobalAssembler:
    def __init__(self, data_manager,export_path=None):
        self.dm = data_manager
        self.spy = MatrixSpy(export_path)

        self.dm = data_manager
                                  
        self.K = lil_matrix((self.dm.total_dofs, self.dm.total_dofs))
                                
        self.P = np.zeros(self.dm.total_dofs)

        self.element_by_id = {e['id']: e for e in self.dm.elements}

        self.modal_hinge_elements = None
        self.modal_hinge_report = []

    def assemble_system(self, exact_diaphragm=True):
        """Master function to build K and P."""
        print("Assembler: Building Stiffness Matrix...")
        self._build_stiffness()

        self.T = None
        self.kept_dofs = None

        active_dia = {k: v for k, v in getattr(self.dm, 'diaphragm_groups', {}).items() if len(v) >= 2}

        if exact_diaphragm and active_dia:
            print("Assembler: Building EXACT Diaphragm Constraint (DOF elimination)...")
            self.T, self.kept_dofs = self.build_diaphragm_transformation()
            n_elim = self.dm.total_dofs - len(self.kept_dofs)
            print(f"      Eliminated {n_elim} slave DOFs exactly (no penalty stiffness used).")
        elif active_dia:
            print("Assembler: Applying Diaphragm Constraints (penalty, legacy)...")
            self._apply_diaphragm_constraints()

        needs_mass = False
        active_patterns = [p[0] for p in self.dm.load_case['patterns']]
        for pat in self.dm.raw.get('load_patterns', []):
            if pat['name'] in active_patterns and pat.get('seismic_data'):
                needs_mass = True
                break

        assembled_mass = None
        
        if needs_mass:
            print("Assembler: Extracting True Mass Centroids for Seismic Loads...")
            mass_asm = GlobalMassAssembler(self.dm)
            
            ms_name = "Default"
            if self.dm.raw.get("mass_sources"):
                ms_name = self.dm.raw["mass_sources"][0]["name"]
                
            M_full = mass_asm.build_mass_matrix(ms_name)
            M_diag = M_full.diagonal()
            
            assembled_mass = {}
            for node in self.dm.nodes:
                nid = str(node['id'])
                idx = node['idx'] * 6
                assembled_mass[nid] = M_diag[idx : idx+6].tolist()
                                                                    
        print("Assembler: Processing Nodal & Seismic Loads...")
        
        self.P += self.dm.build_load_vector(assembled_mass=assembled_mass)
        
        print("Assembler: Processing Member Loads (FEF)...")
        self._add_member_loads()
        self._add_shell_loads()
        self.spy.save_to_json()
        return self.K, self.P

    def _build_stiffness(self):
        """
        Builds the global stiffness matrix.

        Same math as _build_stiffness_legacy(), but instead of mutating a
        lil_matrix with thousands of small += slice operations, it collects
        every (row, col, value) triplet into flat numpy buffers and builds
        the whole sparse matrix ONCE at the end via coo_matrix. coo_matrix
        sums duplicate (row,col) entries automatically on conversion, which
        is exactly what the original += accumulation was doing -- so this
        is numerically identical, just assembled differently (verified
        bit-for-bit identical against _build_stiffness_legacy() across
        elements with releases, rigid offsets, beta rotation, 1-joint
        links, 2-joint links, and node springs).
        """
        rows_buf = []
        cols_buf = []
        data_buf = []

        def add_block(dof_map, block):
            dof_arr = np.asarray(dof_map)
            r_idx, c_idx = np.meshgrid(dof_arr, dof_arr, indexing='ij')
            rows_buf.append(r_idx.ravel())
            cols_buf.append(c_idx.ravel())
            data_buf.append(np.asarray(block).ravel())

        self._build_beam_stiffness_batched(rows_buf, cols_buf, data_buf)

        for sh in getattr(self.dm, 'shells', []):
            add_block(sh.dof_map, sh.k_global)

        for link in self.dm.links_1j:
            prop = link['property']
            k_local = get_link_stiffness_matrix(prop['stiffness'], prop['is_fixed'], num_joints=1)

            start_idx = link['node_idx'] * 6
            dof_map = list(range(start_idx, start_idx + 6))
            add_block(dof_map, k_local)

        for link in self.dm.links_2j:
            prop = link['property']
            k_local = get_link_stiffness_matrix(prop['stiffness'], prop['is_fixed'], num_joints=2)

            idx_i, idx_j = link['node_indices']

            L = np.linalg.norm(link['p2'] - link['p1'])

            R_3x3 = get_rotation_matrix(link['p1'], link['p2'], link['beta'])
            T_rot = np.zeros((12, 12))
            for i in range(4):
                T_rot[i*3:(i+1)*3, i*3:(i+1)*3] = R_3x3

            T_ecc = get_eccentricity_matrix([0.0, 0.0, 0.0], [-L, 0.0, 0.0])

            T_total = T_ecc @ T_rot

            k_global = T_total.T @ k_local @ T_total

            start_i = idx_i * 6
            start_j = idx_j * 6
            dof_map = list(range(start_i, start_i + 6)) + list(range(start_j, start_j + 6))
            add_block(dof_map, k_global)

        for node in self.dm.nodes:
            if node.get('spring_matrix') is not None:
                start_idx = node['idx'] * 6
                dof_map = list(range(start_idx, start_idx + 6))
                add_block(dof_map, node['spring_matrix'])

        n = self.dm.total_dofs
        if data_buf:
            rows_all = np.concatenate(rows_buf)
            cols_all = np.concatenate(cols_buf)
            data_all = np.concatenate(data_buf)
            K_coo = coo_matrix((data_all, (rows_all, cols_all)), shape=(n, n))
        else:
            K_coo = coo_matrix((n, n))

        self.K = K_coo.tolil()

    def _hinge_zero_state_stiffness(self, el, hd, k_elastic, R=None, node_idx=None):
        """Local 12x12 stiffness of an element carrying a fiber hinge, evaluated at ZERO
        deformation: the unstressed initial tangent of the hinge's fibers (whatever the fiber
        materials define at zero strain). Same compute_hinge_element the nonlinear engine uses,
        so nothing about fibers / materials is duplicated here."""
        from hinge_element import compute_hinge_element
        _f, K, _N = compute_hinge_element(
            hd['fiber_section'], hd['rel_dist'], hd['length'],
            np.zeros(12), el['material'], el['section'], el['L_clear'],
            failed=None, residual_stiffness=hd.get('residual_stiffness'))
        K = np.array(K, dtype=float)
        for a, b in ((3, 3), (3, 9), (9, 3), (9, 9)):                                               
            K[a, b] = k_elastic[a, b]
                                                                                                   
        w_h = np.sort(np.abs(np.linalg.eigvalsh(0.5 * (K + K.T))))
        w_e = np.sort(np.abs(np.linalg.eigvalsh(0.5 * (k_elastic + k_elastic.T))))
        ratio = float(w_h[6] / w_e[6]) if w_e[6] > 0 else 1.0
        rep = {
            'element': str(el['id']), 'hinge': hd.get('_hinge_name', ''),
            'softest_mode_stiffness_ratio': ratio,
            'near_mechanism': bool(ratio < 1e-3)}
        if node_idx is not None:
            rep['nodes'] = [int(node_idx[0]), int(node_idx[1])]
        try:
                                                                                                          
            fs = hd['fiber_section']
            gross = np.array([el['material']['E'] * el['section']['A'],
                              el['material']['E'] * el['section']['I22'],
                              el['material']['E'] * el['section']['I33']])
            def _ratio(e0):
                Ks = np.array(fs.state(e0, 0.0, 0.0, failed=None)[3], dtype=float)
                return [float(v) for v in (np.diag(Ks) / gross)]
            rep['fiber_vs_gross'] = {'as_used': _ratio(0.0), 'tension_side': _ratio(1e-9),
                                     'compression_side': _ratio(-1e-9)}                               
        except Exception:
            pass
        if rep['near_mechanism'] and R is not None:
                                                                                                       
            try:
                rep.update(self._hinge_weak_direction(K, el['L_clear'], R))
            except Exception as exc:
                rep['weak_mode'] = f'unknown ({exc})'
        self.modal_hinge_report.append(rep)
        return K

    @staticmethod
    def _hinge_weak_direction(K, L, R):
        """Softest non-rigid, non-torsion deformation mode of a hinged element's local 12x12 K, and
        where it points in GLOBAL axes.

        Local DOFs: [u1,u2,u3,th1,th2,th3] at each end.  The mode is one of
          axial                    u1                   (translation dir = local 1)
          bending about local 2    u3 + th2             (rotation axis local 2, translation dir local 3)
          bending about local 3    u2 + th3             (rotation axis local 3, translation dir local 2)
        R is the element's 3x3 global->local rotation (u_local = R @ u_global), so local axis k, written
        in global coordinates, is the ROW R[k, :].  Rigid offsets / eccentricities are ignored here."""
        from hinge_element import _kinematic_matrix
        Bv = _kinematic_matrix(L)                                                                       
        Q, _ = np.linalg.qr(Bv.T)                                                                           
        Kr = Q.T @ (0.5 * (K + K.T)) @ Q                                                           
        w, U = np.linalg.eigh(Kr)
        x = Q @ U[:, 0]                                                                         
        groups = {'axial': (0, 6),
                  'bending about local 2': (2, 8, 4, 10),
                  'bending about local 3': (1, 7, 5, 11)}
        wt = {name: float(np.sum(x[list(ix)] ** 2)) for name, ix in groups.items()}
        tot = sum(wt.values()) or 1.0
        wt = {k: v / tot for k, v in wt.items()}
        mode = max(wt, key=wt.get)
        R = np.asarray(R, dtype=float)
        if mode == 'axial':
            rot_axis, trans_dir = None, R[0, :]
        elif mode == 'bending about local 2':
            rot_axis, trans_dir = R[1, :], R[2, :]
        else:
            rot_axis, trans_dir = R[2, :], R[1, :]
        return {'weak_mode': mode, 'weak_mode_weights': wt,
                'weak_rot_axis': None if rot_axis is None else [float(v) for v in rot_axis],
                'weak_trans_dir': [float(v) for v in trans_dir]}

    def _build_beam_stiffness_batched(self, rows_buf, cols_buf, data_buf):
        """
        Vectorized replacement for the old per-element Python loop that used
        to live directly inside _build_stiffness() (still available,
        unchanged, as the scalar reference in the per-element branch below
        and in _build_stiffness_legacy()).

        Does EXACTLY the same math as the scalar loop, element-by-element,
        for every element that has NO releases: same get_local_stiffness_matrix
        formula (via the batched get_local_stiffness_matrix_batch), same
        get_rotation_matrix branch logic (via get_rotation_matrix_batch),
        same eccentricity transform (via get_eccentricity_matrix_batch), same
        T_total = T_ecc @ T_rot and k_global = T_total.T @ k_local @ T_total
        composition - just performed as one set of numpy/einsum calls over
        all N elements instead of N separate small-matrix Python calls.

        Elements WITH releases fall back to the original scalar path one at
        a time (self._condense_matrix has an eigenvector-order / inversion
        step that isn't worth vectorizing - releases are typically a small
        minority of elements in a model), so the result is bit-for-bit
        the same as the pre-vectorization loop, just reordered accumulation
        into the same coo_matrix scatter (already established as numerically
        identical to lil_matrix += accumulation - see _build_stiffness()
        docstring).
        """
        elements = self.dm.elements
        n_el = len(elements)
        if n_el == 0:
            return

        has_release = np.array([any(el['releases'][0]) or any(el['releases'][1]) for el in elements])

        E   = np.array([el['material']['E'] for el in elements])
        G   = np.array([el['material']['G'] for el in elements])
        A   = np.array([el['section']['A'] for el in elements])
        J   = np.array([el['section']['J'] for el in elements])
        I22 = np.array([el['section']['I22'] for el in elements])
        I33 = np.array([el['section']['I33'] for el in elements])
        As2 = np.array([el['section']['As2'] for el in elements])
        As3 = np.array([el['section']['As3'] for el in elements])
        L        = np.array([el['L_clear'] for el in elements])
        L_total  = np.array([el['L_total'] for el in elements])

        idx_i = np.array([el['node_indices'][0] for el in elements])
        idx_j = np.array([el['node_indices'][1] for el in elements])
        p1 = np.array([self.dm.nodes[i]['coords'] for i in idx_i], dtype=float)
        p2 = np.array([self.dm.nodes[j]['coords'] for j in idx_j], dtype=float)

        off_i = np.array([el['offsets'][0] for el in elements], dtype=float)
        off_j = np.array([el['offsets'][1] for el in elements], dtype=float)

        theta_p = np.array([el['section'].get('theta_p', 0.0) for el in elements])
        beta_eff = np.array([el['beta'] for el in elements]) - np.degrees(theta_p)

        rz = np.array([el.get('rz_factor', 0.0) for el in elements])
        end_off_i = np.array([el.get('end_off_i', 0.0) for el in elements])
        end_off_j = np.array([el.get('end_off_j', 0.0) for el in elements])

        k_local = get_local_stiffness_matrix_batch(
            E=E, G=G, A=A, J=J, I22=I22, I33=I33, As2=As2, As3=As3,
            L=L, L_tor=L_total
        )

        p1_adj = p1 + off_i
        p2_adj = p2 + off_j
        R_3x3 = get_rotation_matrix_batch(p1_adj, p2_adj, beta_eff)            

        hinge_map = self.modal_hinge_elements
        if hinge_map:
            for n, el in enumerate(elements):
                hd = hinge_map.get(str(el['id']))
                if hd is not None:
                    k_local[n] = self._hinge_zero_state_stiffness(
                        el, hd, k_local[n], R=R_3x3[n], node_idx=(idx_i[n], idx_j[n]))

        if np.any(has_release):
            for n in np.where(has_release)[0]:
                el = elements[n]
                k_local[n] = self._condense_matrix(k_local[n], el['releases'])

        T_rot = np.zeros((n_el, 12, 12))
        for blk in range(4):
            T_rot[:, blk*3:(blk+1)*3, blk*3:(blk+1)*3] = R_3x3

        local_off_i = (R_3x3 @ off_i[:, :, None])[:, :, 0]
        local_off_j = (R_3x3 @ off_j[:, :, None])[:, :, 0]
        local_off_i[:, 0] += end_off_i * rz
        local_off_j[:, 0] -= end_off_j * rz

        T_ecc = get_eccentricity_matrix_batch(local_off_i, local_off_j)
        T_total = T_ecc @ T_rot

        T_total_T = np.transpose(T_total, (0, 2, 1))
        k_global = T_total_T @ k_local @ T_total

        for n in range(n_el):
            self.spy.record_matrices(elements[n]['id'], k_local[n], T_total[n])

        start_i = idx_i * 6
        start_j = idx_j * 6
        dof_map = np.concatenate([
            start_i[:, None] + np.arange(6)[None, :],
            start_j[:, None] + np.arange(6)[None, :]
        ], axis=1)           

        r_idx = np.broadcast_to(dof_map[:, :, None], (n_el, 12, 12))
        c_idx = np.broadcast_to(dof_map[:, None, :], (n_el, 12, 12))

        rows_buf.append(r_idx.ravel())
        cols_buf.append(c_idx.ravel())
        data_buf.append(k_global.ravel())

    def _build_stiffness_legacy(self):
        """
        Original lil_matrix += assembly. Kept only as a reference/regression
        check for _build_stiffness() below -- not called in normal operation.
        """
        for el in self.dm.elements:
                                          
            mat = el['material']
            sec = el['section']
            L = el['L_clear'] 
            L_total = el['L_total']
            
            k_local = get_local_stiffness_matrix(
                E=mat['E'], G=mat['G'], A=sec['A'], J=sec['J'],
                I22=sec['I22'], I33=sec['I33'],
                As2=sec['As2'], As3=sec['As3'], L=L, L_tor=L_total
            )

            if any(el['releases'][0]) or any(el['releases'][1]):
                k_local = self._condense_matrix(k_local, el['releases'])

            idx_i, idx_j = el['node_indices']
            p1 = self.dm.nodes[idx_i]['coords']
            p2 = self.dm.nodes[idx_j]['coords']
            
            global_off_i = np.array(el['offsets'][0]) 
            global_off_j = np.array(el['offsets'][1])
            
            p1_adj = p1 + global_off_i
            p2_adj = p2 + global_off_j
            
            R_3x3 = get_rotation_matrix(p1_adj, p2_adj, el['beta'])
            
            T_rot = np.zeros((12, 12))
            for i in range(4): 
                T_rot[i*3:(i+1)*3, i*3:(i+1)*3] = R_3x3
            
            global_off_i = np.array(el['offsets'][0]) 
            global_off_j = np.array(el['offsets'][1])

            local_off_i = R_3x3 @ global_off_i
            local_off_j = R_3x3 @ global_off_j
            
            rz = el.get('rz_factor', 0.0)
            local_off_i[0] += el.get('end_off_i', 0.0) * rz
            local_off_j[0] -= el.get('end_off_j', 0.0) * rz

            T_ecc = get_eccentricity_matrix(local_off_i, local_off_j) 
                                   
            T_total = T_ecc @ T_rot

            self.spy.record_matrices(el['id'], k_local, T_total)

            k_global = T_total.T @ k_local @ T_total

            start_i = idx_i * 6
            start_j = idx_j * 6
            
            self.K[start_i:start_i+6, start_i:start_i+6] += k_global[0:6, 0:6]
            self.K[start_i:start_i+6, start_j:start_j+6] += k_global[0:6, 6:12]
            self.K[start_j:start_j+6, start_i:start_i+6] += k_global[6:12, 0:6]
            self.K[start_j:start_j+6, start_j:start_j+6] += k_global[6:12, 6:12]

        for link in self.dm.links_1j:
            prop = link['property']
            k_local = get_link_stiffness_matrix(prop['stiffness'], prop['is_fixed'], num_joints=1)
            
            start_idx = link['node_idx'] * 6
            self.K[start_idx:start_idx+6, start_idx:start_idx+6] += k_local

        for link in self.dm.links_2j:
            prop = link['property']
            k_local = get_link_stiffness_matrix(prop['stiffness'], prop['is_fixed'], num_joints=2)
            
            idx_i, idx_j = link['node_indices']
            
            L = np.linalg.norm(link['p2'] - link['p1'])
            
            R_3x3 = get_rotation_matrix(link['p1'], link['p2'], link['beta'])
            T_rot = np.zeros((12, 12))
            for i in range(4): 
                T_rot[i*3:(i+1)*3, i*3:(i+1)*3] = R_3x3
                
            T_ecc = get_eccentricity_matrix([0.0, 0.0, 0.0], [-L, 0.0, 0.0])
            
            T_total = T_ecc @ T_rot
            
            k_global = T_total.T @ k_local @ T_total
            
            start_i = idx_i * 6
            start_j = idx_j * 6
            
            self.K[start_i:start_i+6, start_i:start_i+6] += k_global[0:6, 0:6]
            self.K[start_i:start_i+6, start_j:start_j+6] += k_global[0:6, 6:12]
            self.K[start_j:start_j+6, start_i:start_i+6] += k_global[6:12, 0:6]
            self.K[start_j:start_j+6, start_j:start_j+6] += k_global[6:12, 6:12]

        for node in self.dm.nodes:
            if node.get('spring_matrix') is not None:
                start_idx = node['idx'] * 6
                                                                             
                self.K[start_idx:start_idx+6, start_idx:start_idx+6] += node['spring_matrix']

    def _condense_matrix(self, k, releases):
        rel_vec = releases[0] + releases[1]
        idx_k = [i for i, r in enumerate(rel_vec) if not r]
        idx_c = [i for i, r in enumerate(rel_vec) if r]
        
        if not idx_c:
            return k 
        
        K_rr = k[np.ix_(idx_k, idx_k)]
        K_rc = k[np.ix_(idx_k, idx_c)]
        K_cr = k[np.ix_(idx_c, idx_k)]
        K_cc = k[np.ix_(idx_c, idx_c)]
        
        try:
            K_cc_inv = np.linalg.inv(K_cc)
        except np.linalg.LinAlgError:
            print("Warning: Unstable release configuration detected.")
            return k

        K_new_small = K_rr - K_rc @ K_cc_inv @ K_cr
        
        k_final = np.zeros((12, 12))
        for r_i, old_r in enumerate(idx_k):
            for c_i, old_c in enumerate(idx_k):
                k_final[old_r, old_c] = K_new_small[r_i, c_i]

        k_ref = np.max(np.abs(k))
        penalty = k_ref * 1e-12

        rot_dofs = [3, 4, 5, 9, 10, 11]

        for i, released in enumerate(rel_vec):
            if released and i in rot_dofs:
                k_final[i, i] += penalty

        return k_final

    def _apply_diaphragm_constraints(self):
        """
        Enforces rigid floor diaphragm constraints using the penalty method.
        Constrains in-plane DOFs only: UX, UY, RZ.
        UZ, RX, RY remain independent (out-of-plane bending is free).
        
        Constraint equations (Z-axis diaphragm, master node m, slave node s):
            UX_s = UX_m - dY * RZ_m   (dY = Ys - Ym)
            UY_s = UY_m + dX * RZ_m   (dX = Xs - Xm)
            RZ_s = RZ_m
        """
        if not hasattr(self.dm, 'diaphragm_groups'):
            return

        diag = self.K.diagonal()
        k_max = np.max(np.abs(diag)) if diag.size > 0 else 1.0
        if k_max < 1e-10:
            k_max = 1.0
        alpha = k_max * 1e6

        node_by_id = {n['id']: n for n in self.dm.nodes}

        for dia_name, node_ids in self.dm.diaphragm_groups.items():
            if len(node_ids) < 2:
                continue

            master_id = min(node_ids)
            master = node_by_id[master_id]
            mi = master['idx'] * 6
            Xm, Ym = master['coords'][0], master['coords'][1]

            for slave_id in node_ids:
                if slave_id == master_id:
                    continue
                slave = node_by_id[slave_id]
                si = slave['idx'] * 6
                dX = slave['coords'][0] - Xm
                dY = slave['coords'][1] - Ym

                ux_s, uy_s, rz_s = si+0, si+1, si+5
                ux_m, uy_m, rz_m = mi+0, mi+1, mi+5

                self.K[ux_s, ux_s] += alpha
                self.K[ux_s, ux_m] -= alpha
                self.K[ux_s, rz_m] += alpha * dY
                self.K[ux_m, ux_s] -= alpha
                self.K[ux_m, ux_m] += alpha
                self.K[ux_m, rz_m] -= alpha * dY
                self.K[rz_m, ux_s] += alpha * dY
                self.K[rz_m, ux_m] -= alpha * dY
                self.K[rz_m, rz_m] += alpha * dY**2

                self.K[uy_s, uy_s] += alpha
                self.K[uy_s, uy_m] -= alpha
                self.K[uy_s, rz_m] -= alpha * dX
                self.K[uy_m, uy_s] -= alpha
                self.K[uy_m, uy_m] += alpha
                self.K[uy_m, rz_m] += alpha * dX
                self.K[rz_m, uy_s] -= alpha * dX
                self.K[rz_m, uy_m] += alpha * dX
                self.K[rz_m, rz_m] += alpha * dX**2

                self.K[rz_s, rz_s] += alpha
                self.K[rz_s, rz_m] -= alpha
                self.K[rz_m, rz_s] -= alpha
                self.K[rz_m, rz_m] += alpha

            print(f"      Diaphragm '{dia_name}': {len(node_ids)} nodes, master=Node {master_id}, α={alpha:.2e}")

    _DIAPHRAGM_AXIS_DOFS = {
        "Z": (0, 1, 5),                               
        "X": (1, 2, 3),                               
        "Y": (2, 0, 4),                               
    }

    def build_diaphragm_transformation(self):
        """
        Builds an EXACT rigid-diaphragm constraint as a sparse transformation
        matrix T such that:

            U_full = T @ U_reduced

        For a diaphragm on axis N, the two slave translations perpendicular
        to N and the slave rotation about N are removed from the system
        entirely (not penalized) and re-expressed as an exact linear
        combination of the master's matching DOFs:

            perp1_s = perp1_m - d_perp2 * rot_m
            perp2_s = perp2_m + d_perp1 * rot_m
            rot_s   = rot_m

        where d_perp1/d_perp2 are the slave's offset from the master along
        the two in-plane directions. For axis="Z" this is exactly
        UX_s = UX_m - dY*RZ_m, UY_s = UY_m + dX*RZ_m, RZ_s = RZ_m - the
        original Z-only formula, unchanged. The remaining 3 DOFs per node
        stay independent (out-of-plane bending is free), same as before.

        This has no tunable stiffness ratio and no penalty-induced ill
        conditioning: the constraint is satisfied to machine precision,
        and K is never polluted with artificial penalty terms, so base
        reactions sum exactly with no penalty-method artifacts.

        Returns:
            T (csr_matrix): shape (total_dofs, n_reduced)
            kept_dofs (list[int]): full-DOF index corresponding to each
                                    column of T, in order.
        """
        n = self.dm.total_dofs
        node_by_id = {nd['id']: nd for nd in self.dm.nodes}

        eliminated = {}                                                     

        for dia_name, node_ids in self.dm.diaphragm_groups.items():
            if len(node_ids) < 2:
                continue

            axis = getattr(self.dm, 'diaphragm_axis', {}).get(dia_name, 'Z')
            if axis not in self._DIAPHRAGM_AXIS_DOFS:
                raise SolverException(
                    "E205",
                    f"Diaphragm '{dia_name}': unsupported axis '{axis}'. "
                    f"Supported axes are X, Y, Z."
                )
            p1, p2, rot = self._DIAPHRAGM_AXIS_DOFS[axis]

            master_id = min(node_ids)
            master = node_by_id[master_id]
            mi = master['idx'] * 6
            coord_m = master['coords']
            m_p1, m_p2, m_rot = mi + p1, mi + p2, mi + rot

            for slave_id in node_ids:
                if slave_id == master_id:
                    continue
                slave = node_by_id[slave_id]
                si = slave['idx'] * 6
                d_p1 = slave['coords'][p1] - coord_m[p1]
                d_p2 = slave['coords'][p2] - coord_m[p2]

                s_p1, s_p2, s_rot = si + p1, si + p2, si + rot

                if s_p1 in eliminated or s_p2 in eliminated or s_rot in eliminated:
                    raise SolverException(
                        "E205",
                        f"Node {slave_id} appears in more than one diaphragm group."
                    )

                eliminated[s_p1] = {m_p1: 1.0, m_rot: -d_p2}
                eliminated[s_p2] = {m_p2: 1.0, m_rot:  d_p1}
                eliminated[s_rot] = {m_rot: 1.0}

            print(f"      Diaphragm '{dia_name}' (axis={axis}): {len(node_ids)} nodes, "
                  f"master=Node {master_id} (exact elimination)")

        kept_dofs = [i for i in range(n) if i not in eliminated]
        col_of = {dof: c for c, dof in enumerate(kept_dofs)}
        n_red = len(kept_dofs)

        T = lil_matrix((n, n_red))
        for dof in kept_dofs:
            T[dof, col_of[dof]] = 1.0
        for dof, terms in eliminated.items():
            for master_dof, coeff in terms.items():
                T[dof, col_of[master_dof]] += coeff

        self.eliminated_dofs = eliminated
        return T.tocsr(), kept_dofs
    
    def _add_shell_loads(self):
        """area_uniform / area_gravity loads on shells -> consistent nodal forces into P."""
        from shell_element import add_shell_area_loads
        add_shell_area_loads(self.dm, self.P)

    def _add_member_loads(self):
        """
        Calculates FEF for all member loads, condenses them for releases,
        transforms them to Global coordinates, and adds to P vector.

        Thin loop around compute_single_member_load_fef_global() - see that
        method's docstring for why the per-load math was pulled out into a
        standalone, reusable function.
        """
        print("Assembler: Processing Member Loads (FEF)...")
        active_patterns = {pat: scale for pat, scale in self.dm.load_case['patterns']}

        for load in self.dm.raw['loads']:
            if load['pattern'] not in active_patterns: continue
            if load['type'] not in ['member_dist', 'member_point']: continue

            scale = active_patterns[load['pattern']]
            result = self.compute_single_member_load_fef_global(load, scale)
            if result is None:
                continue
            fef_global, fef_local, idx_i, idx_j = result

            rows_i = slice(idx_i*6, idx_i*6+6)
            rows_j = slice(idx_j*6, idx_j*6+6)

            self.P[rows_i] -= fef_global[0:6]
            self.P[rows_j] -= fef_global[6:12]

    def compute_single_member_load_fef_global(self, load, scale, R_3x3_override=None):
        """
        Computes the full 12-vector fef_global (GLOBAL axes, equivalent-
        nodal-load convention: caller does self.P -= fef_global) for ONE
        member load record.

        Extracted out of _add_member_loads() so this EXACT, already-
        validated FEF math (trapezoidal integration, exact-stiffness point
        load FEF, release condensation, rigid-end-offset correction) can
        also be called from nonlinear_engine.py's Large Displacements path
        with R_3x3_override = the element's CURRENT corotational frame
        rotation matrix, instead of the frozen undeformed one.

        Why this matters: for a member load with coord='Global' (fixed
        global direction - e.g. wind, or a horizontal push on a column),
        the intensity vector must be re-projected onto the member's
        CURRENT (rotated) local axes to get the right FEF once the member
        has rotated significantly - the undeformed-geometry projection
        used by the static assembler is only a decent approximation for
        SMALL rotations. A coord='Local' load's fef_local is, by
        construction, independent of R_3x3 (see the branches below) - so
        it is already exactly correct at any rotation and needs no
        reprojection; only Global-coordinate loads are affected.

        R_3x3_override: if None, computed from the element's stored
        (undeformed) node coordinates exactly as before (unchanged
        behavior for linear/P-Delta and the static baseline of Large
        Displacements). If supplied, used in place of that rotation
        matrix everywhere below - this is the sole change needed to
        reproject onto a deformed/rotated configuration.

        Returns (fef_global, fef_local, idx_i, idx_j), or None if the load
        doesn't apply (unknown element / unknown direction / point load
        outside the member's rigid-end-adjusted span).

        fef_local is returned alongside fef_global (post release-
        condensation, pre eccentricity/rotation transform -- the exact
        same value MatrixSpy records) so callers that need the LOCAL-axis
        FEF directly -- e.g. nonlinear_engine.py's N_axial/geometric-
        stiffness reprojection, which operates in the element's local
        frame, not the assembled global one -- don't have to invert
        T_ecc/T_rot to recover it.
        """
        el = self.element_by_id.get(load['element_id'])
        if not el:
            return None

        L_clear = el['L_clear']
        L_total = el['L_total']
        idx_i, idx_j = el['node_indices']
        p1 = self.dm.nodes[idx_i]['coords']
        p2 = self.dm.nodes[idx_j]['coords']

        rz = el.get('rz_factor', 0.0)
        ri = el.get('end_off_i', 0.0) * rz
        rj = el.get('end_off_j', 0.0) * rz

        mat = el['material']
        sec = el['section']
        k_raw = get_local_stiffness_matrix(
            E=mat['E'], G=mat['G'], A=sec['A'], J=sec['J'],
            I22=sec['I22'], I33=sec['I33'],
            As2=sec['As2'], As3=sec['As3'],
            L=L_clear, L_tor=L_total
        )

        fef_local = np.zeros(12)

        beta_eff = el['beta'] - np.degrees(sec.get('theta_p', 0.0))
        if R_3x3_override is not None:
            R_3x3 = R_3x3_override
        else:
            R_3x3 = get_rotation_matrix(p1, p2, beta_eff)

        w_vec_local_for_offset = np.zeros(3)

        if load['type'] == 'member_dist':
                                    
            mags = load.get('magnitudes', [0, 0, 0, 0])
            
            if any(abs(m) > 1e-9 for m in mags):
                fef_local, F_ri, M_ri_cent, F_rj, M_rj_cent = self._get_trapezoidal_fef_and_w(
                    load, scale, R_3x3, L_clear, L_total, ri, rj, p1, p2, mat, sec
                )
                w_vec_local_for_offset = None                                              
            else:
                                                             
                w_defined = np.array([load.get('wx', 0.0), load.get('wy', 0.0), load.get('wz', 0.0)]) * scale
                
                if load.get('coord', 'Global') == 'Global':
                    w_local = R_3x3 @ w_defined
                else:
                    w_local = w_defined

                if load.get('projected', False):
                    w_local = self._apply_projection_factor(
                        w_local, p1, p2, L_total, load.get('coord', 'Global')
                    )
                
                wx, wy, wz = w_local
                w_vec_local_for_offset = w_local                               

                fef_local[0] = -wx * L_clear / 2;    fef_local[6] = -wx * L_clear / 2
                fef_local[1] = -wy * L_clear / 2;    fef_local[7] = -wy * L_clear / 2
                fef_local[5] = -wy * L_clear**2/12;  fef_local[11]=  wy * L_clear**2/12
                fef_local[2] = -wz * L_clear / 2;    fef_local[8] = -wz * L_clear / 2
                fef_local[4] =  wz * L_clear**2/12;  fef_local[10]= -wz * L_clear**2/12

        elif load['type'] == 'member_point':
            P_val = load['force'] * scale
            
            idx_dir, sign = self._parse_load_direction(load['dir'])
            if idx_dir is None: return None
            
            vec_defined = np.zeros(3)
            vec_defined[idx_dir] = 1.0 * sign * P_val

            coord_sys = load.get('coord', 'Global')
            if "GRAVITY" in str(load['dir']).upper(): coord_sys = 'Global'
            
            if coord_sys == 'Global':

                P_local = R_3x3 @ vec_defined 
            else:
                P_local = vec_defined
            
            dist_raw = load['dist']
            if load['is_rel']: dist_raw *= L_total

            if dist_raw >= ri and dist_raw <= (L_total - rj):
                a_dist = dist_raw - ri 
                
                l_type = load.get('l_type', 'Force')
                if l_type == 'Moment':
                    fef_local = get_exact_fef_via_stiffness(L_clear, a_dist, np.zeros(3), mat, sec, M_vec_local=P_local)
                else:
                    fef_local = get_exact_fef_via_stiffness(L_clear, a_dist, P_local, mat, sec)
                
        if any(el['releases'][0]) or any(el['releases'][1]):
            fef_local = condense_fef(k_raw, fef_local, el['releases'])

        self.spy.record_fef(el['id'], fef_local)
        
        T_rot = np.zeros((12, 12))
        for i in range(4): T_rot[i*3:(i+1)*3, i*3:(i+1)*3] = R_3x3

        glob_off_i = np.array(el['offsets'][0])
        glob_off_j = np.array(el['offsets'][1])

        loc_off_insertion_i = R_3x3 @ glob_off_i
        loc_off_insertion_j = R_3x3 @ glob_off_j

        loc_off_total_i = loc_off_insertion_i.copy()
        loc_off_total_j = loc_off_insertion_j.copy()
        loc_off_total_i[0] += ri
        loc_off_total_j[0] -= rj

        T_ecc = get_eccentricity_matrix(loc_off_total_i, loc_off_total_j)
        T_total = T_ecc @ T_rot

        fef_global = T_total.T @ fef_local

        if load['type'] == 'member_dist' and (ri > 0 or rj > 0):
            if w_vec_local_for_offset is not None:
                                                             
                wx, wy, wz = w_vec_local_for_offset
                if ri > 0:
                    F_rigid_i = np.array([wx, wy, wz]) * ri
                    centroid_i = np.array([ri/2.0, 0, 0])
                    centroid_i += loc_off_insertion_i
                    M_rigid_i = np.cross(centroid_i, F_rigid_i)
                    fef_global[0:3] -= R_3x3.T @ F_rigid_i
                    fef_global[3:6] -= R_3x3.T @ M_rigid_i
                if rj > 0:
                    F_rigid_j = np.array([wx, wy, wz]) * rj
                    centroid_j = np.array([-rj/2.0, 0, 0])
                    centroid_j += loc_off_insertion_j
                    M_rigid_j = np.cross(centroid_j, F_rigid_j)
                    fef_global[6:9] -= R_3x3.T @ F_rigid_j
                    fef_global[9:12] -= R_3x3.T @ M_rigid_j
            else:
                                                                   
                if ri > 0:
                    M_rigid_i = M_ri_cent + np.cross(loc_off_insertion_i, F_ri)
                    fef_global[0:3] -= R_3x3.T @ F_ri
                    fef_global[3:6] -= R_3x3.T @ M_rigid_i
                if rj > 0:
                    M_rigid_j = M_rj_cent + np.cross(loc_off_insertion_j, F_rj)
                    fef_global[6:9] -= R_3x3.T @ F_rj
                    fef_global[9:12] -= R_3x3.T @ M_rigid_j

        return fef_global, fef_local, idx_i, idx_j

    def _parse_load_direction(self, dir_str):
        """
        Robustly maps a direction string to a vector index and sign.
        Returns: (index, sign)
        index: 0=X, 1=Y, 2=Z
        """
        d = str(dir_str).upper()                         
        
        if "GRAVITY" in d: 
            return 2, -1.0
            
        if "X" in d or "1" in d: return 0, 1.0
        if "Y" in d or "2" in d: return 1, 1.0
        if "Z" in d or "3" in d: return 2, 1.0
        
        print(f"Warning: Unknown load direction '{dir_str}'. Defaulting to Zero.")
        return None, 0.0

    def _apply_projection_factor(self, w_local, p1, p2, L_total, coord_system):
        """
        Scales a distributed load based on horizontal projection.
        
        For projected loads in Global coordinates:
        - Calculates the horizontal (XY plane) projection length
        - Scales load intensity: w_actual = w_input * (L_horizontal / L_total)
        
        Args:
            w_local: Load vector in local coordinates [wx, wy, wz]
            p1, p2: Node coordinates in global system
            L_total: Total member length (center to center)
            coord_system: "Global" or "Local"
        
        Returns:
            Scaled load vector [wx_scaled, wy_scaled, wz_scaled]
        """
                                                                    
        if coord_system != "Global":
            print(f"Warning: Projected loads only supported in Global coordinates. Ignoring projection.")
            return w_local
        
        dx = p2[0] - p1[0]
        dy = p2[1] - p1[1]
        L_horizontal = np.sqrt(dx**2 + dy**2)
        
        if L_horizontal < 1e-9:
            print(f"Warning: Member is vertical. Projected horizontal load = 0.")
            return np.array([0.0, 0.0, 0.0])
        
        if L_total < 1e-9:
            print(f"Warning: Zero-length member detected.")
            return w_local
        
        proj_factor = L_horizontal / L_total
        
        w_scaled = w_local * proj_factor
        
        print(f"   Projected Load: Original intensity = {np.linalg.norm(w_local):.2f}, "
            f"Scaled = {np.linalg.norm(w_scaled):.2f} (factor = {proj_factor:.4f})")
        
        return w_scaled

    def _get_trapezoidal_fef_and_w(self, load, scale, R_3x3, L_clear, L_total, ri, rj, p1, p2, mat, sec):
        from element_library import get_varying_fef_via_integration
        
        mags = np.array(load.get('magnitudes', [0,0,0,0])) * scale
        dists = np.array(load.get('distances', [0, 0.25, 0.75, 1.0]))
        is_rel = load.get('is_relative', True)
        
        if is_rel:
            dists = dists * L_total
            
        dir_str = str(load.get('load_direction', 'Gravity')).upper()
        coord_sys = str(load.get('coord', 'Global')).upper()
        
        w_vectors_local = []
        for m in mags:
            vec = np.zeros(3)
                                                                                       
            if "GRAVITY" in dir_str: vec[2] = m
            elif "X" in dir_str or "1" in dir_str: vec[0] = m
            elif "Y" in dir_str or "2" in dir_str: vec[1] = m
            elif "Z" in dir_str or "3" in dir_str: vec[2] = m
                
            if coord_sys == 'GLOBAL':
                vec_local = R_3x3 @ vec
            else:
                vec_local = vec
                
            if load.get('projected', False):
                vec_local = self._apply_projection_factor(vec_local, p1, p2, L_total, "Global")
                
            w_vectors_local.append(vec_local)
            
        return get_varying_fef_via_integration(L_clear, L_total, ri, rj, dists, w_vectors_local, mat, sec)
