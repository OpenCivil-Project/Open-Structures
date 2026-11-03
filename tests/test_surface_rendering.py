"""Native VBO transparency must retain rear surfaces without CPU sorting."""

from contextlib import contextmanager, ExitStack
import unittest
from unittest.mock import DEFAULT, Mock, patch

import numpy as np

from app.graphic import _vbo_area as area
from app.graphic import _vbo_extruded as extruded

class FakeManager(extruded.ExtrudedMixin, area.AreaMixin):
    is_initialized = True
    current_anim_factor = 0.4
    shader_program = 1
    loc_view, loc_proj, loc_alpha, loc_anim = 1, 2, 3, 4
    vao, vbo, ebo = 10, 11, 12
    area_vao, area_vbo, area_ebo = 20, 21, 22
    area_edge_vao, area_edge_vbo = 30, 31
    index_count, area_index_count = 6, 3
    persistent_ext_buffer = None
    ext_owner = 'static'

    def _use_lit_program(self, *args):
        return False

@contextmanager
def mocked_gl():
    """Record the state at every draw/upload without creating an OpenGL context."""
    state, draws, uploads, updates = {}, [], [], []
    names = ('glBindVertexArray', 'glBindBuffer', 'glVertexAttribPointer',
             'glEnableVertexAttribArray', 'glBufferData', 'glBufferSubData',
             'glGenVertexArrays', 'glGenBuffers', 'glUseProgram',
             'glUniformMatrix4fv', 'glUniform1f', 'glEnable', 'glDisable',
             'glColorMask', 'glPolygonOffset', 'glDepthMask', 'glDepthFunc',
             'glDrawElements', 'glBlendFunc')
    with ExitStack() as stack:
        mocks = []
        for module in (extruded, area):
            module_mocks = stack.enter_context(patch.multiple(module, **{name: DEFAULT for name in names}))
            module_mocks['glBindVertexArray'].side_effect = lambda value: state.update(vao=value)
            module_mocks['glDepthMask'].side_effect = lambda value: state.update(depth_write=bool(value))
            module_mocks['glDepthFunc'].side_effect = lambda value: state.update(depth_func=value)
            module_mocks['glColorMask'].side_effect = lambda *values: state.update(color_write=tuple(bool(v) for v in values))
            module_mocks['glDrawElements'].side_effect = lambda mode, count, dtype, offset: draws.append(
                (state['vao'], count, state['depth_write'], state['color_write']))
            module_mocks['glBufferData'].side_effect = lambda target, size, data, usage: uploads.append(
                (target, size, np.asarray(data).copy()))
            module_mocks['glBufferSubData'].side_effect = lambda target, offset, size, data: updates.append(
                (target, offset, size, np.asarray(data).copy()))
            mocks.append(module_mocks)
        yield state, draws, uploads, updates, mocks

class SurfaceRenderingTests(unittest.TestCase):
    def setUp(self):
        self.manager = FakeManager()
        self.view = np.eye(4, dtype=np.float32)

    def test_transparent_frame_and_shell_colors_draw_once_without_depth_writes(self):
        with mocked_gl() as (state, draws, uploads, updates, mocks):
            self.manager.draw(self.view, self.view)
            self.manager.draw_areas(self.view, self.view)
            self.assertEqual(draws, [
                (10, 6, False, (True, True, True, True)),
                (20, 3, False, (True, True, True, True)),
            ])
            self.assertTrue(state['depth_write'])
            self.assertEqual(state['depth_func'], extruded.GL_LESS)
            self.assertEqual(state['color_write'], (True, True, True, True))
            for module_mocks in mocks:
                module_mocks['glBlendFunc'].assert_called_once_with(extruded.GL_SRC_ALPHA, extruded.GL_ONE_MINUS_SRC_ALPHA)
            self.assertEqual(uploads + updates, [])

    def test_opaque_frame_and_shell_colors_write_depth(self):
        with mocked_gl() as (_, draws, _, _, _):
            self.manager.draw(self.view, self.view, transparent=False)
            self.manager.draw_areas(self.view, self.view, transparent=False)
            self.assertEqual(draws, [
                (10, 6, True, (True, True, True, True)),
                (20, 3, True, (True, True, True, True)),
            ])

    def test_post_color_depth_classification_preserves_the_color_pass(self):
        with mocked_gl() as (state, draws, _, _, _):
            self.manager.draw(self.view, self.view)
            self.manager.draw_areas(self.view, self.view)
            self.manager.draw(self.view, self.view, depth_only=True)
            self.manager.draw_area_depth_prepass(self.view, self.view)
            self.assertEqual(draws, [
                (10, 6, False, (True, True, True, True)),
                (20, 3, False, (True, True, True, True)),
                (10, 6, True, (False, False, False, False)),
                (20, 3, True, (False, False, False, False)),
            ])
            self.assertTrue(state['depth_write'])
            self.assertEqual(state['color_write'], (True, True, True, True))

    def test_depth_only_uses_existing_flat_shader_without_lighting_work(self):
        self.manager._use_lit_program = Mock(side_effect=AssertionError('depth-only lighting'))
        with mocked_gl() as (_, draws, _, _, mocks):
            self.manager.draw(self.view, self.view, light={'enabled': True}, depth_only=True)
            self.manager.draw_areas(self.view, self.view, light={'enabled': True}, depth_only=True)
            self.assertEqual(len(draws), 2)
            self.manager._use_lit_program.assert_not_called()
            for module_mocks in mocks:
                self.assertEqual(module_mocks['glUseProgram'].call_args_list[0].args, (self.manager.shader_program,))

    def test_drawing_reuses_native_buffers_without_cpu_sorting_or_allocations(self):
        with mocked_gl() as (_, draws, uploads, updates, mocks),\
                patch.object(np, 'argsort', side_effect=AssertionError('CPU sorting')),\
                patch.object(np, 'concatenate', side_effect=AssertionError('combined copies')):
            for _ in range(3):
                self.manager.draw(self.view, self.view)
                self.manager.draw_areas(self.view, self.view)
            self.assertEqual(len(draws), 6)
            self.assertEqual(uploads + updates, [])
            for module_mocks in mocks:
                module_mocks['glGenVertexArrays'].assert_not_called()
                module_mocks['glGenBuffers'].assert_not_called()
            self.assertFalse(hasattr(self.manager, '_surface_batches'))

    def test_empty_batches_do_not_draw(self):
        self.manager.index_count = self.manager.area_index_count = 0
        with mocked_gl() as (_, draws, _, _, _):
            self.manager.draw(self.view, self.view)
            self.manager.draw_areas(self.view, self.view, depth_only=True)
            self.assertEqual(draws, [])

    def test_original_frame_upload_keeps_thirteen_float_vertex_layout(self):
        vertices = np.arange(9, dtype=np.float32).reshape(3, 3)
        displacements = vertices * 0.1
        colors = np.tile([0.1, 0.2, 0.3, 0.4], (3, 1)).astype(np.float32)
        normals = np.tile([1, 0, 0], (3, 1)).astype(np.float32)
        faces = np.array([[0, 1, 2]], dtype=np.uint32)
        with mocked_gl() as (_, _, uploads, _, mocks):
            self.manager.upload_extruded_geometry(vertices, colors, faces, displacements, normals)
            self.assertEqual(len(uploads), 2)
            target, size, data = uploads[0]
            self.assertEqual((target, size), (extruded.GL_ARRAY_BUFFER, 3 * 13 * 4))
            data = data.reshape(-1, 13)
            np.testing.assert_array_equal(data[:, :3], vertices)
            np.testing.assert_array_equal(data[:, 3:6], displacements)
            np.testing.assert_array_equal(data[:, 6:10], colors)
            np.testing.assert_array_equal(data[:, 10:13], normals)
            np.testing.assert_array_equal(uploads[1][2], faces.reshape(-1))
            self.assertEqual(self.manager.ext_owner, 'static')
            mocks[0]['glGenBuffers'].assert_not_called()

    def test_original_shell_upload_keeps_native_face_and_edge_layouts(self):
        vertices = np.arange(9, dtype=np.float32).reshape(3, 3)
        colors = np.tile([0.1, 0.2, 0.3, 0.4], (3, 1)).astype(np.float32)
        faces = np.array([[0, 1, 2]], dtype=np.uint32)
        edges, edge_colors = vertices[:2], colors[:2]
        with mocked_gl() as (_, _, uploads, _, _):
            self.manager.upload_area_geometry(vertices, colors, faces, edges, edge_colors)
            self.assertEqual([entry[1] for entry in uploads], [3 * 13 * 4, 3 * 4, 2 * 10 * 4])
            np.testing.assert_array_equal(uploads[0][2].reshape(-1, 13)[:, :3], vertices)
            np.testing.assert_array_equal(uploads[2][2].reshape(-1, 10)[:, 6:10], edge_colors)

    def test_playback_updates_original_vbo_once_without_reallocation(self):
        self.manager.ext_owner = 'ltha'
        self.manager.persistent_ext_buffer = np.zeros(3 * 13, dtype=np.float32)
        self.manager.persistent_ext_buffer[12::13] = 1
        vertices = np.arange(9, dtype=np.float32)
        colors = np.tile([0.1, 0.2, 0.3, 0.4], 3).astype(np.float32)
        with mocked_gl() as (_, _, uploads, updates, mocks):
            self.assertTrue(self.manager.fast_update_extruded(vertices, colors))
            self.assertEqual(uploads, [])
            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0][:3], (extruded.GL_ARRAY_BUFFER, 0, 3 * 13 * 4))
            data = updates[0][3].reshape(-1, 13)
            np.testing.assert_array_equal(data[:, :3], vertices.reshape(-1, 3))
            np.testing.assert_array_equal(data[:, 6:10], colors.reshape(-1, 4))
            np.testing.assert_array_equal(data[:, 12], np.ones(3))
            mocks[0]['glBindBuffer'].assert_called_once_with(extruded.GL_ARRAY_BUFFER, self.manager.vbo)
            mocks[0]['glGenBuffers'].assert_not_called()
            self.assertFalse(hasattr(self.manager, '_surface_batches'))

if __name__ == '__main__':
    unittest.main()
