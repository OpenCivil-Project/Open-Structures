                                                          
import numpy as np
from scipy.sparse import lil_matrix
from element_library import get_local_stiffness_matrix, get_rotation_matrix, get_eccentricity_matrix
from matrix_spy import MatrixSpy
from error_definitions import SolverException
from element_library import get_local_stiffness_matrix, get_rotation_matrix, get_eccentricity_matrix, get_exact_fef_via_stiffness, condense_fef
from core.solver.modal.mass_assembler import GlobalMassAssembler

class GlobalAssembler:
    def __init__(self, data_manager,export_path=None):
        self.dm = data_manager
        self.spy = MatrixSpy(export_path)

        self.dm = data_manager
                                  
        self.K = lil_matrix((self.dm.total_dofs, self.dm.total_dofs))
                                
        self.P = np.zeros(self.dm.total_dofs)

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
        self.spy.save_to_json()
        return self.K, self.P

    def _build_stiffness(self):
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
            
            local_off_i[0] += el.get('end_off_i', 0.0) 
            local_off_j[0] -= el.get('end_off_j', 0.0)

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

    def build_diaphragm_transformation(self):
        """
        Builds an EXACT rigid-diaphragm constraint as a sparse transformation
        matrix T such that:

            U_full = T @ U_reduced

        Slave UX, UY, RZ DOFs are removed from the system entirely (not
        penalized) and re-expressed as an exact linear combination of the
        diaphragm master's UX, UY, RZ:

            UX_s = UX_m - dY * RZ_m   (dY = Ys - Ym)
            UY_s = UY_m + dX * RZ_m   (dX = Xs - Xm)
            RZ_s = RZ_m

        UZ, RX, RY remain independent per node (out-of-plane bending is free).

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

            master_id = min(node_ids)
            master = node_by_id[master_id]
            mi = master['idx'] * 6
            Xm, Ym = master['coords'][0], master['coords'][1]
            ux_m, uy_m, rz_m = mi + 0, mi + 1, mi + 5

            for slave_id in node_ids:
                if slave_id == master_id:
                    continue
                slave = node_by_id[slave_id]
                si = slave['idx'] * 6
                dX = slave['coords'][0] - Xm
                dY = slave['coords'][1] - Ym

                ux_s, uy_s, rz_s = si + 0, si + 1, si + 5

                if ux_s in eliminated or uy_s in eliminated or rz_s in eliminated:
                    raise SolverException(
                        "E205",
                        f"Node {slave_id} appears in more than one diaphragm group."
                    )

                eliminated[ux_s] = {ux_m: 1.0, rz_m: -dY}
                eliminated[uy_s] = {uy_m: 1.0, rz_m:  dX}
                eliminated[rz_s] = {rz_m: 1.0}

            print(f"      Diaphragm '{dia_name}': {len(node_ids)} nodes, "
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
    
    def _add_member_loads(self):
        """
        Calculates FEF for all member loads, condenses them for releases,
        transforms them to Global coordinates, and adds to P vector.
        """
        print("Assembler: Processing Member Loads (FEF)...")
        active_patterns = {pat: scale for pat, scale in self.dm.load_case['patterns']}
        
        for load in self.dm.raw['loads']:
                             
            if load['pattern'] not in active_patterns: continue
            if load['type'] not in ['member_dist', 'member_point']: continue
            
            scale = active_patterns[load['pattern']]
            
            el = next((e for e in self.dm.elements if e['id'] == load['element_id']), None)
            if not el: continue
            
            L_clear = el['L_clear']
            L_total = el['L_total']
            idx_i, idx_j = el['node_indices']
            p1 = self.dm.nodes[idx_i]['coords']
            p2 = self.dm.nodes[idx_j]['coords']
            
            ri = el.get('end_off_i', 0.0)
            rj = el.get('end_off_j', 0.0)
            
            mat = el['material']
            sec = el['section']
            k_raw = get_local_stiffness_matrix(
                E=mat['E'], G=mat['G'], A=sec['A'], J=sec['J'],
                I22=sec['I22'], I33=sec['I33'],
                As2=sec['As2'], As3=sec['As3'], 
                L=L_clear, L_tor=L_total
            )

            fef_local = np.zeros(12)
            R_3x3 = get_rotation_matrix(p1, p2, el['beta'])

            w_vec_local_for_offset = np.zeros(3) 

            if load['type'] == 'member_dist':
                w_defined = np.array([load['wx'], load['wy'], load['wz']]) * scale
                
                if load.get('coord', 'Global') == 'Global':
                    w_local = R_3x3 @ w_defined
                else:
                    w_local = w_defined

                if load.get('projected', False):
                    w_local = self._apply_projection_factor(
                        w_local, 
                        p1, 
                        p2, 
                        L_total, 
                        load.get('coord', 'Global')
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
                if idx_dir is None: continue 
                
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
    
            rows_i = slice(idx_i*6, idx_i*6+6)
            rows_j = slice(idx_j*6, idx_j*6+6)
            
            self.P[rows_i] -= fef_global[0:6]
            self.P[rows_j] -= fef_global[6:12]

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
