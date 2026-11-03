"""Drift decomposition and damage-event detection for OpenSees displacement-control runs.

Both are read-only: they look at a COMMITTED solver state (call `capture` only after an accepted step)
and never change the model.

Drift decomposition
-------------------
For every column end that has a bar-slip and/or shear spring in series (OpenCivil inserts them as
coincident node pairs between the support and the member), the control-node displacement is split into

    u_total = u_slip + u_shear + u_flex

    u_slip  = ((theta_slip x r) + (d_slip - d_support)) . e      rigid rotation (fixed-end rotation) of the
                                                                 member above the slip node, about the support,
                                                                 plus any axial/shear slip translation
    u_shear = (d_shear_node - d_slip_node) . e                   relative translation across the shear spring
    u_flex  = u_total - u_slip - u_shear                         what is left: member flexure (+ P-Delta)

`r` is the vector from the support to the control node in the undeformed geometry and `e` the unit vector
of the control DOF. With several columns the contributions are summed; for a single-column test (the PEER
specimens) this is exact.

Damage events
-------------
The fibres of the hinge-end sections (first / last integration point of each nonlinear element) are read
every accepted step ('fiberData2': y, z, area, matTag, stress, strain) and the first step at which a limit
is reached is stored:

    first_yield         any longitudinal bar in tension reaches fy/Es
    bar_hardening       any bar reaches eps_sh (strain hardening starts)
    cover_peak          cover concrete reaches the strain of its peak stress (crushing starts)
    cover_spalling      cover concrete reaches its ultimate strain epscu (stress -> 0 in Concrete04)
    core_crushing       confined core concrete reaches its ultimate strain epscu
    bar_ultimate        any bar in tension reaches eps_su (fracture strain of the steel curve)
    bar_compression_yield  any bar in compression reaches -fy/Es

Each event stores the step number, the control displacement, the base shear and the section / fibre
strain that triggered it. These are strain-based model events -- compare them with the test's observed
damage (e.g. PEER: crushing at 7 mm, spalling at 14 mm), they are not observations.
"""

import math

import numpy as np

EVENT_ORDER = ("first_yield", "bar_compression_yield", "bar_hardening", "cover_peak",
               "cover_spalling", "core_crushing", "bar_ultimate")

EVENT_LABELS = {
    "first_yield": "First yield (tension bar reaches fy/Es)",
    "bar_compression_yield": "Compression bar yield",
    "bar_hardening": "Strain hardening starts",
    "cover_peak": "Cover reaches peak stress (crushing starts)",
    "cover_spalling": "Cover reaches ultimate strain (spalling)",
    "core_crushing": "Core reaches ultimate strain (crushing)",
    "bar_ultimate": "Bar reaches ultimate strain",
}

def _unit(dof):
    """Unit vector (global) of OpenSees DOF 1..6 (translations 1..3 only are used here)."""
    e = np.zeros(3)
    e[(int(dof) - 1) % 3] = 1.0
    return e

class DriftEventMonitor:
    def __init__(self, converter, ops, control_node, control_dof):
        self.conv = converter
        self.ops = ops
        self.node = int(control_node)
        self.dof = int(control_dof)
        self.e = _unit(self.dof)
        self.warnings = []
        self.drift = {"steps": [], "u_total": [], "u_slip": [], "u_shear": [], "u_flex": []}
        self.events = {}
        self._springs = []
        self._targets = []
        self._limits = {}
        self._masks = {}
        self._disabled = False
        self._init_springs()
        self._init_fibers()

    def _warn(self, msg):
        if msg not in self.warnings:
            self.warnings.append(msg)

    def _init_springs(self):
        conv = self.conv
        nodes = conv.nodes
        if self.node not in nodes:
            self._warn("drift decomposition: control node not found")
            return
        c = np.array([nodes[self.node][k] for k in "xyz"], float)
        for rec in getattr(conv, "spring_nodes", []):
            sup = rec["support"]
            if sup not in nodes:
                continue
            p = np.array([nodes[sup][k] for k in "xyz"], float)
            self._springs.append({"support": sup, "slip": rec.get("slip"), "shear": rec.get("shear"),
                                  "r": c - p})

    def _init_fibers(self):
        conv = self.conv
        builder = getattr(conv, "_nl_builder", None)
        if builder is None:
            return
        cache = getattr(builder, "_mat_cache", {})
        tag_role = {}
        for key, tag in cache.items():
            kind = key[0] if isinstance(key, tuple) else str(key)
            if kind == "rebar":
                tag_role[int(tag)] = "steel"
            elif kind == "conc-unconf":
                tag_role[int(tag)] = "cover"
            elif kind == "conc-conf":
                tag_role[int(tag)] = "core"
        self._tag_role = tag_role
        plans = {}
                                                                                                     
        for name, info in getattr(builder, "_built", {}).items():
            if isinstance(name, str) and isinstance(info, dict) and "plan" in info:
                plans[name] = info["plan"]
                                                                       
        for name, plan in plans.items():
            rp = plan.rebar["params"]
            lim = {"ey": rp["fy"] / rp["Es"], "esh": rp["esh"], "esu": rp["eu"]}
            cov = plan.concrete.get("cover")
            cor = plan.concrete.get("core")
            if cov:
                lim["cover_e0"], lim["cover_cu"] = cov["params"]["epsc0"], cov["params"]["epscu"]
            if cor:
                lim["core_cu"] = cor["params"]["epscu"]
            self._limits[name] = lim
        rec = getattr(conv, "_hinge_recorder", None)
        if rec is None:
            self._warn("damage events: no hinge recorder on the converter")
            return
        by_ele = {}
        for key, tag, index in rec._targets:
            by_ele.setdefault(tag, []).append((key, index))
        for tag, lst in by_ele.items():
            idxs = sorted(i for _, i in lst)
            ends = {idxs[0], idxs[-1]}
            for key, index in lst:
                if index in ends:
                    sec = rec.sections[key]["section_name"]
                    if sec in self._limits:
                        self._targets.append((key, tag, index, sec))
        if not self._targets:
            self._warn("damage events: no hinge-end sections matched a built fiber section; none will be detected")
        if not self._tag_role or "steel" not in self._tag_role.values():
            self._warn("damage events: no bar material tag found in the builder's material cache")

    def capture(self, step, u_total, base_vec):
        try:
            self._capture_drift(step, u_total)
        except Exception as exc:                                                                
            self._warn(f"drift decomposition skipped at step {step} ({type(exc).__name__}: {exc})")
        if not self._disabled:
            try:
                self._capture_events(step, u_total, base_vec)
            except Exception as exc:
                self._disabled = True
                self._warn(f"damage-event detection disabled at step {step} ({type(exc).__name__}: {exc})")

    def _disp(self, node):
        v = self.ops.nodeDisp(node)
        return np.array(v[:3], float), np.array(v[3:6], float)

    def _capture_drift(self, step, u_total):
        slip_c = shear_c = 0.0
        for sp in self._springs:
            d_sup, th_sup = self._disp(sp["support"])
            prev_d, prev_th = d_sup, th_sup
            if sp["slip"] is not None:
                d_s, th_s = self._disp(sp["slip"])
                rel_th = th_s - th_sup
                slip_c += float(np.dot(np.cross(rel_th, sp["r"]) + (d_s - d_sup), self.e))
                prev_d, prev_th = d_s, th_s
            if sp["shear"] is not None:
                d_h, th_h = self._disp(sp["shear"])
                shear_c += float(np.dot(d_h - prev_d, self.e))
        h = self.drift
        h["steps"].append(int(step))
        h["u_total"].append(float(u_total))
        h["u_slip"].append(slip_c)
        h["u_shear"].append(shear_c)
        h["u_flex"].append(float(u_total) - slip_c - shear_c)

    def _fire(self, name, step, u, base_vec, key, val):
        if name in self.events:
            return
        V = -float(base_vec[self.dof - 1]) if base_vec is not None else None
        self.events[name] = {"event": name, "label": EVENT_LABELS[name], "step": int(step),
                             "u_m": float(u), "V_N": V, "section": key, "strain": float(val)}

    def _capture_events(self, step, u, base_vec):
        if len(self.events) == len(EVENT_ORDER):
            return
        for key, tag, index, sec in self._targets:
            flat = self.ops.eleResponse(tag, "section", index, "fiberData2")
            arr = np.asarray(flat, float).reshape(-1, 6)
            mk = self._masks.get(key)
            if mk is None:
                roles = np.array([self._tag_role.get(int(t), "") for t in arr[:, 3]])
                mk = {r: roles == r for r in ("steel", "cover", "core")}
                if not mk["steel"].any():
                    raise RuntimeError("no fibers matched to the bar material tag")
                self._masks[key] = mk
            eps = arr[:, 5]
            lim = self._limits[sec]
            st = eps[mk["steel"]]
            smax, smin = float(st.max()), float(st.min())
            if smax >= lim["ey"]:
                self._fire("first_yield", step, u, base_vec, key, smax)
            if smin <= -lim["ey"]:
                self._fire("bar_compression_yield", step, u, base_vec, key, smin)
            if smax >= lim["esh"]:
                self._fire("bar_hardening", step, u, base_vec, key, smax)
            if smax >= lim["esu"]:
                self._fire("bar_ultimate", step, u, base_vec, key, smax)
            if mk["cover"].any() and "cover_cu" in lim:
                cmin = float(eps[mk["cover"]].min())
                if cmin <= lim["cover_e0"]:
                    self._fire("cover_peak", step, u, base_vec, key, cmin)
                if cmin <= lim["cover_cu"]:
                    self._fire("cover_spalling", step, u, base_vec, key, cmin)
            if mk["core"].any() and "core_cu" in lim:
                cmin = float(eps[mk["core"]].min())
                if cmin <= lim["core_cu"]:
                    self._fire("core_crushing", step, u, base_vec, key, cmin)

    def event_list(self):
        return [self.events[n] for n in EVENT_ORDER if n in self.events]

    def drift_record(self):
        h = self.drift
        if not h["steps"]:
            return None
        return {k: ([float(f"{x:.9g}") for x in v] if k != "steps" else list(v)) for k, v in h.items()}

    def summary_lines(self, to_len=lambda v: v, len_name="m"):
        lines = []
        h = self.drift
        if h["steps"] and self._springs:
            i = int(np.argmax(np.abs(h["u_total"])))
            ut = h["u_total"][i]
            if abs(ut) > 1e-12:
                lines.append(
                    f"  [drift] at the largest displacement ({to_len(ut):.4g} {len_name}): "
                    f"slip {100 * h['u_slip'][i] / ut:.0f}% | shear {100 * h['u_shear'][i] / ut:.0f}% | "
                    f"flexure {100 * h['u_flex'][i] / ut:.0f}%")
        for ev in self.event_list():
            v = f", V = {ev['V_N'] / 1e3:.1f} kN" if ev["V_N"] is not None else ""
            lines.append(f"  [event] {ev['label']}: step {ev['step']}, u = {to_len(ev['u_m']):.4g} {len_name}{v}")
        for w in self.warnings:
            lines.append(f"  [!] {w}")
        return lines
