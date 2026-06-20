                          
import numpy as np
from OpenGL.GL import *
import ctypes

class AreaMixin:
    def upload_area_geometry(self, fill_verts, fill_colors, fill_faces, edge_verts, edge_colors, fill_displacements=None, edge_displacements=None):
        if not self.is_initialized:
            return

        if len(fill_verts) == 0:
            self.area_index_count = 0
        else:
            if fill_displacements is None:
                fill_displacements = np.zeros((len(fill_verts), 3), dtype=np.float32)

            fill_data = np.hstack((fill_verts, fill_displacements, fill_colors)).astype(np.float32).flatten()
            indices = fill_faces.astype(np.uint32).flatten()
            self.area_index_count = len(indices)

            glBindVertexArray(self.area_vao)
            glBindBuffer(GL_ARRAY_BUFFER, self.area_vbo)
            glBufferData(GL_ARRAY_BUFFER, fill_data.nbytes, fill_data, GL_STATIC_DRAW)
            glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, self.area_ebo)
            glBufferData(GL_ELEMENT_ARRAY_BUFFER, indices.nbytes, indices, GL_STATIC_DRAW)

            stride = 10 * 4
            glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(0))
            glEnableVertexAttribArray(0)
            glVertexAttribPointer(1, 4, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(24))
            glEnableVertexAttribArray(1)
            glVertexAttribPointer(2, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(12))
            glEnableVertexAttribArray(2)
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

    def draw_areas(self, view_matrix, proj_matrix, alpha_mult=1.0):
        if not self.is_initialized or self.area_index_count == 0:
            return
        glUseProgram(self.shader_program)
        glUniformMatrix4fv(self.loc_view,  1, GL_FALSE, view_matrix)
        glUniformMatrix4fv(self.loc_proj,  1, GL_FALSE, proj_matrix)
        glUniform1f(self.loc_alpha, alpha_mult)
        glUniform1f(self.loc_anim, self.current_anim_factor)
        glEnable(GL_DEPTH_TEST)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

        glDepthMask(GL_FALSE)
                                                                                  
        glDepthFunc(GL_LEQUAL)

        glEnable(GL_POLYGON_OFFSET_FILL)
        glPolygonOffset(2.0, 2.0)
        
        glBindVertexArray(self.area_vao)
        glDrawElements(GL_TRIANGLES, self.area_index_count, GL_UNSIGNED_INT, None)
        glBindVertexArray(0)
        
        glDisable(GL_POLYGON_OFFSET_FILL)
        glDepthFunc(GL_LESS)                    
        glDepthMask(GL_TRUE)                                                          
        glUseProgram(0)

    def draw_area_depth_prepass(self, view_matrix, proj_matrix):
        """Render slab fill into depth buffer only (no colour output).
        This lets draw_area_edges occlude edges that sit behind the slab's
        own faces — the same way frame edges are hidden by frame solid geometry."""
        if not self.is_initialized or self.area_index_count == 0:
            return
        glUseProgram(self.shader_program)
        glUniformMatrix4fv(self.loc_view, 1, GL_FALSE, view_matrix)
        glUniformMatrix4fv(self.loc_proj, 1, GL_FALSE, proj_matrix)
        glUniform1f(self.loc_alpha, 1.0)
        glUniform1f(self.loc_anim, self.current_anim_factor)
        glEnable(GL_DEPTH_TEST)
        glDepthMask(GL_TRUE)                                                     
        glColorMask(GL_FALSE, GL_FALSE, GL_FALSE, GL_FALSE)                           
        glEnable(GL_POLYGON_OFFSET_FILL)
        glPolygonOffset(2.0, 2.0)                                                                     

        glBindVertexArray(self.area_vao)
        glDrawElements(GL_TRIANGLES, self.area_index_count, GL_UNSIGNED_INT, None)
        glBindVertexArray(0)

        glDisable(GL_POLYGON_OFFSET_FILL)
        glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE)                                    
        glUseProgram(0)

    def draw_area_edges(self, view_matrix, proj_matrix, line_width=1.5, alpha_mult=1.0, write_depth=True):
        if not self.is_initialized or self.area_edge_vertex_count == 0:
            return
        glUseProgram(self.shader_program)
        glUniformMatrix4fv(self.loc_view,  1, GL_FALSE, view_matrix)
        glUniformMatrix4fv(self.loc_proj,  1, GL_FALSE, proj_matrix)
        glUniform1f(self.loc_alpha, alpha_mult)                                                   
        glUniform1f(self.loc_anim, self.current_anim_factor)
        glEnable(GL_DEPTH_TEST)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glDepthMask(GL_TRUE if write_depth else GL_FALSE)
        
        glLineWidth(1.0)

        glBindVertexArray(self.area_edge_vao)
        glDrawArrays(GL_LINES, 0, self.area_edge_vertex_count)
        glBindVertexArray(0)

        glDepthMask(GL_TRUE)                  
        glUseProgram(0)
