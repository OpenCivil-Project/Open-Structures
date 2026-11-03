"""Display-only grouping and sampling of independently assigned area loads.

The caller supplies complete load signatures and resolved drawing directions.
These helpers neither combine load values nor modify the original records.
"""
from collections import defaultdict, deque
import math

import numpy as np

_PLANE_TOLERANCE = 1e-8
_DIRECTION_TOLERANCE = 1e-8

def _geometry(record):
    """Return validated face geometry, or None for an unsafe grouping input."""
    try:
        points = np.asarray(record['points'], dtype=np.float64)
        node_ids = tuple(record['node_ids'])
        normal = np.asarray(record['normal'], dtype=np.float64)
        if (points.ndim != 2 or points.shape[1] != 3 or len(points) < 3
                or len(node_ids) != len(points) or len(set(node_ids)) != len(node_ids)
                or normal.shape != (3,) or not np.isfinite(points).all()
                or not np.isfinite(normal).all()):
            return None
        normal_length = float(np.linalg.norm(normal))
        if normal_length < 1e-12:
            return None
        normal = normal / normal_length
        span = max(1.0, float(np.max(np.ptp(points, axis=0))))
        if np.max(np.abs((points - points[0]) @ normal)) > _PLANE_TOLERANCE * span:
            return None
        relative = points - points[0]
        area = abs(float(np.sum(np.cross(relative, np.roll(relative, -1, axis=0)), axis=0) @ normal)) / 2.0
        if area <= 1e-12:
            return None
        edges = np.roll(points, -1, axis=0) - points
        turns = np.cross(edges, np.roll(edges, -1, axis=0)) @ normal
        convex = bool(np.all(turns >= -1e-12) or np.all(turns <= 1e-12))
        directions = []
        for spec in record['specs']:
            direction = np.asarray(spec['direction'], dtype=np.float64)
            if direction.shape != (3,) or not np.isfinite(direction).all():
                return None
            directions.append(direction)
        signature = (record['signature'], record['section_key'], bool(record['selected']))
        hash(signature)
        return {'points': points, 'node_ids': node_ids, 'normal': normal,
                'span': span, 'area': area, 'convex': convex, 'directions': directions,
                'signature': signature}
    except (KeyError, TypeError, ValueError, IndexError, OverflowError):
        return None

def _edges(geometry):
    ids = geometry['node_ids']
    for index, node_id in enumerate(ids):
        following = ids[(index + 1) % len(ids)]
        yield frozenset((node_id, following)), index

def _matches_reference(reference, candidate):
    if reference['signature'] != candidate['signature']:
        return False
    if not np.allclose(reference['normal'], candidate['normal'], rtol=0.0,
                       atol=_DIRECTION_TOLERANCE):
        return False
    tolerance = _PLANE_TOLERANCE * max(reference['span'], candidate['span'])
    distances = (candidate['points'] - reference['points'][0]) @ reference['normal']
    if np.max(np.abs(distances)) > tolerance:
        return False
    if len(reference['directions']) != len(candidate['directions']):
        return False
    return all(np.allclose(a, b, rtol=0.0, atol=_DIRECTION_TOLERANCE)
               for a, b in zip(reference['directions'], candidate['directions']))

def build_area_load_regions(records):
    """Group full-edge-connected matching faces, leaving each assignment intact.

Every candidate is checked against the first face's plane and directions, so
small successive bends cannot accumulate into one incorrectly merged region.
Malformed geometry and nonmanifold connections are handled conservatively.
"""
    records = list(records)
    geometries = [_geometry(record) for record in records]
    edge_owners = defaultdict(list)
    for index, geometry in enumerate(geometries):
        if geometry is not None:
            for edge, _ in _edges(geometry):
                edge_owners[edge].append(index)
    adjacency = defaultdict(list)
    for owners in edge_owners.values():
        if len(owners) == 2:
            a, b = owners
            adjacency[a].append(b)
            adjacency[b].append(a)
    visited = set()
    regions = []
    for seed, record in enumerate(records):
        if seed in visited:
            continue
        visited.add(seed)
        region = [record]
        reference = geometries[seed]
        if reference is not None:
            pending = deque([seed])
            while pending:
                current = pending.popleft()
                for neighbor in adjacency[current]:
                    if neighbor in visited:
                        continue
                    candidate = geometries[neighbor]
                    if candidate is not None and _matches_reference(reference, candidate):
                        visited.add(neighbor)
                        region.append(records[neighbor])
                        pending.append(neighbor)
        regions.append(region)
    return regions

def _inside_face(point, geometry):
    """Point-in-polygon test in the face plane, including its boundary."""
    if geometry['convex']:
        points = geometry['points']
        edges = np.roll(points, -1, axis=0) - points
        crosses = np.cross(edges, np.asarray(point) - points) @ geometry['normal']
        tolerance = 1e-10 * geometry['span'] ** 2
        return bool(np.all(crosses >= -tolerance) or np.all(crosses <= tolerance))
    drop_axis = int(np.argmax(np.abs(geometry['normal'])))
    axes = [axis for axis in range(3) if axis != drop_axis]
    polygon = geometry['points'][:, axes]
    p = np.asarray(point, dtype=np.float64)[axes]
    tolerance = 1e-10 * geometry['span']
    inside = False
    for a, b in zip(polygon, np.roll(polygon, -1, axis=0)):
        edge = b - a
        length_squared = float(edge @ edge)
        if length_squared > 0:
            fraction = float((p - a) @ edge) / length_squared
            if 0.0 <= fraction <= 1.0 and np.linalg.norm(p - a - fraction * edge) <= tolerance:
                return True
        if (a[1] > p[1]) != (b[1] > p[1]):
            intersection = a[0] + (p[1] - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
            if p[0] < intersection:
                inside = not inside
    return inside

def _face_center(record, geometry):
    try:
        center = np.asarray(record['centroid'], dtype=np.float64)
        if center.shape == (3,) and np.isfinite(center).all() and _inside_face(center, geometry):
            return center
    except (KeyError, TypeError, ValueError):
        pass
    points = geometry['points']
    center = points.mean(axis=0)
    if _inside_face(center, geometry):
        return center
                                                                              
    for index in range(len(points)):
        candidate = (points[index - 1] + points[index] + points[(index + 1) % len(points)]) / 3.0
        if _inside_face(candidate, geometry):
            return candidate
    return points[0].copy()

def _anchor_from_valid(valid):
    centers = np.array([_face_center(record, geometry) for record, geometry in valid])
    weights = np.array([geometry['area'] for _, geometry in valid])
    center = np.average(centers, axis=0, weights=weights)
    return valid[int(np.argmin(np.sum((centers - center) ** 2, axis=1)))][0]

def choose_region_anchor(region, prepared=None):
    """Return an actual face near the area-weighted center, including holed regions.

    For a safe label coordinate on a concave face, use the prepared snapshot's
    ``anchor_point`` rather than assuming this record's raw centroid is inside.
    """
    if prepared is not None:
        return prepared['anchor_record']
    region = list(region)
    if not region:
        return None
    valid = [(record, geometry) for record in region
             if (geometry := _geometry(record)) is not None]
    return _anchor_from_valid(valid) if valid else region[0]

def _boundary_from_valid(valid):
    edge_points = defaultdict(list)
    for _, geometry in valid:
        points = geometry['points']
        for edge, index in _edges(geometry):
            edge_points[edge].append((points[index], points[(index + 1) % len(points)]))
    return [(pairs[0][0].copy(), pairs[0][1].copy())
            for pairs in edge_points.values() if len(pairs) == 1]

def region_boundary_edges(region, prepared=None):
    """Return original outer/hole edges; interior division edges are omitted."""
    if prepared is not None:
        return prepared['boundary_edges']
    valid = [(record, geometry) for record in region
             if (geometry := _geometry(record)) is not None]
    return _boundary_from_valid(valid)

def _face_candidates(record, geometry):
    center = _face_center(record, geometry)
    yield center
    points = geometry['points']
    if len(points) == 4:
        candidates = [(points[index] + points[(index + 1) % 4] + 2.0 * center) / 4.0
                      for index in range(4)]
    else:
        step = max(1, len(points) // 4)
        candidates = [0.55 * (points[index] + points[(index + 1) % len(points)]) / 2.0 + 0.45 * center
                      for index in range(0, len(points), step)]
    for candidate in candidates:
        if geometry['convex'] or _inside_face(candidate, geometry):
            yield candidate

def _project_point(project, point):
    try:
        projected = project(point)
        if projected is None:
            return None
        projected = np.asarray(projected, dtype=np.float64).ravel()
        if len(projected) < 2 or not np.isfinite(projected[:2]).all():
            return None
        return projected[:2]
    except (TypeError, ValueError, IndexError, OverflowError):
        return None

def prepare_area_load_region(region):
    """Prepare an immutable-by-convention geometry snapshot for camera updates.

    Rebuild the snapshot after assignments or geometry change. Original records
    are retained for ownership, while candidate coordinates and boundaries are
    copied. ``anchor_point`` is inside a real loaded face, including concave
    faces where the stored vertex centroid can lie outside the polygon.
    """
    region = list(region)
    valid = [(record, geometry) for record in region
             if (geometry := _geometry(record)) is not None]
    if not valid:
        return {'valid_geometry': [], 'anchor_record': region[0] if region else None,
                'anchor_point': None, 'boundary_edges': [], 'candidate_records': (),
                'candidate_points': np.empty((0, 3), dtype=np.float64),
                'bounding_box': None, 'bounding_extent': 0.0}
    anchor = _anchor_from_valid(valid)
    anchor_geometry = next(geometry for record, geometry in valid if record is anchor)
    anchor_point = _face_center(anchor, anchor_geometry).copy()
    candidate_records = [anchor]
    candidate_points = [anchor_point]
    for record, geometry in valid:
        for index, point in enumerate(_face_candidates(record, geometry)):
            if record is anchor and index == 0:
                continue
            candidate_records.append(record)
            candidate_points.append(point)
    all_points = np.concatenate([geometry['points'] for _, geometry in valid])
    lower = all_points.min(axis=0)
    upper = all_points.max(axis=0)
    middle = (lower + upper) / 2.0
    extent = float(np.max(np.linalg.norm(all_points - middle, axis=1)))
    return {'valid_geometry': valid, 'anchor_record': anchor, 'anchor_point': anchor_point,
            'boundary_edges': _boundary_from_valid(valid),
            'candidate_records': tuple(candidate_records),
            'candidate_points': np.asarray(candidate_points, dtype=np.float64).copy(),
            'bounding_box': (lower, upper), 'bounding_extent': extent}

def _project_candidates(project, points):
    batch = getattr(project, 'batch', None)
    if callable(batch):
        try:
            screens = np.asarray(batch(points), dtype=np.float64)
            if screens.ndim == 2 and screens.shape[0] == len(points) and screens.shape[1] >= 2:
                return screens[:, :2]
        except (TypeError, ValueError, IndexError, OverflowError):
            pass
    screens = np.full((len(points), 2), np.nan, dtype=np.float64)
    for index, point in enumerate(points):
        screen = _project_point(project, point)
        if screen is not None:
            screens[index] = screen
    return screens

def sample_region_arrows(region, project, spacing_px=55.0, prepared=None):
    """Choose interior arrow tips with minimum projected spacing within a region.

    Pass a prepared snapshot and a ``project.batch(points)`` method returning an
    Nx2/Nx3 array to avoid revalidating faces and projecting each candidate in
    Python. Invalid batch rows use NaN. The anchor face is prioritized, and
    separate regions are sampled independently so edited cells stay visible.
    Without a projector, at most five tips are spread over loaded faces.
    """
    if prepared is None:
        prepared = prepare_area_load_region(region)
    points = prepared['candidate_points']
    records = prepared['candidate_records']
    if not len(points):
        return []
    if project is None:
        distances = np.sum((points - points[0]) ** 2, axis=1)
        chosen = [0]
        for _ in range(min(4, len(points) - 1)):
            index = int(np.argmax(distances))
            if distances[index] <= 1e-20:
                break
            chosen.append(index)
            distances = np.minimum(distances, np.sum((points - points[index]) ** 2, axis=1))
        return [(records[index], points[index].copy()) for index in chosen]
    try:
        spacing = float(spacing_px)
    except (TypeError, ValueError, OverflowError):
        spacing = 55.0
    if not np.isfinite(spacing) or spacing <= 0:
        spacing = 55.0
    spacing = max(1.0, spacing)
    screens = _project_candidates(project, points)
                                                                             
    safe_coordinate = float(np.iinfo(np.int64).max) / 4.0 * spacing
    visible = np.isfinite(screens).all(axis=1) & (np.abs(screens) < safe_coordinate).all(axis=1)
    indices = np.flatnonzero(visible)
    if not len(indices):
        return []
    visible_screens = screens[indices]
    tiles = np.floor(visible_screens / spacing).astype(np.int64)
    distances = np.sum((visible_screens - (tiles + 0.5) * spacing) ** 2, axis=1)
    order = np.lexsort((indices, distances, tiles[:, 0], tiles[:, 1]))
    ordered_tiles = tiles[order]
    first = np.concatenate(([True], np.any(ordered_tiles[1:] != ordered_tiles[:-1], axis=1)))
    winners = indices[order[first]]
    kept = []
    occupied = defaultdict(list)
    minimum_squared = spacing * spacing

    def add(index):
        screen = screens[index]
        sx, sy = float(screen[0]), float(screen[1])
        tile = (math.floor(sx / spacing), math.floor(sy / spacing))
        for x in range(tile[0] - 1, tile[0] + 2):
            for y in range(tile[1] - 1, tile[1] + 2):
                for nx, ny in occupied.get((x, y), ()):
                    if (sx - nx) ** 2 + (sy - ny) ** 2 < minimum_squared - 1e-8:
                        return
        occupied[tile].append((sx, sy))
        kept.append((records[index], points[index].copy()))

    if visible[0]:
        add(0)
    for index in winners:
        add(int(index))
    return kept
