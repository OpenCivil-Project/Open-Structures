"""Camera-only load updates reuse the uploaded topology and packed storage."""
from contextlib import ExitStack
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from app.graphic import _vbo_force_load as module

class Manager(module.ForceLoadMixin):
    is_initialized = True
    load_fill_vao = 11
    load_fill_vbo = 12
    load_fill_ebo = 13
    load_line_vao = 21
    load_line_vbo = 22

class LoadVBOUpdateTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        names = ('glBindVertexArray', 'glBindBuffer', 'glBufferData', 'glBufferSubData',
                 'glVertexAttribPointer', 'glEnableVertexAttribArray')
        self.gl = {name: self.stack.enter_context(patch.object(module, name)) for name in names}
        self.manager = Manager()
        self.fill = np.array([[0., 0., 0.], [1., 0., 0.], [1., 0., 1.]], dtype=np.float32)
        self.fill_colors = np.array([[.2, .3, .4, .5]] * 3, dtype=np.float32)
        self.faces = np.array([[0, 1, 2]], dtype=np.uint32)
        self.lines = np.array([[0., 0., 1.], [0., 0., 0.]], dtype=np.float32)
        self.line_colors = np.array([[.6, .7, .8, 1.]] * 2, dtype=np.float32)
        self.manager.upload_load_geometry(self.fill, self.fill_colors, self.faces,
                                          self.lines, self.line_colors)
        self.reset_gl()

    def reset_gl(self):
        for function in self.gl.values():
            function.reset_mock()

    def assert_no_topology_upload(self):
        self.gl['glBufferData'].assert_not_called()
        self.gl['glBindVertexArray'].assert_not_called()
        self.gl['glVertexAttribPointer'].assert_not_called()
        self.gl['glEnableVertexAttribArray'].assert_not_called()
        self.assertTrue(all(call.args[0] == module.GL_ARRAY_BUFFER
                            for call in self.gl['glBindBuffer'].call_args_list))

    def test_positions_reuse_storage_preserve_colors_and_index_count(self):
        fill_storage = self.manager._load_fill_buffer
        line_storage = self.manager._load_line_buffer
        for offset in (.25, .5, 1.):
            self.assertTrue(self.manager.update_load_positions(self.fill + offset, self.lines - offset))
            self.assertIs(self.manager._load_fill_buffer, fill_storage)
            self.assertIs(self.manager._load_line_buffer, line_storage)
            np.testing.assert_array_equal(fill_storage[:, :3], self.fill + offset)
            np.testing.assert_array_equal(line_storage[:, :3], self.lines - offset)
            np.testing.assert_array_equal(fill_storage[:, 3:6], np.zeros((3, 3)))
            np.testing.assert_array_equal(line_storage[:, 3:6], np.zeros((2, 3)))
            np.testing.assert_array_equal(fill_storage[:, 6:], self.fill_colors)
            np.testing.assert_array_equal(line_storage[:, 6:], self.line_colors)
        self.assertEqual(self.manager.load_fill_index_count, 3)
        self.assertEqual(self.manager.load_line_vertex_count, 2)
        self.assertEqual(self.gl['glBufferSubData'].call_count, 6)
        self.assert_no_topology_upload()
        for call in self.gl['glBufferSubData'].call_args_list:
            self.assertEqual(call.args[0], module.GL_ARRAY_BUFFER)
            self.assertEqual(call.args[1], 0)
            self.assertEqual(call.args[2], call.args[3].nbytes)
            self.assertTrue(call.args[3].flags.c_contiguous)
            self.assertEqual(call.args[3].dtype, np.float32)

    def test_optional_visibility_colors_update_without_topology_changes(self):
        fill_colors = self.fill_colors.copy(); fill_colors[:, 3] = 0.
        line_colors = self.line_colors.copy(); line_colors[:, 3] = .25
        self.assertTrue(self.manager.update_load_positions(self.fill, self.lines,
                                                          fill_colors, line_colors))
        np.testing.assert_array_equal(self.manager._load_fill_buffer[:, 6:], fill_colors)
        np.testing.assert_array_equal(self.manager._load_line_buffer[:, 6:], line_colors)
        self.assertEqual(self.gl['glBufferSubData'].call_count, 2)
        self.assert_no_topology_upload()

    def test_changed_vertex_count_requests_full_upload_before_any_write(self):
        before_fill = self.manager._load_fill_buffer.copy()
        before_line = self.manager._load_line_buffer.copy()
        self.assertFalse(self.manager.update_load_positions(self.fill + 5., np.vstack((self.lines, self.lines))))
        np.testing.assert_array_equal(self.manager._load_fill_buffer, before_fill)
        np.testing.assert_array_equal(self.manager._load_line_buffer, before_line)
        for function in self.gl.values():
            function.assert_not_called()
                                                                                  
        lines = np.vstack((self.lines, self.lines))
        colors = np.vstack((self.line_colors, self.line_colors))
        self.manager.upload_load_geometry(self.fill, self.fill_colors, self.faces, lines, colors)
        self.reset_gl()
        self.assertTrue(self.manager.update_load_positions(self.fill + 5., lines + 5.))
        self.assert_no_topology_upload()

    def test_bad_color_count_does_not_partially_update_positions(self):
        before_fill = self.manager._load_fill_buffer.copy()
        before_line = self.manager._load_line_buffer.copy()
        self.assertFalse(self.manager.update_load_positions(self.fill + 5., self.lines + 5.,
                                                           line_colors=self.line_colors[:1]))
        np.testing.assert_array_equal(self.manager._load_fill_buffer, before_fill)
        np.testing.assert_array_equal(self.manager._load_line_buffer, before_line)
        self.gl['glBufferSubData'].assert_not_called()

    def test_clear_or_uninitialized_manager_cannot_use_stale_topology(self):
        self.manager.clear_load_geometry()
        self.assertFalse(self.manager.update_load_positions(self.fill, self.lines))
        self.assertEqual(self.manager.load_fill_index_count, 0)
        self.assertEqual(self.manager.load_line_vertex_count, 0)
        self.manager.is_initialized = False
        self.assertFalse(self.manager.update_load_positions(self.fill, self.lines))
        self.gl['glBufferSubData'].assert_not_called()

    def test_empty_fixed_buffers_need_no_gpu_upload(self):
        self.manager.upload_load_geometry(np.empty((0, 3)), np.empty((0, 4)),
                                          np.empty((0, 3), dtype=np.uint32),
                                          np.empty((0, 3)), np.empty((0, 4)))
        self.reset_gl()
        self.assertTrue(self.manager.update_load_positions([], []))
        self.gl['glBufferSubData'].assert_not_called()
        self.assert_no_topology_upload()

if __name__ == '__main__':
    unittest.main()
