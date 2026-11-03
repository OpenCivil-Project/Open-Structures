"""Load glyphs stay bounded through clipping and active camera navigation."""
import copy
from pathlib import Path
import sys
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT, ROOT / 'tests'):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from test_area_load_render import FakeCanvas, ORTHOGRAPHIC, QApplication, mesh, perspective
from test_frame_load_render import FrameCanvas, frame_model, redraw
from app.graphic.load_arrow_geometry import bounded_arrow_length

def screen(point, matrix):
    """Measure projected size without discarding offscreen endpoints."""
    clip = matrix @ np.r_[point, 1.]
    if not np.isfinite(clip).all() or clip[3] <= 0.:
        return None
    return np.array([(clip[0] / clip[3] + 1.) * 400.,
                     (1. - clip[1] / clip[3]) * 300.])

def arrow_glyphs(canvas):
    """Identify actual shaft and two wing segments among overlay boundaries."""
    points = np.asarray(canvas._pending_load_line_pos, dtype=float)
    pairs = points.reshape(-1, 2, 3)
    glyphs = []
    index = 0
    while index + 2 < len(pairs):
        shaft, first_wing, second_wing = pairs[index:index + 3]
        if (np.allclose(shaft[1], first_wing[0], atol=1.e-12, rtol=0.)
                and np.allclose(shaft[1], second_wing[0], atol=1.e-12, rtol=0.)
                and not np.allclose(shaft[0], shaft[1], atol=1.e-12, rtol=0.)):
            glyphs.append(np.array([shaft[0], shaft[1], first_wing[1], second_wing[1]]))
            index += 3
        else:
            index += 1
    return glyphs

class LoadArrowSizingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def assert_glyph_bounds(self, glyphs, matrix, max_pixels=33.):
        self.assertGreater(len(glyphs), 0)
        for glyph in glyphs:
            projected = [screen(point, matrix) for point in glyph]
            self.assertTrue(all(point is not None for point in projected))
            tip = projected[1]
            for endpoint in (projected[0], projected[2], projected[3]):
                self.assertLessEqual(np.linalg.norm(endpoint - tip), max_pixels + 1.e-5)

    def test_offscreen_nominal_tail_still_receives_length_limit(self):
        tip = np.zeros(3)
        direction = np.array([0., 0., -1.])
        for zoom in (1., 2., 3., 5., 10., 40.):
            with self.subTest(zoom=zoom):
                matrix = ORTHOGRAPHIC.copy()
                matrix[:2] *= zoom
                length = bounded_arrow_length(tip, direction, 3., matrix, 800, 600)
                self.assertTrue(np.isfinite(length))
                self.assertGreater(length, 0.)
                pixels = np.linalg.norm(screen(tip, matrix) - screen(tip - direction * length, matrix))
                self.assertLessEqual(pixels, 33. + 1.e-6)

    def test_small_visible_exception_keeps_identifiable_length(self):
        tip = np.zeros(3)
        direction = np.array([0., 0., -1.])
        length = bounded_arrow_length(tip, direction, .01, ORTHOGRAPHIC, 800, 600)
        pixels = np.linalg.norm(screen(tip, ORTHOGRAPHIC) -
                                screen(tip - direction * length, ORTHOGRAPHIC))
        self.assertGreaterEqual(pixels, 24. - 1.e-6)
        self.assertLessEqual(pixels, 33. + 1.e-6)

    def test_perspective_limit_is_measured_at_each_tip_depth(self):
        matrix = perspective()
        direction = np.array([0., 0., -1.])
        lengths = []
        for tip in (np.array([0., -3., 0.]), np.zeros(3), np.array([0., 3., 0.])):
            with self.subTest(tip=tip):
                length = bounded_arrow_length(tip, direction, 20., matrix, 800, 600)
                lengths.append(length)
                tail = tip - direction * length
                self.assertIsNotNone(screen(tail, matrix))
                self.assertLessEqual(np.linalg.norm(screen(tip, matrix) - screen(tail, matrix)),
                                     33. + 1.e-6)
        self.assertGreater(np.ptp(lengths), .01)

    def test_nominal_tail_crossing_camera_is_shortened_before_projection(self):
        matrix = perspective()
        eye = np.array([9., -11., 9.])
        direction = -eye / np.linalg.norm(eye) + np.array([.15, 0., 0.])
        direction /= np.linalg.norm(direction)
        tip = np.zeros(3)
        length = bounded_arrow_length(tip, direction, 100., matrix, 800, 600)
        tail = tip - direction * length
        clip = matrix @ np.r_[tail, 1.]
        self.assertGreater(length, 0.)
        self.assertLess(length, 100.)
        self.assertGreater(clip[3], 0.)
        self.assertLessEqual(abs(clip[2]), clip[3] + 1.e-7)
        self.assertLessEqual(np.linalg.norm(screen(tip, matrix) - screen(tail, matrix)),
                             33. + 1.e-5)

    def test_view_parallel_direction_does_not_expand_to_force_minimum(self):
        matrix = perspective()
        eye = np.array([9., -11., 9.])
        direction = -eye / np.linalg.norm(eye)
        length = bounded_arrow_length(np.zeros(3), direction, .25, matrix, 800, 600)
        self.assertTrue(np.isfinite(length))
        self.assertGreaterEqual(length, 0.)
        self.assertLessEqual(length, .25 + 1.e-8)

    def test_actual_area_glyphs_remain_bounded_at_high_zoom(self):
        model = mesh(1)
        model.loads[0].uniform_load = 5000.
        before = copy.deepcopy(vars(model.loads[0]))
        for zoom in (1., 2., 3., 5., 10.):
            with self.subTest(zoom=zoom):
                matrix = ORTHOGRAPHIC.copy()
                matrix[:2] *= zoom
                canvas = FakeCanvas(model, matrix)
                canvas._draw_area_loads(model)
                self.assert_glyph_bounds(arrow_glyphs(canvas), matrix)
                self.assertEqual(vars(model.loads[0]), before)

    def test_actual_area_glyphs_are_bounded_across_perspective_depths(self):
        model = mesh(4)
        for load in model.loads:
            load.uniform_load = 5000.
        matrix = perspective()
        canvas = FakeCanvas(model, matrix)
        canvas._draw_area_loads(model)
        glyphs = arrow_glyphs(canvas)
        self.assertEqual(len(glyphs), 5)
        self.assert_glyph_bounds(glyphs, matrix)

    def test_view_parallel_area_arrowheads_cannot_expand_across_screen(self):
        near, far = .1, 100.
        factor = 1. / np.tan(np.radians(45.) / 2.)
        projection = np.array([[factor * .75, 0., 0., 0.],
                               [0., factor, 0., 0.],
                               [0., 0., (far + near) / (near - far),
                                2. * far * near / (near - far)],
                               [0., 0., -1., 0.]])
        view = np.eye(4)
        view[2, 3] = -4.
        matrix = projection @ view
        model = mesh(1)
        model.loads[0].uniform_load = 5000.
        canvas = FakeCanvas(model, matrix)
        canvas._draw_area_loads(model)
        self.assert_glyph_bounds(arrow_glyphs(canvas), matrix)

    def test_active_zoom_and_pan_resize_glyphs_without_relocating_tips_or_labels(self):
        model = mesh(1)
        model.elements = {}
        canvas = FrameCanvas(model)
        redraw(canvas, include_area=True)
        original_tips = np.array([glyph[1] for glyph in arrow_glyphs(canvas)])
        original_labels = copy.deepcopy(canvas.load_labels)
        for navigating in ('_is_zooming', '_mouse_pressed'):
            with self.subTest(navigating=navigating):
                setattr(canvas, navigating, True)
                matrix = ORTHOGRAPHIC.copy()
                matrix[:2] *= 1.6
                matrix[0, 3] += .05 if navigating == '_mouse_pressed' else 0.
                canvas._distributed_load_view_time = 0.
                canvas._refresh_distributed_load_view(matrix, 800, 600)
                glyphs = arrow_glyphs(canvas)
                np.testing.assert_allclose([glyph[1] for glyph in glyphs], original_tips,
                                           atol=1.e-12, rtol=0.)
                self.assertEqual(canvas.load_labels, original_labels)
                self.assert_glyph_bounds(glyphs, matrix)
                setattr(canvas, navigating, False)

    def test_frame_glyphs_stay_bounded_after_shell_or_manual_division(self):
        for shell_split in (False, True):
            with self.subTest(shell_split=shell_split):
                model = frame_model(shell_split=shell_split)
                matrix = ORTHOGRAPHIC.copy()
                matrix[:2] *= 10.
                canvas = FrameCanvas(model, matrix)
                redraw(canvas)
                self.assert_glyph_bounds(arrow_glyphs(canvas), matrix)
                self.assertEqual(len(canvas.load_labels), 1)

    def test_frame_navigation_keeps_samples_and_labels_while_limiting_glyph_size(self):
        model = frame_model()
        canvas = FrameCanvas(model)
        redraw(canvas, include_area=True)
        original_tips = np.array([glyph[1] for glyph in arrow_glyphs(canvas)])
        original_labels = copy.deepcopy(canvas.load_labels)
        original_samples = [list(samples) for samples in canvas._frame_load_view_samples]
        canvas._is_zooming = True
        matrix = ORTHOGRAPHIC.copy()
        matrix[:2] *= 1.6
        canvas._distributed_load_view_time = 0.
        canvas._refresh_distributed_load_view(matrix, 800, 600)
        glyphs = arrow_glyphs(canvas)
        project, _, _, _ = canvas._area_load_projection(matrix, 800, 600)
        visible_original_tips = [tip for tip in original_tips if project(tip) is not None]
        np.testing.assert_allclose([glyph[1] for glyph in glyphs], visible_original_tips,
                                   atol=1.e-12, rtol=0.)
        self.assertEqual(len(canvas._frame_load_view_samples), len(original_samples))
        for previous, current in zip(original_samples, canvas._frame_load_view_samples):
            self.assertEqual(len(current), len(previous))
            for (previous_record, previous_t), (current_record, current_t) in zip(previous, current):
                self.assertIs(current_record, previous_record)
                self.assertEqual(current_t, previous_t)
        self.assertEqual(canvas.load_labels, original_labels)
        self.assert_glyph_bounds(glyphs, matrix)

if __name__ == '__main__':
    unittest.main()
