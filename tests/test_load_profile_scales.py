"""Curtain scale fusion preserves scalar glyph bounds and group independence."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT, ROOT / 'tests'):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from app.graphic.load_arrow_geometry import bounded_arrow_length
from app.graphic.load_view_geometry import LoadViewGeometry
from test_area_load_render import ORTHOGRAPHIC, perspective

def cache_for(profiles):
    canvas = SimpleNamespace(_pending_load_fill_verts=[], _pending_load_line_pos=[],
                             _pending_load_line_colors=[], load_labels=[])
    return LoadViewGeometry(canvas, [], [dict(scale_points=rows, fill_vertices=[],
        line_vertices=[]) for rows in profiles], [], 0)

def scalar_scales(profiles, matrix, width, height):
    results = []
    for rows in profiles:
        factor = 1.
        for tip, direction, nominal, maximum in rows:
            clip = matrix @ np.r_[tip, 1.]
            if (not np.isfinite(clip).all() or clip[3] <= 1e-12
                    or abs(clip[2]) > clip[3] or not nominal > 1e-12):
                continue
            length = bounded_arrow_length(tip, direction, nominal, matrix,
                width, height, max_pixels=maximum, min_pixels=0.)
            factor = min(factor, length / nominal)
        results.append(factor)
    return np.array(results)

class LoadProfileScaleTests(unittest.TestCase):
    def assert_scalar_parity(self, profiles, matrices, sizes=((800, 600),)):
        cache = cache_for(profiles)
        for matrix in matrices:
            for width, height in sizes:
                with self.subTest(matrix=matrix, size=(width, height)), np.errstate(invalid='ignore'):
                    expected = scalar_scales(profiles, matrix, width, height)
                    result = cache.profile_scales(matrix, width, height)
                    np.testing.assert_allclose(result, expected, atol=1e-12, rtol=1e-11)

    def test_random_camera_bounds_and_empty_groups_match_scalar(self):
        rng = np.random.default_rng(382)
        profiles = []
        for index in range(90):
            rows = []
            for _ in range(index % 7):
                direction = rng.normal(size=3)
                direction /= np.linalg.norm(direction)
                rows.append((rng.uniform(-6., 6., 3), direction,
                             rng.uniform(.001, 30.), rng.uniform(6., 60.)))
            profiles.append(rows)
        self.assert_scalar_parity(profiles,
            (ORTHOGRAPHIC, perspective(), perspective() * 100.),
            sizes=((800, 600), (1365, 650), (480, 900), (0, 600)))

    def test_depth_boundary_and_nominal_tail_clipping_match_scalar(self):
        eye = np.array([9., -11., 9.])
        towards_eye = eye / np.linalg.norm(eye)
        tips = (np.zeros(3), eye * 1.1, eye * .999, -eye * 20.)
        profiles = [[(tip, direction, nominal, maximum)]
            for tip in tips for direction in (towards_eye, -towards_eye, [0., 0., -1.])
            for nominal in (.001, 10., 100.) for maximum in (6., 33.)]
                                                                           
        profiles += [[(np.array([0., 0., z]), np.array([0., 0., -1.]), 3., 33.)]
                    for z in (-20., 20., -20.01, 20.01)]
        self.assert_scalar_parity(profiles, (ORTHOGRAPHIC, perspective()))

    def test_invalid_references_do_not_change_other_profiles(self):
        rows = [(np.zeros(3), np.array([0., 0., -1.]), 3., 33.),
                (np.array([np.nan, 0., 0.]), np.array([0., 0., -1.]), 3., 33.),
                (np.zeros(3), np.array([np.inf, 0., -1.]), 3., 33.)]
        profiles = [[row] for row in rows]
        profiles += [[(np.zeros(3), np.array([0., 0., -1.]), nominal, 33.)]
                    for nominal in (0., -1., np.nan, np.inf, 1e-13)]
        self.assert_scalar_parity(profiles, (ORTHOGRAPHIC, perspective()),
                                  sizes=((800, 600), (800, 0)))

    def test_no_references_keeps_all_profile_coefficients_at_one(self):
        cache = cache_for([[], [], []])
        np.testing.assert_array_equal(cache.profile_scales(perspective(), 800, 600), np.ones(3))

if __name__ == '__main__':
    unittest.main()
