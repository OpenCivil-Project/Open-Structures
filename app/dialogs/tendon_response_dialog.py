import math
import numpy as np
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, 
                             QPushButton, QGroupBox, QLineEdit, QRadioButton, 
                             QButtonGroup, QWidget, QGridLayout, QFrame)
from PyQt6.QtGui import QPainter, QPen, QColor, QBrush
from PyQt6.QtCore import Qt, pyqtSignal

from app.ui.theme import apply_dialog_style, COLORS
from core.units import UnitConverter
from core.prestress.tendon_evaluator import TendonEvaluator

class TendonResponsePlot(QWidget):
    """Custom interactive QPainter canvas for visualizing prestress loss over length."""
    cursor_moved = pyqtSignal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(280)
        self.setStyleSheet(f"background-color: white; border: 1px solid {COLORS['border']};")
        self.setMouseTracking(True)
        
        self.x_data = []
        self.prior_y = []
        self.final_y = []
        self.cursor_x = 0.0
        self.total_length = 0.0
        self.margin_l, self.margin_r, self.margin_t, self.margin_b = 60, 20, 20, 30

    def set_data(self, x_data, prior_y, final_y):
        self.x_data = x_data
        self.prior_y = prior_y
        self.final_y = final_y
        self.total_length = max(x_data) if len(x_data) > 0 else 0.0
        self.update()

    def set_cursor_x(self, x_val):
        self.cursor_x = max(0.0, min(x_val, self.total_length))
        self.update()

    def mouseMoveEvent(self, event):
        if not self.x_data: return
        plot_w = self.width() - self.margin_l - self.margin_r
        mx = event.position().x() - self.margin_l
        
        ratio = max(0.0, min(mx / plot_w, 1.0))
        self.cursor_x = ratio * self.total_length
        self.cursor_moved.emit(self.cursor_x)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        w, h = self.width(), self.height()
        plot_w = w - self.margin_l - self.margin_r
        plot_h = h - self.margin_t - self.margin_b

        if not self.x_data or not self.prior_y or not self.final_y:
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No Data Available")
            return

        # Calculate bounds based on BOTH arrays
        y_min = min(min(self.prior_y), min(self.final_y))
        y_max = max(max(self.prior_y), max(self.final_y))
        y_range = max(1e-6, y_max - y_min)
        y_min_plot = y_min - (y_range * 0.1)
        y_max_plot = y_max + (y_range * 0.1)
        
        # Draw Grid
        painter.setPen(QPen(QColor("#E0E0E0"), 1, Qt.PenStyle.SolidLine))
        grid_steps = 10
        for i in range(grid_steps + 1):
            px = self.margin_l + (i / grid_steps) * plot_w
            painter.drawLine(int(px), self.margin_t, int(px), h - self.margin_b)
            py = self.margin_t + (i / grid_steps) * plot_h
            painter.drawLine(self.margin_l, int(py), w - self.margin_r, int(py))

        # Y-Axis Labels
        painter.setPen(QPen(QColor("black"), 1))
        fmt = "{:.0f}" if y_range > 10 else "{:.3f}"
        painter.drawText(5, self.margin_t + 5, fmt.format(y_max_plot))
        painter.drawText(5, h - self.margin_b, fmt.format(y_min_plot))

        # 1. Draw Prior to Seating Curve (Magenta)
        painter.setPen(QPen(QColor("#9C27B0"), 2.5)) 
        for i in range(len(self.x_data) - 1):
            x1 = self.margin_l + (self.x_data[i] / self.total_length) * plot_w
            y1 = h - self.margin_b - ((self.prior_y[i] - y_min_plot) / (y_max_plot - y_min_plot)) * plot_h
            x2 = self.margin_l + (self.x_data[i+1] / self.total_length) * plot_w
            y2 = h - self.margin_b - ((self.prior_y[i+1] - y_min_plot) / (y_max_plot - y_min_plot)) * plot_h
            painter.drawLine(int(x1), int(y1), int(x2), int(y2))

        # 2. Draw Final Curve (Green)
        painter.setPen(QPen(QColor("#00E676"), 2.5)) 
        for i in range(len(self.x_data) - 1):
            x1 = self.margin_l + (self.x_data[i] / self.total_length) * plot_w
            y1 = h - self.margin_b - ((self.final_y[i] - y_min_plot) / (y_max_plot - y_min_plot)) * plot_h
            x2 = self.margin_l + (self.x_data[i+1] / self.total_length) * plot_w
            y2 = h - self.margin_b - ((self.final_y[i+1] - y_min_plot) / (y_max_plot - y_min_plot)) * plot_h
            painter.drawLine(int(x1), int(y1), int(x2), int(y2))

        # Draw Cursor Dots
        cx = self.margin_l + (self.cursor_x / self.total_length) * plot_w
        
        cursor_y_prior = np.interp(self.cursor_x, self.x_data, self.prior_y)
        cy_prior = h - self.margin_b - ((cursor_y_prior - y_min_plot) / (y_max_plot - y_min_plot)) * plot_h
        
        cursor_y_final = np.interp(self.cursor_x, self.x_data, self.final_y)
        cy_final = h - self.margin_b - ((cursor_y_final - y_min_plot) / (y_max_plot - y_min_plot)) * plot_h

        painter.setBrush(QBrush(QColor("red")))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(int(cx) - 5, int(cy_prior) - 5, 10, 10)
        painter.drawEllipse(int(cx) - 5, int(cy_final) - 5, 10, 10)


class TendonResponseDialog(QDialog):
    def __init__(self, model, initial_tendon_id=None, preview_load_data=None, parent=None):
        super().__init__(parent)
        self.model = model
        self.preview_load_data = preview_load_data
        
        apply_dialog_style(self)
        self.setWindowTitle("Tendon Response Form")
        self.resize(750, 650)
        
        self.local_unit = UnitConverter()
        
        self.x_array = []
        self.prior_array = []
        self.after_seat_array = []
        self.final_array = []
        self.tendon_area = 1.0

        self._build_ui()
        self._populate_initial_data(initial_tendon_id)

    def _build_ui(self):
        root = QVBoxLayout(self)
        
        top_grid = QGridLayout()
        
        # Tendon Object
        t_group = QGroupBox("Tendon Line Object")
        t_layout = QVBoxLayout(t_group)
        self.combo_tendon = QComboBox()
        self.combo_tendon.addItems([str(tid) for tid in sorted(self.model.tendons.keys())])
        self.combo_tendon.currentTextChanged.connect(self._recalculate_arrays)
        t_layout.addWidget(self.combo_tendon)
        top_grid.addWidget(t_group, 0, 0)
        
        # Load Pattern
        p_group = QGroupBox("Load Pattern")
        p_layout = QVBoxLayout(p_group)
        self.combo_pattern = QComboBox()
        p_layout.addWidget(self.combo_pattern)
        self.combo_pattern.currentTextChanged.connect(self._recalculate_arrays)
        top_grid.addWidget(p_group, 0, 1)

        # Distance at Cursor
        d_group = QGroupBox("Distance at Cursor")
        d_layout = QHBoxLayout(d_group)
        d_layout.addWidget(QLabel("Distance"))
        self.edit_distance = QLineEdit("0.0")
        self.edit_distance.editingFinished.connect(self._on_distance_typed)
        d_layout.addWidget(self.edit_distance)
        top_grid.addWidget(d_group, 0, 2)

        # Result Type
        r_group = QGroupBox("Result Type")
        r_layout = QHBoxLayout(r_group)
        self.rb_force = QRadioButton("Force")
        self.rb_stress = QRadioButton("Stress")
        self.rb_force.setChecked(True)
        self.rb_force.toggled.connect(self._update_readouts)
        r_layout.addWidget(self.rb_force)
        r_layout.addWidget(self.rb_stress)
        top_grid.addWidget(r_group, 1, 0)

        # Load Case / Combos (Disabled per parity with loads-only modeling)
        lc_group = QGroupBox("Load Case/Combo")
        lc_layout = QVBoxLayout(lc_group)
        lc_combo = QComboBox()
        lc_combo.setEnabled(False)
        lc_layout.addWidget(lc_combo)
        
        env_layout = QVBoxLayout()
        for txt in ["Envelope Max/Min", "Envelope Max", "Envelope Min", "Step"]:
            rb = QRadioButton(txt)
            rb.setEnabled(False)
            env_layout.addWidget(rb)
        lc_layout.addLayout(env_layout)
        top_grid.addWidget(lc_group, 1, 1, 2, 1)

        # Readouts
        read_group = QGroupBox("Load Pattern at Cursor")
        read_layout = QGridLayout(read_group)
        
        lbl_prior = QLabel("Prior to Seating")
        lbl_prior.setStyleSheet("color: #D32F2F; font-weight: bold;")
        self.out_prior = QLineEdit()
        self.out_prior.setReadOnly(True)
        read_layout.addWidget(lbl_prior, 0, 0)
        read_layout.addWidget(self.out_prior, 0, 1)

        lbl_after = QLabel("After Seating")
        lbl_after.setStyleSheet("color: #D32F2F; font-weight: bold;")
        self.out_after = QLineEdit()
        self.out_after.setReadOnly(True)
        read_layout.addWidget(lbl_after, 1, 0)
        read_layout.addWidget(self.out_after, 1, 1)

        lbl_final = QLabel("After Other Losses")
        lbl_final.setStyleSheet("color: #388E3C; font-weight: bold;")
        self.out_final = QLineEdit()
        self.out_final.setReadOnly(True)
        read_layout.addWidget(lbl_final, 2, 0)
        read_layout.addWidget(self.out_final, 2, 1)
        
        top_grid.addWidget(read_group, 1, 2)

        # Units
        u_group = QGroupBox("Units")
        u_layout = QVBoxLayout(u_group)
        self.combo_units = QComboBox()
        self.combo_units.addItems(["kN, m, C", "N, m, C", "N, mm, C"]) # Simplified for brevity
        self.combo_units.currentTextChanged.connect(self._on_unit_changed)
        u_layout.addWidget(self.combo_units)
        
        btn_layout = QHBoxLayout()
        btn_excel = QPushButton("Export To Excel...")
        btn_done = QPushButton("Done")
        btn_done.clicked.connect(self.accept)
        btn_layout.addWidget(btn_excel)
        btn_layout.addWidget(btn_done)
        u_layout.addLayout(btn_layout)
        top_grid.addWidget(u_group, 2, 0)

        root.addLayout(top_grid)

        # Canvas
        plot_group = QGroupBox("Tendon Response Plot")
        plot_layout = QVBoxLayout(plot_group)
        self.canvas = TendonResponsePlot()
        self.canvas.cursor_moved.connect(self._on_canvas_cursor_moved)
        plot_layout.addWidget(self.canvas)
        root.addWidget(plot_group)

    def _populate_initial_data(self, initial_tendon_id):
        if initial_tendon_id and str(initial_tendon_id) in [self.combo_tendon.itemText(i) for i in range(self.combo_tendon.count())]:
            self.combo_tendon.setCurrentText(str(initial_tendon_id))
        self._recalculate_arrays()

    def _on_unit_changed(self):
        self.local_unit.set_unit_system(self.combo_units.currentText())
        self._update_readouts()

    def _recalculate_arrays(self):
        tendon_id = int(self.combo_tendon.currentText()) if self.combo_tendon.currentText() else None
        tendon = self.model.tendons.get(tendon_id)
        if not tendon: return

        self.combo_pattern.blockSignals(True)
        self.combo_pattern.clear()
        
        patterns = []
        if hasattr(tendon, 'loads'):
            patterns = [ld['pattern'] for ld in tendon.loads]
            
        if self.preview_load_data and self.preview_load_data['pattern'] not in patterns:
            patterns.append(self.preview_load_data['pattern'])
            
        self.combo_pattern.addItems(patterns)
        
        if self.preview_load_data:
            idx = self.combo_pattern.findText(self.preview_load_data['pattern'])
            if idx >= 0:
                self.combo_pattern.setCurrentIndex(idx)
                
        self.combo_pattern.blockSignals(False)

        pat_name = self.combo_pattern.currentText()
        
        if self.preview_load_data and self.preview_load_data['pattern'] == pat_name:
            load_data = self.preview_load_data
        else:
            load_data = next((ld for ld in getattr(tendon, 'loads', []) if ld['pattern'] == pat_name), None)

        if not load_data or not tendon.layout_points:
            self.canvas.set_data([], [], [])
            return

        total_length = max(p['coord1'] for p in tendon.layout_points)
        self.tendon_area = tendon.tendon_section.area
        
        # Pass the tendon's max discretization length to perfectly sync with model.py
        max_disc = getattr(tendon, 'max_discretization_length', 1.524)
        evaluator = TendonEvaluator(tendon.layout_points, tendon.tendon_section, load_data, total_length, max_disc)

        # Hook directly into the evaluator's custom grid! No arbitrary looping.
        self.x_array = evaluator.discrete_x
        self.prior_array = []
        self.after_seat_array = []
        self.final_array = []

        for x in self.x_array:
            p_prior, p_after, p_final = evaluator.get_force_components(x)
            self.prior_array.append(p_prior)
            self.after_seat_array.append(p_after)
            self.final_array.append(p_final)

        self._update_readouts()
        
    def _update_readouts(self):
        if not self.x_array: return

        display_prior = self.prior_array
        display_final = self.final_array
        
        if self.rb_stress.isChecked():
            display_prior = [self.local_unit.to_display_pressure(v / self.tendon_area) for v in display_prior]
            display_final = [self.local_unit.to_display_pressure(v / self.tendon_area) for v in display_final]
        else:
            display_prior = [self.local_unit.to_display_force(v) for v in display_prior]
            display_final = [self.local_unit.to_display_force(v) for v in display_final]
            
        display_x = [self.local_unit.to_display_length(x) for x in self.x_array]
        
        # Send both lines to the canvas
        self.canvas.set_data(display_x, display_prior, display_final)
        self._on_canvas_cursor_moved(self.canvas.cursor_x)

    def _on_canvas_cursor_moved(self, cursor_x_display):
        if not self.x_array: return
        
        self.edit_distance.blockSignals(True)
        self.edit_distance.setText(f"{cursor_x_display:.4f}")
        self.edit_distance.blockSignals(False)

        # Convert back to SI to interpolate
        cursor_x_si = self.local_unit.from_display_length(cursor_x_display)
        
        val_prior = np.interp(cursor_x_si, self.x_array, self.prior_array)
        val_after = np.interp(cursor_x_si, self.x_array, self.after_seat_array)
        val_final = np.interp(cursor_x_si, self.x_array, self.final_array)

        if self.rb_stress.isChecked():
            val_prior = self.local_unit.to_display_pressure(val_prior / self.tendon_area)
            val_after = self.local_unit.to_display_pressure(val_after / self.tendon_area)
            val_final = self.local_unit.to_display_pressure(val_final / self.tendon_area)
        else:
            val_prior = self.local_unit.to_display_force(val_prior)
            val_after = self.local_unit.to_display_force(val_after)
            val_final = self.local_unit.to_display_force(val_final)

        self.out_prior.setText(f"{val_prior:.4f}")
        self.out_after.setText(f"{val_after:.4f}")
        self.out_final.setText(f"{val_final:.4f}")

    def _on_distance_typed(self):
        try:
            val = float(self.edit_distance.text())
            self.canvas.set_cursor_x(val)
        except ValueError:
            pass