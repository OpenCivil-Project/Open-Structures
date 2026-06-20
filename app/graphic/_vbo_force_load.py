                                
import numpy as np
from OpenGL.GL import *
import ctypes

class ForceLoadMixin:
    def upload_force_geometry(self, fill_verts, fill_colors, fill_faces, line_pos, line_colors):
        if not self.is_initialized:
            return

        if len(fill_verts) > 0:
            dummy_disp = np.zeros((len(fill_verts), 3), dtype=np.float32)
            interleaved = np.hstack((fill_verts, dummy_disp, fill_colors)).astype(np.float32).flatten()
            indices = fill_faces.astype(np.uint32).flatten()
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
            dummy_disp = np.zeros((len(line_pos), 3), dtype=np.float32)
            interleaved = np.hstack((line_pos, dummy_disp, line_colors)).astype(np.float32).flatten()
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
            glUniform1f(self.loc_alpha, 1.0)
            glLineWidth(1.5)
            glBindVertexArray(self.force_line_vao)
            glDrawArrays(GL_LINES, 0, self.force_line_vertex_count)
            glBindVertexArray(0)

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

    def upload_load_geometry(self, fill_verts, fill_colors, fill_faces, line_pos, line_colors):
        """
        Uploads load arrow / distributed load geometry to dedicated GPU buffers.
        Separate from force diagram buffers so both can coexist in the scene.
        """
        if not self.is_initialized:
            return

        if len(fill_verts) > 0:
            dummy_disp = np.zeros((len(fill_verts), 3), dtype=np.float32)
            interleaved = np.hstack((fill_verts, dummy_disp, fill_colors)).astype(np.float32).flatten()
            indices = fill_faces.astype(np.uint32).flatten()
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

        if len(line_pos) > 0:
            dummy_disp = np.zeros((len(line_pos), 3), dtype=np.float32)
            interleaved = np.hstack((line_pos, dummy_disp, line_colors)).astype(np.float32).flatten()
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

    def draw_load_geometry(self, view_matrix, proj_matrix):
        """Draws all load arrows and distributed load curtains in a single pass."""
        if not self.is_initialized:
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
            glUniform1f(self.loc_alpha, 1.0)
            glLineWidth(1.8)
            glBindVertexArray(self.load_line_vao)
            glDrawArrays(GL_LINES, 0, self.load_line_vertex_count)
            glBindVertexArray(0)

        glUseProgram(0)
