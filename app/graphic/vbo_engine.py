import numpy as np
from OpenGL.GL import *
from OpenGL.GL import shaders
import ctypes

from app.graphic._vbo_area import AreaMixin
from app.graphic._vbo_lines import LineMixin
from app.graphic._vbo_extruded import ExtrudedMixin
from app.graphic._vbo_force_load import ForceLoadMixin
from app.graphic._vbo_text import TextMixin
from app.graphic._vbo_static import StaticMixin
from app.graphic._vbo_grid_bubble import GridBubbleMixin, GridLineMixin
from app.graphic._vbo_transparency import TransparencyMixin

from app.graphic.ltha_renderer import VectorizedLTHAEngine 

class VBORenderManager(TransparencyMixin, AreaMixin, LineMixin, ExtrudedMixin, ForceLoadMixin, TextMixin, StaticMixin, GridBubbleMixin, GridLineMixin):
    def __init__(self):
        self.shader_program = None
        self.lit_shader_program = None
        self.line_shader_program = None                                                
        self._vp_px = None
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

        self.spring_vao = None
        self.spring_vbo = None
        self.spring_vertex_count = 0
        self.persistent_spring_buffer = None

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

        self.static_line_vao = None
        self.static_line_vbo = None
        self.static_line_vertex_count = 0

        self.grid_bubble_vao = None
        self.grid_bubble_vbo = None
        self.grid_bubble_vertex_count = 0

        self.grid_line_vao = None
        self.grid_line_vbo = None
        self.grid_line_vertex_count = 0
        self.grid_line_split = 0
        
        self.persistent_ext_buffer = None
        self.ext_owner = None                                                                         

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
            float alpha = v_color.a * u_alpha_mult;
            if (alpha <= 0.0) discard;
            FragColor = vec4(v_color.rgb, alpha);
        }
        """

        self.line_geom_shader_source = """
        #version 330 core
        layout(lines) in;
        layout(triangle_strip, max_vertices = 4) out;

        in vec4 v_color[];
        out vec4 g_color;
        // screen-space (pixel) edge coordinates, used for analytic AA:
        //   x = signed distance across the line from its centre line
        //   y = distance beyond the START cap (negative = inside)
        //   z = distance beyond the END cap   (negative = inside)
        noperspective out vec3 g_edge;

        uniform vec2  u_viewport;   // framebuffer size in pixels
        uniform float u_line_px;    // line width in pixels (>= 1.0)

        void main() {
            vec4 p0 = gl_in[0].gl_Position;
            vec4 p1 = gl_in[1].gl_Position;
            vec4 c0 = v_color[0];
            vec4 c1 = v_color[1];

            // clip the segment against the near plane (z >= -w)
            float d0 = p0.z + p0.w;
            float d1 = p1.z + p1.w;
            if (d0 < 0.0 && d1 < 0.0) return;
            if (d0 < 0.0) {
                float t = d0 / (d0 - d1);
                p0 = mix(p0, p1, t);  c0 = mix(c0, c1, t);
            } else if (d1 < 0.0) {
                float t = d1 / (d1 - d0);
                p1 = mix(p1, p0, t);  c1 = mix(c1, c0, t);
            }
            p0.w = max(p0.w, 1e-6);
            p1.w = max(p1.w, 1e-6);

            vec2 half_vp = u_viewport * 0.5;
            vec2 s0 = p0.xy / p0.w * half_vp;
            vec2 s1 = p1.xy / p1.w * half_vp;

            vec2 d = s1 - s0;
            float len = length(d);
            vec2 dir = (len > 1e-4) ? d / len : vec2(1.0, 0.0);
            vec2 nrm = vec2(-dir.y, dir.x);

            float hw  = 0.5 * u_line_px;
            float ext = hw + 1.0;          // quad is 1px wider than the line: that px is the AA fringe
            vec2 a = s0 - dir * ext;
            vec2 b = s1 + dir * ext;
            vec2 o = nrm * ext;

            gl_Position = vec4((a + o) / half_vp * p0.w, p0.z, p0.w); g_color = c0; g_edge = vec3( ext,  ext, -(len + ext)); EmitVertex();
            gl_Position = vec4((a - o) / half_vp * p0.w, p0.z, p0.w); g_color = c0; g_edge = vec3(-ext,  ext, -(len + ext)); EmitVertex();
            gl_Position = vec4((b + o) / half_vp * p1.w, p1.z, p1.w); g_color = c1; g_edge = vec3( ext, -(len + ext),  ext); EmitVertex();
            gl_Position = vec4((b - o) / half_vp * p1.w, p1.z, p1.w); g_color = c1; g_edge = vec3(-ext, -(len + ext),  ext); EmitVertex();
            EndPrimitive();
        }
        """

        self.line_fragment_shader_source = """
        #version 330 core
        in vec4 g_color;
        noperspective in vec3 g_edge;
        out vec4 FragColor;
        uniform float u_alpha_mult;
        uniform float u_line_px;
        void main() {
            // analytic coverage: 1px linear ramp centred on the true line edge.
            // Works with MSAA on, off, or FXAA -- lines are smooth by themselves.
            float hw = 0.5 * u_line_px;
            float cov = clamp(hw + 0.5 - abs(g_edge.x), 0.0, 1.0)
                      * clamp(hw + 0.5 - g_edge.y,      0.0, 1.0)
                      * clamp(hw + 0.5 - g_edge.z,      0.0, 1.0);
            float a = g_color.a * u_alpha_mult * cov;
            if (a < 0.01) discard;   // keeps the invisible fringe from writing depth
            FragColor = vec4(g_color.rgb, a);
        }
        """

        self.lit_vertex_shader_source = """
        #version 330 core
        layout(location = 0) in vec3 a_position;
        layout(location = 1) in vec4 a_color;
        layout(location = 2) in vec3 a_displacement;
        layout(location = 3) in vec3 a_normal;

        uniform mat4 u_view;
        uniform mat4 u_projection;
        uniform float u_anim_factor;

        out vec4 v_color;
        out vec3 v_normal;
        out vec3 v_world_pos;

        void main() {
            vec3 animated_pos = a_position + a_displacement * u_anim_factor;
            gl_Position = u_projection * u_view * vec4(animated_pos, 1.0);
            v_color = a_color;
            v_normal = a_normal;
            v_world_pos = animated_pos;
        }
        """

        self.lit_fragment_shader_source = """
        #version 330 core
        in vec4 v_color;
        in vec3 v_normal;
        in vec3 v_world_pos;
        out vec4 FragColor;

        uniform float u_alpha_mult;
        uniform vec3 u_light_dir;   // world-space, points FROM the surface TOWARD the light
        uniform vec3 u_view_pos;    // camera position, world-space
        uniform float u_ambient;
        uniform float u_diffuse;
        uniform float u_specular;
        uniform float u_shininess;
        uniform float u_fresnel_intensity;   // 0 = off, glass "glaze" rim strength
        uniform float u_fresnel_power;       // how tight the rim is (higher = thinner edge glow)

        void main() {
            // Derive a flat normal from the final animated triangle. Shared
            // playback vertices and changing deformation cannot leave stale
            // or averaged normals on box/I-beam faces.
            vec3 dpdx = dFdx(v_world_pos);
            vec3 dpdy = dFdy(v_world_pos);
            // Scale before crossing so the normal is independent of model
            // units, including very small sections and large coordinates.
            float derivative_scale = max(max(abs(dpdx.x), abs(dpdx.y)), abs(dpdx.z));
            derivative_scale = max(derivative_scale,
                max(max(abs(dpdy.x), abs(dpdy.y)), abs(dpdy.z)));
            vec3 geometric_normal = derivative_scale > 0.0
                ? cross(dpdx / derivative_scale, dpdy / derivative_scale) : v_normal;
            float normal_length_sq = dot(geometric_normal, geometric_normal);
            vec3 N = normal_length_sq > 1e-20
                ? geometric_normal * inversesqrt(normal_length_sq)
                : normalize(v_normal);
            vec3 V = normalize(u_view_pos - v_world_pos);

            // Double-sided: flip the flat face normal to face the camera so
            // the underside of a slab (or the far wall of a beam) doesn't
            // read as pure black just because winding faces the other way.
            if (dot(N, V) < 0.0) {
                N = -N;
            }

            vec3 L = normalize(u_light_dir);
            float diff = max(dot(N, L), 0.0);

            vec3 H = normalize(L + V);
            float spec = diff > 0.0
                ? pow(max(dot(N, H), 0.0), max(u_shininess, 1.0)) : 0.0;

            // Fresnel/glazing rim: grazing-angle faces (edge-on to the
            // camera) glow brighter, the way light catches the edge of a
            // pane of glass as you tilt it. Sweeps continuously across the
            // surface as the camera orbits, unlike the specular spot above.
            float ndotv = max(dot(N, V), 0.0);
            float fresnel = pow(1.0 - ndotv, max(u_fresnel_power, 0.1)) * u_fresnel_intensity;

            float lighting = u_ambient + u_diffuse * diff;
            vec3 rgb = v_color.rgb * lighting + vec3(1.0) * (u_specular * spec) + vec3(1.0) * fresnel;

            float alpha = v_color.a * u_alpha_mult;
            if (alpha <= 0.0) discard;
            FragColor = vec4(rgb, alpha);
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

            lit_vertex_shader = shaders.compileShader(self.lit_vertex_shader_source, GL_VERTEX_SHADER)
            lit_fragment_shader = shaders.compileShader(self.lit_fragment_shader_source, GL_FRAGMENT_SHADER)
            self.lit_shader_program = shaders.compileProgram(lit_vertex_shader, lit_fragment_shader)

            try:
                _lv = shaders.compileShader(self.vertex_shader_source, GL_VERTEX_SHADER)
                _lg = shaders.compileShader(self.line_geom_shader_source, GL_GEOMETRY_SHADER)
                _lf = shaders.compileShader(self.line_fragment_shader_source, GL_FRAGMENT_SHADER)
                self.line_shader_program = shaders.compileProgram(_lv, _lg, _lf)
                _p = self.line_shader_program
                self.loc_line_view     = glGetUniformLocation(_p, "u_view")
                self.loc_line_proj     = glGetUniformLocation(_p, "u_projection")
                self.loc_line_alpha    = glGetUniformLocation(_p, "u_alpha_mult")
                self.loc_line_anim     = glGetUniformLocation(_p, "u_anim_factor")
                self.loc_line_viewport = glGetUniformLocation(_p, "u_viewport")
                self.loc_line_px       = glGetUniformLocation(_p, "u_line_px")
            except Exception as e:
                print(f"VBO Engine: wide-line shader unavailable, using glLineWidth ({e})")
                self.line_shader_program = None

            self.vao = glGenVertexArrays(1)
            self.vbo = glGenBuffers(1)
            self.ebo = glGenBuffers(1)

            self.line_vao = glGenVertexArrays(1)
            self.line_vbo = glGenBuffers(1)

            self.spring_vao = glGenVertexArrays(1)
            self.spring_vbo = glGenBuffers(1)

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

            self.static_line_vao = glGenVertexArrays(1)
            self.static_line_vbo = glGenBuffers(1)

            self.grid_bubble_vao = glGenVertexArrays(1)
            self.grid_bubble_vbo = glGenBuffers(1)

            self.grid_line_vao = glGenVertexArrays(1)
            self.grid_line_vbo = glGenBuffers(1)

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

            self.loc_lit_view       = glGetUniformLocation(self.lit_shader_program, "u_view")
            self.loc_lit_proj       = glGetUniformLocation(self.lit_shader_program, "u_projection")
            self.loc_lit_alpha      = glGetUniformLocation(self.lit_shader_program, "u_alpha_mult")
            self.loc_lit_anim       = glGetUniformLocation(self.lit_shader_program, "u_anim_factor")
            self.loc_lit_light_dir  = glGetUniformLocation(self.lit_shader_program, "u_light_dir")
            self.loc_lit_view_pos   = glGetUniformLocation(self.lit_shader_program, "u_view_pos")
            self.loc_lit_ambient    = glGetUniformLocation(self.lit_shader_program, "u_ambient")
            self.loc_lit_diffuse    = glGetUniformLocation(self.lit_shader_program, "u_diffuse")
            self.loc_lit_specular   = glGetUniformLocation(self.lit_shader_program, "u_specular")
            self.loc_lit_shininess  = glGetUniformLocation(self.lit_shader_program, "u_shininess")
            self.loc_lit_fresnel_i  = glGetUniformLocation(self.lit_shader_program, "u_fresnel_intensity")
            self.loc_lit_fresnel_p  = glGetUniformLocation(self.lit_shader_program, "u_fresnel_power")

            print(">> VBO Engine: Shaders & Buffers Ready!")
        except Exception as e:
            print(f"❌ VBO Engine Initialization Failed: {e}")

    def set_viewport_px(self, w, h):
        """Called once per frame by canvas.paintGL so the line shader doesn't
        have to do a glGetIntegerv(GL_VIEWPORT) round-trip on every draw call."""
        self._vp_px = (0, 0, int(w), int(h))

    def _use_line_program(self, view_matrix, proj_matrix, alpha_mult, anim_factor, line_width):
        """
        Binds the program used for every GL_LINES draw and sets all uniforms.
        With the geometry-shader program the width is a true float in pixels.
        Below 1px the quad stays 1px wide and the alpha is scaled by the width
        (a 0.5px quad would otherwise miss pixel centres and break into dashes).
        Falls back to plain glLineWidth if the program failed to build.
        """
        lw = float(line_width)
        if self.line_shader_program:
            vp = self._vp_px
            if vp is None:
                vp = glGetIntegerv(GL_VIEWPORT)                                                      
            glUseProgram(self.line_shader_program)
            glUniformMatrix4fv(self.loc_line_view, 1, GL_FALSE, view_matrix)
            glUniformMatrix4fv(self.loc_line_proj, 1, GL_FALSE, proj_matrix)
            glUniform1f(self.loc_line_alpha, alpha_mult * min(lw, 1.0))
            glUniform1f(self.loc_line_anim, anim_factor)
            glUniform2f(self.loc_line_viewport, float(vp[2]), float(vp[3]))
            glUniform1f(self.loc_line_px, max(lw, 1.0))
            return
        glUseProgram(self.shader_program)
        glUniformMatrix4fv(self.loc_view, 1, GL_FALSE, view_matrix)
        glUniformMatrix4fv(self.loc_proj, 1, GL_FALSE, proj_matrix)
        glUniform1f(self.loc_alpha, alpha_mult)
        glUniform1f(self.loc_anim, anim_factor)
        glLineWidth(lw)

    def _use_lit_program(self, view_matrix, proj_matrix, alpha_mult, light):
        """
        Binds the lit shader and pushes view/proj/alpha/anim + all lighting
        uniforms. `light` is the dict produced by canvas.py's paintGL from
        the Graphics Options settings -- see GraphicsOptionsDialog defaults.
        Returns True if the lit program is bound, False if lighting is off
        or the program failed to compile (caller should fall back to the
        flat self.shader_program in that case).
        """
        if not light or not light.get("enabled", False) or not self.lit_shader_program:
            return False

        glUseProgram(self.lit_shader_program)
        glUniformMatrix4fv(self.loc_lit_view, 1, GL_FALSE, view_matrix)
        glUniformMatrix4fv(self.loc_lit_proj, 1, GL_FALSE, proj_matrix)
        glUniform1f(self.loc_lit_alpha, alpha_mult)
        glUniform1f(self.loc_lit_anim, self.current_anim_factor)
        glUniform3f(self.loc_lit_light_dir, *light["light_dir"])
        glUniform3f(self.loc_lit_view_pos, *light["view_pos"])
        glUniform1f(self.loc_lit_ambient, light.get("ambient", 0.35))
        glUniform1f(self.loc_lit_diffuse, light.get("diffuse", 0.75))
        glUniform1f(self.loc_lit_specular, light.get("specular", 0.25))
        glUniform1f(self.loc_lit_shininess, light.get("shininess", 32.0))
        glUniform1f(self.loc_lit_fresnel_i, light.get("fresnel_intensity", 0.0))
        glUniform1f(self.loc_lit_fresnel_p, light.get("fresnel_power", 3.0))
        return True

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
                                                                                
            self.persistent_ext_buffer = np.zeros(num_ext_verts * 13, dtype=np.float32)
            self.persistent_ext_buffer[12::13] = 1.0
        else:
            self.persistent_ext_buffer = None
        self.ext_owner = None
