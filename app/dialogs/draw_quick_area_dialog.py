from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QPushButton, QVBoxLayout,
)

from app.ui.theme import apply_dialog_style, COLORS, SIZES

class DrawQuickAreaDialog(QDialog):
    """Area-section selector for drawing a shell in one grid-cell click."""

    signal_dialog_closed = pyqtSignal()

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model
        apply_dialog_style(self)
        self.setWindowTitle("Quick Area Draw")
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.setMinimumWidth(280)

        layout = QVBoxLayout(self)
        self._banner_style = (
            f"color: {COLORS['text_secondary']}; border: 1px solid {COLORS['border']};"
            f"border-radius: {SIZES['border_radius']}px; padding: 5px; "
            f"font-size: {SIZES['font_size_small']}pt; background: transparent;"
        )
        self.plane_banner = QLabel()
        self.plane_banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.plane_banner.setWordWrap(True)
        self.plane_banner.setStyleSheet(self._banner_style)
        layout.addWidget(self.plane_banner)

        self.prop_group = QGroupBox("Area Parameters")
        form = QFormLayout(self.prop_group)
        self.section_combo = QComboBox()
        self.refresh_sections()
        form.addRow("Section Property:", self.section_combo)
        layout.addWidget(self.prop_group)

        controls = QGroupBox("Drawing Controls")
        controls_layout = QVBoxLayout(controls)
        instructions = QLabel(
            "• Select an <b>XY / XZ / YZ</b> plane and grid layer<br>"
            "• <b>Hover</b> over a grid cell to preview<br>"
            "• <b>Left Click:</b> Fill the highlighted cell with a shell<br>"
            "• <b>Esc:</b> Exit draw mode"
        )
        instructions.setWordWrap(True)
        instructions.setStyleSheet(
            f"color: {COLORS['text_secondary']}; "
            f"font-size: {SIZES['font_size_small']}pt;"
        )
        controls_layout.addWidget(instructions)
        layout.addWidget(controls)

        buttons = QHBoxLayout()
        buttons.addStretch()
        self.close_btn = QPushButton("Close")
        self.close_btn.setObjectName("secondary")
        self.close_btn.clicked.connect(self.close)
        buttons.addWidget(self.close_btn)
        layout.addLayout(buttons)
        self.update_plane_status(None)

    def refresh_sections(self):
        selected_name = self.section_combo.currentText()
        self.section_combo.clear()
        self.section_combo.addItems(list(self.model.area_sections))
        index = self.section_combo.findText(selected_name)
        if index >= 0:
            self.section_combo.setCurrentIndex(index)

    def get_selected_section(self):
        return self.model.area_sections.get(self.section_combo.currentText())

    def update_plane_status(self, plane_info):
        if plane_info is None:
            self.plane_banner.setText("⚠  No plane active — enable XY / XZ / YZ")
            self.prop_group.setEnabled(False)
            return
        axis = plane_info['axis'].upper()
        plane_name = {'X': 'YZ', 'Y': 'XZ', 'Z': 'XY'}[axis]
        self.plane_banner.setText(
            f"Plane: {plane_name}  @  {axis} = {plane_info['value']:.2f} m"
        )
        self.prop_group.setEnabled(True)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            event.accept()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        self.signal_dialog_closed.emit()
        super().closeEvent(event)
