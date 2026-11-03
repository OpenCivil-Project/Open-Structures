"""Pure display grouping for independently assigned distributed frame loads.

Current assignments are inspected, never combined or rewritten. Uniform loads
match exactly. Varying loads only share a chain when their full-span affine
profiles form the same physical ramp, including their complete load metadata.
"""
from collections import defaultdict, deque

import numpy as np

_GEOMETRY_TOLERANCE = 1e-8
_DIRECTION_TOLERANCE = 1e-10
_ROUNDOFF = 32 * np.finfo(float).eps

def _value(load, name, default=None):
    return load.get(name, default) if isinstance(load, dict) else getattr(load, name, default)

def frame_load_components(load, length, axes):
    """Resolve unsigned global bases and signed stored intensity profiles.

    Frame Gravity magnitudes are already signed by the assignment dialog. Its
    global basis is +Z, matching the native trapezoidal-load conversion; do not
    negate these values again. ``axes`` contains the drawn local 1/2/3 rows.
    Partial-span/non-affine profiles are retained but cannot join other frames.
    """
    length = float(length)
    axes = np.asarray(axes, dtype=float)
    if length <= 0 or not np.isfinite(length) or axes.shape != (3, 3) or not np.isfinite(axes).all():
        raise ValueError('Frame load components require a finite positive length and axes.')
    raw = tuple(float(_value(load, name, 0.0)) for name in ('wx', 'wy', 'wz'))
    if not np.isfinite(raw).all():
        raise ValueError('Frame intensities must be finite.')
    coord = str(_value(load, 'coord_system', 'Global')).upper()
    bases = axes if coord == 'LOCAL' else np.eye(3)
    direction_name = str(_value(load, 'load_direction', 'Gravity')).upper().replace('_', ' ')
    metadata = (str(_value(load, 'pattern_name', '')), coord,
                bool(_value(load, 'projected', False)), str(_value(load, 'load_type', 'Force')).upper(),
                direction_name, bool(_value(load, 'is_relative', True)))
    distances = _value(load, 'distances', [])
    magnitudes = _value(load, 'magnitudes', [])
    distances = np.asarray([] if distances is None else distances, dtype=float)
    magnitudes = np.asarray([] if magnitudes is None else magnitudes, dtype=float)
    if not np.isfinite(distances).all() or not np.isfinite(magnitudes).all():
        raise ValueError('Distributed profile coordinates and values must be finite.')
    has_profile = (len(distances) == len(magnitudes) and len(distances) >= 2
                   and bool(np.any(np.abs(magnitudes) > 1e-9)))
    if has_profile:
        if 'GRAVITY' in direction_name or 'Z' in direction_name or '3' in direction_name:
            axis_index = 2
        elif 'X' in direction_name or '1' in direction_name:
            axis_index = 0
        elif 'Y' in direction_name or '2' in direction_name:
            axis_index = 1
        else:
            raise ValueError(f'Unknown frame load direction {direction_name!r}.')
        positions = distances.copy()
        if not _value(load, 'is_relative', True):
            positions /= length
                                                                               
        ordered = bool(np.all(np.diff(positions) > 0))
        full_span = bool(positions[0] == 0.0 and positions[-1] == 1.0)
        expected = magnitudes[0] + positions * (magnitudes[-1] - magnitudes[0])
        tolerance = _ROUNDOFF * max(1.0, float(np.abs(magnitudes).max()))
        affine = bool(ordered and full_span and np.max(np.abs(magnitudes - expected)) <= tolerance)
        direction = bases[axis_index].copy()
        norm = np.linalg.norm(direction)
        if norm < 1e-12:
            raise ValueError('Degenerate frame load axis.')
        return [dict(direction=direction / norm, positions=positions, values=magnitudes.copy(),
                     uniform=False, affine=affine, full_span=full_span,
                     metadata=metadata + ('profile', axis_index, raw),
                     pattern=str(_value(load, 'pattern_name', '')),
                     load_type=str(_value(load, 'load_type', 'Force')))]
    result = []
    for index, value in enumerate(raw):
        if abs(value) <= 1e-9:
            continue
        direction = bases[index].copy()
        norm = np.linalg.norm(direction)
        if norm < 1e-12:
            raise ValueError('Degenerate frame load axis.')
        result.append(dict(direction=direction / norm, positions=np.array([0., 1.]),
                           values=np.array([value, value]), uniform=True, affine=True,
                           full_span=True, metadata=metadata + ('uniform', index),
                           pattern=str(_value(load, 'pattern_name', '')),
                           load_type=str(_value(load, 'load_type', 'Force'))))
    return result

def _geometry(record):
    try:
        points = np.asarray(record['points'], dtype=float)
        ids = tuple(record['node_ids'])
        offsets = np.asarray(record.get('offsets', np.zeros((2, 3))), dtype=float)
        if (points.shape != (2, 3) or len(ids) != 2 or ids[0] == ids[1]
                or offsets.shape != (2, 3) or not np.isfinite(points).all()
                or not np.isfinite(offsets).all()):
            return None
        length = float(np.linalg.norm(points[1] - points[0]))
        if length <= 1e-12:
            return None
        profiles = record['profiles']
        if not profiles:
            return None
        for profile in profiles:
            direction = np.asarray(profile['direction'], dtype=float)
            values = np.asarray(profile['values'], dtype=float)
            positions = np.asarray(profile['positions'], dtype=float)
            if (direction.shape != (3,) or not np.isfinite(direction).all()
                    or values.shape != positions.shape or values.ndim != 1
                    or len(values) < 2 or not np.isfinite(values).all()
                    or not np.isfinite(positions).all()):
                return None
            hash(profile['metadata'])
        hash(record['section_key'])
        return dict(points=points, ids=ids, offsets=offsets, length=length,
                    direction=(points[1] - points[0]) / length,
                    profiles=profiles, key=(record['section_key'], bool(record['selected']), record['visibility']))
    except (KeyError, TypeError, ValueError, IndexError):
        return None

def _compatible(a, b, joint):
    if a['key'] != b['key'] or len(a['profiles']) != len(b['profiles']):
        return False
    ai, bi = a['ids'].index(joint), b['ids'].index(joint)
    if not np.array_equal(a['points'][ai], b['points'][bi]):
        return False
    if not np.array_equal(a['offsets'][ai], b['offsets'][bi]):
        return False
    outgoing_a = a['points'][1-ai] - a['points'][ai]
    outgoing_b = b['points'][1-bi] - b['points'][bi]
    outgoing_a /= a['length']; outgoing_b /= b['length']
    if not np.allclose(outgoing_a, -outgoing_b, rtol=0.0, atol=_GEOMETRY_TOLERANCE):
        return False
    for pa, pb in zip(a['profiles'], b['profiles']):
        if (pa['metadata'] != pb['metadata'] or bool(pa['uniform']) != bool(pb['uniform'])
                or not pa['affine'] or not pb['affine']
                or not np.allclose(pa['direction'], pb['direction'], rtol=0.0,
                                   atol=_DIRECTION_TOLERANCE)):
            return False
        va, vb = np.asarray(pa['values']), np.asarray(pb['values'])
        if pa['uniform']:
            if va[0] != vb[0]:
                return False
        else:
            if va[0 if ai == 0 else -1] != vb[0 if bi == 0 else -1]:
                return False
            slope_a = (va[-1] - va[0]) / a['length'] * a['direction']
            slope_b = (vb[-1] - vb[0]) / b['length'] * b['direction']
            tolerance = _ROUNDOFF * max(1.0, float(np.abs(slope_a).max()), float(np.abs(slope_b).max()))
            if not np.allclose(slope_a, slope_b, rtol=0.0, atol=tolerance):
                return False
    return True

def build_frame_load_chains(records):
    """Group compatible current loading along unambiguous straight node chains."""
    records = list(records)
    geometry = [_geometry(record) for record in records]
    owners = defaultdict(list)
    for index, item in enumerate(geometry):
        if item is not None:
            for node in item['ids']:
                owners[node].append(index)
    adjacency = defaultdict(list)
    for joint, indices in owners.items():
        if len(indices) != 2:
            continue
        a, b = indices
        if _compatible(geometry[a], geometry[b], joint):
            adjacency[a].append(b); adjacency[b].append(a)
    seen, result = set(), []
    for seed, record in enumerate(records):
        if seed in seen:
            continue
        seen.add(seed)
        chain = [record]
        reference = geometry[seed]
        queue = deque([seed])
        while queue:
            current = queue.popleft()
            for index in adjacency[current]:
                if index in seen:
                    continue
                candidate = geometry[index]
                distances = np.linalg.norm(np.cross(
                    candidate['points'] - reference['points'][0], reference['direction']), axis=1)
                tolerance = _GEOMETRY_TOLERANCE * max(1.0, reference['length'], candidate['length'])
                if np.max(distances) > tolerance:
                    continue
                seen.add(index); queue.append(index); chain.append(records[index])
        result.append(chain)
    return result

def _fixed_frame_samples(candidates, points):
    distances = np.sum((points - points[0]) ** 2, axis=1)
    indices = [0]
    for _ in range(min(4, len(points)-1)):
        index = int(np.argmax(distances))
        if distances[index] <= 1e-20:
            break
        indices.append(index)
        distances = np.minimum(distances, np.sum((points-points[index]) ** 2, axis=1))
    return tuple(candidates[index] for index in indices)

def _prepare_single_frame(record, geometry):
    """The common undivided case needs no span search or lattice construction."""
    pair = geometry['points']
    length = geometry['length']
    forward = tuple(pair[0]) <= tuple(pair[1])
    first, last = (pair[0], pair[1]) if forward else (pair[1], pair[0])
    direction = geometry['direction'] if forward else -geometry['direction']
    anchor_t = .5
    partial = next((profile for profile in record['profiles']
        if not profile['uniform'] and not profile.get('full_span', True)), None)
    if partial is not None:
        anchor_t = min(1., max(0., float(partial['positions'][0] + partial['positions'][-1]) * .5))
    ordinary = all(profile.get('affine', False) for profile in record['profiles'])
    parameters = [anchor_t]
    for value in ((0., 1., .25, .75) if forward else (1., 0., .75, .25)):
        if abs(value - anchor_t) > 1e-12:
            parameters.append(value)
    if not ordinary:
                                                                            
        special = [profile for profile in record['profiles'] if not profile.get('affine', False)]
        peaks = [float(profile['positions'][int(np.argmax(np.abs(profile['values'])))])
                 for profile in special]
        knots = [float(t) for profile in special for t in profile['positions']]
        for value in peaks + knots:
            if len(parameters) >= 17:
                break
            if 0 <= value <= 1 and all(abs(value - previous) > 1e-12 for previous in parameters):
                parameters.append(value)
    ts = np.asarray(parameters)
    points = pair[0] + ts[:, None] * (pair[1] - pair[0])
    candidates = tuple((record, float(t)) for t in ts)
    max_abs = [float(np.max(np.abs(profile['values']))) for profile in record['profiles']]
    static = candidates if ordinary else _fixed_frame_samples(candidates, points)
    return dict(records=(record,), spans=((record, 0., length, forward),),
                representative=(record, anchor_t), anchor_record=record, anchor_t=anchor_t,
                candidates=candidates, candidate_records=(record,) * len(ts), candidate_ts=ts,
                candidate_points=points, static_samples=static,
                max_abs=max_abs, common_max_abs=max_abs, start=first.copy(), end=last.copy(),
                direction=direction.copy(), length=length)

def prepare_frame_load_chain(chain):
    """Cache chain ownership and candidate points independently of camera state."""
    chain = list(chain)
    valid = [(record, item) for record in chain if (item := _geometry(record)) is not None]
    if not valid:
        return dict(records=tuple(chain), spans=(), representative=(chain[0], .5) if chain else None,
                    anchor_record=chain[0] if chain else None, anchor_t=.5,
                    candidates=(), candidate_records=(), candidate_ts=np.empty(0),
                    candidate_points=np.empty((0, 3)), max_abs=[], common_max_abs=[],
                    start=None, end=None, direction=None, length=0.0)
    if len(valid) == 1:
        return _prepare_single_frame(*valid[0])
    endpoints = np.concatenate([item['points'] for _, item in valid])
    first = min(endpoints, key=lambda point: tuple(point))
    last = max(endpoints, key=lambda point: tuple(point))
    length = float(np.linalg.norm(last - first))
    direction = (last - first) / length
    spans = []
    for record, item in valid:
        s = (item['points'] - first) @ direction
        spans.append((record, float(min(s)), float(max(s)), bool(s[0] <= s[1])))
    spans.sort(key=lambda span: span[1])
    middle = length * .5
    span = min(spans, key=lambda span: max(span[1] - middle, 0, middle - span[2]))
    anchor_record = span[0]
    ratio = float(np.clip((middle - span[1]) / (span[2] - span[1]), 0, 1))
    anchor_t = ratio if span[3] else 1 - ratio
    candidates = [(anchor_record, anchor_t)]
    points = [np.asarray(anchor_record['points'])[0] + anchor_t * (
        np.asarray(anchor_record['points'])[1] - np.asarray(anchor_record['points'])[0])]
    anchor_s = float((points[0] - first) @ direction)
    ends = np.array([span[2] for span in spans])
                                                                          
    required = [0., length]
    distances = [anchor_s]
    tolerance = max(1., length) * 1e-12
    for value in required:
        if len(distances) >= 17:
            break
        if all(abs(value - previous) > tolerance for previous in distances):
            distances.append(float(value))
    grid = np.linspace(0., length, 5)
    while len(distances) < 17:
        gaps = np.min(np.abs(grid[:, None] - np.asarray(distances)[None, :]), axis=1)
        index = int(np.argmax(gaps))
        if gaps[index] <= tolerance:
            break
        distances.append(float(grid[index]))
    for s in sorted(distances[1:]):
        index = min(len(spans) - 1, int(np.searchsorted(ends, s, side='left')))
        record, lower, upper, forward = spans[index]
        fraction = min(1., max(0., (s - lower) / (upper - lower)))
        t = fraction if forward else 1 - fraction
        pair = np.asarray(record['points'], dtype=float)
        point = pair[0] + t * (pair[1] - pair[0])
        candidates.append((record, t)); points.append(point)
    count = len(anchor_record['profiles'])
    max_abs = [max(float(np.max(np.abs(record['profiles'][i]['values'])))
                   for record, _ in valid) for i in range(count)]
    points = np.asarray(points)
    return dict(records=tuple(span[0] for span in spans), spans=tuple(spans),
                start=first.copy(), end=last.copy(), direction=direction, length=length,
                representative=(anchor_record, anchor_t), anchor_record=anchor_record, anchor_t=anchor_t,
                candidates=tuple(candidates), candidate_records=tuple(record for record, _ in candidates),
                candidate_ts=np.array([t for _, t in candidates]),
                candidate_points=points, static_samples=_fixed_frame_samples(candidates, points),
                max_abs=max_abs, common_max_abs=max_abs)

def sample_frame_load_arrows(chain, project, spacing_px=55.0, prepared=None):
    """Sample continuous loading with view spacing, retaining each chain's seed."""
    prepared = prepare_frame_load_chain(chain) if prepared is None else prepared
    candidates = prepared['candidates']
    points = prepared['candidate_points']
    if not candidates:
        return []
    if project is None:
        static = prepared.get('static_samples')
        return list(static if static is not None else _fixed_frame_samples(candidates, points))
    try:
        spacing = float(spacing_px)
    except (ValueError, TypeError):
        spacing = 55.0
    if not np.isfinite(spacing) or spacing <= 0:
        spacing = 55.0
    screens = None
    batch = getattr(project, 'batch', None)
    if callable(batch):
        try:
            batch_result = np.asarray(batch(points), dtype=float)
            if batch_result.ndim == 2 and batch_result.shape[0] == len(points) and batch_result.shape[1] >= 2:
                screens = batch_result[:, :2]
        except (TypeError, ValueError, IndexError):
            pass
    if screens is None:
        screens = np.full((len(points), 2), np.nan)
        for index, point in enumerate(points):
            screen = project(point)
            if screen is not None:
                value = np.asarray(screen, dtype=float).ravel()
                if len(value) >= 2:
                    screens[index] = value[:2]
    visible = np.flatnonzero(np.isfinite(screens).all(axis=1))
    if not len(visible):
        return []
    tiles = np.floor(screens[visible] / spacing).astype(np.int64)
    distance = np.sum((screens[visible] - (tiles + .5) * spacing) ** 2, axis=1)
    order = np.lexsort((distance, tiles[:, 0], tiles[:, 1]))
    survivors = []
    previous = None
    for index in order:
        tile = tuple(tiles[index])
        if tile != previous:
            survivors.append(int(visible[index])); previous = tile
    seed = 0 if 0 in visible else int(visible[0])
    ordered = [seed] + [index for index in survivors if index != seed]
    occupied, chosen = defaultdict(list), []
    for index in ordered:
        point = screens[index]
        tile = tuple(np.floor(point / spacing).astype(int))
        too_close = any(np.sum((point - neighbor) ** 2) < spacing * spacing - 1e-8
                        for x in range(tile[0]-1, tile[0]+2)
                        for y in range(tile[1]-1, tile[1]+2)
                        for neighbor in occupied[(x, y)])
        if not too_close:
            occupied[tile].append(point); chosen.append(candidates[index])
    return chosen
