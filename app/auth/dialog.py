"""
auth/dialog.py
--------------
Login dialog for Open//Structures.
Compact layout, light + dark themes (follows the system by default, toggle
button in the header, choice is remembered). All backend logic preserved.
"""

import os
import random
from PyQt6.QtCore import (Qt, QTimer, QRect, QSize, QSettings, QPointF,
                          QPropertyAnimation, QEasingCurve)
from PyQt6.QtGui import (
    QFont, QColor, QPainter, QPen, QPixmap, QIcon, QPalette,
    QPainterPath, QPolygonF
)
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QCheckBox, QFrame,
    QWidget, QApplication, QScrollArea, QSizePolicy,
    QStyle, QStyleOptionButton
)

from .thread import GoogleAuthThread, AuthOperationThread, _CANCELLED
from . import email_auth
from .config import FirebaseAuthConfig

LIGHT = dict(
    name="light",
    BG="#F5F4F0", BORDER_STRONG="#C9C7C0",
    TEXT_PRIMARY="#111110", TEXT_SECONDARY="#6B6A65", TEXT_HINT="#A8A7A2",
    ACCENT="#0F62FE", ACCENT_HOVER="#0043CE", ACCENT_PRESSED="#002D9C",
    ACCENT_TEXT="#FFFFFF",
    INPUT_BG="#FFFFFF", INPUT_BORDER="#DEDCD7",
    DIVIDER="#E4E3DE",
    GOOGLE_BG="#FFFFFF", GOOGLE_BORDER="#DDDBD6", GOOGLE_HOVER="#F0EFEB",
    GOOGLE_PRESSED="#E8E7E3",
    DISABLED_BG="#E4E3DE",
    HOVER_TINT="rgba(0,0,0,0.04)", PRESS_TINT="rgba(0,0,0,0.07)",
    ERROR="#DC2626", SUCCESS="#16A34A",
    NOISE=(30, 28, 20),
)

DARK = dict(
    name="dark",
    BG="#16161A", BORDER_STRONG="#4A4A55",
    TEXT_PRIMARY="#F2F2F0", TEXT_SECONDARY="#A1A1AA", TEXT_HINT="#6B6B73",
    ACCENT="#3B7BFF", ACCENT_HOVER="#5C93FF", ACCENT_PRESSED="#2563EB",
    ACCENT_TEXT="#FFFFFF",
    INPUT_BG="#1F1F25", INPUT_BORDER="#33333B",
    DIVIDER="#2E2E36",
    GOOGLE_BG="#1F1F25", GOOGLE_BORDER="#33333B", GOOGLE_HOVER="#2A2A32",
    GOOGLE_PRESSED="#32323B",
    DISABLED_BG="#2A2A32",
    HOVER_TINT="rgba(255,255,255,0.06)", PRESS_TINT="rgba(255,255,255,0.10)",
    ERROR="#F87171", SUCCESS="#4ADE80",
    NOISE=(255, 255, 255),
)

class _Theme:
    """Mutable palette so every widget reads the current colours at call time."""
    def __init__(self, palette):
        self.set(palette)

    def set(self, palette):
        for key, value in palette.items():
            setattr(self, key, value)

    @property
    def is_dark(self):
        return self.name == "dark"

T = _Theme(LIGHT)

_SETTINGS_ORG = "OpenStructures"
_SETTINGS_APP = "Auth"

def _system_prefers_dark() -> bool:
    try:
        scheme = QApplication.styleHints().colorScheme()
        return scheme == Qt.ColorScheme.Dark
    except Exception:
        return False

def _load_theme() -> dict:
    try:
        saved = QSettings(_SETTINGS_ORG, _SETTINGS_APP).value("theme", "", type=str)
    except Exception:
        saved = ""
    if saved == "dark":
        return DARK
    if saved == "light":
        return LIGHT
    return DARK if _system_prefers_dark() else LIGHT

def _save_theme(name: str):
    try:
        QSettings(_SETTINGS_ORG, _SETTINGS_APP).setValue("theme", name)
    except Exception:
        pass

def _make_noise_pixmap(width: int, height: int, density: float = 0.04) -> QPixmap:
    """Subtle grain overlay — drawn once per theme, reused on repaint."""
    rng = random.Random(0xC17117)
    pm = QPixmap(width, height)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    r, g, b = T.NOISE
                                                               
    lo, hi = (3, 8) if T.is_dark else (4, 14)
    for _ in range(int(width * height * density)):
        p.setPen(QColor(r, g, b, rng.randint(lo, hi)))
        p.drawPoint(rng.randint(0, width - 1), rng.randint(0, height - 1))
    p.end()
    return pm

class ThemeToggle(QPushButton):
    """Round sun/moon button — icon is vector-painted so it is crisp and
    perfectly centred on any font / DPI (no emoji glyph metrics involved)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(34, 34)
                                                                          
        self.setStyleSheet(
            "QPushButton { min-width: 34px; max-width: 34px; min-height: 34px;"
            " max-height: 34px; padding: 0; margin: 0; border: none;"
            " background: transparent; }")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setToolTip("Switch light / dark theme")
        self._hover = False

    def enterEvent(self, e):
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self.update()
        super().leaveEvent(e)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        c = QPointF(w / 2, h / 2)

        col = QColor(T.TEXT_PRIMARY if self._hover else T.TEXT_SECONDARY)
        if T.is_dark:
                                                   
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            p.drawEllipse(c, 3.8, 3.8)
            pen = QPen(col, 1.6)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            import math
            for i in range(8):
                ang = math.radians(i * 45)
                dx, dy = math.cos(ang), math.sin(ang)
                p.drawLine(QPointF(c.x() + dx * 6.6, c.y() + dy * 6.6),
                           QPointF(c.x() + dx * 8.4, c.y() + dy * 8.4))
        else:
                                                            
            moon = QPainterPath()
            moon.addEllipse(c, 7.6, 7.6)
            bite = QPainterPath()
            bite.addEllipse(QPointF(c.x() + 4.2, c.y() - 3.6), 6.4, 6.4)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            p.drawPath(moon.subtracted(bite))
        p.end()

class TickCheckBox(QCheckBox):
    """Checkbox that draws a crisp white tick inside the (QSS-styled) box."""

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.isChecked():
            return
        opt = QStyleOptionButton()
        self.initStyleOption(opt)
        r = self.style().subElementRect(QStyle.SubElement.SE_CheckBoxIndicator, opt, self)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor("#FFFFFF"), 1.8)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        x, y, w, h = r.x(), r.y(), r.width(), r.height()
        p.drawPolyline(QPolygonF([
            QPointF(x + w * 0.26, y + h * 0.53),
            QPointF(x + w * 0.43, y + h * 0.70),
            QPointF(x + w * 0.75, y + h * 0.32),
        ]))
        p.end()

class EyeButton(QPushButton):
    """Show/hide-password icon, vector-drawn (eye, slashed when revealed)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(28, 28)
        self.setStyleSheet(
            "QPushButton { min-width: 28px; max-width: 28px; min-height: 28px;"
            " max-height: 28px; padding: 0; margin: 0; border: none;"
            " background: transparent; }")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setToolTip("Show password")
        self.revealed = False
        self._hover = False

    def set_revealed(self, revealed: bool):
        self.revealed = revealed
        self.setToolTip("Hide password" if revealed else "Show password")
        self.update()

    def enterEvent(self, e):
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self.update()
        super().leaveEvent(e)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QPointF(self.width() / 2, self.height() / 2)
        col = QColor(T.TEXT_PRIMARY if self._hover else T.TEXT_SECONDARY)
        pen = QPen(col, 1.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        eye = QPainterPath(QPointF(c.x() - 8, c.y()))
        eye.quadTo(QPointF(c.x(), c.y() - 9), QPointF(c.x() + 8, c.y()))
        eye.quadTo(QPointF(c.x(), c.y() + 9), QPointF(c.x() - 8, c.y()))
        p.drawPath(eye)
        p.setBrush(col)
        p.drawEllipse(c, 2.3, 2.3)
        if self.revealed:
            p.setPen(pen)
            p.drawLine(QPointF(c.x() - 7, c.y() + 7), QPointF(c.x() + 7, c.y() - 7))
        p.end()

class StyledInput(QLineEdit):
    def __init__(self, placeholder="", password=False, parent=None):
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        if password:
            self.setEchoMode(QLineEdit.EchoMode.Password)
        self.setFixedHeight(40)
        self.setFont(QFont("Segoe UI", 10))
        self._focused = False
        self._eye = None
        if password:
            self._eye = EyeButton(self)
            self._eye.clicked.connect(self._toggle_reveal)
        self.apply_theme()

    def _toggle_reveal(self):
        show = self.echoMode() == QLineEdit.EchoMode.Password
        self.setEchoMode(QLineEdit.EchoMode.Normal if show
                         else QLineEdit.EchoMode.Password)
        self._eye.set_revealed(show)
        self.setFocus()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._eye:
            self._eye.move(self.width() - self._eye.width() - 6,
                           (self.height() - self._eye.height()) // 2)

    def apply_theme(self):
        border = T.ACCENT if self._focused else T.INPUT_BORDER
        bw = "1.5px" if self._focused else "1px"
        self.setStyleSheet(f"""
            QLineEdit {{
                background: {T.INPUT_BG};
                border: {bw} solid {border};
                border-radius: 8px;
                padding: {'0 38px 0 12px' if self._eye else '0 12px'};
                color: {T.TEXT_PRIMARY};
                font-size: 13px;
                selection-background-color: {T.ACCENT};
                selection-color: #FFFFFF;
            }}
            QLineEdit:hover {{ border-color: {border if self._focused else T.BORDER_STRONG}; }}
        """)
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.PlaceholderText, QColor(T.TEXT_HINT))
        self.setPalette(pal)
        if self._eye:
            self._eye.update()

    def focusInEvent(self, e):
        self._focused = True
        self.apply_theme()
        super().focusInEvent(e)

    def focusOutEvent(self, e):
        self._focused = False
        self.apply_theme()
        super().focusOutEvent(e)

def _paint_google_g(painter: QPainter, cx: int, cy: int, r: int = 10):
    """Paint a four-colour Google G centred at (cx, cy). Fallback when no logo file."""
    painter.setPen(Qt.PenStyle.NoPen)
    rect = (cx - r, cy - r, r * 2, r * 2)

    painter.setBrush(QColor("#4285F4"))
    painter.drawPie(*rect, -35 * 16, 125 * 16)
    painter.setBrush(QColor("#EA4335"))
    painter.drawPie(*rect, 90 * 16, 120 * 16)
    painter.setBrush(QColor("#FBBC05"))
    painter.drawPie(*rect, 210 * 16, 60 * 16)
    painter.setBrush(QColor("#34A853"))
    painter.drawPie(*rect, 270 * 16, 55 * 16)

    inner = int(r * 0.54)
    painter.setBrush(QColor(T.GOOGLE_BG))
    painter.drawEllipse(cx - inner, cy - inner, inner * 2, inner * 2)

    bar_h = int(r * 0.38)
    bar_w = r - inner + 2
    painter.setBrush(QColor("#4285F4"))
    painter.drawRect(cx, cy - bar_h // 2, bar_w, bar_h)

    painter.setBrush(QColor(T.GOOGLE_BG))
    painter.drawRect(cx - 1, cy - r - 1, r + 2, int(r * 0.48))

class GoogleButton(QPushButton):
    """Full-width Google sign-in button (uses Glogo.png, falls back to a painted G)."""

    def __init__(self, logo_path: str = None, parent=None):
        super().__init__("Continue with Google", parent)
        self.setFixedHeight(40)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFont(QFont("Segoe UI Semibold", 10))
        self._logo_path = logo_path
        self._use_pixmap = False
        self._waiting = False

        if logo_path and os.path.exists(logo_path):
            self.setIcon(QIcon(logo_path))
            self.setIconSize(QSize(20, 20))
            self._use_pixmap = True

        self.apply_theme()

    def apply_theme(self):
        text_color = T.TEXT_SECONDARY if self._waiting else T.TEXT_PRIMARY
        hover_text = f"color: {T.ERROR};" if self._waiting else ""
        self.setStyleSheet(f"""
            QPushButton {{
                background: {T.GOOGLE_BG};
                border: 1px solid {T.GOOGLE_BORDER};
                border-radius: 8px;
                color: {text_color};
                font-size: 13px;
                font-weight: 600;
                padding-left: 8px;
                text-align: center;
            }}
            QPushButton:hover   {{ background: {T.GOOGLE_HOVER}; border-color: {T.BORDER_STRONG}; {hover_text} }}
            QPushButton:pressed {{ background: {T.GOOGLE_PRESSED}; }}
            QPushButton:disabled {{ color: {T.TEXT_HINT}; }}
        """)

    def set_waiting(self, waiting: bool):
        self._waiting = waiting
        self.setText("Cancel Google Sign-In" if waiting else "Continue with Google")
        self.apply_theme()
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._use_pixmap and not self._waiting:
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            _paint_google_g(p, 28, self.height() // 2, r=9)
            p.end()

class DividerLabel(QWidget):
    def __init__(self, text="or", parent=None):
        super().__init__(parent)
        self._text = text
        self.setFixedHeight(16)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        mid = h // 2

        p.setFont(QFont("Segoe UI", 8))
        tw = p.fontMetrics().horizontalAdvance(f"  {self._text}  ")
        lx = (w - tw) // 2

        pen = QPen(QColor(T.DIVIDER))
        pen.setWidth(1)
        p.setPen(pen)
        p.drawLine(0, mid, lx, mid)
        p.drawLine(lx + tw, mid, w, mid)

        p.setPen(QColor(T.TEXT_HINT))
        p.drawText(QRect(lx, 0, tw, h), Qt.AlignmentFlag.AlignCenter, self._text)
        p.end()

def _field_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setFont(QFont("Segoe UI Semibold", 8))
    return lbl

def _field(label: QLabel, edit: QWidget) -> QWidget:
    """Label + input in one container so hiding it removes the spacing too."""
    box = QWidget()
    lay = QVBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(4)
    lay.addWidget(label)
    lay.addWidget(edit)
    return box

def _dialog_qss() -> str:
    """Shared stylesheet for the two small secondary dialogs."""
    return f"""
        QDialog {{ background: {T.BG}; }}
        QLabel  {{ color: {T.TEXT_PRIMARY}; }}
        QPushButton {{
            background: transparent;
            border: 1px solid {T.INPUT_BORDER};
            border-radius: 6px;
            color: {T.TEXT_PRIMARY};
            padding: 6px 12px;
        }}
        QPushButton:hover    {{ background: {T.HOVER_TINT}; border-color: {T.BORDER_STRONG}; }}
        QPushButton:disabled {{ color: {T.TEXT_HINT}; }}
        QPushButton#primary {{
            background: {T.ACCENT}; border: none; color: {T.ACCENT_TEXT}; font-weight: 600;
        }}
        QPushButton#primary:hover    {{ background: {T.ACCENT_HOVER}; }}
        QPushButton#primary:disabled {{ background: {T.DISABLED_BG}; color: {T.TEXT_HINT}; }}
    """

class LoginDialog(QDialog):
    """Open//Structures login dialog — compact, themeable, all auth logic preserved."""

    WIDTH = 420

    def __init__(self, parent=None):
        super().__init__(parent)
        self.user_info = None
        self.remember_me = False
        self._auth_thread = None
        self._account_thread = None
        self._closing = False
        self._mode = "login"

        T.set(_load_theme())

        self.setWindowTitle("Open//Structures")
        self.setFixedWidth(self.WIDTH)

        icon_path = self._find_asset_static("logo.png") or self._find_asset_static("logo.ico")
        if icon_path:
            self.setWindowIcon(QIcon(icon_path))

        self.setWindowFlags(
            Qt.WindowType.Dialog |
            Qt.WindowType.WindowCloseButtonHint |
            Qt.WindowType.MSWindowsFixedSizeDialogHint
        )
        self.setModal(True)

        self._noise = _make_noise_pixmap(self.WIDTH, 1100)
        self._build_ui()
        self._apply_theme()
        self._fit()
        if not FirebaseAuthConfig.validate():
            self._set_status("Account sign-in is currently unavailable. Continue as Guest.")

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(T.BG))
        p.drawPixmap(0, 0, self._noise)
        p.end()

    def _fit(self):
        """Size the dialog to its content (capped to the screen; scrolls if needed)."""
        lay = self._form_layout
        lay.activate()
        h = lay.sizeHint().height()
        if lay.hasHeightForWidth():
            h = max(h, lay.totalHeightForWidth(self.WIDTH))
        screen = self.screen() or QApplication.primaryScreen()
        available = screen.availableGeometry().height() - 60 if screen else 900
        needs_scroll = h > max(420, available)
        self.setFixedHeight(min(h, max(420, available)))
                                                                                    
        self._scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded if needs_scroll
            else Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sb = self._scroll.verticalScrollBar().sizeHint().width() if needs_scroll else 0
        self._form.setFixedWidth(self.WIDTH - sb)
        self._scroll.verticalScrollBar().setValue(0)
        self._place_theme()
        self.update()

    def _place_theme(self):
        """Pin the theme toggle to the form's top-right, vertically centred on the logo."""
        b = self.btn_theme
        b.move(self._form.width() - 32 - b.width() + 6, 28 + (48 - b.height()) // 2)
        b.raise_()

    def showEvent(self, event):
        super().showEvent(event)
        self._place_theme()
        if not getattr(self, "_faded", False):
            self._faded = True
            self.setWindowOpacity(0.0)
            self._fade = QPropertyAnimation(self, b"windowOpacity", self)
            self._fade.setDuration(180)
            self._fade.setStartValue(0.0)
            self._fade.setEndValue(1.0)
            self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
            self._fade.start()

    def _fit_later(self):
        QTimer.singleShot(0, self._fit)

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet("QScrollArea { background: transparent; }")
        self._scroll.viewport().setAutoFillBackground(False)
        self._form = QWidget()
        self._form.setObjectName("authForm")
        self._form.setStyleSheet("QWidget#authForm { background: transparent; }")
        self._scroll.setWidget(self._form)
        outer.addWidget(self._scroll)

        root = QVBoxLayout(self._form)
        self._form_layout = root
        root.setContentsMargins(32, 28, 32, 24)
        root.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(10)

        logo_lbl = QLabel()
        logo_lbl.setFixedSize(48, 48)
        logo_path = self._find_asset("logo.png") or self._find_asset("logo.ico")
        if logo_path:
            px = QPixmap(logo_path).scaled(
                48, 48,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            logo_lbl.setPixmap(px)
        else:
            logo_lbl.setText("O/S")
            self._logo_fallback = logo_lbl
        self.logo_lbl = logo_lbl

        self.app_name = QLabel()
        self.app_name.setTextFormat(Qt.TextFormat.RichText)
        name_font = QFont("Segoe UI")
        name_font.setPixelSize(27)
        name_font.setWeight(QFont.Weight.Bold)
        self.app_name.setFont(name_font)
        self._name_font = name_font
                                                                               
        self.app_name.setStyleSheet(
            "font-family: 'Segoe UI'; font-size: 27px; font-weight: 700;")

        self.btn_theme = ThemeToggle(self._form)
        self.btn_theme.clicked.connect(self._toggle_theme)

        header.addWidget(logo_lbl)
        self.app_name.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Preferred)
        header.addWidget(self.app_name)
        header.addStretch()
        root.addLayout(header)
        root.addSpacing(8)

        heading_box = QVBoxLayout()
        heading_box.setSpacing(2)
        self.lbl_heading = QLabel("Welcome back.")
        self.lbl_heading.setFont(QFont("Segoe UI Semibold", 17))
        self.tagline = QLabel("Sign in to your account")
        self.tagline.setFont(QFont("Segoe UI", 10))
        heading_box.addWidget(self.lbl_heading)
        heading_box.addWidget(self.tagline)
        root.addLayout(heading_box)
        root.addSpacing(4)

        self.lbl_email = _field_label("Email")
        self.input_email = StyledInput("you@example.com")
        root.addWidget(_field(self.lbl_email, self.input_email))

        self.name_lbl = _field_label("Full Name")
        self.input_name = StyledInput("Your full name")
        self.name_field = _field(self.name_lbl, self.input_name)
        self.name_field.setVisible(False)
        root.addWidget(self.name_field)

        self.lbl_password = _field_label("Password")
        self.input_password = StyledInput("••••••••", password=True)
        root.addWidget(_field(self.lbl_password, self.input_password))

        self.confirm_lbl = _field_label("Confirm Password")
        self.input_confirm = StyledInput("••••••••", password=True)
        self.confirm_field = _field(self.confirm_lbl, self.input_confirm)
        self.confirm_field.setVisible(False)
        root.addWidget(self.confirm_field)

        row_rf = QHBoxLayout()
        self.chk_remember = TickCheckBox("Remember me")
        self.chk_remember.setFont(QFont("Segoe UI", 9))
        row_rf.addWidget(self.chk_remember)
        row_rf.addStretch()

        self.lbl_forgot = QLabel()
        self.lbl_forgot.setFont(QFont("Segoe UI", 9))
        self.lbl_forgot.setOpenExternalLinks(False)
        self.lbl_forgot.linkActivated.connect(lambda _: self._on_forgot_password())
        row_rf.addWidget(self.lbl_forgot)
        root.addLayout(row_rf)

        self.btn_primary = QPushButton("Sign In")
        self.btn_primary.setFixedHeight(40)
        self.btn_primary.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_primary.setFont(QFont("Segoe UI Semibold", 10))
        self.btn_primary.clicked.connect(self._on_primary)
        root.addWidget(self.btn_primary)

        self.lbl_status = QLabel("")
        self.lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_status.setFont(QFont("Segoe UI", 8))
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setTextFormat(Qt.TextFormat.PlainText)
        self.lbl_status.setVisible(False)
        root.addWidget(self.lbl_status)

        root.addWidget(DividerLabel("or"))

        glogo_path = self._find_asset("Glogo.png")
        self.btn_google = GoogleButton(logo_path=glogo_path)
        self.btn_google.clicked.connect(self._on_google_login)
        root.addWidget(self.btn_google)

        self.btn_guest = QPushButton("Continue as Guest")
        self.btn_guest.setFixedHeight(40)
        self.btn_guest.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_guest.setFont(QFont("Segoe UI", 10))
        self.btn_guest.clicked.connect(self._on_guest_login)
        root.addWidget(self.btn_guest)

        root.addSpacing(2)
        toggle_row = QHBoxLayout()
        toggle_row.setSpacing(4)
        toggle_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_toggle_hint = QLabel("Don't have an account?")
        self.lbl_toggle_hint.setFont(QFont("Segoe UI", 9))
        toggle_row.addWidget(self.lbl_toggle_hint)

        self.btn_toggle = QPushButton("Create one")
        self.btn_toggle.setFlat(True)
        self.btn_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_toggle.setFont(QFont("Segoe UI Semibold", 9))
        self.btn_toggle.clicked.connect(self._toggle_mode)
        toggle_row.addWidget(self.btn_toggle)
        root.addLayout(toggle_row)

    def _apply_theme(self):
        self.app_name.setText(
            f'<span style="color:{T.TEXT_PRIMARY};">Open</span>'
            f'<span style="color:#0364B3;">//Structures</span>'
        )
                                                                       
        from PyQt6.QtGui import QFontMetrics
        _w = QFontMetrics(self._name_font).horizontalAdvance("Open//Structures")
        self.app_name.setMinimumWidth(_w + 8)
        self.app_name.updateGeometry()

        if hasattr(self, "_logo_fallback"):
            self._logo_fallback.setStyleSheet(
                f"color: {T.ACCENT}; font-size: 18px; font-weight: bold;")

        self.btn_theme.setToolTip("Switch to light theme" if T.is_dark else "Switch to dark theme")
        self.btn_theme.update()

        self.lbl_heading.setStyleSheet(f"color: {T.TEXT_PRIMARY};")
        self.tagline.setStyleSheet(f"color: {T.TEXT_SECONDARY};")
        for lbl in (self.lbl_email, self.name_lbl, self.lbl_password, self.confirm_lbl):
            lbl.setStyleSheet(f"color: {T.TEXT_SECONDARY};")
        for edit in (self.input_email, self.input_name,
                     self.input_password, self.input_confirm):
            edit.apply_theme()

        self.chk_remember.setStyleSheet(f"""
            QCheckBox {{ color: {T.TEXT_SECONDARY}; spacing: 6px; }}
            QCheckBox::indicator {{
                width: 16px; height: 16px;
                border: 1px solid {T.BORDER_STRONG};
                border-radius: 4px;
                background: {T.INPUT_BG};
            }}
            QCheckBox::indicator:hover {{ border-color: {T.ACCENT}; }}
            QCheckBox::indicator:checked {{
                background: {T.ACCENT};
                border-color: {T.ACCENT};
            }}
        """)
        self.lbl_forgot.setText(
            f'<a href="#" style="color:{T.TEXT_SECONDARY};text-decoration:none;">'
            f'Forgot password?</a>')

        self.btn_primary.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {QColor(T.ACCENT).lighter(112).name()}, stop:1 {T.ACCENT});
                border: 1px solid {QColor(T.ACCENT).darker(112).name()};
                border-radius: 8px;
                color: {T.ACCENT_TEXT};
                font-size: 13px;
                font-weight: 600;
            }}
            QPushButton:hover    {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {QColor(T.ACCENT_HOVER).lighter(112).name()}, stop:1 {T.ACCENT_HOVER});
            }}
            QPushButton:pressed  {{ background: {T.ACCENT_PRESSED}; }}
            QPushButton:disabled {{ background: {T.DISABLED_BG}; color: {T.TEXT_HINT}; }}
        """)

        self.btn_google.apply_theme()

        self.btn_guest.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: 1px solid {T.INPUT_BORDER};
                border-radius: 8px;
                color: {T.TEXT_SECONDARY};
                font-size: 13px;
            }}
            QPushButton:hover   {{
                background: {T.HOVER_TINT};
                border-color: {T.BORDER_STRONG};
                color: {T.TEXT_PRIMARY};
            }}
            QPushButton:pressed {{ background: {T.PRESS_TINT}; }}
        """)

        self.lbl_toggle_hint.setStyleSheet(f"color: {T.TEXT_SECONDARY};")
        self.btn_toggle.setStyleSheet(f"""
            QPushButton {{
                color: {T.ACCENT}; border: none; background: transparent; padding: 0;
            }}
            QPushButton:hover {{ color: {T.ACCENT_HOVER}; }}
        """)

        self._style_status(getattr(self, "_status_error", False))
        self.findChild(DividerLabel).update()
        self._noise = _make_noise_pixmap(self.WIDTH, 1100)
        self.update()

    def _toggle_theme(self):
        T.set(LIGHT if T.is_dark else DARK)
        _save_theme(T.name)
        self._apply_theme()

    def _toggle_mode(self):
        if self._account_thread or (self._auth_thread and self._auth_thread.isRunning()):
            return
        if self._mode == "login":
            self._mode = "register"
            self.lbl_heading.setText("Create account.")
            self.tagline.setText("Join Open//Structures today")
            self.btn_primary.setText("Create Account")
            self.lbl_toggle_hint.setText("Already have an account?")
            self.btn_toggle.setText("Sign in")
            self.lbl_forgot.setVisible(False)
            self.name_field.setVisible(True)
            self.confirm_field.setVisible(True)
        else:
            self._mode = "login"
            self.lbl_heading.setText("Welcome back.")
            self.tagline.setText("Sign in to your account")
            self.btn_primary.setText("Sign In")
            self.lbl_toggle_hint.setText("Don't have an account?")
            self.btn_toggle.setText("Create one")
            self.lbl_forgot.setVisible(True)
            self.name_field.setVisible(False)
            self.confirm_field.setVisible(False)
        self._set_status("")
        self._fit_later()

    def _on_primary(self):
        """Start an account request without blocking offline guest access."""
        if self._account_thread:
            return
        email = self.input_email.text().strip()
        password = self.input_password.text()
        if not email or not password:
            self._set_status("Please fill in all fields.", error=True)
            return
        if self._mode == "register":
            name = self.input_name.text().strip()
            if not name:
                self._set_status("Please enter your full name.", error=True)
                return
            if password != self.input_confirm.text():
                self._set_status("Passwords do not match.", error=True)
                return
            self._set_status("Creating your account…")
            self._run_account_request(lambda: email_auth.register(name, email, password),
                                      self._on_register_result)
        else:
            self._set_status("Signing in…")
            self._run_account_request(lambda: email_auth.login(email, password),
                                      self._on_login_result)

    def _run_account_request(self, operation, callback):
        if self._account_thread:
            return
        self.btn_primary.setEnabled(False)
        self.btn_google.setEnabled(False)
        self.btn_toggle.setEnabled(False)
        self.lbl_forgot.setEnabled(False)
                                                                                     
        self.btn_guest.setEnabled(True)
        thread = AuthOperationThread(operation)
        self._account_thread = thread
        thread.result.connect(lambda result: self._account_result(thread, result, callback))
        thread.failed.connect(lambda message: self._account_failed(thread, message))
        thread.start()

    def _account_result(self, thread, result, callback):
        if self._closing or self._account_thread is not thread:
            return
        self._account_thread = None
        self._reset_buttons()
        callback(result)

    def _account_failed(self, thread, message):
        if self._closing or self._account_thread is not thread:
            return
        self._account_thread = None
        self._reset_buttons()
        self._set_status(message, error=True)

    def _on_register_result(self, result):
        ok, error, info = result
        if info and info.get("pending_verification"):
            self._show_verify_dialog(info, error if not ok else "")
        else:
            self._set_status(error or "Account could not be created.", error=True)

    def _on_login_result(self, result):
        ok, error, info = result
        if ok:
            self._finish_login(info)
        elif info and info.get("pending_verification"):
            self._show_verify_dialog(info)
        else:
            self._set_status(error, error=True)

    def _finish_login(self, info):
        if self._closing:
            return
        self.user_info = info
        self.remember_me = self.chk_remember.isChecked()
        name = info.get("name") or "User"
        self._set_status(f"Welcome, {name.split()[0]}!")
        QTimer.singleShot(350, self.accept)

    def _reset_buttons(self):
        self.btn_primary.setEnabled(True)
        self.btn_google.setEnabled(True)
        self.btn_toggle.setEnabled(True)
        self.lbl_forgot.setEnabled(True)
        self.btn_guest.setEnabled(True)

    def _on_forgot_password(self):
        if self._account_thread:
            return
        email = self.input_email.text().strip()
        if not email:
            self._set_status("Enter your email address first.", error=True)
            return
        self._set_status("Sending a password reset link…")
        self._run_account_request(lambda: email_auth.send_forgot_password(email),
                                  lambda result: self._on_reset_result(email, result))

    def _on_reset_result(self, email, result):
        ok, error, _ = result
        if not ok:
            self._set_status(error, error=True)
            return
        self._set_status("Check your inbox for a password reset link.")
        EmailNoticeDialog(email, parent=self).exec()

    def _show_verify_dialog(self, pending, message=""):
        dialog = EmailVerificationDialog(pending, message=message, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._finish_login(dialog.user_info)
        else:
            self._set_status("Open your verification email, then sign in when ready.")

    def _cancel_work(self):
        if self._account_thread:
            self._account_thread.cancel()
            self._account_thread = None
        if self._auth_thread and self._auth_thread.isRunning():
            self._auth_thread.cancel()

    def _on_guest_login(self):
        """Skip account services and continue locally, even without internet."""
        self._cancel_work()
        self._closing = True
        self.user_info = {"name": "Guest", "email": "", "picture": "", "provider": "guest"}
        self.remember_me = True
        self._set_status("Continuing as guest…")
        QTimer.singleShot(150, self.accept)

    def _on_google_login(self):
        """Start the Google OAuth flow in a background thread."""
        if self._account_thread or self._closing:
            return
        if self._auth_thread and self._auth_thread.isRunning():
            self._cancel_google_auth()
            return

        self.btn_google.set_waiting(True)
        self.btn_google.setEnabled(True)
        self.btn_primary.setEnabled(False)
        self.btn_guest.setEnabled(True)
        self.btn_toggle.setEnabled(False)
        self.lbl_forgot.setEnabled(False)
        self._set_status("Opening browser — please sign in…", error=False)

        thread = GoogleAuthThread()
        self._auth_thread = thread
        thread.auth_progress.connect(lambda msg: self._google_progress(thread, msg))
        thread.auth_complete.connect(lambda info: self._google_complete(thread, info))
        thread.auth_failed.connect(lambda message: self._google_failed(thread, message))
        thread.start()

    def _google_current(self, thread):
        return (not self._closing and self._auth_thread is thread
                and not thread._cancelled.is_set() and not self._account_thread)

    def _google_progress(self, thread, message):
        if self._google_current(thread):
            self._set_status(message)

    def _google_complete(self, thread, info):
        if self._google_current(thread):
            self._on_auth_complete(info)

    def _google_failed(self, thread, message):
        if self._google_current(thread):
            self._on_auth_failed(message)

    def _cancel_google_auth(self):
        """Signal the auth thread to stop, and reset the UI."""
        if self._auth_thread:
            self._auth_thread.cancel()
        self._reset_google_ui()

    def _reset_google_ui(self):
        self.btn_google.set_waiting(False)
        self.btn_google.setEnabled(True)
        self.btn_primary.setEnabled(True)
        self.btn_guest.setEnabled(True)
        self.btn_toggle.setEnabled(True)
        self.lbl_forgot.setEnabled(True)
        self._set_status("", error=False)

    def _on_auth_complete(self, user_info: dict):
        if self._closing or (self._auth_thread and self._auth_thread._cancelled.is_set()):
            return
        self._reset_google_ui()
        self.user_info = user_info
        self.remember_me = self.chk_remember.isChecked()
        self._set_status(f"Welcome, {user_info.get('name', 'User')}!", error=False)
        QTimer.singleShot(600, self.accept)

    def _on_auth_failed(self, message: str):
        if self._closing:
            return
        self._reset_google_ui()
        if message == _CANCELLED:
            return
        self._set_status(message, error=True)

    def _style_status(self, error: bool):
        color = T.ERROR if error else T.TEXT_SECONDARY
        self.lbl_status.setStyleSheet(f"color: {color}; font-size: 11px;")

    def _set_status(self, text: str, error: bool = False):
        self._status_error = error
        self._style_status(error)
        self.lbl_status.setText(text)
        visible = bool(text)
        if self.lbl_status.isVisible() != visible:
            self.lbl_status.setVisible(visible)
        self._fit_later()

    def reject(self):
        """Cancel account operations while allowing bounded requests to finish safely."""
        self._closing = True
        self._cancel_work()
        super().reject()

    def closeEvent(self, event):
        self._closing = True
        self._cancel_work()
        super().closeEvent(event)

    @staticmethod
    def _find_asset_static(filename: str):
        base = os.path.dirname(os.path.abspath(__file__))
        candidates = [
            os.path.join(base, "..", "graphic", filename),
            os.path.join(base, "..", "..", "graphic", filename),
            os.path.join(base, "..", filename),
            os.path.join(base, filename),
            os.path.join(os.getcwd(), filename),
        ]
        for path in candidates:
            if os.path.exists(path):
                return os.path.abspath(path)
        return None

    def _find_asset(self, filename: str):
        return self._find_asset_static(filename)

class EmailNoticeDialog(QDialog):
    """Firebase's reset email is completed in the browser."""
    def __init__(self, email, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Check your email")
        self.setMinimumWidth(380)
        self.setStyleSheet(_dialog_qss())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 22)
        layout.setSpacing(14)
        heading = QLabel("Reset your password")
        heading.setFont(QFont("Segoe UI Semibold", 14))
        layout.addWidget(heading)
        message = QLabel(f"If an account exists for {email}, a reset link has been sent.\n\n"
                         "Open the link to choose a new password, then return here to sign in.")
        message.setTextFormat(Qt.TextFormat.PlainText)
        message.setWordWrap(True)
        layout.addWidget(message)
        button = QPushButton("Back to sign in")
        button.setObjectName("primary")
        button.setMinimumHeight(38)
        button.clicked.connect(self.accept)
        layout.addWidget(button)

class EmailVerificationDialog(QDialog):
    """Verify an email link with Firebase before accepting an account session."""
    def __init__(self, pending, message="", parent=None):
        super().__init__(parent)
        self._session = dict(pending["session"])
        self._worker = None
        self._closing = False
        self.user_info = None
        self.setWindowTitle("Verify your email")
        self.setMinimumWidth(400)
        self.setStyleSheet(_dialog_qss())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 22)
        layout.setSpacing(12)
        heading = QLabel("Check your inbox")
        heading.setFont(QFont("Segoe UI Semibold", 14))
        layout.addWidget(heading)
        text = QLabel(f"Open the verification link sent to {pending.get('email', '')},\n"
                      "then come back and choose “I've verified my email”.")
        text.setTextFormat(Qt.TextFormat.PlainText)
        text.setWordWrap(True)
        layout.addWidget(text)
        self.status = QLabel(message or "Need another link? Choose Resend below.")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        self.status.setStyleSheet(f"color: {T.TEXT_SECONDARY};")
        layout.addWidget(self.status)
        self.check_button = QPushButton("I've verified my email")
        self.check_button.setObjectName("primary")
        self.check_button.setMinimumHeight(38)
        self.check_button.clicked.connect(self._check)
        layout.addWidget(self.check_button)
        self.resend_button = QPushButton("Resend verification link")
        self.resend_button.setMinimumHeight(34)
        self.resend_button.clicked.connect(self._resend)
        layout.addWidget(self.resend_button)
        back = QPushButton("Back")
        back.clicked.connect(self.reject)
        layout.addWidget(back)

    def _run(self, operation, callback):
        if self._worker:
            return
        self.check_button.setEnabled(False)
        self.resend_button.setEnabled(False)
        worker = AuthOperationThread(operation)
        self._worker = worker
        worker.result.connect(lambda result: self._result(worker, result, callback))
        worker.failed.connect(lambda message: self._result(worker, (False, message, None), callback))
        worker.start()

    def _result(self, worker, result, callback):
        if self._closing or self._worker is not worker:
            return
        self._worker = None
        self.check_button.setEnabled(True)
        self.resend_button.setEnabled(True)
        callback(result)

    def _check(self):
        access = self._session["access_token"]
        refresh = self._session["refresh_token"]
        self.status.setText("Checking your verification…")
        self._run(lambda: email_auth.check_verification(access, refresh), self._checked)

    def _checked(self, result):
        ok, error, info = result
        if not ok:
            self.status.setText(error)
            return
        self.user_info = info
        self._closing = True
        self.accept()

    def _resend(self):
        access = self._session["access_token"]
        self.status.setText("Sending a new verification link…")
        self._run(lambda: email_auth.resend_verification(access), self._resent)

    def _resent(self, result):
        ok, error, _ = result
        self.status.setText("A new verification link has been sent. Check your inbox." if ok else error)

    def reject(self):
        self._closing = True
        if self._worker:
            self._worker.cancel()
        super().reject()

    def closeEvent(self, event):
        self._closing = True
        if self._worker:
            self._worker.cancel()
        super().closeEvent(event)
