"""Regression checks for LTHA display routing and history replacement.

Importing MainWindow/Canvas initializes unrelated Qt, OpenGL and application
services. Compile their actual routing/loader methods from the source AST and
provide small UI stubs, so these behavioral checks run headlessly with unittest.
Geometry and scale mathematics have separate tests in test_deformation_scale.py.
"""

import ast
import contextlib
import copy
import io
import math
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]

def _source_methods(path, names):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    owner = next(node for node in tree.body if isinstance(node, ast.ClassDef)
                 and any(isinstance(method, ast.FunctionDef) and method.name in names
                         for method in node.body))
    methods = [method for method in owner.body
               if isinstance(method, ast.FunctionDef) and method.name in names]
    for method in methods:
        method.decorator_list = []
    module = ast.fix_missing_locations(ast.Module(body=methods, type_ignores=[]))
    namespace = {"os": os, "np": np, "math": math}
    exec(compile(module, str(path), "exec"), namespace)
    return {name: namespace[name] for name in names}

class _Signal:
    def __init__(self):
        self.listeners = []

    def connect(self, callback):
        if callback not in self.listeners:
            self.listeners.append(callback)

    def disconnect(self, callback):
        if callback in self.listeners:
            self.listeners.remove(callback)

class _Timer:
    def __init__(self):
        self.active = False

    def stop(self):
        self.active = False

    def start(self, *args):
        self.active = True

class _Manager:
    def __init__(self):
        self.signal_ltha_frame_update = _Signal()
        self.timer = _Timer()
        self.is_running = False
        self.ltha_mode = False
        self.ltha_current_step = 0

    def stop_animation(self):
        self.is_running = False
        self.timer.stop()

    def start_animation(self):
        self.is_running = True
        self.timer.start()

    def set_speed(self, speed):
        self.speed_factor = speed

    def disable_ltha_mode(self):
        self.ltha_mode = False

    def enable_ltha_mode(self, n_steps, dt):
        self.ltha_mode = True
        self.ltha_current_step = 0

    def invalidate_prerender(self):
        pass

class _Canvas:
    def __init__(self):
        self.animation_manager = _Manager()
        self.view_deflected = True
        self.ltha_mode = False
        self.ltha_history = None
        self.ltha_n_steps = 0
        self.ltha_dt = 0.01
        self.ltha_current_step = 0
        self.ltha_hinge_state_idx = None
        self.ltha_highlight = None
        self.ltha_accel = None
        self._ltha_loaded_case = None

    def _on_ltha_frame(self, index):
        self.ltha_current_step = index

    def invalidate_deflection_cache(self):
        pass

    def invalidate_animation_cache(self):
        pass

    def refresh_deformed_playback(self):
        pass

    def set_selection_ltha_live(self, active):
        self._selection_ltha_live = active

class _Status:
    def __init__(self):
        self.message = ""

    def showMessage(self, message, *args):
        self.message = message

    def currentMessage(self):
        return self.message

class _Harness:
    def __init__(self, results):
        self.canvas = _Canvas()
        self.canvas2 = _Canvas()
        self.active_canvas = self.canvas
        self.model = SimpleNamespace(results=results)
        self.status = _Status()
        self._deformed_dlg = None
        self._node_res_dlg = None
        self._last_force_diagram_settings = {}
        self.scale_calls = []
        self.sound_effect = SimpleNamespace(isPlaying=lambda: False)

    def _compute_auto_scale(self, displacements, **kwargs):
        self.scale_calls.append(kwargs)
        return 0.03125

    def _attach_hinge_state_history(self, data):
        pass

    def _on_ltha_frame_tick(self, index):
        pass

    def draw_both_canvases(self):
        pass

class LthaPlaybackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        for name, method in _source_methods(
                ROOT / "app/main.py",
                {"switch_modal_view", "_teardown_ltha_playback", "_results_status_text",
                 "toggle_animation", "set_animation_speed", "_on_ltha_frame_tick"}).items():
            setattr(_Harness, name, method)
        for name, method in _source_methods(
                ROOT / "app/canvas.py", {"load_ltha_history", "clear_ltha_history"}).items():
            setattr(_Canvas, name, method)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="ltha-playback-test-")
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "a.npz"
        np.savez(self.path, node_1=np.full((3, 6), 10.0))
        self.harness = _Harness(self.result(self.path))
        self.log = contextlib.redirect_stdout(io.StringIO())
        self.log.__enter__()
        self.addCleanup(self.log.__exit__, None, None, None)

    @staticmethod
    def result(path, case="A"):
        return {
            "info": {"type": "Linear Time History Analysis", "case_name": case, "dt": 0.01},
            "displacements": {"1": [10.0] * 6},
            "history_path": str(path),
        }

    def live(self):
        self.harness.switch_modal_view("LTHA_LIVE")
        return self.harness.canvas

    def assert_envelope(self):
        for canvas in (self.harness.canvas, self.harness.canvas2):
            self.assertFalse(canvas.ltha_mode)
            self.assertIsNone(canvas.ltha_history)
            self.assertFalse(canvas.animation_manager.ltha_mode)

    def nonlinear_result(self):
        return {
            "info": {"type": "Nonlinear Static", "case_name": "NS"},
            "displacements": {"1": [2.0] * 6},
            "saved_states": [
                {"displacements": {"1": [1.0] * 6}},
                {"displacements": {"1": [2.0] * 6}},
            ],
        }

    def test_live_loads_current_history(self):
        canvas = self.live()
        self.assertTrue(canvas.ltha_mode)
        self.assertEqual(canvas.ltha_n_steps, 3)
        np.testing.assert_array_equal(canvas.ltha_history["1"], np.full((3, 6), 10.0))
        self.assertIs(self.harness.scale_calls[-1]["history"], canvas.ltha_history)

    def test_fractional_scale_reaches_both_canvases(self):
        self.live()
        for canvas in (self.harness.canvas, self.harness.canvas2):
            self.assertEqual(canvas.deflection_scale, 0.03125)
            self.assertEqual(canvas.auto_deflection_scale, 0.03125)

    def test_live_canvases_share_the_same_history(self):
        self.live()
        self.assertTrue(self.harness.canvas2.ltha_mode)
        self.assertIs(self.harness.canvas2.ltha_history, self.harness.canvas.ltha_history)
        self.assertEqual(self.harness.canvas2.ltha_n_steps, 3)

    def test_pause_after_switching_canvas_stops_the_primary_clock(self):
        self.live()
        self.harness.toggle_animation(True, False)
        self.assertTrue(self.harness.canvas.animation_manager.is_running)
        self.harness.active_canvas = self.harness.canvas2
        self.harness.toggle_animation(False, False)
        self.assertFalse(self.harness.canvas.animation_manager.is_running)
        self.assertFalse(self.harness.canvas2.animation_manager.is_running)

    def test_play_from_secondary_uses_only_primary_clock_and_speed(self):
        self.live()
        self.harness.active_canvas = self.harness.canvas2
        self.harness.toggle_animation(True, False)
        self.harness.set_animation_speed(2.0)
        self.assertTrue(self.harness.canvas.animation_manager.is_running)
        self.assertFalse(self.harness.canvas2.animation_manager.is_running)
        self.assertEqual(self.harness.canvas.animation_manager.speed_factor, 2.0)

    def test_live_frame_tick_keeps_both_views_on_same_step(self):
        self.live()
        self.harness.canvas._on_ltha_frame(2)
        self.harness._on_ltha_frame_tick(2)
        self.assertEqual(self.harness.canvas2.ltha_current_step, 2)
        self.assertEqual(self.harness.canvas2.animation_manager.ltha_current_step, 2)

    def test_changed_time_step_reloads_same_history(self):
        old = self.live().ltha_history
        self.harness.model.results['info']['dt'] = 0.02
        self.live()
        self.assertIsNot(self.harness.canvas.ltha_history, old)
        self.assertEqual(self.harness.canvas.ltha_dt, 0.02)

    def test_empty_saved_states_display_the_static_result(self):
        self.harness.model.results = self.nonlinear_result()
        self.harness.model.results['saved_states'] = []
        self.harness.switch_modal_view('MAIN_RESULT')
        self.assert_envelope()

    def test_envelope_stops_and_clears_both_live_canvases(self):
        self.live()
        for canvas in (self.harness.canvas, self.harness.canvas2):
            canvas.animation_manager.is_running = True
            canvas.animation_manager.timer.start()
        self.harness.switch_modal_view("MAIN_RESULT")
        self.assert_envelope()
        for canvas in (self.harness.canvas, self.harness.canvas2):
            self.assertFalse(canvas.animation_manager.is_running)
            self.assertFalse(canvas.animation_manager.timer.active)
            self.assertFalse(canvas._selection_ltha_live)
        self.assertIsNone(self.harness.scale_calls[-1]["history"])

    def test_live_reloads_after_envelope(self):
        old = self.live().ltha_history
        self.harness.switch_modal_view("MAIN_RESULT")
        self.live()
        self.assertIsNot(self.harness.canvas.ltha_history, old)
        self.assertEqual(self.harness.canvas.ltha_n_steps, 3)

    def test_same_case_with_different_archive_reloads(self):
        self.live()
        second = self.path.with_name("b.npz")
        np.savez(second, node_1=np.full((4, 6), 25.0))
        self.harness.model.results = self.result(second)
        canvas = self.live()
        self.assertEqual(canvas.ltha_n_steps, 4)
        self.assertEqual(canvas.ltha_history["1"][0, 0], 25.0)

    def test_same_case_with_overwritten_archive_reloads(self):
        self.live()
        np.savez(self.path, node_1=np.full((5, 6), 30.0))
        self.harness.model.results = self.result(self.path)
        canvas = self.live()
        self.assertEqual(canvas.ltha_n_steps, 5)
        self.assertEqual(canvas.ltha_history["1"][0, 0], 30.0)

    def test_unchanged_live_source_keeps_current_history(self):
        old = self.live().ltha_history
        self.live()
        self.assertIs(self.harness.canvas.ltha_history, old)

    def test_missing_archive_falls_back_to_envelope(self):
        self.live()
        self.harness.model.results = self.result(self.path.with_name("missing.npz"), "Missing")
        self.live()
        self.assert_envelope()
        self.assertIn("envelope", self.harness.status.currentMessage())

    def test_corrupt_archive_falls_back_to_envelope(self):
        self.live()
        corrupt = self.path.with_name("corrupt.npz")
        corrupt.write_bytes(b"invalid archive")
        self.harness.model.results = self.result(corrupt, "Corrupt")
        self.live()
        self.assert_envelope()
        self.assertIn("envelope", self.harness.status.currentMessage())

    def test_nonlinear_main_view_preserves_last_step_playback(self):
        self.harness.model.results = self.nonlinear_result()
        self.harness.switch_modal_view("MAIN_RESULT")
        self.assertTrue(self.harness.canvas.ltha_mode)
        self.assertEqual(self.harness.canvas.ltha_current_step, 1)
        self.assertEqual(self.harness.canvas.animation_manager.ltha_current_step, 1)
        self.assertEqual(self.harness.model.results["displacements"]["1"], [2.0] * 6)

    def test_nonlinear_steps_are_shared_and_selected_on_secondary_canvas(self):
        self.harness.model.results = self.nonlinear_result()
        self.harness.switch_modal_view("MAIN_RESULT")
        self.assertTrue(self.harness.canvas2.ltha_mode)
        self.assertIs(self.harness.canvas2.ltha_history, self.harness.canvas.ltha_history)
        self.assertEqual(self.harness.canvas2.ltha_current_step, 1)

    def test_modal_switch_clears_previous_live_case(self):
        self.live()
        self.harness.model.results = {
            "info": {"type": "Modal Analysis", "case_name": "M"},
            "mode_shapes": {"Mode 1": {"1": [0.1] * 6}},
        }
        self.harness.switch_modal_view("Mode 1")
        self.assert_envelope()
        self.assertEqual(self.harness.model.results["displacements"]["1"], [0.1] * 6)

    def test_replacing_history_discards_stale_tensor_and_pending_frame(self):
        canvas = self.harness.canvas
        canvas.ltha_tensor = np.zeros((1, 2, 6))
        canvas.ltha_node_map = {"old": 0}
        canvas.ltha_engine = object()
        canvas._ltha_pending_t = 100
        canvas._needs_ltha_vbo_update = True
        self.assertTrue(canvas.load_ltha_history(self.path, 0.01))
        for name in ("ltha_tensor", "ltha_node_map", "ltha_engine"):
            self.assertFalse(hasattr(canvas, name))
        self.assertEqual(canvas._ltha_pending_t, 0)
        self.assertFalse(canvas._needs_ltha_vbo_update)

    def test_invalid_timestep_clears_previous_history(self):
        for dt in (0.0, -0.1, float("nan"), float("inf")):
            with self.subTest(dt=dt):
                canvas = self.live()
                self.assertFalse(canvas.load_ltha_history(self.path, dt))
                self.assertFalse(canvas.ltha_mode)
                self.assertIsNone(canvas.ltha_history)

    def test_inconsistent_node_history_lengths_are_rejected(self):
        np.savez(self.path, node_1=np.zeros((3, 6)), node_2=np.zeros((2, 6)))
        self.assertFalse(self.harness.canvas.load_ltha_history(self.path, 0.01))
        self.assertIsNone(self.harness.canvas.ltha_history)

    def test_nonfinite_displacements_are_rejected(self):
        for value in (float("nan"), float("inf")):
            with self.subTest(value=value):
                np.savez(self.path, node_1=np.full((1, 6), value))
                self.assertFalse(self.harness.canvas.load_ltha_history(self.path, 0.01))
                self.assertIsNone(self.harness.canvas.ltha_history)

    def test_archive_without_node_displacements_is_rejected(self):
        np.savez(self.path, velocity_1=np.zeros((3, 6)))
        self.assertFalse(self.harness.canvas.load_ltha_history(self.path, 0.01))
        self.assertIsNone(self.harness.canvas.ltha_history)

class LthaPlaybackRangeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.select_range = staticmethod(_source_methods(
            ROOT / 'app/main.py', {'set_ltha_playback_range'})['set_ltha_playback_range'])

    def setUp(self):
        from post.animation import AnimationManager
        self.manager = AnimationManager()
        with contextlib.redirect_stdout(io.StringIO()):
            self.manager.enable_ltha_mode(501, 0.01)
        self.secondary_manager = AnimationManager()
        self.refreshes = []

        def canvas(manager):
            return SimpleNamespace(animation_manager=manager, ltha_mode=True,
                                   ltha_n_steps=501, ltha_dt=0.01,
                                   _invalidate_accel_pixmap=lambda: self.refreshes.append('overlay'),
                                   update=lambda: self.refreshes.append('draw'))

        self.window = SimpleNamespace(canvas=canvas(self.manager),
                                      canvas2=canvas(self.secondary_manager))

    def test_seconds_select_inclusive_loop_and_highlight_both_views(self):
        self.assertTrue(self.select_range(self.window, 1.5, 2.5))
        self.assertEqual(self.manager.ltha_playback_start, 150)
        self.assertEqual(self.manager.ltha_playback_end, 250)
        self.assertEqual(self.manager.ltha_current_step, 150)
        for cvs in (self.window.canvas, self.window.canvas2):
            self.assertEqual(cvs.ltha_highlight, (1.5, 2.5))
            self.assertEqual(cvs.animation_manager.ltha_playback_start, 150)
        self.assertEqual(len(self.refreshes), 4)

    def test_full_range_clears_custom_loop_and_highlights(self):
        self.select_range(self.window, 1.5, 2.5)
        self.assertTrue(self.select_range(self.window, 0.0, 5.0))
        self.assertIsNone(self.manager.ltha_playback_start)
        self.assertIsNone(self.manager.ltha_playback_end)
        self.assertIsNone(self.window.canvas.ltha_highlight)
        self.assertIsNone(self.window.canvas2.ltha_highlight)

    def test_invalid_range_retains_last_valid_loop(self):
        self.select_range(self.window, 1.5, 2.5)
        for start, end in ((3.0, 2.0), (float('nan'), 2.0), (1.0, float('inf'))):
            with self.subTest(start=start, end=end):
                self.assertFalse(self.select_range(self.window, start, end))
                self.assertEqual(self.manager.ltha_playback_start, 150)
                self.assertEqual(self.manager.ltha_playback_end, 250)

    def test_nonlinear_step_playback_uses_step_indices(self):
        self.window.canvas.ltha_dt = 1.0
        self.assertTrue(self.select_range(self.window, 2.0, 5.0))
        self.assertEqual(self.manager.ltha_playback_start, 2)
        self.assertEqual(self.manager.ltha_playback_end, 5)

class LthaVisualNormalizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.normalizer = staticmethod(_source_methods(
            ROOT / 'app/main.py', {'_compute_auto_scale'})['_compute_auto_scale'])

    def setUp(self):
        node_i = SimpleNamespace(id=1, x=0.0, y=0.0, z=0.0)
        node_j = SimpleNamespace(id=2, x=24.0, y=0.0, z=0.0)
        self.displacements = {'2': [12.0, 0.0, 0.0, 0.0, 0.0, 0.0]}
        self.model = SimpleNamespace(
            nodes={1: node_i, 2: node_j}, elements={},
            results={'info': {'type': 'Linear Time History Analysis'},
                     'displacements': self.displacements,
                     'displacements_abs': copy.deepcopy(self.displacements)},
        )
        self.window = SimpleNamespace(model=self.model)

    def test_ltha_visual_scale_is_halved_without_modifying_results(self):
        from post.deformation_scale import compute_deformation_scale
        before = copy.deepcopy(self.model.results)
        original = compute_deformation_scale(self.model, self.displacements)
        reduced = self.normalizer(self.window, self.displacements)
        self.assertAlmostEqual(reduced, original / 2.0)
        self.assertEqual(self.model.results, before)

    def test_ltha_envelope_and_live_keep_the_same_reduced_factor(self):
        history = {'2': np.array([[0.0] * 6, self.displacements['2'], [0.0] * 6])}
        before = history['2'].copy()
        envelope = self.normalizer(self.window, self.displacements)
        live = self.normalizer(self.window, self.displacements, history=history)
        self.assertEqual(envelope, live)
        np.testing.assert_array_equal(history['2'], before)

    def test_other_analysis_types_keep_the_original_normalization(self):
        from post.deformation_scale import compute_deformation_scale
        original = compute_deformation_scale(self.model, self.displacements)
        for result_type in ('Linear Static', 'Modal Analysis', 'Response Spectrum Analysis',
                            'Nonlinear Static', 'Buckling Analysis', ''):
            with self.subTest(result_type=result_type):
                self.model.results['info']['type'] = result_type
                self.assertEqual(self.normalizer(self.window, self.displacements), original)

if __name__ == "__main__":
    unittest.main()
