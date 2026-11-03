import math
import re
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QTableWidget, QTableWidgetItem, QPushButton, 
                             QGroupBox, QHeaderView, QRadioButton, QButtonGroup,
                             QFrame, QDoubleSpinBox, QSpinBox, QMessageBox, QWidget, QComboBox,
                             QGridLayout, QCheckBox, QColorDialog, QTabWidget, QScrollArea)
from PyQt6.QtCore import Qt, QRectF, QPointF
from PyQt6.QtGui import QPainter, QPen, QBrush, QColor, QFont
from core.units import unit_registry
from core.grid import (GRID_PRESETS, COLOR_KEYS, ALPHA_KEYS, default_grid_style,
                       resolve_grid_style)
from app.ui.theme import apply_dialog_style, current_theme, COLORS

class GridPreviewWidget(QFrame):
    """
    A mini-canvas that draws the grid system in real-time.
    Supports XY, XZ, and YZ planes.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(280, 280)                       
        self.setStyleSheet(f"border: 1px solid {COLORS['border']};")
        self.style_values = None                                                     
        self.dark = False
        
        self.h_grids = []                                
        self.v_grids = []                              
        self.plane = "XY"
        self.bubble_size = 1.0
        self.bubble_alpha = 1.0
        self.bubble_line_width = 1.5
        self.bubble_ext_width = None
        self.bubble_extension = 2.5

    def update_data(self, h_data, v_data, plane, bubble_size, bubble_alpha=1.0,
                     bubble_line_width=1.5, bubble_extension=None, style_values=None, dark=False,
                     bubble_ext_width=None):
        self.style_values = style_values
        self.dark = dark
        self.h_grids = h_data
        self.v_grids = v_data
        self.plane = plane
        self.bubble_size = bubble_size
        self.bubble_alpha = bubble_alpha
        self.bubble_line_width = bubble_line_width
        self.bubble_ext_width = bubble_ext_width
                                                                        
        self.bubble_extension = bubble_extension if bubble_extension is not None else (bubble_size * 2.5)
        self.update()                  

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        
        painter.fillRect(0, 0, w, h, QColor("#1E1E1E") if self.dark else QColor("#FFFFFF"))
        painter.setPen(Qt.GlobalColor.gray)
        painter.drawText(5, 15, f"View: {self.plane} Plane")
        
        if not self.h_grids or not self.v_grids:
            painter.drawText(w//2 - 30, h//2, "No Grid Data")
            return

        hs = [val for _, val, _ in self.h_grids]
        vs = [val for _, val, _ in self.v_grids]
        
        min_h, max_h = min(hs), max(hs)
        min_v, max_v = min(vs), max(vs)
        
        span_h = max_h - min_h
        span_v = max_v - min_v
        
        margin_h = max(span_h * 0.15, 2.0 * self.bubble_size) 
        margin_v = max(span_v * 0.15, 2.0 * self.bubble_size)
        
        view_min_h = min_h - margin_h
        view_max_h = max_h + margin_h
        view_min_v = min_v - margin_v
        view_max_v = max_v + margin_v
        
        def to_screen(gh, gv):
            sh = (gh - view_min_h) / (view_max_h - view_min_h) * w
            sv = h - (gv - view_min_v) / (view_max_v - view_min_v) * h
            return sh, sv

        sv = self.style_values
        if sv:
            gc = QColor(sv["active"])                                                      
            gc.setAlphaF(sv["a_active"])
            grid_pen = QPen(gc, max(1.0, sv["width_lines"]), Qt.PenStyle.SolidLine)
        else:
            grid_pen = QPen(QColor(180, 180, 180), 1, Qt.PenStyle.SolidLine)
        painter.setPen(grid_pen)
        
        for _, h_val, _ in self.h_grids:
            x1, y1 = to_screen(h_val, view_min_v)
            x2, y2 = to_screen(h_val, view_max_v)
            painter.drawLine(int(x1), int(y1), int(x2), int(y2))
            
        for _, v_val, _ in self.v_grids:
            x1, y1 = to_screen(view_min_h, v_val)
            x2, y2 = to_screen(view_max_h, v_val)
            painter.drawLine(int(x1), int(y1), int(x2), int(y2))

        b_radius = 5 + (self.bubble_size * 2) 

        ext_ratio = self.bubble_extension / max(self.bubble_size, 0.001)
        tail_px = b_radius * ext_ratio * 0.5
        gap_px = b_radius + tail_px                       

        if sv:
            tail_col, circle_col, text_col = QColor(sv["bub_line"]), QColor(sv["bub_circle"]), QColor(sv["bub_text"])
        else:
            tail_col, circle_col, text_col = QColor(100, 150, 220), QColor(Qt.GlobalColor.black), QColor(Qt.GlobalColor.black)
        _tail_w = self.bubble_ext_width if self.bubble_ext_width else self.bubble_line_width
        tail_pen = QPen(tail_col, max(1.0, _tail_w * 0.8))
        circle_pen = QPen(circle_col, max(1.0, self.bubble_line_width * 0.8))
        text_pen = QPen(text_col)
        
        painter.setFont(QFont("Arial", 8))
        bubble_color = QColor("#2A2A2A") if self.dark else QColor(240, 240, 240)
        bubble_color.setAlphaF(self.bubble_alpha)

        for gid, h_val, bub_loc in self.h_grids:
            if bub_loc in ["End", "Both"]:           
                sx, sy = to_screen(h_val, max_v)
                center = QPointF(sx, sy - gap_px) 
                painter.setPen(tail_pen)
                painter.drawLine(QPointF(sx, sy), QPointF(sx, sy - gap_px + b_radius))
                painter.setBrush(QBrush(bubble_color))
                painter.setPen(circle_pen)
                painter.drawEllipse(center, b_radius, b_radius)
                painter.setPen(text_pen)
                painter.drawText(QRectF(sx - b_radius, sy - gap_px - b_radius, b_radius*2, b_radius*2), 
                                 Qt.AlignmentFlag.AlignCenter, str(gid))
                                 
            if bub_loc in ["Start", "Both"]:              
                sx, sy = to_screen(h_val, min_v)
                center = QPointF(sx, sy + gap_px) 
                painter.setPen(tail_pen)
                painter.drawLine(QPointF(sx, sy), QPointF(sx, sy + gap_px - b_radius))
                painter.setBrush(QBrush(bubble_color))
                painter.setPen(circle_pen)
                painter.drawEllipse(center, b_radius, b_radius)
                painter.setPen(text_pen)
                painter.drawText(QRectF(sx - b_radius, sy + gap_px - b_radius, b_radius*2, b_radius*2), 
                                 Qt.AlignmentFlag.AlignCenter, str(gid))

        for gid, v_val, bub_loc in self.v_grids:
            if bub_loc in ["Start", "Both"]:            
                sx, sy = to_screen(min_h, v_val)
                center = QPointF(sx - gap_px, sy)
                painter.setPen(tail_pen)
                painter.drawLine(QPointF(sx, sy), QPointF(sx - gap_px + b_radius, sy))
                painter.setBrush(QBrush(bubble_color))
                painter.setPen(circle_pen)
                painter.drawEllipse(center, b_radius, b_radius)
                painter.setPen(text_pen)
                painter.drawText(QRectF(sx - gap_px - b_radius, sy - b_radius, b_radius*2, b_radius*2), 
                                 Qt.AlignmentFlag.AlignCenter, str(gid))
                                 
            if bub_loc in ["End", "Both"]:             
                sx, sy = to_screen(max_h, v_val)
                center = QPointF(sx + gap_px, sy)
                painter.setPen(tail_pen)
                painter.drawLine(QPointF(sx, sy), QPointF(sx + gap_px - b_radius, sy))
                painter.setBrush(QBrush(bubble_color))
                painter.setPen(circle_pen)
                painter.drawEllipse(center, b_radius, b_radius)
                painter.setPen(text_pen)
                painter.drawText(QRectF(sx + b_radius, sy - b_radius, b_radius*2, b_radius*2), 
                                 Qt.AlignmentFlag.AlignCenter, str(gid))

class GridEditorDialog(QDialog):
    def __init__(self, current_grid, parent=None):
        super().__init__(parent)
        apply_dialog_style(self)
        self.setWindowTitle("Define Grid System Data")
                                                                            
        _w, _h = 1250, 820
        _scr = self.screen()
        if _scr is not None:
            _a = _scr.availableGeometry()
            _w, _h = min(_w, _a.width() - 60), min(_h, _a.height() - 60)
        self.resize(_w, _h)
        self._grid_ref = current_grid
        self._loading = False
        self._dark = self._detect_dark(parent)
        st = getattr(current_grid, 'style', None)
        self._style = default_grid_style()
        if isinstance(st, dict):
            self._style.update({k: v for k, v in st.items() if k in self._style})
        self._style['custom'] = dict(self._style.get('custom') or {})
        
        self.x_data = [] 
        self.y_data = []
        self.z_data = []
        
        self.current_mode = "ordinate" 
        self.initial_bubble_size = getattr(current_grid, 'bubble_size', 1.25)
        self.initial_bubble_alpha = getattr(current_grid, 'bubble_alpha', 1.0)
        self.initial_bubble_line_width = getattr(current_grid, 'bubble_line_width', 1.5)
        self.initial_bubble_ext_width = getattr(current_grid, 'bubble_ext_line_width', None)                          
                                                                         
        self.initial_bubble_extension = getattr(current_grid, 'bubble_extension', self.initial_bubble_size * 2.5)
        self.parse_grid_obj(current_grid)

        self.setup_ui()
        self.populate_all_tables()
        self.update_preview()

    def parse_grid_obj(self, grid_obj):
        """Loads data from the Smart Grid object and converts to Display Units."""
        def to_list(lines_dict, prefix):
            rows = []
            if not lines_dict: return rows
            
            if isinstance(lines_dict[0], float):
                for i, val in enumerate(lines_dict):
                                              
                    disp_val = unit_registry.to_display_length(val)
                    rows.append([f"{prefix}{i+1}", disp_val, "Primary", True, "Start"])
            else:
                for item in lines_dict:
                                              
                    disp_val = unit_registry.to_display_length(item['ord'])
                    rows.append([
                        item['id'], 
                        disp_val, 
                        "Primary",                         
                        item['visible'], 
                        item['bubble']
                    ])
            return rows
        
        self.x_data = to_list(grid_obj.x_lines, "")
        self.y_data = to_list(grid_obj.y_lines, "")
        self.z_data = to_list(grid_obj.z_lines, "Z")

    def setup_ui(self):
                                                                                                 
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        layout = QHBoxLayout(content)
        self._scroll.setWidget(content)
        root.addWidget(self._scroll, 1)
        
        left_panel = QVBoxLayout()
        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel("System Name:"))
        name_layout.addWidget(QLabel("<b>GLOBAL</b>"))
        name_layout.addStretch()
        left_panel.addLayout(name_layout)

        self.table_x = self.create_grid_group("X Grid Data", "x")
        self.table_y = self.create_grid_group("Y Grid Data", "y")
        self.table_z = self.create_grid_group("Z Grid Data", "z")
        
        left_panel.addWidget(self.table_x['group'])
        left_panel.addWidget(self.table_y['group'])
        left_panel.addWidget(self.table_z['group'])
        
        right_panel = QVBoxLayout()
        
        prev_ctrl = QHBoxLayout()
        prev_ctrl.addWidget(QLabel("Preview View:"))
        self.combo_plane = QComboBox()
        self.combo_plane.addItems(["XY Plane (Plan)", "XZ Plane (Elevation)", "YZ Plane (Elevation)"])
        self.combo_plane.currentIndexChanged.connect(self.update_preview)
        prev_ctrl.addWidget(self.combo_plane)
        right_panel.addLayout(prev_ctrl)

        self.preview = GridPreviewWidget()
        right_panel.addWidget(self.preview)
        
        right_panel.addSpacing(6)

        opt_group = QGroupBox("Display Grids as")
        vbox = QVBoxLayout()
        self.rb_ordinate = QRadioButton("Ordinates")
        self.rb_spacing = QRadioButton("Spacing")
        self.rb_ordinate.setChecked(True)
        
        self.rb_ordinate.toggled.connect(lambda: self.toggle_mode("ordinate"))
        self.rb_spacing.toggled.connect(lambda: self.toggle_mode("spacing"))
        
        vbox.addWidget(self.rb_ordinate)
        vbox.addWidget(self.rb_spacing)
        opt_group.setLayout(vbox)
        right_panel.addWidget(opt_group)
        
        bub_page = QWidget()
        bub_vbox = QVBoxLayout(bub_page)
        bub_layout = QHBoxLayout()
        bub_layout.addWidget(QLabel("Bubble Size:"))
        self.spin_bubble = QDoubleSpinBox()
        self.spin_bubble.setRange(0.001, 100.0)
        self.spin_bubble.setDecimals(3)
        self.spin_bubble.setValue(self.initial_bubble_size)
        self.spin_bubble.setSingleStep(0.05)
        self.spin_bubble.valueChanged.connect(self.update_preview)
        bub_layout.addWidget(self.spin_bubble)
        bub_vbox.addLayout(bub_layout)

        bub_alpha_layout = QHBoxLayout()
        bub_alpha_layout.addWidget(QLabel("Bubble Opacity:"))
        self.spin_bubble_alpha = QSpinBox()
        self.spin_bubble_alpha.setRange(10, 100)
        self.spin_bubble_alpha.setValue(round(self.initial_bubble_alpha * 100))
        self.spin_bubble_alpha.setSingleStep(5)
        self.spin_bubble_alpha.setSuffix("%")
        self.spin_bubble_alpha.valueChanged.connect(self.update_preview)
        bub_alpha_layout.addWidget(self.spin_bubble_alpha)
        bub_vbox.addLayout(bub_alpha_layout)

        bub_width_layout = QHBoxLayout()
        bub_width_layout.addWidget(QLabel("Bubble Circle Thickness:"))
        self.spin_bubble_line_width = QDoubleSpinBox()
        self.spin_bubble_line_width.setRange(0.5, 10.0)
        self.spin_bubble_line_width.setDecimals(2)
        self.spin_bubble_line_width.setValue(self.initial_bubble_line_width)
        self.spin_bubble_line_width.setSingleStep(0.25)
        self.spin_bubble_line_width.setToolTip(
            "Thickness (in pixels) of the bubble ID circle.\n"
            "(Also the extension line when 'Same as bubble' is ticked.)"
        )
        self.spin_bubble_line_width.valueChanged.connect(self.update_preview)
        bub_width_layout.addWidget(self.spin_bubble_line_width)
        bub_vbox.addLayout(bub_width_layout)

        ext_w_layout = QHBoxLayout()
        ext_w_layout.addWidget(QLabel("Extension Line Thickness:"))
        self.spin_ext_width = QDoubleSpinBox()
        self.spin_ext_width.setRange(0.5, 10.0)
        self.spin_ext_width.setDecimals(2)
        self.spin_ext_width.setSingleStep(0.25)
        self.spin_ext_width.setToolTip("Thickness (in pixels) of the line that runs from the grid line out to the bubble.")
        ext_w_layout.addWidget(self.spin_ext_width)
        bub_vbox.addLayout(ext_w_layout)

        self.chk_ext_same = QCheckBox("Same as bubble thickness")
        same = self.initial_bubble_ext_width is None
        self.chk_ext_same.setChecked(same)
        self.spin_ext_width.setValue(self.initial_bubble_line_width if same else self.initial_bubble_ext_width)
        self.spin_ext_width.setEnabled(not same)
        self.chk_ext_same.toggled.connect(self._on_ext_same_toggled)
        self.spin_ext_width.valueChanged.connect(self.update_preview)
        self.spin_bubble_line_width.valueChanged.connect(self._sync_ext_width)
        bub_vbox.addWidget(self.chk_ext_same)

        bub_ext_layout = QHBoxLayout()
        bub_ext_layout.addWidget(QLabel("Bubble Extension Length:"))
        self.spin_bubble_extension = QDoubleSpinBox()
        self.spin_bubble_extension.setRange(0.001, 1000.0)
        self.spin_bubble_extension.setDecimals(3)
        self.spin_bubble_extension.setValue(self.initial_bubble_extension)
        self.spin_bubble_extension.setSingleStep(0.1)
        self.spin_bubble_extension.setToolTip(
            "How far the tail line runs past the end of the grid line before\n"
            "the ID bubble is drawn. Independent of Bubble Size."
        )
        self.spin_bubble_extension.valueChanged.connect(self.update_preview)
        bub_ext_layout.addWidget(self.spin_bubble_extension)
        bub_vbox.addLayout(bub_ext_layout)

        self._color_btns = {}
        bcol_box = QGroupBox("Bubble Colors")
        bcol = QGridLayout(bcol_box)
        for r, (label, ckey) in enumerate([("Bubble circle", "bub_circle"),
                                           ("Extension line", "bub_line"),
                                           ("ID text", "bub_text")]):
            bcol.addWidget(QLabel(label), r, 0)
            btn = QPushButton()
            btn.setFixedSize(46, 22)
            btn.clicked.connect(lambda _=False, k=ckey: self._pick_color(k))
            self._color_btns[ckey] = btn
            bcol.addWidget(btn, r, 1)
        bcol.setColumnStretch(0, 1)
        bub_vbox.addWidget(bcol_box)
        bub_vbox.addStretch()

        self.right_tabs = QTabWidget()
        self.right_tabs.addTab(bub_page, "Bubbles")
        self.right_tabs.addTab(self._build_grid_lines_tab(), "Grid Lines")
        right_panel.addWidget(self.right_tabs, 1)

        self._all_visible = True
        self.btn_global_viz = QPushButton("Hide All Gridlines")
        self.btn_global_viz.setToolTip("Toggle visibility of every gridline across all axes at once")
        self.btn_global_viz.clicked.connect(self.toggle_all_axes_visibility)
        right_panel.addWidget(self.btn_global_viz)
        
        btn_box = QHBoxLayout()
        btn_box.addStretch()
        btn_ok = QPushButton("OK")
        btn_ok.clicked.connect(self.accept)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_box.addWidget(btn_ok)
        btn_box.addWidget(btn_cancel)
        root.addLayout(btn_box)

        layout.addLayout(left_panel, 2)                         
        layout.addLayout(right_panel, 1)                                        

    _COLOR_ROWS = [
                                                           
        ("Grid lines (3D)",       "line",        "a_line"),
        ("Grid lines (2D views)", None,          "a_line_2d"),
        ("Active plane",          "active",      "a_active"),
        ("Floor grid",            "floor",       "a_floor"),
        ("Floor major lines",     "floor_major", "a_major"),
        ("Dimension lines + text", "dim",        "a_dim"),
    ]

    @staticmethod
    def _detect_dark(parent):
        """Is the 3D canvas background dark? (falls back to the UI theme)"""
        try:
            return bool(parent.canvas._canvas_is_dark())
        except Exception:
            return current_theme() == "Dark"

    def _ext_width(self):
        """None = extension line follows the bubble thickness."""
        return None if self.chk_ext_same.isChecked() else self.spin_ext_width.value()

    def _sync_ext_width(self, v):
        if self.chk_ext_same.isChecked():
            self.spin_ext_width.setValue(v)

    def _on_ext_same_toggled(self, checked):
        self.spin_ext_width.setEnabled(not checked)
        if checked:
            self.spin_ext_width.setValue(self.spin_bubble_line_width.value())
        self.update_preview()

    def _resolved(self):
        return resolve_grid_style(self._style, self._dark)

    def _final_style(self):
        s = dict(self._style)
        s['custom'] = dict(self._style.get('custom') or {})
        return s

    def _build_grid_lines_tab(self):
        page = QWidget()
        v = QVBoxLayout(page)

        row = QHBoxLayout()
        row.addWidget(QLabel("Preset:"))
        self.combo_preset = QComboBox()
        self.combo_preset.addItems(GRID_PRESETS)
        self.combo_preset.currentTextChanged.connect(self._on_preset_changed)
        row.addWidget(self.combo_preset, 1)
        v.addLayout(row)

        colors_box = QGroupBox("Colors and Opacity")
        grid = QGridLayout(colors_box)
        grid.addWidget(QLabel("<b>Color</b>"), 0, 1)
        grid.addWidget(QLabel("<b>Opacity</b>"), 0, 2)
        self._alpha_spins = {}
        for r, (label, ckey, akey) in enumerate(self._COLOR_ROWS, start=1):
            grid.addWidget(QLabel(label), r, 0)
            if ckey:
                btn = QPushButton()
                btn.setFixedSize(46, 22)
                btn.clicked.connect(lambda _=False, k=ckey: self._pick_color(k))
                self._color_btns[ckey] = btn
                grid.addWidget(btn, r, 1)
            sp = QSpinBox()
            sp.setRange(0, 100)
            sp.setSingleStep(5)
            sp.setSuffix("%")
            sp.valueChanged.connect(lambda _v, k=akey: self._on_alpha_changed(k))
            self._alpha_spins[akey] = sp
            grid.addWidget(sp, r, 2)
        grid.setColumnStretch(0, 1)
        v.addWidget(colors_box)

        lines_box = QGroupBox("Line Width")
        lf = QGridLayout(lines_box)
        lf.addWidget(QLabel("Grid lines:"), 0, 0)
        self.spin_w_lines = QDoubleSpinBox()
        self.spin_w_lines.setRange(0.5, 6.0)
        self.spin_w_lines.setDecimals(2)
        self.spin_w_lines.setSingleStep(0.25)
        self.spin_w_lines.valueChanged.connect(self._on_misc_changed)
        lf.addWidget(self.spin_w_lines, 0, 1)
        lf.addWidget(QLabel("Floor grid:"), 1, 0)
        self.spin_w_floor = QDoubleSpinBox()
        self.spin_w_floor.setRange(0.5, 6.0)
        self.spin_w_floor.setDecimals(2)
        self.spin_w_floor.setSingleStep(0.25)
        self.spin_w_floor.valueChanged.connect(self._on_misc_changed)
        lf.addWidget(self.spin_w_floor, 1, 1)
        hint = QLabel("Widths above 1 px depend on the graphics driver.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        lf.addWidget(hint, 2, 0, 1, 2)
        v.addWidget(lines_box)

        floor_box = QGroupBox("Floor Grid (plan view)")
        ff = QGridLayout(floor_box)
        self.chk_floor = QCheckBox("Show floor grid")
        self.chk_floor.toggled.connect(self._on_misc_changed)
        ff.addWidget(self.chk_floor, 0, 0, 1, 2)
        ff.addWidget(QLabel("Spacing (0 = auto):"), 1, 0)
        self.spin_floor_spacing = QDoubleSpinBox()
        self.spin_floor_spacing.setRange(0.0, 100000.0)
        self.spin_floor_spacing.setDecimals(3)
        self.spin_floor_spacing.setSingleStep(0.5)
        u = unit_registry.length_unit_name
        if u:
            self.spin_floor_spacing.setSuffix(f" {u}")
        self.spin_floor_spacing.valueChanged.connect(self._on_misc_changed)
        ff.addWidget(self.spin_floor_spacing, 1, 1)
        ff.addWidget(QLabel("Major line every N (0 = off):"), 2, 0)
        self.spin_floor_major = QSpinBox()
        self.spin_floor_major.setRange(0, 100)
        self.spin_floor_major.valueChanged.connect(self._on_misc_changed)
        ff.addWidget(self.spin_floor_major, 2, 1)
        v.addWidget(floor_box)

        btn_reset = QPushButton("Reset to Auto")
        btn_reset.setToolTip("Back to the automatic palette and default widths")
        btn_reset.clicked.connect(self._reset_style)
        v.addWidget(btn_reset)
        v.addStretch()

        self._refresh_style_widgets()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(page)
        return scroll

    def _paint_color_btn(self, btn, hex_color):
        btn.setStyleSheet(
            f"QPushButton {{ background-color: {hex_color}; border: 1px solid {COLORS['border']};"
            f" min-width: 0px; min-height: 0px; padding: 0px; }}"
            f"QPushButton:hover {{ border-color: {COLORS['accent']}; }}")

    def _refresh_style_widgets(self):
        """Show the currently resolved values in every control (no feedback loops)."""
        r = self._resolved()
        self._loading = True
        try:
            self.combo_preset.setCurrentText(r["preset"])
            for k, btn in self._color_btns.items():
                self._paint_color_btn(btn, r[k])
            for k, sp in self._alpha_spins.items():
                sp.setValue(int(round(r[k] * 100)))
            self.spin_w_lines.setValue(r["width_lines"])
            self.spin_w_floor.setValue(r["width_floor"])
            self.chk_floor.setChecked(r["show_floor"])
            self.spin_floor_spacing.setValue(
                unit_registry.to_display_length(r["floor_spacing"]) if r["floor_spacing"] > 0 else 0.0)
            self.spin_floor_major.setValue(r["floor_major_every"])
        finally:
            self._loading = False

    def _to_custom(self):
        """Any manual edit of a colour / opacity switches to Custom, seeded with what is shown now."""
        if self._style.get("preset") != "Custom":
            r = self._resolved()
            self._style["custom"] = {k: r[k] for k in (*COLOR_KEYS, *ALPHA_KEYS)}
            self._style["preset"] = "Custom"
            self._loading = True
            self.combo_preset.setCurrentText("Custom")
            self._loading = False

    def _on_preset_changed(self, text):
        if self._loading:
            return
        if text == "Custom" and not self._style.get("custom"):
            r = self._resolved()
            self._style["custom"] = {k: r[k] for k in (*COLOR_KEYS, *ALPHA_KEYS)}
        self._style["preset"] = text
        self._refresh_style_widgets()
        self.update_preview()

    def _pick_color(self, key):
        cur = QColor(self._resolved()[key])
        col = QColorDialog.getColor(cur, self, "Select Color")
        if not col.isValid():
            return
        self._to_custom()
        self._style["custom"][key] = col.name().upper()
        self._paint_color_btn(self._color_btns[key], col.name().upper())
        self.update_preview()

    def _on_alpha_changed(self, key):
        if self._loading:
            return
        self._to_custom()
        self._style["custom"][key] = self._alpha_spins[key].value() / 100.0
        self.update_preview()

    def _on_misc_changed(self, *_):
        if self._loading:
            return
        self._style["width_lines"] = self.spin_w_lines.value()
        self._style["width_floor"] = self.spin_w_floor.value()
        self._style["show_floor"] = self.chk_floor.isChecked()
        disp = self.spin_floor_spacing.value()
        self._style["floor_spacing"] = unit_registry.from_display_length(disp) if disp > 0 else 0.0
        self._style["floor_major_every"] = self.spin_floor_major.value()
        self.update_preview()

    def _reset_style(self):
        self._style = default_grid_style()
        self._refresh_style_widgets()
        self.update_preview()

    def accept(self):
                                                                          
        try:
            self._grid_ref.style = self._final_style()
            self._grid_ref.bubble_ext_line_width = self._ext_width()
        except Exception:
            pass
        super().accept()

    def create_grid_group(self, title, axis_key):
        gb = QGroupBox(title)
        layout = QHBoxLayout()
        
        table = QTableWidget()
        table.setColumnCount(5)
                               
        self.update_table_header(table, "Ordinate") 
        table.verticalHeader().setVisible(False)
        table.itemChanged.connect(self.on_table_changed) 
        
        btn_layout = QVBoxLayout()
        btn_add = QPushButton("Add")
        btn_del = QPushButton("Delete")

        btn_viz = QPushButton("Show/Hide All")
        btn_viz.clicked.connect(lambda: self.toggle_all_visibility(axis_key))

        btn_bub = QPushButton("Cycle All Bubbles")
        btn_bub.setToolTip("Cycles all gridlines in this axis through End, Start, Both, and None")
        btn_bub.clicked.connect(lambda: self.toggle_all_bubbles(axis_key))

        btn_add.clicked.connect(lambda: self.add_grid_line(axis_key))
        btn_del.clicked.connect(lambda: self.delete_grid_line(axis_key))
        
        btn_layout.addWidget(btn_add)
        btn_layout.addWidget(btn_del)
        btn_layout.addWidget(btn_viz)
        btn_layout.addWidget(btn_bub)                                 
        btn_layout.addStretch()
        
        layout.addWidget(table)
        layout.addLayout(btn_layout)
        gb.setLayout(layout)
        return {'group': gb, 'table': table}

    def update_table_header(self, table, val_title):
        """Updates the 2nd column header dynamically."""
                                                              
        unit = unit_registry.length_unit_name           
        labels = ["Grid ID", f"{val_title} ({unit})", "Line Type", "Visible", "Bubble Loc"]
        table.setHorizontalHeaderLabels(labels)
                      
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)

    def toggle_mode(self, new_mode):
        if self.current_mode == new_mode: return
        self.save_tables_to_data()
        self.current_mode = new_mode
        
        title = "Ordinate" if new_mode == "ordinate" else "Spacing"
        self.update_table_header(self.table_x['table'], title)
        self.update_table_header(self.table_y['table'], title)
        self.update_table_header(self.table_z['table'], title)
        
        self.populate_all_tables()

    def get_display_values(self, data_list):
        """Converts ordinates to the current display mode."""
        ordinates = [row[1] for row in data_list]
        if self.current_mode == "ordinate":
            return ordinates
        else:
            spacings = []
            for i in range(len(ordinates) - 1):
                spacings.append(round(ordinates[i+1] - ordinates[i], 4))
            spacings.append(0.0) 
            return spacings

    def populate_all_tables(self):
        self.populate_table(self.table_x['table'], self.x_data)
        self.populate_table(self.table_y['table'], self.y_data)
        self.populate_table(self.table_z['table'], self.z_data)

    def populate_table(self, table, data):
        table.blockSignals(True) 
        table.setRowCount(0)
        display_vals = self.get_display_values(data)
        
        for i, row in enumerate(data):
            table.insertRow(i)
            table.setItem(i, 0, QTableWidgetItem(str(row[0])))
            table.setItem(i, 1, QTableWidgetItem(f"{display_vals[i]:.6f}"))
            table.setItem(i, 2, QTableWidgetItem(row[2]))
            table.setItem(i, 3, QTableWidgetItem("Yes" if row[3] else "No"))
            
            combo = QComboBox()
            combo.addItems(["End", "Start", "Both", "None"])
            combo.setCurrentText(row[4])
            combo.setStyleSheet("QComboBox { border: none; padding-left: 4px; background: transparent; } QComboBox::drop-down { border: none; }")
            
            combo.currentTextChanged.connect(lambda text: self.save_tables_to_data())
            
            table.setCellWidget(i, 4, combo)
            
        table.blockSignals(False)

    def save_tables_to_data(self):
        self.x_data = self.read_table(self.table_x['table'], self.x_data)
        self.y_data = self.read_table(self.table_y['table'], self.y_data)
        self.z_data = self.read_table(self.table_z['table'], self.z_data)
        self.update_preview()

    def read_table(self, table, old_data):
        new_data = []
        rows = table.rowCount()
        raw_vals = []
        ids = []
        
        for r in range(rows):
            it_id = table.item(r, 0)
            it_val = table.item(r, 1)
            ids.append(it_id.text() if it_id else "")
            try: val = float(it_val.text()) if it_val else 0.0
            except: val = 0.0
            raw_vals.append(val)
            
        final_ordinates = []
        if self.current_mode == "ordinate":
            final_ordinates = raw_vals
        else:
                                                     
            current_pos = old_data[0][1] if old_data else 0.0
            final_ordinates.append(current_pos)
                                                        
            for i in range(len(raw_vals) - 1):
                current_pos += raw_vals[i]
                final_ordinates.append(current_pos)

        for r in range(rows):
                                                                 
            it_type = table.item(r, 2)
            l_type = it_type.text() if it_type else "Primary"
            
            it_vis = table.item(r, 3)
                                                     
            is_visible = (it_vis.text() == "Yes") if it_vis else True
            
            combo_bub = table.cellWidget(r, 4)
            bub_loc = combo_bub.currentText() if combo_bub else "End"
            
            new_data.append([ids[r], final_ordinates[r], l_type, is_visible, bub_loc])
            
        return new_data

    def on_table_changed(self, item):
        self.save_tables_to_data()

    def update_preview(self):
        idx = self.combo_plane.currentIndex()
        
        if idx == 0:           
            h_data = [(row[0], row[1], row[4]) for row in self.x_data]                  
            v_data = [(row[0], row[1], row[4]) for row in self.y_data]                
            plane_name = "XY"
        elif idx == 1:           
            h_data = [(row[0], row[1], row[4]) for row in self.x_data]                  
            v_data = [(row[0], row[1], row[4]) for row in self.z_data]                
            plane_name = "XZ"
        else:           
            h_data = [(row[0], row[1], row[4]) for row in self.y_data]                  
            v_data = [(row[0], row[1], row[4]) for row in self.z_data]                
            plane_name = "YZ"

        self.preview.update_data(h_data, v_data, plane_name, self.spin_bubble.value(),
                                 self.spin_bubble_alpha.value() / 100.0,
                                 self.spin_bubble_line_width.value(),
                                 self.spin_bubble_extension.value(),
                                 style_values=self._resolved(), dark=self._dark,
                                 bubble_ext_width=self._ext_width())

    def add_grid_line(self, axis):
        if axis == 'x': data = self.x_data; tbl = self.table_x['table']
        elif axis == 'y': data = self.y_data; tbl = self.table_y['table']
        else: data = self.z_data; tbl = self.table_z['table']
        
        if len(data) >= 2:
            last_ord = data[-1][1]
            prev_ord = data[-2][1]
            spacing = last_ord - prev_ord
            
            if abs(spacing) < 0.001: spacing = unit_registry.to_display_length(3.0)
        else:
            last_ord = data[-1][1] if data else 0.0
            base_spacing = 3.0 if axis == 'z' else 5.0 
                                              
            spacing = unit_registry.to_display_length(base_spacing)

        new_ord = last_ord + spacing

        last_id = data[-1][0] if data else "0"
        match = re.match(r"([A-Za-z]*)(\d+)", last_id)
        if match:
            prefix, num = match.groups()
            new_id = f"{prefix}{int(num)+1}"
        else:
            new_id = f"{len(data)+1}"
                             
        data.append([new_id, new_ord, "Primary", True, "End"])
        
        self.populate_table(tbl, data)
        self.save_tables_to_data()

    def delete_grid_line(self, axis):
        if axis == 'x': data = self.x_data; tbl = self.table_x['table']
        elif axis == 'y': data = self.y_data; tbl = self.table_y['table']
        else: data = self.z_data; tbl = self.table_z['table']
        
        row = tbl.currentRow()
        if row < 0: return 
        del data[row]
        self.populate_table(tbl, data)
        self.save_tables_to_data()

    def get_final_grids(self):
        """Returns list of dicts for the new GridLines class (converted back to base SI units)."""
        def pack(data_list):
            sorted_data = sorted(data_list, key=lambda x: x[1])
            packed = []
            for row in sorted_data:
                                                        
                base_val = unit_registry.from_display_length(row[1])
                packed.append({
                    'id': row[0],
                    'ord': base_val,
                    'visible': row[3],
                    'bubble': row[4]
                })
            return packed

        return {
            "x": pack(self.x_data),
            "y": pack(self.y_data),
            "z": pack(self.z_data),
            "bubble_size": self.spin_bubble.value(),
            "bubble_alpha": self.spin_bubble_alpha.value() / 100.0,
            "bubble_line_width": self.spin_bubble_line_width.value(),
            "bubble_extension": self.spin_bubble_extension.value(),
            "bubble_ext_line_width": self._ext_width(),
            "style": self._final_style()
        }
    
    def toggle_all_axes_visibility(self):
        """Master toggle — hides or shows every gridline across all three axes."""
        self._all_visible = not self._all_visible
        target_text = "Yes" if self._all_visible else "No"
        self.btn_global_viz.setText("Hide All Gridlines" if self._all_visible else "Show All Gridlines")

        for tbl in (self.table_x['table'], self.table_y['table'], self.table_z['table']):
            tbl.blockSignals(True)
            for r in range(tbl.rowCount()):
                tbl.setItem(r, 3, QTableWidgetItem(target_text))
            tbl.blockSignals(False)

        self.save_tables_to_data()

    def toggle_all_visibility(self, axis):
                                  
        if axis == 'x': tbl = self.table_x['table']
        elif axis == 'y': tbl = self.table_y['table']
        else: tbl = self.table_z['table']

        rows = tbl.rowCount()
        if rows == 0: return

        first_item = tbl.item(0, 3)
        current_state = (first_item.text() == "Yes")
        target_text = "No" if current_state else "Yes"
        
        tbl.blockSignals(True)                          
        for r in range(rows):
            tbl.setItem(r, 3, QTableWidgetItem(target_text))
        tbl.blockSignals(False)
        
        self.save_tables_to_data()

    def toggle_all_bubbles(self, axis):
        """Cycles all bubble dropdowns in a specific table to the next state."""
                                                          
        if axis == 'x': tbl = self.table_x['table']
        elif axis == 'y': tbl = self.table_y['table']
        else: tbl = self.table_z['table']

        rows = tbl.rowCount()
        if rows == 0: return

        first_combo = tbl.cellWidget(0, 4)
        if not first_combo: return
        
        current_state = first_combo.currentText()
        sequence = ["End", "Start", "Both", "None"]
        
        try:
            next_index = (sequence.index(current_state) + 1) % len(sequence)
        except ValueError:
            next_index = 0
            
        target_state = sequence[next_index]

        for r in range(rows):
            combo = tbl.cellWidget(r, 4)
            if combo:
                                                                                   
                combo.blockSignals(True) 
                combo.setCurrentText(target_state)
                combo.blockSignals(False)
        
        self.save_tables_to_data()
