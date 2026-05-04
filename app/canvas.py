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

class MCanvas3D(gl.GLViewWidget):
    signal_canvas_clicked = pyqtSignal(float, float, float)
    signal_right_clicked = pyqtSignal()
    signal_box_selection = pyqtSignal(list, list, bool, bool)
    signal_element_selected = pyqtSignal(int)
    signal_mouse_moved = pyqtSignal(float, float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)

        self.display_config = {
            "node_size": 6,
            "node_color": (1, 1, 0, 1),
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

        self.current_model = None
        self.selected_element_ids = [] 
        self.selected_node_ids = [] 
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

        self.active_view_plane = None 

        self.linked_plane_item = None
        self.linked_plane_outline = None

        self.drag_start = None
        self.drag_current = None
        self.is_selecting = False
        self._is_navigating = False

        self.blink_state = True

        self.vbo_manager = VBORenderManager()
                                    
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

    def initializeGL(self):
        super().initializeGL()
        self.vbo_manager.init_gl()    

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

    def draw_model(self, model, sel_elems=None, sel_nodes=None):
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
        
        self._force_draw_model(model, sel_elems, sel_nodes)
    
    def _force_draw_model(self, model, sel_elems=None, sel_nodes=None):
        """
        Force redraw the model even if animation is running.
        Used internally by draw_model when animation is stopped.
        """
        self.current_model = model
        if sel_elems is not None: self.selected_element_ids = sel_elems
        if sel_nodes is not None: self.selected_node_ids = sel_nodes
        self.load_labels = []

        self.node_items.clear()
        self._support_items.clear()                                                                
        self._support_positions = {'fixed': [], 'pinned': [], 'roller': [], 'custom': []}
        self.element_items.clear()     
        self.element_items.clear()

        if hasattr(self, 'load_items'): self.load_items.clear()

        self.invalidate_deflection_cache()

        for item in self.items[:]:
            self.removeItem(item)

        if not self.view_deflected:
            self._draw_reference_grids(model)

        if self.show_joints or self.show_supports:
            self._draw_nodes(model)
        
        in_analysis_mode = hasattr(model, 'has_results') and model.has_results
        
        if self.show_constraints and not in_analysis_mode:  
            self._draw_constraints(model)
                                                  
        if self.view_extruded:
            self._draw_elements_extruded(model)
        else:
                              
            self._draw_elements_wireframe(model) 

        in_analysis_mode = hasattr(model, 'has_results') and model.has_results
        
        if self.show_loads and not in_analysis_mode:
            self._draw_loads(model)
            self._draw_member_loads(model)
            self._draw_member_point_loads(model)

        if self.show_slabs:
            self._draw_slabs(model)

        if self.show_local_axes:
            self._draw_local_axes(model)

        if self.snap_ring not in self.items: self.addItem(self.snap_ring)
        if self.snap_dot not in self.items: self.addItem(self.snap_dot)
        if self.preview_line not in self.items: self.addItem(self.preview_line)
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

    def update_selection_overlay(self, sel_elems, sel_nodes):
        """Fast-path selection update. Skips full geometry rebuild."""
        self.selected_element_ids = list(sel_elems) if sel_elems is not None else []
        self.selected_node_ids = list(sel_nodes) if sel_nodes is not None else []
        
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

        if self.current_model:
            self._rebuild_selection_overlay()
            
            in_analysis_mode = hasattr(self.current_model, 'has_results') and self.current_model.has_results
            if self.show_loads and not in_analysis_mode:
                self._draw_loads(self.current_model)
                self._draw_member_loads(self.current_model)
                self._draw_member_point_loads(self.current_model)

    def _rebuild_selection_overlay(self):
        """Dispatches to wireframe or extruded overlay builder, then nodes."""
        if self.view_extruded:
            self._rebuild_extruded_selection_overlay()
        else:
            self._rebuild_wireframe_selection_overlay()
        self._rebuild_node_selection_overlay()

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
                
                res_i = model.results.get("displacements", {}).get(str(n1.id))
                res_j = model.results.get("displacements", {}).get(str(n2.id))
                
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
                                                                      
                    curve_pts = []
                    for k in range(len(curve_data_full)):
                        pos_full, _, _ = curve_data_full[k]
                        s = k / (len(curve_data_full) - 1) if len(curve_data_full) > 1 else 0.0
                        pos_orig = p1_orig + s * (p2_orig - p1_orig)
                        curve_pts.append(pos_orig + (pos_full - pos_orig) * self.anim_factor)
                                                                                         
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
                res_i = model.results.get("displacements", {}).get(str(n1.id))
                res_j = model.results.get("displacements", {}).get(str(n2.id))

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

                    curve_pts = []
                    for k in range(len(curve_data_full)):
                        pos_full, _, _ = curve_data_full[k]
                        s = k / (len(curve_data_full) - 1) if len(curve_data_full) > 1 else 0.0
                        pos_orig = p1_orig + s * (p2_orig - p1_orig)
                        curve_pts.append(pos_orig + (pos_full - pos_orig) * self.anim_factor)

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
                pos=np.array(sel_pos), size=size + 2,
                color=(1, 0, 0, 1), pxMode=True
            )
                                                                                       
            sp.setGLOptions({
                'glEnable': (GL_BLEND,),
                'glBlendFunc': (GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA),
                'glDisable': (GL_DEPTH_TEST,)
            })
            self.addItem(sp)
            self._sel_overlay_items.append(sp)

    def _draw_nodes(self, model):
        if not model.nodes: return
        
        pos_free = []
        ghost_pos = []
        supports_fixed = []; supports_pinned = []; supports_roller = []; supports_custom = []

        size = self.display_config.get("node_size", 6)
        color_tuple = self.display_config.get("node_color", (1, 1, 0, 1))
        
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
                if v_state == 1:                                
                    ghost_pos.append(xyz)
                continue                                      

            is_active = self._is_visible(n.x, n.y, n.z)
            if not is_active:
                ghost_pos.append(xyz)
                continue
            
            r = n.restraints
            is_fixed = all(r[:3]) and all(r[3:]) 
            is_pinned = all(r[:3]) and not any(r[3:]) 
            is_roller = r[2] and not any(r[0:2]) and not any(r[3:])                  
            has_any = any(r)

            in_analysis_mode = hasattr(model, 'has_results') and model.has_results
            if has_any and self.show_supports and not in_analysis_mode:
                if is_fixed: supports_fixed.append(xyz)
                elif is_pinned: supports_pinned.append(xyz)
                elif is_roller: supports_roller.append(xyz)
                else: supports_custom.append(xyz)
            elif self.show_joints:
                pos_free.append(xyz)

        if pos_free: 
            item = gl.GLScatterPlotItem(
                pos=np.array(pos_free), 
                size=size,                           
                color=color_tuple,                   
                pxMode=True)
            self.addItem(item)
            self.node_items.append(item)

        if supports_fixed:  self._support_positions['fixed']  = supports_fixed;  self._draw_support_meshes(supports_fixed,  'fixed')
        if supports_pinned: self._support_positions['pinned'] = supports_pinned; self._draw_support_meshes(supports_pinned, 'pinned')
        if supports_roller: self._support_positions['roller'] = supports_roller; self._draw_support_meshes(supports_roller, 'roller')
        if supports_custom: self._support_positions['custom'] = supports_custom; self._draw_support_meshes(supports_custom, 'custom')
        
        if ghost_pos and self.show_joints:
            item = gl.GLScatterPlotItem(
                pos=np.array(ghost_pos), size=4, color=(0.7, 0.7, 0.7, 0.4), pxMode=True
            )
            self.addItem(item)
            self.node_items.append(item)

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
        if not model.elements: return

        flex_pos = []; flex_colors = []
        rigid_pos = []; rigid_colors = []
        rigid_black = (0, 0, 0, 1)
        
        curved_pos = []; curved_colors = []
        
        release_dots = []

        ghost_pos = []
        def_color = np.array([0.5, 0.5, 0.5, 1.0]) 
        width = self.display_config.get("line_width", 2.0)

        can_deflect = (self.view_deflected and 
                       hasattr(model, 'has_results') and 
                       model.has_results and 
                       model.results is not None)

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
                res_i = model.results.get("displacements", {}).get(str(n1.id))
                res_j = model.results.get("displacements", {}).get(str(n2.id))
                
                if res_i and res_j:
                                                         
                    cache_key = eid
                    
                    if self.cache_scale_used != self.deflection_scale:
                        self.invalidate_deflection_cache()
                        self.deflection_cache.clear()
                        self.cache_scale_used = self.deflection_scale
                    
                    if cache_key not in self.deflection_cache:
                        v1, v2, v3 = self._get_consistent_axes(el)
                        
                        curve_data = get_deflected_shape(
                            [n1.x, n1.y, n1.z], 
                            [n2.x, n2.y, n2.z], 
                            res_i, res_j, 
                            v1, v2, v3, 
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
                    
                    cached = self.deflection_cache[cache_key]
                    curve_data_full = cached['curve_data']
                    p1_orig = cached['p1_orig']
                    
                    for k in range(len(curve_data_full) - 1):
                        pos_full, _, _ = curve_data_full[k]
                        pos_full_next, _, _ = curve_data_full[k+1]
                        
                        s = k / (len(curve_data_full) - 1)                         
                        pos_orig = p1_flex + s * (p2_flex - p1_flex)
                        
                        displacement = pos_full - pos_orig
                        p_start = pos_orig + displacement * self.anim_factor
                        
                        s_next = (k + 1) / (len(curve_data_full) - 1)
                        pos_orig_next = p1 + s_next * (p2 - p1)
                        displacement_next = pos_full_next - pos_orig_next
                        p_end = pos_orig_next + displacement_next * self.anim_factor
                        
                        curved_pos.append(p_start)
                        curved_pos.append(p_end)
                        curved_colors.append(c)
                        curved_colors.append(c)
                    
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
                
                vec = p2 - p1
                length = np.linalg.norm(vec)
                p1_flex = p1; p2_flex = p2
                
                if length > 0.001 and (off_i > 0 or off_j > 0):
                    u = vec / length
                    if off_i + off_j >= length:
                        scale = (length / (off_i + off_j)) * 0.99
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
                                                     
        all_line_pos = flex_pos + rigid_pos + curved_pos
        all_line_colors = flex_colors + rigid_colors + curved_colors

        if all_line_pos:
            v_arr = np.array(all_line_pos, dtype=np.float32)
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
        if not model.elements: return

        self.ex_vertices = []
        self.ex_faces = []
        self.ex_colors = []
        self.ex_edges = []
        self.ex_edge_colors = []
      
        opacity = self.display_config.get("extrude_opacity", 0.35)
        show_edges = self.display_config.get("show_edges", False)
        edge_c = np.array(self.display_config.get("edge_color", (0, 0, 0, 1)))
        edge_width = self.display_config.get("edge_width", 1.0)
        
        can_deflect = (self.view_deflected and 
                       hasattr(model, 'has_results') and 
                       model.has_results and 
                       model.results is not None)

        for eid, el in model.elements.items():
            n1, n2 = el.node_i, el.node_j
            
            v1 = self._get_visibility_state(n1.x, n1.y, n1.z)
            v2 = self._get_visibility_state(n2.x, n2.y, n2.z)

            if v1 == 0 or v2 == 0: continue

            is_active_elem = (v1 == 2 and v2 == 2)

            is_active_elem = (v1 == 2 and v2 == 2)

            sec = el.section
            shape_yz = sec.get_shape_coords()
            if not shape_yz: continue 

            needs_caps = isinstance(sec, (RectangularSection, CircularSection, TrapezoidalSection))
                             
            if not is_active_elem:
                                                          
                face_color = np.array([0.6, 0.6, 0.6, 0.3]) 
                current_edge_color = np.array([0.6, 0.6, 0.6, 0.1])
            else:
                                            
                c_raw = getattr(sec, 'color', [0.7, 0.7, 0.7])
                if len(c_raw) == 4: c_raw = c_raw[:3]
                face_color = np.array([c_raw[0], c_raw[1], c_raw[2], opacity])
                current_edge_color = edge_c

            path_points = [] 
            
            p1 = np.array([n1.x, n1.y, n1.z])
            p2 = np.array([n2.x, n2.y, n2.z])
            
            if can_deflect:
                res_i = model.results.get("displacements", {}).get(str(n1.id))
                res_j = model.results.get("displacements", {}).get(str(n2.id))
                
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

                self._add_loft_segment(
                    center_a, center_b, 
                    v2_a, v3_a, v2_b, v3_b,
                    shape_yz, face_color, 
                    show_edges, current_edge_color,
                    draw_start_ring=is_first_seg, 
                    draw_end_ring=is_last_seg,
                    draw_caps=needs_caps
                )

        if self.ex_vertices:
                                        
            v_arr = np.array(self.ex_vertices, dtype=np.float32)
            c_arr = np.array(self.ex_colors, dtype=np.float32)
            f_arr = np.array(self.ex_faces, dtype=np.int32)
            
            self.makeCurrent()
                                     
            self.vbo_manager.upload_extruded_geometry(v_arr, c_arr, f_arr)

        if show_edges and self.ex_edges:
            ev_arr = np.array(self.ex_edges, dtype=np.float32)
            ec_arr = np.array(self.ex_edge_colors, dtype=np.float32)
            
            self.makeCurrent()
            self.vbo_manager.upload_line_geometry(ev_arr, ec_arr)
        else:
                                                  
            self.makeCurrent()
            if hasattr(self, 'vbo_manager'):
                self.vbo_manager.upload_line_geometry([], [])

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
        if not hasattr(model, 'slabs') or not model.slabs: return
        
        opacity = self.display_config.get("slab_opacity", 0.4)
                              
        base_color = (0.7, 0.7, 0.7, opacity)                   
        
        verts = []; faces = []; colors = []
        v_start_idx = 0 

        for slab in model.slabs.values():
            nodes = slab.nodes
            n_count = len(nodes)
            if n_count < 3: continue
            if not self._is_visible(nodes[0].x, nodes[0].y, nodes[0].z): continue

            for n in nodes:
                verts.append([n.x, n.y, n.z])
                colors.append(base_color)
            
            for i in range(1, n_count - 1):
                faces.append([v_start_idx, v_start_idx + i, v_start_idx + i + 1])
            v_start_idx += n_count

        if not verts: return

        mesh = gl.GLMeshItem(
            vertexes=np.array(verts), faces=np.array(faces, dtype=np.int32),
            vertexColors=np.array(colors), smooth=False, shader='balloon',
            glOptions='translucent')
        self.addItem(mesh)

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

    def _draw_support_meshes(self, positions, s_type):
        """
        Draws realistic 3D shapes for supports.
        Fixed = Concrete block + Baseplate
        Pinned = Baseplate + Hinge Pyramid
        Roller = Baseplate + Sphere (Roller)
        Custom = Floating Octahedron (Mixed/Partial constraints)
        """
        if not positions: return

        all_verts = []
        all_faces = []
        all_colors = []
        idx_offset = 0

        if s_type == 'fixed': c = (0.40, 0.45, 0.50, 1.0)                
        elif s_type == 'pinned': c = (0.25, 0.55, 0.75, 1.0)               
        elif s_type == 'roller': c = (0.20, 0.65, 0.50, 1.0)              
        else: c = (0.85, 0.55, 0.20, 1.0)                                   

        s = self._screen_scale() * 5

        def add_box(cx, cy, cz, wx, wy, wz):
            nonlocal idx_offset
            v = [
                [cx-wx, cy-wy, cz-wz], [cx+wx, cy-wy, cz-wz], [cx+wx, cy+wy, cz-wz], [cx-wx, cy+wy, cz-wz],
                [cx-wx, cy-wy, cz+wz], [cx+wx, cy-wy, cz+wz], [cx+wx, cy+wy, cz+wz], [cx-wx, cy+wy, cz+wz]
            ]
            f = [
                [0, 1, 2], [0, 2, 3], [4, 5, 6], [4, 6, 7],
                [0, 1, 5], [0, 5, 4], [2, 3, 7], [2, 7, 6],
                [0, 3, 7], [0, 7, 4], [1, 2, 6], [1, 6, 5]
            ]
            all_verts.extend(v)
            all_faces.extend([[i + idx_offset for i in face] for face in f])
            for _ in range(8): all_colors.append(c)
            idx_offset += 8

        def add_pyramid(apex_x, apex_y, apex_z, base_w, height):
            nonlocal idx_offset
            z_base = apex_z - height
            v = [
                [apex_x, apex_y, apex_z],
                [apex_x-base_w, apex_y-base_w, z_base], [apex_x+base_w, apex_y-base_w, z_base],
                [apex_x+base_w, apex_y+base_w, z_base], [apex_x-base_w, apex_y+base_w, z_base]
            ]
            f = [
                [0, 1, 2], [0, 2, 3], [0, 3, 4], [0, 4, 1],
                [1, 2, 3], [1, 3, 4]
            ]
            all_verts.extend(v)
            all_faces.extend([[i + idx_offset for i in face] for face in f])
            for _ in range(5): all_colors.append(c)
            idx_offset += 5

        def add_sphere(cx, cy, cz, radius, bands=8):
            nonlocal idx_offset
            local_verts = []
            local_faces = []
            
            for i in range(bands + 1):
                lat = np.pi * i / bands
                z_val = np.cos(lat)
                r_ring = np.sin(lat)
                for j in range(bands):
                     lon = 2 * np.pi * j / bands
                     x_val = r_ring * np.cos(lon)
                     y_val = r_ring * np.sin(lon)
                     local_verts.append([cx + x_val*radius, cy + y_val*radius, cz + z_val*radius])
            
            for i in range(bands):
                for j in range(bands):
                    row1 = i * bands
                    row2 = (i + 1) * bands
                    c1 = j
                    c2 = (j + 1) % bands
                    p1, p2 = row1 + c1, row1 + c2
                    p3, p4 = row2 + c2, row2 + c1
                    local_faces.append([p1, p2, p4])
                    local_faces.append([p2, p3, p4])

            all_verts.extend(local_verts)
            all_faces.extend([[i + idx_offset for i in face] for face in local_faces])
            for _ in range(len(local_verts)): all_colors.append(c)
            idx_offset += len(local_verts)

        for x, y, z in positions:
            if s_type == 'fixed':
                                                     
                add_box(x, y, z - s, s*0.8, s*0.8, s)
                add_box(x, y, z - s*2.1, s*1.2, s*1.2, s*0.1)

            elif s_type == 'pinned':
                                            
                add_pyramid(x, y, z, s*0.8, s*1.8)
                add_box(x, y, z - s*1.9, s*1.2, s*1.2, s*0.1)

            elif s_type == 'roller':
                                                        
                add_sphere(x, y, z - s*0.9, s*0.9)            
                add_box(x, y, z - s*1.9, s*1.2, s*1.2, s*0.1)                  

            elif s_type == 'custom':
                                                                  
                add_pyramid(x, y, z, s*0.6, s)
                v = [
                    [x, y, z],
                    [x-s*0.6, y-s*0.6, z-s], [x+s*0.6, y-s*0.6, z-s], 
                    [x+s*0.6, y+s*0.6, z-s], [x-s*0.6, y+s*0.6, z-s],
                    [x, y, z-s*2]
                ]
                f = [
                    [0, 1, 2], [0, 2, 3], [0, 3, 4], [0, 4, 1],
                    [5, 2, 1], [5, 3, 2], [5, 4, 3], [5, 1, 4]
                ]
                all_verts.extend(v)
                all_faces.extend([[i + idx_offset for i in face] for face in f])
                for _ in range(6): all_colors.append(c)
                idx_offset += 6

        if not all_verts: return

        mesh = gl.GLMeshItem(
            vertexes=np.array(all_verts, dtype=np.float32),
            faces=np.array(all_faces, dtype=np.int32),
            vertexColors=np.array(all_colors, dtype=np.float32),
            smooth=False, 
            shader='balloon',
            glOptions='opaque'
        )
        self.addItem(mesh)
        self._support_items.append(mesh)

    def _rebuild_support_items(self):
        """Rebuild support meshes with current zoom level — keeps symbols screen-size-stable."""
        for item in self._support_items:
            try: self.removeItem(item)
            except Exception: pass
        self._support_items.clear()

        sp = self._support_positions
        if sp['fixed']:  self._draw_support_meshes(sp['fixed'],  'fixed')
        if sp['pinned']: self._draw_support_meshes(sp['pinned'], 'pinned')
        if sp['roller']: self._draw_support_meshes(sp['roller'], 'roller')
        if sp['custom']: self._draw_support_meshes(sp['custom'], 'custom')

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
        
        def add_arrow(pt, direction, color, is_moment):
            tip = pt
            tail = pt - (direction * L)
            arrow_lines.append(tail); arrow_lines.append(tip)
            arrow_colors.append(color); arrow_colors.append(color)
            
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

        for load in model.loads:
            if not hasattr(load, 'node_id'): continue
            if self.visible_load_patterns and load.pattern_name not in self.visible_load_patterns: continue

            node = model.nodes.get(load.node_id)
            if not node: continue
                                                                           
            if self._get_visibility_state(node.x, node.y, node.z) != 2: continue
            
            origin = np.array([node.x, node.y, node.z])
            is_selected = (node.id in self.selected_node_ids)

            def process_component(val, axis_vec, color, is_moment):
                if abs(val) > 0:
                    d = axis_vec * (1 if val > 0 else -1)
                    add_arrow(origin, d, color, is_moment)
                    
                    l_type = "Moment" if is_moment else "Force"
                    self._add_load_label(origin, d, val, l_type, color, owner_id=node.id, owner_type='node')

            c_black = (0, 0, 0, 1)

            process_component(load.fz, np.array([0, 0, 1.0]), c_black, False)
            process_component(load.fx, np.array([1.0, 0, 0]), c_black, False)
            process_component(load.fy, np.array([0, 1.0, 0]), c_black, False)

            process_component(load.mz, np.array([0, 0, 1.0]), c_black, True)
            process_component(load.mx, np.array([1.0, 0, 0]), c_black, True)
            process_component(load.my, np.array([0, 1.0, 0]), c_black, True)

        if arrow_lines:
            item = gl.GLLinePlotItem(
                pos=np.array(arrow_lines), 
                color=np.array(arrow_colors), 
                mode='lines', width=2.0, antialias=True
            )
            self.addItem(item)
            if not hasattr(self, 'load_items'): self.load_items = []
            self.load_items.append(item)

    def _add_load_label(self, origin, direction, val, l_type, color, owner_id=None, owner_type=None):
        if l_type == "Moment":
            m_scale = unit_registry.force_scale * unit_registry.length_scale
            display_val = abs(val) * m_scale
            unit_str = f"{unit_registry.force_unit_name}.{unit_registry.length_unit_name}"
        else:
            display_val = unit_registry.to_display_force(abs(val))
            unit_str = unit_registry.force_unit_name
            
        label_pos = origin - (direction * 2.2)
        self.load_labels.append({
            'owner_id': owner_id,
            'owner_type': owner_type,
            'pos_3d': label_pos,
            'text': f"{display_val:.2f} {unit_str}",
            'color': color
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

        def get_visible(lines_attr):
            if not lines_attr: return [0.0]
                                                                      
            if isinstance(lines_attr[0], dict):
                return [item['ord'] for item in lines_attr if item.get('visible', True)]
                                                                 
            return lines_attr

        vis_x = get_visible(getattr(model.grid, 'x_lines', model.grid.x_grids))
        vis_y = get_visible(getattr(model.grid, 'y_lines', model.grid.y_grids))
        vis_z = get_visible(getattr(model.grid, 'z_lines', model.grid.z_grids))
        
        if not vis_x or not vis_y or not vis_z: return

        z_min, z_max = min(vis_z), max(vis_z)
        x_min, x_max = min(vis_x), max(vis_x)
        y_min, y_max = min(vis_y), max(vis_y)

        bright_pos = []                       
        dim_pos = []                        

        def is_on_active_plane(p1, p2):
            if not self.active_view_plane: return False                                    
            
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

        if bright_pos:
            self.addItem(gl.GLLinePlotItem(pos=np.array(bright_pos), mode='lines', 
                                           color=(0, 1, 1, 0.8), width=2, antialias=True))
            
        if dim_pos:
            alpha = 0.6 if self.active_view_plane is None else 0.1
            c = (0.6, 0.6, 0.6, alpha)
            self.addItem(gl.GLLinePlotItem(pos=np.array(dim_pos), mode='lines', 
                                           color=c, width=2, antialias=True))
        
        self._rebuild_axis_items()                                      

    def get_snap_point(self, mouse_x, mouse_y):
        if not self.snapping_enabled:
            self.snap_ring.setVisible(False)
            self.snap_dot.setVisible(False)
            self.snap_text.setVisible(False)
            return None
        if not self.current_model: return None

        candidates = []
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

        for z in z_range:
            for x in x_range:
                for y in y_range:
                    candidates.append((x, y, z))
        
        if not candidates: return None
        
        view_w = self.width()
        view_h = self.height()
        full_area = (0, 0, view_w, view_h)
        m_view = self.viewMatrix()
        m_proj = self.projectionMatrix(region=full_area, viewport=full_area)
        mvp = m_proj * m_view
        mvp_matrix = np.array(mvp.data()).reshape(4, 4).T

        best_point = None
        closest_dist = 25.0                                 
        
        for pt in candidates:
            vec = np.array([pt[0], pt[1], pt[2], 1.0])
            clip = np.dot(mvp_matrix, vec)
            if clip[3] <= 0: continue
            ndc_x = clip[0] / clip[3]
            ndc_y = clip[1] / clip[3]
            screen_x = (ndc_x + 1) * view_w / 2
            screen_y = (1 - ndc_y) * view_h / 2
            
            dx = screen_x - mouse_x
            dy = screen_y - mouse_y
            dist = (dx**2 + dy**2)**0.5
            
            if dist < closest_dist:
                closest_dist = dist
                best_point = pt

        if best_point:
            bx, by, bz = best_point
            
            inv_view = np.linalg.inv(np.array(m_view.data()).reshape(4,4).T)
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
    
    def update_selection_during_animation(self, sel_elems=None, sel_nodes=None):
        """
        Updates selection state during animation without causing redraw lag.
        
        This is called when user selects nodes/elements while animation is running.
        Instead of redrawing everything (which causes lag), we just update the
        selection state. The next animation frame will show the updated selection.
        
        Args:
            sel_elems: List of selected element IDs
            sel_nodes: List of selected node IDs
        """
        if sel_elems is not None:
            self.selected_element_ids = sel_elems
        if sel_nodes is not None:
            self.selected_node_ids = sel_nodes
        
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

            for k in range(n_pts - 1):
                pos_full_a, _, _ = curve_data_full[k]
                pos_full_b, _, _ = curve_data_full[k + 1]

                s_a = k / (n_pts - 1)
                s_b = (k + 1) / (n_pts - 1)

                pos_orig_a = p1 + s_a * (p2 - p1)
                pos_orig_b = p1 + s_b * (p2 - p1)

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
            
            for k in range(len(curve_data_full) - 1):
                pos_full, _, _ = curve_data_full[k]
                pos_full_next, _, _ = curve_data_full[k+1]
                
                s = k / (len(curve_data_full) - 1)
                pos_orig = p1 + s * (p2 - p1)
                
                s_next = (k + 1) / (len(curve_data_full) - 1)
                pos_orig_next = p1 + s_next * (p2 - p1)
                
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
            if self.is_selecting:
                self.drag_current = event.pos()
                self.update()
                return
            self.update()
            return

        is_middle_pan = (event.buttons() == Qt.MouseButton.MiddleButton)
        is_tool_pan = (event.buttons() == Qt.MouseButton.LeftButton and getattr(self, 'single_use_pan_active', False))

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
        pos = event.position()
        
        self.camera.zoom(delta, pos.x(), pos.y(), self.width(), self.height())
        self._support_rebuild_timer.start(60) 
        
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
        
        if self.load_labels and self.current_model:
            
            w = self.width()
            h = self.height()
            full_area = (0, 0, w, h)
            m_view = self.viewMatrix()
            m_proj = self.projectionMatrix(region=full_area, viewport=full_area)
            mvp = np.array((m_proj * m_view).data()).reshape(4, 4).T
            
            TEXT_WORLD_HEIGHT = 0.35
            
            font = painter.font()
            
            for label in self.load_labels:

                o_id = label.get('owner_id')
                o_type = label.get('owner_type')
                
                if o_type == 'node' and o_id not in self.selected_node_ids:
                    continue
                if o_type == 'element' and o_id not in self.selected_element_ids:
                    continue

                pos_3d = label['pos_3d']
                
                vec = np.array([pos_3d[0], pos_3d[1], pos_3d[2], 1.0])
                clip = np.dot(mvp, vec)
                
                if clip[3] <= 0.1: continue 

                ndc_x = clip[0] / clip[3]
                ndc_y = clip[1] / clip[3]
                sx = (ndc_x + 1) * w / 2
                sy = (1 - ndc_y) * h / 2
                
                if sx < -50 or sx > w + 50 or sy < -50 or sy > h + 50:
                    continue

                px_size = (h * TEXT_WORLD_HEIGHT) / (clip[3] * 1.2)
                
                if px_size < 6: 
                    continue
                
                if px_size > 60: px_size = 60

                font.setPixelSize(int(px_size))
                painter.setFont(font)

                r, g, b = label['color'][:3]
                text_color = QColor(int(r*255), int(g*255), int(b*255))
    
                text = label['text']
                metrics = painter.fontMetrics()
                t_width = metrics.horizontalAdvance(text)
                t_height = metrics.height()
                
                text_x = int(sx) + 5
                text_y = int(sy) - 5
                
                bg_rect = QRect(text_x - 2, text_y - t_height + 2, t_width + 4, t_height)
                painter.fillRect(bg_rect, QColor(255, 255, 255, 180))                              
                
                painter.setPen(text_color)
                painter.drawText(text_x, text_y, text)

        if getattr(self, 'current_hover_data', None):
            hx = self.current_hover_data['x'] + 15
            hy = self.current_hover_data['y'] + 15
            text = self.current_hover_data['text']
            
            font = painter.font()
            font.setFamily("Consolas")
            font.setPixelSize(11) 
            font.setBold(False)
            painter.setFont(font)
            
            metrics = painter.fontMetrics()
            rect = metrics.boundingRect(0, 0, 400, 400, Qt.TextFlag.TextExpandTabs | Qt.AlignmentFlag.AlignLeft, text)
            
            bg_rect = QRect(int(hx), int(hy), rect.width() + 12, rect.height() + 10)
            painter.fillRect(bg_rect, QColor(40, 40, 40, 200))
            painter.setPen(QColor(80, 80, 80, 200))                     
            painter.drawRect(bg_rect)
            
            painter.setPen(QColor(220, 220, 220)) 
            text_rect = QRect(int(hx) + 6, int(hy) + 5, rect.width(), rect.height())
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft, text)
            
        if self.current_model:
            _w = self.width(); _h = self.height()
            _full = (0, 0, _w, _h)
            _mvp = np.array((self.projectionMatrix(region=_full, viewport=_full) * self.viewMatrix()).data()).reshape(4, 4).T
            self._draw_axis_overlay(painter, _mvp, _w, _h)

        painter.end()
            
    def process_box_selection(self, p_start, p_end):
        if not self.current_model: return
        
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

        found_nodes = []
        found_elems = []

        can_deflect = (self.view_deflected and 
                       hasattr(self.current_model, 'has_results') and 
                       self.current_model.has_results and 
                       self.current_model.results is not None)

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
                sx, sy = s_pos
                if x_min <= sx <= x_max and y_min <= sy <= y_max:
                    found_nodes.append(nid)

        for eid, el in self.current_model.elements.items():
            n1, n2 = el.node_i, el.node_j
            
            v1 = self._get_visibility_state(n1.x, n1.y, n1.z)
            v2 = self._get_visibility_state(n2.x, n2.y, n2.z)
            
            if v1 != 2 or v2 != 2: 
                continue              

            if el.node_i.id not in node_screens or el.node_j.id not in node_screens:
                continue
            
            p1 = node_screens[el.node_i.id]
            p2 = node_screens[el.node_j.id]
            
            p1_in = (x_min <= p1[0] <= x_max and y_min <= p1[1] <= y_max)
            p2_in = (x_min <= p2[0] <= x_max and y_min <= p2[1] <= y_max)

            if is_window_select:
                                                  
                if p1_in and p2_in: found_elems.append(eid)
            else:
                                                    
                rect = (x_min, y_min, x_max, y_max)
                if self._line_intersects_rect(p1, p2, rect):
                    found_elems.append(eid)

        modifiers = QApplication.keyboardModifiers()
        is_additive = (modifiers == Qt.KeyboardModifier.ControlModifier)
        is_deselect = (modifiers == Qt.KeyboardModifier.ShiftModifier)
        self.signal_box_selection.emit(found_nodes, found_elems, is_additive, is_deselect)

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

    def _draw_member_loads(self, model):
        """
        Visualizes Distributed Loads (Professional UX).
        - Unselected: Faint colored curtain ONLY (no arrows, no text). Keeps scene clean.
        - Selected: Darker curtain, Outline, 5 distinct arrows, and Text Label.
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

        for load in model.loads:
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
            v1_ax, v2_ax, v3_ax = self._get_consistent_axes(el) 

            for axis_idx in range(3):
                val = raw_w[axis_idx]
                if abs(val) < 1e-6: continue

                magnitude = max(1.0, abs(val))
                scale = min(1.5, 0.5 + (np.log10(magnitude) * 0.2))
                sign = 1 if val > 0 else -1
                
                if load.coord_system == "Local":
                    load_vec = [v1_ax, v2_ax, v3_ax][axis_idx]
                else:
                    load_vec = np.zeros(3); load_vec[axis_idx] = 1.0

                base_rgb = (0.0, 0.0, 0.0)

                c_ghost      = (*base_rgb, 0.25)
                c_ghost_line = (*base_rgb, 0.60)
                c_sel_fill   = (*base_rgb, 0.55)
                c_line       = (*base_rgb, 1.00)                                  

                offset_vec = -1 * sign * load_vec * scale 
                cross_prod = np.cross(beam_dir, load_vec)
                is_parallel = np.linalg.norm(cross_prod) < 0.01
                visual_shift = v2_ax * 0.5 if is_parallel else np.zeros(3)

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

                display_val = val * unit_registry.force_scale / unit_registry.length_scale
                mid_height = (pt_top_1 + pt_top_2) / 2
                self.load_labels.append({
                    'owner_id': el.id, 'owner_type': 'element',
                    'pos_3d': mid_height.tolist(),                               
                    'text': f"{display_val:.2f} {unit_registry.distributed_load_unit}",  
                    'color': c_line                                         
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
            mesh_ghost = gl.GLMeshItem(
                vertexes=np.array(ghost_verts, dtype=np.float32), faces=np.array(ghost_faces, dtype=np.int32),
                vertexColors=np.array(ghost_colors, dtype=np.float32), smooth=False, shader='balloon', glOptions='translucent'
            )
            self.addItem(mesh_ghost)
            self.load_items.append(mesh_ghost)

        if ghost_lines:
            g_lines = gl.GLLinePlotItem(pos=np.array(ghost_lines), color=np.array(ghost_line_colors), mode='lines', width=1.0, antialias=True)
            g_lines.setGLOptions('translucent')
            self.addItem(g_lines)
            self.load_items.append(g_lines)

        if sel_verts:
            mesh_sel = gl.GLMeshItem(
                vertexes=np.array(sel_verts, dtype=np.float32), faces=np.array(sel_faces, dtype=np.int32),
                vertexColors=np.array(sel_colors, dtype=np.float32), smooth=False, shader='balloon', glOptions='translucent'
            )
            self.addItem(mesh_sel)
            self.load_items.append(mesh_sel)

        if sel_lines:
            lines = gl.GLLinePlotItem(pos=np.array(sel_lines), color=np.array(sel_line_colors), mode='lines', width=2, antialias=True)
            self.addItem(lines)
            self.load_items.append(lines)

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
                width=2.5,                                  
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

            if not is_ghosted:
                self._add_load_label(load_pos, draw_dir, val, "Moment" if is_moment else "Force", c, owner_id=el.id, owner_type='element')

        if arrow_lines:
            self.addItem(gl.GLLinePlotItem(
                pos=np.array(arrow_lines), 
                color=np.array(arrow_colors), 
                mode='lines', width=2.0, antialias=True
            ))

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
        
        for item in self.node_items:
            try: self.removeItem(item)
            except: pass                         
            
        for item in self.element_items:
            try: self.removeItem(item)
            except: pass 
        
        self.node_items.clear()
        self.element_items.clear()
        
        if self.show_joints or self.show_supports:
            self._draw_nodes(self.current_model)
        
        if not self.view_deflected:
            if self.view_extruded:
                self._draw_elements_extruded(self.current_model)
            else:
                self._draw_elements_wireframe(self.current_model)

    def paintGL(self, *args, **kwargs):
        glEnable(GL_MULTISAMPLE)

        top_items = getattr(self, '_sel_overlay_items', []) + [
            self.preview_line, self._beam_col_prev_line, 
            self._brace_prev_x1, self._brace_prev_x2, 
            self._brace_prev_border, self.snap_ring, self.snap_dot,
            self.pivot_dot
        ]
        
        vis_states = []
        for item in top_items:
            vis_states.append(item.visible())
            item.setVisible(False)

        super().paintGL()

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

        if hasattr(self, 'vbo_manager') and self.vbo_manager.is_initialized:
            w, h = self.width(), self.height()
            full_area = (0, 0, w, h)
            m_view = np.array(self.viewMatrix().data(), dtype=np.float32).reshape(4,4)
            m_proj = np.array(self.projectionMatrix(region=full_area, viewport=full_area).data(), dtype=np.float32).reshape(4,4)

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
            self.current_hover_data = None
            self.update()
            return

        w, h = self.width(), self.height()
        full_area = (0, 0, w, h)
        m_view = self.viewMatrix()
        m_proj = self.projectionMatrix(region=full_area, viewport=full_area)
        mvp = np.array((m_proj * m_view).data()).reshape(4, 4).T

        hovered_node = None
        hovered_elem = None
        min_dist = 15.0

        can_deflect = (self.view_deflected and 
                       hasattr(self.current_model, 'has_results') and 
                       self.current_model.has_results and 
                       self.current_model.results is not None)

        node_screens = {}
        for nid, node in self.current_model.nodes.items():
            if self._get_visibility_state(node.x, node.y, node.z) != 2: continue
            
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
                    
                    is_fixed = all(r[:3]) and all(r[3:])
                    is_pinned = all(r[:3]) and not any(r[3:])
                    is_roller = r[2] and not any(r[0:2]) and not any(r[3:])
                    
                    if is_fixed: s_type = "Fixed"
                    elif is_pinned: s_type = "Pinned"
                    elif is_roller: s_type = "Roller"
                    else: s_type = "Custom"
                    
                    dof_names = ["UX", "UY", "UZ", "RX", "RY", "RZ"]
                    active_dofs = [dof_names[i] for i, state in enumerate(r) if state]
                    
                    text += f"\nSupport: {s_type}\nRestraints: [{', '.join(active_dofs)}]"

        elif hovered_elem is not None:
            el = self.current_model.elements[hovered_elem]
            sec_name = el.section.name if el.section else "None"
            text = f"FRAME {hovered_elem}\nSection: {sec_name}"

        if text:
            self.current_hover_data = {'text': text, 'x': px, 'y': py}
        else:
            self.current_hover_data = None

        self.hovered_node_id = hovered_node
        self.hovered_elem_id = hovered_elem
            
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
