import numpy as np
from OpenGL.GL import *
from OpenGL.GL import shaders
from PIL import Image

class VBORenderManager:
    def __init__(self):
        self.shader_program = None
        self.is_initialized = False
        
        self.vao = None
        self.vbo = None
        self.ebo = None
        self.index_count = 0
        self.current_anim_factor = 0.0
                                                 
        self.line_vao = None
        self.line_vbo = None
        self.line_vertex_count = 0

        self.area_vao = None
        self.area_vbo = None
        self.area_ebo = None
        self.area_index_count = 0

        self.area_edge_vao = None
        self.area_edge_vbo = None
        self.area_edge_vertex_count = 0

        self.force_fill_vao = None
        self.force_fill_vbo = None
        self.force_fill_ebo = None
        self.force_fill_index_count = 0

        self.force_line_vao = None
        self.force_line_vbo = None
        self.force_line_vertex_count = 0

        self.load_fill_vao = None
        self.load_fill_vbo = None
        self.load_fill_ebo = None
        self.load_fill_index_count = 0

        self.load_line_vao = None
        self.load_line_vbo = None
        self.load_line_vertex_count = 0

        self.sdf_vertex_shader_source = """
        #version 330 core
        layout(location = 0) in vec3 a_position;
        layout(location = 1) in vec2 a_texcoord;
        layout(location = 2) in vec4 a_color;

        uniform mat4 u_view;
        uniform mat4 u_projection;
        uniform float u_camera_dist; 

        out vec2 v_texcoord;
        out vec4 v_color;

        void main() {
            gl_Position = u_projection * u_view * vec4(a_position, 1.0);
            v_texcoord = a_texcoord;
            v_color = a_color;
        }
        """

        self.sdf_fragment_shader_source = """
        #version 330 core
        in vec2 v_texcoord;
        in vec4 v_color;
        out vec4 FragColor;

        uniform sampler2D u_texture;
        uniform float u_smoothing; 

        void main() {
            float distance = texture(u_texture, v_texcoord).r;
            float alpha = smoothstep(0.5 - u_smoothing, 0.5 + u_smoothing, distance);
            FragColor = vec4(v_color.rgb, v_color.a * alpha);
        }
        """

        self.vertex_shader_source = """
        #version 330 core
        layout(location = 0) in vec3 a_position;
        layout(location = 1) in vec4 a_color;
        layout(location = 2) in vec3 a_displacement;

        uniform mat4 u_view;
        uniform mat4 u_projection;
        uniform float u_anim_factor;

        out vec4 v_color;

        void main() {
            vec3 animated_pos = a_position + a_displacement * u_anim_factor;
            gl_Position = u_projection * u_view * vec4(animated_pos, 1.0);
            v_color = a_color;
        }
        """

        self.fragment_shader_source = """
        #version 330 core
        in vec4 v_color;
        out vec4 FragColor;
        
        uniform float u_alpha_mult; 
        
        void main() {
            FragColor = vec4(v_color.rgb, v_color.a * u_alpha_mult);
        }
        """

    def init_gl(self):
        if self.is_initialized:
            return

        print(">> VBO Engine: Initializing OpenGL Context...")
        try:
            vertex_shader = shaders.compileShader(self.vertex_shader_source, GL_VERTEX_SHADER)
            fragment_shader = shaders.compileShader(self.fragment_shader_source, GL_FRAGMENT_SHADER)
            self.shader_program = shaders.compileProgram(vertex_shader, fragment_shader)

            self.vao = glGenVertexArrays(1)
            self.vbo = glGenBuffers(1)
            self.ebo = glGenBuffers(1)

            self.line_vao = glGenVertexArrays(1)
            self.line_vbo = glGenBuffers(1)

            self.area_vao = glGenVertexArrays(1)
            self.area_vbo = glGenBuffers(1)
            self.area_ebo = glGenBuffers(1)

            self.area_edge_vao = glGenVertexArrays(1)
            self.area_edge_vbo = glGenBuffers(1)

            self.force_fill_vao = glGenVertexArrays(1)
            self.force_fill_vbo = glGenBuffers(1)
            self.force_fill_ebo = glGenBuffers(1)

            self.force_line_vao = glGenVertexArrays(1)
            self.force_line_vbo = glGenBuffers(1)

            self.load_fill_vao = glGenVertexArrays(1)
            self.load_fill_vbo = glGenBuffers(1)
            self.load_fill_ebo = glGenBuffers(1)

            self.load_line_vao = glGenVertexArrays(1)
            self.load_line_vbo = glGenBuffers(1)

            sdf_vert = shaders.compileShader(self.sdf_vertex_shader_source, GL_VERTEX_SHADER)
            sdf_frag = shaders.compileShader(self.sdf_fragment_shader_source, GL_FRAGMENT_SHADER)
            self.text_shader_program = shaders.compileProgram(sdf_vert, sdf_frag)

            self.text_vao = glGenVertexArrays(1)
            self.text_vbo = glGenBuffers(1)
            self.text_ebo = glGenBuffers(1)
            self.text_index_count = 0

            self.loc_text_view = glGetUniformLocation(self.text_shader_program, "u_view")
            self.loc_text_proj = glGetUniformLocation(self.text_shader_program, "u_projection")
            self.loc_text_tex  = glGetUniformLocation(self.text_shader_program, "u_texture")
            self.loc_text_smooth = glGetUniformLocation(self.text_shader_program, "u_smoothing")

            self.is_initialized = True

            self.loc_view  = glGetUniformLocation(self.shader_program, "u_view")
            self.loc_proj  = glGetUniformLocation(self.shader_program, "u_projection")
            self.loc_alpha = glGetUniformLocation(self.shader_program, "u_alpha_mult")
            self.loc_anim  = glGetUniformLocation(self.shader_program, "u_anim_factor")

            print(">> VBO Engine: Shaders & Buffers Ready!")
        except Exception as e:
            print(f"❌ VBO Engine Initialization Failed: {e}")

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

    def set_anim_factor(self, factor):
        """Sets the animation blend factor for the current frame."""
        if not self.is_initialized:
            return
        self.current_anim_factor = float(factor)

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

    def allocate_ltha_buffers(self, num_line_verts, num_ext_verts=0):
        """
        [PHASE 1: ZERO ALLOCATION]
        Pre-allocates the exact memory block needed for the entire model.
        We do this ONCE at load time so Python never triggers Garbage Collection during playback.
        """
        self.line_vertex_count = num_line_verts
                                                         
        if num_line_verts > 0:
            self.persistent_line_buffer = np.zeros(num_line_verts * 10, dtype=np.float32)
        else:
            self.persistent_line_buffer = None
            
        if num_ext_verts > 0:
            self.persistent_ext_buffer = np.zeros(num_ext_verts * 10, dtype=np.float32)
        else:
            self.persistent_ext_buffer = None

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
import numpy as np

class VectorizedLTHAEngine:
    """
    High-performance vectorized engine for LTHA animation.
    Eliminates Python loops by computing Hermite curves for all elements 
    simultaneously using batched NumPy tensor operations.
    """
    def __init__(self, num_elements):
        self.N = num_elements
        self.num_points = 11
        
        self.P1 = np.zeros((self.N, 3), dtype=np.float32)
        self.P2 = np.zeros((self.N, 3), dtype=np.float32)
        self.L = np.zeros((self.N, 1), dtype=np.float32)
        self.off_i = np.zeros((self.N, 1), dtype=np.float32)
        self.off_j = np.zeros((self.N, 1), dtype=np.float32)
        self.R = np.zeros((self.N, 3, 3), dtype=np.float32)
        
        self.idx_i = np.zeros(self.N, dtype=np.int32)
        self.idx_j = np.zeros(self.N, dtype=np.int32)
        self.colors = np.zeros((self.N, 4), dtype=np.float32)
        
        s = np.linspace(0, 1, self.num_points).reshape(1, self.num_points).astype(np.float32)
        s2 = s * s
        s3 = s2 * s
        
        self.s = s
        self.one_minus_s = 1.0 - s
        self.H1 = 1.0 - 3.0*s2 + 2.0*s3
        self.H3 = 3.0*s2 - 2.0*s3
        self.H2_base = s * (1.0 - s)**2
        self.H4_base = s * (s2 - s)

    def compute_wireframe(self, U_nodes, scale):
        """
        Calculates all line geometry for the current frame instantly.
        U_nodes: NumPy array of shape (N_nodes, 6) containing current timestep displacements
        """
        if self.N == 0:
            return np.array([]), np.array([])

        U_i = U_nodes[self.idx_i] * scale
        U_j = U_nodes[self.idx_j] * scale
        
        u_global_i, theta_global_i = U_i[:, :3], U_i[:, 3:]
        u_global_j, theta_global_j = U_j[:, :3], U_j[:, 3:]
        
        u_local_i = np.einsum('nij,nj->ni', self.R, u_global_i)
        theta_local_i = np.einsum('nij,nj->ni', self.R, theta_global_i)
        u_local_j = np.einsum('nij,nj->ni', self.R, u_global_j)
        theta_local_j = np.einsum('nij,nj->ni', self.R, theta_global_j)
        
        u1_i, u1_j = u_local_i[:, 0:1], u_local_j[:, 0:1]
        v_i, v_j   = u_local_i[:, 1:2], u_local_j[:, 1:2]
        w_i, w_j   = u_local_i[:, 2:3], u_local_j[:, 2:3]
        
        dv_i, dv_j = theta_local_i[:, 2:3], theta_local_j[:, 2:3]
        dw_i, dw_j = -theta_local_i[:, 1:2], -theta_local_j[:, 1:2]
        
        x_val = self.L @ self.s
        
        v_flex_i, w_flex_i = v_i + dv_i * self.off_i, w_i + dw_i * self.off_i
        v_flex_j, w_flex_j = v_j - dv_j * self.off_j, w_j - dw_j * self.off_j
        
        L_flex = np.maximum(self.L - self.off_i - self.off_j, 1e-6)
        s_flex = np.clip((x_val - self.off_i) / L_flex, 0.0, 1.0)
        
        s2 = s_flex * s_flex
        s3 = s2 * s_flex
        H1 = 1.0 - 3.0*s2 + 2.0*s3
        H2 = (s_flex * L_flex) * (1.0 - s_flex)**2
        H3 = 3.0*s2 - 2.0*s3
        H4 = (s_flex * L_flex) * (s2 - s_flex)
        
        disp_axial = u1_i + (u1_j - u1_i) * s_flex
        disp_v = v_flex_i * H1 + dv_i * H2 + v_flex_j * H3 + dv_j * H4
        disp_w = w_flex_i * H1 + dw_i * H2 + w_flex_j * H3 + dw_j * H4
        
        mask_i = x_val <= self.off_i + 1e-6
        mask_j = x_val >= self.L - self.off_j - 1e-6
        
        disp_axial = np.where(mask_i, u1_i * np.ones_like(x_val), disp_axial)
        disp_v = np.where(mask_i, v_i + dv_i * x_val, disp_v)
        disp_w = np.where(mask_i, w_i + dw_i * x_val, disp_w)
        
        dx_from_j = x_val - self.L
        disp_axial = np.where(mask_j, u1_j * np.ones_like(x_val), disp_axial)
        disp_v = np.where(mask_j, v_j + dv_j * dx_from_j, disp_v)
        disp_w = np.where(mask_j, w_j + dw_j * dx_from_j, disp_w)

        local_pos = np.stack([x_val + disp_axial, disp_v, disp_w], axis=2)
        
        RT = self.R.transpose(0, 2, 1)
        global_disp = np.einsum('nij,nkj->nki', RT, local_pos)
        v1_global = self.R[:, 0, :]
        P1_shifted = self.P1 + v1_global * self.off_i

        global_pos = P1_shifted[:, None, :] + global_disp
                                                                              
        start_pts = global_pos[:, :-1, :]              
        end_pts   = global_pos[:, 1:, :]               
        
        lines = np.stack([start_pts, end_pts], axis=2)                
        lines_flat = lines.reshape(-1, 3)                         
        
        colors_flat = np.repeat(self.colors, 20, axis=0)            
        
        return lines_flat, colors_flat
    
    def set_extruded_mapping(self, E, P, off, Y, Z, colors):
        """Stores the flat topology mapping for instantly building 3D faces."""
        self.ext_E = np.array(E, dtype=np.int32)
        self.ext_P = np.array(P, dtype=np.int32)
        self.ext_off = np.array(off, dtype=np.float32)
        self.ext_Y = np.array(Y, dtype=np.float32)[:, None]
        self.ext_Z = np.array(Z, dtype=np.float32)[:, None]
        self.ext_colors_flat = np.array(colors, dtype=np.float32).flatten()

    def compute_extruded(self, U_nodes, scale):
        if not hasattr(self, 'ext_E') or len(self.ext_E) == 0:
            return np.array([]), np.array([])
            
        U_i = U_nodes[self.idx_i] * scale
        U_j = U_nodes[self.idx_j] * scale
        
        u_local_i = np.einsum('nij,nj->ni', self.R, U_i[:, :3])
        theta_local_i = np.einsum('nij,nj->ni', self.R, U_i[:, 3:])
        u_local_j = np.einsum('nij,nj->ni', self.R, U_j[:, :3])
        theta_local_j = np.einsum('nij,nj->ni', self.R, U_j[:, 3:])
        
        u1_i, u1_j = u_local_i[:, 0:1], u_local_j[:, 0:1]
        v_i, v_j   = u_local_i[:, 1:2], u_local_j[:, 1:2]
        w_i, w_j   = u_local_i[:, 2:3], u_local_j[:, 2:3]
        dv_i, dv_j = theta_local_i[:, 2:3], theta_local_j[:, 2:3]
        dw_i, dw_j = -theta_local_i[:, 1:2], -theta_local_j[:, 1:2]
        twist_i, twist_j = theta_local_i[:, 0:1], theta_local_j[:, 0:1]

        v_flex_i, w_flex_i = v_i + dv_i * self.off_i, w_i + dw_i * self.off_i
        v_flex_j, w_flex_j = v_j - dv_j * self.off_j, w_j - dw_j * self.off_j
        
        L_flex = np.maximum(self.L - self.off_i - self.off_j, 1e-6)
        x_val = self.off_i + L_flex @ self.s
        s_flex = self.s                                       
        
        s2 = s_flex * s_flex
        s3 = s2 * s_flex
        H1 = 1.0 - 3.0*s2 + 2.0*s3
        H2 = (s_flex * L_flex) * (1.0 - s_flex)**2
        H3 = 3.0*s2 - 2.0*s3
        H4 = (s_flex * L_flex) * (s2 - s_flex)
        
        dH1 = -6.0*s_flex + 6.0*s2
        dH2 = L_flex * (1.0 - 4.0*s_flex + 3.0*s2)
        dH3 = 6.0*s_flex - 6.0*s2
        dH4 = L_flex * (3.0*s2 - 2.0*s_flex)
        
        axial_strain = (u1_j - u1_i) / self.L
        disp_axial = u1_i + axial_strain * x_val
        disp_v = v_flex_i * H1 + dv_i * H2 + v_flex_j * H3 + dv_j * H4
        disp_w = w_flex_i * H1 + dw_i * H2 + w_flex_j * H3 + dw_j * H4
        
        d_axial_ds = (L_flex + axial_strain * L_flex) * np.ones((1, self.num_points), dtype=np.float32)
        d_v_ds = (v_flex_i * dH1 + dv_i * dH2 + v_flex_j * dH3 + dv_j * dH4)
        d_w_ds = (w_flex_i * dH1 + dw_i * dH2 + w_flex_j * dH3 + dw_j * dH4)
        curr_twist = twist_i + (twist_j - twist_i) * (x_val / self.L)

        local_pos = np.stack([x_val + disp_axial, disp_v, disp_w], axis=2)
        local_tan = np.stack([d_axial_ds, d_v_ds, d_w_ds], axis=2)
        
        RT = self.R.transpose(0, 2, 1)
        global_pos = self.P1[:, None, :] + np.einsum('nij,nkj->nki', RT, local_pos)
        
        norms = np.linalg.norm(local_tan, axis=2, keepdims=True)
        norms[norms < 1e-9] = 1.0
        local_tan_norm = local_tan / norms
        v1_curr = np.einsum('nij,nkj->nki', RT, local_tan_norm)

        v2_orig = self.R[:, 1, :][:, None, :] 
        v3_orig = self.R[:, 2, :][:, None, :] 
        
        c_t = np.cos(curr_twist)[..., None] 
        s_t = np.sin(curr_twist)[..., None]
        
        v2_twisted = c_t * v2_orig + s_t * v3_orig
        proj = np.sum(v2_twisted * v1_curr, axis=2, keepdims=True) * v1_curr
        v2_curr = v2_twisted - proj
        
        norms_v2 = np.linalg.norm(v2_curr, axis=2, keepdims=True)
        norms_v2[norms_v2 < 1e-9] = 1.0
        v2_curr = v2_curr / norms_v2
        v3_curr = np.cross(v1_curr, v2_curr)
        
        E = self.ext_E
        P = self.ext_P
        verts = global_pos[E, P] + self.ext_off + self.ext_Y * v2_curr[E, P] + self.ext_Z * v3_curr[E, P]
        
        return verts.flatten(), self.ext_colors_flat
