                           
import numpy as np
from OpenGL.GL import *
from OpenGL.GL import shaders
import ctypes

from app.graphic._vbo_area import AreaMixin
from app.graphic._vbo_lines import LineMixin
from app.graphic._vbo_extruded import ExtrudedMixin
from app.graphic._vbo_force_load import ForceLoadMixin
from app.graphic._vbo_text import TextMixin

from app.graphic.ltha_renderer import VectorizedLTHAEngine 

class VBORenderManager(AreaMixin, LineMixin, ExtrudedMixin, ForceLoadMixin, TextMixin):
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
        self.persistent_line_buffer = None                           

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
        
        self.persistent_ext_buffer = None                            

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

    def set_anim_factor(self, factor):
        """Sets the animation blend factor for the current frame."""
        if not self.is_initialized:
            return
        self.current_anim_factor = float(factor)

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
