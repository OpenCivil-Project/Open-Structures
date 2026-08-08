import json
import numpy as np
from error_definitions import SolverException
import math

class DataManager:
    def __init__(self, json_path):
        try:
            with open(json_path, 'r') as f:
                self.raw = json.load(f)
        except FileNotFoundError:
            raise SolverException("E101", f"Path: {json_path}")
        except json.JSONDecodeError:
            raise SolverException("E102", f"File: {json_path}")

        self.active_dofs = self.raw.get("info", {}).get("active_dofs", [True, True, True, True, True, True])
        
        self.node_id_to_idx = {}                         
        self.materials = {}                              
        self.sections = {}                              
        
        self.nodes = []                                      
        self.elements = []   
        self.link_properties = {}
        self.links_1j = []
        self.links_2j = []                                   
        self.load_case = None                                       
        self.total_dofs = 0                                      

    def _generate_self_weight(self):
        """
        Calculates self-weight for frames and links, injecting them as 
        loads into the raw load list.
        """
        if 'load_patterns' not in self.raw: return
        
        active_pattern_names = {p[0] for p in self.load_case['patterns']} 
        
        target_patterns = []
        for pat in self.raw['load_patterns']:
            if pat['name'] in active_pattern_names and pat['sw_mult'] != 0:
                target_patterns.append(pat)

        if not target_patterns: return

        print(f"      Generating self-weight for patterns: {[p['name'] for p in target_patterns]}")

        count = 0
        
        for el in self.elements:
                                                        
            A_gross = el['section'].get('A_gross', el['section']['A'])
            gamma = el['material']['rho']                                  
            weight_mod = el['section'].get('weight_mod', 1.0)
            
            w_per_len = A_gross * gamma * weight_mod
            
            if w_per_len <= 1e-9: continue

            for pat in target_patterns:
                mult = pat['sw_mult']
                w_z = -1.0 * w_per_len * mult
                
                new_load = {
                    'type': 'member_dist',
                    'pattern': pat['name'],
                    'element_id': el['id'],
                    'wx': 0.0, 
                    'wy': 0.0, 
                    'wz': w_z,
                    'coord': 'Global',
                    'projected': False,
                    '_is_sw': True
                }
                
                if 'loads' not in self.raw: self.raw['loads'] = []
                self.raw['loads'].append(new_load)
                count += 1
                
        for link in self.raw.get('links', []):
            prop = self.link_properties.get(link['prop_name'])
            if not prop: continue
            
            weight = prop.get('weight', 0.0)
            if weight <= 1e-9: continue
            
            nodes = link.get('nodes', [])
            if not nodes: continue
            
            weight_per_node = weight / len(nodes)
            
            for pat in target_patterns:
                mult = pat['sw_mult']
                fz = -1.0 * weight_per_node * mult
                
                for nid in nodes:
                    new_load = {
                        'type': 'nodal',
                        'pattern': pat['name'],
                        'node_id': nid,
                        'fx': 0.0, 'fy': 0.0, 'fz': fz,
                        'mx': 0.0, 'my': 0.0, 'mz': 0.0,
                        '_is_sw': True
                    }
                    if 'loads' not in self.raw: self.raw['loads'] = []
                    self.raw['loads'].append(new_load)
                    count += 1

        if count > 0:
            print(f"      -> Injected {count} self-weight load records.")
            
    def process_all(self, case_name="DEAD"):
        """The master sequence to prepare the solver data."""
        self._parse_properties()
        self._map_nodes()
        self._parse_elements()
        self._parse_links()
        self._prepare_load_case(case_name)
        self._generate_self_weight()
        self._generate_tendon_loads()
        
        from auto_seismic import AutoSeismicGenerator
        AutoSeismicGenerator(self).generate_loads()

    def _map_nodes(self):
                                         
        user_ids = sorted([n['id'] for n in self.raw['nodes']])
        for idx, u_id in enumerate(user_ids):
            self.node_id_to_idx[u_id] = idx
            
        for n_data in self.raw['nodes']:
            self.nodes.append({
                'id': n_data['id'],
                'idx': self.node_id_to_idx[n_data['id']],
                'coords': np.array([n_data['x'], n_data['y'], n_data['z']]),
                'restraints': n_data['restraints'],
                'diaphragm': n_data.get('diaphragm', None),
                                                                   
                'spring_matrix': np.array(n_data['spring_matrix']) if n_data.get('spring_matrix') else None
            })
            
        self.total_dofs = len(user_ids) * 6

        self.diaphragm_groups = {}
        for c in self.raw.get('constraints', []):
            self.diaphragm_groups[c['name']] = []
        for node in self.nodes:
            dia = node['diaphragm']
            if dia and dia in self.diaphragm_groups:
                self.diaphragm_groups[dia].append(node['id'])
        
        active = {k: v for k, v in self.diaphragm_groups.items() if len(v) >= 2}
        if active:
            print(f"      Diaphragms found: { {k: len(v) for k, v in active.items()} }")

    def _parse_properties(self):
                            
        for mat in self.raw['materials']:
            self.materials[mat['name']] = {
                'E': mat['E'], 
                'G': mat['G'], 
                'rho': mat['rho']
            }
            
        for sec in self.raw['sections']:
            p = sec['properties']
            mods = sec.get('modifiers', {})                                       
            
            self.sections[sec['name']] = {
                'mat_name': sec['mat_name'],
                'A_gross': p.get('A', 0.0),                                                  
                'A':   p.get('A', 0.0) * mods.get('A', 1.0),
                'J':   p.get('J', 0.0) * mods.get('J', 1.0),
                'I33': p.get('I33', 0.0) * mods.get('I3', 1.0),
                'I22': p.get('I22', 0.0) * mods.get('I2', 1.0),
                'As2': p.get('As2', 0.0) * mods.get('As2', 1.0),
                'As3': p.get('As3', 0.0) * mods.get('As3', 1.0),
                'theta_p': p.get('theta_p', 0.0),
                'mass_mod': mods.get('Mass', 1.0),
                'weight_mod': mods.get('Weight', 1.0)
            }
                                                                                
        for lp in self.raw.get('link_properties', []):
            self.link_properties[lp['name']] = {
                'stiffness': np.array(lp.get('stiffness', np.zeros((6, 6)))),
                'damping': np.array(lp.get('damping', np.zeros((6, 6)))),
                'is_fixed': lp.get('is_fixed', [False] * 6),
                'mass': lp.get('mass', 0.0),
                'weight': lp.get('weight', 0.0),
                'r1': lp.get('r1', 0.0),
                'r2': lp.get('r2', 0.0),
                'r3': lp.get('r3', 0.0)
            }
        
    def _parse_elements(self):
        for el_data in self.raw['elements']:
                              
            idx_i = self.node_id_to_idx[el_data['n1_id']]
            idx_j = self.node_id_to_idx[el_data['n2_id']]
            
            p1 = next(n['coords'] for n in self.nodes if n['idx'] == idx_i)
            p2 = next(n['coords'] for n in self.nodes if n['idx'] == idx_j)
            
            off_i = np.array(el_data.get('off_i', [0,0,0]))
            off_j = np.array(el_data.get('off_j', [0,0,0]))

            p1_adj = p1 + off_i
            p2_adj = p2 + off_j
            
            L_total = np.linalg.norm(p2_adj - p1_adj)
            
            L_total = np.linalg.norm(p2_adj - p1_adj)
            
            if L_total < 1e-9:
                raise SolverException("E201", f"Element ID: {el_data['id']} connects coincident nodes.")

            end_off_i = el_data.get('end_off_i', 0.0)
            end_off_j = el_data.get('end_off_j', 0.0)
            rz_factor = el_data.get('rz_factor', 0.0)
            
            rigid_i = end_off_i * rz_factor
            rigid_j = end_off_j * rz_factor
            L_clear = L_total - (rigid_i + rigid_j)
            
            try:
                self.elements.append({
                    'id': el_data['id'],
                    'node_indices': [idx_i, idx_j],
                    'section': self.sections[el_data['sec_name']],
                    'material': self.materials[self.sections[el_data['sec_name']]['mat_name']],
                    'L_total': L_total,
                    'L_clear': L_clear,
                    'end_off_i': end_off_i, 
                    'end_off_j': end_off_j,
                    'rz_factor': rz_factor,                       
                    'beta': el_data['beta'],
                    'releases': [el_data['rel_i'], el_data['rel_j']],
                    'offsets': [el_data['off_i'], el_data['off_j']]
                })
            except KeyError as e:
                                                   
                raise SolverException("E103", f"Element {el_data['id']} references missing section: {e}")

    def _prepare_load_case(self, case_name):
                                
        case_data = next((c for c in self.raw['load_cases'] if c['name'] == case_name), None)
        
        if not case_data and case_name == "DEAD" and len(self.raw['load_cases']) > 0:
             case_data = self.raw['load_cases'][0]

        if not case_data:
            raise SolverException("E104", f"Load Case '{case_name}' is not defined in the input.")
            
        self.load_case = {
            'name': case_name,
            'patterns': case_data.get('loads', []),
        }
        
    def build_load_vector(self, assembled_mass=None):
        """Constructs the global P vector for the selected Load Case."""
        P = np.zeros(self.total_dofs)
        
        active_patterns = {pat: scale for pat, scale in self.load_case['patterns']}
        
        for load in self.raw.get('loads', []):
            if load['pattern'] not in active_patterns: continue
            scale = active_patterns[load['pattern']]
            
            if load['type'] == 'nodal':
                node_idx = self.node_id_to_idx[load['node_id']]
                start_row = node_idx * 6
                forces = np.array([load['fx'], load['fy'], load['fz'], load['mx'], load['my'], load['mz']])
                P[start_row : start_row + 6] += forces * scale

        for pat_data in self.raw.get('load_patterns', []):
            pat_name = pat_data['name']
            if pat_name not in active_patterns: continue
            
            seismic_data = pat_data.get('seismic_data')
            if not seismic_data: continue

            scale = active_patterns[pat_name]
            ecc_ratio = seismic_data.get('eccentricity', 0.05)
            diaph_loads = seismic_data.get('diaphragm_loads', {})

            for dia_name, loads in diaph_loads.items():
                if dia_name not in self.diaphragm_groups: continue
                
                node_ids = self.diaphragm_groups[dia_name]
                if len(node_ids) < 2: continue

                master_id = min(node_ids)
                master_node = next(n for n in self.nodes if n['id'] == master_id)
                m_idx = master_node['idx'] * 6
                Xm, Ym = master_node['coords'][0], master_node['coords'][1]

                sum_mass = 0.0
                sum_mx = 0.0
                sum_my = 0.0
                X_min, Y_min = float('inf'), float('inf')
                X_max, Y_max = float('-inf'), float('-inf')

                for nid in node_ids:
                    n = next(node for node in self.nodes if node['id'] == nid)
                    x, y = n['coords'][0], n['coords'][1]
                    
                    X_min, X_max = min(X_min, x), max(X_max, x)
                    Y_min, Y_max = min(Y_min, y), max(Y_max, y)

                    m = 1.0 
                    if assembled_mass and str(nid) in assembled_mass:
                        m = assembled_mass[str(nid)][0]          

                    sum_mass += m
                    sum_mx += m * x
                    sum_my += m * y

                if sum_mass == 0: sum_mass = 1.0           
                X_com = sum_mx / sum_mass
                Y_com = sum_my / sum_mass

                Lx = X_max - X_min
                Ly = Y_max - Y_min

                Fx = loads.get('Fx', 0.0) * scale
                Fy = loads.get('Fy', 0.0) * scale
                Mz_user = loads.get('Mz', 0.0) * scale

                Mz_accidental = Fy * (ecc_ratio * Lx) - Fx * (ecc_ratio * Ly)
                
                Mz_offset = Fy * (X_com - Xm) - Fx * (Y_com - Ym)

                Mz_total = Mz_user + Mz_accidental + Mz_offset

                P[m_idx + 0] += Fx
                P[m_idx + 1] += Fy
                P[m_idx + 5] += Mz_total

                print(f"      Quake '{pat_name}' -> Diaphragm '{dia_name}': Fx={Fx:.2f}, Fy={Fy:.2f}, Mz={Mz_total:.2f} (Applied at Master Node {master_id})")

        return P
    
    def _parse_links(self):
        """Routes links into 1-Joint or 2-Joint categories. Generates phantom nodes for 1-Joint links."""
        for link_data in self.raw.get('links', []):
            prop = self.link_properties[link_data['prop_name']]

            if len(link_data['nodes']) == 1:
                                              
                parent_id = link_data['nodes'][0]
                parent_idx = self.node_id_to_idx[parent_id]
                parent_node = next(n for n in self.nodes if n['idx'] == parent_idx)
                
                phantom_id = f"{parent_id}~Link"
                phantom_idx = len(self.nodes)                       
                
                self.node_id_to_idx[phantom_id] = phantom_idx
                self.nodes.append({
                    'id': phantom_id,
                    'idx': phantom_idx,
                    'coords': np.copy(parent_node['coords']),
                    'restraints': [True, True, True, True, True, True],                  
                    'diaphragm': None,
                    'spring_matrix': None
                })
                
                self.total_dofs += 6 
                
                self.links_2j.append({
                    'id': link_data['id'],
                    'node_indices': [parent_idx, phantom_idx],
                    'property': prop,
                    'beta': link_data.get('beta', 0.0),
                    'p1': np.copy(parent_node['coords']),
                    'p2': np.copy(parent_node['coords']) 
                })

            elif len(link_data['nodes']) == 2:
                idx_i = self.node_id_to_idx[link_data['nodes'][0]]
                idx_j = self.node_id_to_idx[link_data['nodes'][1]]

                p1 = next(n['coords'] for n in self.nodes if n['idx'] == idx_i)
                p2 = next(n['coords'] for n in self.nodes if n['idx'] == idx_j)
                
                self.links_2j.append({
                    'id': link_data['id'],
                    'node_indices': [idx_i, idx_j],
                    'property': prop,
                    'beta': link_data.get('beta', 0.0),
                    'p1': p1,
                    'p2': p2
                })

    def _generate_tendon_loads(self):
        """
        Calculates equivalent loads for tendons modeled as 'Loads'
        and injects them into the raw load list as standard distributed/nodal loads.
        """
        if 'tendons' not in self.raw: return
        active_pattern_names = {p[0] for p in self.load_case['patterns']}
        from core.prestress.tendon_evaluator import TendonEvaluator
        from element_library import get_rotation_matrix
        import math
        import numpy as np
        
        if 'loads' in self.raw:
            self.raw['loads'] = [ld for ld in self.raw['loads'] if not ld.get('_is_tendon_auto')]
        
        count = 0
        for t_data in self.raw['tendons']:
            if t_data.get('modeling_option', 'Loads') != 'Loads': continue
            
            active_loads = [ld for ld in t_data.get('loads', []) if ld['pattern'] in active_pattern_names]
            if not active_loads: continue
                
            sec_name = t_data['sec_name']
            t_sec_data = next((s for s in self.raw.get('tendon_sections', []) if s['name'] == sec_name), None)
            if not t_sec_data: continue
                
            class MockTendonSection:
                def __init__(self, data):
                    self.area = data.get('area', 0.0)
                    class MockMat: E = 200e9 
                    self.material = MockMat()
            
            mock_sec = MockTendonSection(t_sec_data)
            layout_pts = t_data.get('layout_points', [])
            if not layout_pts: continue
            total_length = max(p['coord1'] for p in layout_pts)
            
            for load_data in active_loads:
                pat_name = load_data['pattern']
                evaluator = TendonEvaluator(layout_pts, mock_sec, load_data, total_length)
                
                current_x = 0.0
                for host_id in t_data.get('host_element_ids', []):
                    host_el = next((e for e in self.elements if e['id'] == host_id), None)
                    if not host_el: continue
                    el_len = host_el['L_total']
                    
                    num_samples = 5
                    dists = np.linspace(0, 1.0, num_samples)
                    mags_2 = []                                                      
                    mags_3 = []                                                        
                    
                    for d in dists:
                        local_x = current_x + (d * el_len)
                        P_x = evaluator.get_force(local_x)
                        mags_2.append(1.0 * P_x * evaluator.get_curvature(local_x))
                        mags_3.append(-1.0 * P_x * evaluator.get_curvature_z(local_x))
                        
                    if any(abs(m) > 1e-9 for m in mags_2):
                        if 'loads' not in self.raw: self.raw['loads'] = []
                        self.raw['loads'].append({
                            'type': 'member_dist', 'pattern': pat_name, 'element_id': host_id,
                            'load_direction': 'Local-3', 'coord': 'Local', 'projected': False,
                            'distances': dists.tolist(), 'magnitudes': mags_2, 'is_relative': True,
                            '_is_tendon_auto': True
                        })
                        count += 1
                    if any(abs(m) > 1e-9 for m in mags_3):
                        if 'loads' not in self.raw: self.raw['loads'] = []
                        self.raw['loads'].append({
                            'type': 'member_dist', 'pattern': pat_name, 'element_id': host_id,
                            'load_direction': 'Local-2', 'coord': 'Local', 'projected': False,
                            'distances': dists.tolist(), 'magnitudes': mags_3, 'is_relative': True,
                            '_is_tendon_auto': True
                        })
                        count += 1
                    current_x += el_len
                
                for end_type, force_val, host_id in [
                    ('I-End', evaluator.get_force(0.0), t_data.get('host_element_ids', [])[0]),
                    ('J-End', evaluator.get_force(total_length), t_data.get('host_element_ids', [])[-1])
                ]:
                    if force_val <= 1e-9: continue
                    
                    host_el = next((e for e in self.elements if e['id'] == host_id), None)
                    if not host_el: continue
                    
                    x_eval = 0.0 if end_type == 'I-End' else total_length
                    m2 = evaluator.get_slope(x_eval)                               
                    m3 = evaluator.get_slope_z(x_eval)                               
                    e2 = evaluator.get_eccentricity(x_eval)[1]                 
                    e3 = evaluator.get_eccentricity(x_eval)[2]                 
                    
                    t_vec = np.array([1.0, m2, m3])
                    t_vec = t_vec / np.linalg.norm(t_vec)
                    
                    sign = 1.0 if end_type == 'I-End' else -1.0
                    Fx = sign * force_val * t_vec[0]
                    f2 = sign * force_val * t_vec[1]                                                 
                    f3 = sign * force_val * t_vec[2]                                                   
                        
                    F_local = np.zeros(3)
                    M_local = np.zeros(3)
                    F_local[0] = Fx
                    
                    F_local[2] = f2
                    F_local[1] = -f3
                    ecc_vec = np.array([0.0, -e3, e2])
                    M_local = np.cross(ecc_vec, F_local)
                        
                    idx_i, idx_j = host_el['node_indices']
                    p1 = next(n['coords'] for n in self.nodes if n['idx'] == idx_i)
                    p2 = next(n['coords'] for n in self.nodes if n['idx'] == idx_j)
                    theta_p = host_el['section'].get('theta_p', 0.0)
                    beta_eff = host_el['beta'] - np.degrees(theta_p)
                    
                    R_3x3 = get_rotation_matrix(p1, p2, beta_eff)
                    F_global = R_3x3.T @ F_local
                    M_global = R_3x3.T @ M_local
                    
                    target_idx = idx_i if end_type == 'I-End' else idx_j
                    target_node_id = next(n['id'] for n in self.nodes if n['idx'] == target_idx)
                    
                    if 'loads' not in self.raw: self.raw['loads'] = []
                    self.raw['loads'].append({
                        'type': 'nodal', 'pattern': pat_name, 'node_id': target_node_id,
                        'fx': float(F_global[0]), 'fy': float(F_global[1]), 'fz': float(F_global[2]),
                        'mx': float(M_global[0]), 'my': float(M_global[1]), 'mz': float(M_global[2]),
                        '_is_tendon_auto': True
                    })
                    count += 1

                for i in range(1, len(layout_pts) - 1):
                    x_kink = layout_pts[i]['coord1']
                    P_kink = evaluator.get_force(x_kink)
                    
                    m2_before = evaluator.get_slope(x_kink - 1e-6)
                    m2_after = evaluator.get_slope(x_kink + 1e-6)
                    m3_before = evaluator.get_slope_z(x_kink - 1e-6)
                    m3_after = evaluator.get_slope_z(x_kink + 1e-6)
                    
                    F_kink_2 = 1.0 * P_kink * (math.sin(math.atan(m2_after)) - math.sin(math.atan(m2_before)))
                                                                                        
                    F_kink_3 = -1.0 * P_kink * (math.sin(math.atan(m3_after)) - math.sin(math.atan(m3_before)))
                    
                    if abs(F_kink_2) > 1e-9 or abs(F_kink_3) > 1e-9:
                        current_x = 0.0
                        for host_id in t_data.get('host_element_ids', []):
                            host_el = next((e for e in self.elements if e['id'] == host_id), None)
                            if not host_el: continue
                            el_len = host_el['L_total']
                            
                            if current_x - 1e-5 <= x_kink <= current_x + el_len + 1e-5:
                                rel_dist = max(0.0, min(1.0, (x_kink - current_x) / el_len)) 
                                if 'loads' not in self.raw: self.raw['loads'] = []
                                if abs(F_kink_2) > 1e-9:
                                    self.raw['loads'].append({
                                        'type': 'member_point', 'pattern': pat_name, 'element_id': host_id,
                                        'dir': '3', 'force': F_kink_2, 'dist': rel_dist, 'is_rel': True,
                                        'coord': 'Local', '_is_tendon_auto': True
                                    })
                                    count += 1
                                if abs(F_kink_3) > 1e-9:
                                    self.raw['loads'].append({
                                        'type': 'member_point', 'pattern': pat_name, 'element_id': host_id,
                                        'dir': '2', 'force': F_kink_3, 'dist': rel_dist, 'is_rel': True,
                                        'coord': 'Local', '_is_tendon_auto': True
                                    })
                                    count += 1
                                break 
                            current_x += el_len
                            
        if count > 0:
            print(f"      -> Injected {count} equivalent prestress load records.")
