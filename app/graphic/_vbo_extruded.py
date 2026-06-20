                              
import numpy as np
from OpenGL.GL import *
import ctypes

class ExtrudedMixin:
    def upload_extruded_geometry(self, vertices, colors, faces, displacements=None):
        if not self.is_initialized:
            return
        if len(vertices) == 0:
            self.index_count = 0                                              
            return

        if displacements is None:
            displacements = np.zeros((len(vertices), 3), dtype=np.float32)

        interleaved_data = np.hstack((vertices, displacements, colors)).astype(np.float32).flatten()
        indices = faces.astype(np.uint32).flatten()
        self.index_count = len(indices)

        glBindVertexArray(self.vao)
        glBindBuffer(GL_ARRAY_BUFFER, self.vbo)
        glBufferData(GL_ARRAY_BUFFER, interleaved_data.nbytes, interleaved_data, GL_STATIC_DRAW)
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, self.ebo)
        glBufferData(GL_ELEMENT_ARRAY_BUFFER, indices.nbytes, indices, GL_STATIC_DRAW)

        stride = 10 * 4
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(0))
        glEnableVertexAttribArray(0)
        glVertexAttribPointer(1, 4, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(24))
        glEnableVertexAttribArray(1)
        glVertexAttribPointer(2, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(12))
        glEnableVertexAttribArray(2)
        glBindVertexArray(0)

    def draw(self, view_matrix, proj_matrix):
        if not self.is_initialized or self.index_count == 0:
            return
        glUseProgram(self.shader_program)
        glUniformMatrix4fv(self.loc_view,  1, GL_FALSE, view_matrix)
        glUniformMatrix4fv(self.loc_proj,  1, GL_FALSE, proj_matrix)
        glUniform1f(self.loc_alpha, 1.0)
        glUniform1f(self.loc_anim, self.current_anim_factor)
        glEnable(GL_DEPTH_TEST)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glEnable(GL_POLYGON_OFFSET_FILL)
        glPolygonOffset(1.0, 1.0)
        glBindVertexArray(self.vao)
        glDrawElements(GL_TRIANGLES, self.index_count, GL_UNSIGNED_INT, None)
        glBindVertexArray(0)
        glDisable(GL_POLYGON_OFFSET_FILL)
        glUseProgram(0)

    def fast_update_extruded(self, vertices_flat, colors_flat):
        """Same zero-allocation logic, but for the 3D Extruded Faces."""
        if not self.is_initialized or self.persistent_ext_buffer is None or len(vertices_flat) == 0:
            return

        self.persistent_ext_buffer[0::10] = vertices_flat[0::3]
        self.persistent_ext_buffer[1::10] = vertices_flat[1::3]
        self.persistent_ext_buffer[2::10] = vertices_flat[2::3]

        self.persistent_ext_buffer[6::10] = colors_flat[0::4]
        self.persistent_ext_buffer[7::10] = colors_flat[1::4]
        self.persistent_ext_buffer[8::10] = colors_flat[2::4]
        self.persistent_ext_buffer[9::10] = colors_flat[3::4]

        glBindVertexArray(self.vao)
        glBindBuffer(GL_ARRAY_BUFFER, self.vbo)
        glBufferSubData(GL_ARRAY_BUFFER, 0, self.persistent_ext_buffer.nbytes, self.persistent_ext_buffer)
        glBindVertexArray(0)
