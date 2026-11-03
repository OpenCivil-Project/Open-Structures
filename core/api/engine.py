import os
from core.model import StructuralModel
from core.solver.linear_static.main_engine import run_linear_static_analysis
from core.solver.modal.modal_engine import run_modal_analysis
import json
from core.solver.RSA.rsa_engine import RSAEngine
from core.model_history import HistoryStore, atomic_save_model

_active_model = None

def _save_project_model(model):
    """Record project saves; solver-only copies remain outside this history."""
    filepath = model.active_model_path
    history = HistoryStore(filepath)
    try:
        if os.path.isfile(filepath):
            history.record_file("Existing saved model")
    except Exception as error:
        print(f"History unavailable: {error}")
    atomic_save_model(model, filepath)
    try:
        history.record_file("Saved from script")
    except Exception as error:
        print(f"Model saved, but history could not be recorded: {error}")

def wipe():
    """Clears the current model from memory (Essential for scripting)."""
    global _active_model
    _active_model = None
    print(" -> Model wiped from memory.")

def project(name, base_dir):
    """Creates a new OpenCivil project and sets it as the active model."""
    global _active_model
    
    _active_model = StructuralModel(name=name)
    
    proj_dir = os.path.normpath(os.path.join(base_dir, name))
    os.makedirs(proj_dir, exist_ok=True)
    
    model_path = os.path.join(proj_dir, f"{name}.mf")
    
    _active_model.active_project_dir = proj_dir
    _active_model.active_model_path = model_path
    
    _save_project_model(_active_model)
    print(f" -> Project '{name}' ready at: {proj_dir}")

def open_model(filepath):
    """Loads an existing .mf file into the active model."""
    global _active_model
    
    filepath = os.path.normpath(filepath)
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Error: File not found: {filepath}")
        
    proj_name = os.path.splitext(os.path.basename(filepath))[0]
    _active_model = StructuralModel(name=proj_name)
    _active_model.load_from_file(filepath)
    
    proj_dir = os.path.dirname(os.path.abspath(filepath))
    _active_model.active_project_dir = proj_dir
    _active_model.active_model_path = filepath
    
    print(f" -> Loaded '{_active_model.name}' | Nodes: {len(_active_model.nodes)}, Elements: {len(_active_model.elements)}")

def save():
    """Saves the active model to its file path."""
    global _active_model
    if _active_model is None or not hasattr(_active_model, 'active_model_path'):
        raise RuntimeError("No active project to save. Run 'project()' first.")
    
    _save_project_model(_active_model)
    print(f" -> Saved to: {_active_model.active_model_path}")

def get_active_model():
    """Internal helper function used by other API files to get the current model."""
    global _active_model
    if _active_model is None:
        raise RuntimeError("No active model! Call 'project()' or 'open_model()' first.")
    return _active_model

def solve(case_name):
    """Universal solver orchestrator. Routes to the correct engine based on case type."""
    global _active_model
    if _active_model is None:
        raise RuntimeError("No active project to solve. Run 'project()' first.")
        
    model = _active_model
    
    if case_name not in model.load_cases:
        raise ValueError(f"Error: Load case '{case_name}' not found. Define it first.")
        
    case = model.load_cases[case_name]
    
    out_path = os.path.join(model.active_project_dir, f"{model.name}_{case_name}_results.json")
    model.active_results_path = out_path
    
    _save_project_model(model)
    
    print(f"\n -> Solving Case: '{case_name}' [{case.case_type}]...")
    
    if case.case_type == "Linear Static":
        run_linear_static_analysis(model.active_model_path, out_path)
        print(f"\u2705 SUCCESS! Static results saved to:\n   {out_path}")
        
    elif case.case_type == "Modal":
                                                                        
        model.active_modal_results_path = out_path 
        success = run_modal_analysis(model.active_model_path, out_path, target_case_name=case_name)
        
        if success:
            print(f"\u2705 MODAL SUCCESS! Results saved to:\n   {out_path}")
        else:
            print("\u274C MODAL FAILED. Check the output logs.")
            
    elif case.case_type == "Response Spectrum":
                                                        
        modal_path = getattr(model, 'active_modal_results_path', None)
        if not modal_path or not os.path.exists(modal_path):
            raise FileNotFoundError(
                f"\n❌ ERROR: Modal results not found for RSA case '{case_name}'. "
                "\nPlease run 'oc.solve(\"<YOUR_MODAL_CASE>\")' before running Response Spectrum Analysis."
            )
            
        print(" -> Initializing RSA Engine...")
        
        engine = RSAEngine(modal_results_path=modal_path, model_data=model.__dict__)
        
        direction_map = {"U1": "X", "U2": "Y", "U3": "Z"}
        direction_code = case.rsa_loads[0][0]              
        direction = direction_map.get(direction_code, "X")
        func_name = case.rsa_loads[0][1]                            
        
        results = engine.run(
            function_name=func_name, 
            direction=direction, 
            modal_comb=case.modal_comb, 
            damping_ratio=case.modal_damping
        )
        
        with open(out_path, 'w') as f:
            json.dump(results, f, indent=4)
            
        print(f"✅ RSA SUCCESS! Dynamic envelope saved to:\n   {out_path}")
        
    else:
        print(f" \u26A0\uFE0F Warning: Solver for case type '{case.case_type}' is not yet implemented.")
