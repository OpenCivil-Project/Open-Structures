"""Persist OpenSees beam responses and recover OpenCivil force diagrams.

The adapter emits full-span uniform loads on each solver beam; interior
point forces/moments are applied to real split nodes. Thus the local end
force sum gives the *actual* uniform load, including the current load factor
and frozen predecessor patterns. No native stiffness or model loads are used.
All saved values use SI units. Local end vectors are resisting forces in
[Fx, Fy, Fz, Mx, My, Mz] order at i, then j.
"""

import numpy as np

def is_opensees_result(results, model=None):
    info = (results or {}).get("info", {})
    engine = info.get("engine", info.get("analysis_engine"))
    if engine is not None:
        return str(engine).lower() == "opensees"
    if "opensees_forces" in (results or {}):
        return True
    if str(info.get("version", "")).lower().startswith("opensees"):
        return True
                                                                      
    if results:
        return False
    return getattr(model, "analysis_engine", "native") == "opensees"

def select_opensees_force_state(results, step_number=None):
    """Select final forces, or a one-based saved-state ordinal as in the UI."""
    state = results
    if step_number is not None:
        states = results.get("saved_states") or []
        index = int(step_number) - 1
        if index < 0 or index >= len(states):
            raise ValueError("The selected OpenSees saved state is unavailable. Rerun the analysis with Multiple States.")
        state = states[index]
    if not isinstance(state, dict) or not isinstance(state.get("opensees_forces"), dict):
        raise ValueError("OpenSees member forces are missing from this result. Rerun the analysis to recover forces.")
    return state

def capture_member_forces(converter, ops):
    """Read the live domain before it is wiped; retain every split beam."""
    records = {}
    for eid, chain in converter.split_info.items():
        el = converter.elements[eid]
        origin = np.asarray(ops.nodeCoord(el["n1_id"]), dtype=float)
        oc_axes = np.asarray(converter.element_local_axes[eid], dtype=float)
        segments = []
        for tag in chain["ele_tags"]:
                                                                            
            ni, nj = ops.eleNodes(tag)
            pi = np.asarray(ops.nodeCoord(ni), dtype=float)
            pj = np.asarray(ops.nodeCoord(nj), dtype=float)
                                                                      
            offsets = np.asarray(ops.eleResponse(tag, "offsets"), dtype=float)
            if offsets.shape != (6,) or not np.all(np.isfinite(offsets)):
                raise ValueError(f"OpenSees element {tag}: valid rigid offsets were not returned.")
            pi, pj = pi + offsets[:3], pj + offsets[3:]
            length = float(np.linalg.norm(pj - pi))
            axes = np.asarray([ops.eleResponse(tag, axis)
                               for axis in ("xaxis", "yaxis", "zaxis")], dtype=float)
            forces = np.asarray(ops.eleResponse(tag, "localForce"), dtype=float)
            if not np.isfinite(length) or length <= 0 or axes.shape != (3, 3) or forces.shape != (12,):
                raise ValueError(f"OpenSees element {tag}: valid local axes/length/12 end forces were not returned.")
            if not np.all(np.isfinite(forces)) or not np.all(np.isfinite(axes)):
                raise ValueError(f"OpenSees element {tag}: non-finite force response.")
            rotation = oc_axes @ axes.T
            end_oc = (forces.reshape(4, 3) @ rotation.T).reshape(12)
            segments.append({
                "tag": int(tag),
                "kind": "forceBeamColumn" if tag in converter.nl_elements else "ElasticTimoshenkoBeam",
                "start": float(np.dot(pi - origin, oc_axes[0])),
                "end": float(np.dot(pj - origin, oc_axes[0])),
                "length": length,
                "local_forces": forces.tolist(),
                "to_opencivil": rotation.tolist(),
                "end_forces": end_oc.tolist(),
            })
        records[str(eid)] = {
            "schema_version": 1,
            "end_forces": segments[0]["end_forces"][:6] + segments[-1]["end_forces"][6:],
            "segments": segments,
        }
    return records

def recover_member_forces(record, num_stations=21):
    """Recover each solver segment, preserving both sides of load jumps.

    ForceBeamColumn uses linear basic-force interpolation plus the uniform
    element-load particular solution. Elastic beam diagrams use the same
    end-force equilibrium interpolation. The adapter's ElasticTimoshenkoBeam
    commands omit -geomNonlinear, so those elements remain geometrically
    linear even with a PDelta/Corotational transformation (OpenSees 3.8).
    Both queried end moments are retained, including forceBeamColumn's
    second-order response. This does not reconstruct a native elastic K*u.
    Returned signs match MemberAnalyzer: P=-Fx, V2=Fy, V3=-Fz,
    T=Mx, M2=My, M3=Mz on the i-side of a section cut.
    """
    segments = record.get("segments") or []
    if record.get("schema_version") != 1 or not segments:
        raise ValueError("Unsupported or missing OpenSees member force data. Rerun the analysis.")
    lo, hi = float(segments[0]["start"]), float(segments[-1]["end"])
    if hi <= lo:
        raise ValueError("OpenSees member offsets leave no positive diagram span.")
    grid = np.linspace(lo, hi, max(2, int(num_stations)))
    stations, values = [], []
    for segment in segments:
        a, b, length = (float(segment[k]) for k in ("start", "end", "length"))
        if not np.all(np.isfinite([a, b, length])) or b <= a or length <= 0:
            raise ValueError("OpenSees sub-element has no positive diagram span.")
                                                                               
        x_plot = np.unique(np.r_[a, grid[(grid > a) & (grid < b)], b])
        t = (x_plot - a) / (b - a)
        x = t * length
        f = np.asarray(segment["local_forces"], dtype=float)
        rot = np.asarray(segment["to_opencivil"], dtype=float)
        if (f.shape != (12,) or rot.shape != (3, 3)
                or not np.all(np.isfinite(f)) or not np.all(np.isfinite(rot))):
            raise ValueError("Invalid OpenSees member force data. Rerun the analysis.")
        w = -(f[:3] + f[6:9]) / length
        force = (1.0 - t[:, None]) * f[:3] - t[:, None] * f[6:9]
        moment = (1.0 - t[:, None]) * f[3:6] - t[:, None] * f[9:12]
        moment[:, 1] += w[2] * x * (x - length) / 2.0
        moment[:, 2] -= w[1] * x * (x - length) / 2.0
        force = force @ rot.T
        moment = moment @ rot.T
        values.append(np.column_stack((-force[:, 0], moment[:, 0],
                                       force[:, 1], -force[:, 2],
                                       moment[:, 1], moment[:, 2])))
        stations.append(x_plot)
    output = dict(zip(("P", "T", "V2", "V3", "M2", "M3"), np.concatenate(values).T))
    output.update(stations=np.concatenate(stations),
                  end_forces=np.asarray(record["end_forces"], dtype=float),
                  L_clear=sum(float(segment["length"]) for segment in segments))
    return output
