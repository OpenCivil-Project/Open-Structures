"""
mouse_crosshair.py  --  "Precision Pointer": a CAD-style crosshair for the 3D canvas.

Place this file in the ``graphic`` package (next to view_cube.py).

Everything crosshair-related lives here so it can be maintained (or removed)
without touching the canvas internals:

    CROSSHAIR_DEFAULTS / CROSSHAIR_KEYS   settings schema (stored in graphics_settings / prefs file)
    crosshair_segments()                  pure geometry (small or full-screen arms, centre gap)
    MouseCrosshair                        runtime controller owned by a canvas
    mode_flag_property()                  lets a canvas react the instant a draw mode flips
    CrosshairSettingsWidget               the "Crosshair" tab for the Graphics dialog
    save_crosshair_prefs()                persists only the crosshair keys to the prefs file

It is a pure 2D overlay: no solver or model work, just a few lines painted on
top of the canvas, so it cannot slow the analysis down.

Canvas integration (see canvas.py for the exact hooks):
    self.crosshair = MouseCrosshair(self, drawing_mode_fn=..., ink_rgb_fn=...)
    mouseMoveEvent -> self.crosshair.refresh(pos, snap_xy, nav)
    wheelEvent     -> self.crosshair.on_wheel(pos)
    leaveEvent     -> self.crosshair.on_leave()
    paintEvent     -> self.crosshair.draw(painter)
"""
import json
import math
import os

from PyQt6.QtCore import Qt, QPointF, QTimer
from PyQt6.QtGui import QColor, QPen, QPainter
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox,
                             QComboBox, QSlider, QSpinBox, QDoubleSpinBox,
                             QGroupBox, QPushButton)

CROSSHAIR_DEFAULTS = {
    "crosshair_enabled":     True,
    "crosshair_show_in":     "draw",                                                      
    "crosshair_size":        "small",                                                         
    "crosshair_arm":         20,                                                  
    "crosshair_gap":         4,                                                
    "crosshair_hide_cursor": True,
    "crosshair_color_auto":  True,                                                                 
    "crosshair_color":       (0.0, 0.47, 0.84, 1.0),
    "crosshair_opacity":     0.85,
    "crosshair_width":       1.0,
    "crosshair_style":       "Solid",                         
}
CROSSHAIR_KEYS = tuple(CROSSHAIR_DEFAULTS)

_PREFS_FILE = ".OpenStructures_prefs.json"

def save_crosshair_prefs(settings, path=None):
    """Write ONLY the crosshair keys of `settings` into the prefs file, leaving
    every other stored preference untouched. Never raises."""
    path = path or os.path.join(os.path.expanduser("~"), _PREFS_FILE)
    data = {}
    try:
        if os.path.exists(path):
            with open(path) as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                data = loaded
    except Exception:
        data = {}
    for k in CROSSHAIR_KEYS:
        if k in settings:
            data[k] = settings[k]
    try:
        with open(path, "w") as f:
            json.dump(data, f)
    except Exception:
        pass

def crosshair_segments(x, y, w, h, gap, arm=None):
    """Line segments (x1, y1, x2, y2) of a crosshair centred on (x, y) inside a
    w-by-h widget, with `gap` px left empty around the centre.

    arm=None  -> full-screen: arms run to the widget edges.
    arm=<px>  -> small: arms reach `arm` px from the centre (always at least 1 px
                 beyond the gap), clipped to the widget.
    """
    gap = max(0.0, float(gap))
    if arm is None:
        x0, x1, y0, y1 = 0.0, float(w), 0.0, float(h)
    else:
        arm = max(float(arm), gap + 1.0)
        x0, x1 = max(0.0, x - arm), min(float(w), x + arm)
        y0, y1 = max(0.0, y - arm), min(float(h), y + arm)
    segs = []
    if x - gap > x0:
        segs.append((x0, y, x - gap, y))
    if x + gap < x1:
        segs.append((x + gap, y, x1, y))
    if y - gap > y0:
        segs.append((x, y0, x, y - gap))
    if y + gap < y1:
        segs.append((x, y + gap, x, y1))
    return segs

def mode_flag_property(attr):
    """Property that behaves exactly like a plain attribute but notifies the
    canvas' crosshair when the flag changes, so the crosshair shows/hides the
    moment a draw mode is switched on/off (no mouse move needed).

    Usage inside the canvas class body:
        snapping_enabled = mode_flag_property('snapping_enabled')
    """
    priv = "_xhm_" + attr

    def _get(self):
        return getattr(self, priv, False)

    def _set(self, value):
        setattr(self, priv, value)
        xh = getattr(self, "crosshair", None)
        if xh is not None:
            xh.mode_changed()

    return property(_get, _set)

class MouseCrosshair:
    """Owns the crosshair state of one canvas: where it is, whether it is
    visible, the hidden-cursor bookkeeping and the repaint throttle.

    canvas must provide: display_config (dict), current_model, width(), height(),
    update(), setCursor(), unsetCursor(); optionally single_use_pan_active.
    """
    REPAINT_MS = 16                                                     

    def __init__(self, canvas, drawing_mode_fn, ink_rgb_fn):
        self.canvas = canvas
        self._drawing_mode = drawing_mode_fn                                              
        self._ink_rgb = ink_rgb_fn                                                 
        self.raw = None                                                                      
        self.pos = None                                                                    
        self._cursor_hidden = False
        self._dirty = False
        self._timer = QTimer(canvas)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._timer_tick)

    def cfg(self, key):
        return self.canvas.display_config.get(key, CROSSHAIR_DEFAULTS[key])

    def drawing_mode(self):
        return bool(self._drawing_mode())

    def is_active(self):
        """Should a crosshair be shown right now (ignoring the mouse position)?"""
        c = self.canvas
        if not self.cfg("crosshair_enabled"):
            return False
        if getattr(c, "current_model", None) is None:
            return False
        if getattr(c, "single_use_pan_active", False):
            return False
        if self.cfg("crosshair_show_in") != "always" and not self.drawing_mode():
            return False
        return True

    def refresh(self, raw, snap_xy=None, nav=False):
        """Recompute where (and whether) the crosshair is drawn.
        raw: mouse position (QPointF) or None when outside; snap_xy: screen
        position of the snap target or None; nav: True while orbiting/panning/box-selecting."""
        self.raw = raw
        if raw is None or nav or not self.is_active():
            new = None
        elif snap_xy is not None:
            new = (float(snap_xy[0]), float(snap_xy[1]))                                 
        else:
            new = (float(raw.x()), float(raw.y()))
        if new == self.pos:
            self._sync_cursor()
            return
        self.pos = new
        self._sync_cursor()
        if new is None:
            self.canvas.update()                                                  
        else:
            self._request_update()

    def mode_changed(self):
        """A draw-mode flag flipped."""
        self.refresh(self.raw, None)

    def apply_settings(self):
        """Settings changed (dialog Apply / menu toggle): re-evaluate and repaint."""
        self.refresh(self.raw, getattr(self.canvas, "_snap_screen_xy", None))
        self.canvas.update()

    def on_wheel(self, pos):
        """Zooming moves the scene under a stationary mouse; fall back to the raw position."""
        self.raw = pos
        if self.pos is not None:
            self.pos = (float(pos.x()), float(pos.y()))

    def on_leave(self):
        self.refresh(None)

    def _sync_cursor(self):
        """Hide the OS cursor while the crosshair is visible; restore it otherwise."""
        c = self.canvas
        if getattr(c, "single_use_pan_active", False):
            self._cursor_hidden = False                                                      
            return
        want = (self.pos is not None) and bool(self.cfg("crosshair_hide_cursor"))
        if want and not self._cursor_hidden:
            c.setCursor(Qt.CursorShape.BlankCursor)
            self._cursor_hidden = True
        elif not want and self._cursor_hidden:
            c.unsetCursor()
            self._cursor_hidden = False

    def _request_update(self):
        """Leading-edge throttle: repaint now, then at most every REPAINT_MS."""
        if self._timer.isActive():
            self._dirty = True
            return
        self.canvas.update()
        self._timer.start(self.REPAINT_MS)

    def _timer_tick(self):
        if self._dirty:
            self._dirty = False
            self.canvas.update()
            self._timer.start(self.REPAINT_MS)

    def draw(self, painter):
        """Paint the crosshair. Call from the canvas' paintEvent, last."""
        pos = self.pos
        if pos is None or not self.is_active():
            return
        w, h = self.canvas.width(), self.canvas.height()
        x, y = pos
        if x < 0 or y < 0 or x > w or y > h:
            return

        if self.cfg("crosshair_color_auto"):
            r, g, b = self._ink_rgb()
        else:
            col = self.cfg("crosshair_color")
            r, g, b = col[0], col[1], col[2]
        opacity = max(0.05, min(1.0, float(self.cfg("crosshair_opacity"))))
        width = max(0.5, float(self.cfg("crosshair_width")))
        gap = max(0, int(self.cfg("crosshair_gap")))
        arm = None if self.cfg("crosshair_size") == "full" else max(1, int(self.cfg("crosshair_arm")))

        pen = QPen(QColor.fromRgbF(float(r), float(g), float(b), opacity), width)
        pen.setCosmetic(True)
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        if str(self.cfg("crosshair_style")).lower() == "dashed":
            pen.setDashPattern([6.0, 4.0])

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)                              
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        off = 0.5 if int(round(width)) % 2 == 1 else 0.0
        px, py = math.floor(x) + off, math.floor(y) + off
        for x1, y1, x2, y2 in crosshair_segments(px, py, w, h, gap, arm):
            painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))
        painter.restore()

class CrosshairSettingsWidget(QWidget):
    """The "Crosshair" tab. Usage inside the Graphics dialog:

        self.xh_widget = CrosshairSettingsWidget(self.settings, ColorButton, self)
        self.tabs.addTab(self.xh_widget, "Crosshair")
        ...
        get_settings():  {..., **self.xh_widget.get_settings()}

    color_button_cls is the dialog's own ColorButton (constructed as cls(color_tuple, parent)),
    passed in so this module never has to import the dialog.
    """

    def __init__(self, settings, color_button_cls, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        self._sub = []                                                                             

        self.chk_enabled = QCheckBox("Enable Precision Pointer (CAD-style crosshair)")
        self.chk_enabled.toggled.connect(self._refresh_enabled)
        v.addWidget(self.chk_enabled)

        row = QHBoxLayout()
        lbl = QLabel("Show in:")
        self.combo_show = QComboBox()
        self.combo_show.addItems(["Drawing / snapping modes only", "Always"])
        row.addWidget(lbl)
        row.addWidget(self.combo_show)
        v.addLayout(row)
        self._sub += [lbl, self.combo_show]

        row = QHBoxLayout()
        lbl = QLabel("Size:")
        self.combo_size = QComboBox()
        self.combo_size.addItems(["Small (fixed length)", "Full screen"])
        self.combo_size.currentIndexChanged.connect(self._refresh_enabled)
        row.addWidget(lbl)
        row.addWidget(self.combo_size)
        v.addLayout(row)
        self._sub += [lbl, self.combo_size]

        row = QHBoxLayout()
        self.lbl_arm = QLabel("Arm length (from center):")
        self.spin_arm = QSpinBox()
        self.spin_arm.setRange(5, 300)
        self.spin_arm.setSuffix(" px")
        row.addWidget(self.lbl_arm)
        row.addWidget(self.spin_arm)
        row.addStretch()
        v.addLayout(row)

        self.chk_hide_cursor = QCheckBox("Hide system cursor while the crosshair is visible")
        v.addWidget(self.chk_hide_cursor)
        self._sub.append(self.chk_hide_cursor)

        g = QGroupBox("Appearance")
        gv = QVBoxLayout(g)

        row = QHBoxLayout()
        self.chk_auto = QCheckBox("Automatic color (follows theme)")
        self.chk_auto.toggled.connect(self._refresh_enabled)
        self.btn_col = color_button_cls(tuple(CROSSHAIR_DEFAULTS["crosshair_color"]), self)
        row.addWidget(self.chk_auto)
        row.addStretch()
        row.addWidget(self.btn_col)
        gv.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel("Opacity:"))
        self.sl_opacity = QSlider(Qt.Orientation.Horizontal)
        self.sl_opacity.setRange(10, 100)
        row.addWidget(self.sl_opacity)
        gv.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel("Line width:"))
        self.spin_width = QDoubleSpinBox()
        self.spin_width.setRange(0.5, 3.0)
        self.spin_width.setSingleStep(0.5)
        row.addWidget(self.spin_width)
        row.addSpacing(12)
        row.addWidget(QLabel("Style:"))
        self.combo_style = QComboBox()
        self.combo_style.addItems(["Solid", "Dashed"])
        row.addWidget(self.combo_style)
        row.addStretch()
        gv.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel("Center gap:"))
        self.spin_gap = QSpinBox()
        self.spin_gap.setRange(0, 40)
        self.spin_gap.setSuffix(" px")
        row.addWidget(self.spin_gap)
        row.addStretch()
        gv.addLayout(row)

        v.addWidget(g)
        self._sub.append(g)

        btn_reset = QPushButton("Reset Crosshair Defaults")
        btn_reset.setObjectName("secondary")
        btn_reset.clicked.connect(self.reset_defaults)
        v.addWidget(btn_reset)
        v.addStretch()

        self.set_values(settings)

    def set_values(self, settings):
        d = CROSSHAIR_DEFAULTS
        g = lambda k: settings.get(k, d[k])
        self.chk_enabled.setChecked(bool(g("crosshair_enabled")))
        self.combo_show.setCurrentIndex(1 if g("crosshair_show_in") == "always" else 0)
        self.combo_size.setCurrentIndex(1 if g("crosshair_size") == "full" else 0)
        self.spin_arm.setValue(int(g("crosshair_arm")))
        self.chk_hide_cursor.setChecked(bool(g("crosshair_hide_cursor")))
        self.chk_auto.setChecked(bool(g("crosshair_color_auto")))
        self.btn_col.color = self.btn_col._tuple_to_qcolor(tuple(g("crosshair_color")))
        self.btn_col._update_style()
        self.sl_opacity.setValue(int(round(float(g("crosshair_opacity")) * 100)))
        self.spin_width.setValue(float(g("crosshair_width")))
        self.combo_style.setCurrentText(str(g("crosshair_style")).title())
        self.spin_gap.setValue(int(g("crosshair_gap")))
        self._refresh_enabled()

    def reset_defaults(self):
        self.set_values(CROSSHAIR_DEFAULTS)

    def get_settings(self):
        return {
            "crosshair_enabled":     self.chk_enabled.isChecked(),
            "crosshair_show_in":     "always" if self.combo_show.currentIndex() == 1 else "draw",
            "crosshair_size":        "full" if self.combo_size.currentIndex() == 1 else "small",
            "crosshair_arm":         int(self.spin_arm.value()),
            "crosshair_gap":         int(self.spin_gap.value()),
            "crosshair_hide_cursor": self.chk_hide_cursor.isChecked(),
            "crosshair_color_auto":  self.chk_auto.isChecked(),
            "crosshair_color":       self.btn_col.get_color_tuple(),
            "crosshair_opacity":     self.sl_opacity.value() / 100.0,
            "crosshair_width":       float(self.spin_width.value()),
            "crosshair_style":       self.combo_style.currentText(),
        }

    def _refresh_enabled(self, *_args):
                                                                  
        on = self.chk_enabled.isChecked()
        for w in self._sub:
            w.setEnabled(on)
        small = self.combo_size.currentIndex() == 0
        self.lbl_arm.setEnabled(on and small)
        self.spin_arm.setEnabled(on and small)
        self.btn_col.setEnabled(on and not self.chk_auto.isChecked())
