"""Perspective-safe lengths for model-attached load glyphs, in logical pixels."""
import numpy as np

def project_vectors(vectors, matrix):
    """Project 3D rows without starting a BLAS thread pool for a 3x4 product."""
    return np.einsum('ij,kj->ik', vectors, matrix[:, :3], optimize=False)

def bounded_arrow_length(tip, direction, nominal_length, mvp, width, height,
                         max_pixels=33., min_pixels=24.):
    """Measure an arrow without requiring its proposed tail to be on screen.

    The homogeneous projection gives the exact length at the requested pixel
    distance. Depth-plane limits keep the tail on the same side of the camera.
    Nearly view-parallel arrows retain their world length instead of growing
    toward infinity to satisfy a minimum visible length.
    """
    nominal = float(nominal_length)
    if nominal <= 0 or not np.isfinite(nominal):
        return 0.
    if mvp is None or width <= 0 or height <= 0:
        return nominal
    matrix = np.asarray(mvp, dtype=float)
    clip = matrix @ np.r_[tip, 1.]
    step = matrix @ np.r_[-np.asarray(direction, dtype=float), 0.]
    if not np.isfinite(clip).all() or not np.isfinite(step).all() or clip[3] <= 1e-12:
        return 0.
    limit = np.inf
    for value, derivative in ((clip[3] + clip[2], step[3] + step[2]),
                              (clip[3] - clip[2], step[3] - step[2]),
                              (clip[3], step[3])):
        if value <= 0:
            return 0.
        if derivative < 0:
            limit = min(limit, value / -derivative * .999)
    length = min(nominal, limit)
    pixel_scale = np.array([width / 2., height / 2.])
    ndc = clip[:2] / clip[3]
    jacobian = pixel_scale[:, None] * (matrix[:2, :3] - ndc[:, None] * matrix[3, :3])
    projected_step = float(np.linalg.norm(pixel_scale * (step[:2] - ndc * step[3])))
    if projected_step <= 1e-12:
        return length
    pixels = length * projected_step / (clip[3] + length * step[3])
    target = min(float(max_pixels), max(float(min_pixels), pixels))
    if target > pixels and projected_step < .1 * np.linalg.norm(jacobian):
        return length
    denominator = projected_step - target * step[3]
    if denominator <= 1e-12:
        return length
    return float(min(target * clip[3] / denominator, limit))

def bounded_arrow_lengths(tips, directions, nominal_lengths, mvp, width, height,
                          max_pixels=33., min_pixels=24.):
    """Size a cached array of glyphs with one projection and no per-glyph calls.

    Pixel bounds can be scalars or arrays, allowing area shafts, frame shafts
    and arrowhead wings to share a batch. Invalid or clipped glyphs return zero
    without affecting the other rows.
    """
    tips = np.asarray(tips, dtype=float).reshape(-1, 3)
    directions = np.asarray(directions, dtype=float).reshape(-1, 3)
    count = len(tips)
    nominal = np.broadcast_to(np.asarray(nominal_lengths, dtype=float), (count,))
    lengths = np.where(np.isfinite(nominal) & (nominal > 0), nominal, 0.)
    if not count or mvp is None or width <= 0 or height <= 0:
        return lengths
    matrix = np.asarray(mvp, dtype=float)
    clip = project_vectors(tips, matrix) + matrix[:, 3]
    step = -project_vectors(directions, matrix)
    plane_values = np.column_stack((clip[:, 3] + clip[:, 2],
                                    clip[:, 3] - clip[:, 2], clip[:, 3]))
    plane_steps = np.column_stack((step[:, 3] + step[:, 2],
                                   step[:, 3] - step[:, 2], step[:, 3]))
    valid = (np.isfinite(clip).all(axis=1) & np.isfinite(step).all(axis=1)
             & (clip[:, 3] > 1e-12) & (plane_values > 0).all(axis=1) & (lengths > 0))
    pixel_scale = np.array([width / 2., height / 2.])
    with np.errstate(divide='ignore', invalid='ignore', over='ignore'):
        limits = np.where(plane_steps < 0, plane_values / -plane_steps * .999,
                          np.inf).min(axis=1)
        lengths = np.minimum(lengths, limits)
        ndc = clip[:, :2] / clip[:, 3:4]
        projected_step = np.linalg.norm(pixel_scale * (step[:, :2] - ndc * step[:, 3:4]), axis=1)
        pixels = lengths * projected_step / (clip[:, 3] + lengths * step[:, 3])
        target = np.minimum(max_pixels, np.maximum(min_pixels, pixels))
        denominator = projected_step - target * step[:, 3]
        resize = valid & (projected_step > 1e-12) & (denominator > 1e-12)
        if np.any(np.asarray(min_pixels) > 0):
                                                                           
            row_norms = np.einsum('ij,ij->i', matrix[:2, :3], matrix[:2, :3])
            row_cross = matrix[:2, :3] @ matrix[3, :3]
            w_norm = np.dot(matrix[3, :3], matrix[3, :3])
            jacobian_norm = np.sqrt(np.maximum(0., ((row_norms - 2 * ndc * row_cross
                + ndc ** 2 * w_norm) * pixel_scale ** 2).sum(axis=1)))
            resize &= ~((target > pixels) & (projected_step < .1 * jacobian_norm))
        lengths = np.where(resize, np.minimum(target * clip[:, 3] / denominator, limits), lengths)
    return np.where(valid, lengths, 0.)
