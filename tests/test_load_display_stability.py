"""Camera navigation must not replace model-owned load samples or labels."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT, ROOT / 'tests'):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from test_area_load_render import QApplication, ORTHOGRAPHIC, mesh, snapshot
from test_frame_load_render import FrameCanvas, frame_model, ordered_loads
from app.graphic.load_view_geometry import visible_points
from core.loads import AreaUniformLoad

BUFFERS = ('_pending_load_fill_verts', '_pending_load_fill_colors',
           '_pending_load_fill_faces', '_pending_load_line_pos',
           '_pending_load_line_colors')

def redraw(canvas):
    for name in BUFFERS:
        setattr(canvas, name, [])
    canvas.load_labels = []
    canvas._draw_member_loads(canvas.current_model)
    canvas._draw_area_loads(canvas.current_model)

def samples(canvas):
    area = [(record['area_id'], tuple(point)) for region in canvas._area_load_view_samples
            for record, point in region]
    frame = [(record['element_id'], float(t)) for chain in canvas._frame_load_view_samples
             for record, t in chain]
    return area, frame

def add_remote_area(model):
    area = copy.deepcopy(next(iter(model.area_elements.values())))
    area.id = 9001
    for index, node in enumerate(area.nodes):
        node.id = 100001 + index
        node.x += 80.
    model.area_elements[area.id] = area
    model.loads.append(AreaUniformLoad(area.id, 'Dead', uniform_load=7.))
    return area.id

class LoadDisplayStabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def canvas(self, model, matrix=ORTHOGRAPHIC):
        if not hasattr(model, 'elements'):
            model.elements = {}
        canvas = FrameCanvas(model, matrix)
        canvas.vbo_manager.update_load_positions = Mock(return_value=True)
        redraw(canvas)
        self.addCleanup(self.stop_timers, canvas)
        return canvas

    @staticmethod
    def stop_timers(canvas):
        for name in ('_distributed_load_view_timer', '_area_load_view_timer'):
            timer = getattr(canvas, name, None)
            if timer is not None:
                timer.stop()

    def test_zoom_end_pan_and_resize_never_resample_or_relayout(self):
        canvas = self.canvas(frame_model(shell_split=True))
        original_samples = samples(canvas)
        original_labels = copy.deepcopy(canvas.load_labels)
        faces = np.asarray(canvas._pending_load_fill_faces).copy()
        lengths = tuple(len(getattr(canvas, name)) for name in BUFFERS)
        cache = canvas._load_view_geometry
        canvas._render_area_load_regions = Mock(wraps=canvas._render_area_load_regions)
        canvas._render_frame_load_chains = Mock(wraps=canvas._render_frame_load_chains)
        canvas._upload_loads_to_vbo.reset_mock()
        canvas._upload_load_labels_to_gpu = Mock(wraps=canvas._upload_load_labels_to_gpu)
        matrix = ORTHOGRAPHIC.copy()
        with patch('app.graphic.area_load_render.layout_load_labels',
                   create=True, side_effect=lambda labels, *args: (list(labels), [])) as area_layout,\
             patch('app.graphic.frame_load_render.layout_load_labels',
                   create=True, side_effect=lambda labels, *args: (list(labels), [])) as frame_layout:
            for zoom in (1.3, 2., 3.):
                matrix = ORTHOGRAPHIC.copy()
                matrix[:2] *= zoom
                canvas._is_zooming = True
                canvas._refresh_distributed_load_view(matrix, 800, 600)
                                                                              
                canvas._is_zooming = False
                canvas._distributed_load_view_time = 0.
                canvas._refresh_distributed_load_view(matrix, 800, 600)
            canvas._mouse_pressed = True
            matrix[0, 3] += .4
            canvas._refresh_distributed_load_view(matrix, 800, 600)
            canvas._mouse_pressed = False
            canvas._distributed_load_view_time = 0.
            canvas._refresh_distributed_load_view(matrix, 800, 600)
            canvas._refresh_distributed_load_view(matrix, 1200, 800)
            canvas._render_area_load_regions.assert_not_called()
            canvas._render_frame_load_chains.assert_not_called()
            area_layout.assert_not_called()
            frame_layout.assert_not_called()
        canvas._upload_loads_to_vbo.assert_not_called()
        canvas._upload_load_labels_to_gpu.assert_not_called()
        self.assertEqual(samples(canvas), original_samples)
        self.assertEqual(canvas.load_labels, original_labels)
        self.assertEqual(tuple(len(getattr(canvas, name)) for name in BUFFERS), lengths)
        np.testing.assert_array_equal(canvas._pending_load_fill_faces, faces)
        self.assertIs(canvas._load_view_geometry, cache)

    def test_initial_camera_does_not_choose_samples_or_label_positions(self):
        model = mesh(16)
        add_remote_area(model)
        first = self.canvas(model)
        other_view = ORTHOGRAPHIC.copy()
        other_view[:2] *= 3.
        other_view[0, 3] = -14.4
        second = self.canvas(model, other_view)
        self.assertEqual(samples(first), samples(second))
        self.assertEqual(first.load_labels, second.load_labels)
        self.assertEqual(len(first.load_labels), 2)

    def test_offscreen_groups_are_kept_and_project_into_view_without_rebuild(self):
        model = mesh(4)
        remote_id = add_remote_area(model)
        canvas = self.canvas(model)
        annotations = copy.deepcopy(canvas.load_labels)
        self.assertEqual(len(annotations), 2)
        remote = next(item for item in annotations if remote_id in item['owner_ids'])
        anchor = np.asarray([remote['leader_anchor']])
        self.assertFalse(visible_points(anchor, ORTHOGRAPHIC)[0])
        remote_samples = [point for region in canvas._area_load_view_samples
                          for record, point in region if record['area_id'] == remote_id]
        self.assertGreater(len(remote_samples), 0)
        canvas._render_area_load_regions = Mock(wraps=canvas._render_area_load_regions)
        canvas._render_frame_load_chains = Mock(wraps=canvas._render_frame_load_chains)
        canvas._upload_load_labels_to_gpu = Mock(wraps=canvas._upload_load_labels_to_gpu)
        canvas._upload_loads_to_vbo.reset_mock()
        pan = ORTHOGRAPHIC.copy()
        pan[0, 3] = -14.4
        canvas._mouse_pressed = True
        canvas._refresh_distributed_load_view(pan, 800, 600)
        canvas._mouse_pressed = False
        canvas._distributed_load_view_time = 0.
        canvas._refresh_distributed_load_view(pan, 800, 600)
        self.assertTrue(visible_points(anchor, pan)[0])
        self.assertEqual(canvas.load_labels, annotations)
        canvas._render_area_load_regions.assert_not_called()
        canvas._render_frame_load_chains.assert_not_called()
        canvas._upload_load_labels_to_gpu.assert_not_called()
        canvas._upload_loads_to_vbo.assert_not_called()

    def test_model_labels_stay_near_their_owner_at_original_font_size(self):
        model = mesh(16)
        remote_id = add_remote_area(model)
        canvas = self.canvas(model)
        self.assertEqual(len(canvas.load_labels), 2)
        self.assertTrue(any(remote_id in item['owner_ids'] for item in canvas.load_labels))
        for item in canvas.load_labels:
            self.assertEqual(item['text_height'], .22)
            distance = np.linalg.norm(np.asarray(item['pos_3d']) - item['leader_anchor'])
            self.assertLessEqual(distance, 8 * item['text_height'])

    def test_fine_division_has_fixed_tip_budget_and_edited_child_remains_distinct(self):
        model = mesh(16)
        before = snapshot(model)
        canvas = self.canvas(model)
        base_samples = samples(canvas)
        self.assertEqual(len(canvas._area_load_regions), 1)
        self.assertLessEqual(len(base_samples[0]), 5)
        self.assertEqual(len(canvas.load_labels), 1)
        self.assertEqual(canvas.load_labels[0]['group_count'], 256)
        self.assertEqual(snapshot(model), before)
        changed = model.loads[127]
        changed.uniform_load = 7.
        redraw(canvas)
        self.assertEqual(len(canvas.load_labels), 2)
        self.assertEqual({item['val'] for item in canvas.load_labels}, {5., 7.})
        exception = next(item for item in canvas.load_labels if item['val'] == 7.)
        self.assertEqual(exception['owner_ids'], (changed.area_id,))
        self.assertLessEqual(len(samples(canvas)[0]), 10)
        changed.uniform_load = 5.
        redraw(canvas)
        self.assertEqual(len(canvas.load_labels), 1)
        self.assertEqual(samples(canvas), base_samples)

    def test_frame_divisions_keep_fixed_samples_and_changed_segment_owners(self):
        for shell_split in (False, True):
            with self.subTest(shell_split=shell_split):
                model = frame_model(shell_split=shell_split)
                canvas = self.canvas(model)
                original_samples = samples(canvas)
                self.assertLessEqual(len(original_samples[1]), 5)
                frame_labels = [item for item in canvas.load_labels if item['owner_type'] == 'element']
                self.assertEqual(len(frame_labels), 1)
                self.assertEqual(frame_labels[0]['group_count'], 8)
                changed = ordered_loads(model)[3]
                changed.wz = -7.
                redraw(canvas)
                frame_labels = [item for item in canvas.load_labels if item['owner_type'] == 'element']
                self.assertEqual(sorted(item['group_count'] for item in frame_labels), [1, 3, 4])
                exception = next(item for item in frame_labels if item['val'] == 7.)
                self.assertEqual(exception['owner_ids'], (changed.element_id,))
                changed.wz = -5.
                redraw(canvas)
                self.assertEqual(samples(canvas), original_samples)

if __name__ == '__main__':
    unittest.main()
