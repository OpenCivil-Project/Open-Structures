"""Static load descriptors; the vertex shader sizes glyphs for each camera."""
import ctypes

import numpy as np
from OpenGL.GL import *
from OpenGL.GL import shaders

BOUNDS_GLSL = r"""
uniform mat4 u_view;
uniform mat4 u_projection;
uniform vec2 u_logical_viewport;
uniform samplerBuffer u_profile_factors;

float profile_factor(float group) {
    return group >= 0.0 ? texelFetch(u_profile_factors, int(group + .5)).r : 1.0;
}

bool visible_owner(vec3 point) {
    vec4 p = u_projection * u_view * vec4(point, 1.0);
    return p.w > 1e-7 && all(lessThanEqual(abs(p.xyz), vec3(p.w)));
}

float bounded_length(vec3 tip, vec3 direction, float nominal, float max_px, float min_px) {
    if (nominal <= 0.0) return 0.0;
    mat4 mvp = u_projection * u_view;
    vec4 p = mvp * vec4(tip, 1.0);
    vec4 step = mvp * vec4(-direction, 0.0);
    vec3 values = vec3(p.w + p.z, p.w - p.z, p.w);
    vec3 changes = vec3(step.w + step.z, step.w - step.z, step.w);
    if (p.w <= 1e-7 || any(lessThanEqual(values, vec3(0.0)))) return 0.0;
    float limit = 1e30;
    for (int i = 0; i < 3; ++i) {
        if (changes[i] < 0.0) limit = min(limit, values[i] / -changes[i] * .999);
    }
    float result = min(nominal, limit);
    vec2 ndc = p.xy / p.w;
    vec2 pixels = u_logical_viewport * .5;
    float speed = length(pixels * (step.xy - ndc * step.w));
    if (speed <= 1e-7) return result;
    vec3 row_x = vec3(mvp[0].x, mvp[1].x, mvp[2].x);
    vec3 row_y = vec3(mvp[0].y, mvp[1].y, mvp[2].y);
    vec3 row_w = vec3(mvp[0].w, mvp[1].w, mvp[2].w);
    vec3 jac_x = pixels.x * (row_x - ndc.x * row_w);
    vec3 jac_y = pixels.y * (row_y - ndc.y * row_w);
    float jac_norm = sqrt(dot(jac_x, jac_x) + dot(jac_y, jac_y));
    float current = result * speed / (p.w + result * step.w);
    float target = min(max_px, max(min_px, current));
    if (target > current && speed < .1 * jac_norm) return result;
    float denominator = speed - target * step.w;
    if (denominator <= 1e-7) return result;
    return min(target * p.w / denominator, limit);
}
"""

GLYPH_VERTEX_SHADER = """#version 330 core
layout(location=0) in vec3 a_tip;
layout(location=1) in vec3 a_direction;
layout(location=2) in vec3 a_side;
layout(location=3) in vec4 a_color;
layout(location=4) in vec3 a_shape;
layout(location=5) in vec4 a_parameters;
out vec4 v_color;
out vec3 v_world_position;
""" + BOUNDS_GLSL + """
void main() {
    v_color = a_color;
    float nominal = a_parameters.x * profile_factor(a_parameters.w);
    float shaft = bounded_length(a_tip, a_direction, nominal, a_parameters.y, a_parameters.z);
    vec3 base = a_tip - a_direction * (a_shape.x * shaft);
    if (a_shape.y != 0.0) {
        vec3 wing_direction = a_side * a_shape.y;
        float wing = bounded_length(base, -wing_direction, shaft * a_shape.z, 6.0, 0.0);
        base += wing_direction * wing;
    }
    v_world_position = base;
    if (!visible_owner(a_tip) || shaft <= 0.0) {
        v_color.a = 0.0;
        gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
    } else {
        gl_Position = u_projection * u_view * vec4(base, 1.0);
    }
}
"""

CURTAIN_VERTEX_SHADER = """#version 330 core
layout(location=0) in vec3 a_base;
layout(location=1) in vec4 a_color;
layout(location=2) in vec3 a_offset;
layout(location=3) in float a_group;
layout(location=4) in vec3 a_owner;
layout(location=5) in float a_has_owner;
out vec4 v_color;
out vec3 v_world_position;
""" + BOUNDS_GLSL + """
void main() {
    v_color = a_color;
    v_world_position = a_base + a_offset * profile_factor(a_group);
    if (a_has_owner > .5 && !visible_owner(a_owner)) {
        v_color.a = 0.0;
        gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
    } else {
        gl_Position = u_projection * u_view * vec4(v_world_position, 1.0);
    }
}
"""

def pack_load_view_payload(cache, fill_colors, fill_indices):
    """Build independent static fill, line, and glyph buffers once per edit."""
    def pack_curtain(positions, colors, moving):
        packed = np.zeros((len(positions), 15), dtype=np.float32)
        packed[:, :3] = positions
        packed[:, 3:7] = colors
        packed[:, 10] = -1.
        groups, indices, bases, offsets = moving
        packed[indices, :3] = bases
        packed[indices, 7:10] = offsets
        packed[indices, 10] = groups
        return packed

    fill = pack_curtain(cache.fill_positions, fill_colors, cache.moving_fill)
    lines = pack_curtain(cache.line_positions, cache.original_colors, cache.moving_lines)
    if len(cache.leader_indices):
        for offset in (0, 1):
            lines[cache.leader_indices + offset, 11:14] = cache.leader_anchors
            lines[cache.leader_indices + offset, 14] = 1.
    headed = cache.heads > 0.
    counts = np.where(headed, 6, 2)
    owners = np.repeat(np.arange(len(cache.tips)), counts)
    glyphs = np.empty((len(owners), 20), dtype=np.float32)
    glyphs[:, :3] = cache.tips[owners]
    glyphs[:, 3:6] = cache.directions[owners]
    glyphs[:, 6:9] = cache.sides[owners]
    glyphs[:, 13:16] = 0.
    glyphs[:, 16] = cache.nominal[owners]
    glyphs[:, 17] = cache.maximum[owners]
    glyphs[:, 18] = cache.minimum[owners]
    glyphs[:, 19] = cache.arrow_groups[owners]
    starts = np.r_[0, np.cumsum(counts)[:-1]].astype(int) if len(counts) else np.empty(0, dtype=int)
    glyphs[starts, 13] = 1.
    source_indices = cache.arrow_indices[owners] + np.arange(len(owners)) - np.repeat(starts, counts)
    glyphs[:, 9:13] = cache.original_colors[source_indices]
    head_rows = np.flatnonzero(headed)
    head_starts = starts[head_rows]
    for offset, sign in ((3, 1.), (5, -1.)):
        glyphs[head_starts + offset, 13] = cache.heads[head_rows]
        glyphs[head_starts + offset, 14] = sign
        glyphs[head_starts + offset, 15] = cache.heads[head_rows] * cache.wings[head_rows]
    keep_lines = np.ones(len(lines), dtype=bool)
    keep_lines[source_indices] = False
    return dict(fill=fill, fill_indices=np.ascontiguousarray(fill_indices, dtype=np.uint32).ravel(),
                lines=np.ascontiguousarray(lines[keep_lines]), glyphs=glyphs,
                profile_count=cache.profile_count)

class LoadViewGPURenderer:
    """Load-only programs and storage; force diagrams retain their own shaders."""
    texture_unit = 6

    def __init__(self, manager):
        self.manager = manager
        self.ready = False
        self.logical_viewport = (1., 1.)
        self.programs = {}
        self.locations = {}
        for name, vertex, geometry, fragment in (
                ('fill', CURTAIN_VERTEX_SHADER, None, manager.fragment_shader_source),
                ('lines', CURTAIN_VERTEX_SHADER, manager.line_geom_shader_source,
                 manager.line_fragment_shader_source),
                ('glyphs', GLYPH_VERTEX_SHADER, manager.line_geom_shader_source,
                 manager.line_fragment_shader_source)):
            stages = [shaders.compileShader(vertex, GL_VERTEX_SHADER)]
            if geometry is not None:
                stages.append(shaders.compileShader(geometry, GL_GEOMETRY_SHADER))
            stages.append(shaders.compileShader(fragment, GL_FRAGMENT_SHADER))
            program = shaders.compileProgram(*stages)
            self.programs[name] = program
            self.locations[name] = {uniform: glGetUniformLocation(program, uniform) for uniform in (
                'u_view', 'u_projection', 'u_logical_viewport', 'u_profile_factors',
                'u_viewport', 'u_line_px', 'u_alpha_mult')}
        self.vaos = {name: glGenVertexArrays(1) for name in self.programs}
        self.vbos = {name: glGenBuffers(1) for name in self.programs}
        self.fill_ebo = glGenBuffers(1)
        self.factor_vbo = glGenBuffers(1)
        self.factor_texture = glGenTextures(1)
        self.factors = np.empty(0, dtype=np.float32)
        self.counts = dict(fill=0, lines=0, glyphs=0)

    def upload(self, payload):
        self.ready = False
        for name in ('fill', 'lines', 'glyphs'):
            data = payload[name]
            glBindVertexArray(self.vaos[name])
            glBindBuffer(GL_ARRAY_BUFFER, self.vbos[name])
            glBufferData(GL_ARRAY_BUFFER, data.nbytes, data, GL_STATIC_DRAW)
            sizes = (3, 3, 3, 4, 3, 4) if name == 'glyphs' else (3, 4, 3, 1, 3, 1)
            stride = sum(sizes) * 4
            offset = 0
            for location, size in enumerate(sizes):
                glVertexAttribPointer(location, size, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(offset))
                glEnableVertexAttribArray(location)
                offset += size * 4
            self.counts[name] = len(data)
            if name == 'fill':
                indices = payload['fill_indices']
                glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, self.fill_ebo)
                glBufferData(GL_ELEMENT_ARRAY_BUFFER, indices.nbytes, indices, GL_STATIC_DRAW)
                self.counts['fill'] = len(indices)
        glBindVertexArray(0)
        self.factors = np.ones(max(1, payload['profile_count']), dtype=np.float32)
        glBindBuffer(GL_TEXTURE_BUFFER, self.factor_vbo)
        glBufferData(GL_TEXTURE_BUFFER, self.factors.nbytes, self.factors, GL_DYNAMIC_DRAW)
        glActiveTexture(GL_TEXTURE0 + self.texture_unit)
        glBindTexture(GL_TEXTURE_BUFFER, self.factor_texture)
        glTexBuffer(GL_TEXTURE_BUFFER, GL_R32F, self.factor_vbo)
        glBindTexture(GL_TEXTURE_BUFFER, 0)
        glActiveTexture(GL_TEXTURE0)
        glBindBuffer(GL_TEXTURE_BUFFER, 0)
        glBindBuffer(GL_ARRAY_BUFFER, 0)
        self.ready = True

    def update_factors(self, factors, width, height):
        data = np.asarray(factors, dtype=np.float32).ravel()
        if not len(data):
            data = np.ones(1, dtype=np.float32)
        if len(data) != len(self.factors):
            return False
        self.logical_viewport = (max(1., float(width)), max(1., float(height)))
        if not np.array_equal(data, self.factors):
            self.factors[:] = data
            glBindBuffer(GL_TEXTURE_BUFFER, self.factor_vbo)
            glBufferSubData(GL_TEXTURE_BUFFER, 0, self.factors.nbytes, self.factors)
            glBindBuffer(GL_TEXTURE_BUFFER, 0)
        return True

    def _use_program(self, name, view, projection):
        glUseProgram(self.programs[name])
        loc = self.locations[name]
        glUniformMatrix4fv(loc['u_view'], 1, GL_FALSE, view)
        glUniformMatrix4fv(loc['u_projection'], 1, GL_FALSE, projection)
        glUniform2f(loc['u_logical_viewport'], *self.logical_viewport)
        glUniform1i(loc['u_profile_factors'], self.texture_unit)
        glUniform1f(loc['u_alpha_mult'], 1.)
        if name != 'fill':
            vp = self.manager._vp_px
            if vp is None:
                vp = glGetIntegerv(GL_VIEWPORT)
            glUniform2f(loc['u_viewport'], float(vp[2]), float(vp[3]))
            glUniform1f(loc['u_line_px'], 1.8)

    def draw(self, view, projection):
        if not self.ready:
            return False
        glActiveTexture(GL_TEXTURE0 + self.texture_unit)
        glBindTexture(GL_TEXTURE_BUFFER, self.factor_texture)
        glEnable(GL_DEPTH_TEST)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        try:
            if self.counts['fill']:
                self._use_program('fill', view, projection)
                glEnable(GL_POLYGON_OFFSET_FILL)
                glPolygonOffset(2., 2.)
                glBindVertexArray(self.vaos['fill'])
                glDrawElements(GL_TRIANGLES, self.counts['fill'], GL_UNSIGNED_INT, None)
                glDisable(GL_POLYGON_OFFSET_FILL)
            glDepthFunc(GL_LEQUAL)
            for name in ('lines', 'glyphs'):
                if self.counts[name]:
                    self._use_program(name, view, projection)
                    glBindVertexArray(self.vaos[name])
                    glDrawArrays(GL_LINES, 0, self.counts[name])
        finally:
            glDepthFunc(GL_LESS)
            glDisable(GL_POLYGON_OFFSET_FILL)
            glBindVertexArray(0)
            glUseProgram(0)
            glBindTexture(GL_TEXTURE_BUFFER, 0)
            glActiveTexture(GL_TEXTURE0)
        return True
