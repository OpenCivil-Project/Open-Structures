import numpy as np
import math
import time
import pyqtgraph.opengl as gl
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, pyqtSignal, QRect, QTimer
from PyQt6.QtGui import QPainter, QColor, QPen, QVector3D
from core.units import unit_registry
from graphic.camera_ctrl import ArcballCamera
from post.deflection import get_deflected_shape, get_deflected_points_batch
from post.animation import AnimationManager
from graphic.view_cube import ViewCube
from graphic.mouse_crosshair import MouseCrosshair, mode_flag_property
from OpenGL.GL import *
from core.properties import RectangularSection, CircularSection, TrapezoidalSection
from PyQt6.QtWidgets import QLabel        
from graphic.vbo_engine import VBORenderManager, VectorizedLTHAEngine                               
from graphic.sdf_text import SDFTextBuilder
from graphic.area_load_render import AreaLoadDisplayMixin
from graphic.frame_load_render import FrameLoadDisplayMixin
from graphic._vbo_supports import build_boundary_visuals, build_ltha_spring_plates
from core.ForceComputationWorker import ForceComputationWorker

def vec_contour_colormap(t, alpha=1.0):
    """Vectorised twin of MCanvas3D._contour_colormap. t: (...,) -> (...,4) float32."""
    t = np.clip(np.asarray(t, dtype=np.float64), 0.0, 1.0)
    r = np.zeros_like(t); g = np.zeros_like(t); b = np.zeros_like(t)
    m1 = t < 0.25
    m2 = (t >= 0.25) & (t < 0.5)
    m3 = (t >= 0.5) & (t < 0.75)
    m4 = t >= 0.75
    g[m1] = t[m1] / 0.25;               b[m1] = 1.0
    g[m2] = 1.0;                        b[m2] = 1.0 - (t[m2] - 0.25) / 0.25
    r[m3] = (t[m3] - 0.5) / 0.25;       g[m3] = 1.0
    r[m4] = 1.0;                        g[m4] = 1.0 - (t[m4] - 0.75) / 0.25
    out = np.empty(t.shape + (4,), dtype=np.float32)
    out[..., 0] = r; out[..., 1] = g; out[..., 2] = b; out[..., 3] = alpha
    return out

def vec_contour_scalar(d, comp, absolute):
    """d: (...,>=3) displacement rows -> scalar the contour colours by."""
    idx = {'Ux': 0, 'Uy': 1, 'Uz': 2}.get(comp)
    if idx is not None:
        v = d[..., idx]
        return np.abs(v) if absolute else v
    return np.sqrt(d[..., 0] ** 2 + d[..., 1] ** 2 + d[..., 2] ** 2)

def vec_rest_axes(P1, P2, beta_deg):
    """Vectorised MCanvas3D._get_consistent_axes. P1,P2:(n,3) beta:(n,) -> R (n,3,3) rows=(vx,vy,vz)."""
    P1 = np.asarray(P1, dtype=np.float64); P2 = np.asarray(P2, dtype=np.float64)
    n = len(P1)
    R = np.zeros((n, 3, 3), dtype=np.float64)
    R[:] = np.eye(3)
    vx = P2 - P1
    L = np.linalg.norm(vx, axis=1)
    ok = L >= 1e-6
    if not ok.any():
        return R
    vx = vx[ok] / L[ok, None]
    vertical = np.isclose(np.abs(vx[:, 2]), 1.0)
    up = np.zeros_like(vx); up[:, 2] = 1.0
    up[vertical] = (1.0, 0.0, 0.0)
    vy = np.cross(up, vx);  vy /= np.linalg.norm(vy, axis=1, keepdims=True)
    vz = np.cross(vx, vy);  vz /= np.linalg.norm(vz, axis=1, keepdims=True)
    beta = np.asarray(beta_deg, dtype=np.float64)[ok]
    rad = np.radians(beta)
    c = np.cos(rad)[:, None]; s = np.sin(rad)[:, None]
    nz = (beta != 0)[:, None]
    vy2 = np.where(nz, c * vy + s * vz, vy)
    vz2 = np.where(nz, -s * vy + c * vz, vz)
    R[ok, 0] = vx; R[ok, 1] = vy2; R[ok, 2] = vz2
    return R

def vec_extruded_metadata(params, show_edges, edge_c, nseg=10):
    """
    Vectorised replacement for the python loops of _build_ltha_extruded_metadata.

    params: list of (e_idx, shape(M,2) ndarray [shared object per section], needs_caps,
                     face_color(4,), y_shift, z_shift, off_i(3,), off_j(3,))
    Returns dict(map_E, map_P, map_off, map_Y, map_Z, colors, faces(F,3), edges(K,2) | None)
    Vertex layout is identical to the original: per element, per segment i: [a-ring(M), b-ring(M)].
    """
    n = len(params)
    if n == 0:
        return None
    Ms = np.fromiter((p[1].shape[0] for p in params), dtype=np.int64, count=n)
    blk = 2 * nseg * Ms
    offs = np.zeros(n, dtype=np.int64)
    np.cumsum(blk[:-1], out=offs[1:])
    V = int(blk.sum())

    mE = np.empty(V, dtype=np.int32)
    mP = np.empty(V, dtype=np.int8)
    moff = np.empty((V, 3), dtype=np.float32)
    mY = np.empty(V, dtype=np.float32)
    mZ = np.empty(V, dtype=np.float32)
    col = np.empty((V, 4), dtype=np.float32)

    groups = {}
    for k, p in enumerate(params):
        groups.setdefault((id(p[1]), bool(p[2])), []).append(k)

    face_chunks, edge_chunks = [], []
    i_ar = np.arange(nseg)

    for (_, caps), gi in groups.items():
        gi = np.asarray(gi, dtype=np.int64)
        S = params[gi[0]][1]
        M = S.shape[0]
        E = len(gi)
        e_idx = np.fromiter((params[k][0] for k in gi), dtype=np.int32, count=E)
        ys = np.fromiter((params[k][4] for k in gi), dtype=np.float64, count=E)
        zs = np.fromiter((params[k][5] for k in gi), dtype=np.float64, count=E)
        oi = np.array([params[k][6] for k in gi], dtype=np.float64).reshape(E, 3)
        oj = np.array([params[k][7] for k in gi], dtype=np.float64).reshape(E, 3)
        fc = np.array([params[k][3] for k in gi], dtype=np.float32).reshape(E, 4)

        j_ar = np.arange(M)
        L = (i_ar[:, None, None] * 2 * M + np.arange(2)[None, :, None] * M + j_ar[None, None, :])              
        idx = (offs[gi][:, None, None, None] + L[None]).reshape(E, -1)                                             

        P = (i_ar[:, None, None] + np.arange(2)[None, :, None]) + np.zeros((1, 1, M), dtype=np.int64)              
        Pf = P.reshape(-1)
        s = Pf / float(nseg)                                                                                      

        mE[idx] = e_idx[:, None]
        mP[idx] = Pf[None, :]
        off = (1.0 - s)[None, :, None] * oi[:, None, :] + s[None, :, None] * oj[:, None, :]                     
        moff[idx] = off
        Yv = np.tile(S[:, 0], nseg * 2)                                                                           
        Zv = np.tile(S[:, 1], nseg * 2)
        mY[idx] = Yv[None, :] + ys[:, None]
        mZ[idx] = Zv[None, :] + zs[:, None]
        col[idx] = fc[:, None, :]

        start = (offs[gi][:, None] + (i_ar * 2 * M)[None, :])                                                   
        j = j_ar; nj = (j + 1) % M
        a_cur = start[:, :, None] + j[None, None, :]
        a_nxt = start[:, :, None] + nj[None, None, :]
        b_cur = start[:, :, None] + M + j[None, None, :]
        b_nxt = start[:, :, None] + M + nj[None, None, :]
        f1 = np.stack([a_cur, a_nxt, b_nxt], axis=-1).reshape(-1, 3)
        f2 = np.stack([a_cur, b_nxt, b_cur], axis=-1).reshape(-1, 3)
        face_chunks.extend([f1, f2])
        if caps and M >= 3:
            jj = np.arange(1, M - 1)
            s0 = start[:, 0][:, None]                                      
            face_chunks.append(np.stack([np.broadcast_to(s0, (E, len(jj))), s0 + jj[None, :] + 1,
                                         s0 + jj[None, :]], axis=-1).reshape(-1, 3))
            sl = start[:, nseg - 1][:, None] + M                                  
            face_chunks.append(np.stack([np.broadcast_to(sl, (E, len(jj))), sl + jj[None, :],
                                         sl + jj[None, :] + 1], axis=-1).reshape(-1, 3))
        if show_edges:
            edge_chunks.append(np.stack([a_cur, b_cur], axis=-1).reshape(-1, 2))
            edge_chunks.append(np.stack([a_cur[:, 0], a_nxt[:, 0]], axis=-1).reshape(-1, 2))
            edge_chunks.append(np.stack([b_cur[:, nseg - 1], b_nxt[:, nseg - 1]], axis=-1).reshape(-1, 2))

    faces = np.concatenate(face_chunks, axis=0).astype(np.uint32)
    edges = np.concatenate(edge_chunks, axis=0).astype(np.int32) if edge_chunks else None
    return dict(map_E=mE, map_P=mP, map_off=moff, map_Y=mY, map_Z=mZ, colors=col,
                faces=faces, edges=edges)

_GL_PROFILE = __import__('os').environ.get('OS_GL_PROFILE', '0') == '1'                                                    

class MCanvas3D(FrameLoadDisplayMixin, AreaLoadDisplayMixin, gl.GLViewWidget):
    signal_canvas_clicked = pyqtSignal(float, float, float)
    signal_right_clicked = pyqtSignal()
    signal_box_selection = pyqtSignal(list, list, list, list, list, bool, bool) 
    signal_area_box_selection = pyqtSignal(list, bool, bool)                                   
    signal_element_selected = pyqtSignal(int)
    signal_mouse_moved = pyqtSignal(float, float, float)

    snapping_enabled = mode_flag_property('snapping_enabled')
    beam_col_mode    = mode_flag_property('beam_col_mode')
    cross_brace_mode = mode_flag_property('cross_brace_mode')
    quick_area_mode  = mode_flag_property('quick_area_mode')
    _box_sel_area_follows = False

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)

        self.display_config = {
            "node_size": 6,
            "node_color": (1, 0, 0, 1),
            "line_width": 2.0,
            "extrude_opacity": 0.35,
            "show_edges": True,
            "edge_width": 1.5,
            "edge_opacity": 0.08,
            "edge_color": (0, 0, 0, 1),
            "slab_opacity": 0.4
        }
        self.view_cube = ViewCube()
        self.opts['distance']  = 10                                                       
        self.opts['elevation'] = 30
        self.opts['azimuth']   = 45
        self.opts['fov']       = 60
        self.opts['center']    = QVector3D(0, 0, 0)                                                     
        self.setBackgroundColor('#FFFFFF')

        self._area_preview_line = gl.GLLinePlotItem(color=(0, 1, 1, 1), width=2, mode='line_strip')
        self._area_preview_line.setVisible(False)

        _dummy_pos = np.zeros((2, 3), dtype=np.float32)
        _dummy_col = np.zeros((2, 4), dtype=np.float32)
        self._area_interior_lines = gl.GLLinePlotItem(
            pos=_dummy_pos, color=_dummy_col, width=1.5, mode='lines', antialias=False
        )
        self._area_interior_lines.setGLOptions({
            'glEnable':    (GL_BLEND,),
            'glBlendFunc': (GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA),
            'glDisable':   (GL_DEPTH_TEST,),
        })
        self._area_interior_lines.setVisible(False)
        self.hovered_area_id = None                                           

        self.current_model = None
        self.selected_element_ids = [] 
        self.selected_node_ids = [] 
        self.selected_area_ids = []
        self.view_extruded = True
        self.snapping_enabled = False
        self.snap_modes = {'grid': True, 'joints': True, 'midpoints': False}
        self.snap_radius = 25.0
        self._snap_extra_key = None
        self._snap_extra_pts = np.zeros((0, 3), dtype=np.float32)
        self._snap_screen_xy = None                                                
        self.crosshair = MouseCrosshair(
            self,
            drawing_mode_fn=lambda: bool(self.snapping_enabled or self.beam_col_mode or self.cross_brace_mode or self.quick_area_mode),
            ink_rgb_fn=self._theme_ink_rgb,
        )
        self.load_labels = []
        self.view_extruded = True 
        self.show_joints = True      
        self.show_supports = True    
        self.show_releases = True   
        self.show_loads = True
        self.show_hinges = True
        self.load_type_filter = "both"
        self.visible_load_patterns = []
        self.show_local_axes = False
        self.show_slabs = True
        self.show_constraints = True
        self.camera = ArcballCamera(self)
        self.view_deflected = False    
        self.deflection_scale = 50.0
        self.contour_active = False
        self.contour_component = "Resultant"
        self.contour_range_auto = True
        self.contour_absolute = False
        self.contour_min = 0.0
        self.contour_max = 1.0
        self.view_shadow = True
        self.shadow_color = (0.7, 0.7, 0.7, 0.5)
        self.show_grid = True

        self.show_ghost_structure = True                       
        self._view_overrides = {}                                                                                            
        self._pre_force_was_extruded  = False                                                 
        self._pre_force_was_deflected = False
        self._pre_force_was_grid      = False

        self._plane_state = 0
        self._view_mode = "3D"
        self._grid_index = 0

        self.current_hover_data = None
        self.hovered_node_id = None
        self.hovered_elem_id = None
        self.hovered_tendon_id = None
        self.selected_tendon_ids = []

        self.hovered_cable_id = None                 
        self.selected_cable_ids = []

        self.deflection_cache = {}
        self.cache_valid = False
        self.cache_scale_used = None  
        self.anim_factor = 1.0 
        self.animation_manager = AnimationManager(self)
        self.animation_manager.signal_frame_update.connect(self._on_anim_frame)
        self.animation_manager.signal_ltha_frame_update.connect(self._on_ltha_frame)

        self.ltha_history = None                                                
        self.ltha_n_steps = 0
        self.ltha_dt = 0.01
        self.ltha_mode = False                                            
        self.ltha_highlight = None  
        self._selection_ltha_live = False
                                                                   
        self.ltha_hinge_state_idx = None                                                          
        self._ltha_hinge_cache = None
        self._hinge_highlight_key = None                                              
        self._hinge_blink_timer = None
        self._needs_hinge_refresh = False

        self.force_diagram_active = False
        self._force_calc_token = 0
        self._force_worker = None
        self._pending_force_request = None

        self.reaction_diagram_active = False
        self.reaction_data = {}
        self._pre_reaction_was_extruded = False
        self._pre_reaction_was_deflected = False
        self._pre_reaction_was_grid = False

        self._accel_overlay_pixmap    = None                                            
        self._accel_overlay_size      = (0, 0)                                  
        self._accel_overlay_last_step = -1                                                
        
        self.prerendered_geometry_frames = []                                 
        self.is_animation_cached = False                                           
        self.current_animation_frame = 0                                            
        
        self.animation_manager.canvas = self

        self.static_items = []      
        self.node_items = []         
        self.element_items = []
        self._axis_items = []                                                          
        self._pending_static_line_pos = []
        self._pending_static_line_colors = []
        self._pending_bubble_line_pos = []
        self._pending_bubble_line_colors = []
        self._bubble_line_width = 1.5
        self._pending_grid_a_pos, self._pending_grid_a_col = [], []                                            
        self._pending_grid_b_pos, self._pending_grid_b_col = [], []                 
        self._grid_width_lines = 1.5
        self._grid_width_floor = 1.0
        self.load_items = []
        self._support_items = []
        self._support_positions = {'fixed': [], 'pinned': [], 'roller': [], 'custom': []}
        self._support_rebuild_timer = QTimer()
        self._support_rebuild_timer.setSingleShot(True)
        self._support_rebuild_timer.timeout.connect(lambda: self._rebuild_support_items(_from_zoom=True))
        self._boundary_node_cache = None
        self._last_support_rebuild_scale = None
        self._sel_overlay_items = []      
        self._dash_anim = []                                                                 
        self._dash_phase = 0.0
        self._area_dash_src = None
        self.last_selection_state = {'nodes': [], 'elements': [], 'blink': True}
        self._loads_dirty = True                                                      

        self._label_hide_timer = QTimer()
        self._label_hide_timer.setSingleShot(True)
        self._label_hide_timer.timeout.connect(lambda: setattr(self, '_is_zooming', False))
        self._label_hide_timer.timeout.connect(self.update)
        self._label_pixmap         = None                                 
        self._label_pixmap_dirty   = False                      
        self._label_rebuild_timer  = QTimer()
        self._label_rebuild_timer.setSingleShot(True)
        
        self._label_hide_timer.timeout.connect(
            lambda: self._schedule_label_rebuild(0)
)
        self._is_zooming = False

        self.active_view_plane = None 

        self.linked_plane_item = None
        self.linked_plane_outline = None

        self.drag_start = None
        self.drag_current = None
        self.is_selecting = False
        self._is_navigating = False

        self.blink_state = True

        self.vbo_manager = VBORenderManager()
        self.text_builder = SDFTextBuilder()

        self._node_screen_cache = {}
        self._screen_cache_key = None
                                    
        self.pivot_dot = gl.GLScatterPlotItem(pos=np.array([[0,0,0]]), size=6, 
                                              color=(1, 1, 0, 0.3), pxMode=True)
        self.pivot_dot.setGLOptions('translucent')
        self.pivot_dot.setVisible(False)
        self.addItem(self.pivot_dot)
        
        self.pivot_timer = QTimer()
        self.pivot_timer.setSingleShot(True)
        self.pivot_timer.timeout.connect(lambda: self.pivot_dot.setVisible(False))

        self.snap_ring = gl.GLLinePlotItem(pos=np.array([[0,0,0]]), mode='line_strip', 
                                           color=(1, 0, 0, 0.4), width=1.5, antialias=True)
        self.snap_ring.setGLOptions('translucent')
        self.addItem(self.snap_ring)
        
        self.snap_dot = gl.GLScatterPlotItem(pos=np.array([[0,0,0]]), size=5, 
                                             color=(1, 0, 0, 0.5), pxMode=True)
        self.snap_dot.setGLOptions('translucent')
        self.addItem(self.snap_dot)

        self.snap_text = gl.GLTextItem(pos=np.array([0,0,0]), text="", color=(0.2, 0.6, 1.0, 0.8))
        self.addItem(self.snap_text)
        
        self.snap_ring.setVisible(False)
        self.snap_dot.setVisible(False)

        self.inspection_dot = gl.GLScatterPlotItem(
            pos=np.array([[0, 0, 0]]),
            size=14,
            color=(1, 0, 0, 1),
            pxMode=True
        )
        self.inspection_dot.setGLOptions({'glDepthMask': (True,), 'glDepthFunc': (GL_ALWAYS,)})
        self.inspection_dot.setVisible(False)
        self.addItem(self.inspection_dot)

        self._draw_start = None  
        self.preview_line = gl.GLLinePlotItem(
            pos=np.array([[0,0,0],[0,0,0]]), 
            mode='lines', 
            color=(0.2, 0.6, 1.0, 0.6), 
            width=3, 
            antialias=True
        )
        self.preview_line.setGLOptions('translucent')
        self.preview_line.setVisible(False)
        self.addItem(self.preview_line)

        self.section_locator = gl.GLLinePlotItem(pos=np.zeros((5,3)), mode='line_strip', color=(1.0, 0.55, 0.0, 1.0), width=3.0, antialias=True)
        self.section_locator_mesh = gl.GLMeshItem(smooth=False, drawEdges=False, color=(1.0, 0.55, 0.0, 0.4))
        self.section_locator.setGLOptions('translucent')
        self.section_locator_mesh.setGLOptions('translucent')
        self.section_locator.setVisible(False)
        self.section_locator_mesh.setVisible(False)
        self.addItem(self.section_locator)
        self.addItem(self.section_locator_mesh)

        self.cross_brace_mode = False
        self._brace_hover_cell = None

        _dummy2 = np.array([[0,0,0],[1,1,0]], dtype=np.float32)
        self._brace_prev_x1 = gl.GLLinePlotItem(pos=_dummy2, mode='lines',
                                                  color=(1.0, 0.55, 0.0, 0.85), width=2.5, antialias=True)
        self._brace_prev_x1.setGLOptions('translucent')
        self._brace_prev_x1.setVisible(False)
        self.addItem(self._brace_prev_x1)

        self._brace_prev_x2 = gl.GLLinePlotItem(pos=_dummy2.copy(), mode='lines',
                                                  color=(1.0, 0.55, 0.0, 0.85), width=2.5, antialias=True)
        self._brace_prev_x2.setGLOptions('translucent')
        self._brace_prev_x2.setVisible(False)
        self.addItem(self._brace_prev_x2)

        self._brace_prev_border = gl.GLLinePlotItem(
            pos=np.zeros((5, 3), dtype=np.float32), mode='line_strip',
            color=(1.0, 0.55, 0.0, 0.35), width=1.5, antialias=True)
        self._brace_prev_border.setGLOptions('translucent')
        self._brace_prev_border.setVisible(False)
        self.addItem(self._brace_prev_border)

        self.quick_area_mode = False
        self._quick_area_hover_cell = None
        self._quick_area_prev_border = gl.GLLinePlotItem(
            pos=np.zeros((5, 3), dtype=np.float32), mode='line_strip',
            color=(0.0, 0.65, 0.85, 0.95), width=2.5, antialias=True)
        self._quick_area_prev_border.setGLOptions('translucent')
        self._quick_area_prev_border.setVisible(False)
        self.addItem(self._quick_area_prev_border)
        self._quick_area_prev_fill = gl.GLMeshItem(
            vertexes=np.zeros((4, 3), dtype=np.float32),
            faces=np.array([[0, 1, 2], [0, 2, 3]], dtype=np.uint32),
            smooth=False, drawEdges=False, color=(0.0, 0.65, 0.85, 0.25))
        self._quick_area_prev_fill.setGLOptions('translucent')
        self._quick_area_prev_fill.setVisible(False)
        self.addItem(self._quick_area_prev_fill)

        self.beam_col_mode = False
        self._beam_col_hover_seg = None                                 
        self._beam_col_type = 'beam'                          

        _dummy3 = np.array([[0,0,0],[1,0,0]], dtype=np.float32)
        self._beam_col_prev_line = gl.GLLinePlotItem(
            pos=_dummy3, mode='lines',
            color=(0.1, 0.8, 0.3, 0.9), width=3.5, antialias=True
        )
        self._beam_col_prev_line.setGLOptions('translucent')
        self._beam_col_prev_line.setVisible(False)
        self.addItem(self._beam_col_prev_line)

        self.force_mesh_item = gl.GLMeshItem(
            smooth=False,          
            drawEdges=False, 
            glOptions='translucent' 
        )
        self.addItem(self.force_mesh_item)
        self.force_mesh_item.hide() 

        self.force_line_item = gl.GLLinePlotItem(
            mode='lines',
            antialias=True
        )
        self.addItem(self.force_line_item)
        self.force_line_item.hide()

    _FXAA_VS = """#version 330 core
out vec2 v_uv;
void main() {
    vec2 p = vec2(float((gl_VertexID << 1) & 2), float(gl_VertexID & 2));
    v_uv = p;
    gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
}
"""
    _FXAA_FS = """#version 330 core
in vec2 v_uv;
out vec4 FragColor;
uniform sampler2D u_tex;
uniform vec2  u_texel;
uniform float u_threshold;   // relative edge threshold (lower = more edges smoothed)
uniform float u_subpix;      // sub-pixel (thin line / isolated pixel) smoothing 0..1

const float EDGE_MIN = 0.0312;
const float Q[12] = float[12](1.0, 1.0, 1.0, 1.0, 1.0, 1.5, 2.0, 2.0, 2.0, 2.0, 4.0, 8.0);

float luma(vec3 c) { return dot(c, vec3(0.299, 0.587, 0.114)); }
float lumaAt(vec2 uv) { return luma(textureLod(u_tex, uv, 0.0).rgb); }
#define lumaOff(o) luma(textureLodOffset(u_tex, v_uv, 0.0, o).rgb)

void main() {
    vec4  cM = texture(u_tex, v_uv);
    float lM = luma(cM.rgb);
    float lN = lumaOff(ivec2( 0,  1));
    float lS = lumaOff(ivec2( 0, -1));
    float lE = lumaOff(ivec2( 1,  0));
    float lW = lumaOff(ivec2(-1,  0));

    float lMax = max(lM, max(max(lN, lS), max(lE, lW)));
    float lMin = min(lM, min(min(lN, lS), min(lE, lW)));
    float range = lMax - lMin;
    if (range < max(EDGE_MIN, lMax * u_threshold)) { FragColor = cM; return; }

    float lNW = lumaOff(ivec2(-1,  1));
    float lNE = lumaOff(ivec2( 1,  1));
    float lSW = lumaOff(ivec2(-1, -1));
    float lSE = lumaOff(ivec2( 1, -1));
    float lNS = lN + lS;
    float lWE = lW + lE;

    // edge orientation
    float edgeH = abs(-2.0 * lW + (lNW + lSW)) + abs(-2.0 * lM + lNS) * 2.0 + abs(-2.0 * lE + (lNE + lSE));
    float edgeV = abs(-2.0 * lN + (lNW + lNE)) + abs(-2.0 * lM + lWE) * 2.0 + abs(-2.0 * lS + (lSW + lSE));
    bool horz = edgeH >= edgeV;

    float l1 = horz ? lS : lW;
    float l2 = horz ? lN : lE;
    float g1 = l1 - lM;
    float g2 = l2 - lM;
    bool steep1 = abs(g1) >= abs(g2);
    float grad = 0.25 * max(abs(g1), abs(g2));

    float stepLen = horz ? u_texel.y : u_texel.x;
    float lAvg;
    if (steep1) { stepLen = -stepLen; lAvg = 0.5 * (l1 + lM); }
    else        { lAvg = 0.5 * (l2 + lM); }

    vec2 pos = v_uv;
    if (horz) pos.y += stepLen * 0.5; else pos.x += stepLen * 0.5;

    // walk along the edge in both directions until its end is found
    vec2 off = horz ? vec2(u_texel.x, 0.0) : vec2(0.0, u_texel.y);
    vec2 p1 = pos - off;
    vec2 p2 = pos + off;
    float e1 = lumaAt(p1) - lAvg;
    float e2 = lumaAt(p2) - lAvg;
    bool r1 = abs(e1) >= grad;
    bool r2 = abs(e2) >= grad;
    if (!r1) p1 -= off;
    if (!r2) p2 += off;
    for (int i = 2; i < 12 && !(r1 && r2); i++) {
        if (!r1) { e1 = lumaAt(p1) - lAvg; r1 = abs(e1) >= grad; }
        if (!r2) { e2 = lumaAt(p2) - lAvg; r2 = abs(e2) >= grad; }
        if (!r1) p1 -= off * Q[i];
        if (!r2) p2 += off * Q[i];
    }

    float d1 = horz ? (v_uv.x - p1.x) : (v_uv.y - p1.y);
    float d2 = horz ? (p2.x - v_uv.x) : (p2.y - v_uv.y);
    bool  dir1 = d1 < d2;
    float dist = min(d1, d2);
    float thick = d1 + d2;
    float pixelOffset = -dist / thick + 0.5;

    bool centerSmaller = lM < lAvg;
    bool correct = ((dir1 ? e1 : e2) < 0.0) != centerSmaller;
    float finalOffset = correct ? pixelOffset : 0.0;

    // sub-pixel antialiasing for thin features
    float lAvg3 = (1.0 / 12.0) * (2.0 * (lNS + lWE) + lNW + lNE + lSW + lSE);
    float sub = clamp(abs(lAvg3 - lM) / range, 0.0, 1.0);
    sub = smoothstep(0.0, 1.0, sub);
    sub = sub * sub * u_subpix;
    finalOffset = max(finalOffset, sub);

    vec2 fuv = v_uv;
    if (horz) fuv.y += finalOffset * stepLen; else fuv.x += finalOffset * stepLen;
    FragColor = vec4(textureLod(u_tex, fuv, 0.0).rgb, cM.a);
}
"""

    def _fxaa_wanted(self):
        try:
            return (int(self.display_config.get("msaa_level", 2)) == 5
                    and not getattr(self, '_fxaa_failed', False))
        except Exception:
            return False

    def _fxaa_release(self):
        for name, fn in (('_fxaa_fbo', glDeleteFramebuffers), ('_fxaa_rbo', glDeleteRenderbuffers),
                         ('_fxaa_tex', glDeleteTextures)):
            v = getattr(self, name, None)
            if v:
                try: fn(1, [v])
                except Exception: pass
            setattr(self, name, None)
        self._fxaa_size = None

    def _fxaa_begin(self):
        """Bind the offscreen FBO for scene rendering. Returns True if FXAA is active this frame."""
        if not self._fxaa_wanted():
            return False
        try:
            from OpenGL.GL import shaders
            w, h = max(1, int(self.deviceWidth())), max(1, int(self.deviceHeight()))
            if getattr(self, '_fxaa_prog', None) is None:
                self._fxaa_prog = shaders.compileProgram(
                    shaders.compileShader(self._FXAA_VS, GL_VERTEX_SHADER),
                    shaders.compileShader(self._FXAA_FS, GL_FRAGMENT_SHADER))
                self._fxaa_loc_tex = glGetUniformLocation(self._fxaa_prog, "u_tex")
                self._fxaa_loc_texel = glGetUniformLocation(self._fxaa_prog, "u_texel")
                self._fxaa_loc_thr = glGetUniformLocation(self._fxaa_prog, "u_threshold")
                self._fxaa_loc_sub = glGetUniformLocation(self._fxaa_prog, "u_subpix")
                self._fxaa_vao = glGenVertexArrays(1)
                self._fxaa_fbo = self._fxaa_tex = self._fxaa_rbo = None
                self._fxaa_size = None
            if getattr(self, '_fxaa_size', None) != (w, h):
                self._fxaa_release()
                self._fxaa_tex = glGenTextures(1)
                glBindTexture(GL_TEXTURE_2D, self._fxaa_tex)
                glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, w, h, 0, GL_RGBA, GL_UNSIGNED_BYTE, None)
                glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
                glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
                glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
                glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
                glBindTexture(GL_TEXTURE_2D, 0)
                self._fxaa_rbo = glGenRenderbuffers(1)
                glBindRenderbuffer(GL_RENDERBUFFER, self._fxaa_rbo)
                glRenderbufferStorage(GL_RENDERBUFFER, GL_DEPTH24_STENCIL8, w, h)
                glBindRenderbuffer(GL_RENDERBUFFER, 0)
                self._fxaa_fbo = glGenFramebuffers(1)
                glBindFramebuffer(GL_FRAMEBUFFER, self._fxaa_fbo)
                glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, self._fxaa_tex, 0)
                glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_DEPTH_STENCIL_ATTACHMENT, GL_RENDERBUFFER, self._fxaa_rbo)
                if glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE:
                    raise RuntimeError("FXAA framebuffer incomplete")
                self._fxaa_size = (w, h)
            else:
                glBindFramebuffer(GL_FRAMEBUFFER, self._fxaa_fbo)
            return True
        except Exception as e:
            print(f"FXAA disabled (falling back to no AA): {e}")
            self._fxaa_failed = True
            try: glBindFramebuffer(GL_FRAMEBUFFER, self.defaultFramebufferObject())
            except Exception: pass
            return False

    def _fxaa_end(self):
        """Run the FXAA pass from the offscreen texture into the widget's real framebuffer."""
        w, h = self._fxaa_size
        glBindFramebuffer(GL_FRAMEBUFFER, self.defaultFramebufferObject())
        glViewport(0, 0, w, h)
        glDisable(GL_DEPTH_TEST)
        glDisable(GL_BLEND)
        glUseProgram(self._fxaa_prog)
        glActiveTexture(GL_TEXTURE0)
        glBindTexture(GL_TEXTURE_2D, self._fxaa_tex)
        glUniform1i(self._fxaa_loc_tex, 0)
        glUniform2f(self._fxaa_loc_texel, 1.0 / w, 1.0 / h)
        try:
            _t = max(0.0, min(1.0, float(self.display_config.get("fxaa_strength", 60)) / 100.0))
        except Exception:
            _t = 0.6
        glUniform1f(self._fxaa_loc_thr, 0.25 - 0.1875 * _t)                                    
        glUniform1f(self._fxaa_loc_sub, _t)                            
        glBindVertexArray(self._fxaa_vao)
        glDrawArrays(GL_TRIANGLES, 0, 3)
        glBindVertexArray(0)
        glBindTexture(GL_TEXTURE_2D, 0)
        glUseProgram(0)
        glEnable(GL_DEPTH_TEST)
        glClear(GL_DEPTH_BUFFER_BIT)                                                                   

    def initializeGL(self):
        super().initializeGL()
        self.vbo_manager.init_gl()    
        self.vbo_manager.load_font_texture()  

    def _theme_ink_rgb(self):
        """
        Returns the (r, g, b) tuple used to draw load/reaction arrows (force,
        moment, distributed load, area load, etc.) and their value labels.

        These used to be hard-coded black, which disappears against a Dark
        theme background. Reads display_config['ui_theme'] (set from
        Graphics Options / main window, "Light" or "Dark") and returns white
        ink for Dark, black ink for Light so the arrows and labels stay
        legible in both.
        """
        theme = self.display_config.get('ui_theme', 'Light') if hasattr(self, 'display_config') else 'Light'
        if theme == 'Dark':
            return (1.0, 1.0, 1.0)
        return (0.0, 0.0, 0.0)

    def _theme_ink_color(self, alpha=1.0):
        """Same as _theme_ink_rgb() but returns a full RGBA tuple."""
        r, g, b = self._theme_ink_rgb()
        return (r, g, b, alpha)

    def _line_intersects_rect(self, p1, p2, rect):
        """
        Robust Line Segment vs Rectangle Intersection.
        rect = (x_min, y_min, x_max, y_max)
        """
        x_min, y_min, x_max, y_max = rect
        
        if min(p1[0], p2[0]) > x_max or max(p1[0], p2[0]) < x_min: return False
        if min(p1[1], p2[1]) > y_max or max(p1[1], p2[1]) < y_min: return False
        
        if x_min <= p1[0] <= x_max and y_min <= p1[1] <= y_max: return True
        if x_min <= p2[0] <= x_max and y_min <= p2[1] <= y_max: return True
        
        def ccw(A, B, C):
            return (C[1]-A[1]) * (B[0]-A[0]) > (B[1]-A[1]) * (C[0]-A[0])

        def intersect(A, B, C, D):
            return ccw(A,C,D) != ccw(B,C,D) and ccw(A,B,C) != ccw(A,B,D)

        bl = (x_min, y_min); br = (x_max, y_min)
        tr = (x_max, y_max); tl = (x_min, y_max)
        
        if intersect(p1, p2, bl, br): return True         
        if intersect(p1, p2, br, tr): return True        
        if intersect(p1, p2, tr, tl): return True      
        if intersect(p1, p2, tl, bl): return True       
        
        return False

    def compute_model_bbox(self, model=None):
        """
        Compute bounding box from ACTUAL node positions (not the grid).
        Returns (center: QVector3D, diagonal: float, bounds: dict | None).
        bounds is None when the model has no nodes yet — callers should fall
        back to the grid in that case.
        """
        m = model or self.current_model
        if not m or not m.nodes:
            return QVector3D(0, 0, 0), 1.0, None

        _bk = (id(m), len(m.nodes))
        _bc = getattr(self, '_bbox_cache', None)
        if _bc is not None and _bc[0] == _bk:
            lo, hi = _bc[1]
        else:
            arr = np.array([(n.x, n.y, n.z) for n in m.nodes.values()], dtype=np.float64)
            lo, hi = arr.min(axis=0), arr.max(axis=0)
            self._bbox_cache = (_bk, (lo, hi))
        min_x, min_y, min_z = (float(v) for v in lo)
        max_x, max_y, max_z = (float(v) for v in hi)

        cx = (min_x + max_x) / 2.0
        cy = (min_y + max_y) / 2.0
        cz = (min_z + max_z) / 2.0

        dx, dy, dz = max_x - min_x, max_y - min_y, max_z - min_z
        diagonal = max(math.sqrt(dx*dx + dy*dy + dz*dz), 0.001)

        return QVector3D(cx, cy, cz), diagonal, {
            'min': (min_x, min_y, min_z),
            'max': (max_x, max_y, max_z),
            'span': (dx, dy, dz),
        }

    @staticmethod
    def _fit_distance(diagonal: float, fov: float) -> float:
        """
        Compute the camera distance that fits a bounding sphere exactly inside the viewport.
        """
                                                                         
        if fov == 0:
                                                                              
            return diagonal * 0.9 
            
        radius = diagonal / 2.0
        base_dist = (radius / math.tan(math.radians(fov) / 2.0))
        
        return base_dist * 1.8
    
    def set_standard_view(self, view_name):
                                                                               
        target_center, diagonal, bounds = self.compute_model_bbox()

        if bounds:
                                                                              
            self.camera.set_model_scale(diagonal)
        else:
                                                                            
            if self.current_model and self.current_model.grid:
                gx = self.current_model.grid.x_grids
                gy = self.current_model.grid.y_grids
                gz = self.current_model.grid.z_grids
                if gx and gy and gz:
                    mid_x = (min(gx) + max(gx)) / 2.0
                    mid_y = (min(gy) + max(gy)) / 2.0
                    mid_z = (min(gz) + max(gz)) / 2.0
                    spans = [max(gx)-min(gx), max(gy)-min(gy), max(gz)-min(gz)]
                    diagonal = max(math.sqrt(sum(s*s for s in spans)), 0.1)
                    target_center = QVector3D(mid_x, mid_y, mid_z)
                    self.camera.set_model_scale(diagonal)

        if view_name in ["XY", "XZ", "YZ"] and self.active_view_plane:
            val = self.active_view_plane['value']
            axis = self.active_view_plane['axis']
            if axis == 'x': target_center.setX(val)
            elif axis == 'y': target_center.setY(val)
            elif axis == 'z': target_center.setZ(val)

        self._view_mode = view_name
        
        if view_name == "ISO":
            t_az, t_el, t_fov = -135, 35.264, 1
        elif view_name == "3D":
            t_az, t_el, t_fov = -135, 30, 60
        elif view_name == "XY":
            t_az, t_el, t_fov = -90, 90, 1                                               
        elif view_name == "XZ":
            t_az, t_el, t_fov = -90, 0, 1                
        elif view_name == "YZ":
            t_az, t_el, t_fov = 180, 0, 1                
        else:
            t_az, t_el, t_fov = -135, 30, 60

        target_dist = self._fit_distance(diagonal, t_fov)

        self.opts['fov'] = t_fov
        try:
            self.camera.anim.finished.disconnect()
        except:
            pass
            
        self.camera.animate_to(target_center, target_dist, t_az, t_el)

    def invalidate_snap_cache(self):
        self._snap_extra_key = None

    def set_snap_options(self, grid=None, joints=None, midpoints=None, radius=None):
        if grid is not None:      self.snap_modes['grid'] = bool(grid)
        if joints is not None:    self.snap_modes['joints'] = bool(joints)
        if midpoints is not None: self.snap_modes['midpoints'] = bool(midpoints)
        if radius is not None:    self.snap_radius = float(radius)
        self.invalidate_snap_cache()

    def _snap_extra_points(self, model):
        """Existing joints and/or frame midpoints as snap candidates (cached)."""
        want_j = self.snap_modes.get('joints', False)
        want_m = self.snap_modes.get('midpoints', False)
        if not (want_j or want_m):
            return np.zeros((0, 3), dtype=np.float32)
        key = (id(model), len(model.nodes), len(model.elements), want_j, want_m)
        if self._snap_extra_key == key:
            return self._snap_extra_pts
        def _node(ref):
            if hasattr(ref, 'x'):                                       
                return ref
            return model.nodes.get(ref) or model.nodes.get(str(ref))
        pts = []
        if want_j:
            for n in model.nodes.values():
                pts.append((n.x, n.y, n.z))
        if want_m:
            for el in model.elements.values():
                a, b = _node(el.node_i), _node(el.node_j)
                if a is not None and b is not None:
                    pts.append(((a.x + b.x) * 0.5, (a.y + b.y) * 0.5, (a.z + b.z) * 0.5))
        arr = np.array(pts, dtype=np.float32).reshape(-1, 3)
        self._snap_extra_key = key
        self._snap_extra_pts = arr
        return arr

    def _resolve_draw_model(self, model):
        """
        Deformed view of a solver-meshed run: draw the MESHED copy (split frames + sub-shells)
        with the full results, so beams bend through their mid nodes and shells show their mesh.
        Undeformed view (and runs without a solver mesh) always use the live model untouched.
        """
        live = model
        if getattr(model, '_is_solver_mesh_copy', False):
            live = getattr(self, '_live_model', None) or model                                          
        else:
            self._live_model = model

        use = live
        res = getattr(live, 'results', None)
        if (self.view_deflected and getattr(live, 'has_results', False) and isinstance(res, dict)
                and (res.get("info") or {}).get("solver_mesh") and getattr(live, 'file_path', None)):
            try:
                from app.solver_mesh_remap import load_mesh_context
                ctx = load_mesh_context(live.file_path)
            except Exception:
                import traceback; traceback.print_exc()
                ctx = None
            if ctx:
                meshed, mesh_map = ctx
                meshed.results = res
                meshed.has_results = True
                meshed.valid_result_paths = getattr(live, 'valid_result_paths', [])
                meshed._is_solver_mesh_copy = True
                meshed._canvas_mesh_map = mesh_map
                use = meshed

        prev = getattr(self, '_last_draw_model', None)
        if use is not prev:
            if (prev is not None and getattr(prev, '_is_solver_mesh_copy', False))\
                    or getattr(use, '_is_solver_mesh_copy', False):
                                                                                               
                self._zoom_coord_cache = None
                self._bbox_cache = None
                self._area_geom_cache = None
                self._sgpu_key = None
                self._sgpu_mode = None
                self._boundary_node_cache = None
            self._last_draw_model = use
        return use

    def _sync_selection_to_model(self, model):
        """A selected long beam also highlights the segments it was split into (meshed view only)."""
        extra = getattr(self, '_sel_extra_ids', set())
        ids = [i for i in (self.selected_element_ids or []) if i not in extra]
        extra_new = set()
        if model is not None and getattr(model, '_is_solver_mesh_copy', False):
            from app.solver_mesh_remap import expand_selected_frames
            expanded = expand_selected_frames(getattr(model, '_canvas_mesh_map', None) or {}, ids)
            extra_new = set(expanded) - set(ids)
            ids = expanded
        self._sel_extra_ids = extra_new
        self.selected_element_ids = ids

    def draw_model(self, model, sel_elems=None, sel_nodes=None, progress=None):
        self._snap_extra_key = None
        """
        Draws the model on the canvas.
        
        IMPORTANT: If animation is running, this method will:
        - Update selection state silently
        - NOT redraw (to prevent interrupting smooth animation)
        
        To force redraw during animation, call _force_draw_model() instead.
        """
                                             
        self.current_model = model
        if sel_elems is not None: 
            self.selected_element_ids = sel_elems
        if sel_nodes is not None: 
            self.selected_node_ids = sel_nodes
        
        if self.animation_manager.is_running:
                                                                             
            return                                               
        
        self._force_draw_model(model, sel_elems, sel_nodes, progress=progress)
    
    def update_area_preview(self, node_coords, mouse_x, mouse_y, mouse_z):
        """Draws a rubber-band polygon from the clicked nodes to the mouse cursor."""
        if not node_coords:
            self._area_preview_line.setVisible(False)
            return
            
        pts = list(node_coords)
        pts.append((mouse_x, mouse_y, mouse_z))
        pts.append(pts[0])                                        
        
        self._area_preview_line.setData(pos=np.array(pts), color=(0, 1, 1, 1), width=2, mode='line_strip')
        self._area_preview_line.setVisible(True)

    def hide_area_preview(self):
        self._area_preview_line.setVisible(False)

    _DASH_LEN = 0.4                                 
    _DASH_GAP = 0.25                               
    _DASH_TRAVEL_PER_PX = 0.003                                                                             
                                                                                                      
    _DASH_MAX_SEGMENTS = 1500

    @staticmethod
    def _dash_batch(P1, P2, dash, gap, ph):
        """
        Vectorised dashed segments for many straight segments at once.

        P1, P2 : (M,3) segment start/end points
        dash, gap : scalar or (M,) dash / gap length along each segment
        ph     : scalar or (M,) pattern offset in [0, dash+gap) -- increasing it
                 slides the dashes from P1 toward P2.  ph=0 starts a dash at P1.

        Returns a (2n,3) float32 array of line-pair endpoints (GL_LINES layout).
        """
        P1 = np.asarray(P1, dtype=np.float64).reshape(-1, 3)
        P2 = np.asarray(P2, dtype=np.float64).reshape(-1, 3)
        M = len(P1)
        empty = np.zeros((0, 3), dtype=np.float32)
        if M == 0:
            return empty
        dash = np.broadcast_to(np.asarray(dash, dtype=np.float64), (M,))
        gap = np.broadcast_to(np.asarray(gap, dtype=np.float64), (M,))
        ph = np.broadcast_to(np.asarray(ph, dtype=np.float64), (M,))

        d = P2 - P1
        L = np.linalg.norm(d, axis=1)
        ok = L > 1e-6
        if not ok.any():
            return empty
        P1, d, L = P1[ok], d[ok], L[ok]
        dash, gap, ph = dash[ok], gap[ok], ph[ok]
        u = d / L[:, None]
        period = dash + gap

        K = int(np.ceil(np.max(L / period))) + 2
        k = np.arange(K, dtype=np.float64)[None, :]
        s = (k - 1.0) * period[:, None] + ph[:, None]
        e = s + dash[:, None]
        Lc = L[:, None]
        s = np.clip(s, 0.0, Lc)
        e = np.clip(e, 0.0, Lc)
        m = e > s + 1e-9
        if not m.any():
            return empty
        rows = np.nonzero(m)[0]
        base = P1[rows]
        uu = u[rows]
        a = base + uu * s[m][:, None]
        b = base + uu * e[m][:, None]
        out = np.empty((2 * len(a), 3), dtype=np.float64)
        out[0::2] = a
        out[1::2] = b
        return out.astype(np.float32)

    @staticmethod
    def _polyline_segments(pts):
        """Polyline (N,3) -> (P1, P2, cum): its segments plus the arclength at
        which each one starts, so the dash pattern flows across the vertices."""
        pts = np.asarray(pts, dtype=np.float64)
        P1 = pts[:-1]
        P2 = pts[1:]
        seg = np.linalg.norm(P2 - P1, axis=1)
        cum = np.concatenate([[0.0], np.cumsum(seg)[:-1]])
        return P1, P2, cum

    def _dash_frac(self):
        return float(getattr(self, '_dash_phase', 0.0)) % 1.0

    def _dash_geometry(self, P1, P2, cum, frac):
        period = self._DASH_LEN + self._DASH_GAP
        ph = (frac * period - cum) % period
        return self._dash_batch(P1, P2, self._DASH_LEN, self._DASH_GAP, ph)

    def _area_dash_geometry(self, src, frac):
        P1, P2, dash, gap = src
        return self._dash_batch(P1, P2, dash, gap, frac * (dash + gap))

    def _add_dash_overlay(self, acc, width, color=(1.0, 1.0, 0.0, 1.0)):
        """acc: list of (P1, P2, cum) tuples. Builds one animated dashed line
        item and registers it so advance_selection_dashes() can slide it."""
        if not acc:
            return
        P1 = np.concatenate([a[0] for a in acc])
        P2 = np.concatenate([a[1] for a in acc])
        cum = np.concatenate([np.asarray(a[2], dtype=np.float64) for a in acc])
        if len(P1) == 0:
            return
        if len(P1) > self._DASH_MAX_SEGMENTS:
            pos = np.empty((2 * len(P1), 3), dtype=np.float32)
            pos[0::2] = P1
            pos[1::2] = P2
            col = np.tile(np.array(color, dtype=np.float32), (len(pos), 1))
            item = gl.GLLinePlotItem(pos=pos, color=col, mode='lines', width=width, antialias=False)
            item.setGLOptions({
                'glEnable': (GL_BLEND,),
                'glBlendFunc': (GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA),
                'glDisable': (GL_DEPTH_TEST,)
            })
            self.addItem(item)
            self._sel_overlay_items.append(item)
            return                                                                         
        pos = self._dash_geometry(P1, P2, cum, self._dash_frac())
        visible = len(pos) > 0
        if not visible:
            pos = np.zeros((2, 3), dtype=np.float32)
        col = np.tile(np.array(color, dtype=np.float32), (len(pos), 1))
        item = gl.GLLinePlotItem(pos=pos, color=col, mode='lines', width=width, antialias=True)
        item.setGLOptions({
            'glEnable': (GL_BLEND,),
            'glBlendFunc': (GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA),
            'glDisable': (GL_DEPTH_TEST,)
        })
        item.setVisible(visible)
        self.addItem(item)
        self._sel_overlay_items.append(item)
        if not hasattr(self, '_dash_anim'):
            self._dash_anim = []
        self._dash_anim.append({'item': item, 'P1': P1, 'P2': P2, 'cum': cum, 'color': color})

    def advance_selection_dashes(self, travel_px):
        """Slides every selection dash pattern along its line by an amount
        proportional to `travel_px`. Cheap: only re-slices cached segments,
        never touches the model."""
        recs = getattr(self, '_dash_anim', None) or []
        area_src = getattr(self, '_area_dash_src', None)
        area_item = getattr(self, '_area_interior_lines', None)
        area_on = (area_src is not None and area_item is not None and area_item.visible()
                   and len(area_src[0]) <= self._DASH_MAX_SEGMENTS)
        if not recs and not area_on:
            return

        self._dash_phase = (float(getattr(self, '_dash_phase', 0.0))
                            + travel_px * self._DASH_TRAVEL_PER_PX) % 1.0
        frac = self._dash_phase

        live = self._sel_overlay_items
        for rec in recs:
            item = rec['item']
            if item not in live:
                continue
            pos = self._dash_geometry(rec['P1'], rec['P2'], rec['cum'], frac)
            if len(pos) == 0:
                item.setVisible(False)
                continue
            col = np.tile(np.array(rec['color'], dtype=np.float32), (len(pos), 1))
            item.setData(pos=pos, color=col)
            item.setVisible(True)

        if area_on:
            pos = self._area_dash_geometry(area_src, frac)
            if len(pos) == 0:
                area_item.setVisible(False)
            else:
                col = np.tile(np.array([1.0, 1.0, 0.0, 1.0], dtype=np.float32), (len(pos), 1))
                area_item.setData(pos=pos, color=col, width=1.5, mode='lines')
                area_item.setVisible(True)
        self.update()

    def _march_selection_dashes(self, pos):
        """Called from mouseMoveEvent: converts mouse travel into dash travel."""
        last = getattr(self, '_dash_last_pos', None)
        self._dash_last_pos = (pos.x(), pos.y())
        if last is None:
            return
        if not getattr(self, '_dash_anim', None) and getattr(self, '_area_dash_src', None) is None:
            return
        dist = math.hypot(pos.x() - last[0], pos.y() - last[1])
        self._dash_pending_px = getattr(self, '_dash_pending_px', 0.0) + min(dist, 60.0)
        now = time.perf_counter()
        if now - getattr(self, '_dash_last_t', 0.0) < 0.012:
            return
        self._dash_last_t = now
        px, self._dash_pending_px = self._dash_pending_px, 0.0
        if px > 0.0:
            self.advance_selection_dashes(px)

    def _shell_interior_dashes(self, pts, inset=0.18, n_dashes=5):
        """
        Interior dashed outline for a shell face.

        The polygon is shrunk toward its centroid by `inset`, and each edge of
        that inset polygon carries `n_dashes` dash/gap cycles.

        pts : (N, 3) world-space polygon vertices in order
        Returns (P1, P2, dash, gap): one row per inset edge, with the dash and
        gap length for that edge, ready for _dash_batch().
        """
        pts = np.asarray(pts, dtype=np.float64)
        centroid  = pts.mean(axis=0)
        inset_pts = pts + (centroid - pts) * inset
        P1 = inset_pts
        P2 = np.roll(inset_pts, -1, axis=0)
        L = np.linalg.norm(P2 - P1, axis=1)
        keep = L > 1e-6
        period = L[keep] / n_dashes
        return P1[keep], P2[keep], period * 0.55, period * 0.45

    def _rebuild_area_interior_lines(self):
        """
        Rebuild the interior dashed-line overlay for shells.

        Shows pure yellow dashes (matching frame selection colour) only for areas
        that are currently selected or hovered.  All other shells are invisible.
        Called from _update_area_vbo (selection change) and _handle_hover_tooltip
        (hover change).
        """
        if not hasattr(self, '_area_interior_lines'):
            return
        model = self.current_model
        if not model or not getattr(self, 'show_slabs', True):
            self._area_interior_lines.setVisible(False)
            self._area_dash_src = None
            return

        sel_ids     = set(getattr(self, 'selected_area_ids', []))
        hov_id      = getattr(self, 'hovered_area_id', None)
        active_ids  = sel_ids | ({hov_id} if hov_id is not None else set())

        if not active_ids:
            self._area_interior_lines.setVisible(False)
            self._area_dash_src = None
            return

        SEL_COLOR = [1.0, 1.0, 0.0, 1.0]                                        
        verts, colors = [], []

        for aeid in active_ids:
            ae = model.area_elements.get(aeid)
            if ae is None or len(ae.nodes) < 3:
                continue

            states = [self._get_visibility_state(n.x, n.y, n.z) for n in ae.nodes] + [self._vo_state('area', ae.id)]
            if min(states) < 2:
                continue
                                                                   
            pts = np.array([[n.x, n.y, n.z] for n in ae.nodes])
            if self._area_can_deflect(model):
                pts = self._area_deflect_pts(model, ae.nodes, pts,
                                             self.deflection_scale * self.anim_factor)
            _a, _b, _d, _g = self._shell_interior_dashes(pts)
            if len(_a):
                verts.append((_a, _b, _d, _g))

        if verts:
            src = (np.concatenate([v[0] for v in verts]), np.concatenate([v[1] for v in verts]),
                   np.concatenate([v[2] for v in verts]), np.concatenate([v[3] for v in verts]))
            self._area_dash_src = src
            iv = self._area_dash_geometry(src, self._dash_frac())
            if len(iv):
                ic = np.tile(np.array(SEL_COLOR, dtype=np.float32), (len(iv), 1))
                self._area_interior_lines.setData(pos=iv, color=ic, width=1.5, mode='lines')
                self._area_interior_lines.setVisible(True)
            else:
                self._area_interior_lines.setVisible(False)
        else:
            self._area_dash_src = None
            self._area_interior_lines.setVisible(False)
    
    def clear_selection(self):
        """Clears all selection state from the canvas."""
        self.selected_element_ids = []
        self.selected_node_ids    = []
        self.selected_area_ids    = []
        self.selected_tendon_ids  = []
        self.selected_cable_ids   = []
        self.selected_link_ids    = []
        self._rebuild_selection_overlay()
        self._rebuild_area_interior_lines()                                        
        self.update()                               

    def rebuild_scene(self):
        """Full scene rebuild — use after any structural model change (mesh, delete, etc.)."""
        if self.current_model is not None:
            self.invalidate_area_vbo()                                          
            self._force_draw_model(self.current_model)

    def invalidate_area_vbo(self):
        """Force the next _update_area_vbo call to do a full rebuild,
        bypassing the structural cache.  Call this whenever area section
        properties change (colour, thickness) without changing element count."""
        self._area_vbo_dirty = True

    def refresh_graphics_geometry(self, model):
        """Apply baked appearance changes without resetting playback or selection."""
        if model is None:
            return
        manager = self.animation_manager
        animated = manager.is_running and not getattr(self, 'ltha_mode', False)
        factor = self.vbo_manager.current_anim_factor
        self.invalidate_animation_cache()
        self.invalidate_area_vbo()
        self._anim_vbo_built = False
        self._ltha_vbo_built = False
        self._ltha_hinge_cache = None
        self._needs_anim_vbo_build = False
        self._needs_ltha_vbo_update = False
        self._undef_frames = None
        self._sgpu_key = None
        self._sgpu_mode = None
                                                                              
        self._force_draw_model(model)
        if animated and self.view_deflected:
            self._needs_anim_vbo_build = True
            self.vbo_manager.set_anim_factor(factor)
        self.update()

    def _area_can_deflect(self, model):
        """True when shells should be drawn deformed (same rule as frames)."""
        res = getattr(model, 'results', None)
        return bool(self.view_deflected
                    and getattr(model, 'has_results', False)
                    and res is not None
                    and res.get("displacements"))

    def _area_deflect_pts(self, model, nodes, pts, factor):
        """pts (N,3) rest corners -> pts + translations * factor.
        factor = deflection_scale * anim_factor. Missing node results = 0."""
        if factor == 0.0:
            return pts
        disp = model.results.get("displacements", {})
        d = np.zeros((len(nodes), 3), dtype=np.float64)
        for i, n in enumerate(nodes):
            r = disp.get(str(n.id))
            if r:
                d[i] = r[:3]
        return pts + (d * factor).astype(pts.dtype)

    def _area_fast_geom(self, model):
        key = (id(model), len(model.area_elements))
        c = getattr(self, '_area_geom_cache', None)
        if c is not None and c.get('key') == key:
            return c if c.get('ok') else None
        c = {'key': key, 'ok': False, 'groups': {}}
        self._area_geom_cache = c
        hexc = {}

        def rgb(h):
            if h not in hexc:
                if isinstance(h, str) and h.startswith('#'):
                    s = h.lstrip('#')
                    hexc[h] = (int(s[0:2], 16) / 255.0, int(s[2:4], 16) / 255.0, int(s[4:6], 16) / 255.0)
                else:
                    hexc[h] = (0.5, 0.5, 0.5)
            return hexc[h]

        buckets = {3: [], 4: []}
        for aeid, ae in model.area_elements.items():
            nn = len(ae.nodes)
            if nn < 3:
                continue
            if nn not in buckets:
                return None
            buckets[nn].append(ae)
        for nn, lst in buckets.items():
            if not lst:
                continue
            P = np.array([[(nd.x, nd.y, nd.z) for nd in ae.nodes] for ae in lst], dtype=np.float32)
            secs = [ae.section for ae in lst]
            c['groups'][nn] = dict(
                E=len(lst), P=P,
                rgb=np.array([rgb(getattr(s, 'display_color', '#808080')) for s in secs], dtype=np.float32),
                ins=np.array([float(getattr(ae, 'insertion_offset', 0.0) or 0.0) for ae in lst], dtype=np.float64),
                thk=np.array([float(getattr(s, 'membrane_thickness', getattr(s, 'thickness', 0.2))) for s in secs],
                             dtype=np.float64),
                trib=np.array([getattr(s, 'modeling_type', None) == "Tributary Area" for s in secs], dtype=bool),
                ids=[str(nd.id) for ae in lst for nd in ae.nodes],
            )
        c['ok'] = True
        return c

    def _area_fast_disp(self, c, results):
        if c.get('dkey') == id(results):
            return
        disp = results.get("displacements", {})
        get = disp.get
        for nn, g in c['groups'].items():
            rows = [get(s) for s in g['ids']]
            g['D'] = np.array([r[:3] if r else (0.0, 0.0, 0.0) for r in rows],
                              dtype=np.float64).reshape(g['E'], nn, 3)
        c['dkey'] = id(results)

    def _area_fast_pass(self, c, defl_factor, ctx):
        deflected = ctx['view_deflected']
        is_ext = ctx['is_extruded']
        fo = ctx['face_opacity']
        edge_c = np.asarray(ctx['edge_c'], dtype=np.float32)
        con = ctx['contour']
        f32 = np.float32
        fv, fcl, ff, fnl, ev, ecl = [], [], [], [], [], []
        tris = []
        voff = 0

        order = (3, 4) if is_ext else (4, 3)
        for nn in order:
            g = c['groups'].get(nn)
            if g is None:
                continue
            sel = ~g['trib'] if deflected else slice(None)
            P = g['P'][sel]
            E = len(P)
            if E == 0:
                continue
            D = g['D'][sel] if 'D' in g else None
            rgb = g['rgb'][sel]; ins = g['ins'][sel]; thk = g['thk'][sel]
            if defl_factor != 0.0 and D is not None:
                P = P + (D * defl_factor).astype(f32)

            def _flat_normal(Q):
                if nn == 4:
                    v1, v2 = Q[:, 2] - Q[:, 0], Q[:, 3] - Q[:, 1]
                else:
                    v1, v2 = Q[:, 1] - Q[:, 0], Q[:, 2] - Q[:, 0]
                nr = np.cross(v1, v2)
                ln = np.linalg.norm(nr, axis=1, keepdims=True)
                ok = ln > 1e-9
                return np.where(ok, nr / np.where(ok, ln, 1.0), np.array([0.0, 0.0, 1.0], dtype=f32)).astype(f32)

            flat_n = _flat_normal(P)
            if np.any(ins != 0.0):
                P = P + (flat_n[:, None, :] * ins[:, None, None]).astype(f32)

            fill = np.concatenate([rgb, np.full((E, 1), fo, dtype=f32)], axis=1)
            vcols = ccen = None
            if con is not None:
                dn = vec_contour_scalar(D, con['comp'], con['abs']) * con['f']
                ts = (dn - con['min']) / (con['max'] - con['min'])
                vcols = vec_contour_colormap(ts, con['alpha'])
                ccen = vec_contour_colormap(ts.mean(axis=1), con['alpha'])
            use_cen = vcols is not None and nn >= 4
            ni = [(i + 1) % nn for i in range(nn)]

            if not is_ext and nn == 3:
                tris.append((P, vcols if vcols is not None else np.repeat(fill[:, None, :], 3, axis=1)))
                continue

            if not is_ext:
                nv = nn + (1 if use_cen else 0)
                V = np.empty((E, nv, 3), dtype=f32); V[:, :nn] = P
                C = np.empty((E, nv, 4), dtype=f32)
                C[:, :nn] = vcols if vcols is not None else fill[:, None, :]
                N = np.broadcast_to(flat_n[:, None, :], (E, nv, 3))
                if use_cen:
                    V[:, nn] = P.mean(axis=1); C[:, nn] = ccen
                    local = np.array([[nn, i, ni[i]] for i in range(nn)], dtype=np.uint32)
                else:
                    local = np.array([[0, i, i + 1] for i in range(1, nn - 1)], dtype=np.uint32)
                base = (voff + np.arange(E, dtype=np.int64) * nv).astype(np.uint32)
                ff.append((base[:, None, None] + local[None]).reshape(-1, 3))
                ev.append(P[:, [j for i in range(nn) for j in (i, ni[i])]].reshape(-1, 3))
                ecl.append(np.broadcast_to(edge_c, (E * nn * 2, 4)))
                fv.append(V.reshape(-1, 3)); fcl.append(C.reshape(-1, 4)); fnl.append(N.reshape(-1, 3))
                voff += E * nv
                continue

            nrm = _flat_normal(P).astype(np.float64)
            off = (nrm * (thk / 2.0)[:, None])[:, None, :].astype(f32)
            top, bot = P + off, P - off
            nv = 2 * nn + (2 if use_cen else 0)
            V = np.empty((E, nv, 3), dtype=f32); V[:, :nn] = top; V[:, nn:2 * nn] = bot
            C = np.empty((E, nv, 4), dtype=f32)
            fcv = vcols if vcols is not None else fill[:, None, :]
            C[:, :nn] = fcv; C[:, nn:2 * nn] = fcv
            Nn = np.empty((E, nv, 3), dtype=f32)
            Nn[:, :nn] = nrm[:, None, :]; Nn[:, nn:2 * nn] = -nrm[:, None, :]
            if use_cen:
                V[:, 2 * nn] = top.mean(axis=1); V[:, 2 * nn + 1] = bot.mean(axis=1)
                C[:, 2 * nn] = ccen; C[:, 2 * nn + 1] = ccen
                Nn[:, 2 * nn] = nrm; Nn[:, 2 * nn + 1] = -nrm
                local = [[2 * nn, i, ni[i]] for i in range(nn)] + [[2 * nn + 1, nn + ni[i], nn + i] for i in range(nn)]
            else:
                local = [[0, i, i + 1] for i in range(1, nn - 1)] + [[nn, nn + i + 1, nn + i] for i in range(1, nn - 1)]
            for i in range(nn):
                local += [[i, nn + i, nn + ni[i]], [i, nn + ni[i], ni[i]]]
            local = np.array(local, dtype=np.uint32)
            base = (voff + np.arange(E, dtype=np.int64) * nv).astype(np.uint32)
            ff.append((base[:, None, None] + local[None]).reshape(-1, 3))
            segs = []
            for i in range(nn):
                segs += [top[:, i], top[:, ni[i]], bot[:, i], bot[:, ni[i]], top[:, i], bot[:, i]]
            ev.append(np.stack(segs, axis=1).reshape(-1, 3))
            ecl.append(np.broadcast_to(edge_c, (E * nn * 6, 4)))
            fv.append(V.reshape(-1, 3)); fcl.append(C.reshape(-1, 4)); fnl.append(Nn.reshape(-1, 3))
            voff += E * nv

        e3 = np.zeros((0, 3), dtype=f32)
        if tris:
            Pt = np.concatenate([t[0] for t in tris], axis=0)
            Ct = np.concatenate([t[1] for t in tris], axis=0)
            Nt = len(Pt)
            b_fv = Pt.reshape(-1, 3); b_fc = Ct.reshape(-1, 4)
            base = (np.arange(Nt, dtype=np.uint32) * 3) + np.uint32(voff)
            b_ff = np.stack([base, base + 1, base + 2], axis=1)
            p0, p1, p2 = Pt[:, 0], Pt[:, 1], Pt[:, 2]
            b_ev = Pt[:, [0, 1, 1, 2, 2, 0]].reshape(-1, 3)
            tn = np.cross(p1 - p0, p2 - p0)
            tl = np.linalg.norm(tn, axis=1, keepdims=True)
            okk = tl > 1e-9
            tn = np.where(okk, tn / np.where(okk, tl, 1.0), np.array([0.0, 0.0, 1.0], dtype=f32)).astype(f32)
            fv.append(b_fv); fcl.append(b_fc); ff.append(b_ff); fnl.append(np.repeat(tn, 3, axis=0))
            ev.append(b_ev); ecl.append(np.broadcast_to(edge_c, (Nt * 6, 4)))

        if not fv:
            em = np.array([], dtype=f32)
            all_fv = all_fc = all_fn = all_ev = all_ec = em
            all_ff = np.array([], dtype=np.uint32)
        else:
            all_fv = np.concatenate(fv, axis=0).astype(f32, copy=False)
            all_fc = np.concatenate(fcl, axis=0).astype(f32, copy=False)
            all_ff = np.concatenate(ff, axis=0).astype(np.uint32, copy=False)
            all_fn = np.concatenate(fnl, axis=0).astype(f32, copy=False)
            all_ev = np.concatenate(ev, axis=0).astype(f32, copy=False)
            all_ec = np.ascontiguousarray(np.concatenate(ecl, axis=0), dtype=f32)
        self._ghost_edge_buf = []
        return (all_fv, all_fc, all_ff, all_fn, all_ev, all_ec, [], [], [], [], [], 0)

    def _area_fast_builder(self, model, can_defl, is_extruded, face_opacity, edge_c, contour):
        """Returns a _build_pass-compatible callable or None when the scene isn't 'simple'."""
        try:
            if self.active_view_plane is not None:
                return None
            if self._view_overrides.get('area'):
                return None
            if getattr(self, 'show_tributary_heatmap', False):
                return None
            c = self._area_fast_geom(model)
            if c is None:
                return None
            if can_defl:
                self._area_fast_disp(c, model.results)
            elif contour is not None:
                return None
            ctx = dict(view_deflected=bool(getattr(self, 'view_deflected', False)), is_extruded=bool(is_extruded),
                       face_opacity=float(face_opacity), edge_c=edge_c, contour=contour)
            return lambda f: self._area_fast_pass(c, f, ctx)
        except Exception:
            import traceback; traceback.print_exc()
            return None

    def _update_area_vbo(self, model):
        if not hasattr(self, 'vbo_manager') or not self.vbo_manager.is_initialized:
            return

        _plane = self.active_view_plane
        _can_defl  = self._area_can_deflect(model)
        _anim_mode = bool(_can_defl and self.animation_manager.is_running
                          and not getattr(self, 'ltha_mode', False))
        _eff_scale = float(self.deflection_scale)
        _static_f  = (0.0 if _anim_mode else float(self.anim_factor)) if _can_defl else 0.0
        _contour_on = bool(_can_defl and getattr(self, 'contour_active', False))
        _new_key = (
            frozenset(model.area_elements.keys()),
            _can_defl, _anim_mode, _eff_scale, _static_f,
            _contour_on,
            (getattr(self, 'contour_component', None), bool(getattr(self, 'contour_absolute', False)),
             bool(getattr(self, 'contour_range_auto', True)),
             float(getattr(self, 'contour_min', 0.0)), float(getattr(self, 'contour_max', 1.0))) if _contour_on else None,
            id(getattr(model, 'results', None)) if _can_defl else None,
                                                                                  
            getattr(self, 'show_slabs',          True),
            getattr(self, 'view_extruded',        False),
            getattr(self, 'view_deflected',       False),
            getattr(self, 'show_tributary_loads', False),
            getattr(self, 'show_tributary_heatmap', False),
            (id(getattr(model, 'tributary_visuals', None))
             if getattr(self, 'show_tributary_heatmap', False) else None),
            _plane['axis']  if _plane else None,
            _plane['value'] if _plane else None,
            getattr(self, 'show_ghost_structure', True),
            float(self.display_config.get('slab_opacity',    0.45)),
            float(self.display_config.get('extrude_opacity', 0.65)),
            tuple(self.display_config.get('shell_edge_color',
                  self.display_config.get('edge_color', (0, 0, 0, 1)))),
        )
        if (not getattr(self, '_area_vbo_dirty', True) and
                getattr(self, '_area_vbo_key', None) == _new_key):
            self._rebuild_area_interior_lines()                                              
            return                          
        self._area_vbo_dirty = False
        self._area_vbo_key   = _new_key
                                                                                   
        if not getattr(self, 'show_slabs', True): 
            self.vbo_manager.upload_area_geometry(
                np.array([], dtype=np.float32), np.array([], dtype=np.float32), np.array([], dtype=np.uint32),
                np.array([], dtype=np.float32), np.array([], dtype=np.float32)
            )
            if hasattr(self, '_area_interior_lines'):
                self._area_interior_lines.setVisible(False)
            return

        is_extruded = getattr(self, 'view_extruded', False)

        face_opacity  = float(self.display_config.get("extrude_opacity", 0.65)) if is_extruded\
                        else float(self.display_config.get("slab_opacity", 0.45))
        ec_raw        = self.display_config.get("shell_edge_color", self.display_config.get("edge_color", (0, 0, 0, 1)))
        global_edge_c = list(ec_raw[:3]) + [1.0]                                      

        _color_cache = {}
        def _parse_hex(c_hex):
            if c_hex not in _color_cache:
                if isinstance(c_hex, str) and c_hex.startswith('#'):
                    h = c_hex.lstrip('#')
                    _color_cache[c_hex] = (int(h[0:2], 16) / 255.0, int(h[2:4], 16) / 255.0, int(h[4:6], 16) / 255.0)
                else:
                    _color_cache[c_hex] = (0.5, 0.5, 0.5)
            return _color_cache[c_hex]

        _no_plane = (self.active_view_plane is None)
        if not _no_plane:
            _ax, _val = self.active_view_plane['axis'], self.active_view_plane['value']
            _ghost_ok = getattr(self, 'show_ghost_structure', True)
            _vis_cache = {}
            def _vis(x, y, z):
                k = (x, y, z)
                if k not in _vis_cache:
                    cv = x if _ax == 'x' else (y if _ax == 'y' else z)
                    _vis_cache[k] = 2 if abs(cv - _val) < 0.005 else (1 if _ghost_ok else 0)
                return _vis_cache[k]
        else:
            def _vis(x, y, z): return 2

        if _contour_on:
            _disp_all = model.results.get("displacements", {})
            _c_min, _c_max = self._get_contour_range(_disp_all)
            _c_f = 1.0 if _anim_mode else _static_f                                      
            _c_alpha = max(face_opacity, 0.85)                                   
        def _node_colors(nodes):
            ts = []
            for n in nodes:
                r = _disp_all.get(str(n.id))
                sv = self._contour_scalar(r) * _c_f if r else 0.0
                ts.append((sv - _c_min) / (_c_max - _c_min))
            cols = [list(self._contour_colormap(t, alpha=_c_alpha)) for t in ts]
            cen = list(self._contour_colormap(sum(ts) / len(ts), alpha=_c_alpha))
            return cols, cen

        def _build_pass(defl_factor):
            tri_pts, tri_fc, tri_ec, tri_vc = [], [], [], []
            ghost_pts, ghost_fc = [], []
            ghost_edges = []                                                     

            fill_verts, fill_colors, fill_faces = [], [], []
            fill_normals = []
            edge_verts, edge_colors = [], []
            ghost_verts, ghost_faces, ghost_colors = [], [], []
            vert_offset, ghost_v_offset = 0, 0

            for aeid, ae in model.area_elements.items():
                if getattr(self, 'view_deflected', False):
                    if hasattr(ae.section, 'modeling_type') and ae.section.modeling_type == "Tributary Area":
                        continue
                nodes = ae.nodes
                n_count = len(nodes)
                if n_count < 3: continue

                min_state = min(min(_vis(n.x, n.y, n.z) for n in nodes), self._vo_state('area', aeid))
                if min_state == 0: continue

                r, g, b = _parse_hex(getattr(ae.section, 'display_color', '#808080'))
                pts = np.array([[n.x, n.y, n.z] for n in nodes], dtype=np.float32)
                pts = self._area_deflect_pts(model, nodes, pts, defl_factor)

                if n_count == 4:
                    _nv1, _nv2 = pts[2] - pts[0], pts[3] - pts[1]
                else:
                    _nv1, _nv2 = pts[1] - pts[0], pts[2] - pts[0]
                elem_flat_normal = np.cross(_nv1, _nv2)
                _en_len = np.linalg.norm(elem_flat_normal)
                elem_flat_normal = elem_flat_normal / _en_len if _en_len > 1e-9 else np.array([0.0, 0.0, 1.0], dtype=np.float32)
                _ins = getattr(ae, 'insertion_offset', 0.0)
                if _ins:
                    pts = pts + (elem_flat_normal * _ins).astype(pts.dtype)

                is_selected = hasattr(self, 'selected_area_ids') and aeid in self.selected_area_ids

                if min_state == 1:
                                                                                    
                    g_fill = [r, g, b, 0.15]
                    g_edge = [ec_raw[0], ec_raw[1], ec_raw[2], 0.35]
                    for pt in pts:
                        fill_verts.append(pt.tolist()); fill_colors.append(g_fill)
                        fill_normals.append(elem_flat_normal.tolist())
                    for i in range(1, n_count - 1):
                        fill_faces.append([vert_offset, vert_offset + i, vert_offset + i + 1])
                    for i in range(n_count):
                        edge_verts.extend([pts[i].tolist(), pts[(i + 1) % n_count].tolist()])
                        edge_colors.extend([g_edge, g_edge])
                    vert_offset += n_count
                    continue

                fill_color = [r, g, b, face_opacity]
                edge_c = global_edge_c
                vcols, ccen = (_node_colors(nodes) if _contour_on else (None, None))
                use_cen = vcols is not None and n_count >= 4                                              

                is_trib_area = hasattr(ae.section, 'modeling_type') and ae.section.modeling_type == "Tributary Area"
                heat_data = None
                if is_trib_area and getattr(self, 'show_tributary_heatmap', False) and not is_extruded:
                    trib_viz = getattr(model, 'tributary_visuals', None)
                    if trib_viz:
                        heat_data = trib_viz.get('heatmap', {}).get(aeid)

                if heat_data is not None and heat_data['faces'].size > 0:
                    hv, hc, hf = heat_data['verts'], heat_data['colors'], heat_data['faces']
                    for pt in hv:
                        fill_verts.append(pt.tolist())
                    fill_colors.extend(hc.tolist())
                    fill_normals.extend([elem_flat_normal.tolist()] * len(hv))
                    fill_faces.extend((hf + vert_offset).tolist())
                    vert_offset += len(hv)
                    for i in range(n_count):
                        ni = (i + 1) % n_count
                        edge_verts.extend([pts[i].tolist(), pts[ni].tolist()])
                        edge_colors.extend([edge_c, edge_c])
                    continue
                                           
                if not is_extruded and n_count == 3:                            
                    tri_pts.append(pts); tri_fc.append(fill_color); tri_ec.append(edge_c)
                    if vcols is not None: tri_vc.append(vcols)
                elif not is_extruded:                        
                    for k, pt in enumerate(pts):
                        fill_verts.append(pt.tolist()); fill_colors.append(vcols[k] if vcols is not None else fill_color)
                        fill_normals.append(elem_flat_normal.tolist())
                    if use_cen:
                        fill_verts.append(pts.mean(axis=0).tolist()); fill_colors.append(ccen)
                        fill_normals.append(elem_flat_normal.tolist())
                        for i in range(n_count):
                            fill_faces.append([vert_offset + n_count, vert_offset + i, vert_offset + (i + 1) % n_count])
                    else:
                        for i in range(1, n_count - 1):
                            fill_faces.append([vert_offset, vert_offset + i, vert_offset + i + 1])
                    for i in range(n_count):
                        ni = (i + 1) % n_count
                        edge_verts.extend([pts[i].tolist(), pts[ni].tolist()])
                        edge_colors.extend([edge_c, edge_c])
                    vert_offset += n_count + (1 if use_cen else 0)
                else:                       
                    t = getattr(ae.section, 'membrane_thickness', getattr(ae.section, 'thickness', 0.2))
                    if n_count == 4: v1, v2 = pts[2] - pts[0], pts[3] - pts[1]
                    else: v1, v2 = pts[1] - pts[0], pts[2] - pts[0]
                
                    normal = np.cross(v1, v2)
                    nlen = np.linalg.norm(normal)
                    normal = normal / nlen if nlen > 1e-9 else np.array([0, 0, 1.0])
                    offset = normal * (t / 2.0)
                    top_pts, bot_pts = pts + offset, pts - offset

                    for k, pt in enumerate(top_pts): fill_verts.append(pt.tolist()); fill_colors.append(vcols[k] if vcols is not None else fill_color); fill_normals.append(normal.tolist())
                    for k, pt in enumerate(bot_pts): fill_verts.append(pt.tolist()); fill_colors.append(vcols[k] if vcols is not None else fill_color); fill_normals.append((-normal).tolist())
                    b_off = vert_offset + n_count
                    if use_cen:
                        tc, bc = vert_offset + 2 * n_count, vert_offset + 2 * n_count + 1
                        fill_verts.append(top_pts.mean(axis=0).tolist()); fill_colors.append(ccen); fill_normals.append(normal.tolist())
                        fill_verts.append(bot_pts.mean(axis=0).tolist()); fill_colors.append(ccen); fill_normals.append((-normal).tolist())
                        for i in range(n_count):
                            ni = (i + 1) % n_count
                            fill_faces.append([tc, vert_offset + i, vert_offset + ni])
                            fill_faces.append([bc, b_off + ni, b_off + i])
                    else:
                        for i in range(1, n_count - 1): fill_faces.append([vert_offset, vert_offset + i, vert_offset + i + 1])
                        for i in range(1, n_count - 1): fill_faces.append([b_off, b_off + i + 1, b_off + i])
                    for i in range(n_count):
                        ni = (i + 1) % n_count
                        t1, t2 = vert_offset + i, vert_offset + ni
                        b1, b2 = b_off + i, b_off + ni
                        fill_faces.extend([[t1, b1, b2], [t1, b2, t2]])
                        edge_verts.extend([top_pts[i].tolist(), top_pts[ni].tolist(), bot_pts[i].tolist(), bot_pts[ni].tolist(), top_pts[i].tolist(), bot_pts[i].tolist()])
                        edge_colors.extend([edge_c] * 6)
                    vert_offset += 2 * n_count + (2 if use_cen else 0)

            N_tri = len(tri_pts)
            if N_tri > 0:
                b_fv = np.concatenate(tri_pts, axis=0)
                if tri_vc:
                    b_fc = np.array(tri_vc, dtype=np.float32).reshape(-1, 4)
                else:
                    b_fc = np.repeat(np.array(tri_fc, dtype=np.float32), 3, axis=0)
                base = (np.arange(N_tri, dtype=np.uint32) * 3) + vert_offset
                b_ff = np.stack([base, base + 1, base + 2], axis=1)

                p0, p1, p2 = b_fv[0::3], b_fv[1::3], b_fv[2::3]
                b_ev = np.empty((N_tri * 6, 3), dtype=np.float32)
                b_ev[0::6], b_ev[1::6] = p0, p1
                b_ev[2::6], b_ev[3::6] = p1, p2
                b_ev[4::6], b_ev[5::6] = p2, p0
                b_ec = np.repeat(np.array(tri_ec, dtype=np.float32), 6, axis=0)

                tri_n = np.cross(p1 - p0, p2 - p0)
                tri_n_len = np.linalg.norm(tri_n, axis=1, keepdims=True)
                tri_n = np.where(tri_n_len > 1e-9, tri_n / np.where(tri_n_len > 1e-9, tri_n_len, 1.0), np.array([0.0, 0.0, 1.0], dtype=np.float32))
                b_fn = np.repeat(tri_n, 3, axis=0)

                if fill_verts:
                    all_fv = np.concatenate([np.array(fill_verts, dtype=np.float32), b_fv], axis=0)
                    all_fc = np.concatenate([np.array(fill_colors, dtype=np.float32), b_fc], axis=0)
                    all_ff = np.concatenate([np.array(fill_faces, dtype=np.uint32), b_ff], axis=0)
                    all_fn = np.concatenate([np.array(fill_normals, dtype=np.float32), b_fn], axis=0)
                    all_ev = np.concatenate([np.array(edge_verts, dtype=np.float32), b_ev], axis=0)
                    all_ec = np.concatenate([np.array(edge_colors, dtype=np.float32), b_ec], axis=0)
                else:
                    all_fv, all_fc, all_ff, all_fn, all_ev, all_ec = b_fv, b_fc, b_ff, b_fn, b_ev, b_ec
            else:
                all_fv = np.array(fill_verts, dtype=np.float32).reshape(-1, 3) if fill_verts else np.array([], dtype=np.float32)
                all_fc = np.array(fill_colors, dtype=np.float32).reshape(-1, 4) if fill_colors else np.array([], dtype=np.float32)
                all_ff = np.array(fill_faces, dtype=np.uint32).reshape(-1, 3) if fill_faces else np.array([], dtype=np.uint32)
                all_fn = np.array(fill_normals, dtype=np.float32).reshape(-1, 3) if fill_normals else np.array([], dtype=np.float32)
                all_ev = np.array(edge_verts, dtype=np.float32).reshape(-1, 3) if edge_verts else np.array([], dtype=np.float32)
                all_ec = np.array(edge_colors, dtype=np.float32).reshape(-1, 4) if edge_colors else np.array([], dtype=np.float32)

            self._ghost_edge_buf = ghost_edges
            return (all_fv, all_fc, all_ff, all_fn, all_ev, all_ec,
                    ghost_pts, ghost_fc, ghost_verts, ghost_colors, ghost_faces, ghost_v_offset)

        _fast_contour = None
        if _contour_on:
            _fast_contour = dict(comp=getattr(self, 'contour_component', 'Resultant'),
                                 abs=bool(getattr(self, 'contour_absolute', False)),
                                 min=_c_min, max=_c_max, f=_c_f, alpha=_c_alpha)
        _fast = self._area_fast_builder(model, _can_defl, is_extruded, face_opacity, global_edge_c, _fast_contour)
        if _fast is not None:
            _build_pass = _fast

        fill_disp = edge_disp = None
        if _anim_mode:
                                                                                   
            _rest = _build_pass(0.0)
            _peak = _build_pass(_eff_scale)
            (all_fv, all_fc, all_ff, all_fn, all_ev, all_ec,
             ghost_pts, ghost_fc, ghost_verts, ghost_colors, ghost_faces, ghost_v_offset) = _rest
            if _peak[0].shape == all_fv.shape and all_fv.size:
                fill_disp = (_peak[0] - all_fv).astype(np.float32)
            if _peak[4].shape == all_ev.shape and all_ev.size:
                edge_disp = (_peak[4] - all_ev).astype(np.float32)
        else:
                                                                             
            (all_fv, all_fc, all_ff, all_fn, all_ev, all_ec,
             ghost_pts, ghost_fc, ghost_verts, ghost_colors, ghost_faces, ghost_v_offset) =\
                _build_pass(_eff_scale * _static_f if _can_defl else 0.0)

        if hasattr(self, '_area_ghost_items'):
            for item in self._area_ghost_items:
                try:
                    self.removeItem(item)
                    if item in self.element_items:
                        self.element_items.remove(item)
                except Exception:
                    pass
        self._area_ghost_items = []

        N_gh = len(ghost_pts)
        if N_gh > 0:
            b_gv = np.concatenate(ghost_pts, axis=0)
            b_gc = np.repeat(np.array(ghost_fc, dtype=np.float32), 3, axis=0)
            base_g = (np.arange(N_gh, dtype=np.int32) * 3) + ghost_v_offset
            b_gf = np.stack([base_g, base_g + 1, base_g + 2], axis=1)

            gv = np.concatenate([np.array(ghost_verts, dtype=np.float32), b_gv], axis=0) if ghost_verts else b_gv
            gc = np.concatenate([np.array(ghost_colors, dtype=np.float32), b_gc], axis=0) if ghost_colors else b_gc
            gf = np.concatenate([np.array(ghost_faces, dtype=np.int32), b_gf], axis=0) if ghost_faces else b_gf
        else:
            gv = np.array(ghost_verts, dtype=np.float32) if ghost_verts else None
            gc = np.array(ghost_colors, dtype=np.float32) if ghost_colors else None
            gf = np.array(ghost_faces, dtype=np.int32) if ghost_faces else None

        if gv is not None and gv.size > 0:
            ghost_mesh = gl.GLMeshItem(vertexes=gv, faces=gf, vertexColors=gc, smooth=False, glOptions='translucent')
            self.addItem(ghost_mesh)
            self.element_items.append(ghost_mesh)
            self._area_ghost_items.append(ghost_mesh)

        _ge = getattr(self, '_ghost_edge_buf', None)
        if _ge:
            ec = self.display_config.get("shell_edge_color", self.display_config.get("edge_color", (0, 0, 0, 1)))
            ghost_outline = gl.GLLinePlotItem(
                pos=np.array(_ge, dtype=np.float32),
                color=(ec[0], ec[1], ec[2], 0.35), width=1.0,
                mode='lines', antialias=True)
            ghost_outline.setGLOptions('translucent')
            self.addItem(ghost_outline)
            self.element_items.append(ghost_outline)
            self._area_ghost_items.append(ghost_outline)

        if all_fv.size > 0 or all_ev.size > 0:
            self.vbo_manager.upload_area_geometry(all_fv, all_fc, all_ff, all_ev, all_ec,
                                                  fill_displacements=fill_disp, edge_displacements=edge_disp,
                                                  fill_normals=all_fn if all_fn.size else None)
        else:
            self.vbo_manager.upload_area_geometry(
                np.array([], dtype=np.float32), np.array([], dtype=np.float32), np.array([], dtype=np.uint32),
                np.array([], dtype=np.float32), np.array([], dtype=np.float32)
            )

        self._rebuild_area_interior_lines()

    def clear_hover_popup(self):
        self.current_hover_data = None
        self.hovered_node_id = None
        self.hovered_elem_id = None
        self.hovered_area_id = None
        self.hovered_tendon_id = None
        self.update()

    def _force_draw_model(self, model, sel_elems=None, sel_nodes=None, progress=None):
        """
        Force redraw the model even if animation is running.
        Used internally by draw_model when animation is stopped.
        """
        def _p(msg):
            if progress: progress(msg)

        _p("Initializing OpenGL render context...")
        model = self._resolve_draw_model(model)
        self.current_model = model
        if not getattr(self, '_deform_toggle', False):
                                                                           
            self._zoom_coord_cache = None
            self._bbox_cache = None
            self._area_geom_cache = None
            self._undef_frames = None
            self._sgpu_key = None
            self._sgpu_mode = None
            self._boundary_node_cache = None

        _p("Allocating GPU memory pools for structural data...")
        _p("Compiling core vertex and fragment shader programs...")
        _p("Establishing global lighting and material states...")

        if sel_elems is not None: self.selected_element_ids = sel_elems
        if sel_nodes is not None: self.selected_node_ids = sel_nodes
        self._sync_selection_to_model(model)
        self._loads_dirty = True                                           
        self.load_labels = []

        _p("Flushing legacy OpenGL buffers and geometry caches...")
        self.node_items.clear()
        self._support_items.clear()                                                                
        self._support_positions = {'fixed': [], 'pinned': [], 'roller': [], 'custom': []}
        self.element_items.clear()     
        self.element_items.clear()

        self.grid_labels = [] 
        if hasattr(self, 'static_items'): self.static_items.clear()
        self._pending_static_line_pos = []
        self._pending_static_line_colors = []
        self._pending_bubble_line_pos = []
        self._pending_bubble_line_colors = []
        self._pending_grid_a_pos, self._pending_grid_a_col = [], []
        self._pending_grid_b_pos, self._pending_grid_b_col = [], []
        self._bubble_split = 0

        if hasattr(self, 'load_items'): self.load_items.clear()

        self.invalidate_deflection_cache()

        _preserve = {self.force_mesh_item, self.force_line_item}
        for item in self.items[:]:
            if item not in _preserve:
                self.removeItem(item)

        if not self.view_deflected and self.show_grid:
            _p("Generating spatial reference grids...")
            self._draw_reference_grids(model)

        if self.show_joints or self.show_supports:
            _p("Building joint & support meshes...")
            self._draw_nodes(model)
        
        in_analysis_mode = hasattr(model, 'has_results') and model.has_results

        if self.show_constraints and not in_analysis_mode:
            _p("Rendering rigid diaphragm links...")
            self._draw_constraints(model)

        _p("Configuring depth buffers and hardware multisampling (MSAA)...")
        _gpu_frames = self._static_gpu_frames(model)
        if self.view_extruded:
            _p("Extruding 3D frame elements to VBO...")
            if not _gpu_frames:
                self._draw_elements_extruded(model)
                if not self.view_deflected:
                    self._store_undeformed_frames(model)
            self._draw_tendons_extruded(model)
            self._draw_cables_extruded(model)
        else:
            _p("Generating wireframe elements...")
            if not _gpu_frames:
                self._draw_elements_wireframe(model)
                if not self.view_deflected:
                    self._store_undeformed_frames(model)
            self._draw_tendons_wireframe(model)
            self._draw_cables_wireframe(model)

        if (self.show_loads and not in_analysis_mode) or self.show_hinges:
            _p("Generating applied load geometries...")
            self._load_view_geometry = None
            self._pending_load_fill_verts = []
            self._pending_load_fill_colors = []
            self._pending_load_fill_faces = []
            self._pending_load_line_pos = []
            self._pending_load_line_colors = []
            if self.show_loads and not in_analysis_mode:
                self._draw_loads(model)
                self._draw_member_point_loads(model)
                self._draw_cable_loads(model)
            if self.show_hinges:
                self._draw_frame_hinges(model)
            if self.show_loads and not in_analysis_mode:
                self._draw_member_loads(model)
                self._draw_area_loads(model)
            _p("Pushing load buffers to GPU...")
            self._upload_loads_to_vbo()
            self._upload_load_labels_to_gpu() 
        elif self.reaction_diagram_active and in_analysis_mode and self.reaction_data:
            self._load_view_geometry = None
            self._pending_load_fill_verts = []
            self._pending_load_fill_colors = []
            self._pending_load_fill_faces = []
            self._pending_load_line_pos = []
            self._pending_load_line_colors = []
            self._draw_reactions(model)
            self._upload_loads_to_vbo()
            _p("Baking SDF text labels...")
            self._upload_load_labels_to_gpu()
        else:
            self.vbo_manager.clear_load_geometry()
                                                                                                         
            self._upload_load_labels_to_gpu()

        self._loads_dirty = False

        self._area_vbo_dirty = True
        self._area_ghost_items = []

        if self.show_slabs:
            _p("Triangulating shell/area VBOs...")
            self._draw_slabs(model)
            self._update_area_vbo(model)

        if self.show_local_axes:
            _p("Generating local coordinate triads...")
            self._draw_local_axes(model)

        _p("Pushing static overlay geometry to GPU...")
        self._upload_static_geometry()

        _p("Finalizing viewport overlay...")
        
        if self.snap_ring not in self.items: self.addItem(self.snap_ring)
        if self.snap_dot not in self.items: self.addItem(self.snap_dot)
        if self.inspection_dot not in self.items: self.addItem(self.inspection_dot)              
        if self.preview_line not in self.items: self.addItem(self.preview_line)
        if self._area_preview_line not in self.items: self.addItem(self._area_preview_line)
        if self._area_interior_lines not in self.items: self.addItem(self._area_interior_lines)
        if self._brace_prev_x1 not in self.items: self.addItem(self._brace_prev_x1)
        if self._brace_prev_x2 not in self.items: self.addItem(self._brace_prev_x2)
        if self._brace_prev_border not in self.items: self.addItem(self._brace_prev_border)
        if self._quick_area_prev_border not in self.items: self.addItem(self._quick_area_prev_border)
        if self._quick_area_prev_fill not in self.items: self.addItem(self._quick_area_prev_fill)
        if self._beam_col_prev_line not in self.items: self.addItem(self._beam_col_prev_line)

        self.snap_ring.setGLOptions('translucent')
        self.snap_dot.setGLOptions('translucent')

        self._sel_overlay_items = []
        self._rebuild_selection_overlay()

        if model.nodes:                                                                
            center, diag, _ = self.compute_model_bbox(model)
            self.camera.set_model_scale(max(diag, 0.001))
            
            current_dist = self.opts.get('distance', 0)
            if current_dist <= 0:
                needed_dist = self._fit_distance(diag, self.opts.get('fov', 60))
                self.opts['center'] = center
                self.camera.animate_to(target_center=center, target_dist=needed_dist)

        self.refresh_deformed_playback()

    def update_selection_overlay(self, sel_elems, sel_nodes, sel_areas=None, sel_links=None, sel_tendons=None, progress=None):

        def _p(msg):
            if progress: progress(msg)

        if not hasattr(self, 'current_model') or self.current_model is None:
            return
                   
        """Fast-path selection update. Skips full geometry rebuild."""
        self.selected_element_ids = list(sel_elems) if sel_elems is not None else []
        self.selected_node_ids    = list(sel_nodes)  if sel_nodes  is not None else []
        self.selected_area_ids    = list(sel_areas)  if sel_areas  is not None else []
        self.selected_link_ids    = list(sel_links)  if sel_links  is not None else []
        self.selected_tendon_ids  = list(sel_tendons) if sel_tendons is not None else []
        self._sync_selection_to_model(self.current_model)
        current_model = self.current_model
        in_analysis_mode = hasattr(current_model, 'has_results') and current_model.has_results if current_model else False
        
        for item in self._sel_overlay_items:
            try:
                self.removeItem(item)
            except Exception:
                pass
        self._sel_overlay_items = []

        if not hasattr(self, 'load_items'): self.load_items = []
        for item in self.load_items:
            try: self.removeItem(item)
            except Exception: pass
        self.load_items.clear()

        self.load_labels.clear()
        if hasattr(self, 'show_loads'):
            self.load_labels = []
            if (self.show_loads and not in_analysis_mode) or self.show_hinges:
                self._load_view_geometry = None
                self._pending_load_fill_verts = []
                self._pending_load_fill_colors = []
                self._pending_load_fill_faces = []
                self._pending_load_line_pos = []
                self._pending_load_line_colors = []
                if self.show_loads and not in_analysis_mode:
                    self._draw_loads(self.current_model)
                    self._draw_member_point_loads(self.current_model)
                    self._draw_cable_loads(self.current_model)
                if self.show_hinges:
                    self._draw_frame_hinges(self.current_model)
                if self.show_loads and not in_analysis_mode:
                    self._draw_member_loads(self.current_model)
                    self._draw_area_loads(self.current_model)
                
                self._upload_loads_to_vbo()
                self._loads_dirty = False

                self._upload_load_labels_to_gpu()
            elif self.reaction_diagram_active and in_analysis_mode and self.reaction_data:
                self._load_view_geometry = None
                self._pending_load_fill_verts = []
                self._pending_load_fill_colors = []
                self._pending_load_fill_faces = []
                self._pending_load_line_pos = []
                self._pending_load_line_colors = []
                self._draw_reactions(current_model)
                _p("Pushing load buffers to GPU...")
                self._upload_loads_to_vbo()
                _p("Binding SDF font texture atlas to GPU pipelines...")
                self._upload_load_labels_to_gpu()
            
            else:
                self.vbo_manager.clear_load_geometry()
                self._upload_load_labels_to_gpu()

        self._update_area_vbo(self.current_model)
        self._rebuild_selection_overlay()
        self.update()

    def _get_active_displacements(self):
        """
        Returns (lookup_fn, is_ltha) where lookup_fn(nid) -> [dx,dy,dz,rx,ry,rz]
        or None.

        Selection overlays used to always read model.results["displacements"]
        -- the static peak/envelope -- even while an LTHA history was loaded
        and playing/paused at some other timestep. That's a different data
        source than the one driving the vibrating ghost structure itself
        (ltha_tensor, sliced at ltha_current_step), so a selection made
        mid-playback or while paused would render at the peak position
        instead of the actual current timestep.

        NOTE: this deliberately does NOT key off self.ltha_mode. ltha_mode
        just means "an LTHA history is loaded in memory" -- it stays True
        forever once playback has started, even after the results dialog
        switches its case combo over to a static envelope/mode shape. What
        we actually need here is "is the thing on screen right now the live
        timestep or a static case", which is a different question -- that's
        what self._selection_ltha_live tracks, set explicitly by whoever
        owns the results-case combo (see set_selection_ltha_live()).

        This only ever gets called for however many nodes/elements are
        selected (selection changes, not every playback frame), so there's
        no need to vectorize or cache across the whole model -- a plain
        per-node dict/tensor lookup is already effectively instant regardless
        of structure size.
        """
        ltha_active = (getattr(self, '_selection_ltha_live', False)
                       and getattr(self, 'ltha_tensor', None) is not None
                       and getattr(self, 'ltha_node_map', None) is not None)

        if ltha_active:
            t = getattr(self, 'ltha_current_step', 0)
            node_map = self.ltha_node_map
            tensor = self.ltha_tensor

            def lookup(nid):
                idx = node_map.get(str(nid))
                if idx is None:
                    return None
                return tensor[idx, t, :]

            return lookup, True

        model = self.current_model
        disp_dict = (model.results.get("displacements", {})
                     if (model is not None and getattr(model, 'results', None)) else {})

        def lookup(nid):
            return disp_dict.get(str(nid))

        return lookup, False

    def set_selection_ltha_live(self, active):
        """
        Called by whoever owns the results-case combo (e.g.
        NodeResultsDialog.on_case_changed) whenever the displayed case
        switches between the live LTHA timestep and a static case
        (envelope, modal, buckling). Tells _get_active_displacements()
        which source selection overlays should actually read from right
        now -- independent of whether ltha_mode (an LTHA history being
        loaded at all) happens to still be True.
        """
        self._selection_ltha_live = bool(active)
        self._rebuild_selection_overlay()
        self.update()

    def _rebuild_selection_overlay(self):
        """Dispatches to wireframe or extruded overlay builder, then nodes."""
        self._dash_anim = []
        if self.view_extruded:
            self._rebuild_extruded_selection_overlay()
        else:
            self._rebuild_wireframe_selection_overlay()
        self._rebuild_node_selection_overlay()
        self._rebuild_link_selection_overlay()
        self._rebuild_tendon_selection_overlay()   
        self._rebuild_cable_selection_overlay()             

    def _rebuild_tendon_selection_overlay(self):
        if not getattr(self, 'selected_tendon_ids', None) or not self.current_model: return
        model = self.current_model
        tendons = getattr(model, 'tendons', {})
        if not tendons: return

        dash_acc = []
        for tid in self.selected_tendon_ids:
            if tid not in tendons or self._vo_state('tendon', tid) != 2: continue
            tendon = tendons[tid]
            pts = self._get_tendon_world_points(tendon)
            if pts is None or len(pts) < 2: continue
            dash_acc.append(self._polyline_segments(pts))
        self._add_dash_overlay(dash_acc, width=3.5)

    def _rebuild_cable_selection_overlay(self):
        if not getattr(self, 'selected_cable_ids', None) or not self.current_model: return
        cables = getattr(self.current_model, 'cables', {})
        if not cables: return

        dash_acc = []
        for cid in self.selected_cable_ids:
            if cid not in cables or self._vo_state('cable', cid) != 2: continue
            cable = cables[cid]
            pts = self._get_cable_world_points(cable)
            if pts is None or len(pts) < 2: continue
            dash_acc.append(self._polyline_segments(pts))
        self._add_dash_overlay(dash_acc, width=3.5)

    def _rebuild_link_selection_overlay(self):
        if not getattr(self, 'selected_link_ids', None) or not self.current_model: return
        model = self.current_model
        sel_color = np.array([1.0, 1.0, 0.0, 1.0])
        sel_pos = []

        if not hasattr(model, 'links'): return

        for lid in self.selected_link_ids:
            if lid not in model.links or self._vo_state('link', lid) != 2: continue
            nodes = model.links[lid]['nodes']

            if len(nodes) == 2:
                n0, n1 = nodes[0], nodes[1]
                                                      
                nd1 = model.nodes.get(n0) or model.nodes.get(int(n0)) or model.nodes.get(str(n0))
                nd2 = model.nodes.get(n1) or model.nodes.get(int(n1)) or model.nodes.get(str(n1))
                if not nd1 or not nd2: continue
                if min(self._get_visibility_state(nd1.x, nd1.y, nd1.z), self._get_visibility_state(nd2.x, nd2.y, nd2.z)) != 2:
                    continue
                sel_pos.extend([[nd1.x, nd1.y, nd1.z], [nd2.x, nd2.y, nd2.z]])

        if sel_pos:
            item = gl.GLLinePlotItem(pos=np.array(sel_pos), color=sel_color, mode='lines', width=4.0, antialias=True)
            item.setGLOptions({'glEnable': (GL_BLEND,), 'glBlendFunc': (GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA), 'glDisable': (GL_DEPTH_TEST,)})
            self.addItem(item)
            self._sel_overlay_items.append(item)

    def _rebuild_wireframe_selection_overlay(self):
        if not self.selected_element_ids or not self.current_model:
            return
        model = self.current_model
        sel_color = np.array([1.0, 1.0, 0.0, 1.0])
        width = self.display_config.get("line_width", 2.0)

        lookup, is_ltha = self._get_active_displacements()

        can_deflect = (self.view_deflected and
                       (is_ltha or (hasattr(model, 'has_results') and
                                    model.has_results and
                                    model.results is not None)))

        if can_deflect:
            dash_acc = []
            solid_pos = []
            for eid in self.selected_element_ids:
                if eid not in model.elements:
                    continue
                el = model.elements[eid]
                n1, n2 = el.node_i, el.node_j

                if min(self._end_states('frame', el, eid)) != 2:
                    continue

                p1 = np.array([n1.x, n1.y, n1.z])
                p2 = np.array([n2.x, n2.y, n2.z])
                
                res_i = lookup(n1.id)
                res_j = lookup(n2.id)
                
                if res_i is not None and res_j is not None:
                    v1_orig, v2_orig, v3_orig = self._get_consistent_axes(el)

                    if is_ltha:
                                                                           
                        curve_data_full = get_deflected_shape(
                            [n1.x, n1.y, n1.z], [n2.x, n2.y, n2.z],
                            res_i, res_j, v1_orig, v2_orig, v3_orig,
                            scale=self.deflection_scale, num_points=11
                        )
                        curve_pts = np.array([cd[0] for cd in curve_data_full], dtype=np.float64)
                    else:
                        if eid not in self.deflection_cache:
                            curve_data = get_deflected_shape(
                                [n1.x, n1.y, n1.z], [n2.x, n2.y, n2.z],
                                res_i, res_j, v1_orig, v2_orig, v3_orig,
                                scale=self.deflection_scale, num_points=11
                            )
                            self.deflection_cache[eid] = {
                                'curve_data': curve_data,
                                'p1_orig': p1.copy(),
                                'p2_orig': p2.copy()
                            }

                        cached = self.deflection_cache[eid]
                        curve_data_full = cached['curve_data']
                        p1_orig = cached['p1_orig']
                        p2_orig = cached['p2_orig']

                        p1_flex, p2_flex = p1_orig, p2_orig

                        K = len(curve_data_full)
                        pos_full_arr = np.array([cd[0] for cd in curve_data_full], dtype=np.float64)
                        s_arr = (np.arange(K) / (K - 1))[:, None] if K > 1 else np.zeros((K, 1))
                        pos_orig_arr = p1_flex + s_arr * (p2_flex - p1_flex)
                        curve_pts = pos_orig_arr + (pos_full_arr - pos_orig_arr) * self.anim_factor

                    dash_acc.append(self._polyline_segments(curve_pts))
                else:
                    solid_pos.extend([p1, p2])

            self._add_dash_overlay(dash_acc, width=1.5)
            if solid_pos:
                item = gl.GLLinePlotItem(
                    pos=np.array(solid_pos),
                    color=np.tile(sel_color, (len(solid_pos), 1)),
                    mode='lines', width=2.0, antialias=True
                )
                item.setGLOptions({
                    'glEnable': (GL_BLEND,),
                    'glBlendFunc': (GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA),
                    'glDisable': (GL_DEPTH_TEST,)
                })
                self.addItem(item)
                self._sel_overlay_items.append(item)
            return

        sel_pos = []
        sel_colors = [] 

        for eid in self.selected_element_ids:
            if eid not in model.elements:
                continue
            el = model.elements[eid]
            n1, n2 = el.node_i, el.node_j

            if min(self._end_states('frame', el, eid)) != 2:
                continue

            p1 = np.array([n1.x, n1.y, n1.z])
            p2 = np.array([n2.x, n2.y, n2.z])
            off_i = getattr(el, 'end_offset_i', 0.0)
            off_j = getattr(el, 'end_offset_j', 0.0)
            vec = p2 - p1
            length = np.linalg.norm(vec)
            p1_flex, p2_flex = p1, p2
            if length > 0.001 and (off_i > 0 or off_j > 0):
                u = vec / length
                if off_i + off_j >= length:
                    scale = (length / (off_i + off_j)) * 0.99
                    p1_flex = p1 + (u * off_i * scale)
                    p2_flex = p2 - (u * off_j * scale)
                else:
                    p1_flex = p1 + (u * off_i)
                    p2_flex = p2 - (u * off_j)
            
            sel_pos.extend([p1_flex, p2_flex])
            sel_colors.extend([sel_color, sel_color]) 
            
        if sel_pos:                                          
            _arr = np.asarray(sel_pos, dtype=np.float64)
            _P1, _P2 = _arr[0::2], _arr[1::2]
            self._add_dash_overlay([(_P1, _P2, np.zeros(len(_P1)))], width=1.2)

    def _rebuild_extruded_selection_overlay(self):
        if not self.selected_element_ids or not self.current_model:
            return
        model = self.current_model
        color_sel = np.array([1.0, 1.0, 0.0, 1.0])

        lookup, is_ltha = self._get_active_displacements()

        can_deflect = (self.view_deflected and
                       (is_ltha or (hasattr(model, 'has_results') and
                                    model.has_results and
                                    model.results is not None)))

        dash_acc = []

        for eid in self.selected_element_ids:
            if eid not in model.elements:
                continue
            el = model.elements[eid]
            n1, n2 = el.node_i, el.node_j

            if min(self._end_states('frame', el, eid)) != 2:
                continue

            p1 = np.array([n1.x, n1.y, n1.z])
            p2 = np.array([n2.x, n2.y, n2.z])

            if can_deflect:
                                       
                res_i = lookup(n1.id)
                res_j = lookup(n2.id)

                if res_i is not None and res_j is not None:
                    v1_orig, v2_orig, v3_orig = self._get_consistent_axes(el)

                    if is_ltha:
                                                                    
                        curve_data_full = get_deflected_shape(
                            [n1.x, n1.y, n1.z], [n2.x, n2.y, n2.z],
                            res_i, res_j, v1_orig, v2_orig, v3_orig,
                            scale=self.deflection_scale, num_points=11
                        )
                        curve_pts = np.array([cd[0] for cd in curve_data_full], dtype=np.float64)
                    else:
                        if eid not in self.deflection_cache:
                            off_i = getattr(el, 'end_offset_i', 0.0)
                            off_j = getattr(el, 'end_offset_j', 0.0)

                            curve_data = get_deflected_shape(
                                [n1.x, n1.y, n1.z], [n2.x, n2.y, n2.z],
                                res_i, res_j, v1_orig, v2_orig, v3_orig,
                                scale=self.deflection_scale, num_points=11
                            )
                            self.deflection_cache[eid] = {
                                'curve_data': curve_data,
                                'p1_orig': p1.copy(),
                                'p2_orig': p2.copy()
                            }

                        cached = self.deflection_cache[eid]
                        curve_data_full = cached['curve_data']
                        p1_orig = cached['p1_orig']
                        p2_orig = cached['p2_orig']

                        p1_flex, p2_flex = p1_orig, p2_orig

                        K = len(curve_data_full)
                        pos_full_arr = np.array([cd[0] for cd in curve_data_full], dtype=np.float64)
                        s_arr = (np.arange(K) / (K - 1))[:, None] if K > 1 else np.zeros((K, 1))
                        pos_orig_arr = p1_flex + s_arr * (p2_flex - p1_flex)
                        curve_pts = pos_orig_arr + (pos_full_arr - pos_orig_arr) * self.anim_factor

                    dash_acc.append(self._polyline_segments(curve_pts))
                    continue

                factor = 1.0 if is_ltha else self.anim_factor
                if res_i is not None:
                    p1 = p1 + np.array(res_i[:3]) * self.deflection_scale * factor
                if res_j is not None:
                    p2 = p2 + np.array(res_j[:3]) * self.deflection_scale * factor

            dash_acc.append((np.asarray(p1, dtype=np.float64)[None, :],
                             np.asarray(p2, dtype=np.float64)[None, :],
                             np.zeros(1)))

        self._add_dash_overlay(dash_acc, width=1.8)

    def _rebuild_node_selection_overlay(self):
        if not self.selected_node_ids or not self.current_model:
            return
        model = self.current_model
        size = self.display_config.get("node_size", 6)

        lookup, is_ltha = self._get_active_displacements()

        can_deflect = (self.view_deflected and
                       (is_ltha or (hasattr(model, 'has_results') and
                                    model.has_results and
                                    model.results is not None)))

        sel_pos = []
        for nid in self.selected_node_ids:
            if nid not in model.nodes:
                continue
            n = model.nodes[nid]

            if self._node_vis(n) != 2:
                continue

            nx, ny, nz = n.x, n.y, n.z
            if can_deflect:
                disp = lookup(nid)
                if disp is not None:
                    factor = 1.0 if is_ltha else self.anim_factor
                    nx += disp[0] * self.deflection_scale * factor
                    ny += disp[1] * self.deflection_scale * factor
                    nz += disp[2] * self.deflection_scale * factor
            sel_pos.append([nx, ny, nz])

        if sel_pos:
            sp = gl.GLScatterPlotItem(
                pos=np.array(sel_pos),
                size=size,
                color=(1, 0, 0, 1),
                pxMode=True
            )
            sp.setGLOptions({
                'glEnable': (GL_BLEND,),
                'glBlendFunc': (GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA),
                'glDisable': (GL_DEPTH_TEST,)
            })
            self.addItem(sp)
            self._sel_overlay_items.append(sp)

    def _boundary_visuals_kwargs(self, model):
        """
        Decides which link types to draw and whether they should follow the
        deflected shape, based on the current view mode. Returns a kwargs dict
        for build_boundary_visuals().

        - No results yet: show both link types, undeformed (today's behavior).
        - Force diagram active: 2-joint links only, always undeformed.
        - Deflected view (not force diagram): 1-joint links, nodal springs, and
          2-joint links all follow the deflected shape. 2-joint links use each
          end's exact solved nodal displacement directly (a link has no
          distributed stiffness along its length to interpolate, unlike a
          frame element, so the straight segment between displaced endpoints
          is exact, not an approximation).
        - Results loaded but undeformed and no force diagram: same as "no
          results" case, since geometry is undeformed anyway.
        """
        in_analysis_mode = hasattr(model, 'has_results') and model.has_results

        if getattr(self, 'ltha_mode', False):
                                                                      
            return dict(show_1joint_links=False, show_2joint_links=False, show_support_glyphs=False)

        if not in_analysis_mode:
            return dict(show_1joint_links=True, show_2joint_links=True, show_support_glyphs=True)

        if self.force_diagram_active:
            return dict(show_1joint_links=False, show_2joint_links=True, show_support_glyphs=False)

        if self.view_deflected:
            return dict(
                show_1joint_links=True,
                show_2joint_links=True,
                show_support_glyphs=False,
                node_displacements=model.results.get("displacements", {}),
                disp_scale=self.deflection_scale * self.anim_factor
            )

        return dict(show_1joint_links=True, show_2joint_links=True, show_support_glyphs=True)

    _DRAW_UNSELECTED_NODES = False
    _NODE_GL_OPTS = {'glEnable': (GL_BLEND,),
                     'glBlendFunc': (GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA),
                     'glDisable': (GL_DEPTH_TEST,)}

    def _draw_nodes(self, model):
        if not model.nodes: return
        
        pos_free = []
        ghost_pos = []

        size = self.display_config.get("node_size", 6)
        color_tuple = self.display_config.get("node_color", (1, 0, 0, 1))
        
        can_deflect = (self.view_deflected and 
                       hasattr(model, 'has_results') and 
                       model.has_results and 
                       model.results is not None)

        _skip_loop = (not self._DRAW_UNSELECTED_NODES and self.active_view_plane is None
                      and not self._view_overrides.get('node'))
        for nid, n in (() if _skip_loop else model.nodes.items()):
            nx, ny, nz = n.x, n.y, n.z
            
            if can_deflect:
                disp = model.results.get("displacements", {}).get(str(nid))
                if disp:
                    nx += disp[0] * self.deflection_scale * self.anim_factor
                    ny += disp[1] * self.deflection_scale * self.anim_factor
                    nz += disp[2] * self.deflection_scale * self.anim_factor

            xyz = [nx, ny, nz]
            
            v_state = self._node_vis(n)
            if v_state < 2:
                if v_state == 1: ghost_pos.append(xyz)
                continue                                      

            is_active = self._is_visible(n.x, n.y, n.z)
            if not is_active:
                ghost_pos.append(xyz)
                continue
            
            r = getattr(n, 'restraints', [])
            has_any_restraint = any(r) if r else False
            in_analysis_mode = hasattr(model, 'has_results') and model.has_results

            if has_any_restraint and self.show_supports and not in_analysis_mode:
                pass                                                    
            elif self.show_joints:
                pos_free.append(xyz)

        if pos_free and self._DRAW_UNSELECTED_NODES:
            item = gl.GLScatterPlotItem(pos=np.array(pos_free), size=size, color=color_tuple, pxMode=True,
                                        glOptions=self._NODE_GL_OPTS)
            self.addItem(item)
            self.node_items.append(item)

        if ghost_pos and self.show_joints:
            item = gl.GLScatterPlotItem(pos=np.array(ghost_pos), size=4, color=(0.7, 0.7, 0.7, 0.4), pxMode=True,
                                        glOptions=self._NODE_GL_OPTS)
            self.addItem(item)
            self.node_items.append(item)

        if self.show_supports and not getattr(self, 'ltha_mode', False):
                                                                                         
            visible_nodes = {nid: n for nid, n in self._boundary_nodes_sparse(model).items() if self._node_vis(n) == 2}
            
            scale = self._screen_scale() 
            links_dict = {k: v for k, v in getattr(model, 'links', {}).items() if self._vo_state('link', k) == 2}
            link_props = getattr(model, 'link_properties', {})
            
            mesh_item, line_item = build_boundary_visuals(
                visible_nodes, 
                links_dict=links_dict, 
                link_props=link_props, 
                scale=scale,
                **self._boundary_visuals_kwargs(model)
            )
                                                 
            if mesh_item:
                self.addItem(mesh_item)
                self._support_items.append(mesh_item)
                self.node_items.append(mesh_item)
                
            if line_item:
                self.addItem(line_item)
                self._support_items.append(line_item)
                self.node_items.append(line_item)

    def _is_visible(self, x, y, z):
        """
        Helper compatibility method. 
        Returns True if the object is visible (either Active OR Ghost).
        This ensures loads and nodes in the background are not skipped.
        """
                                                                    
        if not hasattr(self, 'active_view_plane'): return True
        
        state = self._get_visibility_state(x, y, z)
        return state >= 1                                                    
 
    def clear_linked_view_plane(self):
        """Remove linked viewport helper plane."""

        if self.linked_plane_item:
            try:
                self.removeItem(self.linked_plane_item)
            except:
                pass
            self.linked_plane_item = None

        if self.linked_plane_outline:
            try:
                self.removeItem(self.linked_plane_outline)
            except:
                pass
            self.linked_plane_outline = None

    def update_linked_view_plane(self, plane_data):
        """
        Draw translucent helper plane representing
        the other viewport's active 2D plane.
        """

        self.clear_linked_view_plane()

        if not plane_data:
            return

        if self._view_mode not in ["3D", "ISO"]:
            return

        if not self.current_model:
            return

        center, diag, bounds = self.compute_model_bbox()

        if not bounds:
            return

        pad = diag * 0.10

        min_x, min_y, min_z = bounds['min']
        max_x, max_y, max_z = bounds['max']
        
        min_x -= pad; max_x += pad
        min_y -= pad; max_y += pad
        min_z -= pad; max_z += pad

        axis = plane_data.get('axis')
        value = plane_data.get('value')

        if axis == 'z':
            corners = np.array([
                [min_x, min_y, value],
                [max_x, min_y, value],
                [max_x, max_y, value],
                [min_x, max_y, value]
            ], dtype=np.float32)

        elif axis == 'y':
            corners = np.array([
                [min_x, value, min_z],
                [max_x, value, min_z],
                [max_x, value, max_z],
                [min_x, value, max_z]
            ], dtype=np.float32)

        elif axis == 'x':
            corners = np.array([
                [value, min_y, min_z],
                [value, max_y, min_z],
                [value, max_y, max_z],
                [value, min_y, max_z]
            ], dtype=np.float32)

        else:
            return

        faces = np.array([
            [0, 1, 2],
            [0, 2, 3]
        ])

        mesh = gl.GLMeshItem(
            vertexes=corners,
            faces=faces,
            smooth=False,
            drawEdges=False,
            color=(0.2, 0.6, 1.0, 0.0)                       
        )

        mesh.setGLOptions({
            'glEnable': (GL_BLEND,),
            'glBlendFunc': (GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA),
            'glDisable': (GL_DEPTH_TEST,)
        })

        outline_pts = np.vstack([corners, corners[0]])

        outline = gl.GLLinePlotItem(
            pos=outline_pts,
            mode='line_strip',
            color=(0.2, 0.6, 1.0, 1.0),
            width=1.0,                        
            antialias=True
        )

        outline.setGLOptions({
            'glEnable': (GL_BLEND,),
            'glBlendFunc': (GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA),
            'glDisable': (GL_DEPTH_TEST,)
        })

        self.addItem(mesh)
        self.addItem(outline)

        self.linked_plane_item = mesh
        self.linked_plane_outline = outline
        
    def _contour_colormap(self, t, alpha=1.0):
        """
        Maps a normalized scalar t in [0, 1] to an RGBA color.
        Classic blue -> cyan -> green -> yellow -> red ramp.
        """
        t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
        if t < 0.25:
            r, g, b = 0.0, t / 0.25, 1.0
        elif t < 0.5:
            r, g, b = 0.0, 1.0, 1.0 - (t - 0.25) / 0.25
        elif t < 0.75:
            r, g, b = (t - 0.5) / 0.25, 1.0, 0.0
        else:
            r, g, b = 1.0, 1.0 - (t - 0.75) / 0.25, 0.0
        return (r, g, b, alpha)

    def _contour_scalar(self, disp_vector):
        """Reduces a 6-DOF displacement vector to the scalar contour is currently coloring by."""
        comp = getattr(self, 'contour_component', 'Resultant')
        idx = {'Ux': 0, 'Uy': 1, 'Uz': 2}.get(comp)
        if idx is not None:
            val = disp_vector[idx]
            return abs(val) if getattr(self, "contour_absolute", False) else val
        ux, uy, uz = disp_vector[0], disp_vector[1], disp_vector[2]
        return (ux * ux + uy * uy + uz * uz) ** 0.5

    def _get_contour_range(self, displacements):
        """
        Returns (c_min, c_max) for the current contour component.
        Automatic: min/max across the current case's displacement dict (vectorised, cached per results).
        User Defined: whatever the dialog set on contour_min/contour_max.
        """
        if getattr(self, 'contour_range_auto', True):
            if not displacements:
                return 0.0, 1.0
            ck = (id(displacements), len(displacements))
            cc = getattr(self, '_disp_mat_cache', None)
            if cc is not None and cc[0] == ck:
                mat = cc[1]
            else:
                mat = np.array([v[:3] for v in displacements.values()], dtype=np.float64)
                self._disp_mat_cache = (ck, mat)
            sc = vec_contour_scalar(mat, getattr(self, 'contour_component', 'Resultant'),
                                    bool(getattr(self, 'contour_absolute', False)))
            c_min, c_max = float(sc.min()), float(sc.max())
        else:
            c_min = getattr(self, 'contour_min', 0.0)
            c_max = getattr(self, 'contour_max', 1.0)
        if c_max - c_min < 1e-12:
            c_max = c_min + 1e-12
        return c_min, c_max

    def _draw_elements_wireframe(self, model):
        if not model.elements:
            self.makeCurrent()
            self.vbo_manager.upload_line_geometry([], [])
            return

        flex_pos    = []; flex_colors    = []
        rigid_pos   = []; rigid_colors   = []
        rigid_black = (0, 0, 0, 1)
        curved_pos  = []; curved_colors  = []
        release_dots = []
        ghost_pos   = []
        def_color   = np.array([0.5, 0.5, 0.5, 1.0])
        width       = self.display_config.get("line_width", 2.0)

        can_deflect = (self.view_deflected and
                    hasattr(model, 'has_results') and
                    model.has_results and
                    model.results is not None)

        displacements = model.results.get("displacements", {}) if can_deflect else {}

        contour_on = can_deflect and getattr(self, 'contour_active', False)
        if contour_on:
            contour_c_min, contour_c_max = self._get_contour_range(displacements)

        for eid, el in model.elements.items():
            n1, n2 = el.node_i, el.node_j
            v1, v2 = self._end_states('frame', el, eid)

            if v1 == 0 or v2 == 0:
                continue

            is_active_elem = (v1 == 2 and v2 == 2)

            if not is_active_elem:
                p1 = np.array([n1.x, n1.y, n1.z])
                p2 = np.array([n2.x, n2.y, n2.z])
                ghost_pos.extend([p1, p2])
                continue

            p1 = np.array([n1.x, n1.y, n1.z])
            p2 = np.array([n2.x, n2.y, n2.z])

            c = getattr(el.section, 'color', def_color)
            if len(c) == 3: c = (*c, 1.0)
            c = np.array(c)

            drawn_as_curve = False

            if can_deflect:
                                             
                res_i = displacements.get(str(n1.id))
                res_j = displacements.get(str(n2.id))

                if res_i and res_j:
                    cache_key = eid

                    if self.cache_scale_used != self.deflection_scale:
                        self.invalidate_deflection_cache()
                        self.deflection_cache.clear()
                        self.cache_scale_used = self.deflection_scale

                    if cache_key not in self.deflection_cache:
                        v1_ax, v2_ax, v3_ax = self._get_consistent_axes(el)
                        curve_data = get_deflected_shape(
                            [n1.x, n1.y, n1.z],
                            [n2.x, n2.y, n2.z],
                            res_i, res_j,
                            v1_ax, v2_ax, v3_ax,
                            scale=self.deflection_scale,
                            num_points=11
                        )
                        self.deflection_cache[cache_key] = {
                            'curve_data': curve_data,
                            'p1_orig': p1.copy(),
                            'p2_orig': p2.copy()
                        }

                    cached          = self.deflection_cache[cache_key]
                    curve_data_full = cached['curve_data']

                    p1_flex, p2_flex = p1, p2

                    K            = len(curve_data_full)
                    pos_full_arr = np.array([cd[0] for cd in curve_data_full], dtype=np.float64)
                    s_arr        = (np.arange(K) / (K - 1))[:, None]
                    pos_orig_arr = p1_flex + s_arr * (p2_flex - p1_flex)
                    pts          = pos_orig_arr + (pos_full_arr - pos_orig_arr) * self.anim_factor
                    pairs        = np.empty((2 * (K - 1), 3), dtype=np.float64)
                    pairs[0::2]  = pts[:-1]
                    pairs[1::2]  = pts[1:]
                    curved_pos.extend(pairs)

                    if contour_on:
                                                                                   
                        s_i = self._contour_scalar(res_i) * self.anim_factor
                        s_j = self._contour_scalar(res_j) * self.anim_factor
                        station_scalars = s_i + (s_j - s_i) * s_arr.flatten()
                        station_colors = [
                            self._contour_colormap((sv - contour_c_min) / (contour_c_max - contour_c_min))
                            for sv in station_scalars
                        ]
                        seg_colors = np.empty((2 * (K - 1), 4), dtype=np.float32)
                        seg_colors[0::2] = station_colors[:-1]
                        seg_colors[1::2] = station_colors[1:]
                        curved_colors.extend(seg_colors)
                    else:
                        curved_colors.extend([c] * (2 * (K - 1)))

                    drawn_as_curve = True

                    if self.view_shadow:
                        dist = np.linalg.norm(p2 - p1)
                        dash_len = 0.5
                        if dist > 0:
                            num_dashes = int(dist / dash_len)
                            vec = (p2 - p1) / dist
                            for d in range(0, num_dashes, 2):
                                d_start = p1 + (vec * d * dash_len)
                                d_end   = p1 + (vec * (d + 1) * dash_len)
                                if np.linalg.norm(d_end - p1) > dist: d_end = p2
                                ghost_pos.append(d_start)
                                ghost_pos.append(d_end)

            if not drawn_as_curve:
                off_i = getattr(el, 'end_offset_i', 0.0)
                off_j = getattr(el, 'end_offset_j', 0.0)

                vec    = p2 - p1
                length = np.linalg.norm(vec)
                p1_flex = p1; p2_flex = p2

                if length > 0.001 and (off_i > 0 or off_j > 0):
                    u = vec / length
                    if off_i + off_j >= length:
                        scale   = (length / (off_i + off_j)) * 0.99
                        p1_flex = p1 + (u * off_i * scale)
                        p2_flex = p2 - (u * off_j * scale)
                    else:
                        p1_flex = p1 + (u * off_i)
                        p2_flex = p2 - (u * off_j)

                    if off_i > 0:
                        curved_pos.extend([p1, p1_flex])
                        curved_colors.extend([rigid_black, rigid_black])
                    if off_j > 0:
                        curved_pos.extend([p2_flex, p2])
                        curved_colors.extend([rigid_black, rigid_black])

                flex_pos.extend([p1_flex, p2_flex])
                flex_colors.extend([c, c])

                if self.show_releases:
                    flex_vec = p2_flex - p1_flex
                    flex_len = np.linalg.norm(flex_vec)
                    if flex_len > 0:
                        offset_vec = (flex_vec / flex_len) * 0.15
                        if hasattr(el, 'releases_i') and (el.releases_i[4] or el.releases_i[5]):
                            release_dots.append(p1_flex + offset_vec)
                        if hasattr(el, 'releases_j') and (el.releases_j[4] or el.releases_j[5]):
                            release_dots.append(p2_flex - offset_vec)

        all_line_pos    = flex_pos + rigid_pos + curved_pos
        all_line_colors = flex_colors + rigid_colors + curved_colors

        if all_line_pos:
            v_arr = np.array(all_line_pos,    dtype=np.float32)
            c_arr = np.array(all_line_colors, dtype=np.float32)
            self.makeCurrent()
            self.vbo_manager.upload_line_geometry(v_arr, c_arr)
        else:
            self.makeCurrent()
            if hasattr(self, 'vbo_manager'):
                self.vbo_manager.upload_line_geometry([], [])

        if release_dots:
            dot_item = gl.GLScatterPlotItem(
                pos=np.array(release_dots), size=0.25, color=(0, 1, 0, 1), pxMode=False
            )
            dot_item.setGLOptions('opaque')
            self.addItem(dot_item)
            self.element_items.append(dot_item)

        if ghost_pos:
            c = self.shadow_color
            ghost_item = gl.GLLinePlotItem(
                pos=np.array(ghost_pos), color=c, mode='lines', width=2.0, antialias=True
            )
            ghost_item.setGLOptions('translucent')
            self.addItem(ghost_item)
            self.element_items.append(ghost_item)
            
    def _draw_elements_extruded(self, model):
        if not model.elements:
            self.makeCurrent()
            self.vbo_manager.upload_extruded_geometry(
                np.empty((0, 3), dtype=np.float32),
                np.empty((0, 4), dtype=np.float32),
                np.empty((0, 3), dtype=np.int32),
            )
            self.vbo_manager.upload_line_geometry([], [])
            return

        self.ex_vertices = []
        self.ex_faces = []
        self.ex_colors = []
        self.ex_normals = []
        self.ex_edges = []
        self.ex_edge_colors = []

        ghost_ex_verts, ghost_ex_faces, ghost_ex_colors = [], [], []
      
        opacity = self.display_config.get("extrude_opacity", 0.35)
        show_edges = self.display_config.get("show_edges", False)
        edge_c = np.array(self.display_config.get("edge_color", (0, 0, 0, 1)), dtype=np.float32)
        edge_width = self.display_config.get("edge_width", 1.0)
        
        can_deflect = (self.view_deflected and 
                       hasattr(model, 'has_results') and 
                       model.has_results and 
                       model.results is not None)

        displacements = model.results.get("displacements", {}) if can_deflect else {}

        contour_on = can_deflect and getattr(self, 'contour_active', False)
        if contour_on:
            contour_c_min, contour_c_max = self._get_contour_range(displacements)

        fallback_line_pos    = []
        fallback_line_colors = []

        for eid, el in model.elements.items():
            n1, n2 = el.node_i, el.node_j
            
            v1, v2 = self._end_states('frame', el, eid)

            if v1 == 0 or v2 == 0: continue

            is_active_elem = (v1 == 2 and v2 == 2)

            sec = el.section
            shape_yz = sec.get_shape_coords()
            if not shape_yz:
                _p1 = np.array([n1.x, n1.y, n1.z])
                _p2 = np.array([n2.x, n2.y, n2.z])
                _c_raw = list(getattr(sec, 'color', [0.5, 0.5, 0.5, 1.0]))
                if len(_c_raw) == 3:
                    _c_raw.append(1.0)
                _lc = np.array(_c_raw[:4], dtype=np.float32)
                if not is_active_elem:
                    _lc = np.array([0.6, 0.6, 0.6, 0.4], dtype=np.float32)

                if can_deflect:
                                             
                    res_i = displacements.get(str(n1.id))
                    res_j = displacements.get(str(n2.id))
                    if res_i and res_j:
                        v1_ax, v2_ax, v3_ax = self._get_consistent_axes(el)
                        eff_scale = self.deflection_scale * self.anim_factor
                        curve_data = get_deflected_shape(
                            [n1.x, n1.y, n1.z], [n2.x, n2.y, n2.z],
                            res_i, res_j, v1_ax, v2_ax, v3_ax,
                            scale=eff_scale,
                            num_points=11
                        )
                        curve_pts = [cd[0] for cd in curve_data]
                        for k in range(len(curve_pts) - 1):
                            fallback_line_pos.extend([curve_pts[k], curve_pts[k + 1]])
                            fallback_line_colors.extend([_lc, _lc])
                        continue

                fallback_line_pos.extend([_p1, _p2])
                fallback_line_colors.extend([_lc, _lc])
                continue

            needs_caps = isinstance(sec, (RectangularSection, CircularSection, TrapezoidalSection))
            
            if not is_active_elem:
                face_color = np.array([0.6, 0.6, 0.6, 0.15])
                current_edge_color = np.array([0.6, 0.6, 0.6, 0.1])           
                show_edges_for_this = False                                    
            else:
                c_raw = getattr(sec, 'color', [0.7, 0.7, 0.7])
                if len(c_raw) == 4: c_raw = c_raw[:3]
                face_color = np.array([c_raw[0], c_raw[1], c_raw[2], opacity])
                current_edge_color = edge_c
                show_edges_for_this = show_edges

            path_points = []
            path_colors = []
            
            p1 = np.array([n1.x, n1.y, n1.z])
            p2 = np.array([n2.x, n2.y, n2.z])
            
            if can_deflect:
                                         
                res_i = displacements.get(str(n1.id))
                res_j = displacements.get(str(n2.id))
                
                if res_i and res_j:
                    v1_orig, v2_orig, v3_orig = self._get_consistent_axes(el)
                    eff_scale = self.deflection_scale * self.anim_factor

                    curve_data = get_deflected_shape(
                        [n1.x, n1.y, n1.z], [n2.x, n2.y, n2.z],
                        res_i, res_j,
                        v1_orig, v2_orig, v3_orig,
                        scale=eff_scale,
                        num_points=11
                    )   

                    K = len(curve_data)
                    if contour_on:
                        s_i = self._contour_scalar(res_i) * self.anim_factor
                        s_j = self._contour_scalar(res_j) * self.anim_factor
                    
                    for k in range(len(curve_data)):
                        pos, tan_vec, twist = curve_data[k]
                        
                        v1_curr = tan_vec 

                        c_t = np.cos(twist); s_t = np.sin(twist)
                        v2_twisted = (c_t * v2_orig) + (s_t * v3_orig)
                        
                        proj = np.dot(v2_twisted, v1_curr) * v1_curr
                        v2_curr = v2_twisted - proj
                        n2_len = np.linalg.norm(v2_curr)
                        if n2_len > 1e-6: v2_curr /= n2_len
                        else: v2_curr = v2_orig 
                            
                        v3_curr = np.cross(v1_curr, v2_curr)
                        path_points.append( (pos, v2_curr, v3_curr) )

                        if contour_on:
                            frac = k / (K - 1) if K > 1 else 0.0
                            scalar = s_i + (s_j - s_i) * frac
                            path_colors.append(
                                self._contour_colormap((scalar - contour_c_min) / (contour_c_max - contour_c_min), alpha=opacity)
                            )

            if not path_points:
                off_i = getattr(el, 'end_offset_i', 0.0)
                off_j = getattr(el, 'end_offset_j', 0.0)
                
                vec = p2 - p1
                length = np.linalg.norm(vec)
                vx = vec / length if length > 0 else np.array([1,0,0])

                p1_draw = p1
                p2_draw = p2

                if (off_i > 0 or off_j > 0) and length > 0.001:
                    if off_i + off_j >= length:
                        scale = (length / (off_i + off_j)) * 0.99
                        p1_draw = p1 + (vx * off_i * scale)
                        p2_draw = p2 - (vx * off_j * scale)
                    else:
                        p1_draw = p1 + (vx * off_i)
                        p2_draw = p2 - (vx * off_j)

                v1, v2, v3 = self._get_consistent_axes(el)
                path_points.append( (p1_draw, v2, v3) )
                path_points.append( (p2_draw, v2, v3) )

            y_shift, z_shift = el.get_cardinal_offsets()
            off_vec_i = getattr(el, 'joint_offset_i', np.array([0,0,0]))
            off_vec_j = getattr(el, 'joint_offset_j', np.array([0,0,0]))
            
            num_pts = len(path_points)
            has_contour_colors = contour_on and len(path_colors) == num_pts
            
            for i in range(num_pts - 1):
                pos_a, v2_a, v3_a = path_points[i]
                pos_b, v2_b, v3_b = path_points[i+1]
                
                if num_pts > 1:
                    s_a = i / (num_pts - 1)
                    s_b = (i + 1) / (num_pts - 1)
                else:
                    s_a, s_b = 0.0, 1.0

                curr_off_a = (1 - s_a) * off_vec_i + s_a * off_vec_j
                curr_off_b = (1 - s_b) * off_vec_i + s_b * off_vec_j
                
                center_a = pos_a + curr_off_a + (y_shift * v2_a) + (z_shift * v3_a)
                center_b = pos_b + curr_off_b + (y_shift * v2_b) + (z_shift * v3_b)

                is_first_seg = (i == 0)
                is_last_seg = (i == num_pts - 2)

                if not is_active_elem:
                    self._add_loft_to_arrays(
                        center_a, center_b, v2_a, v3_a, v2_b, v3_b,
                        shape_yz, face_color, show_edges=False, edge_color=None,
                        draw_start_ring=is_first_seg, draw_end_ring=is_last_seg,
                        draw_caps=needs_caps,
                        ex_vertices=ghost_ex_verts,                          
                        ex_faces=ghost_ex_faces, 
                        ex_colors=ghost_ex_colors,
                        ex_edges=[], ex_edge_colors=[] 
                    )
                else:
                    self._add_loft_segment(
                        center_a, center_b, 
                        v2_a, v3_a, v2_b, v3_b,
                        shape_yz, face_color, 
                        show_edges_for_this, current_edge_color,
                        draw_start_ring=is_first_seg, 
                        draw_end_ring=is_last_seg,
                        draw_caps=needs_caps,
                        color_a=path_colors[i] if has_contour_colors else None,
                        color_b=path_colors[i + 1] if has_contour_colors else None
                    )

        v_arr = np.array(self.ex_vertices, dtype=np.float32) if self.ex_vertices else np.empty((0, 3), dtype=np.float32)
        c_arr = np.array(self.ex_colors,   dtype=np.float32) if self.ex_colors   else np.empty((0, 4), dtype=np.float32)
        f_arr = np.array(self.ex_faces,    dtype=np.int32)   if self.ex_faces    else np.empty((0, 3), dtype=np.int32)
        n_arr = np.array(self.ex_normals,  dtype=np.float32) if self.ex_normals  else np.empty((0, 3), dtype=np.float32)

        self.makeCurrent()
        self.vbo_manager.upload_extruded_geometry(v_arr, c_arr, f_arr, normals=n_arr if len(n_arr) else None)

        if show_edges and self.ex_edges:
            ev_arr = np.array(self.ex_edges, dtype=np.float32)
            ec_arr = np.array(self.ex_edge_colors, dtype=np.float32)
            if fallback_line_pos:
                fb_v = np.array(fallback_line_pos, dtype=np.float32)
                fb_c = np.array(fallback_line_colors, dtype=np.float32)
                ev_arr = np.vstack([ev_arr, fb_v])
                ec_arr = np.vstack([ec_arr, fb_c])
            self.makeCurrent()
            self.vbo_manager.upload_line_geometry(ev_arr, ec_arr)
        elif fallback_line_pos:
            fb_v = np.array(fallback_line_pos, dtype=np.float32)
            fb_c = np.array(fallback_line_colors, dtype=np.float32)
            self.makeCurrent()
            self.vbo_manager.upload_line_geometry(fb_v, fb_c)
        else:
            self.makeCurrent()
            if hasattr(self, 'vbo_manager'):
                self.vbo_manager.upload_line_geometry([], [])

        if ghost_ex_verts:
            ghost_ext_mesh = gl.GLMeshItem(
                vertexes=np.array(ghost_ex_verts, dtype=np.float32),
                faces=np.array(ghost_ex_faces, dtype=np.int32),
                vertexColors=np.array(ghost_ex_colors, dtype=np.float32),
                smooth=False,
                glOptions='translucent'
            )
            self.addItem(ghost_ext_mesh)
            self.element_items.append(ghost_ext_mesh)

    def _add_loft_segment(self, c1, c2, v2_a, v3_a, v2_b, v3_b, shape, color, show_edges, edge_color, draw_start_ring=False, draw_end_ring=False, draw_caps=False, color_a=None, color_b=None):
        """
        Smart Extrusion: Generates triangles but selectively hides internal 'ribs' 
        to maintain the clean 'glass' look.

        Side-wall vertices are duplicated per quad face rather than shared
        around the ring, so each face carries its own flat normal for
        lighting -- sharing them would average adjacent face normals
        together and round hard edges on box/I-beam sections into an
        incorrect soft curve. (Exact normal sign doesn't matter here: the
        lit fragment shader flips normals to face the camera, so getting a
        face's winding "backwards" still shades correctly.)
        """
        verts_a = []
        for y, z in shape:
            p = c1 + (y * v2_a) + (z * v3_a)
            verts_a.append(p)

        verts_b = []
        for y, z in shape:
            p = c2 + (y * v2_b) + (z * v3_b)
            verts_b.append(p)

        ring_color_a = color_a if color_a is not None else color
        ring_color_b = color_b if color_b is not None else color

        n = len(shape)
        for i in range(n):
            next_i = (i + 1) % n

            pa0, pa1 = verts_a[i], verts_a[next_i]
            pb0, pb1 = verts_b[i], verts_b[next_i]

            face_normal = np.cross(pa1 - pa0, pb0 - pa0)
            f_len = np.linalg.norm(face_normal)
            face_normal = face_normal / f_len if f_len > 1e-9 else np.array([0.0, 0.0, 1.0])

            base = len(self.ex_vertices)
            self.ex_vertices.extend([pa0, pa1, pb1, pb0])
            self.ex_colors.extend([ring_color_a, ring_color_a, ring_color_b, ring_color_b])
            self.ex_normals.extend([face_normal, face_normal, face_normal, face_normal])

            self.ex_faces.append([base + 0, base + 1, base + 2])
            self.ex_faces.append([base + 0, base + 2, base + 3])

            if show_edges:
                self.ex_edges.extend([verts_a[i], verts_b[i]])
                self.ex_edge_colors.extend([edge_color, edge_color])

                if draw_start_ring:
                    self.ex_edges.extend([verts_a[i], verts_a[next_i]])
                    self.ex_edge_colors.extend([edge_color, edge_color])

                if draw_end_ring:
                    self.ex_edges.extend([verts_b[i], verts_b[next_i]])
                    self.ex_edge_colors.extend([edge_color, edge_color])

        if draw_caps:
            if draw_start_ring and n >= 3:
                cap_normal = np.cross(verts_a[1] - verts_a[0], verts_a[2] - verts_a[0])
                cn_len = np.linalg.norm(cap_normal)
                cap_normal = cap_normal / cn_len if cn_len > 1e-9 else np.array([0.0, 0.0, 1.0])
                base = len(self.ex_vertices)
                self.ex_vertices.extend(verts_a)
                self.ex_colors.extend([ring_color_a] * n)
                self.ex_normals.extend([cap_normal] * n)
                for i in range(1, n - 1):
                    self.ex_faces.append([base, base + i + 1, base + i])
            if draw_end_ring and n >= 3:
                cap_normal = np.cross(verts_b[1] - verts_b[0], verts_b[2] - verts_b[0])
                cn_len = np.linalg.norm(cap_normal)
                cap_normal = cap_normal / cn_len if cn_len > 1e-9 else np.array([0.0, 0.0, 1.0])
                base = len(self.ex_vertices)
                self.ex_vertices.extend(verts_b)
                self.ex_colors.extend([ring_color_b] * n)
                self.ex_normals.extend([cap_normal] * n)
                for i in range(1, n - 1):
                    self.ex_faces.append([base, base + i, base + i + 1])
    
    def show_reaction_diagram(self, model, reaction_data, sign_convention='ground_on_structure'):
        if self.force_diagram_active:
            self.clear_force_diagrams()
        self.reaction_data = reaction_data
        self.reaction_diagram_active = True
        self.reaction_sign_convention = sign_convention                 
        
        self._pre_reaction_was_deflected = self.view_deflected
        self.view_deflected = False

        self._pre_reaction_was_grid = self.show_grid
        self.show_grid = False
        
        self._force_draw_model(model)
        self.update()
        return True

    def clear_reaction_diagram(self, model=None):
        if not self.reaction_diagram_active:
            return
        self.reaction_diagram_active = False
        self.reaction_data = {}
        
        self.view_deflected = self._pre_reaction_was_deflected
        self.show_grid = self._pre_reaction_was_grid
        
        if model:
            self._force_draw_model(model)
        self.update()

    def show_force_diagram(self, model, component='M3', scale_factor=None,
                           displacements=None, matrices_path=None, show_labels=False,
                           show_labels_mode='all', text_size=None, selected_ids=None, is_envelope=True, step_number=None):
        """
        Builds and renders the 3D force diagrams for the active model asynchronously.
        """
        if self.reaction_diagram_active:
            self.clear_reaction_diagram(model)

        needs_redraw = False
        if self.view_extruded:
            self._pre_force_was_extruded = True
            self.view_extruded = False
            needs_redraw = True
        if self.view_deflected:
            self._pre_force_was_deflected = True
            self.view_deflected = False
            self.invalidate_deflection_cache()
            needs_redraw = True
        if self.show_grid:
            self._pre_force_was_grid = True
            self.show_grid = False
            needs_redraw = True
        if needs_redraw:
            self._force_draw_model(model)

        self._force_calc_token += 1

        worker = ForceComputationWorker(
            self._force_calc_token, model, component, scale_factor, displacements, matrices_path,
            show_labels, show_labels_mode, text_size, self.active_view_plane,
            self.show_ghost_structure, selected_ids, is_envelope, step_number,
            text_builder=getattr(self, 'text_builder', None),
            background_labels=self._scaled_load_labels(),
            grid_labels=getattr(self, 'grid_labels', []),
            text_revision=getattr(self, '_text_geometry_revision', 0),
        )
                                                                            
        if self._force_worker is not None:
            self._force_worker.requestInterruption()
            self._pending_force_request = worker
        else:
            self._start_force_worker(worker)

        return True                             

    def _start_force_worker(self, worker):
        self._force_worker = worker
        worker.signal_finished.connect(self._on_force_computation_finished)
        worker.finished.connect(self._on_force_worker_stopped)
        worker.start()

    def _on_force_worker_stopped(self):
        worker = self._force_worker
        self._force_worker = None
        if worker is not None:
            worker.deleteLater()
        pending = self._pending_force_request
        self._pending_force_request = None
        if pending is not None and pending.token == self._force_calc_token:
            self._start_force_worker(pending)

    def _on_force_computation_finished(self, success, vbo_data, labels, token):
                                                                                         
        if getattr(self, '_force_calc_token', 0) != token:
            return

        if not success:
            self.makeCurrent()
            self.vbo_manager.clear_force_geometry()
            self._pending_force_upload = None
            self.force_labels = []
            self.force_diagram_active = False
            self._upload_load_labels_to_gpu()
            self.update()
            return

        self.force_labels = labels
        
        self.makeCurrent()
        text_geometry = vbo_data.get('text_geometry')
        if (text_geometry is not None and vbo_data.get('text_revision') ==
                getattr(self, '_text_geometry_revision', 0)):
            self.vbo_manager.upload_text_geometry(*text_geometry)
        else:
            self._upload_load_labels_to_gpu()

        self._pending_force_upload = vbo_data
        self.force_diagram_active = True
        self.update()

    def clear_force_diagrams(self):
        """Hides force diagrams and restores extruded/deformed state that was active before."""
        self._force_calc_token += 1
        self._pending_force_request = None
        self._pending_force_upload = None
        if self._force_worker is not None:
            self._force_worker.requestInterruption()
        self.force_diagram_active = False
        self.force_mesh_item.hide()
        self.force_line_item.hide()
        self.force_labels = []
        self._label_pixmap = None
        self.vbo_manager.clear_force_geometry()              

        self.makeCurrent()
        self._upload_load_labels_to_gpu()                                                            

        needs_redraw = False
        if getattr(self, '_pre_force_was_extruded', False):
            self._pre_force_was_extruded = False
            self.view_extruded = True
            needs_redraw = True
        if getattr(self, '_pre_force_was_deflected', False):
            self._pre_force_was_deflected = False
            self.view_deflected = True
            needs_redraw = True
        if getattr(self, '_pre_force_was_grid', False):
            self._pre_force_was_grid = False
            self.show_grid = True
            needs_redraw = True
        if needs_redraw and self.current_model:
            self._force_draw_model(self.current_model)
            
    def _add_loft_to_arrays(self, c1, c2, v2_a, v3_a, v2_b, v3_b, shape, color, show_edges, edge_color,
                            draw_start_ring=False, draw_end_ring=False,
                            ex_vertices=None, ex_faces=None, ex_colors=None,
                            ex_edges=None, ex_edge_colors=None, draw_caps=False):
        """
        Same as _add_loft_segment but adds to provided arrays instead of self.ex_*
        Used for pre-rendering animation frames.
        """
                               
        start_idx = len(ex_vertices)
        
        verts_a = []
        for y, z in shape:
            p = c1 + (y * v2_a) + (z * v3_a)
            verts_a.append(p)
        
        verts_b = []
        for y, z in shape:
            p = c2 + (y * v2_b) + (z * v3_b)
            verts_b.append(p)
        
        ex_vertices.extend(verts_a)
        ex_vertices.extend(verts_b)
        
        for _ in range(len(verts_a) + len(verts_b)):
            ex_colors.append(color)
        
        n = len(shape)
        for i in range(n):
            next_i = (i + 1) % n
            
            idx_a_curr = start_idx + i
            idx_a_next = start_idx + next_i
            idx_b_curr = start_idx + n + i
            idx_b_next = start_idx + n + next_i
            
            ex_faces.append([idx_a_curr, idx_a_next, idx_b_next])
            ex_faces.append([idx_a_curr, idx_b_next, idx_b_curr])
            
            if show_edges:
                                   
                ex_edges.extend([verts_a[i], verts_b[i]])
                ex_edge_colors.extend([edge_color, edge_color])
                
                if draw_start_ring:
                    ex_edges.extend([verts_a[i], verts_a[next_i]])
                    ex_edge_colors.extend([edge_color, edge_color])
                
                if draw_end_ring:
                    ex_edges.extend([verts_b[i], verts_b[next_i]])
                    ex_edge_colors.extend([edge_color, edge_color])

        if draw_caps:
            if draw_start_ring and n >= 3:
                root_a = start_idx
                for i in range(1, n - 1):
                    ex_faces.append([root_a, start_idx + i + 1, start_idx + i])
            if draw_end_ring and n >= 3:
                root_b = start_idx + n
                for i in range(1, n - 1):
                    ex_faces.append([root_b, start_idx + n + i, start_idx + n + i + 1])
    
    def _triangulate_cap_indices(self, indices, full_faces):
        """Helper to triangulate a polygon given vertex indices."""
        if len(indices) < 3: return
        root = indices[0]
        for i in range(1, len(indices) - 1):
            full_faces.append([root, indices[i], indices[i+1]])
    def _triangulate_cap(self, indices, full_faces, full_colors, color):
        """
        Closes the ends of the extruded shape using a Triangle Fan.
        Works well for Rectangles and standard I-Sections.
        """
        if len(indices) < 3: return
        
        root = indices[0]
        
        for i in range(1, len(indices) - 1):
            p2 = indices[i]
            p3 = indices[i+1]
            
            full_faces.append([root, p2, p3])
            
            full_colors.append(color)
            full_colors.append(color)
            full_colors.append(color)

    def _get_tendon_world_points(self, tendon):
        """
        Tessellates a TendonObject's layout_points (local coord1/2/3 table) into
        a world-space (N,3) polyline.

        segment_type "Linear" -> straight interpolation.
        segment_type "Parabolic"/"Circular" -> cubic Bezier using each point's
        own `slope` as tangent, control points offset by dx/3 — this is the
        exact same formula tendon_geometry_dialog.py's 2D profile preview
        uses, so the 3D curve matches what the geometry dialog already shows.

        The tendon's `plane` ("1-2" or "1-3") selects which of coord2/coord3
        is the slope-driven "active" profile axis; the other axis has no
        slope data and is simply linearly interpolated.
        """
        pts = tendon.layout_points
        if len(pts) < 2:
            return None

        v_x, v_y_raw, v_z_raw = tendon.get_local_axes()
                                                                             
        v_2 = v_z_raw
        v_3 = -v_y_raw
        origin = tendon.node_i.get_coords()
        active_is_coord2 = (tendon.plane == "1-2")
        max_len = max(getattr(tendon, 'max_discretization_length', 1.0), 0.05)

        world_pts = []
        for i in range(len(pts) - 1):
            p0, p1 = pts[i], pts[i + 1]
            c1_0, c1_1 = p0["coord1"], p1["coord1"]
            seg_len = abs(c1_1 - c1_0)
            is_curved = p1.get("segment_type", "Linear") in ("Parabolic", "Circular")
            n_sub = max(8, int(math.ceil(seg_len / max_len))) if is_curved else max(1, int(math.ceil(seg_len / max_len)))

            act0 = p0["coord2"] if active_is_coord2 else p0["coord3"]
            act1 = p1["coord2"] if active_is_coord2 else p1["coord3"]
            m0, m1 = p0.get("slope", 0.0), p1.get("slope", 0.0)
            inact0 = p0["coord3"] if active_is_coord2 else p0["coord2"]
            inact1 = p1["coord3"] if active_is_coord2 else p1["coord2"]

            dx = c1_1 - c1_0
            dy = act1 - act0

            start_k = 0 if i == 0 else 1
            for k in range(start_k, n_sub + 1):
                t = k / n_sub
                if is_curved:
                                                              
                    c1 = c1_0 + t * dx
                    act = act0 + (m0 * dx * t) + (dy - m0 * dx) * (t**2)
                else:
                    c1, act = c1_0 + t * dx, act0 + t * dy
                inact = inact0 + t * (inact1 - inact0)
                c2 = act if active_is_coord2 else inact
                c3 = inact if active_is_coord2 else act
                world_pts.append(origin + c1 * v_x + c2 * v_2 + c3 * v_3)

        return np.array(world_pts, dtype=np.float64)

    def _draw_tendons_wireframe(self, model):
        """Draw/geometry-definition only (per TendonObject docstring) — this is
        the first actual rendering pass: one GLLinePlotItem per tendon, same
        per-item pattern already used for ghost dashes / release dots above,
        since tendons are few compared to bulk frame elements (no VBO batching
        needed)."""
        tendons = getattr(model, 'tendons', {})
        if not tendons or not getattr(self, 'show_tendons', True) or self.view_deflected:
            return
        for tid, tendon in tendons.items():
            _vs = self._vo_state('tendon', tid)
            if _vs == 0:
                continue
            pts = self._get_tendon_world_points(tendon)
            if pts is None or len(pts) < 2:
                continue
            if _vs == 1:
                self._add_vo_ghost_line(pts)
                continue
            sec = getattr(tendon, 'tendon_section', None)
            c = getattr(sec, 'color', (0, 1, 1, 1)) if sec else (0, 1, 1, 1)
            
            if len(c) == 3: c = (*c, 1.0)
            item = gl.GLLinePlotItem(pos=pts, color=tuple(c), width=2.5,
                                      mode='line_strip', antialias=True)
            
            item.setGLOptions('opaque')
            self.addItem(item)
            self.element_items.append(item)

    def _draw_tendons_extruded(self, model):
        """Sweeps a circular cross-section (radius from TendonSection.dia or
        .area) along the tessellated tendon polyline. A circle is rotation-
        symmetric, so a simple parallel-transport side-vector is sufficient —
        no twist tracking is needed the way frame-element extrusion needs it
        for arbitrary (asymmetric) section shapes."""
        tendons = getattr(model, 'tendons', {})
        if not tendons or not getattr(self, 'show_tendons', True) or self.view_deflected:
            return
        sides = 10
        for tid, tendon in tendons.items():
            _vs = self._vo_state('tendon', tid)
            if _vs == 0:
                continue
            pts = self._get_tendon_world_points(tendon)
            if pts is None or len(pts) < 2:
                continue
            if _vs == 1:
                self._add_vo_ghost_line(pts)
                continue
            sec = tendon.tendon_section
            sec = tendon.tendon_section
            radius = (sec.dia / 2.0) if getattr(sec, 'is_dia', False) else math.sqrt(max(sec.area, 1e-8) / math.pi)
            
            c = getattr(sec, 'color', (0, 1, 1, 1))
            if len(c) == 3: c = (*c, 1.0)
            face_color = np.array(c, dtype=np.float32)

            tangents = []
            for i in range(len(pts) - 1):
                d = pts[i + 1] - pts[i]
                L = np.linalg.norm(d)
                tangents.append(d / L if L > 1e-9 else np.array([1.0, 0.0, 0.0]))
            tangents.append(tangents[-1])

            v_x0, v_y0, _ = tendon.get_local_axes()
            side = v_y0 - np.dot(v_y0, tangents[0]) * tangents[0]
            if np.linalg.norm(side) < 1e-6:
                ref = np.array([0.0, 0.0, 1.0])
                side = ref - np.dot(ref, tangents[0]) * tangents[0]
            side = side / np.linalg.norm(side)

            rings = []
            for i, p in enumerate(pts):
                t = tangents[i]
                side = side - np.dot(side, t) * t
                n_side = np.linalg.norm(side)
                side = side / n_side if n_side > 1e-6 else side
                up = np.cross(t, side)
                rings.append([p + radius * (math.cos(a) * side + math.sin(a) * up)
                              for a in np.linspace(0, 2 * math.pi, sides, endpoint=False)])

            verts, faces, colors = [], [], []
            for i in range(len(rings) - 1):
                base = len(verts)
                verts.extend(rings[i]); verts.extend(rings[i + 1])
                for s in range(sides):
                    s2 = (s + 1) % sides
                    a, b, c_, d_ = base + s, base + s2, base + sides + s, base + sides + s2
                    faces.append([a, b, c_]); faces.append([b, d_, c_])
                colors.extend([face_color] * (2 * sides))

            if not verts:
                continue
            mesh = gl.GLMeshItem(vertexes=np.array(verts, dtype=np.float32),
                                  faces=np.array(faces, dtype=np.int32),
                                  vertexColors=np.array(colors, dtype=np.float32),
                                  smooth=True,
                                  glOptions='translucent' if face_color[3] < 0.999 else 'opaque')
            self.addItem(mesh)
            self.element_items.append(mesh)

    def _draw_cables_wireframe(self, model):
        cables = getattr(model, 'cables', {})
        if not cables or self.view_deflected: return
        
        for cid, cable in cables.items():
            _vs = self._vo_state('cable', cid)
            if _vs == 0:
                continue
            pts = self._get_cable_world_points(cable)
            if pts is None or len(pts) < 2:
                continue
            if _vs == 1:
                self._add_vo_ghost_line(pts)
                continue

            sec = getattr(cable, 'cable_section', None)
            c = getattr(sec, 'color', (1, 0, 0, 1)) if sec else (1, 0, 0, 1)
            if len(c) == 3: c = (*c, 1.0)
            
            item = gl.GLLinePlotItem(pos=pts, color=tuple(c), width=2.5, mode='line_strip', antialias=True)
            item.setGLOptions('opaque')
            self.addItem(item)
            self.element_items.append(item)

    def _draw_cables_extruded(self, model):
        cables = getattr(model, 'cables', {})
        if not cables or self.view_deflected: return
        
        sides = 10
        for cid, cable in cables.items():
            _vs = self._vo_state('cable', cid)
            if _vs == 0:
                continue
            pts = self._get_cable_world_points(cable)
            if pts is None or len(pts) < 2:
                continue
            if _vs == 1:
                self._add_vo_ghost_line(pts)
                continue

            sec = getattr(cable, 'cable_section', None)
            if not sec: continue
            
            radius = (sec.dia / 2.0) if getattr(sec, 'is_dia', False) else math.sqrt(max(sec.area, 1e-8) / math.pi)
            c = getattr(sec, 'color', (1, 0, 0, 1))
            if len(c) == 3: c = (*c, 1.0)
            face_color = np.array(c, dtype=np.float32)

            tangents = []
            for i in range(len(pts) - 1):
                d = pts[i + 1] - pts[i]
                L = np.linalg.norm(d)
                tangents.append(d / L if L > 1e-9 else np.array([1.0, 0.0, 0.0]))
            tangents.append(tangents[-1])

            ref = np.array([0.0, 0.0, 1.0])
            if abs(tangents[0][2]) > 0.99: ref = np.array([1.0, 0.0, 0.0])
            side = np.cross(ref, tangents[0])
            side /= np.linalg.norm(side)

            rings = []
            for i, pt in enumerate(pts):
                t = tangents[i]
                side = side - np.dot(side, t) * t
                n_side = np.linalg.norm(side)
                side = side / n_side if n_side > 1e-6 else side
                up = np.cross(t, side)
                
                rings.append([pt + radius * (math.cos(a) * side + math.sin(a) * up)
                              for a in np.linspace(0, 2 * math.pi, sides, endpoint=False)])

            verts, faces, colors = [], [], []
            for i in range(len(rings) - 1):
                base = len(verts)
                verts.extend(rings[i]); verts.extend(rings[i + 1])
                for s in range(sides):
                    s2 = (s + 1) % sides
                    a, b, c_, d_ = base + s, base + s2, base + sides + s, base + sides + s2
                    faces.append([a, b, c_]); faces.append([b, d_, c_])
                colors.extend([face_color] * (2 * sides))

            mesh = gl.GLMeshItem(vertexes=np.array(verts, dtype=np.float32),
                                  faces=np.array(faces, dtype=np.int32),
                                  vertexColors=np.array(colors, dtype=np.float32),
                                  smooth=True,
                                  glOptions='translucent' if face_color[3] < 0.999 else 'opaque')
            self.addItem(mesh)
            self.element_items.append(mesh)
            
    def _draw_slabs(self, model):
                                                                                                
        pass

    def set_view_overrides(self, overrides):
        """Replace the whole override table ({kind: {id: 0|1}}) and flag caches."""
        self._view_overrides = {k: dict(v) for k, v in (overrides or {}).items() if v}
        self.view_overrides_changed()

    def view_overrides_changed(self):
        """Invalidate every cache that bakes visibility in at build time."""
        self.invalidate_area_vbo()
        self.invalidate_animation_cache()
        self._anim_vbo_built = False
        self._ltha_vbo_built = False
        self._ltha_hinge_cache = None

    def _vo_state(self, kind, oid):
        d = self._view_overrides.get(kind)
        if not d:
            return 2
        return d.get(oid, 2)

    def _pickable(self, kind, oid):
        """Ghosted / hidden objects are inert: not hoverable, not selectable."""
        return self._vo_state(kind, oid) == 2

    def _node_vis(self, n):
        return min(self._get_visibility_state(n.x, n.y, n.z), self._vo_state('node', n.id))

    def _end_states(self, kind, obj, oid=None):
        """(state_i, state_j) of a two-node object: plane state of each end,
        capped by the object's own user state."""
        u = self._vo_state(kind, obj.id if oid is None else oid)
        a, b = obj.node_i, obj.node_j
        return (min(self._get_visibility_state(a.x, a.y, a.z), u),
                min(self._get_visibility_state(b.x, b.y, b.z), u))

    def _add_vo_ghost_line(self, pts):
        """Faint translucent polyline for a ghosted tendon / cable."""
        item = gl.GLLinePlotItem(pos=np.asarray(pts, dtype=np.float32),
                                 color=(0.5, 0.5, 0.5, 0.35), width=2.0,
                                 mode='line_strip', antialias=True)
        item.setGLOptions('translucent')
        self.addItem(item)
        self.element_items.append(item)

    def _get_visibility_state(self, x, y, z):
        if self.active_view_plane is None:
            return 2

        axis = self.active_view_plane['axis']
        val = self.active_view_plane['value']
        
        tol = 0.005 

        current_val = {'x': x, 'y': y, 'z': z}[axis]

        if abs(current_val - val) < tol:
            return 2                    

        return 1 if self.show_ghost_structure else 0

    def apply_deformation_fast(self, model, sel_elems=None, sel_nodes=None):
        """Re-draw after a deformed-shape / scale / contour / shadow change WITHOUT the
        heavy bookkeeping of a model edit: geometry caches are kept, only the
        deformation-dependent buffers are refreshed."""
        self._deform_toggle = True
        try:
            self._force_draw_model(model, sel_elems, sel_nodes)
        finally:
            self._deform_toggle = False

    def refresh_supports_only(self):
        """Rebuild ONLY the support / spring / link glyphs (no grids, frames, loads, slabs...).
        Used after a restraint or spring assignment, where nothing else in the scene changed."""
        if getattr(self, 'ltha_mode', False) or not getattr(self, 'current_model', None):
            return
        self._last_support_rebuild_scale = None                                               
        self._boundary_node_cache = None                                                      
        self._rebuild_support_items()
        self.update()

    def _boundary_nodes_sparse(self, model):
        """Only the nodes build_boundary_visuals actually cares about: nodes with
        restraints / springs, plus nodes referenced by links.  Cached so a zoom does
        not have to walk every node of a huge model in Python."""
        nodes = model.nodes
        links = getattr(model, 'links', {}) or {}
        key = (id(model), len(nodes), len(links))
        c = self._boundary_node_cache
        if c is not None and c[0] == key:
            return c[1]
        sparse = {}
        for nid, n in nodes.items():
            r = getattr(n, 'restraints', None)
            if (r is not None and any(r)) or getattr(n, 'spring_matrix', None) is not None:
                sparse[nid] = n
        for lk in links.values():
            for nid in lk.get('nodes', ()):
                n = nodes.get(nid) or nodes.get(str(nid))
                if n is not None:
                    sparse[nid] = n
        self._boundary_node_cache = (key, sparse)
        return sparse

    def _rebuild_support_items(self, _from_zoom=False):
        """Rebuild support meshes with current zoom level — keeps symbols screen-size-stable."""
        if getattr(self, 'ltha_mode', False):
                                                                      
            return

        if not self.current_model or not getattr(self, 'show_supports', True):
            _old = set(map(id, self._support_items))
            for item in self._support_items:
                try: self.removeItem(item)
                except Exception: pass
            self._support_items.clear()
            self.node_items = [item for item in self.node_items if id(item) not in _old]
            return

        scale = self._screen_scale()

        last_scale = self._last_support_rebuild_scale
        if last_scale is not None and last_scale > 0:
            rel_change = abs(scale - last_scale) / last_scale
            if rel_change < 0.02:
                return

        self._last_support_rebuild_scale = scale

        _old = set(map(id, self._support_items))
        for item in self._support_items:
            try: self.removeItem(item)
            except Exception: pass
        self._support_items.clear()

        self.node_items = [item for item in self.node_items if id(item) not in _old]

        _src_nodes = self._boundary_nodes_sparse(self.current_model)
        visible_nodes = {nid: n for nid, n in _src_nodes.items() if self._node_vis(n) == 2}
        links_dict = {k: v for k, v in getattr(self.current_model, 'links', {}).items() if self._vo_state('link', k) == 2}
        link_props = getattr(self.current_model, 'link_properties', {})
        
        mesh_item, line_item = build_boundary_visuals(
            visible_nodes, 
            links_dict=links_dict, 
            link_props=link_props, 
            scale=scale,
            **self._boundary_visuals_kwargs(self.current_model)
        )
        
        if mesh_item:
            self.addItem(mesh_item)
            self._support_items.append(mesh_item)
            self.node_items.append(mesh_item)
            
        if line_item:
            self.addItem(line_item)
            self._support_items.append(line_item)
            self.node_items.append(line_item)
            
    def _draw_loads(self, model):
        """
        Visualizes Nodal Loads.
        - Always: Draws Arrow.
        - Selected: Draws Text Label with Units.
        """
        if not model.loads: return
        if not self.show_loads: return
        if self.load_type_filter == "frame": return 
        sel_set = set(self.selected_node_ids)
        
        arrow_lines = []
        arrow_colors = []
        
        L = 2.0; H = 0.5; W = 0.2                           

        AXIS_X = np.array([1.0, 0.0, 0.0])
        AXIS_Y = np.array([0.0, 1.0, 0.0])
        AXIS_Z = np.array([0.0, 0.0, 1.0])
        PERP_X = AXIS_X
        PERP_Z = AXIS_Z
        c_black = self._theme_ink_color()

        def add_arrow(pt, direction, color, is_moment):
            if is_moment:
                tail = pt
                tip = pt + direction * L
            else:
                tip = pt
                tail = pt - direction * L

            arrow_lines.append(tail)
            arrow_lines.append(tip)
            arrow_colors.append(color)
            arrow_colors.append(color)
            
            def add_head(base_pt):
                if abs(direction[2]) > 0.9: perp = PERP_X
                elif abs(direction[1]) > 0.9: perp = PERP_X
                else: perp = PERP_Z
                w_vec = perp * W
                base = base_pt - (direction * H)
                arrow_lines.append(base_pt); arrow_lines.append(base + w_vec)
                arrow_lines.append(base_pt); arrow_lines.append(base - w_vec)
                for _ in range(4): arrow_colors.append(color)

            add_head(tip)             
            if is_moment:
                add_head(tip - (direction * (H * 0.8)))

        for load in model.loads:
            if not hasattr(load, 'node_id'): continue
            if self.visible_load_patterns and load.pattern_name not in self.visible_load_patterns: continue

            node = model.nodes.get(load.node_id)
            if not node: continue
                                                                           
            if self._node_vis(node) != 2: continue
            
            origin = np.array([node.x, node.y, node.z])
            is_selected = (node.id in sel_set)

            def process_component(val, axis_vec, color, is_moment, l_type=None):
                if abs(val) > 0:
                    d = axis_vec * (1 if val > 0 else -1)
                    add_arrow(origin, d, color, is_moment)
                    
                    if is_selected:
                        if l_type is None:
                            l_type = "Moment" if is_moment else "Force"
                        self._add_load_label(origin, d, val, l_type, color, owner_id=node.id, owner_type='node')

            if hasattr(load, 'ux'):
                                                            
                c_disp = c_black
                process_component(load.uz, AXIS_Z, c_disp, False, "Displacement")
                process_component(load.ux, AXIS_X, c_disp, False, "Displacement")
                process_component(load.uy, AXIS_Y, c_disp, False, "Displacement")

                process_component(load.rz, AXIS_Z, c_disp, True, "Rotation")
                process_component(load.rx, AXIS_X, c_disp, True, "Rotation")
                process_component(load.ry, AXIS_Y, c_disp, True, "Rotation")
            else:
                                                 
                process_component(getattr(load, 'fz', 0), AXIS_Z, c_black, False, "Force")
                process_component(getattr(load, 'fx', 0), AXIS_X, c_black, False, "Force")
                process_component(getattr(load, 'fy', 0), AXIS_Y, c_black, False, "Force")

                process_component(getattr(load, 'mz', 0), AXIS_Z, c_black, True, "Moment")
                process_component(getattr(load, 'mx', 0), AXIS_X, c_black, True, "Moment")
                process_component(getattr(load, 'my', 0), AXIS_Y, c_black, True, "Moment")

        if arrow_lines:
                                                                             
            self._pending_load_line_pos.extend(arrow_lines)
            self._pending_load_line_colors.extend(arrow_colors)

    def _draw_reactions(self, model):
        """Visualizes Joint Reactions (Analysis Mode only)."""
        if not self.reaction_data:
            return

        arrow_lines = []
        arrow_colors = []

        L = 2.0; H = 0.5; W = 0.2
        c_black = self._theme_ink_color()

        def add_arrow(pt, direction, color, is_moment):
            if is_moment:
                tail = pt
                tip = pt + direction * L
            else:
                tip = pt
                tail = pt - direction * L

            arrow_lines.append(tail)
            arrow_lines.append(tip)
            arrow_colors.append(color)
            arrow_colors.append(color)

            def add_head(base_pt):
                if abs(direction[2]) > 0.9: perp = np.array([1.0, 0.0, 0.0])
                elif abs(direction[1]) > 0.9: perp = np.array([1.0, 0.0, 0.0])
                else: perp = np.array([0.0, 0.0, 1.0])
                w_vec = perp * W
                base = base_pt - (direction * H)
                arrow_lines.append(base_pt); arrow_lines.append(base + w_vec)
                arrow_lines.append(base_pt); arrow_lines.append(base - w_vec)
                for _ in range(4): arrow_colors.append(color)

            add_head(tip)
            if is_moment:
                add_head(tip - (direction * (H * 0.8)))

        for nid, dofs in self.reaction_data.items():
            node = model.nodes.get(nid)
                                                                 
            if node is None and str(nid).isdigit():
                node = model.nodes.get(int(nid))
            if not node:
                continue

            if self._node_vis(node) != 2:
                continue

            origin = np.array([node.x, node.y, node.z])

            def process_component(val, axis_vec, is_moment):
                
                if getattr(self, 'reaction_sign_convention', 'ground_on_structure') == 'ground_on_structure':
                    val = -val
                
                if abs(val) > 1e-9:
                    d = axis_vec * (1 if val > 0 else -1)
                    add_arrow(origin, d, c_black, is_moment)
                    l_type = "Moment" if is_moment else "Force"
                    self._add_load_label(origin, d, val, l_type, c_black, owner_id=node.id, owner_type='node')

            f1, f2, f3, m1, m2, m3 = dofs[:6]
            process_component(f1, np.array([1.0, 0.0, 0.0]), False)
            process_component(f2, np.array([0.0, 1.0, 0.0]), False)
            process_component(f3, np.array([0.0, 0.0, 1.0]), False)
            process_component(m1, np.array([1.0, 0.0, 0.0]), True)
            process_component(m2, np.array([0.0, 1.0, 0.0]), True)
            process_component(m3, np.array([0.0, 0.0, 1.0]), True)

        if arrow_lines:
            self._pending_load_line_pos.extend(arrow_lines)
            self._pending_load_line_colors.extend(arrow_colors)

    def _add_load_label(self, origin, direction, val, l_type, color, owner_id=None, owner_type=None):
        if l_type == "Moment":
            m_scale = unit_registry.force_scale * unit_registry.length_scale
            display_val = abs(val) * m_scale
            unit_str = f"{unit_registry.force_unit_name}.{unit_registry.length_unit_name}"
        elif l_type == "Displacement":
            display_val = unit_registry.to_display_length(abs(val))
            unit_str = unit_registry.current_unit_label.split(',')[1].strip() if ',' in unit_registry.current_unit_label else "m"
        elif l_type == "Rotation":
            display_val = abs(val)
            unit_str = "rad"
        else:
            display_val = unit_registry.to_display_force(abs(val))
            unit_str = unit_registry.force_unit_name
            
        if l_type == "Moment" or l_type == "Rotation":
            label_pos = origin + (direction * 1.6)
        else:
            label_pos = origin - (direction * 1.6)
        
        v_right = direction.copy()
        if v_right[0] < -0.01: v_right = -v_right                                  
        
        v_up = np.array([0.0, 0.0, 1.0])
        if abs(v_right[2]) > 0.99:                            
            v_up = np.array([1.0, 0.0, 0.0])

        label_offset = 0.05                           
        moment_extra = 0.30                                                       
        if l_type == "Moment":
            label_pos = label_pos - (v_up * (label_offset + moment_extra))
        else:
            label_pos = label_pos + (v_up * label_offset)

        if not hasattr(self, 'load_labels'): self.load_labels = []
        self.load_labels.append({
            'owner_id': owner_id, 'owner_type': owner_type,
            'pos_3d': label_pos.tolist(),                               
            'text': f"{display_val:.2f} {unit_str}",  
            'val': val,
            'color': list(color[:4]) if len(color) >= 4 else [0,0,0,1],
            'v_right': v_right.tolist(),
            'v_up': v_up.tolist(),
            'align': 'center',
            'text_height': 0.20
        })

    def _screen_scale(self):
        """
        Returns world-units-per-pixel for the current camera state.
        Multiply by a target pixel size to get a zoom-invariant world length.
        """
        dist = self.opts.get('distance', 40)
        fov  = self.opts.get('fov', 60)
        h_px = max(self.height(), 1)
        if fov and fov > 0:
            visible_h = 2.0 * dist * math.tan(math.radians(fov) / 2.0)
        else:
                                                                                      
            visible_h = dist * 2.0
        return visible_h / h_px

    def _rebuild_axis_items(self):
        """Remove any previously added GL axis items. Axes are now drawn as a
        2D painter overlay in paintEvent so they always render on top."""
        for item in self._axis_items:
            try:
                self.removeItem(item)
            except Exception:
                pass
        self._axis_items.clear()

    def _draw_axis_overlay(self, painter, mvp, w, h):
        """
        Draw X/Y/Z axis lines as a 2D QPainter overlay so they are always
        visible on top of the mesh.  Projects the world-space origin and each
        unit axis point through the current MVP, then draws fixed-length 60 px
        lines in screen space — zoom-invariant and never occluded.
        """
        if not self.current_model:
            return

        origin_s = self._project_to_screen(0, 0, 0, mvp, w, h)
        if not origin_s:
            return
        ox, oy = origin_s

        AXIS_PX  = 80                                          
        LABEL_PAD = 6
        HEAD_LEN = 10                                                                 
        HEAD_W   = 5                                                                  

        from PyQt6.QtGui import QFont, QColor, QPen, QPolygonF, QBrush
        from PyQt6.QtCore import QPointF
        ax_font = QFont("Consolas", 12, QFont.Weight.Bold)

        axes = [
            ((1, 0, 0), QColor(255,  50,  50), "X"),
            ((0, 1, 0), QColor( 50, 200,  50), "Y"),
            ((0, 0, 1), QColor( 50,  50, 255), "Z"),
        ]

        for (ax, ay, az), color, label in axes:
            tip_s = self._project_to_screen(ax, ay, az, mvp, w, h)
            if not tip_s:
                continue
            dx = tip_s[0] - ox
            dy = tip_s[1] - oy
            length = math.sqrt(dx * dx + dy * dy)
            if length < 1e-6:
                continue

            ux, uy = dx / length, dy / length
            ex = ox + ux * AXIS_PX
            ey = oy + uy * AXIS_PX

            painter.setPen(QPen(color, 2))
            painter.drawLine(int(ox), int(oy), int(ex), int(ey))

            perp_x, perp_y = -uy, ux
            base_x = ex - ux * HEAD_LEN
            base_y = ey - uy * HEAD_LEN
            head_tip   = QPointF(ex, ey)
            head_side1 = QPointF(base_x + perp_x * HEAD_W, base_y + perp_y * HEAD_W)
            head_side2 = QPointF(base_x - perp_x * HEAD_W, base_y - perp_y * HEAD_W)

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(color))
            painter.drawPolygon(QPolygonF([head_tip, head_side1, head_side2]))
            painter.setBrush(Qt.BrushStyle.NoBrush)

            painter.setFont(ax_font)
            painter.setPen(color)
            painter.drawText(int(ex) + LABEL_PAD, int(ey) + LABEL_PAD, label)

    def _generate_circle_pts(self, center, radius, axis='z', segments=32):
        """Generates paired points for a perfect circle using GL_LINES."""
        pts = []
        for i in range(segments):
            t1 = 2.0 * math.pi * i / segments
            t2 = 2.0 * math.pi * (i + 1) / segments
            
            if axis == 'z':
                p1 = [center[0] + radius * math.cos(t1), center[1] + radius * math.sin(t1), center[2]]
                p2 = [center[0] + radius * math.cos(t2), center[1] + radius * math.sin(t2), center[2]]
            elif axis == 'y':
                p1 = [center[0] + radius * math.cos(t1), center[1], center[2] + radius * math.sin(t1)]
                p2 = [center[0] + radius * math.cos(t2), center[1], center[2] + radius * math.sin(t2)]
            elif axis == 'x':
                p1 = [center[0], center[1] + radius * math.cos(t1), center[2] + radius * math.sin(t1)]
                p2 = [center[0], center[1] + radius * math.cos(t2), center[2] + radius * math.sin(t2)]
            
            pts.extend([p1, p2])
        return pts
    
    def _add_grid_bubble(self, center, radius, text, plane_axis, color=None):
        """Prepares the grid ID text for the SDF GPU pipeline (Perfect Center)."""
        if not hasattr(self, 'grid_labels'):
            self.grid_labels = []
            
        v_right = np.array([1.0, 0.0, 0.0])
        v_up = np.array([0.0, 1.0, 0.0])
        
        if plane_axis == 'y': 
            v_up = np.array([0.0, 0.0, 1.0])
        elif plane_axis == 'x': 
            v_right = np.array([0.0, 1.0, 0.0])
            v_up = np.array([0.0, 0.0, 1.0])

        t_height = radius * 1.15
        text_str = str(text)
        n_chars = len(text_str)

        h_offset = t_height * (0.725 + 0.275 * n_chars)
        v_offset = t_height * 0.9
        adj_center = center - (v_right * h_offset) - (v_up * v_offset)

        self.grid_labels.append({
            'owner_id': text, 'owner_type': 'grid',
            'pos_3d': adj_center.tolist(),
            'text': text_str,
            'val': 0,
            'color': list(color) if color else [0.15, 0.45, 0.85, 1.0],
            'v_right': v_right.tolist(),
            'v_up': v_up.tolist(),
            'align': 'left',                                                     
            'text_height': t_height
        })

    def _add_grid_dimension(self, center, text, plane_axis, t_height, v_right, v_up, color=None):
        """Adds the spacing dimension text between grid lines."""
        if not hasattr(self, 'grid_labels'):
            self.grid_labels = []

        vr = np.array(v_right)
        vu = np.array(v_up)
        text_str = str(text)
        n_chars = len(text_str)

        h_offset = t_height * (0.725 + 0.275 * n_chars)
        v_offset = t_height * 0.9
        adj_center = center - (vr * h_offset) - (vu * v_offset)

        self.grid_labels.append({
            'owner_id': text, 'owner_type': 'grid_dim',
            'pos_3d': adj_center.tolist(),
            'text': text_str,
            'val': 0,
            'color': list(color) if color else [0.2, 0.5, 0.8, 1.0],
            'v_right': v_right,
            'v_up': v_up,
            'align': 'left',
            'text_height': t_height
        })

    def _draw_reference_grids(self, model):
        grid = model.grid
        if not grid: return

        def get_vis(lines_attr, fallback):
            if not lines_attr: return fallback
            if isinstance(lines_attr[0], dict): return [i['ord'] for i in lines_attr if i.get('visible', True)]
            return lines_attr

        def get_full_data(lines_attr, fallback):
            if not lines_attr: return [{'id': str(i+1), 'ord': v, 'bubble': 'End'} for i, v in enumerate(fallback)]
            if isinstance(lines_attr[0], dict): return [i for i in lines_attr if i.get('visible', True)]
            return [{'id': str(i+1), 'ord': v, 'bubble': 'End'} for i, v in enumerate(lines_attr)]

        vis_x = get_vis(getattr(grid, 'x_lines', []), getattr(grid, 'x_grids', []))
        vis_y = get_vis(getattr(grid, 'y_lines', []), getattr(grid, 'y_grids', []))
        vis_z = get_vis(getattr(grid, 'z_lines', []), getattr(grid, 'z_grids', []))

        if not vis_x or not vis_y or not vis_z: return

        z_min, z_max = min(vis_z), max(vis_z)
        x_min, x_max = min(vis_x), max(vis_x)
        y_min, y_max = min(vis_y), max(vis_y)

        from core.grid import resolve_grid_style, hex_to_rgba
        gs = resolve_grid_style(getattr(grid, 'style', None), self._canvas_is_dark())
        self._grid_width_lines = gs['width_lines']
        self._grid_width_floor = gs['width_floor']
        bub_text_rgba = hex_to_rgba(gs['bub_text'], 1.0)                      
        dim_text_rgba = hex_to_rgba(gs['dim'], 1.0)                                   

        bright_pos, dim_pos = [], []
        
        is_3d = self.active_view_plane is None
        active_axis = self.active_view_plane['axis'] if not is_3d else 'z'
        active_val = self.active_view_plane['value'] if not is_3d else z_min

        def is_on_active_plane(p1, p2):
            if is_3d: return False 
            axis = self.active_view_plane['axis']
            val = self.active_view_plane['value']
            tol = 0.001
            if axis == 'x': return abs(p1[0] - val) < tol and abs(p2[0] - val) < tol
            if axis == 'y': return abs(p1[1] - val) < tol and abs(p2[1] - val) < tol
            if axis == 'z': return abs(p1[2] - val) < tol and abs(p2[2] - val) < tol
            return False

        for x in vis_x:
            for y in vis_y:
                p1 = [x, y, z_min]; p2 = [x, y, z_max]
                if is_on_active_plane(p1, p2): bright_pos.extend([p1, p2])
                else: dim_pos.extend([p1, p2])
        for z in vis_z:
            for y in vis_y:
                p1 = [x_min, y, z]; p2 = [x_max, y, z]
                if is_on_active_plane(p1, p2): bright_pos.extend([p1, p2])
                else: dim_pos.extend([p1, p2])
        for z in vis_z:
            for x in vis_x:
                p1 = [x, y_min, z]; p2 = [x, y_max, z]
                if is_on_active_plane(p1, p2): bright_pos.extend([p1, p2])
                else: dim_pos.extend([p1, p2])

        graph_paper_pos, graph_major_pos = [], []
        if active_axis == 'z' and gs['show_floor']:
            span_x = max(30.0, (x_max - x_min) * 1.5)
            span_y = max(30.0, (y_max - y_min) * 1.5)
            cx, cy = (x_max + x_min)/2.0, (y_max + y_min)/2.0
            
            u_name = unit_registry.length_unit_name
            if u_name in ['mm']: auto_step = unit_registry.from_display_length(1000.0)
            elif u_name in ['cm', 'in']: auto_step = unit_registry.from_display_length(100.0)
            else: auto_step = unit_registry.from_display_length(1.0)
            if auto_step < 0.1: auto_step = 1.0 
            
            step = gs['floor_spacing'] if gs['floor_spacing'] > 0 else auto_step
                                                                             
            if (2 * span_x) / step > 1500 or (2 * span_y) / step > 1500:
                step = auto_step

            ix0, ix1 = math.floor((cx - span_x)/step), math.ceil((cx + span_x)/step)
            iy0, iy1 = math.floor((cy - span_y)/step), math.ceil((cy + span_y)/step)
            gx_start, gx_end = ix0 * step, ix1 * step
            gy_start, gy_end = iy0 * step, iy1 * step
            major_n = gs['floor_major_every']

            for ix in range(ix0, ix1 + 1):
                gx = ix * step
                seg = [[gx, gy_start, active_val], [gx, gy_end, active_val]]
                if major_n > 0 and ix % major_n == 0: graph_major_pos.extend(seg)
                else: graph_paper_pos.extend(seg)
            for iy in range(iy0, iy1 + 1):
                gy = iy * step
                seg = [[gx_start, gy, active_val], [gx_end, gy, active_val]]
                if major_n > 0 and iy % major_n == 0: graph_major_pos.extend(seg)
                else: graph_paper_pos.extend(seg)

        bubble_circ_pos, bubble_lines, dim_lines = [], [], []
        self.grid_labels = []
        
        x_data = get_full_data(getattr(grid, 'x_lines', []), getattr(grid, 'x_grids', []))
        y_data = get_full_data(getattr(grid, 'y_lines', []), getattr(grid, 'y_grids', []))
        
        b_scale = getattr(grid, 'bubble_size', 1.25)
        bubble_radius = b_scale * 0.45
                                                                             
        ext = getattr(grid, 'bubble_extension', b_scale * 2.5)
        self._bubble_line_width = getattr(grid, 'bubble_line_width', 1.5)
        _ew = getattr(grid, 'bubble_ext_line_width', None)
        self._bubble_ext_width = float(_ew) if _ew else self._bubble_line_width
        tick = bubble_radius * 0.25
        
        def format_dist(d):
            disp_d = unit_registry.to_display_length(d)
            u_str = unit_registry.length_unit_name
            if not u_str: u_str = "m" 
            if abs(disp_d - round(disp_d)) < 1e-3:
                return f"{int(round(disp_d))} {u_str}"
            return f"{disp_d:.2f} {u_str}"
            
        if active_axis == 'z':
            for i, d in enumerate(x_data):
                x = d['ord']
                bub_loc = d.get('bubble', 'End')
                
                if bub_loc in ['End', 'Both']:
                    bubble_lines.extend([[x, y_max, active_val], [x, y_max + ext, active_val]])
                    center = np.array([x, y_max + ext + bubble_radius, active_val])
                    bubble_circ_pos.extend(self._generate_circle_pts(center, bubble_radius, 'z'))
                    self._add_grid_bubble(center, bubble_radius, d['id'], 'z', color=bub_text_rgba)
                    
                    if i < len(x_data) - 1:
                        next_x = x_data[i+1]['ord']
                        dist = abs(next_x - x)
                        dim_y = y_max + ext * 0.6
                        dim_lines.extend([[x, dim_y, active_val], [next_x, dim_y, active_val]])
                        dim_lines.extend([[x, dim_y-tick, active_val], [x, dim_y+tick, active_val]])
                        dim_lines.extend([[next_x, dim_y-tick, active_val], [next_x, dim_y+tick, active_val]])
                        
                        dim_center = np.array([(x + next_x)/2.0, dim_y + bubble_radius*1.1, active_val])
                        self._add_grid_dimension(dim_center, format_dist(dist), 'z', bubble_radius * 0.8, [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], color=dim_text_rgba)

                if bub_loc in ['Start', 'Both']:
                    bubble_lines.extend([[x, y_min, active_val], [x, y_min - ext, active_val]])
                    center = np.array([x, y_min - ext - bubble_radius, active_val])
                    bubble_circ_pos.extend(self._generate_circle_pts(center, bubble_radius, 'z'))
                    self._add_grid_bubble(center, bubble_radius, d['id'], 'z', color=bub_text_rgba)
                    
                    if i < len(x_data) - 1:
                        next_x = x_data[i+1]['ord']
                        dist = abs(next_x - x)
                        dim_y = y_min - ext * 0.6
                        dim_lines.extend([[x, dim_y, active_val], [next_x, dim_y, active_val]])
                        dim_lines.extend([[x, dim_y-tick, active_val], [x, dim_y+tick, active_val]])
                        dim_lines.extend([[next_x, dim_y-tick, active_val], [next_x, dim_y+tick, active_val]])
                        
                        dim_center = np.array([(x + next_x)/2.0, dim_y - bubble_radius*1.1, active_val])
                        self._add_grid_dimension(dim_center, format_dist(dist), 'z', bubble_radius * 0.8, [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], color=dim_text_rgba)

            for i, d in enumerate(y_data):
                y = d['ord']
                bub_loc = d.get('bubble', 'End')
                
                if bub_loc in ['End', 'Both']:
                    bubble_lines.extend([[x_max, y, active_val], [x_max + ext, y, active_val]])
                    center = np.array([x_max + ext + bubble_radius, y, active_val])
                    bubble_circ_pos.extend(self._generate_circle_pts(center, bubble_radius, 'z'))
                    self._add_grid_bubble(center, bubble_radius, d['id'], 'z', color=bub_text_rgba)
                    
                    if i < len(y_data) - 1:
                        next_y = y_data[i+1]['ord']
                        dist = abs(next_y - y)
                        dim_x = x_max + ext * 0.6
                        dim_lines.extend([[dim_x, y, active_val], [dim_x, next_y, active_val]])
                        dim_lines.extend([[dim_x-tick, y, active_val], [dim_x+tick, y, active_val]])
                        dim_lines.extend([[dim_x-tick, next_y, active_val], [dim_x+tick, next_y, active_val]])
                        
                        dim_center = np.array([dim_x + bubble_radius*1.1, (y + next_y)/2.0, active_val])
                        self._add_grid_dimension(dim_center, format_dist(dist), 'z', bubble_radius * 0.8, [0.0, 1.0, 0.0], [-1.0, 0.0, 0.0], color=dim_text_rgba)

                if bub_loc in ['Start', 'Both']:
                    bubble_lines.extend([[x_min, y, active_val], [x_min - ext, y, active_val]])
                    center = np.array([x_min - ext - bubble_radius, y, active_val])
                    bubble_circ_pos.extend(self._generate_circle_pts(center, bubble_radius, 'z'))
                    self._add_grid_bubble(center, bubble_radius, d['id'], 'z', color=bub_text_rgba)
                    
                    if i < len(y_data) - 1:
                        next_y = y_data[i+1]['ord']
                        dist = abs(next_y - y)
                        dim_x = x_min - ext * 0.6
                        dim_lines.extend([[dim_x, y, active_val], [dim_x, next_y, active_val]])
                        dim_lines.extend([[dim_x-tick, y, active_val], [dim_x+tick, y, active_val]])
                        dim_lines.extend([[dim_x-tick, next_y, active_val], [dim_x+tick, next_y, active_val]])
                        
                        dim_center = np.array([dim_x - bubble_radius*1.1, (y + next_y)/2.0, active_val])
                        self._add_grid_dimension(dim_center, format_dist(dist), 'z', bubble_radius * 0.8, [0.0, 1.0, 0.0], [-1.0, 0.0, 0.0], color=dim_text_rgba)

        a_inactive = gs['a_line'] if is_3d else gs['a_line_2d']
        self._push_grid_lines(dim_pos,        hex_to_rgba(gs['line'],   a_inactive),   'a')
        self._push_grid_lines(bright_pos,     hex_to_rgba(gs['active'], gs['a_active']), 'a')
        self._push_grid_lines(dim_lines,      hex_to_rgba(gs['dim'],    gs['a_dim']),    'a')
        self._push_grid_lines(graph_paper_pos, hex_to_rgba(gs['floor'],       gs['a_floor']), 'b')
        self._push_grid_lines(graph_major_pos, hex_to_rgba(gs['floor_major'], gs['a_major']), 'b')

        self._push_bubble_lines(bubble_lines,     hex_to_rgba(gs['bub_line'],   0.9))
        self._bubble_split = len(self._pending_bubble_line_pos)                                      
        self._push_bubble_lines(bubble_circ_pos,  hex_to_rgba(gs['bub_circle'], 1.0))

        self._rebuild_axis_items()
        
    def get_snap_point(self, mouse_x, mouse_y):
        self._snap_screen_xy = None
        if not self.snapping_enabled:
            self.snap_ring.setVisible(False)
            self.snap_dot.setVisible(False)
            self.snap_text.setVisible(False)
            return None
        if not self.current_model: return None

        grids = self.current_model.grid
        
        if self.active_view_plane:
            val = self.active_view_plane['value']
            axis = self.active_view_plane['axis']
            z_range = [val] if axis == 'z' else grids.z_grids
            y_range = [val] if axis == 'y' else grids.y_grids
            x_range = [val] if axis == 'x' else grids.x_grids
        else:
            z_range = grids.z_grids
            y_range = grids.y_grids
            x_range = grids.x_grids

        chunks = []
        if self.snap_modes.get('grid', True):
            xs = np.array(x_range, dtype=np.float32)
            ys = np.array(y_range, dtype=np.float32)
            zs = np.array(z_range, dtype=np.float32)
            gx, gy, gz = np.meshgrid(xs, ys, zs, indexing='ij')
            chunks.append(np.column_stack([gx.ravel(), gy.ravel(), gz.ravel()]))

        extra = self._snap_extra_points(self.current_model)
        if len(extra):
            if self.active_view_plane:
                _ax = {'x': 0, 'y': 1, 'z': 2}[self.active_view_plane['axis']]
                extra = extra[np.abs(extra[:, _ax] - float(self.active_view_plane['value'])) < 1e-4]
            if len(extra):
                chunks.append(extra)

        if not chunks:
            self.snap_ring.setVisible(False)
            self.snap_dot.setVisible(False)
            self.snap_text.setVisible(False)
            return None
        pts_xyz = np.vstack(chunks).astype(np.float32)

        if len(pts_xyz) == 0: return None

        view_w = self.width()
        view_h = self.height()
        full_area = (0, 0, view_w, view_h)
        m_view = self.viewMatrix()
        m_proj = self.projectionMatrix(region=full_area, viewport=full_area)

        _snap_key = (m_view.data(), view_w, view_h)
        if getattr(self, '_snap_cache_key', None) != _snap_key:
            mvp = m_proj * m_view
            self._snap_mvp_matrix = np.array(mvp.data(), dtype=np.float32).reshape(4, 4).T
            self._snap_inv_view   = np.linalg.inv(np.array(m_view.data(), dtype=np.float32).reshape(4, 4).T)
            self._snap_cache_key  = _snap_key

        mvp_matrix = self._snap_mvp_matrix
        inv_view   = self._snap_inv_view

        ones  = np.ones((len(pts_xyz), 1), dtype=np.float32)
        pts_h = np.hstack([pts_xyz, ones])           
        clip  = pts_h @ mvp_matrix.T                 

        valid = clip[:, 3] > 0
        if not valid.any():
            self.snap_ring.setVisible(False)
            self.snap_dot.setVisible(False)
            self.snap_text.setVisible(False)
            return None

        clip_v = clip[valid]
        pts_v  = pts_xyz[valid]

        w_inv    = 1.0 / clip_v[:, 3]
        screen_x = (clip_v[:, 0] * w_inv + 1.0) * view_w * 0.5
        screen_y = (1.0 - clip_v[:, 1] * w_inv) * view_h * 0.5

        dists = np.hypot(screen_x - mouse_x, screen_y - mouse_y)
        idx   = int(np.argmin(dists))

        best_point = None
        if dists[idx] < self.snap_radius:
            best_point = tuple(float(v) for v in pts_v[idx])
            self._snap_screen_xy = (float(screen_x[idx]), float(screen_y[idx]))

        if best_point:
            bx, by, bz = best_point
            cam_pos = inv_view[:3, 3]
            dir_vec = np.array([cam_pos[0]-bx, cam_pos[1]-by, cam_pos[2]-bz])
            dist_cam = np.linalg.norm(dir_vec)
            
            if dist_cam > 0:
                norm_dir = dir_vec / dist_cam
                                                               
                nx, ny, nz = bx + norm_dir[0]*0.3, by + norm_dir[1]*0.3, bz + norm_dir[2]*0.3
            else:
                nx, ny, nz = bx, by, bz
                norm_dir = np.array([0,0,1])

            world_up = np.array([0, 0, 1])
            if abs(np.dot(world_up, norm_dir)) > 0.99: 
                world_up = np.array([0, 1, 0])                       
            
            right = np.cross(world_up, norm_dir)
            right /= np.linalg.norm(right)
            
            up = np.cross(norm_dir, right)
            up /= np.linalg.norm(up)
            
            radius = 0.4            
            segments = 16
            angles = np.linspace(0, 2*np.pi, segments + 1)
            ring_pts = []
            
            center = np.array([nx, ny, nz])
            
            for ang in angles:
                                                             
                pt = center + radius * (np.cos(ang) * right + np.sin(ang) * up)
                ring_pts.append(pt)

            self.snap_ring.setData(pos=np.array(ring_pts), color=(1, 0, 0, 0.4), width=1.5)
            self.snap_ring.setVisible(True)

            self.snap_dot.setData(pos=np.array([[nx, ny, nz]]), color=(1, 1, 0, 0.5), size=5)                
            self.snap_dot.setVisible(True)
            
            coord_str = f"X: {bx:.2f}  Y: {by:.2f}  Z: {bz:.2f}"
            self.snap_text.setData(pos=np.array([nx + 0.3, ny + 0.3, nz + 0.3]), text=coord_str)
            self.snap_text.setVisible(True)
            
        else:
            self.snap_ring.setVisible(False)
            self.snap_dot.setVisible(False)
            self.snap_text.setVisible(False)                              
        
        return best_point
    
    def _on_anim_frame(self, factor):
        self.anim_factor = factor

        if not self.view_deflected:
            return

        if not self.animation_manager.is_running:
                                                    
            self.vbo_manager.set_anim_factor(0.0)
            self._force_draw_model(
                self.current_model,
                self.selected_element_ids,
                self.selected_node_ids
            )
            return

        self.vbo_manager.set_anim_factor(factor)
        if self.selected_area_ids or getattr(self, 'hovered_area_id', None) is not None:
            self._rebuild_area_interior_lines()
        self.update()
        
    def load_ltha_history(self, npz_path, dt, accel=None):
        """
        Loads the LTHA time history from a .npz file saved by ltha_engine.
        accel can be:
          - None
          - a flat list (legacy single-direction)
          - a dict {"X": [...], "Y": [...], ...} (new multi-direction)
        """
                                                                                    
        self.clear_ltha_history()
        if accel is None:
            self.ltha_accel = None
        elif isinstance(accel, dict):
            self.ltha_accel = {d: np.array(v, dtype=np.float32)
                               for d, v in accel.items() if v}
        else:
                                                           
            self.ltha_accel = {"X": np.array(accel, dtype=np.float32)}

        self.ltha_current_step = 0
        self._accel_overlay_pixmap    = None                                          
        self._accel_overlay_size      = (0, 0)
        self._accel_overlay_last_step = -1
        try:
            with np.load(npz_path, allow_pickle=False) as data:
                history = {k[5:]: data[k] for k in data.files if k.startswith("node_")}
            if not history:
                raise ValueError("No nodal displacement history found")
            n_steps = next(iter(history.values())).shape[0]
            if n_steps < 1 or any(arr.shape != (n_steps, 6) for arr in history.values()):
                raise ValueError("Nodal histories must have a common (steps, 6) shape")
            dt = float(dt)
            if not np.isfinite(dt) or dt <= 0.0:
                raise ValueError("History time step must be finite and positive")
            if any(not np.isfinite(arr).all() for arr in history.values()):
                raise ValueError("Nodal history contains non-finite displacements")
            self.ltha_history = history
            self.ltha_n_steps = n_steps
            self.ltha_dt = dt
            self.ltha_mode = True
            self.invalidate_animation_cache()
            self._ltha_vbo_built = False
            print(f"[Canvas] LTHA history loaded: {self.ltha_n_steps} steps, dt={dt}s, "
                  f"{len(self.ltha_history)} nodes")
            return True
        except Exception as e:
            print(f"[Canvas] Failed to load LTHA history: {e}")
            self.clear_ltha_history()
            return False

    def clear_ltha_history(self):
        """Call when loading a different result or model."""
        self.ltha_history = None
        self.ltha_n_steps = 0
        self.ltha_mode = False
        self._ltha_loaded_case = None
        self._ltha_loaded_source = None
        for attr in ('ltha_tensor', 'ltha_node_map', 'ltha_engine'):
            if hasattr(self, attr):
                delattr(self, attr)
        self.ltha_accel = None
        self.ltha_highlight = None
        self._selection_ltha_live = False
        self.ltha_hinge_state_idx = None
        self._ltha_hinge_cache = None
        self.ltha_current_step = 0
        self._needs_ltha_vbo_update = False
        self._needs_hinge_refresh = False
        self._ltha_pending_t = 0
        self.invalidate_animation_cache()
        self._anim_vbo_built = False
        self._ltha_vbo_built = False

        if getattr(self, '_ltha_spring_plate_item', None) is not None:
            try:
                self.removeItem(self._ltha_spring_plate_item)
            except Exception:
                pass
            if self._ltha_spring_plate_item in self._support_items:
                self._support_items.remove(self._ltha_spring_plate_item)
            self._ltha_spring_plate_item = None

        if hasattr(self, 'vbo_manager') and self.vbo_manager.is_initialized:
            self.vbo_manager.upload_spring_geometry(np.array([]), np.array([]))

    def _on_ltha_frame(self, t_index):
        """
        Called by AnimationManager every frame in LTHA mode.
        CPU work only — stores pending timestep and sets a dirty flag.
        ALL GL uploads happen in paintGL where the context is guaranteed current.
        """
        if not self.ltha_history or not self.current_model:
            return

        t = max(0, min(t_index, self.ltha_n_steps - 1))
        self.ltha_current_step = t

        if not self.view_deflected:
            return

        if not getattr(self, '_ltha_vbo_built', False):
            if not self._build_ltha_vbo():
                return

        self._ltha_pending_t = t
        self._needs_ltha_vbo_update = True
        self.update()

    def refresh_deformed_playback(self):
        """Single entry point to re-sync the deformed mesh AND the hinge markers
        with the current step / scale / contour settings. Call after anything
        that changes them (dialog Apply / Normalize / scale / contour / toggle,
        or any static redraw while a step history is shown). Mesh and hinges are
        rebuilt in the same paint, from the same step and scale."""
        if not (self.view_deflected and getattr(self, 'ltha_mode', False)
                and self.ltha_history and self.current_model):
            return
        if not getattr(self, '_ltha_vbo_built', False):
            if not self._build_ltha_vbo():
                return
        self._ltha_pending_t = max(0, min(int(getattr(self, 'ltha_current_step', 0)),
                                          self.ltha_n_steps - 1))
        self._needs_ltha_vbo_update = True
        self._needs_hinge_refresh = True
        self.update()

    def _build_ltha_vbo(self):
        """Called ONCE on first LTHA frame to setup Engine."""
        if not self.ltha_history or not self.current_model:
            return False

        self.ltha_node_map = {str(nid): idx for idx, nid in enumerate(self.ltha_history.keys())}
        N_nodes = len(self.ltha_node_map)
        dummy_idx = N_nodes 
        self.ltha_tensor = np.zeros((N_nodes + 1, self.ltha_n_steps, 6), dtype=np.float32)
        
        for nid, hist_array in self.ltha_history.items():
            self.ltha_tensor[self.ltha_node_map[str(nid)]] = hist_array

        self._ltha_elements = [el for el in self.current_model.elements.values()
                               if self._vo_state('frame', el.id) == 2
                               and min(self._end_states('frame', el)) > 0]

        if len(self._ltha_elements) == 0:
            return False
        ("Allocating GPU Vertex Buffer Objects (VBOs) for Time History tensor...")
        self.ltha_engine = VectorizedLTHAEngine(len(self._ltha_elements))

        for i, el in enumerate(self._ltha_elements):
            p1 = np.array([el.node_i.x, el.node_i.y, el.node_i.z], dtype=np.float32)
            p2 = np.array([el.node_j.x, el.node_j.y, el.node_j.z], dtype=np.float32)
            self.ltha_engine.P1[i], self.ltha_engine.P2[i] = p1, p2
            self.ltha_engine.L[i, 0] = max(np.linalg.norm(p2 - p1), 1e-6)
                                                                                     
            self.ltha_engine.off_i[i, 0] = 0.0
            self.ltha_engine.off_j[i, 0] = 0.0
            self.ltha_engine.R[i] = np.vstack(self._get_consistent_axes(el))
            self.ltha_engine.idx_i[i] = self.ltha_node_map.get(str(el.node_i.id), dummy_idx)
            self.ltha_engine.idx_j[i] = self.ltha_node_map.get(str(el.node_j.id), dummy_idx)
            wire = getattr(el.section, 'color', [0.5, 0.5, 0.5, 1.0])
            self.ltha_engine.colors[i] = wire if len(wire) == 4 else list(wire) + [1.0]

        real_tensor = self.ltha_tensor[:N_nodes, :, :3]
        self.ltha_contour_ranges = {}
        for comp, comp_idx in (("Ux", 0), ("Uy", 1), ("Uz", 2)):
            vals = real_tensor[:, :, comp_idx]
            self.ltha_contour_ranges[(comp, False)] = (float(vals.min()), float(vals.max()))
            self.ltha_contour_ranges[(comp, True)] = (0.0, float(np.abs(vals).max()))
        resultant = np.linalg.norm(real_tensor, axis=2)
        res_range = (float(resultant.min()), float(resultant.max()))
        self.ltha_contour_ranges[("Resultant", False)] = res_range
        self.ltha_contour_ranges[("Resultant", True)] = res_range

        c_min, c_max = self.ltha_contour_ranges.get((self.contour_component, getattr(self, "contour_absolute", False)), (0.0, 1.0))
        if c_max - c_min < 1e-12:
            c_max = c_min + 1e-12
        self.ltha_engine.set_contour(getattr(self, "contour_active", False), self.contour_component, c_min, c_max, self.display_config.get("extrude_opacity", 0.35), getattr(self, "contour_absolute", False))

        self._build_ltha_extruded_metadata()

        scale = self._screen_scale()
        s = scale * 6.0
        links_dict = getattr(self.current_model, 'links', {}) or {}
        link_props = getattr(self.current_model, 'link_properties', {}) or {}

        nodal_springs = []
        axis_defs = [
            (0, (1.0, 0.0, 0.0), [0.90, 0.45, 0.45, 1.0]),
            (1, (0.0, 1.0, 0.0), [0.45, 0.75, 0.50, 1.0]),
            (2, (0.0, 0.0, -1.0), [0.45, 0.60, 0.90, 1.0]),
            (3, (-1.0, 0.0, 0.0), [0.95, 0.75, 0.40, 1.0]),
            (4, (0.0, -1.0, 0.0), [0.95, 0.75, 0.40, 1.0]),
            (5, (0.0, 0.0, 1.0), [0.95, 0.75, 0.40, 1.0]),
        ]
        for nid, node in self.current_model.nodes.items():
            if self._vo_state('node', nid) != 2:
                continue
            k = getattr(node, 'spring_matrix', None)
            if k is None:
                continue
            off_diag = k - np.diag(np.diag(k))
            if np.any(np.abs(off_diag) > 1e-6):
                continue                                                                               
            idx = self.ltha_node_map.get(str(nid), dummy_idx)
            base_pt = (node.x, node.y, node.z)
            for dof, axis_vec, color in axis_defs:
                if abs(k[dof, dof]) > 1e-6:
                    nodal_springs.append({
                        'idx': idx, 'base_pt': base_pt, 'axis_vec': axis_vec,
                        'length': 22 * scale, 'radius': 3 * scale, 'color': color,
                    })
        self.ltha_engine.set_nodal_spring_mapping(nodal_springs)

        link1_springs, link2_springs = [], []
        c_link = [0.0, 0.0, 0.0, 1.0]
        for lid, link in links_dict.items():
            if self._vo_state('link', lid) != 2:
                continue
            prop = link_props.get(link['prop_name'])
            if not prop:
                continue
            nodes = link['nodes']
            if len(nodes) == 1:
                nid = nodes[0]
                n = self.current_model.nodes.get(nid) or self.current_model.nodes.get(str(nid))
                if not n:
                    continue
                idx = self.ltha_node_map.get(str(nid), dummy_idx)
                ground_z = n.z - s * 2.2
                link1_springs.append({
                    'idx': idx, 'base_pt': (n.x, n.y, n.z),
                    'ground_pt': (n.x, n.y, ground_z),
                    'radius': s * 0.5, 'color': c_link,
                })
            elif len(nodes) == 2:
                nid_i, nid_j = nodes
                n_i = self.current_model.nodes.get(nid_i) or self.current_model.nodes.get(str(nid_i))
                n_j = self.current_model.nodes.get(nid_j) or self.current_model.nodes.get(str(nid_j))
                if not (n_i and n_j):
                    continue
                idx_i = self.ltha_node_map.get(str(nid_i), dummy_idx)
                idx_j = self.ltha_node_map.get(str(nid_j), dummy_idx)
                link2_springs.append({
                    'idx_i': idx_i, 'idx_j': idx_j,
                    'base_i': (n_i.x, n_i.y, n_i.z), 'base_j': (n_j.x, n_j.y, n_j.z),
                    'radius': s * 0.6, 'color': c_link,
                })
        self.ltha_engine.set_link1_mapping(link1_springs)
        self.ltha_engine.set_link2_mapping(link2_springs)

        self._clear_static_elements()

        if getattr(self, '_ltha_spring_plate_item', None) is not None:
            try:
                self.removeItem(self._ltha_spring_plate_item)
            except Exception:
                pass
            self._ltha_spring_plate_item = None

        plate_mesh = build_ltha_spring_plates(self.current_model.nodes, links_dict, link_props, scale=scale)
        self._ltha_spring_plate_item = plate_mesh
        if plate_mesh:
            self.addItem(plate_mesh)
            self._support_items.append(plate_mesh)

        self._ltha_hinge_cache = None                                                   

        self._ltha_vbo_built = True
        return True
    
    def _build_ltha_line_frame(self, t):
        """
        [STEP 3: THE FINAL BOSS - 144 FPS PLAYBACK]
        Fast per-frame wireframe update for LTHA.
        Slices the tensor and runs batched C-operations. Zero Python loops.
        """
                                                   
        if not hasattr(self, 'ltha_engine') or not hasattr(self, 'ltha_tensor'):
            return

        c_min, c_max = getattr(self, "ltha_contour_ranges", {}).get((self.contour_component, getattr(self, "contour_absolute", False)), (0.0, 1.0))
        self.ltha_engine.set_contour(getattr(self, "contour_active", False), self.contour_component, c_min, c_max, self.display_config.get("extrude_opacity", 0.35), getattr(self, "contour_absolute", False))

        U_current = self.ltha_tensor[:, t, :]

        verts, colors = self.ltha_engine.compute_wireframe(U_current, self.deflection_scale)

        if len(verts) == 0:
            return

        self.vbo_manager.update_line_geometry_inplace(verts, colors)

    def _build_ltha_extruded_frame(self, t):
        """
        144 FPS EXTRUDED PLAYBACK.
        Zero Allocations. Zero Python For-Loops.
        """
        if not hasattr(self, 'ltha_engine') or not hasattr(self, 'ltha_tensor'):
            return

        c_min, c_max = getattr(self, "ltha_contour_ranges", {}).get((self.contour_component, getattr(self, "contour_absolute", False)), (0.0, 1.0))
        self.ltha_engine.set_contour(getattr(self, "contour_active", False), self.contour_component, c_min, c_max, self.display_config.get("extrude_opacity", 0.35), getattr(self, "contour_absolute", False))

        U_current = self.ltha_tensor[:, t, :]
        
        verts_flat, colors_flat = self.ltha_engine.compute_extruded(U_current, self.deflection_scale)

        if len(verts_flat) == 0:
            return

        if not self.vbo_manager.ext_buffer_matches(len(verts_flat) // 3):
            self._build_ltha_extruded_metadata()
            if not self.vbo_manager.ext_buffer_matches(len(verts_flat) // 3):
                return

        self.vbo_manager.fast_update_extruded(verts_flat, colors_flat)

        if hasattr(self.ltha_engine, 'edge_indices') and self.ltha_engine.edge_indices is not None:
            edge_verts_flat = verts_flat.reshape(-1, 3)[self.ltha_engine.edge_indices].flatten()
            n_edge_verts = len(self.ltha_engine.edge_indices)
            if self.vbo_manager.line_vertex_count != n_edge_verts:
                                                                                    
                self.vbo_manager.upload_line_geometry(
                    edge_verts_flat.reshape(-1, 3),
                    self.ltha_engine.edge_colors_flat.reshape(-1, 4)
                )
            else:
                self.vbo_manager.fast_update_lines(edge_verts_flat, self.ltha_engine.edge_colors_flat)

    def _build_ltha_spring_frame(self, t):
        """
        Per-frame spring/link coil update. Same tensor, same zero-Python-loop
        approach as the beam wireframe -- just a different (smaller) VBO so
        it never gets pulled into the extruded-mode silhouette double-pass.
        """
        if not hasattr(self, 'ltha_engine') or not hasattr(self, 'ltha_tensor'):
            return

        U_current = self.ltha_tensor[:, t, :]
        verts, colors = self.ltha_engine.compute_all_springs(U_current, self.deflection_scale)

        if len(verts) == 0:
            return

        self.vbo_manager.update_spring_geometry_inplace(verts, colors)

    def invalidate_animation_cache(self):
        """
        Clears the pre-rendered animation geometry cache.
        
        Call this when:
        - Deflection scale changes
        - Model changes
        - Results change
        - Any setting that affects rendering
        """
        self.prerendered_geometry_frames.clear()
        self.is_animation_cached = False
        self.current_animation_frame = 0
    
    def _clear_static_elements(self):
        """
        Removes all static element geometry from the scene.
        
        Called when starting animation to prevent "double structure" issue.
        Keeps: nodes, supports, loads, constraints, grid, snap markers
        Removes: All element lines and meshes
        """
        items_to_remove = []
        
        for item in self.items[:]:
                                                                                   
            if isinstance(item, gl.GLLinePlotItem):
                if item not in [self.snap_ring, self.snap_dot]:
                                                                           
                    items_to_remove.append(item)
            
            elif isinstance(item, gl.GLMeshItem):
                items_to_remove.append(item)
        
        for item in items_to_remove:
            try:
                self.removeItem(item)
            except:
                pass
        
        self.element_items.clear()
    
    def prerender_animation_frames(self, anim_factors, progress_callback=None):
        """
        Pre-calculates ALL geometry for all 60 animation frames.
        
        THIS IS THE KEY METHOD THAT MAKES ANIMATION SMOOTH!
        
        Args:
            anim_factors: List of 60 animation factor values (-1.0 to 1.0)
            progress_callback: Function(percent) called with progress 0-100
            
        Process:
        1. For each of 60 frames:
           - Sets anim_factor
           - Calculates ALL curved element geometry
           - Stores positions and colors
        2. Updates progress bar
        
        Result: Playback just swaps between pre-built frames = BUTTER SMOOTH!
        
        On a slow PC:
        - Pre-rendering takes 5-10 seconds (shows progress bar)
        - Playback is 60 FPS smooth (no calculations during playback)
        """
        if not self.current_model:
            return
        
        can_deflect = (self.view_deflected and 
                       hasattr(self.current_model, 'has_results') and 
                       self.current_model.has_results and 
                       self.current_model.results is not None)
        
        if not can_deflect:
                                                       
            self.is_animation_cached = False
            return
        
        self.prerendered_geometry_frames.clear()
        
        total_frames = len(anim_factors)
        
        for frame_idx, factor in enumerate(anim_factors):
                                               
            frame_geometry = self._calculate_frame_geometry(factor)
            
            self.prerendered_geometry_frames.append(frame_geometry)
            
            if progress_callback:
                percent = int((frame_idx + 1) / total_frames * 100)
                progress_callback(percent)
        
        self.is_animation_cached = True
        self.current_animation_frame = 0

    def _build_animated_line_vbo(self):
        """
        Builds the line VBO with rest positions + peak displacement.
        Called ONCE when animation starts. No loading bar, no loop.
        The shader handles all animation math from here.
        """
        model = self.current_model
        if not model:
            return False

        can_deflect = (self.view_deflected and
                    hasattr(model, 'has_results') and
                    model.has_results and
                    model.results is not None)
        if not can_deflect:
            return False

        if self.cache_scale_used != self.deflection_scale:
            self.invalidate_deflection_cache()
            self.cache_scale_used = self.deflection_scale

        rest_verts   = []
        displacements = []
        colors       = []

        for eid, el in model.elements.items():
            n1, n2 = el.node_i, el.node_j

            v1, v2 = self._end_states('frame', el, eid)
            if v1 == 0 or v2 == 0 or self._vo_state('frame', eid) != 2:
                continue

            p1 = np.array([n1.x, n1.y, n1.z])
            p2 = np.array([n2.x, n2.y, n2.z])

            wire_color = getattr(el.section, 'color', [0.5, 0.5, 0.5, 1.0])
            if len(wire_color) == 3:
                wire_color = list(wire_color) + [1.0]
            wire_color = np.array(wire_color)

            res_i = model.results.get("displacements", {}).get(str(n1.id))
            res_j = model.results.get("displacements", {}).get(str(n2.id))

            if not (res_i and res_j):
                rest_verts.extend([p1, p2])
                displacements.extend([[0,0,0], [0,0,0]])
                colors.extend([wire_color, wire_color])
                continue

            if eid not in self.deflection_cache:
                v1_ax, v2_ax, v3_ax = self._get_consistent_axes(el)

                curve_data = get_deflected_shape(
                    [n1.x, n1.y, n1.z], [n2.x, n2.y, n2.z],
                    res_i, res_j, v1_ax, v2_ax, v3_ax,
                    scale=self.deflection_scale, num_points=11
                )
                self.deflection_cache[eid] = {
                    'curve_data': curve_data,
                    'p1_orig': p1.copy(),
                    'p2_orig': p2.copy()
                }

            curve_data_full = self.deflection_cache[eid]['curve_data']
            n_pts = len(curve_data_full)

            p1_flex, p2_flex = p1, p2

            for k in range(n_pts - 1):
                pos_full_a, _, _ = curve_data_full[k]
                pos_full_b, _, _ = curve_data_full[k + 1]

                s_a = k / (n_pts - 1)
                s_b = (k + 1) / (n_pts - 1)

                pos_orig_a = p1_flex + s_a * (p2_flex - p1_flex)             
                pos_orig_b = p1_flex + s_b * (p2_flex - p1_flex)             

                rest_verts.extend([pos_orig_a, pos_orig_b])
                displacements.extend([pos_full_a - pos_orig_a,
                                    pos_full_b - pos_orig_b])
                colors.extend([wire_color, wire_color])

        if not rest_verts:
            return False

        self.vbo_manager.upload_line_geometry(
            np.array(rest_verts,    dtype=np.float32),
            np.array(colors,        dtype=np.float32),
            np.array(displacements, dtype=np.float32)
        )
        print("[Canvas] Animated VBO built. Loading bar is dead.")
        return True

    def _build_animated_extruded_vbo(self):
        """
        Builds solid faces and general-section lines with rest + peak displacement.
        Runs _calculate_frame_geometry twice (factor 0 and 1) instead of 60 times.
        """
        if not self.current_model:
            return False

        can_deflect = (self.view_deflected and
                    hasattr(self.current_model, 'has_results') and
                    self.current_model.has_results and
                    self.current_model.results is not None)
        if not can_deflect:
            return False

        rest = self._calculate_frame_geometry(0.0)
        peak = self._calculate_frame_geometry(1.0)

        rest_lines = rest['ex_edges'] + rest['fallback_pos']
        peak_lines = peak['ex_edges'] + peak['fallback_pos']
        if not rest['ex_vertices'] and not rest_lines:
            return False

        rest_verts = np.array(rest['ex_vertices'], dtype=np.float32).reshape(-1, 3)
        peak_verts = np.array(peak['ex_vertices'], dtype=np.float32).reshape(-1, 3)
        displacements = peak_verts - rest_verts

        colors = np.array(rest['ex_colors'], dtype=np.float32).reshape(-1, 4)
        faces  = np.array(rest['ex_faces'],  dtype=np.uint32).reshape(-1, 3)

        # Empty uploads clear stale faces/edges when the displayed section mix changes.
        self.vbo_manager.upload_extruded_geometry(rest_verts, colors, faces, displacements)
        rest_lines = np.array(rest_lines, dtype=np.float32).reshape(-1, 3)
        peak_lines = np.array(peak_lines, dtype=np.float32).reshape(-1, 3)
        line_colors = np.array(rest['ex_edge_colors'] + rest['fallback_colors'],
                               dtype=np.float32).reshape(-1, 4)
        self.vbo_manager.upload_line_geometry(rest_lines, line_colors, peak_lines - rest_lines)
        print("[Canvas] Animated extruded and fallback line VBOs built.")
        return True
    
    def _calculate_frame_geometry(self, anim_factor):
        """
        Calculates the complete geometry for ONE animation frame.
        
        NOW INCLUDES BOTH WIREFRAME AND EXTRUDED GEOMETRY!
        
        Args:
            anim_factor: The animation factor for this frame (-1.0 to 1.0)
            
        Returns:
            Dictionary containing all rendering data for this frame:
            {
                # Wireframe data
                'curved_pos': [...],      
                'curved_colors': [...],   
                
                # Extruded data
                'ex_vertices': [...],     # Mesh vertices
                'ex_faces': [...],        # Face indices
                'ex_colors': [...],       # Vertex colors
                'ex_edges': [...],        # Edge lines
                'ex_edge_colors': [...],  # Edge colors
                'center_lines': [...],    # Selection highlights
                'center_colors': [...],   
            }
        """
        model = self.current_model
        
        curved_pos = []
        curved_colors = []
        fallback_pos = []
        fallback_colors = []
        
        ex_vertices = []
        ex_faces = []
        ex_colors = []
        ex_edges = []
        ex_edge_colors = []
        center_lines = []
        center_colors = []
        
        opacity = self.display_config.get("extrude_opacity", 0.35)
        show_edges = self.display_config.get("show_edges", False)
        edge_c = np.array(self.display_config.get("edge_color", (0, 0, 0, 1)), dtype=np.float32)
        color_edge_select = np.array([1.0, 1.0, 0.0, 1.0])
        
        for eid, el in model.elements.items():
            n1, n2 = el.node_i, el.node_j
            
            v1, v2 = self._end_states('frame', el, eid)
            
            if v1 == 0 or v2 == 0:
                continue
            
            if v1 == 1 and v2 == 1:
                continue
            
            p1 = np.array([n1.x, n1.y, n1.z])
            p2 = np.array([n2.x, n2.y, n2.z])
            
            if eid in self.selected_element_ids:
                wire_color = np.array([1.0, 0.0, 0.0, 1.0])
            else:
                wire_color = getattr(el.section, 'color', np.array([0.5, 0.5, 0.5, 1.0]))
                if len(wire_color) == 3:
                    wire_color = (*wire_color, 1.0)
                wire_color = np.array(wire_color)
            
            res_i = model.results.get("displacements", {}).get(str(n1.id))
            res_j = model.results.get("displacements", {}).get(str(n2.id))
            
            if not (res_i and res_j):
                continue                            
            
            cache_key = eid
            
            if self.cache_scale_used != self.deflection_scale:
                self.invalidate_deflection_cache()
                self.deflection_cache.clear()
                self.cache_scale_used = self.deflection_scale
            
            if cache_key not in self.deflection_cache:
                v1_ax, v2_ax, v3_ax = self._get_consistent_axes(el)
                
                curve_data = get_deflected_shape(
                    [n1.x, n1.y, n1.z], 
                    [n2.x, n2.y, n2.z], 
                    res_i, res_j, 
                    v1_ax, v2_ax, v3_ax, 
                    scale=self.deflection_scale,
                    num_points=11
                )
                
                self.deflection_cache[cache_key] = {
                    'curve_data': curve_data,
                    'p1_orig': p1.copy(),
                    'p2_orig': p2.copy()
                }
            
            cached = self.deflection_cache[cache_key]
            curve_data_full = cached['curve_data']
            
            p1_flex, p2_flex = p1, p2

            curve_start = len(curved_pos)
            for k in range(len(curve_data_full) - 1):
                pos_full, _, _ = curve_data_full[k]
                pos_full_next, _, _ = curve_data_full[k+1]
                
                s = k / (len(curve_data_full) - 1)
                pos_orig = p1_flex + s * (p2_flex - p1_flex)             
                
                s_next = (k + 1) / (len(curve_data_full) - 1)
                pos_orig_next = p1_flex + s_next * (p2_flex - p1_flex)             
                
                displacement = pos_full - pos_orig
                p_start = pos_orig + displacement * anim_factor
                
                displacement_next = pos_full_next - pos_orig_next
                p_end = pos_orig_next + displacement_next * anim_factor
                
                curved_pos.append(p_start)
                curved_pos.append(p_end)
                curved_colors.append(wire_color)
                curved_colors.append(wire_color)
            
            sec = el.section
            shape_yz = sec.get_shape_coords()
            if not shape_yz:
                # Keep only unshaped members as lines in the extruded animation.
                fallback_pos.extend(curved_pos[curve_start:])
                fallback_colors.extend(curved_colors[curve_start:])
                continue

            needs_caps = isinstance(sec, (RectangularSection, CircularSection, TrapezoidalSection))
            
            is_active_elem = (v1 == 2 and v2 == 2)
            
            if not is_active_elem:
                face_color = np.array([0.6, 0.6, 0.6, 0.3])
                current_edge_color = np.array([0.6, 0.6, 0.6, 0.1])
            else:
                c_raw = getattr(sec, 'color', [0.7, 0.7, 0.7])
                if len(c_raw) == 4:
                    c_raw = c_raw[:3]
                face_color = np.array([c_raw[0], c_raw[1], c_raw[2], opacity])
                current_edge_color = edge_c
            
            path_points = []
            v1_orig, v2_orig, v3_orig = self._get_consistent_axes(el)
            
            for k in range(len(curve_data_full)):
                pos_full, tan_vec, twist = curve_data_full[k]
                
                s = k / (len(curve_data_full) - 1) if len(curve_data_full) > 1 else 0.0
                pos_orig = p1 + s * (p2 - p1)
                
                displacement = pos_full - pos_orig
                pos_anim = pos_orig + displacement * anim_factor
                
                v1_curr = tan_vec
                c_t = np.cos(twist)
                s_t = np.sin(twist)
                v2_twisted = (c_t * v2_orig) + (s_t * v3_orig)
                
                proj = np.dot(v2_twisted, v1_curr) * v1_curr
                v2_curr = v2_twisted - proj
                n2_len = np.linalg.norm(v2_curr)
                if n2_len > 1e-6:
                    v2_curr /= n2_len
                else:
                    v2_curr = v2_orig
                
                v3_curr = np.cross(v1_curr, v2_curr)
                path_points.append((pos_anim, v2_curr, v3_curr))
            
            if eid in self.selected_element_ids and len(path_points) >= 2:
                for i in range(len(path_points) - 1):
                    center_lines.extend([path_points[i][0], path_points[i+1][0]])
                    center_colors.extend([color_edge_select, color_edge_select])
            
            y_shift, z_shift = el.get_cardinal_offsets()
            off_vec_i = getattr(el, 'joint_offset_i', np.array([0, 0, 0]))
            off_vec_j = getattr(el, 'joint_offset_j', np.array([0, 0, 0]))
            
            num_pts = len(path_points)
            
            for i in range(num_pts - 1):
                pos_a, v2_a, v3_a = path_points[i]
                pos_b, v2_b, v3_b = path_points[i + 1]
                
                if num_pts > 1:
                    s_a = i / (num_pts - 1)
                    s_b = (i + 1) / (num_pts - 1)
                else:
                    s_a, s_b = 0.0, 1.0
                
                curr_off_a = (1 - s_a) * off_vec_i + s_a * off_vec_j
                curr_off_b = (1 - s_b) * off_vec_i + s_b * off_vec_j
                
                center_a = pos_a + curr_off_a + (y_shift * v2_a) + (z_shift * v3_a)
                center_b = pos_b + curr_off_b + (y_shift * v2_b) + (z_shift * v3_b)
                
                is_first_seg = (i == 0)
                is_last_seg = (i == num_pts - 2)
                
                self._add_loft_to_arrays(
                    center_a, center_b,
                    v2_a, v3_a, v2_b, v3_b,
                    shape_yz, face_color,
                    show_edges, current_edge_color,
                    draw_start_ring=is_first_seg,
                    draw_end_ring=is_last_seg,
                    draw_caps=needs_caps,
                    ex_vertices=ex_vertices,
                    ex_faces=ex_faces,
                    ex_colors=ex_colors,
                    ex_edges=ex_edges,
                    ex_edge_colors=ex_edge_colors
                )
        
        return {
            'curved_pos': curved_pos,
            'curved_colors': curved_colors,
            'fallback_pos': fallback_pos,
            'fallback_colors': fallback_colors,
            'ex_vertices': ex_vertices,
            'ex_faces': ex_faces,
            'ex_colors': ex_colors,
            'ex_edges': ex_edges,
            'ex_edge_colors': ex_edge_colors,
            'center_lines': center_lines,
            'center_colors': center_colors,
        }
    
    def _render_prerendered_frame(self, frame_idx):
        """
        Renders a pre-calculated animation frame.
        
        NOW SUPPORTS BOTH WIREFRAME AND EXTRUDED MODES!
        
        THIS IS BLAZING FAST because:
        - No calculations needed
        - No cache lookups  
        - No get_deflected_shape calls
        - Just swap OpenGL buffers
        
        Args:
            frame_idx: Index of the frame to render (0-59)
        """
                                           
        frame = self.prerendered_geometry_frames[frame_idx]

        for node_item in self.node_items:
            node_item.setVisible(False)
        
        for item in self.element_items:
            try:
                self.removeItem(item)
            except:
                pass
        self.element_items.clear()
        
        if self.view_extruded:
                                       
            ex_vertices = frame['ex_vertices']
            ex_faces = frame['ex_faces']
            ex_colors = frame['ex_colors']
            ex_edges = frame['ex_edges']
            ex_edge_colors = frame['ex_edge_colors']
            center_lines = frame['center_lines']
            center_colors = frame['center_colors']
            
            if center_lines:
                cl = gl.GLLinePlotItem(
                    pos=np.array(center_lines),
                    color=np.array(center_colors),
                    mode='lines',
                    width=5.0,
                    antialias=True
                )
                cl.setGLOptions('translucent')
                self.addItem(cl)
                self.element_items.append(cl)
            
            if ex_vertices:
                mesh = gl.GLMeshItem(
                    vertexes=np.array(ex_vertices, dtype=np.float32),
                    faces=np.array(ex_faces, dtype=np.int32),
                    vertexColors=np.array(ex_colors, dtype=np.float32),
                    smooth=False,
                    drawEdges=False,
                    glOptions='translucent'
                )
                self.addItem(mesh)
                self.element_items.append(mesh)
            
            show_edges = self.display_config.get("show_edges", False)
            edge_width = self.display_config.get("edge_width", 1.0)
            
            if show_edges and ex_edges:
                ed = gl.GLLinePlotItem(
                    pos=np.array(ex_edges),
                    color=np.array(ex_edge_colors),
                    mode='lines',
                    width=edge_width,
                    antialias=True
                )
                ed.setGLOptions('opaque')
                self.addItem(ed)
                self.element_items.append(ed)
        
        else:
                                        
            curved_pos = frame['curved_pos']
            curved_colors = frame['curved_colors']
            
            if curved_pos:
                curved_item = gl.GLLinePlotItem(
                    pos=np.array(curved_pos),
                    color=np.array(curved_colors),
                    mode='lines',
                    width=self.display_config.get("line_width", 2.0),
                    antialias=True
                )
                self.addItem(curved_item)
                self.element_items.append(curved_item)
        
    def mousePressEvent(self, event):

        self._mouse_pressed = True
        super().mousePressEvent(event)

        hit = self.view_cube.check_click(event.pos().x(), event.pos().y(), self.width(), self.height())
 
        if hit:
            print("View Cube Clicked!")
            return 

        self._prev_mouse_pos = event.pos()
        modifiers = QApplication.keyboardModifiers()
        
        if event.button() == Qt.MouseButton.LeftButton:
                                                 
            if getattr(self, 'single_use_pan_active', False):
                self.setCursor(Qt.CursorShape.ClosedHandCursor)                           
                return                                                      

            if getattr(self, 'beam_col_mode', False):
                if self._beam_col_hover_seg is not None:
                    p1, p2 = self._beam_col_hover_seg
                    mid = (p1 + p2) / 2.0
                    self.signal_canvas_clicked.emit(float(mid[0]), float(mid[1]), float(mid[2]))
                return

            if getattr(self, 'cross_brace_mode', False):
                pos = event.pos()
                hit = self._raycast_to_plane(pos.x(), pos.y())
                if hit is not None:
                    self.signal_canvas_clicked.emit(float(hit[0]), float(hit[1]), float(hit[2]))
                return

            if self.quick_area_mode:
                pos = event.pos()
                hit = self._raycast_to_plane(pos.x(), pos.y())
                corners = self._find_quick_area_cell_from_hit(hit) if hit is not None else None
                if corners is not None:
                    self._show_quick_area_preview(corners)
                    self.signal_canvas_clicked.emit(float(hit[0]), float(hit[1]), float(hit[2]))
                else:
                    self.hide_quick_area_preview()
                return

            if self.snapping_enabled:
                pos = event.pos()
                snap_coord = self.get_snap_point(pos.x(), pos.y())
                if snap_coord is not None:
                    self.signal_canvas_clicked.emit(snap_coord[0], snap_coord[1], snap_coord[2])
                return

            self.drag_start = event.pos()
            self.drag_current = event.pos()
            self.is_selecting = True
            self._is_navigating = True
            self.update()

        elif event.button() == Qt.MouseButton.RightButton:
            self._is_navigating = True
            self.signal_right_clicked.emit()
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not _GL_PROFILE:
            return self._mouse_move_impl(event)
        _t = time.perf_counter()
        try:
            return self._mouse_move_impl(event)
        finally:
            st = self.__dict__.setdefault('_mm_prof', {'n': 0, 'sum': 0.0, 'max': 0.0})
            d = (time.perf_counter() - _t) * 1000.0
            st['n'] += 1; st['sum'] += d; st['max'] = max(st['max'], d)
            if st['n'] >= 100:
                print(f"[MOUSE PROFILE] mouseMoveEvent avg {st['sum'] / st['n']:.2f} ms, max {st['max']:.2f} ms over {st['n']} events")
                st['n'] = 0; st['sum'] = 0.0; st['max'] = 0.0

    def _mouse_move_impl(self, event):
        self._march_selection_dashes(event.position())
        buttons = event.buttons()
        is_middle_pan = (buttons == Qt.MouseButton.MiddleButton)
        is_tool_pan   = (buttons == Qt.MouseButton.LeftButton and getattr(self, 'single_use_pan_active', False))
        is_rotating   = (buttons == Qt.MouseButton.LeftButton and not self.is_selecting and not getattr(self, 'single_use_pan_active', False))

        self._is_navigating = is_middle_pan or is_tool_pan or is_rotating or self.is_selecting

        _xh_nav = bool(is_middle_pan or is_tool_pan or self.is_selecting
                       or (is_rotating and not self.crosshair.drawing_mode()))
        if _xh_nav:
            self.crosshair.refresh(event.position(), None, True)

        if self._is_navigating and self.current_hover_data is not None:
            self.current_hover_data = None
            self.update()
        if self.is_selecting:
            self.drag_current = event.pos()
            self.update()
            return

        if is_middle_pan or is_tool_pan:
            if hasattr(self, '_prev_mouse_pos'):
                dx = event.pos().x() - self._prev_mouse_pos.x()
                dy = event.pos().y() - self._prev_mouse_pos.y()
                modifiers = QApplication.keyboardModifiers()
                if modifiers == Qt.KeyboardModifier.ShiftModifier:
                    self.camera.rotate(dx, dy)
                else:
                    self.camera.pan(dx, dy, self.width(), self.height())
            self._prev_mouse_pos = event.pos()
            
            if is_tool_pan:
                return

        elif event.buttons() == Qt.MouseButton.LeftButton:
                                                                                                  
            is_drawing = (getattr(self, 'beam_col_mode', False) or 
                          getattr(self, 'cross_brace_mode', False) or 
                          self.quick_area_mode or
                          self.snapping_enabled)
            
            if not is_drawing:
                self.show_pivot_dot(True)
                if hasattr(self, '_prev_mouse_pos'):
                    dx = event.pos().x() - self._prev_mouse_pos.x()
                    dy = event.pos().y() - self._prev_mouse_pos.y()
                    self.camera.rotate(dx, dy)
                self._prev_mouse_pos = event.pos()
                super().mouseMoveEvent(event)

        else:
            super().mouseMoveEvent(event)

        snap_pt = self.get_snap_point(event.pos().x(), event.pos().y())

        if self._draw_start is not None and snap_pt is not None:
            self.update_preview_line(self._draw_start, snap_pt)
        else:
            self.hide_preview_line()

        if snap_pt is not None:
            self.signal_mouse_moved.emit(snap_pt[0], snap_pt[1], snap_pt[2])

        if not _xh_nav:
            self.crosshair.refresh(event.position(), self._snap_screen_xy)

        if getattr(self, 'cross_brace_mode', False):
            self.snap_ring.setVisible(False)
            self.snap_dot.setVisible(False)
            self._update_brace_preview(event.pos().x(), event.pos().y())

        if self.quick_area_mode:
            self.snap_ring.setVisible(False)
            self.snap_dot.setVisible(False)
            self._update_quick_area_preview(event.pos().x(), event.pos().y())

        if getattr(self, 'beam_col_mode', False):
            self.snap_ring.setVisible(False)
            self.snap_dot.setVisible(False)
            self._update_beam_col_preview(event.pos().x(), event.pos().y())

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        pos   = event.position()
        self._snap_screen_xy = None
        self.crosshair.on_wheel(pos)

        _now = time.perf_counter()
        _zc = getattr(self, '_zoom_hit_cache', None)
        if (_zc is not None and (_now - _zc[0]) < 0.25
                and abs(pos.x() - _zc[1]) < 6 and abs(pos.y() - _zc[2]) < 6):
            hit = _zc[3]
        else:
            hit = self._find_zoom_target(pos.x(), pos.y())
        self._zoom_hit_cache = (_now, pos.x(), pos.y(), hit)

        self.camera.zoom(delta, pos.x(), pos.y(), self.width(), self.height(), hit_point=hit)

        self._support_rebuild_timer.start(180)
        self._is_zooming = True
        self._label_hide_timer.start(400)

        self._is_navigating = True

        if not hasattr(self, '_zoom_lod_timer'):
            self._zoom_lod_timer = QTimer()
            self._zoom_lod_timer.setSingleShot(True)
            self._zoom_lod_timer.timeout.connect(self._end_zoom_navigation)

        self._zoom_lod_timer.start(150)

        self.update()

    def _end_zoom_navigation(self):
        """Snaps back to high-quality rendering 150ms after the scroll wheel stops."""
        self._is_navigating = False
        self._is_zooming = False                           
        self.update()

    def mouseReleaseEvent(self, event):
                                 
        if event.button() == Qt.MouseButton.LeftButton and getattr(self, 'single_use_pan_active', False):
            self.single_use_pan_active = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            
            main_window = self.window()
            if hasattr(main_window, 'btn_pan'):
                main_window.btn_pan.setChecked(False)
            if hasattr(main_window, 'status'):
                main_window.status.showMessage("Ready")
                
            super().mouseReleaseEvent(event)
            return
                                           
        if self.is_selecting and event.button() == Qt.MouseButton.LeftButton:
            self.is_selecting = False
            self._is_navigating = False
            self.update() 

            suppress_selection = getattr(self, '_suppress_next_click_selection', False)
            self._suppress_next_click_selection = False

            if self.drag_start:
                drag_dist = (event.pos() - self.drag_start).manhattanLength()
                self._last_selection_was_click = (drag_dist <= 8)

                if not suppress_selection:
                    if drag_dist > 8:
                        self.process_box_selection(self.drag_start, event.pos(), is_single_click=False)
                    else:
                        self.process_box_selection(event.pos(), event.pos(), is_single_click=True)
                        self._handle_hover_tooltip(event.pos().x(), event.pos().y())

            self.drag_start = None
            self.drag_current = None
            
        self._is_navigating = False
        self._schedule_label_rebuild(delay_ms=80)
        self._mouse_pressed = False
        self.update()
        super().mouseReleaseEvent(event)

    def pick_single_object(self, pos):
        """
        Picks the object nearest to pos.
        Uses crossing-select mode (p_end.x < p_start.x) so element lines are
        tested with _line_intersects_rect rather than requiring both endpoints
        inside the tiny hit box — which would make frame click-selection impossible.
        """
        start_centered = type(pos)(pos.x() + 5, pos.y() - 5)
        end_centered   = type(pos)(pos.x() - 5, pos.y() + 5)
        self.process_box_selection(start_centered, end_centered, is_single_click=True)

    def leaveEvent(self, event):
        self._snap_screen_xy = None
        self.crosshair.on_leave()
        self.hide_quick_area_preview()
        super().leaveEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        
        painter = QPainter(self)
                                                                 
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        if self.is_selecting and self.drag_start and self.drag_current:
            x1, y1 = self.drag_start.x(), self.drag_start.y()
            x2, y2 = self.drag_current.x(), self.drag_current.y()
            w_sel = x2 - x1
            h_sel = y2 - y1
            rect = QRect(min(x1, x2), min(y1, y2), abs(w_sel), abs(h_sel))
            
            if w_sel > 0:
                c = QColor(0, 120, 215, 40)
                border = QColor(0, 120, 215, 200)
                pen = QPen(border, 1.5, Qt.PenStyle.SolidLine)
            else:
                c = QColor(0, 180, 80, 40)
                border = QColor(0, 180, 80, 200)
                pen = QPen(border, 1.5)
                pen.setDashPattern([5, 4])
            
            painter.setBrush(c)
            painter.setPen(pen)
            painter.drawRect(rect)

        if getattr(self, 'current_hover_data', None):
            from PyQt6.QtGui import QFont, QImage, QFontMetrics
            hx = self.current_hover_data['x'] + 15
            hy = self.current_hover_data['y'] + 15
            text = self.current_hover_data['text']

            font = QFont("Consolas")
            font.setPixelSize(11)
            font.setBold(False)

            flags = Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignLeft
                                                                    
            rect = QFontMetrics(font).boundingRect(0, 0, 400, 400, flags, text)

            img = QImage(rect.width() + 12, rect.height() + 10, QImage.Format.Format_ARGB32)
            img.fill(Qt.GlobalColor.transparent)
            rp = QPainter(img)
            rp.setFont(font)
            rp.fillRect(img.rect(), QColor(40, 40, 40, 200))
            rp.setPen(QColor(80, 80, 80, 200))
            rp.drawRect(img.rect().adjusted(0, 0, -1, -1))
            rp.setPen(QColor(220, 220, 220))
            rp.drawText(QRect(6, 5, rect.width(), rect.height()), flags, text)
            rp.end()

            painter.drawImage(int(hx), int(hy), img)
            
        if self.current_model:
            w = self.width()
            h = self.height()
            full_area = (0, 0, w, h)
            mvp = np.array(
                (self.projectionMatrix(region=full_area, viewport=full_area) *
                 self.viewMatrix()).data()
            ).reshape(4, 4).T
            self._draw_axis_overlay(painter, mvp, w, h)

        self.crosshair.draw(painter)

        painter.end()

    def _schedule_label_rebuild(self, delay_ms=80):
        """
        Debounced trigger for _rebuild_label_pixmap.
        Safe to call from anywhere (timer callbacks, events, etc.).
        """
        self._label_rebuild_timer.start(delay_ms)
    
    def _is_moving(self):
        return getattr(self, '_mouse_pressed', False)        

    def process_box_selection(self, p_start, p_end, is_single_click=False):
        if not self.current_model:
            return

        w = self.width()
        h = self.height()
        full_area = (0, 0, w, h)
        m_view = self.viewMatrix()
        m_proj = self.projectionMatrix(region=full_area, viewport=full_area)
        mvp = np.array((m_proj * m_view).data()).reshape(4, 4).T

        model = self.current_model
        can_deflect = (
            self.view_deflected
            and hasattr(model, 'has_results')
            and model.has_results
            and model.results is not None
        )

        node_screens = {}
        vis_nids = []
        if model.nodes:
            all_nids = list(model.nodes.keys())
            all_nodes = list(model.nodes.values())
            vis_mask = [self._get_visibility_state(n.x, n.y, n.z) == 2 for n in all_nodes]
            vis_nids = [all_nids[i] for i, v in enumerate(vis_mask) if v]
            vis_nodes = [all_nodes[i] for i, v in enumerate(vis_mask) if v]

            if vis_nids:
                positions = np.array([[n.x, n.y, n.z] for n in vis_nodes], dtype=np.float64)
                if can_deflect:
                    displacements = model.results.get("displacements", {})
                    disp = np.zeros_like(positions)
                    for i, nid in enumerate(vis_nids):
                        d = displacements.get(str(nid))
                        if d is not None:
                            disp[i] = d[:3]
                    positions += disp * (self.deflection_scale * self.anim_factor)

                N = len(positions)
                pos_h = np.hstack([positions, np.ones((N, 1))])
                clip = pos_h @ mvp.T
                w_clip = clip[:, 3]
                screen_valid = w_clip > 0
                safe_w = np.where(screen_valid, w_clip, 1.0)
                sx = (clip[:, 0] / safe_w * 0.5 + 0.5) * w
                sy = (1.0 - (clip[:, 1] / safe_w * 0.5 + 0.5)) * h

                for i, nid in enumerate(vis_nids):
                    if screen_valid[i]:
                        node_screens[nid] = (float(sx[i]), float(sy[i]))

        def pt_seg_dist(pt, a, b):
            ax, ay = a; bx, by = b
            l2 = (bx - ax) ** 2 + (by - ay) ** 2
            if l2 == 0: return math.hypot(pt[0] - ax, pt[1] - ay)
            t = max(0.0, min(1.0, ((pt[0] - ax) * (bx - ax) + (pt[1] - ay) * (by - ay)) / l2))
            px, py = ax + t * (bx - ax), ay + t * (by - ay)
            return math.hypot(pt[0] - px, pt[1] - py)

        found_nodes, found_elems, found_links, found_tendons, found_area_elems = [], [], [], [], []
        found_cables = []

        if is_single_click:
            mx = (p_start.x() + p_end.x()) / 2.0
            my = (p_start.y() + p_end.y()) / 2.0
            candidates = []

            for nid, pos in node_screens.items():
                d = math.hypot(pos[0] - mx, pos[1] - my)
                if d <= 10: candidates.append((d, 1, 'node', nid))

            for eid, el in model.elements.items():
                if can_deflect and eid in getattr(self, 'deflection_cache', {}):
                    cached = self.deflection_cache[eid]
                    curve_data_full = cached['curve_data']
                    p1_orig = cached['p1_orig']
                    p2_orig = cached['p2_orig']
                    screen_pts = []
                    for k in range(len(curve_data_full)):
                        pos_full, _, _ = curve_data_full[k]
                        s = k / (len(curve_data_full) - 1) if len(curve_data_full) > 1 else 0.0
                        pos_orig = p1_orig + s * (p2_orig - p1_orig)
                        displacement = pos_full - pos_orig
                        pos_anim = pos_orig + displacement * self.anim_factor
                        s_pos = self._project_to_screen(pos_anim[0], pos_anim[1], pos_anim[2], mvp, w, h)
                        if s_pos: screen_pts.append(s_pos)
                    min_d = float('inf')
                    for k in range(len(screen_pts)-1):
                        d = pt_seg_dist((mx, my), screen_pts[k], screen_pts[k+1])
                        if d < min_d: min_d = d
                    if min_d <= 10: candidates.append((min_d, 2, 'elem', eid))
                else:
                    p1 = node_screens.get(el.node_i.id)
                    p2 = node_screens.get(el.node_j.id)
                    if p1 and p2:
                        d = pt_seg_dist((mx, my), p1, p2)
                        if d <= 10: candidates.append((d, 2, 'elem', eid))

            if getattr(model, 'tendons', None):
                for tid, t in model.tendons.items():
                    pts = self._get_tendon_world_points(t)
                    if pts is not None and len(pts) >= 2:
                        s_pts = []
                        for p in pts:
                            s_pos = self._project_to_screen(p[0], p[1], p[2], mvp, w, h)
                            if s_pos: s_pts.append(s_pos)
                        min_t_dist = float('inf')
                        for k in range(len(s_pts)-1):
                            d = pt_seg_dist((mx, my), s_pts[k], s_pts[k+1])
                            if d < min_t_dist: min_t_dist = d
                        if min_t_dist <= 10:
                            candidates.append((min_t_dist, 3, 'tendon', tid))

            if getattr(model, 'cables', None):
                for cid, c in model.cables.items():
                    pts = self._get_cable_world_points(c)
                    if pts is not None and len(pts) >= 2:
                        s_pts = []
                        for p in pts:
                            s_pos = self._project_to_screen(p[0], p[1], p[2], mvp, w, h)
                            if s_pos: s_pts.append(s_pos)
                        min_c_dist = float('inf')
                        for k in range(len(s_pts)-1):
                            d = pt_seg_dist((mx, my), s_pts[k], s_pts[k+1])
                            if d < min_c_dist: min_c_dist = d
                        if min_c_dist <= 10:
                            candidates.append((min_c_dist, 2.5, 'cable', cid))

            if hasattr(model, 'links'):
                for lid, link in model.links.items():
                    nodes = link['nodes']
                    if len(nodes) == 1:
                        nid = nodes[0]
                        real_node = model.nodes.get(nid) or model.nodes.get(int(nid)) or model.nodes.get(str(nid))
                        if real_node:
                            scale = getattr(self, 'cache_scale_used', 1.0)
                            if scale is None:
                                bounds = getattr(self, 'compute_model_bbox', lambda: None)()
                                scale = bounds[1] * 0.05 if bounds and len(bounds)>=2 else 1.0
                            ground_z = real_node.z - scale * 6.0 * 2.2
                            s = self._project_to_screen(real_node.x, real_node.y, ground_z, mvp, w, h)
                            if s:
                                d = math.hypot(s[0] - mx, s[1] - my)
                                if d <= 10: candidates.append((d, 4, 'link', lid))
                    elif len(nodes) == 2:
                        p1 = node_screens.get(nodes[0]) or node_screens.get(int(nodes[0])) or node_screens.get(str(nodes[0]))
                        p2 = node_screens.get(nodes[1]) or node_screens.get(int(nodes[1])) or node_screens.get(str(nodes[1]))
                        if p1 and p2:
                            d = pt_seg_dist((mx, my), p1, p2)
                            if d <= 10: candidates.append((d, 4, 'link', lid))

            for aeid, ae in model.area_elements.items():
                if getattr(self, 'view_deflected', False):
                    if hasattr(ae.section, 'modeling_type') and ae.section.modeling_type == "Tributary Area":
                        continue
                corner_screens = []
                for n in ae.nodes:
                    s = node_screens.get(n.id) or self._project_to_screen(n.x, n.y, n.z, mvp, w, h)
                    if s: corner_screens.append(s)
                if len(corner_screens) >= 3:
                    if self._point_in_polygon_2d(mx, my, corner_screens):
                        candidates.append((10.0, 5, 'area', aeid))

            _pk = {'node': 'node', 'elem': 'frame', 'tendon': 'tendon', 'cable': 'cable', 'link': 'link', 'area': 'area'}
            candidates = [c for c in candidates if self._pickable(_pk[c[2]], c[3])]

            if candidates:
                candidates.sort(key=lambda x: (x[0], x[1]))
                min_d = candidates[0][0]
                tied = [c for c in candidates if c[0] <= min_d + 2.0]
                
                now = time.monotonic()
                if hasattr(self, '_click_cycle_pos'):
                    dist_click = math.hypot(mx - self._click_cycle_pos[0], my - self._click_cycle_pos[1])
                    if dist_click < 5.0 and (now - getattr(self, '_click_cycle_time', 0)) < 1.0:
                        self._click_cycle_index = (getattr(self, '_click_cycle_index', -1) + 1) % len(tied)
                    else:
                        self._click_cycle_index = 0
                else:
                    self._click_cycle_index = 0
                    
                self._click_cycle_pos = (mx, my)
                self._click_cycle_time = now

                deselect_click = (QApplication.keyboardModifiers() == Qt.KeyboardModifier.ShiftModifier)
                best = None
                if deselect_click:
                    selected_map = {
                        'node':   getattr(self, 'selected_node_ids', []),
                        'elem':   getattr(self, 'selected_element_ids', []),
                        'tendon': getattr(self, 'selected_tendon_ids', []),
                        'cable':  getattr(self, 'selected_cable_ids', []),
                        'link':   getattr(self, 'selected_link_ids', []),
                        'area':   getattr(self, 'selected_area_ids', []),
                    }
                    already_selected = [c for c in tied if c[3] in selected_map.get(c[2], [])]
                    if already_selected:
                        best = already_selected[0]
                if best is None:
                    best = tied[self._click_cycle_index]
                ctype, cid = best[2], best[3]
                
                if ctype == 'node': found_nodes.append(cid)
                elif ctype == 'elem': found_elems.append(cid)
                elif ctype == 'tendon': found_tendons.append(cid)
                elif ctype == 'cable': found_cables.append(cid)
                elif ctype == 'link': found_links.append(cid)
                elif ctype == 'area': found_area_elems.append(cid)

        else:
            self._click_cycle_key = None
            self._click_cycle_index = -1

            x_min, x_max = min(p_start.x(), p_end.x()), max(p_start.x(), p_end.x())
            y_min, y_max = min(p_start.y(), p_end.y()), max(p_start.y(), p_end.y())
            is_window_select = (p_end.x() > p_start.x())
            rect = (x_min, y_min, x_max, y_max)

            for nid, pos in node_screens.items():
                if x_min <= pos[0] <= x_max and y_min <= pos[1] <= y_max:
                    found_nodes.append(nid)

            for eid, el in model.elements.items():
                p1 = node_screens.get(el.node_i.id)
                p2 = node_screens.get(el.node_j.id)
                if p1 and p2:
                    if is_window_select:
                        if (x_min <= p1[0] <= x_max and y_min <= p1[1] <= y_max and
                            x_min <= p2[0] <= x_max and y_min <= p2[1] <= y_max):
                            found_elems.append(eid)
                    else:
                        if self._line_intersects_rect(p1, p2, rect):
                            found_elems.append(eid)

            if getattr(model, 'tendons', None):
                for tid, t in model.tendons.items():
                    pts = self._get_tendon_world_points(t)
                    if pts is not None and len(pts) >= 2:
                        s_pts = []
                        for p in pts:
                            s_pos = self._project_to_screen(p[0], p[1], p[2], mvp, w, h)
                            if s_pos: s_pts.append(s_pos)
                        if not s_pts: continue
                        if is_window_select:
                            if all(x_min <= p[0] <= x_max and y_min <= p[1] <= y_max for p in s_pts):
                                found_tendons.append(tid)
                        else:
                            hit = False
                            for k in range(len(s_pts)-1):
                                if self._line_intersects_rect(s_pts[k], s_pts[k+1], rect):
                                    hit = True
                                    break
                            if hit: found_tendons.append(tid)

            if getattr(model, 'cables', None):
                for cid, c in model.cables.items():
                    pts = self._get_cable_world_points(c)
                    if pts is not None and len(pts) >= 2:
                        s_pts = []
                        for p in pts:
                            s_pos = self._project_to_screen(p[0], p[1], p[2], mvp, w, h)
                            if s_pos: s_pts.append(s_pos)
                        if not s_pts: continue
                        if is_window_select:
                            if all(x_min <= p[0] <= x_max and y_min <= p[1] <= y_max for p in s_pts):
                                found_cables.append(cid)
                        else:
                            hit = False
                            for k in range(len(s_pts)-1):
                                if self._line_intersects_rect(s_pts[k], s_pts[k+1], rect):
                                    hit = True
                                    break
                            if hit: found_cables.append(cid)

            if hasattr(model, 'links'):
                for lid, link in model.links.items():
                    nodes = link['nodes']
                    if len(nodes) == 1:
                        nid = nodes[0]
                        real_node = model.nodes.get(nid) or model.nodes.get(int(nid)) or model.nodes.get(str(nid))
                        if real_node:
                            scale = getattr(self, 'cache_scale_used', 1.0)
                            if scale is None:
                                bounds = getattr(self, 'compute_model_bbox', lambda: None)()
                                scale = bounds[1] * 0.05 if bounds and len(bounds)>=2 else 1.0
                            ground_z = real_node.z - scale * 6.0 * 2.2
                            s = self._project_to_screen(real_node.x, real_node.y, ground_z, mvp, w, h)
                            if s and (x_min <= s[0] <= x_max) and (y_min <= s[1] <= y_max):
                                found_links.append(lid)
                    elif len(nodes) == 2:
                        p1 = node_screens.get(nodes[0]) or node_screens.get(int(nodes[0])) or node_screens.get(str(nodes[0]))
                        p2 = node_screens.get(nodes[1]) or node_screens.get(int(nodes[1])) or node_screens.get(str(nodes[1]))
                        if p1 and p2:
                            if is_window_select:
                                if (x_min <= p1[0] <= x_max and y_min <= p1[1] <= y_max and
                                    x_min <= p2[0] <= x_max and y_min <= p2[1] <= y_max):
                                    found_links.append(lid)
                            else:
                                if self._line_intersects_rect(p1, p2, rect):
                                    found_links.append(lid)

            for aeid, ae in model.area_elements.items():
                if getattr(self, 'view_deflected', False):
                    if hasattr(ae.section, 'modeling_type') and ae.section.modeling_type == "Tributary Area":
                        continue
                corner_screens = []
                for n in ae.nodes:
                    s = node_screens.get(n.id) or self._project_to_screen(n.x, n.y, n.z, mvp, w, h)
                    if s: corner_screens.append(s)
                if len(corner_screens) < 3:
                    continue

                if is_window_select:
                    if all(x_min <= p[0] <= x_max and y_min <= p[1] <= y_max for p in corner_screens):
                        found_area_elems.append(aeid)
                else:
                    cx_pick = (x_min + x_max) / 2.0
                    cy_pick = (y_min + y_max) / 2.0
                    if self._point_in_polygon_2d(cx_pick, cy_pick, corner_screens):
                        found_area_elems.append(aeid)
                    else:
                        n_pts = len(corner_screens)
                        for i in range(n_pts):
                            if self._line_intersects_rect(corner_screens[i], corner_screens[(i + 1) % n_pts], rect):
                                found_area_elems.append(aeid)
                                break

        found_nodes      = [i for i in found_nodes      if self._pickable('node', i)]
        found_elems      = [i for i in found_elems      if self._pickable('frame', i)]
        found_links      = [i for i in found_links      if self._pickable('link', i)]
        found_tendons    = [i for i in found_tendons    if self._pickable('tendon', i)]
        found_cables     = [i for i in found_cables     if self._pickable('cable', i)]
        found_area_elems = [i for i in found_area_elems if self._pickable('area', i)]

        modifiers   = QApplication.keyboardModifiers()
        is_additive = (modifiers == Qt.KeyboardModifier.ControlModifier)
        is_deselect = (modifiers == Qt.KeyboardModifier.ShiftModifier)
        emit_areas = bool(found_area_elems or not is_single_click)
        self._box_sel_area_follows = emit_areas
        try:
            self.signal_box_selection.emit(found_nodes, found_elems, found_links, found_tendons, found_cables, is_additive, is_deselect)
            if emit_areas:
                self.signal_area_box_selection.emit(found_area_elems, is_additive, is_deselect)
        finally:
            self._box_sel_area_follows = False

    def _point_in_polygon_2d(self, px, py, pts):
        """Winding number test — works for convex and concave screen-space polygons."""
        winding = 0
        n = len(pts)
        for i in range(n):
            x1, y1 = pts[i]
            x2, y2 = pts[(i + 1) % n]
            if y1 <= py:
                if y2 > py and (x2-x1)*(py-y1) - (px-x1)*(y2-y1) > 0:
                    winding += 1
            else:
                if y2 <= py and (x2-x1)*(py-y1) - (px-x1)*(y2-y1) < 0:
                    winding -= 1
        return winding != 0

    def _project_to_screen(self, x, y, z, mvp, w, h):
        vec = np.array([x, y, z, 1.0])
        clip = np.dot(mvp, vec)
        
        if clip[3] <= 0: 
            return None
            
        ndc_x = clip[0] / clip[3]
        ndc_y = clip[1] / clip[3]
        
        if abs(ndc_x) > 2.0 or abs(ndc_y) > 2.0:
            return None
            
        screen_x = (ndc_x + 1) * w / 2
        screen_y = (1 - ndc_y) * h / 2
        return (screen_x, screen_y)

    def _find_zoom_target(self, mouse_x, mouse_y, screen_radius=150):
        """Find closest node or element midpoint to mouse in screen space.

        Fast path: coordinates are cached as one contiguous float32 (N,3) array,
        only the clip-space x/y/w rows are computed, and very large models are
        strided down to ~200k candidates (this is only a *snap* target, so exact
        coverage of every node is not needed)."""
        if not self.current_model or not self.current_model.nodes:
            return None

        view_w = self.width()
        view_h = self.height()
        full_area = (0, 0, view_w, view_h)
        mvp_matrix = np.array(
            (self.projectionMatrix(region=full_area, viewport=full_area) *
            self.viewMatrix()).data(), dtype=np.float64
        ).reshape(4, 4).T

        can_deflect = getattr(self, 'view_deflected', False) and\
                      hasattr(self.current_model, 'has_results') and\
                      self.current_model.has_results and\
                      self.current_model.results is not None

        scale = getattr(self, 'deflection_scale', 1.0) * getattr(self, 'anim_factor', 1.0)

        _m = self.current_model
        _ck = (id(_m), len(_m.nodes), len(_m.elements), bool(can_deflect),
               float(scale) if can_deflect else 0.0, id(_m.results) if can_deflect else 0)
        _zc = getattr(self, '_zoom_coord_cache', None)
        if _zc is not None and _zc[0] == _ck:
            all_coords = _zc[1]
        else:
            nodes = _m.nodes
            if can_deflect:
                _disps = _m.results.get("displacements", {})
                node_disps = {}
                node_coords = []
                for nid, n in nodes.items():
                    dx = dy = dz = 0.0
                    disp = _disps.get(str(nid))
                    if disp:
                        dx, dy, dz = disp[0]*scale, disp[1]*scale, disp[2]*scale
                        node_disps[nid] = (dx, dy, dz)
                    node_coords.append((n.x + dx, n.y + dy, n.z + dz))
                elem_coords = []
                _z3 = (0.0, 0.0, 0.0)
                for el in _m.elements.values():
                    n1, n2 = el.node_i, el.node_j
                    d1 = node_disps.get(n1.id, _z3)
                    d2 = node_disps.get(n2.id, _z3)
                    elem_coords.append(((n1.x + d1[0] + n2.x + d2[0]) * 0.5,
                                        (n1.y + d1[1] + n2.y + d2[1]) * 0.5,
                                        (n1.z + d1[2] + n2.z + d2[2]) * 0.5))
            else:
                node_coords = [(n.x, n.y, n.z) for n in nodes.values()]
                elem_coords = [((el.node_i.x + el.node_j.x) * 0.5,
                                (el.node_i.y + el.node_j.y) * 0.5,
                                (el.node_i.z + el.node_j.z) * 0.5)
                               for el in _m.elements.values()]

            node_arr = np.asarray(node_coords, dtype=np.float32).reshape(-1, 3)
            elem_arr = np.asarray(elem_coords, dtype=np.float32).reshape(-1, 3)
            all_coords = np.ascontiguousarray(
                np.vstack([node_arr, elem_arr]) if len(elem_arr) else node_arr)
            self._zoom_coord_cache = (_ck, all_coords)

        pts = all_coords
        _MAXC = 200_000
        if len(pts) > _MAXC:
            pts = pts[::(len(pts) // _MAXC) + 1]

        M = mvp_matrix
        R = np.ascontiguousarray(np.stack([M[0, :3], M[1, :3], M[3, :3]], axis=1), dtype=np.float32)
        t = np.array([M[0, 3], M[1, 3], M[3, 3]], dtype=np.float32)
        cxyw = pts @ R + t                                                      

        w_c = cxyw[:, 2]
        valid_mask = w_c > 0
        if not np.any(valid_mask):
            return None

        cv = cxyw[valid_mask]
        pv = pts[valid_mask]
        inv_w = 1.0 / cv[:, 2]
        sx = (cv[:, 0] * inv_w + 1.0) * (view_w * 0.5)
        sy = (1.0 - cv[:, 1] * inv_w) * (view_h * 0.5)

        dist_sq = (sx - mouse_x) ** 2 + (sy - mouse_y) ** 2
        min_idx = int(np.argmin(dist_sq))

        if dist_sq[min_idx] < screen_radius ** 2:
            best_pt = pv[min_idx]
            return QVector3D(float(best_pt[0]), float(best_pt[1]), float(best_pt[2]))

        return None

    def _raycast_to_plane(self, mouse_x, mouse_y):
        """Unprojects mouse position into world space and intersects with active_view_plane."""
        if not self.active_view_plane:
            return None
        w, h = self.width(), self.height()
        full_area = (0, 0, w, h)
        m_view = self.viewMatrix()
        m_proj = self.projectionMatrix(region=full_area, viewport=full_area)
        mvp = np.array((m_proj * m_view).data()).reshape(4, 4).T
        try:
            inv_mvp = np.linalg.inv(mvp)
        except np.linalg.LinAlgError:
            return None

        ndc_x =  (2.0 * mouse_x / w) - 1.0
        ndc_y = -(2.0 * mouse_y / h) + 1.0

        near_clip = np.dot(inv_mvp, np.array([ndc_x, ndc_y, -1.0, 1.0]))
        far_clip  = np.dot(inv_mvp, np.array([ndc_x, ndc_y,  1.0, 1.0]))
        if near_clip[3] == 0 or far_clip[3] == 0:
            return None

        near_w = near_clip[:3] / near_clip[3]
        far_w  = far_clip[:3]  / far_clip[3]
        ray_dir = far_w - near_w

        axis     = self.active_view_plane['axis']
        val      = self.active_view_plane['value']
        axis_idx = {'x': 0, 'y': 1, 'z': 2}[axis]

        denom = ray_dir[axis_idx]
        if abs(denom) < 1e-9:
            return None

        t   = (val - near_w[axis_idx]) / denom
        hit = near_w + t * ray_dir
        return hit

    def update_inspection_dot(self, element, ratio):
        if not element or not self.current_model:
            return

        n1, n2 = element.node_i, element.node_j

        p1 = np.array([n1.x, n1.y, n1.z], dtype=float)
        p2 = np.array([n2.x, n2.y, n2.z], dtype=float)

        off_i = getattr(element, 'end_offset_i', 0.0)
        off_j = getattr(element, 'end_offset_j', 0.0)

        vec = p2 - p1
        length = np.linalg.norm(vec)

        if length > 1e-6:
            u = vec / length

            if off_i + off_j >= length:
                scale = (length / (off_i + off_j)) * 0.99
                p1 = p1 + (u * off_i * scale)
                p2 = p2 - (u * off_j * scale)
            else:
                p1 = p1 + (u * off_i)
                p2 = p2 - (u * off_j)

        pos = p1 + ratio * (p2 - p1)

        if not np.all(np.isfinite(pos)):
            return

        self.inspection_dot.setData(
            pos=pos.reshape(1, 3),
            color=(1, 0, 0, 1),
            size=10
        )

        self.inspection_dot.setVisible(True)

    def hide_inspection_dot(self):
        self.inspection_dot.setVisible(False)
        
    def _find_grid_cell_from_hit(self, hit):
        """Given a world point on the active plane, returns the 4 cell corners or None."""
        if not self.active_view_plane or not self.current_model:
            return None
        grids = self.current_model.grid
        axis  = self.active_view_plane['axis']
        val   = self.active_view_plane['value']

        def bracket(v, slist):
            lo = hi = None
            for gv in slist:
                if gv <= v + 0.001: lo = gv
                if gv >= v - 0.001 and hi is None: hi = gv; break
            if lo is None or hi is None or abs(lo - hi) < 0.001: return None, None
            return lo, hi

        xs = sorted(grids.x_grids)
        ys = sorted(grids.y_grids)
        zs = sorted(grids.z_grids)
        x, y, z = hit

        if axis == 'z':
            x_lo, x_hi = bracket(x, xs)
            y_lo, y_hi = bracket(y, ys)
            if None in [x_lo, x_hi, y_lo, y_hi]: return None
            return [(x_lo,y_lo,val),(x_hi,y_lo,val),(x_hi,y_hi,val),(x_lo,y_hi,val)]
        elif axis == 'x':
            y_lo, y_hi = bracket(y, ys)
            z_lo, z_hi = bracket(z, zs)
            if None in [y_lo, y_hi, z_lo, z_hi]: return None
            return [(val,y_lo,z_lo),(val,y_hi,z_lo),(val,y_hi,z_hi),(val,y_lo,z_hi)]
        elif axis == 'y':
            x_lo, x_hi = bracket(x, xs)
            z_lo, z_hi = bracket(z, zs)
            if None in [x_lo, x_hi, z_lo, z_hi]: return None
            return [(x_lo,val,z_lo),(x_hi,val,z_lo),(x_hi,val,z_hi),(x_lo,val,z_hi)]
        return None

    def _find_quick_area_cell_from_hit(self, hit):
        """Return the bounded grid cell with its shell normal along the positive plane axis."""
        plane = self.active_view_plane
        grid = getattr(self.current_model, 'grid', None)
        expected_axis = {'XY': 'z', 'XZ': 'y', 'YZ': 'x'}.get(self._view_mode)
        if not plane or grid is None or plane.get('axis') != expected_axis:
            return None

        point = np.asarray(hit, dtype=float)
        val = float(plane['value'])
        if point.shape != (3,) or not np.all(np.isfinite(point)) or not np.isfinite(val):
            return None
        axis_idx = {'x': 0, 'y': 1, 'z': 2}[expected_axis]
        if abs(point[axis_idx] - val) > 1e-7:
            return None

        def bracket(value, grid_values):
            lines = np.unique(np.asarray(grid_values, dtype=float))
            lines = lines[np.isfinite(lines)]
            if len(lines) < 2 or value < lines[0] - 1e-7 or value > lines[-1] + 1e-7:
                return None
                                                                                 
            near = np.flatnonzero(np.abs(lines - value) <= 1e-7)
            if len(near):
                value = lines[near[0]]
            index = min(max(int(np.searchsorted(lines, value, side='right')) - 1, 0), len(lines) - 2)
            lo, hi = float(lines[index]), float(lines[index + 1])
            return (lo, hi) if hi - lo > 1e-7 else None

        if expected_axis == 'z':
            xb, yb = bracket(point[0], grid.x_grids), bracket(point[1], grid.y_grids)
            if xb is None or yb is None:
                return None
            xl, xh = xb; yl, yh = yb
            return [(xl, yl, val), (xh, yl, val), (xh, yh, val), (xl, yh, val)]
        if expected_axis == 'x':
            yb, zb = bracket(point[1], grid.y_grids), bracket(point[2], grid.z_grids)
            if yb is None or zb is None:
                return None
            yl, yh = yb; zl, zh = zb
            return [(val, yl, zl), (val, yh, zl), (val, yh, zh), (val, yl, zh)]
        xb, zb = bracket(point[0], grid.x_grids), bracket(point[2], grid.z_grids)
        if xb is None or zb is None:
            return None
        xl, xh = xb; zl, zh = zb
        return [(xl, val, zl), (xl, val, zh), (xh, val, zh), (xh, val, zl)]

    def hide_quick_area_preview(self):
        self._quick_area_hover_cell = None
        self._quick_area_prev_border.setVisible(False)
        self._quick_area_prev_fill.setVisible(False)
        self.update()

    def _update_quick_area_preview(self, mouse_x, mouse_y):
        hit = self._raycast_to_plane(mouse_x, mouse_y)
        corners = self._find_quick_area_cell_from_hit(hit) if hit is not None else None
        if corners is None:
            self.hide_quick_area_preview()
            return
        self._show_quick_area_preview(corners)

    def _show_quick_area_preview(self, corners):
        """Keep the highlighted mesh and click target on the same grid cell."""
        if corners != self._quick_area_hover_cell or not self._quick_area_prev_border.visible():
            points = np.asarray(corners, dtype=np.float32)
            self._quick_area_prev_border.setData(pos=np.vstack([points, points[0]]))
            self._quick_area_prev_fill.setMeshData(
                vertexes=points, faces=np.array([[0, 1, 2], [0, 2, 3]], dtype=np.uint32))
        self._quick_area_hover_cell = corners
        self._quick_area_prev_border.setVisible(True)
        self._quick_area_prev_fill.setVisible(True)
        self.update()

    def _update_brace_preview(self, mouse_x, mouse_y):
        """Shows the orange X preview over the hovered grid cell."""
        hit = self._raycast_to_plane(mouse_x, mouse_y)
        if hit is None:
            self._brace_hover_cell = None
            self._brace_prev_x1.setVisible(False)
            self._brace_prev_x2.setVisible(False)
            self._brace_prev_border.setVisible(False)
            return

        corners = self._find_grid_cell_from_hit(hit)
        if corners is None:
            self._brace_hover_cell = None
            self._brace_prev_x1.setVisible(False)
            self._brace_prev_x2.setVisible(False)
            self._brace_prev_border.setVisible(False)
            return

        self._brace_hover_cell = corners
        c = corners

        self._brace_prev_x1.setData(pos=np.array([c[0], c[2]], dtype=np.float32))
        self._brace_prev_x2.setData(pos=np.array([c[1], c[3]], dtype=np.float32))

        border = np.array([c[0], c[1], c[2], c[3], c[0]], dtype=np.float32)
        self._brace_prev_border.setData(pos=border)

        self._brace_prev_x1.setVisible(True)
        self._brace_prev_x2.setVisible(True)
        self._brace_prev_border.setVisible(True)
        self.update()
    
    def _update_beam_col_preview(self, mouse_x, mouse_y):
        """Highlights the nearest grid segment (beam or column) under the mouse."""
        seg = self._find_nearest_grid_segment(mouse_x, mouse_y, self._beam_col_type)
        if seg is None:
            self._beam_col_hover_seg = None
            self._beam_col_prev_line.setVisible(False)
            self.update()
            return
        self._beam_col_hover_seg = seg
        p1, p2 = seg
        self._beam_col_prev_line.setData(pos=np.array([p1, p2], dtype=np.float32))
        self._beam_col_prev_line.setVisible(True)
        self.update()

    def _find_nearest_grid_segment(self, mouse_x, mouse_y, member_type):
        """
        Project every candidate grid segment to screen and return the (p1, p2)
        pair whose screen-space midpoint-to-line distance is smallest.
        """
        if not self.current_model or not self.current_model.grid:
            return None

        w, h = self.width(), self.height()
        full_area = (0, 0, w, h)
        m_view = self.viewMatrix()
        m_proj = self.projectionMatrix(region=full_area, viewport=full_area)
        mvp = np.array((m_proj * m_view).data()).reshape(4, 4).T

        grids = self.current_model.grid

        if self.active_view_plane:
            val = self.active_view_plane['value']
            axis = self.active_view_plane['axis']
            xs = [val] if axis == 'x' else sorted(grids.x_grids)
            ys = [val] if axis == 'y' else sorted(grids.y_grids)
            zs = [val] if axis == 'z' else sorted(grids.z_grids)
        else:
            xs = sorted(grids.x_grids)
            ys = sorted(grids.y_grids)
            zs = sorted(grids.z_grids)

        best_seg  = None
        best_dist = 18.0                        

        if member_type == 'column':
                                                               
            for x in xs:
                for y in ys:
                    for k in range(len(zs) - 1):
                        p1 = np.array([x, y, zs[k]])
                        p2 = np.array([x, y, zs[k + 1]])
                        d  = self._screen_dist_to_seg(p1, p2, mouse_x, mouse_y, mvp, w, h)
                        if d is not None and d < best_dist:
                            best_dist = d
                            best_seg  = (p1, p2)
        else:
                                                                    
            for y in ys:
                for z in zs:
                    for i in range(len(xs) - 1):
                        p1 = np.array([xs[i],     y, z])
                        p2 = np.array([xs[i + 1], y, z])
                        d  = self._screen_dist_to_seg(p1, p2, mouse_x, mouse_y, mvp, w, h)
                        if d is not None and d < best_dist:
                            best_dist = d
                            best_seg  = (p1, p2)
                                                                    
            for x in xs:
                for z in zs:
                    for j in range(len(ys) - 1):
                        p1 = np.array([x, ys[j],     z])
                        p2 = np.array([x, ys[j + 1], z])
                        d  = self._screen_dist_to_seg(p1, p2, mouse_x, mouse_y, mvp, w, h)
                        if d is not None and d < best_dist:
                            best_dist = d
                            best_seg  = (p1, p2)
        return best_seg

    def _screen_dist_to_seg(self, p1, p2, mx, my, mvp, w, h):
        """Pixel distance from (mx, my) to the projected 3-D segment p1→p2."""
        s1 = self._project_to_screen(p1[0], p1[1], p1[2], mvp, w, h)
        s2 = self._project_to_screen(p2[0], p2[1], p2[2], mvp, w, h)
        if s1 is None or s2 is None:
            return None
        x1, y1 = s1
        x2, y2 = s2
        l2 = (x2 - x1) ** 2 + (y2 - y1) ** 2
        if l2 == 0:
            return ((mx - x1) ** 2 + (my - y1) ** 2) ** 0.5
        t  = max(0.0, min(1.0, ((mx - x1) * (x2 - x1) + (my - y1) * (y2 - y1)) / l2))
        px = x1 + t * (x2 - x1)
        py = y1 + t * (y2 - y1)
        return ((mx - px) ** 2 + (my - py) ** 2) ** 0.5
    
    def keyPressEvent(self, event):
        super().keyPressEvent(event)
        event.ignore()

    def _interp_linear(self, ts, vals, t):
        """Piecewise-linear interpolation of vals over ts at parameter t (ts assumed sorted, 0-1)."""
        if t <= ts[0]: return vals[0]
        if t >= ts[-1]: return vals[-1]
        for i in range(len(ts) - 1):
            if ts[i] <= t <= ts[i + 1]:
                span = ts[i + 1] - ts[i]
                if span < 1e-9: return vals[i]
                frac = (t - ts[i]) / span
                return vals[i] + frac * (vals[i + 1] - vals[i])
        return vals[-1]

    def _draw_member_loads_legacy(self, model):
        """
        Visualizes Distributed Loads (Professional UX).
        - Unselected: Faint colored curtain ONLY (no arrows, no text). Keeps scene clean.
        - Selected: Darker curtain, Outline, 5 distinct arrows, and Text Label.
        - Trapezoidal/triangular loads (load.distances / load.magnitudes populated)
          get a multi-point "load curtain" whose height follows the profile,
          instead of the flat rectangular uniform-load curtain.
        """
        if not model.loads: return
        if not self.show_loads: return
        if self.load_type_filter == "nodal": return
        sel_set = set(self.selected_element_ids)
        
        sel_verts = []; sel_colors = []; sel_faces = []
        sel_idx_counter = 0
        sel_lines = []; sel_line_colors = []

        ghost_verts = []; ghost_colors = []; ghost_faces = []
        ghost_idx_counter = 0
        ghost_lines = []; ghost_line_colors = []

        loads_by_beam = {}
        for ld in model.loads:
            if hasattr(ld, 'element_id') and hasattr(ld, 'wx'):
                                                  
                if getattr(ld, 'is_tributary_generated', False) and not getattr(self, 'show_tributary_loads', False):
                    continue
                if self.visible_load_patterns and getattr(ld, 'pattern_name', None) not in self.visible_load_patterns:
                    continue
                
                key = (ld.element_id, getattr(ld, 'pattern_name', None))
                if key not in loads_by_beam:
                    loads_by_beam[key] = []
                loads_by_beam[key].append(ld)

        for load in model.loads:
                                                                              
            if getattr(load, 'is_tributary_generated', False) and not getattr(self, 'show_tributary_loads', False):
                continue

            if not hasattr(load, 'wx') or not hasattr(load, 'element_id'): continue
            if self.visible_load_patterns and load.pattern_name not in self.visible_load_patterns:
                continue
            
            el = model.elements.get(load.element_id)
            if not el: continue
            
            v1, v2 = self._end_states('frame', el)
            if v1 == 0 or v2 == 0: continue
            
            is_ghosted = (v1 != 2 or v2 != 2)
            is_selected = (el.id in sel_set)

            p1 = np.array([el.node_i.x, el.node_i.y, el.node_i.z])
            p2 = np.array([el.node_j.x, el.node_j.y, el.node_j.z])
            beam_vec = p2 - p1
            beam_len = np.linalg.norm(beam_vec)
            if beam_len == 0: continue
            beam_dir = beam_vec / beam_len 
            
            raw_w = [load.wx, load.wy, load.wz]
            
            dists = getattr(load, 'distances', None)
            mags  = getattr(load, 'magnitudes', None)
            if dists and mags and len(mags) > 0 and max(abs(m) for m in mags) > 1e-9:
                max_mag = max((abs(m) for m in mags), default=0.0)
                l_dir = getattr(load, 'load_direction', 'Gravity').upper()
                
                if l_dir == 'GRAVITY': 
                    raw_w[2] = max_mag if raw_w[2] == 0 else raw_w[2]
                elif 'X' in l_dir or '1' in l_dir: 
                    raw_w[0] = max_mag if raw_w[0] == 0 else raw_w[0]
                elif 'Y' in l_dir or '2' in l_dir: 
                    raw_w[1] = max_mag if raw_w[1] == 0 else raw_w[1]
                else: 
                    raw_w[2] = max_mag if raw_w[2] == 0 else raw_w[2]

            v1_ax, v2_ax, v3_ax = self._get_consistent_axes(el) 

            for axis_idx in range(3):
                val = raw_w[axis_idx]
                if abs(val) < 1e-6: continue

                if load.coord_system == "Local":
                    load_vec = [v1_ax, v2_ax, v3_ax][axis_idx]
                else:
                    load_vec = np.zeros(3); load_vec[axis_idx] = 1.0

                base_rgb = self._theme_ink_rgb()

                c_ghost      = (*base_rgb, 0.25)
                c_ghost_line = (*base_rgb, 0.60)
                c_sel_fill   = (*base_rgb, 0.55)
                c_line       = (*base_rgb, 1.00)                                  

                cross_prod = np.cross(beam_dir, load_vec)
                is_parallel = np.linalg.norm(cross_prod) < 0.01
                visual_shift = v2_ax * 0.5 if is_parallel else np.zeros(3)

                dists = getattr(load, 'distances', None)
                mags  = getattr(load, 'magnitudes', None)
                has_trap = bool(
                    dists and mags and len(dists) == len(mags) and len(dists) >= 2
                    and max(abs(m) for m in mags) > 1e-9
                )

                udll_val = 0.0
                has_companion_trap = False
                
                companion_loads = loads_by_beam.get((el.id, getattr(load, 'pattern_name', None)), [])

                for other_load in companion_loads:
                    if (getattr(other_load, 'coord_system', "Global") == getattr(load, 'coord_system', "Global") and
                        getattr(other_load, 'load_direction', "Gravity") == getattr(load, 'load_direction', "Gravity") and
                        other_load is not load):

                        o_dists = getattr(other_load, 'distances', None)
                        o_mags  = getattr(other_load, 'magnitudes', None)
                        o_is_trap = bool(o_dists and o_mags and len(o_dists) == len(o_mags) and len(o_dists) >= 2 and max(abs(m) for m in o_mags) > 1e-9)

                        if not o_is_trap:
                            udll_val += [other_load.wx, other_load.wy, other_load.wz][axis_idx]
                        else:
                            has_companion_trap = True
                                                                              
                if has_trap:
                    is_rel = getattr(load, 'is_relative', True)
                    pts_t = []
                    for d in dists:
                        t = d if is_rel else (d / beam_len if beam_len > 0 else 0.0)
                        pts_t.append(max(0.0, min(1.0, t)))

                    order = sorted(range(len(pts_t)), key=lambda k: pts_t[k])
                    ts_sorted   = [pts_t[k] for k in order]
                    
                    mags_sorted = [mags[k] + udll_val for k in order]

                    max_abs_mag = max((abs(m) for m in mags_sorted), default=0.0)
                    ref_magnitude = max(1.0, max_abs_mag)
                    
                    scale = min(0.6, 0.2 + (np.log10(ref_magnitude) * 0.1))

                    base_pts, top_pts = [], []
                    for t, m in zip(ts_sorted, mags_sorted):
                        pb = p1 + t * (p2 - p1) + visual_shift
                        point_scale = scale * (m / max_abs_mag) if max_abs_mag > 0 else 0.0
                        base_pts.append(pb)
                        top_pts.append(pb - point_scale * load_vec)

                    N = len(base_pts)

                    if is_ghosted:
                        c_fill, c_edge = (*base_rgb, 0.08), (*base_rgb, 0.20)
                        t_verts, t_colors, t_faces = ghost_verts, ghost_colors, ghost_faces
                        t_lines, t_line_colors = ghost_lines, ghost_line_colors
                    elif not is_selected:
                        c_fill, c_edge = c_ghost, c_ghost_line
                        t_verts, t_colors, t_faces = ghost_verts, ghost_colors, ghost_faces
                        t_lines, t_line_colors = ghost_lines, ghost_line_colors
                    else:
                        c_fill, c_edge = c_sel_fill, c_line
                        t_verts, t_colors, t_faces = sel_verts, sel_colors, sel_faces
                        t_lines, t_line_colors = sel_lines, sel_line_colors

                    start_idx = len(t_verts)
                    for pb, pt in zip(base_pts, top_pts):
                        t_verts.append(pb); t_colors.append(c_fill)
                        t_verts.append(pt); t_colors.append(c_fill)
                    for i in range(N - 1):
                        b0, tp0 = start_idx + 2 * i,     start_idx + 2 * i + 1
                        b1, tp1 = start_idx + 2 * i + 2, start_idx + 2 * i + 3
                        t_faces.append([b0, b1, tp1])
                        t_faces.append([b0, tp1, tp0])

                    for i in range(N - 1):
                        t_lines.extend([top_pts[i], top_pts[i + 1]])
                        t_line_colors.extend([c_edge, c_edge])
                    t_lines.extend([top_pts[0], base_pts[0]])
                    t_line_colors.extend([c_edge, c_edge])
                    t_lines.extend([top_pts[-1], base_pts[-1]])
                    t_line_colors.extend([c_edge, c_edge])

                    if is_selected and not is_ghosted:
                        v_right = beam_dir.copy()
                        if v_right[0] < -0.01: v_right = -v_right
                        v_up_text = np.array([0.0, 0.0, 1.0])
                        if abs(v_right[2]) > 0.99:
                            v_up_text = np.array([1.0, 0.0, 0.0])

                        q_scale = unit_registry.force_scale / unit_registry.length_scale
                        unit_str = f"{unit_registry.force_unit_name}/{unit_registry.length_unit_name}"
                        peak_signed = max(mags_sorted, key=lambda m: abs(m))
                        peak_val = peak_signed * q_scale

                        mid_top = np.mean(top_pts, axis=0)
                        label_pos = mid_top + (v_up_text * 0.20)

                        self.load_labels.append({
                            'owner_id': el.id, 'owner_type': 'element',
                            'pos_3d': label_pos.tolist(),
                            'text': f"peak {abs(peak_val):.2f} {unit_str}",
                            'val': max_abs_mag,
                            'color': list(c_line[:4]),
                            'v_right': v_right.tolist(),
                            'v_up': v_up_text.tolist(),
                            'align': 'center',
                            'text_height': 0.20
                        })

                        def add_arrow_var(tip_pos, direction, color, length):
                            if length < 1e-6: return
                            head_size = length * 0.3
                            tail = tip_pos + direction * length
                            sel_lines.extend([tail, tip_pos])
                            sel_line_colors.extend([color, color])
                            perp = np.array([1.0, 0.0, 0.0]) if abs(direction[2]) > 0.9 else np.array([0.0, 0.0, 1.0])
                            side_raw = np.cross(direction, perp)
                            side_n = np.linalg.norm(side_raw)
                            if side_n < 1e-9: return
                            side_vec = (side_raw / side_n) * head_size
                            base = tip_pos + direction * head_size
                            sel_lines.extend([tip_pos, base + side_vec, tip_pos, base - side_vec])
                            sel_line_colors.extend([color] * 4)

                        num_arrows = 3
                        for i in range(num_arrows):
                            t = i / (num_arrows - 1)
                            m_t = self._interp_linear(ts_sorted, mags_sorted, t)
                            if abs(m_t) < 1e-9:
                                continue
                            pt_tip = p1 + t * (p2 - p1) + visual_shift
                            point_scale = scale * (m_t / max_abs_mag) if max_abs_mag > 0 else 0.0
                            arrow_dir = -np.sign(point_scale) * load_vec
                            add_arrow_var(pt_tip, arrow_dir, c_line, abs(point_scale) * 0.9)

                    continue                                                                  

                if has_companion_trap:
                    continue
                
                magnitude = max(1.0, abs(val))
                scale = min(1.5, 0.5 + (np.log10(magnitude) * 0.2))
                sign = 1 if val > 0 else -1

                offset_vec = -1 * sign * load_vec * scale

                pt_base_1 = p1 + visual_shift
                pt_base_2 = p2 + visual_shift
                pt_top_1  = p1 + offset_vec + visual_shift
                pt_top_2  = p2 + offset_vec + visual_shift

                if is_ghosted:
                    c_ghost_dim      = (*base_rgb, 0.08)
                    c_ghost_line_dim = (*base_rgb, 0.20)
                    ghost_verts.extend([pt_base_1, pt_base_2, pt_top_2, pt_top_1])
                    idx = ghost_idx_counter
                    ghost_faces.extend([[idx, idx+1, idx+2], [idx, idx+2, idx+3]])
                    for _ in range(4): ghost_colors.append(c_ghost_dim)
                    ghost_idx_counter += 4
                    
                    ghost_lines.extend([pt_top_1, pt_top_2])
                    ghost_line_colors.extend([c_ghost_line_dim, c_ghost_line_dim])
                    continue 

                if not is_selected:
                                   
                    ghost_verts.extend([pt_base_1, pt_base_2, pt_top_2, pt_top_1])
                    idx = ghost_idx_counter
                    ghost_faces.extend([[idx, idx+1, idx+2], [idx, idx+2, idx+3]])
                    for _ in range(4): ghost_colors.append(c_ghost)
                    ghost_idx_counter += 4
                    
                    ghost_lines.extend([pt_top_1, pt_top_2])
                    ghost_line_colors.extend([c_ghost_line, c_ghost_line])
                    continue 

                v_right = beam_dir.copy()
                if v_right[0] < -0.01: v_right = -v_right                                  
                
                v_up_text = np.array([0.0, 0.0, 1.0])
                if abs(v_right[2]) > 0.99:                            
                    v_up_text = np.array([1.0, 0.0, 0.0])

                q_scale = unit_registry.force_scale / unit_registry.length_scale
                display_val = abs(val) * q_scale
                unit_str = f"{unit_registry.force_unit_name}/{unit_registry.length_unit_name}"

                mid_height = (pt_top_1 + pt_top_2) / 2
                label_pos = mid_height + (v_up_text * 0.20)

                self.load_labels.append({
                    'owner_id': el.id, 'owner_type': 'element',
                    'pos_3d': label_pos.tolist(),                               
                    'text': f"{display_val:.2f} {unit_str}",  
                    'val': val,
                    'color': list(c_line[:4]) if len(c_line) >= 4 else [0,0,0,1],
                    'v_right': v_right.tolist(),
                    'v_up': v_up_text.tolist(),
                    'align': 'center',
                    'text_height': 0.20
                })

                sel_verts.extend([pt_base_1, pt_base_2, pt_top_2, pt_top_1])
                idx = sel_idx_counter
                sel_faces.extend([[idx, idx+1, idx+2], [idx, idx+2, idx+3]])
                for _ in range(4): sel_colors.append(c_sel_fill)
                sel_idx_counter += 4

                sel_lines.extend([pt_top_1, pt_top_2, pt_top_1, pt_base_1, pt_top_2, pt_base_2])
                sel_line_colors.extend([c_line] * 6)

                num_arrows = 5
                arrow_dir = -sign * load_vec 
                arrow_len = scale * 0.9

                def add_arrow(tip_pos, direction, color):
                    head_size = arrow_len * 0.3
                    tail = tip_pos + direction * arrow_len
                    sel_lines.extend([tail, tip_pos])
                    sel_line_colors.extend([color, color])
                    
                    perp = np.array([1.0, 0.0, 0.0]) if abs(direction[2]) > 0.9 else np.array([0.0, 0.0, 1.0])
                    side_vec = np.cross(direction, perp)
                    side_vec = (side_vec / np.linalg.norm(side_vec)) * head_size
                    
                    base = tip_pos + direction * head_size
                    sel_lines.extend([tip_pos, base + side_vec, tip_pos, base - side_vec])
                    sel_line_colors.extend([color] * 4)

                for i in range(num_arrows):
                    t = i / (num_arrows - 1)
                    pt_tip = pt_base_1 + t * (pt_base_2 - pt_base_1)
                    add_arrow(pt_tip, arrow_dir, c_line)

        if ghost_verts:
            base_idx = len(self._pending_load_fill_verts)
            self._pending_load_fill_verts.extend(ghost_verts)
            for face in ghost_faces:
                self._pending_load_fill_faces.append([face[0] + base_idx,
                                                      face[1] + base_idx,
                                                      face[2] + base_idx])
            self._pending_load_fill_colors.extend(ghost_colors)

        if ghost_lines:
            self._pending_load_line_pos.extend(ghost_lines)
            self._pending_load_line_colors.extend(ghost_line_colors)

        if sel_verts:
            base_idx = len(self._pending_load_fill_verts)
            self._pending_load_fill_verts.extend(sel_verts)
            for face in sel_faces:
                self._pending_load_fill_faces.append([face[0] + base_idx,
                                                      face[1] + base_idx,
                                                      face[2] + base_idx])
            self._pending_load_fill_colors.extend(sel_colors)

        if sel_lines:
            self._pending_load_line_pos.extend(sel_lines)
            self._pending_load_line_colors.extend(sel_line_colors)

    def _draw_cable_loads(self, model):
        """Visualizes Distributed Loads assigned to Cables."""
        if not getattr(model, 'loads', None): return
        if not self.show_loads: return
        if self.load_type_filter == "nodal": return
        sel_set = set(getattr(self, 'selected_cable_ids', None) or [])

        sel_verts, sel_colors, sel_faces = [], [], []
        sel_idx_counter = 0
        sel_lines, sel_line_colors = [], []

        ghost_verts, ghost_colors, ghost_faces = [], [], []
        ghost_idx_counter = 0
        ghost_lines, ghost_line_colors = [], []
        
        for load in model.loads:
                                                          
            if not (hasattr(load, 'cable_id') and hasattr(load, 'val')):
                continue
            
            if self.visible_load_patterns and getattr(load, 'pattern_name', None) not in self.visible_load_patterns:
                continue

            cb = getattr(model, 'cables', {}).get(load.cable_id)
            if not cb: continue

            v1_state, v2_state = self._end_states('cable', cb)
            if v1_state == 0 or v2_state == 0: continue

            is_ghosted = (v1_state != 2 or v2_state != 2)
            is_selected = (cb.id in sel_set)

            p1 = np.array([cb.node_i.x, cb.node_i.y, cb.node_i.z])
            p2 = np.array([cb.node_j.x, cb.node_j.y, cb.node_j.z])
            cable_vec = p2 - p1
            cable_len = np.linalg.norm(cable_vec)
            if cable_len < 1e-6: continue
            cable_dir = cable_vec / cable_len

            val = load.val
            if abs(val) < 1e-6: continue

            l_dir = load.direction.upper()
            load_vec = np.zeros(3)
            
            if load.coord_system == "GLOBAL":
                if l_dir == 'GRAVITY': load_vec[2] = -1.0; val = abs(val)
                elif 'X' in l_dir: load_vec[0] = 1.0
                elif 'Y' in l_dir: load_vec[1] = 1.0
                elif 'Z' in l_dir: load_vec[2] = 1.0
            else:
                v1_ax = cable_dir
                up = np.array([1.0, 0.0, 0.0]) if np.isclose(abs(v1_ax[2]), 1.0) else np.array([0.0, 0.0, 1.0])
                v2_ax = np.cross(up, v1_ax)
                v2_ax /= np.linalg.norm(v2_ax)
                v3_ax = np.cross(v1_ax, v2_ax)
                
                if '1' in l_dir: load_vec = v1_ax
                elif '2' in l_dir: load_vec = v2_ax
                elif '3' in l_dir: load_vec = v3_ax

            base_rgb = self._theme_ink_rgb()
            c_ghost      = (*base_rgb, 0.25)
            c_ghost_line = (*base_rgb, 0.60)
            c_sel_fill   = (*base_rgb, 0.55)
            c_line       = (*base_rgb, 1.00)

            magnitude = max(1.0, abs(val))
            scale = min(1.5, 0.5 + (np.log10(magnitude) * 0.2))
            sign = 1 if val > 0 else -1
            
            offset_vec = sign * load_vec * scale

            pt_base_1 = p1
            pt_base_2 = p2
            pt_top_1  = p1 - offset_vec
            pt_top_2  = p2 - offset_vec

            if is_ghosted:
                ghost_verts.extend([pt_base_1, pt_base_2, pt_top_2, pt_top_1])
                idx = ghost_idx_counter
                ghost_faces.extend([[idx, idx+1, idx+2], [idx, idx+2, idx+3]])
                for _ in range(4): ghost_colors.append((*base_rgb, 0.08))
                ghost_idx_counter += 4
                ghost_lines.extend([pt_top_1, pt_top_2])
                ghost_line_colors.extend([(*base_rgb, 0.20)] * 2)
                continue

            if not is_selected:
                ghost_verts.extend([pt_base_1, pt_base_2, pt_top_2, pt_top_1])
                idx = ghost_idx_counter
                ghost_faces.extend([[idx, idx+1, idx+2], [idx, idx+2, idx+3]])
                for _ in range(4): ghost_colors.append(c_ghost)
                ghost_idx_counter += 4
                ghost_lines.extend([pt_top_1, pt_top_2])
                ghost_line_colors.extend([c_ghost_line, c_ghost_line])
                continue

            sel_verts.extend([pt_base_1, pt_base_2, pt_top_2, pt_top_1])
            idx = sel_idx_counter
            sel_faces.extend([[idx, idx+1, idx+2], [idx, idx+2, idx+3]])
            for _ in range(4): sel_colors.append(c_sel_fill)
            sel_idx_counter += 4

            sel_lines.extend([pt_top_1, pt_top_2, pt_top_1, pt_base_1, pt_top_2, pt_base_2])
            sel_line_colors.extend([c_line] * 6)

            num_arrows = 5
            arrow_dir = sign * load_vec
            arrow_len = scale * 0.9

            def add_arrow(tip_pos, direction, color):
                head_size = arrow_len * 0.3
                tail = tip_pos - direction * arrow_len
                sel_lines.extend([tail, tip_pos])
                sel_line_colors.extend([color, color])
                perp = np.array([1.0, 0.0, 0.0]) if abs(direction[2]) > 0.9 else np.array([0.0, 0.0, 1.0])
                side_vec = np.cross(direction, perp)
                side_vec = (side_vec / np.linalg.norm(side_vec)) * head_size
                base = tip_pos - direction * head_size
                sel_lines.extend([tip_pos, base + side_vec, tip_pos, base - side_vec])
                sel_line_colors.extend([color] * 4)

            for i in range(num_arrows):
                t = i / (num_arrows - 1)
                pt_tip = pt_base_1 + t * (pt_base_2 - pt_base_1)
                add_arrow(pt_tip, arrow_dir, c_line)

            v_right = cable_dir.copy()
            if v_right[0] < -0.01: v_right = -v_right
            v_up_text = np.array([0.0, 0.0, 1.0])
            if abs(v_right[2]) > 0.99: v_up_text = np.array([1.0, 0.0, 0.0])

            from core.units import unit_registry
            q_scale = unit_registry.force_scale / unit_registry.length_scale
            display_val = abs(val) * q_scale
            unit_str = f"{unit_registry.force_unit_name}/{unit_registry.length_unit_name}"

            mid_height = (pt_top_1 + pt_top_2) / 2
            label_pos = mid_height + (v_up_text * 0.20)

            self.load_labels.append({
                'owner_id': cb.id, 'owner_type': 'cable',
                'pos_3d': label_pos.tolist(),
                'text': f"{display_val:.2f} {unit_str}",
                'val': val,
                'color': list(c_line[:4]),
                'v_right': v_right.tolist(),
                'v_up': v_up_text.tolist(),
                'align': 'center',
                'text_height': 0.20
            })

        if ghost_verts:
            base_idx = len(self._pending_load_fill_verts)
            self._pending_load_fill_verts.extend(ghost_verts)
            for face in ghost_faces:
                self._pending_load_fill_faces.append([face[0]+base_idx, face[1]+base_idx, face[2]+base_idx])
            self._pending_load_fill_colors.extend(ghost_colors)
        if ghost_lines:
            self._pending_load_line_pos.extend(ghost_lines)
            self._pending_load_line_colors.extend(ghost_line_colors)
        if sel_verts:
            base_idx = len(self._pending_load_fill_verts)
            self._pending_load_fill_verts.extend(sel_verts)
            for face in sel_faces:
                self._pending_load_fill_faces.append([face[0]+base_idx, face[1]+base_idx, face[2]+base_idx])
            self._pending_load_fill_colors.extend(sel_colors)
        if sel_lines:
            self._pending_load_line_pos.extend(sel_lines)
            self._pending_load_line_colors.extend(sel_line_colors)

    def _update_tributary_visuals(self):
        """Draws the faint tributary integration-grid dot overlay ("Show Tributary
        Integration Grid" checkbox). The heatmap itself is NOT drawn here anymore —
        it's a real per-vertex-colored mesh uploaded through _update_area_vbo and
        drawn by vbo_manager.draw_areas, same pipeline as the normal slab fill.
        That's what fixes the lag, the additive-blend whiteout, and the striping
        artifact all at once: it's one small mesh per area, not a point cloud."""
        if not hasattr(self, 'trib_scatter') or self.trib_scatter not in self.items:
            self.trib_scatter = gl.GLScatterPlotItem()
            self.addItem(self.trib_scatter)

        if not getattr(self, 'show_tributary_mesh', False) or getattr(self, 'view_deflected', False):
            self.trib_scatter.setData(pos=np.empty((0,3)), color=np.empty((0,4)))
            return

        visuals = getattr(self.current_model, 'tributary_visuals', None)
        if not visuals or not visuals.get('points'):
            self.trib_scatter.setData(pos=np.empty((0,3)), color=np.empty((0,4)))
            return

        all_pts = np.vstack(visuals['points'])
        grid_colors = np.full((len(all_pts), 4), [1.0, 1.0, 1.0, 0.3], dtype=np.float32)
        self.trib_scatter.setData(pos=all_pts, color=grid_colors, size=2, pxMode=True)

    def _draw_local_axes(self, model):
        """Draws RGB arrows with heads at the center of each element representing local axes."""
        if not model.elements: return
        
        lines = []
        colors = []
        
        L = 0.6                          
        H = 0.15                        
        W = 0.06                       
        
        for el in model.elements.values():
            n1, n2 = el.node_i, el.node_j
            
            if self._vo_state('frame', el.id) != 2 or not (self._is_visible(n1.x, n1.y, n1.z) and self._is_visible(n2.x, n2.y, n2.z)):
                continue

            p1 = np.array([n1.x, n1.y, n1.z])
            p2 = np.array([n2.x, n2.y, n2.z])
            mid = (p1 + p2) / 2.0
            
            v1, v2, v3 = self._get_consistent_axes(el)
            
            v2_draw = v3
            v3_draw = -v2
                                          
            def add_arrow(direction, color):
                tip = mid + direction * L
                
                lines.append(mid)
                lines.append(tip)
                colors.append(color)
                colors.append(color)
                
                if abs(direction[2]) > 0.9: perp = np.array([1.0, 0.0, 0.0])
                elif abs(direction[1]) > 0.9: perp = np.array([1.0, 0.0, 0.0])
                else: perp = np.array([0.0, 0.0, 1.0])
                
                side = np.cross(direction, perp)
                side_n = np.linalg.norm(side)
                if side_n > 1e-9:
                    side = (side / side_n) * W
                
                base = tip - (direction * H)
                
                lines.append(tip); lines.append(base + side)
                colors.append(color); colors.append(color)
                
                lines.append(tip); lines.append(base - side)
                colors.append(color); colors.append(color)

            add_arrow(v1, (1.0, 0.0, 0.0, 1.0))
                                              
            add_arrow(v2_draw, (0.0, 1.0, 0.0, 1.0))
                                             
            add_arrow(v3_draw, (0.0, 0.0, 1.0, 1.0)) 
            
        if lines:
            self._pending_static_line_pos.extend(lines)
            self._pending_static_line_colors.extend(colors)
            
    def _draw_constraints(self, model):
        """
        Draws the Calculated Center of Mass (Master Node) for Diaphragms.
        Visualizes them as a Green Square with lines to connected nodes.
        Filters out diaphragms that do not belong to the active 2D view plane.
        """
        if not model.nodes: return

        groups = {}
        for n in model.nodes.values():
            if n.diaphragm_name:
                if n.diaphragm_name not in groups:
                    groups[n.diaphragm_name] = []
                groups[n.diaphragm_name].append(n)

        if not groups: return

        master_pos = []
        conn_lines = []
        
        for name, nodes in groups.items():
            if not nodes: continue
            
            cx = sum(n.x for n in nodes) / len(nodes)
            cy = sum(n.y for n in nodes) / len(nodes)
            cz = sum(n.z for n in nodes) / len(nodes)
            
            c_pt = [cx, cy, cz]
            
            if not self._is_visible(cx, cy, cz):
                continue
            if all(self._vo_state('node', n.id) != 2 for n in nodes):
                continue
                                                                                                       
            master_pos.append(c_pt)
            
            for n in nodes:
                                                                                        
                if self._is_visible(n.x, n.y, n.z) and self._vo_state('node', n.id) == 2:
                    conn_lines.append(c_pt)
                    conn_lines.append([n.x, n.y, n.z])

        self._push_static_lines(conn_lines, (0, 1, 0, 0.85))

        marker_r = 0.15
        marker_lines = []
        for cx, cy, cz in master_pos:
            marker_lines.extend([
                [cx - marker_r, cy, cz], [cx + marker_r, cy, cz],
                [cx, cy - marker_r, cz], [cx, cy + marker_r, cz],
                [cx, cy, cz - marker_r], [cx, cy, cz + marker_r],
            ])
        self._push_static_lines(marker_lines, (1.0, 0.85, 0.0, 1.0))

    def _area_load_sample_points(self, pts, centroid, n=5):
        """
        Returns up to n interior sample points within a shell polygon
        for evenly distributing load arrows across the face.
        """
        n_nodes = len(pts)
        samples = [centroid]
 
        if n_nodes == 3:                                                              
            for i in range(3):
                mid = (pts[i] + pts[(i + 1) % 3]) / 2.0
                samples.append(0.55 * mid + 0.45 * centroid)
        elif n_nodes == 4:                                      
            for i in range(4):
                qc = (pts[i] + pts[(i + 1) % 4] + 2.0 * centroid) / 4.0
                samples.append(qc)
        else:                                                           
            step = max(1, n_nodes // 4)
            for i in range(0, n_nodes, step):
                mid = (pts[i] + pts[(i + 1) % n_nodes]) / 2.0
                samples.append(0.55 * mid + 0.45 * centroid)
 
        return samples[:n]
 
    def _fan_triangulate(self, pts):
        """Fan-triangulate a convex polygon (list / array of np.ndarray)."""
        return [(pts[0], pts[i], pts[i + 1]) for i in range(1, len(pts) - 1)]
 
    def _draw_member_point_loads(self, model):
        """
        Visualizes Member Point Loads.
        - Always: Draws Arrow geometry (Force or Moment).
        - Selected: Draws Text Label with Units.
        """
        if not model.loads: return
        if not self.show_loads: return
        if self.load_type_filter == "nodal": return 
        sel_set = set(self.selected_element_ids)

        arrow_lines = []
        arrow_colors = []
        
        L = 2.0; H = 0.5; W = 0.2

        for load in model.loads:

            if not hasattr(load, 'force'): continue 
            if self.visible_load_patterns and load.pattern_name not in self.visible_load_patterns: continue

            el = model.elements.get(load.element_id)
            if not el: continue
            
            v1, v2 = self._end_states('frame', el)
            if v1 == 0 or v2 == 0: continue
            is_ghosted = (v1 != 2 or v2 != 2)

            is_selected = (el.id in sel_set)

            p1 = np.array([el.node_i.x, el.node_i.y, el.node_i.z])
            p2 = np.array([el.node_j.x, el.node_j.y, el.node_j.z])
            beam_vec = p2 - p1
            beam_len = np.linalg.norm(beam_vec)
            if beam_len == 0: continue
            
            actual_dist = load.dist * beam_len if load.is_relative else load.dist
            load_pos = p1 + (beam_vec / beam_len) * actual_dist
            
            dir_vec = np.array([0.0, 0.0, 0.0])
            if load.coord_system == "Global":
                if "Gravity" in load.direction: dir_vec = np.array([0, 0, -1])
                elif "X" in load.direction: dir_vec = np.array([1, 0, 0])
                elif "Y" in load.direction: dir_vec = np.array([0, 1, 0])
                elif "Z" in load.direction: dir_vec = np.array([0, 0, 1])
            else:
                v1, v2, v3 = self._get_consistent_axes(el)
                if "1" in load.direction: dir_vec = v1
                elif "2" in load.direction: dir_vec = v2
                elif "3" in load.direction: dir_vec = v3

            val = load.force
            if val == 0: continue
            
            draw_dir = dir_vec * (1.0 if val > 0 else -1.0)
            norm = np.linalg.norm(draw_dir)
            if norm > 0: draw_dir /= norm
            
            is_moment = hasattr(load, 'load_type') and load.load_type == "Moment"
            
            c = self._theme_ink_color(0.15) if is_ghosted else self._theme_ink_color()

            tip = load_pos
            tail = tip - (draw_dir * L)
            arrow_lines.append(tail); arrow_lines.append(tip)
            arrow_colors.append(c); arrow_colors.append(c)

            def add_head(base_pt):
                if abs(draw_dir[2]) > 0.9: perp = np.array([1.0, 0.0, 0.0])
                elif abs(draw_dir[1]) > 0.9: perp = np.array([1.0, 0.0, 0.0])
                else: perp = np.array([0.0, 0.0, 1.0])
                w_vec = perp * W
                base = base_pt - (draw_dir * H)
                arrow_lines.append(base_pt); arrow_lines.append(base + w_vec)
                arrow_lines.append(base_pt); arrow_lines.append(base - w_vec)
                for _ in range(4): arrow_colors.append(c)

            add_head(tip)
            if is_moment:
                add_head(tip - (draw_dir * (H * 0.8)))

            if not is_ghosted and is_selected:
                self._add_load_label(load_pos, draw_dir, val, "Moment" if is_moment else "Force", c, owner_id=el.id, owner_type='element')

        if arrow_lines:
            self._pending_load_line_pos.extend(arrow_lines)
            self._pending_load_line_colors.extend(arrow_colors)

    def _hinges_allowed(self, model=None):
        """Hinge markers are shown while modeling, and for results only when the
        displayed case is a Nonlinear Static run (the one solver that supports
        hinges). For any other results (linear static, modal, buckling, linear
        time history, ...) they disappear, deformed or not. Going back to
        modeling clears the results, which brings them back."""
        model = model if model is not None else getattr(self, 'current_model', None)
        if model is None or not getattr(model, 'has_results', False):
            return True
        res = getattr(model, 'results', None)
        if not isinstance(res, dict):
            return True
        info = res.get('info')
        return isinstance(info, dict) and info.get('type') == 'Nonlinear Static'

    def _draw_frame_hinges(self, model):
        """
        Visualizes assigned frame hinges as small diamond markers at
        their relative distance along the element. Visual only - a
        hinge marker is not its own pickable entity; click the frame
        to select it (see the Element Info dialog for the hinge list).
        Not wired to the solver.
        """
        frame_hinges = getattr(model, 'frame_hinges', None)
        if not frame_hinges: return
        if not self._hinges_allowed(model): return

        if self._hinges_follow_deformed():
            res = self._hinge_lines_for_step(getattr(self, 'ltha_current_step', 0))
            if res is not None:
                self._pending_load_line_pos.extend(list(res[0]))
                self._pending_load_line_colors.extend(list(res[1]))
                return

        hinge_lines = []
        hinge_colors = []
        hinge_color = self._hinge_default_rgba_tuple()
        hinge_shape = self._hinge_shape()                       

        for h in frame_hinges.values():
            el = model.elements.get(h.element_id)
            if not el: continue

            v1, v2 = self._end_states('frame', el)
            if v1 == 0 or v2 == 0: continue
            is_ghosted = (v1 != 2 or v2 != 2)

            p1 = np.array([el.node_i.x, el.node_i.y, el.node_i.z])
            p2 = np.array([el.node_j.x, el.node_j.y, el.node_j.z])
            beam_vec = p2 - p1
            beam_len = np.linalg.norm(beam_vec)
            if beam_len == 0: continue

            pos = p1 + (beam_vec / beam_len) * (h.rel_dist * beam_len)

            _, vy, vz = self._get_consistent_axes(el)
            oi, oj, ys, zs = self._hinge_section_offsets(el)
            sr = float(h.rel_dist)
            pos = pos + (1.0 - sr) * oi + sr * oj + ys * np.asarray(vy) + zs * np.asarray(vz)

            c = self._theme_ink_color(0.15) if is_ghosted else hinge_color

            Sy, Sz = self._hinge_marker_half_sizes(el, hinge_shape)
            seg = self._hinge_outline_points(pos[None, :], np.asarray(vy)[None, :],
                                             np.asarray(vz)[None, :],
                                             np.array([[Sy]]), np.array([[Sz]]), hinge_shape)
            hinge_lines.extend(list(seg))
            hinge_colors.extend([c] * len(seg))

        if hinge_lines:
            self._pending_load_line_pos.extend(hinge_lines)
            self._pending_load_line_colors.extend(hinge_colors)

    _HINGE_SECTION_MARGIN = 1.10                                                 

    @staticmethod
    def _hinge_section_offsets(el):
        """(joint_offset_i, joint_offset_j, y_shift, z_shift) exactly as the
        extruded mesh applies them: the section centre sits at
        pos + (1-s)*off_i + s*off_j + y_shift*v2 + z_shift*v3."""
        z3 = np.zeros(3)
        try:
            oi = np.asarray(getattr(el, 'joint_offset_i', z3), dtype=float).reshape(3)
        except Exception:
            oi = z3
        try:
            oj = np.asarray(getattr(el, 'joint_offset_j', z3), dtype=float).reshape(3)
        except Exception:
            oj = z3
        try:
            ys, zs = el.get_cardinal_offsets()
        except Exception:
            ys, zs = 0.0, 0.0
        return oi, oj, float(ys), float(zs)

    def _hinge_marker_half_sizes(self, el, shape=None):
        """(half-extent along local-2, along local-3) of the hinge marker for
        this element: the smallest marker of the chosen shape that encloses the
        whole section outline, times a small margin, so the marker is never
        buried inside the member. Falls back to 0.25 when the section has no
        outline.
          Diamond: half-diagonals   (|y|/Sy + |z|/Sz <= 1)
          Square:  half-widths      (the outline's bounding box)
          Circle:  ellipse semi-axes (y^2/Sy^2 + z^2/Sz^2 <= 1)"""
        shape = shape or self._hinge_shape()
        try:
            pts = np.asarray(el.section.get_shape_coords() or [], dtype=float)
            if pts.ndim == 2 and pts.shape[0] >= 3 and pts.shape[1] >= 2:
                ya, za = np.abs(pts[:, 0]), np.abs(pts[:, 1])
                ym, zm = max(float(ya.max()), 1e-6), max(float(za.max()), 1e-6)
                                                                       
                if shape == 'Square':
                    k = 1.0
                elif shape == 'Circle':
                    k = float(np.max(np.hypot(ya / ym, za / zm)))
                else:
                    k = float(np.max(ya / ym + za / zm))
                m = self._HINGE_SECTION_MARGIN
                return ym * k * m, zm * k * m
        except Exception:
            pass
        return 0.25, 0.25

    _HINGE_SHAPES = ('Circle', 'Square', 'Diamond')
    _HINGE_SHAPE_DEFAULT = 'Circle'
    _HINGE_CIRCLE_SEGMENTS = 32

    def _hinge_shape(self):
        s = str(self.display_config.get('hinge_shape', self._HINGE_SHAPE_DEFAULT)).strip().title()
        return s if s in self._HINGE_SHAPES else self._HINGE_SHAPE_DEFAULT

    def _hinge_default_rgba_tuple(self):
        """Undeformed / no-state marker colour (display_config['hinge_color'],
        tuple or list from a saved file) as a 4-float tuple."""
        c = self.display_config.get('hinge_color')
        try:
            t = tuple(float(x) for x in c)
            if len(t) == 3:
                t = t + (1.0,)
            if len(t) == 4:
                return t
        except Exception:
            pass
        return tuple(float(x) for x in self._HINGE_DEFAULT_RGBA)

    def _hinge_default_rgba(self):
        return np.array(self._hinge_default_rgba_tuple(), dtype=np.float32)

    @classmethod
    def _hinge_unit_outline(cls, shape):
        """Unit outline vertices (K, 2) in (local-2, local-3) units."""
        if shape == 'Square':
            return np.array([(1, 1), (-1, 1), (-1, -1), (1, -1)], dtype=float)
        if shape == 'Circle':
            th = np.linspace(0.0, 2.0 * np.pi, cls._HINGE_CIRCLE_SEGMENTS, endpoint=False)
            return np.stack([np.cos(th), np.sin(th)], axis=1)
        return np.array([(1, 0), (0, 1), (-1, 0), (0, -1)], dtype=float)            

    def _hinge_outline_points(self, pos, vy, vz, Sy, Sz, shape):
        """Line-segment end points for N markers. pos/vy/vz are (N,3), Sy/Sz are
        (N,1). Returns (N*K*2, 3): per marker, K segments of (start, end)."""
        U = self._hinge_unit_outline(shape)
        a = U[:, 0][None, :, None]
        b = U[:, 1][None, :, None]
        V = (pos[:, None, :]
             + vy[:, None, :] * (Sy[:, :, None] * a)
             + vz[:, None, :] * (Sz[:, :, None] * b))
        W = np.roll(V, -1, axis=1)
        return np.stack([V, W], axis=2).reshape(-1, 3)

    _HINGE_STATE_RGBA = np.array([
        (0x2e / 255, 0x9e / 255, 0x4f / 255, 1.0),                    
        (0xe6 / 255, 0xa7 / 255, 0x00 / 255, 1.0),                    
        (0xe0 / 255, 0x66 / 255, 0x2a / 255, 1.0),                     
        (0xc0 / 255, 0x39 / 255, 0x2b / 255, 1.0),                  
        (1.0, 0.0, 0.0, 1.0),                                                     
    ], dtype=np.float32)
    _HINGE_DEFAULT_RGBA = np.array((0.0, 0.47, 0.84, 1.0), dtype=np.float32)                                                
    _HINGE_BLINK_PERIOD = 1.6                              
    _HINGE_BLINK_STRENGTH = 0.85                                                         

    def _hinges_follow_deformed(self):
        """True whenever a step history is loaded and the deformed shape is on.
        Independent of the playback VBO, so the very first (paused) deformed
        view already puts the hinges in the right place."""
        return bool(self.view_deflected
                    and getattr(self, 'ltha_mode', False)
                    and getattr(self, 'ltha_history', None))

    @staticmethod
    def _hist6(a, n):
        """History array -> (n, 6) float, holding the last value if it is short."""
        out = np.zeros((n, 6), dtype=np.float64)
        if a is None:
            return out
        a = np.asarray(a, dtype=np.float64)
        if a.ndim != 2 or a.shape[0] == 0:
            return out
        m = min(a.shape[0], n)
        out[:m] = a[:m, :6]
        if m < n:
            out[m:] = a[m - 1, :6]
        return out

    def _ensure_hinge_cache(self):
        """Per-hinge constants + the end-node displacement histories, read
        straight from ltha_history (no dependence on ltha_tensor)."""
        c = getattr(self, '_ltha_hinge_cache', None)
        shape = self._hinge_shape()
        if c is not None and c.get('shape') != shape:
            c = None                                                                     
        if c is not None:
            return c
        model = self.current_model
        frame_hinges = getattr(model, 'frame_hinges', None) if model is not None else None
        if not frame_hinges:
            return None
        hist = getattr(self, 'ltha_history', None) or {}
        n_steps = max(int(getattr(self, 'ltha_n_steps', 0)), 1)

        keys, P1, P2, Hi, Hj, Rs, ss, ghost, SY, SZ = [], [], [], [], [], [], [], [], [], []
        OI, OJ, YS, ZS = [], [], [], []
        for h in frame_hinges.values():
            el = model.elements.get(h.element_id)
            if not el:
                continue
            v1, v2 = self._end_states('frame', el)
            if v1 == 0 or v2 == 0:
                continue
            p1 = np.array([el.node_i.x, el.node_i.y, el.node_i.z], dtype=float)
            p2 = np.array([el.node_j.x, el.node_j.y, el.node_j.z], dtype=float)
            if np.linalg.norm(p2 - p1) == 0:
                continue
            keys.append(str(h.element_id))
            P1.append(p1); P2.append(p2)
            Hi.append(self._hist6(hist.get(str(el.node_i.id)), n_steps))
            Hj.append(self._hist6(hist.get(str(el.node_j.id)), n_steps))
            Rs.append(np.vstack(self._get_consistent_axes(el)))
            ss.append(float(h.rel_dist))
            ghost.append(v1 != 2 or v2 != 2)
            sy, sz = self._hinge_marker_half_sizes(el, shape)
            SY.append(sy); SZ.append(sz)
            oi, oj, ys, zs = self._hinge_section_offsets(el)
            OI.append(oi); OJ.append(oj); YS.append(ys); ZS.append(zs)

        if not keys:
            return None
        self._ltha_hinge_cache = {
            'keys': keys,
            'P1': np.array(P1), 'P2': np.array(P2),
            'Hi': np.array(Hi), 'Hj': np.array(Hj),
            'R': np.array(Rs), 's': np.array(ss),
            'ghost': np.array(ghost, dtype=bool),
            'Sy': np.array(SY), 'Sz': np.array(SZ),
            'Oi': np.array(OI), 'Oj': np.array(OJ),
            'Ys': np.array(YS), 'Zs': np.array(ZS),
            'shape': shape,
            'state_src': None, 'state': None,
        }
        return self._ltha_hinge_cache

    def _hinge_state_matrix(self, c):
        """(n_hinges, n_steps) int8 of worst fiber state, -1 = unknown. Rebuilt
        only when the state history object changes."""
        src = getattr(self, 'ltha_hinge_state_idx', None)
        if c['state_src'] is src and c['state'] is not None:
            return c['state']
        n_steps = c['Hi'].shape[1]
        mat = np.full((len(c['keys']), n_steps), -1, dtype=np.int8)
        if src:
            for r, k in enumerate(c['keys']):
                a = src.get(k)
                if a is None or len(a) == 0:
                    continue
                m = min(len(a), n_steps)
                mat[r, :m] = a[:m]
                if m < n_steps:
                    mat[r, m:] = a[m - 1]
        c['state_src'], c['state'] = src, mat
        return mat

    def _hinge_lines_for_step(self, t, deformed=None):
        """Diamond markers for step t. deformed=True puts them at their
        DEFORMED position and colours them by the most critical fiber state;
        otherwise undeformed, default colour. The hinge selected in the Hinge
        Results dialog pulses (bigger + towards the ink colour). Returns
        (lines (M,3), colors (M,4)) or None when there is nothing to draw."""
        if deformed is None:
            deformed = self._hinges_follow_deformed()
        c = self._ensure_hinge_cache()
        if c is None:
            return None
        n = c['Hi'].shape[1]
        t = max(0, min(int(t), n - 1))
        P1, P2, R, s = c['P1'], c['P2'], c['R'], c['s']

        if deformed:
            pos, T = get_deflected_points_batch(
                P1, P2, c['Hi'][:, t, :], c['Hj'][:, t, :], R, s,
                scale=self.deflection_scale)
        else:
            pos = P1 + (P2 - P1) * s[:, None]
            T = R[:, 0, :]

        v1, vy, vz = R[:, 0, :], R[:, 1, :], R[:, 2, :]
        k = np.cross(v1, T)
        f = 1.0 / np.maximum(1.0 + np.einsum('ij,ij->i', v1, T), 1e-6)

        def _rot(v):
            kv = np.cross(k, v)
            return v + kv + np.cross(k, kv) * f[:, None]

        vy2, vz2 = _rot(vy), _rot(vz)

        if deformed:
            sc = self.deflection_scale
            twi = np.einsum('nij,nj->ni', R, c['Hi'][:, t, 3:] * sc)[:, 0]
            twj = np.einsum('nij,nj->ni', R, c['Hj'][:, t, 3:] * sc)[:, 0]
            tw = twi + (twj - twi) * s
            ct, st = np.cos(tw)[:, None], np.sin(tw)[:, None]
            v2t = ct * vy + st * vz
            v2c = v2t - np.sum(v2t * T, axis=1, keepdims=True) * T
            n2 = np.linalg.norm(v2c, axis=1, keepdims=True)
            ok = (n2[:, 0] > 1e-9)[:, None]
            v2c = np.where(ok, v2c / np.maximum(n2, 1e-30), vy2)
            v3c = np.where(ok, np.cross(T, v2c), vz2)
            vy2, vz2 = v2c, v3c
        pos = (pos + (1.0 - s)[:, None] * c['Oi'] + s[:, None] * c['Oj']
               + c['Ys'][:, None] * vy2 + c['Zs'][:, None] * vz2)

        rgba = np.tile(self._hinge_default_rgba(), (len(pos), 1))
        if deformed:
            mat = self._hinge_state_matrix(c)
            st = mat[:, min(t, mat.shape[1] - 1)]
            known = st >= 0
            if np.any(known):
                rgba[known] = self._HINGE_STATE_RGBA[np.clip(st[known], 0, 4)]
        if np.any(c['ghost']):
            rgba[c['ghost']] = np.array(self._theme_ink_color(0.15), dtype=np.float32)

        Sy, Sz = c['Sy'].copy(), c['Sz'].copy()
        hk = getattr(self, '_hinge_highlight_key', None)
        if hk is not None:
            sel = np.array([key == hk for key in c['keys']])
            if np.any(sel):
                ph = 0.5 * (1.0 - np.cos(2.0 * np.pi * time.time() / self._HINGE_BLINK_PERIOD))
                ph *= self._HINGE_BLINK_STRENGTH                                                
                ink = np.array(self._theme_ink_color(1.0), dtype=np.float32)
                rgba[sel] = rgba[sel] * (1.0 - ph) + ink * ph

        Sy, Sz = Sy[:, None], Sz[:, None]
        lines = self._hinge_outline_points(pos, vy2, vz2, Sy, Sz, c.get('shape') or self._hinge_shape())
        colors = np.repeat(rgba, lines.shape[0] // max(len(pos), 1), axis=0)
        return lines.astype(np.float32), colors.astype(np.float32)

    def _update_ltha_hinges(self, t):
        """Re-upload the (tiny) hinge line buffer. Called inside paintGL, GL
        context already current. Only touches the hinge lines, so it is only
        used while results are on screen (loads are not drawn then)."""
        if not getattr(self, 'show_hinges', False):
            return
        if not self._hinges_allowed():
            return
        try:
            res = self._hinge_lines_for_step(t)
            if res is None:
                return
            self.vbo_manager.upload_load_geometry(
                np.zeros((0, 3), dtype=np.float32), np.zeros((0, 4), dtype=np.float32),
                np.zeros((0, 3), dtype=np.uint32), res[0], res[1])
        except Exception as e:
            print(f"[Canvas] hinge update failed: {e}")

    def set_highlight_hinge(self, element_id):
        """Pulse the marker of this element's hinge slowly so it can be found
        in 3D. Pass None to stop."""
        key = None if element_id is None else str(element_id)
        self._hinge_highlight_key = key
        if key is None:
            if self._hinge_blink_timer is not None:
                self._hinge_blink_timer.stop()
        else:
            if self._hinge_blink_timer is None:
                self._hinge_blink_timer = QTimer(self)
                self._hinge_blink_timer.setInterval(50)
                self._hinge_blink_timer.timeout.connect(self._on_hinge_blink_tick)
            if not self._hinge_blink_timer.isActive():
                self._hinge_blink_timer.start()
        self._needs_hinge_refresh = True
        self.update()

    def _on_hinge_blink_tick(self):
        self._needs_hinge_refresh = True
        self.update()

    def show_pivot_dot(self, visible=True):
        if visible:
                                               
            c = self.opts['center']
            self.pivot_dot.setData(pos=np.array([[c.x(), c.y(), c.z()]]))
            self.pivot_dot.setVisible(True)
            self.pivot_timer.start(500)                                  
        else:
            self.pivot_dot.setVisible(False)

    def update_preview_line(self, start, end):
        """Updates the rubber-band preview line during draw mode."""
        if start is None or end is None:
            self.preview_line.setVisible(False)
            return
        pts = np.array([list(start), list(end)])
        self.preview_line.setData(pos=pts)
        self.preview_line.setVisible(True)

    def hide_preview_line(self):
        self.preview_line.setVisible(False)

    def _get_consistent_axes(self, el):
        """
        Unified logic to calculate local axes (v1, v2, v3) for 
        Extrusions, Arrows, and Loads. Ensures visual consistency.
        """
        n1, n2 = el.node_i, el.node_j
        p1 = np.array([n1.x, n1.y, n1.z])
        p2 = np.array([n2.x, n2.y, n2.z])
        
        vx = p2 - p1
        L = np.linalg.norm(vx)
        if L < 1e-6: return np.eye(3)                    
        vx /= L
        
        if np.isclose(abs(vx[2]), 1.0): 
             up = np.array([1.0, 0.0, 0.0]) 
        else:
             up = np.array([0.0, 0.0, 1.0])

        vy = np.cross(up, vx)
        vy /= np.linalg.norm(vy)
        
        vz = np.cross(vx, vy)
        vz /= np.linalg.norm(vz)
        
        beta = getattr(el, 'beta_angle', 0.0)
        if beta != 0:
            rad = np.radians(beta)
            c = np.cos(rad); s = np.sin(rad)
                                  
            vy_rot = c * vy + s * vz
            vz_rot = -s * vy + c * vz
            vy, vz = vy_rot, vz_rot
            
        return vx, vy, vz

    def invalidate_deflection_cache(self):
        """
        Clears the deflection cache when results or settings change.
        """
        self.deflection_cache.clear()
        self.cache_scale_used = None
        
    def _smart_redraw(self):
        """
        Efficiently updates only the selection-dependent items.
        Used by blink timer to avoid full scene rebuild.
        Blink is implemented by toggling overlay visibility — no geometry rebuild.
        """
        if not self.current_model:
            return

        current_state = {
            'nodes': self.selected_node_ids[:],
            'elements': self.selected_element_ids[:],
            'blink': self.blink_state
        }

        if current_state == self.last_selection_state:
            return

        self.last_selection_state = current_state

        visible = self.blink_state
        for item in getattr(self, '_sel_overlay_items', []):
            try:
                item.setVisible(visible)
            except Exception:
                pass

        self.update()

    def paintGL(self, *args, **kwargs):
        glEnable(GL_MULTISAMPLE)

        if _GL_PROFILE:
            _pt = [time.perf_counter()]
            _pm = {}
            def _mark(name):
                glFinish()
                _n = time.perf_counter()
                _pm[name] = _pm.get(name, 0.0) + (_n - _pt[0]) * 1000.0
                _pt[0] = _n
        else:
            def _mark(name):
                pass
        _mark('pre')

        top_items = getattr(self, '_sel_overlay_items', []) + [
            self.preview_line, self._beam_col_prev_line, 
            self._brace_prev_x1, self._brace_prev_x2, 
            self._brace_prev_border, self.snap_ring, self.snap_dot,
            self._quick_area_prev_border, self._quick_area_prev_fill,
            self.pivot_dot, self.inspection_dot,
            self._area_preview_line, self._area_interior_lines
        ]
        if hasattr(self, 'trib_scatter'):
            top_items.append(self.trib_scatter)
        
        vis_states = []
        for item in top_items:
            vis_states.append(item.visible())
            item.setVisible(False)

        self.makeCurrent()
                                                                            
        if hasattr(self, 'vbo_manager') and self.vbo_manager.is_initialized:
            _load_w, _load_h = self.width(), self.height()
            _load_viewport = (0, 0, _load_w, _load_h)
            _load_mvp = np.array((self.projectionMatrix(
                region=_load_viewport, viewport=_load_viewport) *
                self.viewMatrix()).data(), dtype=float).reshape(4, 4).T
            self._refresh_distributed_load_view(_load_mvp, _load_w, _load_h)
        _fxaa_on = self._fxaa_begin()
        glViewport(0, 0, int(self.deviceWidth()), int(self.deviceHeight()))
        if hasattr(self, 'vbo_manager'):
            self.vbo_manager.set_viewport_px(self.deviceWidth(), self.deviceHeight())
        bgcolor = self.opts.get('bgcolor', (0.0, 0.0, 0.0, 1.0))
        glClearColor(*bgcolor)
        glClear(GL_DEPTH_BUFFER_BIT | GL_COLOR_BUFFER_BIT)
        w, h = self.deviceWidth(), self.deviceHeight()
        region = (0, 0, w, h)
        self.setProjection(region=region, viewport=region)
        self.setModelview()
        _mark('fxaa_begin+setup')

        _skip = {self.force_mesh_item, self.force_line_item}
        for item in self.items:
            if item not in _skip and item.visible():
                try:
                    item.paint()
                except Exception:
                    pass

        _mark('pyqtgraph_items')
        if hasattr(self, 'vbo_manager') and self.vbo_manager.is_initialized:
            
            w, h = self.width(), self.height()
            full_area = (0, 0, w, h)
            if not hasattr(self, '_paintgl_m_view'):
                self._paintgl_m_view = np.empty((4, 4), dtype=np.float32)
                self._paintgl_m_proj = np.empty((4, 4), dtype=np.float32)
            self._paintgl_m_view[:] = np.array(self.viewMatrix().data(), dtype=np.float32).reshape(4, 4)
            self._paintgl_m_proj[:] = np.array(self.projectionMatrix(region=full_area, viewport=full_area).data(), dtype=np.float32).reshape(4, 4)
            m_view = self._paintgl_m_view
            m_proj = self._paintgl_m_proj

            light = None
            if self.display_config.get("lighting_enabled", False):
                az = np.radians(float(self.display_config.get("light_azimuth", 45.0)))
                el = np.radians(float(self.display_config.get("light_elevation", 45.0)))
                light_dir = (
                    float(np.cos(el) * np.cos(az)),
                    float(np.cos(el) * np.sin(az)),
                    float(np.sin(el)),
                )
                
                cam_pos = np.linalg.inv(m_view.T)[:3, 3]
                light = {
                    "enabled": True,
                    "light_dir": light_dir,
                    "view_pos": (float(cam_pos[0]), float(cam_pos[1]), float(cam_pos[2])),
                    "ambient": float(self.display_config.get("light_ambient", 0.35)),
                    "diffuse": float(self.display_config.get("light_diffuse", 0.75)),
                    "specular": float(self.display_config.get("light_specular", 0.25)),
                    "shininess": float(self.display_config.get("light_shininess", 32.0)),
                    "fresnel_intensity": float(self.display_config.get("light_fresnel_intensity", 0.4)),
                    "fresnel_power": float(self.display_config.get("light_fresnel_power", 3.0)),
                }

            if getattr(self, 'contour_active', False):
                light = None

            if getattr(self, '_needs_anim_vbo_build', False):
                self._needs_anim_vbo_build = False
                if self.view_extruded:
                    self._anim_vbo_built = self._build_animated_extruded_vbo()
                else:
                    self._anim_vbo_built = self._build_animated_line_vbo()
                self._clear_static_elements()
                if self.current_model is not None:
                    self._update_area_vbo(self.current_model)
                
            if getattr(self, '_needs_ltha_vbo_update', False):
                self._needs_ltha_vbo_update = False
                t = getattr(self, '_ltha_pending_t', 0)
                self.vbo_manager.set_anim_factor(1.0)

                if self.view_extruded:
                    self._build_ltha_extruded_frame(t)
                else:
                    self._build_ltha_line_frame(t)
                self._build_ltha_spring_frame(t)
                self._update_ltha_hinges(t)
                self._needs_hinge_refresh = False

            if getattr(self, '_needs_hinge_refresh', False):
                self._needs_hinge_refresh = False
                self._update_ltha_hinges(getattr(self, 'ltha_current_step', 0))

            show_areas = getattr(self, 'show_slabs', True)
            frame_alpha = float(self.display_config.get("extrude_opacity", 0.35))
            area_alpha = frame_alpha if self.view_extruded else float(
                self.display_config.get("slab_opacity", 0.4))

            if self.view_extruded and frame_alpha >= 1.0:
                self.vbo_manager.draw(m_view, m_proj, light=light, transparent=False)
            if show_areas and area_alpha >= 1.0:
                self.vbo_manager.draw_areas(m_view, m_proj, light=light, transparent=False)

            if not self.view_extruded:
                line_w = float(self.display_config.get("line_width", 2.0))
                self.vbo_manager.draw_lines(m_view, m_proj, line_width=line_w, alpha_mult=1.0, write_depth=True)

            self.vbo_manager.draw_springs(m_view, m_proj, line_width=1.75, alpha_mult=1.0)

            self.vbo_manager.draw_grid_lines(
                m_view, m_proj,
                width_a=getattr(self, '_grid_width_lines', 1.5),
                width_b=getattr(self, '_grid_width_floor', 1.0),
                alpha_mult=1.0
            )

            self.vbo_manager.draw_static(m_view, m_proj, line_width=1.5, alpha_mult=1.0)

            self.vbo_manager.draw_grid_bubbles(
                m_view, m_proj,
                line_width=getattr(self, '_bubble_line_width', 1.5),
                alpha_mult=1.0,
                ext_width=getattr(self, '_bubble_ext_width', None)
            )

            if self.view_extruded:
                edge_w = float(self.display_config.get("edge_width", 1.5))
                self.vbo_manager.draw_lines(
                    m_view, m_proj, line_width=edge_w,
                    alpha_mult=float(self.display_config.get("edge_opacity", 0.08)),
                    write_depth=False)

            _mark('vbo_opaque+lines+grid')
            transparent_frames = self.view_extruded and 0.0 < frame_alpha < 1.0
            transparent_areas = show_areas and 0.0 < area_alpha < 1.0
            if transparent_frames or transparent_areas:
                self.vbo_manager.draw_transparency(
                    m_view, m_proj, include_frames=transparent_frames,
                    include_areas=transparent_areas, light=light,
                    fast=bool(getattr(self, '_is_navigating', False)
                              and not getattr(self, 'is_selecting', False)))
            _mark('draw_transparency')

            if self.view_extruded:
                self.vbo_manager.draw_lines(m_view, m_proj, line_width=edge_w,
                                            alpha_mult=1.0, write_depth=False)
            if show_areas:
                _dc = self.display_config
                shell_edge_w     = float(_dc.get("shell_edge_width", 1.0))
                if _dc.get("shell_show_edges", True):
                    self.vbo_manager.draw_area_edges(m_view, m_proj, line_width=shell_edge_w,
                                                     alpha_mult=1.0, write_depth=False)

            _mark('edges')
            glClear(GL_DEPTH_BUFFER_BIT)

            if getattr(self, '_pending_force_upload', None) is not None:
                d = self._pending_force_upload
                self.vbo_manager.upload_force_geometry(
                    d['fill_verts'], d['fill_colors'], d['fill_faces'],
                    d['line_pos'],   d['line_colors'],
                    prepared=d.get('prepared'),
                )
                self._pending_force_upload = None

            self.vbo_manager.draw_force_geometry(m_view, m_proj)
            self.vbo_manager.draw_load_geometry(m_view, m_proj)

            if hasattr(self.vbo_manager, 'font_texture_id'):
                self.vbo_manager.draw_text(m_view, m_proj, self.vbo_manager.font_texture_id)
                
            glEnable(GL_DEPTH_TEST)
            glDepthMask(GL_TRUE)
            glDepthFunc(GL_LESS)
            
        _mark('loads+text')
        glClear(GL_DEPTH_BUFFER_BIT)
        
        for item, was_visible in zip(top_items, vis_states):
            item.setVisible(was_visible)                                        
            if was_visible:
                try:
                    item.paint()                                   
                except Exception:
                    pass

        _mark('overlay_items')
        if _fxaa_on:
            self._fxaa_end()
            _mark('fxaa_end')

        try:
            w = self.width()
            h = self.height()
            ratio = self.devicePixelRatio() if hasattr(self, 'devicePixelRatio') else 1.0
            az = self.opts.get('azimuth', 45)
            el = self.opts.get('elevation', 30)
            self.view_cube.render(w, h, az, el, device_pixel_ratio=ratio)
        except Exception as e:
            print(f"ViewCube Error: {e}")

        try:
            accel = getattr(self, 'ltha_accel', None)
            if accel is not None and len(accel) > 0:
                self._draw_accel_overlay(accel)
        except Exception as e:
            print(f"Accel overlay error: {e}")

        if _GL_PROFILE:
            _mark('viewcube+accel')
            st = self.__dict__.setdefault('_gl_prof_state', {'n': 0, 'sum': {}, 't0': time.perf_counter()})
            st['n'] += 1
            for k, v in _pm.items():
                st['sum'][k] = st['sum'].get(k, 0.0) + v
            if st['n'] >= 60:
                el = time.perf_counter() - st['t0']
                tot = sum(st['sum'].values()) / st['n']
                parts = '  '.join(f"{k}={v / st['n']:.2f}" for k, v in sorted(st['sum'].items(), key=lambda kv: -kv[1]))
                print(f"[GL PROFILE] {st['n'] / el:5.1f} fps | paintGL {tot:.2f} ms (GPU-synced) | {parts}")
                st['n'] = 0; st['sum'] = {}; st['t0'] = time.perf_counter()

    def _draw_accel_overlay(self, accel_dict):
        """
        Draws up to 3 accelerogram waveforms stacked vertically at the bottom.
        accel_dict: dict {"X": np.array, "Y": np.array, "Z": np.array}

        OPTIMISED: The static waveform (background, labels, zero-lines, highlight band)
        is rendered once into a QPixmap and cached.  Every frame we only blit that
        pixmap and then draw the playhead + time label on top.  This eliminates the
        O(n_samples) Python loop from every paintGL call, making camera movement smooth.

        Cache is invalidated when:
          - Canvas is resized  (size changes)
          - New LTHA data loaded  (load_ltha_history resets _accel_overlay_pixmap=None)
          - ltha_highlight changes (handled via _invalidate_accel_pixmap())
        """
        from PyQt6.QtGui import QPainter, QPen, QColor, QFont, QPixmap
        from PyQt6.QtCore import Qt, QRect, QPointF, QRectF

        if not accel_dict:
            return

        directions = list(accel_dict.keys())[:3]
        n_rows     = len(directions)

        w = self.width()
        h = self.height()

        pad_l, pad_r  = 52, 16
        row_h         = 58
        pad_top       = 8
        pad_bot_label = 18
        panel_h       = row_h * n_rows + pad_bot_label
        panel_y       = h - panel_h - 4
        plot_x0       = pad_l
        plot_x1       = w - pad_r
        plot_w        = plot_x1 - plot_x0

        ltha_n   = getattr(self, 'ltha_n_steps', 1)
        ltha_dt  = getattr(self, 'ltha_dt', 0.01)
        t_tot    = (ltha_n - 1) * ltha_dt if ltha_n > 1 else 1.0
        current_step = getattr(self, 'ltha_current_step', 0)
        t_cur    = current_step * ltha_dt

        dir_colors = {
            "X": QColor(80,  200, 120, 220),
            "Y": QColor(80,  160, 255, 220),
            "Z": QColor(255, 160,  60, 220),
        }

        highlight = getattr(self, 'ltha_highlight', None)

        if self._accel_overlay_pixmap is None or self._accel_overlay_size != (w, h):
            pixmap = QPixmap(w, h)
            pixmap.fill(Qt.GlobalColor.transparent)

            px = QPainter(pixmap)
            px.setRenderHint(QPainter.RenderHint.Antialiasing)

            font_dir  = QFont("Consolas", 8, QFont.Weight.Bold)
            font_info = QFont("Consolas", 8)

            px.fillRect(0, panel_y, w, panel_h, QColor(10, 10, 10, 165))

            pga_parts = []

            for row_i, direction in enumerate(directions):
                accel = accel_dict[direction]
                n     = len(accel)
                if n < 2:
                    continue

                a_max = float(np.max(np.abs(accel)))
                if a_max < 1e-9:
                    a_max = 1.0

                row_y0  = panel_y + row_i * row_h + pad_top
                row_y1  = panel_y + row_i * row_h + row_h - 4
                row_h_p = row_y1 - row_y0
                mid_y   = (row_y0 + row_y1) / 2.0

                wave_color = dir_colors.get(direction, QColor(200, 200, 200, 200))

                if highlight is not None:
                    hl_start, hl_end = highlight
                    hl_x0 = plot_x0 + (hl_start / t_tot) * plot_w
                    hl_x1 = plot_x0 + (hl_end   / t_tot) * plot_w
                    px.fillRect(QRectF(hl_x0, row_y0, hl_x1 - hl_x0, row_h_p),
                                QColor(255, 200, 50, 40))
                    pen_hl = QPen(QColor(255, 200, 50, 140), 1)
                    pen_hl.setStyle(Qt.PenStyle.DashLine)
                    px.setPen(pen_hl)
                    px.drawLine(QPointF(hl_x0, row_y0), QPointF(hl_x0, row_y1))
                    px.drawLine(QPointF(hl_x1, row_y0), QPointF(hl_x1, row_y1))

                pen_wave = QPen(wave_color, 1.0)
                px.setPen(pen_wave)
                step     = max(1, n // int(plot_w))
                prev_pt  = None
                for i in range(0, n, step):
                    pxi = plot_x0 + (i / (n - 1)) * plot_w
                    pyi = mid_y - (accel[i] / a_max) * (row_h_p / 2.0) * 0.82
                    pt  = QPointF(pxi, pyi)
                    if prev_pt is not None:
                        px.drawLine(prev_pt, pt)
                    prev_pt = pt

                pen_zero = QPen(QColor(150, 150, 150, 60), 1)
                pen_zero.setStyle(Qt.PenStyle.DashLine)
                px.setPen(pen_zero)
                px.drawLine(QPointF(plot_x0, mid_y), QPointF(plot_x1, mid_y))

                px.setFont(font_dir)
                px.setPen(QPen(wave_color))
                px.drawText(
                    QRect(0, int(mid_y) - 7, pad_l - 6, 14),
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                    direction
                )

                px.setFont(font_info)
                px.setPen(QPen(QColor(180, 180, 180, 180)))
                px.drawText(
                    QRect(int(plot_x1) - 120, int(row_y0), 120, 14),
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                    f"PGA {a_max:.3f} m/s²"
                )

                pga_parts.append(f"{direction}:{a_max:.3f}")

                if row_i < n_rows - 1:
                    pen_sep = QPen(QColor(80, 80, 80, 120), 1)
                    px.setPen(pen_sep)
                    sep_y = panel_y + (row_i + 1) * row_h
                    px.drawLine(QPointF(plot_x0, sep_y), QPointF(plot_x1, sep_y))

            px.end()

            self._accel_overlay_pixmap    = pixmap
            self._accel_overlay_size      = (w, h)
            self._accel_overlay_pga_parts = pga_parts                       

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        painter.drawPixmap(0, 0, self._accel_overlay_pixmap)

        font_info = QFont("Consolas", 8)

        if ltha_n > 1:
            ph_x     = plot_x0 + (current_step / (ltha_n - 1)) * plot_w
            pen_head = QPen(QColor(255, 80, 80, 220), 1.5)
            painter.setPen(pen_head)
            for row_i in range(n_rows):
                row_y0 = panel_y + row_i * row_h + pad_top
                row_y1 = panel_y + row_i * row_h + row_h - 4
                painter.drawLine(QPointF(ph_x, row_y0), QPointF(ph_x, row_y1))

        label_y = panel_y + row_h * n_rows
        painter.fillRect(0, label_y, w, pad_bot_label, QColor(10, 10, 10, 165))
        pga_parts = getattr(self, '_accel_overlay_pga_parts', [])
        pga_str   = "   ".join(pga_parts)
        painter.setFont(font_info)
        painter.setPen(QPen(QColor(200, 200, 200, 200)))
        painter.drawText(
            QRect(0, label_y, w, pad_bot_label),
            Qt.AlignmentFlag.AlignCenter,
            f"t = {t_cur:.2f}s / {t_tot:.2f}s      {pga_str}"
        )

        painter.end()

    def _invalidate_accel_pixmap(self):
        """
        Call this whenever the static waveform content changes (e.g. highlight band
        is updated).  Does NOT affect the LTHA data or animation state.
        """
        self._accel_overlay_pixmap = None
        self._accel_overlay_size   = (0, 0)

    def _handle_hover_tooltip(self, px, py):
        if not self.current_model:
            if self.current_hover_data is not None:
                self.current_hover_data = None
                self.update()
            return

        w, h = self.width(), self.height()
        full_area = (0, 0, w, h)
        m_view = self.viewMatrix()
        m_proj = self.projectionMatrix(region=full_area, viewport=full_area)
        mvp = np.array((m_proj * m_view).data()).reshape(4, 4).T

        can_deflect = (self.view_deflected and
                       hasattr(self.current_model, 'has_results') and
                       self.current_model.has_results and
                       self.current_model.results is not None)

        _cache_key = (
            mvp.tobytes(),
            can_deflect,
            self.anim_factor   if can_deflect else 0.0,
            self.deflection_scale if can_deflect else 0.0,
            len(self.current_model.nodes),
        )

        if self._screen_cache_key != _cache_key:
            node_screens = {}
            for nid, node in self.current_model.nodes.items():
                if self._get_visibility_state(node.x, node.y, node.z) != 2:
                    continue
                nx, ny, nz = node.x, node.y, node.z
                if can_deflect:
                    disp = self.current_model.results.get("displacements", {}).get(str(nid))
                    if disp:
                        nx += disp[0] * self.deflection_scale * self.anim_factor
                        ny += disp[1] * self.deflection_scale * self.anim_factor
                        nz += disp[2] * self.deflection_scale * self.anim_factor
                s_pos = self._project_to_screen(nx, ny, nz, mvp, w, h)
                if s_pos:
                    node_screens[nid] = s_pos
            self._node_screen_cache = node_screens
            self._screen_cache_key = _cache_key
        else:
            node_screens = self._node_screen_cache

        hovered_node = None
        hovered_elem = None
        hovered_area = None
        hovered_tendon = None
        hovered_cable = None
        min_dist = 15.0

        for nid, s_pos in node_screens.items():
            if not self._pickable('node', nid):
                continue
            dist = ((s_pos[0] - px)**2 + (s_pos[1] - py)**2)**0.5
            if dist < min_dist:
                min_dist = dist
                hovered_node = nid

        if hovered_node is None:
            min_dist_edge = 10.0
            for eid, el in self.current_model.elements.items():
                if not self._pickable('frame', eid):
                    continue

                use_curve = False
                if can_deflect and eid in self.deflection_cache:
                    cached = self.deflection_cache[eid]
                    curve_data_full = cached['curve_data']
                    p1_orig = cached['p1_orig']
                    p2_orig = cached['p2_orig']

                    screen_pts = []
                    for k in range(len(curve_data_full)):
                        pos_full, _, _ = curve_data_full[k]
                        s = k / (len(curve_data_full) - 1) if len(curve_data_full) > 1 else 0.0
                        pos_orig = p1_orig + s * (p2_orig - p1_orig)
                        displacement = pos_full - pos_orig
                        pos_anim = pos_orig + displacement * self.anim_factor
                        s_pos = self._project_to_screen(pos_anim[0], pos_anim[1], pos_anim[2], mvp, w, h)
                        if s_pos:
                            screen_pts.append(s_pos)

                    if len(screen_pts) >= 2:
                        use_curve = True
                        for i in range(len(screen_pts) - 1):
                            x1, y1 = screen_pts[i]
                            x2, y2 = screen_pts[i+1]
                            l2 = (x2 - x1)**2 + (y2 - y1)**2
                            if l2 == 0:
                                dist = ((px - x1)**2 + (py - y1)**2)**0.5
                            else:
                                t = max(0, min(1, ((px - x1) * (x2 - x1) + (py - y1) * (y2 - y1)) / l2))
                                proj_x = x1 + t * (x2 - x1)
                                proj_y = y1 + t * (y2 - y1)
                                dist = ((px - proj_x)**2 + (py - proj_y)**2)**0.5
                            if dist < min_dist_edge:
                                min_dist_edge = dist
                                hovered_elem = eid

                if not use_curve:
                    if el.node_i.id in node_screens and el.node_j.id in node_screens:
                        x1, y1 = node_screens[el.node_i.id]
                        x2, y2 = node_screens[el.node_j.id]
                        l2 = (x2 - x1)**2 + (y2 - y1)**2
                        if l2 == 0:
                            dist = ((px - x1)**2 + (py - y1)**2)**0.5
                        else:
                            t = max(0, min(1, ((px - x1) * (x2 - x1) + (py - y1) * (y2 - y1)) / l2))
                            proj_x = x1 + t * (x2 - x1)
                            proj_y = y1 + t * (y2 - y1)
                            dist = ((px - proj_x)**2 + (py - proj_y)**2)**0.5
                        if dist < min_dist_edge:
                            min_dist_edge = dist
                            hovered_elem = eid

        if hovered_node is None and hovered_elem is None and getattr(self.current_model, 'tendons', None):
            min_dist_tendon = 10.0
            for tid, tendon in self.current_model.tendons.items():
                if not self._pickable('tendon', tid):
                    continue
                pts = self._get_tendon_world_points(tendon)
                if pts is None or len(pts) < 2:
                    continue
                screen_pts = []
                for p in pts:
                    s_pos = self._project_to_screen(p[0], p[1], p[2], mvp, w, h)
                    if s_pos:
                        screen_pts.append(s_pos)
                for i in range(len(screen_pts) - 1):
                    x1, y1 = screen_pts[i]
                    x2, y2 = screen_pts[i + 1]
                    l2 = (x2 - x1)**2 + (y2 - y1)**2
                    if l2 == 0:
                        dist = ((px - x1)**2 + (py - y1)**2)**0.5
                    else:
                        t = max(0, min(1, ((px - x1) * (x2 - x1) + (py - y1) * (y2 - y1)) / l2))
                        proj_x = x1 + t * (x2 - x1)
                        proj_y = y1 + t * (y2 - y1)
                        dist = ((px - proj_x)**2 + (py - proj_y)**2)**0.5
                    if dist < min_dist_tendon:
                        min_dist_tendon = dist
                        hovered_tendon = tid

        if hovered_node is None and hovered_elem is None and hovered_tendon is None and getattr(self.current_model, 'cables', None):
            min_dist_cable = 10.0
            for cid, cable in self.current_model.cables.items():
                if not self._pickable('cable', cid):
                    continue
                pts = self._get_cable_world_points(cable)
                if pts is None or len(pts) < 2:
                    continue
                screen_pts = []
                for p in pts:
                    s_pos = self._project_to_screen(p[0], p[1], p[2], mvp, w, h)
                    if s_pos:
                        screen_pts.append(s_pos)
                for i in range(len(screen_pts) - 1):
                    x1, y1 = screen_pts[i]
                    x2, y2 = screen_pts[i + 1]
                    l2 = (x2 - x1)**2 + (y2 - y1)**2
                    if l2 == 0:
                        dist = ((px - x1)**2 + (py - y1)**2)**0.5
                    else:
                        t = max(0, min(1, ((px - x1) * (x2 - x1) + (py - y1) * (y2 - y1)) / l2))
                        proj_x = x1 + t * (x2 - x1)
                        proj_y = y1 + t * (y2 - y1)
                        dist = ((px - proj_x)**2 + (py - proj_y)**2)**0.5
                    if dist < min_dist_cable:
                        min_dist_cable = dist
                        hovered_cable = cid

        if hovered_node is None and hovered_elem is None and hovered_tendon is None and self.current_model.area_elements:
            for aeid, ae in self.current_model.area_elements.items():
                if not self._pickable('area', aeid):
                    continue
                                                                                
                if getattr(self, 'view_deflected', False):
                    if hasattr(ae.section, 'modeling_type') and ae.section.modeling_type == "Tributary Area":
                        continue
                corner_screens = []
                for n in ae.nodes:
                    s = node_screens.get(n.id)
                    if s is None:
                        s = self._project_to_screen(n.x, n.y, n.z, mvp, w, h)
                    if s:
                        corner_screens.append(s)
                if len(corner_screens) < 3:
                    continue
                if self._point_in_polygon_2d(px, py, corner_screens):
                    hovered_area = aeid
                    break

        text = ""
        in_analysis = getattr(self.current_model, 'has_results', False)

        if hovered_node is not None:
            if in_analysis:
                results = self.current_model.results.get("displacements", {})
                vector = results.get(str(hovered_node), [0.0]*6)
                from core.units import unit_registry
                ux = unit_registry.to_display_length(vector[0])
                uy = unit_registry.to_display_length(vector[1])
                uz = unit_registry.to_display_length(vector[2])
                u_str = unit_registry.length_unit_name
                text = f"JOINT {hovered_node}\nUx: {ux:.4f} {u_str}\nUy: {uy:.4f} {u_str}\nUz: {uz:.4f} {u_str}"
            else:
                node = self.current_model.nodes[hovered_node]
                text = f"JOINT {hovered_node}\nX: {node.x:.2f}\nY: {node.y:.2f}\nZ: {node.z:.2f}"

                if hasattr(node, 'restraints') and any(node.restraints):
                    r = node.restraints
                    is_fixed  = all(r[:3]) and all(r[3:])
                    is_pinned = all(r[:3]) and not any(r[3:])
                    is_roller = r[2] and not any(r[0:2]) and not any(r[3:])
                    if is_fixed:   s_type = "Fixed"
                    elif is_pinned: s_type = "Pinned"
                    elif is_roller: s_type = "Roller"
                    else:           s_type = "Custom"
                    dof_names   = ["UX", "UY", "UZ", "RX", "RY", "RZ"]
                    active_dofs = [dof_names[i] for i, state in enumerate(r) if state]
                    text += f"\nSupport: {s_type}\nRestraints: [{', '.join(active_dofs)}]"

        elif hovered_elem is not None:
            el = self.current_model.elements[hovered_elem]
            sec_name = el.section.name if el.section else "None"
            text = f"FRAME {hovered_elem}\nSection: {sec_name}"

        elif hovered_tendon is not None:
            td = self.current_model.tendons[hovered_tendon]
            sec_name = td.tendon_section.name if td.tendon_section else "None"
            text = f"TENDON {hovered_tendon}\nSection: {sec_name}"

        elif hovered_cable is not None:
            cb = self.current_model.cables[hovered_cable]
            sec_name = cb.cable_section.name if cb.cable_section else "None"
            text = f"CABLE {hovered_cable}\nSection: {sec_name}"

        elif hovered_area is not None:
            ae  = self.current_model.area_elements[hovered_area]
            sec = ae.section
            sec_name = getattr(sec, 'name', 'Unknown')
            t = getattr(sec, 'membrane_thickness', getattr(sec, 'thickness', None))
            t_str = f"{t:.3f}" if isinstance(t, (int, float)) else "—"
            n_corners = len(ae.nodes)
            shape = "Tri" if n_corners == 3 else ("Quad" if n_corners == 4 else f"{n_corners}-gon")
            text = f"AREA {hovered_area}  [{shape}]\nSection: {sec_name}\nThickness: {t_str}"

        new_hover_data = {'text': text, 'x': px, 'y': py} if text else None

        prev_nothing = (self.hovered_node_id is None and
                        self.hovered_elem_id is None and
                        self.hovered_tendon_id is None and
                        self.current_hover_data is None)
        new_nothing  = (hovered_node is None and
                        hovered_elem is None and
                        hovered_tendon is None and
                        new_hover_data is None)

        prev_hov_tendon = self.hovered_tendon_id
        prev_hov_cable = getattr(self, 'hovered_cable_id', None)
        self.current_hover_data = new_hover_data
        self.hovered_node_id    = hovered_node
        self.hovered_elem_id    = hovered_elem
        self.hovered_tendon_id  = hovered_tendon
        self.hovered_cable_id   = hovered_cable
        if hovered_tendon != prev_hov_tendon or hovered_cable != prev_hov_cable:                   
            self.update()

        prev_hov_area = getattr(self, 'hovered_area_id', None)
        self.hovered_area_id  = hovered_area
        if hovered_area != prev_hov_area:
            self._rebuild_area_interior_lines()

        if not (prev_nothing and new_nothing):
            self.update()

    def _build_ltha_extruded_metadata(self):
        """Builds initial topology and vertex mappings for the GPU Extruded Tensor (vectorised)."""
        try:
            return self._build_ltha_extruded_metadata_vec()
        except Exception:
            import traceback; traceback.print_exc()
            return self._build_ltha_extruded_metadata_slow()

    def _build_ltha_extruded_metadata_vec(self):
        from core.properties import RectangularSection, CircularSection, TrapezoidalSection
        opacity = self.display_config.get("extrude_opacity", 0.35)
        show_edges = self.display_config.get("show_edges", False)
        edge_c = np.array(self.display_config.get("edge_color", (0, 0, 0, 1)), dtype=np.float32)
        zero3 = np.zeros(3)
        cache = {}
        params = []
        for e_idx, el in enumerate(self._ltha_elements):
            sec = el.section
            sc = cache.get(id(sec))
            if sc is None:
                sy = sec.get_shape_coords()
                arr = np.asarray(sy, dtype=np.float64).reshape(-1, 2) if sy is not None and len(sy) else None
                sc = (arr, isinstance(sec, (RectangularSection, CircularSection, TrapezoidalSection)),
                      np.array([*getattr(sec, 'color', [0.7, 0.7, 0.7])[:3], opacity], dtype=np.float32))
                cache[id(sec)] = sc
            if sc[0] is None:
                continue
            ys, zs = el.get_cardinal_offsets()
            params.append((e_idx, sc[0], sc[1], sc[2], ys, zs,
                           getattr(el, 'joint_offset_i', zero3), getattr(el, 'joint_offset_j', zero3)))
        md = vec_extruded_metadata(params, show_edges, edge_c)
        if md is None:
            raise RuntimeError("no extrudable elements")
        self.ltha_engine.set_extruded_mapping(md['map_E'], md['map_P'], md['map_off'], md['map_Y'], md['map_Z'],
                                              md['colors'])
        verts_flat, colors_flat = self.ltha_engine.compute_extruded(self.ltha_tensor[:, 0, :] * 0.0, self.deflection_scale)
        faces_flat = md['faces'].astype(np.uint32).flatten()
        self.makeCurrent()
        if not self.vbo_manager.is_initialized:
            self.vbo_manager.init_gl()
        num_ext = len(verts_flat) // 3
        edges = md['edges']
        if show_edges and edges is not None and len(edges):
            self.ltha_engine.edge_indices = edges.astype(np.int32).flatten()
            self.ltha_engine.edge_colors_flat = np.tile(edge_c, len(self.ltha_engine.edge_indices)).astype(np.float32)
            num_edge_verts = len(self.ltha_engine.edge_indices)
        else:
            self.ltha_engine.edge_indices = None
            num_edge_verts = 0
        self.vbo_manager.allocate_ltha_buffers(num_edge_verts, num_ext)
        self.vbo_manager.upload_extruded_geometry(verts_flat.reshape(-1, 3), colors_flat.reshape(-1, 4),
                                                  faces_flat.reshape(-1, 3), ltha=True)
        if num_edge_verts:
            edge_verts_flat = verts_flat.reshape(-1, 3)[self.ltha_engine.edge_indices].flatten()
            self.vbo_manager.upload_line_geometry(edge_verts_flat.reshape(-1, 3),
                                                  self.ltha_engine.edge_colors_flat.reshape(-1, 4))

    def _build_ltha_extruded_metadata_slow(self):
        """Original python-loop implementation (kept as a fallback)."""
        from core.properties import RectangularSection, CircularSection, TrapezoidalSection
        
        ex_faces, ex_colors, ex_edges, ex_edge_colors = [], [], [], []
        map_E, map_P, map_off, map_Y, map_Z = [], [], [], [], []
        
        opacity = self.display_config.get("extrude_opacity", 0.35)
        show_edges = self.display_config.get("show_edges", False)
        edge_c = np.array(self.display_config.get("edge_color", (0, 0, 0, 1)), dtype=np.float32)
        
        current_vert_idx = 0
        
        for e_idx, el in enumerate(self._ltha_elements):
            sec = el.section
            shape_yz = sec.get_shape_coords()
            if not shape_yz: continue
                
            needs_caps = isinstance(sec, (RectangularSection, CircularSection, TrapezoidalSection))
            face_color = np.array([*getattr(sec, 'color', [0.7, 0.7, 0.7])[:3], opacity])
            
            y_shift, z_shift = el.get_cardinal_offsets()
            off_vec_i = getattr(el, 'joint_offset_i', np.array([0.0, 0.0, 0.0]))
            off_vec_j = getattr(el, 'joint_offset_j', np.array([0.0, 0.0, 0.0]))
            
            num_pts = 11
            M = len(shape_yz)
            
            for i in range(num_pts - 1):
                s_a, s_b = i / 10.0, (i + 1) / 10.0
                curr_off_a = (1 - s_a) * off_vec_i + s_a * off_vec_j
                curr_off_b = (1 - s_b) * off_vec_i + s_b * off_vec_j
                
                for off, P_idx in [(curr_off_a, i), (curr_off_b, i + 1)]:
                    for y, z in shape_yz:
                        map_E.append(e_idx); map_P.append(P_idx)
                        map_off.append(off); map_Y.append(y + y_shift); map_Z.append(z + z_shift)
                        ex_colors.append(face_color)
                        
                start_idx = current_vert_idx
                for j in range(M):
                    next_j = (j + 1) % M
                    idx_a_curr, idx_a_next = start_idx + j, start_idx + next_j
                    idx_b_curr, idx_b_next = start_idx + M + j, start_idx + M + next_j
                    
                    ex_faces.extend([[idx_a_curr, idx_a_next, idx_b_next], [idx_a_curr, idx_b_next, idx_b_curr]])
                    
                    if show_edges:
                        ex_edges.append((idx_a_curr, idx_b_curr))
                        ex_edge_colors.extend([edge_c, edge_c])
                        if i == 0:
                            ex_edges.append((idx_a_curr, idx_a_next))
                            ex_edge_colors.extend([edge_c, edge_c])
                        if i == num_pts - 2:
                            ex_edges.append((idx_b_curr, idx_b_next))
                            ex_edge_colors.extend([edge_c, edge_c])
                            
                if needs_caps:
                    if i == 0 and M >= 3:
                        for j in range(1, M - 1): ex_faces.append([start_idx, start_idx + j + 1, start_idx + j])
                    if i == num_pts - 2 and M >= 3:
                        for j in range(1, M - 1): ex_faces.append([start_idx + M, start_idx + M + j, start_idx + M + j + 1])
                current_vert_idx += 2 * M
                
        self.ltha_engine.set_extruded_mapping(map_E, map_P, map_off, map_Y, map_Z, ex_colors)
        verts_flat, colors_flat = self.ltha_engine.compute_extruded(self.ltha_tensor[:, 0, :] * 0.0, self.deflection_scale)
        faces_flat = np.array(ex_faces, dtype=np.uint32).flatten()
        
        self.makeCurrent()
        if not self.vbo_manager.is_initialized:
            self.vbo_manager.init_gl()

        num_ext = len(verts_flat) // 3
        if show_edges and ex_edges:
            self.ltha_engine.edge_indices = np.array(ex_edges, dtype=np.int32).flatten()
            self.ltha_engine.edge_colors_flat = np.array(ex_edge_colors, dtype=np.float32).flatten()
            num_edge_verts = len(self.ltha_engine.edge_indices)
        else:
            self.ltha_engine.edge_indices = None
            num_edge_verts = 0

        self.vbo_manager.allocate_ltha_buffers(num_edge_verts, num_ext)

        self.vbo_manager.upload_extruded_geometry(verts_flat.reshape(-1, 3), colors_flat.reshape(-1, 4), faces_flat.reshape(-1, 3), ltha=True)
        
        if show_edges and ex_edges:
            edge_verts_flat = verts_flat.reshape(-1, 3)[self.ltha_engine.edge_indices].flatten()
            self.vbo_manager.upload_line_geometry(edge_verts_flat.reshape(-1, 3), self.ltha_engine.edge_colors_flat.reshape(-1, 4))

    _STATIC_EXTRUDE_MAX = 30000                                                                            

    def _frames_gpu_ok(self, model):
        if getattr(self, 'ltha_mode', False) or self.animation_manager.is_running:
            return False
        if self.active_view_plane is not None or self._view_overrides.get('frame'):
            return False
        vm = getattr(self, 'vbo_manager', None)
        return bool(vm is not None and vm.is_initialized and model.elements)

    def _frames_sig(self, model):
        dc = self.display_config
        return (id(model), len(model.elements), bool(self.view_extruded),
                float(dc.get("extrude_opacity", 0.35)), bool(dc.get("show_edges", False)),
                tuple(dc.get("edge_color", (0, 0, 0, 1))))

    def _static_gpu_frames(self, model):
        """True if the frame geometry was handled here (deformed GPU path, or cached undeformed restore)."""
        try:
            if not self._frames_gpu_ok(model):
                return False
            res = getattr(model, 'results', None)
            disp = (res.get("displacements") if (self.view_deflected and getattr(model, 'has_results', False)
                                                  and res is not None) else None)
            if not disp:
                snap = getattr(self, '_undef_frames', None)
                if getattr(self, '_deform_toggle', False) and snap and snap['sig'] == self._frames_sig(model):
                    self.makeCurrent()
                    ext, line = snap['ext'], snap['line']
                    vm = self.vbo_manager
                    if ext is None:
                        vm.upload_extruded_geometry(np.empty((0, 3), np.float32), np.empty((0, 4), np.float32),
                                                    np.empty((0, 3), np.int32))
                    else:
                        vm.upload_extruded_geometry(*ext)
                    if line is None:
                        vm.upload_line_geometry([], [])
                    else:
                        vm.upload_line_geometry(*line)
                    return True
                return False
            return self._static_gpu_show(model, disp)
        except Exception:
            import traceback; traceback.print_exc()
            return False

    def _store_undeformed_frames(self, model):
        try:
            if not self._frames_gpu_ok(model):
                return
            vm = self.vbo_manager
            self._undef_frames = dict(sig=self._frames_sig(model),
                                      ext=(getattr(vm, '_last_ext_args', None) if self.view_extruded else None),
                                      line=getattr(vm, '_last_line_args', None))
        except Exception:
            self._undef_frames = None

    def _static_gpu_show(self, model, disp):
        sig = self._frames_sig(model) + (id(model.results), len(disp))
        if getattr(self, '_sgpu_key', None) != sig or getattr(self, '_sgpu_mode', None) is None:
            if not self._static_gpu_build(model, disp, sig):
                return False
        self.makeCurrent()
        comp = getattr(self, 'contour_component', 'Resultant')
        absl = bool(getattr(self, 'contour_absolute', False))
        rng = dict(self._sgpu_ranges)
        if not getattr(self, 'contour_range_auto', True):
            lo, hi = float(getattr(self, 'contour_min', 0.0)), float(getattr(self, 'contour_max', 1.0))
            rng[(comp, absl)] = (lo, hi if hi - lo > 1e-12 else lo + 1e-12)
        self.ltha_contour_ranges = rng
        if self._sgpu_mode == 'ext':
            self._build_ltha_extruded_frame(0)
        else:
            self.vbo_manager.upload_extruded_geometry(np.empty((0, 3), np.float32), np.empty((0, 4), np.float32),
                                                      np.empty((0, 3), np.int32))
            self._build_ltha_line_frame(0)
        return True

    def _static_gpu_build(self, model, disp, sig):
        self._sgpu_mode = None
        elements = list(model.elements.values())
        n = len(elements)
        ids = list(disp.keys()); N = len(ids)
        node_map = {str(k): i for i, k in enumerate(ids)}
        U = np.zeros((N + 1, 1, 6), dtype=np.float32)
        try:
            arr = np.array([r[:6] for r in disp.values()], dtype=np.float32)
            U[:N, 0, :arr.shape[1]] = arr
        except Exception:
            for i, r in enumerate(disp.values()):
                r = list(r)[:6]
                U[i, 0, :len(r)] = r

        ni = [el.node_i for el in elements]; nj = [el.node_j for el in elements]
        P1 = np.array([(a.x, a.y, a.z) for a in ni], dtype=np.float64)
        P2 = np.array([(a.x, a.y, a.z) for a in nj], dtype=np.float64)
        beta = np.array([getattr(el, 'beta_angle', 0.0) or 0.0 for el in elements], dtype=np.float64)
        R = vec_rest_axes(P1, P2, beta)
        cols = []
        for el in elements:
            w = getattr(el.section, 'color', [0.5, 0.5, 0.5, 1.0])
            cols.append(list(w) if len(w) == 4 else list(w) + [1.0])

        eng = VectorizedLTHAEngine(n)
        eng.P1[:] = P1; eng.P2[:] = P2
        eng.L[:, 0] = np.maximum(np.linalg.norm(P2 - P1, axis=1), 1e-6)
        eng.off_i[:] = 0.0; eng.off_j[:] = 0.0
        eng.R[:] = R
        eng.idx_i[:] = [node_map.get(str(a.id), N) for a in ni]
        eng.idx_j[:] = [node_map.get(str(a.id), N) for a in nj]
        eng.colors[:] = np.array(cols, dtype=np.float32)

        real = U[:N, :, :3]
        ranges = {}
        for comp, ci in (("Ux", 0), ("Uy", 1), ("Uz", 2)):
            v = real[:, :, ci]
            ranges[(comp, False)] = (float(v.min()), float(v.max()))
            ranges[(comp, True)] = (0.0, float(np.abs(v).max()))
        rr = np.linalg.norm(real, axis=2)
        ranges[("Resultant", False)] = ranges[("Resultant", True)] = (float(rr.min()), float(rr.max()))
        for k, (lo, hi) in list(ranges.items()):
            if hi - lo < 1e-12:
                ranges[k] = (lo, lo + 1e-12)
        self._sgpu_ranges = ranges

        self.ltha_engine = eng
        self.ltha_tensor = U
        self._ltha_elements = elements
        self._ltha_vbo_built = False                                                   
        c_min, c_max = ranges.get((getattr(self, 'contour_component', 'Resultant'),
                                   bool(getattr(self, 'contour_absolute', False))), (0.0, 1.0))
        eng.set_contour(bool(getattr(self, 'contour_active', False)), self.contour_component, c_min, c_max,
                        self.display_config.get("extrude_opacity", 0.35), bool(getattr(self, 'contour_absolute', False)))

        secs = {id(el.section): el.section for el in elements}
        all_shaped = all(bool(s.get_shape_coords()) for s in secs.values())
        use_ext = bool(self.view_extruded) and n <= self._STATIC_EXTRUDE_MAX and all_shaped
        self.makeCurrent()
        if use_ext:
            self._build_ltha_extruded_metadata()
            self._sgpu_mode = 'ext'
        else:
            self.vbo_manager.upload_extruded_geometry(np.empty((0, 3), np.float32), np.empty((0, 4), np.float32),
                                                      np.empty((0, 3), np.int32))
            self._sgpu_mode = 'line'
        self._sgpu_key = sig
        return True

    def _push_static_lines(self, positions, color):
        """
        Accumulates a batch of line-segment endpoints (flat list of [x,y,z]
        pairs) into the pending static-geometry buffers, tagging every vertex
        with `color`. Used by the grid, local-axis, and constraint drawers so
        all of that "drawn once, changes rarely" overlay geometry ends up in
        one GPU buffer instead of one pyqtgraph item per call site.
        """
        if not positions:
            return
        self._pending_static_line_pos.extend(positions)
        self._pending_static_line_colors.extend([color] * len(positions))

    def _push_bubble_lines(self, positions, color):
        """
        Same accumulation pattern as _push_static_lines, but for the grid
        bubble tail lines + ID circles specifically, which are uploaded to
        their own GPU buffer (see _vbo_grid_bubble.py) so their thickness
        can be configured independently (Grid Editor -> Bubble Line
        Thickness) without affecting the rest of the reference grid.
        """
        if not positions:
            return
        self._pending_bubble_line_pos.extend(positions)
        self._pending_bubble_line_colors.extend([color] * len(positions))

    def _canvas_is_dark(self):
        """True when the canvas background is dark (drives the Auto grid palette)."""
        try:
            bg = self.opts.get('bgcolor', (1.0, 1.0, 1.0, 1.0))
            if hasattr(bg, 'redF'):
                r, g, b = bg.redF(), bg.greenF(), bg.blueF()
            else:
                r, g, b = float(bg[0]), float(bg[1]), float(bg[2])
            return (0.299 * r + 0.587 * g + 0.114 * b) < 0.5
        except Exception:
            return False

    def _push_grid_lines(self, positions, color, group):
        """Queue grid guideline segments. group 'a' = structural/active/dimension
        lines, 'b' = floor grid (the two groups can have different widths)."""
        if not positions:
            return
        if group == 'b':
            self._pending_grid_b_pos.extend(positions)
            self._pending_grid_b_col.extend([color] * len(positions))
        else:
            self._pending_grid_a_pos.extend(positions)
            self._pending_grid_a_col.extend([color] * len(positions))

    def _upload_static_geometry(self):
        """
        Flushes everything accumulated via _push_static_lines (reference
        grid, dimension lines, bubbles, local-axis triads, diaphragm
        constraint markers) into the dedicated static VBO in one call.
        Must be called after _draw_reference_grids / _draw_local_axes /
        _draw_constraints have populated the pending arrays for this rebuild.
        """
        if not hasattr(self, 'vbo_manager') or not self.vbo_manager.is_initialized:
            return

        self.makeCurrent()

        pos = getattr(self, '_pending_static_line_pos', [])
        col = getattr(self, '_pending_static_line_colors', [])

        p = np.array(pos, dtype=np.float32) if pos else np.zeros((0, 3), dtype=np.float32)
        c = np.array(col, dtype=np.float32) if col else np.zeros((0, 4), dtype=np.float32)

        self.vbo_manager.upload_static_geometry(p, c)

        bpos = getattr(self, '_pending_bubble_line_pos', [])
        bcol = getattr(self, '_pending_bubble_line_colors', [])

        bp = np.array(bpos, dtype=np.float32) if bpos else np.zeros((0, 3), dtype=np.float32)
        bc = np.array(bcol, dtype=np.float32) if bcol else np.zeros((0, 4), dtype=np.float32)

        self.vbo_manager.upload_grid_bubble_geometry(bp, bc, getattr(self, '_bubble_split', 0))

        ga_p, ga_c = getattr(self, '_pending_grid_a_pos', []), getattr(self, '_pending_grid_a_col', [])
        gb_p, gb_c = getattr(self, '_pending_grid_b_pos', []), getattr(self, '_pending_grid_b_col', [])
        g_pos = ga_p + gb_p
        g_col = ga_c + gb_c
        gp = np.array(g_pos, dtype=np.float32) if g_pos else np.zeros((0, 3), dtype=np.float32)
        gc = np.array(g_col, dtype=np.float32) if g_col else np.zeros((0, 4), dtype=np.float32)
        self.vbo_manager.upload_grid_line_geometry(gp, gc, len(ga_p))

    def _upload_loads_to_vbo(self, refresh_tributary=True):
        """
        Flushes all pending load geometry (nodal arrows, dist load curtains,
        member point load arrows) into the dedicated load VBO in one call.
        Called after _draw_loads / _draw_member_loads / _draw_member_point_loads
        have populated the self._pending_load_* accumulators.
        """
        if not hasattr(self, 'vbo_manager') or not self.vbo_manager.is_initialized:
            return

        self.makeCurrent()

        fill_verts  = self._pending_load_fill_verts
        fill_colors = self._pending_load_fill_colors
        fill_faces  = self._pending_load_fill_faces
        line_pos    = self._pending_load_line_pos
        line_colors = self._pending_load_line_colors

        fv = np.asarray(fill_verts,  dtype=np.float32).reshape(-1, 3)
        fc = np.asarray(fill_colors, dtype=np.float32).reshape(-1, 4)
        ff = np.asarray(fill_faces,  dtype=np.uint32).reshape(-1, 3)
        lp = np.asarray(line_pos,    dtype=np.float32).reshape(-1, 3)
        lc = np.asarray(line_colors, dtype=np.float32).reshape(-1, 4)

        self.vbo_manager.upload_load_geometry(fv, fc, ff, lp, lc)

        cache = getattr(self, '_load_view_geometry', None)
        model = getattr(self, 'current_model', None)
        if (cache is not None and model is not None and not getattr(model, 'has_results', False)
                and getattr(self, 'show_loads', False)
                and hasattr(self.vbo_manager, 'upload_load_view_payload')
                and self.vbo_manager.upload_load_view_payload(cache)):
            _, mvp, width, height = self._area_load_projection()
            if mvp is not None:
                self.vbo_manager.update_load_view_factors(cache.profile_scales(mvp, width, height),
                                                          width, height)

        if not refresh_tributary:
            return

        if getattr(self, 'show_tributary_mesh', False):
                                                                                  
            if hasattr(self, 'current_model') and hasattr(self.current_model, 'tributary_visuals'):
                try:
                    self._update_tributary_visuals()
                except Exception as e:
                    print(f"Canvas Error (Tributary Visuals): {e}")
        else:
                                                                             
            if hasattr(self, 'trib_scatter') and self.trib_scatter is not None:
                self.trib_scatter.setData(pos=np.empty((0, 3)), color=np.empty((0, 4)))

    def _upload_load_labels_to_gpu(self):
        """Pushes current load_labels AND force_labels AND grid_labels to the SDF VBO pipeline."""
        self._text_geometry_revision = getattr(self, '_text_geometry_revision', 0) + 1
        if not hasattr(self, 'text_builder') or not hasattr(self, 'vbo_manager'):
            return
            
        self.makeCurrent()
        
        all_labels = self._scaled_load_labels() +\
                     getattr(self, 'force_labels', []) +\
                     getattr(self, 'grid_labels', [])
        
        if all_labels:
            verts, uvs, colors, indices = self.text_builder.build_text_geometry(all_labels, default_text_height=0.25)
            self.vbo_manager.upload_text_geometry(verts, uvs, colors, indices)
        else:
            self.vbo_manager.upload_text_geometry(np.array([]), np.array([]), np.array([]), np.array([]))

    def update_section_locator(self, element, ratio):
        """Draws a 3D translucent plane mapping the cross-section location."""
        if not element or not self.current_model: return

        p1 = np.array([element.node_i.x, element.node_i.y, element.node_i.z])
        p2 = np.array([element.node_j.x, element.node_j.y, element.node_j.z])
        
        center = p1 + ratio * (p2 - p1)
        v1_ax, v2_ax, v3_ax = self._get_consistent_axes(element)
        
        shape_yz = element.section.get_shape_coords()
        if not shape_yz: return
        
        corners = []
        for y, z in shape_yz:
            pt = center + (y * v2_ax) + (z * v3_ax)
            corners.append(pt)
        
        corners_arr = np.array(corners, dtype=np.float32)
        
        border = np.vstack([corners_arr, corners_arr[0]])
        self.section_locator.setData(pos=border)
        self.section_locator.setVisible(True)
        
        if len(corners) >= 3:
            faces = []
            for i in range(1, len(corners) - 1):
                faces.append([0, i, i + 1])
            self.section_locator_mesh.setMeshData(vertexes=corners_arr, faces=np.array(faces, dtype=np.int32))
            self.section_locator_mesh.setVisible(True)

    def hide_section_locator(self):
        self.section_locator.setVisible(False)
        self.section_locator_mesh.setVisible(False)

    def _get_cable_world_points(self, cable):
        """
        Dynamically calculates the exact catenary curve for the canvas.
        """
        try:
            from core.cable_catenary_solver import solve_cable_geometry
        except ImportError:
            return np.array([[cable.node_i.x, cable.node_i.y, cable.node_i.z],
                             [cable.node_j.x, cable.node_j.y, cable.node_j.z]], dtype=np.float64)
        
        node_i = (cable.node_i.x, cable.node_i.y, cable.node_i.z)
        node_j = (cable.node_j.x, cable.node_j.y, cable.node_j.z)
        
        sec = getattr(cable, 'cable_section', None)
        if not sec:
            return np.array([node_i, node_j], dtype=np.float64)

        mat = getattr(sec, 'material', None)
        area = getattr(sec, 'area', 0.0)
        E = getattr(mat, 'E', 0.0) if mat else 0.0
        unit_weight = getattr(mat, 'unit_weight', 0.0) if mat else 0.0

        EA = E * area
        added_weight = getattr(cable, 'added_weight', 0.0)
        weight_per_length = (area * unit_weight) + added_weight

        target_type = getattr(cable, 'target_type', "Cable - Undeformed Length")
        target_value = getattr(cable, 'target_value', getattr(cable, 'undeformed_length', 0.0))
        
        if not target_value or target_value <= 0:
             return np.array([node_i, node_j], dtype=np.float64)

        n_points = max(15, getattr(cable, 'number_of_segments', 1) + 1)

        res = solve_cable_geometry(
            node_i, node_j, weight_per_length, EA,
            target_type, target_value,
            gravity_dir=(0.0, 0.0, -1.0),
            n_points=n_points
        )

        if res.converged and res.points:
            return np.array([p.xyz for p in res.points], dtype=np.float64)
        
        return np.array([node_i, node_j], dtype=np.float64)

import os as _os
if _os.environ.get("OPENCIVIL_PROFILE"):
    import functools as _ft, cProfile as _cp, pstats as _ps, io as _io
    _depth = [0]

    def _wrap_method(cls, name, thresh, deep=False):
        fn = getattr(cls, name, None)
        if fn is None:
            return
        @_ft.wraps(fn)
        def wrapper(self, *a, **k):
            top = _depth[0] == 0
            prof = _cp.Profile() if (deep and top) else None
            t0 = time.perf_counter()
            _depth[0] += 1
            try:
                if prof is not None:
                    prof.enable()
                try:
                    return fn(self, *a, **k)
                finally:
                    if prof is not None:
                        prof.disable()
            finally:
                _depth[0] -= 1
                dt = time.perf_counter() - t0
                if dt >= thresh:
                    print(f"[prof] {'  ' * _depth[0]}{name} {dt:.3f}s", flush=True)
                    if prof is not None and dt >= 0.5:
                        buf = _io.StringIO()
                        _ps.Stats(prof, stream=buf).sort_stats("cumulative").print_stats(18)
                        print(buf.getvalue(), flush=True)
        setattr(cls, name, wrapper)

    for _n in ("_force_draw_model",):
        _wrap_method(MCanvas3D, _n, 0.05, deep=True)
    for _n in ("_draw_reference_grids", "_draw_nodes", "_draw_constraints", "_draw_elements_extruded",
               "_draw_elements_wireframe", "_draw_tendons_extruded", "_draw_tendons_wireframe",
               "_draw_cables_extruded", "_draw_cables_wireframe", "_draw_loads", "_draw_member_loads",
               "_draw_member_point_loads", "_draw_area_loads", "_draw_cable_loads", "_draw_frame_hinges",
               "_draw_slabs", "_update_area_vbo", "_draw_local_axes", "_upload_static_geometry",
               "_upload_loads_to_vbo", "_upload_load_labels_to_gpu", "_rebuild_selection_overlay",
               "update_selection_overlay", "_rebuild_support_items", "refresh_supports_only",
               "advance_selection_dashes", "_find_zoom_target", "_handle_hover_tooltip",
               "get_snap_point", "_march_selection_dashes"):
        _wrap_method(MCanvas3D, _n, 0.03)
    for _n in ("paintGL", "paintEvent"):
        _wrap_method(MCanvas3D, _n, 0.05)
    print("[prof] OPENCIVIL_PROFILE active: slow calls will be printed", flush=True)
