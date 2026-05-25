"""
auth/user_widget.py
-------------------
Floating top-right user profile widget for OpenCivil's MainWindow.
"""

import os
import urllib.request
import tempfile

from PyQt6.QtCore import (
    Qt, QTimer, QPoint, QRect,
    pyqtSignal, QThread, pyqtSignal as Signal,
    QPropertyAnimation, QEasingCurve, QParallelAnimationGroup
)
from PyQt6.QtGui import (
    QFont, QColor, QPainter, QPainterPath,
    QPixmap, QPen, QLinearGradient
)
from PyQt6.QtWidgets import (
    QWidget, QLabel, QPushButton,
    QVBoxLayout, QHBoxLayout,
    QGraphicsDropShadowEffect, QSizePolicy
)

TEXT_PRIMARY   = "#0F1C2E"
TEXT_SECONDARY = "#64748B"
TEXT_HINT      = "#94A3B8"
ACCENT         = "#0F62FE"
DANGER         = "#DC2626"
DANGER_HOVER   = "rgba(220,38,38,8)"
HOVER_ITEM     = "rgba(15,28,46,6)"
AVATAR_SIZE    = 36
DROPDOWN_W     = 300

class AvatarFetcher(QThread):
    done = Signal(str)

    def __init__(self, url: str):
        super().__init__()
        self._url = url

    def run(self):
        try:
            url = self._url
            if "googleusercontent.com" in url and "=s" not in url:
                url += "=s96-c"
            tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
            urllib.request.urlretrieve(url, tmp.name)
            self.done.emit(tmp.name)
        except Exception:
            self.done.emit("")

class AvatarLabel(QLabel):
    def __init__(self, size=AVATAR_SIZE, parent=None):
        super().__init__(parent)
        self._size     = size
        self._pixmap   = None
        self._initials = "?"
        self.setFixedSize(size, size)

    def set_pixmap(self, pixmap: QPixmap):
        self._pixmap = pixmap.scaled(
            self._size, self._size,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation
        )
        self.update()

    def set_initials(self, name: str):
        parts = name.strip().split()
        self._initials = "".join(p[0].upper() for p in parts[:2]) if parts else "?"
        self._pixmap   = None
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        s = self._size

        clip = QPainterPath()
        clip.addEllipse(0, 0, s, s)
        p.setClipPath(clip)

        if self._pixmap:
            pw, ph = self._pixmap.width(), self._pixmap.height()
            ox = (pw - s) // 2
            oy = (ph - s) // 2
            p.drawPixmap(0, 0, self._pixmap, ox, oy, s, s)
        else:
            grad = QLinearGradient(0, 0, s, s)
            grad.setColorAt(0, QColor("#1D4ED8"))
            grad.setColorAt(1, QColor("#0F62FE"))
            p.fillRect(0, 0, s, s, grad)
            p.setPen(QColor("#FFFFFF"))
            p.setFont(QFont("Segoe UI Semibold", max(7, s // 3)))
            p.drawText(QRect(0, 0, s, s), Qt.AlignmentFlag.AlignCenter, self._initials)

        p.setClipping(False)
        pen = QPen(QColor(0, 0, 0, 18))
        pen.setWidth(1)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(0, 0, s - 1, s - 1)
        p.end()

class UserDropdown(QWidget):
    logout_requested = pyqtSignal()

    def __init__(self, user_info: dict, parent=None):
        super().__init__(
            parent,
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.NoDropShadowWindowHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._user_info = user_info
        self._build_ui()
        self._apply_shadow()

    def _build_ui(self):
                                                                                     
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 24, 24, 24) 
        main_layout.setSpacing(0)

        self.container = QWidget()
        self.container.setFixedWidth(DROPDOWN_W)
        self.container.setStyleSheet("""
            QWidget {
                background-color: white;
                border-radius: 12px;
            }
        """)

        root = QVBoxLayout(self.container)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QWidget()
        header.setStyleSheet("background: transparent;")
        h = QHBoxLayout(header)
        h.setContentsMargins(18, 18, 18, 16)
        h.setSpacing(14)

        self.avatar_big = AvatarLabel(size=46)
        name = self._user_info.get('name', '')
        self.avatar_big.set_initials(name)
        h.addWidget(self.avatar_big, 0, Qt.AlignmentFlag.AlignVCenter)

        col = QVBoxLayout()
        col.setSpacing(3)
        col.setContentsMargins(0, 0, 0, 0)

        lbl_name = QLabel(name)
        lbl_name.setFont(QFont("Segoe UI Semibold", 10))
        lbl_name.setStyleSheet(f"color: {TEXT_PRIMARY}; background: transparent;")
        col.addWidget(lbl_name)

        is_guest = self._user_info.get('provider') == 'guest'
        email_text = "Browsing as guest" if is_guest else self._user_info.get('email', '')
        lbl_email = QLabel(email_text)
        lbl_email.setFont(QFont("Segoe UI", 8))
        lbl_email.setStyleSheet(f"color: {TEXT_HINT}; background: transparent;")
        lbl_email.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        col.addWidget(lbl_email)

        h.addLayout(col, 1)
        root.addWidget(header)

        root.addWidget(self._divider())

        menu = QWidget()
        menu.setStyleSheet("background: transparent;")
        m = QVBoxLayout(menu)
        m.setContentsMargins(10, 8, 10, 10)
        m.setSpacing(2)

        if not is_guest:
            btn_account = self._menu_btn("Manage Account", danger=False)
            btn_account.clicked.connect(lambda: None)
            m.addWidget(btn_account)

        signout_label = "Exit Guest Session" if is_guest else "Sign Out"
        btn_signout = self._menu_btn(signout_label, danger=True)
        btn_signout.clicked.connect(self.logout_requested)
        m.addWidget(btn_signout)

        root.addWidget(menu)
        
        main_layout.addWidget(self.container)
        self.adjustSize()

    def _divider(self):
        d = QWidget()
        d.setFixedHeight(1)
        d.setStyleSheet("background: rgba(0,0,0,10); margin: 0 0;")
        return d

    def _menu_btn(self, text: str, danger: bool = False) -> QPushButton:
        btn = QPushButton(text)
        btn.setFixedHeight(40)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFont(QFont("Segoe UI", 10))
        color    = DANGER      if danger else TEXT_PRIMARY
        hover_bg = DANGER_HOVER if danger else HOVER_ITEM
        btn.setStyleSheet(f"""
            QPushButton {{
                color: {color};
                background: transparent;
                border: none;
                border-radius: 8px;
                text-align: left;
                padding-left: 14px;
                font-size: 13px;
            }}
            QPushButton:hover {{
                background: {hover_bg};
            }}
        """)
        return btn

    def _apply_shadow(self):
        s = QGraphicsDropShadowEffect(self)
        s.setBlurRadius(24)
        s.setOffset(0, 6)
        s.setColor(QColor(0, 0, 0, 55))
                                                                          
        self.container.setGraphicsEffect(s)

    def set_avatar_pixmap(self, pixmap: QPixmap):
        self.avatar_big.set_pixmap(pixmap)

class UserProfileWidget(QWidget):
    logout_requested = pyqtSignal()

    def __init__(self, auth_manager, parent: QWidget = None):
        super().__init__(parent)
        self._auth          = auth_manager
        self._info          = auth_manager.user_info or {}
        self._dropdown      = None
        self._avatar_pixmap = None
        self._fetcher       = None

        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(42)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._build_ui()
        self._apply_shadow()
        self._start_avatar_fetch()

        from PyQt6.QtWidgets import QApplication
        QApplication.instance().installEventFilter(self)

    def _build_ui(self):
        self.setStyleSheet("""
            UserProfileWidget {
                background: white;
                border: 1px solid rgba(0,0,0,14);
                border-radius: 21px;
            }
            UserProfileWidget:hover {
                background: #F8FAFC;
                border-color: rgba(0,0,0,22);
            }
        """)

        layout = QHBoxLayout(self)
                                                                                   
        layout.setContentsMargins(4, 3, 14, 3)
        layout.setSpacing(9)

        self.avatar = AvatarLabel(size=AVATAR_SIZE, parent=self)
        name = self._info.get('name', '')
        self.avatar.set_initials(name)
        layout.addWidget(self.avatar)

        first_name = name.split()[0] if name else "User"
        if len(first_name) > 10:
            first_name = first_name[:9] + "…"

        self.lbl_name = QLabel(first_name)
        self.lbl_name = QLabel(first_name)
        self.lbl_name.setFont(QFont("Segoe UI Semibold",11))
        self.lbl_name.setStyleSheet(f"color: {TEXT_PRIMARY}; background: transparent;")
        layout.addWidget(self.lbl_name)

        self.lbl_chevron = QLabel("▾")
        self.lbl_chevron.setFont(QFont("Segoe UI", 7))
        self.lbl_chevron.setStyleSheet(f"color: {TEXT_HINT}; background: transparent;")
        layout.addWidget(self.lbl_chevron)

        self.adjustSize()

    def _apply_shadow(self):
        s = QGraphicsDropShadowEffect(self)
        s.setBlurRadius(16)
        s.setOffset(0, 3)
        s.setColor(QColor(0, 0, 0, 35))
        self.setGraphicsEffect(s)

    def _start_avatar_fetch(self):
        url = self._info.get('picture', '')
        if not url:
            return
        self._fetcher = AvatarFetcher(url)
        self._fetcher.done.connect(self._on_avatar_fetched)
        self._fetcher.start()

    def _on_avatar_fetched(self, path: str):
        if not path:
            return
        px = QPixmap(path)
        if px.isNull():
            return
        self._avatar_pixmap = px
        self.avatar.set_pixmap(px)
        if self._dropdown:
            self._dropdown.set_avatar_pixmap(px)
        try:
            os.unlink(path)
        except OSError:
            pass

    def reposition(self):
        if not self.parent():
            return
        self.adjustSize()
        p = self.parent()
        x = p.width() - self.width() - 16

        win = self.window()
        if hasattr(win, 'toolbar'):
            tb = win.toolbar
            tb_pos = tb.mapTo(p, QPoint(0, 0))
            y = tb_pos.y() + (tb.height() - self.height()) // 2 - 5

            min_x = tb.sizeHint().width() + 8 
        else:
            y = 7
            min_x = 200  

        if x < min_x:
            self.hide()
            return

        self.show()
        self.move(x, y)
        self.raise_()

    def mousePressEvent(self, _event):
        self._toggle_dropdown()

    def _toggle_dropdown(self):
        if self._dropdown and self._dropdown.isVisible():
            self._dropdown.hide()
            self.lbl_chevron.setText("▾")
            return

        if not self._dropdown:
            self._dropdown = UserDropdown(self._info, parent=self.window())
            self._dropdown.logout_requested.connect(self._on_logout)
            if self._avatar_pixmap:
                self._dropdown.set_avatar_pixmap(self._avatar_pixmap)

        pos  = self.mapTo(self.window(), QPoint(0, self.height() + 8))
        dx   = pos.x() + self.width() - DROPDOWN_W - 24
        
        start_y = pos.y() - 15                         
        end_y = pos.y()                                  

        self._dropdown.move(dx, start_y)
        self._dropdown.setWindowOpacity(0.0)                          
        self._dropdown.show()
        self._dropdown.raise_()

        self.anim_group = QParallelAnimationGroup(self)

        fade_anim = QPropertyAnimation(self._dropdown, b"windowOpacity")
        fade_anim.setDuration(250)              
        fade_anim.setStartValue(0.0)
        fade_anim.setEndValue(1.0)
        fade_anim.setEasingCurve(QEasingCurve.Type.InOutQuad)

        move_anim = QPropertyAnimation(self._dropdown, b"pos")
        move_anim.setDuration(250)
        move_anim.setStartValue(QPoint(dx, start_y))
        move_anim.setEndValue(QPoint(dx, end_y))
        move_anim.setEasingCurve(QEasingCurve.Type.OutBack)                      

        self.anim_group.addAnimation(fade_anim)
        self.anim_group.addAnimation(move_anim)
        self.anim_group.start()

        self.lbl_chevron.setText("▴")

    def _on_logout(self):
        if self._dropdown:
            self._dropdown.hide()
        self._auth.logout()
        self.logout_requested.emit()

    def eventFilter(self, obj, event):
        from PyQt6.QtCore import QEvent, QRect, QPoint

        if obj is self.parent() and event.type() in (
            QEvent.Type.Resize, QEvent.Type.Show
        ):
            self.reposition()

        if self._dropdown and self._dropdown.isVisible():
            if event.type() == QEvent.Type.MouseButtonPress:
                gpos = event.globalPosition().toPoint()
                dd_rect = QRect(self._dropdown.mapToGlobal(QPoint(0, 0)), self._dropdown.size())
                my_rect = QRect(self.mapToGlobal(QPoint(0, 0)), self.size())
                if not dd_rect.contains(gpos) and not my_rect.contains(gpos):
                    self._dropdown.hide()
                    self.lbl_chevron.setText("▾")

        return False
    
    def closeEvent(self, event):
        from PyQt6.QtWidgets import QApplication
        QApplication.instance().removeEventFilter(self)
        super().closeEvent(event)
