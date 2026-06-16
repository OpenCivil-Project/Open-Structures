import os
import json
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QDoubleSpinBox, QCheckBox, QGroupBox,
                             QColorDialog, QSlider)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

class DeformedShapeDialog(QDialog):
    def __init__(self, parent=None, current_scale=50.0, auto_scale=50.0, is_active=False, 
                 show_shadow=True, shadow_color=(0.6, 0.6, 0.6, 0.3),
                 is_animating=False, current_speed=1.0,
                 ltha_mode=False, ltha_n_steps=0, ltha_dt=0.01):
        super().__init__(parent)
        self.setWindowTitle("Deformed Shape & Animation")
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        self.resize(380, 500)

        self.scale_value = current_scale
        self.auto_scale = auto_scale
        self.show_deformed = is_active
        self.shadow_active = show_shadow
        self.shadow_rgba = shadow_color
        self.is_animating = is_animating
        self.anim_speed = current_speed

        self.ltha_mode = ltha_mode
        self.ltha_n_steps = ltha_n_steps
        self.ltha_dt = ltha_dt

        self.prefs_path = os.path.join(os.path.expanduser("~"), ".opencivil_prefs.json")
        self._load_prefs()

        self.init_ui()
        
    def init_ui(self):
        layout = QVBoxLayout(self)

        grp_vis = QGroupBox("Visualization")
        v_layout = QVBoxLayout()

        self.chk_show = QCheckBox("Show Deformed Shape")
        self.chk_show.setChecked(self.show_deformed)
        self.chk_show.toggled.connect(self.on_toggle_show)
        v_layout.addWidget(self.chk_show)

        self.chk_shadow = QCheckBox("Show Undeformed Shadow")
        self.chk_shadow.setChecked(self.shadow_active)
        v_layout.addWidget(self.chk_shadow)

        h_col = QHBoxLayout()
        h_col.addWidget(QLabel("Shadow Color:"))
        self.btn_color = QPushButton()
        self.btn_color.setFixedSize(50, 25)
        self.update_color_button()
        self.btn_color.clicked.connect(self.pick_color)
        h_col.addWidget(self.btn_color)
        h_col.addStretch()
        v_layout.addLayout(h_col)
        grp_vis.setLayout(v_layout)
        layout.addWidget(grp_vis)

        grp_scale = QGroupBox("Scaling")
        s_layout = QVBoxLayout()
        
        lbl_layout = QHBoxLayout()
        lbl_layout.addWidget(QLabel("Scale Factor (Magnification):"))
        
        self.btn_normalize = QPushButton("Normalize")
        self.btn_normalize.setToolTip("Reset to auto-calculated ideal scale")
        self.btn_normalize.clicked.connect(self.on_normalize)
        lbl_layout.addWidget(self.btn_normalize)
        lbl_layout.addStretch()
        s_layout.addLayout(lbl_layout)
                                                            
        self.spin_scale = QDoubleSpinBox()
        self.spin_scale.setRange(0.1, 10000.0)
        self.spin_scale.setValue(self.scale_value)
        self.spin_scale.setSingleStep(10.0)
        
        # Change this line from 1 to 4
        self.spin_scale.setDecimals(4) 
        
        self.spin_scale.setEnabled(self.show_deformed)
        self.spin_scale.valueChanged.connect(self.on_apply)
        s_layout.addWidget(self.spin_scale)
        grp_scale.setLayout(s_layout)
        layout.addWidget(grp_scale)

        self.grp_anim = QGroupBox("Animation  —  LTHA Time History" if self.ltha_mode else "Animation")
        self.grp_anim.setEnabled(self.show_deformed)                                   
        a_layout = QVBoxLayout()

        h_anim = QHBoxLayout()
        self.btn_animate = QPushButton("▶  Play")
        self.btn_animate.setCheckable(True)
        self.btn_animate.setChecked(self.is_animating)
        self.btn_animate.clicked.connect(self.on_toggle_anim)
        self.update_anim_button_style()

        self.chk_sound = QCheckBox("Sound")
        self.chk_sound.setChecked(True)
        self.chk_sound.setVisible(not self.ltha_mode)                                

        h_anim.addWidget(self.btn_animate)
        h_anim.addWidget(self.chk_sound)
        a_layout.addLayout(h_anim)

        if self.ltha_mode:
                                                        
            total_duration = self.ltha_n_steps * self.ltha_dt
            self.lbl_time = QLabel(f"t = 0.00 s  /  {total_duration:.2f} s")
            self.lbl_time.setStyleSheet("font-family: monospace; font-weight: bold;")
            self.lbl_time.setAlignment(Qt.AlignmentFlag.AlignCenter)
            a_layout.addWidget(self.lbl_time)

            self.slider_scrub = QSlider(Qt.Orientation.Horizontal)
            self.slider_scrub.setRange(0, max(0, self.ltha_n_steps - 1))
            self.slider_scrub.setValue(0)
            self.slider_scrub.valueChanged.connect(self.on_scrub)
            a_layout.addWidget(self.slider_scrub)
        else:
            self.lbl_time = None
            self.slider_scrub = None

        h_speed = QHBoxLayout()
        h_speed.addWidget(QLabel("Speed:"))
        self._speed_buttons = {}
        for label, val in [("0.5x", 0.5), ("1x", 1.0), ("2x", 2.0), ("5x", 5.0), ("10x", 10.0)]:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setFixedWidth(40)
            btn.clicked.connect(lambda checked, v=val: self.on_speed_toggle(v))
            h_speed.addWidget(btn)
            self._speed_buttons[val] = btn
        h_speed.addStretch()
        a_layout.addLayout(h_speed)
        self._speed_buttons[1.0].setChecked(True)

        if self.ltha_mode:
            total_dur = self.ltha_n_steps * self.ltha_dt

            h_range = QHBoxLayout()
            h_range.addWidget(QLabel("Start (s):"))
            self.spin_start = QDoubleSpinBox()
            self.spin_start.setRange(0.0, total_dur)
            self.spin_start.setValue(0.0)
            self.spin_start.setSingleStep(1.0)
            self.spin_start.setDecimals(2)
            self.spin_start.setMinimumWidth(90)                               
            self.spin_start.valueChanged.connect(self._on_range_changed)
            h_range.addWidget(self.spin_start)

            h_range.addSpacing(8)
            h_range.addWidget(QLabel("End (s):"))
            self.spin_end = QDoubleSpinBox()
            self.spin_end.setRange(0.0, total_dur)
            self.spin_end.setValue(total_dur)
            self.spin_end.setSingleStep(1.0)
            self.spin_end.setDecimals(2)
            self.spin_end.setMinimumWidth(90)                               
            self.spin_end.valueChanged.connect(self._on_range_changed)
            h_range.addWidget(self.spin_end)
            h_range.addStretch()
            a_layout.addLayout(h_range)

            self.btn_prerender = QPushButton("Pre-Animate")
            self.btn_prerender.setToolTip("Pre-computes frames for the selected time window.")
            self.btn_prerender.clicked.connect(self.on_prerender)
            
            self.btn_clear_pre = QPushButton("Clear")
            self.btn_clear_pre.setToolTip("Clear pre-rendered window and return to full record.")
            self.btn_clear_pre.clicked.connect(self.on_clear_prerender)
            
            h_pre = QHBoxLayout()
            h_pre.addWidget(self.btn_prerender)
            h_pre.addWidget(self.btn_clear_pre)
            a_layout.addLayout(h_pre)
        else:
            self.spin_start = None
            self.spin_end   = None
            self.btn_prerender = None

        self.grp_anim.setLayout(a_layout)
        layout.addWidget(self.grp_anim)

        layout.addStretch()

        btn_layout = QHBoxLayout()
        btn_apply = QPushButton("Apply")
        btn_apply.clicked.connect(self.on_apply)
        btn_ok = QPushButton("Close")
        btn_ok.clicked.connect(self.accept)
        btn_layout.addStretch()
        btn_layout.addWidget(btn_apply)
        btn_layout.addWidget(btn_ok)
        layout.addLayout(btn_layout)

    def update_color_button(self):
        r, g, b, a = self.shadow_rgba
        c_str = f"rgba({int(r*255)}, {int(g*255)}, {int(b*255)}, {a})"
        self.btn_color.setStyleSheet(f"background-color: {c_str}; border: 1px solid #555;")

    def on_clear_prerender(self):
        """Action for the Clear button."""
        if not self.ltha_mode or not self.parent():
            return
            
        if hasattr(self.parent(), 'clear_ltha_prerender'):
            self.parent().clear_ltha_prerender()
            
        self.btn_prerender.setText("Pre-Animate")

    def pick_color(self):
        r, g, b, a = self.shadow_rgba
        initial = QColor()
        initial.setRgbF(r, g, b, a)
        color = QColorDialog.getColor(initial, self, "Pick Shadow Color", QColorDialog.ColorDialogOption.ShowAlphaChannel)
        if color.isValid():
            self.shadow_rgba = color.getRgbF()
            self.update_color_button()
            self.on_apply()

    def on_toggle_show(self, checked):
        if hasattr(self, 'spin_scale'):
            self.spin_scale.setEnabled(checked)
            
        if hasattr(self, 'grp_anim'):
            self.grp_anim.setEnabled(checked)
            
        if not checked and hasattr(self, 'btn_animate') and self.btn_animate.isChecked():
            self.btn_animate.setChecked(False)
            self.on_toggle_anim()
            
        self.on_apply()

    def update_anim_button_style(self):
        if self.btn_animate.isChecked():
            self.btn_animate.setText("⏸  Pause")
            self.btn_animate.setStyleSheet("font-weight: bold;")
            self.spin_scale.setEnabled(False)
        else:
            lbl = "▶  Play" if self.ltha_mode else "Start Animation"
            self.btn_animate.setText(lbl)
            self.btn_animate.setStyleSheet("font-weight: bold;")
            self.spin_scale.setEnabled(True)

    def on_toggle_anim(self):
        self.update_anim_button_style()
        self.is_animating = self.btn_animate.isChecked()
        if self.parent():
            self.parent().toggle_animation(
                self.is_animating,
                self.chk_sound.isChecked()
            )

    def on_scrub(self, value):
        """Called when user drags the LTHA scrubber slider."""
        if not self.ltha_mode:
            return
                           
        t_sec = value * self.ltha_dt
        total_duration = self.ltha_n_steps * self.ltha_dt
        self.lbl_time.setText(f"t = {t_sec:.2f} s  /  {total_duration:.2f} s")
                                                     
        if self.parent():
            mgr = self.parent().canvas.animation_manager
            mgr.scrub_to_step(value)

    def update_scrubber(self, t_index):
        """
        Called externally during playback to keep scrubber in sync.
        Connect animation_manager.signal_ltha_frame_update to this via main.py.
        """
        if not self.ltha_mode or self.slider_scrub is None:
            return
                                                                                   
        self.slider_scrub.blockSignals(True)
        self.slider_scrub.setValue(t_index)
        self.slider_scrub.blockSignals(False)
        t_sec = t_index * self.ltha_dt
        total_duration = self.ltha_n_steps * self.ltha_dt
        self.lbl_time.setText(f"t = {t_sec:.2f} s  /  {total_duration:.2f} s")

    def on_speed_toggle(self, value):
        for v, btn in self._speed_buttons.items():
            btn.setChecked(v == value)
        self.anim_speed = value
        if self.parent():
            self.parent().set_animation_speed(value)

    def _on_range_changed(self):
        """Notify canvas to repaint the highlighted region on the accelerogram."""
        if not self.ltha_mode or self.spin_start is None:
            return
                            
        if self.spin_start.value() >= self.spin_end.value():
            return
        if self.parent() and hasattr(self.parent(), 'canvas'):
            t_start = self.spin_start.value()
            t_end   = self.spin_end.value()
            self.parent().canvas.ltha_highlight = (t_start, t_end)
            self.parent().canvas._invalidate_accel_pixmap()                                             
            self.parent().canvas.update()

    def on_prerender(self):
        if not self.ltha_mode or not self.parent():
            return
        if not hasattr(self.parent(), 'prerender_ltha_animation'):
            return
        t_start = self.spin_start.value() if self.spin_start else 0.0
        t_end   = self.spin_end.value()   if self.spin_end   else self.ltha_n_steps * self.ltha_dt
        self.btn_prerender.setEnabled(False)
        self.btn_prerender.setText("Pre-Animating...")
        self.parent().prerender_ltha_animation(t_start, t_end, self._on_prerender_done)

    def _on_prerender_done(self):
        self.btn_prerender.setEnabled(True)
        self.btn_prerender.setText("Pre-Animate  ✓")
        
        if not self.btn_animate.isChecked():
            self.btn_animate.setChecked(True)
            self.on_toggle_anim()

    def on_apply(self):
        if self.parent():
            self.parent().apply_deformed_shape(
                self.chk_show.isChecked(), 
                self.spin_scale.value(),
                self.chk_shadow.isChecked(),
                self.shadow_rgba
            )
            if self.chk_show.isChecked() and hasattr(self.parent(), 'canvas'):
                self.parent().canvas.clear_force_diagrams()
            
    def accept(self):
                                                  
        super().accept()

    def force_exit_animation_mode(self):
        """
        Called by MainWindow when unlocking the model.
        Forces the dialog UI back to 'Start Animation' state.
        """
        self.is_animating = False
        self.btn_animate.setChecked(False)
        self.update_anim_button_style()
        self.chk_show.setChecked(False)

    def _load_prefs(self):
        """Loads animation preferences from the JSON file."""
        if os.path.exists(self.prefs_path):
            try:
                with open(self.prefs_path, 'r') as f:
                    prefs = json.load(f)
                    
                if not self.is_animating:
                    self.scale_value = prefs.get("deflection_scale", self.scale_value)
                    self.anim_speed = prefs.get("anim_speed", self.anim_speed)
                    
                self.shadow_active = prefs.get("shadow_active", self.shadow_active)
                
                saved_color = prefs.get("shadow_color")
                if saved_color and len(saved_color) == 4:
                    self.shadow_rgba = tuple(saved_color)
            except Exception as e:
                print(f"Failed to load animation prefs: {e}")

    def _save_prefs(self):
        """Saves current animation settings back to the JSON file."""
        prefs = {}
                                                                                           
        if os.path.exists(self.prefs_path):
            try:
                with open(self.prefs_path, 'r') as f:
                    prefs = json.load(f)
            except:
                pass
                
        prefs["deflection_scale"] = self.spin_scale.value()
        prefs["anim_speed"] = self.anim_speed
        prefs["shadow_active"] = self.chk_shadow.isChecked()
        prefs["shadow_color"] = self.shadow_rgba

        try:
            with open(self.prefs_path, 'w') as f:
                json.dump(prefs, f, indent=4)
        except Exception as e:
            print(f"Failed to save animation prefs: {e}")

    def accept(self):
                             
        self._save_prefs()
        super().accept()

    def on_normalize(self):
        self.spin_scale.setValue(self.auto_scale)
        self.on_apply()

    def _load_prefs(self):
        """Loads animation preferences from the JSON file."""
        if os.path.exists(self.prefs_path):
            try:
                with open(self.prefs_path, 'r') as f:
                    prefs = json.load(f)
                    
                if not self.is_animating:
                    self.scale_value = prefs.get("deflection_scale", self.scale_value)
                    self.anim_speed = prefs.get("anim_speed", self.anim_speed)
                    
                self.shadow_active = prefs.get("shadow_active", self.shadow_active)
                
                saved_color = prefs.get("shadow_color")
                if saved_color and len(saved_color) == 4:
                    self.shadow_rgba = tuple(saved_color)
            except Exception as e:
                print(f"Failed to load animation prefs: {e}")
