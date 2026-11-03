"""Camera updates must preserve the active framebuffer and visible load scope."""
import ast
import copy
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / 'tests') not in sys.path:
    sys.path.insert(0, str(ROOT / 'tests'))
from test_area_load_render import (FakeCanvas, Matrix, ORTHOGRAPHIC,
                                   QApplication, label, mesh)
from app.graphic.load_label_layout import layout_load_labels, label_screen_bounds
from app.graphic.load_view_geometry import visible_points

def screen_position(point, mvp):
    clip = mvp @ np.r_[point, 1.]
    return np.array([(clip[0] / clip[3] + 1) * 400,
                     (1 - clip[1] / clip[3]) * 300])

def paint_preparation():
    """Execute the real preparation order, including later load-refresh calls.

    The recorder models QOpenGLWidget.makeCurrent rebinding the widget FBO.
    A late load upload therefore corrupts the active FXAA target even though
    every individual upload is successful.
    """
    tree = ast.parse((ROOT / 'app/canvas.py').read_text(encoding='utf-8-sig'))
    owner = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'MCanvas3D')
    paint = next(n for n in owner.body if isinstance(n, ast.FunctionDef) and n.name == 'paintGL')
    start = next(i for i, node in enumerate(paint.body) if isinstance(node, ast.Expr)
                 and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Attribute)
                 and node.value.func.attr == 'makeCurrent')
    stop = next(i for i, node in enumerate(paint.body[start:], start)
                if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name) and node.value.func.id == 'glViewport')
    preparation = copy.deepcopy(paint.body[start:stop])
    fxaa = next(node for node in ast.walk(paint) if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute) and node.func.attr == '_fxaa_begin')
    late = [node for node in ast.walk(paint) if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and 'refresh' in node.func.attr and 'load' in node.func.attr
            and node.lineno > fxaa.lineno]
    for call in late:
        copied = copy.deepcopy(call)
        copied.args = [ast.Name(id='test_mvp', ctx=ast.Load()), ast.Constant(800), ast.Constant(600)]
        copied.keywords = []
        preparation.append(ast.Expr(value=copied))
    function = ast.FunctionDef(name='prepare', args=ast.arguments(
        posonlyargs=[], args=[ast.arg(arg='self')], kwonlyargs=[],
        kw_defaults=[], defaults=[]), body=preparation, decorator_list=[])
    namespace = {'np': np, 'test_mvp': ORTHOGRAPHIC}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[])),
                 'canvas framebuffer preparation', 'exec'), namespace)
    return namespace['prepare']

class FramebufferRecorder:
    def __init__(self):
        self.framebuffer = None
        self.calls = []
        self.vbo_manager = SimpleNamespace(is_initialized=True)

    def width(self): return 800
    def height(self): return 600
    def viewMatrix(self): return Matrix(np.eye(4))
    def projectionMatrix(self, **kwargs): return Matrix(ORTHOGRAPHIC)

    def makeCurrent(self):
        self.framebuffer = 'widget'
        self.calls.append('makeCurrent')

    def _refresh_area_load_view(self, *args):
        self.calls.append('load upload')
        self.makeCurrent()

    def __getattr__(self, name):
                                                                             
        if name.startswith('_refresh_') and 'load' in name:
            return self._refresh_area_load_view
        raise AttributeError(name)

    def _fxaa_begin(self):
        self.calls.append('fxaa begin')
        self.framebuffer = 'fxaa'
        return True

class LoadDisplayNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def test_load_upload_happens_before_fxaa_target_is_bound(self):
        recorder = FramebufferRecorder()
        paint_preparation()(recorder)
        self.assertIn('load upload', recorder.calls)
        self.assertEqual(recorder.framebuffer, 'fxaa')
        self.assertEqual(recorder.calls[-1], 'fxaa begin')

    def assert_label_is_physically_clipped(self, annotation, matrix):
        self.assertFalse(visible_points([annotation['leader_anchor']], matrix)[0])
        bounds = label_screen_bounds(annotation, matrix, 800, 600)
        if bounds is not None:
            self.assertTrue(bounds[2] < 0 or bounds[0] > 800 or
                            bounds[3] < 0 or bounds[1] > 600)

    def test_offscreen_or_clipped_areas_keep_labels_at_their_physical_owners(self):
        matrices = []
        for dimension, translation in ((0, 3.), (1, 3.), (2, 3.), (2, -3.)):
            matrix = ORTHOGRAPHIC.copy()
            matrix[dimension, 3] += translation
            matrices.append(matrix)
        behind = ORTHOGRAPHIC.copy()
        behind[3, 3] = -1.
        matrices.append(behind)
        for matrix in matrices:
            with self.subTest(matrix=matrix):
                model = mesh(1)
                canvas = FakeCanvas(model, matrix)
                canvas._draw_area_loads(model)
                self.assertEqual(len(canvas.load_labels), 1)
                annotation = canvas.load_labels[0]
                self.assertEqual(annotation['owner_ids'], (1,))
                self.assert_label_is_physically_clipped(annotation, matrix)
                canvas._upload_load_labels_to_gpu()
                self.assertEqual(canvas.uploaded_labels, canvas.load_labels)
                self.assert_label_is_physically_clipped(canvas.uploaded_labels[0], matrix)

    def test_offscreen_exception_keeps_its_value_but_cannot_fly_into_view(self):
        model = mesh()
        model.loads[-1].uniform_load = 9.
        model.loads[27].uniform_load = 7.
        matrix = ORTHOGRAPHIC.copy()
        matrix[0, 3] = .6
        canvas = FakeCanvas(model, matrix)
        canvas._draw_area_loads(model)
        self.assertEqual({item['val'] for item in canvas.load_labels}, {5., 7., 9.})
        visible = [item for item in canvas.load_labels
                   if visible_points([item['leader_anchor']], matrix)[0]]
        self.assertEqual({item['val'] for item in visible}, {5., 7.})
        exception = next(item for item in canvas.load_labels if item['val'] == 9.)
        self.assertFalse(visible_points([exception['leader_anchor']], matrix)[0])
                                                                         
        np.testing.assert_array_equal(exception['pos_3d'][:2], exception['leader_anchor'][:2])
        self.assertGreater(screen_position(exception['pos_3d'], matrix)[0], 800)
        self.assertLessEqual(np.linalg.norm(np.asarray(exception['pos_3d']) -
                                           exception['leader_anchor']), .5)

    def test_layout_does_not_pull_invisible_owners_into_the_view(self):
        positions = ((20., 0., 0.), (0., 20., 0.), (20., 0., 40.), (20., 0., -40.))
        for position in positions:
            with self.subTest(position=position):
                source = dict(label(position=position), leader_anchor=list(position))
                before = copy.deepcopy(source)
                placed, leaders = layout_load_labels([source], [], ORTHOGRAPHIC, 800, 600)
                self.assertEqual(leaders, [])
                self.assertEqual(source, before)
                for result in placed:
                    np.testing.assert_array_equal(result['pos_3d'], source['pos_3d'])

    def test_collision_placement_stays_within_48_pixels_of_its_anchor_position(self):
        source = dict(label(value=7.), group_count=1, leader_anchor=[0., 0., 0.])
        obstacle = label(value=3., height=2., position=(0., 0., -1.4))
        obstacle['text'] = 'A long overlapping load annotation ' * 5
        placed, _ = layout_load_labels([source], [obstacle], ORTHOGRAPHIC, 800, 600)
        self.assertEqual(len(placed), 1)
        self.assertEqual(placed[0]['text'], source['text'])
        self.assertEqual(placed[0]['text_height'], source['text_height'])
        displacement = np.linalg.norm(screen_position(placed[0]['pos_3d'], ORTHOGRAPHIC) -
                                      screen_position(source['pos_3d'], ORTHOGRAPHIC))
        self.assertLessEqual(displacement, 48. + 1.e-8)

    def test_static_camera_does_not_reupload_area_geometry_or_text(self):
        canvas = FakeCanvas(mesh())
        canvas._draw_area_loads(canvas.current_model)
        canvas._area_load_view_time = 0.
        for _ in range(5):
            canvas._refresh_area_load_view(canvas.mvp, 800, 600)
        canvas._upload_loads_to_vbo.assert_not_called()
        canvas.vbo_manager.upload_text_geometry.assert_not_called()

    def test_area_wheel_end_and_resize_preserve_samples_and_text_without_timer(self):
        canvas = FakeCanvas(mesh())
        canvas.vbo_manager.update_load_positions = Mock(return_value=True)
        canvas._draw_area_loads(canvas.current_model)
        labels = copy.deepcopy(canvas.load_labels)
        samples = [(record['area_id'], tuple(point)) for region in canvas._area_load_view_samples
                   for record, point in region]
        faces = np.asarray(canvas._pending_load_fill_faces).copy()
        canvas._render_area_load_regions = Mock(wraps=canvas._render_area_load_regions)
        canvas._fan_triangulate = Mock(wraps=canvas._fan_triangulate)
        moved = canvas.mvp.copy()
        moved[:2] *= 2.
        canvas._is_zooming = True
        canvas._refresh_area_load_view(moved, 800, 600)
        canvas._is_zooming = False
        canvas._area_load_view_time = 0.
        for _ in range(4):
            canvas._refresh_area_load_view(moved, 800, 600)
        canvas._refresh_area_load_view(moved, 1200, 800)
        self.assertEqual(canvas.vbo_manager.update_load_positions.call_count, 2)
        canvas._render_area_load_regions.assert_not_called()
        canvas._fan_triangulate.assert_not_called()
        canvas._upload_loads_to_vbo.assert_not_called()
        canvas.vbo_manager.upload_text_geometry.assert_not_called()
        self.assertEqual(canvas.load_labels, labels)
        self.assertEqual([(record['area_id'], tuple(point)) for region in canvas._area_load_view_samples
                          for record, point in region], samples)
        np.testing.assert_array_equal(canvas._pending_load_fill_faces, faces)
        self.assertIsNone(getattr(canvas, '_area_load_view_timer', None))

if __name__ == '__main__':
    unittest.main()
