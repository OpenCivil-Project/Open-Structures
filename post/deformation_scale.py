"""Stable deformation magnification for static results and complete histories."""

import math
from collections.abc import Mapping

import numpy as np

LTHA_NORMALIZED_VISUAL_INTENSITY = 0.5

def _dof_peaks(dofs):
    """Return translation/rotation norm peaks without changing result arrays."""
    try:
        values = np.asarray(dofs, dtype=float)
    except (TypeError, ValueError, OverflowError):
        return 0.0, 0.0, np.zeros(3)
    if values.ndim == 0 or values.shape[-1] < 3 or values.size == 0:
        return 0.0, 0.0, np.zeros(3)
    values = values.reshape(-1, values.shape[-1])[:, :6]
                                                                            
    values = np.where(np.isfinite(values), values, 0.0)
    with np.errstate(over="ignore"):
        translations = np.hypot.reduce(values[:, :3], axis=1)
        rotations = (np.hypot.reduce(values[:, 3:], axis=1)
                     if values.shape[1] > 3 else np.zeros(len(values)))
    limit = float(np.finfo(float).max)
    return (min(float(translations.max()), limit),
            min(float(rotations.max()), limit),
            np.abs(values[:, :3]).max(axis=0))

def compute_deformation_scale(model, displacements, target_fraction=0.10,
                              saved_states=None, history=None):
    """Fit the complete deformation to a fraction of the model span.

    ``displacements`` is a node-to-DOFs mapping; ``history`` maps nodes to
    time-by-DOFs arrays. Every supplied source contributes, including all saved
    states, so a quiet/final frame cannot produce an oversized playback scale.

    Joint translations use their resultant norm. Frame translations use a
    component envelope in a chord basis, because axial and transverse motion
    have different interpolation weights. A safe Hermite bound also includes
    end rotations: each rotation shape function
    has maximum magnitude 4L/27. Per-node peaks deliberately form a conservative
    bound even when endpoints reach their peaks at different times. Translation
    units and model coordinates must match; rotations are in radians.
    """
    nodes = getattr(model, "nodes", None)
    if not isinstance(nodes, Mapping) or not nodes:
        return 1.0
    try:
        fraction = float(target_fraction)
    except (TypeError, ValueError, OverflowError):
        return 1.0
    if not math.isfinite(fraction) or fraction <= 0.0:
        return 1.0

    coordinates = []
    for node in nodes.values():
        try:
            xyz = (float(node.x), float(node.y), float(node.z))
        except (AttributeError, TypeError, ValueError, OverflowError):
            continue
        if all(math.isfinite(value) for value in xyz):
            coordinates.append(xyz)
    if not coordinates:
        return 1.0
    with np.errstate(over="ignore", invalid="ignore"):
        model_size = float(np.ptp(np.asarray(coordinates), axis=0).max())
    if not math.isfinite(model_size) or model_size <= 0.0:
        return 1.0

    peaks = {}

    def include(source):
        if not isinstance(source, Mapping):
            return
        for node_id, dofs in source.items():
            translation, rotation, components = _dof_peaks(dofs)
            key = str(node_id)
            previous = peaks.get(key, (0.0, 0.0, np.zeros(3)))
            peaks[key] = (max(previous[0], translation),
                          max(previous[1], rotation),
                          np.maximum(previous[2], components))

    include(displacements)
    if saved_states is not None:
        try:
            for state in saved_states:
                if isinstance(state, Mapping):
                    include(state.get("displacements"))
        except TypeError:
            pass
    include(history)

    max_deformation = max((peak[0] for peak in peaks.values()), default=0.0)
    elements = getattr(model, "elements", None)
    if isinstance(elements, Mapping):
        for element in elements.values():
            try:
                node_i, node_j = element.node_i, element.node_j
                length = math.dist((node_i.x, node_i.y, node_i.z),
                                   (node_j.x, node_j.y, node_j.z))
                peak_i = peaks.get(str(node_i.id), (0.0, 0.0, np.zeros(3)))
                peak_j = peaks.get(str(node_j.id), (0.0, 0.0, np.zeros(3)))
            except (AttributeError, TypeError, ValueError, OverflowError):
                continue
            if not math.isfinite(length) or length <= 0.0:
                continue
            axis = (np.asarray([node_j.x, node_j.y, node_j.z], dtype=float)
                    - np.asarray([node_i.x, node_i.y, node_i.z], dtype=float)) / length
            reference = np.array([0.0, 1.0, 0.0] if abs(axis[2]) > 0.99
                                 else [0.0, 0.0, 1.0])
            transverse = np.cross(reference, axis)
            transverse /= np.linalg.norm(transverse)
            basis = np.abs(np.vstack([axis, transverse, np.cross(axis, transverse)]))
            with np.errstate(over="ignore", invalid="ignore"):
                component_bound = np.maximum(basis @ peak_i[2], basis @ peak_j[2])
                translation_bound = float(np.hypot.reduce(component_bound))
            curve_bound = (translation_bound
                           + (4.0 / 27.0) * length * (peak_i[1] + peak_j[1]))
            max_deformation = max(max_deformation, curve_bound)
    if max_deformation <= 0.0:
        return 1.0

    limit = float(np.finfo(float).max)
    max_deformation = min(max_deformation, limit)
    with np.errstate(over="ignore", under="ignore", invalid="ignore"):
        scale = (model_size / max_deformation) * fraction
    if math.isnan(scale):
        return 1.0
    return float(np.clip(scale, np.nextafter(0.0, 1.0), limit))
