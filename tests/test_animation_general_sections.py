"""Solid-view playback preserves general-section sticks beside extruded members.

Run the actual canvas geometry builders without an OpenGL widget. A prescribed
rigid translation gives exact rest-to-peak vertex motion for either section;
the VBO recorder checks what the animation shader will receive.
"""
import ast
import contextlib
import copy
import io
from pathlib import Path
from types import SimpleNamespace
import unittest

import numpy as np

from core.mesh import FrameElement, Node
from core.properties import (CircularSection, GeneralSection, Material,
                             RectangularSection, TrapezoidalSection)
from post.deflection import get_deflected_shape


ROOT = Path(__file__).resolve().parents[1]


def canvas_methods():
    """Extract production methods, avoiding QApplication/OpenGL construction."""
    tree = ast.parse((ROOT / 'app/canvas.py').read_text(encoding='utf-8-sig'))
    owner = next(node for node in tree.body
                 if isinstance(node, ast.ClassDef) and node.name == 'MCanvas3D')
    names = {'_calculate_frame_geometry', '_build_animated_extruded_vbo',
             '_build_animated_line_vbo', '_add_loft_to_arrays'}
    methods = [copy.deepcopy(node) for node in owner.body
               if isinstance(node, ast.FunctionDef) and node.name in names]
    for method in methods:
        method.decorator_list = []
    namespace = {'np': np, 'get_deflected_shape': get_deflected_shape,
                 'RectangularSection': RectangularSection,
                 'CircularSection': CircularSection,
                 'TrapezoidalSection': TrapezoidalSection}
    exec(compile(ast.fix_missing_locations(ast.Module(body=methods, type_ignores=[])),
                 'production animation geometry methods', 'exec'), namespace)
    return namespace


METHODS = canvas_methods()
TRANSLATION = np.array([.01, -.02, .03])
SCALE = 10.
PEAK_DELTA = SCALE * TRANSLATION


class VBORecorder:
    def __init__(self):
        self.lines = []
        self.solids = []

    def upload_line_geometry(self, positions, colors, displacements=None, **kwargs):
        positions = np.asarray(positions, dtype=float).reshape(-1, 3)
        colors = np.asarray(colors, dtype=float).reshape(-1, 4)
        displacement = (np.zeros_like(positions) if displacements is None
                        else np.asarray(displacements, dtype=float).reshape(-1, 3))
        self.lines.append((positions.copy(), colors.copy(), displacement.copy()))

    def upload_extruded_geometry(self, positions, colors, faces,
                                displacements=None, **kwargs):
        positions = np.asarray(positions, dtype=float).reshape(-1, 3)
        displacement = (np.zeros_like(positions) if displacements is None
                        else np.asarray(displacements, dtype=float).reshape(-1, 3))
        self.solids.append((positions.copy(), np.asarray(colors).copy(),
                            np.asarray(faces).copy(), displacement.copy()))


class AnimationCanvas:
    _calculate_frame_geometry = METHODS['_calculate_frame_geometry']
    _build_animated_extruded_vbo = METHODS['_build_animated_extruded_vbo']
    _build_animated_line_vbo = METHODS['_build_animated_line_vbo']
    _add_loft_to_arrays = METHODS['_add_loft_to_arrays']

    def __init__(self, model, show_edges=False):
        self.current_model = model
        self.vbo_manager = VBORecorder()
        self.view_deflected = True
        self.view_extruded = True
        self.deflection_scale = SCALE
        self.cache_scale_used = SCALE
        self.deflection_cache = {}
        self.selected_element_ids = set()
        self.display_config = {'show_edges': show_edges, 'extrude_opacity': .35,
                               'edge_color': (0., 0., 0., 1.)}

    def _end_states(self, *args):
        return 2, 2

    def _vo_state(self, *args):
        return 2

    def _get_consistent_axes(self, element):
        return element.get_local_axes()

    def invalidate_deflection_cache(self):
        self.deflection_cache.clear()


def frame_model(kinds):
    """Separate members share an exact translation, with distinguishable colors."""
    material = Material('Elastic', 200e9, .3, 7850., 'Steel')
    general = GeneralSection('General', material, {
        'A': .06, 'I22': .00045, 'I33': .0002, 'J': .0004,
        'As2': .05, 'As3': .05}, color=(1., 0., 0., 1.))
    rectangular = RectangularSection('Rectangular', material, .2, .3)
    rectangular.color = (0., 0., 1., 1.)
    elements = {}
    displacements = {}
    for index, kind in enumerate(kinds):
        first = Node(index * 2 + 1, 0., index * 3., 0.)
        last = Node(index * 2 + 2, 2., index * 3., 0.)
        section = general if kind == 'general' else rectangular
        elements[index + 1] = FrameElement(index + 1, first, last, section)
        for node in (first, last):
            displacements[str(node.id)] = [*TRANSLATION, 0., 0., 0.]
    return SimpleNamespace(elements=elements, has_results=True,
                           results={'displacements': displacements})


class GeneralSectionAnimationTests(unittest.TestCase):
    def build(self, kinds, show_edges=False):
        canvas = AnimationCanvas(frame_model(kinds), show_edges)
        with contextlib.redirect_stdout(io.StringIO()):
            success = canvas._build_animated_extruded_vbo()
        self.assertTrue(success, 'Visible frame geometry must support solid-view playback')
        return canvas.vbo_manager

    def assert_motion(self, positions, displacement):
        self.assertGreater(len(positions), 0)
        np.testing.assert_allclose(displacement,
                                   np.broadcast_to(PEAK_DELTA, displacement.shape),
                                   rtol=1e-6, atol=1e-7)

    def test_general_only_animates_as_sticks_with_extrusion_enabled(self):
        for show_edges in (False, True):
            with self.subTest(show_edges=show_edges):
                vbo = self.build(['general'], show_edges)
                self.assertFalse(any(len(mesh[0]) for mesh in vbo.solids))
                self.assertTrue(vbo.lines, 'General section needs an animated line upload')
                positions, colors, displacement = vbo.lines[-1]
                self.assert_motion(positions, displacement)
                np.testing.assert_allclose(colors, np.tile([1., 0., 0., 1.], (len(colors), 1)))
                self.assertAlmostEqual(positions[:, 0].min(), 0.)
                self.assertAlmostEqual(positions[:, 0].max(), 2.)

    def test_mixed_general_and_rectangular_members_both_animate(self):
        for show_edges in (False, True):
            with self.subTest(show_edges=show_edges):
                vbo = self.build(['general', 'rectangular'], show_edges)
                solid = next(mesh for mesh in vbo.solids if len(mesh[0]))
                self.assert_motion(solid[0], solid[3])
                self.assertGreater(solid[0][:, 1].min(), 2., 'Only rectangular member has faces')
                self.assertTrue(vbo.lines, 'General member must survive beside extruded faces')
                positions, colors, displacement = vbo.lines[-1]
                red = np.all(np.isclose(colors[:, :3], [1., 0., 0.]), axis=1)
                self.assertTrue(red.any(), 'General member uses its section color')
                self.assert_motion(positions[red], displacement[red])
                np.testing.assert_allclose(positions[red, 1:], 0., atol=1e-7)
                if show_edges:
                    self.assertTrue((~red).any(), 'Enabled solid outlines must remain present')
                    self.assert_motion(positions[~red], displacement[~red])
                else:
                    self.assertTrue(red.all(), 'Hidden solid outlines must not be uploaded')

    def test_rectangular_only_keeps_faces_and_respects_outline_switch(self):
        for show_edges in (False, True):
            with self.subTest(show_edges=show_edges):
                vbo = self.build(['rectangular'], show_edges)
                solid = next(mesh for mesh in vbo.solids if len(mesh[0]))
                self.assert_motion(solid[0], solid[3])
                nonempty_lines = [line for line in vbo.lines if len(line[0])]
                if show_edges:
                    self.assertEqual(len(nonempty_lines), 1)
                    self.assert_motion(nonempty_lines[0][0], nonempty_lines[0][2])
                else:
                    self.assertEqual(nonempty_lines, [])

    def test_switching_section_mix_clears_obsolete_lines_and_faces(self):
        canvas = AnimationCanvas(frame_model(['general', 'rectangular']))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(canvas._build_animated_extruded_vbo())
        self.assertGreater(len(canvas.vbo_manager.lines[-1][0]), 0)
        self.assertGreater(len(canvas.vbo_manager.solids[-1][0]), 0)

        canvas.current_model = frame_model(['rectangular'])
        canvas.invalidate_deflection_cache()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(canvas._build_animated_extruded_vbo())
        self.assertEqual(len(canvas.vbo_manager.lines[-1][0]), 0,
                         'Old general sticks must be cleared when no lines remain')
        self.assertGreater(len(canvas.vbo_manager.solids[-1][0]), 0)

        canvas.current_model = frame_model(['general'])
        canvas.invalidate_deflection_cache()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(canvas._build_animated_extruded_vbo())
        self.assertEqual(len(canvas.vbo_manager.solids[-1][0]), 0,
                         'Old rectangular faces must be cleared for general-only models')
        self.assert_motion(canvas.vbo_manager.lines[-1][0], canvas.vbo_manager.lines[-1][2])

    def test_no_model_results_or_visible_geometry_do_not_report_success(self):
        no_results = frame_model(['general'])
        no_results.has_results = False
        empty = frame_model([])
        for model in (None, no_results, empty):
            with self.subTest(model=model):
                canvas = AnimationCanvas(model)
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertFalse(canvas._build_animated_extruded_vbo())
                self.assertFalse(any(len(line[0]) for line in canvas.vbo_manager.lines))
                self.assertFalse(any(len(mesh[0]) for mesh in canvas.vbo_manager.solids))


if __name__ == '__main__':
    unittest.main()
