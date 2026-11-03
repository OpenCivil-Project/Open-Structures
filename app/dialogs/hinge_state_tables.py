"""
hinge_state_tables.py

Custom tables for the Analysis Results dialog:

    Section State Summary
    Fiber Stress-Strain Response

Pure data module (no Qt). It reads a Nonlinear Static *_results.json dict --
the same "saved_states[i]['hinge_states'] = {eid: {'d': [eps0, k2, k3], 'Lh': ..}}"
contract hinge_results_dialog.py reads -- and rebuilds everything else from
the model with the dialog's own _HingeContext, so the numbers here are the
same numbers the Hinge Results plots show:

    P            = N of the fiber section state          (tension +, sign preserved)
    M2, M3       = _HingeContext.moment(d, "M2"/"M3")    
    U1, R2, R3   = section deformation x hinge length Lh
    fiber strain = eps0 - k2*c3 + k3*c2, stress/state from the backbone
                   -- OR, when the saved step carries "fiber_stress" (written by the solver whenever
                   cyclic hysteresis is active; stress then depends on the load history and cannot be
                   rebuilt from d), the solver's own fiber stress, and P/M2/M3 summed from it.

All values are computed in the solver's base units (kN, m) and scaled to the
display unit system at output time.
"""

import csv
import numpy as np

from app.dialogs.hinge_results_dialog import _build_contexts, _element_length, STATE_ORDER

TABLE_01_NAME = "Section State Summary"
TABLE_02_NAME = "Fiber Stress-Strain Response"

OVERALL_KEYS = ["frame", "case", "case_type", "step", "step_frac", "assign", "gen",
                "rel", "abs", "P", "M2", "M3", "U1", "R2", "R3", "state"]
FIBER_KEYS = ["frame", "case", "case_type", "step", "step_frac", "assign", "gen",
              "fiber", "stress", "strain", "state", "mat", "area", "c3", "c2",
              "rel", "abs"]

def overall_headers(u_force, u_len):
                                                               
    return ["Element", "Load Case", "Analysis Type", "Increment", "Load Factor", "Section Name",
            "Hinge ID", "Rel. Location", f"Abs. Location ({u_len})", f"Axial Force ({u_force})",
            f"Moment 2-2 ({u_force}-{u_len})", f"Moment 3-3 ({u_force}-{u_len})",
            f"Axial Def. ({u_len})", "Rotation 2-2 (rad)", "Rotation 3-3 (rad)", "Controlling State"]

def fiber_headers(u_force, u_len):
                                                                   
    return ["Element", "Load Case", "Analysis Type", "Increment", "Load Factor", "Section Name",
            "Hinge ID", "Fiber ID", f"Stress ({u_force}/{u_len}\u00b2)",
            "Strain", "Material State", "Material", f"Area ({u_len}\u00b2)",
            f"Z-Coord ({u_len})", f"Y-Coord ({u_len})", "Rel. Location",
            f"Abs. Location ({u_len})"]

def build_contexts(model):
    """(contexts, warnings); never raises (no hinges / solver modules missing -> [])."""
    try:
        return _build_contexts(model)
    except Exception as e:
        return [], [f"Hinge contexts unavailable ({e})."]

class HingeStateTables:
    def __init__(self, model, results, contexts):
        info = results.get("info", {}) or {}
        self.case_name = info.get("case_name", "")
        self.case_type = info.get("type", "")
        self.contexts = contexts
        self.steps = self._collect_steps(results)                                         
        self._lengths = {c.key: _element_length(model, c.element_id) for c in contexts}
        self._overall_base = None                                          

    @property
    def available(self):
        return bool(self.contexts) and bool(self.steps)

    @property
    def step_numbers(self):
        return [s[0] for s in self.steps]

    @staticmethod
    def _collect_steps(results):
        steps = []
        for k, st in enumerate(results.get("saved_states") or []):
            hs = st.get("hinge_states")
            if hs:
                steps.append((st.get("step", k), st.get("step_frac"), hs))
        if not steps and results.get("hinge_states"):                            
            steps.append((0, 1.0, results["hinge_states"]))
        steps.sort(key=lambda s: s[0])
        return steps

    def _iter(self, only_step=None):
        last = {}
        for step, frac, hs in self.steps:
            for ctx in self.contexts:
                rec = hs.get(ctx.key)
                if rec is not None and rec.get("d") is not None and len(rec["d"]) >= 3:
                    lh = rec.get("Lh")
                    fsig = rec.get("fiber_stress")
                    sig = np.array(fsig, float) if fsig is not None and len(fsig) == ctx.n else None
                    last[ctx.key] = (np.array(rec["d"][:3], float),
                                     float(lh) if lh is not None else None, sig)
                if ctx.key not in last:
                    continue
                if only_step is not None and step != only_step:
                    continue
                d, lh, sig = last[ctx.key]
                yield step, frac, ctx, d, (lh if lh else ctx.lh_model), sig

    def _abs_dist(self, ctx):
        L = self._lengths.get(ctx.key)
        return ctx.rel_dist * L if L else None

    def _overall_rows_base(self):
        if self._overall_base is None:
            rows = []
            for step, frac, ctx, d, lh, sig in self._iter():
                if sig is not None:                                                                
                    N = ctx.fs.resultants_from_stress(sig)[0]
                    M2 = ctx.moment_from_sigma(sig, "M2"); M3 = ctx.moment_from_sigma(sig, "M3")
                else:
                    N = ctx.fs.state(d[0], d[1], d[2])[0]
                    M2 = ctx.moment(d, "M2"); M3 = ctx.moment(d, "M3")
                rows.append({
                    "frame": ctx.element_id, "case": self.case_name,
                    "case_type": self.case_type, "step": step, "step_frac": frac,
                    "assign": ctx.prop_name, "gen": f"{ctx.element_id}H1",
                    "rel": ctx.rel_dist, "abs": self._abs_dist(ctx),
                    "P": float(N),
                    "M2": float(M2), "M3": float(M3),
                    "U1": float(d[0] * lh) if lh else None,
                    "R2": float(ctx.curvature(d, "M2") * lh) if lh else None,
                    "R3": float(ctx.curvature(d, "M3") * lh) if lh else None,
                    "state": ctx.worst_state(d),
                })
            self._overall_base = rows
        return self._overall_base

    def overall_rows(self, sf=1.0, sl=1.0):
        scale = {"abs": sl, "P": sf, "M2": sf * sl, "M3": sf * sl, "U1": sl}
        out = []
        for r in self._overall_rows_base():
            r = dict(r)
            for k, s in scale.items():
                if r[k] is not None:
                    r[k] = r[k] * s
            out.append(r)
        return out

    def fiber_rows(self, sf=1.0, sl=1.0, only_step=None):
        s_stress, s_area = sf / (sl * sl), sl * sl
        rows = []
        for step, frac, ctx, d, _lh, sig in self._iter(only_step):
            eps = ctx.fiber_strains(d)
            sidx = ctx.state_indices(eps)
            absd = self._abs_dist(ctx)
            absd = absd * sl if absd is not None else None
            for i, e in enumerate(eps):
                fd = ctx.fibers_def[i]
                rows.append({
                    "frame": ctx.element_id, "case": self.case_name,
                    "case_type": self.case_type, "step": step, "step_frac": frac,
                    "assign": ctx.prop_name, "gen": f"{ctx.element_id}H1",
                    "fiber": i + 1,
                    "stress": float(sig[i] if sig is not None else ctx.fiber_stress_at(i, e)) * s_stress,
                    "strain": float(e), "state": STATE_ORDER[int(sidx[i])],
                    "mat": ctx.materials[i], "area": float(ctx.area[i]) * s_area,
                    "c3": float(fd["coord3"]) * sl, "c2": float(fd["coord2"]) * sl,
                    "rel": ctx.rel_dist, "abs": absd,
                })
        return rows

    @staticmethod
    def _as_row(r, keys):
        return ["" if r[k] is None else r[k] for k in keys]

    def write_xlsx(self, path, sf, sl, u_force, u_len):
        import openpyxl                                                        
        wb = openpyxl.Workbook(write_only=True)
                                          
        ws1 = wb.create_sheet("Section Summary")
        ws1.append(overall_headers(u_force, u_len))
        for r in self.overall_rows(sf, sl):
            ws1.append(self._as_row(r, OVERALL_KEYS))
            
        ws2 = wb.create_sheet("Fiber Details")
        ws2.append(fiber_headers(u_force, u_len))
        for r in self.fiber_rows(sf, sl):
            ws2.append(self._as_row(r, FIBER_KEYS))
        wb.save(path)

    def write_csv(self, path_stem, sf, sl, u_force, u_len):
                                      
        p1, p2 = f"{path_stem}_SectionSummary.csv", f"{path_stem}_FiberDetails.csv"
        with open(p1, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(overall_headers(u_force, u_len))
            for r in self.overall_rows(sf, sl):
                w.writerow(self._as_row(r, OVERALL_KEYS))
        with open(p2, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(fiber_headers(u_force, u_len))
            for r in self.fiber_rows(sf, sl):
                w.writerow(self._as_row(r, FIBER_KEYS))
        return p1, p2
