from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, 
                             QCheckBox, QPushButton, QGroupBox)
from PyQt6.QtCore import Qt

from PyQt6.QtWidgets import QFrame
from PyQt6.QtCore import Qt, QRect, QPoint
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QFont, QPolygon

class AnalysisCard(QFrame):
    """
    Clickable card that draws analysis option diagrams via QPainter.
    types: "space", "plane", "grid"
    """
    MEMBER_COLOR  = QColor("#000000")
    SELECT_COLOR  = QColor("#1976D2")
    BG_NORMAL     = QColor("#F5F5F5")
    BG_HOVER      = QColor("#E3F2FD")
    BG_SELECTED   = QColor("#BBDEFB")

    def __init__(self, card_type: str, label: str, parent=None):
        super().__init__(parent)
        self.card_type = card_type
        self.label = label
        self.selected = False
        self._hovered = False

        self.setFixedSize(100, 125)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_selected(self, val: bool):
        self.selected = val
        self.update()

    def enterEvent(self, e):
        self._hovered = True
        self.update()

    def leaveEvent(self, e):
        self._hovered = False
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.parent().parent()._card_clicked(self.card_type)              

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()

        if self.selected:
            bg, border, bw = self.BG_SELECTED, self.SELECT_COLOR, 2
        elif self._hovered:
            bg, border, bw = self.BG_HOVER, QColor("#90CAF9"), 1
        else:
            bg, border, bw = self.BG_NORMAL, QColor("#CCCCCC"), 1

        p.setBrush(QBrush(bg))
        p.setPen(QPen(border, bw))
        p.drawRoundedRect(2, 2, w - 4, h - 4, 6, 6)

        p.setPen(QPen(self.MEMBER_COLOR, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        
        if self.card_type == "space":
            self._draw_space(p)
        elif self.card_type == "plane":
            self._draw_plane(p)
        elif self.card_type == "grid":
            self._draw_grid(p)

        lbl_y = 80
        p.setPen(QPen(self.SELECT_COLOR if self.selected else QColor("#333333")))
        font = QFont()
        font.setBold(self.selected)
        font.setPointSize(8)
        p.setFont(font)
        p.drawText(QRect(0, lbl_y, w, h - lbl_y - 2),
                   Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                   self.label)
        p.end()

    def _draw_support(self, p, x, y):
        """Helper to draw a tiny pin support triangle."""
        p.setBrush(Qt.BrushStyle.NoBrush)
        tri = QPolygon([QPoint(x, y), QPoint(x - 4, y + 6), QPoint(x + 4, y + 6)])
        p.drawPolygon(tri)

    def _draw_plane(self, p):
                         
        x1, x2, x3 = 25, 50, 75
        y_top, y_mid, y_bot = 25, 45, 65
        
        p.drawLine(x1, y_top, x1, y_bot)
        p.drawLine(x2, y_top, x2, y_bot)
        p.drawLine(x3, y_top, x3, y_bot)
               
        p.drawLine(x1, y_top, x3, y_top)
        p.drawLine(x1, y_mid, x3, y_mid)
                  
        for x in (x1, x2, x3): self._draw_support(p, x, y_bot)

    def _draw_grid(self, p):
                                     
        x_lines = [25, 40, 55, 70]
        y_lines = [25, 40, 55, 70]
        
        for x in x_lines:
            p.drawLine(x, y_lines[0], x, y_lines[-1])
        for y in y_lines:
            p.drawLine(x_lines[0], y, x_lines[-1], y)

    def _draw_space(self, p):
                            
        dx, dy = 12, -10                   
        x1, x2 = 30, 60
        y_top, y_bot = 35, 65

        p.drawLine(x1+dx, y_top+dy, x1+dx, y_bot+dy)
        p.drawLine(x2+dx, y_top+dy, x2+dx, y_bot+dy)
        p.drawLine(x1+dx, y_top+dy, x2+dx, y_top+dy)
        
        p.drawLine(x1, y_top, x1+dx, y_top+dy)
        p.drawLine(x2, y_top, x2+dx, y_top+dy)
        p.drawLine(x1, y_bot, x1+dx, y_bot+dy)
        p.drawLine(x2, y_bot, x2+dx, y_bot+dy)

        p.drawLine(x1, y_top, x1, y_bot)
        p.drawLine(x2, y_top, x2, y_bot)
        p.drawLine(x1, y_top, x2, y_top)

        self._draw_support(p, x1, y_bot)
        self._draw_support(p, x2, y_bot)
        self._draw_support(p, x1+dx, y_bot+dy)
        self._draw_support(p, x2+dx, y_bot+dy)

class AnalysisOptionsDialog(QDialog):
    def __init__(self, main_window):
        super().__init__(main_window)
        self.main_window = main_window
        self.setWindowTitle("Analysis Options")
        self.setFixedSize(420, 310)
        self.setModal(True)

        root = QVBoxLayout(self)
        root.setSpacing(15)
        root.setContentsMargins(15, 15, 15, 15)

        dof_group = QGroupBox("Available Global DOFs")
        dof_layout = QHBoxLayout(dof_group)
        
        self.cb_ux = QCheckBox("UX")
        self.cb_uy = QCheckBox("UY")
        self.cb_uz = QCheckBox("UZ")
        self.cb_rx = QCheckBox("RX")
        self.cb_ry = QCheckBox("RY")
        self.cb_rz = QCheckBox("RZ")

        for cb in (self.cb_ux, self.cb_uy, self.cb_uz, self.cb_rx, self.cb_ry, self.cb_rz):
            dof_layout.addWidget(cb)
            
        root.addWidget(dof_group)

        fast_group = QGroupBox("Fast DOFs")
        fast_layout = QHBoxLayout(fast_group)
        fast_layout.setSpacing(10)

        self._cards = {}
        for key, lbl in [("space", "Space Frame\n(3D)"), 
                         ("plane", "Plane Frame\n(XZ Plane)"),
                         ("grid", "Plane Grid\n(XY Plane)")]:
            card = AnalysisCard(key, lbl, parent=fast_group)
            self._cards[key] = card
            fast_layout.addWidget(card)

        root.addWidget(fast_group)

        action_layout = QHBoxLayout()
        action_layout.addStretch()

        self.btn_ok = QPushButton("OK")
        self.btn_ok.setFixedWidth(100)
        self.btn_ok.clicked.connect(self.apply_changes)

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setFixedWidth(100)
        self.btn_cancel.clicked.connect(self.reject)

        action_layout.addWidget(self.btn_ok)
        action_layout.addWidget(self.btn_cancel)
        
        root.addLayout(action_layout)
        
        self._load_current_state()

    def _set_space_frame(self):
        """3D Structure: All DOFs active"""
        self.cb_ux.setChecked(True); self.cb_uy.setChecked(True); self.cb_uz.setChecked(True)
        self.cb_rx.setChecked(True); self.cb_ry.setChecked(True); self.cb_rz.setChecked(True)

    def _set_plane_frame(self):
        """2D Vertical Frame (XZ): UX, UZ, RY active"""
        self.cb_ux.setChecked(True);  self.cb_uy.setChecked(False); self.cb_uz.setChecked(True)
        self.cb_rx.setChecked(False); self.cb_ry.setChecked(True);  self.cb_rz.setChecked(False)

    def _set_plane_grid(self):
        """2D Horizontal Grid (XY): UZ, RX, RY active (Gravity bending out-of-plane)"""
        self.cb_ux.setChecked(False); self.cb_uy.setChecked(False); self.cb_uz.setChecked(True)
        self.cb_rx.setChecked(True);  self.cb_ry.setChecked(True);  self.cb_rz.setChecked(False)

    def _load_current_state(self):
        if hasattr(self.main_window.model, 'active_dofs'):
            dofs = self.main_window.model.active_dofs
            self.cb_ux.setChecked(dofs[0])
            self.cb_uy.setChecked(dofs[1])
            self.cb_uz.setChecked(dofs[2])
            self.cb_rx.setChecked(dofs[3])
            self.cb_ry.setChecked(dofs[4])
            self.cb_rz.setChecked(dofs[5])

    def apply_changes(self):
        active_dofs = [
            self.cb_ux.isChecked(), self.cb_uy.isChecked(), self.cb_uz.isChecked(),
            self.cb_rx.isChecked(), self.cb_ry.isChecked(), self.cb_rz.isChecked()
        ]
        
        self.main_window.model.active_dofs = active_dofs
        self.main_window.status.showMessage("Analysis Options Updated.")
        self.accept()

    def _card_clicked(self, card_type: str):
                                                  
        for key, card in self._cards.items():
            card.set_selected(key == card_type)
            
        if card_type == "space": self._set_space_frame()
        elif card_type == "plane": self._set_plane_frame()
        elif card_type == "grid": self._set_plane_grid()
