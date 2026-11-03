import numpy as np
from OpenGL.GL import *
import ctypes

class GridBubbleMixin:
    """
    Dedicated GPU buffer for the grid "bubble" geometry -- the short tail
    line that extends past the end of a grid line, plus the ID circle drawn
    at the end of that tail (see canvas.py: _draw_reference_grids).

    This used to be lumped into the same batch as the reference grid /
    dimension lines (_vbo_static.py) and drawn with one shared glLineWidth.
    It's split out into its own VAO/VBO so the bubble tail + circle
    thickness can be configured independently (Grid Editor -> "Bubble Line
    Thickness") without changing the thin reference-grid lines.
    """

    def upload_grid_bubble_geometry(self, vertices, colors, split=0):
        """split = number of leading vertices that are the extension (tail) lines;
        the rest are the ID circles. Lets the two have different thickness."""
        if not self.is_initialized:
            return

        if len(vertices) == 0:
            self.grid_bubble_vertex_count = 0
            self.grid_bubble_split = 0
            return
        self.grid_bubble_split = int(split)

        displacements = np.zeros((len(vertices), 3), dtype=np.float32)
        interleaved_data = np.hstack((vertices, displacements, colors)).astype(np.float32).flatten()
        self.grid_bubble_vertex_count = len(vertices)

        glBindVertexArray(self.grid_bubble_vao)
        glBindBuffer(GL_ARRAY_BUFFER, self.grid_bubble_vbo)
        glBufferData(GL_ARRAY_BUFFER, interleaved_data.nbytes, interleaved_data, GL_STATIC_DRAW)

        stride = 10 * 4
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(0))
        glEnableVertexAttribArray(0)
        glVertexAttribPointer(1, 4, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(24))
        glEnableVertexAttribArray(1)
        glVertexAttribPointer(2, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(12))
        glEnableVertexAttribArray(2)
        glBindVertexArray(0)

    def clear_grid_bubble_geometry(self):
        if not self.is_initialized:
            return
        self.grid_bubble_vertex_count = 0

    def draw_grid_bubbles(self, view_matrix, proj_matrix, line_width=1.5, alpha_mult=1.0, ext_width=None):
        if not self.is_initialized or self.grid_bubble_vertex_count == 0:
            return

        glEnable(GL_DEPTH_TEST)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glDepthFunc(GL_LEQUAL)

        glBindVertexArray(self.grid_bubble_vao)
        split = getattr(self, 'grid_bubble_split', 0)
        total = self.grid_bubble_vertex_count
        if ext_width is None or split <= 0 or split >= total:
            self._use_line_program(view_matrix, proj_matrix, alpha_mult, 0.0, float(line_width))
            glDrawArrays(GL_LINES, 0, total)
        else:
            self._use_line_program(view_matrix, proj_matrix, alpha_mult, 0.0, float(ext_width))
            glDrawArrays(GL_LINES, 0, split)
            self._use_line_program(view_matrix, proj_matrix, alpha_mult, 0.0, float(line_width))
            glDrawArrays(GL_LINES, split, total - split)
        glBindVertexArray(0)

        glDepthFunc(GL_LESS)
        glUseProgram(0)

class GridLineMixin:
    """
    Dedicated GPU buffer for the grid GUIDELINES (structural grid lines,
    active-plane lines, dimension lines and the floor "graph paper").

    One buffer, two groups: vertices [0, split) are group A (structural /
    active / dimension lines) and [split, end) are group B (floor grid), so
    each group can be drawn with its own line width in a single VBO.
    """

    def upload_grid_line_geometry(self, vertices, colors, split):
        if not self.is_initialized:
            return

        if len(vertices) == 0:
            self.grid_line_vertex_count = 0
            self.grid_line_split = 0
            return

        displacements = np.zeros((len(vertices), 3), dtype=np.float32)
        interleaved_data = np.hstack((vertices, displacements, colors)).astype(np.float32).flatten()
        self.grid_line_vertex_count = len(vertices)
        self.grid_line_split = int(split)

        glBindVertexArray(self.grid_line_vao)
        glBindBuffer(GL_ARRAY_BUFFER, self.grid_line_vbo)
        glBufferData(GL_ARRAY_BUFFER, interleaved_data.nbytes, interleaved_data, GL_STATIC_DRAW)

        stride = 10 * 4
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(0))
        glEnableVertexAttribArray(0)
        glVertexAttribPointer(1, 4, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(24))
        glEnableVertexAttribArray(1)
        glVertexAttribPointer(2, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(12))
        glEnableVertexAttribArray(2)
        glBindVertexArray(0)

    def clear_grid_line_geometry(self):
        if not self.is_initialized:
            return
        self.grid_line_vertex_count = 0
        self.grid_line_split = 0

    def draw_grid_lines(self, view_matrix, proj_matrix, width_a=1.5, width_b=1.0, alpha_mult=1.0):
        if not self.is_initialized or self.grid_line_vertex_count == 0:
            return

        glEnable(GL_DEPTH_TEST)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glDepthFunc(GL_LEQUAL)

        glBindVertexArray(self.grid_line_vao)
        split = self.grid_line_split
        total = self.grid_line_vertex_count
        if total > split:                                                         
            self._use_line_program(view_matrix, proj_matrix, alpha_mult, 0.0, float(width_b))
            glDrawArrays(GL_LINES, split, total - split)
        if split > 0:                                                           
            self._use_line_program(view_matrix, proj_matrix, alpha_mult, 0.0, float(width_a))
            glDrawArrays(GL_LINES, 0, split)
        glBindVertexArray(0)

        glDepthFunc(GL_LESS)
        glUseProgram(0)
