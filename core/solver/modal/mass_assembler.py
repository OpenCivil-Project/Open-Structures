import numpy as np
from scipy.sparse import lil_matrix

class GlobalMassAssembler:
    def __init__(self, data_manager):
        self.dm = data_manager
        self.total_dofs = self.dm.total_dofs
        self.M = lil_matrix((self.total_dofs, self.total_dofs))
        print(" [DEBUG] Initialized Mass Assembler (V4 - Net Force Method)")

    def build_mass_matrix(self, mass_source_name, progress_callback=None):
        print(f"Mass Assembler: Building M for source '{mass_source_name}'...")
        
        ms_def = self._find_mass_source(mass_source_name)
        if not ms_def:
            print(f"Error: Mass Source '{mass_source_name}' not found. Using zero mass.")
            return self.M

        if ms_def.get("include_self_mass", True):
            if progress_callback:
                progress_callback("Adding element self-weight mass...", 29)
            self._add_element_self_mass()

        if ms_def.get("include_patterns", False):
            patterns = ms_def.get("load_patterns", []) 
            if progress_callback:
                progress_callback("Adding load pattern mass...", 33)
            self._add_mass_from_net_loads(patterns)

        print(f"Mass Assembler: Mass Matrix Assembled. Non-zeros: {self.M.nnz}")
        return self.M

    def _find_mass_source(self, name):
        sources = self.dm.raw.get("mass_sources", [])
        if isinstance(sources, list):
            for s in sources:
                if s["name"] == name: return s
        elif isinstance(sources, dict):
             if name in sources: return sources[name]
        
        if name == "Default":
            if sources:
                if isinstance(sources, list): return sources[0]  
                elif isinstance(sources, dict): return list(sources.values())[0]
        return None

    def _add_element_self_mass(self, scale_factor=1.0):
        print(f"   -> Adding Element Self-Mass (Lumped, Scale={scale_factor:.2f})...")
        for el in self.dm.elements:
            A = el['section']['A']
            rho = el['material']['rho'] 
            L = el['L_total']
            g = 9.80665
            mass_density = rho / g
                                          
            total_mass = A * mass_density * L * scale_factor 
            
            for n_idx in el['node_indices']:
                start_dof = n_idx * 6
                half_mass = total_mass / 2.0
                
                self.M[start_dof + 0, start_dof + 0] += half_mass
                self.M[start_dof + 1, start_dof + 1] += half_mass
                self.M[start_dof + 2, start_dof + 2] += half_mass

    def _add_mass_from_net_loads(self, pattern_list):
        print("   -> Calculating Net Nodal Forces (Algebraic Sum)...")
        g = 9.80665
        from element_library import get_rotation_matrix
        
        F_accum = np.zeros(self.total_dofs)
        
        active_patterns = {}
        for item in pattern_list:
             if isinstance(item, list): active_patterns[item[0]] = item[1]
             elif isinstance(item, dict): active_patterns[item["name"]] = item["scale"]

        if not active_patterns: return

        raw_patterns = self.dm.raw.get("load_patterns", []) 
        
        for pat_name, multiplier in active_patterns.items():
            sw_mult = 0.0
            
            for rp in raw_patterns:
                if rp.get("name") == pat_name:
                    sw_mult = rp.get("sw_mult", 0.0) 
                    break
            
            total_sw_factor = multiplier * sw_mult
            if total_sw_factor > 1e-6:
                print(f"   -> Load Pattern '{pat_name}' has self-weight ({sw_mult}). Adding to mass matrix...")
                self._add_element_self_mass(scale_factor=total_sw_factor)
                
        for load in self.dm.raw.get("loads", []):
            if load.get('_is_sw', False): continue
            pat = load["pattern"]
            if pat not in active_patterns: continue
            
            multiplier = active_patterns[pat]
            
            if load["type"] == "nodal":
                node_idx = self.dm.node_id_to_idx[load["node_id"]]
                start_dof = node_idx * 6
                
                F_accum[start_dof + 0] += load.get("fx", 0.0) * multiplier
                F_accum[start_dof + 1] += load.get("fy", 0.0) * multiplier
                F_accum[start_dof + 2] += load.get("fz", 0.0) * multiplier

            elif load["type"] == "member_dist":
                el = next((e for e in self.dm.elements if e['id'] == load['element_id']), None)
                if not el: continue

                idx_i, idx_j = el['node_indices']
                p1 = self.dm.nodes[idx_i]['coords']
                p2 = self.dm.nodes[idx_j]['coords']

                L_clear = el['L_clear']
                L_total = el['L_total']
                ri = el.get('end_off_i', 0.0)
                rj = el.get('end_off_j', 0.0)

                mat, sec = el['material'], el['section']

                from element_library import get_rotation_matrix, get_varying_fef_via_integration, get_eccentricity_matrix, condense_fef, get_local_stiffness_matrix
                R_3x3 = get_rotation_matrix(p1, p2, el['beta'])

                proj_factor = 1.0
                coord_sys = str(load.get('coord', 'Global')).upper()
                if load.get('projected', False) and coord_sys == 'GLOBAL':
                    dx = p2[0] - p1[0]
                    dy = p2[1] - p1[1]
                    L_horiz = np.sqrt(dx**2 + dy**2)
                    if L_total > 1e-9: proj_factor = L_horiz / L_total

                mags = np.array(load.get('magnitudes', [0,0,0,0])) * multiplier
                
                if any(abs(m) > 1e-9 for m in mags):
                                                                               
                    dists = np.array(load.get('distances', [0, 0.25, 0.75, 1.0]))
                    if load.get('is_relative', True): dists = dists * L_total
                    dir_str = str(load.get('load_direction', 'Gravity')).upper()
                    
                    w_vectors_local = []
                    for m in mags:
                        vec = np.zeros(3)
                        if "GRAVITY" in dir_str: vec[2] = m 
                        elif "X" in dir_str or "1" in dir_str: vec[0] = m
                        elif "Y" in dir_str or "2" in dir_str: vec[1] = m
                        elif "Z" in dir_str or "3" in dir_str: vec[2] = m
                        
                        if coord_sys == 'GLOBAL': vec_local = R_3x3 @ vec
                        else: vec_local = vec
                        
                        vec_local *= proj_factor
                        w_vectors_local.append(vec_local)
                    
                    fef_local, F_ri, M_ri_cent, F_rj, M_rj_cent = get_varying_fef_via_integration(
                        L_clear, L_total, ri, rj, dists, w_vectors_local, mat, sec
                    )
                    
                    if any(el['releases'][0]) or any(el['releases'][1]):
                        k_raw = get_local_stiffness_matrix(E=mat['E'], G=mat['G'], A=sec['A'], J=sec['J'], I22=sec['I22'], I33=sec['I33'], As2=sec['As2'], As3=sec['As3'], L=L_clear, L_tor=L_total)
                        fef_local = condense_fef(k_raw, fef_local, el['releases'])

                    T_rot = np.zeros((12, 12))
                    for i in range(4): T_rot[i*3:(i+1)*3, i*3:(i+1)*3] = R_3x3
                    
                    loc_off_insertion_i = R_3x3 @ np.array(el['offsets'][0])
                    loc_off_insertion_j = R_3x3 @ np.array(el['offsets'][1])
                    
                    loc_off_total_i = loc_off_insertion_i.copy()
                    loc_off_total_j = loc_off_insertion_j.copy()
                    loc_off_total_i[0] += ri
                    loc_off_total_j[0] -= rj

                    T_ecc = get_eccentricity_matrix(loc_off_total_i, loc_off_total_j)
                    T_total = T_ecc @ T_rot

                    fef_global = T_total.T @ fef_local

                    if ri > 0:
                        M_rigid_i = M_ri_cent + np.cross(loc_off_insertion_i, F_ri)
                        fef_global[0:3] -= R_3x3.T @ F_ri
                        fef_global[3:6] -= R_3x3.T @ M_rigid_i
                    if rj > 0:
                        M_rigid_j = M_rj_cent + np.cross(loc_off_insertion_j, F_rj)
                        fef_global[6:9] -= R_3x3.T @ F_rj
                        fef_global[9:12] -= R_3x3.T @ M_rigid_j

                    equiv_nodal_force = -fef_global

                else:
                                                                                      
                    w_defined = np.array([load.get('wx', 0.0), load.get('wy', 0.0), load.get('wz', 0.0)]) * multiplier
                    if coord_sys == 'GLOBAL': w_local = R_3x3 @ w_defined
                    else: w_local = w_defined
                    w_local *= proj_factor
                    
                    wx, wy, wz = w_local
                    fef_local = np.zeros(12)
                    fef_local[0] = -wx * L_clear / 2;    fef_local[6] = -wx * L_clear / 2
                    fef_local[1] = -wy * L_clear / 2;    fef_local[7] = -wy * L_clear / 2
                    fef_local[5] = -wy * L_clear**2/12;  fef_local[11]=  wy * L_clear**2/12
                    fef_local[2] = -wz * L_clear / 2;    fef_local[8] = -wz * L_clear / 2
                    fef_local[4] =  wz * L_clear**2/12;  fef_local[10]= -wz * L_clear**2/12

                    if any(el['releases'][0]) or any(el['releases'][1]):
                        k_raw = get_local_stiffness_matrix(E=mat['E'], G=mat['G'], A=sec['A'], J=sec['J'], I22=sec['I22'], I33=sec['I33'], As2=sec['As2'], As3=sec['As3'], L=L_clear, L_tor=L_total)
                        fef_local = condense_fef(k_raw, fef_local, el['releases'])

                    T_rot = np.zeros((12, 12))
                    for i in range(4): T_rot[i*3:(i+1)*3, i*3:(i+1)*3] = R_3x3
                    
                    loc_off_total_i = R_3x3 @ np.array(el['offsets'][0])
                    loc_off_total_j = R_3x3 @ np.array(el['offsets'][1])
                    loc_off_insertion_i = loc_off_total_i.copy()
                    loc_off_insertion_j = loc_off_total_j.copy()
                    loc_off_total_i[0] += ri
                    loc_off_total_j[0] -= rj

                    T_ecc = get_eccentricity_matrix(loc_off_total_i, loc_off_total_j)
                    T_total = T_ecc @ T_rot

                    fef_global = T_total.T @ fef_local

                    if ri > 0:
                        F_rigid_i = np.array([wx, wy, wz]) * ri
                        centroid_i = np.array([ri/2.0, 0, 0]) + loc_off_insertion_i
                        M_rigid_i = np.cross(centroid_i, F_rigid_i)
                        fef_global[0:3] -= R_3x3.T @ F_rigid_i
                        fef_global[3:6] -= R_3x3.T @ M_rigid_i
                    if rj > 0:
                        F_rigid_j = np.array([wx, wy, wz]) * rj
                        centroid_j = np.array([-rj/2.0, 0, 0]) + loc_off_insertion_j
                        M_rigid_j = np.cross(centroid_j, F_rigid_j)
                        fef_global[6:9] -= R_3x3.T @ F_rigid_j
                        fef_global[9:12] -= R_3x3.T @ M_rigid_j

                    equiv_nodal_force = -fef_global
                
                dof_i = idx_i * 6
                dof_j = idx_j * 6
                F_accum[dof_i + 0] += equiv_nodal_force[0]
                F_accum[dof_i + 1] += equiv_nodal_force[1]
                F_accum[dof_i + 2] += equiv_nodal_force[2]
                F_accum[dof_j + 0] += equiv_nodal_force[6]
                F_accum[dof_j + 1] += equiv_nodal_force[7]
                F_accum[dof_j + 2] += equiv_nodal_force[8]

            elif load["type"] == "member_point":
                                                              
                if load.get("l_type", "Force") == "Moment":
                    continue 
                
                el = next((e for e in self.dm.elements if e['id'] == load['element_id']), None)
                if not el: continue
                
                dir_str = str(load.get('dir', 'Gravity')).upper()
                P_val = load['force'] * multiplier
                
                vec_defined = np.zeros(3)
                if "GRAVITY" in dir_str: vec_defined[2] = -P_val
                elif "X" in dir_str or "1" in dir_str: vec_defined[0] = P_val
                elif "Y" in dir_str or "2" in dir_str: vec_defined[1] = P_val
                elif "Z" in dir_str or "3" in dir_str: vec_defined[2] = P_val
                
                coord_sys = load.get('coord', 'Global')
                if "GRAVITY" in dir_str: coord_sys = 'Global'
                
                if coord_sys == 'Global':
                    vec_global = vec_defined
                else:
                    idx_i, idx_j = el['node_indices']
                    p1 = self.dm.nodes[idx_i]['coords']
                    p2 = self.dm.nodes[idx_j]['coords']
                    from element_library import get_rotation_matrix
                    R_3x3 = get_rotation_matrix(p1, p2, el['beta'])
                    vec_global = R_3x3.T @ vec_defined 
                    
                L_total = el['L_total']
                dist = load['dist']
                if load.get('is_rel', False): 
                    dist *= L_total
                
                frac_j = dist / L_total
                frac_i = 1.0 - frac_j
                
                idx_i, idx_j = el['node_indices']
                dof_i = idx_i * 6
                dof_j = idx_j * 6
                
                F_accum[dof_i + 0] += vec_global[0] * frac_i
                F_accum[dof_i + 1] += vec_global[1] * frac_i
                F_accum[dof_i + 2] += vec_global[2] * frac_i
                
                F_accum[dof_j + 0] += vec_global[0] * frac_j
                F_accum[dof_j + 1] += vec_global[1] * frac_j
                F_accum[dof_j + 2] += vec_global[2] * frac_j

        print("   -> Converting NET Gravity Forces to Mass...")
        mass_added_count = 0

        for i in range(2, self.total_dofs, 6):
            Fz_net = F_accum[i]
            
            mass_val = -Fz_net / g
            
            if abs(mass_val) > 1e-8:
                self.M[i-2, i-2] += mass_val
                self.M[i-1, i-1] += mass_val
                self.M[i,   i]   += mass_val
                mass_added_count += 1
            
        print(f"   -> Added Net Mass to {mass_added_count} nodes.")
