"""Independent small-model reference for the linear/modal validation suite.

No OpenCivil element, assembly, mass, or solver routines are imported here.
The frame matrix is obtained from integrated force flexibility (Castigliano),
not from the twelve-by-twelve coefficients used by the production solver.
Distributed and interior loads are integrated against that independently
derived static displacement interpolation. Dense SciPy solves/eigensolves
provide a second numerical route for the *same discretized physical model*.

Continuum/textbook checks supplied in case ``spec`` remain a separate oracle.
Neither matching this implementation nor matching a second FE library is, by
itself, proof of convergence to a continuum solution.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
from scipy import linalg

G_ACCEL = 9.80665
SOURCES = [
    {
        "title": "Scott Whitney, University of Nebraska: Vibrations of Cantilever Beams (1999)",
        "url": "https://emweb.unl.edu/mechanics-pages/Scott-Whitney/325hweb/Beams.htm",
        "use": "Euler-Bernoulli cantilever deflection and frequency derivation",
    },
    {
        "title": "CALFEM for Python: core.py, bar2e/beam2e/beam3e/beam2de",
        "url": "https://github.com/CALFEM/calfem-python/blob/master/src/calfem/core.py",
        "use": "Public independent FE library and beam/bar reference formulations; not imported",
    },
    {
        "title": "OpenSees public examples: Example3.1.tcl",
        "url": "https://github.com/OpenSees/OpenSees/blob/master/EXAMPLES/ExampleScripts/Example3.1.tcl",
        "use": "Public portal-frame modelling benchmark example; not an analytical oracle",
    },
    {
        "title": "Gere and Timoshenko, Mechanics of Materials; Clough and Penzien, Dynamics of Structures",
        "url": None,
        "use": "Force-flexibility integration, beam boundary conditions, modal generalized eigenproblem",
    },
]


def _symmetric(matrix):
    return (matrix + matrix.T) * 0.5


def _rotation(p1, p2, beta):
    """Right-handed member axes, with roll beta in degrees."""
    x = np.asarray(p2, float) - np.asarray(p1, float)
    x /= np.linalg.norm(x)
    datum = np.array([1.0, 0.0, 0.0]) if abs(x[2]) > 0.999 else np.array([0.0, 0.0, 1.0])
    y = np.cross(datum, x)
    y /= np.linalg.norm(y)
    z = np.cross(x, y)
    angle = math.radians(beta)
    return np.array([x, math.cos(angle) * y + math.sin(angle) * z,
                     -math.sin(angle) * y + math.cos(angle) * z])


def _cross_matrix(vector):
    x, y, z = vector
    return np.array([[0.0, -z, y], [z, 0.0, -x], [-y, x, 0.0]])


def _rigid_arm(arm):
    transform = np.eye(6)
    # u at the member end = u at the node + theta cross arm.
    transform[:3, 3:] = -_cross_matrix(arm)
    return transform


def _bending(EI, shear_rigidity, length):
    """Flexibility for end shear/end moment of a fixed-base segment."""
    shear_compliance = length / shear_rigidity if shear_rigidity > 0 else 0.0
    flexibility = np.array([
        [length**3 / (3 * EI) + shear_compliance, length**2 / (2 * EI)],
        [length**2 / (2 * EI), length / EI],
    ])
    strain = np.array([[-1.0, -length, 1.0, 0.0], [0.0, -1.0, 0.0, 1.0]])
    return flexibility, strain


def _frame_stiffness(material, section, length, total_length):
    E, G = material["E"], material["G"]
    k = np.zeros((12, 12))
    for indices, rigidity in [([0, 6], E * section["A"]), ([3, 9], G * section["J"])]:
        k[np.ix_(indices, indices)] += rigidity / total_length * np.array([[1., -1.], [-1., 1.]])
    for indices, inertia, shear_area, signs in [
        ([1, 5, 7, 11], section["I33"], section["As2"], [1., 1., 1., 1.]),
        ([2, 4, 8, 10], section["I22"], section["As3"], [1., -1., 1., -1.]),
    ]:
        flex, strain = _bending(E * inertia, G * shear_area, length)
        sign = np.diag(signs)
        block = sign @ strain.T @ linalg.solve(flex, strain, assume_a="pos") @ sign
        k[np.ix_(indices, indices)] += block
    return _symmetric(k)


def _interpolation(material, section, length, x):
    """Exact static interpolation of translations/rotations at local x."""
    h = np.zeros((6, 12))
    fraction = x / length
    h[0, [0, 6]] = [1 - fraction, fraction]
    h[3, [3, 9]] = [1 - fraction, fraction]
    for indices, displacement, rotation, inertia, area, signs, rot_sign in [
        ([1, 5, 7, 11], 1, 5, section["I33"], section["As2"], [1., 1., 1., 1.], 1.),
        ([2, 4, 8, 10], 2, 4, section["I22"], section["As3"], [1., -1., 1., -1.], -1.),
    ]:
        EI, GA = material["E"] * inertia, material["G"] * area
        flexibility, strain = _bending(EI, GA, length)
        end_force_map = linalg.solve(flexibility, strain, assume_a="pos")
        v = np.array([1., x, 0., 0.]) + np.array([
            (length * x**2 / 2 - x**3 / 6) / EI + (x / GA if GA > 0 else 0),
            x**2 / (2 * EI),
        ]) @ end_force_map
        theta = np.array([0., 1., 0., 0.]) + np.array([
            (length * x - x**2 / 2) / EI, x / EI,
        ]) @ end_force_map
        h[displacement, indices] = v * signs
        h[rotation, indices] = rot_sign * theta * signs
    return h


def _condense(k, load, release):
    """Zero-force internal release coordinates, without a physical penalty."""
    released = np.flatnonzero(release)
    kept = np.flatnonzero(~np.asarray(release, dtype=bool))
    if not len(released):
        return k.copy(), load.copy()
    kc = k[np.ix_(released, released)]
    cross = k[np.ix_(kept, released)]
    inv = linalg.pinvh(kc, rtol=1e-13)
    condensed = np.zeros_like(k)
    condensed[np.ix_(kept, kept)] = k[np.ix_(kept, kept)] - cross @ inv @ cross.T
    condensed_load = np.zeros(12)
    condensed_load[kept] = load[kept] - cross @ inv @ load[released]
    return _symmetric(condensed), condensed_load


def _direction(name):
    name = str(name).upper()
    if "GRAVITY" in name:
        return np.array([0., 0., -1.])
    for axis, tokens in enumerate((("X", "1"), ("Y", "2"), ("Z", "3"))):
        if any(token in name for token in tokens):
            result = np.zeros(3)
            result[axis] = 1.
            return result
    raise ValueError(f"Unknown reference load direction {name!r}")


def _case_patterns(raw, name):
    case = next(c for c in raw["load_cases"] if c["name"] == name)
    return {item[0]: float(item[1]) for item in case.get("loads", [])}


def _section(raw):
    p, m = raw["properties"], raw.get("modifiers", {})
    return {
        "A_gross": p["A"], "A": p["A"] * m.get("A", 1.),
        "J": p["J"] * m.get("J", 1.),
        "I22": p["I22"] * m.get("I2", 1.), "I33": p["I33"] * m.get("I3", 1.),
        "As2": p.get("As2", 0.) * m.get("As2", 1.),
        "As3": p.get("As3", 0.) * m.get("As3", 1.),
        "theta_p": p.get("theta_p", 0.),
        "mass_mod": m.get("Mass", 1.), "weight_mod": m.get("Weight", 1.),
    }


def _elements(raw, index):
    nodes = {node["id"]: node for node in raw["nodes"]}
    materials = {mat["name"]: mat for mat in raw["materials"]}
    sections = {sec["name"]: sec for sec in raw["sections"]}
    elements = {}
    for record in raw["elements"]:
        pi = np.array([nodes[record["n1_id"]][key] for key in ("x", "y", "z")], float)
        pj = np.array([nodes[record["n2_id"]][key] for key in ("x", "y", "z")], float)
        oi, oj = np.array(record.get("off_i", [0., 0., 0.])), np.array(record.get("off_j", [0., 0., 0.]))
        total = float(np.linalg.norm(pj + oj - pi - oi))
        ri = float(record.get("end_off_i", 0.)) * record.get("rz_factor", 0.)
        rj = float(record.get("end_off_j", 0.)) * record.get("rz_factor", 0.)
        clear = total - ri - rj
        if clear <= 0:
            raise ValueError("Nonpositive member clear length")
        section_record = sections[record["sec_name"]]
        sec = _section(section_record)
        material = materials[section_record["mat_name"]]
        rotation = _rotation(pi + oi, pj + oj, record.get("beta", 0.) - math.degrees(sec["theta_p"]))
        rotate12 = linalg.block_diag(rotation, rotation, rotation, rotation)
        arm_i, arm_j = rotation @ oi, rotation @ oj
        arm_i[0] += ri
        arm_j[0] -= rj
        transform = linalg.block_diag(_rigid_arm(arm_i), _rigid_arm(arm_j)) @ rotate12
        k = _frame_stiffness(material, sec, clear, total)
        release = record.get("rel_i", [False] * 6) + record.get("rel_j", [False] * 6)
        kc, _ = _condense(k, np.zeros(12), release)
        kr = kc.copy()
        # This is a solver stabilization, never labelled physical stiffness.
        for dof in (3, 4, 5, 9, 10, 11):
            if release[dof]:
                kr[dof, dof] += float(np.max(np.abs(k))) * 1e-12
        dofs = np.r_[np.arange(index[record["n1_id"]] * 6, index[record["n1_id"]] * 6 + 6),
                     np.arange(index[record["n2_id"]] * 6, index[record["n2_id"]] * 6 + 6)]
        elements[record["id"]] = dict(record=record, k=k, kc=kc, kr=kr, transform=transform,
                                      rotation=rotation, material=material, section=sec,
                                      length=clear, total=total, ri=ri, rj=rj,
                                      pi=pi, pj=pj, oi=oi, oj=oj, dofs=dofs, release=release)
    return elements


def _load_local(element, load, scale):
    """Consistent local nodal action by virtual work; integrates polynomial q."""
    length, total = element["length"], element["total"]
    ri, rj = element["ri"], element["rj"]
    result = np.zeros(12)
    coordinate = str(load.get("coord", "Global")).upper()
    rotation = element["rotation"]
    if load["type"] == "member_point":
        direction = _direction(load["dir"])
        if "GRAVITY" in str(load["dir"]).upper():
            coordinate = "GLOBAL"
        vector = direction * float(load["force"]) * scale
        if coordinate == "GLOBAL":
            vector = rotation @ vector
        x = float(load["dist"]) * (total if load.get("is_rel", False) else 1.)
        if not ri <= x <= total - rj:
            raise ValueError("Reference point load on rigid arm is not implemented")
        h = _interpolation(element["material"], element["section"], length, x - ri)
        component = slice(3, 6) if load.get("l_type", "Force") == "Moment" else slice(0, 3)
        return h[component].T @ vector
    if load["type"] != "member_dist":
        raise ValueError(f"Unsupported reference member load {load['type']}")
    projected = bool(load.get("projected", False)) and coordinate == "GLOBAL"
    projection = np.linalg.norm((element["pj"] - element["pi"])[:2]) / total if projected else 1.
    magnitudes = load.get("magnitudes", [0., 0., 0., 0.])
    if any(abs(v) > 1e-9 for v in magnitudes):
        stations = np.asarray(load.get("distances", [0., .25, .75, 1.]), float)
        if load.get("is_relative", True):
            stations *= total
        direction = _direction(load.get("load_direction", "Gravity"))
        # Distributed Gravity magnitudes are signed global Z, unlike point Gravity.
        if "GRAVITY" in str(load.get("load_direction", "Gravity")).upper():
            direction = np.array([0., 0., 1.])
        vectors = np.outer(np.asarray(magnitudes, float) * scale * projection, direction)
    else:
        stations = np.array([0., total])
        vector = np.array([load.get(key, 0.) for key in ("wx", "wy", "wz")]) * scale * projection
        vectors = np.vstack([vector, vector])
    if coordinate == "GLOBAL":
        vectors = vectors @ rotation.T
    points, weights = np.polynomial.legendre.leggauss(5)
    for a, b, va, vb in zip(stations[:-1], stations[1:], vectors[:-1], vectors[1:]):
        for lower, upper in zip(sorted({float(a), float(b), *[v for v in (ri, total - rj) if a < v < b]})[:-1],
                                sorted({float(a), float(b), *[v for v in (ri, total - rj) if a < v < b]})[1:]):
            if upper <= lower:
                continue
            for point, weight in zip(points, weights):
                x = (lower + upper) / 2 + point * (upper - lower) / 2
                q = va + (vb - va) * (x - a) / (b - a)
                if x < ri or x > total - rj:
                    # Rigid pieces are assembled separately in global coordinates.
                    continue
                h = _interpolation(element["material"], element["section"], length, x - ri)
                result += h[:3].T @ q * weight * (upper - lower) / 2
    return result


def _load_global(element, load, scale):
    local = _load_local(element, load, scale)
    _, condensed = _condense(element["k"], local, element["release"])
    global_load = element["transform"].T @ condensed
    # Constant distributed load on rigid end portions, through centroid arms.
    if load["type"] == "member_dist" and (element["ri"] or element["rj"]):
        if any(abs(v) > 1e-9 for v in load.get("magnitudes", [])):
            raise ValueError("Varying load on rigid arm is not implemented in reference")
        q = np.array([load.get(key, 0.) for key in ("wx", "wy", "wz")]) * scale
        R = element["rotation"]
        if str(load.get("coord", "Global")).upper() != "GLOBAL":
            q = R.T @ q
        for end, rigid_length, insertion, sign in [(0, element["ri"], element["oi"], 1),
                                                   (6, element["rj"], element["oj"], -1)]:
            force = q * rigid_length
            arm = insertion + R.T @ np.array([sign * rigid_length / 2, 0., 0.])
            global_load[end:end + 3] += force
            global_load[end + 3:end + 6] += np.cross(arm, force)
    return global_load


def _assemble_load(raw, elements, index, patterns):
    vector = np.zeros(6 * len(index))
    loads = list(raw.get("loads", []))
    for pattern in raw.get("load_patterns", []):
        if pattern["name"] not in patterns or not pattern.get("sw_mult", 0.):
            continue
        for eid, element in elements.items():
            q = -element["material"]["rho"] * element["section"]["A_gross"] * element["section"]["weight_mod"] * pattern["sw_mult"]
            loads.append(dict(type="member_dist", pattern=pattern["name"], element_id=eid,
                              wx=0., wy=0., wz=q, coord="Global"))
    for load in loads:
        scale = patterns.get(load["pattern"], 0.)
        if not scale:
            continue
        if load["type"] == "nodal":
            start = index[load["node_id"]] * 6
            vector[start:start + 6] += np.array([load.get(key, 0.) for key in ("fx", "fy", "fz", "mx", "my", "mz")]) * scale
        else:
            element = elements[load["element_id"]]
            vector[element["dofs"]] += _load_global(element, load, scale)
    return vector


def _mass(raw, elements, index, modal_case):
    case = next(c for c in raw["load_cases"] if c["name"] == modal_case)
    sources = raw.get("mass_sources", [])
    if isinstance(sources, dict):
        sources = list(sources.values())
    name = case.get("mass_source", "Default")
    source = next((s for s in sources if s["name"] == name), None)
    if source is None and name == "Default" and sources:
        source = sources[0]
    if source is None:
        raise ValueError(f"No mass source {name}")
    mass = np.zeros(6 * len(index))
    if source.get("include_self_mass", True):
        for element in elements.values():
            total_mass = element["material"]["rho"] / G_ACCEL * element["section"]["A_gross"] * element["total"] * element["section"]["mass_mod"]
            for start in (element["dofs"][0], element["dofs"][6]):
                mass[start:start + 3] += total_mass / 2
        properties = {p["name"]: p for p in raw.get("link_properties", [])}
        for link in raw.get("links", []):
            prop = properties[link["prop_name"]]
            nodes = link["nodes"]
            for node in nodes:
                start = index[node] * 6
                mass[start:start + 3] += prop.get("mass", 0.) / len(nodes)
                mass[start + 3:start + 6] += np.array([prop.get(key, 0.) for key in ("r1", "r2", "r3")]) / len(nodes)
    if source.get("include_patterns", False):
        patterns = {}
        for item in source.get("load_patterns", []):
            if isinstance(item, dict):
                patterns[item["name"]] = item["scale"]
            else:
                patterns[item[0]] = item[1]
        accumulated = _assemble_load(raw, elements, index, patterns)
        # Native mass-source definition: signed net gravity action at each node / g.
        # Member point force masses use linear partition, unlike static interpolation.
        for load in raw.get("loads", []):
            if load["type"] != "member_point" or load.get("l_type", "Force") == "Moment":
                continue
            scale = patterns.get(load["pattern"], 0.)
            if not scale:
                continue
            element = elements[load["element_id"]]
            accumulated[element["dofs"]] -= _load_global(element, load, scale)
            force = _direction(load["dir"]) * load["force"] * scale
            if str(load.get("coord", "Global")).upper() != "GLOBAL" and "GRAVITY" not in str(load["dir"]).upper():
                force = element["rotation"].T @ force
            fraction = load["dist"] if load.get("is_rel", False) else load["dist"] / element["total"]
            accumulated[element["dofs"][:3]] += force * (1 - fraction)
            accumulated[element["dofs"][6:9]] += force * fraction
        for start in range(0, len(mass), 6):
            value = -accumulated[start + 2] / G_ACCEL
            if abs(value) > 1e-8:
                mass[start:start + 3] += value
    return mass


def _physical_modes(k, mass, count):
    """Exact elimination of truly massless coordinates, with no fictitious inertia."""
    massive = np.flatnonzero(mass > 1e-10)
    massless = np.flatnonzero(mass <= 1e-10)
    if np.any(mass < -1e-10):
        raise ValueError("Negative nodal mass in physical reference")
    if not len(massive):
        raise ValueError("No positive free mass")
    recover = np.zeros((len(k), len(massive)))
    recover[massive] = np.eye(len(massive))
    if len(massless):
        inverse = linalg.pinvh(k[np.ix_(massless, massless)], rtol=1e-13)
        recover[massless] = -inverse @ k[np.ix_(massless, massive)]
    reduced = _symmetric(recover.T @ k @ recover)
    values, vectors = linalg.eigh(reduced, np.diag(mass[massive]), check_finite=True)
    take = np.arange(min(count, len(values)))
    return values[take], recover @ vectors[:, take]


def _regularized_modes(k, mass):
    """Dense eigensolve of compliance avoids loss of low frequencies.

    Fictitious rotational masses make the highest omega^2 roughly a million
    times larger than physical values. Solving the inverse symmetric problem
    improves the low-frequency accuracy without changing K or M.
    """
    scale = 1. / np.sqrt(np.maximum(np.diag(k), 1e-30))
    scaled = _symmetric(scale[:, None] * k * scale[None, :])
    try:
        factor = linalg.cho_factor(scaled)
        inverse = linalg.cho_solve(factor, np.eye(len(k)))
        root_mass_scale = np.sqrt(mass) * scale
        compliance = _symmetric(root_mass_scale[:, None] * inverse * root_mass_scale[None, :])
        inverse_values, vectors = linalg.eigh(compliance, driver="evd")
        order = np.argsort(inverse_values)[::-1]
        inverse_values, vectors = inverse_values[order], vectors[:, order]
        values = 1. / np.maximum(inverse_values, 1e-300)
        return values, vectors / np.sqrt(mass)[:, None]
    except linalg.LinAlgError:
        # Preserve zero/negative mechanism modes for diagnostics.
        return linalg.eigh(k, np.diag(mass), driver="gvd")


def analyze(raw: dict[str, Any], static_case="STATIC", modal_case="MODAL", spec=None):
    """Return independent runtime arrays and a JSON-safe ``expected`` record.

    ``frequencies`` are ideal physical discretized frequencies. ``phi`` and
    ``frequencies_regularized`` explicitly include OpenCivil's documented
    numerical release stiffness and mass floor, so regression comparisons can
    separate solver algebra defects from the effect of those stabilizations.
    """
    if raw.get("area_elements") or raw.get("cables") or raw.get("constraints"):
        raise ValueError("This independent reference supports frames, springs and mass-only links")
    node_ids = sorted(node["id"] for node in raw["nodes"])
    index = {nid: i for i, nid in enumerate(node_ids)}
    nodes = {node["id"]: node for node in raw["nodes"]}
    n = 6 * len(node_ids)
    k, kr, spring = np.zeros((n, n)), np.zeros((n, n)), np.zeros((n, n))
    elements = _elements(raw, index)
    for element in elements.values():
        dofs, transform = element["dofs"], element["transform"]
        k[np.ix_(dofs, dofs)] += transform.T @ element["kc"] @ transform
        kr[np.ix_(dofs, dofs)] += transform.T @ element["kr"] @ transform
    for nid, node in nodes.items():
        if node.get("spring_matrix") is not None:
            dofs = np.arange(index[nid] * 6, index[nid] * 6 + 6)
            spring[np.ix_(dofs, dofs)] += np.asarray(node["spring_matrix"], float)
    properties = {p["name"]: p for p in raw.get("link_properties", [])}
    for link in raw.get("links", []):
        if np.any(properties[link["prop_name"]].get("stiffness", np.zeros((6, 6)))) or any(properties[link["prop_name"]].get("is_fixed", [])):
            raise ValueError("Only mass-only links are supported by independent reference")
    k, kr = _symmetric(k + spring), _symmetric(kr + spring)
    active = raw.get("info", {}).get("active_dofs", [True] * 6)
    free = np.array([index[nid] * 6 + dof for nid in node_ids for dof in range(6)
                     if active[dof] and not nodes[nid]["restraints"][dof]], dtype=int)
    p = _assemble_load(raw, elements, index, _case_patterns(raw, static_case))
    u = np.zeros(n)
    if len(free):
        kff = k[np.ix_(free, free)]
        # Exactly disconnected massless release rotations are gauge coordinates.
        row_norm = np.max(np.abs(kff), axis=1)
        live = row_norm > max(1., np.max(row_norm)) * 1e-14
        if np.any(~live & (np.abs(p[free]) > 1e-10)):
            raise ValueError("Static load acts on a zero-stiffness mechanism")
        u[free[live]] = linalg.solve(kff[np.ix_(live, live)], p[free[live]], assume_a="sym")
    residual = k @ u - p
    reaction = np.zeros(n)
    spring_reaction = -spring @ u
    for nid in node_ids:
        start = index[nid] * 6
        for dof in range(6):
            reaction[start + dof] = residual[start + dof] if nodes[nid]["restraints"][dof] else spring_reaction[start + dof]
    mass = _mass(raw, elements, index, modal_case)
    modal = next(c for c in raw["load_cases"] if c["name"] == modal_case)
    requested = int(modal.get("num_modes", 12))
    count = min(requested, max(1, len(free) - 2))
    free_mass = mass[free]
    positive = free_mass[free_mass > 1e-10]
    floor = float(np.min(positive) * 1e-6) if len(positive) else 1e-6
    regularized_mass = mass.copy()
    regularized_mass[free] += (free_mass < 1e-10) * floor
    values, vectors = _regularized_modes(kr[np.ix_(free, free)], regularized_mass[free])
    ideal_values, ideal_vectors = _physical_modes(k[np.ix_(free, free)], free_mass, count)
    phi = np.zeros((n, len(values)))
    phi[free] = vectors
    physical_phi = np.zeros((n, len(ideal_values)))
    physical_phi[free] = ideal_vectors
    for col in range(phi.shape[1]):
        if phi[np.argmax(np.abs(phi[:, col])), col] < 0:
            phi[:, col] *= -1
    frequencies = np.sqrt(np.maximum(ideal_values, 0.)) / (2 * np.pi)
    frequencies_regularized = np.sqrt(np.maximum(values, 0.)) / (2 * np.pi)
    expected = {
        "static": {
            "displacements": {str(nid): u[index[nid] * 6:index[nid] * 6 + 6].tolist() for nid in node_ids},
            "reactions": {str(nid): reaction[index[nid] * 6:index[nid] * 6 + 6].tolist() for nid in node_ids},
        },
        "modal": {
            "frequencies_hz": frequencies.tolist(),
            "regularized_frequencies_hz": frequencies_regularized[:count].tolist(),
            "regularization_relative_shift": ((frequencies_regularized[:len(frequencies)] - frequencies[:len(frequencies)]) /
                                               np.maximum(frequencies[:len(frequencies)], 1e-30)).tolist(),
            "mode_shapes": {str(i + 1): {str(nid): phi[index[nid] * 6:index[nid] * 6 + 6, i].tolist() for nid in node_ids}
                            for i in range(min(count, phi.shape[1]))},
            "assembled_mass": {str(nid): mass[index[nid] * 6:index[nid] * 6 + 6].tolist() for nid in node_ids},
        },
        "metadata": {
            "reference_kind": "Independent discretized force-flexibility reference with separate analytical checks",
            "mass_model": "Translational nodal lumping; rho denotes weight density; explicit link rotary inertia allowed",
            "regularized_reference": "Native-only numerical terms: released rotational diagonal=max(abs(k_local))*1e-12; massless free diagonal=min_positive_free_mass*1e-6",
            "mass_floor": floor, "requested_modes": requested, "native_clamped_modes": count,
            "sources": SOURCES,
        },
        "analytical_checks": (spec or {}).get("analytical_static", []) + (spec or {}).get("analytical_modal", []),
    }
    return dict(node_ids=node_ids, K=k, K_regularized=kr, P=p, mass=mass,
                mass_regularized=regularized_mass, free=free, U=u, R=reaction,
                frequencies=frequencies, frequencies_regularized=frequencies_regularized,
                eigenvalues=values, phi=phi, physical_phi=physical_phi,
                analytic_checks=expected["analytical_checks"], expected=expected)


solve_reference = analyze
