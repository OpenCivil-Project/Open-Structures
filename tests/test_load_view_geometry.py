"""Camera updates reuse load topology and retain divided-load meaning."""
import ast
import copy
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT, ROOT / 'tests'):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from test_area_load_render import QApplication, ORTHOGRAPHIC, label
from test_frame_load_render import (FrameCanvas, assignment_snapshot, frame_model,
                                    ordered_loads)
from app.graphic.load_label_layout import label_screen_bounds
from app.graphic.load_view_geometry import visible_points

BUFFERS = ('_pending_load_fill_verts', '_pending_load_fill_colors',
           '_pending_load_fill_faces', '_pending_load_line_pos',
           '_pending_load_line_colors')

tree = ast.parse((ROOT / 'app/canvas.py').read_text(encoding='utf-8-sig'))
owner = next(node for node in tree.body if isinstance(node, ast.ClassDef)
             and node.name == 'MCanvas3D')
upload = next(node for node in owner.body if isinstance(node, ast.FunctionDef)
              and node.name == '_upload_loads_to_vbo')
namespace = {'np': np}
exec(compile(ast.fix_missing_locations(ast.Module(body=[upload], type_ignores=[])),
             'actual load geometry upload', 'exec'), namespace)
actual_load_upload = namespace['_upload_loads_to_vbo']

def full_redraw(canvas):
                                                                         
    for name in BUFFERS:
        setattr(canvas, name, [])
    canvas.load_labels = []
    canvas._draw_member_loads(canvas.current_model)
    canvas._draw_area_loads(canvas.current_model)
    canvas._upload_loads_to_vbo()

class LoadViewGeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def canvas(self, model, prefix=False):
        canvas = FrameCanvas(model)
        canvas.vbo_manager.update_load_positions = Mock(return_value=True)
        if prefix:
            canvas._pending_load_fill_verts = [[9., -9., -2.], [10., -9., -2.], [9., -8., -2.]]
            canvas._pending_load_fill_colors = [[.2, .3, .4, .5]] * 3
            canvas._pending_load_fill_faces = [[0, 1, 2]]
            canvas._pending_load_line_pos = [[9., -9., -2.], [10., -8., -2.]]
            canvas._pending_load_line_colors = [[.2, .3, .4, .5]] * 2
            canvas.load_labels = [label(value=11., owner_type='node')]
        canvas._draw_member_loads(model)
        canvas._draw_area_loads(model)
        self.assertIsNotNone(canvas._load_view_geometry)
        canvas._render_area_load_regions = Mock(wraps=canvas._render_area_load_regions)
        canvas._render_frame_load_chains = Mock(wraps=canvas._render_frame_load_chains)
        canvas._fan_triangulate = Mock(wraps=canvas._fan_triangulate)
        canvas._upload_loads_to_vbo.reset_mock()
        canvas._upload_load_labels_to_gpu = Mock(wraps=canvas._upload_load_labels_to_gpu)
        self.addCleanup(self.stop_timer, canvas)
        return canvas

    @staticmethod
    def stop_timer(canvas):
        timer = getattr(canvas, '_distributed_load_view_timer', None)
        if timer is not None:
            timer.stop()

    def assert_fast_camera_path(self, canvas, count):
        self.assertEqual(canvas.vbo_manager.update_load_positions.call_count, count)
        canvas._upload_loads_to_vbo.assert_not_called()
        canvas._render_area_load_regions.assert_not_called()
        canvas._render_frame_load_chains.assert_not_called()
        canvas._fan_triangulate.assert_not_called()

    def test_zoom_and_pan_update_positions_without_rebuilding_topology(self):
        model = frame_model(shell_split=True)
        before = assignment_snapshot(model)
        canvas = self.canvas(model, prefix=True)
        cache = canvas._load_view_geometry
        array_ids = tuple(id(value) for value in (cache.fill_positions, cache.line_positions, cache.line_colors))
        static = {name: copy.deepcopy(getattr(canvas, name)) for name in
                  ('_pending_load_fill_colors', '_pending_load_fill_faces')}
        static_ids = {name: id(getattr(canvas, name)) for name in static}
        labels = copy.deepcopy(canvas.load_labels)
        fill_prefix = cache.fill_positions[:3].copy()
        line_prefix = cache.line_positions[:2].copy()
        colors = cache.line_colors.copy()
        samples = [(record, t) for chain in canvas._frame_load_view_samples for record, t in chain]
        for index, (flag, zoom, pan) in enumerate((('_is_zooming', 1.05, 0.),
                ('_mouse_pressed', 1.10, .03), ('_is_zooming', 1.15, -.03)), 1):
            canvas._is_zooming = flag == '_is_zooming'
            canvas._mouse_pressed = flag == '_mouse_pressed'
            matrix = ORTHOGRAPHIC.copy()
            matrix[:2] *= zoom
            matrix[0, 3] += pan
            canvas._refresh_distributed_load_view(matrix, 800, 600)
            self.assert_fast_camera_path(canvas, index)
            self.assertIs(canvas._load_view_geometry, cache)
            self.assertEqual(tuple(id(value) for value in (canvas._pending_load_fill_verts,
                canvas._pending_load_line_pos, canvas._pending_load_line_colors)), array_ids)
            for name, value in static.items():
                self.assertEqual(id(getattr(canvas, name)), static_ids[name])
                self.assertEqual(getattr(canvas, name), value)
            np.testing.assert_array_equal(cache.fill_positions[:3], fill_prefix)
            np.testing.assert_array_equal(cache.line_positions[:2], line_prefix)
            np.testing.assert_array_equal(cache.line_colors, colors)
            self.assertEqual(canvas.load_labels, labels)
            current = [(record, t) for chain in canvas._frame_load_view_samples for record, t in chain]
            self.assertEqual(len(current), len(samples))
            for (old_record, old_t), (record, t) in zip(samples, current):
                self.assertIs(record, old_record)
                self.assertEqual(t, old_t)
        canvas._upload_load_labels_to_gpu.assert_not_called()
        self.assertEqual(assignment_snapshot(model), before)

    def test_offscreen_label_registry_stays_fixed_while_geometry_is_clipped(self):
        canvas = self.canvas(frame_model(shell_split=True), prefix=True)
        cache = canvas._load_view_geometry
        labels = list(canvas.load_labels)
        originals = cache.line_colors.copy()
        canvas._mouse_pressed = True
        offscreen = ORTHOGRAPHIC.copy()
        offscreen[0, 3] = 3.
        canvas._refresh_distributed_load_view(offscreen, 800, 600)
        self.assertEqual(canvas.load_labels, labels)
        for annotation in labels[1:]:
            self.assertFalse(visible_points([annotation['leader_anchor']], offscreen)[0])
            bounds = label_screen_bounds(annotation, offscreen, 800, 600)
            if bounds is not None:
                self.assertTrue(bounds[2] < 0 or bounds[0] > 800 or
                                bounds[3] < 0 or bounds[1] > 600)
        self.assertTrue((cache.line_colors[cache.arrow_indices, 3] == 0.).all())
        np.testing.assert_array_equal(cache.line_colors[:2], originals[:2])
        self.assert_fast_camera_path(canvas, 1)
        canvas._refresh_distributed_load_view(ORTHOGRAPHIC, 800, 600)
        self.assertEqual(canvas.load_labels, labels)
        np.testing.assert_array_equal(cache.line_colors, originals)
        self.assert_fast_camera_path(canvas, 2)
        canvas._upload_load_labels_to_gpu.assert_not_called()
        self.assertIs(canvas._load_view_geometry, cache)

    def test_affine_profile_keeps_shared_endpoints_and_intensity_ratios_during_zoom(self):
        for shell_split in (False, True):
            with self.subTest(shell_split=shell_split):
                model = frame_model(shell_split=shell_split,
                    profile=([0., .25, .75, 1.], [-2., -4., -8., -10.]))
                canvas = self.canvas(model)
                canvas._is_zooming = True
                end = canvas._area_load_display_base['_pending_load_fill_verts']
                for zoom in (1.2, 1.8, 3.):
                    matrix = ORTHOGRAPHIC.copy()
                    matrix[:2] *= zoom
                    canvas._refresh_distributed_load_view(matrix, 800, 600)
                    vertices = canvas._pending_load_fill_verts[:end]
                    bases, tops = vertices[::2], vertices[1::2]
                    intensity = bases[:, 0] + 6.
                    ratios = np.linalg.norm(tops - bases, axis=1) / intensity
                    np.testing.assert_allclose(ratios, np.repeat(ratios[0], len(ratios)),
                                               rtol=1.e-12, atol=1.e-14)
                    for x in np.linspace(-3., 3., 7):
                        shared = tops[np.isclose(bases[:, 0], x)]
                        self.assertGreaterEqual(len(shared), 2)
                        np.testing.assert_allclose(shared, np.repeat(shared[:1], len(shared), axis=0),
                                                   rtol=1.e-12, atol=1.e-14)
                self.assert_fast_camera_path(canvas, 3)

    def test_selection_change_rebuilds_and_replaces_camera_cache(self):
        model = frame_model(shell_split=True)
        canvas = self.canvas(model)
        cache = canvas._load_view_geometry
        canvas._is_zooming = True
        matrix = ORTHOGRAPHIC.copy()
        matrix[0, 3] += .02
        canvas._refresh_distributed_load_view(matrix, 800, 600)
        self.assert_fast_camera_path(canvas, 1)
        canvas.selected_element_ids.remove(ordered_loads(model)[3].element_id)
        canvas.selected_area_ids.remove(list(model.area_elements)[3])
        canvas._refresh_distributed_load_view(matrix, 800, 600)
        canvas._upload_loads_to_vbo.assert_called_once()
        canvas._render_area_load_regions.assert_called_once()
        canvas._render_frame_load_chains.assert_called_once()
        self.assertGreater(canvas._fan_triangulate.call_count, 0)
        self.assertIsNot(canvas._load_view_geometry, cache)
        self.assertFalse(getattr(canvas, '_distributed_load_view_needs_settle', False))
        self.assertEqual(canvas.vbo_manager.update_load_positions.call_count, 1)

    def test_load_edit_regroups_the_real_divided_frames_on_full_redraw(self):
        model = frame_model(shell_split=True)
        canvas = self.canvas(model)
        original_cache = canvas._load_view_geometry
        ordered_loads(model)[3].wz = -7.
        before = assignment_snapshot(model)
        full_redraw(canvas)
        frames = [item for item in canvas.load_labels if item['owner_type'] == 'element']
        self.assertEqual(sorted(item['group_count'] for item in frames), [1, 3, 4])
        self.assertEqual({item['val'] for item in frames}, {5., 7.})
        self.assertIsNot(canvas._load_view_geometry, original_cache)
        self.assertEqual(assignment_snapshot(model), before)
        canvas._upload_loads_to_vbo.assert_called_once()
        canvas._render_frame_load_chains.assert_called_once()
        canvas._render_area_load_regions.assert_called_once()
        canvas.vbo_manager.update_load_positions.assert_not_called()

    def test_wheel_end_idle_and_resize_never_rebuild_sampling_or_text(self):
        canvas = self.canvas(frame_model(shell_split=True))
        cache = canvas._load_view_geometry
        labels = copy.deepcopy(canvas.load_labels)
        samples = [(record['element_id'], float(t)) for chain in canvas._frame_load_view_samples
                   for record, t in chain]
        canvas._is_zooming = True
        matrix = ORTHOGRAPHIC.copy()
        matrix[:2] *= 1.2
        canvas._refresh_distributed_load_view(matrix, 800, 600)
        self.assert_fast_camera_path(canvas, 1)
        canvas._is_zooming = False
        canvas._distributed_load_view_time = 0.
        canvas._refresh_distributed_load_view(matrix, 800, 600)
        self.assert_fast_camera_path(canvas, 1)
        for _ in range(5):
            canvas._refresh_distributed_load_view(matrix, 800, 600)
        self.assert_fast_camera_path(canvas, 1)
        canvas._is_zooming = True
        second = ORTHOGRAPHIC.copy()
        second[:2] *= 1.4
        canvas._refresh_distributed_load_view(second, 800, 600)
        canvas._is_zooming = False
        canvas._distributed_load_view_time = 0.
        canvas._refresh_distributed_load_view(second, 800, 600)
        self.assert_fast_camera_path(canvas, 2)
        canvas._refresh_distributed_load_view(second, 1200, 800)
        self.assert_fast_camera_path(canvas, 3)
        canvas._upload_load_labels_to_gpu.assert_not_called()
        self.assertEqual(canvas.load_labels, labels)
        self.assertEqual([(record['element_id'], float(t)) for chain in canvas._frame_load_view_samples
                          for record, t in chain], samples)
        self.assertIs(canvas._load_view_geometry, cache)
        self.assertIsNone(getattr(canvas, '_distributed_load_view_timer', None))

    def tributary_canvas(self, show):
        canvas = self.canvas(frame_model(shell_split=True))
        canvas.vbo_manager.is_initialized = True
        canvas.vbo_manager.upload_load_geometry = Mock()
        canvas.show_tributary_mesh = show
        canvas.current_model.tributary_visuals = []
        canvas._update_tributary_visuals = Mock()
        canvas.trib_scatter = SimpleNamespace(setData=Mock())
        return canvas

    def test_camera_fallback_upload_does_not_refresh_tributary_items(self):
        for show in (False, True):
            with self.subTest(show_tributary_mesh=show):
                canvas = self.tributary_canvas(show)
                actual_load_upload(canvas, refresh_tributary=False)
                canvas.vbo_manager.upload_load_geometry.assert_called_once()
                canvas._update_tributary_visuals.assert_not_called()
                canvas.trib_scatter.setData.assert_not_called()
                canvas.vbo_manager.upload_load_geometry.reset_mock()
                canvas.vbo_manager.update_load_positions.return_value = False
                canvas._upload_loads_to_vbo = Mock(side_effect=lambda **kwargs:
                                                  actual_load_upload(canvas, **kwargs))
                canvas._mouse_pressed = True
                moving = ORTHOGRAPHIC.copy()
                moving[0, 3] += .02
                canvas._refresh_distributed_load_view(moving, 800, 600)
                canvas._upload_loads_to_vbo.assert_called_once_with(refresh_tributary=False)
                canvas.vbo_manager.upload_load_geometry.assert_called_once()
                canvas._update_tributary_visuals.assert_not_called()
                canvas.trib_scatter.setData.assert_not_called()

    def test_normal_full_upload_keeps_tributary_refresh_behavior(self):
        for show in (False, True):
            with self.subTest(show_tributary_mesh=show):
                canvas = self.tributary_canvas(show)
                actual_load_upload(canvas)
                canvas.vbo_manager.upload_load_geometry.assert_called_once()
                if show:
                    canvas._update_tributary_visuals.assert_called_once()
                    canvas.trib_scatter.setData.assert_not_called()
                else:
                    canvas._update_tributary_visuals.assert_not_called()
                    canvas.trib_scatter.setData.assert_called_once()
                    kwargs = canvas.trib_scatter.setData.call_args.kwargs
                    self.assertEqual(kwargs['pos'].shape, (0, 3))
                    self.assertEqual(kwargs['color'].shape, (0, 4))

if __name__ == '__main__':
    unittest.main()
