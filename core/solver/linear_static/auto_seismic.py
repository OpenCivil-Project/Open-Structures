import numpy as np
from core.solver.RSA.tsc2018_generator import TSC2018SpectrumGenerator

class AutoSeismicGenerator:
    def __init__(self, data_manager):
        self.dm = data_manager

    def generate_loads(self):
        """Main pipeline for Auto-Seismic generation."""
        active_patterns = [p[0] for p in self.dm.load_case['patterns']]
        tsc_patterns = []
        
        for pat in self.dm.raw.get('load_patterns', []):
            if pat['name'] in active_patterns and pat.get('auto_lateral') == 'TSC-2018':
                tsc_patterns.append(pat)

        if not tsc_patterns:
            return 

        print(f"Auto-Seismic: Found {len(tsc_patterns)} TSC-2018 pattern(s). Executing ELF procedure...")

        # PHASE 1: Extract Story Masses and Heights
        story_data = self._get_story_masses_and_heights()
        
        if not story_data:
            print("Auto-Seismic Warning: No mass detected. Skipping.")
            return
            
        # PHASE 2 & 3: Calculate Base Shear and Distribute/Inject
        for pat in tsc_patterns:
            self._apply_tsc2018_forces(pat, story_data)

    def _get_story_masses_and_heights(self):
        """Builds mass matrix and extracts weight per floor/node."""
        from core.solver.modal.mass_assembler import GlobalMassAssembler
        
        ms_name = "Default"
        if self.dm.raw.get("mass_sources"):
            ms_name = self.dm.raw["mass_sources"][0]["name"]
            
        mass_asm = GlobalMassAssembler(self.dm)
        M_full = mass_asm.build_mass_matrix(ms_name)
        M_diag = M_full.diagonal()

        story_data = {} 
        active_dia = {k: v for k, v in getattr(self.dm, 'diaphragm_groups', {}).items() if len(v) >= 2}

        # Keep track of nodes already assigned to a diaphragm to prevent double-counting mass
        diaphragm_nodes = set()

        # --- STEP 1: Process Rigid Diaphragms ---
        for dia_name, node_ids in active_dia.items():
            master_id = min(node_ids)
            master_node = next(n for n in self.dm.nodes if n['id'] == master_id)
            z_elev = master_node['coords'][2]
            
            story_mass = 0.0
            node_masses = {}
            for nid in node_ids:
                node = next(n for n in self.dm.nodes if n['id'] == nid)
                idx = node['idx'] * 6
                m = M_diag[idx]
                story_mass += m
                node_masses[nid] = m
                diaphragm_nodes.add(nid)

            story_data[z_elev] = {"mass": story_mass, "nodes": node_masses, "diaphragm": dia_name}

        # --- STEP 2: Process Unassigned Nodes (Auto-Cluster by Z) ---
        z_tol = 0.05 
        for node in self.dm.nodes:
            nid = node['id']
            if nid in diaphragm_nodes:
                continue # Skip nodes already processed in Step 1
                
            z = node['coords'][2]
            idx = node['idx'] * 6
            node_mass = M_diag[idx]
            
            if node_mass < 1e-6: continue 
            
            matched_z = next((existing_z for existing_z in story_data.keys() if abs(z - existing_z) <= z_tol), None)
            
            if matched_z is not None:
                story_data[matched_z]["mass"] += node_mass
                story_data[matched_z]["nodes"][nid] = node_mass
            else:
                story_data[z] = {"mass": node_mass, "nodes": {nid: node_mass}, "diaphragm": None}

        return story_data

    def _apply_tsc2018_forces(self, pattern, story_data):
        """Calculates TBDY-2018 ELF forces and injects them into the DataManager."""
        pat_name = pattern['name']
        tsc = pattern.get('tsc_data', {})
        
        dir_val = tsc.get('direction', 'X')
        ecc = float(tsc.get('eccentricity', 0.05))
        period_method = tsc.get('period_method', 'Approx')
        ct = float(tsc.get('ct', 0.10))
        user_t = float(tsc.get('user_t', 0.0))
        
        ss = float(tsc.get('ss', 0.0))
        s1 = float(tsc.get('s1', 0.0))
        tl = float(tsc.get('tl', 6.0))
        site_class = tsc.get('site_class', 'ZB')
        
        R_val = float(tsc.get('r', 8.0))
        D_val = float(tsc.get('d', 3.0))
        I_val = float(tsc.get('importance', 1.0))

        # 1. Geometry and Weight
        g = 9.80665
        
        # Find true base elevation from restrained nodes (Supports)
        try:
            base_z = min([n['coords'][2] for n in self.dm.nodes if any(n['restraints'])])
        except ValueError:
            base_z = 0.0 # Fallback if no supports exist

        z_max = max(story_data.keys())
        H = z_max - base_z
        
        if H <= 0: 
            print(f"      Warning: Calculated building height H={H} <= 0. Skipping.")
            return

        total_mass = sum(v["mass"] for v in story_data.values())
        total_weight = total_mass * g

        # 2. Fundamental Period (T)
        if period_method == "User" and user_t > 0:
            T = user_t
        else:
            T = ct * (H ** 0.75)

        # 3. TSC-2018 Spectrum Calculation
        gen = TSC2018SpectrumGenerator()
        fs, f1 = gen.get_coeffs(ss, s1, site_class)
        sds = ss * fs
        sd1 = s1 * f1
        
        Ta = 0.2 * sd1 / sds if sds > 0 else 0.0
        Tb = sd1 / sds if sds > 0 else 0.0

        # Elastic Spectral Acceleration Sae(T)
        if T < Ta: sae = sds * (0.4 + 0.6 * T / Ta)
        elif T <= Tb: sae = sds
        elif T <= tl: sae = sd1 / T
        else: sae = (sd1 * tl) / (T**2)

        # Reduction Factor Ra(T)
        if T > Tb: Ra = R_val / I_val
        else: Ra = D_val + (R_val/I_val - D_val) * (T / Tb)

        # Design Spectral Acceleration SaR(T)
        sar = sae / Ra
        
        # Base Shear (Vt) with Code Minimum Check
        V = total_weight * sar
        V_min = 0.04 * I_val * sds * total_weight
        V = max(V, V_min)

        print(f"      [{pat_name}] T={T:.3f}s, SaR={sar:.4g}, V_base={V:.2f} N")

        # 4. Vertical Distribution (TBDY Eq 4.7.7)
        N_stories = len(story_data)
        dFn = 0.0075 * N_stories * V
        if dFn > 0.1 * V: dFn = 0.1 * V
        
        # hi must be measured from the base level!
        sum_wh = sum((data["mass"] * g) * (z - base_z) for z, data in story_data.items())

        forces = {}
        for z, data in story_data.items():
            wi = data["mass"] * g
            hi = z - base_z
            
            if sum_wh > 0:
                Fi = (V - dFn) * (wi * hi) / sum_wh
            else:
                Fi = V / N_stories # Failsafe for single story
                
            if z == z_max:
                Fi += dFn # Add roof force
                
            forces[z] = Fi

        # 5. Injection (The Golden Ticket)
        # Prepare the seismic dictionary so the UI and static solver catch it
        if 'seismic_data' not in pattern:
            pattern['seismic_data'] = {'eccentricity': ecc, 'diaphragm_loads': {}}
            
        pattern['seismic_data']['eccentricity'] = ecc
        pattern['seismic_data']['diaphragm_loads'] = {}
        
        # Clean out any old nodal loads generated by this pattern previously
        if 'loads' not in self.dm.raw: self.dm.raw['loads'] = []
        self.dm.raw['loads'] = [L for L in self.dm.raw['loads'] if not (L.get('pattern') == pat_name and L.get('_auto_generated'))]

        # Apply the loads
        for z, data in story_data.items():
            Fi = forces[z]
            Fx = Fi if dir_val == "X" else 0.0
            Fy = Fi if dir_val == "Y" else 0.0

            if data["diaphragm"]:
                # Route 1: Drop onto the Diaphragm Master Node
                dia_name = data["diaphragm"]
                pattern['seismic_data']['diaphragm_loads'][dia_name] = {"Fx": Fx, "Fy": Fy, "Mz": 0.0}
            else:
                # Route 2: No Diaphragm? Distribute strictly by individual node mass
                floor_mass = data["mass"]
                for nid, n_mass in data["nodes"].items():
                    fraction = n_mass / floor_mass if floor_mass > 0 else 0.0
                    if fraction > 0:
                        self.dm.raw['loads'].append({
                            "type": "nodal",
                            "pattern": pat_name,
                            "node_id": nid,
                            "fx": Fx * fraction,
                            "fy": Fy * fraction,
                            "fz": 0.0, "mx": 0.0, "my": 0.0, "mz": 0.0,
                            "_auto_generated": True # Hidden tag so we can clean it up later!
                        })