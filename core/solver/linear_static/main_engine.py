import sys
import os
import time
import numpy as np
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)
                                        
from error_definitions import SolverException
from data_manager import DataManager
from assembler import GlobalAssembler
from solver_kernel import LinearSolver
from result_writer import ResultWriter

def run_linear_static_analysis(input_json_path, output_json_path, target_case_name="DEAD", progress_callback=None):
    """
    Main execution pipeline for the Absolute Linear Static Solver.
    Now accepts a specific case name to run.
    """
    print("="*60)
    print(f"METUFIRE SOLVER ENGINE | V0.35")
    print(f"Target: {os.path.basename(input_json_path)}")
    print("="*60)

    if progress_callback is None:
        from progress import noop_callback
        progress_callback = noop_callback

    start_time = time.time()

    try:
        print("[1/5] Initializing Data Manager...")
        progress_callback("Loading model data...", 5)
        dm = DataManager(input_json_path)
        
        print(f"      Target Case: {target_case_name}")
        
        dm.process_all(case_name=target_case_name)
        
        print(f"      Mapped {len(dm.nodes)} Nodes to {dm.total_dofs} DOFs.")
        print(f"      Processed {len(dm.elements)} Timoshenko Elements.")

        num_restrained = sum(1 for n in dm.nodes if any(n['restraints']))
                                                               
        active_patterns = dm.load_case['patterns']
        num_patterns    = len(active_patterns)
        sw_patterns     = [p['name'] for p in dm.raw.get('load_patterns', [])
                           if p.get('sw_mult', 0) != 0
                           and p['name'] in {ap[0] for ap in active_patterns}]
                           
        all_loads    = dm.raw.get('loads', [])
        num_nodal    = sum(1 for l in all_loads if l['type'] == 'nodal')
        num_member   = sum(1 for l in all_loads if l['type'] in ('member_dist', 'member_point'))
                             
        active_dia   = {k: v for k, v in dm.diaphragm_groups.items() if len(v) >= 2}

        progress_callback("", 8)
        progress_callback("B E G I N   A N A L Y S I S", 8)
        progress_callback("", 8)
        progress_callback(f"NUMBER OF JOINTS                     = {len(dm.nodes):>10}", 8)
        progress_callback(f"  WITH RESTRAINTS                    = {num_restrained:>10}", 8)
        progress_callback(f"NUMBER OF FRAME ELEMENTS             = {len(dm.elements):>10}", 8)
        progress_callback(f"NUMBER OF STIFFNESS DOFs             = {dm.total_dofs:>10}", 8)
        progress_callback(f"NUMBER OF LOAD PATTERNS (ACTIVE)     = {num_patterns:>10}", 8)
        progress_callback(f"NUMBER OF NODAL LOADS                = {num_nodal:>10}", 8)
        progress_callback(f"NUMBER OF MEMBER LOADS               = {num_member:>10}", 8)
        if sw_patterns:
            progress_callback(f"SELF-WEIGHT PATTERNS                 = {', '.join(sw_patterns)}", 8)
        if active_dia:
            for dname, dnodes in active_dia.items():
                progress_callback(f"DIAPHRAGM '{dname}'                   = {len(dnodes):>6}  nodes", 8)
        progress_callback(f"GRAVITATIONAL ACCELERATION           = {'9.80665':>10}", 8)
        progress_callback(f"UNITS (FORCE, LENGTH)                = {'kN, m':>10}", 8)
        progress_callback("", 8)

    except SolverException as se:
                                          
        error_details = se.get_details()
        
        print("\n" + "!"*60)
        print(f"ANALYSIS FAILED: [{se.error_code}] {error_details['title']}")
        print("-" * 60)
        print(f"Description: {error_details['desc']}")
        print(f"Suggestion:  {error_details['fix']}")
        print("!"*60 + "\n")

        with open(output_json_path, 'w') as f:
            import json
            json.dump({"status": "FAILED", "error": error_details}, f, indent=4)
            
        return False

    except Exception as e:
                                                
        print(f"FATAL SYSTEM ERROR: {e}")
        return False

    try:
        print("[2/5] Assembling Global System...")
        progress_callback("E L E M E N T   F O R M A T I O N", 15)
        progress_callback("", 15)
        progress_callback("Assembling stiffness matrix...", 20)
        matrix_path = output_json_path.replace("_results.json", "_matrices.json")
        
        assembler = GlobalAssembler(dm, export_path=matrix_path) 
        
        K, P = assembler.assemble_system()
        
        non_zeros  = K.nnz
        total_cells = dm.total_dofs ** 2
        sparsity   = 1.0 - (non_zeros / total_cells) if total_cells > 0 else 0
        print(f"      Matrix Assembled. Non-zeros: {non_zeros}")
        print(f"      Sparsity: {sparsity*100:.2f}% (Optimized)")

        num_dia_constraints = sum(len(v) - 1 for v in active_dia.values()) if active_dia else 0

        progress_callback(f"NUMBER OF COUPLED CONSTRAINT EQS     = {num_dia_constraints:>10}", 25)
        progress_callback("", 25)
        progress_callback(f"STIFFNESS MATRIX NON-ZEROS           = {non_zeros:>10}", 25)
        progress_callback(f"MATRIX SPARSITY                      = {sparsity*100:>9.2f}%", 25)
        progress_callback("", 25)
        
    except Exception as e:
        print(f"\nFATAL ERROR in Assembler: {e}")
        return False

    try:
        print("[3/5] Solving Linear System (Ku=P)...")
        progress_callback("L I N E A R   E Q U A T I O N   S O L U T I O N", 35)
        progress_callback("", 35)
        progress_callback("Forming stiffness at zero initial conditions...", 40)
        solver = LinearSolver(K, P, dm, T=assembler.T, kept_dofs=assembler.kept_dofs)
        U, R = solver.solve()
        
        max_u = max(abs(U)) if len(U) > 0 else 0
        print(f"      Solution Converged.")
        print(f"      Max Displacement: {max_u:.6f} m")

        num_constrained = dm.total_dofs - solver.num_free_dofs

        K_diag = K.tocsc().diagonal()
        num_neg_diag = int(np.sum(K_diag < 0))
        stability_note = "0,  OK." if num_neg_diag == 0 else f"{num_neg_diag},  WARNING"

        progress_callback(f"TOTAL EQUILIBRIUM EQUATIONS          = {solver.num_free_dofs:>10}", 55)
        progress_callback(f"CONSTRAINED DOFs                     = {num_constrained:>10}", 55)
        progress_callback(f"NON-ZERO STIFFNESS TERMS (REDUCED)   = {solver.K_ff_nnz:>10}", 55)
        progress_callback("", 55)
        progress_callback("FORMING STIFFNESS AT ZERO (UNSTRESSED) INITIAL CONDITIONS", 55)
        progress_callback("", 55)
        progress_callback("BASIC STABILITY CHECK:", 60)
        progress_callback(f"  NUMBER OF NEGATIVE STIFFNESS DIAGONALS  = {stability_note}", 60)
        progress_callback("", 60)
        progress_callback(f"MAX DISPLACEMENT                     = {max_u:>14.6f}  m", 65)
        progress_callback("", 65)
        
    except Exception as e:
        print(f"\nFATAL ERROR in Solver: {e}")
        return False

    try:
        print("[4/5] Formatting Results...")
        progress_callback("L I N E A R   S T A T I C   C A S E S", 70)
        progress_callback("", 70)
        progress_callback("Forming results and computing reactions...", 75)
        results = solver.get_results_dict()

        assembled_mass = None
        try:
            mass_sources = dm.raw.get("mass_sources", [])
            if mass_sources:
                modal_dir = os.path.join(current_dir, 'modal')
                if modal_dir not in sys.path:
                    sys.path.append(modal_dir)
                from mass_assembler import GlobalMassAssembler
                ms_name = mass_sources[0]["name"] if isinstance(mass_sources, list) else list(mass_sources.keys())[0]
                mass_asm = GlobalMassAssembler(dm)
                M = mass_asm.build_mass_matrix(ms_name)
                assembled_mass = {}
                for node in dm.nodes:
                    nid = str(node['id'])
                    idx = node['idx'] * 6
                    m_diag = M.diagonal()
                    assembled_mass[nid] = m_diag[idx:idx+6].tolist()
                print(f"      Assembled joint masses computed for source '{ms_name}'.")
        except Exception as e:
            print(f"      [INFO] Assembled mass skipped: {e}")
        
        elapsed = time.time() - start_time
        writer = ResultWriter(output_json_path)
        meta_info = {
            "version": "0.32 Absolute",
            "time_elapsed": f"{elapsed:.4f} sec",
            "dofs": dm.total_dofs,
            "case_name": target_case_name
        }
        writer.write_results(results, meta_info, assembled_mass=assembled_mass)

        br = results.get("base_reaction", {})
        progress_callback(f"CASE: {target_case_name}", 80)
        progress_callback("", 80)
        progress_callback(f"BASE REACTION  Fx = {br.get('Fx', 0.0):>14.4f}  kN", 85)
        progress_callback(f"BASE REACTION  Fy = {br.get('Fy', 0.0):>14.4f}  kN", 85)
        progress_callback(f"BASE REACTION  Fz = {br.get('Fz', 0.0):>14.4f}  kN", 85)
        progress_callback(f"BASE REACTION  Mx = {br.get('Mx', 0.0):>14.4f}  kN·m", 85)
        progress_callback(f"BASE REACTION  My = {br.get('My', 0.0):>14.4f}  kN·m", 85)
        progress_callback(f"BASE REACTION  Mz = {br.get('Mz', 0.0):>14.4f}  kN·m", 85)
        progress_callback("", 90)
        progress_callback("Writing results to disk...", 95)
        progress_callback("", 95)
        
    except Exception as e:
        print(f"\nFATAL ERROR in Writer: {e}")
        return False

    elapsed_total = time.time() - start_time
    progress_callback("A N A L Y S I S   C O M P L E T E", 98)
    progress_callback("", 98)
    progress_callback(f"TOTAL TIME FOR THIS ANALYSIS         = {elapsed_total:>8.3f}  sec", 100)
    progress_callback("", 100)

    print("="*60)
    print("ANALYSIS SEQUENCE COMPLETED SUCCESSFULLY")
    print(f"Total Time: {elapsed_total:.4f}s")
    print("="*60)
    return True

if __name__ == "__main__":
                     
    test_file = os.path.join(current_dir, "test.mf") 
    out_file = os.path.join(current_dir, "results.json")
    
    if os.path.exists(test_file):
        run_linear_static_analysis(test_file, out_file)
    else:
        print(f"Test file not found: {test_file}")
