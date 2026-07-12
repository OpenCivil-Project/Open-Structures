from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QComboBox, 
                             QFormLayout, QPushButton, QGroupBox, QHBoxLayout)
from PyQt6.QtCore import Qt, pyqtSignal

class DrawLink2JDialog(QDialog):
    signal_dialog_closed = pyqtSignal()

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model
        self.setWindowTitle("Draw 2-Joint Link")
        
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint) 
        self.setMinimumWidth(280)
        
        main_layout = QVBoxLayout(self)
        
        prop_group = QGroupBox("Link Parameters")
        form_layout = QFormLayout()
        
        self.prop_combo = QComboBox()
        self.refresh_properties()
        form_layout.addRow("Link Property:", self.prop_combo)
        
        prop_group.setLayout(form_layout)
        main_layout.addWidget(prop_group)
        
        inst_group = QGroupBox("Drawing Controls")
        inst_layout = QVBoxLayout()
        
        lbl = QLabel("• <b>Left Click:</b> Draw link segment<br>"
                     "• <b>Right Click:</b> Stop chain<br>"
                     "• <b>Esc:</b> Exit draw mode")
        lbl.setStyleSheet("color: #555; font-size: 12px;")
        inst_layout.addWidget(lbl)
        inst_group.setLayout(inst_layout)
        main_layout.addWidget(inst_group)
        
        btn_layout = QHBoxLayout()
        btn_layout.addStretch() 
        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.close)
        btn_layout.addWidget(self.close_btn)
        
        main_layout.addLayout(btn_layout)

    def refresh_properties(self):
        current = self.prop_combo.currentText()
        self.prop_combo.clear()
        
        if not hasattr(self.model, 'link_properties') or not self.model.link_properties:
            self.prop_combo.addItem("DefaultLink")
        else:
            self.prop_combo.addItems(list(self.model.link_properties.keys()))
            
        idx = self.prop_combo.findText(current)
        if idx >= 0: self.prop_combo.setCurrentIndex(idx)

    def get_selected_property(self):
        return self.prop_combo.currentText()

    def closeEvent(self, event):
        self.signal_dialog_closed.emit()
        super().closeEvent(event)

class DrawLink1JDialog(QDialog):
    signal_dialog_closed = pyqtSignal()

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model
        self.setWindowTitle("Draw 1-Joint Link (Grounded)")
        
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint) 
        self.setMinimumWidth(280)
        
        main_layout = QVBoxLayout(self)
        
        prop_group = QGroupBox("Link Parameters")
        form_layout = QFormLayout()
        
        self.prop_combo = QComboBox()
        self.refresh_properties()
        form_layout.addRow("Link Property:", self.prop_combo)
        
        prop_group.setLayout(form_layout)
        main_layout.addWidget(prop_group)
        
        inst_group = QGroupBox("Assignment Controls")
        inst_layout = QVBoxLayout()
        
        lbl = QLabel("• <b>Left Click:</b> Assign link to joint<br>"
                     "• <b>Esc:</b> Exit assignment mode")
        lbl.setStyleSheet("color: #555; font-size: 12px;")
        inst_layout.addWidget(lbl)
        inst_group.setLayout(inst_layout)
        main_layout.addWidget(inst_group)
        
        btn_layout = QHBoxLayout()
        btn_layout.addStretch() 
        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.close)
        btn_layout.addWidget(self.close_btn)
        
        main_layout.addLayout(btn_layout)

    def refresh_properties(self):
        current = self.prop_combo.currentText()
        self.prop_combo.clear()
        if not hasattr(self.model, 'link_properties') or not self.model.link_properties:
            self.prop_combo.addItem("DefaultLink")
        else:
            self.prop_combo.addItems(list(self.model.link_properties.keys()))
        idx = self.prop_combo.findText(current)
        if idx >= 0: self.prop_combo.setCurrentIndex(idx)

    def get_selected_property(self):
        return self.prop_combo.currentText()

    def closeEvent(self, event):
        self.signal_dialog_closed.emit()
        super().closeEvent(event)
