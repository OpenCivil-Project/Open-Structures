"""Viewport navigation hints.

A small translucent chip in the corner of the 3D canvas that shows the mouse
controls (zoom / pan / rotate). It is shown for the first few launches, fades
out as soon as the user starts navigating, and can be brought back any time
with F1, the "?" toolbar button, or Help > Navigation Controls.

Edit NAV_CONTROLS below if your canvas bindings change - it is the single
source of truth for the overlay, the tooltips and the Help dialog.
"""
from PyQt6.QtCore import (Qt, QEvent, QObject, QPropertyAnimation, QEasingCurve,
                          QRectF, QSettings, QTimer)
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PyQt6.QtWidgets import QGraphicsOpacityEffect, QWidget

NAV_CONTROLS = [
    ("Scroll",              "Zoom"),
    ("Middle-drag",         "Pan"),
    ("Shift + Middle-drag", "Rotate"),
]

_SETTINGS_KEY = "ui/nav_hint_shown_count_v2"                                                           
_AUTO_SHOW_LAUNCHES = 3                                                  
_VISIBLE_MS = 9000                                        

class NavHintOverlay(QWidget):
    """Click-through hint chip pinned to the bottom-left of `parent`."""

    MARGIN = 14

    def __init__(self, parent, watch=None, extra_hint=None):
        """
        parent     : widget the chip floats over (e.g. the canvas frame)
        watch      : widget whose mouse/wheel events dismiss the chip
                     (e.g. the GL canvas). Events are observed, never consumed.
        extra_hint : optional (gesture, action) appended to the chip,
                     e.g. ("Type", "Run a command")
        """
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._items = list(NAV_CONTROLS) + ([extra_hint] if extra_hint else [])

        self._fx = QGraphicsOpacityEffect(self)
        self._fx.setOpacity(0.0)
        self.setGraphicsEffect(self._fx)
        self._anim = QPropertyAnimation(self._fx, b"opacity", self)
        self._anim.finished.connect(self._after_anim)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.fade_out)

        self._font = QFont("Segoe UI", 9)
        self._key_font = QFont("Segoe UI", 9, QFont.Weight.DemiBold)
        self.setFixedSize(self._measure())
        self.hide()

        parent.installEventFilter(self)                                             
        if watch is not None:
            watch.installEventFilter(self)                                       
        self._reposition()

    def auto_show(self):
        """Show the chip every time a model is opened (until the user navigates)."""
        QTimer.singleShot(1200, self.show_hint)

    def show_hint(self, sticky=False):
        self._reposition()
        self.show()
        self.raise_()
        self._fade(1.0, 180)
        self._timer.stop()
        if not sticky:
            self._timer.start(_VISIBLE_MS)

    def fade_out(self):
        self._timer.stop()
        if self.isVisible():
            self._fade(0.0, 450)

    def toggle(self):
        if self.isVisible() and self._fx.opacity() > 0.5:
            self.fade_out()
        else:
            self.show_hint(sticky=True)

    def _fade(self, target, ms):
        self._anim.stop()
        self._anim.setDuration(ms)
        self._anim.setStartValue(self._fx.opacity())
        self._anim.setEndValue(target)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.start()

    def _after_anim(self):
        if self._fx.opacity() <= 0.01:
            self.hide()

    def _reposition(self):
        p = self.parentWidget()
        if p:
            self.move(self.MARGIN, p.height() - self.height() - self.MARGIN)

    def eventFilter(self, obj, ev):
        t = ev.type()
        if obj is self.parentWidget() and t == QEvent.Type.Resize:
            self._reposition()
        elif t in (QEvent.Type.MouseButtonPress, QEvent.Type.Wheel) and self.isVisible():
            QTimer.singleShot(0, self.fade_out)                                       
        return False                                                        

    _PAD_X, _PAD_Y, _GAP, _KEY_PAD = 12, 8, 16, 7

    def _measure(self):
        kfm, tfm = QFontMetrics(self._key_font), QFontMetrics(self._font)
        w = self._PAD_X * 2
        for i, (g, a) in enumerate(self._items):
            w += kfm.horizontalAdvance(g) + self._KEY_PAD * 2 + 7 + tfm.horizontalAdvance(a)
            if i < len(self._items) - 1:
                w += self._GAP
        from PyQt6.QtCore import QSize
        return QSize(w, tfm.height() + self._PAD_Y * 2 + 6)

    def paintEvent(self, _):
        try:
            from app.ui.theme import COLORS
            bg, border = QColor(COLORS["bg_panel"]), QColor(COLORS["border"])
            fg, dim = QColor(COLORS["text_primary"]), QColor(COLORS["text_secondary"])
        except Exception:
            bg, border = QColor("#2b2b2b"), QColor("#4a4a4a")
            fg, dim = QColor("#e6e6e6"), QColor("#a0a0a0")
        bg.setAlpha(225)

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(border, 1))
        p.setBrush(bg)
        p.drawRoundedRect(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5), 8, 8)

        kfm, tfm = QFontMetrics(self._key_font), QFontMetrics(self._font)
        x, cy = self._PAD_X, self.height() / 2
        for g, a in self._items:
            kw = kfm.horizontalAdvance(g) + self._KEY_PAD * 2
            kh = kfm.height() + 4
            key_rect = QRectF(x, cy - kh / 2, kw, kh)
            p.setPen(QPen(border, 1))
            p.setBrush(QColor(255, 255, 255, 18))
            p.drawRoundedRect(key_rect, 4, 4)
            p.setFont(self._key_font)
            p.setPen(fg)
            p.drawText(key_rect, Qt.AlignmentFlag.AlignCenter, g)
            x += kw + 7
            p.setFont(self._font)
            p.setPen(dim)
            p.drawText(QRectF(x, 0, tfm.horizontalAdvance(a) + 2, self.height()),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, a)
            x += tfm.horizontalAdvance(a) + self._GAP
        p.end()

def navigation_help_html():
    """Rich text for the Help > Navigation Controls dialog."""
    rows = "".join(
        f"<tr><td style='padding:4px 18px 4px 0'><b>{g}</b></td><td>{a}</td></tr>"
        for g, a in NAV_CONTROLS)
    return (f"<table>{rows}</table><br>"
            "<span>Toolbar buttons: <b>ISO / 3D / XY / XZ / YZ</b> jump to a standard view, "
            "<b>Zoom +/-</b> and the <b>Pan</b> hand do the same as the mouse.<br>"
            "Start typing on the canvas to search and run any command.</span>")
