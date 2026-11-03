"""Record the live OpenSees fiber sections without touching native hinges.

Geometry is stored once in info.opensees_hinge_sections; accepted-state
responses use hinge_states, keyed by frame:solver-element:section-index.
Because fiber data is huge, hinge_states is thinned to ~150 snapshots. A second,
light record -- info.opensees_hinge_history -- keeps [eps, kz, ky] and [P, Mz, My]
of EVERY section at EVERY accepted step (no fibers), so moment-curvature loops and
their energy are exact. Layout: {key: {"steps": [n...], "d": [[eps,kz,ky]...],
"f": [[P,Mz,My]...]}} -- each section has its own step list.
The vectors retain OpenSees ordering: [P, Mz, My, T, Vy, Vz] and its
work-conjugate deformations. All values are SI. Actual fiber stresses AND
strains are recorded, including cyclic material history and centroids.
"""

import math

def _finite_vector(values, minimum=1):
    result = [float(v) for v in values]
    if len(result) < minimum or not all(math.isfinite(v) for v in result):
        raise ValueError("empty, incomplete or non-finite response")
    return result

def _short(values):
    """7 significant digits: enough for plots/tables, ~half the JSON size."""
    return [float(f"{v:.7g}") for v in values]

class OpenSeesHingeRecorder:
    """Read-only recorder; call capture only at a committed solver state.

    A failed response is omitted and reported, never filled with zeros or
    reconstructed from native materials. Springs are deliberately excluded:
    their slip/deformation units differ from beam-section strain/curvature.
    """

    def __init__(self, converter, ops):
        self.converter = converter
        self.ops = ops
        self.sections = {}
        self.warnings = []
        self.history = {}
        self._targets = []
        self._fiber_response = {}
        self._discover()

    def _warn(self, message):
        if message not in self.warnings:
            self.warnings.append(message)

    def _discover(self):
        conv = self.converter
        nonlinear = set(conv.nl_elements)
        for eid, chain in conv.split_info.items():
            element = conv.elements[eid]
            for segment, tag in enumerate(chain["ele_tags"]):
                if tag not in nonlinear:
                    continue
                try:
                    points = _finite_vector(self.ops.eleResponse(tag, "integrationPoints"))
                    weights = _finite_vector(self.ops.eleResponse(tag, "integrationWeights"))
                    if len(points) != len(weights):
                        raise ValueError("integration point/weight count mismatch")
                except Exception as exc:
                    self._warn(f"Frame {eid}, OpenSees element {tag}: section locations unavailable ({exc}).")
                    continue
                integration = "HingeRadau" if getattr(conv, "_nl_hinge", "lobatto") == "radau" else "Lobatto"
                for index, (point, weight) in enumerate(zip(points, weights), 1):
                    key = f"{eid}:{tag}:{index}"
                    meta = {
                        "element_id": int(eid), "element_tag": int(tag),
                        "section_index": index, "section_name": element["sec_name"],
                        "segment_index": segment + 1, "integration": integration,
                        "position_m": point, "integration_weight_m": weight,
                        "fibers": [],
                    }
                                                                         
                    if integration == "HingeRadau" and index in (1, len(points)) and weight > 0:
                        meta["hinge_length_m"] = weight
                    self.sections[key] = meta
                    self._targets.append((key, tag, index))

    def _fibers(self, key, tag, index):
        cached = self._fiber_response.get(key)
        known = self.sections[key]["fibers"]
        if cached and known:
                                                                                           
            response, width = cached
            flat = self.ops.eleResponse(tag, "section", index, response)
            if len(flat) != len(known) * width:
                raise ValueError("fiber count changed during this analysis")
            if flat[0] != known[0]["y"] or flat[1] != known[0]["z"]:
                raise ValueError("fiber geometry/order changed during this analysis")
            stresses = [float(v) for v in flat[width - 2::width]]
            strains = [float(v) for v in flat[width - 1::width]]
            if not (all(map(math.isfinite, stresses)) and all(map(math.isfinite, strains))):
                raise ValueError("non-finite fiber stress/strain")
            return known, stresses, strains
        choices = (cached,) if cached else (("fiberData2", 6), ("fiberData", 5))
        error = None
        for response, width in choices:
            try:
                flat = _finite_vector(self.ops.eleResponse(tag, "section", index, response), width)
                if len(flat) % width:
                    raise ValueError("invalid fiber row width")
                rows = [flat[j:j + width] for j in range(0, len(flat), width)]
                geometry, stresses, strains = [], [], []
                for row in rows:
                    if row[2] <= 0:
                        raise ValueError("nonpositive fiber area")
                    geometry.append({"y": row[0], "z": row[1], "area": row[2],
                                     "material_tag": int(row[3]) if width == 6 else None})
                    stresses.append(row[-2])
                    strains.append(row[-1])
                self._fiber_response[key] = (response, width)
                return geometry, stresses, strains
            except Exception as exc:
                error = exc
        raise ValueError(f"fiber stress/strain unavailable ({error})")

    def capture_light(self, step):
        """Per-step M-kappa history: section deformation [eps, kz, ky] and force [P, Mz, My] of every
        section, WITHOUT reading fibers (2 reads per section), so it is cheap enough for every accepted
        step. Call only at a committed solver state. A failed read skips that section for this step
        (reported once); each section keeps its own step list, so alignment is never guessed."""
        for key, tag, index in self._targets:
            try:
                d = _finite_vector(self.ops.eleResponse(tag, "section", index, "deformation"), 3)[:3]
                f = _finite_vector(self.ops.eleResponse(tag, "section", index, "force"), 3)[:3]
            except Exception as exc:
                self._warn(f"OpenSees section {key}: light history skipped at step {step} ({exc}).")
                continue
            h = self.history.setdefault(key, {"steps": [], "d": [], "f": []})
            h["steps"].append(int(step))
            h["d"].append(_short(d))
            h["f"].append(_short(f))

    def capture(self):
        states = {}
        for key, tag, index in self._targets:
            try:
                deformation = _finite_vector(self.ops.eleResponse(tag, "section", index, "deformation"), 3)
                force = _finite_vector(self.ops.eleResponse(tag, "section", index, "force"), 3)
                geometry, stresses, strains = self._fibers(key, tag, index)
                previous = self.sections[key]["fibers"]
                if previous and geometry is not previous and previous != geometry:
                    raise ValueError("fiber geometry/order changed during this analysis")
                self.sections[key]["fibers"] = geometry
                states[key] = {"section_deformation": _short(deformation), "section_force": _short(force),
                               "fiber_stress": _short(stresses), "fiber_strain": _short(strains)}
            except Exception as exc:
                self._warn(f"OpenSees section {key}: response omitted ({exc}).")
        return states
