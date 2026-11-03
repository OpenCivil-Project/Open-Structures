import numpy as np
from OpenGL.GL import *
import ctypes

def _interleave_force_vertices(positions, colors):
    """Pack static vertices once in the layout shared by the force shaders."""
    if not len(positions):
        return np.empty(0, dtype=np.float32)
    packed = np.empty((len(positions), 10), dtype=np.float32)
    packed[:, :3] = positions
    packed[:, 3:6] = 0.0
    packed[:, 6:] = colors
    return packed.ravel()

def prepare_force_geometry(fill_verts, fill_colors, fill_faces, line_pos, line_colors):
    """Prepare CPU buffers off the GUI thread; no OpenGL context is needed."""
    return {
        'fill_buffer': _interleave_force_vertices(fill_verts, fill_colors),
        'fill_indices': np.ascontiguousarray(fill_faces, dtype=np.uint32).ravel(),
        'line_buffer': _interleave_force_vertices(line_pos, line_colors),
    }

class ForceLoadMixin:
    def upload_force_geometry(self, fill_verts, fill_colors, fill_faces, line_pos, line_colors,
                              prepared=None):
        if not self.is_initialized:
            return

        if prepared is None:
            prepared = prepare_force_geometry(fill_verts, fill_colors, fill_faces,
                                              line_pos, line_colors)

        if len(fill_verts) > 0:
            interleaved = prepared['fill_buffer']
            indices = prepared['fill_indices']
            self.force_fill_index_count = len(indices)

            glBindVertexArray(self.force_fill_vao)
            glBindBuffer(GL_ARRAY_BUFFER, self.force_fill_vbo)
            glBufferData(GL_ARRAY_BUFFER, interleaved.nbytes, interleaved, GL_STATIC_DRAW)
            glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, self.force_fill_ebo)
            glBufferData(GL_ELEMENT_ARRAY_BUFFER, indices.nbytes, indices, GL_STATIC_DRAW)

            stride = 10 * 4
            glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(0))
            glEnableVertexAttribArray(0)
            glVertexAttribPointer(1, 4, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(24))
            glEnableVertexAttribArray(1)
            glVertexAttribPointer(2, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(12))
            glEnableVertexAttribArray(2)
            glBindVertexArray(0)
        else:
            self.force_fill_index_count = 0

        if len(line_pos) > 0:
            interleaved = prepared['line_buffer']
            self.force_line_vertex_count = len(line_pos)

            glBindVertexArray(self.force_line_vao)
            glBindBuffer(GL_ARRAY_BUFFER, self.force_line_vbo)
            glBufferData(GL_ARRAY_BUFFER, interleaved.nbytes, interleaved, GL_STATIC_DRAW)

            stride = 10 * 4
            glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(0))
            glEnableVertexAttribArray(0)
            glVertexAttribPointer(1, 4, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(24))
            glEnableVertexAttribArray(1)
            glVertexAttribPointer(2, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(12))
            glEnableVertexAttribArray(2)
            glBindVertexArray(0)
        else:
            self.force_line_vertex_count = 0

    def draw_force_geometry(self, view_matrix, proj_matrix):
        if not self.is_initialized:
            return

        glUseProgram(self.shader_program)
        glUniformMatrix4fv(self.loc_view, 1, GL_FALSE, view_matrix)
        glUniformMatrix4fv(self.loc_proj, 1, GL_FALSE, proj_matrix)
        glUniform1f(self.loc_anim, 0.0)
        glEnable(GL_DEPTH_TEST)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

        if self.force_fill_index_count > 0:
            glUniform1f(self.loc_alpha, 1.0)
            glEnable(GL_POLYGON_OFFSET_FILL)
            glPolygonOffset(1.0, 1.0)
            glBindVertexArray(self.force_fill_vao)
            glDrawElements(GL_TRIANGLES, self.force_fill_index_count, GL_UNSIGNED_INT, None)
            glBindVertexArray(0)
            glDisable(GL_POLYGON_OFFSET_FILL)

        if self.force_line_vertex_count > 0:
            self._use_line_program(view_matrix, proj_matrix, 1.0, 0.0, 1.5)
            glDepthFunc(GL_LEQUAL)
            glBindVertexArray(self.force_line_vao)
            glDrawArrays(GL_LINES, 0, self.force_line_vertex_count)
            glBindVertexArray(0)
            glDepthFunc(GL_LESS)

        glUseProgram(0)

    def clear_force_geometry(self):
        if not self.is_initialized:
            return
        self.force_fill_index_count = 0
        self.force_line_vertex_count = 0

    def clear_load_geometry(self):
        if not self.is_initialized:
            return
        self.load_fill_index_count = 0
        self.load_line_vertex_count = 0
        self._load_fill_buffer = None
        self._load_line_buffer = None
        self._load_fill_indices = None
        self._load_view_gpu_active = False

    def upload_load_geometry(self, fill_verts, fill_colors, fill_faces, line_pos, line_colors):
        """
        Uploads load arrow / distributed load geometry to dedicated GPU buffers.
        Separate from force diagram buffers so both can coexist in the scene.
        """
        if not self.is_initialized:
            return

        self._load_view_gpu_active = False

        if len(fill_verts) > 0:
            dummy_disp = np.zeros((len(fill_verts), 3), dtype=np.float32)
            interleaved = np.hstack((fill_verts, dummy_disp, fill_colors)).astype(np.float32).flatten()
            self._load_fill_buffer = interleaved.reshape(-1, 10)
            indices = fill_faces.astype(np.uint32).flatten()
            self._load_fill_indices = indices
            self.load_fill_index_count = len(indices)

            glBindVertexArray(self.load_fill_vao)
            glBindBuffer(GL_ARRAY_BUFFER, self.load_fill_vbo)
            glBufferData(GL_ARRAY_BUFFER, interleaved.nbytes, interleaved, GL_DYNAMIC_DRAW)
            glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, self.load_fill_ebo)
            glBufferData(GL_ELEMENT_ARRAY_BUFFER, indices.nbytes, indices, GL_DYNAMIC_DRAW)

            stride = 10 * 4
            glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(0))
            glEnableVertexAttribArray(0)
            glVertexAttribPointer(1, 4, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(24))
            glEnableVertexAttribArray(1)
            glVertexAttribPointer(2, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(12))
            glEnableVertexAttribArray(2)
            glBindVertexArray(0)
        else:
            self.load_fill_index_count = 0
            self._load_fill_buffer = np.empty((0, 10), dtype=np.float32)
            self._load_fill_indices = np.empty(0, dtype=np.uint32)

        if len(line_pos) > 0:
            dummy_disp = np.zeros((len(line_pos), 3), dtype=np.float32)
            interleaved = np.hstack((line_pos, dummy_disp, line_colors)).astype(np.float32).flatten()
            self._load_line_buffer = interleaved.reshape(-1, 10)
            self.load_line_vertex_count = len(line_pos)

            glBindVertexArray(self.load_line_vao)
            glBindBuffer(GL_ARRAY_BUFFER, self.load_line_vbo)
            glBufferData(GL_ARRAY_BUFFER, interleaved.nbytes, interleaved, GL_DYNAMIC_DRAW)

            stride = 10 * 4
            glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(0))
            glEnableVertexAttribArray(0)
            glVertexAttribPointer(1, 4, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(24))
            glEnableVertexAttribArray(1)
            glVertexAttribPointer(2, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(12))
            glEnableVertexAttribArray(2)
            glBindVertexArray(0)
        else:
            self.load_line_vertex_count = 0
            self._load_line_buffer = np.empty((0, 10), dtype=np.float32)

    def update_load_positions(self, fill_verts, line_pos, fill_colors=None, line_colors=None):
        """Update fixed load topology without replacing buffers or index data.

        Returns False before any writes if topology changed or no uploaded
        buffers are available. The caller can then perform a full upload.
        Optional colors support visibility changes while the camera moves.
        """
        if not self.is_initialized:
            return False
        fill_buffer = getattr(self, '_load_fill_buffer', None)
        line_buffer = getattr(self, '_load_line_buffer', None)
        if fill_buffer is None or line_buffer is None:
            return False
        fill_verts = np.asarray(fill_verts, dtype=np.float32)
        line_pos = np.asarray(line_pos, dtype=np.float32)
        if (fill_verts.size != len(fill_buffer) * 3 or
                line_pos.size != len(line_buffer) * 3):
            return False
        if fill_colors is not None:
            fill_colors = np.asarray(fill_colors, dtype=np.float32)
            if fill_colors.size != len(fill_buffer) * 4:
                return False
        if line_colors is not None:
            line_colors = np.asarray(line_colors, dtype=np.float32)
            if line_colors.size != len(line_buffer) * 4:
                return False

        fill_buffer[:, :3] = fill_verts.reshape(-1, 3)
        line_buffer[:, :3] = line_pos.reshape(-1, 3)
        if fill_colors is not None:
            fill_buffer[:, 6:] = fill_colors.reshape(-1, 4)
        if line_colors is not None:
            line_buffer[:, 6:] = line_colors.reshape(-1, 4)

        if len(fill_buffer):
            glBindBuffer(GL_ARRAY_BUFFER, self.load_fill_vbo)
            glBufferSubData(GL_ARRAY_BUFFER, 0, fill_buffer.nbytes, fill_buffer)
        if len(line_buffer):
            glBindBuffer(GL_ARRAY_BUFFER, self.load_line_vbo)
            glBufferSubData(GL_ARRAY_BUFFER, 0, line_buffer.nbytes, line_buffer)
        glBindBuffer(GL_ARRAY_BUFFER, 0)
        return True

    def upload_load_view_payload(self, cache):
        """Upload static camera descriptors after the normal model load upload.

        Returns False when the load-only shader is unavailable, leaving the
        cached CPU position path available to the caller.
        """
        self._load_view_gpu_active = False
        if (not self.is_initialized or getattr(self, '_load_view_gpu_failed', False)
                or getattr(self, '_load_fill_buffer', None) is None
                or getattr(self, '_load_fill_indices', None) is None):
            return False
        try:
            from ._vbo_load_view import LoadViewGPURenderer, pack_load_view_payload
            renderer = getattr(self, '_load_view_gpu', None)
            if renderer is None:
                renderer = self._load_view_gpu = LoadViewGPURenderer(self)
            payload = pack_load_view_payload(cache, self._load_fill_buffer[:, 6:],
                                             self._load_fill_indices)
            renderer.upload(payload)
            self._load_view_gpu_active = True
            return True
        except Exception as error:
            self._load_view_gpu_failed = True
            print(f'VBO Engine: load view shader unavailable, using cached CPU geometry ({error})')
            return False

    def update_load_view_factors(self, factors, width, height):
        """Update only the common frame profile factors and logical viewport."""
        renderer = getattr(self, '_load_view_gpu', None)
        if not getattr(self, '_load_view_gpu_active', False) or renderer is None:
            return False
        return renderer.update_factors(factors, width, height)

    def draw_load_geometry(self, view_matrix, proj_matrix):
        """Draws all load arrows and distributed load curtains in a single pass."""
        if not self.is_initialized:
            return
        renderer = getattr(self, '_load_view_gpu', None)
        if getattr(self, '_load_view_gpu_active', False) and renderer is not None:
            if renderer.draw(view_matrix, proj_matrix):
                return
        if self.load_fill_index_count == 0 and self.load_line_vertex_count == 0:
            return

        glUseProgram(self.shader_program)
        glUniformMatrix4fv(self.loc_view, 1, GL_FALSE, view_matrix)
        glUniformMatrix4fv(self.loc_proj, 1, GL_FALSE, proj_matrix)
        glUniform1f(self.loc_anim, 0.0)
        glEnable(GL_DEPTH_TEST)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

        if self.load_fill_index_count > 0:
            glUniform1f(self.loc_alpha, 1.0)
            glEnable(GL_POLYGON_OFFSET_FILL)
            glPolygonOffset(2.0, 2.0)
            glBindVertexArray(self.load_fill_vao)
            glDrawElements(GL_TRIANGLES, self.load_fill_index_count, GL_UNSIGNED_INT, None)
            glBindVertexArray(0)
            glDisable(GL_POLYGON_OFFSET_FILL)

        if self.load_line_vertex_count > 0:
            self._use_line_program(view_matrix, proj_matrix, 1.0, 0.0, 1.8)
            glDepthFunc(GL_LEQUAL)
            glBindVertexArray(self.load_line_vao)
            glDrawArrays(GL_LINES, 0, self.load_line_vertex_count)
            glBindVertexArray(0)
            glDepthFunc(GL_LESS)

        glUseProgram(0)
