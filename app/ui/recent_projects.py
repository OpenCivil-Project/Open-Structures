"""Compact, keyboard-accessible recent-project cards for the File menu."""

import os
from datetime import datetime

from PyQt6.QtCore import Qt, QRectF, QSize, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import (
    QAbstractButton, QComboBox, QFrame, QHBoxLayout, QLabel, QMenu,
    QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from app.ui.theme import COLORS

def activity_label(project):
    """Read current ISO timestamps and the previous registry's date format."""
    value = project.get("last_saved") or project.get("last_opened")
    verb = "Saved" if project.get("last_saved") else "Opened"
    if not value:
        return "Preview available" if project.get("thumbnail") else "Ready to open"
    try:
        stamp = datetime.fromisoformat(value)
    except ValueError:
        try:
            stamp = datetime.strptime(value, "%d/%m/%Y %H:%M:%S")
        except ValueError:
            return verb + " " + value
    if stamp.tzinfo is not None:
        stamp = stamp.astimezone()
    age = (datetime.now().date() - stamp.date()).days
    day = "today" if age == 0 else "yesterday" if age == 1 else stamp.strftime("%d %b %Y")
    return f"{verb} {day}, {stamp:%H:%M}"

class RecentProjectCard(QAbstractButton):
    openRequested = pyqtSignal(str)
    removeRequested = pyqtSignal(str)
    focusMoved = pyqtSignal(int)
    focused = pyqtSignal(object)

    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.project = project
        self.project_path = project["path"]
        self.available = os.path.isfile(self.project_path)
        self.setText(project["name"])
        self.setToolTip(self.project_path + "\n" + activity_label(project))
        self.setAccessibleName(project["name"] + ", " + os.path.basename(self.project_path))
        self.setAccessibleDescription("Open project. Right-click to remove from recent history.")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(88)
        self._hover = False
                                                                                      
        self.preview = QPixmap.fromImage(QImage(project.get("thumbnail", "")))
        self.clicked.connect(lambda: self.openRequested.emit(self.project_path))

    def sizeHint(self):
        return QSize(430, 88)

    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.focused.emit(self)
        self.update()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.update()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Menu or (
            event.key() == Qt.Key.Key_F10 and event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        ):
            self._show_context_menu(self.mapToGlobal(self.rect().center()))
            event.accept()
        elif event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            self.focusMoved.emit(-1 if event.key() == Qt.Key.Key_Up else 1)
            event.accept()
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.click()
            event.accept()
        else:
            super().keyPressEvent(event)

    def contextMenuEvent(self, event):
        self._show_context_menu(event.globalPos())

    def _show_context_menu(self, global_position):
        menu = QMenu(self)
        open_action = menu.addAction("Open project")
        open_action.setEnabled(self.available)
        remove_action = menu.addAction("Remove from recent projects")
        selected = menu.exec(global_position)
        if selected is open_action:
            self.openRequested.emit(self.project_path)
        elif selected is remove_action:
            self.removeRequested.emit(self.project_path)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        active = self._hover or self.hasFocus() or self.isDown()
        area = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        painter.setPen(QPen(QColor(COLORS["accent"] if self.hasFocus() else COLORS["border_light"]), 1))
        painter.setBrush(QColor(COLORS["selection_bg"] if active else COLORS["bg_panel"]))
        painter.drawRoundedRect(area, 6, 6)

        thumb = QRectF(12, 12, 104, 64)
        clip = QPainterPath()
        clip.addRoundedRect(thumb, 4, 4)
        painter.save()
        painter.setClipPath(clip)
        painter.fillRect(thumb, QColor(COLORS["bg_table_header"]))
        if not self.preview.isNull():
            scaled = self.preview.scaled(104, 64, Qt.AspectRatioMode.KeepAspectRatio,
                                         Qt.TransformationMode.SmoothTransformation)
            painter.drawPixmap(int(thumb.x() + (104 - scaled.width()) / 2),
                               int(thumb.y() + (64 - scaled.height()) / 2), scaled)
        else:
            painter.setPen(QPen(QColor(COLORS["text_disabled"]), 1.5))
            for x in (42, 64, 86):
                painter.drawLine(x, 29, x, 61)
            painter.drawLine(42, 29, 86, 29)
            painter.drawLine(42, 45, 86, 45)
            painter.drawLine(38, 62, 90, 62)
        painter.restore()

        x, width = 130, max(1, self.width() - 146)
        font = QFont(self.font())
        font.setPointSizeF(10)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(COLORS["text_primary"]))
        title = painter.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideRight, width)
        painter.drawText(x, 31, title)
        font.setPointSizeF(9)
        font.setBold(False)
        painter.setFont(font)
        painter.setPen(QColor(COLORS["text_secondary"]))
        filename = painter.fontMetrics().elidedText(os.path.basename(self.project_path),
                                                   Qt.TextElideMode.ElideMiddle, width)
        painter.drawText(x, 51, filename)
        font.setPointSizeF(8)
        painter.setFont(font)
        painter.setPen(QColor(COLORS["text_secondary"] if self.available else COLORS["text_disabled"]))
        detail = activity_label(self.project) if self.available else "File unavailable · right-click to remove"
        painter.drawText(x, 70, painter.fontMetrics().elidedText(detail, Qt.TextElideMode.ElideRight, width))

class RecentProjectsPanel(QWidget):
    openRequested = pyqtSignal(str)
    removeRequested = pyqtSignal(str)
    limitRequested = pyqtSignal(int)
    clearRequested = pyqtSignal()

    def __init__(self, projects, limit, limits, parent=None):
        super().__init__(parent)
        screen = self.screen().availableGeometry()
        self.setFixedWidth(min(460, max(280, screen.width() - 40)))
        self.setAutoFillBackground(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 10)
        layout.setSpacing(8)
        title = QLabel("Recent projects")
        font = QFont(title.font())
        font.setPointSizeF(11)
        font.setBold(True)
        title.setFont(font)
        layout.addWidget(title)
        layout.addWidget(QLabel(f"Most recently used first · {len(projects)} of {limit}"))

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(6)
        self.cards = []
        for project in projects:
            card = RecentProjectCard(project, content)
            card.openRequested.connect(self.openRequested)
            card.removeRequested.connect(self.removeRequested)
            card.focusMoved.connect(self._move_focus)
            card.focused.connect(lambda widget: self.scroll.ensureWidgetVisible(widget, 0, 8))
            content_layout.addWidget(card)
            self.cards.append(card)
        if not projects:
            empty = QLabel("No recent projects yet.\nOpen or save a model to see it here.")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setWordWrap(True)
            content_layout.addWidget(empty)
        content_layout.addStretch()
        self.scroll.setWidget(content)
        row_height = len(projects) * 94 - 6 if projects else 120
        self.scroll.setFixedHeight(min(max(120, row_height), max(120, min(430, screen.height() - 220))))
        layout.addWidget(self.scroll)

        footer = QHBoxLayout()
        label = QLabel("&Keep:")
        self.limit_combo = QComboBox()
        for value in limits:
            self.limit_combo.addItem(f"{value} projects", value)
        self.limit_combo.setCurrentIndex(self.limit_combo.findData(limit))
        self.limit_combo.setAccessibleName("Recent project limit")
        label.setBuddy(self.limit_combo)
        self.limit_combo.activated.connect(lambda _: self.limitRequested.emit(self.limit_combo.currentData()))
        footer.addWidget(label)
        footer.addWidget(self.limit_combo)
        footer.addStretch()
        clear = QPushButton("Clear history")
        clear.setObjectName("secondary")
        clear.setToolTip("Remove recent entries; project files are kept.")
        clear.setEnabled(bool(projects))
        clear.clicked.connect(self.clearRequested)
        footer.addWidget(clear)
        layout.addLayout(footer)

    def _move_focus(self, offset):
        current = next((index for index, card in enumerate(self.cards) if card.hasFocus()), 0)
        if self.cards:
            self.cards[(current + offset) % len(self.cards)].setFocus()

    def showEvent(self, event):
        super().showEvent(event)
        if self.cards:
            self.cards[0].setFocus(Qt.FocusReason.PopupFocusReason)
