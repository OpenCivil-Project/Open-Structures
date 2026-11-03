"""Divided-frame load displays preserve assignments and continuous overlays."""
import ast
import copy
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / 'tests') not in sys.path:
    sys.path.insert(0, str(ROOT / 'tests'))
from test_area_load_render import FakeCanvas, ORTHOGRAPHIC, QApplication, label
from app.graphic.frame_load_render import FrameLoadDisplayMixin
from core.model import StructuralModel, MemberLoad
from core.loads import MemberPointLoad
from core.units import unit_registry

def canvas_methods():
    """Use the actual legacy renderer and drawn axes without constructing GL."""
    tree = ast.parse((ROOT / 'app/canvas.py').read_text(encoding='utf-8-sig'))
    owner = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'MCanvas3D')
    names = {'_draw_member_loads_legacy', '_get_consistent_axes', '_interp_linear'}
    methods = [copy.deepcopy(n) for n in owner.body
               if isinstance(n, ast.FunctionDef) and n.name in names]
    for method in methods:
        method.decorator_list = []
    namespace = {'np': np, 'unit_registry': unit_registry}
    exec(compile(ast.fix_missing_locations(ast.Module(body=methods, type_ignores=[])),
                 'actual frame canvas methods', 'exec'), namespace)
    return namespace

_METHODS = canvas_methods()
_BUFFERS = ('_pending_load_fill_verts', '_pending_load_fill_colors',
            '_pending_load_fill_faces', '_pending_load_line_pos', '_pending_load_line_colors')

class FrameCanvas(FrameLoadDisplayMixin, FakeCanvas):
    _draw_member_loads_legacy = _METHODS['_draw_member_loads_legacy']
    _get_consistent_axes = _METHODS['_get_consistent_axes']
    _interp_linear = staticmethod(_METHODS['_interp_linear'])

    def __init__(self, model, mvp=ORTHOGRAPHIC, mode='smart'):
        super().__init__(model, mvp)
        self.selected_element_ids = list(model.elements)
        self.display_config['frame_load_display_mode'] = mode
        self._mouse_pressed = False
        self._is_zooming = False

    def _end_states(self, kind, element):
        return (2, 2)

def frame_model(n=8, shell_split=False, profile=None, coord_system='Global', beta=0.):
    """Exercise real user division paths, including shell-triggered splitting."""
    model = StructuralModel('Frame display regression')
    section = SimpleNamespace(name='Beam')
    first = model.add_node(-4., 0., 0.)
    last = model.add_node(4., 0., 0.)
    beam = model.add_element(first, last, section, beta)
    if profile is None:
        model.assign_member_load(beam.id, 'DEAD', wz=-5., coord_system=coord_system)
    else:
        distances, magnitudes = profile
        model.assign_member_load(beam.id, 'DEAD', distances=distances, magnitudes=magnitudes,
                                 coord_system=coord_system, load_direction='Z')
    if shell_split:
        top_right = model.add_node(4., 4., 0.)
        top_left = model.add_node(-4., 4., 0.)
        slab_section = SimpleNamespace(name='Slab', material_angle=0., membrane_thickness=.2)
        area = model.add_area_element([first, last, top_right, top_left], slab_section)
        model.assign_area_uniform_load(area.id, 'DEAD', 2.)
        model.mesh_area_elements([area.id], n=n, m=1, divide_frames=True)
    elif n > 1:
        model.divide_frame_by_number(beam.id, n)
    return model

def ordered_loads(model):
    return sorted((load for load in model.loads if hasattr(load, 'wx')),
                  key=lambda load: model.elements[load.element_id].node_i.x)

def canonical(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (list, tuple)):
        return [canonical(item) for item in value]
    if isinstance(value, dict):
        return {key: canonical(item) for key, item in value.items()}
    if hasattr(value, '__dict__'):
        return (type(value).__name__, canonical(vars(value)))
    return value

def assignment_snapshot(model):
    return canonical((model.loads, model.nodes, model.elements, model.area_elements))

def redraw(canvas, include_area=False):
    for name in _BUFFERS:
        setattr(canvas, name, [])
    canvas.load_labels.clear()
    canvas._draw_member_loads(canvas.current_model)
    if include_area:
        canvas._draw_area_loads(canvas.current_model)

class FrameLoadRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def assert_contiguous_owners(self, canvas):
        for annotation in canvas.load_labels:
            elements = [canvas.current_model.elements[eid] for eid in annotation['owner_ids']]
            spans = sorted((min(e.node_i.x, e.node_j.x), max(e.node_i.x, e.node_j.x))
                           for e in elements)
            for left, right in zip(spans, spans[1:]):
                self.assertEqual(left[1], right[0])

    def test_manual_and_shell_divisions_group_edits_and_restoration(self):
        for shell_split in (False, True):
            with self.subTest(shell_split=shell_split):
                model = frame_model(shell_split=shell_split)
                self.assertEqual(len(model.elements), 8)
                canvas = FrameCanvas(model)
                redraw(canvas)
                self.assertEqual(len(canvas.load_labels), 1)
                self.assertEqual(canvas.load_labels[0]['group_count'], 8)
                self.assertEqual(set(canvas.load_labels[0]['owner_ids']), set(model.elements))
                load = ordered_loads(model)[3]
                load.wz = -5.000001
                redraw(canvas)
                self.assertEqual(len(canvas.load_labels), 3)
                self.assertEqual(sorted(item['group_count'] for item in canvas.load_labels), [1, 3, 4])
                self.assertEqual({item['val'] for item in canvas.load_labels}, {5., 5.000001})
                self.assertEqual(len({item['text'] for item in canvas.load_labels}), 2)
                self.assert_contiguous_owners(canvas)
                load.wz = -5.
                redraw(canvas)
                self.assertEqual(len(canvas.load_labels), 1)

    def test_render_and_view_refresh_preserve_complete_assignment_data(self):
        for shell_split in (False, True):
            with self.subTest(shell_split=shell_split):
                model = frame_model(shell_split=shell_split)
                load = ordered_loads(model)[3]
                load.wz = -7.
                load.projected = True
                load.load_type = 'Moment'
                model.loads.append(MemberPointLoad(load.element_id, 'DEAD', 11., .33, True,
                                                   'Local', '2', 'Force'))
                before = assignment_snapshot(model)
                canvas = FrameCanvas(model)
                redraw(canvas, include_area=True)
                changed = canvas.mvp.copy(); changed[0, 3] += .025
                canvas._distributed_load_view_time = 0.
                canvas._refresh_distributed_load_view(changed, 800, 600)
                self.assertEqual(assignment_snapshot(model), before)

    def test_linear_child_profiles_share_one_continuous_curtain_scale(self):
        model = frame_model(profile=([0., .25, .75, 1.], [-2., -4., -8., -10.]))
        canvas = FrameCanvas(model)
        redraw(canvas)
        self.assertEqual(len(canvas.load_labels), 1)
        self.assertEqual(canvas.load_labels[0]['val'], 10.)
        verts = np.asarray(canvas._pending_load_fill_verts)
        base, top = verts[::2], verts[1::2]
        heights = np.linalg.norm(top - base, axis=1)
        expected_values = 2. + (base[:, 0] + 4.)
        np.testing.assert_allclose(heights / expected_values,
                                   np.repeat(heights[-1] / expected_values[-1], len(heights)), atol=1e-14)
        for x in np.linspace(-3., 3., 7):
            joint = top[np.isclose(base[:, 0], x)]
            self.assertGreaterEqual(len(joint), 2)
            np.testing.assert_allclose(joint, np.repeat(joint[:1], len(joint), axis=0), atol=1e-14)
        ordered_loads(model)[3].magnitudes[-1] -= .001
        redraw(canvas)
        self.assertEqual(len(canvas.load_labels), 3)
        self.assert_contiguous_owners(canvas)

    def test_partial_and_non_affine_profiles_stay_independent(self):
        for positions, values in (([.2, .8], [-2., -5.]),
                                  ([0., .5, 1.], [-2., -8., -5.])):
            with self.subTest(positions=positions):
                model = frame_model()
                for load in ordered_loads(model):
                    load.wz = 0.
                    load.distances = positions[:]
                    load.magnitudes = values[:]
                canvas = FrameCanvas(model)
                redraw(canvas)
                self.assertEqual(len(canvas.load_labels), 8)
                self.assertTrue(all(item['group_count'] == 1 for item in canvas.load_labels))
                verts = np.asarray(canvas._pending_load_fill_verts)[::2]
                if positions[0] > 0:
                    for load in ordered_loads(model):
                        element = model.elements[load.element_id]
                        self.assertTrue(np.any(np.isclose(verts[:, 0], element.node_i.x + positions[0])))
                        self.assertFalse(np.any(np.isclose(verts[:, 0], element.node_i.x)))

    def test_point_companions_are_excluded_from_distributed_profiles(self):
        model = frame_model()
        canvas = FrameCanvas(model)
        redraw(canvas)
        before = canonical((canvas.load_labels, [getattr(canvas, name) for name in _BUFFERS]))
        for load in ordered_loads(model):
            model.loads.append(MemberPointLoad(load.element_id, 'DEAD', 11., .5, True,
                                               'Global', 'Gravity', 'Force'))
        redraw(canvas)
        self.assertEqual(canonical((canvas.load_labels, [getattr(canvas, name) for name in _BUFFERS])), before)

    def test_every_member_and_hidden_modes(self):
        model = frame_model()
        for mode, count in (('every_member', 8), ('hidden', 0)):
            with self.subTest(mode=mode):
                canvas = FrameCanvas(model, mode=mode)
                redraw(canvas)
                self.assertEqual(len(canvas.load_labels), count)
                self.assertGreater(len(canvas._pending_load_fill_faces), 0)
                self.assertGreater(len(canvas._pending_load_line_pos), 0)

    def test_pattern_type_and_projection_changes_break_chains(self):
        for attribute, value in (('pattern_name', 'LIVE'), ('load_type', 'Moment'), ('projected', True)):
            with self.subTest(attribute=attribute):
                model = frame_model()
                setattr(ordered_loads(model)[3], attribute, value)
                canvas = FrameCanvas(model)
                redraw(canvas)
                self.assertEqual(len(canvas.load_labels), 3)
                self.assertEqual(sorted(item['group_count'] for item in canvas.load_labels), [1, 3, 4])
                self.assert_contiguous_owners(canvas)
                if attribute == 'pattern_name':
                    self.assertTrue(any(item['text'].startswith('LIVE:') for item in canvas.load_labels))
                    canvas.visible_load_patterns = ['DEAD']
                    redraw(canvas)
                    self.assertEqual(len(canvas.load_labels), 2)

    def test_extra_assignment_preserves_the_complete_child_stack(self):
        model = frame_model()
        owner = ordered_loads(model)[3].element_id
        model.loads.append(MemberLoad(owner, 'DEAD', wy=3., load_direction='Y'))
        canvas = FrameCanvas(model)
        redraw(canvas)
        self.assertEqual(len(canvas.load_labels), 4)
        self.assertEqual(sorted(item['group_count'] for item in canvas.load_labels), [1, 1, 3, 4])
        self.assertEqual(sorted(item['val'] for item in canvas.load_labels), [3., 5., 5., 5.])

    def test_local_load_geometry_uses_each_members_drawn_axes(self):
        model = frame_model(coord_system='Local', beta=37.)
        canvas = FrameCanvas(model)
        redraw(canvas)
        self.assertEqual(len(canvas.load_labels), 1)
        vertices = np.asarray(canvas._pending_load_fill_verts)
        displacement = vertices[1::2] - vertices[::2]
        actual = displacement / np.linalg.norm(displacement, axis=1)[:, None]
        expected = canvas._get_consistent_axes(next(iter(model.elements.values())))[2]
        np.testing.assert_allclose(actual, np.repeat([expected], len(actual), axis=0), atol=1e-14)

    def test_reversed_member_orientation_only_merges_matching_global_loads(self):
        for coord in ('Global', 'Local'):
            with self.subTest(coord=coord):
                model = frame_model(coord_system=coord)
                loads = ordered_loads(model)
                for load in loads:
                    load.wz = 0.; load.wy = -5.; load.load_direction = 'Y'
                reversed_element = model.elements[loads[3].element_id]
                reversed_element.node_i, reversed_element.node_j = reversed_element.node_j, reversed_element.node_i
                canvas = FrameCanvas(model)
                redraw(canvas)
                self.assertEqual(len(canvas.load_labels), 1 if coord == 'Global' else 3)
                if coord == 'Local':
                    vertices = np.asarray(canvas._pending_load_fill_verts)
                    displacement = vertices[1::2] - vertices[::2]
                    self.assertTrue((displacement[:, 1] < 0.).any())
                    self.assertTrue((displacement[:, 1] > 0.).any())

    def test_offscreen_and_clipped_chains_keep_physically_clipped_annotations(self):
        for dimension, translation in ((0, 3.), (1, 3.), (2, 3.), (2, -3.), (3, -2.)):
            with self.subTest(dimension=dimension, translation=translation):
                matrix = ORTHOGRAPHIC.copy(); matrix[dimension, 3] += translation
                canvas = FrameCanvas(frame_model(), mvp=matrix)
                redraw(canvas)
                self.assertEqual(len(canvas.load_labels), 1)
                project, _, _, _ = canvas._area_load_projection(matrix, 800, 600)
                self.assertIsNone(project(canvas.load_labels[0]['leader_anchor']))
                cache = canvas._load_view_geometry
                self.assertTrue((cache.line_colors[cache.arrow_indices, 3] == 0.).all())

    def test_combined_refresh_keeps_static_prefix_and_area_overlay(self):
        model = frame_model(shell_split=True)
        canvas = FrameCanvas(model)
                                                                                 
        canvas.load_labels = [dict(label(value=i + 1.), owner_type=kind)
                              for i, kind in enumerate(('node', 'point', 'cable', 'hinge'))]
        for index, name in enumerate(_BUFFERS):
            getattr(canvas, name).extend([[index, i, -9., 1.] if name.endswith('colors')
                                         else [index, i, -9.] for i in range(4)])
        prefix = canonical((canvas.load_labels, [getattr(canvas, name) for name in _BUFFERS]))
        canvas._draw_member_loads(model)
        canvas._draw_area_loads(model)
        initial_area = canonical([item for item in canvas.load_labels if item['owner_type'] == 'area'])
        counts = [len(getattr(canvas, name)) for name in _BUFFERS]
                                                                           
        canvas._distributed_load_view_time = 0.
        canvas._refresh_distributed_load_view(canvas.mvp, 801, 600)
        self.assertEqual(canonical((canvas.load_labels[:4], [getattr(canvas, name)[:4] for name in _BUFFERS])), prefix)
        self.assertEqual(len([item for item in canvas.load_labels if item['owner_type'] == 'area']), len(initial_area))
        self.assertEqual([len(getattr(canvas, name)) for name in _BUFFERS], counts)
        canvas._upload_loads_to_vbo.assert_called_once()
        canvas.vbo_manager.upload_text_geometry.assert_not_called()
        for _ in range(5):
            canvas._refresh_distributed_load_view(canvas.mvp, 801, 600)
        canvas._upload_loads_to_vbo.assert_called_once()
        self.assertEqual([len(getattr(canvas, name)) for name in _BUFFERS], counts)
        canvas.selected_element_ids.remove(ordered_loads(model)[3].element_id)
        canvas._refresh_distributed_load_view(canvas.mvp, 801, 600)
        self.assertEqual(canonical((canvas.load_labels[:4], [getattr(canvas, name)[:4] for name in _BUFFERS])), prefix)
        self.assertEqual(len([item for item in canvas.load_labels if item['owner_type'] == 'area']), len(initial_area))

    def test_navigation_resizes_geometry_but_defers_sampling_and_label_layout(self):
        for flag in ('_mouse_pressed', '_is_zooming'):
            with self.subTest(flag=flag):
                canvas = FrameCanvas(frame_model(shell_split=True))
                redraw(canvas, include_area=True)
                old_samples = canonical((canvas._frame_load_view_samples, canvas._area_load_view_samples))
                old_labels = canonical(canvas.load_labels)
                changed = canvas.mvp.copy(); changed[0, 3] += .05
                canvas._distributed_load_view_time = 0.
                setattr(canvas, flag, True)
                for offset in (.01, .02, .03):
                    moving = changed.copy(); moving[0, 3] += offset
                    canvas._refresh_distributed_load_view(moving, 800, 600)
                self.assertEqual(canvas._upload_loads_to_vbo.call_count, 3)
                canvas.vbo_manager.upload_text_geometry.assert_not_called()
                self.assertEqual(canonical((canvas._frame_load_view_samples, canvas._area_load_view_samples)), old_samples)
                self.assertEqual(canonical(canvas.load_labels), old_labels)
                self.assertFalse(canvas._distributed_load_view_needs_settle)
                self.assertFalse(hasattr(canvas, '_distributed_load_view_timer'))
                setattr(canvas, flag, False)
                canvas._distributed_load_view_time = 0.
                canvas._refresh_distributed_load_view(moving, 800, 600)
                self.assertEqual(canvas._upload_loads_to_vbo.call_count, 3)
                canvas._refresh_distributed_load_view(changed, 800, 600)
                self.assertEqual(canvas._upload_loads_to_vbo.call_count, 4)
                canvas.vbo_manager.upload_text_geometry.assert_not_called()
                self.assertFalse(canvas._distributed_load_view_needs_settle)

if __name__ == '__main__':
    unittest.main()
