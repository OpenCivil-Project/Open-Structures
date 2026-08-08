import numpy as np
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QSlider, QLabel, QHBoxLayout
from PyQt6.QtCore import Qt
import pyqtgraph as pg

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
        self.plot.setLabel('left', 'Vertical Axis (Local 2)', units='m')
        self.plot.setLabel('bottom', 'Horizontal Axis (Local 3)', units='m')
        layout.addWidget(self.plot)
        
        self.info_label = QLabel("Element: -- | Local x: 0.00 m")
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
            
        self.info_label.setText(f"Element: {current_el.id} | Local x: {local_x:.3f} m")
        
        self.draw_2d_section(current_el, local_x)
        
        self.main_canvas.update_inspection_dot(current_el, ratio)

    def draw_2d_section(self, element, local_x):
        self.plot.clear()
        
        shape_yz = element.section.get_shape_coords()
        if shape_yz:
                                                                        
            pts_horiz = [-y for y, z in shape_yz] 
            pts_vert = [z for y, z in shape_yz]
            
            pts_horiz.append(pts_horiz[0])
            pts_vert.append(pts_vert[0])
            
            self.plot.plot(pts_horiz, pts_vert, pen=pg.mkPen('k', width=2), brush=pg.mkBrush(100, 150, 255, 100))
        
        tendon_coords = self._slice_tendons_2d(element, local_x)
        for y_internal, z_internal in tendon_coords:
                                                                     
            self.plot.plot([-y_internal], [z_internal], symbol='o', symbolBrush='r', symbolPen='k', symbolSize=12)

    def closeEvent(self, event):
                                                         
        self.main_canvas.hide_inspection_dot()
        super().closeEvent(event)
    
    def _slice_tendons_2d(self, element, local_x):
        """Finds where the 3D tendon polyline intersects the 2D section plane."""
        coords_2d = []
        if not hasattr(self.model, 'tendons'): return coords_2d
        
        p1 = np.array([element.node_i.x, element.node_i.y, element.node_i.z])
        v1, v2, v3 = self.main_canvas._get_consistent_axes(element)
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
                    y_local = np.dot(delta, v2)
                    z_local = np.dot(delta, v3)
                    
                    coords_2d.append((y_local, z_local))
                    break                          
                    
        return coords_2d

