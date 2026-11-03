import json
from error_definitions import SolverException
from core.compact_json import write_json

class ResultWriter:
    def __init__(self, output_path):
        self.output_path = output_path

    def write_results(self, results_dict, info=None, assembled_mass=None, saved_states=None,
                       hinge_states=None):
        """
        Saves the analysis results to JSON.

        saved_states: optional list of per-step snapshot dicts, each shaped
        like {"step": int, "step_frac": float, "displacements": {...},
        "reactions": {...}}, in ascending step order. Only Nonlinear Static
        cases with "Multiple States" selected pass this; every other caller
        is unaffected and the "saved_states" key is simply omitted.

        hinge_states: optional dict {element_id_str: {"d": [eps0, kappa2,
        kappa3], "Lh": hinge_length}}, the FINAL converged step's fiber-hinge
        section deformations -- see hinge_results_dialog.py's module
        docstring for the full contract. Written as a top-level key,
        omitted entirely when None (e.g. a model with no hinges, or a
        formulation the hinge P-Delta path doesn't cover). This is a
        fallback for "Final State Only" runs; a "Multiple States" run
        instead carries the equivalent per-step data inside each entry of
        saved_states[i]["hinge_states"] (added directly by the caller,
        not here).
        """
        print(f"Writer: Saving results to {self.output_path}...")
        
        output_data = {
            "status": "SUCCESS",
            "info": info if info else {},
            "restrained_nodes": results_dict.get("restrained_nodes", []),
            "displacements": results_dict["displacements"],
            "reactions": results_dict["reactions"],
            "base_reaction": results_dict.get("base_reaction", {})
        }

        if assembled_mass is not None:
            output_data["assembled_mass"] = assembled_mass

        if results_dict.get("shell_forces"):
            output_data["shell_forces"] = results_dict["shell_forces"]

        if "opensees_forces" in results_dict:
            output_data["opensees_forces"] = results_dict["opensees_forces"]

        if saved_states is not None:
            output_data["saved_states"] = saved_states

        if hinge_states is not None:
            output_data["hinge_states"] = hinge_states

        try:
                                                                                               
            n_items = len(output_data["displacements"]) * (1 + len(saved_states or []))
            with open(self.output_path, 'w') as f:
                write_json(output_data, f, n_items=n_items)
            print("Writer: Save Complete.")
            return True
        except Exception as e:
                                          
            raise SolverException("E401", f"Error details: {str(e)}")
