import numpy as np
from OpenGL.GL import *
import ctypes

class ExtrudedMixin:
    def upload_extruded_geometry(self, vertices, colors, faces, displacements=None, normals=None, ltha=False):
        """ltha=True marks the GL buffer as laid out for LTHA/step playback
        (the only layout fast_update_extruded may write into). Every other
        upload marks it 'static', so the fast path can never write playback
        vertices under a different index list."""
        if not self.is_initialized:
            return
        if not ltha:
                                                                                                      
            self._last_ext_args = (vertices, colors, faces, displacements, normals)
        if len(vertices) == 0:
            self.ext_owner = 'static'
            self.index_count = 0                                              
            return

        if displacements is None:
            displacements = np.zeros((len(vertices), 3), dtype=np.float32)

        if normals is None:
                                                                            
            normals = np.tile(np.array([0.0, 0.0, 1.0], dtype=np.float32), (len(vertices), 1))

        interleaved_data = np.hstack((vertices, displacements, colors, normals)).astype(np.float32).flatten()
        indices = faces.astype(np.uint32).flatten()
        self.index_count = len(indices)

        glBindVertexArray(self.vao)
        glBindBuffer(GL_ARRAY_BUFFER, self.vbo)
        glBufferData(GL_ARRAY_BUFFER, interleaved_data.nbytes, interleaved_data, GL_STATIC_DRAW)
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, self.ebo)
        glBufferData(GL_ELEMENT_ARRAY_BUFFER, indices.nbytes, indices, GL_STATIC_DRAW)
        self.ext_owner = 'ltha' if ltha else 'static'

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

    def draw(self, view_matrix, proj_matrix, light=None, transparent=True, depth_only=False):
        """Draw the existing frame buffer once without sorting or copying it.

        The canvas compositor captures the nearest face before accumulating
        rear faces. Buffer layouts and playback uploads remain unchanged.
        """
        if not self.is_initialized or self.index_count == 0:
            return

        stage = getattr(self, '_transparency_stage', None)
        used_lit = (self._use_transparency_tail_program(view_matrix, proj_matrix, 1.0, light)
                    if stage == 'tail' else
                    not depth_only and self._use_lit_program(view_matrix, proj_matrix, 1.0, light))
        if not used_lit:
            glUseProgram(self.shader_program)
            glUniformMatrix4fv(self.loc_view,  1, GL_FALSE, view_matrix)
            glUniformMatrix4fv(self.loc_proj,  1, GL_FALSE, proj_matrix)
            glUniform1f(self.loc_alpha, 1.0)
            glUniform1f(self.loc_anim, self.current_anim_factor)

        glEnable(GL_DEPTH_TEST)
        if stage == 'front':
            glDisable(GL_BLEND)
        else:
            glEnable(GL_BLEND)
            glBlendFunc(GL_ONE, GL_ONE) if stage == 'tail' else glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
                                                                                     
        glEnable(GL_POLYGON_OFFSET_FILL)
        glPolygonOffset(1.0, 1.0)
        glBindVertexArray(self.vao)
        colour_write = GL_FALSE if depth_only else GL_TRUE
        glColorMask(colour_write, colour_write, colour_write, colour_write)
        glDepthMask(GL_TRUE if depth_only or not transparent else GL_FALSE)
        glDepthFunc(GL_LEQUAL)
        try:
            glDrawElements(GL_TRIANGLES, self.index_count, GL_UNSIGNED_INT, None)
        finally:
            glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE)
            glDepthMask(GL_TRUE)
            glDepthFunc(GL_LESS)
            glBindVertexArray(0)
            glDisable(GL_POLYGON_OFFSET_FILL)
            glUseProgram(0)
            if stage:
                glEnable(GL_BLEND)
                glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

    def ext_buffer_matches(self, num_verts):
        """True only if the GL extruded buffer currently holds the LTHA
        layout with exactly num_verts vertices."""
        return (getattr(self, 'ext_owner', None) == 'ltha'
                and self.persistent_ext_buffer is not None
                and len(self.persistent_ext_buffer) == num_verts * 13)

    def fast_update_extruded(self, vertices_flat, colors_flat):
        """Same zero-allocation logic, but for the 3D Extruded Faces.
        Normals are intentionally left untouched here (still whatever
        allocate_ltha_buffers seeded them with) -- this fast path is used
        for LTHA playback where per-frame normal recomputation isn't wired
        up yet; see the note in allocate_ltha_buffers."""
        if not self.is_initialized or self.persistent_ext_buffer is None or len(vertices_flat) == 0:
            return False
        if not self.ext_buffer_matches(len(vertices_flat) // 3):
            return False                                                                            

        self.persistent_ext_buffer[0::13] = vertices_flat[0::3]
        self.persistent_ext_buffer[1::13] = vertices_flat[1::3]
        self.persistent_ext_buffer[2::13] = vertices_flat[2::3]

        self.persistent_ext_buffer[6::13] = colors_flat[0::4]
        self.persistent_ext_buffer[7::13] = colors_flat[1::4]
        self.persistent_ext_buffer[8::13] = colors_flat[2::4]
        self.persistent_ext_buffer[9::13] = colors_flat[3::4]

        glBindVertexArray(self.vao)
        glBindBuffer(GL_ARRAY_BUFFER, self.vbo)
        glBufferSubData(GL_ARRAY_BUFFER, 0, self.persistent_ext_buffer.nbytes, self.persistent_ext_buffer)
        glBindVertexArray(0)
        return True
