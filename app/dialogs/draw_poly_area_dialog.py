from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox
from PyQt6.QtCore import Qt

try:
    from app.ui.theme import apply_dialog_style
except ImportError:
    def apply_dialog_style(d): pass

class DrawPolyAreaDialog(QDialog):
    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model
        self.setWindowTitle("Draw Poly Area")
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        self.setMinimumWidth(250)
        apply_dialog_style(self)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        
        row = QHBoxLayout()
        row.addWidget(QLabel("Section:"))
        self.cbo_section = QComboBox()
        row.addWidget(self.cbo_section)
        layout.addLayout(row)
        
        lbl_status = QLabel("Click joints to draw area.\nRight-Click or press Enter to finish.")
        lbl_status.setStyleSheet("color: #666; font-style: italic; margin-top: 10px;")
        layout.addWidget(lbl_status)

    def refresh_sections(self):
        self.cbo_section.clear()
        for name in self.model.area_sections:
            self.cbo_section.addItem(name)

    def get_selected_section(self):
        name = self.cbo_section.currentText()
        return self.model.area_sections.get(name)

    def closeEvent(self, event):
                                                                                   
        if hasattr(self.parent(), 'on_draw_poly_area_finished'):
            self.parent().on_draw_poly_area_finished()
        super().closeEvent(event)
