import json
import numpy as np
from core.compact_json import json_key

COMPACT_ABOVE_ELEMENTS = 2000

class MatrixSpy:
    def __init__(self, output_path):
        self.output_path = output_path
        self.data = {}

    def record_matrices(self, elem_id, k_local, t_matrix):
        """Captures Stiffness and Transformation matrices."""
        if elem_id not in self.data:
            self.data[elem_id] = {"k": None, "t": None, "fef": np.zeros(12)}
        
        self.data[elem_id]["k"] = k_local
        self.data[elem_id]["t"] = t_matrix

    def record_fef(self, elem_id, fef_local):
        """Accumulates Fixed End Forces (handles multiple loads on one member)."""
        if elem_id not in self.data:
                                                                          
            self.data[elem_id] = {"k": None, "t": None, "fef": np.zeros(12)}
        
        self.data[elem_id]["fef"] += fef_local

    def record_final_forces(self, elem_id, f_local_final):
        """
        Records the CONVERGED, fully-nonlinear local end-force vector for
        an element -- for P-Delta: (k_local + k_geo) @ (t @ u_global) +
        fef, using the same k_geo basis as record_matrices' own "k"; for
        Large Displacements: the corotational f_local at the final
        converged state. Purely additive: only Nonlinear Static calls
        this, at the very end of the analysis (see nonlinear_engine.py's
        "Element Force Diagram fix" block), by calling save_to_json()
        again to re-write the same *_matrices.json with this extra field.
        Linear Static callers, and any consumer reading an older export
        with no "f_final" key, are completely unaffected -- MemberAnalyzer
        (spy_dialogs.py) falls back to its existing k@(t@u)+fef recovery
        whenever "f_final" is absent or None.
        """
        if elem_id not in self.data:
            self.data[elem_id] = {"k": None, "t": None, "fef": np.zeros(12)}
        self.data[elem_id]["f_final"] = f_local_final

    def save_to_json(self):
        """Converts numpy arrays to lists and saves to disk."""
        if not self.output_path: return

        if len(self.data) > COMPACT_ABOVE_ELEMENTS:
            self._save_to_json_compact()
            return

        export_dict = {}
        for eid, mats in self.data.items():
            f_final = mats.get("f_final")
            export_dict[eid] = {
                "k": mats["k"].tolist() if mats["k"] is not None else None,
                "t": mats["t"].tolist() if mats["t"] is not None else None,
                "fef": mats["fef"].tolist(),
                "f_final": f_final.tolist() if f_final is not None else None
            }
        
        try:
            with open(self.output_path, 'w') as f:
                json.dump(export_dict, f, indent=4)
            print(f"MatrixSpy: Successfully exported element matrices to {self.output_path}")
        except Exception as e:
            print(f"MatrixSpy Error: Could not save file. {e}")

    def _save_to_json_compact(self):
        """
        Large models: same content and same structure as save_to_json(), but written one
        element at a time with compact separators. Avoids building a second, all-elements
        copy of every matrix as Python lists (that copy alone is ~10 KB per element) and
        avoids indent=4 (one number per line).
        """
        try:
            with open(self.output_path, 'w') as f:
                f.write("{")
                first = True
                for eid, mats in self.data.items():
                    f_final = mats.get("f_final")
                    entry = json.dumps({
                        "k": mats["k"].tolist() if mats["k"] is not None else None,
                        "t": mats["t"].tolist() if mats["t"] is not None else None,
                        "fef": mats["fef"].tolist(),
                        "f_final": f_final.tolist() if f_final is not None else None
                    }, separators=(",", ":"))
                    if not first:
                        f.write(",")
                    first = False
                    f.write(json.dumps(json_key(eid)))
                    f.write(":")
                    f.write(entry)
                f.write("}")
            print(f"MatrixSpy: Successfully exported element matrices to {self.output_path}")
        except Exception as e:
            print(f"MatrixSpy Error: Could not save file. {e}")
