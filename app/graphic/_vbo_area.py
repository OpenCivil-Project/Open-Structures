import numpy as np
from OpenGL.GL import *
import ctypes

class AreaMixin:
    def upload_area_geometry(self, fill_verts, fill_colors, fill_faces, edge_verts, edge_colors, fill_displacements=None, edge_displacements=None, fill_normals=None):
        if not self.is_initialized:
            return

        if len(fill_verts) == 0:
            self.area_index_count = 0
        else:
            if fill_displacements is None:
                fill_displacements = np.zeros((len(fill_verts), 3), dtype=np.float32)

            if fill_normals is None:
                                                                      
                fill_normals = np.tile(np.array([0.0, 0.0, 1.0], dtype=np.float32), (len(fill_verts), 1))

            fill_data = np.hstack((fill_verts, fill_displacements, fill_colors, fill_normals)).astype(np.float32).flatten()
            indices = fill_faces.astype(np.uint32).flatten()
            self.area_index_count = len(indices)

            glBindVertexArray(self.area_vao)
            glBindBuffer(GL_ARRAY_BUFFER, self.area_vbo)
            glBufferData(GL_ARRAY_BUFFER, fill_data.nbytes, fill_data, GL_STATIC_DRAW)
            glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, self.area_ebo)
            glBufferData(GL_ELEMENT_ARRAY_BUFFER, indices.nbytes, indices, GL_STATIC_DRAW)

            stride = 13 * 4
            glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(0))
            glEnableVertexAttribArray(0)
            glVertexAttribPointer(1, 4, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(24))
            glEnableVertexAttribArray(1)
            glVertexAttribPointer(2, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(12))
            glEnableVertexAttribArray(2)
            glVertexAttribPointer(3, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(40))
            glEnableVertexAttribArray(3)
            glBindVertexArray(0)

        if len(edge_verts) == 0:
            self.area_edge_vertex_count = 0
        else:
            if edge_displacements is None:
                edge_displacements = np.zeros((len(edge_verts), 3), dtype=np.float32)
            edge_data = np.hstack((edge_verts, edge_displacements, edge_colors)).astype(np.float32).flatten()
            self.area_edge_vertex_count = len(edge_verts)

            glBindVertexArray(self.area_edge_vao)
            glBindBuffer(GL_ARRAY_BUFFER, self.area_edge_vbo)
            glBufferData(GL_ARRAY_BUFFER, edge_data.nbytes, edge_data, GL_STATIC_DRAW)

            stride = 10 * 4
            glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(0))
            glEnableVertexAttribArray(0)
            glVertexAttribPointer(1, 4, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(24))
            glEnableVertexAttribArray(1)
            glVertexAttribPointer(2, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(12))
            glEnableVertexAttribArray(2)
            glBindVertexArray(0)

    def draw_areas(self, view_matrix, proj_matrix, alpha_mult=1.0, light=None,
                   transparent=True, depth_only=False):
        """Draw the native shell buffer for the front or rear composition pass."""
        if not self.is_initialized or self.area_index_count == 0:
            return
        stage = getattr(self, '_transparency_stage', None)
        used_lit = (self._use_transparency_tail_program(view_matrix, proj_matrix, alpha_mult, light)
                    if stage == 'tail' else
                    not depth_only and self._use_lit_program(view_matrix, proj_matrix, alpha_mult, light))
        if not used_lit:
            glUseProgram(self.shader_program)
            glUniformMatrix4fv(self.loc_view,  1, GL_FALSE, view_matrix)
            glUniformMatrix4fv(self.loc_proj,  1, GL_FALSE, proj_matrix)
            glUniform1f(self.loc_alpha, alpha_mult)
            glUniform1f(self.loc_anim, self.current_anim_factor)
        glEnable(GL_DEPTH_TEST)
        if stage == 'front':
            glDisable(GL_BLEND)
        else:
            glEnable(GL_BLEND)
            glBlendFunc(GL_ONE, GL_ONE) if stage == 'tail' else glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

        glDepthMask(GL_TRUE if depth_only or not transparent else GL_FALSE)
        colour_write = GL_FALSE if depth_only else GL_TRUE
        glColorMask(colour_write, colour_write, colour_write, colour_write)
                                                                                  
        glDepthFunc(GL_LEQUAL)

        if stage:
            glDisable(GL_POLYGON_OFFSET_FILL)
        else:
            glEnable(GL_POLYGON_OFFSET_FILL)
            glPolygonOffset(2.0, 2.0)
        
        glBindVertexArray(self.area_vao)
        try:
            glDrawElements(GL_TRIANGLES, self.area_index_count, GL_UNSIGNED_INT, None)
        finally:
            glBindVertexArray(0)
            glDisable(GL_POLYGON_OFFSET_FILL)
            glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE)
            glDepthFunc(GL_LESS)
            glDepthMask(GL_TRUE)
            glUseProgram(0)
            if stage:
                glEnable(GL_BLEND)
                glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

    def draw_area_depth_prepass(self, view_matrix, proj_matrix):
        """Classify shell outlines after translucent colour has been drawn."""
        self.draw_areas(view_matrix, proj_matrix, depth_only=True)

    def draw_area_edges(self, view_matrix, proj_matrix, line_width=1.5, alpha_mult=1.0, write_depth=True):
        if not self.is_initialized or self.area_edge_vertex_count == 0:
            return
        self._use_line_program(view_matrix, proj_matrix, alpha_mult,
                               self.current_anim_factor, line_width)
        glEnable(GL_DEPTH_TEST)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glDepthMask(GL_TRUE if write_depth else GL_FALSE)

        glBindVertexArray(self.area_edge_vao)
        glDrawArrays(GL_LINES, 0, self.area_edge_vertex_count)
        glBindVertexArray(0)

        glDepthMask(GL_TRUE)                  
        glUseProgram(0)
