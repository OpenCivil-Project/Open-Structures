import numpy as np
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QSlider, QLabel, QHBoxLayout
from PyQt6.QtCore import Qt
import pyqtgraph as pg
from core.units import unit_registry                                  

class CrossSectionViewerDialog(QDialog):
    def __init__(self, model, main_canvas, selected_elements, parent=None):
        super().__init__(parent)
        self.setWindowTitle("2D Section Viewer")
        self.resize(500, 550)
        self.model = model
        self.main_canvas = main_canvas
        
        self.elements = selected_elements 
        self.lengths = []
        for el in self.elements:
            p1 = np.array([el.node_i.x, el.node_i.y, el.node_i.z])
            p2 = np.array([el.node_j.x, el.node_j.y, el.node_j.z])
            self.lengths.append(np.linalg.norm(p2 - p1))
            
        self.total_length = sum(self.lengths)
        
        self.init_ui()
        self.update_view(0)

    def init_ui(self):
        layout = QVBoxLayout(self)
        
        self.plot = pg.PlotWidget(background='w')
        self.plot.setAspectLocked(True)
        self.plot.showGrid(x=True, y=True, alpha=0.3)
        
        self.plot.setLabel('left', ' ')
        self.plot.setLabel('bottom', ' ')
        
        layout.addWidget(self.plot)
        
        u_name = unit_registry.length_unit_name
        self.info_label = QLabel(f"Element: -- | Local x: 0.00 {u_name}")
        self.info_label.setStyleSheet("font-family: Consolas; font-weight: bold; font-size: 12px;")
        layout.addWidget(self.info_label)
        
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 1000)
        self.slider.valueChanged.connect(self.update_view)
        layout.addWidget(self.slider)

    def update_view(self, value):
        if not self.elements or self.total_length == 0: return
        
        current_dist = (value / 1000.0) * self.total_length
        accumulated = 0.0
        
        current_el = None
        local_x = 0.0
        ratio = 0.0
        
        for el, length in zip(self.elements, self.lengths):
            if accumulated + length >= current_dist or el == self.elements[-1]:
                current_el = el
                local_x = current_dist - accumulated
                ratio = local_x / length if length > 0 else 0.0
                break
            accumulated += length
            
        disp_x = unit_registry.to_display_length(local_x)
        u_name = unit_registry.length_unit_name
        self.info_label.setText(f"Element: {current_el.id} | Local x: {disp_x:.3f} {u_name}")
        
        self.draw_2d_section(current_el, local_x, ratio)
        self.main_canvas.update_inspection_dot(current_el, ratio)

    def draw_2d_section(self, element, local_x, ratio):
        self.plot.clear()
        
        shape_yz = element.section.get_shape_coords()
        if not shape_yz: return
            
        orig_beta = getattr(element, 'beta_angle', 0.0)
        v1, v2_rot, v3_rot = self.main_canvas._get_consistent_axes(element)
        
        element.beta_angle = 0.0
        _, vy_unrot, vz_unrot = self.main_canvas._get_consistent_axes(element)
        element.beta_angle = orig_beta
        
        y_shift, z_shift = element.get_cardinal_offsets()
        off_i = getattr(element, 'joint_offset_i', np.zeros(3))
        off_j = getattr(element, 'joint_offset_j', np.zeros(3))
        
        curr_off_global = (1.0 - ratio) * off_i + ratio * off_j
        shift_global = curr_off_global + (y_shift * v2_rot) + (z_shift * v3_rot)
        
        h_shift = np.dot(shift_global, -vy_unrot)
        v_shift = np.dot(shift_global, vz_unrot)
        
        rad = np.radians(orig_beta)
        c = np.cos(rad)
        s = np.sin(rad)
        
        u_name = unit_registry.length_unit_name
        
        pts_horiz = []
        pts_vert = []
        for y, z in shape_yz:
                                        
            h = -(y * c - z * s)
            v = (y * s + z * c)
            
            h += h_shift
            v += v_shift
            
            pts_horiz.append(unit_registry.to_display_length(h))
            pts_vert.append(unit_registry.to_display_length(v))
        
        pts_horiz.append(pts_horiz[0])
        pts_vert.append(pts_vert[0])
        
        self.plot.plot(pts_horiz, pts_vert, pen=pg.mkPen('k', width=2), brush=pg.mkBrush(100, 150, 255, 100))
        
        max_extent = max(abs(max(pts_horiz)), abs(min(pts_horiz)), abs(max(pts_vert)), abs(min(pts_vert)))
        arrow_len = max(0.1, max_extent * 1.3)
        
        l2_h = arrow_len * s
        l2_v = arrow_len * c
        self.plot.plot([0, l2_h], [0, l2_v], pen=pg.mkPen('g', width=2, style=Qt.PenStyle.DashLine))
        
        l2_label = pg.TextItem(f"Local 2 ({u_name})", color='g', anchor=(0.5, 0.5))
        l2_label.setPos(l2_h * 1.1, l2_v * 1.1)
        self.plot.addItem(l2_label)
        
        l3_h = arrow_len * c
        l3_v = -arrow_len * s
        self.plot.plot([0, l3_h], [0, l3_v], pen=pg.mkPen('b', width=2, style=Qt.PenStyle.DashLine))
        
        l3_label = pg.TextItem(f"Local 3 ({u_name})", color='b', anchor=(0.5, 0.5))
        l3_label.setPos(l3_h * 1.1, l3_v * 1.1)
        self.plot.addItem(l3_label)
                                           
        tendon_coords = self._slice_tendons_2d(element, local_x)
        for h_tendon, v_tendon in tendon_coords:
            h_disp = unit_registry.to_display_length(h_tendon)
            v_disp = unit_registry.to_display_length(v_tendon)
            self.plot.plot([h_disp], [v_disp], symbol='o', symbolBrush='r', symbolPen='k', symbolSize=12)
            
    def _slice_tendons_2d(self, element, local_x):
        coords_2d = []
        if not hasattr(self.model, 'tendons'): return coords_2d
        
        p1 = np.array([element.node_i.x, element.node_i.y, element.node_i.z])
        
        orig_beta = getattr(element, 'beta_angle', 0.0)
        element.beta_angle = 0.0
        v1, vy_unrot, vz_unrot = self.main_canvas._get_consistent_axes(element)
        element.beta_angle = orig_beta
        
        plane_center = p1 + (v1 * local_x)
        
        tendons_in_elem = [t for t in self.model.tendons.values() if element.id in getattr(t, 'host_element_ids', [])]
        
        for t in tendons_in_elem:
            pts = self.main_canvas._get_tendon_world_points(t)
            if pts is None or len(pts) < 2: continue
            
            dists_x = [np.dot(pt - p1, v1) for pt in pts]
            
            for k in range(len(dists_x) - 1):
                d_start, d_end = dists_x[k], dists_x[k+1]
                
                if min(d_start, d_end) <= local_x <= max(d_start, d_end):
                    span = d_end - d_start
                    if abs(span) < 1e-6:
                        pt_int = pts[k]
                    else:
                        ratio = (local_x - d_start) / span
                        pt_int = pts[k] + ratio * (pts[k+1] - pts[k])
                    
                    delta = pt_int - plane_center
                    
                    h_tendon = np.dot(delta, -vy_unrot)
                    v_tendon = np.dot(delta, vz_unrot)
                    
                    coords_2d.append((h_tendon, v_tendon))
                    break
                    
        return coords_2d

    def closeEvent(self, event):
        self.main_canvas.hide_inspection_dot()
        super().closeEvent(event)

    def reject(self):
        self.main_canvas.hide_inspection_dot()
        super().reject()
