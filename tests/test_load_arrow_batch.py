"""Batched cached glyph sizing preserves the established projection contract."""
from pathlib import Path
import sys
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT, ROOT / 'tests'):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from app.graphic.load_arrow_geometry import bounded_arrow_length, bounded_arrow_lengths
from test_area_load_render import ORTHOGRAPHIC, perspective

class LoadArrowBatchTests(unittest.TestCase):
    def assert_scalar_parity(self, tips, directions, nominal, matrix,
                             width=800, height=600, max_pixels=33., min_pixels=24.):
        count = len(tips)
        maximum = np.broadcast_to(max_pixels, (count,))
        minimum = np.broadcast_to(min_pixels, (count,))
        nominal = np.broadcast_to(nominal, (count,))
        expected = [bounded_arrow_length(tip, direction, value, matrix, width, height,
                                         max_pixels=high, min_pixels=low)
                    for tip, direction, value, high, low in
                    zip(tips, directions, nominal, maximum, minimum)]
        result = bounded_arrow_lengths(tips, directions, nominal, matrix, width, height,
                                       max_pixels=max_pixels, min_pixels=min_pixels)
        np.testing.assert_allclose(result, expected, atol=1e-12, rtol=1e-11)
        return result

    def test_random_perspective_and_orthographic_camera_parity(self):
        rng = np.random.default_rng(421)
        tips = rng.uniform(-5., 5., (400, 3))
        directions = rng.normal(size=(400, 3))
        directions /= np.linalg.norm(directions, axis=1)[:, None]
        nominal = rng.uniform(.001, 50., 400)
        for matrix in (ORTHOGRAPHIC, perspective(), perspective() * 10.):
            for width, height in ((800, 600), (1365, 650), (480, 900)):
                for maximum, minimum in ((33., 24.), (6., 0.)):
                    with self.subTest(matrix=matrix, size=(width, height), maximum=maximum):
                        self.assert_scalar_parity(tips, directions, nominal, matrix, width, height,
                                                  max_pixels=maximum, min_pixels=minimum)

    def test_mixed_shaft_and_wing_bounds_share_a_batch(self):
        rng = np.random.default_rng(38)
        tips = rng.uniform(-4., 4., (90, 3))
        directions = rng.normal(size=(90, 3))
        directions /= np.linalg.norm(directions, axis=1)[:, None]
        maximum = np.tile([33., 6., 6.], 30)
        minimum = np.tile([24., 0., 0.], 30)
        self.assert_scalar_parity(tips, directions, np.linspace(.01, 30., 90), perspective(),
                                  max_pixels=maximum, min_pixels=minimum)

    def test_bad_row_does_not_corrupt_other_glyphs(self):
        tips = np.array([[0., 0., 0.], [np.nan, 0., 0.], [0., 0., 0.],
                         [0., 0., 0.], [0., 0., 0.], [0., 0., 0.]])
        directions = np.tile([0., 0., -1.], (6, 1))
        directions[2, 0] = np.inf
        nominal = np.array([3., 3., 3., np.nan, -3., 0.])
        with np.errstate(invalid='ignore'):
            result = self.assert_scalar_parity(tips, directions, nominal, ORTHOGRAPHIC)
        self.assertGreater(result[0], 0.)
        np.testing.assert_array_equal(result[1:], np.zeros(5))

    def test_camera_depth_clipping_and_view_parallel_directions(self):
        eye = np.array([9., -11., 9.])
        view_direction = -eye / np.linalg.norm(eye)
        tips = np.array([np.zeros(3), eye * 1.1, eye * .999, -eye * 20., np.zeros(3)])
        directions = np.array([view_direction, [0., 0., -1.], [0., 0., -1.],
                               [0., 0., -1.], view_direction + [.15, 0., 0.]])
        directions /= np.linalg.norm(directions, axis=1)[:, None]
        result = self.assert_scalar_parity(tips, directions, [.25, 10., 10., 10., 100.], perspective())
        self.assertLessEqual(result[0], .25)
        np.testing.assert_array_equal(result[1:4], np.zeros(3))
        self.assertGreater(result[4], 0.)
        self.assertLess(result[4], 100.)

    def test_empty_batch_and_unavailable_view(self):
        np.testing.assert_array_equal(bounded_arrow_lengths([], [], [], perspective(), 800, 600), [])
        tips = np.zeros((3, 3))
        directions = np.tile([0., 0., -1.], (3, 1))
        for matrix, width, height in ((None, 800, 600), (perspective(), 0, 600),
                                      (perspective(), 800, 0)):
            result = self.assert_scalar_parity(tips, directions, [3., -.5, np.inf], matrix,
                                               width=width, height=height)
            np.testing.assert_array_equal(result, [3., 0., 0.])

if __name__ == '__main__':
    unittest.main()
