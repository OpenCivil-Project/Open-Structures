# app/graphic/_vbo_text.py
import os
import numpy as np
from OpenGL.GL import *
from PIL import Image
import ctypes

class TextMixin:
    def allocate_text_buffer(self, num_quads):
        """
        Pre-allocates a persistent CPU-side text buffer for num_quads glyphs.
        Each quad = 4 vertices × 9 floats (xyz + uv + rgba) = 36 floats.
        Call once after font atlas is loaded and label count is known.
        """
        num_verts = num_quads * 4
        self.persistent_text_buffer = np.zeros(num_verts * 9, dtype=np.float32)
        self.persistent_text_index_buffer = np.zeros(num_quads * 6, dtype=np.uint32)
        self.persistent_text_quad_cap = num_quads

        for q in range(num_quads):
            b = q * 4
            self.persistent_text_index_buffer[q*6:q*6+6] = [b, b+1, b+2, b+2, b+3, b]

        glBindVertexArray(self.text_vao)
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, self.text_ebo)
        glBufferData(GL_ELEMENT_ARRAY_BUFFER,
                     self.persistent_text_index_buffer.nbytes,
                     self.persistent_text_index_buffer,
                     GL_STATIC_DRAW)
        glBindVertexArray(0)

    def fast_update_text(self, vertices, texcoords, colors, num_quads):
        """
        Zero-allocation text update using SubData.
        Slices new vertex data directly into the persistent buffer.
        Only call after allocate_text_buffer().
        num_quads must be <= persistent_text_quad_cap.
        """
        if not self.is_initialized or not hasattr(self, 'persistent_text_buffer'):
            return
        if num_quads == 0:
            self.text_index_count = 0
            return

        num_verts = num_quads * 4
        buf = self.persistent_text_buffer
                                                                  
        buf[0::9] = vertices[0::3]      
        buf[1::9] = vertices[1::3]      
        buf[2::9] = vertices[2::3]      
        buf[3::9] = texcoords[0::2]     
        buf[4::9] = texcoords[1::2]     
        buf[5::9] = colors[0::4]        
        buf[6::9] = colors[1::4]        
        buf[7::9] = colors[2::4]        
        buf[8::9] = colors[3::4]        

        self.text_index_count = num_quads * 6

        glBindVertexArray(self.text_vao)
        glBindBuffer(GL_ARRAY_BUFFER, self.text_vbo)
        glBufferSubData(GL_ARRAY_BUFFER, 0,
                        num_verts * 9 * 4,                                  
                        buf[:num_verts * 9])
        glBindVertexArray(0)

    def load_font_texture(self, image_name="font_atlas.png"):
        if not self.is_initialized:
            return
        
        import os
        current_dir = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(current_dir, image_name)
        
        try:
                                                                            
            img = Image.open(path).convert('L')
                                                                             
            img = img.transpose(Image.FLIP_TOP_BOTTOM)
            img_data = np.array(img, np.uint8)
            
            self.font_texture_id = glGenTextures(1)
            glBindTexture(GL_TEXTURE_2D, self.font_texture_id)
            
            glPixelStorei(GL_UNPACK_ALIGNMENT, 1)
            
            glTexImage2D(GL_TEXTURE_2D, 0, GL_RED, img.width, img.height, 0, GL_RED, GL_UNSIGNED_BYTE, img_data)
            
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
            
            glBindTexture(GL_TEXTURE_2D, 0)
            
            glPixelStorei(GL_UNPACK_ALIGNMENT, 4)
            
            print(">> VBO Engine: SDF Font Texture Loaded!")
        except Exception as e:
            print(f"❌ Failed to load font texture: {e}")

    def upload_text_geometry(self, vertices, texcoords, colors, indices):
        if not self.is_initialized or len(vertices) == 0:
            self.text_index_count = 0
            return

        interleaved = np.hstack((vertices, texcoords, colors)).astype(np.float32).flatten()
        indices = indices.astype(np.uint32).flatten()
        new_index_count = len(indices)

        glBindVertexArray(self.text_vao)
        glBindBuffer(GL_ARRAY_BUFFER, self.text_vbo)

        if new_index_count == self.text_index_count:
            glBufferSubData(GL_ARRAY_BUFFER, 0, interleaved.nbytes, interleaved)
        else:
            glBufferData(GL_ARRAY_BUFFER, interleaved.nbytes, interleaved, GL_DYNAMIC_DRAW)
            glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, self.text_ebo)
            glBufferData(GL_ELEMENT_ARRAY_BUFFER, indices.nbytes, indices, GL_DYNAMIC_DRAW)

        self.text_index_count = new_index_count

        stride = 9 * 4
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(0))
        glEnableVertexAttribArray(0)
        glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(12))
        glEnableVertexAttribArray(1)
        glVertexAttribPointer(2, 4, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(20))
        glEnableVertexAttribArray(2)

        glBindVertexArray(0)

    def draw_text(self, view_matrix, proj_matrix, texture_id):
        if not self.is_initialized or self.text_index_count == 0:
            return

        glUseProgram(self.text_shader_program)
        glUniformMatrix4fv(self.loc_text_view, 1, GL_FALSE, view_matrix)
        glUniformMatrix4fv(self.loc_text_proj, 1, GL_FALSE, proj_matrix)
        
        glUniform1f(self.loc_text_smooth, 0.05) 

        glActiveTexture(GL_TEXTURE0)
        glBindTexture(GL_TEXTURE_2D, texture_id)
        glUniform1i(self.loc_text_tex, 0)

        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glDisable(GL_DEPTH_TEST)                                                                        

        glBindVertexArray(self.text_vao)
        glDrawElements(GL_TRIANGLES, self.text_index_count, GL_UNSIGNED_INT, None)
        glBindVertexArray(0)

        glEnable(GL_DEPTH_TEST)
        glUseProgram(0)

        glActiveTexture(GL_TEXTURE0)
        glBindTexture(GL_TEXTURE_2D, 0)
        glBindBuffer(GL_ARRAY_BUFFER, 0)
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, 0)