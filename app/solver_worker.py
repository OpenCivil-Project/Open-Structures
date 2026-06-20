import sys
import os
import traceback
import json
import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal

current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(current_dir)
if root_dir not in sys.path: sys.path.append(root_dir)
from core.solver.linear_static.main_engine import run_linear_static_analysis
from core.solver.modal.modal_engine import run_modal_analysis
from core.solver.RSA.rsa_engine import RSAEngine
from core.solver.LTHA.ltha_engine import run_ltha_analysis
from core.solver.buckling.buckling_engine import run_buckling_analysis
from core.model import StructuralModel

class SolverWorker(QThread):
    signal_finished = pyqtSignal(bool, str)
    signal_progress = pyqtSignal(str, int)                    

    def __init__(self, input_path, output_path, case_type="Linear Static", case_name="DEAD"):
        super().__init__()
        self.input_path = input_path
        self.output_path = output_path
        self.case_type = case_type
        self.case_name = case_name 

    def run(self):
        try:
            print(f"Worker: Starting {self.case_type} Engine on {self.input_path} (Case: {self.case_name})...")
            success = False
            
            if self.case_type == "Modal":
                from progress import make_callback
                cb = make_callback(self.signal_progress.emit)
                success = run_modal_analysis(self.input_path, self.output_path, progress_callback=cb)

            elif self.case_type in ["Response Spectrum", "LTHA"]:
                
                temp_model = StructuralModel("Temp")
                try:
                    temp_model.load_from_file(self.input_path)
                except Exception as e:
                    raise Exception(f"Failed to load model data: {e}")

                modal_case_name = "MODAL"           
                case_obj = temp_model.load_cases.get(self.case_name)
                if case_obj and hasattr(case_obj, 'modal_case') and case_obj.modal_case:
                    modal_case_name = case_obj.modal_case
                
                exact_swap = self.output_path.replace(f"_{self.case_name}_results.json", f"_{modal_case_name}_results.json")
                base = self.output_path.replace("_results.json", "")
                
                candidates = [
                    exact_swap,
                    base + f"_{modal_case_name}_results.json",
                    base.rsplit("_", 1)[0] + f"_{modal_case_name}_results.json" if "_" in base else ""
                ]
                
                modal_output_path = ""
                for c in candidates:
                    if c and os.path.exists(c):
                        modal_output_path = c
                        print(f"Worker: Found Modal Results at {modal_output_path}")
                        break
                        
                if not modal_output_path:
                    raise Exception(f"Could not locate modal results for case '{modal_case_name}'. Run the Modal case first.")

                if self.case_type == "Response Spectrum":
                    
                    engine = RSAEngine(modal_output_path, temp_model.__dict__)
                    
                    from progress import make_callback
                    cb = make_callback(self.signal_progress.emit)
                    
                    shear_results = [] 
                    disp_results = []
                    rsa_detailed_tables = {} 
                    summary_items = []

                    fx_results = []
                    fy_results = []
                    fz_results = []

                    mx_results = []
                    my_results = []
                    mz_results = []

                    if hasattr(case_obj, 'rsa_loads') and case_obj.rsa_loads:
                        cb(f"Worker: Found {len(case_obj.rsa_loads)} load components.", 5)
                        modal_comb = getattr(case_obj, 'modal_comb', 'SRSS')
                        
                        all_rsa_directions = []
                        
                        for u_dir, func, scale in case_obj.rsa_loads:
                            direction = "X"
                            if u_dir == "U2": direction = "Y"
                            elif u_dir == "U3": direction = "Z"
                            
                            damp_val = getattr(case_obj, 'modal_damping', 0.05)
                            
                            res_dict = engine.run(
                                function_name=func, 
                                direction=direction, 
                                modal_comb=modal_comb, 
                                damping_ratio=damp_val,
                                progress_callback=cb
                            )

                            if res_dict:
                                                                                          
                                dir_info = res_dict.get("rsa_info", {})
                                dir_info["direction"] = direction
                                dir_info["scale"] = scale
                                all_rsa_directions.append(dir_info)

                                shear_results.append(res_dict["base_shear_coeff"])
                                disp_results.append(res_dict["displacements"])
                                
                                if "detailed_table" in res_dict:
                                    rsa_detailed_tables[direction] = res_dict["detailed_table"]

                                if "base_reaction" in res_dict:
                                    fx_results.append(res_dict["base_reaction"]["Fx"])
                                    fy_results.append(res_dict["base_reaction"]["Fy"])
                                    fz_results.append(res_dict["base_reaction"]["Fz"])

                                    mx_results.append(res_dict["base_reaction"]["Mx"])
                                    my_results.append(res_dict["base_reaction"]["My"])
                                    mz_results.append(res_dict["base_reaction"]["Mz"])

                                else:
                                    fx_results.append(0.0); fy_results.append(0.0); fz_results.append(0.0)
                                    mx_results.append(0.0); my_results.append(0.0); mz_results.append(0.0) 
                                
                                if "rsa_summary" in res_dict:
                                    summary_items.extend(res_dict["rsa_summary"])

                        method = getattr(case_obj, 'dir_comb', 'SRSS')
                        final_base_shear = 0.0
                        final_displacements = {}
                        final_Fx, final_Fy, final_Fz = 0.0, 0.0, 0.0
                        final_Mx, final_My, final_Mz = 0.0, 0.0, 0.0
                        
                        if shear_results:
                            if method == "SRSS":
                                final_base_shear = np.sqrt(sum(v**2 for v in shear_results))
                                final_Fx = np.sqrt(sum(v**2 for v in fx_results))
                                final_Fy = np.sqrt(sum(v**2 for v in fy_results))
                                final_Fz = np.sqrt(sum(v**2 for v in fz_results))
                                final_Mx = np.sqrt(sum(v**2 for v in mx_results))
                                final_My = np.sqrt(sum(v**2 for v in my_results))
                                final_Mz = np.sqrt(sum(v**2 for v in mz_results))
                            else:           
                                final_base_shear = sum(abs(v) for v in shear_results)
                                final_Fx = sum(abs(v) for v in fx_results)
                                final_Fy = sum(abs(v) for v in fy_results)
                                final_Fz = sum(abs(v) for v in fz_results)
                                final_Mx = sum(abs(v) for v in mx_results)
                                final_My = sum(abs(v) for v in my_results)
                                final_Mz = sum(abs(v) for v in mz_results)
                            
                            if disp_results:
                                ref_disps = disp_results[0]
                                for nid in ref_disps.keys():
                                    combined_dofs = np.zeros(6)
                                    for run_idx, d_dict in enumerate(disp_results):
                                        if nid in d_dict:
                                            vals = np.array(d_dict[nid])
                                            if method == "SRSS":
                                                combined_dofs += (vals * case_obj.rsa_loads[run_idx][2])**2
                                            else:
                                                combined_dofs += np.abs(vals * case_obj.rsa_loads[run_idx][2])
                                                
                                    if method == "SRSS":
                                        combined_dofs = np.sqrt(combined_dofs)
                                        
                                    final_displacements[nid] = combined_dofs.tolist()

                            try:
                                with open(self.output_path, 'r') as f:
                                    full_data = json.load(f)
                            except:
                                full_data = {}

                            full_data["status"] = "SUCCESS"
                            
                            full_data["rsa_info"] = {
                                "type": "Response Spectrum Combined",
                                "dir_comb": method,
                                "directions": all_rsa_directions
                            }
                            
                            full_data["base_shear_coeff"] = final_base_shear
                            full_data["displacements"] = final_displacements
                            full_data["base_reaction"] = {
                                "Fx": final_Fx, "Fy": final_Fy, "Fz": final_Fz,
                                "Mx": final_Mx, "My": final_My, "Mz": final_Mz                                                  
                            }
                            full_data["rsa_detailed"] = rsa_detailed_tables
                            full_data["rsa_summary"] = summary_items
                            
                            with open(self.output_path, 'w') as f:
                                json.dump(full_data, f, indent=4)
                                
                            import shutil
                            import glob
                            
                            base_path = self.output_path.replace("_results.json", "") 
                            
                            if "_" in os.path.basename(base_path):
                                prefix_dir = os.path.dirname(base_path)
                                base_name = os.path.basename(base_path).rsplit("_", 1)[0]
                                search_pattern = os.path.join(prefix_dir, f"{base_name}_*_matrices.json")
                            else:
                                search_pattern = f"{base_path}_*_matrices.json"
                            
                            found_matrices = glob.glob(search_pattern)
                            rsa_matrices_path = self.output_path.replace("_results.json", "_matrices.json")
                            
                            if found_matrices:
                                                                                                       
                                shutil.copy2(found_matrices[0], rsa_matrices_path)
                                print(f"Worker: Successfully linked element matrices from {os.path.basename(found_matrices[0])}")
                            else:
                                print(f"Worker Warning: Could not find any static matrices matching '{search_pattern}'. Spy Dialogs may be empty.")
                                
                            success = True
                        else:
                            success = False
                    else:
                        print("Error: No RSA loads defined.")
                        success = False

                elif self.case_type == "LTHA":
                    success = run_ltha_analysis(
                        modal_results_path=modal_output_path,
                        model_data=temp_model.__dict__,
                        output_path=self.output_path,
                        case_name=self.case_name
                    )

            elif self.case_type == "Buckling":
                from progress import make_callback
                cb = make_callback(self.signal_progress.emit)

                base = self.output_path.replace("_results.json", "")

                static_case_name = "DEAD"
                try:
                    temp_model = StructuralModel("Temp")
                    temp_model.load_from_file(self.input_path)
                    case_obj = temp_model.load_cases.get(self.case_name)
                    if case_obj and hasattr(case_obj, 'nonlinear_case') and case_obj.nonlinear_case:
                        static_case_name = case_obj.nonlinear_case
                except Exception:
                    pass

                static_results_path  = base.rsplit("_", 1)[0] + f"_{static_case_name}_results.json"
                static_matrices_path = base.rsplit("_", 1)[0] + f"_{static_case_name}_matrices.json"

                success = run_buckling_analysis(
                    self.input_path,
                    self.output_path,
                    static_results_path,
                    static_matrices_path,
                    case_name=self.case_name,
                    progress_callback=cb
                )

            else:
                from progress import make_callback
                cb = make_callback(self.signal_progress.emit)
                success = run_linear_static_analysis(self.input_path, self.output_path, self.case_name, progress_callback=cb)
            
            if success:
                self.signal_finished.emit(True, "Analysis Completed Successfully.")
            else:
                self.signal_finished.emit(False, "Solver Engine returned failure status.")
                
        except Exception as e:
            err_msg = "".join(traceback.format_exception(None, e, e.__traceback__))
            print(f"Worker Error:\n{err_msg}")
            self.signal_finished.emit(False, f"Solver Crashed:\n{str(e)}")
