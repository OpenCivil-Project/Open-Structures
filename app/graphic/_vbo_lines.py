                           
import numpy as np
from OpenGL.GL import *
import ctypes

class LineMixin:
    def upload_line_geometry(self, vertices, colors, displacements=None):
        if not self.is_initialized:
            return
            
        if len(vertices) == 0:
            self.line_vertex_count = 0
            return

        if displacements is None:
            displacements = np.zeros((len(vertices), 3), dtype=np.float32)

        interleaved_data = np.hstack((vertices, displacements, colors)).astype(np.float32).flatten()
        self.line_vertex_count = len(vertices)

        glBindVertexArray(self.line_vao)
        glBindBuffer(GL_ARRAY_BUFFER, self.line_vbo)
        glBufferData(GL_ARRAY_BUFFER, interleaved_data.nbytes, interleaved_data, GL_STATIC_DRAW)

        stride = 10 * 4                                        
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(0))
        glEnableVertexAttribArray(0)
        glVertexAttribPointer(1, 4, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(24))                  
        glEnableVertexAttribArray(1)
        glVertexAttribPointer(2, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(12))                  
        glEnableVertexAttribArray(2)
        glBindVertexArray(0)

    def draw_lines(self, view_matrix, proj_matrix, line_width=2.0, alpha_mult=1.0, write_depth=True):
        if not self.is_initialized or self.line_vertex_count == 0:
            return
        glUseProgram(self.shader_program)
        glUniformMatrix4fv(self.loc_view,  1, GL_FALSE, view_matrix)
        glUniformMatrix4fv(self.loc_proj,  1, GL_FALSE, proj_matrix)
        glUniform1f(self.loc_alpha, alpha_mult)
        glUniform1f(self.loc_anim, self.current_anim_factor)
        glEnable(GL_DEPTH_TEST)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        if not write_depth:
            glDepthMask(GL_FALSE)
        glLineWidth(float(line_width))
        glBindVertexArray(self.line_vao)
        glDrawArrays(GL_LINES, 0, self.line_vertex_count)
        glBindVertexArray(0)
        if not write_depth:
            glDepthMask(GL_TRUE)
        glUseProgram(0)

    def draw_extruded_edges(self, view_matrix, proj_matrix, line_width=1.5):
        if not self.is_initialized or self.line_vertex_count == 0:
            return
        glUseProgram(self.shader_program)
        glUniformMatrix4fv(self.loc_view,  1, GL_FALSE, view_matrix)
        glUniformMatrix4fv(self.loc_proj,  1, GL_FALSE, proj_matrix)
        glUniform1f(self.loc_anim, 0.0)
        glEnable(GL_DEPTH_TEST)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glLineWidth(line_width)
        glBindVertexArray(self.line_vao)
        glDepthFunc(GL_GREATER)
        glUniform1f(self.loc_alpha, 0.15)
        glDrawArrays(GL_LINES, 0, self.line_vertex_count)
        glDepthFunc(GL_LEQUAL)
        glUniform1f(self.loc_alpha, 1.0)
        glDrawArrays(GL_LINES, 0, self.line_vertex_count)
        glBindVertexArray(0)
        glDepthFunc(GL_LESS)
        glUseProgram(0)

    def update_line_geometry_inplace(self, vertices, colors):
        """
        For LTHA/hover: zero-allocation update when vertex count matches.
        Routes through fast_update_lines when a persistent buffer is ready,
        falls back to glBufferData only when size changes (rare, e.g. structure edit).
        """
        if not self.is_initialized or len(vertices) == 0:
            return

        if self.persistent_line_buffer is not None and len(vertices) == self.line_vertex_count:
            vertices_flat = vertices.flatten() if vertices.ndim > 1 else vertices
            colors_flat = colors.flatten() if colors.ndim > 1 else colors
            self.fast_update_lines(vertices_flat, colors_flat)
            return

        zeros = np.zeros((len(vertices), 3), dtype=np.float32)
        data = np.hstack((vertices, zeros, colors)).astype(np.float32).flatten()
        glBindVertexArray(self.line_vao)
        glBindBuffer(GL_ARRAY_BUFFER, self.line_vbo)
        if len(vertices) == self.line_vertex_count:
            glBufferSubData(GL_ARRAY_BUFFER, 0, data.nbytes, data)
        else:
            glBufferData(GL_ARRAY_BUFFER, data.nbytes, data, GL_DYNAMIC_DRAW)
            self.line_vertex_count = len(vertices)
                                                            
            self.persistent_line_buffer = np.zeros(len(vertices) * 10, dtype=np.float32)
                                                                                               
        glBindVertexArray(0)

    def fast_update_lines(self, vertices_flat, colors_flat):
        """
        Microsecond-fast VBO update. Slices new coordinates directly into 
        the existing memory block. Zero np.zeros(), zero np.hstack().
        """
        if not self.is_initialized or self.persistent_line_buffer is None or len(vertices_flat) == 0:
            return

        self.persistent_line_buffer[0::10] = vertices_flat[0::3]
        self.persistent_line_buffer[1::10] = vertices_flat[1::3]
        self.persistent_line_buffer[2::10] = vertices_flat[2::3]

        self.persistent_line_buffer[6::10] = colors_flat[0::4]
        self.persistent_line_buffer[7::10] = colors_flat[1::4]
        self.persistent_line_buffer[8::10] = colors_flat[2::4]
        self.persistent_line_buffer[9::10] = colors_flat[3::4]

        glBindVertexArray(self.line_vao)
        glBindBuffer(GL_ARRAY_BUFFER, self.line_vbo)
        glBufferSubData(GL_ARRAY_BUFFER, 0, self.persistent_line_buffer.nbytes, self.persistent_line_buffer)
        glBindVertexArray(0)
