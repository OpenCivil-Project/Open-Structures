import numpy as np
import math
import pyqtgraph.opengl as gl
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, pyqtSignal, QRect, QTimer
from PyQt6.QtGui import QPainter, QColor, QPen, QVector3D
from core.units import unit_registry
from graphic.camera_ctrl import ArcballCamera
from post.deflection import get_deflected_shape
from post.animation import AnimationManager
from graphic.view_cube import ViewCube
from OpenGL.GL import *
from core.properties import RectangularSection, CircularSection, TrapezoidalSection
from PyQt6.QtWidgets import QLabel        
from graphic.vbo_engine import VBORenderManager, VectorizedLTHAEngine                               
from graphic.sdf_text import SDFTextBuilder
from graphic._vbo_supports import build_boundary_visuals

class MCanvas3D(gl.GLViewWidget):
    signal_canvas_clicked = pyqtSignal(float, float, float)
    signal_right_clicked = pyqtSignal()
    signal_box_selection = pyqtSignal(list, list, list, bool, bool)
    signal_area_box_selection = pyqtSignal(list, bool, bool)                                   
    signal_element_selected = pyqtSignal(int)
    signal_mouse_moved = pyqtSignal(float, float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)

        self.display_config = {
            "node_size": 6,
            "node_color": (1, 0, 0, 1),
            "line_width": 2.0,
            "extrude_opacity": 0.65,
            "show_edges": True,
            "edge_width": 1.5,
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
        self.load_labels = []
        self.view_extruded = True 
        self.show_joints = True      
        self.show_supports = True    
        self.show_releases = True   
        self.show_loads = True
        self.load_type_filter = "both"
        self.visible_load_patterns = []
        self.show_local_axes = False
        self.show_slabs = True
        self.show_constraints = True
        self.camera = ArcballCamera(self)
        self.view_deflected = False    
        self.deflection_scale = 50.0
        self.view_shadow = True
        self.shadow_color = (0.7, 0.7, 0.7, 0.5)
        self.show_grid = True

        self.show_ghost_structure = True                       
        self._pre_force_was_extruded  = False                                                 
        self._pre_force_was_deflected = False
        self._pre_force_was_grid      = False

        self._plane_state = 0
        self._view_mode = "3D"
        self._grid_index = 0

        self.current_hover_data = None
        self.hovered_node_id = None
        self.hovered_elem_id = None

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

        self.force_diagram_active = False

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
        self.load_items = []
        self._support_items = []
        self._support_positions = {'fixed': [], 'pinned': [], 'roller': [], 'custom': []}
        self._support_rebuild_timer = QTimer()
        self._support_rebuild_timer.setSingleShot(True)
        self._support_rebuild_timer.timeout.connect(self._rebuild_support_items)
        self._sel_overlay_items = []      
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

    def initializeGL(self):
        super().initializeGL()
        self.vbo_manager.init_gl()    
        self.vbo_manager.load_font_texture()  

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

        xs = [n.x for n in m.nodes.values()]
        ys = [n.y for n in m.nodes.values()]
        zs = [n.z for n in m.nodes.values()]

        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        min_z, max_z = min(zs), max(zs)

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

    def draw_model(self, model, sel_elems=None, sel_nodes=None, progress=None):
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

    def _shell_interior_dashes(self, pts, inset=0.18, n_dashes=5):
        """
        Compute interior dashed line segments for a shell face (SAP2000 style).

        The polygon is shrunk toward its centroid by `inset` fraction, then each
        edge of that inset polygon is split into `n_dashes` dash segments.

        pts      : (N, 3) float array — 3-D world-space polygon vertices in order
        inset    : 0..1 fraction to shrink toward centroid (0.18 → 18 % inward)
        n_dashes : number of dash/gap cycles per inset edge

        Returns list of [p_start, p_end] pairs; each element is a list of 3 floats.
        """
        centroid  = pts.mean(axis=0)
        inset_pts = pts + (centroid - pts) * inset
        n         = len(inset_pts)

        segs = []
        for i in range(n):
            p1 = inset_pts[i]
            p2 = inset_pts[(i + 1) % n]
            d  = p2 - p1
            L  = np.linalg.norm(d)
            if L < 1e-6:
                continue
            u        = d / L
            period   = L / n_dashes
            dash_len = period * 0.55                        

            t = 0.0
            for _ in range(n_dashes):
                s = p1 + t * u
                e = p1 + (t + dash_len) * u
                segs.append([s.tolist(), e.tolist()])
                t += period
        return segs

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
            return

        sel_ids     = set(getattr(self, 'selected_area_ids', []))
        hov_id      = getattr(self, 'hovered_area_id', None)
        active_ids  = sel_ids | ({hov_id} if hov_id is not None else set())

        if not active_ids:
            self._area_interior_lines.setVisible(False)
            return

        SEL_COLOR = [1.0, 1.0, 0.0, 1.0]                                        
        verts, colors = [], []

        for aeid in active_ids:
            ae = model.area_elements.get(aeid)
            if ae is None or len(ae.nodes) < 3:
                continue

            states = [self._get_visibility_state(n.x, n.y, n.z) for n in ae.nodes]
            if min(states) < 2:
                continue
                                                                   
            pts = np.array([[n.x, n.y, n.z] for n in ae.nodes])
            for seg in self._shell_interior_dashes(pts):
                verts.extend(seg)
                colors.extend([SEL_COLOR, SEL_COLOR])

        if verts:
            iv = np.array(verts,  dtype=np.float32)
            ic = np.array(colors, dtype=np.float32)
            self._area_interior_lines.setData(pos=iv, color=ic, width=1.5, mode='lines')
            self._area_interior_lines.setVisible(True)
        else:
            self._area_interior_lines.setVisible(False)
    
    def clear_selection(self):
        """Clears all selection state from the canvas."""
        self.selected_element_ids = []
        self.selected_node_ids    = []
        self.selected_area_ids    = []
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

    def _update_area_vbo(self, model):
        if not hasattr(self, 'vbo_manager') or not self.vbo_manager.is_initialized:
            return

        _plane = self.active_view_plane
        _new_key = (
            frozenset(model.area_elements.keys()),
                                                                                  
            getattr(self, 'show_slabs',          True),
            getattr(self, 'view_extruded',        False),
            getattr(self, 'view_deflected',       False),
            getattr(self, 'show_tributary_loads', False),
            getattr(self, 'show_tributary_heatmap', False),
            _plane['axis']  if _plane else None,
            _plane['value'] if _plane else None,
            getattr(self, 'show_ghost_structure', True),
            float(self.display_config.get('slab_opacity',    0.45)),
            float(self.display_config.get('extrude_opacity', 0.65)),
            tuple(self.display_config.get('edge_color',      (0, 0, 0, 1))),
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
        ec_raw        = self.display_config.get("edge_color", (0, 0, 0, 1))
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

        tri_pts, tri_fc, tri_ec = [], [], []
        ghost_pts, ghost_fc = [], []

        fill_verts, fill_colors, fill_faces = [], [], []
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

            min_state = min(_vis(n.x, n.y, n.z) for n in nodes)
            if min_state == 0: continue

            r, g, b = _parse_hex(getattr(ae.section, 'display_color', '#808080'))
            pts = np.array([[n.x, n.y, n.z] for n in nodes], dtype=np.float32)

            is_selected = hasattr(self, 'selected_area_ids') and aeid in self.selected_area_ids

            if min_state == 1:        
                                                                                  
                if n_count == 3:
                    ghost_pts.append(pts); ghost_fc.append([r, g, b, 0.15])
                else:
                    for pt in pts:
                        ghost_verts.append(pt.tolist()); ghost_colors.append([r, g, b, 0.15])
                    for i in range(1, n_count - 1):
                        ghost_faces.append([ghost_v_offset, ghost_v_offset + i, ghost_v_offset + i + 1])
                    ghost_v_offset += n_count
                continue

            fill_color = [r, g, b, face_opacity]
            edge_c = global_edge_c

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
                fill_faces.extend((hf + vert_offset).tolist())
                vert_offset += len(hv)
                for i in range(n_count):
                    ni = (i + 1) % n_count
                    edge_verts.extend([pts[i].tolist(), pts[ni].tolist()])
                    edge_colors.extend([edge_c, edge_c])
                continue
                                           
            if not is_extruded and n_count == 3:                            
                tri_pts.append(pts); tri_fc.append(fill_color); tri_ec.append(edge_c)
            elif not is_extruded:                        
                for pt in pts:
                    fill_verts.append(pt.tolist()); fill_colors.append(fill_color)
                for i in range(1, n_count - 1):
                    fill_faces.append([vert_offset, vert_offset + i, vert_offset + i + 1])
                for i in range(n_count):
                    ni = (i + 1) % n_count
                    edge_verts.extend([pts[i].tolist(), pts[ni].tolist()])
                    edge_colors.extend([edge_c, edge_c])
                vert_offset += n_count
            else:                       
                t = getattr(ae.section, 'membrane_thickness', getattr(ae.section, 'thickness', 0.2))
                if n_count == 4: v1, v2 = pts[2] - pts[0], pts[3] - pts[1]
                else: v1, v2 = pts[1] - pts[0], pts[2] - pts[0]
                
                normal = np.cross(v1, v2)
                nlen = np.linalg.norm(normal)
                normal = normal / nlen if nlen > 1e-9 else np.array([0, 0, 1.0])
                offset = normal * (t / 2.0)
                top_pts, bot_pts = pts + offset, pts - offset

                for pt in top_pts: fill_verts.append(pt.tolist()); fill_colors.append(fill_color)
                for pt in bot_pts: fill_verts.append(pt.tolist()); fill_colors.append(fill_color)
                for i in range(1, n_count - 1): fill_faces.append([vert_offset, vert_offset + i, vert_offset + i + 1])
                b_off = vert_offset + n_count
                for i in range(1, n_count - 1): fill_faces.append([b_off, b_off + i + 1, b_off + i])
                for i in range(n_count):
                    ni = (i + 1) % n_count
                    t1, t2 = vert_offset + i, vert_offset + ni
                    b1, b2 = b_off + i, b_off + ni
                    fill_faces.extend([[t1, b1, b2], [t1, b2, t2]])
                    edge_verts.extend([top_pts[i].tolist(), top_pts[ni].tolist(), bot_pts[i].tolist(), bot_pts[ni].tolist(), top_pts[i].tolist(), bot_pts[i].tolist()])
                    edge_colors.extend([edge_c] * 6)
                vert_offset += 2 * n_count

        N_tri = len(tri_pts)
        if N_tri > 0:
            b_fv = np.concatenate(tri_pts, axis=0)
            b_fc = np.repeat(np.array(tri_fc, dtype=np.float32), 3, axis=0)
            base = (np.arange(N_tri, dtype=np.uint32) * 3) + vert_offset
            b_ff = np.stack([base, base + 1, base + 2], axis=1)

            p0, p1, p2 = b_fv[0::3], b_fv[1::3], b_fv[2::3]
            b_ev = np.empty((N_tri * 6, 3), dtype=np.float32)
            b_ev[0::6], b_ev[1::6] = p0, p1
            b_ev[2::6], b_ev[3::6] = p1, p2
            b_ev[4::6], b_ev[5::6] = p2, p0
            b_ec = np.repeat(np.array(tri_ec, dtype=np.float32), 6, axis=0)

            if fill_verts:
                all_fv = np.concatenate([np.array(fill_verts, dtype=np.float32), b_fv], axis=0)
                all_fc = np.concatenate([np.array(fill_colors, dtype=np.float32), b_fc], axis=0)
                all_ff = np.concatenate([np.array(fill_faces, dtype=np.uint32), b_ff], axis=0)
                all_ev = np.concatenate([np.array(edge_verts, dtype=np.float32), b_ev], axis=0)
                all_ec = np.concatenate([np.array(edge_colors, dtype=np.float32), b_ec], axis=0)
            else:
                all_fv, all_fc, all_ff, all_ev, all_ec = b_fv, b_fc, b_ff, b_ev, b_ec
        else:
            all_fv = np.array(fill_verts, dtype=np.float32).reshape(-1, 3) if fill_verts else np.array([], dtype=np.float32)
            all_fc = np.array(fill_colors, dtype=np.float32).reshape(-1, 4) if fill_colors else np.array([], dtype=np.float32)
            all_ff = np.array(fill_faces, dtype=np.uint32).reshape(-1, 3) if fill_faces else np.array([], dtype=np.uint32)
            all_ev = np.array(edge_verts, dtype=np.float32).reshape(-1, 3) if edge_verts else np.array([], dtype=np.float32)
            all_ec = np.array(edge_colors, dtype=np.float32).reshape(-1, 4) if edge_colors else np.array([], dtype=np.float32)

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

        if all_fv.size > 0 or all_ev.size > 0:
            self.vbo_manager.upload_area_geometry(all_fv, all_fc, all_ff, all_ev, all_ec)
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
        self.update()

    def _force_draw_model(self, model, sel_elems=None, sel_nodes=None, progress=None):
        """
        Force redraw the model even if animation is running.
        Used internally by draw_model when animation is stopped.
        """
        def _p(msg):
            if progress: progress(msg)

        _p("Initializing OpenGL render context...")
        self.current_model = model

        _p("Allocating GPU memory pools for structural data...")
        _p("Compiling core vertex and fragment shader programs...")
        _p("Establishing global lighting and material states...")

        if sel_elems is not None: self.selected_element_ids = sel_elems
        if sel_nodes is not None: self.selected_node_ids = sel_nodes
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
        if self.view_extruded:
            _p("Extruding 3D frame elements to VBO...")
            self._draw_elements_extruded(model)
        else:
            _p("Generating wireframe elements...")
            self._draw_elements_wireframe(model)

        if self.show_loads and not in_analysis_mode:
            _p("Generating applied load geometries...")
            self._pending_load_fill_verts = []
            self._pending_load_fill_colors = []
            self._pending_load_fill_faces = []
            self._pending_load_line_pos = []
            self._pending_load_line_colors = []
            self._draw_loads(model)
            self._draw_member_loads(model)
            self._draw_member_point_loads(model)
            self._draw_area_loads(model)  
            _p("Pushing load buffers to GPU...")
            self._upload_loads_to_vbo()
            self._upload_load_labels_to_gpu() 
        elif self.reaction_diagram_active and in_analysis_mode and self.reaction_data:
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

        if self.show_slabs:
            _p("Triangulating shell/area VBOs...")
            self._draw_slabs(model)
            self._update_area_vbo(model)

        if self.show_local_axes:
            _p("Generating local coordinate triads...")
            self._draw_local_axes(model)

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

    def update_selection_overlay(self, sel_elems, sel_nodes, sel_areas=None, sel_links=None, progress=None):

        def _p(msg):
            if progress: progress(msg)

        if not hasattr(self, 'current_model') or self.current_model is None:
            return
                   
        """Fast-path selection update. Skips full geometry rebuild."""
        self.selected_element_ids = list(sel_elems) if sel_elems is not None else []
        self.selected_node_ids    = list(sel_nodes)  if sel_nodes  is not None else []
        self.selected_area_ids    = list(sel_areas)  if sel_areas  is not None else []
        self.selected_link_ids    = list(sel_links)  if sel_links  is not None else []
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
            if self.show_loads and not in_analysis_mode:
                self._pending_load_fill_verts = []
                self._pending_load_fill_colors = []
                self._pending_load_fill_faces = []
                self._pending_load_line_pos = []
                self._pending_load_line_colors = []
                self._draw_loads(self.current_model)
                self._draw_member_loads(self.current_model)
                self._draw_member_point_loads(self.current_model)
                self._draw_area_loads(self.current_model)

                self._upload_loads_to_vbo()
                self._loads_dirty = False

                self._upload_load_labels_to_gpu()
            elif self.reaction_diagram_active and in_analysis_mode and self.reaction_data:
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

    def _rebuild_selection_overlay(self):
        """Dispatches to wireframe or extruded overlay builder, then nodes."""
        if self.view_extruded:
            self._rebuild_extruded_selection_overlay()
        else:
            self._rebuild_wireframe_selection_overlay()
        self._rebuild_node_selection_overlay()
        self._rebuild_link_selection_overlay()

    def _rebuild_link_selection_overlay(self):
        if not getattr(self, 'selected_link_ids', None) or not self.current_model: return
        model = self.current_model
        sel_color = np.array([1.0, 1.0, 0.0, 1.0])
        sel_pos = []

        if not hasattr(model, 'links'): return

        for lid in self.selected_link_ids:
            if lid not in model.links: continue
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

        can_deflect = (self.view_deflected and
                       hasattr(model, 'has_results') and
                       model.has_results and
                       model.results is not None)

        displacements = model.results.get("displacements", {}) if can_deflect else {}

        if can_deflect:
            curved_pos = []
            curved_colors = []
            for eid in self.selected_element_ids:
                if eid not in model.elements:
                    continue
                el = model.elements[eid]
                n1, n2 = el.node_i, el.node_j

                if min(self._get_visibility_state(n1.x, n1.y, n1.z), self._get_visibility_state(n2.x, n2.y, n2.z)) != 2:
                    continue

                p1 = np.array([n1.x, n1.y, n1.z])
                p2 = np.array([n2.x, n2.y, n2.z])
                
                res_i = displacements.get(str(n1.id))
                res_j = displacements.get(str(n2.id))
                
                if res_i and res_j:
                    if eid not in self.deflection_cache:
                        v1_orig, v2_orig, v3_orig = self._get_consistent_axes(el)

                        off_i = getattr(el, 'end_offset_i', 0.0)
                        off_j = getattr(el, 'end_offset_j', 0.0)

                        curve_data = get_deflected_shape(
                            [n1.x, n1.y, n1.z], [n2.x, n2.y, n2.z],
                            res_i, res_j, v1_orig, v2_orig, v3_orig,
                            scale=self.deflection_scale, num_points=11, 
                            off_i=getattr(el, 'end_offset_i', 0.0), off_j=getattr(el, 'end_offset_j', 0.0)                     
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

                    off_i = getattr(el, 'end_offset_i', 0.0)
                    off_j = getattr(el, 'end_offset_j', 0.0)
                    vec = p2_orig - p1_orig
                    _len = np.linalg.norm(vec)
                    p1_flex, p2_flex = p1_orig.copy(), p2_orig.copy()
                    if _len > 0.001 and (off_i > 0 or off_j > 0):
                        _u = vec / _len
                        if off_i + off_j >= _len:
                            _scale = (_len / (off_i + off_j)) * 0.99
                            p1_flex = p1_orig + (_u * off_i * _scale)
                            p2_flex = p2_orig - (_u * off_j * _scale)
                        else:
                            p1_flex = p1_orig + (_u * off_i)
                            p2_flex = p2_orig - (_u * off_j)

                    K = len(curve_data_full)
                    pos_full_arr = np.array([cd[0] for cd in curve_data_full], dtype=np.float64)
                    s_arr = (np.arange(K) / (K - 1))[:, None] if K > 1 else np.zeros((K, 1))
                    pos_orig_arr = p1_flex + s_arr * (p2_flex - p1_flex)
                    curve_pts = pos_orig_arr + (pos_full_arr - pos_orig_arr) * self.anim_factor
                                                                                         
                    dash, gap = 0.4, 0.25
                    dist_accum, on = 0.0, True
                    for k in range(len(curve_pts) - 1):
                        seg_start = curve_pts[k]
                        seg_end   = curve_pts[k + 1]
                        seg_vec   = seg_end - seg_start
                        seg_len   = np.linalg.norm(seg_vec)
                        if seg_len < 1e-6:
                            continue
                        seg_u = seg_vec / seg_len
                        walked = 0.0
                        while walked < seg_len:
                            interval = dash if on else gap
                            remaining_in_interval = interval - dist_accum
                            can_walk = min(remaining_in_interval, seg_len - walked)
                            if on:
                                curved_pos.extend([seg_start + seg_u * walked,
                                                   seg_start + seg_u * (walked + can_walk)])
                                curved_colors.extend([sel_color, sel_color])
                            walked += can_walk
                            dist_accum += can_walk
                            if dist_accum >= interval:
                                dist_accum = 0.0
                                on = not on
                else:
                    curved_pos.extend([p1, p2])
                    curved_colors.extend([sel_color, sel_color])
                    
            if curved_pos:
                item = gl.GLLinePlotItem(
                    pos=np.array(curved_pos), color=np.array(curved_colors),
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

            if min(self._get_visibility_state(n1.x, n1.y, n1.z), self._get_visibility_state(n2.x, n2.y, n2.z)) != 2:
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
            dash_pos, dash_colors = [], []
            for k in range(0, len(sel_pos) - 1, 2):
                p1_d = np.array(sel_pos[k])
                p2_d = np.array(sel_pos[k + 1])
                vec = p2_d - p1_d
                seg_len = np.linalg.norm(vec)
                if seg_len < 1e-6:
                    continue
                u = vec / seg_len
                pos_d, on = 0.0, True
                dash, gap = 0.4, 0.25
                while pos_d < seg_len:
                    end_d = min(pos_d + (dash if on else gap), seg_len)
                    if on:
                        dash_pos.extend([p1_d + u * pos_d, p1_d + u * end_d])
                        dash_colors.extend([sel_color, sel_color])
                    pos_d, on = end_d, not on
            item = gl.GLLinePlotItem(
                pos=np.array(dash_pos) if dash_pos else np.array(sel_pos), 
                color=np.array(dash_colors) if dash_colors else np.array(sel_colors), 
                mode='lines', width=1.5, antialias=True
            )
            item.setGLOptions({
                'glEnable': (GL_BLEND,),
                'glBlendFunc': (GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA),
                'glDisable': (GL_DEPTH_TEST,)
            })
            self.addItem(item)
            self._sel_overlay_items.append(item)

    def _rebuild_extruded_selection_overlay(self):
        if not self.selected_element_ids or not self.current_model:
            return
        model = self.current_model
        color_sel = np.array([1.0, 1.0, 0.0, 1.0])

        can_deflect = (self.view_deflected and
                       hasattr(model, 'has_results') and
                       model.has_results and
                       model.results is not None)

        displacements = model.results.get("displacements", {}) if can_deflect else {}

        dash_lines = []
        dash_colors_ext = []
        dash, gap = 0.4, 0.25

        for eid in self.selected_element_ids:
            if eid not in model.elements:
                continue
            el = model.elements[eid]
            n1, n2 = el.node_i, el.node_j

            if min(self._get_visibility_state(n1.x, n1.y, n1.z), self._get_visibility_state(n2.x, n2.y, n2.z)) != 2:
                continue

            p1 = np.array([n1.x, n1.y, n1.z])
            p2 = np.array([n2.x, n2.y, n2.z])

            if can_deflect:
                                       
                res_i = displacements.get(str(n1.id))
                res_j = displacements.get(str(n2.id))

                if res_i and res_j:
                    if eid not in self.deflection_cache:
                        v1_orig, v2_orig, v3_orig = self._get_consistent_axes(el)

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

                    off_i = getattr(el, 'end_offset_i', 0.0)
                    off_j = getattr(el, 'end_offset_j', 0.0)
                    vec = p2_orig - p1_orig
                    _len = np.linalg.norm(vec)
                    p1_flex, p2_flex = p1_orig.copy(), p2_orig.copy()
                    if _len > 0.001 and (off_i > 0 or off_j > 0):
                        _u = vec / _len
                        if off_i + off_j >= _len:
                            _scale = (_len / (off_i + off_j)) * 0.99
                            p1_flex = p1_orig + (_u * off_i * _scale)
                            p2_flex = p2_orig - (_u * off_j * _scale)
                        else:
                            p1_flex = p1_orig + (_u * off_i)
                            p2_flex = p2_orig - (_u * off_j)

                    K = len(curve_data_full)
                    pos_full_arr = np.array([cd[0] for cd in curve_data_full], dtype=np.float64)
                    s_arr = (np.arange(K) / (K - 1))[:, None] if K > 1 else np.zeros((K, 1))
                    pos_orig_arr = p1_flex + s_arr * (p2_flex - p1_flex)
                    curve_pts = pos_orig_arr + (pos_full_arr - pos_orig_arr) * self.anim_factor

                    dist_accum, on = 0.0, True
                    for k in range(len(curve_pts) - 1):
                        seg_start = curve_pts[k]
                        seg_end   = curve_pts[k + 1]
                        seg_vec   = seg_end - seg_start
                        seg_len   = np.linalg.norm(seg_vec)
                        if seg_len < 1e-6:
                            continue
                        seg_u = seg_vec / seg_len
                        walked = 0.0
                        while walked < seg_len:
                            interval = dash if on else gap
                            remaining = interval - dist_accum
                            can_walk = min(remaining, seg_len - walked)
                            if on:
                                dash_lines.extend([seg_start + seg_u * walked,
                                                   seg_start + seg_u * (walked + can_walk)])
                                dash_colors_ext.extend([color_sel, color_sel])
                            walked += can_walk
                            dist_accum += can_walk
                            if dist_accum >= interval:
                                dist_accum = 0.0
                                on = not on
                    continue

                if res_i:
                    p1 = p1 + np.array(res_i[:3]) * self.deflection_scale * self.anim_factor
                if res_j:
                    p2 = p2 + np.array(res_j[:3]) * self.deflection_scale * self.anim_factor

            vec = p2 - p1
            seg_len = np.linalg.norm(vec)
            if seg_len < 1e-6:
                continue
            u = vec / seg_len
            pos_d, on = 0.0, True
            while pos_d < seg_len:
                end_d = min(pos_d + (dash if on else gap), seg_len)
                if on:
                    dash_lines.extend([p1 + u * pos_d, p1 + u * end_d])
                    dash_colors_ext.extend([color_sel, color_sel])
                pos_d, on = end_d, not on

        if dash_lines:
            cl = gl.GLLinePlotItem(
                pos=np.array(dash_lines),
                color=np.array(dash_colors_ext),
                mode='lines', width=2.5, antialias=True
            )
            cl.setGLOptions({
                'glEnable': (GL_BLEND,),
                'glBlendFunc': (GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA),
                'glDisable': (GL_DEPTH_TEST,)
            })
            
            self.addItem(cl)
            self._sel_overlay_items.append(cl)
            
    def _rebuild_node_selection_overlay(self):
        if not self.selected_node_ids or not self.current_model:
            return
        model = self.current_model
        size = self.display_config.get("node_size", 6)

        can_deflect = (self.view_deflected and
                       hasattr(model, 'has_results') and
                       model.has_results and
                       model.results is not None)

        sel_pos = []
        for nid in self.selected_node_ids:
            if nid not in model.nodes:
                continue
            n = model.nodes[nid]

            if self._get_visibility_state(n.x, n.y, n.z) != 2:
                continue

            nx, ny, nz = n.x, n.y, n.z
            if can_deflect:
                disp = model.results.get("displacements", {}).get(str(nid))
                if disp:
                    nx += disp[0] * self.deflection_scale * self.anim_factor
                    ny += disp[1] * self.deflection_scale * self.anim_factor
                    nz += disp[2] * self.deflection_scale * self.anim_factor
            sel_pos.append([nx, ny, nz])

        if sel_pos:
            sp = gl.GLScatterPlotItem(
                pos=np.array(sel_pos),
                size=size,
                color=(1, 1, 0, 1),
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
                              
        for nid, n in model.nodes.items():
            nx, ny, nz = n.x, n.y, n.z
            
            if can_deflect:
                disp = model.results.get("displacements", {}).get(str(nid))
                if disp:
                    nx += disp[0] * self.deflection_scale * self.anim_factor
                    ny += disp[1] * self.deflection_scale * self.anim_factor
                    nz += disp[2] * self.deflection_scale * self.anim_factor

            xyz = [nx, ny, nz]
            
            v_state = self._get_visibility_state(n.x, n.y, n.z)
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

        if pos_free: 
            item = gl.GLScatterPlotItem(pos=np.array(pos_free), size=size, color=color_tuple, pxMode=True)
            self.addItem(item)
            self.node_items.append(item)

        if ghost_pos and self.show_joints:
            item = gl.GLScatterPlotItem(pos=np.array(ghost_pos), size=4, color=(0.7, 0.7, 0.7, 0.4), pxMode=True)
            self.addItem(item)
            self.node_items.append(item)

        if self.show_supports:
                                                                                         
            visible_nodes = {nid: n for nid, n in model.nodes.items() if self._get_visibility_state(n.x, n.y, n.z) == 2}
            
            scale = self._screen_scale() 
            links_dict = getattr(model, 'links', {})
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

        for eid, el in model.elements.items():
            n1, n2 = el.node_i, el.node_j
            v1 = self._get_visibility_state(n1.x, n1.y, n1.z)
            v2 = self._get_visibility_state(n2.x, n2.y, n2.z)

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
                            num_points=11,
                            off_i=getattr(el, 'end_offset_i', 0.0),
                            off_j=getattr(el, 'end_offset_j', 0.0)
                        )
                        self.deflection_cache[cache_key] = {
                            'curve_data': curve_data,
                            'p1_orig': p1.copy(),
                            'p2_orig': p2.copy()
                        }

                    cached          = self.deflection_cache[cache_key]
                    curve_data_full = cached['curve_data']

                    _off_i = getattr(el, 'end_offset_i', 0.0)
                    _off_j = getattr(el, 'end_offset_j', 0.0)
                    _vec   = p2 - p1
                    _len   = np.linalg.norm(_vec)
                    p1_flex, p2_flex = p1.copy(), p2.copy()
                    if _len > 0.001 and (_off_i > 0 or _off_j > 0):
                        _u = _vec / _len
                        if _off_i + _off_j >= _len:
                            _scale  = (_len / (_off_i + _off_j)) * 0.99
                            p1_flex = p1 + (_u * _off_i * _scale)
                            p2_flex = p2 - (_u * _off_j * _scale)
                        else:
                            p1_flex = p1 + (_u * _off_i)
                            p2_flex = p2 - (_u * _off_j)

                    if _off_i > 0:
                        p1_def       = p1 + np.array(res_i[:3]) * self.deflection_scale * self.anim_factor
                        p1_flex_def, _, _ = curve_data_full[0]
                        p1_flex_anim = p1_flex + (p1_flex_def - p1_flex) * self.anim_factor
                        curved_pos.extend([p1_def, p1_flex_anim])
                        curved_colors.extend([rigid_black, rigid_black])

                    if _off_j > 0:
                        p2_def       = p2 + np.array(res_j[:3]) * self.deflection_scale * self.anim_factor
                        p2_flex_def, _, _ = curve_data_full[-1]
                        p2_flex_anim = p2_flex + (p2_flex_def - p2_flex) * self.anim_factor
                        curved_pos.extend([p2_flex_anim, p2_def])
                        curved_colors.extend([rigid_black, rigid_black])

                    K            = len(curve_data_full)
                    pos_full_arr = np.array([cd[0] for cd in curve_data_full], dtype=np.float64)
                    s_arr        = (np.arange(K) / (K - 1))[:, None]
                    pos_orig_arr = p1_flex + s_arr * (p2_flex - p1_flex)
                    pts          = pos_orig_arr + (pos_full_arr - pos_orig_arr) * self.anim_factor
                    pairs        = np.empty((2 * (K - 1), 3), dtype=np.float64)
                    pairs[0::2]  = pts[:-1]
                    pairs[1::2]  = pts[1:]
                    curved_pos.extend(pairs)
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
        self.ex_edges = []
        self.ex_edge_colors = []

        ghost_ex_verts, ghost_ex_faces, ghost_ex_colors = [], [], []
      
        opacity = self.display_config.get("extrude_opacity", 0.35)
        show_edges = self.display_config.get("show_edges", False)
        edge_c = np.array(self.display_config.get("edge_color", (0, 0, 0, 1)))
        edge_width = self.display_config.get("edge_width", 1.0)
        
        can_deflect = (self.view_deflected and 
                       hasattr(model, 'has_results') and 
                       model.has_results and 
                       model.results is not None)

        displacements = model.results.get("displacements", {}) if can_deflect else {}

        fallback_line_pos    = []
        fallback_line_colors = []

        for eid, el in model.elements.items():
            n1, n2 = el.node_i, el.node_j
            
            v1 = self._get_visibility_state(n1.x, n1.y, n1.z)
            v2 = self._get_visibility_state(n2.x, n2.y, n2.z)

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
                            num_points=11,
                            off_i=getattr(el, 'end_offset_i', 0.0),
                            off_j=getattr(el, 'end_offset_j', 0.0)
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
                        num_points=11,
                        off_i=getattr(el, 'end_offset_i', 0.0),
                        off_j=getattr(el, 'end_offset_j', 0.0)
                    )   
                    
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
                        draw_caps=needs_caps
                    )

        v_arr = np.array(self.ex_vertices, dtype=np.float32) if self.ex_vertices else np.empty((0, 3), dtype=np.float32)
        c_arr = np.array(self.ex_colors,   dtype=np.float32) if self.ex_colors   else np.empty((0, 4), dtype=np.float32)
        f_arr = np.array(self.ex_faces,    dtype=np.int32)   if self.ex_faces    else np.empty((0, 3), dtype=np.int32)

        self.makeCurrent()
        self.vbo_manager.upload_extruded_geometry(v_arr, c_arr, f_arr)

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

    def _add_loft_segment(self, c1, c2, v2_a, v3_a, v2_b, v3_b, shape, color, show_edges, edge_color, draw_start_ring=False, draw_end_ring=False, draw_caps=False):
        """
        Smart Extrusion: Generates triangles but selectively hides internal 'ribs' 
        to maintain the clean 'glass' look.
        """
                               
        start_idx = len(self.ex_vertices)
        
        verts_a = []
        for y, z in shape:
            p = c1 + (y * v2_a) + (z * v3_a)
            verts_a.append(p)
            
        verts_b = []
        for y, z in shape:
            p = c2 + (y * v2_b) + (z * v3_b)
            verts_b.append(p)
            
        self.ex_vertices.extend(verts_a)
        self.ex_vertices.extend(verts_b)
        
        for _ in range(len(verts_a) + len(verts_b)):
            self.ex_colors.append(color)
            
        n = len(shape)
        for i in range(n):
            next_i = (i + 1) % n
            
            idx_a_curr = start_idx + i
            idx_a_next = start_idx + next_i
            idx_b_curr = start_idx + n + i
            idx_b_next = start_idx + n + next_i
            
            self.ex_faces.append([idx_a_curr, idx_a_next, idx_b_next])
            self.ex_faces.append([idx_a_curr, idx_b_next, idx_b_curr])
            
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
                root_a = start_idx
                for i in range(1, n - 1):
                                                                     
                    self.ex_faces.append([root_a, start_idx + i + 1, start_idx + i])
            if draw_end_ring and n >= 3:
                root_b = start_idx + n
                for i in range(1, n - 1):
                                                                 
                    self.ex_faces.append([root_b, start_idx + n + i, start_idx + n + i + 1])
    
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
                           show_labels_mode='all', text_size=None, selected_ids=None):
        """
        Builds and renders the 3D force diagrams for the active model.
        """
        from core.force_diagram import ForceDiagramBuilder

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

        builder = ForceDiagramBuilder(
            model,
            component=component,
            scale_factor=scale_factor,
            displacements=displacements,
            matrices_path=matrices_path,
            show_labels=show_labels,
            show_labels_mode=show_labels_mode,
            text_size=text_size,active_view_plane=self.active_view_plane,                    
            show_ghost_structure=self.show_ghost_structure,
            selected_ids=selected_ids
        )
        success = builder.build()

        if not success:
            self.vbo_manager.clear_force_geometry()
            self.force_labels = []
            return False

        self.force_labels = builder.labels

        self.makeCurrent()
                                                                                
        self._upload_load_labels_to_gpu()

        self._pending_force_upload = {
            'fill_verts':  builder.fill_verts,
            'fill_colors': builder.fill_colors,
            'fill_faces':  builder.fill_faces,
            'line_pos':    builder.line_pos,
            'line_colors': builder.line_colors,
        }

        self.force_diagram_active = True

        self.update()
        return True

    def clear_force_diagrams(self):
        """Hides force diagrams and restores extruded/deformed state that was active before."""
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

    def _draw_slabs(self, model):
                                                                                                
        pass

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

    def _rebuild_support_items(self):
        """Rebuild support meshes with current zoom level — keeps symbols screen-size-stable."""
        for item in self._support_items:
            try: self.removeItem(item)
            except Exception: pass
        self._support_items.clear()
        
        self.node_items = [item for item in self.node_items if item not in self._support_items]

        if not self.current_model or not getattr(self, 'show_supports', True): 
            return

        visible_nodes = {nid: n for nid, n in self.current_model.nodes.items() if self._get_visibility_state(n.x, n.y, n.z) == 2}

        scale = self._screen_scale()
        links_dict = getattr(self.current_model, 'links', {})
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
        
        arrow_lines = []
        arrow_colors = []
        
        L = 2.0; H = 0.5; W = 0.2                           

        AXIS_X = np.array([1.0, 0.0, 0.0])
        AXIS_Y = np.array([0.0, 1.0, 0.0])
        AXIS_Z = np.array([0.0, 0.0, 1.0])
        PERP_X = AXIS_X
        PERP_Z = AXIS_Z
        c_black = (0, 0, 0, 1)

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
                                                                           
            if self._get_visibility_state(node.x, node.y, node.z) != 2: continue
            
            origin = np.array([node.x, node.y, node.z])
            is_selected = (node.id in self.selected_node_ids)

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
        c_black = (0, 0, 0, 1)

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

            if self._get_visibility_state(node.x, node.y, node.z) != 2:
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

        from PyQt6.QtGui import QFont, QColor, QPen
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

            ex = ox + (dx / length) * AXIS_PX
            ey = oy + (dy / length) * AXIS_PX

            painter.setPen(QPen(color, 2))
            painter.drawLine(int(ox), int(oy), int(ex), int(ey))

            painter.setFont(ax_font)
            painter.setPen(color)
            painter.drawText(int(ex) + LABEL_PAD, int(ey) + LABEL_PAD, label)

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

        graph_paper_pos = []
        if active_axis == 'z':
            span_x = max(30.0, (x_max - x_min) * 1.5)
            span_y = max(30.0, (y_max - y_min) * 1.5)
            cx, cy = (x_max + x_min)/2.0, (y_max + y_min)/2.0
            
            u_name = unit_registry.length_unit_name
            if u_name in ['mm']: step = unit_registry.from_display_length(1000.0)
            elif u_name in ['cm', 'in']: step = unit_registry.from_display_length(100.0)
            else: step = unit_registry.from_display_length(1.0)
            if step < 0.1: step = 1.0                
            
            gx_start, gx_end = math.floor((cx - span_x)/step)*step, math.ceil((cx + span_x)/step)*step
            gy_start, gy_end = math.floor((cy - span_y)/step)*step, math.ceil((cy + span_y)/step)*step

            for gx in np.arange(gx_start, gx_end + step, step):
                graph_paper_pos.extend([[gx, gy_start, active_val], [gx, gy_end, active_val]])
            for gy in np.arange(gy_start, gy_end + step, step):
                graph_paper_pos.extend([[gx_start, gy, active_val], [gx_end, gy, active_val]])

        bubble_circ_pos, bubble_lines, dim_lines = [], [], []
        self.grid_labels = []
        
        x_data = get_full_data(getattr(grid, 'x_lines', []), getattr(grid, 'x_grids', []))
        y_data = get_full_data(getattr(grid, 'y_lines', []), getattr(grid, 'y_grids', []))
        
        b_scale = getattr(grid, 'bubble_size', 1.25)
        bubble_radius = b_scale * 0.45
        ext = b_scale * 2.5
        tick = bubble_radius * 0.25
        
        def format_dist(d):
                                                                        
            disp_d = unit_registry.to_display_length(d)
            
            u_str = unit_registry.length_unit_name
            if not u_str: u_str = "m"                
            
            if abs(disp_d - round(disp_d)) < 1e-4:
                return f"{int(round(disp_d))} {u_str}"
            else:
                return f"{disp_d:.2f} {u_str}"
            
        if active_axis == 'z':
            for i, d in enumerate(x_data):
                x = d['ord']
                bub_loc = d.get('bubble', 'End')
                
                if bub_loc in ['End', 'Both']:
                    bubble_lines.extend([[x, y_max, active_val], [x, y_max + ext, active_val]])
                    center = np.array([x, y_max + ext + bubble_radius, active_val])
                    bubble_circ_pos.extend(self._generate_circle_pts(center, bubble_radius, 'z'))
                    self._add_grid_bubble(center, bubble_radius, d['id'], 'z')
                    
                    if i < len(x_data) - 1:
                        next_x = x_data[i+1]['ord']
                        dist = abs(next_x - x)
                        dim_y = y_max + ext * 0.6
                        dim_lines.extend([[x, dim_y, active_val], [next_x, dim_y, active_val]])
                        dim_lines.extend([[x, dim_y-tick, active_val], [x, dim_y+tick, active_val]])
                        dim_lines.extend([[next_x, dim_y-tick, active_val], [next_x, dim_y+tick, active_val]])
                        
                        dim_center = np.array([(x + next_x)/2.0, dim_y + bubble_radius*0.6, active_val])
                        self._add_grid_dimension(dim_center, format_dist(dist), 'z', bubble_radius * 0.9, [1.0, 0.0, 0.0], [0.0, 1.0, 0.0])

                if bub_loc in ['Start', 'Both']:
                    bubble_lines.extend([[x, y_min, active_val], [x, y_min - ext, active_val]])
                    center = np.array([x, y_min - ext - bubble_radius, active_val])
                    bubble_circ_pos.extend(self._generate_circle_pts(center, bubble_radius, 'z'))
                    self._add_grid_bubble(center, bubble_radius, d['id'], 'z')
                    
                    if i < len(x_data) - 1:
                        next_x = x_data[i+1]['ord']
                        dist = abs(next_x - x)
                        dim_y = y_min - ext * 0.6
                        dim_lines.extend([[x, dim_y, active_val], [next_x, dim_y, active_val]])
                        dim_lines.extend([[x, dim_y-tick, active_val], [x, dim_y+tick, active_val]])
                        dim_lines.extend([[next_x, dim_y-tick, active_val], [next_x, dim_y+tick, active_val]])
                        
                        dim_center = np.array([(x + next_x)/2.0, dim_y - bubble_radius*0.6, active_val])
                        self._add_grid_dimension(dim_center, format_dist(dist), 'z', bubble_radius * 0.9, [1.0, 0.0, 0.0], [0.0, 1.0, 0.0])

            for i, d in enumerate(y_data):
                y = d['ord']
                bub_loc = d.get('bubble', 'End')
                
                if bub_loc in ['End', 'Both']:
                    bubble_lines.extend([[x_max, y, active_val], [x_max + ext, y, active_val]])
                    center = np.array([x_max + ext + bubble_radius, y, active_val])
                    bubble_circ_pos.extend(self._generate_circle_pts(center, bubble_radius, 'z'))
                    self._add_grid_bubble(center, bubble_radius, d['id'], 'z')
                    
                    if i < len(y_data) - 1:
                        next_y = y_data[i+1]['ord']
                        dist = abs(next_y - y)
                        dim_x = x_max + ext * 0.6
                        dim_lines.extend([[dim_x, y, active_val], [dim_x, next_y, active_val]])
                        dim_lines.extend([[dim_x-tick, y, active_val], [dim_x+tick, y, active_val]])
                        dim_lines.extend([[dim_x-tick, next_y, active_val], [dim_x+tick, next_y, active_val]])
                        
                        dim_center = np.array([dim_x + bubble_radius*0.6, (y + next_y)/2.0, active_val])
                        self._add_grid_dimension(dim_center, format_dist(dist), 'z', bubble_radius * 0.9, [0.0, 1.0, 0.0], [-1.0, 0.0, 0.0])

                if bub_loc in ['Start', 'Both']:
                    bubble_lines.extend([[x_min, y, active_val], [x_min - ext, y, active_val]])
                    center = np.array([x_min - ext - bubble_radius, y, active_val])
                    bubble_circ_pos.extend(self._generate_circle_pts(center, bubble_radius, 'z'))
                    self._add_grid_bubble(center, bubble_radius, d['id'], 'z')
                    
                    if i < len(y_data) - 1:
                        next_y = y_data[i+1]['ord']
                        dist = abs(next_y - y)
                        dim_x = x_min - ext * 0.6
                        dim_lines.extend([[dim_x, y, active_val], [dim_x, next_y, active_val]])
                        dim_lines.extend([[dim_x-tick, y, active_val], [dim_x+tick, y, active_val]])
                        dim_lines.extend([[dim_x-tick, next_y, active_val], [dim_x+tick, next_y, active_val]])
                        
                        dim_center = np.array([dim_x - bubble_radius*0.6, (y + next_y)/2.0, active_val])
                        self._add_grid_dimension(dim_center, format_dist(dist), 'z', bubble_radius * 0.9, [0.0, 1.0, 0.0], [-1.0, 0.0, 0.0])

        if active_axis == 'z':
            for i, d in enumerate(x_data):
                x = d['ord']
                bub_loc = d.get('bubble', 'End')
                
                if bub_loc in ['End', 'Both']:
                    bubble_lines.extend([[x, y_max, active_val], [x, y_max + ext, active_val]])
                    center = np.array([x, y_max + ext + bubble_radius, active_val])
                    bubble_circ_pos.extend(self._generate_circle_pts(center, bubble_radius, 'z'))
                    self._add_grid_bubble(center, bubble_radius, d['id'], 'z')
                    
                    if i < len(x_data) - 1:
                        next_x = x_data[i+1]['ord']
                        dist = abs(next_x - x)
                        dim_y = y_max + ext * 0.6
                        dim_lines.extend([[x, dim_y, active_val], [next_x, dim_y, active_val]])
                        dim_lines.extend([[x, dim_y-tick, active_val], [x, dim_y+tick, active_val]])
                        dim_lines.extend([[next_x, dim_y-tick, active_val], [next_x, dim_y+tick, active_val]])
                        dim_center = np.array([(x + next_x)/2.0, dim_y + bubble_radius*0.3, active_val])
                        self._add_grid_dimension(dim_center, format_dist(dist), 'z', bubble_radius * 0.8, [1.0, 0.0, 0.0], [0.0, 1.0, 0.0])

                if bub_loc in ['Start', 'Both']:
                    bubble_lines.extend([[x, y_min, active_val], [x, y_min - ext, active_val]])
                    center = np.array([x, y_min - ext - bubble_radius, active_val])
                    bubble_circ_pos.extend(self._generate_circle_pts(center, bubble_radius, 'z'))
                    self._add_grid_bubble(center, bubble_radius, d['id'], 'z')
                    
                    if i < len(x_data) - 1:
                        next_x = x_data[i+1]['ord']
                        dist = abs(next_x - x)
                        dim_y = y_min - ext * 0.6
                        dim_lines.extend([[x, dim_y, active_val], [next_x, dim_y, active_val]])
                        dim_lines.extend([[x, dim_y-tick, active_val], [x, dim_y+tick, active_val]])
                        dim_lines.extend([[next_x, dim_y-tick, active_val], [next_x, dim_y+tick, active_val]])
                        dim_center = np.array([(x + next_x)/2.0, dim_y + bubble_radius*0.3, active_val])
                        self._add_grid_dimension(dim_center, format_dist(dist), 'z', bubble_radius * 0.8, [1.0, 0.0, 0.0], [0.0, 1.0, 0.0])

            for i, d in enumerate(y_data):
                y = d['ord']
                bub_loc = d.get('bubble', 'End')
                
                if bub_loc in ['End', 'Both']:
                    bubble_lines.extend([[x_max, y, active_val], [x_max + ext, y, active_val]])
                    center = np.array([x_max + ext + bubble_radius, y, active_val])
                    bubble_circ_pos.extend(self._generate_circle_pts(center, bubble_radius, 'z'))
                    self._add_grid_bubble(center, bubble_radius, d['id'], 'z')
                    
                    if i < len(y_data) - 1:
                        next_y = y_data[i+1]['ord']
                        dist = abs(next_y - y)
                        dim_x = x_max + ext * 0.6
                        dim_lines.extend([[dim_x, y, active_val], [dim_x, next_y, active_val]])
                        dim_lines.extend([[dim_x-tick, y, active_val], [dim_x+tick, y, active_val]])
                        dim_lines.extend([[dim_x-tick, next_y, active_val], [dim_x+tick, next_y, active_val]])
                        dim_center = np.array([dim_x - bubble_radius*0.2, (y + next_y)/2.0, active_val])
                        self._add_grid_dimension(dim_center, format_dist(dist), 'z', bubble_radius * 0.8, [0.0, 1.0, 0.0], [-1.0, 0.0, 0.0])

                if bub_loc in ['Start', 'Both']:
                    bubble_lines.extend([[x_min, y, active_val], [x_min - ext, y, active_val]])
                    center = np.array([x_min - ext - bubble_radius, y, active_val])
                    bubble_circ_pos.extend(self._generate_circle_pts(center, bubble_radius, 'z'))
                    self._add_grid_bubble(center, bubble_radius, d['id'], 'z')
                    
                    if i < len(y_data) - 1:
                        next_y = y_data[i+1]['ord']
                        dist = abs(next_y - y)
                        dim_x = x_min - ext * 0.6
                        dim_lines.extend([[dim_x, y, active_val], [dim_x, next_y, active_val]])
                        dim_lines.extend([[dim_x-tick, y, active_val], [dim_x+tick, y, active_val]])
                        dim_lines.extend([[dim_x-tick, next_y, active_val], [dim_x+tick, next_y, active_val]])
                        dim_center = np.array([dim_x - bubble_radius*0.2, (y + next_y)/2.0, active_val])
                        self._add_grid_dimension(dim_center, format_dist(dist), 'z', bubble_radius * 0.8, [0.0, 1.0, 0.0], [-1.0, 0.0, 0.0])

        if graph_paper_pos:
            item = gl.GLLinePlotItem(pos=np.array(graph_paper_pos), mode='lines', color=(0.7, 0.7, 0.7, 0.25), width=1.0, antialias=True)
            self.addItem(item)
            self.static_items.append(item)

        if bright_pos:
            item = gl.GLLinePlotItem(pos=np.array(bright_pos), mode='lines', color=(0.4, 0.4, 0.4, 0.8), width=2, antialias=True)
            self.addItem(item)
            self.static_items.append(item)
            
        if dim_pos:
            alpha = 0.5 if is_3d else 0.15
            item = gl.GLLinePlotItem(pos=np.array(dim_pos), mode='lines', color=(0.6, 0.6, 0.6, alpha), width=1.5, antialias=True)
            self.addItem(item)
            self.static_items.append(item)

        if bubble_lines:
            item = gl.GLLinePlotItem(pos=np.array(bubble_lines), mode='lines', color=(0.3, 0.6, 0.9, 0.9), width=2, antialias=True)
            self.addItem(item)
            self.static_items.append(item)
            
        if dim_lines:
            item = gl.GLLinePlotItem(pos=np.array(dim_lines), mode='lines', color=(0.3, 0.5, 0.7, 0.8), width=1.0, antialias=True)
            self.addItem(item)
            self.static_items.append(item)

        if bubble_circ_pos:
            bub_item = gl.GLLinePlotItem(pos=np.array(bubble_circ_pos), mode='lines', color=(0.3, 0.6, 0.9, 1.0), width=2.0, antialias=True)
            self.addItem(bub_item)
            self.static_items.append(bub_item)

        self._rebuild_axis_items()

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
    
    def _add_grid_bubble(self, center, radius, text, plane_axis):
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
            'color': [0.15, 0.45, 0.85, 1.0], 
            'v_right': v_right.tolist(),
            'v_up': v_up.tolist(),
            'align': 'left',                                                     
            'text_height': t_height
        })

    def _add_grid_dimension(self, center, text, plane_axis, t_height, v_right, v_up):
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
            'color': [0.2, 0.5, 0.8, 1.0], 
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

        graph_paper_pos = []
        if active_axis == 'z':
            span_x = max(30.0, (x_max - x_min) * 1.5)
            span_y = max(30.0, (y_max - y_min) * 1.5)
            cx, cy = (x_max + x_min)/2.0, (y_max + y_min)/2.0
            
            u_name = unit_registry.length_unit_name
            if u_name in ['mm']: step = unit_registry.from_display_length(1000.0)
            elif u_name in ['cm', 'in']: step = unit_registry.from_display_length(100.0)
            else: step = unit_registry.from_display_length(1.0)
            if step < 0.1: step = 1.0 
            
            gx_start, gx_end = math.floor((cx - span_x)/step)*step, math.ceil((cx + span_x)/step)*step
            gy_start, gy_end = math.floor((cy - span_y)/step)*step, math.ceil((cy + span_y)/step)*step

            for gx in np.arange(gx_start, gx_end + step, step):
                graph_paper_pos.extend([[gx, gy_start, active_val], [gx, gy_end, active_val]])
            for gy in np.arange(gy_start, gy_end + step, step):
                graph_paper_pos.extend([[gx_start, gy, active_val], [gx_end, gy, active_val]])

        bubble_circ_pos, bubble_lines, dim_lines = [], [], []
        self.grid_labels = []
        
        x_data = get_full_data(getattr(grid, 'x_lines', []), getattr(grid, 'x_grids', []))
        y_data = get_full_data(getattr(grid, 'y_lines', []), getattr(grid, 'y_grids', []))
        
        b_scale = getattr(grid, 'bubble_size', 1.25)
        bubble_radius = b_scale * 0.45
        ext = b_scale * 2.5
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
                    self._add_grid_bubble(center, bubble_radius, d['id'], 'z')
                    
                    if i < len(x_data) - 1:
                        next_x = x_data[i+1]['ord']
                        dist = abs(next_x - x)
                        dim_y = y_max + ext * 0.6
                        dim_lines.extend([[x, dim_y, active_val], [next_x, dim_y, active_val]])
                        dim_lines.extend([[x, dim_y-tick, active_val], [x, dim_y+tick, active_val]])
                        dim_lines.extend([[next_x, dim_y-tick, active_val], [next_x, dim_y+tick, active_val]])
                        
                        dim_center = np.array([(x + next_x)/2.0, dim_y + bubble_radius*1.1, active_val])
                        self._add_grid_dimension(dim_center, format_dist(dist), 'z', bubble_radius * 0.8, [1.0, 0.0, 0.0], [0.0, 1.0, 0.0])

                if bub_loc in ['Start', 'Both']:
                    bubble_lines.extend([[x, y_min, active_val], [x, y_min - ext, active_val]])
                    center = np.array([x, y_min - ext - bubble_radius, active_val])
                    bubble_circ_pos.extend(self._generate_circle_pts(center, bubble_radius, 'z'))
                    self._add_grid_bubble(center, bubble_radius, d['id'], 'z')
                    
                    if i < len(x_data) - 1:
                        next_x = x_data[i+1]['ord']
                        dist = abs(next_x - x)
                        dim_y = y_min - ext * 0.6
                        dim_lines.extend([[x, dim_y, active_val], [next_x, dim_y, active_val]])
                        dim_lines.extend([[x, dim_y-tick, active_val], [x, dim_y+tick, active_val]])
                        dim_lines.extend([[next_x, dim_y-tick, active_val], [next_x, dim_y+tick, active_val]])
                        
                        dim_center = np.array([(x + next_x)/2.0, dim_y - bubble_radius*1.1, active_val])
                        self._add_grid_dimension(dim_center, format_dist(dist), 'z', bubble_radius * 0.8, [1.0, 0.0, 0.0], [0.0, 1.0, 0.0])

            for i, d in enumerate(y_data):
                y = d['ord']
                bub_loc = d.get('bubble', 'End')
                
                if bub_loc in ['End', 'Both']:
                    bubble_lines.extend([[x_max, y, active_val], [x_max + ext, y, active_val]])
                    center = np.array([x_max + ext + bubble_radius, y, active_val])
                    bubble_circ_pos.extend(self._generate_circle_pts(center, bubble_radius, 'z'))
                    self._add_grid_bubble(center, bubble_radius, d['id'], 'z')
                    
                    if i < len(y_data) - 1:
                        next_y = y_data[i+1]['ord']
                        dist = abs(next_y - y)
                        dim_x = x_max + ext * 0.6
                        dim_lines.extend([[dim_x, y, active_val], [dim_x, next_y, active_val]])
                        dim_lines.extend([[dim_x-tick, y, active_val], [dim_x+tick, y, active_val]])
                        dim_lines.extend([[dim_x-tick, next_y, active_val], [dim_x+tick, next_y, active_val]])
                        
                        dim_center = np.array([dim_x + bubble_radius*1.1, (y + next_y)/2.0, active_val])
                        self._add_grid_dimension(dim_center, format_dist(dist), 'z', bubble_radius * 0.8, [0.0, 1.0, 0.0], [-1.0, 0.0, 0.0])

                if bub_loc in ['Start', 'Both']:
                    bubble_lines.extend([[x_min, y, active_val], [x_min - ext, y, active_val]])
                    center = np.array([x_min - ext - bubble_radius, y, active_val])
                    bubble_circ_pos.extend(self._generate_circle_pts(center, bubble_radius, 'z'))
                    self._add_grid_bubble(center, bubble_radius, d['id'], 'z')
                    
                    if i < len(y_data) - 1:
                        next_y = y_data[i+1]['ord']
                        dist = abs(next_y - y)
                        dim_x = x_min - ext * 0.6
                        dim_lines.extend([[dim_x, y, active_val], [dim_x, next_y, active_val]])
                        dim_lines.extend([[dim_x-tick, y, active_val], [dim_x+tick, y, active_val]])
                        dim_lines.extend([[dim_x-tick, next_y, active_val], [dim_x+tick, next_y, active_val]])
                        
                        dim_center = np.array([dim_x - bubble_radius*1.1, (y + next_y)/2.0, active_val])
                        self._add_grid_dimension(dim_center, format_dist(dist), 'z', bubble_radius * 0.8, [0.0, 1.0, 0.0], [-1.0, 0.0, 0.0])

        if graph_paper_pos:
            item = gl.GLLinePlotItem(pos=np.array(graph_paper_pos), mode='lines', color=(0.7, 0.7, 0.7, 0.25), width=1.0, antialias=True)
            self.addItem(item)
            self.static_items.append(item)

        if bright_pos:
            item = gl.GLLinePlotItem(pos=np.array(bright_pos), mode='lines', color=(0.4, 0.4, 0.4, 0.8), width=2, antialias=True)
            self.addItem(item)
            self.static_items.append(item)
            
        if dim_pos:
            alpha = 0.5 if is_3d else 0.15
            item = gl.GLLinePlotItem(pos=np.array(dim_pos), mode='lines', color=(0.6, 0.6, 0.6, alpha), width=1.5, antialias=True)
            self.addItem(item)
            self.static_items.append(item)

        if bubble_lines:
            item = gl.GLLinePlotItem(pos=np.array(bubble_lines), mode='lines', color=(0.3, 0.6, 0.9, 0.9), width=2, antialias=True)
            self.addItem(item)
            self.static_items.append(item)
            
        if dim_lines:
            item = gl.GLLinePlotItem(pos=np.array(dim_lines), mode='lines', color=(0.3, 0.5, 0.7, 0.8), width=1.0, antialias=True)
            self.addItem(item)
            self.static_items.append(item)

        if bubble_circ_pos:
            bub_item = gl.GLLinePlotItem(pos=np.array(bubble_circ_pos), mode='lines', color=(0.3, 0.6, 0.9, 1.0), width=2.0, antialias=True)
            self.addItem(bub_item)
            self.static_items.append(bub_item)

        self._rebuild_axis_items()
        
    def get_snap_point(self, mouse_x, mouse_y):
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

        xs = np.array(x_range, dtype=np.float32)
        ys = np.array(y_range, dtype=np.float32)
        zs = np.array(z_range, dtype=np.float32)
        gx, gy, gz = np.meshgrid(xs, ys, zs, indexing='ij')
        pts_xyz = np.column_stack([gx.ravel(), gy.ravel(), gz.ravel()])          

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
        if dists[idx] < 25.0:
            best_point = tuple(float(v) for v in pts_v[idx])

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
        self.update()
        
    def load_ltha_history(self, npz_path, dt, accel=None):
        """
        Loads the LTHA time history from a .npz file saved by ltha_engine.
        accel can be:
          - None
          - a flat list (legacy single-direction)
          - a dict {"X": [...], "Y": [...], ...} (new multi-direction)
        """
                                                  
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
            data = np.load(npz_path)
            self.ltha_history = {k[5:]: data[k] for k in data.files}
            self.ltha_n_steps = next(iter(self.ltha_history.values())).shape[0]
            self.ltha_dt = dt
            self.ltha_mode = True
            self.invalidate_animation_cache()
            self._ltha_vbo_built = False
            print(f"[Canvas] LTHA history loaded: {self.ltha_n_steps} steps, dt={dt}s, "
                  f"{len(self.ltha_history)} nodes")
        except Exception as e:
            print(f"[Canvas] Failed to load LTHA history: {e}")
            self.ltha_mode = False

    def clear_ltha_history(self):
        """Call when loading a different result or model."""
        self.ltha_history = None
        self.ltha_n_steps = 0
        self.ltha_mode = False
        self.ltha_accel = None
        self.ltha_highlight = None
        self.invalidate_animation_cache()
        self._anim_vbo_built = False
        self._ltha_vbo_built = False

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
            self._build_ltha_vbo()

        self._ltha_pending_t = t
        self._needs_ltha_vbo_update = True
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
                               if self._get_visibility_state(el.node_i.x, el.node_i.y, el.node_i.z) > 0 
                               and self._get_visibility_state(el.node_j.x, el.node_j.y, el.node_j.z) > 0]

        if len(self._ltha_elements) == 0:
            return False
        ("Allocating GPU Vertex Buffer Objects (VBOs) for Time History tensor...")
        self.ltha_engine = VectorizedLTHAEngine(len(self._ltha_elements))

        for i, el in enumerate(self._ltha_elements):
            p1 = np.array([el.node_i.x, el.node_i.y, el.node_i.z], dtype=np.float32)
            p2 = np.array([el.node_j.x, el.node_j.y, el.node_j.z], dtype=np.float32)
            self.ltha_engine.P1[i], self.ltha_engine.P2[i] = p1, p2
            self.ltha_engine.L[i, 0] = max(np.linalg.norm(p2 - p1), 1e-6)
            self.ltha_engine.off_i[i, 0] = getattr(el, 'end_offset_i', 0.0)
            self.ltha_engine.off_j[i, 0] = getattr(el, 'end_offset_j', 0.0)
            self.ltha_engine.R[i] = np.vstack(self._get_consistent_axes(el))
            self.ltha_engine.idx_i[i] = self.ltha_node_map.get(str(el.node_i.id), dummy_idx)
            self.ltha_engine.idx_j[i] = self.ltha_node_map.get(str(el.node_j.id), dummy_idx)
            wire = getattr(el.section, 'color', [0.5, 0.5, 0.5, 1.0])
            self.ltha_engine.colors[i] = wire if len(wire) == 4 else list(wire) + [1.0]

        self._build_ltha_extruded_metadata()
        
        self._clear_static_elements()
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

        U_current = self.ltha_tensor[:, t, :]
        
        verts_flat, colors_flat = self.ltha_engine.compute_extruded(U_current, self.deflection_scale)

        if len(verts_flat) == 0:
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

            v1 = self._get_visibility_state(n1.x, n1.y, n1.z)
            v2 = self._get_visibility_state(n2.x, n2.y, n2.z)
            if v1 == 0 or v2 == 0:
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

                off_i = getattr(el, 'end_offset_i', 0.0)
                off_j = getattr(el, 'end_offset_j', 0.0)

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

            off_i = getattr(el, 'end_offset_i', 0.0)
            off_j = getattr(el, 'end_offset_j', 0.0)
            vec = p2 - p1
            _len = np.linalg.norm(vec)
            p1_flex, p2_flex = p1.copy(), p2.copy()
            if _len > 0.001 and (off_i > 0 or off_j > 0):
                _u = vec / _len
                if off_i + off_j >= _len:
                    _scale = (_len / (off_i + off_j)) * 0.99
                    p1_flex = p1 + (_u * off_i * _scale)
                    p2_flex = p2 - (_u * off_j * _scale)
                else:
                    p1_flex = p1 + (_u * off_i)
                    p2_flex = p2 - (_u * off_j)

                if off_i > 0:
                    p1_flex_def, _, _ = curve_data_full[0]
                    rest_verts.extend([p1, p1_flex])
                    displacements.extend([
                        np.array(res_i[:3]) * self.deflection_scale,
                        p1_flex_def - p1_flex
                    ])
                    colors.extend([np.array([0,0,0,1]), np.array([0,0,0,1])])

                if off_j > 0:
                    p2_flex_def, _, _ = curve_data_full[-1]
                    rest_verts.extend([p2_flex, p2])
                    displacements.extend([
                        p2_flex_def - p2_flex,
                        np.array(res_j[:3]) * self.deflection_scale
                    ])
                    colors.extend([np.array([0,0,0,1]), np.array([0,0,0,1])])

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
        Builds extruded face VBO with rest + peak displacement.
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

        if not rest['ex_vertices'] or not peak['ex_vertices']:
            return False

        rest_verts = np.array(rest['ex_vertices'], dtype=np.float32)
        peak_verts = np.array(peak['ex_vertices'], dtype=np.float32)
        displacements = peak_verts - rest_verts

        colors = np.array(rest['ex_colors'], dtype=np.float32)
        faces  = np.array(rest['ex_faces'],  dtype=np.uint32)

        self.vbo_manager.upload_extruded_geometry(rest_verts, colors, faces, displacements)
        print("[Canvas] Animated extruded VBO built.")

        if rest['ex_edges'] and peak['ex_edges']:
            rest_edges = np.array(rest['ex_edges'], dtype=np.float32)
            peak_edges = np.array(peak['ex_edges'], dtype=np.float32)
            edge_displacements = peak_edges - rest_edges
            edge_colors = np.array(rest['ex_edge_colors'], dtype=np.float32)
            self.vbo_manager.upload_line_geometry(rest_edges, edge_colors, edge_displacements)
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
        
        ex_vertices = []
        ex_faces = []
        ex_colors = []
        ex_edges = []
        ex_edge_colors = []
        center_lines = []
        center_colors = []
        
        opacity = self.display_config.get("extrude_opacity", 0.35)
        show_edges = self.display_config.get("show_edges", False)
        edge_c = np.array(self.display_config.get("edge_color", (0, 0, 0, 1)))
        color_edge_select = np.array([1.0, 1.0, 0.0, 1.0])
        
        for eid, el in model.elements.items():
            n1, n2 = el.node_i, el.node_j
            
            v1 = self._get_visibility_state(n1.x, n1.y, n1.z)
            v2 = self._get_visibility_state(n2.x, n2.y, n2.z)
            
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
                    num_points=11, off_i=getattr(el, 'end_offset_i', 0.0), off_j=getattr(el, 'end_offset_j', 0.0)
                    
                )
                
                self.deflection_cache[cache_key] = {
                    'curve_data': curve_data,
                    'p1_orig': p1.copy(),
                    'p2_orig': p2.copy()
                }
            
            cached = self.deflection_cache[cache_key]
            curve_data_full = cached['curve_data']
            
            off_i = getattr(el, 'end_offset_i', 0.0)
            off_j = getattr(el, 'end_offset_j', 0.0)
            vec = p2 - p1
            _len = np.linalg.norm(vec)
            p1_flex, p2_flex = p1.copy(), p2.copy()
            if _len > 0.001 and (off_i > 0 or off_j > 0):
                _u = vec / _len
                if off_i + off_j >= _len:
                    _scale = (_len / (off_i + off_j)) * 0.99
                    p1_flex = p1 + (_u * off_i * _scale)
                    p2_flex = p2 - (_u * off_j * _scale)
                else:
                    p1_flex = p1 + (_u * off_i)
                    p2_flex = p2 - (_u * off_j)

            if off_i > 0:
                p1_def = p1 + np.array(res_i[:3]) * self.deflection_scale * anim_factor
                p1_flex_def, _, _ = curve_data_full[0]
                p1_flex_anim = p1_flex + (p1_flex_def - p1_flex) * anim_factor
                curved_pos.extend([p1_def, p1_flex_anim])
                curved_colors.extend([np.array([0,0,0,1]), np.array([0,0,0,1])])

            if off_j > 0:
                p2_def = p2 + np.array(res_j[:3]) * self.deflection_scale * anim_factor
                p2_flex_def, _, _ = curve_data_full[-1]
                p2_flex_anim = p2_flex + (p2_flex_def - p2_flex) * anim_factor
                curved_pos.extend([p2_flex_anim, p2_def])
                curved_colors.extend([np.array([0,0,0,1]), np.array([0,0,0,1])])

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
        buttons = event.buttons()
        is_middle_pan = (buttons == Qt.MouseButton.MiddleButton)
        is_tool_pan   = (buttons == Qt.MouseButton.LeftButton and getattr(self, 'single_use_pan_active', False))
        is_rotating   = (buttons == Qt.MouseButton.LeftButton and not self.is_selecting and not getattr(self, 'single_use_pan_active', False))

        self._is_navigating = is_middle_pan or is_tool_pan or is_rotating or self.is_selecting

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

        if getattr(self, 'cross_brace_mode', False):
            self.snap_ring.setVisible(False)
            self.snap_dot.setVisible(False)
            self._update_brace_preview(event.pos().x(), event.pos().y())

        if getattr(self, 'beam_col_mode', False):
            self.snap_ring.setVisible(False)
            self.snap_dot.setVisible(False)
            self._update_beam_col_preview(event.pos().x(), event.pos().y())

        if is_middle_pan or is_tool_pan or is_rotating:
            self._support_rebuild_timer.start(80)

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        pos   = event.position()
        hit   = self._find_zoom_target(pos.x(), pos.y())
        
        self.camera.zoom(delta, pos.x(), pos.y(), self.width(), self.height(), hit_point=hit)
        
        self._support_rebuild_timer.start(60)
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
            
            if self.drag_start:
                drag_dist = (event.pos() - self.drag_start).manhattanLength()
                
                if drag_dist > 5: 
                    self.process_box_selection(self.drag_start, event.pos())
                else:
                    self.pick_single_object(event.pos())
                                                                             
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
        self.process_box_selection(start_centered, end_centered)

    def paintEvent(self, event):
        super().paintEvent(event)
        
        painter = QPainter(self)                                
        
        if self.is_selecting and self.drag_start and self.drag_current:
            x1, y1 = self.drag_start.x(), self.drag_start.y()
            x2, y2 = self.drag_current.x(), self.drag_current.y()
            w_sel = x2 - x1
            h_sel = y2 - y1
            rect = QRect(min(x1, x2), min(y1, y2), abs(w_sel), abs(h_sel))
            
            if w_sel > 0:
                c = QColor(0, 0, 255, 50); border = QColor(0, 0, 255, 200)
            else:
                c = QColor(0, 255, 0, 50); border = QColor(0, 255, 0, 200)
            
            painter.setBrush(c)
            painter.setPen(QPen(border, 1, Qt.PenStyle.SolidLine))
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

        painter.end()

    def _schedule_label_rebuild(self, delay_ms=80):
        """
        Debounced trigger for _rebuild_label_pixmap.
        Safe to call from anywhere (timer callbacks, events, etc.).
        """
        self._label_rebuild_timer.start(delay_ms)
    
    def _is_moving(self):
        return getattr(self, '_mouse_pressed', False)        

    def process_box_selection(self, p_start, p_end):
        if not self.current_model:
            return

        x_min = min(p_start.x(), p_end.x())
        x_max = max(p_start.x(), p_end.x())
        y_min = min(p_start.y(), p_end.y())
        y_max = max(p_start.y(), p_end.y())

        is_window_select = (p_end.x() > p_start.x())

        w = self.width()
        h = self.height()

        full_area = (0, 0, w, h)
        m_view = self.viewMatrix()
        m_proj = self.projectionMatrix(region=full_area, viewport=full_area)
        mvp = np.array((m_proj * m_view).data()).reshape(4, 4).T

        can_deflect = (
            self.view_deflected
            and hasattr(self.current_model, 'has_results')
            and self.current_model.has_results
            and self.current_model.results is not None
        )

        model = self.current_model

        node_items = list(model.nodes.items())
        found_nodes = []
        node_screens = {}

        if node_items:
            all_nids   = [nid for nid, _ in node_items]
            all_nodes  = [n   for _, n  in node_items]

            vis_mask  = [self._get_visibility_state(n.x, n.y, n.z) == 2 for n in all_nodes]
            vis_nids  = [all_nids[i]  for i, v in enumerate(vis_mask) if v]
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

                N     = len(positions)
                pos_h = np.hstack([positions, np.ones((N, 1))])          
                clip  = pos_h @ mvp.T                                    

                w_clip       = clip[:, 3]
                screen_valid = w_clip > 0
                safe_w       = np.where(screen_valid, w_clip, 1.0)

                sx = (clip[:, 0] / safe_w * 0.5 + 0.5) * w
                sy = (1.0 - (clip[:, 1] / safe_w * 0.5 + 0.5)) * h

                in_box = (screen_valid
                        & (sx >= x_min) & (sx <= x_max)
                        & (sy >= y_min) & (sy <= y_max))

                for i, nid in enumerate(vis_nids):
                    if screen_valid[i]:
                        node_screens[nid] = (float(sx[i]), float(sy[i]))
                        if in_box[i]:
                            found_nodes.append(nid)

        found_elems = []
        e_ids, p1s, p2s = [], [], []

        for eid, el in model.elements.items():
            p1 = node_screens.get(el.node_i.id)
            p2 = node_screens.get(el.node_j.id)
            if p1 is None or p2 is None:
                continue
            e_ids.append(eid)
            p1s.append(p1)
            p2s.append(p2)

        if e_ids:
            if is_window_select:
                p1_arr = np.array(p1s)
                p2_arr = np.array(p2s)
                p1_in  = ((p1_arr[:, 0] >= x_min) & (p1_arr[:, 0] <= x_max) &
                        (p1_arr[:, 1] >= y_min) & (p1_arr[:, 1] <= y_max))
                p2_in  = ((p2_arr[:, 0] >= x_min) & (p2_arr[:, 0] <= x_max) &
                        (p2_arr[:, 1] >= y_min) & (p2_arr[:, 1] <= y_max))
                found_elems = [e_ids[i] for i in np.where(p1_in & p2_in)[0]]
            else:
                rect = (x_min, y_min, x_max, y_max)
                found_elems = [
                    e_ids[i] for i in range(len(e_ids))
                    if self._line_intersects_rect(p1s[i], p2s[i], rect)
                ]

        found_links = []
        l_ids, lp1s, lp2s = [], [], []

        if hasattr(model, 'links'):
            for lid, link in model.links.items():
                nodes = link['nodes']
                if len(nodes) == 1:
                    n0 = nodes[0]
                                                                          
                    real_node = model.nodes.get(n0) or model.nodes.get(int(n0)) or model.nodes.get(str(n0))
                    
                    if real_node:
                                                   
                        if hasattr(self, 'cache_scale_used') and self.cache_scale_used is not None:
                            scale = self.cache_scale_used
                        else:
                            bounds = getattr(self, 'compute_model_bbox', lambda: None)()
                            if bounds and len(bounds) >= 2:
                                                                        
                                scale = bounds[1] * 0.05
                            else:
                                scale = 1.0

                        ground_z = real_node.z - scale * 6.0 * 2.2
                        
                        s = self._project_to_screen(real_node.x, real_node.y, ground_z, mvp, w, h)
                        
                        if s and (x_min <= s[0] <= x_max) and (y_min <= s[1] <= y_max):
                            found_links.append(lid)

                elif len(nodes) == 2:
                    n0, n1 = nodes[0], nodes[1]
                    p1 = node_screens.get(n0) or node_screens.get(int(n0)) or node_screens.get(str(n0))
                    p2 = node_screens.get(n1) or node_screens.get(int(n1)) or node_screens.get(str(n1))
                    if p1 is None or p2 is None: continue
                    l_ids.append(lid)
                    lp1s.append(p1)
                    lp2s.append(p2)

            if l_ids:
                if is_window_select:
                    p1_arr = np.array(lp1s); p2_arr = np.array(lp2s)
                    p1_in = ((p1_arr[:, 0] >= x_min) & (p1_arr[:, 0] <= x_max) & (p1_arr[:, 1] >= y_min) & (p1_arr[:, 1] <= y_max))
                    p2_in = ((p2_arr[:, 0] >= x_min) & (p2_arr[:, 0] <= x_max) & (p2_arr[:, 1] >= y_min) & (p2_arr[:, 1] <= y_max))
                    found_links.extend([l_ids[i] for i in np.where(p1_in & p2_in)[0]])
                else:
                    rect = (x_min, y_min, x_max, y_max)
                    found_links.extend([l_ids[i] for i in range(len(l_ids)) if self._line_intersects_rect(lp1s[i], lp2s[i], rect)])   
        found_area_elems = []
        for aeid, ae in model.area_elements.items():
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

            if is_window_select:
                if all(x_min <= p[0] <= x_max and y_min <= p[1] <= y_max
                    for p in corner_screens):
                    found_area_elems.append(aeid)
            else:
                cx_pick = (x_min + x_max) / 2.0
                cy_pick = (y_min + y_max) / 2.0
                if self._point_in_polygon_2d(cx_pick, cy_pick, corner_screens):
                    found_area_elems.append(aeid)
                else:
                    rect  = (x_min, y_min, x_max, y_max)
                    n_pts = len(corner_screens)
                    for i in range(n_pts):
                        if self._line_intersects_rect(
                            corner_screens[i], corner_screens[(i + 1) % n_pts], rect
                        ):
                            found_area_elems.append(aeid)
                            break

        modifiers   = QApplication.keyboardModifiers()
        is_additive = (modifiers == Qt.KeyboardModifier.ControlModifier)
        is_deselect = (modifiers == Qt.KeyboardModifier.ShiftModifier)
        self.signal_box_selection.emit(found_nodes, found_elems, found_links, is_additive, is_deselect)
        self.signal_area_box_selection.emit(found_area_elems, is_additive, is_deselect)

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
        """Find closest node or element midpoint to mouse in screen space (Vectorized)."""
        if not self.current_model or not self.current_model.nodes:
            return None
            
        view_w = self.width()
        view_h = self.height()
        full_area = (0, 0, view_w, view_h)
        mvp_matrix = np.array(
            (self.projectionMatrix(region=full_area, viewport=full_area) * 
            self.viewMatrix()).data()
        ).reshape(4, 4).T

        can_deflect = getattr(self, 'view_deflected', False) and\
                      hasattr(self.current_model, 'has_results') and\
                      self.current_model.has_results and\
                      self.current_model.results is not None
                      
        scale = getattr(self, 'deflection_scale', 1.0) * getattr(self, 'anim_factor', 1.0)
        
        node_coords = []
        node_disps = {}                                                          
        
        for nid, n in self.current_model.nodes.items():
            dx, dy, dz = 0.0, 0.0, 0.0
            if can_deflect:
                disp = self.current_model.results.get("displacements", {}).get(str(nid))
                if disp:
                    dx, dy, dz = disp[0]*scale, disp[1]*scale, disp[2]*scale
                    node_disps[nid] = (dx, dy, dz)
                    
            node_coords.append([n.x + dx, n.y + dy, n.z + dz, 1.0])
            
        elem_coords = []
        for el in self.current_model.elements.values():
            n1, n2 = el.node_i, el.node_j
            d1 = node_disps.get(n1.id, (0.0, 0.0, 0.0))
            d2 = node_disps.get(n2.id, (0.0, 0.0, 0.0))
            
            mx = (n1.x + d1[0] + n2.x + d2[0]) * 0.5
            my = (n1.y + d1[1] + n2.y + d2[1]) * 0.5
            mz = (n1.z + d1[2] + n2.z + d2[2]) * 0.5
            elem_coords.append([mx, my, mz, 1.0])
            
        node_coords = np.array(node_coords) if node_coords else np.empty((0, 4))
        elem_coords = np.array(elem_coords) if elem_coords else np.empty((0, 4))
        all_coords = np.vstack([node_coords, elem_coords]) if len(elem_coords) > 0 else node_coords

        clip = all_coords @ mvp_matrix.T
        
        valid_mask = clip[:, 3] > 0
        if not np.any(valid_mask): 
            return None
            
        clip_valid = clip[valid_mask]
        coords_valid = all_coords[valid_mask]
        
        ndc_x = clip_valid[:, 0] / clip_valid[:, 3]
        ndc_y = clip_valid[:, 1] / clip_valid[:, 3]
        
        sx = (ndc_x + 1.0) * view_w / 2.0
        sy = (1.0 - ndc_y) * view_h / 2.0
        
        dist_sq = (sx - mouse_x)**2 + (sy - mouse_y)**2
        
        min_idx = np.argmin(dist_sq)
        
        if dist_sq[min_idx] < screen_radius**2:
            best_pt = coords_valid[min_idx]
            return QVector3D(best_pt[0], best_pt[1], best_pt[2])
            
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

    def _draw_member_loads(self, model):
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
        
        sel_verts = []; sel_colors = []; sel_faces = []
        sel_idx_counter = 0
        sel_lines = []; sel_line_colors = []

        ghost_verts = []; ghost_colors = []; ghost_faces = []
        ghost_idx_counter = 0
        ghost_lines = []; ghost_line_colors = []

        loads_by_beam = {}
        for ld in model.loads:
            if hasattr(ld, 'element_id'):
                                                  
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
            
            v1 = self._get_visibility_state(el.node_i.x, el.node_i.y, el.node_i.z)
            v2 = self._get_visibility_state(el.node_j.x, el.node_j.y, el.node_j.z)
            if v1 == 0 or v2 == 0: continue
            
            is_ghosted = (v1 != 2 or v2 != 2)
            is_selected = (el.id in self.selected_element_ids)

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

                base_rgb = (0.0, 0.0, 0.0)

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
        """Draws RGB arrows at the center of each element representing local axes."""
        if not model.elements: return
        
        lines = []
        colors = []
        
        L = 0.5                                          
        
        for el in model.elements.values():
            n1, n2 = el.node_i, el.node_j
            
            if not (self._is_visible(n1.x, n1.y, n1.z) and self._is_visible(n2.x, n2.y, n2.z)):
                continue

            p1 = np.array([n1.x, n1.y, n1.z])
            p2 = np.array([n2.x, n2.y, n2.z])
            mid = (p1 + p2) / 2.0
            
            v1, v2, v3 = self._get_consistent_axes(el)
            
            lines.append(mid); lines.append(mid + v1 * L)
            colors.append((1, 0, 0, 1)); colors.append((1, 0, 0, 1))
            
            lines.append(mid); lines.append(mid + v2 * L)
            colors.append((0, 1, 0, 1)); colors.append((0, 1, 0, 1))
            
            lines.append(mid); lines.append(mid + v3 * L)
            colors.append((0, 0, 1, 1)); colors.append((0, 0, 1, 1))
            
        if lines:
            self.addItem(gl.GLLinePlotItem(
                pos=np.array(lines), 
                color=np.array(colors), 
                mode='lines', 
                width=2.0, 
                antialias=True
            ))

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
                                                                                                       
            master_pos.append(c_pt)
            
            for n in nodes:
                                                                                        
                if self._is_visible(n.x, n.y, n.z):
                    conn_lines.append(c_pt)
                    conn_lines.append([n.x, n.y, n.z])

        if conn_lines:
            self.addItem(gl.GLLinePlotItem(
                pos=np.array(conn_lines),
                color=(0, 1, 0, 0.85),                             
                mode='lines',
                width=0.7,                                  
                antialias=True
            ))

        if master_pos:
            master_item = gl.GLScatterPlotItem(
                pos=np.array(master_pos), 
                size=5,                                                      
                color=(1.0, 0.85, 0.0, 1.0),                     
                pxMode=True                                                            
            )
                                                                                          
            master_item.setGLOptions('translucent')
            self.addItem(master_item)

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
 
    def _draw_area_loads(self, model):
        """
        Visualizes AreaUniformLoad and AreaGravityLoad over shell faces.
 
        Visual language
        ---------------
        Ghosted (other plane) : skipped entirely — no clutter
        Unselected            : faint arrows at 3 points, no fill
        Selected              : full-color arrows at 5 points
                                + tinted fill overlay
                                + floating label
 
        Colors
        ------
        AreaUniformLoad  → blue   (pressure / force-per-area)
        AreaGravityLoad  → orange (gravity multiplier ×g)
        """
        if not model.loads:
            return
        if not self.show_loads:
            return
        if self.load_type_filter == "nodal":
            return
 
        COLOR_UNIFORM = (0.0, 0.0, 0.0)                                         
        COLOR_GRAVITY = (0.0, 0.0, 0.0) 
 
        for load in model.loads:
                                     
            if not hasattr(load, 'area_id'):
                continue
            if (self.visible_load_patterns
                    and load.pattern_name not in self.visible_load_patterns):
                continue
 
            ae = model.area_elements.get(load.area_id)
            if ae is None or len(ae.nodes) < 3:
                continue
 
            states = [self._get_visibility_state(n.x, n.y, n.z) for n in ae.nodes]
            if min(states) == 0:
                continue                             
 
            is_ghosted  = (min(states) < 2)
            is_selected = (ae.id in self.selected_area_ids)
 
            if is_ghosted:
                continue
 
            pts      = np.array([[n.x, n.y, n.z] for n in ae.nodes], dtype=np.float64)
            centroid = pts.mean(axis=0)
 
            v1    = pts[1] - pts[0]
            v2    = pts[2] - pts[0]
            raw_n = np.cross(v1, v2)
            n_len = np.linalg.norm(raw_n)
            if n_len < 1e-9:
                continue
            shell_normal = raw_n / n_len
 
            shell_size = float(np.max(np.linalg.norm(pts - centroid, axis=1)))
 
            arrows_spec = []
 
            if hasattr(load, 'uniform_load'):                                
                val = load.uniform_load
                if abs(val) < 1e-9:
                    continue
                base_rgb = COLOR_UNIFORM
                sign     = 1.0 if val > 0 else -1.0
 
                d = load.load_direction
                if   d == 'Gravity':  dir_vec = np.array([0., 0., -1.])
                elif d == 'Local 1':  dir_vec = shell_normal.copy()
                elif d == 'Local 2':
                    lv2   = np.cross(shell_normal, v1 / (np.linalg.norm(v1) + 1e-12))
                    lv2_n = np.linalg.norm(lv2)
                    dir_vec = (lv2 / lv2_n) if lv2_n > 1e-9 else np.array([1., 0., 0.])
                elif d == 'Local 3':
                    v1_n    = np.linalg.norm(v1)
                    dir_vec = v1 / v1_n if v1_n > 1e-9 else np.array([1., 0., 0.])
                elif d == 'Global X': dir_vec = np.array([1., 0., 0.])
                elif d == 'Global Y': dir_vec = np.array([0., 1., 0.])
                elif d == 'Global Z': dir_vec = np.array([0., 0., 1.])
                else:                  dir_vec = np.array([0., 0., -1.])
 
                arrows_spec.append((sign * dir_vec, abs(val), base_rgb))
 
            elif hasattr(load, 'gx'):                                         
                base_rgb = COLOR_GRAVITY
                for gval, gdir in [
                    (load.gx, np.array([1., 0., 0.])),
                    (load.gy, np.array([0., 1., 0.])),
                    (load.gz, np.array([0., 0., 1.])),
                ]:
                    if abs(gval) < 1e-9:
                        continue
                    arrows_spec.append(
                        ((1. if gval > 0 else -1.) * gdir, abs(gval), base_rgb)
                    )
 
            if not arrows_spec:
                continue
 
            for (dir_vec, magnitude, base_rgb) in arrows_spec:
 
                log_s      = min(2.0, 0.4 + np.log10(max(1.0, magnitude)) * 0.2)
                arrow_len  = max(log_s * shell_size * 0.45, shell_size * 0.18)
 
                if not is_selected:
                    c_fill     = (*base_rgb, 0.0)                                   
                    c_line     = (*base_rgb, 0.35)                 
                    do_fill    = False
                    do_label   = False
                    n_samples  = 3                                         
                else:
                    c_fill     = (*base_rgb, 0.22)                   
                    c_line     = (*base_rgb, 1.00)                
                    do_fill    = True
                    do_label   = True
                    n_samples  = 5                                         
 
                if do_fill:
                    tris   = self._fan_triangulate(pts)
                    base_v = len(self._pending_load_fill_verts)
                    for tri in tris:
                        for pt in tri:
                            self._pending_load_fill_verts.append(pt.tolist())
                            self._pending_load_fill_colors.append(c_fill)
                    for i in range(len(tris)):
                        b = base_v + i * 3
                        self._pending_load_fill_faces.append([b, b + 1, b + 2])
 
                head_len = arrow_len * 0.28
 
                perp_seed = (np.array([1., 0., 0.])
                             if abs(dir_vec[2]) > 0.8 else np.array([0., 0., 1.]))
                side_raw  = np.cross(dir_vec, perp_seed)
                side_n    = np.linalg.norm(side_raw)
                side_vec  = ((side_raw / side_n) * head_len * 0.4
                             if side_n > 1e-9 else np.zeros(3))
 
                is_ext = getattr(self, 'view_extruded', False)
                t = getattr(ae.section, 'membrane_thickness', getattr(ae.section, 'thickness', 0.2)) if is_ext else 0.0
                
                offset_mag = (t / 2.0) + (shell_size * 0.005)
                surface_offset = shell_normal * offset_mag
                
                if np.dot(dir_vec, shell_normal) > 0:
                    surface_offset = -surface_offset

                sample_pts = self._area_load_sample_points(pts, centroid, n_samples)
 
                for sp in sample_pts:
                    tip  = np.array(sp) + surface_offset
                    tail = tip - dir_vec * arrow_len                               
 
                    self._pending_load_line_pos.extend([tail.tolist(), tip.tolist()])
                    self._pending_load_line_colors.extend([c_line, c_line])
 
                    if is_selected:
                                         
                        base_pt = tip - dir_vec * head_len
                        self._pending_load_line_pos.extend([
                            tip.tolist(), (base_pt + side_vec).tolist(),
                            tip.tolist(), (base_pt - side_vec).tolist(),
                        ])
                        self._pending_load_line_colors.extend([c_line] * 4)
 
                if do_label:
                    if hasattr(load, 'uniform_load'):
                        q_scale     = unit_registry.force_scale / (unit_registry.length_scale ** 2)
                        display_val = magnitude * q_scale
                        unit_str    = (f"{unit_registry.force_unit_name}/"
                                       f"{unit_registry.length_unit_name}\u00b2")
                    else:                                                         
                        display_val = magnitude
                        unit_str    = "\u00d7g"                   
 
                    label_pos = centroid + surface_offset - dir_vec * (arrow_len * 1.30)
 
                    v_up    = np.array([0., 0., 1.])
                    v_right = np.cross(v_up, dir_vec)
                    vr_n    = np.linalg.norm(v_right)
                    if vr_n < 0.1:                                                
                        v_right = np.array([1., 0., 0.])
                    else:
                        v_right = v_right / vr_n
 
                    self.load_labels.append({
                        'owner_id':    ae.id,
                        'owner_type':  'area',
                        'pos_3d':      label_pos.tolist(),
                        'text':        f"{display_val:.2f} {unit_str}",
                        'val':         magnitude,
                        'color':       list(base_rgb) + [1.0],
                        'v_right':     v_right.tolist(),
                        'v_up':        v_up.tolist(),
                        'align':       'center',
                        'text_height': 0.22,
                    })

    def _draw_member_point_loads(self, model):
        """
        Visualizes Member Point Loads.
        - Always: Draws Arrow geometry (Force or Moment).
        - Selected: Draws Text Label with Units.
        """
        if not model.loads: return
        if not self.show_loads: return
        if self.load_type_filter == "nodal": return 

        arrow_lines = []
        arrow_colors = []
        
        L = 2.0; H = 0.5; W = 0.2

        for load in model.loads:

            if not hasattr(load, 'force'): continue 
            if self.visible_load_patterns and load.pattern_name not in self.visible_load_patterns: continue

            el = model.elements.get(load.element_id)
            if not el: continue
            
            v1 = self._get_visibility_state(el.node_i.x, el.node_i.y, el.node_i.z)
            v2 = self._get_visibility_state(el.node_j.x, el.node_j.y, el.node_j.z)
            if v1 == 0 or v2 == 0: continue
            is_ghosted = (v1 != 2 or v2 != 2)

            is_selected = (el.id in self.selected_element_ids)

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
            
            c = (0, 0, 0, 0.15) if is_ghosted else (0, 0, 0, 1)

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

            add_head(tip)
            if is_moment:
                add_head(tip - (draw_dir * (H * 0.8)))

            if not is_ghosted and is_selected:
                self._add_load_label(load_pos, draw_dir, val, "Moment" if is_moment else "Force", c, owner_id=el.id, owner_type='element')

        if arrow_lines:
            self._pending_load_line_pos.extend(arrow_lines)
            self._pending_load_line_colors.extend(arrow_colors)

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

        top_items = getattr(self, '_sel_overlay_items', []) + [
            self.preview_line, self._beam_col_prev_line, 
            self._brace_prev_x1, self._brace_prev_x2, 
            self._brace_prev_border, self.snap_ring, self.snap_dot,
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
        glViewport(0, 0, int(self.deviceWidth()), int(self.deviceHeight()))
        bgcolor = self.opts.get('bgcolor', (0.0, 0.0, 0.0, 1.0))
        glClearColor(*bgcolor)
        glClear(GL_DEPTH_BUFFER_BIT | GL_COLOR_BUFFER_BIT)
        w, h = self.deviceWidth(), self.deviceHeight()
        region = (0, 0, w, h)
        self.setProjection(region=region, viewport=region)
        self.setModelview()

        _skip = {self.force_mesh_item, self.force_line_item}
        for item in self.items:
            if item not in _skip and item.visible():
                try:
                    item.paint()
                except Exception:
                    pass

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

            if getattr(self, '_needs_anim_vbo_build', False):
                self._needs_anim_vbo_build = False
                if not getattr(self, '_anim_vbo_built', False):
                    self._anim_vbo_built = True
    
                if self.view_extruded:
                    self._build_animated_extruded_vbo()
                else:
                    self._build_animated_line_vbo()
                self._clear_static_elements()
                
            if getattr(self, '_needs_ltha_vbo_update', False):
                self._needs_ltha_vbo_update = False
                t = getattr(self, '_ltha_pending_t', 0)
                self.vbo_manager.set_anim_factor(1.0)

                if self.view_extruded:
                    self._build_ltha_extruded_frame(t)
                else:
                    self._build_ltha_line_frame(t)

            if self.view_extruded:
                edge_w = float(self.display_config.get("edge_width", 1.5))
                edge_alpha = float(self.display_config.get("edge_opacity", 0.08))

                is_anim = self.animation_manager.is_running and self.view_deflected
                if is_anim:
                    self.vbo_manager.draw(m_view, m_proj)
                    self.vbo_manager.draw_lines(m_view, m_proj, line_width=edge_w, alpha_mult=1.0, write_depth=True)
                else:
                    self.vbo_manager.draw_lines(m_view, m_proj, line_width=edge_w, alpha_mult=edge_alpha, write_depth=False)
                    self.vbo_manager.draw(m_view, m_proj)
                    self.vbo_manager.draw_lines(m_view, m_proj, line_width=edge_w, alpha_mult=1.0, write_depth=True)
            else:
                line_w = float(self.display_config.get("line_width", 2.0))
                self.vbo_manager.draw_lines(m_view, m_proj, line_width=line_w, alpha_mult=1.0, write_depth=True)

            if getattr(self, 'show_slabs', True):
                edge_w = float(self.display_config.get("edge_width", 1.5))
                
                if getattr(self, '_is_navigating', False):
                    self.vbo_manager.draw_areas(m_view, m_proj)
                else:
                    self.vbo_manager.draw_area_depth_prepass(m_view, m_proj)
                    self.vbo_manager.draw_area_edges(m_view, m_proj, line_width=edge_w, alpha_mult=1.0, write_depth=True)
                    self.vbo_manager.draw_areas(m_view, m_proj)

            glClear(GL_DEPTH_BUFFER_BIT)

            if getattr(self, '_pending_force_upload', None) is not None:
                d = self._pending_force_upload
                self.vbo_manager.upload_force_geometry(
                    d['fill_verts'], d['fill_colors'], d['fill_faces'],
                    d['line_pos'],   d['line_colors'],
                )
                self._pending_force_upload = None

            self.vbo_manager.draw_force_geometry(m_view, m_proj)
            self.vbo_manager.draw_load_geometry(m_view, m_proj)

            if hasattr(self.vbo_manager, 'font_texture_id'):
                self.vbo_manager.draw_text(m_view, m_proj, self.vbo_manager.font_texture_id)
                
            glEnable(GL_DEPTH_TEST)
            glDepthMask(GL_TRUE)
            glDepthFunc(GL_LESS)
            
        glClear(GL_DEPTH_BUFFER_BIT)
        
        for item, was_visible in zip(top_items, vis_states):
            item.setVisible(was_visible)                                        
            if was_visible:
                try:
                    item.paint()                                   
                except Exception:
                    pass

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
        min_dist = 15.0

        for nid, s_pos in node_screens.items():
            dist = ((s_pos[0] - px)**2 + (s_pos[1] - py)**2)**0.5
            if dist < min_dist:
                min_dist = dist
                hovered_node = nid

        if hovered_node is None:
            min_dist_edge = 10.0
            for eid, el in self.current_model.elements.items():

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

        if hovered_node is None and hovered_elem is None and self.current_model.area_elements:
            for aeid, ae in self.current_model.area_elements.items():
                                                                                
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
                        self.current_hover_data is None)
        new_nothing  = (hovered_node is None and
                        hovered_elem is None and
                        new_hover_data is None)

        self.current_hover_data = new_hover_data
        self.hovered_node_id    = hovered_node
        self.hovered_elem_id    = hovered_elem

        prev_hov_area = getattr(self, 'hovered_area_id', None)
        self.hovered_area_id  = hovered_area
        if hovered_area != prev_hov_area:
            self._rebuild_area_interior_lines()

        if not (prev_nothing and new_nothing):
            self.update()

    def _build_ltha_extruded_metadata(self):
        """Builds initial topology and vertex mappings for the GPU Extruded Tensor."""
        from core.properties import RectangularSection, CircularSection, TrapezoidalSection
        
        ex_faces, ex_colors, ex_edges, ex_edge_colors = [], [], [], []
        map_E, map_P, map_off, map_Y, map_Z = [], [], [], [], []
        
        opacity = self.display_config.get("extrude_opacity", 0.35)
        show_edges = self.display_config.get("show_edges", False)
        edge_c = np.array(self.display_config.get("edge_color", (0, 0, 0, 1)))
        
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

        self.vbo_manager.upload_extruded_geometry(verts_flat.reshape(-1, 3), colors_flat.reshape(-1, 4), faces_flat.reshape(-1, 3))
        
        if show_edges and ex_edges:
            edge_verts_flat = verts_flat.reshape(-1, 3)[self.ltha_engine.edge_indices].flatten()
            self.vbo_manager.upload_line_geometry(edge_verts_flat.reshape(-1, 3), self.ltha_engine.edge_colors_flat.reshape(-1, 4))

    def _upload_loads_to_vbo(self):
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

        fv = np.array(fill_verts,  dtype=np.float32) if fill_verts  else np.zeros((0, 3), dtype=np.float32)
        fc = np.array(fill_colors, dtype=np.float32) if fill_colors else np.zeros((0, 4), dtype=np.float32)
        ff = np.array(fill_faces,  dtype=np.uint32)  if fill_faces  else np.zeros((0, 3), dtype=np.uint32)
        lp = np.array(line_pos,    dtype=np.float32) if line_pos    else np.zeros((0, 3), dtype=np.float32)
        lc = np.array(line_colors, dtype=np.float32) if line_colors else np.zeros((0, 4), dtype=np.float32)

        self.vbo_manager.upload_load_geometry(fv, fc, ff, lp, lc)

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
        if not hasattr(self, 'text_builder') or not hasattr(self, 'vbo_manager'):
            return
            
        self.makeCurrent()
        
        all_labels = getattr(self, 'load_labels', []) +\
                     getattr(self, 'force_labels', []) +\
                     getattr(self, 'grid_labels', [])
        
        if all_labels:
            verts, uvs, colors, indices = self.text_builder.build_text_geometry(all_labels, default_text_height=0.25)
            self.vbo_manager.upload_text_geometry(verts, uvs, colors, indices)
        else:
            self.vbo_manager.upload_text_geometry(np.array([]), np.array([]), np.array([]), np.array([]))
