"""
auth/dialog.py
--------------
Redesigned login dialog for OpenCivil.
Quiet-confidence aesthetic: off-white textured surface, zero gradients,
IBM blue (#0F62FE) as the single accent. All backend logic preserved.
"""

import os
import random
from PyQt6.QtCore import (
    Qt, QTimer, QPropertyAnimation, QEasingCurve,
    QPoint, pyqtProperty, QRect
)
from PyQt6.QtGui import (
    QFont, QColor, QPainter, QPainterPath, QLinearGradient,
    QBrush, QPen, QPixmap, QIcon, QFontDatabase
)
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QCheckBox, QFrame,
    QGraphicsDropShadowEffect, QWidget, QSizePolicy,
    QApplication, QSpacerItem
)

from .thread import GoogleAuthThread
from . import email_auth

BG            = "#F5F4F0"                            
SURFACE       = "#FFFFFF"
BORDER        = "#E4E3DE"
BORDER_STRONG = "#C9C7C0"
TEXT_PRIMARY  = "#111110"
TEXT_SECONDARY= "#6B6A65"
TEXT_HINT     = "#A8A7A2"
ACCENT        = "#0F62FE"                                   
ACCENT_HOVER  = "#0043CE"
ACCENT_PRESSED= "#002D9C"
ACCENT_TEXT   = "#FFFFFF"
INPUT_BG      = "#FAFAF8"
INPUT_BORDER  = "#DEDCD7"
INPUT_FOCUS   = "#0F62FE"
DIVIDER       = "#E4E3DE"
ERROR_COLOR   = "#DC2626"
SUCCESS_COLOR = "#16A34A"
GOOGLE_BG     = "#FFFFFF"
GOOGLE_BORDER = "#DDDBD6"
GOOGLE_HOVER  = "#F0EFEb"

def _make_noise_pixmap(width: int, height: int, density: float = 0.04) -> QPixmap:
    """Return a subtle grain overlay pixmap — drawn once, reused on repaint."""
    rng = random.Random(0xC17117)                                        
    pm = QPixmap(width, height)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    total = int(width * height * density)
    for _ in range(total):
        x = rng.randint(0, width - 1)
        y = rng.randint(0, height - 1)
        alpha = rng.randint(4, 14)
        p.setPen(QColor(30, 28, 20, alpha))
        p.drawPoint(x, y)
    p.end()
    return pm

class StyledInput(QLineEdit):
    def __init__(self, placeholder="", password=False, parent=None):
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        if password:
            self.setEchoMode(QLineEdit.EchoMode.Password)
        self.setFixedHeight(42)
        self.setFont(QFont("Segoe UI", 10))
        self._apply_style(focused=False)

    def _apply_style(self, focused: bool):
        border = INPUT_FOCUS if focused else INPUT_BORDER
        bw = "1.5px" if focused else "1px"
        self.setStyleSheet(f"""
            QLineEdit {{
                background: {INPUT_BG};
                border: {bw} solid {border};
                border-radius: 6px;
                padding: 0 12px;
                color: {TEXT_PRIMARY};
                font-size: 13px;
                selection-background-color: {ACCENT};
            }}
            QLineEdit::placeholder {{
                color: {TEXT_HINT};
            }}
        """)

    def focusInEvent(self, e):
        self._apply_style(True)
        super().focusInEvent(e)

    def focusOutEvent(self, e):
        self._apply_style(False)
        super().focusOutEvent(e)

def _paint_google_g(painter: QPainter, cx: int, cy: int, r: int = 10):
    """
    Paint a proper four-colour Google G centred at (cx, cy).

    Strategy:
      1. Draw four coloured pie slices (the ring)
      2. Punch a white inner circle
      3. Draw the blue horizontal bar on the right
      4. Mask the top-right gap that makes the G open
    Qt angles: 0 = 3 o'clock, positive = counter-clockwise, units = 1/16 degree.
    """
    painter.setPen(Qt.PenStyle.NoPen)
    rect = (cx - r, cy - r, r * 2, r * 2)

    painter.setBrush(QColor("#4285F4"))
    painter.drawPie(*rect, -35 * 16, 125 * 16)

    painter.setBrush(QColor("#EA4335"))
    painter.drawPie(*rect,  90 * 16, 120 * 16)

    painter.setBrush(QColor("#FBBC05"))
    painter.drawPie(*rect, 210 * 16,  60 * 16)

    painter.setBrush(QColor("#34A853"))
    painter.drawPie(*rect, 270 * 16,  55 * 16)

    inner = int(r * 0.54)
    painter.setBrush(QColor("#FFFFFF"))
    painter.drawEllipse(cx - inner, cy - inner, inner * 2, inner * 2)

    bar_h = int(r * 0.38)
    bar_w = r - inner + 2
    painter.setBrush(QColor("#4285F4"))
    painter.drawRect(cx, cy - bar_h // 2, bar_w, bar_h)

    painter.setBrush(QColor("#FFFFFF"))
    painter.drawRect(cx - 1, cy - r - 1, r + 2, int(r * 0.48))

class GoogleButton(QPushButton):
    """
    Full-width Google sign-in button.
    Loads Glogo.png for the icon; falls back to a painted G if not found.
    """

    def __init__(self, logo_path: str = None, parent=None):
        super().__init__("Continue with Google", parent)
        self.setFixedHeight(42)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFont(QFont("Segoe UI Semibold", 10))
        self._logo_path  = logo_path
        self._use_pixmap = False

        if logo_path and os.path.exists(logo_path):
            icon = QIcon(logo_path)
            self.setIcon(icon)
            self.setIconSize(__import__('PyQt6.QtCore', fromlist=['QSize']).QSize(20, 20))
            self._use_pixmap = True

        self.setStyleSheet(f"""
            QPushButton {{
                background: {GOOGLE_BG};
                border: 1px solid {GOOGLE_BORDER};
                border-radius: 6px;
                color: {TEXT_PRIMARY};
                font-size: 13px;
                font-weight: 600;
                padding-left: 8px;
                text-align: center;
            }}
            QPushButton:hover   {{ background: {GOOGLE_HOVER}; border-color: {BORDER_STRONG}; }}
            QPushButton:pressed {{ background: #E8E7E3; }}
            QPushButton:disabled {{ color: {TEXT_HINT}; }}
        """)

    def paintEvent(self, event):
        super().paintEvent(event)
                                                                
        if not self._use_pixmap:
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            icon_cx = 28
            _paint_google_g(p, icon_cx, self.height() // 2, r=9)
            p.end()

class DividerLabel(QWidget):
    def __init__(self, text="or", parent=None):
        super().__init__(parent)
        self._text = text
        self.setFixedHeight(18)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        mid = h // 2

        f = QFont("Segoe UI", 8)
        p.setFont(f)
        fm = p.fontMetrics()
        tw = fm.horizontalAdvance(f"  {self._text}  ")
        lx = (w - tw) // 2

        pen = QPen(QColor(DIVIDER))
        pen.setWidth(1)
        p.setPen(pen)
        p.drawLine(0, mid, lx, mid)
        p.drawLine(lx + tw, mid, w, mid)

        p.setPen(QColor(TEXT_HINT))
        p.drawText(QRect(lx, 0, tw, h), Qt.AlignmentFlag.AlignCenter, self._text)
        p.end()

def _field_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setFont(QFont("Segoe UI Semibold", 8))
    lbl.setStyleSheet(f"color: {TEXT_SECONDARY};")
    return lbl

class LoginDialog(QDialog):
    """
    Redesigned OpenCivil login dialog.
    Quiet-confidence aesthetic — all auth logic preserved.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.user_info    = None
        self.remember_me  = False
        self._auth_thread = None
        self._mode        = "login"

        self.setWindowTitle("OpenCivil")
        self.setFixedSize(420, 624)

        icon_path = self._find_asset_static("logo.png") or self._find_asset_static("logo.ico")
        if icon_path:
            self.setWindowIcon(QIcon(icon_path))

        self.setWindowFlags(
            Qt.WindowType.Dialog |
            Qt.WindowType.WindowCloseButtonHint |
            Qt.WindowType.MSWindowsFixedSizeDialogHint
        )
        self.setModal(True)

        self._noise = _make_noise_pixmap(420, 700)
        self._build_ui()

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(BG))
        p.drawPixmap(0, 0, self._noise)
        p.end()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(40, 36, 40, 36)
        root.setSpacing(0)

        logo_row = QHBoxLayout()
        logo_row.setSpacing(8)
        logo_row.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        logo_lbl = QLabel()
        logo_path = self._find_asset("logo.png") or self._find_asset("logo.ico")
        if logo_path:
            px = QPixmap(logo_path).scaled(
                22, 22,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            logo_lbl.setPixmap(px)
        else:
            logo_lbl.setText("◈")
            logo_lbl.setStyleSheet(f"color: {ACCENT}; font-size: 18px;")

        app_name = QLabel("OpenCivil")
        app_name.setFont(QFont("Segoe UI Semibold", 12))
        app_name.setStyleSheet(f"color: {TEXT_PRIMARY};")

        logo_row.addWidget(logo_lbl)
        logo_row.addWidget(app_name)
        root.addLayout(logo_row)
        root.addSpacing(40)

        self.lbl_heading = QLabel("Welcome back.")
        self.lbl_heading.setFont(QFont("Segoe UI Semibold", 22))
        self.lbl_heading.setStyleSheet(f"color: {TEXT_PRIMARY};")
        root.addWidget(self.lbl_heading)
        root.addSpacing(4)

        self.tagline = QLabel("Sign in to your account")
        self.tagline.setFont(QFont("Segoe UI", 11))
        self.tagline.setStyleSheet(f"color: {TEXT_SECONDARY};")
        root.addWidget(self.tagline)
        root.addSpacing(30)

        root.addWidget(_field_label("Email"))
        root.addSpacing(5)
        self.input_email = StyledInput("you@example.com")
        root.addWidget(self.input_email)
        root.addSpacing(14)

        self.name_lbl = _field_label("Full Name")
        self.name_lbl.setVisible(False)
        root.addWidget(self.name_lbl)
        root.addSpacing(5)
        self.input_name = StyledInput("Your full name")
        self.input_name.setVisible(False)
        root.addWidget(self.input_name)
        root.addSpacing(14)

        root.addWidget(_field_label("Password"))
        root.addSpacing(5)
        self.input_password = StyledInput("••••••••", password=True)
        root.addWidget(self.input_password)
        root.addSpacing(14)

        self.confirm_lbl = _field_label("Confirm Password")
        self.confirm_lbl.setVisible(False)
        root.addWidget(self.confirm_lbl)
        root.addSpacing(5)
        self.input_confirm = StyledInput("••••••••", password=True)
        self.input_confirm.setVisible(False)
        root.addWidget(self.input_confirm)
        root.addSpacing(14)

        row_rf = QHBoxLayout()
        self.chk_remember = QCheckBox("Remember me")
        self.chk_remember.setFont(QFont("Segoe UI", 9))
        self.chk_remember.setStyleSheet(f"""
            QCheckBox {{
                color: {TEXT_SECONDARY};
                spacing: 6px;
            }}
            QCheckBox::indicator {{
                width: 14px; height: 14px;
                border: 1px solid {INPUT_BORDER};
                border-radius: 3px;
                background: {INPUT_BG};
            }}
            QCheckBox::indicator:checked {{
                background: {ACCENT};
                border-color: {ACCENT};
            }}
        """)
        row_rf.addWidget(self.chk_remember)
        row_rf.addStretch()

        self.lbl_forgot = QLabel(
            f'<a href="#" style="color:{TEXT_SECONDARY};text-decoration:none;">'
            f'Forgot password?</a>'
        )
        self.lbl_forgot.setFont(QFont("Segoe UI", 9))
        self.lbl_forgot.setOpenExternalLinks(False)
        self.lbl_forgot.linkActivated.connect(lambda _: self._on_forgot_password())
        row_rf.addWidget(self.lbl_forgot)
        root.addLayout(row_rf)
        root.addSpacing(20)

        self.btn_primary = QPushButton("Sign In")
        self.btn_primary.setFixedHeight(42)
        self.btn_primary.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_primary.setFont(QFont("Segoe UI Semibold", 10))
        self.btn_primary.setStyleSheet(f"""
            QPushButton {{
                background: {ACCENT};
                border: none;
                border-radius: 6px;
                color: {ACCENT_TEXT};
                font-size: 13px;
                font-weight: 600;
            }}
            QPushButton:hover   {{ background: {ACCENT_HOVER}; }}
            QPushButton:pressed {{ background: {ACCENT_PRESSED}; }}
            QPushButton:disabled {{
                background: {INPUT_BORDER};
                color: {TEXT_HINT};
            }}
        """)
        self.btn_primary.clicked.connect(self._on_primary)
        root.addWidget(self.btn_primary)
        root.addSpacing(20)

        self.lbl_status = QLabel("")
        self.lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_status.setFont(QFont("Segoe UI", 8))
        self.lbl_status.setStyleSheet(f"color: {TEXT_HINT};")
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setFixedHeight(16)
        root.addWidget(self.lbl_status)
        root.addSpacing(18)

        root.addWidget(DividerLabel("or"))
        root.addSpacing(14)

        glogo_path = self._find_asset("Glogo.png")
        self.btn_google = GoogleButton(logo_path=glogo_path)
        self.btn_google.clicked.connect(self._on_google_login)
        root.addWidget(self.btn_google)

        root.addSpacing(12)

        self.btn_guest = QPushButton("Continue as Guest")
        self.btn_guest.setFixedHeight(42)
        self.btn_guest.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_guest.setFont(QFont("Segoe UI", 10))
        self.btn_guest.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: 1px solid {INPUT_BORDER};
                border-radius: 6px;
                color: {TEXT_SECONDARY};
                font-size: 13px;
            }}
            QPushButton:hover   {{
                background: rgba(0,0,0,4);
                border-color: {BORDER_STRONG};
                color: {TEXT_PRIMARY};
            }}
            QPushButton:pressed {{ background: rgba(0,0,0,7); }}
        """)
        self.btn_guest.clicked.connect(self._on_guest_login)
        root.addWidget(self.btn_guest)

        root.addSpacing(24)
        root.addStretch()

        toggle_row = QHBoxLayout()
        toggle_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_toggle_hint = QLabel("Don't have an account?")
        self.lbl_toggle_hint.setFont(QFont("Segoe UI", 9))
        self.lbl_toggle_hint.setStyleSheet(f"color: {TEXT_SECONDARY};")
        toggle_row.addWidget(self.lbl_toggle_hint)

        self.btn_toggle = QPushButton("Create one")
        self.btn_toggle.setFlat(True)
        self.btn_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_toggle.setFont(QFont("Segoe UI Semibold", 9))
        self.btn_toggle.setStyleSheet(f"""
            QPushButton {{
                color: {ACCENT};
                border: none;
                background: transparent;
                padding: 0;
                margin-left: 4px;
            }}
            QPushButton:hover {{ color: {ACCENT_HOVER}; }}
        """)
        self.btn_toggle.clicked.connect(self._toggle_mode)
        toggle_row.addWidget(self.btn_toggle)
        root.addLayout(toggle_row)

    def _toggle_mode(self):
        if self._mode == "login":
            self._mode = "register"
            self.lbl_heading.setText("Create account.")
            self.tagline.setText("Join OpenCivil today")
            self.btn_primary.setText("Create Account")
            self.lbl_toggle_hint.setText("Already have an account?")
            self.btn_toggle.setText("Sign in")
            self.lbl_forgot.setVisible(False)
            self.name_lbl.setVisible(True)
            self.input_name.setVisible(True)
            self.confirm_lbl.setVisible(True)
            self.input_confirm.setVisible(True)
            self.setFixedHeight(724)
        else:
            self._mode = "login"
            self.lbl_heading.setText("Welcome back.")
            self.tagline.setText("Sign in to your account")
            self.btn_primary.setText("Sign In")
            self.lbl_toggle_hint.setText("Don't have an account?")
            self.btn_toggle.setText("Create one")
            self.lbl_forgot.setVisible(True)
            self.name_lbl.setVisible(False)
            self.input_name.setVisible(False)
            self.confirm_lbl.setVisible(False)
            self.input_confirm.setVisible(False)
            self.setFixedHeight(624)
        self.lbl_status.setText("")

    def _on_primary(self):
        """Email/password sign-in or register — wired to MongoDB backend."""
        email    = self.input_email.text().strip()
        password = self.input_password.text()

        if not email or not password:
            self._set_status("Please fill in all fields.", error=True)
            return

        self.btn_primary.setEnabled(False)
        self.btn_google.setEnabled(False)

        if self._mode == "register":
            name    = self.input_name.text().strip()
            confirm = self.input_confirm.text()
            if not name:
                self._set_status("Please enter your full name.", error=True)
                self._reset_buttons()
                return
            if password != confirm:
                self._set_status("Passwords do not match.", error=True)
                self._reset_buttons()
                return

            self._set_status("Creating your account…", error=False)
            QApplication.processEvents()

            ok, err, _ = email_auth.register(name, email, password)
            if not ok:
                self._set_status(err, error=True)
                self._reset_buttons()
                return

            self._set_status("", error=False)
            self._reset_buttons()
            self._show_verify_dialog(email, name)

        else:
            self._set_status("Signing in…", error=False)
            QApplication.processEvents()

            ok, err, user_info = email_auth.login(email, password)
            if not ok:
                if "verify your email" in err:
                    self._set_status("Sending new verification code...", error=False)
                    QApplication.processEvents()
                    
                    from . import email_service
                    from .db import set_verify_code
                    fresh_code = email_service.generate_code(6)
                    set_verify_code(email, fresh_code)
                    
                    email_service.send_verification_email(email, "User", fresh_code)
                    
                    self._set_status("", error=False)
                    self._reset_buttons()
                    self._show_verify_dialog(email, "User")
                    return
                self._set_status(err, error=True)
                self._reset_buttons()
                return

            self.user_info   = user_info
            self.remember_me = self.chk_remember.isChecked()
            self._set_status(f"Welcome back, {user_info['name'].split()[0]}!", error=False)
            QTimer.singleShot(600, self.accept)

    def _reset_buttons(self):
        self.btn_primary.setEnabled(True)
        self.btn_google.setEnabled(True)

    def _on_forgot_password(self):
        email = self.input_email.text().strip()
        if not email:
            self._set_status("Enter your email address first.", error=True)
            return

        self._set_status("Sending reset code…", error=False)
        QApplication.processEvents()

        ok, err, _ = email_auth.send_forgot_password(email)
        if not ok:
            self._set_status(err, error=True)
            return

        self._set_status("", error=False)
        self._show_reset_dialog(email)

    def _show_verify_dialog(self, email: str, name: str):
        dlg = CodeInputDialog(
            title     = "Verify your email",
            subtitle  = f"We sent a 6-digit code to\n{email}",
            btn_label = "Verify Account",
            parent    = self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        code = dlg.get_code()
        ok, err, _ = email_auth.confirm_verification(email, code)
        if not ok:
            self._set_status(err, error=True)
            return

        ok2, err2, user_info = email_auth.login(email, self.input_password.text())
        if ok2:
            self.user_info   = user_info
            self.remember_me = self.chk_remember.isChecked()
            self._set_status(f"Welcome, {name.split()[0]}! Account verified ✓", error=False)
            QTimer.singleShot(800, self.accept)
        else:
            self._set_status("Verified! Please sign in.", error=False)
            self._toggle_mode()

    def _show_reset_dialog(self, email: str):
        dlg = ResetPasswordDialog(email=email, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._set_status("Password reset! Please sign in.", error=False)

    def _on_guest_login(self):
        """Skip authentication and enter as a local guest."""
        self.user_info = {
            "name":     "Guest",
            "email":    "",
            "picture":  "",
            "provider": "guest",
        }
        self.remember_me = True                                      
        self._set_status("Continuing as guest…", error=False)
        QTimer.singleShot(300, self.accept)

    def _on_google_login(self):
        """Start the Google OAuth flow in a background thread."""
        self.btn_google.setEnabled(False)
        self.btn_primary.setEnabled(False)
        self._set_status("Opening browser…", error=False)

        self._auth_thread = GoogleAuthThread()
        self._auth_thread.auth_progress.connect(
            lambda msg: self._set_status(msg, error=False)
        )
        self._auth_thread.auth_complete.connect(self._on_auth_complete)
        self._auth_thread.auth_failed.connect(self._on_auth_failed)
        self._auth_thread.start()

    def _on_auth_complete(self, user_info: dict):
        self.user_info   = user_info
        self.remember_me = self.chk_remember.isChecked()
        self._set_status(f"Welcome, {user_info.get('name', 'User')}!", error=False)
        QTimer.singleShot(600, self.accept)

    def _on_auth_failed(self, message: str):
        self.btn_google.setEnabled(True)
        self.btn_primary.setEnabled(True)
        self._set_status(message, error=True)

    def _set_status(self, text: str, error: bool = False):
        color = ERROR_COLOR if error else TEXT_SECONDARY
        self.lbl_status.setStyleSheet(f"color: {color}; font-size: 11px;")
        self.lbl_status.setText(text)

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

class CodeInputDialog(QDialog):
    """Generic 6-digit code entry — matches redesigned aesthetic."""

    def __init__(self, title: str, subtitle: str,
                 btn_label: str = "Confirm", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setFixedSize(360, 260)
        self.setWindowFlags(
            Qt.WindowType.Dialog |
            Qt.WindowType.WindowCloseButtonHint
        )
        self.setModal(True)
        self._noise = _make_noise_pixmap(360, 260)
        self._build(title, subtitle, btn_label)

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(BG))
        p.drawPixmap(0, 0, self._noise)
        p.end()

    def _build(self, title, subtitle, btn_label):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 28, 32, 28)
        lay.setSpacing(0)

        lbl_title = QLabel(title)
        lbl_title.setFont(QFont("Segoe UI Semibold", 13))
        lbl_title.setStyleSheet(f"color: {TEXT_PRIMARY};")
        lay.addWidget(lbl_title)
        lay.addSpacing(6)

        lbl_sub = QLabel(subtitle)
        lbl_sub.setFont(QFont("Segoe UI", 9))
        lbl_sub.setStyleSheet(f"color: {TEXT_SECONDARY};")
        lbl_sub.setWordWrap(True)
        lay.addWidget(lbl_sub)
        lay.addSpacing(20)

        self.input_code = StyledInput("Enter 6-digit code")
        self.input_code.setMaxLength(6)
        self.input_code.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.input_code.setFont(QFont("Segoe UI Semibold", 16))
        lay.addWidget(self.input_code)
        lay.addSpacing(6)

        self.lbl_err = QLabel("")
        self.lbl_err.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_err.setFont(QFont("Segoe UI", 9))
        self.lbl_err.setStyleSheet(f"color: {ERROR_COLOR};")
        self.lbl_err.setFixedHeight(14)
        lay.addWidget(self.lbl_err)
        lay.addSpacing(16)

        btn = QPushButton(btn_label)
        btn.setFixedHeight(42)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFont(QFont("Segoe UI Semibold", 10))
        btn.setStyleSheet(f"""
            QPushButton {{
                background: {ACCENT};
                border: none; border-radius: 6px;
                color: white; font-size: 13px;
            }}
            QPushButton:hover   {{ background: {ACCENT_HOVER}; }}
            QPushButton:pressed {{ background: {ACCENT_PRESSED}; }}
        """)
        btn.clicked.connect(self._confirm)
        lay.addWidget(btn)

    def _confirm(self):
        code = self.input_code.text().strip()
        if len(code) != 6 or not code.isdigit():
            self.lbl_err.setText("Please enter the 6-digit code.")
            return
        self.accept()

    def get_code(self) -> str:
        return self.input_code.text().strip()

class ResetPasswordDialog(QDialog):
    """Two-step: enter reset code → enter new password."""

    def __init__(self, email: str, parent=None):
        super().__init__(parent)
        self._email = email
        self.setWindowTitle("Reset Password")
        self.setFixedSize(360, 340)
        self.setWindowFlags(
            Qt.WindowType.Dialog |
            Qt.WindowType.WindowCloseButtonHint
        )
        self.setModal(True)
        self._noise = _make_noise_pixmap(360, 340)
        self._build()

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(BG))
        p.drawPixmap(0, 0, self._noise)
        p.end()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 28, 32, 28)
        lay.setSpacing(0)

        lbl_title = QLabel("Reset your password")
        lbl_title.setFont(QFont("Segoe UI Semibold", 13))
        lbl_title.setStyleSheet(f"color: {TEXT_PRIMARY};")
        lay.addWidget(lbl_title)
        lay.addSpacing(6)

        lbl_sub = QLabel(f"Enter the code sent to {self._email}\nand choose a new password.")
        lbl_sub.setFont(QFont("Segoe UI", 9))
        lbl_sub.setStyleSheet(f"color: {TEXT_SECONDARY};")
        lbl_sub.setWordWrap(True)
        lay.addWidget(lbl_sub)
        lay.addSpacing(20)

        lay.addWidget(_field_label("Reset Code"))
        lay.addSpacing(5)
        self.input_code = StyledInput("6-digit code")
        self.input_code.setMaxLength(6)
        lay.addWidget(self.input_code)
        lay.addSpacing(14)

        lay.addWidget(_field_label("New Password"))
        lay.addSpacing(5)
        self.input_pass = StyledInput("Min. 8 characters", password=True)
        lay.addWidget(self.input_pass)
        lay.addSpacing(8)

        self.lbl_err = QLabel("")
        self.lbl_err.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_err.setFont(QFont("Segoe UI", 9))
        self.lbl_err.setStyleSheet(f"color: {ERROR_COLOR};")
        self.lbl_err.setFixedHeight(14)
        lay.addWidget(self.lbl_err)
        lay.addSpacing(16)

        btn = QPushButton("Reset Password")
        btn.setFixedHeight(42)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFont(QFont("Segoe UI Semibold", 10))
        btn.setStyleSheet(f"""
            QPushButton {{
                background: {ACCENT};
                border: none; border-radius: 6px;
                color: white; font-size: 13px;
            }}
            QPushButton:hover   {{ background: {ACCENT_HOVER}; }}
            QPushButton:pressed {{ background: {ACCENT_PRESSED}; }}
        """)
        btn.clicked.connect(self._confirm)
        lay.addWidget(btn)

    def _confirm(self):
        code     = self.input_code.text().strip()
        password = self.input_pass.text()

        if len(code) != 6 or not code.isdigit():
            self.lbl_err.setText("Please enter the 6-digit code.")
            return
        if len(password) < 8:
            self.lbl_err.setText("Password must be at least 8 characters.")
            return

        QApplication.processEvents()
        ok, err, _ = email_auth.confirm_reset(self._email, code, password)
        if not ok:
            self.lbl_err.setText(err)
            return
        self.accept()
