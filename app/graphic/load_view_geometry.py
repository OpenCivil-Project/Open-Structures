"""Cached load topology with batched, camera-only coordinate updates."""
import numpy as np

from .load_arrow_geometry import bounded_arrow_lengths, project_vectors

def visible_points(points, mvp):
    points = np.asarray(points, dtype=float).reshape(-1, 3)
    clip = project_vectors(points, mvp) + mvp[:, 3]
    return (np.isfinite(clip).all(axis=1) & (clip[:, 3] > 1e-12)
            & (np.abs(clip[:, :3]) <= clip[:, 3:4]).all(axis=1))

def depth_valid_points(points, mvp):
    """Curtain scale uses fixed references, regardless of viewport edges."""
    points = np.asarray(points, dtype=float).reshape(-1, 3)
    clip = project_vectors(points, mvp) + mvp[:, 3]
    return (np.isfinite(clip).all(axis=1) & (clip[:, 3] > 1e-12)
            & (np.abs(clip[:, 2]) <= clip[:, 3]))

def _profile_scale_factors(tips, directions, nominal, maximum, mvp, width, height):
    """Fuse depth testing and maximum-only sizing for fixed curtain references."""
    clip = project_vectors(tips, mvp) + mvp[:, 3]
    cw, cz = clip[:, 3], clip[:, 2]
    depth_valid = (np.isfinite(clip).all(axis=1) & (cw > 1e-12) & (np.abs(cz) <= cw))
    lengths = np.where(np.isfinite(nominal) & (nominal > 0), nominal, 0.)
    if width > 0 and height > 0:
        step = -project_vectors(directions, mvp)
        sw, sz = step[:, 3], step[:, 2]
        near, far = cw + cz, cw - cz
        valid = (depth_valid & (near > 0) & (far > 0)
                 & np.isfinite(step).all(axis=1) & (lengths > 0))
                                                                            
        limit = np.full(len(tips), np.inf)
        plane_limit = np.empty(len(tips))
        with np.errstate(divide='ignore', invalid='ignore', over='ignore'):
            for value, derivative in ((near, sw + sz), (far, sw - sz), (cw, sw)):
                plane_limit.fill(np.inf)
                np.divide(value, -derivative, out=plane_limit, where=derivative < 0)
                plane_limit *= .999
                np.minimum(limit, plane_limit, out=limit)
            lengths = np.minimum(lengths, limit)
            dx = (step[:, 0] - clip[:, 0] / cw * sw) * (width / 2.)
            dy = (step[:, 1] - clip[:, 1] / cw * sw) * (height / 2.)
            projected_step = np.sqrt(dx * dx + dy * dy)
            pixels = lengths * projected_step / (cw + lengths * sw)
            target = np.minimum(maximum, np.maximum(0., pixels))
            denominator = projected_step - target * sw
            resize = valid & (projected_step > 1e-12) & (denominator > 1e-12)
            lengths = np.where(resize, np.minimum(target * cw / denominator, limit), lengths)
        lengths[~valid] = 0.
    factors = np.ones(len(tips))
    np.divide(lengths, nominal, out=factors, where=depth_valid & (nominal > 1e-12))
    return factors

class LoadViewGeometry:
    def __init__(self, canvas, arrows, profiles, leaders, label_start):
        self.fill_positions = np.asarray(canvas._pending_load_fill_verts, dtype=float).reshape(-1, 3).copy()
        self.line_positions = np.asarray(canvas._pending_load_line_pos, dtype=float).reshape(-1, 3).copy()
        self.line_colors = np.asarray(canvas._pending_load_line_colors, dtype=float).reshape(-1, 4).copy()
        self.original_colors = self.line_colors.copy()
        self.labels = list(canvas.load_labels)
        self.label_start = label_start
        self.label_anchors = np.asarray([item.get('leader_anchor', item['pos_3d']) for item in self.labels[label_start:]],
                                       dtype=float).reshape(-1, 3)
        profile_ids = {id(profile): index for index, profile in enumerate(profiles)}
        self.profile_count = len(profiles)
        scale_rows, fill_rows, line_rows = [], [], []
        for index, profile in enumerate(profiles):
            scale_rows.extend((index, *row) for row in profile['scale_points'])
            fill_rows.extend((index, *row) for row in profile['fill_vertices'])
            line_rows.extend((index, *row) for row in profile['line_vertices'])
        self.scale_groups = np.asarray([row[0] for row in scale_rows], dtype=int)
        self.scale_starts = (np.r_[0, np.flatnonzero(np.diff(self.scale_groups)) + 1]
                             if len(self.scale_groups) else np.empty(0, dtype=int))
        self.scale_profile_ids = self.scale_groups[self.scale_starts]
        self.scale_tips = np.asarray([row[1] for row in scale_rows], dtype=float).reshape(-1, 3)
        self.scale_directions = np.asarray([row[2] for row in scale_rows], dtype=float).reshape(-1, 3)
        self.scale_nominal = np.asarray([row[3] for row in scale_rows], dtype=float)
        self.scale_max = np.asarray([row[4] for row in scale_rows], dtype=float)
        self.moving_fill = self._moving_rows(fill_rows)
        self.moving_lines = self._moving_rows(line_rows)
        self.arrow_indices = np.asarray([item['index'] for item in arrows], dtype=int)
        self.tips = np.asarray([item['tip'] for item in arrows], dtype=float).reshape(-1, 3)
        self.directions = np.asarray([item['direction'] for item in arrows], dtype=float).reshape(-1, 3)
        self.sides = np.asarray([item['side'] for item in arrows], dtype=float).reshape(-1, 3)
        self.nominal = np.asarray([item['nominal'] for item in arrows], dtype=float)
        self.maximum = np.asarray([item['maximum'] for item in arrows], dtype=float)
        self.minimum = np.asarray([item['minimum'] for item in arrows], dtype=float)
        self.heads = np.asarray([item['head'] for item in arrows], dtype=float)
        self.wings = np.asarray([item['wing'] for item in arrows], dtype=float)
        self.arrow_groups = np.asarray([profile_ids.get(id(item.get('profile')), -1) for item in arrows], dtype=int)
        self.leader_indices = np.asarray([item[0] for item in leaders], dtype=int)
        self.leader_anchors = np.asarray([item[1] for item in leaders], dtype=float).reshape(-1, 3)

    @staticmethod
    def _moving_rows(rows):
        return (np.asarray([row[0] for row in rows], dtype=int),
                np.asarray([row[1] for row in rows], dtype=int),
                np.asarray([row[2] for row in rows], dtype=float).reshape(-1, 3),
                np.asarray([row[3] for row in rows], dtype=float).reshape(-1, 3))

    def profile_scales(self, mvp, width, height):
        """Only the small continuous-curtain coefficient table depends on CPU projection."""
        mvp = np.asarray(mvp, dtype=float)
        scales = np.ones(self.profile_count)
        if len(self.scale_groups):
            factors = _profile_scale_factors(self.scale_tips, self.scale_directions,
                self.scale_nominal, self.scale_max, mvp, width, height)
            scales[self.scale_profile_ids] = np.minimum(1., np.minimum.reduceat(factors, self.scale_starts))
        return scales

    def update(self, mvp, width, height):
        mvp = np.asarray(mvp, dtype=float)
        scales = self.profile_scales(mvp, width, height)
        for target, rows in ((self.fill_positions, self.moving_fill),
                             (self.line_positions, self.moving_lines)):
            groups, indices, bases, offsets = rows
            target[indices] = bases + offsets * scales[groups, None]
        self.line_colors[:] = self.original_colors
        if len(self.arrow_indices):
            nominal = self.nominal.copy()
            grouped = self.arrow_groups >= 0
            nominal[grouped] *= scales[self.arrow_groups[grouped]]
            lengths = bounded_arrow_lengths(self.tips, self.directions, nominal, mvp,
                                           width, height, self.maximum, self.minimum)
            visible = visible_points(self.tips, mvp)
            lengths[~visible] = 0.
            base = self.tips - self.directions * (lengths * self.heads)[:, None]
            tails = self.tips - self.directions * lengths[:, None]
            index = self.arrow_indices
            self.line_positions[index] = tails
            self.line_positions[index + 1] = self.tips
            self.line_colors[index, 3] *= visible
            self.line_colors[index + 1, 3] *= visible
            headed = self.heads > 0
            if headed.any():
                rows = np.flatnonzero(headed)
                wing_nominal = lengths[rows] * self.heads[rows] * self.wings[rows]
                plus = bounded_arrow_lengths(base[rows], -self.sides[rows], wing_nominal,
                                             mvp, width, height, 6., 0.)
                minus = bounded_arrow_lengths(base[rows], self.sides[rows], wing_nominal,
                                              mvp, width, height, 6., 0.)
                start = index[rows]
                self.line_positions[start + 2] = self.tips[rows]
                self.line_positions[start + 3] = base[rows] + self.sides[rows] * plus[:, None]
                self.line_positions[start + 4] = self.tips[rows]
                self.line_positions[start + 5] = base[rows] - self.sides[rows] * minus[:, None]
                for offset in (2, 3, 4, 5):
                    self.line_colors[start + offset, 3] *= visible[rows]
        if len(self.leader_indices):
            visible = visible_points(self.leader_anchors, mvp)
            self.line_colors[self.leader_indices, 3] *= visible
            self.line_colors[self.leader_indices + 1, 3] *= visible
        return self.labels
