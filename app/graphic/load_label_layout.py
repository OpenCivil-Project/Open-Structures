"""Move load annotations in the view without changing their glyph size or values."""
from collections import defaultdict, deque

import numpy as np

_NEIGHBOR_LIMIT = 128
_CELL_SIZE = 64.
_CANDIDATE_PATTERN = np.array([(0, 0)] + [
    (x, y) for band in range(1, 9) for x, y in (
        (0, -band), (0, band), (-band, 0), (band, 0),
        (-1, -band), (1, -band), (-1, band), (1, band))], dtype=float)

class _LocalBoxes:
    """Bound collision work in crowded views while retaining every annotation."""
    def __init__(self, width, height):
        self.viewport = np.array([width, height], dtype=float)
        self.boxes = []
        self.cells = defaultdict(lambda: deque(maxlen=_NEIGHBOR_LIMIT))

    def _cells(self, box, gap=0.):
        lower = np.maximum(box[:2] - gap, 0.)
        upper = np.minimum(box[2:] + gap, self.viewport)
        if (lower > upper).any():
            return
        lower = np.floor(lower / _CELL_SIZE).astype(int)
        upper = np.floor(upper / _CELL_SIZE).astype(int)
        for y in range(lower[1], upper[1] + 1):
            for x in range(lower[0], upper[0] + 1):
                yield x, y

    def append(self, box):
        index = len(self.boxes)
        self.boxes.append(box)
        for cell in self._cells(box):
            self.cells[cell].append(index)

    def nearby(self, box):
        indices = set()
        for cell in self._cells(box, 4.):
            for index in reversed(self.cells.get(cell, ())):
                indices.add(index)
                if len(indices) >= _NEIGHBOR_LIMIT:
                    break
            if len(indices) >= _NEIGHBOR_LIMIT:
                break
        return np.asarray([self.boxes[index] for index in sorted(indices)],
                          dtype=float).reshape(-1, 4)

def _screen(point, mvp, width, height):
    clip = mvp @ np.append(point, 1.0)
    if not np.isfinite(clip).all() or clip[3] <= 1e-12:
        return None
    ndc = clip[:3] / clip[3]
    if abs(ndc[2]) > 1:
        return None
    return np.array([(ndc[0] + 1) * width / 2,
                     (1 - ndc[1]) * height / 2, ndc[2]])

def _label_world_corners(label, text_scale):
    text = label.get('text', '')
    if not text:
        return None
    h = float(label.get('text_height', 0.25)) * text_scale
    origin = np.asarray(label['pos_3d'], dtype=float)
    right = np.asarray(label['v_right'], dtype=float)
    up = np.asarray(label['v_up'], dtype=float)
    advance = 0.55 * h
    total = len(text) * advance
    alignment = label.get('align', 'center')
    shift = h * 0.5 if alignment == 'left' else (
        -total - h * 0.5 if alignment == 'right' else -total / 2)
    start = origin + right * shift + up * h * 0.4
    end = start + right * ((len(text) - 1) * advance + h)
    return np.array([start, end, end + up * h, start + up * h])

def _project_corners(clip, width, height):
    valid = (np.isfinite(clip).all(axis=(-2, -1))
             & (clip[..., 3] > 1e-12).all(axis=-1)
             & (np.abs(clip[..., 2]) <= clip[..., 3]).all(axis=-1))
    with np.errstate(divide='ignore', invalid='ignore'):
        xy = clip[..., :2] / clip[..., 3:4]
    xy = xy * np.array([width / 2., -height / 2.]) + np.array([width / 2., height / 2.])
    bounds = np.concatenate((xy.min(axis=-2), xy.max(axis=-2)), axis=-1)
    valid &= np.isfinite(bounds).all(axis=-1)
    return bounds, valid

def label_screen_bounds(label, mvp, width, height, text_scale=1.0):
    """Bound the actual SDF glyph quad layout, including the last glyph width."""
    corners = _label_world_corners(label, text_scale)
    if corners is None:
        return None
    mvp = np.asarray(mvp, dtype=float)
    clip = corners @ mvp[:, :3].T + mvp[:, 3]
    bounds, valid = _project_corners(clip, width, height)
    return bounds if valid else None

def _overlap(a, b, gap=4.0):
    span = np.minimum(a[2:], b[2:] + gap) - np.maximum(a[:2], b[:2] - gap)
    return float(np.maximum(span, 0).prod())

def layout_load_labels(labels, obstacles, mvp, width, height, text_scale=1.0):
    """Return moved copies and leader segments; retain every distinct annotation.

    Small/exception regions receive first choice. If the view cannot fit all
    values at this size, choose the least locally obstructed position rather
    than hide a different load or reduce its font. Collision work uses at most
    128 nearby boxes per annotation, even when thousands occupy one place.
    """
    if not labels or width <= 0 or height <= 0:
        return list(labels), []
    mvp = np.asarray(mvp, dtype=float).reshape(4, 4)
    try:
        inverse = np.linalg.inv(mvp)
    except np.linalg.LinAlgError:
        return list(labels), []
    occupied = _LocalBoxes(width, height)
    for label in obstacles:
        box = label_screen_bounds(label, mvp, width, height)
        if box is not None:
            occupied.append(box)
    placed = [None] * len(labels)
    leaders = []
    order = sorted(range(len(labels)), key=lambda i: (
        labels[i].get('group_count', 1), i))

    def unproject(screen):
        ndc = np.array([2 * screen[0] / width - 1,
                        1 - 2 * screen[1] / height, screen[2], 1.0])
        world = inverse @ ndc
        return world[:3] / world[3]

    for index in order:
        source = labels[index]
        label = dict(source)
        owner_screen = _screen(source.get('leader_anchor', source['pos_3d']),
                               mvp, width, height)
        if (owner_screen is None or (owner_screen[:2] < 0).any()
                or (owner_screen[:2] > [width, height]).any()):
            continue
        corners = _label_world_corners(label, text_scale)
        clip = None if corners is None else corners @ mvp[:, :3].T + mvp[:, 3]
        box, valid_box = (None, False) if clip is None else _project_corners(clip, width, height)
        origin_screen = _screen(label['pos_3d'], mvp, width, height)
        if not valid_box or origin_screen is None:
            placed[index] = label
            continue
        size = box[2:] - box[:2]
        clamp = np.maximum(6 - box[:2], 0) - np.maximum(
            box[2:] - np.array([width - 6, height - 6]), 0)
        step_y = min(42.0, max(18.0, size[1] + 8))
        step_x = min(48.0, max(36.0, size[0] + 8))
        offsets = _CANDIDATE_PATTERN * [step_x, step_y] + clamp
        if np.linalg.norm(clamp) > 48:
            offsets[0] = 0.
        distances = np.linalg.norm(offsets, axis=1)
        rows = np.flatnonzero(distances <= 48)
                                                                             
        screens = np.tile(origin_screen, (len(rows), 1))
        screens[:, :2] += offsets[rows]
        ndc = np.column_stack((2 * screens[:, 0] / width - 1,
                               1 - 2 * screens[:, 1] / height,
                               screens[:, 2], np.ones(len(rows))))
        world = ndc @ inverse.T
        with np.errstate(divide='ignore', invalid='ignore'):
            positions = world[:, :3] / world[:, 3:4]
        world_delta = positions - np.asarray(label['pos_3d'])
        candidate_clip = clip[None, :, :] + (world_delta @ mvp[:, :3].T)[:, None, :]
        bounds, valid = _project_corners(candidate_clip, width, height)
        valid &= (bounds[:, :2] >= 4).all(axis=1) & (bounds[:, 2:] <= [width - 4, height - 4]).all(axis=1)
        candidates = np.flatnonzero(valid)
        candidate, chosen_bounds, delta = label, box, np.zeros(2)
        if len(candidates):
            boxes = bounds[candidates]
            nearby = occupied.nearby(np.r_[boxes[:, :2].min(axis=0), boxes[:, 2:].max(axis=0)])
            span = np.minimum(boxes[:, None, 2:], nearby[None, :, 2:] + 4.) - np.maximum(
                boxes[:, None, :2], nearby[None, :, :2] - 4.)
            span = np.maximum(span, 0.)
            overlaps = (span[:, :, 0] * span[:, :, 1]).sum(axis=1)
            empty = np.flatnonzero(overlaps == 0.)
            choice = int(empty[0]) if len(empty) else int(np.lexsort(
                (np.arange(len(candidates)), distances[rows[candidates]], overlaps))[0])
            chosen = candidates[choice]
            delta = offsets[rows[chosen]]
            candidate = (label if np.linalg.norm(delta) <= 1e-12 else
                         dict(label, pos_3d=positions[chosen].tolist()))
            chosen_bounds = bounds[chosen]
        placed[index] = candidate
        occupied.append(chosen_bounds)
        if np.linalg.norm(delta) > 1:
            anchor = np.asarray(source.get('leader_anchor', source['pos_3d']), dtype=float)
            anchor_screen = _screen(anchor, mvp, width, height)
            if anchor_screen is not None:
                endpoint = np.clip(anchor_screen[:2], chosen_bounds[:2], chosen_bounds[2:])
                endpoint_world = unproject(np.r_[endpoint, origin_screen[2]])
                leaders.append((anchor, endpoint_world, source.get('color', [0, 0, 0, 1])))
    return [label for label in placed if label is not None], leaders
