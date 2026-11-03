from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QComboBox,
                             QFormLayout, QPushButton, QGroupBox, QHBoxLayout, QFrame)
from PyQt6.QtCore import Qt, pyqtSignal

from app.ui.theme import apply_dialog_style, COLORS, SIZES

class DrawCrossBraceDialog(QDialog):

    signal_dialog_closed = pyqtSignal()

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model
        apply_dialog_style(self)

        self.setWindowTitle("Quick Cross Brace")

        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.setMinimumWidth(280)

        main_layout = QVBoxLayout(self)

        self._banner_style = (
            f"color: {COLORS['text_secondary']}; border: 1px solid {COLORS['border']};"
            f"border-radius: {SIZES['border_radius']}px; padding: 5px; font-size: {SIZES['font_size_small']}pt;"
        )

        self.plane_banner = QLabel("⚠  No plane active — enable XY / XZ / YZ")
        self.plane_banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.plane_banner.setWordWrap(True)
        self.plane_banner.setStyleSheet(self._banner_style)
        main_layout.addWidget(self.plane_banner)

        self.prop_group = QGroupBox("Brace Parameters")
        form_layout = QFormLayout()

        self.section_combo = QComboBox()
        self.refresh_sections()
        form_layout.addRow("Section Property:", self.section_combo)

        self.brace_type_combo = QComboBox()
        self.brace_type_combo.addItems(["X Brace", "Diagonal ↗", "Diagonal ↖"])
        form_layout.addRow("Brace Type:", self.brace_type_combo)

        self.release_combo = QComboBox()
        self.release_combo.addItems(["Pinned-Pinned", "Continuous"])
        form_layout.addRow("End Releases:", self.release_combo)

        self.prop_group.setLayout(form_layout)
        main_layout.addWidget(self.prop_group)

        inst_group = QGroupBox("Drawing Controls")
        inst_layout = QVBoxLayout()

        lbl = QLabel("• <b>Hover</b> over a grid cell to preview<br>"
                     "• <b>Left Click:</b> Place brace in highlighted cell<br>"
                     "• <b>Esc:</b> Exit draw mode")
        lbl.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: {SIZES['font_size_small']}pt;")
        inst_layout.addWidget(lbl)
        inst_group.setLayout(inst_layout)
        main_layout.addWidget(inst_group)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.close_btn = QPushButton("Close")
        self.close_btn.setObjectName("secondary")
        self.close_btn.clicked.connect(self.close)
        btn_layout.addWidget(self.close_btn)
        main_layout.addLayout(btn_layout)

        self.prop_group.setEnabled(False)

    def update_plane_status(self, plane_info):
        if plane_info is None:
            self.plane_banner.setText("⚠  No plane active — enable XY / XZ / YZ")
            self.prop_group.setEnabled(False)
        else:
            axis = plane_info['axis'].upper()
            val  = plane_info['value']
            plane_name = {'X': 'YZ', 'Y': 'XZ', 'Z': 'XY'}[axis]
            self.plane_banner.setText(f"Plane: {plane_name}  @  {axis} = {val:.2f} m")
            self.prop_group.setEnabled(True)

        self.plane_banner.setStyleSheet(self._banner_style + "background: transparent;")

    def refresh_sections(self):
        current = self.section_combo.currentText()
        self.section_combo.clear()
        if not self.model.sections:
            self.section_combo.addItem("Default")
        else:
            self.section_combo.addItems(list(self.model.sections.keys()))
        idx = self.section_combo.findText(current)
        if idx >= 0:
            self.section_combo.setCurrentIndex(idx)

    def get_selected_section(self):
        name = self.section_combo.currentText()
        if name in self.model.sections:
            return self.model.sections[name]
        return None

    def get_brace_type(self):
        t = self.brace_type_combo.currentText()
        if t == "X Brace":    return "x"
        if t == "Diagonal ↗": return "diag_a"
        return "diag_b"

    def get_release_arrays(self):
        if self.release_combo.currentText() == "Pinned-Pinned":
            rel_i = [False, False, False, False, True, True]
            rel_j = [False, False, False, False, True, True]
        else:
            rel_i = [False, False, False, False, False, False]
            rel_j = [False, False, False, False, False, False]
        return rel_i, rel_j

    def closeEvent(self, event):
        self.signal_dialog_closed.emit()
        super().closeEvent(event)
