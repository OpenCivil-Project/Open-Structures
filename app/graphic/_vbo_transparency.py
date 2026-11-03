"""GPU transparency using an exact front surface and an order-independent tail.

The existing frame/shell VAOs are rendered twice. Geometry uploads, playback
buffers and CPU ordering are unchanged; resources are allocated lazily.
"""

import re

import numpy as np
from OpenGL.GL import *
from OpenGL.GL import shaders
from OpenGL.raw.GL.VERSION.GL_1_1 import glTexImage2D as _raw_glTexImage2D

_ZERO_COLOR = np.zeros(4, dtype=np.float32)
_TP_FAST_NAV = True                                                                              
_FULLSCREEN_VERTEX = """
#version 330 core
void main() {
    const vec2 p[3] = vec2[3](vec2(-1.0, -1.0), vec2(3.0, -1.0), vec2(-1.0, 3.0));
    gl_Position = vec4(p[gl_VertexID], 0.0, 1.0);
}
"""
_COMPOSITE_FRAGMENT = """
#version 330 core
uniform sampler2D u_front_color;
uniform sampler2D u_front_depth;
uniform sampler2D u_tail_accum;
uniform sampler2D u_tail_optical;
uniform ivec2 u_viewport_origin;
uniform int u_tail_lo;
out vec4 FragColor;
void main() {
    ivec2 pixel = ivec2(gl_FragCoord.xy) - u_viewport_origin;
    vec4 front = texelFetch(u_front_color, pixel, 0);
    vec4 accum;
    float optical;
    if (u_tail_lo != 0) {
        vec2 uv = (vec2(pixel) + 0.5) / vec2(textureSize(u_front_color, 0));
        accum = texture(u_tail_accum, uv);
        optical = max(texture(u_tail_optical, uv).r, 0.0);
    } else {
        accum = texelFetch(u_tail_accum, pixel, 0);
        optical = max(texelFetch(u_tail_optical, pixel, 0).r, 0.0);
    }
    float tail_alpha = 1.0 - exp(-optical);
    float front_alpha = clamp(front.a, 0.0, 1.0);
    float coverage = front_alpha + (1.0 - front_alpha) * tail_alpha;
    if (coverage <= 0.0) discard;
    vec3 tail_rgb = accum.rgb / max(accum.a, 1e-6);
    vec3 premultiplied = front.rgb * front_alpha
        + tail_rgb * ((1.0 - front_alpha) * tail_alpha);
    FragColor = vec4(premultiplied, coverage);
    gl_FragDepth = texelFetch(u_front_depth, pixel, 0).r;
}
"""

def tail_fragment_source(source):
    """Adapt the existing flat/lit shader without duplicating its shading math."""
    declaration = """layout(location = 0) out vec4 FragColor;
layout(location = 1) out vec4 TailDepth;
uniform sampler2D u_transparency_front_depth;"""
    result, count = re.subn(r"\bout\s+vec4\s+FragColor\s*;", declaration, source)
    end = result.rfind("}")
    if count != 1 or end < 0:
        raise ValueError("Transparency requires one FragColor output and a final main function")
    tail = """
    float nearest_depth = texelFetch(u_transparency_front_depth, ivec2(gl_FragCoord.xy), 0).r;
    if (gl_FragCoord.z <= nearest_depth + 1e-7) discard;
    float tail_a = clamp(FragColor.a, 0.0, 1.0);
    if (tail_a <= 0.0) discard;
    // A cheap depth bias favours nearby tail layers. The exact front layer
    // remains separate, so near-opaque front coverage does not depend on it.
    float weight = (0.01 + tail_a)
        / (0.01 + 1000.0 * max(gl_FragCoord.z - nearest_depth, 0.0));
    weight = clamp(weight, 1e-2, 1e2);
    FragColor = vec4(FragColor.rgb * tail_a, tail_a) * weight;
    TailDepth = vec4(-log(max(1.0 - tail_a, 1e-6)), 0.0, 0.0, 0.0);
"""
    return result[:end] + tail + result[end:]

class TransparencyMixin:
    def _release_transparency_targets(self):
        targets = getattr(self, '_transparency_targets', {})
        fbos = [value for name, value in targets.items() if name.endswith('_fbo')]
        textures = [value for name, value in targets.items() if not name.endswith('_fbo')]
        if fbos:
            glDeleteFramebuffers(len(fbos), fbos)
        if textures:
            glDeleteTextures(len(textures), textures)
        self._transparency_targets = {}
        self._transparency_size = None

    def release_transparency(self):
        """Release lazily-created resources while this manager's context is current."""
        self._release_transparency_targets()
        for program, _ in getattr(self, '_transparency_tail_programs', {}).values():
            glDeleteProgram(program)
        self._transparency_tail_programs = {}
        composite = getattr(self, '_transparency_composite_program', None)
        if composite:
            glDeleteProgram(composite)
        self._transparency_composite_program = None
        vao = getattr(self, '_transparency_composite_vao', None)
        if vao:
            glDeleteVertexArrays(1, [vao])
        self._transparency_composite_vao = None

    def _ensure_transparency_targets(self, width, height):
        if getattr(self, '_transparency_size', None) == (width, height):
            return
        self._release_transparency_targets()
        targets = self._transparency_targets

        def texture(name, internal, format_, type_, w=None, h=None, linear=False):
            w = width if w is None else w
            h = height if h is None else h
            filt = GL_LINEAR if linear else GL_NEAREST
            tex = int(glGenTextures(1))
            targets[name] = tex
            glBindTexture(GL_TEXTURE_2D, tex)
                                                                        
            allocate = _raw_glTexImage2D if type_ == GL_UNSIGNED_INT_24_8 else glTexImage2D
            allocate(GL_TEXTURE_2D, 0, internal, w, h, 0, format_, type_, None)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, filt)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, filt)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
            return tex

        def framebuffer(name, depth, color_textures):
            fbo = int(glGenFramebuffers(1))
            targets[name] = fbo
            glBindFramebuffer(GL_FRAMEBUFFER, fbo)
            glFramebufferTexture2D(GL_FRAMEBUFFER, GL_DEPTH_STENCIL_ATTACHMENT, GL_TEXTURE_2D, depth, 0)
            for index, tex in enumerate(color_textures):
                glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0 + index, GL_TEXTURE_2D, tex, 0)
            if color_textures:
                attachments = [GL_COLOR_ATTACHMENT0 + i for i in range(len(color_textures))]
                glDrawBuffers(len(attachments), attachments)
                glReadBuffer(GL_COLOR_ATTACHMENT0)
            else:
                glDrawBuffer(GL_NONE)
                glReadBuffer(GL_NONE)
            status = glCheckFramebufferStatus(GL_FRAMEBUFFER)
            if status != GL_FRAMEBUFFER_COMPLETE:
                raise RuntimeError(f"Transparency framebuffer {name} is incomplete (0x{int(status):x})")

        try:
            front_color = texture('front_color', GL_RGBA16F, GL_RGBA, GL_HALF_FLOAT)
            front_depth = texture('front_depth', GL_DEPTH24_STENCIL8, GL_DEPTH_STENCIL, GL_UNSIGNED_INT_24_8)
            scene_depth = texture('scene_depth', GL_DEPTH24_STENCIL8, GL_DEPTH_STENCIL, GL_UNSIGNED_INT_24_8)
            accum = texture('tail_accum', GL_RGBA16F, GL_RGBA, GL_HALF_FLOAT)
            optical = texture('tail_optical', GL_R16F, GL_RED, GL_HALF_FLOAT)
            framebuffer('scene_fbo', scene_depth, [])
            framebuffer('front_fbo', front_depth, [front_color])
            framebuffer('tail_fbo', scene_depth, [accum, optical])
                                                                                  
            self._tp_lo_ok = False
            try:
                lw, lh = max(1, (width + 1) // 2), max(1, (height + 1) // 2)
                self._tp_lo_size = (lw, lh)
                s_lo = texture('scene_depth_lo', GL_DEPTH24_STENCIL8, GL_DEPTH_STENCIL, GL_UNSIGNED_INT_24_8, lw, lh)
                f_lo = texture('front_depth_lo', GL_DEPTH24_STENCIL8, GL_DEPTH_STENCIL, GL_UNSIGNED_INT_24_8, lw, lh)
                a_lo = texture('tail_accum_lo', GL_RGBA16F, GL_RGBA, GL_HALF_FLOAT, lw, lh, True)
                o_lo = texture('tail_optical_lo', GL_R16F, GL_RED, GL_HALF_FLOAT, lw, lh, True)
                framebuffer('scene_lo_fbo', s_lo, [])
                framebuffer('front_lo_fbo', f_lo, [])
                framebuffer('tail_lo_fbo', s_lo, [a_lo, o_lo])
                self._tp_lo_ok = True
            except Exception:
                self._tp_lo_ok = False
            self._transparency_size = (width, height)
        except Exception:
            self._release_transparency_targets()
            raise

    def _ensure_transparency_composite(self):
        if getattr(self, '_transparency_composite_program', None):
            return
        self._transparency_composite_program = shaders.compileProgram(
            shaders.compileShader(_FULLSCREEN_VERTEX, GL_VERTEX_SHADER),
            shaders.compileShader(_COMPOSITE_FRAGMENT, GL_FRAGMENT_SHADER))
        names = ('u_front_color', 'u_front_depth', 'u_tail_accum', 'u_tail_optical', 'u_viewport_origin', 'u_tail_lo')
        self._transparency_composite_locations = {
            name: glGetUniformLocation(self._transparency_composite_program, name) for name in names}
        self._transparency_composite_vao = int(glGenVertexArrays(1))

    def _use_transparency_tail_program(self, view_matrix, proj_matrix, alpha_mult, light):
        """Bind a lazily compiled tail variant for the existing native VBO draw."""
        lit = bool(light and light.get('enabled', False))
        if not hasattr(self, '_transparency_tail_programs'):
            self._transparency_tail_programs = {}
        if lit not in self._transparency_tail_programs:
            vertex = self.lit_vertex_shader_source if lit else self.vertex_shader_source
            fragment = self.lit_fragment_shader_source if lit else self.fragment_shader_source
            program = shaders.compileProgram(
                shaders.compileShader(vertex, GL_VERTEX_SHADER),
                shaders.compileShader(tail_fragment_source(fragment), GL_FRAGMENT_SHADER))
            names = ('u_view', 'u_projection', 'u_alpha_mult', 'u_anim_factor',
                     'u_transparency_front_depth', 'u_light_dir', 'u_view_pos', 'u_ambient',
                     'u_diffuse', 'u_specular', 'u_shininess', 'u_fresnel_intensity', 'u_fresnel_power')
            locations = {name: glGetUniformLocation(program, name) for name in names}
            self._transparency_tail_programs[lit] = (program, locations)
        program, loc = self._transparency_tail_programs[lit]
        glUseProgram(program)
        glUniformMatrix4fv(loc['u_view'], 1, GL_FALSE, view_matrix)
        glUniformMatrix4fv(loc['u_projection'], 1, GL_FALSE, proj_matrix)
        glUniform1f(loc['u_alpha_mult'], alpha_mult)
        glUniform1f(loc['u_anim_factor'], self.current_anim_factor)
        glActiveTexture(GL_TEXTURE0)
        glBindTexture(GL_TEXTURE_2D, self._transparency_targets[
            'front_depth_lo' if getattr(self, '_tp_lo_active', False) else 'front_depth'])
        glUniform1i(loc['u_transparency_front_depth'], 0)
        if lit:
            glUniform3f(loc['u_light_dir'], *light['light_dir'])
            glUniform3f(loc['u_view_pos'], *light['view_pos'])
            for uniform, setting, default in (
                    ('u_ambient', 'ambient', 0.35), ('u_diffuse', 'diffuse', 0.75),
                    ('u_specular', 'specular', 0.25), ('u_shininess', 'shininess', 32.0),
                    ('u_fresnel_intensity', 'fresnel_intensity', 0.0),
                    ('u_fresnel_power', 'fresnel_power', 3.0)):
                glUniform1f(loc[uniform], light.get(setting, default))
        return True

    @staticmethod
    def _transparency_save_state():
        scalar_names = {
            'draw_fbo': GL_DRAW_FRAMEBUFFER_BINDING, 'read_fbo': GL_READ_FRAMEBUFFER_BINDING,
            'program': GL_CURRENT_PROGRAM, 'vao': GL_VERTEX_ARRAY_BINDING,
            'active_texture': GL_ACTIVE_TEXTURE, 'depth_func': GL_DEPTH_FUNC,
            'blend_src_rgb': GL_BLEND_SRC_RGB, 'blend_dst_rgb': GL_BLEND_DST_RGB,
            'blend_src_alpha': GL_BLEND_SRC_ALPHA, 'blend_dst_alpha': GL_BLEND_DST_ALPHA,
            'blend_equation_rgb': GL_BLEND_EQUATION_RGB, 'blend_equation_alpha': GL_BLEND_EQUATION_ALPHA,
        }
        state = {name: int(glGetIntegerv(enum)) for name, enum in scalar_names.items()}
        state['viewport'] = tuple(int(v) for v in glGetIntegerv(GL_VIEWPORT))
        state['color_mask'] = tuple(bool(v) for v in glGetBooleanv(GL_COLOR_WRITEMASK))
        state['depth_mask'] = bool(glGetBooleanv(GL_DEPTH_WRITEMASK))
        state['enabled'] = {enum: bool(glIsEnabled(enum)) for enum in (
            GL_BLEND, GL_DEPTH_TEST, GL_STENCIL_TEST, GL_SCISSOR_TEST, GL_CULL_FACE, GL_POLYGON_OFFSET_FILL)}
        state['polygon_factor'] = float(glGetFloatv(GL_POLYGON_OFFSET_FACTOR))
        state['polygon_units'] = float(glGetFloatv(GL_POLYGON_OFFSET_UNITS))
        state['textures'] = []
        for unit in range(4):
            glActiveTexture(GL_TEXTURE0 + unit)
            state['textures'].append(int(glGetIntegerv(GL_TEXTURE_BINDING_2D)))
        glActiveTexture(state['active_texture'])
        return state

    @staticmethod
    def _transparency_restore_state(state):
        glBindFramebuffer(GL_DRAW_FRAMEBUFFER, state['draw_fbo'])
        glBindFramebuffer(GL_READ_FRAMEBUFFER, state['read_fbo'])
        glViewport(*state['viewport'])
        glColorMask(*state['color_mask'])
        glDepthMask(state['depth_mask'])
        glDepthFunc(state['depth_func'])
        glBlendFuncSeparate(state['blend_src_rgb'], state['blend_dst_rgb'],
                            state['blend_src_alpha'], state['blend_dst_alpha'])
        glBlendEquationSeparate(state['blend_equation_rgb'], state['blend_equation_alpha'])
        glPolygonOffset(state['polygon_factor'], state['polygon_units'])
        for enum, enabled in state['enabled'].items():
            (glEnable if enabled else glDisable)(enum)
        for unit, texture in enumerate(state['textures']):
            glActiveTexture(GL_TEXTURE0 + unit)
            glBindTexture(GL_TEXTURE_2D, texture)
        glActiveTexture(state['active_texture'])
        glBindVertexArray(state['vao'])
        glUseProgram(state['program'])

    def draw_transparency(self, view_matrix, proj_matrix, include_frames=True,
                          include_areas=True, light=None, fast=False):
        try:
            return self._draw_transparency_impl(view_matrix, proj_matrix, include_frames,
                                                include_areas, light, fast)
        except RuntimeError:
            if not fast:
                raise
            self._tp_lo_ok = False                                                         
            return self._draw_transparency_impl(view_matrix, proj_matrix, include_frames,
                                                include_areas, light, False)

    def _draw_transparency_impl(self, view_matrix, proj_matrix, include_frames=True,
                                include_areas=True, light=None, fast=False):
        """Composite partial-alpha surfaces in two GPU geometry passes.

        The caller draws opaque/background geometry first. This method keeps
        its colour and depth, supplies nearest transparent depth for outlines,
        and restores framebuffer/viewport/render state. Allocation failures
        raise an explicit error rather than falling back to unsorted blending.
        """
        frames = bool(include_frames and getattr(self, 'index_count', 0))
        areas = bool(include_areas and getattr(self, 'area_index_count', 0))
        if not self.is_initialized or not (frames or areas):
            return False
        state = self._transparency_save_state()
        previous_stage = getattr(self, '_transparency_stage', None)
        x, y, width, height = state['viewport']
        if width <= 0 or height <= 0:
            return False
        try:
            glDisable(GL_SCISSOR_TEST)
            glDisable(GL_STENCIL_TEST)
            glDisable(GL_CULL_FACE)
            glDisable(GL_POLYGON_OFFSET_FILL)
            glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE)
            glActiveTexture(GL_TEXTURE0)
            self._ensure_transparency_targets(width, height)
            self._ensure_transparency_composite()
            targets = self._transparency_targets
            lo = bool(fast and _TP_FAST_NAV and getattr(self, '_tp_lo_ok', False))
            lw, lh = getattr(self, '_tp_lo_size', (width, height))
                                                                           
            glBindFramebuffer(GL_READ_FRAMEBUFFER, state['draw_fbo'])
            for target in ('scene_fbo', 'front_fbo'):
                glBindFramebuffer(GL_DRAW_FRAMEBUFFER, targets[target])
                glBlitFramebuffer(x, y, x + width, y + height, 0, 0, width, height,
                                  GL_DEPTH_BUFFER_BIT, GL_NEAREST)
            if lo:
                glBindFramebuffer(GL_READ_FRAMEBUFFER, targets['scene_fbo'])
                glBindFramebuffer(GL_DRAW_FRAMEBUFFER, targets['scene_lo_fbo'])
                glBlitFramebuffer(0, 0, width, height, 0, 0, lw, lh,
                                  GL_DEPTH_BUFFER_BIT, GL_NEAREST)
            glViewport(0, 0, width, height)

            def geometry(transparent):
                if frames:
                    self.draw(view_matrix, proj_matrix, light=light, transparent=transparent)
                if areas:
                    self.draw_areas(view_matrix, proj_matrix, light=light, transparent=transparent)

            glBindFramebuffer(GL_DRAW_FRAMEBUFFER, targets['front_fbo'])
            glClearBufferfv(GL_COLOR, 0, _ZERO_COLOR)
            self._transparency_stage = 'front'
            geometry(False)

            if lo:
                glBindFramebuffer(GL_READ_FRAMEBUFFER, targets['front_fbo'])
                glBindFramebuffer(GL_DRAW_FRAMEBUFFER, targets['front_lo_fbo'])
                glBlitFramebuffer(0, 0, width, height, 0, 0, lw, lh,
                                  GL_DEPTH_BUFFER_BIT, GL_NEAREST)
                glViewport(0, 0, lw, lh)
            glBindFramebuffer(GL_DRAW_FRAMEBUFFER, targets['tail_lo_fbo' if lo else 'tail_fbo'])
            glClearBufferfv(GL_COLOR, 0, _ZERO_COLOR)
            glClearBufferfv(GL_COLOR, 1, _ZERO_COLOR)
            glBlendEquation(GL_FUNC_ADD)
            self._transparency_stage = 'tail'
            self._tp_lo_active = lo
            try:
                geometry(True)
            finally:
                self._tp_lo_active = False

            glBindFramebuffer(GL_DRAW_FRAMEBUFFER, state['draw_fbo'])
            glViewport(x, y, width, height)
            glDisable(GL_CULL_FACE)
            glDisable(GL_POLYGON_OFFSET_FILL)
            glEnable(GL_DEPTH_TEST)
            glDepthFunc(GL_ALWAYS)
            glDepthMask(GL_TRUE)
            glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE)
            glEnable(GL_BLEND)
            glBlendEquation(GL_FUNC_ADD)
            glBlendFunc(GL_ONE, GL_ONE_MINUS_SRC_ALPHA)
            glUseProgram(self._transparency_composite_program)
            loc = self._transparency_composite_locations
            sfx = '_lo' if lo else ''
            for unit, (uniform, texture) in enumerate((
                    ('u_front_color', 'front_color'), ('u_front_depth', 'front_depth'),
                    ('u_tail_accum', 'tail_accum' + sfx), ('u_tail_optical', 'tail_optical' + sfx))):
                glActiveTexture(GL_TEXTURE0 + unit)
                glBindTexture(GL_TEXTURE_2D, targets[texture])
                glUniform1i(loc[uniform], unit)
            glUniform2i(loc['u_viewport_origin'], x, y)
            glUniform1i(loc['u_tail_lo'], 1 if lo else 0)
            glBindVertexArray(self._transparency_composite_vao)
            glDrawArrays(GL_TRIANGLES, 0, 3)
            return True
        except Exception as error:
            raise RuntimeError(f"GPU transparency rendering failed: {error}") from error
        finally:
            self._transparency_stage = previous_stage
            self._transparency_restore_state(state)
