"""GPU load descriptors stay static; camera updates change only group factors."""
import ctypes
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from app.graphic import _vbo_load_view as module
from app.graphic._vbo_force_load import ForceLoadMixin

def cache_fixture():
    fill = np.array([[0., 0., 0.], [1., 0., 0.], [1., 0., 1.]])
    positions = np.zeros((12, 3)); positions[6:8, 0] = 1.
    positions[8:] = [[0., 0., 0.], [.1, .1, .1], [0., 0., 1.], [1., 0., 1.]]
    colors = np.array([[.2, .3, .4, 1.]] * 12)
    empty = (np.empty(0, dtype=int), np.empty(0, dtype=int),
             np.empty((0, 3)), np.empty((0, 3)))
    moving_fill = (np.zeros(3, dtype=int), np.arange(3), fill.copy(), np.array([[0., 0., 1.]] * 3))
    moving_lines = (np.zeros(2, dtype=int), np.array([10, 11]),
                    np.array([[0., 0., 0.], [1., 0., 0.]]), np.array([[0., 0., 1.]] * 2))
    return SimpleNamespace(fill_positions=fill, line_positions=positions, original_colors=colors,
        moving_fill=moving_fill, moving_lines=moving_lines, profile_count=1,
        leader_indices=np.array([8]), leader_anchors=np.array([[0., 0., 0.]]),
        heads=np.array([.28, 0.]), wings=np.array([.4, 0.]),
        tips=np.array([[0., 0., 0.], [1., 0., 0.]]),
        directions=np.array([[0., 0., -1.]] * 2), sides=np.array([[0., -1., 0.]] * 2),
        nominal=np.array([3., 3.]), maximum=np.array([33., 33.]), minimum=np.array([24., 0.]),
        arrow_groups=np.array([0, -1]), arrow_indices=np.array([0, 6]))

class LoadViewGPUBufferTests(unittest.TestCase):
    def test_payload_separates_glyphs_and_preserves_curtain_groups_and_leaders(self):
        cache = cache_fixture()
        fill_colors = np.array([[.1, .2, .3, .4]] * 3)
        payload = module.pack_load_view_payload(cache, fill_colors, [[0, 1, 2]])
        self.assertEqual(payload['glyphs'].shape, (8, 20))
        self.assertEqual(payload['lines'].shape, (4, 15))
        self.assertEqual(payload['fill'].shape, (3, 15))
        np.testing.assert_array_equal(payload['glyphs'][:, 19], [0.] * 6 + [-1.] * 2)
        np.testing.assert_allclose(payload['glyphs'][:, 13], [1., 0., 0., .28, 0., .28, 1., 0.])
        np.testing.assert_array_equal(payload['glyphs'][:, 14], [0., 0., 0., 1., 0., -1., 0., 0.])
        np.testing.assert_array_equal(payload['fill'][:, 10], [0., 0., 0.])
        np.testing.assert_array_equal(payload['fill'][:, 3:7], fill_colors.astype(np.float32))
        np.testing.assert_array_equal(payload['lines'][:2, 14], [1., 1.])
        np.testing.assert_array_equal(payload['lines'][2:, 10], [0., 0.])
        np.testing.assert_array_equal(payload['fill_indices'], [0, 1, 2])
        for name in ('glyphs', 'lines', 'fill'):
            self.assertTrue(payload[name].flags.c_contiguous)
            self.assertEqual(payload[name].dtype, np.float32)

    def test_camera_factor_update_uploads_only_changed_tiny_table(self):
        renderer = module.LoadViewGPURenderer.__new__(module.LoadViewGPURenderer)
        renderer.factors = np.array([1., 1.], dtype=np.float32)
        renderer.factor_vbo = 17
        renderer.logical_viewport = (1., 1.)
        with (patch.object(module, 'glBindBuffer') as bind,
              patch.object(module, 'glBufferSubData') as sub,
              patch.object(module, 'glBufferData') as data):
            self.assertTrue(renderer.update_factors([1., 1.], 800, 600))
            sub.assert_not_called()
            self.assertTrue(renderer.update_factors([.5, 1.], 900, 650))
            sub.assert_called_once()
            self.assertEqual(sub.call_args.args[0], module.GL_TEXTURE_BUFFER)
            self.assertEqual(sub.call_args.args[2], 8)
            data.assert_not_called()
            self.assertEqual(renderer.logical_viewport, (900., 650.))
            self.assertFalse(renderer.update_factors([1.], 1000, 700))
            self.assertEqual(renderer.logical_viewport, (900., 650.))

    def test_draw_routes_to_load_only_renderer_without_force_shader_changes(self):
        manager = ForceLoadMixin()
        manager.is_initialized = True
        manager._load_view_gpu_active = True
        manager._load_view_gpu = SimpleNamespace(draw=Mock(return_value=True))
        with patch('app.graphic._vbo_force_load.glUseProgram') as use:
            manager.draw_load_geometry('view', 'projection')
            manager._load_view_gpu.draw.assert_called_once_with('view', 'projection')
            use.assert_not_called()

    def test_shader_failure_preserves_cpu_fallback_and_does_not_retry_every_frame(self):
        manager = ForceLoadMixin()
        manager.is_initialized = True
        manager._load_fill_buffer = np.empty((0, 10), dtype=np.float32)
        manager._load_fill_indices = np.empty(0, dtype=np.uint32)
        with (patch.object(module, 'LoadViewGPURenderer', side_effect=RuntimeError('unavailable')) as constructor,
              patch('builtins.print')):
            self.assertFalse(manager.upload_load_view_payload(cache_fixture()))
            self.assertFalse(manager._load_view_gpu_active)
            self.assertFalse(manager.upload_load_view_payload(cache_fixture()))
            constructor.assert_called_once()

def run_native_feedback():
    """Compile the production shaders and measure their actual GPU vertices."""
    from PyQt6.QtGui import QGuiApplication, QOffscreenSurface, QOpenGLContext, QSurfaceFormat
    from app.graphic.vbo_engine import VBORenderManager
    from app.graphic.load_arrow_geometry import bounded_arrow_length
    from OpenGL import GL
    app = QGuiApplication([])
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    surface = QOffscreenSurface(); surface.setFormat(fmt); surface.create()
    context = QOpenGLContext(); context.setFormat(fmt)
    if not context.create() or not context.makeCurrent(surface):
        print('Native OpenGL 3.3 context unavailable')
        return 77
    manager = VBORenderManager()
    renderer = module.LoadViewGPURenderer(manager)
    cache = cache_fixture()
    payload = module.pack_load_view_payload(cache, [[.1, .2, .3, .4]] * 3, [[0, 1, 2]])
    renderer.upload(payload)
    assert renderer.update_factors([.5], 800, 600)

    def compile_feedback(source):
        vertex = module.shaders.compileShader(source, GL.GL_VERTEX_SHADER)
        program = GL.glCreateProgram(); GL.glAttachShader(program, vertex)
        names = [ctypes.create_string_buffer(name) for name in
                 (b'v_world_position', b'v_color', b'gl_Position')]
        pointers = (ctypes.POINTER(ctypes.c_char) * len(names))(
            *(ctypes.cast(name, ctypes.POINTER(ctypes.c_char)) for name in names))
        GL.glTransformFeedbackVaryings(program, len(names), pointers, GL.GL_INTERLEAVED_ATTRIBS)
        GL.glLinkProgram(program)
        assert GL.glGetProgramiv(program, GL.GL_LINK_STATUS), GL.glGetProgramInfoLog(program)
        return program

    def feedback(program, data, sizes, matrix):
        vao = GL.glGenVertexArrays(1); input_vbo = GL.glGenBuffers(1); output_vbo = GL.glGenBuffers(1)
        GL.glBindVertexArray(vao); GL.glBindBuffer(GL.GL_ARRAY_BUFFER, input_vbo)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, data.nbytes, data, GL.GL_STATIC_DRAW)
        offset = 0
        for location, size in enumerate(sizes):
            GL.glVertexAttribPointer(location, size, GL.GL_FLOAT, GL.GL_FALSE,
                                     sum(sizes) * 4, ctypes.c_void_p(offset))
            GL.glEnableVertexAttribArray(location); offset += size * 4
        GL.glBindBuffer(GL.GL_TRANSFORM_FEEDBACK_BUFFER, output_vbo)
        GL.glBufferData(GL.GL_TRANSFORM_FEEDBACK_BUFFER, len(data) * 11 * 4, None, GL.GL_STREAM_READ)
        GL.glBindBufferBase(GL.GL_TRANSFORM_FEEDBACK_BUFFER, 0, output_vbo)
        GL.glUseProgram(program)
        GL.glUniformMatrix4fv(GL.glGetUniformLocation(program, 'u_view'), 1, False,
                             np.eye(4, dtype=np.float32))
        GL.glUniformMatrix4fv(GL.glGetUniformLocation(program, 'u_projection'), 1, False,
                             np.ascontiguousarray(matrix.T, dtype=np.float32))
        GL.glUniform2f(GL.glGetUniformLocation(program, 'u_logical_viewport'), 800., 600.)
        GL.glUniform1i(GL.glGetUniformLocation(program, 'u_profile_factors'), renderer.texture_unit)
        GL.glActiveTexture(GL.GL_TEXTURE0 + renderer.texture_unit)
        GL.glBindTexture(GL.GL_TEXTURE_BUFFER, renderer.factor_texture)
        GL.glEnable(GL.GL_RASTERIZER_DISCARD)
        GL.glBeginTransformFeedback(GL.GL_POINTS); GL.glDrawArrays(GL.GL_POINTS, 0, len(data))
        GL.glEndTransformFeedback(); GL.glDisable(GL.GL_RASTERIZER_DISCARD)
        GL.glBindBuffer(GL.GL_TRANSFORM_FEEDBACK_BUFFER, output_vbo)
        result = GL.glGetBufferSubData(GL.GL_TRANSFORM_FEEDBACK_BUFFER, 0, len(data) * 11 * 4)
        result = np.frombuffer(result, dtype=np.float32).reshape(-1, 11).copy()
        GL.glBindBufferBase(GL.GL_TRANSFORM_FEEDBACK_BUFFER, 0, 0)
        GL.glBindVertexArray(0); GL.glUseProgram(0)
        GL.glDeleteBuffers(2, [input_vbo, output_vbo]); GL.glDeleteVertexArrays(1, [vao])
        return result

    orthographic = np.array([[.18, 0., 0., 0.], [0., .12, .2, 0.],
                             [0., 0., .05, 0.], [0., 0., 0., 1.]])
    eye = np.array([9., -11., 9.]); forward = -eye / np.linalg.norm(eye)
    side = np.cross(forward, [0., 0., 1.]); side /= np.linalg.norm(side)
    up = np.cross(side, forward)
    view = np.eye(4); view[:3, :3] = np.array([side, up, -forward]); view[:3, 3] = -view[:3, :3] @ eye
    factor = 1. / np.tan(np.radians(45.) / 2.)
    projection = np.array([[factor * .75, 0., 0., 0.], [0., factor, 0., 0.],
                           [0., 0., -1.002002, -.2002002], [0., 0., -1., 0.]])
    matrices = []
    for zoom in (1., 2., 5., 10., 40.):
        matrix = orthographic.copy(); matrix[:2] *= zoom; matrices.append(matrix)
    matrices.append(projection @ view)
    behind = orthographic.copy(); behind[3, 3] = -1.; matrices.append(behind)
    clipped = orthographic.copy(); clipped[0, 3] = 3.; matrices.append(clipped)
    cases = [(matrix, payload['glyphs']) for matrix in matrices]
    crossing = payload['glyphs'].copy()
    direction = -eye / np.linalg.norm(eye) + np.array([.15, 0., 0.])
    direction /= np.linalg.norm(direction)
    wing_side = np.cross(direction, [0., 0., 1.]); wing_side /= np.linalg.norm(wing_side)
    crossing[:6, 3:6] = direction
    crossing[:6, 6:9] = wing_side
    crossing[:6, 16] = 100.
    cases.append((projection @ view, crossing))
    overhead = np.eye(4); overhead[2, 3] = -4.
    parallel = payload['glyphs'].copy(); parallel[:6, 16] = 100.
    cases.append((projection @ overhead, parallel))
    program = compile_feedback(module.GLYPH_VERTEX_SHADER)
    for matrix, data in cases:
        actual = feedback(program, data, (3, 3, 3, 4, 3, 4), matrix)
        expected = []
        for row in data:
            tip, direction, side = row[:3], row[3:6], row[6:9]
            shape, parameters = row[13:16], row[16:20]
            nominal = parameters[0] * (.5 if parameters[3] >= 0 else 1.)
            shaft = bounded_arrow_length(tip, direction, nominal, matrix, 800, 600,
                                         parameters[1], parameters[2])
            base = tip - direction * shape[0] * shaft
            if shape[1]:
                wing_direction = side * shape[1]
                wing = bounded_arrow_length(base, -wing_direction, shaft * shape[2], matrix, 800, 600, 6., 0.)
                base += wing_direction * wing
            expected.append(base)
            clip = matrix @ np.r_[tip, 1.]
            visible = clip[3] > 0 and (np.abs(clip[:3]) <= clip[3]).all() and shaft > 0
            np.testing.assert_allclose(actual[len(expected) - 1, 6], float(visible), atol=1e-6)
        np.testing.assert_allclose(actual[:, :3], expected, atol=2e-5, rtol=2e-5)
    curtain_program = compile_feedback(module.CURTAIN_VERTEX_SHADER)
    actual = feedback(curtain_program, payload['fill'], (3, 4, 3, 1, 3, 1), orthographic)
    np.testing.assert_allclose(actual[:, :3], payload['fill'][:, :3] + payload['fill'][:, 7:10] * .5)
    print('Production load shaders compiled; GPU transform feedback matches CPU bounds in ten camera views and shared curtain scale.')
    context.doneCurrent()
    return 0

class NativeLoadShaderTests(unittest.TestCase):
    def test_production_shader_vertices_match_cpu_bounds_in_native_context(self):
        environment = os.environ.copy()
        environment.pop('QT_QPA_PLATFORM', None)
        result = subprocess.run([sys.executable, '-B', str(Path(__file__).resolve()), '--native-feedback'],
                                cwd=ROOT, env=environment, capture_output=True, text=True, timeout=60)
        if result.returncode == 77:
            self.skipTest(result.stdout.strip())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

if __name__ == '__main__':
    if '--native-feedback' in sys.argv:
        sys.exit(run_native_feedback())
    unittest.main()
