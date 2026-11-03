from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QSlider, QSpinBox, QCheckBox, QPushButton, 
                             QColorDialog, QTabWidget, QWidget, QGroupBox,
                             QDoubleSpinBox, QComboBox)                                               
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

from app.ui.theme import (apply_dialog_style, COLORS, set_theme, current_theme,
                          glass_strength, set_glass_strength,
                          glass_transparency, set_glass_transparency, GLASS_MAX_TRANSPARENCY)
from app.ui.blur import blur_supported
from graphic.mouse_crosshair import CrosshairSettingsWidget

class ColorButton(QPushButton):
    """A helper button that shows the selected color."""
    def __init__(self, color_tuple, parent=None):
        super().__init__(parent)
        self.setFixedSize(60, 25)
        self.color = self._tuple_to_qcolor(color_tuple)
        self._update_style()
        self.clicked.connect(self.pick_color)

    def _tuple_to_qcolor(self, t):
                                                     
        return QColor(int(t[0]*255), int(t[1]*255), int(t[2]*255), int(t[3]*255))

    def _qcolor_to_tuple(self, c):
                                            
        return (c.redF(), c.greenF(), c.blueF(), c.alphaF())

    def _update_style(self):
                                        
        c = self.color
                                                        
        text_color = "white" if (c.red() + c.green() + c.blue()) / 3 < 128 else "black"
        self.setStyleSheet(f"background-color: {c.name()}; border: 1px solid {COLORS['text_secondary']}; color: {text_color};")
        self.setText("Pick")

    def pick_color(self):
        new_c = QColorDialog.getColor(self.color, self.parent(), "Select Color", QColorDialog.ColorDialogOption.ShowAlphaChannel)
        if new_c.isValid():
            self.color = new_c
            self._update_style()

    def get_color_tuple(self):
        return self._qcolor_to_tuple(self.color)

class GraphicsOptionsDialog(QDialog):
    def __init__(self, parent=None, current_settings=None):
        super().__init__(parent)
        apply_dialog_style(self)
        self.setWindowTitle("Graphics Options")
        self.resize(470, 380)
        self.settings = current_settings or {}
        
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        tab_gen = QWidget()
        v_gen = QVBoxLayout(tab_gen)

        h_theme = QHBoxLayout()
        h_theme.addWidget(QLabel("UI Theme:"))
        self.combo_theme = QComboBox()
        self.combo_theme.addItems(["Light", "Dark"])
        self.combo_theme.setCurrentText(self.settings.get("ui_theme", "Light"))
        self.combo_theme.currentTextChanged.connect(self._auto_switch_canvas_colors)
        h_theme.addWidget(self.combo_theme)
        v_gen.addLayout(h_theme)
        
        h_bg = QHBoxLayout()
        h_bg.addWidget(QLabel("Background Color:"))
        self.btn_bg = ColorButton(self.settings.get("background_color", (1,1,1,1)), self)
        
        current_theme = self.combo_theme.currentText()
        bg_sum = sum(self.btn_bg.get_color_tuple()[:3])
        if current_theme == "Dark" and bg_sum > 2.5:
            self._auto_switch_canvas_colors("Dark")
        elif current_theme == "Light" and bg_sum < 0.5:
            self._auto_switch_canvas_colors("Light")
            
        h_bg.addWidget(self.btn_bg)
        v_gen.addLayout(h_bg)

        h_aa = QHBoxLayout()
        h_aa.addWidget(QLabel("Anti-aliasing (MSAA):"))
        self.combo_aa = QComboBox()
                                                                                    
        for _txt, _code in (("Off", 0), ("FXAA (fast)", 5), ("2x", 4), ("4x", 1), ("8x", 2), ("16x", 3)):
            self.combo_aa.addItem(_txt, _code)
        self.combo_aa.setToolTip("Lower is faster on integrated GPUs. Applies after restart.")
        
        try:
            saved_msaa = int(self.settings.get("msaa_level", 1))
        except (ValueError, TypeError):
            saved_msaa = 1
            
        _idx = self.combo_aa.findData(saved_msaa)
        self.combo_aa.setCurrentIndex(_idx if _idx >= 0 else self.combo_aa.findData(1))
        h_aa.addWidget(self.combo_aa)
        v_gen.addLayout(h_aa)

        h_fx = QHBoxLayout()
        h_fx.addWidget(QLabel("FXAA Strength:"))
        self.sl_fxaa = QSlider(Qt.Orientation.Horizontal)
        self.sl_fxaa.setRange(0, 100)
        try:
            _fx = int(self.settings.get("fxaa_strength", 60))
        except (ValueError, TypeError):
            _fx = 60
        self.sl_fxaa.setValue(max(0, min(100, _fx)))
        self.lbl_fxaa = QLabel(f"{self.sl_fxaa.value()}%")
        self.lbl_fxaa.setMinimumWidth(36)
        self.sl_fxaa.valueChanged.connect(lambda v: self.lbl_fxaa.setText(f"{v}%"))
        self.sl_fxaa.setToolTip("Low = crisper lines, High = smoother edges. Applies instantly with Apply.")
        h_fx.addWidget(self.sl_fxaa)
        h_fx.addWidget(self.lbl_fxaa)
        v_gen.addLayout(h_fx)
        self.combo_aa.currentIndexChanged.connect(
            lambda _i: self.sl_fxaa.setEnabled(self.combo_aa.currentData() == 5))
        self.sl_fxaa.setEnabled(self.combo_aa.currentData() == 5)

        h_glass = QHBoxLayout()
        h_glass.addWidget(QLabel("Glass Blur Strength:"))
        self.sl_glass = QSlider(Qt.Orientation.Horizontal)
        self.sl_glass.setRange(0, 100)
        try:
            _gs = int(self.settings.get("glass_strength", glass_strength()))
        except (ValueError, TypeError):
            _gs = glass_strength()
        self.sl_glass.setValue(max(0, min(100, _gs)))
        self.lbl_glass = QLabel(f"{self.sl_glass.value()}%")
        self.lbl_glass.setMinimumWidth(36)
        self.sl_glass.valueChanged.connect(lambda v: self.lbl_glass.setText(f"{v}%"))
        h_glass.addWidget(self.sl_glass)
        h_glass.addWidget(self.lbl_glass)
        self.sl_glass.setToolTip("0% = solid windows, 100% = most see-through (more of the "
                                 "blurred background shows through menus, dialogs and the "
                                 "command palette).")
        if not blur_supported():
            self.sl_glass.setEnabled(False)
            self.sl_glass.setToolTip("Blur is only available on Windows 10/11.")
        v_gen.addLayout(h_glass)

        h_transp = QHBoxLayout()
        h_transp.addWidget(QLabel("Glass Transparency:"))
        self.sl_transp = QSlider(Qt.Orientation.Horizontal)
        self.sl_transp.setRange(0, GLASS_MAX_TRANSPARENCY)
        try:
            _gt = int(self.settings.get("glass_transparency", glass_transparency()))
        except (ValueError, TypeError):
            _gt = glass_transparency()
        self.sl_transp.setValue(max(0, min(GLASS_MAX_TRANSPARENCY, _gt)))
        self.lbl_transp = QLabel(f"{self.sl_transp.value()}%")
        self.lbl_transp.setMinimumWidth(36)
        self.sl_transp.valueChanged.connect(lambda v: self.lbl_transp.setText(f"{v}%"))
        h_transp.addWidget(self.sl_transp)
        h_transp.addWidget(self.lbl_transp)
        self.sl_transp.setToolTip(f"Extra see-through on top of the blur (max {GLASS_MAX_TRANSPARENCY}%, "
                                  "so windows never become fully transparent). Text stays sharp.")
        if not blur_supported():
            self.sl_transp.setEnabled(False)
            self.sl_transp.setToolTip("Blur is only available on Windows 10/11.")
        v_gen.addLayout(h_transp)
        lbl_note = QLabel("MSAA changes apply after restart. Other settings apply with Apply.")
        lbl_note.setObjectName("hint")
        lbl_note.setWordWrap(True)
        v_gen.addWidget(lbl_note)

        self.btn_restart = QPushButton("Restart Now")
        self.btn_restart.setObjectName("secondary")
        self.btn_restart.clicked.connect(self._on_restart)
        v_gen.addWidget(self.btn_restart)
        
        v_gen.addStretch()
        self.tabs.addTab(tab_gen, "General")

        tab_nodes = QWidget()
        v_nodes = QVBoxLayout(tab_nodes)
        
        h_ns = QHBoxLayout()
        h_ns.addWidget(QLabel("Node Size (px):"))
        self.spin_node_size = QSpinBox()
        self.spin_node_size.setRange(2, 20)
        self.spin_node_size.setValue(self.settings.get("node_size", 6))
        h_ns.addWidget(self.spin_node_size)
        v_nodes.addLayout(h_ns)

        h_nc = QHBoxLayout()
        h_nc.addWidget(QLabel("Node Color:"))
        self.btn_node_col = ColorButton(self.settings.get("node_color", (1,0,0,1)), self)
        h_nc.addWidget(self.btn_node_col)
        v_nodes.addLayout(h_nc)

        v_nodes.addStretch()
        self.tabs.addTab(tab_nodes, "Joints")

        tab_frames = QWidget()
        v_frames = QVBoxLayout(tab_frames)
        
        g_wire = QGroupBox("Wireframe (Stick Mode)")
        l_wire = QVBoxLayout(g_wire)
        h_lw = QHBoxLayout()
        h_lw.addWidget(QLabel("Line Width:"))
        
        self.spin_line_width = QDoubleSpinBox()
        self.spin_line_width.setRange(0.1, 10.0)
        self.spin_line_width.setSingleStep(0.5)
        self.spin_line_width.setValue(float(self.settings.get("line_width", 2.0)))
        
        h_lw.addWidget(self.spin_line_width)
        l_wire.addLayout(h_lw)
        v_frames.addWidget(g_wire)

        g_ext = QGroupBox("Extruded (Solid Mode)")
        l_ext = QVBoxLayout(g_ext)
        
        h_op = QHBoxLayout()
        h_op.addWidget(QLabel("Face Transparency:"))                      
        self.sl_ext_op = QSlider(Qt.Orientation.Horizontal)
        self.sl_ext_op.setRange(0, 100)            
        self.sl_ext_op.setValue(round((1.0 - self.settings.get("extrude_opacity", 0.35)) * 100))
        self.lbl_ext_op = QLabel(f"{self.sl_ext_op.value()}%")
        self.lbl_ext_op.setMinimumWidth(36)
        self.sl_ext_op.valueChanged.connect(lambda v: self.lbl_ext_op.setText(f"{v}%"))
        self.sl_ext_op.setToolTip("0% = opaque faces; 100% = invisible faces. "
                                  "Applies to extruded frames and slabs with Apply.")
        h_op.addWidget(self.sl_ext_op)
        h_op.addWidget(self.lbl_ext_op)
        l_ext.addLayout(h_op)

        self.chk_edges = QCheckBox("Show Edges")
        self.chk_edges.setChecked(self.settings.get("show_edges", False))
        l_ext.addWidget(self.chk_edges)

        h_edge_op = QHBoxLayout()
        h_edge_op.addWidget(QLabel("Hidden Edge Transparency:"))
        self.sl_edge_op = QSlider(Qt.Orientation.Horizontal)
        self.sl_edge_op.setRange(0, 100)
        self.sl_edge_op.setValue(round((1.0 - self.settings.get("edge_opacity", 0.08)) * 100))
        self.lbl_edge_op = QLabel(f"{self.sl_edge_op.value()}%")
        self.lbl_edge_op.setMinimumWidth(36)
        self.sl_edge_op.valueChanged.connect(lambda v: self.lbl_edge_op.setText(f"{v}%"))
        self.sl_edge_op.setToolTip("Controls rear edge traces: 0% = opaque; 100% = invisible. "
                                   "Visible outlines retain the Edge Color alpha.")
        h_edge_op.addWidget(self.sl_edge_op)
        h_edge_op.addWidget(self.lbl_edge_op)
        l_ext.addLayout(h_edge_op)
                                          
        h_ec = QHBoxLayout()
        h_ec.addWidget(QLabel("Edge Color:"))
        self.btn_edge_col = ColorButton(self.settings.get("edge_color", (0,0,0,1)), self)
        h_ec.addWidget(self.btn_edge_col)
        l_ext.addLayout(h_ec)
        
        h_ew = QHBoxLayout()
        h_ew.addWidget(QLabel("Edge Width:"))
        
        self.spin_edge_width = QDoubleSpinBox()
        self.spin_edge_width.setRange(0.1, 5.0)
        self.spin_edge_width.setSingleStep(0.05)
        self.spin_edge_width.setDecimals(2)
        self.spin_edge_width.setValue(float(self.settings.get("edge_width", 1.0)))
        
        h_ew.addWidget(self.spin_edge_width)
        l_ext.addLayout(h_ew)

        v_frames.addWidget(g_ext)
        v_frames.addStretch()
        self.tabs.addTab(tab_frames, "Frames")

        tab_fibers = QWidget()
        v_fibers = QVBoxLayout(tab_fibers)

        h_fs = QHBoxLayout()
        h_fs.addWidget(QLabel("Fiber Marker Shape:"))
        self.combo_hinge_shape = QComboBox()
        self.combo_hinge_shape.addItems(["Circle", "Square", "Diamond"])
        self.combo_hinge_shape.setCurrentText(self.settings.get("hinge_shape", "Circle"))
        h_fs.addWidget(self.combo_hinge_shape)
        v_fibers.addLayout(h_fs)

        h_fc = QHBoxLayout()
        h_fc.addWidget(QLabel("Fiber Marker Color:"))
        self.btn_hinge_col = ColorButton(self.settings.get("hinge_color", (0.0, 0.47, 0.84, 1.0)), self)
        h_fc.addWidget(self.btn_hinge_col)
        v_fibers.addLayout(h_fc)

        lbl_fiber_note = QLabel("Color applies when the fiber is undeformed / has no state. "
                                "During analysis steps the state colors (cracked, yielded, ...) still take over.")
        lbl_fiber_note.setObjectName("hint")
        lbl_fiber_note.setWordWrap(True)
        v_fibers.addWidget(lbl_fiber_note)

        v_fibers.addStretch()
        self.tabs.addTab(tab_fibers, "Fibers")

        tab_slabs = QWidget()
        v_slabs = QVBoxLayout(tab_slabs)
        
        g_sedge = QGroupBox("Shell Edges")
        l_sedge = QVBoxLayout(g_sedge)

        self.chk_shell_edges = QCheckBox("Show Edges")
        self.chk_shell_edges.setChecked(bool(self.settings.get("shell_show_edges", True)))
        l_sedge.addWidget(self.chk_shell_edges)

        h_sec = QHBoxLayout()
        h_sec.addWidget(QLabel("Edge Color:"))
        self.btn_shell_edge_col = ColorButton(
            self.settings.get("shell_edge_color", self.settings.get("edge_color", (0, 0, 0, 1))), self)
        h_sec.addWidget(self.btn_shell_edge_col)
        l_sedge.addLayout(h_sec)

        h_sew = QHBoxLayout()
        h_sew.addWidget(QLabel("Edge Width:"))
        self.spin_shell_edge_width = QDoubleSpinBox()
        self.spin_shell_edge_width.setRange(0.1, 5.0)
        self.spin_shell_edge_width.setSingleStep(0.05)
        self.spin_shell_edge_width.setDecimals(2)
        self.spin_shell_edge_width.setValue(float(self.settings.get("shell_edge_width", 1.0)))
        h_sew.addWidget(self.spin_shell_edge_width)
        l_sedge.addLayout(h_sew)

        v_slabs.addWidget(g_sedge)
        v_slabs.addStretch()
        self.tabs.addTab(tab_slabs, "Slabs")

        tab_loads = QWidget()
        v_loads = QVBoxLayout(tab_loads)

        h_load_mode = QHBoxLayout()
        h_load_mode.addWidget(QLabel("Area Load Labels:"))
        self.combo_area_load_mode = QComboBox()
        for text, mode in (("Smart", "smart"), ("Every area", "every_area"),
                           ("Hidden", "hidden")):
            self.combo_area_load_mode.addItem(text, mode)
        load_mode_index = self.combo_area_load_mode.findData(
            self.settings.get("area_load_display_mode", "smart"))
        self.combo_area_load_mode.setCurrentIndex(max(0, load_mode_index))
        self.combo_area_load_mode.setToolTip(
            "Smart shares labels across connected areas with matching loads. "
            "Every area shows individual labels. Hidden hides area load text.")
        h_load_mode.addWidget(self.combo_area_load_mode)
        v_loads.addLayout(h_load_mode)

        h_frame_load_mode = QHBoxLayout()
        h_frame_load_mode.addWidget(QLabel("Frame Distributed Load Labels:"))
        self.combo_frame_load_mode = QComboBox()
        for text, mode in (("Smart", "smart"), ("Every member", "every_member"),
                           ("Hidden", "hidden")):
            self.combo_frame_load_mode.addItem(text, mode)
        frame_mode_index = self.combo_frame_load_mode.findData(
            self.settings.get("frame_load_display_mode", "smart"))
        self.combo_frame_load_mode.setCurrentIndex(max(0, frame_mode_index))
        self.combo_frame_load_mode.setToolTip(
            "Smart shares labels along straight members with continuous matching loads. "
            "Every member shows individual labels. Hidden hides distributed frame load text.")
        h_frame_load_mode.addWidget(self.combo_frame_load_mode)
        v_loads.addLayout(h_frame_load_mode)

        h_load_text = QHBoxLayout()
        h_load_text.addWidget(QLabel("Load Text Size:"))
        self.spin_load_text_size = QSpinBox()
        self.spin_load_text_size.setRange(50, 250)
        self.spin_load_text_size.setSingleStep(10)
        self.spin_load_text_size.setSuffix("%")
        try:
            load_text_percent = round(float(self.settings.get("load_text_scale", 1.0)) * 100)
        except (ValueError, TypeError, OverflowError):
            load_text_percent = 100
        self.spin_load_text_size.setValue(load_text_percent)
        self.spin_load_text_size.setToolTip(
            "Scales assigned-load text. 100% keeps the current size. "
            "Force diagram text size is set in Display Forces.")
        h_load_text.addWidget(self.spin_load_text_size)
        v_loads.addLayout(h_load_text)

        h_arrow_spacing = QHBoxLayout()
        h_arrow_spacing.addWidget(QLabel("Arrow Spacing Guide:"))
        self.spin_area_load_arrow_spacing = QSpinBox()
        self.spin_area_load_arrow_spacing.setRange(20, 150)
        self.spin_area_load_arrow_spacing.setSingleStep(5)
        self.spin_area_load_arrow_spacing.setSuffix(" px")
        try:
            arrow_spacing = round(float(self.settings.get("area_load_arrow_spacing", 55.0)))
        except (ValueError, TypeError, OverflowError):
            arrow_spacing = 55
        self.spin_area_load_arrow_spacing.setValue(arrow_spacing)
        self.spin_area_load_arrow_spacing.setToolTip(
            "Controls the fixed arrow count and size with Smart or Hidden labels. "
            "Larger values show fewer arrows. Zoom and pan keep their arrangement.")
        h_arrow_spacing.addWidget(self.spin_area_load_arrow_spacing)
        v_loads.addLayout(h_arrow_spacing)
        def update_arrow_spacing(_index=None):
            self.spin_area_load_arrow_spacing.setEnabled(
                self.combo_area_load_mode.currentData() in ("smart", "hidden")
                or self.combo_frame_load_mode.currentData() in ("smart", "hidden"))
        self.combo_area_load_mode.currentIndexChanged.connect(update_arrow_spacing)
        self.combo_frame_load_mode.currentIndexChanged.connect(update_arrow_spacing)
        update_arrow_spacing()

        lbl_load_note = QLabel("Smart changes the display only. Each area's or member's load remains editable.")
        lbl_load_note.setObjectName("hint")
        lbl_load_note.setWordWrap(True)
        v_loads.addWidget(lbl_load_note)
        v_loads.addStretch()
        self.tabs.addTab(tab_loads, "Loads")

        self.xh_widget = CrosshairSettingsWidget(self.settings, ColorButton, self)
        self.tabs.addTab(self.xh_widget, "Crosshair")

        tab_light = QWidget()
        v_light = QVBoxLayout(tab_light)

        self.chk_lighting = QCheckBox("Enable Lighting (Blinn-Phong)")
        self.chk_lighting.setChecked(self.settings.get("lighting_enabled", False))
        self.chk_lighting.toggled.connect(self._on_lighting_toggled)
        v_light.addWidget(self.chk_lighting)

        lbl_light_note = QLabel("Lighting applies to frame and slab faces, including animation. "
                                "Contour colors stay unshaded. Lines and joints keep flat colors.")
        lbl_light_note.setObjectName("hint")
        lbl_light_note.setWordWrap(True)
        v_light.addWidget(lbl_light_note)

        g_dir = QGroupBox("Light Direction")
        l_dir = QVBoxLayout(g_dir)

        h_az = QHBoxLayout()
        h_az.addWidget(QLabel("Azimuth:"))
        self.sl_light_az = QSlider(Qt.Orientation.Horizontal)
        self.sl_light_az.setRange(0, 360)
        self.sl_light_az.setValue(int(self.settings.get("light_azimuth", 45.0)))
        self.lbl_light_az = QLabel(f"{self.sl_light_az.value()}°")
        self.lbl_light_az.setMinimumWidth(36)
        self.sl_light_az.valueChanged.connect(lambda v: self.lbl_light_az.setText(f"{v}°"))
        self.sl_light_az.setToolTip("Direction toward the light in the global XY plane, measured from +X.")
        h_az.addWidget(self.sl_light_az)
        h_az.addWidget(self.lbl_light_az)
        l_dir.addLayout(h_az)

        h_el = QHBoxLayout()
        h_el.addWidget(QLabel("Elevation:"))
        self.sl_light_el = QSlider(Qt.Orientation.Horizontal)
        self.sl_light_el.setRange(0, 90)
        self.sl_light_el.setValue(int(self.settings.get("light_elevation", 45.0)))
        self.lbl_light_el = QLabel(f"{self.sl_light_el.value()}°")
        self.lbl_light_el.setMinimumWidth(36)
        self.sl_light_el.valueChanged.connect(lambda v: self.lbl_light_el.setText(f"{v}°"))
        self.sl_light_el.setToolTip("Light height above the global XY plane: 0° horizontal, 90° overhead.")
        h_el.addWidget(self.sl_light_el)
        h_el.addWidget(self.lbl_light_el)
        l_dir.addLayout(h_el)

        v_light.addWidget(g_dir)

        g_shade = QGroupBox("Shading")
        l_shade = QVBoxLayout(g_shade)

        h_amb = QHBoxLayout()
        h_amb.addWidget(QLabel("Ambient:"))
        self.sl_light_ambient = QSlider(Qt.Orientation.Horizontal)
        self.sl_light_ambient.setRange(0, 100)
        self.sl_light_ambient.setValue(round(self.settings.get("light_ambient", 0.35) * 100))
        self.lbl_light_ambient = QLabel(f"{self.sl_light_ambient.value()}%")
        self.lbl_light_ambient.setMinimumWidth(36)
        self.sl_light_ambient.valueChanged.connect(lambda v: self.lbl_light_ambient.setText(f"{v}%"))
        self.sl_light_ambient.setToolTip("Base brightness on every face, including faces away from the light.")
        h_amb.addWidget(self.sl_light_ambient)
        h_amb.addWidget(self.lbl_light_ambient)
        l_shade.addLayout(h_amb)

        h_dif = QHBoxLayout()
        h_dif.addWidget(QLabel("Diffuse:"))
        self.sl_light_diffuse = QSlider(Qt.Orientation.Horizontal)
        self.sl_light_diffuse.setRange(0, 100)
        self.sl_light_diffuse.setValue(round(self.settings.get("light_diffuse", 0.75) * 100))
        self.lbl_light_diffuse = QLabel(f"{self.sl_light_diffuse.value()}%")
        self.lbl_light_diffuse.setMinimumWidth(36)
        self.sl_light_diffuse.valueChanged.connect(lambda v: self.lbl_light_diffuse.setText(f"{v}%"))
        self.sl_light_diffuse.setToolTip("Brightness added to faces pointing toward the light.")
        h_dif.addWidget(self.sl_light_diffuse)
        h_dif.addWidget(self.lbl_light_diffuse)
        l_shade.addLayout(h_dif)

        h_spec = QHBoxLayout()
        h_spec.addWidget(QLabel("Specular:"))
        self.sl_light_specular = QSlider(Qt.Orientation.Horizontal)
        self.sl_light_specular.setRange(0, 100)
        self.sl_light_specular.setValue(round(self.settings.get("light_specular", 0.25) * 100))
        self.lbl_light_specular = QLabel(f"{self.sl_light_specular.value()}%")
        self.lbl_light_specular.setMinimumWidth(36)
        self.sl_light_specular.valueChanged.connect(lambda v: self.lbl_light_specular.setText(f"{v}%"))
        self.sl_light_specular.setToolTip("Strength of the glossy highlight. Orbit the camera to see it move.")
        h_spec.addWidget(self.sl_light_specular)
        h_spec.addWidget(self.lbl_light_specular)
        l_shade.addLayout(h_spec)

        h_shin = QHBoxLayout()
        h_shin.addWidget(QLabel("Shininess:"))
        self.spin_light_shininess = QSpinBox()
        self.spin_light_shininess.setRange(1, 256)
        self.spin_light_shininess.setValue(int(self.settings.get("light_shininess", 32)))
        self.spin_light_shininess.setToolTip("Higher values make the specular highlight smaller and sharper.")
        h_shin.addWidget(self.spin_light_shininess)
        l_shade.addLayout(h_shin)

        h_glaze = QHBoxLayout()
        h_glaze.addWidget(QLabel("Glass Glaze (Rim Glow):"))
        self.sl_light_fresnel = QSlider(Qt.Orientation.Horizontal)
        self.sl_light_fresnel.setRange(0, 100)
        self.sl_light_fresnel.setValue(round(self.settings.get("light_fresnel_intensity", 0.4) * 100))
        self.lbl_light_fresnel = QLabel(f"{self.sl_light_fresnel.value()}%")
        self.lbl_light_fresnel.setMinimumWidth(36)
        self.sl_light_fresnel.valueChanged.connect(lambda v: self.lbl_light_fresnel.setText(f"{v}%"))
        self.sl_light_fresnel.setToolTip("Rim highlight on faces seen at a shallow angle. "
                                       "0% disables the glaze; orbit the camera to see it change.")
        h_glaze.addWidget(self.sl_light_fresnel)
        h_glaze.addWidget(self.lbl_light_fresnel)
        l_shade.addLayout(h_glaze)

        h_glaze_p = QHBoxLayout()
        h_glaze_p.addWidget(QLabel("Glaze Sharpness:"))
        self.spin_light_fresnel_power = QDoubleSpinBox()
        self.spin_light_fresnel_power.setRange(0.5, 10.0)
        self.spin_light_fresnel_power.setSingleStep(0.5)
        self.spin_light_fresnel_power.setValue(float(self.settings.get("light_fresnel_power", 3.0)))
        self.spin_light_fresnel_power.setToolTip("Higher values concentrate the glaze closer to the silhouette.")
        h_glaze_p.addWidget(self.spin_light_fresnel_power)
        l_shade.addLayout(h_glaze_p)

        v_light.addWidget(g_shade)

        self._lighting_sub_widgets = [g_dir, g_shade]
        self._on_lighting_toggled(self.chk_lighting.isChecked())

        v_light.addStretch()
        self.tabs.addTab(tab_light, "Lighting")

        h_btns = QHBoxLayout()
        h_btns.addStretch()
        self.btn_ok = QPushButton("OK")
        self.btn_ok.setObjectName("primary")
        self.btn_ok.clicked.connect(self._on_ok)
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setObjectName("secondary")
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_apply = QPushButton("Apply")
        self.btn_apply.setObjectName("secondary")
        self.btn_apply.clicked.connect(self.on_apply)
        
        h_btns.addWidget(self.btn_ok)
        h_btns.addWidget(self.btn_cancel)
        h_btns.addWidget(self.btn_apply)
        layout.addLayout(h_btns)

    def _auto_switch_canvas_colors(self, theme_name):
        """Automatically flips the canvas color when theme changes, but leaves edge lines alone."""
        if theme_name == "Dark":
            self.btn_bg.color = QColor(30, 30, 30, 255)                    
        else:
            self.btn_bg.color = QColor(255, 255, 255, 255)                  
            
        self.btn_bg._update_style()

    def select_tab(self, name):
        """Switch to the tab whose title is `name` (used by Edit > Precision Pointer Settings)."""
        for i in range(self.tabs.count()):
            if self.tabs.tabText(i) == name:
                self.tabs.setCurrentIndex(i)
                return

    def _on_lighting_toggled(self, checked):
        for w in getattr(self, "_lighting_sub_widgets", []):
            w.setEnabled(checked)
        
    def _on_restart(self):
        import subprocess, sys, os
        
        parent = self.parent()
        
        if parent and hasattr(parent, "update_graphics_settings"):
            parent.update_graphics_settings(self.get_settings())
        
        file_path = None
        if parent and hasattr(parent, "model") and parent.model:
            file_path = getattr(parent.model, "file_path", None)

        if getattr(sys, 'frozen', False):
            args = [sys.executable]
        else:
            args = [sys.executable, os.path.abspath(sys.argv[0])]
            
        if file_path and os.path.exists(file_path):
            args.append(os.path.abspath(file_path))

        if parent:
            if not parent.close():
                                                                                             
                return 

        subprocess.Popen(args)
        self.accept()

    def get_settings(self):
        """Collects all values from widgets and returns the dict."""
        msaa_idx = int(self.combo_aa.currentData())
        return {
            "ui_theme": self.combo_theme.currentText(),
            "background_color": self.btn_bg.get_color_tuple(),
            "msaa_level": msaa_idx,
            "fxaa_strength": self.sl_fxaa.value(),
            "glass_strength": self.sl_glass.value(),
            "glass_transparency": self.sl_transp.value(),
            "antialias": msaa_idx > 0,                                                     
            "node_size": self.spin_node_size.value(),
            "node_color": self.btn_node_col.get_color_tuple(),
            
            "line_width": self.spin_line_width.value(),
            
            "extrude_opacity": (100 - self.sl_ext_op.value()) / 100.0,
            "show_edges": self.chk_edges.isChecked(),
            "edge_opacity": (100 - self.sl_edge_op.value()) / 100.0,
            "edge_color": self.btn_edge_col.get_color_tuple(),
                                   
            "edge_width": self.spin_edge_width.value(),
            
            "hinge_color": self.btn_hinge_col.get_color_tuple(),
            "hinge_shape": self.combo_hinge_shape.currentText(),

            "shell_show_edges": self.chk_shell_edges.isChecked(),
            "shell_edge_color": self.btn_shell_edge_col.get_color_tuple(),
            "shell_edge_width": self.spin_shell_edge_width.value(),

            "area_load_display_mode": self.combo_area_load_mode.currentData(),
            "frame_load_display_mode": self.combo_frame_load_mode.currentData(),
            "load_text_scale": self.spin_load_text_size.value() / 100.0,
            "area_load_arrow_spacing": float(self.spin_area_load_arrow_spacing.value()),

            **self.xh_widget.get_settings(),

            "lighting_enabled": self.chk_lighting.isChecked(),
            "light_azimuth": float(self.sl_light_az.value()),
            "light_elevation": float(self.sl_light_el.value()),
            "light_ambient": self.sl_light_ambient.value() / 100.0,
            "light_diffuse": self.sl_light_diffuse.value() / 100.0,
            "light_specular": self.sl_light_specular.value() / 100.0,
            "light_shininess": float(self.spin_light_shininess.value()),
            "light_fresnel_intensity": self.sl_light_fresnel.value() / 100.0,
            "light_fresnel_power": float(self.spin_light_fresnel_power.value()),
        }

    def _on_ok(self):
        """Apply settings then close — so OK behaves like Apply + close."""
        self.on_apply()
        self.accept()

    def on_apply(self):
        if self.parent() and hasattr(self.parent(), "update_graphics_settings"):
            self.parent().update_graphics_settings(self.get_settings())
        self._apply_theme_live()

    def _apply_theme_live(self):
        """Switch the whole app's theme / glass strength immediately (theme.py does
        the work), then restyle this dialog. Persisting both stays with the parent
        (ui_theme and glass_strength are saved in the prefs file)."""
        name = self.combo_theme.currentText()
        strength = self.sl_glass.value()
        theme_changed = name != current_theme()
        transp = self.sl_transp.value()
        glass_changed = strength != glass_strength() or transp != glass_transparency()
        if theme_changed or glass_changed:
            if glass_changed:
                set_glass_strength(strength)
                set_glass_transparency(transp)
            if theme_changed:
                set_theme(name)
            apply_dialog_style(self)
            for b in self.findChildren(ColorButton):
                b._update_style()
