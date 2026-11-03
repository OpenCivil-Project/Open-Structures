"""Resolve drawn area loads in the native shell solver's coordinate convention.

The quad axes below mirror ``linear_static.shell_element.local_axes`` exactly.
Importing that solver module requires its executable's bare-module search path,
so the GUI keeps this small pure implementation and checks it against the solver
in tests. No solver calculation or saved direction identifier is changed.
"""

from collections.abc import Mapping

import numpy as np

def _cross3(a, b):
                                                                           
    return np.array([a[1] * b[2] - a[2] * b[1],
                     a[2] * b[0] - a[0] * b[2],
                     a[0] * b[1] - a[1] * b[0]])

def area_load_axes(points, section=None):
    """Return rows (local 1, local 2, local 3) expressed in global coordinates.

    Quads use the exact native solver convention, including material_angle.
    The native shell solver rejects nonquads. For visualizing triangles and
    polygons, use their winding normal and the same in-plane-axis convention;
    that fallback does not claim native solver support for these faces.
    """
    P = np.asarray(points, dtype=float)
    if P.ndim != 2 or P.shape[1] != 3 or len(P) < 3 or not np.isfinite(P).all():
        raise ValueError("Area load axes require finite 3D polygon coordinates.")
    if len(P) == 4:
        n = _cross3(P[2] - P[0], P[3] - P[1])
    else:
                                                                               
        n = np.zeros(3)
        for i in range(1, len(P) - 1):
            n += _cross3(P[i] - P[0], P[i + 1] - P[0])
    nn = np.linalg.norm(n)
    if nn < 1e-14:
        raise ValueError("degenerate (zero-area) polygon")
    e3 = n / nn
    if abs(e3[2]) > 1.0 - 1e-9:
        e2 = np.array([0.0, 1.0, 0.0])
    else:
        e2 = np.array([0.0, 0.0, 1.0]) - e3[2] * e3
        e2 /= np.linalg.norm(e2)
    e1 = _cross3(e2, e3)
    if isinstance(section, Mapping):
        beta_deg = float(section.get("material_angle", section.get("angle", 0.0)) or 0.0)
    else:
        beta_deg = float(getattr(section, "material_angle", 0.0) or 0.0)
    if not np.isfinite(beta_deg):
        raise ValueError("Area material angle must be finite.")
    if beta_deg:
        b = np.radians(beta_deg)
        c, s = np.cos(b), np.sin(b)
        e1, e2 = c * e1 + s * e2, -s * e1 + c * e2
    return np.array([e1, e2, e3])

def _value(load, name, serialized_name=None, default=None):
    if isinstance(load, Mapping):
        return load.get(name, load.get(serialized_name, default))
    return getattr(load, name, default)

def _component(axis, value):
    value = float(value)
    if not np.isfinite(value):
        raise ValueError("Area load components must be finite.")
    if value == 0.0:
        return None
    direction = np.asarray(axis, dtype=float)
    direction = direction / np.linalg.norm(direction)
    return ((direction if value > 0 else -direction), abs(value))

def area_load_components(load, points, section=None):
    """Return separate (signed unit direction, positive magnitude) arrows.

    Uniform pressures use their explicit Gravity/Global/Local direction just
    like the solver. Gravity multipliers use GLOBAL axes or the rotated local
    basis: summing their drawn vectors is equivalent to ``R.T @ (gx,gy,gz)``.
    Components stay separate rather than being replaced by a resultant.
    Both live load objects and serialized solver load dictionaries are accepted.
    """
    uniform = _value(load, "uniform_load", "load")
    if uniform is not None:
        direction = str(_value(load, "load_direction", "direction", "Gravity"))
        direction = direction.upper().replace("_", " ")
        global_axes = {"GRAVITY": np.array([0., 0., -1.]),
                       "GLOBAL X": np.array([1., 0., 0.]),
                       "GLOBAL Y": np.array([0., 1., 0.]),
                       "GLOBAL Z": np.array([0., 0., 1.])}
        if direction in global_axes:
            axis = global_axes[direction]
        elif direction in ("LOCAL 1", "LOCAL 2", "LOCAL 3"):
            axis = area_load_axes(points, section)[int(direction[-1]) - 1]
        else:
            raise ValueError(f"Unknown area load direction '{direction}'.")
        component = _component(axis, uniform)
        return [component] if component is not None else []

    coord = str(_value(load, "coord_system", "coord", "GLOBAL")).upper()
    axes = np.eye(3) if coord == "GLOBAL" else area_load_axes(points, section)
    components = []
    for index, name in enumerate(("gx", "gy", "gz")):
        component = _component(axes[index], _value(load, name, default=0.0))
        if component is not None:
            components.append(component)
    return components
