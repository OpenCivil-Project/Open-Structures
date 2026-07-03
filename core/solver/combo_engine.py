import os
import json
import numpy as np

def compute_load_combinations(model, model_file_path):
    """
    Reads existing _results.json files, scales them according to combinations,
    and writes new _results.json files out for the UI to read natively.
    """
    base_path = os.path.splitext(model_file_path)[0]
    
    if not hasattr(model, 'load_combos') or not model.load_combos:
        return

    for combo_name, combo in model.load_combos.items():
        has_rsa = False
        base_disp = {}
        base_reac = {"Fx": 0.0, "Fy": 0.0, "Fz": 0.0, "Mx": 0.0, "My": 0.0, "Mz": 0.0}
        
        env_disp = {}
        env_reac = {"Fx": 0.0, "Fy": 0.0, "Fz": 0.0, "Mx": 0.0, "My": 0.0, "Mz": 0.0}
        
        missing_case = False

        for case_name, scale in combo.cases:
            case_file = f"{base_path}_{case_name}_results.json"
            if not os.path.exists(case_file):
                print(f"Warning: Results for {case_name} missing. Skipping combo.")
                missing_case = True
                break
                
            with open(case_file, 'r') as f:
                res = json.load(f)
                
            is_rsa = res.get("info", {}).get("type") == "Response Spectrum"
            if is_rsa:
                has_rsa = True
                
            # Process Displacements
            for nid, dofs in res.get("displacements", {}).items():
                dofs_arr = np.array(dofs)
                if is_rsa:
                    if nid not in env_disp: env_disp[nid] = np.zeros(6)
                    env_disp[nid] += np.abs(dofs_arr * scale)
                else:
                    if nid not in base_disp: base_disp[nid] = np.zeros(6)
                    base_disp[nid] += dofs_arr * scale
                    
            # Process Reactions
            reac = res.get("base_reaction", {})
            if reac:
                if is_rsa:
                    for k in env_reac: env_reac[k] += abs(reac.get(k, 0.0) * scale)
                else:
                    for k in base_reac: base_reac[k] += reac.get(k, 0.0) * scale
        
        if missing_case:
            continue
            
        def save_combo_file(suffix, disp, reac):
            out_file = f"{base_path}_{combo_name}{suffix}_results.json"
            disp_out = {str(k): v.tolist() for k, v in disp.items()}
            
            combo_res = {
                "status": "SUCCESS",
                "info": {
                    "type": "Linear Static", # Tag as static so existing UI reads it normally
                    "case_name": f"{combo_name}{suffix}"
                },
                "displacements": disp_out,
                "base_reaction": reac
            }
            with open(out_file, 'w') as f:
                json.dump(combo_res, f, indent=4)
                
        if has_rsa:
            # Envelope Max
            max_disp = {k: base_disp.get(k, np.zeros(6)) + env_disp.get(k, np.zeros(6)) for k in set(base_disp) | set(env_disp)}
            max_reac = {k: base_reac[k] + env_reac[k] for k in base_reac}
            save_combo_file(" (Max)", max_disp, max_reac)
            
            # Envelope Min
            min_disp = {k: base_disp.get(k, np.zeros(6)) - env_disp.get(k, np.zeros(6)) for k in set(base_disp) | set(env_disp)}
            min_reac = {k: base_reac[k] - env_reac[k] for k in base_reac}
            save_combo_file(" (Min)", min_disp, min_reac)
        else:
            save_combo_file("", base_disp, base_reac)