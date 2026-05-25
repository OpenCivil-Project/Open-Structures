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
                
                w_vec = np.array([load.get('wx', 0.0), load.get('wy', 0.0), load.get('wz', 0.0)])
                
                if load.get('coord', 'Global') == 'Local':
                    idx_i, idx_j = el['node_indices']
                    p1_adj = self.dm.nodes[idx_i]['coords'] + np.array(el['offsets'][0])
                    p2_adj = self.dm.nodes[idx_j]['coords'] + np.array(el['offsets'][1])
                    R = get_rotation_matrix(p1_adj, p2_adj, el['beta'])
                    w_global = R.T @ w_vec
                else:
                    w_global = w_vec
                
                F_total = w_global * el['L_total'] * multiplier
                
                for n_idx in el['node_indices']:
                    dof = n_idx * 6
                    F_accum[dof + 0] += F_total[0] / 2.0
                    F_accum[dof + 1] += F_total[1] / 2.0
                    F_accum[dof + 2] += F_total[2] / 2.0

            elif load["type"] == "member_point":
                el = next((e for e in self.dm.elements if e['id'] == load['element_id']), None)
                if not el: continue

                force = load.get('force', 0.0)
                direction = load.get('dir', 'Gravity')
                coord = load.get('coord', 'Global')

                F_vec_global = np.zeros(3)
                
                if direction == "Gravity":

                    F_vec_global[2] = -abs(force) 
                elif coord == "Global":
                    idx = 0 if "X" in direction else (1 if "Y" in direction else 2)
                    F_vec_global[idx] = force
                elif coord == "Local":
                    local_vec = np.zeros(3)
                    idx = 0 if "1" in direction else (1 if "2" in direction else 2)
                    local_vec[idx] = force
                    
                    idx_i, idx_j = el['node_indices']
                    p1_adj = self.dm.nodes[idx_i]['coords'] + np.array(el['offsets'][0])
                    p2_adj = self.dm.nodes[idx_j]['coords'] + np.array(el['offsets'][1])
                    R = get_rotation_matrix(p1_adj, p2_adj, el['beta'])
                    F_vec_global = R.T @ local_vec

                F_vec_global *= multiplier

                dist = load.get('dist', 0.5)
                if not load.get('is_rel', True): dist = dist / el['L_total']
                
                ratios = [1.0 - dist, dist] 
                
                for k, n_idx in enumerate(el['node_indices']):
                    dof = n_idx * 6
                    F_accum[dof + 0] += F_vec_global[0] * ratios[k]
                    F_accum[dof + 1] += F_vec_global[1] * ratios[k]
                    F_accum[dof + 2] += F_vec_global[2] * ratios[k]

        print("   -> Converting NET Gravity Forces to Mass...")
        mass_added_count = 0

        for i in range(2, self.total_dofs, 6):
            Fz_net = F_accum[i]
            
            if Fz_net < -1e-5:
                mass_val = abs(Fz_net) / g
                
                self.M[i-2, i-2] += mass_val
                self.M[i-1, i-1] += mass_val
                self.M[i,   i]   += mass_val
                mass_added_count += 1
            
        print(f"   -> Added Net Mass to {mass_added_count} nodes.")
