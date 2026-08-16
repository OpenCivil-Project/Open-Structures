from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QComboBox, 
                             QFormLayout, QPushButton, QGroupBox, QHBoxLayout)
from PyQt6.QtCore import Qt, pyqtSignal

class DrawFrameDialog(QDialog):
                                               
    signal_dialog_closed = pyqtSignal()

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model
        self.setWindowTitle("Draw Frame/Cable/Tendon Object")
        
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint) 
        self.setMinimumWidth(280)
        
        main_layout = QVBoxLayout(self)

        type_group = QGroupBox("Object Type")
        type_layout = QFormLayout()
        self.object_type_combo = QComboBox()
        self.object_type_combo.addItems(["Frame", "Tendon", "Cable"])              
        self.object_type_combo.currentTextChanged.connect(self._on_object_type_changed)
        type_layout.addRow("Draw:", self.object_type_combo)
        type_group.setLayout(type_layout)
        main_layout.addWidget(type_group)

        prop_group = QGroupBox("Line Object Parameters")
        form_layout = QFormLayout()
        
        self.section_combo = QComboBox()
        self.refresh_sections()
        self.section_label = QLabel("Section Property:")
        form_layout.addRow(self.section_label, self.section_combo)
        
        self.release_combo = QComboBox()
        self.release_combo.addItems(["Continuous", "Pinned"])
        self.release_label = QLabel("Moment Releases:")
        form_layout.addRow(self.release_label, self.release_combo)

        self.tendon_note = QLabel(
            "Tendon must be drawn over an existing, continuous, straight run "
            "of frame elements. Geometry (layout, local axis) is defined in "
            "the dialog that opens after the second click."
        )
        self.tendon_note.setWordWrap(True)
        self.tendon_note.setStyleSheet("color: #555; font-size: 11px;")
        self.tendon_note.setVisible(False)
        form_layout.addRow(self.tendon_note)
        
        prop_group.setLayout(form_layout)
        main_layout.addWidget(prop_group)
        
        inst_group = QGroupBox("Drawing Controls")
        inst_layout = QVBoxLayout()
        
        lbl = QLabel("• <b>Left Click:</b> Draw segment<br>"
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

    def _on_object_type_changed(self, mode):
        is_tendon = (mode == "Tendon")
        is_cable = (mode == "Cable")

        self.release_combo.setVisible(not (is_tendon or is_cable))
        self.release_label.setVisible(not (is_tendon or is_cable))
        
        self.tendon_note.setVisible(is_tendon)

        if is_tendon:
            self.section_label.setText("Tendon Section:")
            self.refresh_tendon_sections()
        elif is_cable:
            self.section_label.setText("Cable Section:")
            self.refresh_cable_sections()
        else:
            self.section_label.setText("Section Property:")
            self.refresh_sections()

    def get_draw_mode(self):
        """Returns 'Frame', 'Tendon', or 'Cable' — main.py branches its click handler on this."""
        return self.object_type_combo.currentText()

    def refresh_sections(self):
        current = self.section_combo.currentText()
        self.section_combo.clear()
        if not self.model.sections:
            self.section_combo.addItem("Default")
        else:
            self.section_combo.addItems(list(self.model.sections.keys()))
        idx = self.section_combo.findText(current)
        if idx >= 0: self.section_combo.setCurrentIndex(idx)

    def refresh_tendon_sections(self):
        current = self.section_combo.currentText()
        self.section_combo.clear()
        if not self.model.tendon_sections:
            self.section_combo.addItem("(Define a Tendon Section first)")
        else:
            self.section_combo.addItems(list(self.model.tendon_sections.keys()))
        idx = self.section_combo.findText(current)
        if idx >= 0: self.section_combo.setCurrentIndex(idx)

    def get_selected_section(self):
        name = self.section_combo.currentText()
        if name in self.model.sections:
            return self.model.sections[name]
        return None

    def get_selected_tendon_section(self):
        name = self.section_combo.currentText()
        if name in self.model.tendon_sections:
            return self.model.tendon_sections[name]
        return None

    def get_release_arrays(self):
        release_type = self.release_combo.currentText()
        if release_type == "Pinned":
                                            
            rel_i = [False, False, False, False, True, True]
            rel_j = [False, False, False, False, True, True]
        else:
                         
            rel_i = [False, False, False, False, False, False]
            rel_j = [False, False, False, False, False, False]
        return rel_i, rel_j

    def closeEvent(self, event):
        self.signal_dialog_closed.emit()
        super().closeEvent(event)

    def refresh_cable_sections(self):
        current = self.section_combo.currentText()
        self.section_combo.clear()
        if not hasattr(self.model, 'cable_sections') or not self.model.cable_sections:
            self.section_combo.addItem("(Define a Cable Section first)")
        else:
            self.section_combo.addItems(list(self.model.cable_sections.keys()))
        idx = self.section_combo.findText(current)
        if idx >= 0: self.section_combo.setCurrentIndex(idx)

    def get_selected_cable_section(self):
        name = self.section_combo.currentText()
        if hasattr(self.model, 'cable_sections') and name in self.model.cable_sections:
            return self.model.cable_sections[name]
        return None
