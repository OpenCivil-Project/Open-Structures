"""Regression checks for exact front coverage and lazy GPU transparency."""

import itertools
import math
import unittest
from unittest.mock import DEFAULT, patch

import numpy as np

from app.graphic import _vbo_transparency as transparency

def composite_reference(front_alpha, tail_layers):
    accum = np.zeros(3)
    accum_alpha = optical = 0.0
    for color, alpha, depth_delta in tail_layers:
        weight = min(100.0, max(0.01, (0.01 + alpha) / (0.01 + 1000 * depth_delta)))
        accum += np.asarray(color) * alpha * weight
        accum_alpha += alpha * weight
        optical -= math.log(max(1 - alpha, 1e-6))
    tail_alpha = 1 - math.exp(-optical)
    color = np.array([1.0, 0.0, 0.0]) * front_alpha
    color += accum / max(accum_alpha, 1e-6) * (1 - front_alpha) * tail_alpha
    return color, front_alpha + (1 - front_alpha) * tail_alpha

class FakeManager(transparency.TransparencyMixin):
    is_initialized = True
    index_count = 6
    area_index_count = 3

    def __init__(self):
        self.geometry = []

    def _transparency_save_state(self):
        return {'draw_fbo': 100, 'read_fbo': 200, 'viewport': (2, 3, 640, 480)}

    def _transparency_restore_state(self, state):
        self.restored = state

    def _ensure_transparency_targets(self, width, height):
        self._transparency_targets = {
            'scene_fbo': 10, 'front_fbo': 11, 'tail_fbo': 12,
            'front_color': 20, 'front_depth': 21, 'tail_accum': 22, 'tail_optical': 23,
        }

    def _ensure_transparency_composite(self):
        self._transparency_composite_program = 30
        self._transparency_composite_vao = 31
        self._transparency_composite_locations = {name: i for i, name in enumerate(
            ('u_front_color', 'u_front_depth', 'u_tail_accum', 'u_tail_optical', 'u_viewport_origin'))}

    def draw(self, view, proj, light=None, transparent=True):
        self.geometry.append(('frames', self._transparency_stage, transparent))

    def draw_areas(self, view, proj, light=None, transparent=True):
        self.geometry.append(('areas', self._transparency_stage, transparent))

class GPUTransparencyTests(unittest.TestCase):
    def test_front_opacity_bounds_rear_visibility_at_user_slider_values(self):
        for slider_percent in (1, 24, 50):
            alpha = 1 - slider_percent / 100.0
            tail = [((0, 0, 1), alpha, 0.001 * (i + 1)) for i in range(8)]
            color, coverage = composite_reference(alpha, tail)
            self.assertAlmostEqual(color[0], alpha)
            self.assertLessEqual(color[2], slider_percent / 100.0 + 1e-12)
            self.assertGreater(color[2], 0)
            self.assertLessEqual(coverage, 1)

    def test_tail_is_order_independent_and_zero_alpha_contributes_nothing(self):
        layers = [((0, 1, 0), 0.5, 0.002), ((0, 0, 1), 0.3, 0.003), ((1, 1, 1), 0, 0.001)]
        expected = composite_reference(0.4, layers)
        for ordering in itertools.permutations(layers):
            actual = composite_reference(0.4, ordering)
            np.testing.assert_allclose(actual[0], expected[0])
            self.assertAlmostEqual(actual[1], expected[1])

    def test_shader_adaptation_retains_existing_color_and_adds_two_additive_outputs(self):
        source = '#version 330 core\nout vec4 FragColor;\nvoid main(){FragColor=vec4(0.2,0.4,0.6,0.5);}'
        adapted = transparency.tail_fragment_source(source)
        self.assertIn('FragColor=vec4(0.2,0.4,0.6,0.5);', adapted)
        self.assertIn('layout(location = 0) out vec4 FragColor;', adapted)
        self.assertIn('layout(location = 1) out vec4 TailDepth;', adapted)
        self.assertIn('gl_FragCoord.z <= nearest_depth + 1e-7', adapted)
        self.assertIn('-log(max(1.0 - tail_a, 1e-6))', adapted)
        self.assertTrue(adapted.rstrip().endswith('}'))
        with self.assertRaises(ValueError):
            transparency.tail_fragment_source('void main(){}')

    def test_targets_are_created_once_and_reallocated_only_on_resize(self):
        manager = transparency.TransparencyMixin()
        names = ('glGenTextures', 'glGenFramebuffers', 'glBindTexture', 'glTexImage2D', '_raw_glTexImage2D',
                 'glTexParameteri', 'glBindFramebuffer', 'glFramebufferTexture2D',
                 'glDrawBuffers', 'glDrawBuffer', 'glReadBuffer', 'glCheckFramebufferStatus',
                 'glDeleteTextures', 'glDeleteFramebuffers')
        with patch.multiple(transparency, **{name: DEFAULT for name in names}) as mocks:
            ids = itertools.count(1)
            mocks['glGenTextures'].side_effect = lambda count: next(ids)
            mocks['glGenFramebuffers'].side_effect = lambda count: next(ids)
            mocks['glCheckFramebufferStatus'].return_value = transparency.GL_FRAMEBUFFER_COMPLETE
            manager._ensure_transparency_targets(640, 480)
            manager._ensure_transparency_targets(640, 480)
            self.assertEqual(mocks['glTexImage2D'].call_count + mocks['_raw_glTexImage2D'].call_count, 5)
            self.assertEqual(mocks['_raw_glTexImage2D'].call_count, 2)
            self.assertEqual(mocks['glGenFramebuffers'].call_count, 3)
            manager._ensure_transparency_targets(800, 600)
            self.assertEqual(mocks['glTexImage2D'].call_count + mocks['_raw_glTexImage2D'].call_count, 10)
            mocks['glDeleteTextures'].assert_called_once()
            mocks['glDeleteFramebuffers'].assert_called_once()

    def test_two_native_geometry_passes_then_one_composite_and_state_restore(self):
        manager = FakeManager()
        view = np.eye(4, dtype=np.float32)
        names = ('glDisable', 'glEnable', 'glColorMask', 'glBindFramebuffer', 'glBlitFramebuffer',
                 'glViewport', 'glClearBufferfv', 'glDepthFunc', 'glDepthMask', 'glBlendEquation',
                 'glBlendFunc', 'glUseProgram', 'glActiveTexture', 'glBindTexture', 'glUniform1i',
                 'glUniform2i', 'glBindVertexArray', 'glDrawArrays')
        with patch.multiple(transparency, **{name: DEFAULT for name in names}) as mocks:
            self.assertTrue(manager.draw_transparency(view, view))
            self.assertEqual(manager.geometry, [
                ('frames', 'front', False), ('areas', 'front', False),
                ('frames', 'tail', True), ('areas', 'tail', True),
            ])
            self.assertEqual(mocks['glBlitFramebuffer'].call_count, 2)
            mocks['glBlitFramebuffer'].assert_called_with(
                2, 3, 642, 483, 0, 0, 640, 480, transparency.GL_DEPTH_BUFFER_BIT, transparency.GL_NEAREST)
            mocks['glDrawArrays'].assert_called_once_with(transparency.GL_TRIANGLES, 0, 3)
            mocks['glDepthFunc'].assert_called_once_with(transparency.GL_ALWAYS)
            mocks['glBlendFunc'].assert_called_once_with(transparency.GL_ONE, transparency.GL_ONE_MINUS_SRC_ALPHA)
            self.assertEqual(manager.restored['read_fbo'], 200)
            self.assertIsNone(manager._transparency_stage)

    def test_empty_or_uninitialized_manager_creates_no_gpu_resources(self):
        manager = FakeManager()
        manager.is_initialized = False
        with patch.object(manager, '_transparency_save_state', side_effect=AssertionError('GPU work')):
            self.assertFalse(manager.draw_transparency(None, None))
            manager.is_initialized = True
            manager.index_count = manager.area_index_count = 0
            self.assertFalse(manager.draw_transparency(None, None))

    def test_setup_failure_is_explicit_and_restores_stage_and_framebuffer(self):
        manager = FakeManager()
        manager._transparency_stage = 'previous'
        with patch.multiple(transparency, glDisable=DEFAULT, glColorMask=DEFAULT, glActiveTexture=DEFAULT),\
                patch.object(manager, '_ensure_transparency_targets', side_effect=RuntimeError('allocation failed')):
            with self.assertRaisesRegex(RuntimeError, 'GPU transparency rendering failed: allocation failed'):
                manager.draw_transparency(None, None)
            self.assertEqual(manager._transparency_stage, 'previous')
            self.assertEqual(manager.restored['draw_fbo'], 100)

if __name__ == '__main__':
    unittest.main()
