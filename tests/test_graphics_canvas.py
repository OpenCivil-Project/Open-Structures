"""Appearance refresh must preserve current playback and rebuild baked colors."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
tree = ast.parse((ROOT / 'app/canvas.py').read_text(encoding='utf-8-sig'))
owner = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'MCanvas3D')
names = {'refresh_graphics_geometry', 'refresh_deformed_playback', '_frames_sig',
         '_draw_elements_extruded'}
methods = [n for n in owner.body if isinstance(n, ast.FunctionDef) and n.name in names]
namespace = {'np': np, '_mark': lambda name: None}
exec(compile(ast.fix_missing_locations(ast.Module(body=methods, type_ignores=[])),
             'canvas appearance methods', 'exec'), namespace)

paint = next(n for n in owner.body if isinstance(n, ast.FunctionDef) and n.name == 'paintGL')
render_owner = next(n for n in ast.walk(paint) if isinstance(n, ast.If)
                    and any(isinstance(s, ast.Assign) and any(
                        isinstance(t, ast.Name) and t.id == 'show_areas' for t in s.targets)
                            for s in n.body))
start = next(i for i, n in enumerate(render_owner.body) if isinstance(n, ast.Assign)
             and any(isinstance(t, ast.Name) and t.id == 'show_areas' for t in n.targets))
stop = next(i for i, n in enumerate(render_owner.body[start:], start) if isinstance(n, ast.Expr)
            and isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Name)
            and n.value.func.id == 'glClear')
render = ast.FunctionDef(name='render_phases', args=ast.arguments(
    posonlyargs=[], args=[ast.arg(arg=name) for name in ('self','m_view','m_proj','light')],
    kwonlyargs=[], kw_defaults=[], defaults=[]), body=render_owner.body[start:stop], decorator_list=[])
exec(compile(ast.fix_missing_locations(ast.Module(body=[render], type_ignores=[])),
             'native surface routing', 'exec'), namespace)

class _DrawRecorder:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.calls.append((name, kwargs))
        return record

class _Canvas:
    refresh_graphics_geometry = namespace['refresh_graphics_geometry']
    refresh_deformed_playback = namespace['refresh_deformed_playback']
    _frames_sig = namespace['_frames_sig']

    def __init__(self, running=False, ltha=False):
        self.animation_manager = SimpleNamespace(is_running=running, timer=Mock(),
                                                 ltha_current_step=7)
        self.vbo_manager = SimpleNamespace(current_anim_factor=-.37)
        self.vbo_manager.set_anim_factor = self.set_factor
        self.current_model = SimpleNamespace(elements={1: object()})
        self.view_deflected = True
        self.view_extruded = True
        self.ltha_mode = ltha
        self.ltha_history = {'1': object()} if ltha else None
        self.ltha_current_step = 7
        self.ltha_n_steps = 20
        self._anim_vbo_built = True
        self._ltha_vbo_built = True
        self._ltha_hinge_cache = object()
        self._undef_frames = object()
        self._sgpu_key = object()
        self._sgpu_mode = 'ext'
        self.display_config = {'extrude_opacity': .35, 'edge_opacity': .08}
        self.invalidate_animation_cache = Mock()
        self.invalidate_area_vbo = Mock()
        self.update = Mock()
        self.rebuilds = []
        self.playback_builds = 0

    def set_factor(self, factor):
        self.vbo_manager.current_anim_factor = factor

    def _force_draw_model(self, model):
        self.rebuilds.append(model)
        self.current_model = model
        self.vbo_manager.current_anim_factor = 0
        self.refresh_deformed_playback()

    def _build_ltha_vbo(self):
        self.playback_builds += 1
        self._ltha_vbo_built = True
        return True

class GraphicsCanvasTests(unittest.TestCase):
    def render(self, alpha):
        manager = _DrawRecorder()
        canvas = SimpleNamespace(view_extruded=True, show_slabs=True, vbo_manager=manager,
                                 display_config={'extrude_opacity': alpha, 'show_edges': True,
                                                 'shell_show_edges': True, 'edge_opacity': .08})
        namespace['render_phases'](canvas, object(), object(), None)
        return manager.calls

    def test_partial_opacity_uses_compositor_instead_of_unsorted_native_draws(self):
        calls = self.render(.35)
        composites = [(i, options) for i, (name, options) in enumerate(calls)
                      if name == 'draw_transparency']
        self.assertEqual(len(composites), 1)
        composite, options = composites[0]
        self.assertTrue(options['include_frames'])
        self.assertTrue(options['include_areas'])
        self.assertFalse(any(name in ('draw','draw_areas','draw_surfaces') for name, _ in calls))
        outlines = [options['alpha_mult'] for name, options in calls if name == 'draw_lines']
        self.assertEqual(outlines, [.08, 1.0])
        grid = next(i for i, (name, _) in enumerate(calls) if name == 'draw_grid_lines')
        edge_passes = [i for i, (name, _) in enumerate(calls) if name == 'draw_lines']
        self.assertLess(grid, composite)
        self.assertLess(edge_passes[0], composite)
        self.assertLess(composite, edge_passes[1])

    def test_one_percent_transparency_still_orders_the_front_surface(self):
        calls = self.render(.99)
        self.assertEqual(sum(name == 'draw_transparency' for name, _ in calls), 1)
        self.assertFalse(any(name in ('draw','draw_areas') for name, _ in calls))

    def test_opaque_surfaces_draw_once_and_zero_alpha_skips_faces(self):
        calls = self.render(1.)
        surfaces = [options for name, options in calls if name in ('draw','draw_areas')]
        self.assertEqual(len(surfaces), 2)
        self.assertTrue(all(not options['transparent'] for options in surfaces))
        self.assertFalse(any(options.get('depth_only') for options in surfaces))
        self.assertFalse(any(name == 'draw_transparency' for name, _ in calls))
        self.assertFalse(any(name in ('draw','draw_areas','draw_transparency')
                             for name, _ in self.render(0.)))

    def test_modal_refresh_keeps_clock_and_current_factor(self):
        canvas = _Canvas(running=True)
        canvas.refresh_graphics_geometry(canvas.current_model)
        self.assertEqual(canvas.rebuilds, [canvas.current_model])
        self.assertTrue(canvas._needs_anim_vbo_build)
        self.assertAlmostEqual(canvas.vbo_manager.current_anim_factor, -.37)
        self.assertTrue(canvas.animation_manager.is_running)
        canvas.animation_manager.timer.assert_not_called()
        self.assertIsNone(canvas._undef_frames)
        self.assertIsNone(canvas._sgpu_key)

    def test_paused_and_running_history_refresh_same_step(self):
        for running in (False, True):
            with self.subTest(running=running):
                canvas = _Canvas(running=running, ltha=True)
                canvas.refresh_graphics_geometry(canvas.current_model)
                self.assertEqual(canvas.playback_builds, 1)
                self.assertEqual(canvas._ltha_pending_t, 7)
                self.assertEqual(canvas.ltha_current_step, 7)
                self.assertEqual(canvas.animation_manager.ltha_current_step, 7)
                self.assertEqual(canvas.animation_manager.is_running, running)
                self.assertTrue(canvas._needs_ltha_vbo_update)
                self.assertTrue(canvas._needs_hinge_refresh)
                self.assertFalse(canvas._needs_anim_vbo_build)
                canvas.animation_manager.timer.assert_not_called()

    def test_static_refresh_rebuilds_without_scheduling_animation(self):
        canvas = _Canvas()
        canvas.refresh_graphics_geometry(canvas.current_model)
        self.assertEqual(len(canvas.rebuilds), 1)
        self.assertFalse(canvas._needs_anim_vbo_build)
        self.assertFalse(canvas._needs_ltha_vbo_update)
        canvas.invalidate_area_vbo.assert_called_once()
        canvas.invalidate_animation_cache.assert_called_once()

    def test_hidden_edge_opacity_does_not_change_static_frame_geometry(self):
        canvas = _Canvas()
        first = canvas._frames_sig(canvas.current_model)
        canvas.display_config['edge_opacity'] = .7
        self.assertEqual(first, canvas._frames_sig(canvas.current_model))

    def test_invisible_edges_leave_shapeless_frame_sticks_visible(self):
        draw = namespace['_draw_elements_extruded']
        node_i = SimpleNamespace(id=1, x=0., y=0., z=0.)
        node_j = SimpleNamespace(id=2, x=1., y=0., z=0.)
        section = SimpleNamespace(color=[.2, .3, .4, .9], get_shape_coords=lambda: [])
        element = SimpleNamespace(node_i=node_i, node_j=node_j, section=section)
        model = SimpleNamespace(elements={1: element}, has_results=False)
        for alpha in (0., .08, 1.):
            with self.subTest(edge_opacity=alpha):
                canvas = SimpleNamespace(display_config={'edge_opacity': alpha},
                                         view_deflected=False, makeCurrent=Mock(),
                                         vbo_manager=Mock(), _end_states=lambda *a: (2, 2))
                draw(canvas, model)
                positions, colors = canvas.vbo_manager.upload_line_geometry.call_args.args
                np.testing.assert_allclose(positions, [[0, 0, 0], [1, 0, 0]])
                np.testing.assert_allclose(colors[:, 3], [.9, .9])

if __name__ == '__main__':
    unittest.main()
