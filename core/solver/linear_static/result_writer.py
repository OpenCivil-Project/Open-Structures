                                                              
import json
from error_definitions import SolverException

class ResultWriter:
    def __init__(self, output_path):
        self.output_path = output_path

    def write_results(self, results_dict, info=None, assembled_mass=None):
        """
        Saves the analysis results to JSON.
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

        try:
            with open(self.output_path, 'w') as f:
                json.dump(output_data, f, indent=4)
            print("Writer: Save Complete.")
            return True
        except Exception as e:
                                          
            raise SolverException("E401", f"Error details: {str(e)}")
