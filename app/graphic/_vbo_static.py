import numpy as np
from OpenGL.GL import *
import ctypes

class StaticMixin:
    """
    Batches all the 'drawn once, changes rarely' line geometry that used to be
    a pile of individual pyqtgraph GLLinePlotItems: reference grid, dimension
    lines, grid bubbles, member local-axis triads, and diaphragm constraint
    markers. One GL_STATIC_DRAW buffer, one draw call per frame, instead of
    ~8+ separate items each doing their own bind/draw every frame regardless
    of whether the camera or the model changed.

    Uses GL_STATIC_DRAW deliberately (not the persistent-buffer fast-update
    pattern used for lines/springs) because this geometry is rebuilt rarely
    (model load, grid settings change, constraint edit) rather than every
    frame, so there's nothing to gain from a persistent CPU-side buffer here.
    """

    def upload_static_geometry(self, vertices, colors):
        if not self.is_initialized:
            return

        if len(vertices) == 0:
            self.static_line_vertex_count = 0
            return

        displacements = np.zeros((len(vertices), 3), dtype=np.float32)
        interleaved_data = np.hstack((vertices, displacements, colors)).astype(np.float32).flatten()
        self.static_line_vertex_count = len(vertices)

        glBindVertexArray(self.static_line_vao)
        glBindBuffer(GL_ARRAY_BUFFER, self.static_line_vbo)
        glBufferData(GL_ARRAY_BUFFER, interleaved_data.nbytes, interleaved_data, GL_STATIC_DRAW)

        stride = 10 * 4
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(0))
        glEnableVertexAttribArray(0)
        glVertexAttribPointer(1, 4, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(24))
        glEnableVertexAttribArray(1)
        glVertexAttribPointer(2, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(12))
        glEnableVertexAttribArray(2)
        glBindVertexArray(0)

    def clear_static_geometry(self):
        if not self.is_initialized:
            return
        self.static_line_vertex_count = 0

    def draw_static(self, view_matrix, proj_matrix, line_width=1.0, alpha_mult=1.0):
        if not self.is_initialized or self.static_line_vertex_count == 0:
            return
        glUseProgram(self.shader_program)
        glUniformMatrix4fv(self.loc_view, 1, GL_FALSE, view_matrix)
        glUniformMatrix4fv(self.loc_proj, 1, GL_FALSE, proj_matrix)
        glUniform1f(self.loc_alpha, alpha_mult)
        glUniform1f(self.loc_anim, 0.0)
        glEnable(GL_DEPTH_TEST)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glLineWidth(float(line_width))
        glBindVertexArray(self.static_line_vao)
        glDrawArrays(GL_LINES, 0, self.static_line_vertex_count)
        glBindVertexArray(0)
        glUseProgram(0)
