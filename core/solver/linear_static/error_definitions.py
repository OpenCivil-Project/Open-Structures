                                                                  
class SolverException(Exception):
    """
    Custom Exception class for MetuFire Solver.
    Carries an error_code to lookup details later.
    """
    def __init__(self, error_code, extra_info=""):
        self.error_code = error_code
        self.extra_info = extra_info
        super().__init__(self.get_message())

    def get_message(self):
        err = SOLVER_ERRORS.get(self.error_code, SOLVER_ERRORS["E000"])
        return f"[{self.error_code}] {err['title']}: {self.extra_info}"

    def get_details(self):
        """Returns the full dictionary for UI/Dialog usage."""
                               
        data = SOLVER_ERRORS.get(self.error_code, SOLVER_ERRORS["E000"]).copy()
                                                         
        if self.extra_info:
            data['desc'] += f"\n\nContext: {self.extra_info}"
        return data

SOLVER_ERRORS = {
                                    
    "E000": {
        "title": "Unknown System Error",
        "desc": "An unexpected error occurred that does not match any known error codes.",
        "fix": "Check the Python console logs for a raw stack trace. Contact the developer."
    },
    
    "E101": {
        "title": "Input File Not Found",
        "desc": "The solver could not locate the input .json file at the specified path.",
        "fix": "Ensure the file path is correct and the file exists. Avoid special characters in the filename."
    },
    "E102": {
        "title": "Invalid JSON Format",
        "desc": "The input file is corrupted or is not a valid JSON structure.",
        "fix": "Open the file in a text editor to check for missing braces or syntax errors."
    },
    "E103": {
        "title": "Missing Material or Section",
        "desc": "An element is referencing a Material or Section name that was not defined in the properties list.",
        "fix": "Check your 'elements' list. Ensure every 'sec_name' matches a name in the 'sections' list exactly."
    },
    "E104": {
        "title": "Load Case Not Found",
        "desc": "The requested Load Case name does not exist in the 'load_cases' definition.",
        "fix": "Check the spelling of the Load Case name or ensure at least one load case is defined in the input."
    },

    "E201": {
        "title": "Zero Length Element",
        "desc": "An element has a length of effectively zero (Start Node and End Node are coincident).",
        "fix": "Check node coordinates. Delete or merge coincident nodes."
    },
    "E202": {
        "title": "Invalid Section Properties",
        "desc": "A section has Area (A) or Inertia (I) equal to or less than zero.",
        "fix": "Review the Section Database. Area and Inertia must be positive values."
    },
    "E203": {
        "title": "Unstable Release Configuration",
        "desc": "An element has releases that make it internally unstable (e.g., released Moment at both ends without support, or torsional instability).",
        "fix": "Check member releases. You cannot release the same rotational DOF at both ends unless the element is a truss/link."
    },
    "E205": {
        "title": "Diaphragm DOF Conflict",
        "desc": "A restraint (support) was applied directly to a node's UX/UY/RZ that is a SLAVE in a rigid diaphragm, or a node belongs to more than one diaphragm group. Slave in-plane DOFs are eliminated and no longer exist independently.",
        "fix": "Apply the restraint to the diaphragm's MASTER node instead, or remove the node from the diaphragm constraint. Ensure each node belongs to at most one diaphragm."
    },

    "E301": {
        "title": "Structure is Unstable (Singular Matrix)",
        "desc": "The Stiffness Matrix is singular and cannot be inverted. This usually means the structure is a 'Mechanism' (it moves freely).",
        "fix": "1. Check Support Conditions (is the structure floating?).\n2. Check for disconnected nodes.\n3. Check for too many internal releases (e.g. 3 hinges in a span)."
    },
    "E302": {
        "title": "Huge Displacements Detected",
        "desc": "The solver calculated displacements exceeding reasonable limits (e.g., > 1e6 meters).",
        "fix": "Check your units (E modulus vs Load units). Ensure your model is restrained against rotation."
    },

    "E401": {
        "title": "Result Write Failure",
        "desc": "Could not save the 'results.json' file.",
        "fix": "Ensure the output file is not open in another program (like Excel or Notepad). Check folder write permissions."
    }
}
