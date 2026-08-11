"""
Tendon Geometry Dialog
=======================
SAP-parity "Tendon Data For Line Object" dialog + "Tendon Quick Start
Templates" sub-dialog + a small "Modify Axes" helper.

Scope (deliberate, per project ground rules):
  - This is DRAW / GEOMETRY-DEFINITION only. No stiffness contribution,
    no solver hookup, no canvas rendering yet.
  - Opens on a TendonObject that ALREADY EXISTS in model.tendons (created
    by CmdDrawTendon right after the 2-click draw, seeded with a default
    2-point straight layout). This same dialog is reused later for
    "Tendon Information..." on an already-placed tendon (double click /
    right-click properties) — same constructor, same flow.
  - Edits happen on a local working copy; nothing is written back onto
    the TendonObject until OK is pressed. Cancel leaves the tendon exactly
    as it was when the dialog opened.

Stubbed-for-now (explicitly, not silently):
  - Tendon Loads (combo/Add.../Show...) — disabled, "Coming soon."
  - Parabolic Calculator... — disabled/stub message. The main point table
    already covers Linear/Parabolic/Circular segment typing; building a
    second competing table editor blind (without canvas hookup) risks
    diverging data models.
  - Move Tendon... — disabled/stub message (needs canvas).
  - Mouse Pointer Location / Snap Option — fields present (SAP-parity,
    nothing hidden), but inert until canvas hookup exists.
  - Group Loaded By Tendon — display-only "ALL", disabled (load grouping
    not implemented).
  - Object Type — display-only "Current Tendon", disabled (no multi-
    object simultaneous edit yet).
"""

import copy
import math
import numpy as np
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QComboBox,
    QPushButton, QGroupBox, QFormLayout, QLineEdit, QMessageBox, QWidget,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QRadioButton, QButtonGroup, QDoubleSpinBox, QFrame, QSizePolicy,
    QSplitter
)
from PyQt6.QtGui import QColor, QPainter, QPen, QFont
from PyQt6.QtCore import Qt

from app.ui.theme import apply_dialog_style, COLORS

def _card_qss():
    """Rounded, lightly-bordered panel look for the top-level dialog
    sections — deliberately distinct from the flat/boxy SAP-style
    QGroupBox appearance this dialog used to have."""
    return (
        f"QGroupBox {{ border: 1px solid {COLORS['border']}; border-radius: 6px; "
        f"margin-top: 10px; padding-top: 6px; font-weight: 600; }}"
        f"QGroupBox::title {{ subcontrol-origin: margin; left: 10px; "
        f"padding: 0 4px; color: {COLORS['accent']}; }}"
    )

from PyQt6.QtWidgets import QStyledItemDelegate

class ComboBoxDelegate(QStyledItemDelegate):
    def __init__(self, items, parent=None):
        super().__init__(parent)
        self.items = items

    def createEditor(self, parent, option, index):
        editor = QComboBox(parent)
        editor.addItems(self.items)
        return editor

    def setEditorData(self, editor, index):
        text = index.model().data(index, Qt.ItemDataRole.EditRole)
        idx = editor.findText(text)
        if idx >= 0:
            editor.setCurrentIndex(idx)

    def setModelData(self, editor, model, index):
        model.setData(index, editor.currentText(), Qt.ItemDataRole.EditRole)

from PyQt6.QtGui import QPainterPath                                         

from PyQt6.QtGui import QPainterPath

from PyQt6.QtGui import QPainterPath, QPainter, QPen, QColor, QBrush
from PyQt6.QtCore import Qt
import math

class TendonProfileCanvas(QWidget):
    """
    QPainter plot of the tendon layout points with interactive pan, zoom,
    and a stabilized Y-axis to prevent floating-point label overlap.
    """

    N_TICKS = 4  

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(180)
        self.setStyleSheet(
            f"background-color: {COLORS['bg_panel']}; "
            f"border: 1px solid {COLORS['border']}; border-radius: 4px;")
        
        self.points = []
        self.slopes = None
        self.seg_types = None
        self.axis_label = "1-2"
        self.unit_abbrev = "m"

        self.zoom = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self._is_panning = False
        self._last_mouse = None

    def set_unit(self, unit_abbrev):
        self.unit_abbrev = unit_abbrev or "m"
        self.update()

    def set_data(self, points, axis_label, slopes=None, seg_types=None, unit_abbrev=None):
        self.points = points
        self.axis_label = axis_label
        self.slopes = slopes
        self.seg_types = seg_types
        if unit_abbrev is not None:
            self.unit_abbrev = unit_abbrev
        
        self.zoom = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self.update()

    def _axis_names(self):
        if "-" in self.axis_label:
            return self.axis_label.split("-")
        return "1", "2"

    @staticmethod
    def _nice_step(span, n_ticks):
        if span <= 1e-9:
            return 1.0
        raw = span / max(n_ticks, 1)
        mag = 10 ** math.floor(math.log10(raw))
        for m in (1, 2, 2.5, 5, 10):
            if raw <= m * mag:
                return m * mag
        return 10 * mag

    def wheelEvent(self, event):
        zoom_in = event.angleDelta().y() > 0
        factor = 1.15 if zoom_in else (1.0 / 1.15)
        
        new_zoom = max(0.1, min(self.zoom * factor, 50.0))
        actual_factor = new_zoom / self.zoom
        
        w, h = self.width(), self.height()
        margin_l, margin_r, margin_t, margin_b = 56, 54, 14, 42
        
        plot_w = w - margin_l - margin_r
        plot_h = h - margin_t - margin_b
        
        base_center_px = margin_l + plot_w / 2.0
        base_center_py = h - margin_b - plot_h / 2.0
        
        m_x = event.position().x()
        m_y = event.position().y()
        
        dx = m_x - base_center_px
        dy = m_y - base_center_py
        
        self.pan_x = dx - (dx - self.pan_x) * actual_factor
        self.pan_y = dy - (dy - self.pan_y) * actual_factor
        
        self.zoom = new_zoom
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_panning = True
            self._last_mouse = event.pos()

    def mouseMoveEvent(self, event):
        if self._is_panning and self._last_mouse:
            dx = event.pos().x() - self._last_mouse.x()
            dy = event.pos().y() - self._last_mouse.y()
            self.pan_x += dx
            self.pan_y += dy
            self._last_mouse = event.pos()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_panning = False

    def mouseDoubleClickEvent(self, event):
                                                             
        self.zoom = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        painter.setClipRect(self.rect())

        w, h = self.width(), self.height()
        margin_l, margin_r, margin_t, margin_b = 56, 54, 14, 42 
        x_name, y_name = self._axis_names()

        if len(self.points) < 2:
            painter.setPen(QPen(QColor(COLORS["text_secondary"]), 1))
            painter.drawText(margin_l, h // 2, "No layout points yet.")
            return

        xs = [p[0] for p in self.points]
        ys = [p[1] for p in self.points]
        x_min, x_max = min(xs), max(xs)
        y_min, y_max = min(ys + [0.0]), max(ys + [0.0])

        range_x = max(1e-9, x_max - x_min)
        
        range_y = max(0.2, y_max - y_min) 

        plot_w = w - margin_l - margin_r
        plot_h = h - margin_t - margin_b

        base_scale = min(plot_w / range_x, plot_h / range_y)
        scale = base_scale * self.zoom

        offset_x = margin_l + (plot_w - range_x * scale) / 2.0 + self.pan_x
        offset_y = margin_b + (plot_h - range_y * scale) / 2.0 - self.pan_y

        def to_px(x, y):
            px = offset_x + (x - x_min) * scale
            py = h - offset_y - (y - y_min) * scale
            return px, py

        data_w = plot_w / scale
        data_h = plot_h / scale

        px_min_x_data = x_min - (offset_x - margin_l) / scale
        px_max_x_data = px_min_x_data + data_w

        py_min_y_data = y_min - (offset_y - margin_b) / scale
        py_max_y_data = py_min_y_data + data_h

        step_x = self._nice_step(data_w, self.N_TICKS)
        step_y = self._nice_step(data_h, self.N_TICKS)

        gx = math.floor(px_min_x_data / step_x) * step_x
        while gx <= px_max_x_data + 1e-9:
            px, _ = to_px(gx, 0)
            if margin_l <= px <= w - margin_r:
                painter.setPen(QPen(QColor(COLORS["border"]), 1, Qt.PenStyle.DotLine))
                painter.drawLine(int(px), int(margin_t), int(px), int(h - margin_b))
                
                tick_str = self._format_tick(gx)
                painter.setPen(QPen(QColor(COLORS["text_secondary"]), 1))
                
                offset = 4 if abs(gx) < 1e-9 else 14 
                painter.drawText(int(px) - offset, h - margin_b + 18, tick_str)
            gx += step_x

        gy = math.floor(py_min_y_data / step_y) * step_y
        while gy <= py_max_y_data + 1e-9:
            _, py = to_px(0, gy)
            if margin_t <= py <= h - margin_b:
                painter.setPen(QPen(QColor(COLORS["border"]), 1, Qt.PenStyle.DotLine))
                painter.drawLine(int(margin_l), int(py), int(w - margin_r), int(py))
                
                tick_str = self._format_tick(gy)
                painter.setPen(QPen(QColor(COLORS["text_secondary"]), 1))
                painter.drawText(int(w - margin_r + 6), int(py) + 4, tick_str)
            gy += step_y

        if py_min_y_data <= 0.0 <= py_max_y_data:
            painter.setPen(QPen(QColor(COLORS["text_secondary"]), 1.2))
            _, py_zero = to_px(0, 0.0)
            painter.drawLine(int(margin_l), int(py_zero), int(w - margin_r), int(py_zero))

        painter.setPen(QPen(QColor(COLORS["text_secondary"]), 1))
        
        painter.drawText(int(margin_l), h - 6, f"{x_name} Coord ({self.unit_abbrev})")
        painter.save()
        painter.translate(14, margin_t + plot_h / 2 + 24)
        painter.rotate(-90)
        painter.drawText(0, 0, f"{y_name} Coord ({self.unit_abbrev})")
        painter.restore()

        painter.setPen(QPen(QColor(COLORS["accent"]), 2.2))
        path = QPainterPath()
        px_start, py_start = to_px(self.points[0][0], self.points[0][1])
        path.moveTo(px_start, py_start)

        for i in range(len(self.points) - 1):
            x0, y0 = self.points[i]
            x1, y1 = self.points[i + 1]

            is_linear = True
            if self.axis_label != "2-3":
                if self.seg_types and len(self.seg_types) > i + 1:
                    if self.seg_types[i + 1] in ("Parabolic", "Circular"):
                        is_linear = False
                elif self.slopes:
                    is_linear = False

            if is_linear or not self.slopes or len(self.slopes) <= i + 1:
                px1, py1 = to_px(x1, y1)
                path.lineTo(px1, py1)
                continue

            m0 = self.slopes[i]
            m1 = self.slopes[i + 1]
            dx = x1 - x0
            if dx == 0:
                px1, py1 = to_px(x1, y1)
                path.lineTo(px1, py1)
                continue

            cp1_x = x0 + dx / 3.0
            cp1_y = y0 + m0 * (dx / 3.0)
            cp2_x = x1 - dx / 3.0
            cp2_y = y1 - m1 * (dx / 3.0)

            px1, py1 = to_px(cp1_x, cp1_y)
            px2, py2 = to_px(cp2_x, cp2_y)
            px3, py3 = to_px(x1, y1)
            path.cubicTo(px1, py1, px2, py2, px3, py3)

        painter.drawPath(path)

        for i, (x, y) in enumerate(self.points):
            px, py = to_px(x, y)
            
            color = QColor("#0288D1") if i == 0 else (
                QColor("#D32F2F") if i == len(self.points) - 1 else QColor("black"))
            
            painter.setBrush(QBrush(color))
            painter.setPen(QPen(QColor(COLORS["bg_panel"]), 1.5))
            painter.drawEllipse(int(px) - 4, int(py) - 4, 8, 8)

        painter.setPen(QPen(QColor("black"), 1.2))
        
        triad_x = margin_l + 15
        triad_y = h - margin_b - 15
        arrow_len = 25
        
        painter.drawLine(triad_x, triad_y, triad_x + arrow_len, triad_y)
        painter.drawLine(triad_x + arrow_len, triad_y, triad_x + arrow_len - 4, triad_y - 3)
        painter.drawLine(triad_x + arrow_len, triad_y, triad_x + arrow_len - 4, triad_y + 3)
        painter.drawText(triad_x + arrow_len + 6, triad_y + 4, x_name)
        
        painter.drawLine(triad_x, triad_y, triad_x, triad_y - arrow_len)
        painter.drawLine(triad_x, triad_y - arrow_len, triad_x - 3, triad_y - arrow_len + 4)
        painter.drawLine(triad_x, triad_y - arrow_len, triad_x + 3, triad_y - arrow_len + 4)
        painter.drawText(triad_x - 4, triad_y - arrow_len - 6, y_name)

    def _format_tick(self, val):
        """Format tick values to avoid scientific notation for standard ranges."""
                                              
        if abs(val) < 1e-9:
            return "0"
                                                                            
        if abs(val - round(val)) < 1e-9:
            return f"{int(round(val))}"
                                                                    
        return f"{val:.5f}".rstrip('0').rstrip('.')

class ModifyAxesDialog(QDialog):
    def __init__(self, plane="1-2", angle=0.0, parent=None):
        super().__init__(parent)
        apply_dialog_style(self)
        self.setWindowTitle("Modify Tendon Local Axes")
        self.setFixedWidth(320)

        root = QVBoxLayout(self)
        form = QFormLayout()

        self.plane_combo = QComboBox()
        self.plane_combo.addItems(["1-2", "1-3"])
        idx = self.plane_combo.findText(plane)
        if idx >= 0:
            self.plane_combo.setCurrentIndex(idx)
        form.addRow("Plane:", self.plane_combo)

        self.angle_spin = QDoubleSpinBox()
        self.angle_spin.setRange(-360.0, 360.0)
        self.angle_spin.setDecimals(2)
        self.angle_spin.setSuffix(" deg")
        self.angle_spin.setValue(float(angle))
        form.addRow("Angle:", self.angle_spin)

        root.addLayout(form)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        ok_btn = QPushButton("OK")
        ok_btn.setObjectName("primary")
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("secondary")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        root.addLayout(btn_row)

    def get_plane(self):
        return self.plane_combo.currentText()

    def get_angle(self):
        return self.angle_spin.value()

class TendonQuickStartDialog(QDialog):
    """
    Generates a starting layout_points list for one of SAP's 9 quick-start
    profile shapes. This is a convenience SEED, exactly like SAP's own
    Quick Start tool — the resulting points land in the main table where
    they can (and typically should) be fine-tuned to the project's exact
    eccentricities.

    Sag/offset magnitudes here are a reasonable geometric default
    (fraction of span length), not derived from section depth or cover —
    there's no rebar/section-depth data plumbed through yet. Adjust the
    generated Coord 2 values in the main table as needed.
    """

    TEMPLATES = [
        ("straight1", "Straight Tendon 1"),
        ("bends1", "Straight Tendon With Bends 1"),
        ("bends2", "Straight Tendon With Bends 2"),
        ("parabolic1", "Parabolic Tendon 1"),
        ("parabolic2", "Parabolic Tendon 2"),
        ("parabolic3", "Parabolic Tendon 3"),
        ("parabolic4", "Parabolic Tendon 4"),
        ("circular1", "Circular Tendon 1"),
        ("circular2", "Circular Tendon 2"),
    ]

    def __init__(self, total_length, plane="1-2", angle=0.0, max_spans=8, parent=None):
        super().__init__(parent)
        apply_dialog_style(self)
        self.setWindowTitle("Tendon Quick Start Templates")
        self.resize(560, 480)
        self.total_length = float(total_length)
        self.result_points = None

        root = QVBoxLayout(self)
        root.setSpacing(10)

        top_row = QHBoxLayout()

        plane_group = QGroupBox("Define Tendon In This Tendon Line Object Local Plane")
        pg_layout = QHBoxLayout(plane_group)
        pg_layout.addWidget(QLabel("Plane:"))
        self.plane_combo = QComboBox()
        self.plane_combo.addItems(["1-2", "1-3"])
        idx = self.plane_combo.findText(plane)
        if idx >= 0:
            self.plane_combo.setCurrentIndex(idx)
        pg_layout.addWidget(self.plane_combo)
        pg_layout.addWidget(QLabel("Angle:"))
        self.angle_edit = QLineEdit(f"{angle:.2f}")
        self.angle_edit.setFixedWidth(60)
        pg_layout.addWidget(self.angle_edit)
        modify_btn = QPushButton("Modify Axes...")
        modify_btn.clicked.connect(self._modify_axes)
        pg_layout.addWidget(modify_btn)
        top_row.addWidget(plane_group, stretch=3)

        spans_group = QGroupBox("Number of Spans")
        sg_layout = QVBoxLayout(spans_group)
        self.spans_combo = QComboBox()
        self.spans_combo.addItems([str(n) for n in range(1, max(max_spans, 1) + 1)])
        sg_layout.addWidget(self.spans_combo)
        top_row.addWidget(spans_group, stretch=1)

        root.addLayout(top_row)

        select_group = QGroupBox("Select A Quick Start Option")
        sel_layout = QGridLayout(select_group)                         
        self.radio_group = QButtonGroup(self)
        self.radios = {}
        
        row, col = 0, 0
        for key, label in self.TEMPLATES:
            rb = QRadioButton(label)
            self.radios[key] = rb
            self.radio_group.addButton(rb)
            sel_layout.addWidget(rb, row, col)
            
            col += 1
            if col > 1:  
                col = 0
                row += 1
                
        self.radios["straight1"].setChecked(True)
        root.addWidget(select_group)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        ok_btn = QPushButton("OK")
        ok_btn.setObjectName("primary")
        ok_btn.clicked.connect(self._on_ok)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("secondary")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        root.addLayout(btn_row)

    def _modify_axes(self):
        try:
            angle = float(self.angle_edit.text() or 0.0)
        except ValueError:
            angle = 0.0
        dlg = ModifyAxesDialog(self.plane_combo.currentText(), angle, self)
        if dlg.exec():
            self.plane_combo.setCurrentText(dlg.get_plane())
            self.angle_edit.setText(f"{dlg.get_angle():.2f}")

    def _selected_key(self):
        for key, rb in self.radios.items():
            if rb.isChecked():
                return key
        return "straight1"

    def _on_ok(self):
        num_spans = int(self.spans_combo.currentText())
        key = self._selected_key()
        self.result_points = self._generate(key, num_spans, self.total_length)
        self.accept()

    def _generate(self, key, num_spans, L):
        span_len = L / num_spans
        pts = []
        pid = 1

        def add(coord1, coord2, seg_type):
            nonlocal pid
            pts.append({
                "id": pid, "segment_type": seg_type, "coord1": round(coord1, 6),
                "coord2_type": "Specified", "coord2": round(coord2, 6),
                "coord3_type": "Specified", "coord3": 0.0, "slope": 0.0,
            })
            pid += 1

        add(0.0, 0.0, "Start of Tendon")

        if key == "straight1":
            for s in range(1, num_spans + 1):
                add(span_len * s, 0.0, "Linear")

        elif key in ("bends1", "bends2"):
            sag = -span_len * 0.06
            hog = span_len * 0.03 if key == "bends2" else 0.0
            for s in range(num_spans):
                mid = span_len * s + span_len / 2.0
                end = span_len * (s + 1)
                add(mid, sag if s % 2 == 0 else -sag + hog, "Linear")
                add(end, 0.0, "Linear")

        elif key == "parabolic1":
                                                           
            sag = -span_len * 0.06
            for s in range(num_spans):
                start = span_len * s
                mid = start + span_len / 2.0
                end = start + span_len
                add(mid, sag, "Parabolic")
                add(end, 0.0, "Parabolic")

        elif key == "parabolic2":
                                                                       
            sag = -span_len * 0.06
            rise = span_len * 0.02
            for s in range(num_spans):
                start = span_len * s
                q1 = start + span_len * 0.25
                mid = start + span_len * 0.5
                q3 = start + span_len * 0.75
                end = start + span_len
                add(q1, rise, "Parabolic")
                add(mid, sag, "Parabolic")
                add(q3, rise, "Parabolic")
                add(end, 0.0, "Parabolic")

        elif key == "parabolic3":
                                                                    
            sag = -span_len * 0.06
            for s in range(num_spans):
                start = span_len * s
                p2 = start + span_len * 0.65
                end = start + span_len
                add(p2, sag, "Parabolic")
                add(end, 0.0, "Parabolic")

        elif key == "parabolic4":
                                                                              
            hog = span_len * 0.06
            for s in range(num_spans):
                start = span_len * s
                mid = start + span_len / 2.0
                end = start + span_len
                add(mid, hog, "Parabolic")
                add(end, 0.0, "Parabolic")

        elif key in ("circular1", "circular2"):
                                                                          
            sag = -span_len * (0.05 if key == "circular1" else 0.08)
            n_samples = 4
            for s in range(num_spans):
                start = span_len * s
                for k in range(1, n_samples + 1):
                    frac = k / n_samples
                    x = start + span_len * frac
                                                                               
                    y = sag * math.sin(math.pi * frac)
                    add(x, y, "Circular")

        else:
            add(L, 0.0, "Linear")

        if abs(pts[-1]["coord1"] - L) > 1e-6:
            pts[-1]["coord1"] = round(L, 6)

        return pts

class TendonGeometryDialog(QDialog):
    """
    Full SAP-parity tendon geometry dialog. Works on a local (working-copy)
    dataset; nothing touches the real TendonObject until OK is pressed.

    Usage (both draw-then-configure and later "Tendon Information..." edit
    use the exact same call):

        dlg = TendonGeometryDialog(tendon, model, parent=self)
        if dlg.exec():
            ...   # tendon has already been updated in place
    """

    SEGMENT_TYPES = ["Linear", "Parabolic", "Circular"]

    def __init__(self, tendon, model, parent=None):
        super().__init__(parent)
        self.tendon = tendon
        self.model = model
        apply_dialog_style(self)

        self.setWindowTitle(f"Tendon Data For Line Object {tendon.id}")
        self.resize(1380, 500)                                                      

        self.working_points = copy.deepcopy(tendon.layout_points)
        self.working_plane = tendon.plane
        self.working_angle = tendon.local_axis_angle
        self.working_coord_system = getattr(tendon, "coordinate_system", "Local")
        self.working_max_disc = tendon.max_discretization_length
        self.working_modeling_option = tendon.modeling_option
        self.working_prestress_type = tendon.prestress_type
        self.working_section = tendon.tendon_section
        self.working_loads = copy.deepcopy(getattr(tendon, "loads", []))
        
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(14, 14, 14, 14)

        right_col_widget = QWidget()
        right_col_widget.setLayout(self._build_right_column())
        right_col_widget.setStyleSheet(_card_qss())

        body = QSplitter(Qt.Orientation.Horizontal)
        body.setChildrenCollapsible(False)
        body.setHandleWidth(10)
        body.addWidget(self._build_layout_group())
        body.addWidget(self._build_display_group())
        body.addWidget(right_col_widget)
        body.setStretchFactor(0, 5)
        body.setStretchFactor(1, 4)
        body.setStretchFactor(2, 6)
        root.addWidget(body)

        bottom = QHBoxLayout()
        bottom.addStretch()
        ok_btn = QPushButton("OK")
        ok_btn.setObjectName("primary")
        ok_btn.setFixedWidth(90)
        ok_btn.clicked.connect(self._on_ok)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("secondary")
        cancel_btn.setFixedWidth(90)
        cancel_btn.clicked.connect(self.reject)
        bottom.addWidget(ok_btn)
        bottom.addWidget(cancel_btn)
        root.addLayout(bottom)

        self.local_scale = self._parse_length_scale(self.units_combo.currentText())
        for pt in self.working_points:
            pt["coord1"] *= self.local_scale
            pt["coord2"] *= self.local_scale
            pt["coord3"] = pt.get("coord3", 0.0) * self.local_scale
        self.working_max_disc *= self.local_scale

        self.units_combo.currentIndexChanged.connect(self._on_unit_changed)

        self._update_unit_labels()
        self._refresh_table()
        self._refresh_plot()
        self._refresh_loads_combo()
                                                                        
    def _parse_length_scale(self, unit_str):
        parts = unit_str.replace(" ", "").split(",")
        if len(parts) > 1:
            u = parts[1]
            if u == "m": return 1.0
            if u == "mm": return 1000.0
            if u == "cm": return 100.0
            if u == "ft": return 3.28084
            if u == "in": return 39.3701
        return 1.0

    def _length_unit_abbrev(self, unit_str):
        """Second field of the 'kN, m, C' style string, e.g. 'm', 'mm', 'ft'."""
        parts = unit_str.replace(" ", "").split(",")
        return parts[1] if len(parts) > 1 else "m"

    def _update_unit_labels(self):
        """Push the current length unit into every label that displays one —
        the editor-row headers, table headers, discretization row, and the
        plot canvas's axis titles. Previously these stayed hardcoded at 'm'
        no matter what was picked in the Units combo."""
        u = self._length_unit_abbrev(self.units_combo.currentText())
        self.coord1_hdr.setText(f"1 Coord ({u})")
        self.coord2_hdr.setText(f"2 Coord ({u})")
        self.coord3_hdr.setText(f"3 Coord ({u})")
        self.disc_hdr.setText(f"Length ({u}):")
        self.table.setHorizontalHeaderLabels(
            ["Point ID", "Segment Type", f"1 Coord ({u})", f"2 Coord ({u})", f"3 Coord ({u})"])
        self.plot_canvas.set_unit(u)

    def _on_unit_changed(self):
        new_scale = self._parse_length_scale(self.units_combo.currentText())
        ratio = new_scale / self.local_scale

        if abs(ratio - 1.0) >= 1e-12:
            for pt in self.working_points:
                pt["coord1"] *= ratio
                pt["coord2"] *= ratio
                pt["coord3"] *= ratio

            self.working_max_disc *= ratio
            self.disc_spin.setValue(self.disc_spin.value() * ratio)

            self.local_scale = new_scale

            self._refresh_table()

        self._update_unit_labels()
        self._refresh_plot()
        self._refresh_loads_combo()                     

    def _build_layout_group(self):
        layout_group = QGroupBox("Tendon Layout Data")
        layout_group.setStyleSheet(_card_qss())
        lg = QVBoxLayout(layout_group)

        editor_row = QGridLayout()
        editor_row.addWidget(QLabel("Point ID"), 0, 0)
        editor_row.addWidget(QLabel("Segment Type"), 0, 1)
        self.coord1_hdr = QLabel("1 Coord (m)")
        self.coord2_hdr = QLabel("2 Coord (m)")
        self.coord3_hdr = QLabel("3 Coord (m)")
        editor_row.addWidget(self.coord1_hdr, 0, 2)
        editor_row.addWidget(self.coord2_hdr, 0, 3)
        editor_row.addWidget(self.coord3_hdr, 0, 4)

        self.point_id_combo = QComboBox()
        self.point_id_combo.currentIndexChanged.connect(self._on_point_id_combo_changed)
        editor_row.addWidget(self.point_id_combo, 1, 0)

        self.segment_combo = QComboBox()
        self.segment_combo.addItems(self.SEGMENT_TYPES)
        editor_row.addWidget(self.segment_combo, 1, 1)

        self.coord1_spin = QDoubleSpinBox()
        self.coord2_spin = QDoubleSpinBox()
        self.coord3_spin = QDoubleSpinBox()
        for spin in (self.coord1_spin, self.coord2_spin, self.coord3_spin):
            spin.setRange(-100000.0, 100000.0)
            spin.setDecimals(4)
        editor_row.addWidget(self.coord1_spin, 1, 2)
        editor_row.addWidget(self.coord2_spin, 1, 3)
        editor_row.addWidget(self.coord3_spin, 1, 4)
        lg.addLayout(editor_row)

        table_row = QHBoxLayout()
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Point ID", "Segment Type", "1 Coord (m)", "2 Coord (m)", "3 Coord (m)"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._on_table_row_selected)
        table_row.addWidget(self.table, stretch=1)

        side_btns = QVBoxLayout()
        self.btn_insert_above = QPushButton("Insert Above")
        self.btn_insert_below = QPushButton("Insert Below")
        self.btn_modify = QPushButton("Modify")
        self.btn_delete = QPushButton("Delete")
        self.btn_delete_all = QPushButton("Delete All")
        self.btn_delete_all.setObjectName("danger")

        self.btn_insert_above.clicked.connect(lambda: self._insert_point(above=True))
        self.btn_insert_below.clicked.connect(lambda: self._insert_point(above=False))
        self.btn_modify.clicked.connect(self._modify_point)
        self.btn_delete.clicked.connect(self._delete_point)
        self.btn_delete_all.clicked.connect(self._delete_all_points)

        for b in (self.btn_insert_above, self.btn_insert_below, self.btn_modify,
                  self.btn_delete, self.btn_delete_all):
            side_btns.addWidget(b)
        side_btns.addStretch()
        table_row.addLayout(side_btns)

        lg.addLayout(table_row, stretch=1)                                       

        note = QLabel(
            "Notes: 1. Parabolic and circular 'intermediate point' segments use points "
            "(n-1), (n) and (n+1).  2. Parabolic and circular 'end point' segments use "
            "points (n-2), (n-1) and (n).")
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 8pt;")
        lg.addWidget(note)

        return layout_group

    def _build_display_group(self):
        display_group = QGroupBox("Tendon Layout Display")
        display_group.setStyleSheet(_card_qss())
        dg = QVBoxLayout(display_group)

        self.plot_canvas = TendonProfileCanvas()
        dg.addWidget(self.plot_canvas, stretch=1)                                        

        hint = QLabel("Double Click Picture For Expanded Display")
        hint.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 8pt;")
        dg.addWidget(hint)

        display_bottom = QHBoxLayout()

        axes_group = QGroupBox("Tendon Layout Display Options")
        ag = QVBoxLayout(axes_group)
        self.axis_group = QButtonGroup(self)
        self.rb_12 = QRadioButton("Show 1-2 Axes")
        self.rb_13 = QRadioButton("Show 1-3 Axes")
        self.rb_23 = QRadioButton("Show 2-3 Axes")
        self.rb_12.setChecked(True)
        for rb in (self.rb_12, self.rb_13, self.rb_23):
            self.axis_group.addButton(rb)
            rb.toggled.connect(self._refresh_plot)
            ag.addWidget(rb)
        display_bottom.addWidget(axes_group)

        snap_group = QGroupBox("Snap Option")
        sg = QVBoxLayout(snap_group)
        self.snap_group_btns = QButtonGroup(self)
        self.rb_no_snap = QRadioButton("No Snap")
        self.rb_snap_tendon = QRadioButton("Snap To Tendon")
        self.rb_snap_tendon.setChecked(True)
        for rb in (self.rb_no_snap, self.rb_snap_tendon):
            self.snap_group_btns.addButton(rb)
            sg.addWidget(rb)
        snap_group.setToolTip("Used when editing via the 3D canvas — not yet linked.")
        snap_group.setEnabled(False)
        display_bottom.addWidget(snap_group)

        dg.addLayout(display_bottom)

        btn_row = QHBoxLayout()
        refresh_btn = QPushButton("Refresh Plot")
        refresh_btn.clicked.connect(self._refresh_plot)
        show_table_btn = QPushButton("Show Table...")
        show_table_btn.clicked.connect(self._focus_table)
        btn_row.addWidget(refresh_btn)
        btn_row.addWidget(show_table_btn)
        dg.addLayout(btn_row)

        units_row = QHBoxLayout()
        units_row.addWidget(QLabel("Units:"))
        self.units_combo = QComboBox()
        self.units_combo.addItems(["kN, m, C", "N, m, C", "N, mm, C", "Tonf, m, C", "kgf, m, C", "kip, ft, F", "kip, in, F"])
        
        from core.units import unit_registry
        idx = self.units_combo.findText(unit_registry.current_unit_label)
        if idx >= 0: self.units_combo.setCurrentIndex(idx)

        units_row.addWidget(self.units_combo)
        units_row.addStretch()
        dg.addLayout(units_row)

        return display_group
                                                                        
    def _build_right_column(self):
        main_col = QHBoxLayout()
        col1 = QVBoxLayout()
        col2 = QVBoxLayout()

        end_group = QGroupBox("Tendon End Point Objects")
        eg = QFormLayout(end_group)
        i_lbl = QLabel(str(self.tendon.node_i.id))
        i_lbl.setStyleSheet("background-color:#0288D1; color:white; padding:2px 6px; border-radius:3px;")
        j_lbl = QLabel(str(self.tendon.node_j.id))
        j_lbl.setStyleSheet("background-color:#D32F2F; color:white; padding:2px 6px; border-radius:3px;")
        eg.addRow("I-End:", i_lbl)
        eg.addRow("J-End:", j_lbl)
        col1.addWidget(end_group)

        sec_group = QGroupBox("Tendon Section")
        sgl = QVBoxLayout(sec_group)
        sec_row = QHBoxLayout()
        self.section_combo = QComboBox()
        self._refresh_section_combo()
        sec_row.addWidget(self.section_combo, stretch=1)
        sgl.addLayout(sec_row)
        sec_btn_row = QHBoxLayout()
        add_sec_btn = QPushButton("Add...")
        add_sec_btn.clicked.connect(self._add_section)
        show_sec_btn = QPushButton("Show...")
        show_sec_btn.clicked.connect(self._show_sections)
        sec_btn_row.addWidget(add_sec_btn)
        sec_btn_row.addWidget(show_sec_btn)
        sgl.addLayout(sec_btn_row)
        col1.addWidget(sec_group)

        model_group = QGroupBox("Analysis Modeling / Prestress")
        mgl = QFormLayout(model_group)
        self.modeling_combo = QComboBox()
        self.modeling_combo.addItems(["Loads", "Elements"])
        self.modeling_combo.setCurrentText(self.working_modeling_option)
        mgl.addRow("Model As:", self.modeling_combo)
        self.prestress_combo = QComboBox()
        self.prestress_combo.addItems(["Prestress", "Post-Tension"])
        self.prestress_combo.setCurrentText(self.working_prestress_type)
        mgl.addRow("Type:", self.prestress_combo)
        col1.addWidget(model_group)

        loads_group = QGroupBox("Tendon Loads")
        lgl = QVBoxLayout(loads_group)
        self.loads_combo = QComboBox()
        self._refresh_loads_combo()
        lgl.addWidget(self.loads_combo)

        loads_btn_row = QHBoxLayout()
        add_load_btn = QPushButton("Add...")
        add_load_btn.clicked.connect(self._add_tendon_load)
        show_load_btn = QPushButton("Show...")
        show_load_btn.clicked.connect(self._show_tendon_load)
        loads_btn_row.addWidget(add_load_btn)
        loads_btn_row.addWidget(show_load_btn)
        lgl.addLayout(loads_btn_row)
        col1.addWidget(loads_group)

        axis_group = QGroupBox("Tendon Local Axes Angle")
        axl = QFormLayout(axis_group)
        angle_row = QHBoxLayout()
        self.angle_edit = QLineEdit(f"{self.working_angle:.2f}")
        self.angle_edit.setReadOnly(True)
        angle_row.addWidget(self.angle_edit)
        modify_axes_btn = QPushButton("Modify...")
        modify_axes_btn.clicked.connect(self._modify_axes)
        angle_row.addWidget(modify_axes_btn)
        axl.addRow("Angle:", angle_row)
        col1.addWidget(axis_group)

        quickstart_group = QGroupBox("Layout Tools")
        qg = QVBoxLayout(quickstart_group)
        quick_start_btn = QPushButton("Quick Start...")
        quick_start_btn.clicked.connect(self._quick_start)
        qg.addWidget(quick_start_btn)
        parabolic_btn = QPushButton("Parabolic Calculator...")
        parabolic_btn.clicked.connect(self._parabolic_calculator_stub)
        qg.addWidget(parabolic_btn)
        col2.addWidget(quickstart_group)

        disc_group = QGroupBox("Max. Tendon Discretization")
        dgl = QFormLayout(disc_group)
        self.disc_spin = QDoubleSpinBox()
        self.disc_spin.setRange(0.01, 1000.0)
        self.disc_spin.setDecimals(3)
        self.disc_spin.setValue(self.working_max_disc)
        self.disc_hdr = QLabel("Length (m):")
        dgl.addRow(self.disc_hdr, self.disc_spin)
        col2.addWidget(disc_group)

        group_loaded = QGroupBox("Group Loaded By Tendon")
        glg = QVBoxLayout(group_loaded)
        group_combo = QComboBox()
        group_combo.addItem("ALL")
        glg.addWidget(group_combo)
        group_loaded.setToolTip("Coming soon — load-group targeting isn't implemented yet.")
        group_loaded.setEnabled(False)
        col2.addWidget(group_loaded)

        coord_group = QGroupBox("Coordinate System")
        cgl = QVBoxLayout(coord_group)
        self.coord_combo = QComboBox()
        self.coord_combo.addItems(["Local", "Global"])
        self.coord_combo.setCurrentText(self.working_coord_system)
        cgl.addWidget(self.coord_combo)
        col2.addWidget(coord_group)

        obj_type_group = QGroupBox("Object Type")
        ogl = QVBoxLayout(obj_type_group)
        obj_combo = QComboBox()
        obj_combo.addItem("Current Tendon")
        ogl.addWidget(obj_combo)
        obj_type_group.setEnabled(False)
        col2.addWidget(obj_type_group)

        move_group = QGroupBox("Move")
        mvl = QVBoxLayout(move_group)
        move_btn = QPushButton("Move Tendon...")
        move_btn.clicked.connect(self._move_tendon_stub)
        mvl.addWidget(move_btn)
        col2.addWidget(move_group)

        col1.addStretch()
        col2.addStretch()

        main_col.addLayout(col1)
        main_col.addLayout(col2)
        return main_col
    
    def _refresh_table(self):
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.working_points))
        self.point_id_combo.blockSignals(True)
        self.point_id_combo.clear()

        for row, pt in enumerate(self.working_points):
                                                                                                  
            id_item = QTableWidgetItem(str(pt["id"]))
            id_item.setFlags(id_item.flags() & ~Qt.ItemFlag.ItemIsEditable & ~Qt.ItemFlag.ItemIsSelectable)
            self.table.setItem(row, 0, id_item)
            
            self.table.setItem(row, 1, QTableWidgetItem(pt["segment_type"]))
            self.table.setItem(row, 2, QTableWidgetItem(f"{pt['coord1']:.4f}"))
            self.table.setItem(row, 3, QTableWidgetItem(f"{pt['coord2']:.4f}"))
            self.table.setItem(row, 4, QTableWidgetItem(f"{pt.get('coord3', 0.0):.4f}"))
            
            if row == 0:
                self.table.item(row, 0).setBackground(QColor("#0288D1"))
                self.table.item(row, 0).setForeground(QColor("white"))
            elif row == len(self.working_points) - 1:
                self.table.item(row, 0).setBackground(QColor("#D32F2F"))
                self.table.item(row, 0).setForeground(QColor("white"))
                
            self.point_id_combo.addItem(str(pt["id"]))

        self.point_id_combo.blockSignals(False)
        self.table.blockSignals(False)
        if self.working_points:
            self.table.selectRow(0)

    def _current_row(self):
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        return rows[0].row() if rows else -1

    def _on_table_row_selected(self):
        row = self._current_row()
        if row < 0 or row >= len(self.working_points):
            return
        pt = self.working_points[row]
        self.point_id_combo.blockSignals(True)
        self.point_id_combo.setCurrentIndex(row)
        self.point_id_combo.blockSignals(False)

        is_start = (row == 0)
        self.segment_combo.setEnabled(not is_start)
        self.coord1_spin.setEnabled(not is_start)
        self.btn_delete.setEnabled(not is_start)
        self.btn_insert_above.setEnabled(not is_start)

        if pt["segment_type"] in self.SEGMENT_TYPES:
            self.segment_combo.setCurrentText(pt["segment_type"])
        self.coord1_spin.setValue(pt["coord1"])
        self.coord2_spin.setValue(pt["coord2"])
        self.coord3_spin.setValue(pt.get("coord3", 0.0))

    def _on_point_id_combo_changed(self, index):
        if 0 <= index < self.table.rowCount():
            self.table.selectRow(index)

    def _renumber(self):
        self.working_points.sort(key=lambda p: p["coord1"])
        for i, pt in enumerate(self.working_points):
            pt["id"] = i + 1
        if self.working_points:
            self.working_points[0]["segment_type"] = "Start of Tendon"
            self.working_points[0]["coord1"] = 0.0

    def _insert_point(self, above: bool):
        row = self._current_row()
        if row < 0:
            row = len(self.working_points) - 1
        new_pt = {
            "id": 0, "segment_type": self.segment_combo.currentText(),
            "coord1": self.coord1_spin.value(),
            "coord2_type": "Specified", "coord2": self.coord2_spin.value(),
            "coord3_type": "Specified", "coord3": self.coord3_spin.value(),
            "slope": 0.0,
        }
        insert_at = row if above else row + 1
        self.working_points.insert(insert_at, new_pt)
        self._renumber()
        self._refresh_table()
        self._refresh_plot()

    def _modify_point(self):
        row = self._current_row()
        if row < 0 or row >= len(self.working_points):
            return
        pt = self.working_points[row]
        if row != 0:
            pt["segment_type"] = self.segment_combo.currentText()
            pt["coord1"] = self.coord1_spin.value()
        pt["coord2"] = self.coord2_spin.value()
        pt["coord3"] = self.coord3_spin.value()
        self._renumber()
        self._refresh_table()
        self._refresh_plot()

    def _delete_point(self):
        row = self._current_row()
        if row <= 0 or row >= len(self.working_points):
            return
        if len(self.working_points) <= 2:
            QMessageBox.warning(self, "Cannot Delete",
                                 "A tendon must have at least a start and end point.")
            return
        del self.working_points[row]
        self._renumber()
        self._refresh_table()
        self._refresh_plot()

    def _delete_all_points(self):
        if QMessageBox.question(self, "Delete All Points",
                                 "Reset to a default straight 2-point layout?")\
                != QMessageBox.StandardButton.Yes:
            return
        L = self.tendon.length() * self.local_scale
        self.working_points = [
            {"id": 1, "segment_type": "Start of Tendon", "coord1": 0.0,
             "coord2_type": "Specified", "coord2": 0.0,
             "coord3_type": "Specified", "coord3": 0.0, "slope": 0.0},
            {"id": 2, "segment_type": "Linear", "coord1": L,
             "coord2_type": "Specified", "coord2": 0.0,
             "coord3_type": "Specified", "coord3": 0.0, "slope": 0.0},
        ]
        self._refresh_table()
        self._refresh_plot()

    def _focus_table(self):
        self.table.setFocus()
        self.table.scrollToTop()

    def _refresh_plot(self):
        if self.rb_13.isChecked():
            axis_label, key = "1-3", "coord3"
        elif self.rb_23.isChecked():
            axis_label, key = "2-3", "coord2"
        else:
            axis_label, key = "1-2", "coord2"

        if axis_label == "2-3":
            pts = [(p["coord2"], p.get("coord3", 0.0)) for p in self.working_points]
        else:
            pts = [(p["coord1"], p.get(key, 0.0)) for p in self.working_points]

        slopes = [p.get("slope", 0.0) for p in self.working_points]
        seg_types = [p.get("segment_type", "Linear") for p in self.working_points]

        self.plot_canvas.set_data(pts, axis_label, slopes, seg_types)

    def _refresh_section_combo(self):
        current = self.working_section.name if self.working_section else None
        self.section_combo.blockSignals(True)
        self.section_combo.clear()
        self.section_combo.addItems(list(self.model.tendon_sections.keys()))
        if current:
            idx = self.section_combo.findText(current)
            if idx >= 0:
                self.section_combo.setCurrentIndex(idx)
        self.section_combo.blockSignals(False)

    def _add_section(self):
        from app.dialogs.tendon_dialog import TendonEditorDialog
        before = set(self.model.tendon_sections.keys())
        dlg = TendonEditorDialog(self.model, parent=self)
        if dlg.exec():
            after = set(self.model.tendon_sections.keys())
            new_names = after - before
            self._refresh_section_combo()
            if new_names:
                self.section_combo.setCurrentText(next(iter(new_names)))

    def _show_sections(self):
        from app.dialogs.tendon_dialog import TendonManagerDialog
        current = self.section_combo.currentText()
        dlg = TendonManagerDialog(self.model, parent=self)
        dlg.exec()
        self._refresh_section_combo()
        idx = self.section_combo.findText(current)
        if idx >= 0:
            self.section_combo.setCurrentIndex(idx)

    def _modify_axes(self):
        dlg = ModifyAxesDialog(self.working_plane, self.working_angle, self)
        if dlg.exec():
            self.working_plane = dlg.get_plane()
            self.working_angle = dlg.get_angle()
            self.angle_edit.setText(f"{self.working_angle:.2f}")

    def _quick_start(self):
        max_spans = max(len(self.tendon.host_element_ids), 1)
        L_display = self.tendon.length() * self.local_scale
        dlg = TendonQuickStartDialog(L_display, self.working_plane,
                                      self.working_angle, max_spans=max(max_spans, 8),
                                      parent=self)
        if dlg.exec() and dlg.result_points:
            self.working_points = dlg.result_points
            self.working_plane = dlg.plane_combo.currentText()
            try:
                self.working_angle = float(dlg.angle_edit.text() or 0.0)
            except ValueError:
                pass
            self.angle_edit.setText(f"{self.working_angle:.2f}")
            self._refresh_table()
            self._refresh_plot()

    def _parabolic_calculator_stub(self):
        L_display = self.tendon.length() * self.local_scale
        dlg = DefineParabolicTendonDialog(
            tendon_length=L_display,
            plane=self.working_plane,
            angle=self.working_angle,
            existing_points=self.working_points,
            parent=self
        )
        if dlg.exec() and dlg.result_points:
            self.working_points = dlg.result_points
            self._refresh_table()
            self._refresh_plot()

    def _move_tendon_stub(self):
        QMessageBox.information(
            self, "Coming Soon",
            "Move Tendon isn't implemented yet — this needs the 3D canvas hookup.")

    def _on_ok(self):
        if len(self.working_points) < 2:
            QMessageBox.critical(self, "Invalid Layout",
                                  "A tendon needs at least a start and end point.")
            return

        coords1 = [p["coord1"] for p in self.working_points]
        if any(b - a <= 1e-9 for a, b in zip(coords1, coords1[1:])):
            QMessageBox.critical(self, "Invalid Layout",
                                  "Coord 1 values must be strictly increasing along the tendon.")
            return

        L = self.tendon.length() * self.local_scale
        if abs(coords1[-1] - L) > 1e-3:
            resp = QMessageBox.question(
                self, "Layout Doesn't Span Full Length",
                f"The last point is at Coord 1 = {coords1[-1]:.4f}, but the tendon's "
                f"actual length (node-to-node) is {L:.4f}. Clamp the last point to "
                f"the tendon's full length?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if resp == QMessageBox.StandardButton.Yes:
                self.working_points[-1]["coord1"] = L

        section_name = self.section_combo.currentText()
        section = self.model.tendon_sections.get(section_name)
        if section is None:
            QMessageBox.critical(self, "No Tendon Section",
                                  "Select (or define) a Tendon Section before continuing.")
            return

        saved_points = copy.deepcopy(self.working_points)

        for pt in saved_points:
            pt["coord1"] /= self.local_scale
            pt["coord2"] /= self.local_scale
            pt["coord3"] /= self.local_scale

        self.tendon.layout_points = saved_points
        self.tendon.plane = self.working_plane
        self.tendon.local_axis_angle = self.working_angle
        self.tendon.coordinate_system = self.coord_combo.currentText()
        self.tendon.max_discretization_length = self.disc_spin.value() / self.local_scale
        self.tendon.tendon_section = section
        self.tendon.modeling_option = self.modeling_combo.currentText()
        self.tendon.prestress_type = self.prestress_combo.currentText()
        self.tendon.color = section.color

        self.tendon.loads = self.working_loads
        self.model.generate_tendon_loads()

        self.accept()

    def _refresh_loads_combo(self):
        self.loads_combo.blockSignals(True)
        self.loads_combo.clear()
        
        if not getattr(self, 'working_loads', []):
            self.loads_combo.addItem("None")
        else:
            from core.units import UnitConverter, unit_registry
            local_unit = UnitConverter()
            
            if hasattr(self, 'units_combo') and self.units_combo.currentText():
                local_unit.set_unit_system(self.units_combo.currentText())
            else:
                local_unit.set_unit_system(unit_registry.current_unit_label)
            
            for load in self.working_loads:
                is_force = load.get("load_type") == "Force"
                raw_val = load.get("load_value", 0.0)
                
                disp_val = local_unit.to_display_force(raw_val) if is_force else local_unit.to_display_pressure(raw_val)
                unit_str = local_unit.force_unit_name if is_force else local_unit.pressure_unit
                
                self.loads_combo.addItem(f"{load['pattern']} ({load['load_type']}: {disp_val:.4g} {unit_str})")
                
        self.loads_combo.blockSignals(False)

    def _add_tendon_load(self):
        from app.dialogs.tendon_load_dialog import TendonLoadDialog
        dlg = TendonLoadDialog(self.model, parent=self)
        if dlg.exec():
            data = dlg.get_data()
                                                            
            self.working_loads = [ld for ld in self.working_loads if ld["pattern"] != data["pattern"]]
            if data["action"] == "Replace":
                self.working_loads.append(data)
            self._refresh_loads_combo()

    def _show_tendon_load(self):
        if not self.working_loads:
            QMessageBox.information(self, "Tendon Loads", "No loads assigned to this tendon yet.")
            return
            
        selected_idx = self.loads_combo.currentIndex()
        if selected_idx < 0 or selected_idx >= len(self.working_loads):
            return
            
        selected_load_data = self.working_loads[selected_idx]
        
        from app.dialogs.tendon_load_dialog import TendonLoadDisplayDialog
        dlg = TendonLoadDisplayDialog(selected_load_data, self.tendon.id, parent=self)
        if dlg.exec():
                                                          
            if dlg.action_taken == "Delete":
                self.working_loads.pop(selected_idx)
            elif dlg.action_taken == "Modify":
                self.working_loads[selected_idx] = dlg.load_data
                
            self._refresh_loads_combo()

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QComboBox,
    QPushButton, QGroupBox, QLineEdit, QTableWidget, QTableWidgetItem, 
    QHeaderView, QAbstractItemView, QRadioButton, QButtonGroup, QSpinBox, 
    QCheckBox, QItemDelegate, QDoubleSpinBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

class DefineParabolicTendonDialog(QDialog):
                                            
    def __init__(self, tendon_length, plane="1-2", angle=0.0, existing_points=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Define Parabolic Tendon Layout")
        self.resize(800, 650)
        self.tendon_length = tendon_length
        self.result_points = []

        self.initial_points = existing_points or [] 
        
        apply_dialog_style(self)
        root = QVBoxLayout(self)
        
        top_row = QHBoxLayout()
        
        plane_group = QGroupBox("Define Tendon In This Tendon Line Object Local Plane")
        pg_layout = QHBoxLayout(plane_group)
        self.plane_combo = QComboBox()
        self.plane_combo.addItems(["1-2", "1-3"])
        self.plane_combo.setCurrentText(plane)
        self.plane_combo.currentTextChanged.connect(self._refresh_plot)
        pg_layout.addWidget(QLabel("Plane:"))
        pg_layout.addWidget(self.plane_combo)
        
        self.angle_edit = QLineEdit(f"{angle:.2f}")
        self.angle_edit.setFixedWidth(60)
        pg_layout.addWidget(QLabel("Angle:"))
        pg_layout.addWidget(self.angle_edit)
        
        modify_btn = QPushButton("Modify Axes...")
        pg_layout.addWidget(modify_btn)
        top_row.addWidget(plane_group)
        
        pts_group = QGroupBox("Number of Control Points")
        pts_layout = QHBoxLayout(pts_group)
        self.num_points_spin = QSpinBox()
        self.num_points_spin.setRange(2, 50)
        num_pts = len(self.initial_points) if len(self.initial_points) >= 2 else 3
        self.num_points_spin.setValue(num_pts)
        self.num_points_spin.valueChanged.connect(self._build_table)
        pts_layout.addWidget(QLabel("Number of Points"))
        pts_layout.addWidget(self.num_points_spin)
        top_row.addWidget(pts_group)
        
        root.addLayout(top_row)
        
        table_group = QGroupBox("Tendon Layout Data")
        tg_layout = QVBoxLayout(table_group)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Point", "Coord 1", "Coord 2 Type", "Coord 2", "Slope Type", "Slope"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        
        self.combo_delegate = ComboBoxDelegate(["Specified", "Prog Calc"], self)
        self.table.setItemDelegateForColumn(2, self.combo_delegate)
        self.table.setItemDelegateForColumn(4, self.combo_delegate)
        
        tg_layout.addWidget(self.table)
        root.addWidget(table_group, stretch=1)
        
        display_group = QGroupBox("Tendon Layout Display")
        dg = QHBoxLayout(display_group)
        
        self.plot_canvas = TendonProfileCanvas()
        dg.addWidget(self.plot_canvas, stretch=3)
        
        readout_layout = QVBoxLayout()
        try:
            from core.units import unit_registry
            units_text = unit_registry.current_unit_label
        except Exception:
            units_text = "kN, m, C"
        readout_layout.addWidget(QLabel(f"Units: {units_text}"))
        self.snap_group_btns = QButtonGroup(self)
        self.rb_no_snap = QRadioButton("No Snap")
        self.rb_snap_pts = QRadioButton("Snap to Points")
        self.rb_snap_pts.setChecked(True)
        for rb in (self.rb_no_snap, self.rb_snap_pts):
            self.snap_group_btns.addButton(rb)
            readout_layout.addWidget(rb)
        readout_layout.addStretch()
        dg.addLayout(readout_layout, stretch=1)
        
        root.addWidget(display_group, stretch=1)
        
        footer = QHBoxLayout()
        
        calc_group = QGroupBox("Calculated Results")
        calc_layout = QHBoxLayout(calc_group)
        clear_btn = QPushButton("Clear")
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._calculate_parabola)
        calc_layout.addWidget(clear_btn)
        calc_layout.addWidget(refresh_btn)
        footer.addWidget(calc_group)
        
        close_group = QGroupBox("Close Form")
        close_layout = QHBoxLayout(close_group)
        self.use_calc_check = QCheckBox("Use Calculated Results for This Tendon")
        self.use_calc_check.setChecked(True)
        done_btn = QPushButton("Done")
        done_btn.clicked.connect(self._on_done)
        close_layout.addWidget(self.use_calc_check)
        close_layout.addWidget(done_btn)
        footer.addWidget(close_group)
        
        root.addLayout(footer)
        
        self._build_table()
        if self.initial_points:
            self._load_existing_points()

    def _load_existing_points(self):
        """Populates the table with points already defined in the main dialog."""
        for r, pt in enumerate(self.initial_points):
            if r >= self.table.rowCount():
                break
                
            self.table.item(r, 1).setText(f"{pt.get('coord1', 0.0):.4f}")
            
            self.table.item(r, 2).setText(pt.get('coord2_type', 'Specified'))
            
            self.table.item(r, 3).setText(f"{pt.get('coord2', 0.0):.4f}")
            
            slope_type = pt.get('slope_type', 'Prog Calc')                                   
            type_item = self.table.item(r, 4)
            if type_item is None:
                type_item = QTableWidgetItem()
                self.table.setItem(r, 4, type_item)
            type_item.setText(slope_type)

            slope = pt.get('slope', 0.0)
            slope_item = self.table.item(r, 5)
            if slope_item is None:
                slope_item = QTableWidgetItem()
                self.table.setItem(r, 5, slope_item)
            slope_item.setText(f"{slope:.4f}")
            
        self._calculate_parabola()

    def _build_table(self):
        num_rows = self.num_points_spin.value()
        current_rows = self.table.rowCount()
        self.table.setRowCount(num_rows)
        
        for row in range(num_rows):
            if row >= current_rows:
                pt_item = QTableWidgetItem(str(row + 1))
                                                           
                pt_item.setFlags(pt_item.flags() & ~Qt.ItemFlag.ItemIsEditable & ~Qt.ItemFlag.ItemIsSelectable)
                
                if row == 0:
                    pt_item.setBackground(QColor("#0288D1"))
                    pt_item.setForeground(QColor("white"))
                elif row == num_rows - 1:
                    pt_item.setBackground(QColor("#D32F2F"))
                    pt_item.setForeground(QColor("white"))
                self.table.setItem(row, 0, pt_item)
                
                c1 = 0.0 if row == 0 else (self.tendon_length if row == num_rows - 1 else self.tendon_length * (row / (num_rows - 1)))
                self.table.setItem(row, 1, QTableWidgetItem(f"{c1:.4f}"))
                self.table.setItem(row, 2, QTableWidgetItem("Specified"))
                self.table.setItem(row, 3, QTableWidgetItem("0.0000"))
                self.table.setItem(row, 4, QTableWidgetItem("Prog Calc"))
                
                slope_item = QTableWidgetItem("0.0000")
                self.table.setItem(row, 5, slope_item)
                
        for r in range(num_rows):
            item = self.table.item(r, 0)
            if item is None:
                continue
                
            if r == 0:
                item.setBackground(QColor("#0288D1"))
                item.setForeground(QColor("white"))
            elif r == num_rows - 1:
                item.setBackground(QColor("#D32F2F"))
                item.setForeground(QColor("white"))
            else:
                item.setBackground(QColor(self.palette().color(self.backgroundRole())))
                                                                                                     
                item.setData(Qt.ItemDataRole.ForegroundRole, None)
                
        self._refresh_plot()

    def _refresh_plot(self):
        pts = []
        slopes = []
        for r in range(self.table.rowCount()):
            try:
                x = float(self.table.item(r, 1).text())
                y = float(self.table.item(r, 3).text())
                
                slope_item = self.table.item(r, 5)
                slope = float(slope_item.text()) if slope_item and slope_item.text() else 0.0
                
                pts.append((x, y))
                slopes.append(slope)
            except (ValueError, AttributeError):
                pass
                
        self.plot_canvas.set_data(pts, self.plane_combo.currentText(), slopes)

    def _calculate_parabola(self):
        num_rows = self.table.rowCount()
        x = np.zeros(num_rows)
        y = np.zeros(num_rows)
        slope_types = []
        slopes = np.zeros(num_rows)
        
        for r in range(num_rows):
            try:
                x[r] = float(self.table.item(r, 1).text())
                y[r] = float(self.table.item(r, 3).text())
                stype = self.table.item(r, 4).text()
                slope_types.append(stype)
                
                if stype == "Specified":
                    slopes[r] = float(self.table.item(r, 5).text())
            except (ValueError, AttributeError):
                return 
                
        for r in range(num_rows - 1):
            if slope_types[r] == "Prog Calc" and slope_types[r+1] == "Specified":
                dx = x[r+1] - x[r]
                dy = y[r+1] - y[r]
                if dx != 0:
                    slopes[r] = 2.0 * (dy / dx) - slopes[r+1]

        for r in range(1, num_rows):
            if slope_types[r] == "Prog Calc" and slope_types[r-1] == "Specified":
                dx = x[r] - x[r-1]
                dy = y[r] - y[r-1]
                if dx != 0:
                    slopes[r] = 2.0 * (dy / dx) - slopes[r-1]

        for r in range(num_rows):
            if slope_types[r] == "Prog Calc":
                self.table.item(r, 5).setText(f"{slopes[r]:.4f}")
                
        self._refresh_plot()

    def _on_done(self):
        if not self.use_calc_check.isChecked():
            self.reject()
            return
            
        self._calculate_parabola()
        
        num_rows = self.table.rowCount()
        self.result_points = []
        
        for r in range(num_rows):
            try:
                c1 = float(self.table.item(r, 1).text())
                c2 = float(self.table.item(r, 3).text())
                slope = float(self.table.item(r, 5).text())
            except ValueError:
                continue

            seg_type = "Start of Tendon" if r == 0 else "Parabolic"

            pt = {
                "id": r + 1,
                "segment_type": seg_type,
                "coord1": c1,
                "coord2_type": self.table.item(r, 2).text(),
                "coord2": c2,
                "coord3_type": "Specified",
                "coord3": 0.0, 
                "slope_type": self.table.item(r, 4).text(),                            
                "slope": slope
            }
            self.result_points.append(pt)
            
        self.accept()
