"""
Plot Function Data Layer — OpenCivil Time History Plot System.

Generalized so any analysis type (LTHA now, later nonlinear/pushover/IDA)
can plug results in by implementing the PlotFunctionSource interface. The
dialog/canvas layer never touches raw npz/json — it only ever asks a
PlotFunctionSource for (time, values, label).

Data assumptions (LTHA v1, per ltha_engine.py):
    <case>_LTHA_history.npz holds full per-step time series:
        node_<id>              -> relative displacement   (n_steps, 6)
        vel_node_<id>          -> relative velocity        (n_steps, 6)
        acc_node_<id>          -> relative acceleration    (n_steps, 6)
        reac_node_<id>         -> reaction history, restrained nodes only
        base_reaction_history  -> total base reaction      (n_steps, 6)

    <case>_results.json holds:
        info: {dt, n_steps, directions, case, type}
        accel_history: {direction: [n_steps]}   ground motion, m/s^2

Deliberately NOT implemented — no data exists yet, not stubbed:
    Frame/element internal forces  (needs internal force recovery)
    Input Energy                   (needs solver-side energy bookkeeping)
"""

import json
import numpy as np

DOF_INDEX = {"UX": 0, "UY": 1, "UZ": 2, "RX": 3, "RY": 4, "RZ": 5}
DOF_LABELS = list(DOF_INDEX.keys())
DIR_TO_DOF = {"X": "UX", "Y": "UY", "Z": "UZ"}
DOF_TO_DIR = {v: k for k, v in DIR_TO_DOF.items()}

class LTHACaseData:
    """
    Loads and caches one LTHA case's result files. One instance is shared by
    every PlotFunctionSource plotted against that case, so the npz is only
    read from disk once per dialog session.
    """

    def __init__(self, results_json_path):
        with open(results_json_path, 'r') as f:
            self.results = json.load(f)

        if self.results.get("status") != "SUCCESS":
            raise ValueError(f"Cannot plot — case did not complete successfully: {results_json_path}")

        info = self.results["info"]
        self.case_name = info["case"]
        self.dt = info["dt"]
        self.n_steps = info["n_steps"]
        self.directions = info["directions"]
        self.time = np.arange(self.n_steps) * self.dt

        history_path = self.results["history_path"]
        self._npz = np.load(history_path)

        self.ground_accel = {
            d: np.array(v, dtype=float)
            for d, v in self.results.get("accel_history", {}).items()
        }
        self._ground_vel_cache = {}

    def npz_array(self, key):
        if key not in self._npz:
            return None
        return self._npz[key]

    def ground_velocity(self, direction):
        """Ground velocity, integrated once from ground accel and cached."""
        if direction in self._ground_vel_cache:
            return self._ground_vel_cache[direction]
        accel = self.ground_accel.get(direction)
        if accel is None:
            return None
        v = np.zeros(self.n_steps)
        n = min(self.n_steps, len(accel))
        for j in range(n - 1):
            v[j + 1] = v[j] + 0.5 * (accel[j] + accel[j + 1]) * self.dt
        self._ground_vel_cache[direction] = v
        return v

class PlotFunctionSource:
    """
    Interface every plot function type implements. A source is a small,
    picklable-ish config object (joint id, component, options) that resolves
    to one trace once handed an LTHACaseData. Nothing here holds numpy arrays
    directly — everything is re-read/re-derived from the case on demand, so
    switching the Load Case dropdown just means calling get_series() again.
    """
    type_name = "Base"

    def get_series(self, case: LTHACaseData):
        """Return (time: np.ndarray, values: np.ndarray, label: str)."""
        raise NotImplementedError

    def display_name(self):
        raise NotImplementedError

class JointResponseSource(PlotFunctionSource):
    """Joint Displacement / Velocity / Acceleration — relative or absolute."""
    type_name = "Joint Response"
    _NPZ_PREFIX = {"Displ": "node_", "Vel": "vel_node_", "Accel": "acc_node_"}

    def __init__(self, joint_id, vector_type="Displ", component="UX", absolute=False, name=None):
        if vector_type not in self._NPZ_PREFIX:
            raise ValueError(f"vector_type must be one of {list(self._NPZ_PREFIX)}")
        if component not in DOF_LABELS:
            raise ValueError(f"component must be one of {DOF_LABELS}")
        if absolute and vector_type == "Displ":
            raise ValueError(
                "Absolute displacement isn't physically meaningful for modal-superposition "
                "LTHA — use Absolute Velocity or Absolute Acceleration instead."
            )
        self.joint_id = str(joint_id)
        self.vector_type = vector_type
        self.component = component
        self.absolute = absolute
        self.name = name or self._auto_name()

    def _auto_name(self):
        prefix = "Abs " if self.absolute else ""
        return f"{prefix}{self.vector_type} {self.component} - Joint {self.joint_id}"

    def display_name(self):
        return self.name

    def get_series(self, case: LTHACaseData):
        key = self._NPZ_PREFIX[self.vector_type] + self.joint_id
        arr = case.npz_array(key)
        if arr is None:
            raise ValueError(f"No {self.vector_type} history for Joint {self.joint_id} in this case.")

        values = arr[:, DOF_INDEX[self.component]].copy()

        if self.absolute:
            direction = DOF_TO_DIR.get(self.component)
            if direction is None or direction not in case.ground_accel:
                raise ValueError(
                    f"No ground motion drives component {self.component}; "
                    f"absolute response is undefined for it in this case."
                )
            ground = (case.ground_accel[direction] if self.vector_type == "Accel"
                      else case.ground_velocity(direction))
            n = min(len(ground), len(values))
            values = values[:n] + ground[:n]

        n = len(values)
        return case.time[:n], values, self.display_name()

class ReactionSource(PlotFunctionSource):
    """Joint reaction time history — restrained joints only."""
    type_name = "Joint Reaction"
    _FORCE_TO_DOF = {"FX": "UX", "FY": "UY", "FZ": "UZ", "MX": "RX", "MY": "RY", "MZ": "RZ"}

    def __init__(self, joint_id, component="FX", name=None):
        if component not in self._FORCE_TO_DOF:
            raise ValueError(f"component must be one of {list(self._FORCE_TO_DOF)}")
        self.joint_id = str(joint_id)
        self.component = component
        self.name = name or f"Reaction {component} - Joint {self.joint_id}"

    def display_name(self):
        return self.name

    def get_series(self, case: LTHACaseData):
        key = f"reac_node_{self.joint_id}"
        arr = case.npz_array(key)
        if arr is None:
            raise ValueError(f"Joint {self.joint_id} is not restrained — no reaction history exists.")
        values = arr[:, DOF_INDEX[self._FORCE_TO_DOF[self.component]]].copy()
        n = len(values)
        return case.time[:n], values, self.display_name()

class BaseReactionSource(PlotFunctionSource):
    """Total base reaction time history, summed over all restrained joints."""
    type_name = "Base Reaction"
    _COMPONENTS = {"FX": 0, "FY": 1, "FZ": 2, "MX": 3, "MY": 4, "MZ": 5}

    def __init__(self, component="FX", name=None):
        if component not in self._COMPONENTS:
            raise ValueError(f"component must be one of {list(self._COMPONENTS)}")
        self.component = component
        self.name = name or f"Base {component}"

    def display_name(self):
        return self.name

    def get_series(self, case: LTHACaseData):
        arr = case.npz_array("base_reaction_history")
        if arr is None:
            raise ValueError("No base reaction history in this case.")
        values = arr[:, self._COMPONENTS[self.component]].copy()
        n = len(values)
        return case.time[:n], values, self.display_name()

class GroundMotionSource(PlotFunctionSource):
    """The input ground acceleration record itself, per direction."""
    type_name = "Ground Motion"

    def __init__(self, direction="X", name=None):
        if direction not in ("X", "Y", "Z"):
            raise ValueError("direction must be X, Y, or Z")
        self.direction = direction
        self.name = name or f"Ground Accel {direction}"

    def display_name(self):
        return self.name

    def get_series(self, case: LTHACaseData):
        values = case.ground_accel.get(self.direction)
        if values is None:
            raise ValueError(f"No ground motion recorded for direction {self.direction} in this case.")
        n = len(values)
        return case.time[:n], values, self.display_name()

PLOT_FUNCTION_TYPES = {
    "Joint Response": JointResponseSource,
    "Joint Reaction": ReactionSource,
    "Base Reaction": BaseReactionSource,
    "Ground Motion": GroundMotionSource,
}
