"""
OpenCivil window blur
=====================
Real "frosted glass" (blur-behind) for dialogs, drop-down menus and the
command palette. Windows only - on any other OS every function here is a
harmless no-op and `blur_supported()` returns False, so theme.py falls back to
normal solid backgrounds.

  * Windows 11 (22H2+, build 22621+): system acrylic backdrop + rounded corners
  * Windows 10 / early Windows 11   : classic blur-behind (corners stay square)

Usage
-----
You normally do nothing: theme.set_theme() calls `install(app)`, which watches
for every QDialog / QMenu and blurs it automatically.

    from app.ui.blur import enable_blur, set_blur_enabled
    enable_blur(some_frameless_widget)     # manual, for custom popups
    set_blur_enabled(False)                # kill switch (call before set_theme)
"""

import sys

from PyQt6.QtCore import QObject, QEvent, Qt, QRectF
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QRegion
from PyQt6.QtWidgets import QApplication, QDialog, QMenu, QWidget

IS_WINDOWS = sys.platform == "win32"
_ENABLED = True
_manager = None

CORNER_RADIUS = 8

try:
    WIN_BUILD = sys.getwindowsversion().build if IS_WINDOWS else 0
except Exception:
    WIN_BUILD = 0

_DWMWA_WINDOW_CORNER_PREFERENCE = 33
_DWMWA_SYSTEMBACKDROP_TYPE = 38
_DWMWA_USE_IMMERSIVE_DARK_MODE = 20
_DWMSBT_TRANSIENTWINDOW = 3                   
_DWMWCP_DONOTROUND, _DWMWCP_ROUND = 1, 2
_WCA_ACCENT_POLICY = 19
_ACCENT_ENABLE_BLURBEHIND = 3

if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    class _MARGINS(ctypes.Structure):
        _fields_ = [("l", ctypes.c_int), ("r", ctypes.c_int),
                    ("t", ctypes.c_int), ("b", ctypes.c_int)]

    class _ACCENT_POLICY(ctypes.Structure):
        _fields_ = [("AccentState", ctypes.c_int), ("AccentFlags", ctypes.c_int),
                    ("GradientColor", ctypes.c_uint), ("AnimationId", ctypes.c_int)]

    class _WINCOMPATTRDATA(ctypes.Structure):
        _fields_ = [("Attribute", ctypes.c_int), ("Data", ctypes.c_void_p),
                    ("SizeOfData", ctypes.c_size_t)]

def set_blur_enabled(flag: bool) -> None:
    global _ENABLED
    _ENABLED = bool(flag)

def blur_supported() -> bool:
    """True when this OS can blur behind a window (Windows 10 1803+)."""
    return IS_WINDOWS and _ENABLED and WIN_BUILD >= 17134

def _dwm_set(hwnd, attr, value):
    v = ctypes.c_int(value)
    ctypes.windll.dwmapi.DwmSetWindowAttribute(
        wintypes.HWND(hwnd), ctypes.c_uint(attr), ctypes.byref(v), ctypes.sizeof(v))

def _accent_blur(hwnd):
    policy = _ACCENT_POLICY(_ACCENT_ENABLE_BLURBEHIND, 0, 0, 0)
    data = _WINCOMPATTRDATA(_WCA_ACCENT_POLICY,
                            ctypes.cast(ctypes.pointer(policy), ctypes.c_void_p),
                            ctypes.sizeof(policy))
    ctypes.windll.user32.SetWindowCompositionAttribute(
        wintypes.HWND(hwnd), ctypes.byref(data))

def _is_dark() -> bool:
    try:
        from app.ui.theme import current_theme
        return current_theme() == "Dark"
    except Exception:
        return True

def enable_blur(widget, dark=None, rounded=True) -> bool:
    """
    Blur whatever is behind `widget` (must be a shown top-level window with
    WA_TranslucentBackground set, and a semi-transparent painted background -
    otherwise there is nothing to see through).  Returns True if applied.
    """
    if not blur_supported():
        return False
    try:
        hwnd = int(widget.winId())
        if dark is None:
            dark = _is_dark()
        _dwm_set(hwnd, _DWMWA_USE_IMMERSIVE_DARK_MODE, 1 if dark else 0)

        if WIN_BUILD >= 22621:
                                                              
            _dwm_set(hwnd, _DWMWA_WINDOW_CORNER_PREFERENCE,
                     _DWMWCP_ROUND if rounded else _DWMWCP_DONOTROUND)
            m = _MARGINS(-1, -1, -1, -1)
            ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(
                wintypes.HWND(hwnd), ctypes.byref(m))
            _dwm_set(hwnd, _DWMWA_SYSTEMBACKDROP_TYPE, _DWMSBT_TRANSIENTWINDOW)
        else:
            if WIN_BUILD >= 22000:
                _dwm_set(hwnd, _DWMWA_WINDOW_CORNER_PREFERENCE,
                         _DWMWCP_ROUND if rounded else _DWMWCP_DONOTROUND)
            _accent_blur(hwnd)
        return True
    except Exception:
        return False

def _round_mask(widget, radius=CORNER_RADIUS) -> None:
    """Windows 10 has no DWM rounded corners, so clip frameless popups with a
    rounded window region instead (edges are not anti-aliased, but it works)."""
    try:
        path = QPainterPath()
        path.addRoundedRect(QRectF(widget.rect()), radius, radius)
        widget.setMask(QRegion(path.toFillPolygon().toPolygon()))
    except Exception:
        pass

def _is_managed(obj) -> bool:
    return isinstance(obj, QWidget) and obj.isWindow() and bool(obj.property("_blur_ready"))

def _is_frameless_popup(obj) -> bool:
    return isinstance(obj, QMenu) or bool(obj.property("blur_popup"))

def _glass_fill(dialog) -> None:
    """Overwrite (not blend over) the dirty area with the dialog's glass colour.

    On a translucent window the normal background is painted with alpha *on top of*
    whatever was there, so text that changes while the dialog is open (progress
    labels, hover states) piles up as ghosts. Painting with CompositionMode_Source
    replaces the old pixels, so every repaint starts clean. Runs just before the
    dialog's children are painted."""
    from app.ui.theme import COLORS, glass_alpha
    color = QColor(COLORS["bg_dialog"])
    color.setAlpha(glass_alpha("dialog"))
    p = QPainter(dialog)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
    p.fillRect(dialog.rect(), color)
    p.end()

class _BlurManager(QObject):
    """App-wide event filter: prepares and blurs every QDialog and QMenu, plus any
    custom popup that sets  widget.setProperty("_blur_ready", True)  and
    widget.setProperty("blur_popup", True)  (e.g. the command palette)."""

    def eventFilter(self, obj, event):
        try:
            t = event.type()
            if t == QEvent.Type.Polish:
                                                                              
                if isinstance(obj, (QDialog, QMenu)) and obj.isWindow()\
                        and not obj.property("_blur_ready"):
                    obj.setProperty("_blur_ready", True)
                    obj.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
                    obj.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
                    if isinstance(obj, QMenu):
                        obj.setWindowFlag(Qt.WindowType.NoDropShadowWindowHint, True)
                    elif not obj.styleSheet():
                                                                                      
                        from app.ui.theme import apply_dialog_style
                        apply_dialog_style(obj)
            elif t == QEvent.Type.Show:
                if _is_managed(obj):
                    enable_blur(obj, rounded=True)
                    if WIN_BUILD < 22000 and _is_frameless_popup(obj):
                        _round_mask(obj)
            elif t == QEvent.Type.Paint:
                if isinstance(obj, QDialog) and _is_managed(obj):
                    _glass_fill(obj)
            elif t == QEvent.Type.Resize:
                if WIN_BUILD < 22000 and _is_managed(obj) and obj.isVisible()\
                        and _is_frameless_popup(obj):
                    _round_mask(obj)
        except Exception:
            pass
        return False

def install(app) -> None:
    """Idempotent. Called by theme.set_theme()."""
    global _manager
    if not blur_supported() or _manager is not None:
        return
    _manager = _BlurManager(app)
    app.installEventFilter(_manager)

def refresh() -> None:
    """Re-apply blur (dark/light title bar + backdrop tint) to every blurred
    window that is currently open. Called by theme.set_theme()."""
    if not blur_supported():
        return
    for w in QApplication.topLevelWidgets():
        if w.isVisible() and w.property("_blur_ready"):
            enable_blur(w, rounded=True)
