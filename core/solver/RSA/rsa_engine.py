import sys
import os
import json
import numpy as np

current_dir = os.path.dirname(os.path.abspath(__file__)) 
solver_dir = os.path.dirname(os.path.dirname(current_dir)) 

if current_dir not in sys.path: sys.path.append(current_dir)
if solver_dir not in sys.path: sys.path.append(solver_dir)

from tsc2018_generator import TSC2018SpectrumGenerator

class RSAEngine:
    def __init__(self, modal_results_path, model_data):
        self.modal_path = modal_results_path
        self.model_data = model_data
        self.generator = TSC2018SpectrumGenerator()
        
    @staticmethod
    def _cqc_rho(omega_i, omega_j, zeta):
        """
        CQC cross-correlation coefficient.
        """
        if omega_i == 0 or omega_j == 0:
            return 1.0 if (omega_i == omega_j) else 0.0
        r = omega_i / omega_j
        num = 8.0 * zeta**2 * (1.0 + r) * r**1.5
        den = (1.0 - r**2)**2 + 4.0 * zeta**2 * r * (1.0 + r)**2
        return num / den if den != 0.0 else 1.0
    
    def run(self, function_name="FUNC1", direction="X", modal_comb="SRSS", damping_ratio=None, eq_scale=1.0, progress_callback=None):
                                                                    
        if progress_callback is None:
            def default_cb(msg, pct): print(msg)
            progress_callback = default_cb

        progress_callback(f"--- RSA ENGINE STARTED ({direction}-Direction, Modal Comb: {modal_comb}) ---", 10)
        
        if not os.path.exists(self.modal_path):
            raise Exception("Modal Results not found.\n\n>> Please set 'MODAL' to 'Run' in the Analysis Dialog first!")
            
        with open(self.modal_path, 'r') as f:
            modal_data = json.load(f)
            
        if "tables" not in modal_data or "periods" not in modal_data["tables"]:
            raise Exception("Modal Data is missing from the result file...")

        periods = modal_data["tables"]["periods"]
        mass_ratios = modal_data["tables"]["participation_mass"]
        mode_shapes = modal_data.get("mode_shapes", {}) 
        
        funcs = self.model_data.get("functions", {})
        if function_name not in funcs:
            progress_callback(f"Error: Function '{function_name}' not defined.", 10)
            return None
        func_params = funcs[function_name]
        progress_callback(f"Using Function: {function_name} (R={func_params['R']}, I={func_params['I']})", 15)

        spectrum_direction = func_params.get("Direction", "Horizontal")
        interp_method = func_params.get("Interpolation", "Linear") 
        
        if damping_ratio is not None:
            zeta = float(damping_ratio)
            progress_callback(f"      -> Using Load Case Damping: {zeta*100}%", 20)
        else:
            zeta = func_params.get("Damping", 0.05)
            progress_callback(f"      -> Using Function Default Damping: {zeta*100}%", 20)

        per_mode_shear = []          
        per_mode_omega = []          
        per_mode_u     = {}
        per_mode_cross_force = []      

        per_mode_mx = []
        per_mode_my = []
        per_mode_mz = []     

        if mode_shapes:
            first_mode = list(mode_shapes.values())[0]
            for nid in first_mode.keys():
                per_mode_u[nid] = []

        if zeta == 0.05:
            eta = 1.0
        else:

            source_damp_percent = 5.0
            target_damp_percent = zeta * 100.0
            
            denom = 2.31 - 0.41 * np.log(source_damp_percent)
            
            num = 2.31 - 0.41 * np.log(target_damp_percent)
            
            eta = num / denom
            progress_callback(f"      -> Applied Damping Correction (Newmark & Hall): {eta:.5f}", 22)

        progress_callback("-" * 65, 25)
        progress_callback(f"{'Mode':<5} | {'Period (s)':<10} | {'SaR (g)':<9} | {'Mass Ratio':<10} | {'Base Shear Coeff'}", 25)
        progress_callback("-" * 65, 25)

        g_exact = 9.80665
        spec_T, spec_Sa, params = self.generator.generate_spectrum_curve(
            ss=func_params['Ss'], s1=func_params['S1'], site_class=func_params['SiteClass'], 
            R=func_params['R'], D=func_params['D'], I=func_params['I'], 
            tl=func_params['TL'], direction=spectrum_direction, t_max=10.0                   
        )

        m_total_x = 0.0; m_total_y = 0.0; m_total_z = 0.0
        if "total_mass" in modal_data:
            m_total_x = modal_data["total_mass"].get("x", 0.0)
            m_total_y = modal_data["total_mass"].get("y", 0.0)
            m_total_z = modal_data["total_mass"].get("z", 0.0)
            
        detailed_table = []

        for i, mode_info in enumerate(periods):
            T = mode_info["T"]
            omega = mode_info["omega"]
            
            if interp_method == "Exact":
                                                                                         
                if spectrum_direction == "Horizontal":
                    if T == 0:
                        sar_g_raw = (0.4 * params["SDS"]) / func_params['D']
                    else:
                        sae = self.generator.calculate_horizontal_sa(T, params["SDS"], params["SD1"], params["TA"], params["TB"], func_params['TL'])
                        ra = self.generator.calculate_reduction_factor(T, func_params['R'], func_params['D'], func_params['I'], params["TB"])
                        sar_g_raw = sae / ra
                else:
                    if T == 0:
                        sar_g_raw = 0.32 * params["SDS"]
                    else:
                        sar_g_raw = self.generator.calculate_vertical_sa(T, params["SDS"], params["TA"], params["TB"], func_params['TL'])
            else:
                                                                              
                sar_g_raw = np.interp(T, spec_T, spec_Sa)
            sar_g = sar_g_raw * eta  

            if direction == "X": 
                ratio = mass_ratios[i]["Ux"]
                raw_g = mass_ratios[i].get("Gamma_x", 0.0)
                gamma = np.sign(raw_g) * np.sqrt(ratio * m_total_x) if m_total_x > 0 else 0.0
                
            elif direction == "Y": 
                ratio = mass_ratios[i]["Uy"]
                raw_g = mass_ratios[i].get("Gamma_y", 0.0)
                gamma = np.sign(raw_g) * np.sqrt(ratio * m_total_y) if m_total_y > 0 else 0.0
                
            else:
                ratio = mass_ratios[i]["Uz"]
                raw_g = mass_ratios[i].get("Gamma_z", 0.0)
                gamma = np.sign(raw_g) * np.sqrt(ratio * m_total_z) if m_total_z > 0 else 0.0
            
            if direction == "X" and m_total_y > 0:
                Uy_i = mass_ratios[i].get("Uy", 0.0)
                gamma_x = np.sqrt(ratio   * m_total_x) if ratio   > 0 else 0.0
                gamma_y = np.sqrt(Uy_i    * m_total_y) if Uy_i    > 0 else 0.0
                cross_force_i = gamma_x * gamma_y * sar_g * eq_scale                  
            elif direction == "Y" and m_total_x > 0:
                Ux_i = mass_ratios[i].get("Ux", 0.0)
                gamma_y = np.sqrt(ratio   * m_total_y) if ratio   > 0 else 0.0
                gamma_x = np.sqrt(Ux_i    * m_total_x) if Ux_i    > 0 else 0.0
                cross_force_i = gamma_x * gamma_y * sar_g * eq_scale                  
            else:
                cross_force_i = 0.0
            per_mode_cross_force.append(cross_force_i)

            if i < 6:
                print(f"[CROSS] Mode {i+1}: ratio={ratio:.5f}, cross_i={cross_force_i:.4f} kN")

            if omega > 0:
                accel_ms2 = sar_g * eq_scale                  
                sd = accel_ms2 / (omega**2)
            else:
                accel_ms2 = 0.0
                sd = 0.0

            base_shear_coeff = sar_g * ratio
            
            per_mode_shear.append(base_shear_coeff)
            per_mode_omega.append(omega)

            pct = 25 + int(50 * (i + 1) / len(periods))
            progress_callback(f"{i+1:<5} | {T:<10.4f} | {sar_g:<9.4f} | {ratio:<10.4f} | {base_shear_coeff:<10.5f}", pct)

            detailed_table.append({
                "mode": i + 1,
                "T": T,
                "Damping": zeta,
                "SaR_g": sar_g,                          
                "SaR_ms2": accel_ms2,                        
                "Sd": sd,                                         
                "Ratio": ratio,
                "V_coeff": base_shear_coeff
            })

            mode_mx = 0.0
            mode_my = 0.0
            mode_mz = 0.0

            if omega > 0 and mode_shapes:
                scale_factor = gamma * sd
                accel_scale_factor = gamma * accel_ms2                           
                
                mode_key = f"Mode {i+1}"
                if mode_key in mode_shapes:
                    shape_data = mode_shapes[mode_key]
                    for nid, dofs in shape_data.items():
                        if nid in per_mode_u:
                            per_mode_u[nid].append(np.array(dofs) * scale_factor)

                        real_nid = int(nid) if str(nid).isdigit() else nid
                        node = self.model_data.get("nodes", {}).get(real_nid)
                        
                        if not node:
                            node = self.model_data.get("nodes", {}).get(str(nid), {})

                        if hasattr(node, 'x'): 
                            X, Y, Z = node.x, node.y, node.z
                        elif isinstance(node, dict):
                            X = node.get("x", 0.0)
                            Y = node.get("y", 0.0)
                            Z = node.get("z", 0.0)
                        else:
                            X, Y, Z = 0.0, 0.0, 0.0

                        m_x, m_y, m_z = 0.0, 0.0, 0.0
                        m_rx, m_ry, m_rz = 0.0, 0.0, 0.0
                        if "assembled_mass" in modal_data and nid in modal_data["assembled_mass"]:
                            masses = modal_data["assembled_mass"][nid]
                            m_x, m_y, m_z = masses[0], masses[1], masses[2]
                            if len(masses) >= 6:
                                m_rx, m_ry, m_rz = masses[3], masses[4], masses[5]

                        F_x = m_x * (accel_scale_factor * dofs[0])
                        F_y = m_y * (accel_scale_factor * dofs[1])
                        F_z = m_z * (accel_scale_factor * dofs[2])
                        
                        M_xx = m_rx * (accel_scale_factor * dofs[3]) if len(dofs) >= 6 else 0.0
                        M_yy = m_ry * (accel_scale_factor * dofs[4]) if len(dofs) >= 6 else 0.0
                        M_zz = m_rz * (accel_scale_factor * dofs[5]) if len(dofs) >= 6 else 0.0

                        mode_mx += M_xx + (Y * F_z) - (Z * F_y)
                        mode_my += M_yy + (Z * F_x) - (X * F_z)
                        mode_mz += M_zz + (X * F_y) - (Y * F_x)
                else:
                    for nid in per_mode_u:
                        per_mode_u[nid].append(np.zeros(6))
            else:
                for nid in per_mode_u:
                    per_mode_u[nid].append(np.zeros(6))
                    
            per_mode_mx.append(mode_mx)
            per_mode_my.append(mode_my)
            per_mode_mz.append(mode_mz)

        n_modes = len(per_mode_shear)

        progress_callback(f"Performing {modal_comb} Combination...", 85)

        if modal_comb == "CQC" and n_modes > 0:
            shear_total = 0.0
            mx_total = 0.0
            my_total = 0.0
            mz_total = 0.0
            for i in range(n_modes):
                for j in range(n_modes):
                    rho = self._cqc_rho(per_mode_omega[i], per_mode_omega[j], zeta)
                    shear_total += per_mode_shear[i] * rho * per_mode_shear[j]
                    mx_total += per_mode_mx[i] * rho * per_mode_mx[j]        
                    my_total += per_mode_my[i] * rho * per_mode_my[j]        
                    mz_total += per_mode_mz[i] * rho * per_mode_mz[j]
            final_base_shear = np.sqrt(abs(shear_total))
            final_Mx = np.sqrt(abs(mx_total))        
            final_My = np.sqrt(abs(my_total))        
            final_Mz = np.sqrt(abs(mz_total))        

            final_displacements = {}
            for nid, vecs in per_mode_u.items():
                if len(vecs) != n_modes: continue
                dof_total = np.zeros(6)
                for i in range(n_modes):
                    for j in range(n_modes):
                        rho = self._cqc_rho(per_mode_omega[i], per_mode_omega[j], zeta)
                        dof_total += vecs[i] * vecs[j] * rho
                final_displacements[nid] = np.sqrt(np.abs(dof_total)).tolist()

        else:
            final_base_shear = np.sqrt(sum(v**2 for v in per_mode_shear))
            final_Mx = np.sqrt(sum(v**2 for v in per_mode_mx))        
            final_My = np.sqrt(sum(v**2 for v in per_mode_my))        
            final_Mz = np.sqrt(sum(v**2 for v in per_mode_mz))        
            final_displacements = {}
            for nid, vecs in per_mode_u.items():
                sq_sum = np.zeros(6)
                for v in vecs:
                    sq_sum += v**2
                final_displacements[nid] = np.sqrt(sq_sum).tolist()

        final_cross_force = np.sqrt(sum(v**2 for v in per_mode_cross_force)) if per_mode_cross_force else 0.0

        print(f"[CROSS] direction={direction} | final_cross_force={final_cross_force:.4f} kN")

        total_mass = 0.0
                                                                                   
        if direction == "X": active_mass = m_total_x
        elif direction == "Y": active_mass = m_total_y
        else: active_mass = m_total_z
        
        total_weight = active_mass * g_exact
        
        base_shear_force = final_base_shear * active_mass * eq_scale

        static_mass = 0.0
        if "assembled_mass" in modal_data:
                                               
            idx = 0 if direction == "X" else (1 if direction == "Y" else 2)
            static_mass = sum(m_vals[idx] for m_vals in modal_data["assembled_mass"].values())
            
        static_weight = static_mass * g_exact
        
        true_code_coeff = base_shear_force / static_weight if static_weight > 0 else final_base_shear

        max_sum_ux = mass_ratios[-1].get("SumUx", 0.0) * 100 if mass_ratios else 0.0
        max_sum_uy = mass_ratios[-1].get("SumUy", 0.0) * 100 if mass_ratios else 0.0
        max_sum_uz = mass_ratios[-1].get("SumUz", 0.0) * 100 if mass_ratios else 0.0

        rsa_summary_payload = [
            {
                "label": "Total Static Weight (W)", 
                "value": static_weight, 
                "unit_type": "force",
                "desc": "Physical weight of the structure, including fixed supports."
            },
            {
                "label": "Active Dynamic Weight", 
                "value": total_weight, 
                "unit_type": "force",
                "desc": "Unrestrained weight participating in the mass matrix."
            },
            {
                "label": f"Base Shear Force ({direction})", 
                "value": base_shear_force, 
                "unit_type": "force",
                "desc": f"Combined dynamic base shear ({modal_comb})."
            },
            {
                "label": f"Code Base Shear Ratio ({direction})", 
                "value": true_code_coeff, 
                "unit_type": "ratio",
                "desc": "Effective seismic coefficient for scaling."
            },
            {
                "label": f"Active Dynamic Shear Ratio ({direction})", 
                "value": final_base_shear, 
                "unit_type": "ratio",
                "desc": "Old ratio based strictly on unrestrained active mass."
            },
            {
                "label": f"Cumulative Mass ({direction})", 
                "value": max_sum_ux if direction == "X" else (max_sum_uy if direction == "Y" else max_sum_uz), 
                "unit_type": "percent",
                "desc": f"Total participating mass ratio in {direction}-direction."
            }
        ]

        uncombined_u_serializable = {}
        for nid, vecs in per_mode_u.items():
            uncombined_u_serializable[nid] = [v.tolist() for v in vecs]

        return {
            "status": "SUCCESS",
            "base_shear_coeff": true_code_coeff,                                                       
            "base_reaction": {
                "Fx": base_shear_force if direction == "X" else final_cross_force,
                "Fy": final_cross_force if direction == "X" else (base_shear_force if direction == "Y" else 0.0),
                "Fz": base_shear_force if direction == "Z" else 0.0,
                "Mx": final_Mx,            
                "My": final_My,            
                "Mz": final_Mz             
            },
            "displacements": final_displacements,
            "rsa_info": {                          
                "method": modal_comb,              
                "zeta": zeta,                      
                "omega_array": per_mode_omega,     
                "uncombined_u": uncombined_u_serializable
            },
            "detailed_table": detailed_table,
            "spectrum_direction": spectrum_direction,
            "analysis_direction": direction,
            "rsa_summary": rsa_summary_payload                                            
        }
